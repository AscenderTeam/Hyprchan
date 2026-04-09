from __future__ import annotations

import json
import re
from pathlib import Path
from types import TracebackType
from typing import TypeAlias, TypeVar, cast

import aiosqlite

from hyprchan.core.extensions.workspace import get_extension_data_dir

_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
JsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)
TDefault = TypeVar("TDefault")


def extension_kv_path(name: str, filename: str = "kv.sqlite3") -> Path:
    return get_extension_data_dir(name) / filename


class ExtensionKV:
    path: Path
    table: str

    def __init__(self, path: Path, *, table: str = "kv") -> None:
        if not _TABLE_RE.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        self.path = path
        self.table = table
        self._conn: aiosqlite.Connection | None = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("ExtensionKV is not connected")
        return self._conn

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        conn = self._require_conn()
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        await conn.commit()

    async def close(self) -> None:
        if self._conn is None:
            return
        conn = self._require_conn()
        await conn.close()
        self._conn = None

    async def get(self, key: str, default: TDefault | None = None) -> JsonValue | TDefault | None:
        await self.connect()
        conn = self._require_conn()
        cursor = await conn.execute(
            f"SELECT value FROM {self.table} WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return default
        try:
            return cast(JsonValue, json.loads(row[0]))
        except json.JSONDecodeError:
            return default

    async def set(self, key: str, value: JsonValue) -> None:
        await self.connect()
        conn = self._require_conn()
        payload = json.dumps(value)
        await conn.execute(
            f"INSERT OR REPLACE INTO {self.table} (key, value) VALUES (?, ?)",
            (key, payload),
        )
        await conn.commit()

    async def delete(self, key: str) -> bool:
        await self.connect()
        conn = self._require_conn()
        cursor = await conn.execute(
            f"DELETE FROM {self.table} WHERE key = ?", (key,)
        )
        await conn.commit()
        deleted = cursor.rowcount > 0
        await cursor.close()
        return deleted

    async def keys(self) -> list[str]:
        await self.connect()
        conn = self._require_conn()
        cursor = await conn.execute(f"SELECT key FROM {self.table}")
        rows = await cursor.fetchall()
        await cursor.close()
        return [row[0] for row in rows]

    async def clear(self) -> None:
        await self.connect()
        conn = self._require_conn()
        await conn.execute(f"DELETE FROM {self.table}")
        await conn.commit()

    async def __aenter__(self) -> "ExtensionKV":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
