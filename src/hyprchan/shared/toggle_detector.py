import asyncio
from collections import deque
import time
from typing import Any, Callable

from hyprchan.shared.utils.sensitivity_mapper import sensitivity_to_params


class AsyncToggleDetector:
    """
    Purpose:

    * Detect **abnormally frequent toggles** within a short window.

    Properties:

    * Stateless beyond sliding window
    * Time‑based threshold
    * Reusable after firing

    Output:

    * Boolean `toggle_fired`

    This detector answers only:

    > “Is this event rate unusually high right now?”
    """
    def __init__(
        self, 
        threshold: int, 
        window_sec: float, 
        callback: Callable[..., Any], 
        cooldown: float = 4
    ) -> None:
        self.threshold = threshold
        self.window = window_sec
        self.callback = callback
        self.cooldown = cooldown
        
        self.events = deque()
        self.lock = asyncio.Lock()
        self.cooldown_until = 0
    
    @staticmethod
    def from_sensitivity_param(
        sensitivity: float, 
        callback: Callable[..., Any],
        cooldown: float = 0
    ):
        threshold, window = sensitivity_to_params(sensitivity)
        return AsyncToggleDetector(threshold, window, callback, cooldown)
    
    async def toggle(self):
        async with self.lock:
            now = time.monotonic()
            
            if now < self.cooldown_until:
                return
            
            self.events.append(now)
            
            while self.events and now - self.events[0] > self.window:
                self.events.popleft()
            
            if len(self.events) >= self.threshold:
                asyncio.create_task(self.callback())
                self.events.clear()
                self.cooldown_until = now + self.cooldown
            