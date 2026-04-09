from typing import Sequence

from ascender.core.router import RouterRoute

from hyprchan.controllers.v1.events.speech.speech_controller import SpeechController
from hyprchan.controllers.v1.events.vision.vision_controller import VisionController
from hyprchan.controllers.v1.events.windows.windows_controller import WindowsController


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
    {
        "path": "/events/speech",
        "tags": ["Events - Speech"],
        "guards": [],
        "controller": SpeechController,
    },
]
