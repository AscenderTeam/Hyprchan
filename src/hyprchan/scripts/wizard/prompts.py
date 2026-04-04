# pyright: reportMissingImports=false

from __future__ import annotations

import inspect
from typing import Annotated, Any, Protocol, get_args, get_origin

import questionary
from questionary import Choice as QChoice
from questionary import Style as QStyle
from rich.console import Console
from rich.prompt import Confirm as RichConfirm
from rich.prompt import Prompt

from .components import Choice, Component, Confirm, Input, SecretInput, UNDEFINED


class PromptDriver(Protocol):
    def ask_component(
        self,
        param_name: str,
        component: Component,
        expected_type: Any,
        default: Any,
    ) -> Any: ...

    def ask_failure_action(self, step_name: str, error: str) -> str: ...


class RichPromptDriver:
    def __init__(self, console: Console) -> None:
        self.console = console

    def ask_component(
        self,
        param_name: str,
        component: Component,
        expected_type: Any,
        default: Any,
    ) -> Any:
        if isinstance(component, Choice):
            return self._ask_choice(param_name, component, expected_type)
        if isinstance(component, Confirm):
            return RichConfirm.ask(
                param_name.replace("_", " ").capitalize(),
                console=self.console,
                default=component.default,
            )
        if isinstance(component, SecretInput):
            return self._ask_input(
                param_name,
                component.placeholder,
                required=component.required,
                default=component.default,
                expected_type=expected_type,
                password=True,
            )

        input_component = component if isinstance(component, Input) else Input()
        resolved_default = input_component.default
        if resolved_default is UNDEFINED and default is not inspect._empty:
            resolved_default = default
        return self._ask_input(
            param_name,
            input_component.placeholder,
            required=input_component.required,
            default=resolved_default,
            expected_type=expected_type,
            password=False,
        )

    def ask_failure_action(self, step_name: str, error: str) -> str:
        self.console.print(
            f"[bold red]Step failed:[/bold red] {step_name} -> {error}",
        )
        return Prompt.ask(
            "Choose action",
            choices=["retry", "skip", "abort"],
            default="abort",
            console=self.console,
        )

    def _ask_choice(self, param_name: str, component: Choice, expected_type: Any) -> Any:
        title = param_name.replace("_", " ").capitalize()
        if component.multiple:
            raw_value = Prompt.ask(
                f"{title} (comma separated)",
                default=component.placeholder or None,
                console=self.console,
            )
            raw = str(raw_value or "").strip()
            selected = [item.strip() for item in raw.split(",") if item.strip()]
            if not selected:
                raise ValueError(f"{param_name} requires at least one choice")
            invalid = [item for item in selected if item not in component.options]
            if invalid:
                raise ValueError(
                    f"invalid choice(s): {', '.join(invalid)}; allowed: {', '.join(component.options)}"
                )
            return selected

        chosen_value = Prompt.ask(
            title,
            choices=component.options,
            default=component.options[0] if component.options else None,
            console=self.console,
        )
        chosen = str(chosen_value or "").strip()
        if not chosen:
            if component.options:
                chosen = component.options[0]
            else:
                raise ValueError(f"{param_name} has no available choices")

        if _expects_list(expected_type):
            return [chosen]
        return chosen

    def _ask_input(
        self,
        param_name: str,
        placeholder: str,
        *,
        required: bool,
        default: Any,
        expected_type: Any,
        password: bool,
    ) -> Any:
        title = param_name.replace("_", " ").capitalize()
        prompt_text = title if not placeholder else f"{title} ({placeholder})"
        provided_default = None if default is UNDEFINED else str(default)
        raw_value = Prompt.ask(
            prompt_text,
            default=provided_default,
            console=self.console,
            password=password,
        )
        raw = str(raw_value or "")
        if required and not raw.strip():
            raise ValueError(f"{param_name} is required")
        if not raw.strip() and default is not UNDEFINED:
            return _coerce_value(default, expected_type)
        return _coerce_value(raw, expected_type)


