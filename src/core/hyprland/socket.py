import asyncio
from collections import defaultdict
import json
from logging import Logger
import traceback
from typing import Annotated, Any, Callable, Literal, overload
from ascender.common import Injectable
from ascender.core import Application, Inject

from core.hyprland.const import COMMAND_SOCK_DIR, EVENT_SOCK_DIR
from core.hyprland.sock_stream import UNIXSockStream
from core.hyprland.utils import _ListenerSpec, analyze_listener, dispatch_event


@Injectable(provided_in="root")
class HyprlandSocket:
    listeners: dict[str, list[_ListenerSpec]]
    
    def __init__(self, application: Application, logger: Annotated[Logger, Inject("ASC_LOGGER")]) -> None:
        self._application = application
        self.listeners = defaultdict(list)
        self.sender, self.reader = UNIXSockStream(sock_path=COMMAND_SOCK_DIR, sock2_path=EVENT_SOCK_DIR).split()
        
        self.logger = logger
        
        self.active = False
        self._listener_task = None
        
        self._application.app.add_event_handler("startup", self.__on_startup)
        self._application.app.add_event_handler("shutdown", self.__on_shutdown)
    
    async def __on_startup(self):
        self._listener_task = asyncio.create_task(self.start_global_listener())
    
    async def __on_shutdown(self):
        self.active = False
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                self.logger.info("Gracefully stopping hyprland listener socket...")
        
    @overload
    async def send_command(self, cmd: str) -> str:
        ...
    
    @overload
    async def send_command(self, cmd: str, is_json: Literal[True]) -> Any:
        ...
    
    async def send_command(self, cmd: str, is_json: bool = False) -> str | Any:
        if is_json:
            cmd = f"[j]/{cmd}"
        
        response = (await self.sender.send_command(cmd.encode("utf-8"))).decode("utf-8")
        
        if is_json:
            return json.loads(response)
        
        return response
    
    async def start_global_listener(self):
        self.logger.info("Starting [cyan]Hyprland[/cyan] global event listener...")
        self.active = True
        async for data in self.reader.listen(auto_decode=True):
            if not data:
                continue
            
            if not self.active:
                break
            
            event_parts = data.split(">>", 1)
            event = event_parts[0]
            payload = event_parts[1] if len(event_parts) > 1 else None
            try:
                await dispatch_event(self.listeners, event, payload)
            except:
                traceback.print_exc()
                pass

    def add_event_listener(self, event: str, callback: Callable[..., Any]):
        self.listeners[event].append(analyze_listener(callback))
