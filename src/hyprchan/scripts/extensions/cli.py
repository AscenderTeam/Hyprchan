from __future__ import annotations

import asyncio

from ascender.core.cli_engine import Command, GenericCLI, Handler
from ascender.core.di.abc.base_injector import Injector

from config.personalization_store import (
    load_enabled_extensions,
    save_enabled_extensions,
)
from core.extensions.loader import ExtensionLoader
from core.hypraios.kernel.kernel import HyprAIOSKernel


@Command(
    name="extensions",
    description="Temporary extension loader utilities.",
    aliases=["ext"],
)
class ExtensionsCLI(GenericCLI):
    def __init__(self, injector: Injector) -> None:
        super().__init__()
        self.injector = injector

    @Handler("load", description="Load an extension by name or path.")
    def load(self, extension: str) -> None:
        kernel = self.injector.get(HyprAIOSKernel)
        loader = ExtensionLoader(kernel)  # pyright: ignore[reportArgumentType]
        asyncio.run(loader.load(extension))
        print(f"Loaded extension: {extension}")

    @Handler("enable", description="Enable an extension for runtime autoload.")
    def enable(self, extension: str) -> None:
        enabled = load_enabled_extensions()
        if extension not in enabled:
            enabled.append(extension)
            save_enabled_extensions(enabled)
        print(f"Enabled extension: {extension}")

    @Handler("disable", description="Disable an extension for runtime autoload.")
    def disable(self, extension: str) -> None:
        enabled = [item for item in load_enabled_extensions() if item != extension]
        save_enabled_extensions(enabled)
        print(f"Disabled extension: {extension}")

    @Handler("list", description="List enabled extensions.")
    def list(self) -> None:
        enabled = load_enabled_extensions()
        if not enabled:
            print("No extensions enabled.")
            return
        print("Enabled extensions:")
        for name in enabled:
            print(f"- {name}")
