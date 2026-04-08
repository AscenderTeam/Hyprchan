from __future__ import annotations

import asyncio

from ascender.core.cli_engine import Command, GenericCLI, Handler
from ascender.core.di.abc.base_injector import Injector

from config.personalization_store import (
    load_enabled_extensions,
    save_enabled_extensions,
)
from config.paths import extensions_dir
from core.extensions.loader import ExtensionLoader
from core.extensions.installer import ExtensionInstaller
from core.hypraios.kernel.kernel import HyprAIOSKernel
from scripts.wizard import Wizard


@Command(
    name="extensions",
    description="Temporary extension loader utilities.",
    aliases=["ext"],
)
class ExtensionsCLI(GenericCLI):
    def __init__(self, injector: Injector) -> None:
        super().__init__()
        self.injector = injector

    @Handler("install", description="Install an extension from a Git repository or URL.")
    def install(self, resource: str) -> None:
        path = extensions_dir()
        path.mkdir(parents=True, exist_ok=True)
        installer = ExtensionInstaller(str(path))
        
        print(f"Installing extension from {resource} into {path}...")
        
        async def run_install():
            result = await installer.install(resource)
            if isinstance(result, Wizard):
                print("\nRunning extension setup wizard...")
                # Run the wizard synchronously
                result.run_sync()
                print(f"Successfully installed and configured extension from {resource}.")
            elif result:
                print(f"Successfully installed extension from {resource}.")
            else:
                print(f"Failed to install extension from {resource}.")

        asyncio.run(run_install())

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
