import asyncio
import time
from typing import Any, Callable
from hyprchan.core.hypraios.utils.dynamic_variable import DynamicVariable
from hyprchan.core.hypraios.utils.fault_adaptive_parameter import FaultAdaptiveParameter
from hyprchan.core.hypraios.utils.flag_variable import FlagVariable


class MainKernelLoop:
    def __init__(
        self, gamma: FaultAdaptiveParameter, rho: FaultAdaptiveParameter
    ) -> None:
        self.gamma = gamma
        self.rho = rho

        self.cooldown_floor = 0.05

        self.cooldown = DynamicVariable(value=self.cooldown_floor, max_val=10)
        # Cooldown is regulated by specific formula for each cases
        # After inference: loop_dt * gamma
        # On perception signal: max(cooldown_floor, cooldown * ρ (this shit is rho))
        self.loop_dt = DynamicVariable(value=0.05, max_val=1, min_val=0.005)

        self._running = FlagVariable(False)
        self._last_tick = None
        self._wake_event = asyncio.Event()

    def tick(self, now: float | None = None):
        # 1. We calculate current time if 'now' parameter is not defined.
        # NOTE: The tick is time-sensitive and its function - time-gating.
        # It corrects cooldown and defines is MainKernelLoop is allowed to do work right now
        if now is None:
            now = time.monotonic()

        # 2. We update the `_last_tick` parameter in accordance with `now` variable.
        if self._last_tick is None:
            self._last_tick = now
            return False

        # 3. We measure the delta time from when _last_tick was started.
        dt = now - self._last_tick
        self._last_tick = now

        # 4. The cooldown value subtracted with delta-time
        # That happens per tick if it is higher than 0.
        if self.cooldown.value > 0:
            self.cooldown.value -= dt
            return self.cooldown.value <= 0

        return True

    async def loop(self, callback: Callable[..., Any]):
        await self._running.aset(True)
        self._last_tick = time.monotonic()

        while self._running.value:
            if self.tick():
                await callback()

                self.cooldown.value = self.loop_dt.value * self.gamma.value

            sleep_time = min(self.cooldown.value, self.loop_dt.value)
            sleep_time = max(sleep_time, self.cooldown_floor)

            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                pass
            finally:
                self._wake_event.clear()

    async def stop(self):
        await self._running.aset(False)
        self._wake_event.set()

    def perception_signal(self):
        self.cooldown.value = max(
            self.cooldown_floor, self.cooldown.value * self.rho.value
        )

        self._wake_event.set()
