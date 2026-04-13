"""
This file is used to configure the ORM settings & API Configurations.
Please do not store sensitive information in this file, this file is not for storing tokens and secret keys.
"""

import os
from pathlib import Path

from hyprchan.config.paths import env_paths
from hyprchan.config.personalization import load_personalization_config


def _hydrate_env_from_dotenv():
    # Priority order: Shell Env > User Config .env > Repo Root .env
    # We load in priority order and only set if key is not already in os.environ
    for env_file in reversed(env_paths()):
        if not env_file.exists():
            continue

        try:
            lines = env_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")


_hydrate_env_from_dotenv()


def _env_flag(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


PRODUCTION = _env_flag("PRODUCTION", False)
if PRODUCTION:
    os.environ.setdefault("PRODUCTION", "1")
else:
    os.environ.setdefault("PRODUCTION", "0")
    os.environ.setdefault("ASCENDER_ENV", "development")
    os.environ.setdefault("ASC_ENV", "development")
    os.environ.setdefault("LOG_LEVEL", "DEBUG")


DATABASE_CONNECTION = {
    "type": "dbstring",
    "content": os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:mysecretpassword@localhost:5432/hyprchan",
    ),
    "entities": [
        "hyprchan.entities.episode",
        "hyprchan.entities.fact",
        "hyprchan.entities.concept",
        "hyprchan.entities.edge",
        "hyprchan.entities.dream",
        "hyprchan.entities.skills",
    ],
    "pool_options": {},
}

ORIGINS = [
    "*",
]

BASE_PATH = os.path.dirname(os.path.abspath(__file__))

MIN_THRESHOLD = 3
MAX_THRESHOLD = 12

MIN_WINDOW = 0.25
MAX_WINDOW = 2.0


_PERSONALIZATION = load_personalization_config()

OPENAI_OAUTH_TOKEN = os.getenv("OPENAI_OAUTH_TOKEN", os.getenv("OPENAI_API_KEY", ""))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", _PERSONALIZATION.ai.model)
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

INFERENCE_TARGET = os.getenv(
    "INFERENCE_TARGET", f"{_PERSONALIZATION.ai.provider}:{OPENAI_MODEL}"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
GEMINI_API_BASE_URL = os.getenv(
    "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_API_BASE_URL = os.getenv(
    "OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"
)
OPENROUTER_HTTP_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "")
OPENROUTER_X_TITLE = os.getenv("OPENROUTER_X_TITLE", "")

HYPRMEMORY_VECTOR_DIM = int(os.getenv("HYPRMEMORY_VECTOR_DIM", "1536"))

def _resolve_sprites_base_dir() -> str:
    package_sprites = Path(__file__).resolve().parent / "assets" / "sprites"
    if package_sprites.exists():
        return str(package_sprites)

    # Dev fallback when running from repository root.
    repo_sprites = Path.cwd() / "public" / "assets" / "sprites"
    return str(repo_sprites.resolve())


SPRITES_BASE_DIR = _resolve_sprites_base_dir()

WEBCAM_VISION_ENABLED = _env_flag("WEBCAM_VISION_ENABLED", True)
WEBCAM_DEVICE_INDEX = int(os.getenv("WEBCAM_DEVICE_INDEX", "0"))
WEBCAM_POLL_INTERVAL_SEC = float(os.getenv("WEBCAM_POLL_INTERVAL_SEC", "0.25"))
WEBCAM_MIN_MOTION_RATIO = float(os.getenv("WEBCAM_MIN_MOTION_RATIO", "0.02"))
WEBCAM_MIN_FACE_RATIO = float(os.getenv("WEBCAM_MIN_FACE_RATIO", "0.002"))
WEBCAM_MIN_EMIT_INTERVAL_SEC = float(os.getenv("WEBCAM_MIN_EMIT_INTERVAL_SEC", "1.2"))
WEBCAM_AUTO_INSTALL_OPENCV = _env_flag("WEBCAM_AUTO_INSTALL_OPENCV", True)
WEBCAM_AUTO_FIND_DEVICE = _env_flag("WEBCAM_AUTO_FIND_DEVICE", True)
WEBCAM_MAX_DEVICE_INDEX = int(os.getenv("WEBCAM_MAX_DEVICE_INDEX", "4"))

MULTIMODAL_SNAPSHOT_ENABLED = _env_flag("MULTIMODAL_SNAPSHOT_ENABLED", False)
MULTIMODAL_SNAPSHOT_INTERVAL_SEC = float(
    os.getenv("MULTIMODAL_SNAPSHOT_INTERVAL_SEC", "120")
)

SPEECH_PERCEPTION_ENABLED = _env_flag("SPEECH_PERCEPTION_ENABLED", True)
SPEECH_INPUT_DEVICE = os.getenv("SPEECH_INPUT_DEVICE", "")
SPEECH_LANGUAGE = os.getenv("SPEECH_LANGUAGE", "auto")
SPEECH_FRAME_DURATION_MS = int(os.getenv("SPEECH_FRAME_DURATION_MS", "30"))
SPEECH_MIN_SPEECH_SEC = float(os.getenv("SPEECH_MIN_SPEECH_SEC", "0.4"))
SPEECH_END_SILENCE_SEC = float(os.getenv("SPEECH_END_SILENCE_SEC", "0.8"))
SPEECH_MAX_SPEECH_SEC = float(os.getenv("SPEECH_MAX_SPEECH_SEC", "15"))
SPEECH_PRE_ROLL_SEC = float(os.getenv("SPEECH_PRE_ROLL_SEC", "0.3"))
SPEECH_MIN_START_DBFS = float(os.getenv("SPEECH_MIN_START_DBFS", "-38"))
SPEECH_MIN_CONTINUE_DBFS = float(os.getenv("SPEECH_MIN_CONTINUE_DBFS", "-43"))

EVENT_COMPACTION_ENABLED = _env_flag("EVENT_COMPACTION_ENABLED", True)
EVENT_COMPACTION_MODEL = os.getenv("EVENT_COMPACTION_MODEL", "gpt-5-nano")
EVENT_COMPACTION_BATCH_SIZE = int(os.getenv("EVENT_COMPACTION_BATCH_SIZE", "50"))
EVENT_COMPACTION_KEEP_TAIL = int(os.getenv("EVENT_COMPACTION_KEEP_TAIL", "0"))

EXTENSIONS_ENABLED = list(_PERSONALIZATION.extensions.enabled)
