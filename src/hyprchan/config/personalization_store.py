from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hyprchan.config.paths import user_config_dir


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = yaml.safe_load(raw)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _save_raw(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def personalization_path() -> Path:
    return user_config_dir() / "personalization.yaml"


def load_enabled_extensions() -> list[str]:
    raw = _load_raw(personalization_path())
    extensions = raw.get("extensions")
    if isinstance(extensions, dict):
        return _ensure_list(extensions.get("enabled"))
    return []


def save_enabled_extensions(enabled: list[str]) -> None:
    raw = _load_raw(personalization_path())
    extensions = raw.get("extensions")
    if not isinstance(extensions, dict):
        extensions = {}
    deduped = []
    seen: set[str] = set()
    for name in enabled:
        cleaned = str(name).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    extensions["enabled"] = deduped
    raw["extensions"] = extensions
    _save_raw(personalization_path(), raw)
