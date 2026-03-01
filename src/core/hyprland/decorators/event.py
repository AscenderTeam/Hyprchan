from typing import Any, Callable
from ascender.core import ControllerDecoratorHook, inject

from core.hyprland.socket import HyprlandSocket


class HyprEvent(ControllerDecoratorHook):
    hyprsocket: HyprlandSocket = inject(HyprlandSocket)
    
    def __init__(self, name: str) -> None:
        super().__init__()
        self.event_name = name
    
    def on_load(self, callable: Callable[..., Any]):
        self.hyprsocket.add_event_listener(self.event_name, callable)