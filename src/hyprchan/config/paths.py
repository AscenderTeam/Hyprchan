from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "hyprchan").exists():
            return parent
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd().resolve()


def project_config_dir() -> Path:
    return repo_root() / "hyprchan-configs"


def user_config_dir() -> Path:
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "hyprchan"
    return Path.home() / ".config" / "hyprchan"


def builtins_extensions_dir() -> Path:
    override = os.getenv("HYPRCHAN_BUILTINS_EXTENSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    candidates = [
        # Source checkout canonical path.
        repo_root() / "extensions",
        # Installed wheel path when `extensions/**` is shipped at site-packages root.
        Path(__file__).resolve().parents[2] / "extensions",
        # Legacy built-ins location for backward compatibility.
        Path(__file__).resolve().parent.parent / "builtins" / "extensions",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def extensions_dir() -> Path:
    return user_config_dir() / "extensions"


def personalization_paths() -> list[Path]:
    override = os.getenv("HYPRCHAN_PERSONALIZATION_PATH", "").strip()
    if override:
        return [Path(override)]

    return [
        project_config_dir() / "personalization.yaml",
        user_config_dir() / "personalization.yaml",
    ]


def env_paths() -> list[Path]:
    override = os.getenv("HYPRCHAN_ENV_PATH", "").strip()
    if override:
        return [Path(override)]

    return [
        repo_root() / ".env",
        user_config_dir() / ".env",
    ]