class QuestionaryPromptDriver:
    """Prompt driver with popup-style controls (select + checkbox + input)."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._style = QStyle(
            [
                ("qmark", "fg:#6aa6ff bold"),
                ("question", "bold"),
                ("answer", "fg:#d7e8ff"),
                ("pointer", "fg:#6aa6ff bold"),
                ("highlighted", "fg:#6aa6ff bold"),
                ("selected", "fg:#6aa6ff"),
                ("separator", "fg:#617487"),
                ("instruction", "fg:#8ea1b3"),
                ("text", ""),
            ]
        )

    def ask_component(
        self,
        param_name: str,
        component: Component,
        expected_type: Any,
        default: Any,
    ) -> Any:
        if isinstance(component, Choice):
            return self._ask_choice(param_name, component, expected_type)
        if isinstance(component, Confirm):
            value = questionary.confirm(
                _prompt_title(param_name),
                default=component.default,
                style=self._style,
            ).ask()
            return bool(value)
        if isinstance(component, SecretInput):
            return self._ask_input(
                param_name,
                placeholder=component.placeholder,
                required=component.required,
                default=component.default,
                expected_type=expected_type,
                password=True,
            )

        input_component = component if isinstance(component, Input) else Input()
        resolved_default = input_component.default
        if resolved_default is UNDEFINED and default is not inspect._empty:
            resolved_default = default
        return self._ask_input(
            param_name,
            placeholder=input_component.placeholder,
            required=input_component.required,
            default=resolved_default,
            expected_type=expected_type,
            password=False,
        )

    def ask_failure_action(self, step_name: str, error: str) -> str:
        self.console.print(f"[bold red]Step failed:[/bold red] {step_name} -> {error}")
        choice = questionary.select(
            "Choose action",
            choices=[
                QChoice("Retry step", value="retry"),
                QChoice("Skip step", value="skip"),
                QChoice("Abort wizard", value="abort"),
            ],
            style=self._style,
            qmark=">",
        ).ask()
        return str(choice or "abort")

    def _ask_choice(self, param_name: str, component: Choice, expected_type: Any) -> Any:
        title = _prompt_title(param_name)
        if not component.options:
            raise ValueError(f"{param_name} has no available choices")

        if component.multiple:
            values = questionary.checkbox(
                title,
                choices=[QChoice(option, value=option) for option in component.options],
                style=self._style,
                qmark=">",
                instruction="Space to toggle, Enter to submit",
            ).ask()
            selected = [str(item) for item in (values or [])]
            if not selected:
                raise ValueError(f"{param_name} requires at least one choice")
            return selected

        selected = questionary.select(
            title,
            choices=[QChoice(option, value=option) for option in component.options],
            style=self._style,
            qmark=">",
        ).ask()
        if not selected:
            if component.options:
                selected = component.options[0]
            else:
                raise ValueError(f"{param_name} has no available choices")

        if _expects_list(expected_type):
            return [str(selected)]
        return str(selected)

    def _ask_input(
        self,
        param_name: str,
        *,
        placeholder: str,
        required: bool,
        default: Any,
        expected_type: Any,
        password: bool,
    ) -> Any:
        prompt_text = _prompt_title(param_name)
        if placeholder:
            prompt_text = f"{prompt_text} ({placeholder})"
        default_value = "" if default is UNDEFINED else str(default)

        if password:
            raw = questionary.password(
                prompt_text,
                default=default_value if default is not UNDEFINED else "",
                style=self._style,
                qmark=">",
            ).ask()
        else:
            raw = questionary.text(
                prompt_text,
                default=default_value if default is not UNDEFINED else "",
                style=self._style,
                qmark=">",
            ).ask()

        value = str(raw or "")
        if required and not value.strip():
            raise ValueError(f"{param_name} is required")
        if not value.strip() and default is not UNDEFINED:
            return _coerce_value(default, expected_type)
        return _coerce_value(value, expected_type)


def resolve_component_and_type(
    annotation: Any,
    parameter_default: Any,
) -> tuple[Any, Component]:
    default_component = Input(required=parameter_default is inspect._empty)

    if annotation is inspect._empty:
        return str, default_component

    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if not args:
            return str, default_component
        expected_type = args[0]
        for meta in args[1:]:
            if isinstance(meta, (Choice, Input, Confirm, SecretInput)):
                return expected_type, meta
        return expected_type, default_component

    return annotation, default_component


def _expects_list(expected_type: Any) -> bool:
    origin = get_origin(expected_type)
    if origin is list:
        return True
    return expected_type is list


def _coerce_value(value: Any, expected_type: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(expected_type)
    if expected_type in {str, inspect._empty, Any}:
        return str(value)
    if expected_type is int:
        return int(value)
    if expected_type is float:
        return float(value)
    if expected_type is bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        return normalized in {"1", "true", "yes", "on"}
    if origin is list:
        if isinstance(value, list):
            return value
        return [item.strip() for item in str(value).split(",") if item.strip()]
    return value


def _prompt_title(param_name: str) -> str:
    return param_name.replace("_", " ").capitalize()


__all__ = [
    "PromptDriver",
    "QuestionaryPromptDriver",
    "RichPromptDriver",
    "resolve_component_and_type",
]
