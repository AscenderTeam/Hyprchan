import os
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from scripts.wizard import Choice, Confirm, Wizard, WizardContext, step
from scripts.wizard.prompts import PromptDriver
from scripts.wizard.wizard import WizardRenderer

from setup.config_assembler import ConfigAssembler


class InstallationMaster(Wizard):
    title = "HYPR-CHAN Installation Master"
    banner = """
██╗  ██╗██╗   ██╗██████╗ ██████╗  ██████╗██╗  ██╗ █████╗ ███╗   ██╗
██║  ██║╚██╗ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║██╔══██╗████╗  ██║
███████║ ╚████╔╝ ██████╔╝██████╔╝██║     ███████║███████║██╔██╗ ██║
██╔══██║  ╚██╔╝  ██╔═══╝ ██╔══██╗██║     ██╔══██║██╔══██║██║╚██╗██║
██║  ██║   ██║   ██║     ██║  ██║╚██████╗██║  ██║██║  ██║██║ ╚████║
╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝

                  (\__/)
                  ( >.< )  ♥
                  / >🎀 \

                 HYPR-CHAN
    """

    def __init__(
        self,
        *,
        renderer: WizardRenderer | None = None,
        prompt_driver: PromptDriver | None = None,
    ) -> None:
        super().__init__(renderer=renderer, prompt_driver=prompt_driver)
        self.console = Console()
        self.config_assembler = ConfigAssembler()

    @step(name="introduction", description="Welcome to Hyprchan's setup wizard!")
    def introduction(self, ctx: WizardContext):
        disclaimer = open(
            os.path.join(os.path.dirname(__file__), "disclaimer.txt"),
            encoding="utf-8",
        ).read()

        table = Panel(
            disclaimer,
            title="[bold]Hyprchan Setup Wizard[/bold]",
            subtitle="Security warning",
            border_style="cyan",
        )
        self.console.print(table)

        confirm = ctx.confirm("Do you agree to the disclaimer?", default=True)

        if not confirm:
            exit(1)

        personalization_path, env_path = self.config_assembler.start_personalization()

        self.console.print(
            f"Personalization config will be created at [bold cyan]{personalization_path}[/]"
        )
        self.console.print(
            f"Environment config will be created at [bold cyan]{env_path}[/]"
        )
        self.console.clear()

        return

    @step(name="Choose your provider", description="Choose your LLM provider")
    def choose_provider(
        self,
        ctx: WizardContext,
        provider: Annotated[
            str,
            Choice(options=["openai", "gemini", "anthropic", "openrouter", "custom"]),
        ],
    ):
        if provider == "custom":
            custom_url = ctx.input(
                "Provider URL",
                placeholder="(It should be OpenAI compatible API)",
                required=True,
            )
            self.config_assembler.select_provider("openai", custom_url)
            return

        self.config_assembler.select_provider(provider)
        return

    @step(
        name="Select model", description="Select LLM model to power Hypr-chan's brain"
    )
    def choose_model(self, ctx: WizardContext):
        models = self.config_assembler.list_models()
        models.append("custom")

        model = ctx.choice("LLM model", models)

        if model == "custom":
            custom_model = ctx.input(
                "LLM model name",
                placeholder="Type the name of the model...",
                required=True,
            )
            self.config_assembler.select_model(custom_model)
            return

        self.config_assembler.select_model(model.removesuffix(" (recommended)"))
