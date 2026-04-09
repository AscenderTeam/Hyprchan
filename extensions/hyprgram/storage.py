import hashlib
import time
from typing import cast

from hyprchan.core.extensions.storage import ExtensionKV

JsonValue = (
    str
    | int
    | float
    | bool
    | None
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)


class DataStorage:
    kv: ExtensionKV
    _send_dedupe_ttl_sec: float
    _outbound_log_key: str
    _outbound_log_limit: int

    def __init__(self, kv: ExtensionKV) -> None:
        self.kv = kv
        self._send_dedupe_ttl_sec = 120.0
        self._outbound_log_key = "telegram_outbound_log"
        self._outbound_log_limit = 40

    async def add_trusted_user(self, user_id: int) -> dict[str, bool]:
        await self.kv.set(f"trusted_user:{user_id}", True)

        return {"ok": True}

    async def remove_trusted_user(self, user_id: int) -> dict[str, bool]:
        deleted = await self.kv.delete(f"trusted_user:{user_id}")
        return {"ok": deleted}

    async def is_trusted_user(self, user_id: int) -> bool:
        return bool(await self.kv.get(f"trusted_user:{user_id}", False))

    async def has_replied_to_message(self, chat_id: int, message_id: int) -> bool:
        key = f"reply_sent:{chat_id}:{message_id}"
        value = await self.kv.get(key, None)
        return isinstance(value, (int, float))

    async def mark_replied_to_message(self, chat_id: int, message_id: int) -> None:
        key = f"reply_sent:{chat_id}:{message_id}"
        await self.kv.set(key, time.time())

    async def should_send_message(self, chat_id: int, text: str) -> bool:
        normalized = " ".join(text.split()).strip().lower()
        if not normalized:
            return False
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]
        key = f"send_fingerprint:{chat_id}:{digest}"
        now = time.time()
        last_seen_raw = await self.kv.get(key, None)
        last_seen: float | None = None
        if isinstance(last_seen_raw, (int, float)):
            last_seen = float(last_seen_raw)
        elif isinstance(last_seen_raw, str):
            try:
                last_seen = float(last_seen_raw)
            except ValueError:
                last_seen = None
        if last_seen is not None and (now - last_seen) < self._send_dedupe_ttl_sec:
            return False
        await self.kv.set(key, now)
        return True

    async def remember_outbound(
        self,
        *,
        chat_id: int,
        text: str,
        mode: str,
        source_message_id: int | None = None,
    ) -> None:
        normalized_text = " ".join(text.split()).strip()
        if source_message_id is not None:
            await self.mark_replied_to_message(chat_id, source_message_id)

        raw_log = await self.kv.get(self._outbound_log_key, [])
        log_rows: list[dict[str, JsonValue]] = []
        if isinstance(raw_log, list):
            for item in raw_log:
                if not isinstance(item, dict):
                    continue
                row_chat_id = item.get("chat_id")
                row_text = item.get("text")
                row_mode = item.get("mode")
                row_ts = item.get("ts")
                if not isinstance(row_chat_id, int):
                    continue
                if not isinstance(row_text, str):
                    continue
                if not isinstance(row_mode, str):
                    continue
                if not isinstance(row_ts, (int, float)):
                    continue
                row_message_id = item.get("source_message_id")
                if not isinstance(row_message_id, int):
                    row_message_id = None
                log_rows.append(
                    {
                        "chat_id": row_chat_id,
                        "text": row_text,
                        "mode": row_mode,
                        "ts": float(row_ts),
                        "source_message_id": row_message_id,
                    }
                )

        log_rows.append(
            {
                "chat_id": chat_id,
                "text": normalized_text,
                "mode": mode,
                "ts": time.time(),
                "source_message_id": source_message_id,
            }
        )
        payload: list[JsonValue] = [
            cast(JsonValue, row) for row in log_rows[-self._outbound_log_limit :]
        ]
        await self.kv.set(self._outbound_log_key, payload)

    async def build_outbound_context(self, *, limit: int = 4) -> str | None:
        raw_log = await self.kv.get(self._outbound_log_key, [])
        if not isinstance(raw_log, list):
            return None

        entries: list[dict[str, JsonValue]] = []
        for item in raw_log[-max(1, limit) :]:
            if not isinstance(item, dict):
                continue
            row_chat_id = item.get("chat_id")
            row_text = item.get("text")
            row_mode = item.get("mode")
            row_message_id = item.get("source_message_id")
            if (
                not isinstance(row_chat_id, int)
                or not isinstance(row_text, str)
                or not isinstance(row_mode, str)
            ):
                continue
            if not isinstance(row_message_id, int):
                row_message_id = None
            entries.append(
                {
                    "chat_id": row_chat_id,
                    "text": row_text,
                    "mode": row_mode,
                    "source_message_id": row_message_id,
                }
            )

        if not entries:
            return None

        lines = ["Telegram outbound actions already completed recently:"]
        for entry in entries:
            preview = str(entry["text"])[:100]
            target_message = entry["source_message_id"]
            target_text = (
                f" message_id={target_message}" if isinstance(target_message, int) else ""
            )
            lines.append(
                f"- {entry['mode']} chat_id={entry['chat_id']}{target_text}: {preview}"
            )
        lines.append("Avoid repeating the same outbound Telegram response.")
        return "\n".join(lines)
