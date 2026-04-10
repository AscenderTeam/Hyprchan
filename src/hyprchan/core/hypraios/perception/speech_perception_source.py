import asyncio
import inspect
import logging
import math
import time
from collections.abc import Callable
from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Protocol

import numpy as np

from hyprchan.core.hypraios.contracts import (
    PerceptionEvent,
    PerceptionEventCallback,
    PerceptionStatus,
)


logger = logging.getLogger(__name__)


SpeechSpeakingStateCallback = Callable[[bool], Any]
SpeechTranscriptionStateCallback = Callable[[bool, float], Any]


class SpeechTranscriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> "SpeechTranscription | str": ...


@dataclass(slots=True)
class SpeechTranscription:
    text: str
    language: str | None = None
    language_confidence: float | None = None


@dataclass(slots=True)
class SpeechPerceptionConfig:
    sample_rate: int = 16000
    channels: int = 1
    frame_duration_ms: int = 30
    min_speech_sec: float = 0.4
    end_silence_sec: float = 0.8
    max_speech_sec: float = 15.0
    pre_roll_sec: float = 0.3
    min_start_dbfs: float = -38.0
    min_continue_dbfs: float = -43.0
    noise_gate_margin_start_db: float = 10.0
    noise_gate_margin_continue_db: float = 6.0
    noise_floor_alpha: float = 0.95
    queue_max_frames: int = 256
    input_device: str = ""
    language: str = "auto"
    model_name: str = "Systran/faster-whisper-large-v3"
    event_type: str = "communication_message"
    origin: str = "communication_controller"

    def __post_init__(self) -> None:
        self.sample_rate = max(8000, int(self.sample_rate))
        self.channels = max(1, int(self.channels))
        self.frame_duration_ms = max(10, int(self.frame_duration_ms))
        self.min_speech_sec = max(0.1, float(self.min_speech_sec))
        self.end_silence_sec = max(0.1, float(self.end_silence_sec))
        self.max_speech_sec = max(self.min_speech_sec, float(self.max_speech_sec))
        self.pre_roll_sec = max(0.0, float(self.pre_roll_sec))
        self.queue_max_frames = max(8, int(self.queue_max_frames))

    @property
    def frame_size(self) -> int:
        return max(1, int((self.sample_rate * self.frame_duration_ms) / 1000))


class FasterWhisperSpeechTranscriber:
    def __init__(self, *, model_name: str, language: str) -> None:
        from faster_whisper import WhisperModel  # type: ignore

        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self.language = language

    def transcribe(self, audio: np.ndarray) -> SpeechTranscription:
        normalized_language = str(self.language or "").strip().lower()
        language_arg = (
            None
            if normalized_language in {"", "auto", "autodetect", "detect"}
            else self.language
        )
        segments, info = self.model.transcribe(audio, language=language_arg)
        parts = [segment.text.strip() for segment in segments if segment.text.strip()]
        detected_language = str(getattr(info, "language", "") or "").strip() or None
        raw_confidence = getattr(info, "language_probability", None)
        try:
            confidence = float(raw_confidence) if raw_confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        return SpeechTranscription(
            text=" ".join(parts).strip(),
            language=detected_language,
            language_confidence=confidence,
        )


