from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.hypraios.constants import Phases

if TYPE_CHECKING:
    from hyprchan.core.hyprmemory.services.memory_service import HyprMemoryService


class HyprchanExtension(ABC):
    memory: "HyprMemoryService | None" = None
    workspace_dir: Path | None = None
    data_dir: Path | None = None

    @abstractmethod
    async def on_init(self, executor: ExtensionExecutor) -> None: ...

    async def on_shutdown(self) -> None: ...

    async def on_phase_change(self, old_phase: Phases, new_phase: Phases) -> None: ...
