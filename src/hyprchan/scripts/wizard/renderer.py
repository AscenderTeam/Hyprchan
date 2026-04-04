# pyright: reportMissingImports=false

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from .models import StepState, StepStatus


@dataclass(slots=True, frozen=True)
class WizardDisplayConfig:
    title: str
    subtitle: str = ""
    banner: str | None = None


_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_STATUS_MAP: dict[StepStatus, tuple[str, str]] = {
    StepStatus.COMPLETED: ("✓", "bold green"),
    StepStatus.FAILED: ("✗", "bold red"),
    StepStatus.SKIPPED: ("›", "bold yellow"),
    StepStatus.PENDING: ("○", "dim"),
}


class RichWizardRenderer:
    """Scroll-forward terminal renderer using Rich.

    Instead of a full-screen ``Live`` layout the renderer prints elements
    sequentially so the terminal scrolls naturally like modern Node-style
    CLI wizards (create-t3-app, create-next-app, etc.).
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, config: WizardDisplayConfig, steps: list[StepState]) -> None:
        self._started = True
        self._print_header(config, steps)

    def stop(self) -> None:
        self._started = False

    def refresh(self, _config: WizardDisplayConfig, _steps: list[StepState]) -> None:
        # Scroll-forward renderer intentionally does nothing on generic
        # refresh — each element is printed once by the orchestrator.
        pass

    # ------------------------------------------------------------------
    # Display helpers called by the wizard orchestrator
    # ------------------------------------------------------------------

    def print_banner(self, config: WizardDisplayConfig) -> None:
        """Render the ASCII art banner if one is configured."""
        if not config.banner:
            return
        banner_text = Text(config.banner.rstrip("\n"))
        banner_text.stylize("bold bright_cyan")
        self.console.print(
            Panel.fit(
                Align.center(banner_text),
                border_style="bright_magenta",
                padding=(0, 2),
            )
        )

    def print_title(self, config: WizardDisplayConfig) -> None:
        """Render title / subtitle block."""
        title = Text(config.title, style="bold bright_white")
        if config.subtitle:
            title.append(f"\n{config.subtitle}", style="dim italic")
        self.console.print(
            Panel.fit(title, border_style="bright_cyan", padding=(0, 2)),
        )

    def print_step_overview(self, steps: list[StepState]) -> None:
        """Render the pending step timeline once at startup."""
        self.console.print()
        for i, step in enumerate(steps):
            icon, style = _STATUS_MAP.get(step.status, ("○", "dim"))
            line = Text("  ")
            line.append(f"{icon} ", style=style)
            line.append(step.name, style="bold white")
            if step.description:
                line.append(f"  {step.description}", style="dim")
            self.console.print(line)
            if i < len(steps) - 1:
                self.console.print(Text("  │", style="dim"))
        self.console.print()

    def print_step_enter(self, step: StepState, index: int, total: int) -> None:
        """Print a section header when a step becomes active."""
        self.console.print(
            Rule(
                f"  Step {index + 1}/{total} ─ {step.name}  ",
                style="bright_cyan",
            ),
        )
        if step.description:
            self.console.print(
                Text(f"  {step.description}", style="dim italic"),
            )
        self.console.print()

    def print_step_result(self, step: StepState) -> None:
        """Print the outcome of a finished step."""
        icon, style = _STATUS_MAP.get(step.status, ("○", "dim"))
        line = Text("  ")
        line.append(f"{icon} ", style=style)
        line.append(step.name, style=style)
        if step.status == StepStatus.FAILED and step.error:
            line.append(f"  {step.error}", style="red")
        self.console.print(line)
        self.console.print()

    def print_success(self, message: str) -> None:
        """Print a final success banner."""
        self.console.print()
        text = Text(f"  ✓  {message}  ", style="bold bright_green")
        self.console.print(
            Panel.fit(
                Align.center(text),
                border_style="green",
                padding=(0, 2),
            ),
        )
        self.console.print()

    def print_error(self, message: str) -> None:
        """Print a final error banner."""
        self.console.print()
        text = Text(f"  ✗  {message}  ", style="bold red")
        self.console.print(
            Panel.fit(
                Align.center(text),
                border_style="red",
                padding=(0, 2),
            ),
        )
        self.console.print()

    def spinner_text(self) -> str:
        """Return the current braille spinner frame (for inline use)."""
        idx = int(time.time() * 12) % len(_SPINNER_FRAMES)
        return _SPINNER_FRAMES[idx]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _print_header(
        self,
        config: WizardDisplayConfig,
        steps: list[StepState],
    ) -> None:
        self.console.print()
        self.print_banner(config)
        self.print_title(config)
        self.print_step_overview(steps)


__all__ = ["RichWizardRenderer", "WizardDisplayConfig"]
