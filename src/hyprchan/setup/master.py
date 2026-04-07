import os
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from scripts.wizard import Choice, Confirm, Wizard, WizardContext, step
from scripts.wizard.prompts import PromptDriver
from scripts.wizard.wizard import WizardRenderer

from setup.config_assembler import ConfigAssembler
from setup.openai_oauth import OpenAIOAuth
from setup.postgres_installer import PostgresInstaller
from setup.service_manager import ServiceManager


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
        self.service_manager = ServiceManager()

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

    @step(name="API configuration", description="Configure provider API key")
    def api_key(self, ctx: WizardContext):
        model = self.config_assembler.selected_model
        if isinstance(model, str) and "-codex" in model:
            self.console.print(
                "[yellow]Codex model detected. Initiating OAuth2 flow...[/yellow]"
            )
            oauth = OpenAIOAuth()
            token = oauth.catch_token()
            if token:
                self.console.print("[green]Token received successfully![/green]")
                self.config_assembler.set_api_key(token)
                return
            else:
                self.console.print(
                    "[red]OAuth flow failed or timed out. Falling back to manual entry.[/red]"
                )

        api_key = ctx.input(
            "Provider API key", placeholder="Enter your API key", required=True
        )
        self.config_assembler.set_api_key(api_key)

    @step(
        name="Memory setup",
        description="Do you want Hypr-chan to remember and collect memory?",
    )
    def database_configuration(
        self, ctx: WizardContext, enable: Annotated[bool, Confirm(default=True)]
    ):
        if not enable:
            return

        panel = Panel(
            (
                "[cyan]HyprMemory[/] is a brain-inspired memory system for hyprchan which allows for her to remember (factual, episodic & procedural) memories and collect information into a long-term memory.\n"
                "- **STM (Short-term)**: Redis/in-memory TTL store for raw perception + recent items.\n"
                "- **LTM (Long-term)**: Postgres storage for episodes, semantic facts, concepts, graph edges, and dream logs.\n"
                "- **WM (Working-memory)**: Prompt blocks composed from recall results.\n"
                "- **Retrieval**: Hybrid dense + lexical + graph spreading activation with emotion-aware reranking.\n"
                "- **Consolidation**: Sleep-time STM -> LTM distillation with fatigue-bounded processing.\n"
                "- **Dreams**: Optional LLM judge generates a dream fragment as a consolidation side-effect.\n\n"
                "NOTE: [yellow]Hypr-chan will sleep if fatigue will creep high up.[/]\n"
            ),
            title="Hypr-memory setup",
        )

        self.console.print(panel)

        self.console.print("For better quality we need postgres database.")

        use_postgrs = ctx.confirm("Use postgresql", default=True)

        if use_postgrs:
            installer = PostgresInstaller(self.config_assembler.env_path)

            method = ctx.choice(
                "Database connection method",
                [
                    "docker (automatic)",
                    "manual connection string",
                    "manual components",
                ],
            )

            if method == "docker (automatic)":
                password = ctx.secret("Postgres Password", default="mysecretpassword")
                self.console.print(
                    "[cyan]Starting Postgres container with pgvector...[/]"
                )
                if installer.install_docker(password=password):
                    self.console.print(
                        "[green]Postgres container started successfully.[/]"
                    )
                else:
                    self.console.print(
                        "[red]Docker installation failed. Is docker running?[/]"
                    )
                    # Fallback to manual if docker fails
                    method = "manual connection string"

            if method == "manual connection string":
                db_string = ctx.input(
                    "Database URL",
                    placeholder="postgresql+asyncpg://user:pass@host:port/dbname",
                    required=True,
                )
                installer.configure_manual(db_string)

            elif method == "manual components":
                host = ctx.input("Host", default="localhost")
                port = int(ctx.input("Port", default="5432"))
                user = ctx.input("Username", default="postgres")
                password = ctx.secret("Password")
                dbname = ctx.input("Database Name", default="hyprchan")
                installer.configure_manual_parts(host, port, user, password, dbname)

            # Final check/enable pgvector
            if method != "docker (automatic)":
                self.console.print(
                    "[yellow]Don't forget to enable pgvector extension manually or use `CREATE EXTENSION IF NOT EXISTS vector;`[/]"
                )

    @step(name="HyprMemory", description="Enable long-term memory systems")
    def hyprmemory_configuration(self, ctx: WizardContext):
        self.console.print(
            "[cyan]HyprMemory[/] is a brain-inspired memory system for hyprchan which allows for her to remember (factual, episodic & procedural) memories and collect information into a long-term memory.\n"
        )
        enabled = ctx.confirm("Enable HyprMemory?", default=True)
        self.config_assembler.enable_hyprmemory(enabled)

    @step(name="Background Service", description="Install as background daemon")
    def daemon_setup(self, ctx: WizardContext):
        manager = ServiceManager()
        if not (manager.is_linux() or manager.is_macos()):
            self.console.print(
                "[yellow]Background service only supported on Linux (systemd) and macOS (launchd) for now.[/]"
            )
            return

        install = ctx.confirm("Install Hyprchan as a background service?", default=True)
        if install:
            if manager.install_service():
                self.console.print(
                    "[green]Service installed and enabled successfully![/green]"
                )
                if ctx.confirm("Start the service now?", default=True):
                    if manager.start_service():
                        self.console.print(
                            "[green]Service started successfully![/green]"
                        )
                    else:
                        self.console.print("[red]Failed to start the service.[/red]")
            else:
                self.console.print("[red]Failed to install background service.[/red]")

    @step(name="Final Step", description="Are you ready to launch and meet hypr-chan?")
    def launch(
        self, ctx: WizardContext, unleash: Annotated[bool, Confirm(default=True)]
    ):
        if unleash:
            self.service_manager.start_service()
            self.console.print("[cyan]Hypr-chan is waking up...![/]")
            self.console.print("To talk to [cyan bold]her[/] type `hyprchan tui`")
