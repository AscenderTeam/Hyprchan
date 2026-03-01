import os
from ascender.common.api_docs import DefineAPIDocs
from ascender.core.database import provideDatabase, ORMEnum
from ascender.core.router import provideRouter
from ascender.core.types import IBootstrap
from routes import routes
from settings import AGENTHUB_MAX_PAYLOAD, AGENTHUB_ORG, AGENTHUB_TOKEN, DATABASE_CONNECTION

from agenthub.providers.agenthub_provider import provideAgentHub

from shared.attp import provideAttpClient

from attp_core.rs_api import Limits


appBootstrap: IBootstrap = {
    "providers": [
        {
            "provide": DefineAPIDocs,
            "value": DefineAPIDocs(swagger_url="/docs", redoc_url="/redoc"),
        },
        provideRouter(routes),
        provideDatabase(ORMEnum.SQLALCHEMY, DATABASE_CONNECTION),
        provideAgentHub(),
        provideAttpClient(
            AGENTHUB_TOKEN, 
            AGENTHUB_ORG,
            limits=Limits(max_payload_size=AGENTHUB_MAX_PAYLOAD)
        )
    ]
}