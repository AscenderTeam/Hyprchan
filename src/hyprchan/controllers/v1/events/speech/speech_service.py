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
    SPEECH_INITIAL_PROMPT,
    SPEECH_INPUT_DEVICE,
    SPEECH_LANGUAGE,
    SPEECH_LOG_PROB_THRESHOLD,
    SPEECH_MAX_SPEECH_SEC,
    SPEECH_MIN_CONTINUE_DBFS,
    SPEECH_MIN_SPEECH_SEC,
    SPEECH_MIN_START_DBFS,
    SPEECH_NO_SPEECH_THRESHOLD,
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
        self._vad_speaking = False
        self._transcription_active_count = 0

    async def on_startup(self) -> None:
        self._source = None
        self._startup_error = None
        self._vad_speaking = False
        self._transcription_active_count = 0
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
            initial_prompt=SPEECH_INITIAL_PROMPT,
            no_speech_threshold=SPEECH_NO_SPEECH_THRESHOLD,
            log_prob_threshold=SPEECH_LOG_PROB_THRESHOLD,
        )

        self._source = SpeechPerceptionSource(
            self._record_event,
            config=config,
            speaking_state_callback=self._on_speaking_state_changed,
            transcription_state_callback=self._on_transcription_state_changed,
        )
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
        self._vad_speaking = False
        self._transcription_active_count = 0
        self._set_speech_glow_active(False)

    def _enqueue_animation_command(self, name: str, *args: Any) -> None:
        animations = getattr(self.kernel, "animations", None)
        if animations is None:
            return
        command = getattr(animations, name, None)
        if not callable(command):
            return
        command(*args)

    def _set_speech_glow_active(self, active: bool) -> None:
        self._enqueue_animation_command("enqueue_speech_glow_active", bool(active))

    def _fade_speech_glow(self, duration_sec: float) -> None:
        self._enqueue_animation_command("enqueue_speech_glow_fade", float(duration_sec))

    async def _on_speaking_state_changed(self, speaking: bool) -> None:
        self._vad_speaking = bool(speaking)
        if self._vad_speaking:
            self._set_speech_glow_active(True)
            return

        if self._transcription_active_count <= 0:
            self._fade_speech_glow(0.6)

    async def _on_transcription_state_changed(
        self, active: bool, speech_duration_sec: float
    ) -> None:
        if active:
            self._transcription_active_count += 1
            self._set_speech_glow_active(True)
            return

        self._transcription_active_count = max(0, self._transcription_active_count - 1)
        if self._vad_speaking or self._transcription_active_count > 0:
            self._set_speech_glow_active(True)
            return

        fade_duration = max(0.4, min(1.2, 0.45 + (float(speech_duration_sec) * 0.2)))
        self._fade_speech_glow(fade_duration)

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
