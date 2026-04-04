from __future__ import annotations

from datetime import datetime
from typing import Any

import settings
from ascender.core.database import DBEntity
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column


class SkillEntity(DBEntity):
    __tablename__ = "hypr_skills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text())
    tags: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    goal_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    context_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tool_sequence: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(), default=list
    )
    arg_templates: Mapped[dict[str, Any] | None] = mapped_column(JSON(), default=dict)
    failure_modes: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(), default=list
    )
    success_score: Mapped[float] = mapped_column(Float(), default=0.0)
    success_count: Mapped[int] = mapped_column(Integer(), default=0)
    failure_count: Mapped[int] = mapped_column(Integer(), default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.HYPRMEMORY_VECTOR_DIM), nullable=True
    )
