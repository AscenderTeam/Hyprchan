from dataclasses import dataclass
from typing import Any

from hyprchan.core.hyprmemory.models import MemoryState


@dataclass(frozen=True)
class MemoryBuffer:
    index: int
    role: str
    content: str | dict[str, Any]
    state: MemoryState | None = None
    meta: dict[str, Any] | None = None
    kind: str = "chat.message"
