from ascender.common.api_docs import DefineAPIDocs
from ascender.core.database import provideDatabase, ORMEnum
from ascender.core.router import provideRouter
from ascender.core.types import IBootstrap
from typing import Any, cast
from routes import routes
from settings import (
    AGENTHUB_MAX_PAYLOAD,
    AGENTHUB_ORG,
    AGENTHUB_TOKEN,
    DATABASE_CONNECTION,
)

try:
    from agenthub.providers.agenthub_provider import provideAgentHub  # type: ignore[import-not-found]
except ModuleNotFoundError:
    provideAgentHub = None

from shared.attp import provideAttpClient

from attp_core.rs_api import Limits


providers = [
    {
        "provide": DefineAPIDocs,
        "value": DefineAPIDocs(swagger_url="/docs", redoc_url="/redoc"),
    },
    provideRouter(routes),
    provideDatabase(ORMEnum.SQLALCHEMY, cast(Any, DATABASE_CONNECTION)),
    provideAttpClient(
        AGENTHUB_TOKEN,
        AGENTHUB_ORG,
        limits=Limits(max_payload_size=AGENTHUB_MAX_PAYLOAD),
    ),
]

if provideAgentHub is not None:
    providers.append(provideAgentHub())


appBootstrap: IBootstrap = {
    "providers": providers,
}
