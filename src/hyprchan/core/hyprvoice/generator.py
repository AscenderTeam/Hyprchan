from __future__ import annotations

from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any


class VoiceGenerator(ABC):
    @abstractmethod
    async def generate(self, text: str) -> BytesIO: ...

    @abstractmethod
    async def stream(self, text: str) -> Any: ...

    async def stop(self) -> None:
        """Cancel any in-progress generation. Override if the generator needs cleanup."""
