from __future__ import annotations

from dataclasses import dataclass

from ascender.core.database import DatabaseEngine
from sqlalchemy import select

from core.hyprmemory.interfaces import EmbeddingProvider, LTMStore, VectorStore
from core.hyprmemory.models import ConceptNode, Episode, MemoryQuery
from core.hyprmemory.stores.ltm_postgres import PostgresLTMStore
from entities.concept import ConceptEntity
from entities.episode import EpisodeEntity


@dataclass(slots=True)
class PgVectorStore(VectorStore):
    """PgVector-backed vector search for episodes and concepts."""

    database: DatabaseEngine
    ltm_store: LTMStore
    embedder: EmbeddingProvider

    def __post_init__(self) -> None:
        self._context = self.database.generate_context()

    async def upsert_episode(self, episode: Episode) -> None:
        await self.ltm_store.store_episode(episode)

    async def upsert_concept(self, concept: ConceptNode) -> None:
        await self.ltm_store.store_concept(concept)

    async def search_episodes(self, query: MemoryQuery, top_k: int) -> list[Episode]:
        query_vec = await self.embedder.embed(query.text)
        async with self._context() as session:
            stmt = (
                select(EpisodeEntity)
                .where(EpisodeEntity.embedding.is_not(None))
                .order_by(EpisodeEntity.embedding.cosine_distance(query_vec))
                .limit(top_k)
            )
            result = await session.execute(stmt)
            return [PostgresLTMStore.episode_from_entity(row[0]) for row in result.all()]

    async def search_concepts(self, query: MemoryQuery, top_k: int) -> list[ConceptNode]:
        query_vec = await self.embedder.embed(query.text)
        async with self._context() as session:
            stmt = (
                select(ConceptEntity)
                .where(ConceptEntity.embedding.is_not(None))
                .order_by(ConceptEntity.embedding.cosine_distance(query_vec))
                .limit(top_k)
            )
            result = await session.execute(stmt)
            return [PostgresLTMStore.concept_from_entity(row[0]) for row in result.all()]
