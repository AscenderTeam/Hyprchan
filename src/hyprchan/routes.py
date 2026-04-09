from typing import Sequence
from ascender.core.router import RouterRoute
from hyprchan.controllers.v1.main_controller import MainController
from hyprchan.controllers.v1.routes_module import RoutesV1Module


routes: Sequence[RouterRoute] = [
    {
        "path": "/v1",
        "controller": MainController,
        "include_in_schema": True,
        "load_children": lambda: RoutesV1Module
    },
]

__all__ = ["routes"]