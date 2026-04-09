import os
from typing import Any, cast

from animations.depressed_sit import DepressedSitAnimation
from animations.falling_asleep_sit import FallingAsleepSitAnimation
from animations.idle_sit import IdleSitAnimation
from animations.sleeping_sit import SleepingSitAnimation
from animations.startle_wakeup_sit import StartleWakeupSitAnimation
from ascender.common.api_docs import DefineAPIDocs
from ascender.core.cli_engine import useCLI
from ascender.core.database import ORMEnum, provideDatabase
from ascender.core.router import provideRouter
from ascender.core.types import IBootstrap
from core.animations.provider import provideAnimations
from routes import routes
from scripts.animation_cli import AnimationCLI
from scripts.extensions.cli import ExtensionsCLI
from scripts.tui.cli import HyprTuiCLI
from scripts.wizard.cli import WizardCLI
from settings import (
    DATABASE_CONNECTION,
)

try:
    from agenthub.providers.agenthub_provider import (
        provideAgentHub,
    )
except ModuleNotFoundError:
    provideAgentHub = None

from alp import provideALP
from shared.database_runtime import resolve_database_connection

runtime_database_connection = resolve_database_connection(
    cast(dict[str, Any], DATABASE_CONNECTION)
)

if os.getenv("PRODUCTION") is None:
    os.environ["PRODUCTION"] = "0"

if os.getenv("ASCENDER_ENV") is None and os.getenv(
    "PRODUCTION", "0"
).strip().lower() in {
    "0",
    "false",
    "no",
    "off",
}:
    os.environ["ASCENDER_ENV"] = "development"

providers = [
    {
        "provide": DefineAPIDocs,
        "value": DefineAPIDocs(swagger_url="/docs", redoc_url="/redoc"),
    },
    provideRouter(routes),
    provideDatabase(ORMEnum.SQLALCHEMY, cast(Any, runtime_database_connection)),
    useCLI(AnimationCLI),
    useCLI(ExtensionsCLI),
    useCLI(HyprTuiCLI),
    useCLI(WizardCLI),
    provideALP(),
    provideAnimations(
        [
            DepressedSitAnimation(),
            FallingAsleepSitAnimation(),
            SleepingSitAnimation(),
            IdleSitAnimation(),
            StartleWakeupSitAnimation(),
        ],
        target_fps=8,
    ),
]

appBootstrap: IBootstrap = {
    "providers": providers,
}
