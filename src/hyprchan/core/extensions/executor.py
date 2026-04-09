import time
from typing import Any

from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.hooks.types import HookFn, HookName


class ExtensionExecutor:
    def __init__(self, kernel: Any):
        self.__kernel = kernel

    @property
    def phase(self) -> Phases:
        return self.__kernel.states.phase

    @property
    def is_passive(self) -> bool:
        return self.phase == Phases.PASSIVE

    @property
    def is_active(self) -> bool:
        return self.phase == Phases.ACTIVE

    @property
    def is_sleeping(self) -> bool:
        return self.phase == Phases.SLEEP

    @property
    def until_next_ponder(self) -> float:
        return self.__kernel.next_passive_ponder_at - time.monotonic()

    @property
    def tool_manager(self):
        return self.__kernel.linguistic_engine.tool_runtime.tool_registry

    def delay_pondering(self, timeout: float = 5.0):
        self.__kernel.next_passive_ponder_at += timeout

    def trigger_pondering(self):
        self.__kernel.next_passive_ponder_at = 0

    def add_hook(
        self,
        name: HookName,
        hook: HookFn,
        *,
        priority: int = 0,
        once: bool = False,
    ) -> None:
        self.__kernel.hooks.register(name, hook, priority=priority, once=once)

    def remove_hook(self, name: HookName, hook: HookFn) -> None:
        self.__kernel.hooks.unregister(name, hook)

    async def run_inference_cycle(self, inputs: list[dict[str, Any]]):
        await self.__kernel._run_inference_cycle(inputs)

    async def emit_signal(
        self,
        *,
        event_type: str,
        description: str,
        origin: str,
        amplitude: float = 1.0,
        force_active: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signal = await self.__kernel.record_perception(
            event_type=event_type,
            description=description,
            origin=origin,
            amplitude=amplitude,
            force_active=force_active,
            metadata=metadata,
        )
        self.__kernel.main_loop.perception_signal()
        return signal
