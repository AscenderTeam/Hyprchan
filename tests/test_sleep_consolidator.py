from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.hyprmemory.consolidation.sleep_consolidator import SleepConsolidator
from core.hyprmemory.models import (
    ConceptNode,
    Episode,
    EpisodeSummary,
    FactCandidate,
    GraphEdge,
    MemoryState,
    STMItem,
    SemanticFeeling,
)


class _FakeSTMStore:
    def __init__(self, items: list[STMItem]) -> None:
        self._items = list(items)
        self.cleared = False

    async def append_trace(self, trace) -> None:  # pragma: no cover - interface only
        return None

    async def append_item(self, item) -> None:  # pragma: no cover - interface only
        return None

    async def fetch_pending_items(self, limit: int | None = None) -> list[STMItem]:
        if limit is None:
            return list(self._items)
        return list(self._items[:limit])

    async def clear_pending_items(self) -> None:
        self.cleared = True

    async def count_pending_items(self) -> int:
        return len(self._items)


class _FakeLTMStore:
    def __init__(self) -> None:
        self.episodes = []
        self.facts = []
        self.concepts = []
        self.edges = []
        self.dreams = []

    async def store_episode(self, episode: Episode) -> None:
        self.episodes.append(episode)

    async def store_fact(self, fact) -> None:
        self.facts.append(fact)

    async def store_concept(self, concept: ConceptNode) -> None:
        self.concepts.append(concept)

    async def store_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    async def recent_episodes(self, limit: int):  # pragma: no cover - interface only
        return list(self.episodes[:limit])

    async def list_concepts(self, limit: int):  # pragma: no cover - interface only
        return list(self.concepts[:limit])

    async def list_facts(self, limit: int):  # pragma: no cover - interface only
        return list(self.facts[:limit])

    async def fetch_edges(self, node_ids: list[str], limit: int):
        return [
            edge for edge in self.edges if edge.src in node_ids or edge.dst in node_ids
        ][:limit]

    async def store_dream(self, dream) -> None:
        self.dreams.append(dream)

    async def list_dreams(self, limit: int):  # pragma: no cover - interface only
        return list(self.dreams[:limit])

    async def clear_dreams(self) -> None:  # pragma: no cover - interface only
        self.dreams.clear()


class _FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text)), float(sum(1 for c in text if c.isalpha()))]


class _FakeFeelingJudge:
    def project(self, state: MemoryState) -> SemanticFeeling:
        return SemanticFeeling(
            label="steady focus",
            cognitive="balanced awareness",
            motivation="steady maintenance",
            stability=0.7,
        )


class _FakeSalienceJudge:
    def score(self, **kwargs) -> float:
        return 0.75


class _FakeLinkingJudge:
    def propose_edges(
        self, episode: Episode, concepts: list[ConceptNode]
    ) -> list[GraphEdge]:
        now = datetime.now(timezone.utc)
        return [
            GraphEdge(
                edge_id=f"edge-{idx}",
                src=episode.episode_id,
                dst=concept.concept_id,
                type="semantic_sim",
                weight=0.9,
                ts=now,
                decay_half_life_hours=24.0,
            )
            for idx, concept in enumerate(concepts)
        ]


class _FakeConsolidationJudge:
    async def summarize(self, items: list[STMItem], *, state: MemoryState):
        return EpisodeSummary(
            gist="Summarized chunk", entities=["HyprChan"], topics=["testing"]
        )

    async def extract_facts(self, items: list[STMItem], *, state: MemoryState):
        return [
            FactCandidate(
                subject="user",
                predicate="prefers",
                object="terminal workflows",
                confidence=0.88,
                qualifiers={"source": "llm"},
            )
        ]

    async def dream_fragment(self, episodes: list[Episode], *, state: MemoryState):
        return "Neon windows fold into a quiet stream of code."


def _item(*, item_id: str, ts: datetime, content: str, role: str = "user") -> STMItem:
    return STMItem(
        item_id=item_id,
        ts=ts,
        kind="chat.message",
        content=content,
        meta={"role": role, "entities": ["HyprChan"]},
        state=MemoryState(f=20.0, v=0.2, e=0.6, a=0.3),
        salience=0.5,
    )


@pytest.mark.asyncio
async def test_consolidate_splits_windows_and_extracts_preference_fact() -> None:
    base = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    items = [
        _item(item_id="1", ts=base, content="I really love spicy ramen."),
        _item(
            item_id="2", ts=base + timedelta(seconds=30), content="Switching workspace."
        ),
        _item(
            item_id="3",
            ts=base + timedelta(seconds=700),
            content="Reviewing tests again.",
        ),
    ]
    stm = _FakeSTMStore(items)
    ltm = _FakeLTMStore()

    consolidator = SleepConsolidator(
        stm_store=stm,
        ltm_store=ltm,
        embedder=_FakeEmbedder(),
        feeling_judge=_FakeFeelingJudge(),
        salience_judge=_FakeSalienceJudge(),
        linking_judge=_FakeLinkingJudge(),
    )

    report = await consolidator.consolidate(budget_f=10.0)

    assert report.processed_items == 3
    assert report.episodes_written == 2
    assert report.facts_written >= 1
    assert report.edges_written >= 1
    assert report.fatigue_spent == 3.0
    assert stm.cleared is True
    assert any(fact.object == "spicy ramen" for fact in ltm.facts)


@pytest.mark.asyncio
async def test_consolidate_uses_llm_judge_summary_facts_and_dreams() -> None:
    base = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    items = [
        _item(item_id="1", ts=base, content="Let's keep this concise."),
        _item(
            item_id="2",
            ts=base + timedelta(seconds=5),
            content="Noted and acknowledged.",
        ),
    ]
    stm = _FakeSTMStore(items)
    ltm = _FakeLTMStore()

    consolidator = SleepConsolidator(
        stm_store=stm,
        ltm_store=ltm,
        embedder=_FakeEmbedder(),
        feeling_judge=_FakeFeelingJudge(),
        salience_judge=_FakeSalienceJudge(),
        linking_judge=_FakeLinkingJudge(),
        consolidation_judge=_FakeConsolidationJudge(),
    )

    report = await consolidator.consolidate(budget_f=5.0)

    assert report.episodes_written == 1
    assert report.facts_written == 1
    assert report.dreams_written == 1
    assert ltm.episodes[0].gist == "Summarized chunk"
    assert ltm.facts[0].object == "terminal workflows"
    assert ltm.dreams[0].source == "llm_judge"
