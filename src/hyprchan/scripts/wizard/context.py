from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, overload

from .components import (
    UNDEFINED,
    Choice,
    Component,
    Confirm,
    Input,
    SecretInput,
)


@dataclass(slots=True, frozen=True)
class DynamicStepRequest:
    key: str
    name: str
    description: str
    handler: Callable[..., Any]


@dataclass(slots=True)
class WizardContext:
    title: str
    state: dict[str, Any] = field(default_factory=dict)
    current_step_key: str | None = None

    _add_step_callback: Callable[[DynamicStepRequest], None] | None = field(
        default=None,
        repr=False,
    )
    _prompt_callback: Callable[[str, Component, Any, Any], Any] | None = field(
        default=None,
        repr=False,
    )

    def bind_step_adder(self, callback: Callable[[DynamicStepRequest], None]) -> None:
        self._add_step_callback = callback

    def bind_prompt_handler(
        self,
        callback: Callable[[str, Component, Any, Any], Any],
    ) -> None:
        self._prompt_callback = callback

    def add_step(
        self,
        handler: Callable[..., Any],
        *,
        name: str,
        description: str = "",
        key: str | None = None,
    ) -> None:
        if self._add_step_callback is None:
            raise RuntimeError("WizardContext is not bound to a running wizard")

        step_key = key or f"dynamic_{name.lower().replace(' ', '_')}"
        self._add_step_callback(
            DynamicStepRequest(
                key=step_key,
                name=name,
                description=description,
                handler=handler,
            )
        )

    def input(
        self,
        name: str,
        *,
        placeholder: str = "",
        required: bool = False,
        default: object = UNDEFINED,
    ) -> str:
        return str(
            self._ask(
                name=name,
                component=Input(
                    placeholder=placeholder,
                    required=required,
                    default=default,
                ),
                expected_type=str,
                default=default,
            )
        )

    @overload
    def choice(self, name: str, options: list[str]) -> str: ...

    @overload
    def choice(
        self, name: str, options: list[str], *, multiple: Literal[True] = True
    ) -> list[str]: ...

    def choice(
        self,
        name: str,
        options: list[str],
        *,
        multiple: bool = False,
    ) -> str | list[str]:
        value = self._ask(
            name=name,
            component=Choice(options=options, multiple=multiple),
            expected_type=list[str] if multiple else str,
            default=UNDEFINED,
        )
        if multiple:
            return [str(item) for item in value]
        return str(value)

    def confirm(self, name: str, *, default: bool = False) -> bool:
        return bool(
            self._ask(
                name=name,
                component=Confirm(default=default),
                expected_type=bool,
                default=default,
            )
        )

    def secret(
        self,
        name: str,
        *,
        placeholder: str = "",
        required: bool = True,
        default: object = UNDEFINED,
    ) -> str:
        return str(
            self._ask(
                name=name,
                component=SecretInput(
                    placeholder=placeholder,
                    required=required,
                    default=default,
                ),
                expected_type=str,
                default=default,
            )
        )

    def _ask(
        self,
        *,
        name: str,
        component: Component,
        expected_type: Any,
        default: Any,
    ) -> Any:
        if self._prompt_callback is None:
            raise RuntimeError("WizardContext is not bound to a prompt handler")
        return self._prompt_callback(name, component, expected_type, default)


__all__ = ["DynamicStepRequest", "WizardContext"]
