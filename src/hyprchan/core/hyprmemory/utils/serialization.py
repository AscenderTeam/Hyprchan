from __future__ import annotations

from datetime import datetime
from typing import Any

from hyprchan.core.hyprmemory.models import MemoryState, SemanticFeeling


def state_to_dict(state: MemoryState) -> dict[str, float]:
    return {"f": state.f, "v": state.v, "e": state.e, "a": state.a}


def state_from_dict(payload: dict[str, Any]) -> MemoryState:
    return MemoryState(
        f=float(payload.get("f", 0.0)),
        v=float(payload.get("v", 0.0)),
        e=float(payload.get("e", 0.0)),
        a=float(payload.get("a", 0.0)),
    )


def feeling_to_dict(feeling: SemanticFeeling) -> dict[str, Any]:
    return {
        "label": feeling.label,
        "cognitive": feeling.cognitive,
        "motivation": feeling.motivation,
        "stability": feeling.stability,
    }


def feeling_from_dict(payload: dict[str, Any]) -> SemanticFeeling:
    return SemanticFeeling(
        label=str(payload.get("label", "")),
        cognitive=str(payload.get("cognitive", "")),
        motivation=str(payload.get("motivation", "")),
        stability=float(payload.get("stability", 0.0)),
    )


def datetime_to_iso(ts: datetime) -> str:
    return ts.isoformat()


def datetime_from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
