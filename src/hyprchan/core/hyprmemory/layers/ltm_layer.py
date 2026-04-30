from __future__ import annotations

from datetime import datetime

from hyprchan.core.hyprmemory.interfaces import LTMStore
from hyprchan.core.hyprmemory.models import ConceptNode, DreamEntry, Episode, GraphEdge, SemanticFact


class LongTermMemoryLayer:
    """Long-term memory access layer (LTM)."""

    def __init__(self, store: LTMStore) -> None:
        self.store = store

    async def store_episode(self, episode: Episode) -> None:
        """Persist an episodic memory node."""
        await self.store.store_episode(episode)

    async def store_fact(self, fact: SemanticFact) -> None:
        """Persist a semantic fact triple."""
        await self.store.store_fact(fact)

    async def store_concept(self, concept: ConceptNode) -> None:
        """Persist a concept node for the memory graph."""
        await self.store.store_concept(concept)

    async def store_edge(self, edge: GraphEdge) -> None:
        """Persist a graph edge for associative recall."""
        await self.store.store_edge(edge)

    async def recent_episodes(self, limit: int) -> list[Episode]:
        """Fetch recent episodic memories."""
        return await self.store.recent_episodes(limit=limit)

    async def episodes_in_range(self, ts_from: datetime, ts_to: datetime, limit: int) -> list[Episode]:
        """Fetch episodes whose window overlaps [ts_from, ts_to], ordered by ts_start asc."""
        return await self.store.episodes_in_range(ts_from=ts_from, ts_to=ts_to, limit=limit)

    async def list_facts(self, limit: int) -> list[SemanticFact]:
        """Fetch semantic facts."""
        return await self.store.list_facts(limit=limit)

    async def list_concepts(self, limit: int) -> list[ConceptNode]:
        """Fetch concept nodes."""
        return await self.store.list_concepts(limit=limit)

    async def fetch_edges(self, node_ids: list[str], limit: int) -> list[GraphEdge]:
        """Fetch associative edges connected to node ids."""
        return await self.store.fetch_edges(node_ids, limit=limit)

    async def store_dream(self, dream: DreamEntry) -> None:
        """Persist a dream log entry."""
        await self.store.store_dream(dream)

    async def list_dreams(self, limit: int) -> list[DreamEntry]:
        """Fetch recent dream log entries."""
        return await self.store.list_dreams(limit=limit)

    async def clear_dreams(self) -> None:
        """Clear stored dream log entries after consumption."""
        await self.store.clear_dreams()
