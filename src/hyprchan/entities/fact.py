from __future__ import annotations

from datetime import datetime

from ascender.core.database import DBEntity
from sqlalchemy import DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class FactEntity(DBEntity):
    __tablename__ = "hypr_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(String(128))
    predicate: Mapped[str] = mapped_column(String(128))
    object: Mapped[str] = mapped_column(Text())
    qualifiers: Mapped[dict | None] = mapped_column(JSON(), default=dict)
    confidence: Mapped[float] = mapped_column(Float(), default=0.0)
    support_episode_ids: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contradictions: Mapped[list[dict] | None] = mapped_column(JSON(), default=list)
