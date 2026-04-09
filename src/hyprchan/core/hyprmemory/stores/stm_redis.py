from __future__ import annotations

import json

from redis.asyncio import Redis

from hyprchan.core.hyprmemory.interfaces import STMStore
from hyprchan.core.hyprmemory.models import PerceptionTrace, STMItem
from hyprchan.core.hyprmemory.utils.serialization import (
    datetime_from_iso,
    datetime_to_iso,
    state_from_dict,
    state_to_dict,
)


class RedisSTMStore(STMStore):
    """Redis-backed STM store with TTL-bounded retention."""

    def __init__(
        self,
        redis: Redis,
        *,
        namespace: str = "hyprmemory",
        ttl_seconds: int = 6 * 60 * 60,
        max_items: int = 1024,
    ) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.key_traces = f"{namespace}:stm:traces"
        self.key_items = f"{namespace}:stm:items"

    async def append_trace(self, trace: PerceptionTrace) -> None:
        payload = {
            "trace_id": trace.trace_id,
            "ts": datetime_to_iso(trace.ts),
            "type": trace.type,
            "payload": trace.payload,
            "state": state_to_dict(trace.state),
            "session_id": trace.session_id,
            "flags": trace.flags,
        }
        await self.redis.lpush(self.key_traces, json.dumps(payload))
        await self.redis.ltrim(self.key_traces, 0, self.max_items)
        await self.redis.expire(self.key_traces, self.ttl_seconds)

    async def append_item(self, item: STMItem) -> None:
        payload = {
            "item_id": item.item_id,
            "ts": datetime_to_iso(item.ts),
            "kind": item.kind,
            "content": item.content,
            "meta": item.meta,
            "state": state_to_dict(item.state),
            "salience": item.salience,
        }
        await self.redis.lpush(self.key_items, json.dumps(payload))
        await self.redis.ltrim(self.key_items, 0, self.max_items)
        await self.redis.expire(self.key_items, self.ttl_seconds)

    async def fetch_pending_items(self, limit: int | None = None) -> list[STMItem]:
        end = -1 if limit is None else max(0, limit - 1)
        raw_items = await self.redis.lrange(self.key_items, 0, end)
        items: list[STMItem] = []
        for raw in raw_items:
            payload = json.loads(raw)
            items.append(
                STMItem(
                    item_id=payload["item_id"],
                    ts=datetime_from_iso(payload["ts"]),
                    kind=payload["kind"],
                    content=payload["content"],
                    meta=payload.get("meta", {}),
                    state=state_from_dict(payload.get("state", {})),
                    salience=float(payload.get("salience", 0.0)),
                )
            )
        return items

    async def clear_pending_items(self) -> None:
        await self.redis.delete(self.key_items)

    async def count_pending_items(self) -> int:
        return int(await self.redis.llen(self.key_items))
