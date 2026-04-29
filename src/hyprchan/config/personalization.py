from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
import yaml

from hyprchan.config.paths import personalization_paths


class AiConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=400, ge=32, le=4096)


class StmConfig(BaseModel):
    mode: str = "redis"


class LtmConfig(BaseModel):
    provider: str = "postgres"


class MemoryConfig(BaseModel):
    enabled: bool = True
    read_active: bool = True
    sleep_enabled: bool = True
    buffer_limit: int = Field(default=3, ge=1, le=32)
    stm: StmConfig = Field(default_factory=StmConfig)
    ltm: LtmConfig = Field(default_factory=LtmConfig)


class TuiConfig(BaseModel):
    poll_interval: float = Field(default=1.0, ge=0.2, le=10.0)
    theme: str = "hypr-dark"
    vi_mode: bool = True


class ExtensionsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class VoiceConfig(BaseModel):
    enabled: bool = False
    engine: str = "hyprchan_audio"
    url: str | None = None
    token: str | None = None
    trim_quotes: bool = True  # strip roleplay action markers: *sighs*, *grabs hand*, etc.
    device: str | None = None  # None = sounddevice default; int index or device name as string
    sample_rate: int = Field(default=22050, ge=8000, le=96000)


class PersonalizationConfig(BaseModel):
    version: int = 1
    ai: AiConfig = Field(default_factory=AiConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)


_ENV_MAP: dict[str, str] = {
    "HYPRCHAN_AI_PROVIDER": "ai.provider",
    "HYPRCHAN_AI_MODEL": "ai.model",
    "HYPRCHAN_AI_TEMPERATURE": "ai.temperature",
    "HYPRCHAN_AI_MAX_OUTPUT_TOKENS": "ai.max_output_tokens",
    "HYPRCHAN_MEMORY_ENABLED": "memory.enabled",
    "HYPRCHAN_MEMORY_READ_ACTIVE": "memory.read_active",
    "HYPRCHAN_MEMORY_SLEEP_ENABLED": "memory.sleep_enabled",
    "HYPRCHAN_MEMORY_BUFFER_LIMIT": "memory.buffer_limit",
    "HYPRCHAN_MEMORY_STM_MODE": "memory.stm.mode",
    "HYPRCHAN_MEMORY_LTM_PROVIDER": "memory.ltm.provider",
    "HYPRCHAN_TUI_POLL_INTERVAL": "tui.poll_interval",
    "HYPRCHAN_TUI_THEME": "tui.theme",
    "HYPRCHAN_TUI_VI_MODE": "tui.vi_mode",
    "HYPRCHAN_EXTENSIONS_ENABLED": "extensions.enabled",
    "OPENAI_MODEL": "ai.model",
    # Voice output
    "HYPRCHAN_VOICE_ENABLED": "voice.enabled",
    "HYPRCHAN_VOICE_ENGINE": "voice.engine",
    "HYPRCHAN_VOICE_URL": "voice.url",
    "SPEECH_TOKEN": "voice.token",
    "HYPRCHAN_VOICE_TRIM_QUOTES": "voice.trim_quotes",
    "HYPRCHAN_VOICE_DEVICE": "voice.device",
    "HYPRCHAN_VOICE_SAMPLE_RATE": "voice.sample_rate",
}


def _dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()  # type: ignore[no-any-return]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        data = yaml.safe_load(raw)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _set_nested(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        node = cursor.get(part)
        if not isinstance(node, dict):
            node = {}
            cursor[part] = node
        cursor = node
    cursor[parts[-1]] = value


def _coerce_value(raw: str, target: Any) -> Any:
    if target is None:
        # Optional field — keep as raw string; model validation handles the type
        return raw
    if isinstance(target, list):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(target, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(target, int):
        try:
            return int(raw)
        except ValueError:
            return target
    if isinstance(target, float):
        try:
            return float(raw)
        except ValueError:
            return target
    return raw


def _apply_env_overrides(config: PersonalizationConfig) -> PersonalizationConfig:
    data = _dump_model(config)
    for env_key, path in _ENV_MAP.items():
        raw = os.getenv(env_key)
        if raw is None or raw == "":
            continue
        cursor: Any = data
        found = True
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                found = False
                break
            cursor = cursor[part]
        if not found:
            continue
        value = _coerce_value(raw, cursor)
        _set_nested(data, path, value)
    return PersonalizationConfig(**data)


def load_personalization_config() -> PersonalizationConfig:
    config = PersonalizationConfig()
    merged = _dump_model(config)
    paths = personalization_paths()
    for path in reversed(paths):
        merged = _deep_merge(merged, _load_yaml(path))
    config = PersonalizationConfig(**merged)
    return _apply_env_overrides(config)
