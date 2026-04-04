import asyncio
import inspect
from typing import Any, Callable

from core.hypraios.perception.activity_detector import AsyncActivityDetector


class PerceptionWatcher:
    def __init__(
        self,
        attention_callback: Callable[..., Any],
        *,
        queue_limit: int = 256,
        activity_detector: AsyncActivityDetector | None = None,
    ) -> None:
        self.attention_callback = attention_callback
        self.queue_limit = max(16, queue_limit)
        self.activity_detector = activity_detector or AsyncActivityDetector()

        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self.queue_limit
        )
        self._lock = asyncio.Lock()

    async def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            event_weight = max(0.0, float(event.get("amplitude", 0.0)))
        except (TypeError, ValueError):
            event_weight = 0.0
        origin = str(event.get("origin", "unknown"))
        activity_level, attention_required = self.activity_detector.register_event(
            event_weight=event_weight,
            origin=origin,
        )

        payload = dict(event)
        payload["activity_level"] = activity_level
        payload["attention_required"] = attention_required

        async with self._lock:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            self._queue.put_nowait(payload)

        if attention_required:
            callback_result = self.attention_callback()
            if inspect.isawaitable(callback_result):
                asyncio.ensure_future(callback_result)

        return {
            "activity_level": activity_level,
            "attention_required": attention_required,
        }

    async def drain_events(self, limit: int = 64) -> list[dict[str, Any]]:
        drain_limit = max(1, limit)
        events: list[dict[str, Any]] = []
        async with self._lock:
            while len(events) < drain_limit:
                try:
                    events.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

        return events
