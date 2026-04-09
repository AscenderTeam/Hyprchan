from logging import Logger
from typing import Annotated, Any

from ascender.common import Injectable
from ascender.core import Inject
from ascender.core.applications.application import Application

from hyprchan.core.hypraios.kernel.kernel import HyprAIOSKernel
from hyprchan.core.hypraios.perception.speech_perception_source import (
    SpeechPerceptionConfig,
    SpeechPerceptionSource,
)
from hyprchan.settings import (
    SPEECH_END_SILENCE_SEC,
    SPEECH_FRAME_DURATION_MS,
    SPEECH_INPUT_DEVICE,
    SPEECH_LANGUAGE,
    SPEECH_MAX_SPEECH_SEC,
    SPEECH_MIN_CONTINUE_DBFS,
    SPEECH_MIN_SPEECH_SEC,
    SPEECH_MIN_START_DBFS,
    SPEECH_PERCEPTION_ENABLED,
    SPEECH_PRE_ROLL_SEC,
)
from hyprchan.shared.lifecycle import ServiceLifecycle


@Injectable(provided_in="root")
class SpeechService(ServiceLifecycle):
    def __init__(
        self,
        application: Application,
        kernel: HyprAIOSKernel,
        logger: Annotated[Logger, Inject("ASC_LOGGER")],
    ) -> None:
        super().__init__(application)
        self.kernel = kernel
        self.logger = logger
        self._source: SpeechPerceptionSource | None = None
        self._startup_error: str | None = None

    async def on_startup(self) -> None:
        self._source = None
        self._startup_error = None
        self.logger.debug("SpeechService startup begin")

        if not SPEECH_PERCEPTION_ENABLED:
            self.logger.info("Speech perception disabled by configuration")
            return

        config = SpeechPerceptionConfig(
            input_device=SPEECH_INPUT_DEVICE,
            language=SPEECH_LANGUAGE,
            frame_duration_ms=SPEECH_FRAME_DURATION_MS,
            min_speech_sec=SPEECH_MIN_SPEECH_SEC,
            end_silence_sec=SPEECH_END_SILENCE_SEC,
            max_speech_sec=SPEECH_MAX_SPEECH_SEC,
            pre_roll_sec=SPEECH_PRE_ROLL_SEC,
            min_start_dbfs=SPEECH_MIN_START_DBFS,
            min_continue_dbfs=SPEECH_MIN_CONTINUE_DBFS,
        )

        self._source = SpeechPerceptionSource(self._record_event, config=config)
        try:
            await self._source.start()
        except Exception as exc:
            self._startup_error = str(exc)
            self._source = None
            self.logger.warning("Speech perception unavailable: %s", exc)
            return

        self.logger.debug("Speech perception source started successfully")
        self.logger.info(
            "Speech perception active on input %s",
            self._source.status().get("input_device_name"),
        )

    async def on_shutdown(self) -> None:
        self.logger.debug("SpeechService shutdown begin")
        if self._source is not None:
            await self._source.stop()

    async def _record_event(self, event: dict[str, Any]) -> None:
        transcript = str(event.get("description", "")).strip()
        if not transcript:
            return

        self.logger.debug(
            "Speech transcript event accepted chars=%s",
            len(transcript),
        )

        metadata = {
            key: value
            for key, value in event.items()
            if key not in {"type", "description", "origin", "amplitude"}
        }

        await self.kernel.record_perception(
            event_type="communication_message",
            description=transcript,
            origin="communication_controller",
            amplitude=1.0,
            force_active=True,
            metadata=metadata,
        )

    def status(self) -> dict[str, Any]:
        self.logger.debug("SpeechService status requested")
        if not SPEECH_PERCEPTION_ENABLED:
            return {
                "enabled": False,
                "running": False,
                "message": "SPEECH_PERCEPTION_ENABLED is false",
            }

        if self._source is None:
            return {
                "enabled": True,
                "running": False,
                "error": self._startup_error,
            }

        return {
            "enabled": True,
            **self._source.status(),
        }
