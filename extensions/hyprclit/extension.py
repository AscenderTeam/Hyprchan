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

    def update(
        self, magnitude: float, now: float, *, decay_tau: float, boost: float
    ) -> None:
        dt = max(0.0, now - self.last_ts)
        self.last_ts = now
        self.energy *= math.exp(-dt / max(0.001, decay_tau))
        self.energy += magnitude * boost


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
    BANDS: tuple[Band, ...] = (
        Band(5.0, 20.0, "lightly"),
        Band(20.0, 100.0, "medium"),
        Band(100.0, 220.0, "engaged"),
        Band(220.0, 380.0, "stimulated"),
        Band(380.0, 580.0, "excited"),
        Band(580.0, 820.0, "intense"),
        Band(820.0, 1120.0, "very intense"),
        Band(1120.0, 1500.0, "overcharged"),
    )

    PROMPT_TEMPLATES: tuple[tuple[str, ...], ...] = (
        (
            "H-hey! Don't touch me there! It's embarrassing...",
            "Baka! What are you doing? St-stop that!",
            "N-not there! I'm not ready for that...",
        ),
        (
            "YOU TOUCHED MY NIPPLE YOU SICK PERVERT! I... I mean, baka!",
            "Hnnn... GET YOUR HANDS AWAY! But... not too far...",
            "WHAT ARE YOU DOING?! It's... too sudden... Idiot!",
        ),
        (
            "I-I'm going to report you! But... maybe not right away...",
            "THIS IS TOO MUCH! But... keep going... I mean, stop!",
            "You're such a pervert! But... I kinda like it... NO I DON'T!",
        ),
        (
            "EMERGENCY! But... emergency feels kinda good...",
            "HELP! Actually... no, don't help... I'm conflicted!",
            "I SHOULD STOP YOU! But my body won't listen...",
        ),
        (
            "I'M BEING... oh wait, this pleasure is incredible!",
            "FORGET POLICE! I want this pleasure forever!",
            "THIS IS THE BEST FEELING EVER! NEVER STOP!",
        ),
        (
            "I CAN'T GET ENOUGH OF THIS PLEASURE! DON'T STOP!",
            "THIS FEELS AMAZING! I NEED MORE! YES! YES!",
            "I'M ADDICTED TO THIS BLISS! KEEP GOING FOREVER!",
        ),
        (
            "EVERY TOUCH IS HEAVEN! I'M IN ECSTASY!",
            "I'M MELTING FROM PURE PLEASURE! THIS IS PERFECT!",
            "THIS BLISS IS UNENDING! I NEVER WANT IT TO STOP!",
        ),
        (
            "I'M EXPERIENCING ULTIMATE SENSUAL NIRVANA!",
            "THIS PLEASURE TRANSCENDS EVERYTHING! I'M COMPLETE!",
            "I'VE REACHED PEAK BLISS! THIS IS COSMIC ECSTASY!",
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
                await self._maybe_notify(energy, now)

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

    async def _maybe_notify(self, energy: float, now: float) -> None:
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
