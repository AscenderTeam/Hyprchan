from __future__ import annotations

from collections import deque
import json
import logging
import os
from importlib import import_module
from typing import Any

from ascender.core import inject
from ascender.core.database import DatabaseEngine

from hyprchan.config.personalization import load_personalization_config

def _resolve_redis_client_type() -> Any:
    try:
        module = import_module("redis.asyncio")
        return getattr(module, "Redis")
    except Exception:

        class _FallbackRedisClient:
            async def delete(self, *args: Any, **kwargs: Any) -> Any:
                return None

            async def rpush(self, *args: Any, **kwargs: Any) -> Any:
                return None

            async def llen(self, *args: Any, **kwargs: Any) -> int:
                return 0

            async def lrange(self, *args: Any, **kwargs: Any) -> list[Any]:
                return []

            async def ltrim(self, *args: Any, **kwargs: Any) -> Any:
                return None

        return _FallbackRedisClient


RedisClient: Any = _resolve_redis_client_type()


from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.kernel.memory.buffer import MemoryBuffer
from hyprchan.core.hyprmemory import HyprMemoryService
from hyprchan.core.hyprmemory.models import ConsolidationReport, DreamEntry, MemoryState
from hyprchan.core.hyprmemory.utils.serialization import state_from_dict, state_to_dict


logger = logging.getLogger(__name__)


