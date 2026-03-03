"""
This file is used to configure the ORM settings & API Configurations.
Please do not store sensitive information in this file, this file is not for storing tokens and secret keys.
"""

import os
from pathlib import Path


def _hydrate_env_from_dotenv():
    root = Path(__file__).resolve().parent.parent
    env_file = root / ".env"
    if not env_file.exists():
        return

    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

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


DATABASE_CONNECTION = {
    "type": "dbstring",
    "content": os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/hyprchan",
    ),
    "entities": [
        "entities.episode",
        "entities.fact",
        "entities.concept",
        "entities.edge",
        "entities.dream",
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

AGENTHUB_TOKEN = os.getenv("AGENTHUB_TOKEN", "unspecified")
AGENTHUB_ORG = int(os.getenv("AGENTHUB_ORG", "1"))
AGENTHUB_MAX_PAYLOAD = 10 * 1024 * 1024

OPENAI_OAUTH_TOKEN = os.getenv("OPENAI_OAUTH_TOKEN", os.getenv("OPENAI_API_KEY", ""))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

HYPRMEMORY_VECTOR_DIM = int(os.getenv("HYPRMEMORY_VECTOR_DIM", "64"))

SPRITES_BASE_DIR = os.path.abspath(os.path.join("public", "assets", "sprites"))

WEBCAM_VISION_ENABLED = _env_flag("WEBCAM_VISION_ENABLED", True)
WEBCAM_DEVICE_INDEX = int(os.getenv("WEBCAM_DEVICE_INDEX", "0"))
WEBCAM_POLL_INTERVAL_SEC = float(os.getenv("WEBCAM_POLL_INTERVAL_SEC", "0.25"))
WEBCAM_MIN_MOTION_RATIO = float(os.getenv("WEBCAM_MIN_MOTION_RATIO", "0.02"))
WEBCAM_MIN_FACE_RATIO = float(os.getenv("WEBCAM_MIN_FACE_RATIO", "0.002"))
WEBCAM_MIN_EMIT_INTERVAL_SEC = float(os.getenv("WEBCAM_MIN_EMIT_INTERVAL_SEC", "1.2"))
WEBCAM_AUTO_INSTALL_OPENCV = _env_flag("WEBCAM_AUTO_INSTALL_OPENCV", True)
WEBCAM_AUTO_FIND_DEVICE = _env_flag("WEBCAM_AUTO_FIND_DEVICE", True)
WEBCAM_MAX_DEVICE_INDEX = int(os.getenv("WEBCAM_MAX_DEVICE_INDEX", "4"))

MULTIMODAL_SNAPSHOT_ENABLED = _env_flag("MULTIMODAL_SNAPSHOT_ENABLED", True)
MULTIMODAL_SNAPSHOT_INTERVAL_SEC = float(
    os.getenv("MULTIMODAL_SNAPSHOT_INTERVAL_SEC", "120")
)

SPEECH_PERCEPTION_ENABLED = _env_flag("SPEECH_PERCEPTION_ENABLED", True)
SPEECH_INPUT_DEVICE = os.getenv("SPEECH_INPUT_DEVICE", "")
SPEECH_LANGUAGE = os.getenv("SPEECH_LANGUAGE", "en")
SPEECH_FRAME_DURATION_MS = int(os.getenv("SPEECH_FRAME_DURATION_MS", "30"))
SPEECH_MIN_SPEECH_SEC = float(os.getenv("SPEECH_MIN_SPEECH_SEC", "0.4"))
SPEECH_END_SILENCE_SEC = float(os.getenv("SPEECH_END_SILENCE_SEC", "0.8"))
SPEECH_MAX_SPEECH_SEC = float(os.getenv("SPEECH_MAX_SPEECH_SEC", "15"))
SPEECH_PRE_ROLL_SEC = float(os.getenv("SPEECH_PRE_ROLL_SEC", "0.3"))
SPEECH_MIN_START_DBFS = float(os.getenv("SPEECH_MIN_START_DBFS", "-38"))
SPEECH_MIN_CONTINUE_DBFS = float(os.getenv("SPEECH_MIN_CONTINUE_DBFS", "-43"))
