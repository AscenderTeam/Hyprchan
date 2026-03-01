from logging import Logger
from typing import Annotated
from ascender.common import Injectable
from ascender.core import Inject, Service

from core.hyprland.socket import HyprlandSocket
from shared.lifecycle import ServiceLifecycle
from shared.toggle_detector import AsyncToggleDetector


@Injectable(provided_in="root")
class WindowsService(ServiceLifecycle):
    workspace_sensor: AsyncToggleDetector
    monitor_sensor: AsyncToggleDetector
    window_sensor: AsyncToggleDetector
    
    def __init__(self, hyprland: HyprlandSocket, logger: Annotated[Logger, Inject("ASC_LOGGER")]):
        super().__init__()
        self.workspace_sensitivity = 0.2
        self.monitor_sensitivity = 0.2
        self.window_sensitivity = 0.4
        self.hyprland = hyprland
        self.logger = logger
    
    async def on_startup(self):
        self.logger.info("[cyan bold] Initiating all sensors... [/]")
        self.workspace_sensor = AsyncToggleDetector.from_sensitivity_param(
            self.workspace_sensitivity, 
            lambda: self.hyprland.send_command("notify 0 5000 0 You're switching your workspace very fast!"),
            cooldown=5
        )
        
        self.window_sensor = AsyncToggleDetector.from_sensitivity_param(
            self.window_sensitivity,
            lambda: self.hyprland.send_command("notify 4 5000 0 What are you doing?"),
            cooldown=5
        )
        
        self.monitor_sensor = AsyncToggleDetector.from_sensitivity_param(
            self.monitor_sensitivity,
            lambda: self.hyprland.send_command("notify 1 5000 0 Monitors are quite... Overwhelmed don't you think?"),
            cooldown=4
        )
        self.logger.info("[green bold] All sensors are active! [/]")
    
    async def workspace_change(self, workspace_id: str, workspace_name: str):
        await self.workspace_sensor.toggle()
    
    async def monitor_focus_change(self):
        await self.monitor_sensor.toggle()
    
    async def active_window_change(self):
        await self.window_sensor.toggle()