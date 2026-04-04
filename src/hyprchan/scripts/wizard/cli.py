from __future__ import annotations

import webbrowser
from typing import Annotated

from ascender.core.cli_engine import Command, GenericCLI, Handler
from ascender.core.di.abc.base_injector import Injector

from . import Choice, Confirm, Input, MainInstaller, WizardContext, step

RICKROLL_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class MemeInstaller(MainInstaller):
    subtitle = "Meme demo flow with exactly three steps."

    @step(name="Callsign", description="Pick your onboarding codename.")
    def choose_callsign(
        self,
        codename: Annotated[
            str,
            Input(
                placeholder="agent codename",
                required=False,
                default="chaos-penguin",
            ),
        ],
    ) -> dict[str, str]:
        return {"codename": codename}

    @step(name="Vibe Check", description="Select your startup vibe.")
    async def choose_vibe(
        self,
        vibe: Annotated[str, Choice(["cozy", "turbo", "gremlin"], multiple=False)],
    ) -> dict[str, str]:
        return {"vibe": vibe}

    @step(name="Final Ritual", description="Perform the sacred launch ritual.")
    def launch_ritual(
        self,
        ctx: WizardContext,
        unleash: Annotated[bool, Confirm(default=True)],
    ) -> dict[str, str]:
        if unleash:
            opened = webbrowser.open(RICKROLL_URL, new=2)
            if not opened:
                pass

        return {
            "status": "sent" if unleash else "withheld",
            "url": RICKROLL_URL,
            "current_step": ctx.current_step_key or "unknown",
        }


@Command(
    name="wizard",
    description="Wizard framework playground utilities.",
    aliases=["wiz"],
)
class WizardCLI(GenericCLI):
    def __init__(self, injector: Injector) -> None:
        super().__init__()
        self.injector = injector

    @Handler("meme", description="Run the meme wizard (3 steps + rickroll finale).")
    def meme(self) -> None:
        installer = MemeInstaller()
        result = installer.run_sync()
        if result is None:
            print("Wizard exited before returning a result.")
            return
        print(f"Wizard finished: {result.status.value}")
        if result.status.value != "completed":
            print(f"Stopped at step: {result.failed_step}")
            if result.error:
                print(f"Reason: {result.error}")
