from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable


@dataclass(frozen=True)
class _ListenerSpec:
    callback: Callable[..., Any]
    positional_count: int
    has_varargs: bool
    use_raw_payload: bool


def analyze_listener(callback: Callable[..., Any]) -> _ListenerSpec:
    signature = inspect.signature(callback)
    params = list(signature.parameters.values())
    positional_params = [
        param
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params)
    positional_count = len(positional_params)
    use_raw_payload = positional_count == 1 and not has_varargs
    return _ListenerSpec(
        callback=callback,
        positional_count=positional_count,
        has_varargs=has_varargs,
        use_raw_payload=use_raw_payload,
    )


def build_listener_args(
    listener: _ListenerSpec,
    payload: str | None,
    payload_parts: list[str],
) -> list[Any]:
    if listener.positional_count == 0 and not listener.has_varargs:
        return []
    if listener.use_raw_payload:
        return [payload]
    
    args = list(payload_parts)
    if not listener.has_varargs and len(args) > listener.positional_count:
        args = args[:listener.positional_count]
    return args


async def dispatch_event(
    listeners: dict[str, list[_ListenerSpec]],
    event: str,
    payload: str | None,
) -> None:
    event_listeners = listeners.get(event, [])
    if not event_listeners:
        return
    
    payload_parts = payload.split(",") if payload else []
    for listener in event_listeners:
        args = build_listener_args(listener, payload, payload_parts)
        result = listener.callback(*args)
        if inspect.isawaitable(result):
            await result
