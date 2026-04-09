from __future__ import annotations

import math
from typing import Iterable


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def l2_distance(a: Iterable[float], b: Iterable[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    num = 0.0
    denom_a = 0.0
    denom_b = 0.0
    for x, y in zip(a, b):
        num += x * y
        denom_a += x * x
        denom_b += y * y
    denom = math.sqrt(denom_a) * math.sqrt(denom_b)
    if denom == 0.0:
        return 0.0
    return num / denom


def exp_decay(delta_seconds: float, tau_seconds: float) -> float:
    if tau_seconds <= 0:
        return 0.0
    return math.exp(-delta_seconds / tau_seconds)
