from typing import Any, Callable, Protocol, runtime_checkable


PerceptionEvent = dict[str, Any]
PerceptionEventCallback = Callable[[PerceptionEvent], Any]
PerceptionStatus = dict[str, Any]


@runtime_checkable
class PerceptionSource(Protocol):
    """
    Contract for perception providers in HyprAI OS.

    Providers publish raw events only. They never mutate kernel state,
    force phase transitions, or trigger inference directly.
    """

    @property
    def source_name(self) -> str: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def last_error(self) -> str | None: ...

    @property
    def last_observation(self) -> dict[str, Any] | None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def scan_once(self, *, emit: bool = True) -> PerceptionEvent | None: ...

    def status(self) -> PerceptionStatus: ...
