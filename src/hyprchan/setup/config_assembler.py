import json
import os
from pathlib import Path

import httpx
import yaml
from platformdirs import user_config_dir


class ConfigAssembler:
    def __init__(self) -> None:
        self.name = "hyprchan"
        self.appauthor = "ascenderteam"
        self.config_dir = Path(os.path.join(user_config_dir(), self.name))

        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.personalization_path = self.config_dir / "personalization.yaml"
        self.env_path = self.config_dir / ".env"

    def start_personalization(self):
        if not self.personalization_path.exists():
            self.personalization_path.touch()

        if not self.env_path.exists():
            self.env_path.touch()

        return self.personalization_path, self.env_path

    def select_provider(self, name: str, custom_base_url: str | None = None):
        provider = name.lower().strip()

        # Default models per provider
        models = {
            "openai": "gpt-4o-mini",
            "gemini": "gemini-2.5-flash",
            "openrouter": "anthropic/claude-3.5-sonnet",
            "anthropic": "anthropic/claude-3.5-sonnet",
        }

        model = models.get(provider, "gpt-4o-mini")

        # Normalize provider name for INFERENCE_TARGET
        target_provider = provider
        if target_provider == "anthropic":
            target_provider = "openrouter"
        elif target_provider == "custom":
            target_provider = "openai"

        # 1. Update personalization.yml
        config = {}
        if self.personalization_path.exists():
            try:
                content = self.personalization_path.read_text(encoding="utf-8").strip()
                if content:
                    config = yaml.safe_load(content) or {}
            except Exception:
                pass

        if not isinstance(config, dict):
            config = {}

        if "ai" not in config or not isinstance(config["ai"], dict):
            config["ai"] = {}

        config["ai"]["provider"] = target_provider
        config["ai"]["model"] = model

        self.personalization_path.write_text(
            str(yaml.dump(config, default_flow_style=False, sort_keys=False)),
            encoding="utf-8",
        )

        # 2. Update .env
        env_lines = []
        if self.env_path.exists():
            try:
                env_lines = self.env_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                pass

        target_key = "INFERENCE_TARGET"
        target_value = f"{target_provider}:{model}"

        base_url_keys = {
            "openai": "OPENAI_API_BASE_URL",
            "gemini": "GEMINI_API_BASE_URL",
            "openrouter": "OPENROUTER_API_BASE_URL",
        }
        base_url_key = base_url_keys.get(target_provider)

        new_env_lines = []
        target_found = False
        base_url_found = False

        for line in env_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_env_lines.append(line)
                continue

            if "=" in line:
                parts = line.split("=", 1)
                key = parts[0].strip()

                if key == target_key:
                    new_env_lines.append(f"{target_key}={target_value}")
                    target_found = True
                elif base_url_key and key == base_url_key and custom_base_url:
                    new_env_lines.append(f"{base_url_key}={custom_base_url}")
                    base_url_found = True
                else:
                    new_env_lines.append(line)
            else:
                new_env_lines.append(line)

        if not target_found:
            new_env_lines.append(f"{target_key}={target_value}")

        if custom_base_url and base_url_key and not base_url_found:
            new_env_lines.append(f"{base_url_key}={custom_base_url}")

        self.env_path.write_text("\n".join(new_env_lines) + "\n", encoding="utf-8")

    def _get_current_provider(self) -> str:
        # Check .env first
        if self.env_path.exists():
            try:
                lines = self.env_path.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("INFERENCE_TARGET="):
                        val = stripped.split("=", 1)[1].strip()
                        if ":" in val:
                            return val.split(":", 1)[0].strip()
            except Exception:
                pass

        # Then check personalization.yml
        if self.personalization_path.exists():
            try:
                content = self.personalization_path.read_text(encoding="utf-8").strip()
                if content:
                    config = yaml.safe_load(content)
                    if (
                        config
                        and isinstance(config, dict)
                        and "ai" in config
                        and isinstance(config["ai"], dict)
                        and "provider" in config["ai"]
                    ):
                        return str(config["ai"]["provider"])
            except Exception:
                pass

        return "openai"

    def select_model(self, model: str):
        provider = self._get_current_provider()
        model = model.strip()

        # 1. Update personalization.yml
        config = {}
        if self.personalization_path.exists():
            try:
                content = self.personalization_path.read_text(encoding="utf-8").strip()
                if content:
                    config = yaml.safe_load(content) or {}
            except Exception:
                pass

        if not isinstance(config, dict):
            config = {}

        if "ai" not in config or not isinstance(config["ai"], dict):
            config["ai"] = {}

        config["ai"]["model"] = model

        self.personalization_path.write_text(
            str(yaml.dump(config, default_flow_style=False, sort_keys=False)),
            encoding="utf-8",
        )

        # 2. Update .env
        env_lines = []
        if self.env_path.exists():
            try:
                env_lines = self.env_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                pass

        target_key = "INFERENCE_TARGET"
        target_value = f"{provider}:{model}"

        new_env_lines = []
        found = False
        for line in env_lines:
            stripped = line.strip()
            if stripped.startswith(f"{target_key}="):
                new_env_lines.append(f"{target_key}={target_value}")
                found = True
            else:
                new_env_lines.append(line)

        if not found:
            new_env_lines.append(f"{target_key}={target_value}")

        self.env_path.write_text("\n".join(new_env_lines) + "\n", encoding="utf-8")

    def _get_api_key(self, provider: str) -> str | None:
        env_content = ""
        if self.env_path.exists():
            env_content = self.env_path.read_text(encoding="utf-8")

        keys = {
            "openai": ["OPENAI_OAUTH_TOKEN", "OPENAI_API_KEY"],
            "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "openrouter": ["OPENROUTER_API_KEY"],
        }

        search_keys = keys.get(provider, [])
        for line in env_content.splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                if key.strip() in search_keys:
                    return val.strip().strip('"').strip("'")
        return None

    def list_models(self, provider: str | None = None) -> list[str]:
        if provider is None:
            provider = self._get_current_provider()

        if provider == "openai":
            return [
                "gpt-5.4",
                "gpt-5.4-mini",
                "gpt-5.4-nano",
                "gpt-5",
                "gpt-5-mini",
                "gpt-5-nano",
                "gpt-4.1",
                "gpt-5.4-codex",
                "gpt-5.3-codex",
                "gpt-5.2-codex",
                "gpt-5.1-codex",
            ]
        if provider == "gemini":
            return [
                "gemini-3.1-pro",
                "gemini-3.1-flash-lite",
                "gemini-3-flash-preview",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.5-pro",
            ]
        if provider == "openrouter":
            return ["qwen/qwen3.6-plus:free", "moonshotai/kimi-k2.5 (recommended)"]

        return []
