from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, TypedDict

from core.hypraios.constants import Phases

AiMode = Literal["passive", "active_user", "active_self"]
HookName = Literal[
    "on_ponder",
    "on_passive_enter",
    "on_passive_leave",
    "on_ai_inference",
    "on_ai_response",
]


class PonderPayload(TypedDict, total=False):
    phase: Phases
    idle_seconds: float
    next_passive_ponder_at: float
    pending_memory_units: float
    fatigue: float
    context_window_size: int
    inputs: list[dict[str, object]]
    trigger_reason: str
    can_run_now: bool
    skip: bool


class PassiveEnterPayload(TypedDict, total=False):
    prev_phase: Phases
    reason: str | None
    fatigue: float


class PassiveLeavePayload(TypedDict, total=False):
    next_phase: Phases
    reason: str | None
    fatigue: float


class AiInferencePayload(TypedDict, total=False):
    phase: Phases
    mode: AiMode
    inputs: list[dict[str, object]]
    inference_count: int
    model: str | None


class AiResponsePayload(TypedDict, total=False):
    phase: Phases
    mode: AiMode
    response: dict[str, object]
    latency_ms: float | None
    token_count: int | None


@dataclass(slots=True)
class HookResult:
    payload: dict[str, object] | None = None
    stop: bool = False


HookPayload = dict[str, object]
HookReturn = HookResult | dict[str, object] | None
HookFn = Callable[[HookPayload], HookReturn] | Callable[[HookPayload], object]
