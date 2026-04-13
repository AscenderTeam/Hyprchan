from __future__ import annotations

from typing import Any

from ascender.core.database import DatabaseEngine
from hyprchan.entities.skills import SkillEntity
from sqlalchemy import String, func, or_, select

from hyprchan.core.hyprmemory.interfaces import ProceduralMemoryStore
from hyprchan.core.hyprmemory.models import ProceduralMemory


class PostgresProceduralStore(ProceduralMemoryStore):
    """Postgres-backed procedural memory store using SQLAlchemy async sessions."""

    def __init__(self, database: DatabaseEngine) -> None:
        self._context = database.generate_context()

    async def upsert(self, memory: ProceduralMemory) -> None:
        async with self._context() as session:
            entity = SkillEntity(
                id=memory.memory_id,
                name=memory.name,
                description=memory.description,
                tags=memory.tags,
                tool_sequence=memory.tool_sequence,
                failure_notes=memory.failure_notes,
                success_score=memory.success_score,
                embedding=memory.embedding,
            )
            await session.merge(entity)
            await session.commit()
            # self.logger.debug(f"Upserted skill {memory.name} to Postgres")

    async def fetch_by_id(self, memory_id: str) -> ProceduralMemory | None:
        async with self._context() as session:
            stmt = select(SkillEntity).where(
                SkillEntity.id == memory_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._from_entity(row)

    async def fetch_by_name(self, name: str) -> ProceduralMemory | None:
        async with self._context() as session:
            stmt = select(SkillEntity).where(
                SkillEntity.name == name
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._from_entity(row)

    async def list_recent(self, limit: int) -> list[ProceduralMemory]:
        async with self._context() as session:
            stmt = (
                select(SkillEntity)
                .order_by(SkillEntity.success_score.desc(), SkillEntity.name.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self._from_entity(row[0]) for row in result.all()]

    async def search_by_embedding(
        self, query_embedding: list[float], top_k: int
    ) -> list[ProceduralMemory]:
        if not query_embedding:
            return []
        async with self._context() as session:
            stmt = (
                select(SkillEntity)
                .where(SkillEntity.embedding.is_not(None))
                .order_by(
                    SkillEntity.embedding.cosine_distance(query_embedding)
                )
                .limit(top_k)
            )
            result = await session.execute(stmt)
            return [self._from_entity(row[0]) for row in result.all()]

    async def query(self, term: str, limit: int) -> list[ProceduralMemory]:
        term = term.strip()
        if not term:
            return []
        pattern = f"%{term.lower()}%"
        async with self._context() as session:
            stmt = (
                select(SkillEntity)
                .where(  # type: ignore[assignment]
                    or_(
                        func.lower(SkillEntity.name).ilike(pattern),
                        func.lower(SkillEntity.description).ilike(pattern),
                        func.lower(func.coalesce(func.cast(SkillEntity.tags, String), "")).ilike(pattern),
                    )
                )
                .order_by(SkillEntity.success_score.desc(), SkillEntity.name.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self._from_entity(row[0]) for row in result.all()]

    @staticmethod
    def _from_entity(entity: SkillEntity) -> ProceduralMemory:
        return ProceduralMemory(
            memory_id=entity.id,
            name=entity.name,
            description=entity.description,
            tags=list(entity.tags or []),
            tool_sequence=list(entity.tool_sequence or []),
            failure_notes=list(entity.failure_notes or []),
            success_score=float(entity.success_score or 0.0),
            embedding=PostgresProceduralStore._coerce_embedding(entity.embedding),
        )

    @staticmethod
    def _coerce_embedding(value: Any) -> list[float]:
        if value is None:
            return []
        return [float(item) for item in list(value)]
