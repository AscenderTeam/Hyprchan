from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.hyprmemory.models import (
    ConceptNode,
    Episode,
    GraphEdge,
    MemoryQuery,
    MemoryState,
    RecallBudget,
    SemanticFact,
    SemanticFeeling,
)
from core.hyprmemory.services.retriever import HybridRetriever, RetrieverConfig


def _episode(
    episode_id: str,
    *,
    gist: str,
    embedding: list[float],
    salience: float,
    age_hours: float,
) -> Episode:
    end = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    start = end - timedelta(minutes=3)
    return Episode(
        episode_id=episode_id,
        ts_start=start,
        ts_end=end,
        gist=gist,
        entities=["HyprChan"],
        topics=["testing"],
        emotion_vec=MemoryState(f=10.0, v=0.3, e=0.7, a=0.2),
        semantic_feeling=SemanticFeeling(
            label="steady focus",
            cognitive="balanced awareness",
            motivation="steady maintenance",
            stability=0.8,
        ),
        source_trace_ids=[f"trace-{episode_id}"],
        embedding=embedding,
        salience=salience,
    )


class _FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        if "primary" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


class _FakeVectorStore:
    def __init__(self, episodes: list[Episode], concepts: list[ConceptNode]) -> None:
        self._episodes = episodes
        self._concepts = concepts

    async def upsert_episode(self, episode: Episode) -> None:  # pragma: no cover
        return None

    async def upsert_concept(self, concept: ConceptNode) -> None:  # pragma: no cover
        return None

    async def search_episodes(self, query: MemoryQuery, top_k: int) -> list[Episode]:
        return list(self._episodes[:top_k])

    async def search_concepts(
        self, query: MemoryQuery, top_k: int
    ) -> list[ConceptNode]:
        return list(self._concepts[:top_k])


class _FakeLTMStore:
    def __init__(
        self,
        *,
        lexical_episodes: list[Episode],
        edges: list[GraphEdge],
        facts: list[SemanticFact],
    ) -> None:
        self.lexical_episodes = lexical_episodes
        self.edges = edges
        self.facts = facts

    async def store_episode(self, episode: Episode) -> None:  # pragma: no cover
        return None

    async def store_fact(self, fact: SemanticFact) -> None:  # pragma: no cover
        return None

    async def store_concept(self, concept: ConceptNode) -> None:  # pragma: no cover
        return None

    async def store_edge(self, edge: GraphEdge) -> None:  # pragma: no cover
        return None

    async def recent_episodes(self, limit: int) -> list[Episode]:
        return list(self.lexical_episodes[:limit])

    async def list_concepts(self, limit: int) -> list[ConceptNode]:  # pragma: no cover
        return []

    async def list_facts(self, limit: int) -> list[SemanticFact]:
        return list(self.facts[:limit])

    async def fetch_edges(self, node_ids: list[str], limit: int) -> list[GraphEdge]:
        return [edge for edge in self.edges if edge.src in node_ids][:limit]

    async def store_dream(self, dream) -> None:  # pragma: no cover
        return None

    async def list_dreams(self, limit: int):  # pragma: no cover
        return []

    async def clear_dreams(self) -> None:  # pragma: no cover
        return None


@pytest.mark.asyncio
async def test_recall_dedupes_episodes_and_respects_budget() -> None:
    primary = _episode(
        "ep-primary",
        gist="primary context",
        embedding=[1.0, 0.0],
        salience=0.8,
        age_hours=1,
    )
    secondary = _episode(
        "ep-secondary",
        gist="secondary context",
        embedding=[0.0, 1.0],
        salience=0.2,
        age_hours=48,
    )
    concept = ConceptNode(
        concept_id="cn-primary",
        kind="topic",
        name="testing",
        embedding=[1.0, 0.0],
        prior=0.1,
    )
    fact = SemanticFact(
        fact_id="fact-1",
        subject="user",
        predicate="prefers",
        object="concise answers",
        qualifiers={},
        confidence=0.9,
        support_episode_ids=["ep-primary"],
        last_verified=datetime.now(timezone.utc),
    )

    retriever = HybridRetriever(
        ltm_store=_FakeLTMStore(
            lexical_episodes=[secondary, primary],
            edges=[],
            facts=[fact],
        ),
        vector_store=_FakeVectorStore(
            episodes=[primary, primary],
            concepts=[concept, concept],
        ),
        embedder=_FakeEmbedder(),
        config=RetrieverConfig(
            w_semantic=1.0,
            w_lexical=0.0,
            w_recency=0.0,
            w_salience=0.0,
            w_activation=0.0,
            w_graph_prior=0.0,
            w_emotion=0.0,
        ),
    )

    result = await retriever.recall(
        MemoryQuery(
            text="primary query",
            state=MemoryState(f=8.0, v=0.2, e=0.7, a=0.2),
            budget=RecallBudget(top_k=1, lexical_k=1, graph_hops=0, graph_top_m=3),
        )
    )

    assert len(result.episodes) == 1
    assert result.episodes[0].episode_id == "ep-primary"
    assert len(result.concepts) == 1
    assert result.concepts[0].concept_id == "cn-primary"
    assert len(result.facts) == 1


@pytest.mark.asyncio
async def test_spreading_activation_propagates_to_connected_nodes() -> None:
    linked_edge = GraphEdge(
        edge_id="edge-1",
        src="ep-seed",
        dst="ep-linked",
        type="semantic_sim",
        weight=0.8,
        ts=datetime.now(timezone.utc),
        decay_half_life_hours=48.0,
    )
    retriever = HybridRetriever(
        ltm_store=_FakeLTMStore(lexical_episodes=[], edges=[linked_edge], facts=[]),
        vector_store=_FakeVectorStore(episodes=[], concepts=[]),
        embedder=_FakeEmbedder(),
        config=RetrieverConfig(activation_decay=1.0),
    )

    activations = await retriever._spreading_activation(
        {"ep-seed": 0.75},
        hops=1,
        top_m=5,
    )

    assert activations["ep-seed"] == 0.75
    assert activations["ep-linked"] == pytest.approx(0.6)
