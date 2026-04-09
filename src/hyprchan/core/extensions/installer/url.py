import asyncio
import io
import shutil
import zipfile
import tarfile
from pathlib import Path
from typing import Any

import httpx
from .downloader import Downloader


class URLDownloader(Downloader):
    def __init__(self, extensions_path: str):
        self.extensions_path = extensions_path
        self._resource: str | None = None
        self._additional: Any = None
        self._target_path: Path | None = None

    async def fetch(self, resource: str, additional: Any) -> bool:
        """
        Validate the URL resource and prepare target path.
        `additional` should be a dict with 'name' (required).
        """
        self._resource = resource
        self._additional = additional or {}
        
        name = self._additional.get("name")
        if not name:
            # We must have a name for the folder if we're downloading a single archive.
            # Derive from URL filename if not provided.
            filename = resource.rstrip("/").split("/")[-1]
            # Strip common archive extensions
            for ext in [".zip", ".tar.gz", ".tgz", ".tar"]:
                if filename.endswith(ext):
                    filename = filename[:-len(ext)]
                    break
            name = filename

        self._target_path = Path(self.extensions_path) / name
        
        # Simple HEAD request to see if URL is reachable
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.head(resource)
                return response.status_code < 400
        except Exception:
            return False

    async def download(self):
        """Download and extract the archive."""
        if not self._resource or not self._target_path:
            raise RuntimeError("Must call fetch() before download()")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(self._resource)
            if response.status_code >= 400:
                raise RuntimeError(f"Failed to download resource: {response.status_code}")

        content = response.content
        
        if self._target_path.exists():
            if self._target_path.is_dir():
                shutil.rmtree(self._target_path)
            else:
                self._target_path.unlink()

        self._target_path.mkdir(parents=True, exist_ok=True)

        try:
            # Check for zip
            if zipfile.is_zipfile(io.BytesIO(content)):
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    # We might want to handle nested folders inside zip
                    # (some archives have a top-level folder)
                    self._extract_zip(zf, self._target_path)
            # Check for tar
            elif self._resource.endswith((".tar.gz", ".tgz", ".tar")):
                with tarfile.open(fileobj=io.BytesIO(content)) as tf:
                    self._extract_tar(tf, self._target_path)
            else:
                raise ValueError("Unsupported archive format. Supported: .zip, .tar.gz, .tgz, .tar")
        except Exception as exc:
            # Cleanup on failure
            if self._target_path.exists():
                shutil.rmtree(self._target_path)
            raise RuntimeError(f"Extraction failed: {exc}") from exc

    def _extract_zip(self, zf: zipfile.ZipFile, target: Path):
        # If all files share a common top-level directory, we should probably strip it
        # However, a simpler approach is to just extract.
        # But some zips contain exactly one folder that contains everything.
        members = zf.namelist()
        root_dir = self._find_archive_root(members)
        
        if root_dir:
            # Shift everything up
            for member in members:
                if member == root_dir: continue
                relative_path = Path(member).relative_to(root_dir)
                if not member.endswith("/"): # It's a file
                    with zf.open(member) as source, (target / relative_path).open('wb') as dest:
                        (target / relative_path).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfileobj(source, dest)
                else:
                    (target / relative_path).mkdir(parents=True, exist_ok=True)
        else:
            zf.extractall(target)

    def _extract_tar(self, tf: tarfile.TarFile, target: Path):
        members = tf.getnames()
        root_dir = self._find_archive_root(members)

        if root_dir:
            for member in tf.getmembers():
                if member.name == root_dir: continue
                relative_path = Path(member.name).relative_to(root_dir)
                member.name = str(relative_path)
                tf.extract(member, target)
        else:
            tf.extractall(target)

    def _find_archive_root(self, members: list[str]) -> str | None:
        """Find common root directory in archive members if it exists."""
        if not members: return None
        
        first = members[0].split('/')[0]
        if not first: return None
        
        for member in members:
            if not member.startswith(first + '/'):
                if member == first: continue # Folder itself is fine
                return None
        return first + '/' if not first.endswith('/') else first

    async def start(self):
        """Post-download hook."""
        if not self._target_path or not self._target_path.exists():
            raise RuntimeError("Download must be successful before start()")
        
        # In the future, this could trigger dependency installation.
        return True
