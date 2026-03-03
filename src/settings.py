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


DATABASE_CONNECTION = {
    "type": "dbstring",
    "content": "sqlite+aiosqlite:///database.db",  # Replace with your own db string
    "entities": [],
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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-5.3")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

SPRITES_BASE_DIR = os.path.abspath(os.path.join("public", "assets", "sprites"))
