from typing import Sequence

from ascender.core.router import RouterRoute

from controllers.v1.events.vision.vision_controller import VisionController
from controllers.v1.events.windows.windows_controller import WindowsController


routes: Sequence[RouterRoute] = [
    {
        "path": "/events/windows",
        "tags": ["Events - Windows"],
        "guards": [],
        "controller": WindowsController,
    },
    {
        "path": "/events/vision",
        "tags": ["Events - Vision"],
        "guards": [],
        "controller": VisionController,
    },
]
