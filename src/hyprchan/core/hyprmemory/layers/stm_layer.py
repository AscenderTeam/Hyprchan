from __future__ import annotations

from hyprchan.core.hyprmemory.interfaces import STMStore
from hyprchan.core.hyprmemory.models import PerceptionTrace, STMItem


class ShortTermMemoryLayer:
    """Short-term memory access layer (STM)."""

    def __init__(self, store: STMStore) -> None:
        self.store = store

    async def observe(self, trace: PerceptionTrace) -> None:
        """Append a raw perception trace into STM."""
        await self.store.append_trace(trace)

    async def store_item(self, item: STMItem) -> None:
        """Append a structured STM item (message/event/tool)."""
        await self.store.append_item(item)

    async def pending_items(self, limit: int | None = None) -> list[STMItem]:
        """Fetch pending STM items for consolidation."""
        return await self.store.fetch_pending_items(limit=limit)

    async def clear_pending(self) -> None:
        """Clear STM pending items after consolidation."""
        await self.store.clear_pending_items()

    async def pending_count(self) -> int:
        """Return the count of pending STM items."""
        return await self.store.count_pending_items()
