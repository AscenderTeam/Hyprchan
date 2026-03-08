import asyncio
import json
import time
from collections import deque
from logging import Logger
from pathlib import Path
from typing import Annotated, Any

from ascender.common import Injectable
from ascender.core import Inject

from core.animations.engine import AnimationEngine
from core.hypraios.constants import Phases
from core.hypraios.kernel.main_loop import MainKernelLoop
from core.hypraios.kernel.memory.buffer import MemoryBuffer
from core.hypraios.kernel.memory.memory_gate import MemoryGate
from core.hypraios.kernel.states import KernelStates
from core.hypraios.linguistic.linguistic_engine import LinguisticEngine
from core.hypraios.mood.phase_engine import PhaseEngine
from core.hypraios.perception.watcher import PerceptionWatcher
from core.hypraios.utils.dynamic_variable import DynamicVariable
from core.hypraios.utils.fault_adaptive_parameter import FaultAdaptiveParameter
from core.hyprmemory.models import MemoryState


@Injectable(provided_in="root")
class HyprAIOSKernel:
    MEMORY_FILE = Path(__file__).resolve().parents[4] / "agent_memory.json"

    def __init__(
        self,
        logger: Annotated[Logger, Inject("ASC_LOGGER")],
        animations: AnimationEngine,
    ) -> None:
        self.logger = logger
        self.animations = animations

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
        self.memory_gate = MemoryGate()

        self._loop_task: asyncio.Task | None = None
        self._sleep_task: asyncio.Task | None = None
        self._booted = False
        self._shutting_down = False

        self.active_reason = "SELF"
        self._self_active_idle_ticks = 0
        self.pending_memory_units = 0.0
        self.memory_step = 1.0
        self.sleep_dt = 0.2

        self.passive_ponder_idle_threshold_sec = 40.0
        self.passive_ponder_interval_sec = self.passive_ponder_idle_threshold_sec
        now = time.monotonic()
        self.next_passive_ponder_at = now + self.passive_ponder_interval_sec
        self.last_user_input_at = now
        self.last_user_input_epoch = time.time()

        self.context_events: deque[dict[str, Any]] = deque(maxlen=256)
        self.event_log: deque[dict[str, Any]] = deque(maxlen=512)
        self.response_log: deque[dict[str, Any]] = deque(maxlen=128)
        self.last_inference: dict[str, Any] | None = None
        self.last_inference_error: str | None = None

        self._event_seq = 0
        self._response_waiters: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._on_loop_lock = asyncio.Lock()
        self._memory_dirty = False
        self._last_memory_save_at = 0.0
        self.memory_autosave_interval_sec = 300.0

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _memory_state(self) -> MemoryState:
        return MemoryState(
            f=float(self.states.f.value),
            v=float(self.states.v.value),
            e=float(self.states.e.value),
            a=float(self.states.a.value),
        )

    @staticmethod
    def _memory_query_text(inputs: list[dict[str, Any]]) -> str:
        for event in reversed(inputs):
            if not isinstance(event, dict):
                continue
            if str(event.get("origin", "")) != "communication_controller":
                continue
            description = str(event.get("description", "")).strip()
            if description:
                return description[:600]

        for event in reversed(inputs):
            if not isinstance(event, dict):
                continue
            description = str(event.get("description", "")).strip()
            if description:
                return description[:400]

        return ""

    def _compute_passive_ponder_interval(self) -> float:
        interval = self.passive_ponder_idle_threshold_sec
        if self.states.phase == Phases.SLEEP:
            interval = 120.0
        return self._clamp(interval, 2.0, 120.0)

    def _schedule_next_passive_ponder(self) -> None:
        self.passive_ponder_interval_sec = self._compute_passive_ponder_interval()
        self.next_passive_ponder_at = (
            time.monotonic() + self.passive_ponder_interval_sec
        )

    def _next_event_id(self) -> int:
        self._event_seq += 1
        return self._event_seq

    def _remember_event(self, event: dict[str, Any]) -> None:
        self.context_events.append(dict(event))
        self.event_log.append(dict(event))
        self._memory_dirty = True

    def _remember_response(self, response: dict[str, Any]) -> None:
        response_payload = dict(response)
        response_id = self._next_event_id()
        response_payload["response_id"] = response_id

        self.response_log.append(response_payload)
        self.last_inference = dict(response_payload)

        response_event = {
            "id": response_id,
            "timestamp": response_payload.get("timestamp", time.time()),
            "type": "agent_response",
            "description": str(response_payload.get("output", "")),
            "origin": "hyprchan_agent",
            "amplitude": 0.0,
            "is_user": False,
            "activity_level": 0.0,
            "attention_required": False,
        }
        self.context_events.append(dict(response_event))
        self.event_log.append(response_event)
        self._memory_dirty = True

    def _agent_memory_payload(self) -> dict[str, Any]:
        return {
            "version": 2,
            "saved_at": time.time(),
            "kernel": {
                "phase": self.states.phase.name,
                "active_reason": self.active_reason,
                "last_user_input_at_epoch": self.last_user_input_epoch,
                "next_passive_ponder_at": self.next_passive_ponder_at,
            },
            "states": {
                "f": self.states.f.value,
                "v": self.states.v.value,
                "e": self.states.e.value,
                "a": self.states.a.value,
            },
        }

    def _save_agent_memory(self) -> None:
        try:
            payload = self._agent_memory_payload()
            self.MEMORY_FILE.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
            )
            self._memory_dirty = False
            self._last_memory_save_at = time.monotonic()
        except Exception as exc:
            self.logger.warning("Failed to save agent memory: %s", exc)

    def _maybe_autosave_agent_memory(self, *, force: bool = False) -> None:
        if not self._memory_dirty:
            return
        if force:
            self._save_agent_memory()
            return

        now = time.monotonic()
        if (now - self._last_memory_save_at) >= self.memory_autosave_interval_sec:
            self._save_agent_memory()

    def _load_agent_memory(self) -> None:
        if not self.MEMORY_FILE.exists():
            return

        try:
            data = json.loads(self.MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            self.logger.warning("Failed to load agent memory: %s", exc)
            return

        if not isinstance(data, dict):
            return

        kernel_payload = data.get("kernel")
        if isinstance(kernel_payload, dict):
            active_reason = kernel_payload.get("active_reason")
            if isinstance(active_reason, str) and active_reason.strip():
                self.active_reason = active_reason.strip().upper()

            last_user_epoch = kernel_payload.get("last_user_input_at_epoch")
            if isinstance(last_user_epoch, (int, float)):
                self.last_user_input_epoch = float(last_user_epoch)
                elapsed = max(0.0, time.time() - self.last_user_input_epoch)
                self.last_user_input_at = max(0.0, time.monotonic() - elapsed)

        states_payload = data.get("states")
        if isinstance(states_payload, dict):
            for key in ("f", "v", "e", "a"):
                raw = states_payload.get(key)
                if raw is None:
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                state_var = getattr(self.states, key, None)
                if state_var is not None:
                    state_var.value = value

        self.logger.info("Loaded agent memory from %s", self.MEMORY_FILE.name)
        self._memory_dirty = False
        self._last_memory_save_at = time.monotonic()

    def _build_passive_inputs(self) -> list[dict[str, Any]]:
        recent_events = list(self.context_events)[-8:]
        compact_recent = []
        for event in recent_events:
            origin = str(event.get("origin", "unknown"))
            event_type = str(event.get("type", "unknown"))
            description = str(event.get("description", ""))
            compact_recent.append(f"{origin}:{event_type}:{description}"[:220])

        recap = (
            " | ".join(compact_recent[-4:]) if compact_recent else "(no recent events)"
        )
        payload: list[dict[str, Any]] = [
            {
                "type": "internal_fatigue_state",
                "amplitude": max(
                    0.1, self.states.f.value / max(self.f_max.value, 1e-6)
                ),
                "description": (
                    f"fatigue={self.states.f.value:.3f}/{self.f_max.value:.0f}, "
                    f"energy={self.states.e.value:.3f}, arousal={self.states.a.value:.3f}"
                ),
                "origin": "system_nervous_layer",
            },
            {
                "type": "internal_mood_state",
                "amplitude": max(0.1, abs(self.states.v.value)),
                "description": (
                    f"valence={self.states.v.value:.3f}, phase={self.states.phase.name}, "
                    f"cooldown_eta={max(0.0, self.next_passive_ponder_at - time.monotonic()):.1f}s"
                ),
                "origin": "system_nervous_layer",
            },
            {
                "type": "context_recap",
                "amplitude": 0.2,
                "description": f"recent_events={recap}",
                "origin": "memory_core",
            },
        ]

        latest_visual_event = next(
            (
                event
                for event in reversed(self.context_events)
                if str(event.get("type", "")) == "perception_visual_snapshot"
                and isinstance(event.get("images"), list)
                and bool(event.get("images"))
            ),
            None,
        )
        if isinstance(latest_visual_event, dict):
            payload.append(dict(latest_visual_event))

        return payload

    async def _run_inference_cycle(
        self, inputs: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        memory_system_prompt = ""
        buffer_messages: list[dict[str, Any]] | None = None
        memory_state: MemoryState | None = None
        if self.memory_gate.enabled:
            memory_state = self._memory_state()
            query_text = self._memory_query_text(inputs)
            try:
                memory_system_prompt = (
                    await self.memory_gate.build_system_prompt_injection(
                        query_text=query_text,
                        state=memory_state,
                        phase=self.states.phase,
                    )
                )
            except Exception as err:
                self.logger.warning("Memory recall failed: %s", err)
                memory_system_prompt = ""

            buffer_messages = await self.memory_gate.buffer_messages()

        try:
            inference_result = await self.linguistic_engine.feed(
                inputs,
                self.states,
                memory_system=memory_system_prompt or None,
                buffer_messages=buffer_messages,
            )
        except RuntimeError as err:
            self.logger.warning("Inference skipped: %s", err)
            self.last_inference_error = str(err)
            return None
        except Exception as err:
            self.logger.warning("Inference failed unexpectedly: %s", err)
            self.last_inference_error = f"{type(err).__name__}: {err}"
            return None

        if not inference_result:
            return None

        self.last_inference_error = None

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

        payload = {
            "timestamp": time.time(),
            "output": str(
                phase_result.get("output", inference_result.get("output", ""))
            ),
            "input": str(inference_result.get("input", "")),
            "phase": self.states.phase.name,
            "active_reason": self.active_reason,
            "total_tokens": token_count,
            "mood": str(phase_result.get("mood", "steady")),
            "delta": float(phase_result.get("delta", 0.0)),
            "rudeness": float(phase_result.get("rudeness", 0.0)),
        }

        tool_events = inference_result.get("tool_events", [])
        if isinstance(tool_events, list):
            for raw_event in tool_events:
                if not isinstance(raw_event, dict):
                    continue
                event_payload = {
                    "id": self._next_event_id(),
                    "timestamp": float(raw_event.get("captured_at", time.time())),
                    "type": str(raw_event.get("type", "tool_observation")),
                    "description": str(raw_event.get("description", "")),
                    "origin": str(raw_event.get("origin", "linguistic_tools")),
                    "amplitude": float(raw_event.get("amplitude", 0.15) or 0.15),
                    "is_user": False,
                    "activity_level": 0.0,
                    "attention_required": False,
                }

                if "tool_name" in raw_event:
                    event_payload["tool_name"] = raw_event.get("tool_name")
                images = raw_event.get("images")
                if isinstance(images, list) and images:
                    event_payload["images"] = images

                self._remember_event(event_payload)

                if (
                    self.memory_gate.enabled
                    and memory_state is not None
                    and str(event_payload.get("description", "")).strip()
                ):
                    try:
                        await self.memory_gate.store_message(
                            role="tool",
                            content=str(event_payload.get("description", "")).strip(),
                            state=memory_state,
                            meta={
                                "event_id": event_payload.get("id"),
                                "origin": event_payload.get("origin"),
                                "type": event_payload.get("type"),
                                "tool_name": event_payload.get("tool_name"),
                            },
                            kind="tool.observation",
                        )
                    except Exception as exc:
                        self.logger.warning("Memory store tool failed: %s", exc)

        self._remember_response(payload)

        if self.memory_gate.enabled and memory_state is not None:
            output_text = str(payload.get("output", "")).strip()
            if output_text:
                try:
                    response_id = (
                        int(self.response_log[-1].get("response_id", 0))
                        if self.response_log
                        else 0
                    )
                    await self.memory_gate.append_buffer(
                        MemoryBuffer(
                            index=response_id,
                            role="assistant",
                            content=output_text,
                            state=memory_state,
                            meta={
                                "response_id": (
                                    self.response_log[-1].get("response_id")
                                    if self.response_log
                                    else None
                                ),
                                "origin": "hyprchan_agent",
                                "type": "agent_response",
                            },
                            kind="chat.message",
                        )
                    )
                except Exception as exc:
                    self.logger.warning("Memory buffer assistant failed: %s", exc)

        self._schedule_next_passive_ponder()
        return payload

    async def communicate(
        self, text: str, *, timeout_sec: float = 20.0
    ) -> dict[str, Any]:
        message = text.strip()
        if not message:
            return {"status": "invalid", "error": "message is empty"}

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[dict[str, Any]] = loop.create_future()
        signal = await self.record_perception(
            event_type="communication_message",
            description=message,
            origin="communication_controller",
            amplitude=1.0,
            force_active=True,
            response_future=waiter,
        )

        self.main_loop.perception_signal()
        if not self._on_loop_lock.locked():
            await self.on_loop()

        event_id = int(signal.get("event_id", 0) or 0)
        try:
            response = await asyncio.wait_for(waiter, timeout=max(1.0, timeout_sec))
            return {
                "status": "ok",
                "event_id": event_id,
                "response": response,
            }
        except asyncio.TimeoutError:
            if event_id in self._response_waiters:
                self._response_waiters.pop(event_id, None)
            return {
                "status": "pending",
                "event_id": event_id,
                "message": "response not ready yet",
            }

    def events_view(self, *, since_id: int = 0, limit: int = 200) -> dict[str, Any]:
        low = max(0, int(since_id))
        cap = max(1, min(1000, int(limit)))
        events = [
            item for item in list(self.event_log) if int(item.get("id", 0) or 0) > low
        ][-cap:]
        responses = [
            item
            for item in list(self.response_log)
            if int(item.get("response_id", 0) or 0) > low
        ][-cap:]
        latest_event_id = int(self.event_log[-1].get("id", 0)) if self.event_log else 0
        return {
            "latest_event_id": latest_event_id,
            "phase": self.states.phase.name,
            "active_reason": self.active_reason,
            "next_passive_ponder_sec": max(
                0.0, self.next_passive_ponder_at - time.monotonic()
            ),
            "events": events,
            "responses": responses,
            "last_inference": self.last_inference,
            "last_inference_error": self.last_inference_error,
        }

    async def bootup(self):
        if self._booted:
            return

        self._last_memory_save_at = time.monotonic()
        self._load_agent_memory()
        self._schedule_next_passive_ponder()
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

        for event_id, waiter in list(self._response_waiters.items()):
            if not waiter.done():
                waiter.cancel()
            self._response_waiters.pop(event_id, None)

        self._booted = False
        self.states.phase = Phases.MAINT
        self._maybe_autosave_agent_memory(force=True)

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
        self.animations.load_animation("sit.falling_asleep")

    async def _sleep_worker(self):
        total = max(self.pending_memory_units, 1.0)
        processed = 0.0
        consolidation_task: asyncio.Task | None = None

        if self.memory_gate.enabled and self.memory_gate.sleep_enabled:
            sleep_budget = max(self.pending_memory_units, 1.0)
            consolidation_task = asyncio.create_task(
                self.memory_gate.sleep_consolidate(budget_f=sleep_budget)
            )

        while not self._shutting_down and self.states.f.value > 0 and processed < total:
            delta_m = min(self.memory_step, total - processed)
            processed += delta_m
            self.pending_memory_units = max(0.0, self.pending_memory_units - delta_m)

            self.states.f.value -= self.k_sleep.value * delta_m
            await asyncio.sleep(self.sleep_dt)

        if consolidation_task is not None:
            try:
                await consolidation_task
            except Exception as exc:
                self.logger.warning("Memory consolidation failed: %s", exc)

        if self.memory_gate.enabled and self.memory_gate.sleep_enabled:
            try:
                dreams = await self.memory_gate.fetch_dream_log()
                self.memory_gate.queue_dream_log(dreams)
            except Exception as exc:
                self.logger.warning("Dream log fetch failed: %s", exc)

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
        metadata: dict[str, Any] | None = None,
        response_future: asyncio.Future[dict[str, Any]] | None = None,
    ):
        prior_phase = self.states.phase
        event_id = self._next_event_id()
        payload = {
            "id": event_id,
            "timestamp": time.time(),
            "type": event_type,
            "description": description,
            "origin": origin,
            "amplitude": amplitude,
            "is_user": origin == "communication_controller",
        }
        if metadata:
            payload.update(metadata)

        if response_future is not None:
            self._response_waiters[event_id] = response_future

        try:
            signal = await self.perception_watcher.record_event(payload)
        except Exception:
            self._response_waiters.pop(event_id, None)
            raise

        event_for_log = {**payload, **signal}
        self._remember_event(event_for_log)

        if self.memory_gate.enabled:
            memory_state = self._memory_state()
            try:
                await self.memory_gate.observe_event(
                    event_type=event_type,
                    payload=event_for_log,
                    state=memory_state,
                )
            except Exception as exc:
                self.logger.warning("Memory observe failed: %s", exc)

            if (
                payload["is_user"]
                and event_type == "communication_message"
                and description.strip()
            ):
                try:
                    await self.memory_gate.append_buffer(
                        MemoryBuffer(
                            index=event_id,
                            role="user",
                            content=description.strip(),
                            state=memory_state,
                            meta={
                                "event_id": event_id,
                                "origin": origin,
                                "type": event_type,
                            },
                            kind="chat.message",
                        )
                    )
                except Exception as exc:
                    self.logger.warning("Memory buffer user failed: %s", exc)

        if payload["is_user"]:
            self.last_user_input_at = time.monotonic()
            self.last_user_input_epoch = time.time()
            self._schedule_next_passive_ponder()

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

        return {**signal, "event_id": event_id}

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
        async with self._on_loop_lock:
            events = await self.perception_watcher.drain_events(limit=128)
            self._apply_passive_fatigue(events)

            user_events = [
                event
                for event in events
                if str(event.get("origin", "")) == "communication_controller"
            ]

            should_run_passive_ponder = False
            if self.states.phase == Phases.PASSIVE:
                now = time.monotonic()
                idle_seconds = now - self.last_user_input_at
                should_run_passive_ponder = (
                    idle_seconds >= self.passive_ponder_idle_threshold_sec
                    and now >= self.next_passive_ponder_at
                )

            inputs_for_inference: list[dict[str, Any]] | None = None
            if user_events:
                self.states.phase = Phases.ACTIVE
                self.active_reason = "USER"
                self._self_active_idle_ticks = 0
                inputs_for_inference = list(self.context_events)[-90:]
            elif should_run_passive_ponder:
                inputs_for_inference = self._build_passive_inputs()

            if not inputs_for_inference:
                await self._apply_idle_dynamics()
                self._maybe_autosave_agent_memory()
                return

            response = await self._run_inference_cycle(inputs_for_inference)
            if response is None:
                if user_events:
                    skipped_ids = sorted(
                        {
                            int(event.get("id", 0) or 0)
                            for event in user_events
                            if int(event.get("id", 0) or 0) > 0
                        }
                    )
                    if skipped_ids:
                        skipped_payload = {
                            "status": "error",
                            "error": self.last_inference_error or "inference skipped",
                            "trigger_event_id": skipped_ids[-1],
                            "trigger_event_ids": skipped_ids,
                        }
                        for skipped_id in skipped_ids:
                            waiter = self._response_waiters.pop(skipped_id, None)
                            if waiter is not None and not waiter.done():
                                waiter.set_result(dict(skipped_payload))

                await self._apply_idle_dynamics()
                self._maybe_autosave_agent_memory()
                return

            if user_events:
                trigger_ids = sorted(
                    {
                        int(event.get("id", 0) or 0)
                        for event in user_events
                        if int(event.get("id", 0) or 0) > 0
                    }
                )

                if trigger_ids:
                    response["trigger_event_id"] = trigger_ids[-1]
                    response["trigger_event_ids"] = trigger_ids
                    response_payload = dict(response)
                    if self.response_log:
                        self.response_log[-1].update(
                            {
                                "trigger_event_id": trigger_ids[-1],
                                "trigger_event_ids": trigger_ids,
                            }
                        )
                        self.last_inference = dict(self.response_log[-1])
                        response_payload = dict(self.response_log[-1])
                        self._memory_dirty = True

                        response_id = int(response_payload.get("response_id", 0) or 0)
                        if response_id > 0:
                            for idx in range(len(self.context_events) - 1, -1, -1):
                                candidate = self.context_events[idx]
                                if int(candidate.get("id", 0) or 0) != response_id:
                                    continue
                                updated = dict(candidate)
                                updated["trigger_event_id"] = trigger_ids[-1]
                                updated["trigger_event_ids"] = trigger_ids
                                self.context_events[idx] = updated
                                break

                    for trigger_id in trigger_ids:
                        waiter = self._response_waiters.pop(trigger_id, None)
                        if waiter is not None and not waiter.done():
                            waiter.set_result(dict(response_payload))

            self._maybe_autosave_agent_memory()
