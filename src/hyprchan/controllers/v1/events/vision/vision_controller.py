from ascender.core import Controller, Get

from hyprchan.controllers.v1.events.vision.vision_service import VisionService


@Controller(
    standalone=True,
    guards=[],
    imports=[],
    providers=[],
)
class VisionController:
    def __init__(self, vision_service: VisionService):
        self.vision_service = vision_service

    @Get("status")
    async def status(self):
        return self.vision_service.status()

    @Get("scan")
    async def scan(self):
        return await self.vision_service.scan_once()
