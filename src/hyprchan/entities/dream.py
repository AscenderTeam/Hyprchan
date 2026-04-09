from __future__ import annotations

from datetime import datetime

from ascender.core.database import DBEntity
from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class DreamEntity(DBEntity):
    __tablename__ = "hypr_dreams"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content: Mapped[str] = mapped_column(Text())
    episode_ids: Mapped[list[str] | None] = mapped_column(JSON(), default=list)
    source: Mapped[str] = mapped_column(String(64), default="llm_judge")