class SpeechSegmenter:
    def __init__(self, config: SpeechPerceptionConfig) -> None:
        self.config = config

        self.pre_roll_frames = max(
            1, int(config.pre_roll_sec * config.sample_rate / config.frame_size)
        )
        self.start_trigger_frames = max(
            1, int(0.18 * config.sample_rate / config.frame_size)
        )
        self.min_speech_frames = max(
            1, int(config.min_speech_sec * config.sample_rate / config.frame_size)
        )
        self.end_silence_frames = max(
            1, int(config.end_silence_sec * config.sample_rate / config.frame_size)
        )
        self.max_speech_frames = max(
            1, int(config.max_speech_sec * config.sample_rate / config.frame_size)
        )

        self.pre_roll: deque[np.ndarray] = deque(maxlen=self.pre_roll_frames)
        self.active_frames: list[np.ndarray] = []
        self.is_speaking = False
        self.start_frame_counter = 0
        self.silence_frame_counter = 0
        self.speech_frame_counter = 0
        self.noise_floor_dbfs = -55.0

    def push(self, frame: np.ndarray) -> np.ndarray | None:
        dbfs = self._dbfs(frame)
        self._adapt_noise_floor(dbfs)

        dynamic_start_dbfs = max(
            self.config.min_start_dbfs,
            self.noise_floor_dbfs + self.config.noise_gate_margin_start_db,
        )
        dynamic_continue_dbfs = max(
            self.config.min_continue_dbfs,
            self.noise_floor_dbfs + self.config.noise_gate_margin_continue_db,
        )

        self.pre_roll.append(frame)

        if not self.is_speaking:
            if dbfs >= dynamic_start_dbfs:
                self.start_frame_counter += 1
            else:
                self.start_frame_counter = 0

            if self.start_frame_counter >= self.start_trigger_frames:
                self.is_speaking = True
                self.active_frames = list(self.pre_roll)
                self.speech_frame_counter = len(self.active_frames)
                self.silence_frame_counter = 0
                self.start_frame_counter = 0
            return None

        self.active_frames.append(frame)
        self.speech_frame_counter += 1

        if dbfs < dynamic_continue_dbfs:
            self.silence_frame_counter += 1
        else:
            self.silence_frame_counter = 0

        should_finalize = (
            self.silence_frame_counter >= self.end_silence_frames
            or self.speech_frame_counter >= self.max_speech_frames
        )

        if not should_finalize:
            return None

        trim_count = min(self.silence_frame_counter, len(self.active_frames))
        if trim_count > 0:
            voiced_frames = self.active_frames[:-trim_count]
        else:
            voiced_frames = list(self.active_frames)

        self._reset_active_state()

        if len(voiced_frames) < self.min_speech_frames:
            return None

        return np.concatenate(voiced_frames, axis=0).reshape(-1).astype(np.float32)

    def _reset_active_state(self) -> None:
        self.is_speaking = False
        self.active_frames = []
        self.speech_frame_counter = 0
        self.silence_frame_counter = 0
        self.start_frame_counter = 0

    def _adapt_noise_floor(self, dbfs: float) -> None:
        if self.is_speaking:
            return
        alpha = self.config.noise_floor_alpha
        self.noise_floor_dbfs = (alpha * self.noise_floor_dbfs) + ((1.0 - alpha) * dbfs)

    @staticmethod
    def _dbfs(frame: np.ndarray) -> float:
        if frame.size <= 0:
            return -120.0
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        if rms <= 1e-9:
            return -120.0
        return 20.0 * math.log10(rms)


