from __future__ import annotations

import os
from typing import Any

from ascender.core import inject

from core.hypraios.constants import Phases
from core.hypraios.kernel.memory.buffer import MemoryBuffer
from core.hyprmemory import HyprMemoryService
from core.hyprmemory.models import DreamEntry, MemoryState


class MemoryGate:
    wm_buffer: list[MemoryBuffer]

    def __init__(self) -> None:
        self.enabled = os.getenv("HYPRMEMORY_ENABLED", "0").strip().lower() == "1"
        self.read_active = (
            os.getenv("HYPRMEMORY_READ_ACTIVE", "0").strip().lower() == "1"
        )
        self.sleep_enabled = (
            os.getenv("HYPRMEMORY_SLEEP_ENABLED", "0").strip().lower() == "1"
        )
        self.buffer_limit = max(1, int(os.getenv("HYPRMEMORY_BUFFER_LIMIT", "3")))
        self.wm_buffer = []
        self._memory_service: HyprMemoryService | None = None
        self._pending_dream_log: str | None = None
        self._last_error: str | None = None

    def _resolve_memory_service(self) -> HyprMemoryService | None:
        if not self.enabled:
            return None
        if self._memory_service is not None:
            return self._memory_service
        fallback = object()
        try:
            service = inject(HyprMemoryService, fallback=fallback)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        if service is fallback:
            return None
        self._memory_service = service
        return service

    def _clamp_buffer(self):
        if len(self.wm_buffer) > self.buffer_limit:
            self.wm_buffer = self.wm_buffer[-self.buffer_limit :]

    @property
    def memory(self) -> HyprMemoryService | None:
        return self._resolve_memory_service()

    def reset_buffer(self):
        """
        Clears the working-memory buffer.

        NOTE: Make sure that STM works and then call this function.
        """
        self.wm_buffer.clear()

    def append_buffer(self, buffer: MemoryBuffer):
        self.wm_buffer.append(buffer)
        self._clamp_buffer()

    def fetch_buffer(self):
        return list(self.wm_buffer)

    def buffer_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in self.wm_buffer:
            role = str(item.role or "user").strip().lower()
            if role not in {"user", "assistant", "system"}:
                role = "user"
            messages.append({"role": role, "content": item.content})
        return messages

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
            return
        await memory.observe(
            event_type=event_type,
            payload=payload,
            state=state,
            session_id=session_id,
            flags=flags,
        )

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
            parts.append(self._pending_dream_log)
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
                        "HYPRMEMORY RECALL (associative/episodic/emotional):\n"
                        + "\n\n".join(blocks)
                    )

        return "\n\n".join(parts).strip()

    async def sleep_consolidate(self, budget_f: float) -> None:
        if not self.enabled or not self.sleep_enabled:
            return
        memory = self._resolve_memory_service()
        if memory is None:
            return
        await memory.sleep_consolidate(budget_f=budget_f)

    async def fetch_dream_log(self) -> list[DreamEntry]:
        if not self.enabled or not self.sleep_enabled:
            return []
        memory = self._resolve_memory_service()
        if memory is None:
            return []
        return await memory.fetch_dream_log(clear=True, limit=8)

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
