from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass


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

        if magnitude < 0.1:
            decay_rate = 2.0 / max(0.001, decay_tau)
        else:
            decay_rate = 1.0 / max(0.001, decay_tau)

        self.energy *= math.exp(-dt * decay_rate)

        sensitivity_mult = 1.0 + (self.energy / 1000.0) * 0.5
        self.energy += magnitude * boost * sensitivity_mult

        if self.energy > 240.0 and not self.refractory:
            if now - self.last_orgasm_at > 2.0:
                self.orgasm_count += 1
                self.last_orgasm_at = now
                self.energy = max(180.0, self.energy * 0.7)
                self.refractory = True

        if self.refractory and now - self.last_orgasm_at > random.uniform(1.0, 3.0):
            self.refractory = False
