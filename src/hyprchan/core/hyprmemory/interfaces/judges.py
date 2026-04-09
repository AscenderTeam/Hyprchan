from __future__ import annotations

from typing import Protocol

from hyprchan.core.hyprmemory.models import (
    ConceptNode,
    Episode,
    EpisodeSummary,
    FactCandidate,
    GraphEdge,
    MemoryState,
    STMItem,
)


class LinkingJudge(Protocol):
    def propose_edges(
        self,
        episode: Episode,
        concepts: list[ConceptNode],
    ) -> list[GraphEdge]: ...


class ConsolidationJudge(Protocol):
    async def summarize(
        self, items: list[STMItem], *, state: MemoryState
    ) -> EpisodeSummary | None: ...

    async def extract_facts(
        self, items: list[STMItem], *, state: MemoryState
    ) -> list[FactCandidate]: ...

    async def dream_fragment(
        self, episodes: list[Episode], *, state: MemoryState
    ) -> str | None: ...
