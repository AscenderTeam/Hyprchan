from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from hyprchan.core.hyprmemory.interfaces import EmbeddingProvider, LTMStore, VectorStore
from hyprchan.core.hyprmemory.models import ConceptNode, Episode, MemoryQuery, RecallResult
from hyprchan.core.hyprmemory.utils.math import clamp, cosine_similarity, exp_decay
from hyprchan.core.hyprmemory.utils.text import lexical_similarity


@dataclass(slots=True)
class RetrieverConfig:
    tau_seconds: float = 7 * 24 * 60 * 60
    w_semantic: float = 0.45
    w_lexical: float = 0.2
    w_recency: float = 0.2
    w_salience: float = 0.15
    w_activation: float = 0.35
    w_graph_prior: float = 0.2
    w_emotion: float = 0.25
    activation_decay: float = 0.7
    edge_limit: int = 256


class HybridRetriever:
    """Hybrid retrieval pipeline with spreading activation and emotion reranking.

    Combines MemGPT-style hierarchical recall (arXiv:2310.08560), Synapse-inspired
    spreading activation over memory graphs, and Emotional RAG state-aware reranking
    (arXiv:2410.23041).
    """

    def __init__(
        self,
        *,
        ltm_store: LTMStore,
        vector_store: VectorStore,
        embedder: EmbeddingProvider,
        config: RetrieverConfig | None = None,
    ) -> None:
        self.ltm_store = ltm_store
        self.vector_store = vector_store
        self.embedder = embedder
        self.config = config or RetrieverConfig()

    async def recall(self, query: MemoryQuery) -> RecallResult:
        budget = query.budget
        query_vec = await self.embedder.embed(query.text)
        dense_episodes = await self.vector_store.search_episodes(query, budget.top_k)
        dense_concepts = await self.vector_store.search_concepts(query, budget.top_k)

        lexical_candidates = await self.ltm_store.recent_episodes(
            limit=max(budget.lexical_k * 4, budget.lexical_k)
        )

        lexical_ranked = sorted(
            lexical_candidates,
            key=lambda ep: lexical_similarity(query.text, ep.gist),
            reverse=True,
        )
        lexical_episodes = lexical_ranked[: budget.lexical_k]

        episode_pool = self._dedupe_episodes(dense_episodes + lexical_episodes)
        concept_pool = self._dedupe_concepts(dense_concepts)

        anchor_scores = self._score_candidates(query, query_vec, episode_pool)
        activations = await self._spreading_activation(
            anchor_scores,
            budget.graph_hops,
            budget.graph_top_m,
        )

        ranked_episodes = self._rank_episodes(query, episode_pool, anchor_scores, activations)
        ranked_concepts = self._rank_concepts(query, concept_pool, activations)

        facts = await self.ltm_store.list_facts(limit=budget.top_k)

        return RecallResult(
            episodes=ranked_episodes[: budget.top_k],
            facts=facts,
            concepts=ranked_concepts[: budget.top_k],
        )

    def _dedupe_episodes(self, episodes: Iterable[Episode]) -> list[Episode]:
        seen = set()
        result: list[Episode] = []
        for episode in episodes:
            if episode.episode_id in seen:
                continue
            seen.add(episode.episode_id)
            result.append(episode)
        return result

    def _dedupe_concepts(self, concepts: Iterable[ConceptNode]) -> list[ConceptNode]:
        seen = set()
        result: list[ConceptNode] = []
        for concept in concepts:
            if concept.concept_id in seen:
                continue
            seen.add(concept.concept_id)
            result.append(concept)
        return result

    def _score_candidates(
        self, query: MemoryQuery, query_vec: list[float], episodes: list[Episode]
    ) -> dict[str, float]:
        now = datetime.now().astimezone()
        scores: dict[str, float] = {}
        for episode in episodes:
            sim_sem = cosine_similarity(query_vec, episode.embedding)
            sim_lex = lexical_similarity(query.text, episode.gist)
            recency = exp_decay((now - episode.ts_end).total_seconds(), self.config.tau_seconds)
            prior_salience = episode.salience
            score = (
                self.config.w_semantic * sim_sem
                + self.config.w_lexical * sim_lex
                + self.config.w_recency * recency
                + self.config.w_salience * prior_salience
            )
            scores[episode.episode_id] = clamp(score, 0.0, 1.0)
        return scores

    async def _spreading_activation(
        self,
        anchor_scores: dict[str, float],
        hops: int,
        top_m: int,
    ) -> dict[str, float]:
        activations = dict(anchor_scores)
        if not activations or hops <= 0:
            return activations

        current = dict(activations)
        for hop in range(hops):
            if not current:
                break
            node_ids = list(current.keys())
            edges = await self.ltm_store.fetch_edges(node_ids, limit=self.config.edge_limit)
            next_scores: dict[str, float] = {}
            for edge in edges:
                src_activation = current.get(edge.src, 0.0)
                if src_activation <= 0.0:
                    continue
                propagated = src_activation * edge.weight * (self.config.activation_decay ** hop)
                next_scores[edge.dst] = next_scores.get(edge.dst, 0.0) + propagated
            # sparsify
            sorted_nodes = sorted(
                next_scores.items(), key=lambda item: item[1], reverse=True
            )[:top_m]
            current = {node_id: score for node_id, score in sorted_nodes}
            for node_id, score in current.items():
                activations[node_id] = max(activations.get(node_id, 0.0), score)
        return activations

    def _rank_episodes(
        self,
        query: MemoryQuery,
        episodes: list[Episode],
        anchor_scores: dict[str, float],
        activations: dict[str, float],
    ) -> list[Episode]:
        ranked = sorted(
            episodes,
            key=lambda ep: self._final_score(query, ep, anchor_scores, activations),
            reverse=True,
        )
        return ranked

    def _rank_concepts(
        self,
        query: MemoryQuery,
        concepts: list[ConceptNode],
        activations: dict[str, float],
    ) -> list[ConceptNode]:
        ranked = sorted(
            concepts,
            key=lambda cn: activations.get(cn.concept_id, 0.0) + cn.prior,
            reverse=True,
        )
        return ranked

    def _final_score(
        self,
        query: MemoryQuery,
        episode: Episode,
        anchor_scores: dict[str, float],
        activations: dict[str, float],
    ) -> float:
        sim_emotion = cosine_similarity(query.state.vector(), episode.emotion_vec.vector())
        activation = activations.get(episode.episode_id, 0.0)
        graph_prior = episode.salience
        return (
            self.config.w_semantic * anchor_scores.get(episode.episode_id, 0.0)
            + self.config.w_activation * activation
            + self.config.w_graph_prior * graph_prior
            + self.config.w_emotion * sim_emotion
        )
