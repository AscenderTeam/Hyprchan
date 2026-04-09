from __future__ import annotations

from datetime import datetime

from ascender.core.database import DBEntity
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from hyprchan import settings


class EpisodeEntity(DBEntity):
    __tablename__ = "hypr_episodes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ts_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gist: Mapped[str] = mapped_column(Text())
    entities: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    topics: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    emotion_vec: Mapped[dict | None] = mapped_column(JSON(), default=dict)
    semantic_feeling: Mapped[dict | None] = mapped_column(JSON(), default=dict)
    source_trace_ids: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.HYPRMEMORY_VECTOR_DIM), nullable=True
    )
    salience: Mapped[float] = mapped_column(Float(), default=0.0)
    version: Mapped[int] = mapped_column(Integer(), default=1)
