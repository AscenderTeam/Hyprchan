from __future__ import annotations

import asyncio
import importlib
import logging
import re
import wave
from io import BytesIO
from typing import TYPE_CHECKING

import numpy as np

from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hyprvoice.generator import VoiceGenerator

if TYPE_CHECKING:
    from hyprchan.config.personalization import VoiceConfig

logger = logging.getLogger(__name__)


def _resolve_sd_device(device: str | None):
    """Convert the YAML/env device value to a sounddevice-compatible device identifier."""
    if not device or device.strip().lower() in {"", "default", "none"}:
        return None
    try:
        return int(device)
    except ValueError:
        return device


def _load_generator(config: "VoiceConfig") -> VoiceGenerator | None:
    engine = config.engine.strip()
    module_path = f"hyprchan.core.hyprvoice.generators.{engine}"
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        logger.warning(
            "Voice generator module not found for engine %r: %s", engine, exc
        )
        return None

    for attr_name in dir(mod):
        obj = getattr(mod, attr_name)
        try:
            if (
                isinstance(obj, type)
                and issubclass(obj, VoiceGenerator)
                and obj is not VoiceGenerator
            ):
                kwargs: dict = {}
                if config.url is not None:
                    kwargs["url"] = config.url
                if config.token is not None:
                    kwargs["token"] = config.token
                return obj(**kwargs)
        except Exception:
            continue

    logger.warning("No VoiceGenerator subclass found in module %r", module_path)
    return None


def _decode_wav(buf: BytesIO) -> tuple[np.ndarray, int]:
    with wave.open(buf) as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
    dtype = dtype_map.get(sampwidth, np.int16)
    audio = np.frombuffer(raw, dtype=dtype)
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels)
    return audio, framerate


class VoiceManager:
    """
    Manages voice output for Hyprchan.

    - Instantiates the configured generator on ``setup()``.
    - ``speak()`` is a non-blocking fire-and-forget: audio generation and
      sounddevice playback run in a background asyncio task.
    - Speech is suppressed unless the kernel is in ``ACTIVE`` phase.
    - Only one utterance plays at a time; a new ``speak()`` cancels any
      in-progress playback.
    """

    def __init__(self, config: "VoiceConfig") -> None:
        self._config = config
        self._generator: VoiceGenerator | None = None
        self._speak_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Load the generator.  Call once after the event loop is running."""
        if not self._config.enabled:
            return
        self._generator = _load_generator(self._config)
        if self._generator is None:
            logger.warning(
                "Voice disabled: could not load generator for engine %r",
                self._config.engine,
            )

    async def teardown(self) -> None:
        """Cancel in-flight speech and stop sounddevice output."""
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()
            try:
                await self._speak_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._config.enabled and self._generator is not None

    def speak(self, text: str, *, phase: Phases) -> None:
        """
        Fire-and-forget: generate and play ``text`` if ``phase`` is ACTIVE.
        Cancels any currently playing utterance first.
        """
        if not self._config.enabled or self._generator is None:
            return
        if phase != Phases.ACTIVE:
            return

        text = self._prepare_text(text)
        if not text:
            return

        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()

        self._speak_task = asyncio.create_task(self._do_speak(text))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    _ROLEPLAY_RE = re.compile(r"\*[^*]+\*")

    def _strip_roleplay_markers(self, text: str) -> str:
        """Remove *action text* emote markers, e.g. '*sighs* Hello' → 'Hello'."""
        cleaned = self._ROLEPLAY_RE.sub("", text)
        # Collapse runs of whitespace left behind
        return " ".join(cleaned.split())

    def _prepare_text(self, text: str) -> str:
        if self._config.trim_quotes:
            text = self._strip_roleplay_markers(text)
        return text.strip()

    async def _do_speak(self, text: str) -> None:
        assert self._generator is not None
        try:
            buf = await self._generator.generate(text)
            await self._play_wav(buf)
        except asyncio.CancelledError:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.warning("Voice speak failed: %s", exc)

    async def _play_wav(self, buf: BytesIO) -> None:
        try:
            audio, framerate = _decode_wav(buf)
        except Exception as exc:
            logger.warning("Voice WAV decode failed: %s", exc)
            return

        device = _resolve_sd_device(self._config.device)

        def _blocking_play() -> None:
            import sounddevice as sd

            sd.stop()
            sd.play(audio, framerate, device=device)
            sd.wait()

        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, _blocking_play)
        try:
            await fut
        except asyncio.CancelledError:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.warning("Voice playback error: %s", exc)
