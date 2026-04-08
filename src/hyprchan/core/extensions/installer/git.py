import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from .downloader import Downloader


class GitDownloader(Downloader):
    def __init__(self, extensions_path: str):
        self.extensions_path = extensions_path
        self._resource: str | None = None
        self._additional: Any = None
        self._target_path: Path | None = None

    async def fetch(self, resource: str, additional: Any) -> bool:
        """
        Validate the git resource and prepare target path.
        `additional` can be a dict with 'branch' and 'name'.
        """
        self._resource = resource
        self._additional = additional or {}

        name = self._additional.get("name")
        if not name:
            # Extract name from git URL
            name = resource.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]

        self._target_path = Path(self.extensions_path) / name

        # Check if git is available
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            return process.returncode == 0
        except FileNotFoundError:
            return False

    async def download(self):
        """Perform git clone."""
        if not self._resource or not self._target_path:
            raise RuntimeError("Must call fetch() before download()")

        if self._target_path.exists():
            # If it exists, we might want to pull or delete.
            # For a clean install, we delete.
            if self._target_path.is_dir():
                shutil.rmtree(self._target_path)
            else:
                self._target_path.unlink()

        cmd = ["git", "clone", self._resource, str(self._target_path)]

        branch = self._additional.get("branch")
        if branch:
            cmd.extend(["-b", branch])

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Git clone failed: {stderr.decode()}")

    async def start(self):
        """Post-download hook (e.g. check for manifest)."""
        if not self._target_path or not self._target_path.exists():
            raise RuntimeError("Download must be successful before start()")

        manifest_path = self._target_path / "manifest.yml"
        if not manifest_path.exists():
            # Warning or error? Extensions MUST have a manifest.
            pass

        # In the future, this could trigger dependency installation or initial setup.
        return True