class SpeechPerceptionSource:
    def __init__(
        self,
        event_callback: PerceptionEventCallback,
        *,
        config: SpeechPerceptionConfig | None = None,
        transcriber: SpeechTranscriber | None = None,
        sounddevice_module: Any | None = None,
        speaking_state_callback: SpeechSpeakingStateCallback | None = None,
        transcription_state_callback: SpeechTranscriptionStateCallback | None = None,
    ) -> None:
        self.event_callback = event_callback
        self.config = config or SpeechPerceptionConfig()
        self.segmenter = SpeechSegmenter(self.config)
        self.speaking_state_callback = speaking_state_callback
        self.transcription_state_callback = transcription_state_callback

        self._transcriber = transcriber
        self._sounddevice_module = sounddevice_module
        self._audio_stream: Any | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(
            maxsize=self.config.queue_max_frames
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_error: str | None = None
        self._last_observation: dict[str, Any] | None = None
        self._active_device_name: str | None = None
        self._active_device_id: int | None = None
        self._dropped_frames = 0
        self._stream_sample_rate = int(self.config.sample_rate)
        self._transcribe_sample_rate = int(self.config.sample_rate)
        self._last_speaking_state = bool(self.segmenter.is_speaking)

    @property
    def source_name(self) -> str:
        return "speech_perception"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_observation(self) -> dict[str, Any] | None:
        return self._last_observation

    async def start(self) -> None:
        if self._task and not self._task.done():
            logger.debug("Speech source start ignored; already running")
            return

        sd = self._sounddevice_module
        if sd is None:
            import sounddevice as sd_runtime  # type: ignore

            sd = sd_runtime
            self._sounddevice_module = sd

        if self._transcriber is None:
            self._transcriber = FasterWhisperSpeechTranscriber(
                model_name=self.config.model_name,
                language=self.config.language,
            )
            logger.debug(
                "Speech transcriber initialized model=%s language=%s",
                self.config.model_name,
                self.config.language,
            )

        self._loop = asyncio.get_running_loop()
        device_id, device_name, device_default_sample_rate = self._resolve_input_device(
            sd
        )
        self._active_device_id = device_id
        self._active_device_name = device_name
        logger.info("Speech source using input device: %s", device_name)

        preferred_sample_rate = int(self.config.sample_rate)
        try:
            self._audio_stream = self._open_stream(
                sd,
                device_id=device_id,
                sample_rate=preferred_sample_rate,
            )
            self._stream_sample_rate = preferred_sample_rate
        except Exception as exc:
            fallback_sample_rate = int(round(float(device_default_sample_rate or 0.0)))
            if fallback_sample_rate <= 0 or not self._is_invalid_sample_rate_error(exc):
                raise

            self._last_error = (
                f"Preferred sample rate {preferred_sample_rate} unsupported on device "
                f"{device_name}; falling back to {fallback_sample_rate}."
            )
            self._audio_stream = self._open_stream(
                sd,
                device_id=device_id,
                sample_rate=fallback_sample_rate,
            )
            self._stream_sample_rate = fallback_sample_rate
            logger.warning(self._last_error)

        runtime_config = replace(self.config, sample_rate=self._stream_sample_rate)
        self.segmenter = SpeechSegmenter(runtime_config)
        stream = self._audio_stream
        if stream is None:
            raise RuntimeError("Speech input stream failed to initialize.")
        stream.start()

        self._running = True
        self._task = asyncio.create_task(self._worker())
        logger.info(
            "Speech source started stream_sample_rate=%s frame_size=%s",
            self._stream_sample_rate,
            self.segmenter.config.frame_size,
        )

    async def stop(self) -> None:
        self._running = False
        logger.debug("Speech source stop requested")
        await self._emit_speaking_state(False, force=True)

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        stream = self._audio_stream
        self._audio_stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        logger.info("Speech source stopped")

    async def scan_once(self, *, emit: bool = True) -> PerceptionEvent | None:
        try:
            frame = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
        return await self._consume_frame(frame, emit=emit)

    def status(self) -> PerceptionStatus:
        return {
            "source": self.source_name,
            "running": self.is_running,
            "last_error": self.last_error,
            "last_observation": self.last_observation,
            "input_device_id": self._active_device_id,
            "input_device_name": self._active_device_name,
            "stream_sample_rate": self._stream_sample_rate,
            "transcribe_sample_rate": self._transcribe_sample_rate,
            "dropped_frames": self._dropped_frames,
        }

    async def _emit_speaking_state(
        self, speaking: bool, *, force: bool = False
    ) -> None:
        if not force and speaking == self._last_speaking_state:
            return

        self._last_speaking_state = speaking
        callback = self.speaking_state_callback
        if callback is None:
            return

        try:
            result = callback(speaking)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning("Speech speaking-state callback failed: %s", exc)

    async def _emit_transcription_state(
        self, active: bool, duration_sec: float
    ) -> None:
        callback = self.transcription_state_callback
        if callback is None:
            return

        try:
            result = callback(active, duration_sec)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning("Speech transcription-state callback failed: %s", exc)

    async def _worker(self) -> None:
        while self._running:
            frame = await self._queue.get()
            try:
                await self._consume_frame(frame, emit=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("Speech worker frame processing failed: %s", exc)

    async def _consume_frame(
        self,
        frame: np.ndarray,
        *,
        emit: bool,
    ) -> PerceptionEvent | None:
        utterance = self.segmenter.push(frame)
        speaking_now = bool(self.segmenter.is_speaking)
        dbfs = SpeechSegmenter._dbfs(frame)
        self._last_observation = {
            "timestamp": time.time(),
            "dbfs": round(dbfs, 2),
            "noise_floor_dbfs": round(self.segmenter.noise_floor_dbfs, 2),
            "speaking": speaking_now,
            "input_device_name": self._active_device_name,
        }

        utterance_duration_sec = 0.0
        if utterance is not None:
            utterance_duration_sec = float(utterance.shape[0]) / max(
                1, self._stream_sample_rate
            )
            await self._emit_transcription_state(True, utterance_duration_sec)

        await self._emit_speaking_state(speaking_now)

        if utterance is None:
            return None

        transcriber = self._transcriber
        if transcriber is None:
            await self._emit_transcription_state(False, utterance_duration_sec)
            return None

        try:
            transcribe_audio = self._resample_audio_if_needed(
                utterance,
                source_sample_rate=self._stream_sample_rate,
                target_sample_rate=self._transcribe_sample_rate,
            )
            raw_transcription = await asyncio.to_thread(
                transcriber.transcribe, transcribe_audio
            )
        finally:
            await self._emit_transcription_state(False, utterance_duration_sec)

        transcription = self._normalize_transcription(raw_transcription)
        cleaned = transcription.text.strip()
        if not cleaned:
            return None

        logger.debug(
            "Speech utterance finalized chars=%s duration=%.3fs language=%s",
            len(cleaned),
            utterance_duration_sec,
            transcription.language,
        )

        event: PerceptionEvent = {
            "type": self.config.event_type,
            "origin": self.config.origin,
            "description": cleaned,
            "amplitude": 1.0,
            "speech_duration_sec": round(utterance_duration_sec, 3),
            "transcript": cleaned,
            "input_device_name": self._active_device_name,
        }
        if transcription.language:
            event["speech_language"] = transcription.language
        if transcription.language_confidence is not None:
            event["speech_language_confidence"] = round(
                float(transcription.language_confidence), 4
            )

        if emit:
            callback_result = self.event_callback(event)
            if inspect.isawaitable(callback_result):
                await callback_result

        self._last_observation = {
            **(self._last_observation or {}),
            "last_transcript": cleaned,
            "last_transcript_sec": event["speech_duration_sec"],
            "last_speech_language": transcription.language,
        }
        return event

    @staticmethod
    def _normalize_transcription(raw: SpeechTranscription | str) -> SpeechTranscription:
        if isinstance(raw, SpeechTranscription):
            return raw
        return SpeechTranscription(text=str(raw or ""))

    def _audio_callback(
        self,
        indata: np.ndarray,
        _frames: int,
        _time_info: Any,
        _status: Any,
    ) -> None:
        loop = self._loop
        if loop is None:
            return

        mono = np.asarray(indata, dtype=np.float32).reshape(-1)
        frame = mono.copy()

        def _enqueue() -> None:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._dropped_frames += 1
                if self._dropped_frames % 50 == 0:
                    logger.warning(
                        "Speech frame queue saturated dropped_frames=%s",
                        self._dropped_frames,
                    )
            self._queue.put_nowait(frame)

        loop.call_soon_threadsafe(_enqueue)

    def _resolve_input_device(
        self, sounddevice_module: Any
    ) -> tuple[int | None, str, float | None]:
        configured = self.config.input_device.strip()
        devices = list(sounddevice_module.query_devices())

        if configured:
            selected = self._select_configured_device(devices, configured)
            if selected is None:
                raise RuntimeError(
                    f"Configured speech input device not found: {configured}"
                )
            idx, info = selected
            return (
                idx,
                str(info.get("name", f"device-{idx}")),
                float(info.get("default_samplerate", 0.0) or 0.0),
            )

        try:
            default_info = sounddevice_module.query_devices(kind="input")
        except Exception:
            default_info = None

        if isinstance(default_info, dict):
            default_name = str(default_info.get("name", "default-input"))
            return (
                None,
                default_name,
                float(default_info.get("default_samplerate", 0.0) or 0.0),
            )

        for idx, info in enumerate(devices):
            try:
                max_channels = int(info.get("max_input_channels", 0))
            except (TypeError, ValueError):
                max_channels = 0
            if max_channels > 0:
                return (
                    idx,
                    str(info.get("name", f"device-{idx}")),
                    float(info.get("default_samplerate", 0.0) or 0.0),
                )

        raise RuntimeError(
            "No input microphone device available for speech perception."
        )

    @staticmethod
    def _select_configured_device(
        devices: list[dict[str, Any]],
        configured: str,
    ) -> tuple[int, dict[str, Any]] | None:
        normalized = configured.strip()
        if normalized.lstrip("-").isdigit():
            idx = int(normalized)
            if 0 <= idx < len(devices):
                info = devices[idx]
                if int(info.get("max_input_channels", 0) or 0) > 0:
                    return idx, info

        lowered = normalized.lower()
        for idx, info in enumerate(devices):
            name = str(info.get("name", ""))
            if (
                lowered in name.lower()
                and int(info.get("max_input_channels", 0) or 0) > 0
            ):
                return idx, info

        return None

    def _open_stream(
        self,
        sounddevice_module: Any,
        *,
        device_id: int | None,
        sample_rate: int,
    ) -> Any:
        runtime_config = replace(self.config, sample_rate=max(8000, int(sample_rate)))
        return sounddevice_module.InputStream(
            samplerate=runtime_config.sample_rate,
            channels=runtime_config.channels,
            dtype="float32",
            blocksize=runtime_config.frame_size,
            device=device_id,
            callback=self._audio_callback,
        )

    @staticmethod
    def _is_invalid_sample_rate_error(exc: Exception) -> bool:
        return "Invalid sample rate" in str(exc)

    @staticmethod
    def _resample_audio_if_needed(
        audio: np.ndarray,
        *,
        source_sample_rate: int,
        target_sample_rate: int,
    ) -> np.ndarray:
        src = max(1, int(source_sample_rate))
        dst = max(1, int(target_sample_rate))
        if src == dst:
            return audio.astype(np.float32, copy=False)

        if audio.size <= 1:
            return audio.astype(np.float32, copy=False)

        src_len = int(audio.shape[0])
        dst_len = max(1, int(round(src_len * (dst / src))))
        src_x = np.linspace(0.0, 1.0, num=src_len, endpoint=False)
        dst_x = np.linspace(0.0, 1.0, num=dst_len, endpoint=False)
        resampled = np.interp(dst_x, src_x, audio).astype(np.float32)
        return resampled
