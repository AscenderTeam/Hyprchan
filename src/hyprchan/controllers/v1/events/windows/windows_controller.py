from ascender.core import Controller
from controllers.v1.events.windows.windows_service import WindowsService
from core.hyprland import HyprEvent


@Controller(
    standalone=True,
    guards=[],
    imports=[],
    providers=[],
)
class WindowsController:
    def __init__(self, windows_service: WindowsService):
        self.windows_service = windows_service

    @HyprEvent("workspacev2")
    async def hypr_workspace_change(self, workspace_id: str, workspace_name: str):
        await self.windows_service.workspace_change(workspace_id, workspace_name)

    @HyprEvent("focusedmonv2")
    async def hypr_monitor_focus(self, monitor_name: str, workspace_id: str):
        await self.windows_service.monitor_focus_change()

    @HyprEvent("activewindow")
    async def hypr_activewindow_change(self, window_class: str, window_title: str):
        # print("ACTIVE MONITOR:", window_title)
        await self.windows_service.active_window_change()
