from ascender.core import Controller, Get

from core.hypraios.kernel.kernel import HyprAIOSKernel


@Controller(
    standalone=True,
    guards=[],
    imports=[],
    providers=[],
)
class MainController:
    def __init__(self, kernel: HyprAIOSKernel):
        self.kernel = kernel

    @Get()
    async def main_endpoint(self):
        return "main works!"

    @Get("summon")
    async def summon(self):
        await self.kernel.record_perception(
            event_type="communication_summon",
            description="Direct communication summon from user",
            origin="communication_controller",
            amplitude=1.0,
            force_active=True,
        )
        return {"status": "ok", "phase": str(self.kernel.states.phase.name)}
