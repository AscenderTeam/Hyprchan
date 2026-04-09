from __future__ import annotations

from ascender.core.cli_engine import Command, GenericCLI, Handler
from ascender.core.di.abc.base_injector import Injector

from scripts.tui.app import run_tui


@Command(
    name="tui",
    description="Launch the Hyprchan terminal UI (API-driven).",
    aliases=["ui"],
)
class HyprTuiCLI(GenericCLI):
    def __init__(self, injector: Injector) -> None:
        self.injector = injector

    @Handler("run", description="Run the Hyprchan TUI in this process.")
    def run(self) -> None:
        run_tui()
