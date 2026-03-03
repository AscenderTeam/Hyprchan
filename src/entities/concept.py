from __future__ import annotations

from ascender.core.database import DBEntity
from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column
import settings


class ConceptEntity(DBEntity):
    __tablename__ = "hypr_concepts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256))
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.HYPRMEMORY_VECTOR_DIM), nullable=True
    )
    prior: Mapped[float] = mapped_column(Float(), default=0.0)
