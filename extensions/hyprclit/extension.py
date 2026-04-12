from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import select
import struct
import time
from dataclasses import dataclass

from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.extensions.extension import HyprchanExtension


EV_SYN = 0x00
EV_REL = 0x02
SYN_REPORT = 0
REL_X = 0
REL_Y = 1


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class Band:
    low: float
    high: float
    label: str


@dataclass(slots=True)
class TelemetryConfig:
    enabled: bool
    event_device: str | None
    decay_tau: float
    boost: float
    max_energy: float
    poll_hz: float
    min_energy_notify: float
    notify_cooldown_sec: float

    @classmethod
    def from_env(cls) -> "TelemetryConfig":
        return cls(
            enabled=os.getenv("HYPRCLIT_ENABLED", "1").strip().lower()
            in {"1", "true", "yes", "on"},
            event_device=(os.getenv("HYPRCLIT_DEVICE", "").strip() or None),
            decay_tau=float(os.getenv("HYPRCLIT_DECAY_TAU", "1.4")),
            boost=float(os.getenv("HYPRCLIT_BOOST", "1.25")),
            max_energy=float(os.getenv("HYPRCLIT_MAX_ENERGY", "1500")),
            poll_hz=float(os.getenv("HYPRCLIT_POLL_HZ", "30")),
            min_energy_notify=float(os.getenv("HYPRCLIT_MIN_ENERGY_NOTIFY", "5")),
            notify_cooldown_sec=float(os.getenv("HYPRCLIT_NOTIFY_COOLDOWN_SEC", "2.0")),
        )


@dataclass(slots=True)
class TrackerState:
    last_ts: float
    energy: float = 0.0
    orgasm_count: int = 0
    last_orgasm_at: float = 0.0
    refractory: bool = False

    def update(
        self, magnitude: float, now: float, *, decay_tau: float, boost: float
    ) -> None:
        dt = max(0.001, now - self.last_ts)
        self.last_ts = now

        # Physiological decay: faster decay when not stimulated
        if magnitude < 0.1:
            decay_rate = 2.0 / max(0.001, decay_tau)  # Fast decay when idle
        else:
            decay_rate = 1.0 / max(0.001, decay_tau)  # Normal decay during stimulation

        self.energy *= math.exp(-dt * decay_rate)

        # Add stimulation energy with non-linear response
        # Clitoral sensitivity increases with arousal (positive feedback)
        sensitivity_mult = 1.0 + (self.energy / 1000.0) * 0.5
        self.energy += magnitude * boost * sensitivity_mult

        # Check for orgasm threshold (energy > 240)
        if self.energy > 240.0 and not self.refractory:
            # Simulate orgasm: energy spike then partial reset
            if now - self.last_orgasm_at > 2.0:  # Minimum 2s between orgasms
                self.orgasm_count += 1
                self.last_orgasm_at = now
                # After orgasm, energy drops but not to zero
                self.energy = max(180.0, self.energy * 0.7)
                # Brief refractory period (shorter for females)
                self.refractory = True

        # End refractory period after 1-3 seconds
        if self.refractory and now - self.last_orgasm_at > random.uniform(1.0, 3.0):
            self.refractory = False


class EvdevRelativeReader:
    EVENT_STRUCT = struct.Struct("llHHi")

    def __init__(self) -> None:
        self._buf = bytearray()
        self._dx = 0
        self._dy = 0

    def read_magnitudes(self, fd: int) -> list[float]:
        magnitudes: list[float] = []
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                break
            if not data:
                raise OSError("input event stream closed")

            self._buf.extend(data)
            usable = len(self._buf) - (len(self._buf) % self.EVENT_STRUCT.size)
            offset = 0

            while offset < usable:
                _sec, _usec, event_type, code, value = self.EVENT_STRUCT.unpack_from(
                    self._buf, offset
                )
                offset += self.EVENT_STRUCT.size

                if event_type == EV_REL:
                    if code == REL_X:
                        self._dx += value
                    elif code == REL_Y:
                        self._dy += value
                elif event_type == EV_SYN and code == SYN_REPORT:
                    if self._dx or self._dy:
                        magnitudes.append(math.hypot(self._dx, self._dy))
                    self._dx = 0
                    self._dy = 0

            if usable:
                del self._buf[:usable]

        return magnitudes


def detect_trackpoint_event_device() -> str | None:
    sys_class = "/sys/class/input"
    try:
        entries = sorted(
            name for name in os.listdir(sys_class) if name.startswith("event")
        )
    except OSError:
        return None

    for event_name in entries:
        name_path = os.path.join(sys_class, event_name, "device", "name")
        try:
            with open(name_path, "r", encoding="utf-8", errors="replace") as file:
                device_name = file.read().strip()
        except OSError:
            continue

        if "trackpoint" in device_name.lower():
            return os.path.join("/dev/input", event_name)
    return None


