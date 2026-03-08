from logging import Logger
from typing import Annotated
from ascender.common import Injectable
from ascender.core import Inject
from ascender.core.applications.application import Application

from controllers.v1.events.speech.speech_service import SpeechService
from controllers.v1.events.vision.vision_service import VisionService
from core.hyprland.socket import HyprlandSocket
from core.hypraios.kernel.kernel import HyprAIOSKernel
from shared.lifecycle import ServiceLifecycle
from shared.toggle_detector import AsyncToggleDetector


@Injectable(provided_in="root")
class WindowsService(ServiceLifecycle):
    workspace_sensor: AsyncToggleDetector
    monitor_sensor: AsyncToggleDetector
    window_sensor: AsyncToggleDetector

    def __init__(
        self,
        application: Application,
        hyprland: HyprlandSocket,
        kernel: HyprAIOSKernel,
        vision_service: VisionService,
        speech_service: SpeechService,
        logger: Annotated[Logger, Inject("ASC_LOGGER")],
    ):
        super().__init__(application)
        self.workspace_sensitivity = 0.2
        self.monitor_sensitivity = 0.2
        self.window_sensitivity = 0.4
        self.hyprland = hyprland
        self.kernel = kernel
        self.vision_service = vision_service
        self.speech_service = speech_service
        self.logger = logger

    async def _on_workspace_burst(self):
        self.logger.debug("Workspace burst detected; notifying user and kernel")
        await self.hyprland.send_command(
            "notify 0 5000 0 You're switching your workspace very fast!"
        )
        await self.kernel.record_perception(
            event_type="workspace_toggle_burst",
            description="workspace switches surged rapidly",
            origin="windows_controller",
            amplitude=1.4,
        )

    async def _on_window_burst(self):
        self.logger.debug("Window burst detected; notifying user and kernel")
        await self.hyprland.send_command("notify 4 5000 0 What are you doing?")
        await self.kernel.record_perception(
            event_type="window_toggle_burst",
            description="window focus changed rapidly",
            origin="windows_controller",
            amplitude=1.2,
        )

    async def _on_monitor_burst(self):
        self.logger.debug("Monitor burst detected; notifying user and kernel")
        await self.hyprland.send_command(
            "notify 1 5000 0 Monitors are quite... Overwhelmed don't you think?"
        )
        await self.kernel.record_perception(
            event_type="monitor_toggle_burst",
            description="monitor focus switched rapidly",
            origin="windows_controller",
            amplitude=1.1,
        )

    async def on_startup(self):
        self.logger.info("[cyan bold] Initiating all sensors... [/]")
        self.logger.debug(
            "Sensor sensitivities workspace=%s monitor=%s window=%s",
            self.workspace_sensitivity,
            self.monitor_sensitivity,
            self.window_sensitivity,
        )
        self.workspace_sensor = AsyncToggleDetector.from_sensitivity_param(
            self.workspace_sensitivity, self._on_workspace_burst, cooldown=5
        )

        self.window_sensor = AsyncToggleDetector.from_sensitivity_param(
            self.window_sensitivity, self._on_window_burst, cooldown=5
        )

        self.monitor_sensor = AsyncToggleDetector.from_sensitivity_param(
            self.monitor_sensitivity, self._on_monitor_burst, cooldown=4
        )
        await self.kernel.bootup()
        self.logger.info("[green bold] All sensors are active! [/]")

    async def on_shutdown(self):
        self.logger.debug("WindowsService shutdown requested")
        await self.kernel.shutdown()

    async def workspace_change(self, workspace_id: str, workspace_name: str):
        self.logger.debug(
            "Workspace changed id=%s name=%s",
            workspace_id,
            workspace_name,
        )
        await self.workspace_sensor.toggle()
        await self.kernel.record_perception(
            event_type="workspace_switch",
            description=f"workspace switched to {workspace_name} ({workspace_id})",
            origin="windows_controller",
            amplitude=0.35,
        )

    async def monitor_focus_change(self):
        self.logger.debug("Monitor focus change detected")
        await self.monitor_sensor.toggle()
        await self.kernel.record_perception(
            event_type="monitor_focus",
            description="monitor focus changed",
            origin="windows_controller",
            amplitude=0.25,
        )

    async def active_window_change(self):
        self.logger.debug("Active window change detected")
        await self.window_sensor.toggle()
        await self.kernel.record_perception(
            event_type="window_focus",
            description="active window changed",
            origin="windows_controller",
            amplitude=0.2,
        )
