from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def project_config_dir() -> Path:
    return repo_root() / "hyprchan-configs"


def user_config_dir() -> Path:
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "hyprchan"
    return Path.home() / ".config" / "hyprchan"


def personalization_paths() -> list[Path]:
    override = os.getenv("HYPRCHAN_PERSONALIZATION_PATH", "").strip()
    if override:
        return [Path(override)]

    return [
        project_config_dir() / "personalization.yaml",
        user_config_dir() / "personalization.yaml",
    ]
