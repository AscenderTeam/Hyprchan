import importlib
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from hyprchan.core.extensions.types.manifest import IExtManifest
from hyprchan.scripts.wizard import Wizard


class Downloader(ABC):
    extensions_path: str
    _target_path: Path | None = None

    @abstractmethod
    async def fetch(self, resource: str, additional: Any) -> bool: ...

    @abstractmethod
    async def download(self): ...

    @abstractmethod
    async def start(self): ...

    def check_for_setup(self) -> Wizard | None:
        """
        Checks manifest.yml for a 'setup' field (format package:Class).
        If found, loads and returns the Wizard instance.
        """
        if not self._target_path or not self._target_path.exists():
            return None

        manifest_path = self._target_path / "manifest.yml"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

            manifest = IExtManifest.model_validate(raw)
            if not manifest.setup or ":" not in manifest.setup:
                return None

            module_name, class_name = manifest.setup.split(":")

            # Add extension directory to sys.path to allow importing the setup module
            target_str = str(self._target_path)
            if target_str not in sys.path:
                sys.path.insert(0, target_str)

            module = importlib.import_module(module_name)
            wizard_cls = getattr(module, class_name)

            if not issubclass(wizard_cls, Wizard):
                return None

            return wizard_cls()
        except Exception:
            # Silent failure for KISS
            return None
