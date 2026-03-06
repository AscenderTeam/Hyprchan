from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryBuffer:
    index: int
    role: str
    content: str | dict[str, Any]
