from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from langchain_core.tools import StructuredTool

from core.hypraios.constants import Phases


@dataclass(slots=True)
class ToolContext:
    phase: Phases | None
    memory_enabled: bool
    animation_poses: list[str]


ToolPredicate = Callable[[ToolContext], bool]
ToolMarker = Literal["mandatory", "optional"]


@dataclass(slots=True)
class ToolSpec:
    name: str
    tool: StructuredTool
    priority: int = 0
    marker: ToolMarker = "optional"
    predicate: ToolPredicate | None = None
