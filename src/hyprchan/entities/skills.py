from __future__ import annotations

from typing import Any

import settings
from ascender.core.database import DBEntity
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class SkillEntity(DBEntity):
    __tablename__ = "hypr_skills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text())
    tags: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    tool_sequence: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(), default=list
    )
    failure_notes: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    success_score: Mapped[float] = mapped_column(Float(), default=0.0)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.HYPRMEMORY_VECTOR_DIM), nullable=True
    )
