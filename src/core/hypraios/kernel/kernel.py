import asyncio
from logging import Logger
from typing import Annotated

from ascender.common import Injectable
from ascender.core import Inject

from core.hypraios.constants import Phases
from core.hypraios.kernel.main_loop import MainKernelLoop
from core.hypraios.kernel.states import KernelStates
from core.hypraios.linguistic.linguistic_engine import LinguisticEngine
from core.hypraios.mood.phase_engine import PhaseEngine
from core.hypraios.perception.watcher import PerceptionWatcher
from core.hypraios.utils.dynamic_variable import DynamicVariable
from core.hypraios.utils.fault_adaptive_parameter import FaultAdaptiveParameter


@Injectable(provided_in="root")
class HyprAIOSKernel:
    def __init__(self, logger: Annotated[Logger, Inject("ASC_LOGGER")]) -> None:
        self.logger = logger

        self.gamma = FaultAdaptiveParameter(
            value=1.0, min_delta=0.5, max_delta=3.0, step=0.05, cache_key="gamma"
        )
        self.rho = FaultAdaptiveParameter(
            value=0.4, min_delta=0.1, max_delta=0.9, step=0.05, cache_key="rho"
        )
        self.f_max = FaultAdaptiveParameter(
            value=100, max_delta=0.25, min_delta=0.5, step=0.002
        )

        self.k_tok = FaultAdaptiveParameter(
            value=0.015, min_delta=0.01, max_delta=0.05, step=0.001, cache_key="k_tok"
        )
        self.k_inf = FaultAdaptiveParameter(
            value=0.4, min_delta=0.25, max_delta=1.5, step=0.05, cache_key="k_inf"
        )
        self.k_self = FaultAdaptiveParameter(
            value=0.8, min_delta=0.4, max_delta=2.5, step=0.05, cache_key="k_self"
        )
        self.k_evt = FaultAdaptiveParameter(
            value=0.08, min_delta=0.05, max_delta=0.2, step=0.01, cache_key="k_evt"
        )
        self.k_sleep = FaultAdaptiveParameter(
            value=1.0, min_delta=0.5, max_delta=2.0, step=0.05, cache_key="k_sleep"
        )
        self.fatigue_inference_divisor = FaultAdaptiveParameter(
            value=10.0,
            min_delta=1.0,
            max_delta=20.0,
            step=1.0,
            cache_key="fatigue_inference_divisor",
        )

        self.main_loop = MainKernelLoop(self.gamma, self.rho)

        self.states = KernelStates(
            f=DynamicVariable(value=0, min_val=0, max_val=self.f_max.value),
            v=DynamicVariable(value=0.35, min_val=-1, max_val=1, clamp_on_write=True),
            e=DynamicVariable(value=0.65, min_val=0, max_val=1, clamp_on_write=True),
            a=DynamicVariable(value=0.2, min_val=0, max_val=1, clamp_on_write=True),
            c=self.main_loop.cooldown,
            phase=Phases.PASSIVE,
        )

        self.phase_engine = PhaseEngine(self.states)
        self.linguistic_engine = LinguisticEngine()
        self.perception_watcher = PerceptionWatcher(self.main_loop.perception_signal)

        self._loop_task: asyncio.Task | None = None
        self._sleep_task: asyncio.Task | None = None
        self._booted = False
        self._shutting_down = False

        self.active_reason = "SELF"
        self._self_active_idle_ticks = 0
        self.pending_memory_units = 0.0
        self.memory_step = 1.0
        self.sleep_dt = 0.2

    async def bootup(self):
        if self._booted:
            return

        self.logger.info("Booting HyprAI OS kernel")
        self._booted = True
        self._shutting_down = False
        self.states.phase = Phases.PASSIVE
        await self.start_awake_loop()

    async def shutdown(self):
        self._shutting_down = True
        self.logger.info("Shutting down HyprAI OS kernel")

        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
            try:
                await self._sleep_task
            except asyncio.CancelledError:
                pass

        await self.main_loop.stop()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        self._booted = False
        self.states.phase = Phases.MAINT

    async def start_awake_loop(self):
        if self._loop_task and not self._loop_task.done():
            return

        if self.states.phase == Phases.SLEEP:
            self.states.phase = Phases.PASSIVE
        self._loop_task = asyncio.create_task(self.main_loop.loop(self.on_loop))

    async def start_sleep_loop(self):
        if self.states.phase == Phases.SLEEP:
            return
        if self._sleep_task and not self._sleep_task.done():
            return

        self.states.phase = Phases.SLEEP

        await self.main_loop.stop()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        self._sleep_task = asyncio.create_task(self._sleep_worker())

    async def _sleep_worker(self):
        total = max(self.pending_memory_units, 1.0)
        processed = 0.0

        while not self._shutting_down and self.states.f.value > 0 and processed < total:
            delta_m = min(self.memory_step, total - processed)
            processed += delta_m
            self.pending_memory_units = max(0.0, self.pending_memory_units - delta_m)

            self.states.f.value -= self.k_sleep.value * delta_m
            await asyncio.sleep(self.sleep_dt)

        self.phase_engine.reset_after_sleep()

        if not self._shutting_down:
            self.states.phase = Phases.PASSIVE
            await self.start_awake_loop()

    async def record_perception(
        self,
        *,
        event_type: str,
        description: str,
        origin: str,
        amplitude: float,
        force_active: bool = False,
    ):
        prior_phase = self.states.phase
        signal = await self.perception_watcher.record_event(
            {
                "type": event_type,
                "description": description,
                "origin": origin,
                "amplitude": amplitude,
            }
        )

        if force_active:
            self.states.phase = Phases.ACTIVE
            self.active_reason = "USER"
            self._self_active_idle_ticks = 0

            if prior_phase == Phases.SLEEP:
                if self._sleep_task and not self._sleep_task.done():
                    self._sleep_task.cancel()
                    try:
                        await self._sleep_task
                    except asyncio.CancelledError:
                        pass
                await self.start_awake_loop()

        return signal

    def _apply_passive_fatigue(self, events: list[dict]):
        weight = 0.0
        for event in events:
            try:
                weight += max(0.0, float(event.get("amplitude", 0.0)))
            except (TypeError, ValueError):
                continue

        if weight > 0:
            self.states.f.value += self.k_evt.value * weight
            self.pending_memory_units += weight

    def _apply_inference_fatigue(self, token_count: int):
        fatigue_delta = (self.k_tok.value * max(token_count, 0)) + self.k_inf.value
        if self.states.phase == Phases.ACTIVE and self.active_reason == "SELF":
            fatigue_delta += self.k_self.value

        divisor = max(1.0, self.fatigue_inference_divisor.value)
        fatigue_delta /= divisor

        self.states.f.value += fatigue_delta
        self.pending_memory_units += max(1.0, token_count / 40.0)

    async def _apply_idle_dynamics(self):
        self.states.a.value *= 0.92
        self.states.e.value = min(1.0, self.states.e.value + 0.01)

        if self.states.phase == Phases.ACTIVE and self.active_reason == "SELF":
            self._self_active_idle_ticks += 1
            if self._self_active_idle_ticks >= 2:
                self.states.phase = Phases.PASSIVE
                self._self_active_idle_ticks = 0
                self.active_reason = "SELF"

        if self.states.f.value >= self.f_max.value:
            await self.start_sleep_loop()

    async def on_loop(self):
        """
        Called on each kernel loop cycle.
        """
        events = await self.perception_watcher.drain_events(limit=128)
        self._apply_passive_fatigue(events)

        if self.states.phase == Phases.PASSIVE:
            high_pressure = any(
                bool(event.get("attention_required")) for event in events
            )
            if high_pressure:
                self.states.phase = Phases.ACTIVE
                self.active_reason = "SELF"
                self._self_active_idle_ticks = 0

        if not events:
            await self._apply_idle_dynamics()
            return

        try:
            inference_result = await self.linguistic_engine.feed(events, self.states)
        except RuntimeError as err:
            self.logger.warning("Inference skipped: %s", err)
            await self._apply_idle_dynamics()
            return

        if not inference_result:
            await self._apply_idle_dynamics()
            return

        phase_result = await self.phase_engine.after_inference(
            input=inference_result["input"],
            output=inference_result["output"],
        )

        self.active_reason = str(phase_result.get("active_reason", self.active_reason))
        token_count = int(inference_result.get("total_tokens", 0))
        self._apply_inference_fatigue(token_count)

        if (
            self.states.f.value >= self.f_max.value * 0.85
            and self.states.phase != Phases.SLEEP
        ):
            self.states.phase = Phases.MAINT

        if (
            self.states.phase == Phases.MAINT
            and self.states.f.value < self.f_max.value * 0.65
        ):
            self.states.phase = Phases.PASSIVE

        if self.states.f.value >= self.f_max.value:
            await self.start_sleep_loop()
