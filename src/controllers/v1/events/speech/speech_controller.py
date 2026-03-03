from ascender.core import Controller, Get

from controllers.v1.events.speech.speech_service import SpeechService


@Controller(
    standalone=True,
    guards=[],
    imports=[],
    providers=[],
)
class SpeechController:
    def __init__(self, speech_service: SpeechService):
        self.speech_service = speech_service

    @Get("status")
    async def status(self):
        return self.speech_service.status()
