from __future__ import annotations

from typing import Any

from ascender.core.database import DatabaseEngine
from sqlalchemy import delete, or_, select

from hyprchan.core.hyprmemory.interfaces import LTMStore
from hyprchan.core.hyprmemory.models import (
    ConceptNode,
    DreamEntry,
    Episode,
    GraphEdge,
    SemanticFact,
)
from hyprchan.core.hyprmemory.utils.serialization import (
    feeling_from_dict,
    feeling_to_dict,
    state_from_dict,
    state_to_dict,
)
from hyprchan.entities.concept import ConceptEntity
from hyprchan.entities.dream import DreamEntity
from hyprchan.entities.edge import EdgeEntity
from hyprchan.entities.episode import EpisodeEntity
from hyprchan.entities.fact import FactEntity


class PostgresLTMStore(LTMStore):
    """Postgres-backed LTM store using SQLAlchemy async sessions."""

    def __init__(self, database: DatabaseEngine) -> None:
        self._context = database.generate_context()

    async def store_episode(self, episode: Episode) -> None:
        async with self._context() as session:
            entity = EpisodeEntity(
                id=episode.episode_id,
                ts_start=episode.ts_start,
                ts_end=episode.ts_end,
                gist=episode.gist,
                entities=episode.entities,
                topics=episode.topics,
                emotion_vec=state_to_dict(episode.emotion_vec),
                semantic_feeling=feeling_to_dict(episode.semantic_feeling),
                source_trace_ids=episode.source_trace_ids,
                embedding=episode.embedding,
                salience=episode.salience,
                version=episode.version,
            )
            session.add(entity)
            await session.commit()

    async def store_fact(self, fact: SemanticFact) -> None:
        async with self._context() as session:
            entity = FactEntity(
                id=fact.fact_id,
                subject=fact.subject,
                predicate=fact.predicate,
                object=fact.object,
                qualifiers=fact.qualifiers,
                confidence=fact.confidence,
                support_episode_ids=fact.support_episode_ids,
                last_verified=fact.last_verified,
                contradictions=fact.contradictions,
            )
            session.add(entity)
            await session.commit()

    async def store_concept(self, concept: ConceptNode) -> None:
        async with self._context() as session:
            entity = ConceptEntity(
                id=concept.concept_id,
                kind=concept.kind,
                name=concept.name,
                embedding=concept.embedding,
                prior=concept.prior,
            )
            session.add(entity)
            await session.commit()

    async def store_edge(self, edge: GraphEdge) -> None:
        async with self._context() as session:
            entity = EdgeEntity(
                id=edge.edge_id,
                src=edge.src,
                dst=edge.dst,
                type=edge.type,
                weight=edge.weight,
                ts=edge.ts,
                decay_half_life_hours=edge.decay_half_life_hours,
            )
            session.add(entity)
            await session.commit()

    async def recent_episodes(self, limit: int) -> list[Episode]:
        async with self._context() as session:
            stmt = (
                select(EpisodeEntity).order_by(EpisodeEntity.ts_end.desc()).limit(limit)
            )
            result = await session.execute(stmt)
            return [self.episode_from_entity(row[0]) for row in result.all()]

    async def list_concepts(self, limit: int) -> list[ConceptNode]:
        async with self._context() as session:
            stmt = (
                select(ConceptEntity).order_by(ConceptEntity.prior.desc()).limit(limit)
            )
            result = await session.execute(stmt)
            return [self.concept_from_entity(row[0]) for row in result.all()]

    async def list_facts(self, limit: int) -> list[SemanticFact]:
        async with self._context() as session:
            stmt = (
                select(FactEntity).order_by(FactEntity.confidence.desc()).limit(limit)
            )
            result = await session.execute(stmt)
            return [self.fact_from_entity(row[0]) for row in result.all()]

    async def fetch_edges(self, node_ids: list[str], limit: int) -> list[GraphEdge]:
        if not node_ids:
            return []
        async with self._context() as session:
            stmt = (
                select(EdgeEntity)
                .where(or_(EdgeEntity.src.in_(node_ids), EdgeEntity.dst.in_(node_ids)))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self.edge_from_entity(row[0]) for row in result.all()]

    async def store_dream(self, dream: DreamEntry) -> None:
        async with self._context() as session:
            entity = DreamEntity(
                id=dream.dream_id,
                ts=dream.ts,
                content=dream.content,
                episode_ids=dream.episode_ids,
                source=dream.source,
            )
            session.add(entity)
            await session.commit()

    async def list_dreams(self, limit: int) -> list[DreamEntry]:
        async with self._context() as session:
            stmt = select(DreamEntity).order_by(DreamEntity.ts.desc()).limit(limit)
            result = await session.execute(stmt)
            return [self.dream_from_entity(row[0]) for row in result.all()]

    async def clear_dreams(self) -> None:
        async with self._context() as session:
            await session.execute(delete(DreamEntity))
            await session.commit()

    @staticmethod
    def episode_from_entity(entity: EpisodeEntity) -> Episode:
        return Episode(
            episode_id=entity.id,
            ts_start=entity.ts_start,
            ts_end=entity.ts_end,
            gist=entity.gist,
            entities=list(entity.entities or []),
            topics=list(entity.topics or []),
            emotion_vec=state_from_dict(entity.emotion_vec or {}),
            semantic_feeling=feeling_from_dict(entity.semantic_feeling or {}),
            source_trace_ids=list(entity.source_trace_ids or []),
            embedding=PostgresLTMStore._coerce_embedding(entity.embedding),
            salience=float(entity.salience or 0.0),
            version=int(entity.version or 1),
        )

    @staticmethod
    def concept_from_entity(entity: ConceptEntity) -> ConceptNode:
        return ConceptNode(
            concept_id=entity.id,
            kind=entity.kind,
            name=entity.name,
            embedding=PostgresLTMStore._coerce_embedding(entity.embedding),
            prior=float(entity.prior or 0.0),
        )

    @staticmethod
    def fact_from_entity(entity: FactEntity) -> SemanticFact:
        return SemanticFact(
            fact_id=entity.id,
            subject=entity.subject,
            predicate=entity.predicate,
            object=entity.object,
            qualifiers=dict(entity.qualifiers or {}),
            confidence=float(entity.confidence or 0.0),
            support_episode_ids=list(entity.support_episode_ids or []),
            last_verified=entity.last_verified,
            contradictions=list(entity.contradictions or []),
        )

    @staticmethod
    def edge_from_entity(entity: EdgeEntity) -> GraphEdge:
        return GraphEdge(
            edge_id=entity.id,
            src=entity.src,
            dst=entity.dst,
            type=entity.type,
            weight=float(entity.weight or 0.0),
            ts=entity.ts,
            decay_half_life_hours=float(entity.decay_half_life_hours or 0.0),
        )

    @staticmethod
    def dream_from_entity(entity: DreamEntity) -> DreamEntry:
        return DreamEntry(
            dream_id=entity.id,
            ts=entity.ts,
            content=entity.content,
            episode_ids=list(entity.episode_ids or []),
            source=entity.source,
        )

    @staticmethod
    def _coerce_embedding(value: Any) -> list[float]:
        if value is None:
            return []
        return [float(item) for item in list(value)]
