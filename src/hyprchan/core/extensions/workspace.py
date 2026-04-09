from __future__ import annotations

from pathlib import Path

from hyprchan.config.paths import extensions_dir
from hyprchan.core.extensions.types.manifest import IExtManifest


def resolve_extension_workspace(name: str, manifest: IExtManifest | None = None) -> Path:
    if manifest and manifest.workspace:
        absolute = (manifest.workspace.absolute_path or "").strip()
        if absolute:
            return Path(absolute).expanduser().resolve()
        subdir = (manifest.workspace.default_subdir or "").strip()
        if subdir:
            return (extensions_dir() / subdir).expanduser().resolve()
    return (extensions_dir() / name).expanduser().resolve()


def get_extension_workspace(name: str, *, subdir: str | None = None) -> Path:
    root = (extensions_dir() / name).expanduser().resolve()
    if subdir:
        return root / subdir
    return root


def get_extension_data_dir(name: str) -> Path:
    return get_extension_workspace(name, subdir="data")
