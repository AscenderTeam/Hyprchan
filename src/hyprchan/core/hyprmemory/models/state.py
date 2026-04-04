from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryState:
    """Scalar state vector for memory modulation (f, v, e, a)."""

    f: float
    v: float
    e: float
    a: float

    def vector(self) -> list[float]:
        return [self.f, self.v, self.e, self.a]


@dataclass(slots=True)
class SemanticFeeling:
    """Deterministic semantic projection of internal scalar state."""

    label: str
    cognitive: str
    motivation: str
    stability: float
