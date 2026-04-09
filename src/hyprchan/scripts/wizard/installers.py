from __future__ import annotations

from .wizard import Wizard

DEFAULT_BANNER = r"""
 _   _                       _
| | | |_   _ _ __  _ __ ___| |__   __ _ _ __
| |_| | | | | '_ \| '__/ __| '_ \ / _` | '_ \
|  _  | |_| | |_) | | | (__| | | | (_| | | | |
|_| |_|\__, | .__/|_|  \___|_| |_|\__,_|_| |_|
       |___/|_|
"""


class MainInstaller(Wizard):
    title: str = "Hyprchan Onboarding"
    subtitle: str = "Interactive setup wizard for your project."
    banner: str | None = DEFAULT_BANNER


class ExtensionInstaller(Wizard):
    extension_name: str
    title: str
    subtitle: str
    banner: str | None

    def __init__(
        self,
        extension_name: str,
        **kwargs: object,
    ) -> None:
        self.extension_name = extension_name
        self.title = f"Extension Setup: {extension_name}"
        self.subtitle = "Extension-owned setup flow"
        self.banner = DEFAULT_BANNER
        super().__init__(**kwargs)  # type: ignore[arg-type]


__all__ = ["ExtensionInstaller", "MainInstaller"]
