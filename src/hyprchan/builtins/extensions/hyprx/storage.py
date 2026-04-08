from __future__ import annotations

from datetime import UTC, datetime
import time

from hyprchan import ExtensionKV


class HyprXStorage:
    def __init__(self, kv: ExtensionKV) -> None:
        self.kv = kv

    @staticmethod
    def _day_stamp() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    async def get_last_mention_id(self) -> int | None:
        raw = await self.kv.get("mentions:last_seen_id", None)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        return None

    async def set_last_mention_id(self, mention_id: int) -> None:
        await self.kv.set("mentions:last_seen_id", int(mention_id))

    async def should_poll_mentions(self, cooldown_sec: float) -> bool:
        raw = await self.kv.get("mentions:last_poll_ts", None)
        last_poll: float | None = None
        if isinstance(raw, (int, float)):
            last_poll = float(raw)
        elif isinstance(raw, str):
            try:
                last_poll = float(raw)
            except ValueError:
                last_poll = None
        if last_poll is None:
            return True
        return (time.time() - last_poll) >= cooldown_sec

    async def mark_mentions_polled(self) -> None:
        await self.kv.set("mentions:last_poll_ts", time.time())

    async def has_replied_to_tweet(self, tweet_id: int) -> bool:
        raw = await self.kv.get(f"twitter_reply_sent:{tweet_id}", None)
        return isinstance(raw, (int, float))

    async def mark_replied_to_tweet(self, tweet_id: int) -> None:
        await self.kv.set(f"twitter_reply_sent:{tweet_id}", time.time())

    async def daily_count(self, bucket: str) -> int:
        raw = await self.kv.get(f"daily:{bucket}:{self._day_stamp()}", 0)
        if isinstance(raw, int):
            return max(0, raw)
        if isinstance(raw, str) and raw.isdigit():
            return max(0, int(raw))
        return 0

    async def claim_daily_quota(self, bucket: str, limit: int) -> bool:
        if limit <= 0:
            return False
        key = f"daily:{bucket}:{self._day_stamp()}"
        current = await self.daily_count(bucket)
        if current >= limit:
            return False
        await self.kv.set(key, current + 1)
        return True

    async def should_probe_autopost(self, cooldown_sec: float) -> bool:
        raw = await self.kv.get("autopost:last_probe_ts", None)
        last_probe: float | None = None
        if isinstance(raw, (int, float)):
            last_probe = float(raw)
        elif isinstance(raw, str):
            try:
                last_probe = float(raw)
            except ValueError:
                last_probe = None
        if last_probe is None:
            return True
        return (time.time() - last_probe) >= cooldown_sec

    async def mark_autopost_probe(self) -> None:
        await self.kv.set("autopost:last_probe_ts", time.time())
