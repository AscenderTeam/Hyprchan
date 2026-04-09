from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from core.hyprmemory.interfaces import (
    ConsolidationJudge,
    EmbeddingProvider,
    LinkingJudge,
    LTMStore,
    SalienceJudge,
    SemanticFeelingJudge,
    STMStore,
)
from core.hyprmemory.models import (
    ConceptNode,
    ConsolidationReport,
    DreamEntry,
    Episode,
    EpisodeSummary,
    FactCandidate,
    MemoryState,
    SemanticFact,
    STMItem,
)
from core.hyprmemory.utils.id import generate_id
from core.hyprmemory.utils.math import clamp
from core.hyprmemory.utils.text import tokenize
from core.hyprmemory.utils.time import utc_now

_USER_PREF_RE = re.compile(
    r"\b(i|i\s+really)\s+(like|love|prefer)\s+(?P<pref>[^.?!]+)", re.I
)


@dataclass(slots=True)
class ConsolidationConfig:
    episode_window_seconds: int = 300
    max_gist_chars: int = 360
    max_topic_terms: int = 6
    k_sleep: float = 1.0


class SleepConsolidator:
    """Consolidate STM into episodic + semantic LTM records during sleep.

    Inspired by REMem's episodic gists + fact triples (arXiv:2503.15869) and
    MemGPT-style tiered memory consolidation (arXiv:2310.08560).
    """

    def __init__(
        self,
        *,
        stm_store: STMStore,
        ltm_store: LTMStore,
        embedder: EmbeddingProvider,
        feeling_judge: SemanticFeelingJudge,
        salience_judge: SalienceJudge,
        linking_judge: LinkingJudge,
        consolidation_judge: ConsolidationJudge | None = None,
        config: ConsolidationConfig | None = None,
    ) -> None:
        self.stm_store = stm_store
        self.ltm_store = ltm_store
        self.embedder = embedder
        self.feeling_judge = feeling_judge
        self.salience_judge = salience_judge
        self.linking_judge = linking_judge
        self.consolidation_judge = consolidation_judge
        self.config = config or ConsolidationConfig()

    async def consolidate(self, budget_f: float) -> ConsolidationReport:
        if budget_f <= 0:
            return ConsolidationReport(0, 0, 0, 0, 0, 0.0)

        max_items = int(budget_f / self.config.k_sleep)
        items = await self.stm_store.fetch_pending_items(limit=max_items)
        if not items:
            return ConsolidationReport(0, 0, 0, 0, 0, 0.0)

        sleep_state = self._average_state(items)
        episodes = await self._build_episodes(items, state=sleep_state)
        facts: list[SemanticFact] = []
        edges_written = 0
        dreams_written = 0

        for episode, chunk_items in episodes:
            episode.embedding = await self.embedder.embed(episode.gist)
            await self.ltm_store.store_episode(episode)
            for fact in await self._facts_from_items(episode, chunk_items, sleep_state):
                facts.append(fact)
                await self.ltm_store.store_fact(fact)

            concepts = await self._build_concepts(episode)
            for concept in concepts:
                await self.ltm_store.store_concept(concept)

            edges = self.linking_judge.propose_edges(episode, concepts)
            for edge in edges:
                await self.ltm_store.store_edge(edge)
            edges_written += len(edges)

        dream = await self._dream_from_episodes(
            [episode for episode, _ in episodes], sleep_state
        )
        if dream:
            await self.ltm_store.store_dream(dream)
            dreams_written = 1

        await self.stm_store.clear_pending_items()

        fatigue_spent = min(budget_f, len(items) * self.config.k_sleep)
        return ConsolidationReport(
            processed_items=len(items),
            episodes_written=len(episodes),
            facts_written=len(facts),
            edges_written=edges_written,
            dreams_written=dreams_written,
            fatigue_spent=fatigue_spent,
        )

    async def _build_episodes(
        self, items: list[STMItem], *, state: MemoryState
    ) -> list[tuple[Episode, list[STMItem]]]:
        if not items:
            return []

        sorted_items = sorted(items, key=lambda item: item.ts)
        episodes: list[list[STMItem]] = []
        current: list[STMItem] = [sorted_items[0]]
        window = timedelta(seconds=self.config.episode_window_seconds)

        for item in sorted_items[1:]:
            if item.ts - current[-1].ts <= window:
                current.append(item)
            else:
                episodes.append(current)
                current = [item]
        episodes.append(current)

        built: list[tuple[Episode, list[STMItem]]] = []
        for chunk in episodes:
            summary = await self._summary_from_items(chunk, state)
            built.append((self._episode_from_items(chunk, summary), chunk))
        return built

    def _episode_from_items(
        self, items: list[STMItem], summary: EpisodeSummary | None
    ) -> Episode:
        ts_start = items[0].ts
        ts_end = items[-1].ts
        gist = summary.gist if summary else self._gist_from_items(items)
        entities, topics = (
            (summary.entities, summary.topics)
            if summary
            else self._extract_entities_topics(items)
        )
        emotion_vec = self._average_state(items)
        semantic_feeling = self.feeling_judge.project(emotion_vec)
        salience = self._salience_from_items(items, emotion_vec)
        embedding = []
        # Embed later in async pipeline
        return Episode(
            episode_id=generate_id(),
            ts_start=ts_start,
            ts_end=ts_end,
            gist=gist,
            entities=entities,
            topics=topics,
            emotion_vec=emotion_vec,
            semantic_feeling=semantic_feeling,
            source_trace_ids=[item.item_id for item in items],
            embedding=embedding,
            salience=salience,
            version=1,
        )

    async def _summary_from_items(
        self, items: list[STMItem], state: MemoryState
    ) -> EpisodeSummary | None:
        if not self.consolidation_judge:
            return None
        return await self.consolidation_judge.summarize(items, state=state)

    async def _build_concepts(self, episode: Episode) -> list[ConceptNode]:
        concepts: list[ConceptNode] = []
        seen = set()
        for name in episode.entities + episode.topics:
            if name in seen:
                continue
            seen.add(name)
            embedding = await self.embedder.embed(name)
            concepts.append(
                ConceptNode(
                    concept_id=generate_id(),
                    kind="entity" if name in episode.entities else "topic",
                    name=name,
                    embedding=embedding,
                    prior=0.1,
                )
            )
        return concepts

    def _gist_from_items(self, items: list[STMItem]) -> str:
        parts = []
        for item in items:
            parts.append(item.content.strip())
        gist = " | ".join(part for part in parts if part)
        return gist[: self.config.max_gist_chars]

    def _extract_entities_topics(
        self, items: list[STMItem]
    ) -> tuple[list[str], list[str]]:
        entities: list[str] = []
        topics: list[str] = []
        for item in items:
            meta_entities = (
                item.meta.get("entities") if isinstance(item.meta, dict) else None
            )
            meta_topics = (
                item.meta.get("topics") if isinstance(item.meta, dict) else None
            )
            if isinstance(meta_entities, list):
                entities.extend(str(ent) for ent in meta_entities if ent)
            if isinstance(meta_topics, list):
                topics.extend(str(topic) for topic in meta_topics if topic)

        tokens = []
        for item in items:
            tokens.extend(tokenize(item.content))
        freq: dict[str, int] = {}
        for token in tokens:
            if len(token) < 4:
                continue
            freq[token] = freq.get(token, 0) + 1
        ranked = sorted(freq.items(), key=lambda pair: pair[1], reverse=True)
        top_terms = [term for term, _ in ranked[: self.config.max_topic_terms]]
        auto_topics = [term for term in top_terms if term not in topics]
        return list(dict.fromkeys(entities)), list(dict.fromkeys(topics + auto_topics))

    def _average_state(self, items: list[STMItem]) -> MemoryState:
        if not items:
            return MemoryState(f=0.0, v=0.0, e=0.0, a=0.0)
        f = sum(item.state.f for item in items) / len(items)
        v = sum(item.state.v for item in items) / len(items)
        e = sum(item.state.e for item in items) / len(items)
        a = sum(item.state.a for item in items) / len(items)
        return MemoryState(f=f, v=v, e=e, a=a)

    def _salience_from_items(self, items: list[STMItem], emotion: MemoryState) -> float:
        novelty = 0.5
        goal_rel = 0.5
        emotion_intensity = clamp(abs(emotion.v) + emotion.a, 0.0, 1.0)
        user_importance = 0.0
        for item in items:
            role = str(item.meta.get("role", ""))
            if role == "user":
                user_importance = 1.0
                break
        return self.salience_judge.score(
            novelty=novelty,
            goal_rel=goal_rel,
            emotion_intensity=emotion_intensity,
            user_importance=user_importance,
        )

    def _extract_facts(
        self, episode: Episode, items: list[STMItem]
    ) -> list[SemanticFact]:
        facts: list[SemanticFact] = []
        for item in items:
            match = _USER_PREF_RE.search(item.content)
            if not match:
                continue
            pref = match.group("pref").strip()
            facts.append(
                SemanticFact(
                    fact_id=generate_id(),
                    subject="user",
                    predicate="prefers",
                    object=pref,
                    qualifiers={"start": utc_now().isoformat(), "end": None},
                    confidence=0.6,
                    support_episode_ids=[episode.episode_id],
                    last_verified=utc_now(),
                    contradictions=[],
                )
            )
        return facts

    async def _facts_from_items(
        self, episode: Episode, items: list[STMItem], state: MemoryState
    ) -> list[SemanticFact]:
        if self.consolidation_judge:
            candidates = await self.consolidation_judge.extract_facts(
                items, state=state
            )
            if candidates:
                return [
                    self._fact_from_candidate(episode, candidate)
                    for candidate in candidates
                ]
        return self._extract_facts(episode, items)

    def _fact_from_candidate(
        self, episode: Episode, candidate: FactCandidate
    ) -> SemanticFact:
        return SemanticFact(
            fact_id=generate_id(),
            subject=candidate.subject,
            predicate=candidate.predicate,
            object=candidate.object,
            qualifiers=candidate.qualifiers,
            confidence=clamp(candidate.confidence, 0.0, 1.0),
            support_episode_ids=[episode.episode_id],
            last_verified=utc_now(),
            contradictions=[],
        )

    async def _dream_from_episodes(
        self, episodes: list[Episode], state: MemoryState
    ) -> DreamEntry | None:
        if not self.consolidation_judge:
            return None
        fragment = await self.consolidation_judge.dream_fragment(episodes, state=state)
        if not fragment:
            return None
        return DreamEntry(
            dream_id=generate_id(),
            ts=utc_now(),
            content=fragment.strip(),
            episode_ids=[episode.episode_id for episode in episodes],
            source="llm_judge",
        )
