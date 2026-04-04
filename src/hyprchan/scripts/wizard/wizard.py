# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable
from typing import Any, Callable, Protocol, cast

from rich.console import Console

from .components import Component
from .context import DynamicStepRequest, WizardContext
from .models import StepState, StepStatus, WizardResult, WizardStatus
from .prompts import (
    PromptDriver,
    QuestionaryPromptDriver,
    resolve_component_and_type,
)
from .renderer import RichWizardRenderer, WizardDisplayConfig
from .step import StepDefinition, collect_step_methods


class WizardRenderer(Protocol):
    console: Any

    def start(self, config: WizardDisplayConfig, steps: list[StepState]) -> None: ...
    def stop(self) -> None: ...
    def refresh(self, config: WizardDisplayConfig, steps: list[StepState]) -> None: ...
    def print_success(self, message: str) -> None: ...


class Wizard:
    title: str = "Hyprchan Setup"
    subtitle: str = ""
    banner: str | None = None

    def __init__(
        self,
        *,
        renderer: WizardRenderer | None = None,
        prompt_driver: PromptDriver | None = None,
    ) -> None:
        self.renderer = renderer or RichWizardRenderer()
        self.console: Console = self.renderer.console
        self.prompt_driver = prompt_driver or QuestionaryPromptDriver(self.console)

        self.context = WizardContext(title=self.title)
        self.context.bind_step_adder(self._add_dynamic_step)
        self.context.bind_prompt_handler(self._ask_component_from_context)

        self._steps: list[StepDefinition] = collect_step_methods(self)
        self._step_states: list[StepState] = [
            StepState(key=step.key, name=step.name, description=step.description)
            for step in self._steps
        ]
        self._current_step_index: int = -1

    async def run(self) -> WizardResult:
        display = WizardDisplayConfig(
            title=self.title,
            subtitle=self.subtitle,
            banner=self.banner,
        )
        self.renderer.start(display, self._step_states)

        try:
            index = 0
            while index < len(self._steps):
                self._current_step_index = index
                step = self._steps[index]
                state = self._step_states[index]
                state.status = StepStatus.RUNNING
                state.error = None
                self.context.current_step_key = step.key

                self.renderer.refresh(display, self._step_states)
                outcome = await self._execute_step(step, state, display)
                if outcome == "abort":
                    return WizardResult(
                        status=WizardStatus.ABORTED,
                        state=dict(self.context.state),
                        failed_step=step.key,
                        error=state.error,
                    )

                index += 1

            self.renderer.refresh(display, self._step_states)
            self.renderer.print_success("Setup flow completed.")
            return WizardResult(status=WizardStatus.COMPLETED, state=dict(self.context.state))
        finally:
            self.renderer.stop()

    def run_sync(self) -> WizardResult:
        display = WizardDisplayConfig(
            title=self.title,
            subtitle=self.subtitle,
            banner=self.banner,
        )
        self.renderer.start(display, self._step_states)

        try:
            index = 0
            while index < len(self._steps):
                self._current_step_index = index
                step = self._steps[index]
                state = self._step_states[index]
                state.status = StepStatus.RUNNING
                state.error = None
                self.context.current_step_key = step.key

                self.renderer.refresh(display, self._step_states)
                outcome = self._execute_step_sync(step, state, display)
                if outcome == "abort":
                    return WizardResult(
                        status=WizardStatus.ABORTED,
                        state=dict(self.context.state),
                        failed_step=step.key,
                        error=state.error,
                    )
                index += 1

            self.renderer.refresh(display, self._step_states)
            self.renderer.print_success("Setup flow completed.")
            return WizardResult(status=WizardStatus.COMPLETED, state=dict(self.context.state))
        finally:
            self.renderer.stop()

    async def _execute_step(
        self,
        step: StepDefinition,
        state: StepState,
        display: WizardDisplayConfig,
    ) -> str:
        while True:
            try:
                kwargs = self._resolve_step_kwargs(step.handler)
                result = step.handler(**kwargs)
                resolved = await self._resolve_step_result(result, display)
                if resolved is not None:
                    self.context.state[step.key] = resolved
                state.status = StepStatus.COMPLETED
                state.error = None
                self.renderer.refresh(display, self._step_states)
                return "ok"
            except Exception as exc:  # noqa: BLE001
                state.status = StepStatus.FAILED
                state.error = str(exc)
                self.renderer.refresh(display, self._step_states)

                action = self._ask_failure_action(step.name, str(exc))
                if action == "retry":
                    state.status = StepStatus.RUNNING
                    state.error = None
                    self.renderer.refresh(display, self._step_states)
                    continue
                if action == "skip":
                    state.status = StepStatus.SKIPPED
                    self.renderer.refresh(display, self._step_states)
                    return "skip"
                return "abort"

    def _execute_step_sync(
        self,
        step: StepDefinition,
        state: StepState,
        display: WizardDisplayConfig,
    ) -> str:
        while True:
            try:
                kwargs = self._resolve_step_kwargs(step.handler)
                result = step.handler(**kwargs)
                resolved = self._resolve_step_result_sync(result)
                if resolved is not None:
                    self.context.state[step.key] = resolved
                state.status = StepStatus.COMPLETED
                state.error = None
                self.renderer.refresh(display, self._step_states)
                return "ok"
            except Exception as exc:  # noqa: BLE001
                state.status = StepStatus.FAILED
                state.error = str(exc)
                self.renderer.refresh(display, self._step_states)

                action = self._ask_failure_action(step.name, str(exc))
                if action == "retry":
                    state.status = StepStatus.RUNNING
                    state.error = None
                    self.renderer.refresh(display, self._step_states)
                    continue
                if action == "skip":
                    state.status = StepStatus.SKIPPED
                    self.renderer.refresh(display, self._step_states)
                    return "skip"
                return "abort"

    def _resolve_step_kwargs(self, handler: Any) -> dict[str, Any]:
        signature = inspect.signature(handler, eval_str=True)
        kwargs: dict[str, Any] = {}

        for name, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            if name == "ctx":
                kwargs[name] = self.context
                continue

            expected_type, component = resolve_component_and_type(
                param.annotation,
                param.default,
            )

            while True:
                try:
                    value = self._ask_component(
                        param_name=name,
                        component=component,
                        expected_type=expected_type,
                        default=param.default,
                    )
                    kwargs[name] = value
                    break
                except ValueError as exc:
                    self.console.print(f"[red]{exc}[/red]")

        return kwargs

    async def _resolve_step_result(
        self,
        result: object,
        display: WizardDisplayConfig,
    ) -> Any:
        if inspect.isawaitable(result):
            task = asyncio.ensure_future(result)
            while not task.done():
                self.renderer.refresh(display, self._step_states)
                await asyncio.sleep(0.08)
            return await task
        return result

    def _resolve_step_result_sync(self, result: object) -> Any:
        if inspect.isawaitable(result):
            return asyncio.run(self._await_value(cast(Awaitable[Any], result)))
        return result

    async def _await_value(self, awaitable: Awaitable[Any]) -> Any:
        return await awaitable

    def _add_dynamic_step(self, request: DynamicStepRequest) -> None:
        insert_at = max(0, self._current_step_index + 1)
        step_key = self._unique_step_key(request.key)
        step = StepDefinition(
            key=step_key,
            name=request.name,
            description=request.description,
            handler=request.handler,
        )
        state = StepState(key=step.key, name=step.name, description=step.description)

        self._steps.insert(insert_at, step)
        self._step_states.insert(insert_at, state)

    def _unique_step_key(self, requested_key: str) -> str:
        existing = {step.key for step in self._steps}
        if requested_key not in existing:
            return requested_key
        suffix = 2
        while f"{requested_key}_{suffix}" in existing:
            suffix += 1
        return f"{requested_key}_{suffix}"

    def _ask_component_from_context(
        self,
        name: str,
        component: Component,
        expected_type: Any,
        default: Any,
    ) -> Any:
        while True:
            try:
                return self._ask_component(
                    param_name=name,
                    component=component,
                    expected_type=expected_type,
                    default=default,
                )
            except ValueError as exc:
                self.console.print(f"[red]{exc}[/red]")

    def _ask_component(
        self,
        *,
        param_name: str,
        component: Component,
        expected_type: Any,
        default: Any,
    ) -> Any:
        return self._call_prompt(
            lambda: self.prompt_driver.ask_component(
                param_name=param_name,
                component=component,
                expected_type=expected_type,
                default=default,
            )
        )

    def _ask_failure_action(self, step_name: str, error: str) -> str:
        result = self._call_prompt(lambda: self.prompt_driver.ask_failure_action(step_name, error))
        return str(result)

    def _call_prompt(self, fn: Callable[[], Any]) -> Any:
        try:
            loop = asyncio.get_running_loop()
            running_loop = loop.is_running()
        except RuntimeError:
            running_loop = False

        if not running_loop:
            return fn()

        value: Any = None
        captured_error: Exception | None = None

        def _runner() -> None:
            nonlocal value, captured_error
            try:
                value = fn()
            except Exception as exc:  # noqa: BLE001
                captured_error = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()

        if captured_error is not None:
            raise captured_error
        return value


__all__ = ["Wizard"]
