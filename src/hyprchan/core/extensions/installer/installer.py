from typing import Any, Union

from scripts.wizard import Wizard

from .downloader import Downloader
from .git import GitDownloader
from .url import URLDownloader


class ExtensionInstaller:
    """
    High-level installer that decides which downloader to use.
    """

    def __init__(self, extensions_path: str):
        self.extensions_path = extensions_path

    def get_downloader(self, resource: str) -> Downloader:
        if resource.startswith(("git@", "http://", "https://")) and (
            resource.endswith(".git")
            or "github.com" in resource
            or "gitlab.com" in resource
        ):
            return GitDownloader(self.extensions_path)
        elif resource.startswith(("http://", "https://")):
            return URLDownloader(self.extensions_path)

        raise ValueError(f"Unsupported resource type: {resource}")

    async def install(
        self, resource: str, additional: Any = None
    ) -> Union[bool, Wizard]:
        downloader = self.get_downloader(resource)
        if await downloader.fetch(resource, additional):
            await downloader.download()
            await downloader.start()

            wizard = downloader.check_for_setup()
            return wizard if wizard else True

        return False
