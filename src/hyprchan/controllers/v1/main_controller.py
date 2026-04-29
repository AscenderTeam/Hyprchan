import asyncio
from pathlib import Path

from alp import ALPReceiver
from ascender.core import Controller, Get, Post
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from hyprchan.core.hypraios.kernel.kernel import HyprAIOSKernel


class CommunicationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    timeout_sec: float = Field(default=20.0, ge=1.0, le=60.0)


@Controller(
    standalone=True,
    guards=[],
    imports=[],
    providers=[],
)
class MainController:
    def __init__(self, kernel: HyprAIOSKernel):
        self.kernel = kernel
        self._ui_file = (
            Path(__file__).resolve().parents[4] / "public" / "agent_communication.html"
        )
        self._boot_task: asyncio.Task[None] | None = None

    async def _ensure_booted(self) -> None:
        if self._boot_task is None or self._boot_task.done():
            self._boot_task = asyncio.create_task(self.kernel.bootup())
        await self._boot_task

    @Get()
    async def main_endpoint(self):
        await self._ensure_booted()
        return "main works!"

    @Get("summon")
    async def summon(self):
        await self._ensure_booted()
        await self.kernel.record_perception(
            event_type="communication_summon",
            description="Direct communication summon from user",
            origin="communication_controller",
            amplitude=1.0,
            force_active=True,
        )
        return {"status": "ok", "phase": str(self.kernel.states.phase.name)}

    @Get("communication")
    async def communication_ui(self) -> HTMLResponse:
        if self._ui_file.exists():
            return HTMLResponse(self._ui_file.read_text(encoding="utf-8"))

        return HTMLResponse(
            "<html><body><h1>Communication UI missing</h1></body></html>",
            status_code=404,
        )

    @Post("communication/send")
    async def communication_send(self, payload: CommunicationRequest):
        await self._ensure_booted()
        return await self.kernel.communicate(
            payload.text,
            timeout_sec=float(payload.timeout_sec),
        )

    @Get("communication/events")
    async def communication_events(self, since_id: int = 0, limit: int = 200):
        await self._ensure_booted()
        return self.kernel.events_view(since_id=since_id, limit=limit)

    @ALPReceiver("connect")
    async def on_connect(self, sid: str):
        pass

    @ALPReceiver("message")
    async def on_alp_message(self, sid: str, data: CommunicationRequest):
        await self._ensure_booted()
        return await self.kernel.communicate(
            data.text, timeout_sec=float(data.timeout_sec)
        )
