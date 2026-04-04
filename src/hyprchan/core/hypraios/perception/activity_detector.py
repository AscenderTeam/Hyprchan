from collections import Counter, deque
import time


class AsyncActivityDetector:
    """
    Detect sustained activity pressure over a longer moving window.
    """

    def __init__(
        self, window_sec: float = 8.0, attention_threshold: float = 6.0
    ) -> None:
        self.window_sec = max(1.0, window_sec)
        self.attention_threshold = max(0.1, attention_threshold)
        self._events: deque[tuple[float, float, str]] = deque()

    def register_event(self, *, event_weight: float, origin: str) -> tuple[float, bool]:
        now = time.monotonic()
        weight = max(0.0, float(event_weight))
        self._events.append((now, weight, origin))

        while self._events and now - self._events[0][0] > self.window_sec:
            self._events.popleft()

        total_weight = sum(item[1] for item in self._events)
        origin_counts = Counter(item[2] for item in self._events)
        repeated_origin_bonus = 0.0
        if origin_counts:
            repeated_origin_bonus = max(origin_counts.values()) * 0.25

        pressure = total_weight + repeated_origin_bonus
        activity_level = min(1.0, pressure / self.attention_threshold)
        attention_required = pressure >= self.attention_threshold
        return activity_level, attention_required
