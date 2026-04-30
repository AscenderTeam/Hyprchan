import os
from typing import Any, cast

from alp import provideALP
from ascender.common.api_docs import DefineAPIDocs
from ascender.core.cli_engine import useCLI
from ascender.core.database import ORMEnum, provideDatabase
from ascender.core.router import provideRouter
from ascender.core.types import IBootstrap

from hyprchan.animations.depressed_sit import DepressedSitAnimation
from hyprchan.animations.falling_asleep_sit import FallingAsleepSitAnimation
from hyprchan.animations.idle_sit import IdleSitAnimation
from hyprchan.animations.sleeping_sit import SleepingSitAnimation
from hyprchan.animations.startle_wakeup_sit import StartleWakeupSitAnimation
from hyprchan.core.animations.provider import provideAnimations
from hyprchan.core.hyprmemory.provider import provideHyprmemory
from hyprchan.routes import routes
from hyprchan.scripts.animation_cli import AnimationCLI
from hyprchan.scripts.extensions.cli import ExtensionsCLI
from hyprchan.scripts.start_cli import StartCLI
from hyprchan.scripts.tui.cli import HyprTuiCLI
from hyprchan.scripts.wizard.cli import WizardCLI
from hyprchan.settings import (
    DATABASE_CONNECTION,
)
from hyprchan.shared.database_runtime import resolve_database_connection

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
    useCLI(StartCLI),
    provideHyprmemory(),
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
