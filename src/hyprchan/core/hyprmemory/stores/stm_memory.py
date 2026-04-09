from __future__ import annotations

from collections import deque
from datetime import timedelta

from core.hyprmemory.interfaces import STMStore
from core.hyprmemory.models import PerceptionTrace, STMItem
from core.hyprmemory.utils.time import utc_now


class InMemorySTMStore(STMStore):
    """In-memory STM fallback when Redis is unavailable."""

    def __init__(self, *, ttl_seconds: int = 6 * 60 * 60, max_items: int = 1024) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: deque[STMItem] = deque(maxlen=max_items)
        self._traces: deque[PerceptionTrace] = deque(maxlen=max_items)

    async def append_trace(self, trace: PerceptionTrace) -> None:
        self._traces.appendleft(trace)

    async def append_item(self, item: STMItem) -> None:
        self._items.appendleft(item)

    async def fetch_pending_items(self, limit: int | None = None) -> list[STMItem]:
        self._evict_expired()
        if limit is None:
            return list(self._items)
        return list(self._items)[:limit]

    async def clear_pending_items(self) -> None:
        self._items.clear()

    async def count_pending_items(self) -> int:
        self._evict_expired()
        return len(self._items)

    def _evict_expired(self) -> None:
        cutoff = utc_now() - timedelta(seconds=self.ttl_seconds)
        self._items = deque(
            [item for item in self._items if item.ts >= cutoff], maxlen=self.max_items
        )
        self._traces = deque(
            [trace for trace in self._traces if trace.ts >= cutoff],
            maxlen=self.max_items,
        )
