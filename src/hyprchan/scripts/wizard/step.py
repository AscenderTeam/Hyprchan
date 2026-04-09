from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

StepHandler = Callable[..., Any]


@dataclass(slots=True, frozen=True)
class StepMetadata:
    name: str
    description: str


@dataclass(slots=True, frozen=True)
class StepDefinition:
    key: str
    name: str
    description: str
    handler: StepHandler


_STEP_META_ATTR = "__wizard_step_meta__"


def step(name: str, description: str = "") -> Callable[[StepHandler], StepHandler]:
    def decorator(func: StepHandler) -> StepHandler:
        setattr(func, _STEP_META_ATTR, StepMetadata(name=name, description=description))
        return func

    return decorator


def get_step_metadata(handler: StepHandler) -> StepMetadata | None:
    meta = getattr(handler, _STEP_META_ATTR, None)
    if isinstance(meta, StepMetadata):
        return meta
    return None


def collect_step_methods(owner: object) -> list[StepDefinition]:
    """Collect @step methods preserving class definition order."""

    by_key: dict[str, StepDefinition] = {}
    ordered_keys: list[str] = []

    for cls in reversed(type(owner).__mro__):
        namespace = vars(cls)
        for key, value in namespace.items():
            if not callable(value):
                continue
            bound = getattr(owner, key, None)
            if not callable(bound):
                continue
            meta = get_step_metadata(bound)
            if meta is None:
                continue

            definition = StepDefinition(
                key=key,
                name=meta.name,
                description=meta.description,
                handler=bound,
            )
            if key not in by_key:
                ordered_keys.append(key)
            by_key[key] = definition

    return [by_key[key] for key in ordered_keys]


__all__ = [
    "StepDefinition",
    "StepHandler",
    "StepMetadata",
    "collect_step_methods",
    "get_step_metadata",
    "step",
]
