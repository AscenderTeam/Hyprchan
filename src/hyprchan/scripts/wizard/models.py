from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WizardStatus(str, Enum):
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass(slots=True)
class StepState:
    key: str
    name: str
    description: str
    status: StepStatus = StepStatus.PENDING
    error: str | None = None


@dataclass(slots=True)
class WizardResult:
    status: WizardStatus
    state: dict[str, Any] = field(default_factory=dict)
    failed_step: str | None = None
    error: str | None = None


__all__ = [
    "StepState",
    "StepStatus",
    "WizardResult",
    "WizardStatus",
]
