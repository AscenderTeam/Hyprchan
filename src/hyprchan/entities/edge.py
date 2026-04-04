from __future__ import annotations

from datetime import datetime

from ascender.core.database import DBEntity
from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column


class EdgeEntity(DBEntity):
    __tablename__ = "hypr_edges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    src: Mapped[str] = mapped_column(String(64))
    dst: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(64))
    weight: Mapped[float] = mapped_column(Float(), default=0.0)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decay_half_life_hours: Mapped[float] = mapped_column(Float(), default=72.0)