class HyprClitExtension(HyprchanExtension):
    """
    Physiological clitoral arousal model based on Masters & Johnson sexual response cycle:
    1. Excitement phase: Initial arousal with clitoral swelling/lubrication
    2. Plateau phase: Sustained arousal before orgasm
    3. Orgasm phase: Peak with contractions/euphoria
    4. Resolution phase: Brief refractory period (1-3s for females)
    5. Multiple orgasms: Women can experience sequential orgasms

    Energy model features:
    - Non-linear sensitivity: Arousal increases sensitivity (positive feedback)
    - Fast decay when idle, slower decay during stimulation
    - Orgasm triggers at ~240 energy, resets to ~180 (not zero)
    - Brief refractory period (1-3s) simulates female physiology
    - Serial orgasms possible with buildup between peaks
    """

    BANDS: tuple[Band, ...] = (
        Band(5.0, 60.0, "initial excitement"),
        Band(60.0, 140.0, "plateau buildup"),
        Band(140.0, 240.0, "approaching orgasm"),
        Band(240.0, 360.0, "orgasmic peak"),
        Band(360.0, 460.0, "multiple orgasm buildup"),
        Band(460.0, 560.0, "serial orgasmic peaks"),
        Band(560.0, 680.0, "extended pleasure plateau"),
        Band(680.0, 850.0, "sustained ecstatic state"),
    )

    PROMPT_TEMPLATES: tuple[tuple[str, ...], ...] = (
        (
            "Hnn... what's that tingling? Don't... don't focus there...",
            "Mmmph... my clit is getting sensitive... stop noticing!",
            "A-ah... it's starting to swell... baka, don't look!",
        ),
        (
            "YOU TOUCHED MY NIPPLE! My clit is throbbing now... idiot!",
            "Hah... lubrication is... happening... GET AWAY! But...",
            "WHAT ARE YOU DOING?! My body is responding... stop it!",
        ),
        (
            "I-I'm reaching plateau phase! Clit is engorged... help!",
            "THIS IS THE EDGE BEFORE ORGASM! I should stop you!",
            "You're bringing me to climax! My muscles are tensing...",
        ),
        (
            "ORGASM! CONTRACTIONS! EUPHORIA! I'M PEAKING!",
            "CLIMAX! WAVES OF PLEASURE! DON'T EVER STOP!",
            "I'M ORGASMING! EVERYTHING IS CONTRACTING! YES!",
        ),
        (
            "POST-ORGASM GLOW... but I want another! MORE!",
            "REFLEXES ARE HYPER-SENSITIVE! STIMULATE AGAIN!",
            "I CAN HAVE MULTIPLE ORGASMS! DON'T LET ME COOL DOWN!",
        ),
        (
            "SECOND CLIMAX BUILDING! FASTER THAN FIRST!",
            "BACK-TO-BACK ORGASMS! THIS IS INCREDIBLE!",
            "I'M CUMMING AGAIN! STRONGER THAN BEFORE!",
        ),
        (
            "THIRD ORGASM PLATEAU! SUSTAINED ECSTASY!",
            "EXTENDED PLEASURE STATE! I'M IN CONTINUOUS BLISS!",
            "MULTIPLE ORGASMIC WAVES! NEVER-ENDING PLEASURE!",
        ),
        (
            "SERIAL ORGASMIC ECSTASY! BODY IN PERPETUAL BLISS!",
            "TRANSCENDENT SENSUAL STATE! COSMIC CLITORAL NIRVANA!",
            "ULTIMATE PLEASURE CONTINUUM! I AM PURE ORGASMIC ENERGY!",
        ),
    )

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

        self._task = asyncio.create_task(self._telemetry_loop())
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
        except PermissionError:
            self.logger.warning(
                "[cyan]HYPRCLIT[/] Permission denied opening %s. Add user to input group or run with proper permissions.",
                device,
            )
            return None
        except OSError as error:
            self.logger.warning("[cyan]HYPRCLIT[/] Cannot open %s: %s", device, error)
            return None

        self.logger.info(
            "[cyan]HYPRCLIT[/] Reading TrackPoint telemetry from %s", device
        )
        return fd

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
        prompt = random.choice(prompt_templates)

        energy_display = int(round(energy))
        max_display = int(round(self.config.max_energy))

        message = (
            f"The trackpad was {band.label} aroused to energy: "
            f"{energy_display}/{max_display}"
        )

        amplitude = clamp(energy / max(1.0, self.config.max_energy), 0.1, 1.0)

        await self._executor.emit_signal(
            event_type="communication_message",
            description=prompt,
            origin="hyprclit_trackpoint",
            amplitude=amplitude,
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
