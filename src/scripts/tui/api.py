from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ServerSnapshot:
    connected: bool = False
    phase: str = "-"
    active_reason: str = "-"
    next_ponder_sec: float = 0.0
    latest_event_id: int = 0
    last_error: str | None = None
    memory_gate: dict[str, Any] | None = None


class HyprApiClient:
    def __init__(self, base_url: str, timeout_sec: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_sec)
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        resp = await self._client.get(f"{self.base_url}")
        resp.raise_for_status()
        return True

    async def send_message(self, text: str, timeout_sec: float = 25.0) -> dict[str, Any]:
        resp = await self._client.post(
            f"{self.base_url}/communication/send",
            json={"text": text, "timeout_sec": timeout_sec},
        )
        resp.raise_for_status()
        return resp.json()

    async def summon(self) -> dict[str, Any]:
        resp = await self._client.get(f"{self.base_url}/summon")
        resp.raise_for_status()
        return resp.json()

    async def fetch_events(self, *, since_id: int, limit: int = 200) -> dict[str, Any]:
        resp = await self._client.get(
            f"{self.base_url}/communication/events",
            params={"since_id": since_id, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()
