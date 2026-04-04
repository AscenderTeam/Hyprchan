from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class EventCompactionRequest:
    events: list[dict[str, Any]]
    max_sentence_chars: int = 220


@dataclass(slots=True)
class EventCompactionResult:
    summary: str
    model: str
    compacted_count: int


class EventCompacter(ABC):
    @abstractmethod
    async def compact(
        self, request: EventCompactionRequest
    ) -> EventCompactionResult | None:
        raise NotImplementedError
