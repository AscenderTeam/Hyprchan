"""
This file is used to configure the ORM settings & API Configurations.
Please do not store sensitive information in this file, this file is not for storing tokens and secret keys.
"""
import os


DATABASE_CONNECTION = {
    "type": "dbstring",
    "content": "sqlite+aiosqlite:///database.db", # Replace with your own db string
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