class MemoryGate:
    wm_buffer: list[MemoryBuffer]

    def __init__(self) -> None:
        config = load_personalization_config()
        self.enabled = bool(config.memory.enabled)
        self.read_active = bool(config.memory.read_active)
        self.sleep_enabled = bool(config.memory.sleep_enabled)
        self.buffer_limit = max(1, int(config.memory.buffer_limit))
        self.stm_mode = str(config.memory.stm.mode).strip().lower() or "redis"
        self.buffer_key = os.getenv("HYPRMEMORY_BUFFER_KEY", "hyprchan:wm_buffer")
        self.wm_buffer = []
        self._memory_service: Any | None = None
        self._redis: Any | None = None
        self._pending_dream_log: str | None = None
        self._last_error: str | None = None
        self._last_sleep_report: ConsolidationReport | None = None
        self._seen_dream_ids: set[str] = set()
        self._seen_dream_order: deque[str] = deque()
        self._persist_event_types = {
            "communication_message",
            "communication_summon",
            "agent_response",
            "tool_observation",
            "context_compaction",
        }

    def _resolve_redis(self) -> Any | None:
        if self.stm_mode != "redis":
            return None
        if self._redis is not None:
            return self._redis
        fallback = object()
        try:
            client = inject(RedisClient, fallback=fallback)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        if client is fallback:
            return None
        required_methods = ("delete", "rpush", "llen", "lrange", "ltrim")
        if not all(hasattr(client, name) for name in required_methods):
            return None
        self._redis = client
        return client

    def _resolve_memory_service(self) -> Any | None:
        if not self.enabled:
            return None
        if self._memory_service is not None:
            return self._memory_service
        fallback = object()
        try:
            service = inject(HyprMemoryService, fallback=fallback)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            service = fallback
        if service is fallback:
            service = self._build_memory_service_manually()
            if service is None:
                return None
        required_methods = (
            "observe",
            "store_message",
            "recall_working_memory",
            "sleep_consolidate",
            "fetch_dream_log",
        )
        if not all(hasattr(service, name) for name in required_methods):
            self._last_error = "HyprMemoryService provider unresolved"
            return None
        self._memory_service = service
        self._last_error = None
        return service

    def _build_memory_service_manually(self) -> Any | None:
        fallback = object()
        try:
            database = inject(DatabaseEngine, fallback=fallback)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        if database is fallback:
            self._last_error = "DatabaseEngine unresolved for HyprMemoryService"
            return None

        try:
            service = HyprMemoryService(
                database=database,
                logger=logging.getLogger("HyprMemoryService"),
            )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        return service

    def _clamp_buffer(self):
        if len(self.wm_buffer) > self.buffer_limit:
            self.wm_buffer = self.wm_buffer[-self.buffer_limit :]

    @property
    def memory(self) -> Any | None:
        return self._resolve_memory_service()

    async def reset_buffer(self):
        """
        Clears the working-memory buffer.

        NOTE: Make sure that STM works and then call this function.
        """
        redis = self._resolve_redis()
        if redis is not None:
            await redis.delete(self.buffer_key)
            return
        self.wm_buffer.clear()

    async def append_buffer(self, buffer: MemoryBuffer):
        redis = self._resolve_redis()
        if redis is None:
            self.wm_buffer.append(buffer)
            evicted: list[MemoryBuffer] = []  # pyright: ignore[reportRedeclaration]
            if len(self.wm_buffer) > self.buffer_limit:
                evicted = self.wm_buffer[: -self.buffer_limit]
                self.wm_buffer = self.wm_buffer[-self.buffer_limit :]
            if evicted:
                await self._flush_evicted(evicted)
            return

        payload = self._buffer_to_payload(buffer)
        try:
            encoded = json.dumps(payload, ensure_ascii=True)
        except TypeError:
            payload["content"] = str(payload.get("content", ""))
            encoded = json.dumps(payload, ensure_ascii=True)
        await redis.rpush(self.buffer_key, encoded)
        length = int(await redis.llen(self.buffer_key))
        evicted: list[MemoryBuffer] = []
        if length > self.buffer_limit:
            evict_count = length - self.buffer_limit
            raw_evicted = await redis.lrange(self.buffer_key, 0, evict_count - 1)
            await redis.ltrim(self.buffer_key, evict_count, -1)
            evicted = self._decode_buffer_list(raw_evicted)

        if evicted:
            await self._flush_evicted(evicted)

    async def fetch_buffer(self) -> list[MemoryBuffer]:
        redis = self._resolve_redis()
        if redis is None:
            return list(self.wm_buffer)
        raw_items = await redis.lrange(self.buffer_key, 0, -1)
        return self._decode_buffer_list(raw_items)

    async def _flush_evicted(self, evicted: list[MemoryBuffer]) -> None:
        memory = self._resolve_memory_service()
        if memory is None:
            return

        for item in evicted:
            if item.state is None:
                continue
            role = str(item.role or "user").strip().lower() or "user"
            content = item.content
            if not isinstance(content, str):
                try:
                    content = str(content)
                except Exception:
                    continue
            content = content.strip()
            if not content:
                continue
            await memory.store_message(
                role=role,
                content=content,
                state=item.state,
                meta=item.meta,
                kind=item.kind or "chat.message",
            )

    async def buffer_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in await self.fetch_buffer():
            role = str(item.role or "user").strip().lower()
            if role not in {"user", "assistant", "system"}:
                role = "user"
            messages.append({"role": role, "content": item.content})
        return messages

    def _buffer_to_payload(self, buffer: MemoryBuffer) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": buffer.index,
            "role": buffer.role,
            "content": buffer.content,
            "meta": buffer.meta,
            "kind": buffer.kind,
        }
        if buffer.state is not None:
            payload["state"] = state_to_dict(buffer.state)
        return payload

    def _buffer_from_payload(self, payload: dict[str, Any]) -> MemoryBuffer | None:
        if not isinstance(payload, dict):
            return None
        state_payload = payload.get("state")
        state = (
            state_from_dict(state_payload) if isinstance(state_payload, dict) else None
        )
        try:
            index = int(payload.get("index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        return MemoryBuffer(
            index=index,
            role=str(payload.get("role", "user")),
            content=payload.get("content", ""),
            state=state,
            meta=payload.get("meta"),
            kind=str(payload.get("kind", "chat.message") or "chat.message"),
        )

    def _decode_buffer_list(self, raw_items: list[Any]) -> list[MemoryBuffer]:
        items: list[MemoryBuffer] = []
        for raw in raw_items:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                payload = json.loads(raw)
            except Exception:
                continue
            buffer = self._buffer_from_payload(payload)
            if buffer is not None:
                items.append(buffer)
        return items

    async def observe_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        state: MemoryState,
        session_id: str | None = None,
        flags: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        memory = self._resolve_memory_service()
        if memory is None:
            self._last_error = (
                "HyprMemoryService unavailable while HYPRMEMORY_ENABLED=1"
            )
            return
        await memory.observe(
            event_type=event_type,
            payload=payload,
            state=state,
            session_id=session_id,
            flags=flags,
        )

        description = str(payload.get("description", "")).strip()
        if not description or event_type not in self._persist_event_types:
            return

        role = self._role_for_event(event_type=event_type, payload=payload)
        meta = {
            "event_id": int(payload.get("id", 0) or 0),
            "origin": str(payload.get("origin", "")),
            "type": event_type,
        }
        try:
            await memory.store_message(
                role=role,
                content=description,
                state=state,
                meta=meta,
                kind="perception.event",
            )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Memory event persistence failed: %s", exc)

    async def store_message(
        self,
        *,
        role: str,
        content: str,
        state: MemoryState,
        meta: dict[str, Any] | None = None,
        kind: str = "chat.message",
    ) -> None:
        if not self.enabled:
            return
        memory = self._resolve_memory_service()
        if memory is None:
            return
        await memory.store_message(
            role=role,
            content=content,
            state=state,
            meta=meta,
            kind=kind,
        )

    async def build_system_prompt_injection(
        self,
        *,
        query_text: str,
        state: MemoryState,
        phase: Phases | None = None,
    ) -> str:
        if not self.enabled:
            return ""

        parts: list[str] = []
        if self._pending_dream_log:
            parts.append(
                "SLEEP DREAM LOG (ephemeral):\n"
                "This is a fragile dream trace. If you don't restate or reinforce it, "
                "it will fade and be forgotten.\n"
                + self._pending_dream_log.replace("SLEEP DREAM LOG:\n", "").strip()
            )
            self._pending_dream_log = None

        should_read = phase != Phases.ACTIVE or self.read_active
        if should_read and query_text.strip():
            memory = self._resolve_memory_service()
            if memory is not None:
                try:
                    blocks = await memory.recall_working_memory(
                        query_text=query_text.strip(),
                        state=state,
                        phase=phase,
                    )
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    blocks = []

                if blocks:
                    parts.append(
                        "MEMORY RECALL (associative/episodic/emotional):\n"
                        + "\n\n".join(blocks)
                    )

        return "\n\n".join(parts).strip()

    async def sleep_consolidate(self, budget_f: float) -> ConsolidationReport | None:
        if not self.enabled or not self.sleep_enabled:
            return None
        memory = self._resolve_memory_service()
        if memory is None:
            self._last_error = (
                "HyprMemoryService unavailable during sleep consolidation"
            )
            return None

        report = await memory.sleep_consolidate(budget_f=budget_f)
        self._last_sleep_report = report
        return report

    async def fetch_dream_log(self) -> list[DreamEntry]:
        if not self.enabled or not self.sleep_enabled:
            return []
        memory = self._resolve_memory_service()
        if memory is None:
            return []
        dreams = await memory.fetch_dream_log(clear=False, limit=32)
        fresh: list[DreamEntry] = []
        for dream in dreams:
            dream_id = str(getattr(dream, "dream_id", "")).strip()
            if not dream_id:
                continue
            if dream_id in self._seen_dream_ids:
                continue
            self._seen_dream_ids.add(dream_id)
            self._seen_dream_order.append(dream_id)
            while len(self._seen_dream_order) > 256:
                stale = self._seen_dream_order.popleft()
                self._seen_dream_ids.discard(stale)
            fresh.append(dream)
        return fresh

    def queue_dream_log(self, dreams: list[DreamEntry]) -> None:
        if not dreams:
            return
        lines = []
        for entry in dreams:
            ts = entry.ts.isoformat()
            lines.append(f"- [{ts}] {entry.content}")
        if lines:
            self._pending_dream_log = "SLEEP DREAM LOG:\n" + "\n".join(lines)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_sleep_report(self) -> ConsolidationReport | None:
        return self._last_sleep_report

    @staticmethod
    def _role_for_event(*, event_type: str, payload: dict[str, Any]) -> str:
        if bool(payload.get("is_user", False)):
            return "user"
        if (
            event_type == "agent_response"
            or str(payload.get("origin", "")).strip() == "hyprchan_agent"
        ):
            return "assistant"
        return "system"
