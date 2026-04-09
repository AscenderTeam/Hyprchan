from __future__ import annotations

from ascender.core.cli_engine import Command, GenericCLI, Handler
from ascender.core.di.abc.base_injector import Injector


@Command(
    name="animation",
    description="Launch and manage the GTK animation engine.",
    aliases=["anim"],
)
class AnimationCLI(GenericCLI):
    def __init__(self, injector: Injector) -> None:
        self.injector = injector

    @Handler("run", description="Run the animation engine in this process.")
    def run(self) -> None:
        print("Starting animation engine...")
        from hyprchan.core.animations.engine import AnimationEngine

        self.injector.get(AnimationEngine)
