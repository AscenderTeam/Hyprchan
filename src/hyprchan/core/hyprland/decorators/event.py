from typing import Any, Callable
from ascender.core import ControllerDecoratorHook, inject

from core.hyprland.socket import HyprlandSocket


class HyprEvent(ControllerDecoratorHook):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.event_name = name

    def on_load(self, callable: Callable[..., Any]):
        fallback = object()
        socket = inject(HyprlandSocket, fallback=fallback)
        if socket is fallback:
            return
        socket.add_event_listener(self.event_name, callable)
