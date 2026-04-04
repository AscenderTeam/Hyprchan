from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from langchain_core.tools import StructuredTool

from core.hypraios.tools.types import ToolContext, ToolSpec


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, ToolSpec]
    _logger: Logger | None = None

    def __init__(self, logger: Logger | None = None) -> None:
        self._tools = {}
        self._logger = logger

    def register(self, spec: ToolSpec, *, replace: bool = True) -> None:
        if not replace and spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        if spec.name in self._tools and self._logger is not None:
            self._logger.info("Replacing tool registration: %s", spec.name)
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def clear(self) -> None:
        self._tools.clear()

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def build(self, context: ToolContext) -> list[StructuredTool]:
        tools = list(self._tools.values())
        tools.sort(key=lambda item: item.priority, reverse=True)
        built: list[StructuredTool] = []
        for spec in tools:
            if spec.predicate is not None:
                try:
                    if not spec.predicate(context):
                        continue
                except Exception as exc:
                    if self._logger is not None:
                        self._logger.warning(
                            "Tool predicate failed for %s: %s", spec.name, exc
                        )
                    continue
            built.append(spec.tool)
        return built
