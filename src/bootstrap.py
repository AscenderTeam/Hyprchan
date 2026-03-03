from typing import Any, cast

from ascender.common.api_docs import DefineAPIDocs
from ascender.core.cli_engine import useCLI
from ascender.core.database import ORMEnum, provideDatabase
from ascender.core.router import provideRouter
from ascender.core.types import IBootstrap

from animations.depressed_sit import DepressedSitAnimation
from core.animations.provider import provideAnimations
from routes import routes
from scripts.animation_cli import AnimationCLI
from settings import (
    AGENTHUB_MAX_PAYLOAD,
    AGENTHUB_ORG,
    AGENTHUB_TOKEN,
    DATABASE_CONNECTION,
)

try:
    from agenthub.providers.agenthub_provider import (
        provideAgentHub,  # type: ignore[import-not-found]
    )
except ModuleNotFoundError:
    provideAgentHub = None

from attp_core.rs_api import Limits

from shared.attp import provideAttpClient

providers = [
    {
        "provide": DefineAPIDocs,
        "value": DefineAPIDocs(swagger_url="/docs", redoc_url="/redoc"),
    },
    provideRouter(routes),
    provideDatabase(ORMEnum.SQLALCHEMY, cast(Any, DATABASE_CONNECTION)),
    useCLI(AnimationCLI),
    provideAttpClient(
        AGENTHUB_TOKEN,
        AGENTHUB_ORG,
        limits=Limits(max_payload_size=AGENTHUB_MAX_PAYLOAD),
    ),
    provideAnimations([DepressedSitAnimation()], target_fps=15),
]

if provideAgentHub is not None:
    providers.append(provideAgentHub())


appBootstrap: IBootstrap = {
    "providers": providers,
}
