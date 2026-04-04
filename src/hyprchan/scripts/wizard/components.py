from __future__ import annotations

from dataclasses import dataclass
from typing import Final


class _Undefined:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNDEFINED"


UNDEFINED: Final = _Undefined()


@dataclass(slots=True, frozen=True)
class Choice:
    options: list[str]
    multiple: bool = False
    placeholder: str = ""


@dataclass(slots=True, frozen=True)
class Input:
    placeholder: str = ""
    required: bool = False
    default: object = UNDEFINED


@dataclass(slots=True, frozen=True)
class Confirm:
    default: bool = False


@dataclass(slots=True, frozen=True)
class SecretInput:
    placeholder: str = ""
    required: bool = True
    default: object = UNDEFINED


Component = Choice | Input | Confirm | SecretInput

__all__ = [
    "Choice",
    "Component",
    "Confirm",
    "Input",
    "SecretInput",
    "UNDEFINED",
]
