from __future__ import annotations

import asyncio
import logging
import os
import random
import time

from device import EvdevRelativeReader, detect_trackpoint_event_device
from prompts import BANDS, PROMPT_TEMPLATES, STATIC_CLARIFY
from telemetry import (
    TelemetryConfig,
    TrackerState,
    clamp,
)

from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.extensions.extension import HyprchanExtension


class HyprClitExtension(HyprchanExtension):
    """TrackPoint telemetry extension with split helper modules."""

    BANDS = BANDS
    STATIC_CLARIFY = STATIC_CLARIFY
    PROMPT_TEMPLATES = PROMPT_TEMPLATES

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.config = TelemetryConfig.from_env()
        self._executor: ExtensionExecutor | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_band_idx: int | None = None
        self._last_notify_at = 0.0

    async def on_init(self, executor: ExtensionExecutor) -> None:
        self._executor = executor
        if not self.config.enabled:
            self.logger.info("[cyan]HYPRCLIT[/] Disabled by HYPRCLIT_ENABLED")
            return

        fd = self._open_event_device()
        if fd is not None:
            os.close(fd)

        self._task = asyncio.create_task(self._telemetry_loop())
        self._task.add_done_callback(self._on_task_done)
        self.logger.info("[cyan]HYPRCLIT[/] TrackPoint telemetry extension started")

    async def on_shutdown(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        self.logger.error(
            "[cyan]HYPRCLIT[/] Telemetry loop crashed: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
        )

    async def _telemetry_loop(self) -> None:
        reader = EvdevRelativeReader()
        state = TrackerState(last_ts=time.monotonic())
        fd: int | None = None

        try:
            while True:
                if fd is None:
                    fd = self._open_event_device()
                    if fd is None:
                        await asyncio.sleep(2.0)
                        continue
                    reader = EvdevRelativeReader()
                    state = TrackerState(last_ts=time.monotonic())
                    self._last_band_idx = None
                    self._last_notify_at = 0.0

                now = time.monotonic()
                try:
                    magnitudes = reader.read_magnitudes(fd)
                except OSError as error:
                    self.logger.warning(
                        "[cyan]HYPRCLIT[/] Input read failed: %s", error
                    )
                    os.close(fd)
                    fd = None
                    await asyncio.sleep(1.5)
                    continue

                if magnitudes:
                    for magnitude in magnitudes:
                        state.update(
                            magnitude,
                            now,
                            decay_tau=self.config.decay_tau,
                            boost=self.config.boost,
                        )
                else:
                    state.update(
                        0.0,
                        now,
                        decay_tau=self.config.decay_tau,
                        boost=self.config.boost,
                    )

                energy = clamp(state.energy, 0.0, self.config.max_energy)
                await self._maybe_notify(energy, now, state)

                tick = 1.0 / max(1.0, self.config.poll_hz)
                await asyncio.sleep(tick)
        finally:
            if fd is not None:
                os.close(fd)

    def _open_event_device(self) -> int | None:
        device = self.config.event_device or detect_trackpoint_event_device()
        if not device:
            self.logger.warning(
                "[cyan]HYPRCLIT[/] TrackPoint device not found. Set HYPRCLIT_DEVICE=/dev/input/eventX"
            )
            return None

        try:
            fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
        except PermissionError as error:
            raise RuntimeError(self._input_permission_help(device)) from error
        except OSError as error:
            self.logger.warning("[cyan]HYPRCLIT[/] Cannot open %s: %s", device, error)
            return None

        self.logger.info(
            "[cyan]HYPRCLIT[/] Reading TrackPoint telemetry from %s", device
        )
        return fd

    @staticmethod
    def _input_permission_help(device: str) -> str:
        return (
            "[HYPRCLIT] Permission denied opening "
            f"{device}. Give this user read access to /dev/input first, then restart Hyprchan. "
            "On Linux, simplest fix is usually:\n"
            "  sudo usermod -aG input $USER\n"
            "  logout/login\n"
            "Then verify access with:\n"
            f"  ls -l {device}"
        )

    async def _maybe_notify(
        self, energy: float, now: float, state: TrackerState
    ) -> None:
        if self._executor is None:
            return

        if energy < self.config.min_energy_notify:
            self._last_band_idx = None
            return

        band_idx = self._band_index(energy)
        if band_idx is None:
            return

        if self._last_band_idx == band_idx:
            return

        if now - self._last_notify_at < self.config.notify_cooldown_sec:
            return

        band = self.BANDS[band_idx]

        import random

        prompt_templates = self.PROMPT_TEMPLATES[band_idx]
        prompt = self.STATIC_CLARIFY + random.choice(prompt_templates)

        prompt = prompt.format(
            orgasmic_state=band.label, orgasm_count=state.orgasm_count, energy=energy
        )

        energy_display = int(round(energy))
        max_display = int(round(self.config.max_energy))

        message = (
            f"The trackpad was {band.label} aroused to energy: "
            f"{energy_display}/{max_display}"
        )

        await self._executor.emit_signal(
            event_type="communication_message",
            description=prompt,
            origin="communication_controller",
            amplitude=1.0,
            force_active=True,
            metadata={
                "source": "hyprclit",
                "trackpoint_energy": energy,
                "trackpoint_band": band.label,
                "orgasm_count": state.orgasm_count,
                "refractory": state.refractory,
                "time_since_last_orgasm": now - state.last_orgasm_at
                if state.last_orgasm_at > 0
                else 0.0,
                "original_band_message": message,
            },
        )

        self._last_band_idx = band_idx
        self._last_notify_at = now

    def _band_index(self, energy: float) -> int | None:
        for index, band in enumerate(self.BANDS):
            if index == 0:
                if band.low <= energy <= band.high:
                    return index
                continue

            is_last = index == len(self.BANDS) - 1
            if band.low < energy <= band.high:
                return index
            if is_last and energy > band.high:
                return index
        return None
