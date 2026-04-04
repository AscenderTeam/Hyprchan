from __future__ import annotations

import time
from collections import deque
from typing import Any


def build_stm_payload(
    *,
    context_events: list[dict[str, Any]],
    event_log: list[dict[str, Any]],
    response_log: list[dict[str, Any]],
    last_inference: dict[str, Any] | None,
    last_inference_error: str | None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "saved_at": time.time(),
        "context_events": context_events,
        "event_log": event_log,
        "response_log": response_log,
        "last_inference": last_inference,
        "last_inference_error": last_inference_error,
    }


def parse_stm_payload(
    data: dict[str, Any],
    *,
    context_events_maxlen: int | None,
    event_log_maxlen: int | None,
    response_log_maxlen: int | None,
) -> dict[str, Any]:
    context_events = data.get("context_events")
    event_log = data.get("event_log")
    response_log = data.get("response_log")

    parsed = {
        "context_events": deque(
            [item for item in context_events if isinstance(item, dict)]
            if isinstance(context_events, list)
            else [],
            maxlen=context_events_maxlen,
        ),
        "event_log": deque(
            [item for item in event_log if isinstance(item, dict)]
            if isinstance(event_log, list)
            else [],
            maxlen=event_log_maxlen,
        ),
        "response_log": deque(
            [item for item in response_log if isinstance(item, dict)]
            if isinstance(response_log, list)
            else [],
            maxlen=response_log_maxlen,
        ),
        "last_inference": data.get("last_inference")
        if isinstance(data.get("last_inference"), dict)
        else None,
        "last_inference_error": data.get("last_inference_error")
        if isinstance(data.get("last_inference_error"), str)
        else None,
    }

    return parsed
