import asyncio
import json
import time
from collections import deque
from logging import Logger
from pathlib import Path
from typing import Annotated, Any

from ascender.common import Injectable
from ascender.core import Inject
from hyprchan.core.animations.engine import AnimationEngine
from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.hooks.manager import HookManager
from hyprchan.core.hypraios.kernel.event_compaction import (
    EventCompacter,
    EventCompactionRequest,
    EventCompactionResult,
    GPT5NanoEventCompacter,
)
from hyprchan.core.hypraios.kernel.main_loop import MainKernelLoop
from hyprchan.core.hypraios.kernel.memory.buffer import MemoryBuffer
from hyprchan.core.hypraios.kernel.memory.memory_gate import MemoryGate
from hyprchan.core.hypraios.kernel.memory.stm_payload import build_stm_payload, parse_stm_payload
from hyprchan.core.hypraios.kernel.memory.stm_snapshot import StmSnapshotStore
from hyprchan.core.hypraios.kernel.states import KernelStates
from hyprchan.core.hypraios.linguistic.linguistic_engine import LinguisticEngine
from hyprchan.core.hypraios.mood.phase_engine import PhaseEngine
from hyprchan.core.hypraios.perception.watcher import PerceptionWatcher
from hyprchan.core.hypraios.utils.dynamic_variable import DynamicVariable
from hyprchan.core.hypraios.utils.fault_adaptive_parameter import FaultAdaptiveParameter
from hyprchan.core.hyprmemory import HyprMemoryService
from hyprchan.core.hyprmemory.models import MemoryState
from hyprchan.core.hyprvoice.manager import VoiceManager
from hyprchan.settings import (
    EVENT_COMPACTION_BATCH_SIZE,
    EVENT_COMPACTION_ENABLED,
    EVENT_COMPACTION_KEEP_TAIL,
    EVENT_COMPACTION_MODEL,
    EXTENSIONS_ENABLED,
    VOICE_CONFIG,
)


@Injectable(provided_in="root")
class HyprAIOSKernel:
    MEMORY_FILE = Path(__file__).resolve().parents[5] / "agent_memory.json"

    def __init__(
        self,
        logger: Annotated[Logger, Inject("ASC_LOGGER")],
        animations: AnimationEngine,
        memory_service: HyprMemoryService,
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
            value=0.010, min_delta=0.01, max_delta=0.05, step=0.001, cache_key="k_tok"
        )
        self.k_inf = FaultAdaptiveParameter(
            value=0.25, min_delta=0.25, max_delta=1.5, step=0.05, cache_key="k_inf"
        )
        self.k_self = FaultAdaptiveParameter(
            value=0.50, min_delta=0.4, max_delta=2.5, step=0.05, cache_key="k_self"
        )
        self.k_evt = FaultAdaptiveParameter(
            value=0.05, min_delta=0.05, max_delta=0.2, step=0.01, cache_key="k_evt"
        )
        self.k_sleep = FaultAdaptiveParameter(
            value=1.0, min_delta=0.5, max_delta=2.0, step=0.05, cache_key="k_sleep"
        )
        self.fatigue_inference_divisor = FaultAdaptiveParameter(
            value=15.0,
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
        self.linguistic_engine = LinguisticEngine(memory_service=memory_service)
        self.perception_watcher = PerceptionWatcher(self.main_loop.perception_signal)
        self.memory_gate = MemoryGate(memory_service=memory_service)
        self.hooks = HookManager(self.logger)
        self.voice_manager = VoiceManager(VOICE_CONFIG)

        self._loop_task: asyncio.Task | None = None
        self._sleep_task: asyncio.Task | None = None
        self._booted = False
        self._shutting_down = False
        self._crash_recovered = False

        self.active_reason = "SELF"
        self._self_active_idle_ticks = 0
        self.pending_memory_units = 0.0
        self.memory_step = 1.0
        self.sleep_dt = 0.2

        self.passive_ponder_idle_threshold_sec = 40.0
        self.passive_ponder_interval_sec = self.passive_ponder_idle_threshold_sec
        self.passive_min_inference_gap_sec = 8.0
        self.passive_autonomy_interval_sec = 180.0
        self.passive_signal_amplitude_threshold = 0.9
        now = time.monotonic()
        self.next_passive_ponder_at = now + self.passive_ponder_interval_sec
        self.last_user_input_at = now
        self.last_user_input_epoch = time.time()
        self._last_passive_inference_at = 0.0
        self._last_passive_scanned_event_id = 0
        self._passive_notice_pending = True
        self._last_fatigue_cue_level = 0

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

        self.event_compaction_enabled = bool(EVENT_COMPACTION_ENABLED)
        self.event_compaction_batch_size = max(10, int(EVENT_COMPACTION_BATCH_SIZE))
        self.event_compaction_keep_tail = max(0, int(EVENT_COMPACTION_KEEP_TAIL))
        self.event_compacter: EventCompacter | None = None
        if self.event_compaction_enabled:
            self.event_compacter = GPT5NanoEventCompacter(model=EVENT_COMPACTION_MODEL)

        self._stm_store = StmSnapshotStore(
            base_dir=self.MEMORY_FILE.parent,
            logger=self.logger,
        )

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
        conversation_anchors: list[str] = []
        for event in reversed(inputs):
            if not isinstance(event, dict):
                continue
            description = str(event.get("description", "")).strip()
            if not description:
                continue
            origin = str(event.get("origin", ""))
            event_type = str(event.get("type", ""))
            if (
                bool(event.get("is_user", False))
                or event_type == "communication_message"
                or origin in {"communication_controller", "hyprgram"}
            ):
                conversation_anchors.append(f"user: {description[:220]}")
            elif origin == "hyprchan_agent" or event_type == "agent_response":
                conversation_anchors.append(f"assistant: {description[:220]}")
            if len(conversation_anchors) >= 4:
                break

        if conversation_anchors:
            return " | ".join(reversed(conversation_anchors))[:600]

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
        self.logger.debug(
            "Next passive ponder scheduled in %.2fs",
            self.passive_ponder_interval_sec,
        )

    async def _set_phase(self, next_phase: Phases, reason: str | None = None) -> None:
        prev_phase = self.states.phase
        if prev_phase == next_phase:
            return

        if prev_phase == Phases.PASSIVE:
            await self.hooks.fire(
                "on_passive_leave",
                {
                    "next_phase": next_phase,
                    "reason": reason,
                    "fatigue": float(self.states.f.value),
                },
            )

        self.states.phase = next_phase

        if next_phase == Phases.PASSIVE:
            self._passive_notice_pending = True
            self._remember_event(
                {
                    "id": self._next_event_id(),
                    "timestamp": time.time(),
                    "type": "passive_mode_notice",
                    "description": (
                        "Passive mode entered. Internal thoughts are not auto-delivered unless explicitly communicated."
                    ),
                    "origin": "system_nervous_layer",
                    "amplitude": 0.35,
                    "is_user": False,
                    "activity_level": 0.0,
                    "attention_required": False,
                }
            )
            await self.hooks.fire(
                "on_passive_enter",
                {
                    "prev_phase": prev_phase,
                    "reason": reason,
                    "fatigue": float(self.states.f.value),
                },
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

    @staticmethod
    def _is_protected_event_for_compaction(event: dict[str, Any]) -> bool:
        if bool(event.get("is_user", False)):
            return True

        event_type = str(event.get("type", "")).strip().lower()
        origin = str(event.get("origin", "")).strip().lower()

        protected_types = {
            "communication_message",
            "communication_summon",
            "agent_response",
            "tool_observation",
            "context_compaction",
        }
        protected_origins = {
            "communication_controller",
            "hyprchan_agent",
            "linguistic_tools",
            "memory_compacter",
        }

        if event_type in protected_types:
            return True
        if origin in protected_origins:
            return True
        return False

    def _next_compaction_batch(self) -> tuple[int, int, list[dict[str, Any]]] | None:
        events = list(self.context_events)
        if not events:
            return None

        batch_size = max(10, int(self.event_compaction_batch_size))
        keep_tail = max(0, int(self.event_compaction_keep_tail))
        eligible_end = max(0, len(events) - keep_tail)
        if eligible_end < batch_size:
            return None

        run_start: int | None = None
        run_len = 0

        for idx in range(eligible_end):
            event = events[idx]
            if self._is_protected_event_for_compaction(event):
                run_start = None
                run_len = 0
                continue

            if run_start is None:
                run_start = idx
                run_len = 1
            else:
                run_len += 1

            if run_start is not None and run_len >= batch_size:
                start = run_start
                end = start + batch_size - 1
                return start, end, events[start : end + 1]

        return None

    def _build_compaction_event(
        self,
        *,
        source_events: list[dict[str, Any]],
        summary: EventCompactionResult,
    ) -> dict[str, Any]:
        from_event_id = int(source_events[0].get("id", 0) or 0)
        to_event_id = int(source_events[-1].get("id", 0) or 0)
        amplitude_total = 0.0
        for item in source_events:
            try:
                amplitude_total += max(0.0, float(item.get("amplitude", 0.0) or 0.0))
            except (TypeError, ValueError):
                continue

        return {
            "id": self._next_event_id(),
            "timestamp": time.time(),
            "type": "context_compaction",
            "description": str(summary.summary).strip(),
            "origin": "memory_compacter",
            "amplitude": round(amplitude_total, 6),
            "is_user": False,
            "activity_level": 0.0,
            "attention_required": False,
            "compacted_count": int(summary.compacted_count),
            "from_event_id": from_event_id,
            "to_event_id": to_event_id,
            "compaction_model": str(summary.model or "gpt-5-nano"),
        }

    async def _maybe_compact_context_events(self) -> None:
        if not self.event_compaction_enabled:
            return
        compacter = self.event_compacter
        if compacter is None:
            return

        batches = 0
        while True:
            batch = self._next_compaction_batch()
            if batch is None:
                return

            start, end, source_events = batch
            request = EventCompactionRequest(
                events=source_events,
                max_sentence_chars=220,
            )

            try:
                summary = await compacter.compact(request)
            except Exception as exc:
                self.logger.warning("Event compaction failed: %s", exc)
                return

            if summary is None or not str(summary.summary).strip():
                return

            compacted_event = self._build_compaction_event(
                source_events=source_events,
                summary=summary,
            )

            events = list(self.context_events)
            replaced = events[:start] + [compacted_event] + events[end + 1 :]
            self.context_events = deque(replaced, maxlen=self.context_events.maxlen)
            self._memory_dirty = True
            batches += 1

            if batches >= 8:
                return

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

    def _save_stm_snapshot(self) -> None:
        payload = build_stm_payload(
            context_events=list(self.context_events),
            event_log=list(self.event_log),
            response_log=list(self.response_log),
            last_inference=self.last_inference,
            last_inference_error=self.last_inference_error,
        )
        self._stm_store.save(payload)

    def _load_stm_snapshot(self) -> None:
        data = self._stm_store.load()
        if not data:
            return
        parsed = parse_stm_payload(
            data,
            context_events_maxlen=self.context_events.maxlen,
            event_log_maxlen=self.event_log.maxlen,
            response_log_maxlen=self.response_log.maxlen,
        )
        self.context_events = parsed["context_events"]
        self.event_log = parsed["event_log"]
        self.response_log = parsed["response_log"]
        self.last_inference = parsed["last_inference"]
        self.last_inference_error = parsed["last_inference_error"]

    def _detect_crash_marker(self) -> bool:
        return self._stm_store.detect_crash_marker()

    def _touch_crash_marker(self) -> None:
        self._stm_store.touch_crash_marker()

    def _clear_crash_marker(self) -> None:
        self._stm_store.clear_crash_marker()

    def _mark_crash_recovery(self) -> None:
        if self._crash_recovered:
            return
        self._crash_recovered = True
        self._remember_event(
            {
                "id": self._next_event_id(),
                "timestamp": time.time(),
                "type": "system_notice",
                "description": (
                    "System recovery notice: previous session ended abruptly. "
                    "Hyprchan reports a fainting blackout; short-term memory may feel hazy."
                ),
                "origin": "kernel",
                "amplitude": 0.0,
                "is_user": False,
            }
        )

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
        payload: list[dict[str, Any]] = []
        payload.extend(self._build_passive_internal_cues())

        new_signals, has_urgent_signal = self._collect_meaningful_passive_signals()
        payload.extend(new_signals)

        if payload:
            recap_event = self._build_passive_context_recap()
            if recap_event is not None:
                payload.append(recap_event)

            conversation_anchor = self._build_conversation_anchor_cue()
            if conversation_anchor is not None:
                payload.append(conversation_anchor)

        self.logger.debug(
            "Built passive input payload size=%s meaningful=%s urgent=%s",
            len(payload),
            len(new_signals),
            has_urgent_signal,
        )
        return payload

    def _is_allowed_active_event(self, event: dict[str, Any]) -> bool:
        if not isinstance(event, dict):
            return False

        if bool(event.get("is_user", False)):
            return True

        origin = str(event.get("origin", "")).strip().lower()
        event_type = str(event.get("type", "")).strip().lower()

        if origin in {"communication_controller", "hyprgram", "hyprx"}:
            return True
        if event_type in {
            "communication_message",
            "communication_summon",
            "agent_response",
            "tool_observation",
            "context_compaction",
        }:
            return True

        # Explicitly acquired context (camera/screenshot/memory recall) comes
        # through the linguistic tools observation channel.
        if origin == "linguistic_tools":
            return True

        return False

    def _build_active_inputs(self, *, limit: int = 90) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for event in reversed(self.context_events):
            if not isinstance(event, dict):
                continue
            if not self._is_allowed_active_event(event):
                continue
            filtered.append(dict(event))
            if len(filtered) >= max(1, limit):
                break
        filtered.reverse()
        return filtered

    @staticmethod
    def _strip_event_images(event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        payload.pop("images", None)
        return payload

    @staticmethod
    def _compact_desc(value: Any, *, limit: int = 220) -> str:
        return " ".join(str(value).split())[:limit]

    def _is_low_value_passive_event(self, event: dict[str, Any]) -> bool:
        origin = str(event.get("origin", "")).strip().lower()
        event_type = str(event.get("type", "")).strip().lower()

        if event_type == "perception_visual_snapshot":
            return True
        if origin == "system_nervous_layer" and (
            event_type.startswith("internal_") or event_type == "passive_mode_notice"
        ):
            return True
        if origin in {
            "windows_controller",
            "multimodal_snapshot_source",
            "vision_service",
            "opencv_perception_source",
        }:
            return True
        if event_type.startswith("window_") or event_type.startswith("vision_"):
            return True
        return False

    def _is_meaningful_passive_event(self, event: dict[str, Any]) -> bool:
        if not isinstance(event, dict):
            return False
        if bool(event.get("is_user", False)):
            return False
        if self._is_low_value_passive_event(event):
            return False

        event_type = str(event.get("type", "")).strip().lower()
        origin = str(event.get("origin", "")).strip().lower()
        if event_type in {"communication_message", "communication_summon"}:
            return True
        if origin.startswith("hyprgram") or origin.startswith("extension"):
            return True
        if bool(event.get("attention_required", False)):
            return True

        try:
            amplitude = float(event.get("amplitude", 0.0) or 0.0)
        except (TypeError, ValueError):
            amplitude = 0.0
        return amplitude >= self.passive_signal_amplitude_threshold

    def _collect_meaningful_passive_signals(self) -> tuple[list[dict[str, Any]], bool]:
        new_events: list[dict[str, Any]] = []
        latest_scanned_id = self._last_passive_scanned_event_id
        for event in self.context_events:
            if not isinstance(event, dict):
                continue
            event_id = int(event.get("id", 0) or 0)
            if event_id <= self._last_passive_scanned_event_id:
                continue
            latest_scanned_id = max(latest_scanned_id, event_id)
            new_events.append(event)

        if latest_scanned_id > self._last_passive_scanned_event_id:
            self._last_passive_scanned_event_id = latest_scanned_id

        meaningful: list[dict[str, Any]] = []
        has_urgent_signal = False
        for event in new_events:
            if not self._is_meaningful_passive_event(event):
                continue

            sanitized = self._strip_event_images(event)
            meaningful.append(sanitized)

            event_type = str(event.get("type", "")).strip().lower()
            if event_type in {"communication_message", "communication_summon"} or bool(
                event.get("attention_required", False)
            ):
                has_urgent_signal = True

        return meaningful[-10:], has_urgent_signal

    def _fatigue_cue_level(self) -> int:
        ratio = self.states.f.value / max(self.f_max.value, 1e-6)
        if ratio >= 0.9:
            return 3
        if ratio >= 0.75:
            return 2
        if ratio >= 0.6:
            return 1
        return 0

    def _build_fatigue_cue(self) -> dict[str, Any] | None:
        level = self._fatigue_cue_level()
        previous = self._last_fatigue_cue_level
        self._last_fatigue_cue_level = level
        if level <= previous:
            return None

        descriptions = {
            1: "You are getting a little tired. Pace yourself and stay steady.",
            2: "Fatigue is building. Prioritize light decisions or preparation.",
            3: "You are very tired now. Strongly prefer recovery and low-intensity actions.",
        }
        return {
            "type": "internal_fatigue_cue",
            "amplitude": 0.55 + (level * 0.1),
            "description": descriptions[level],
            "origin": "system_nervous_layer",
        }

    def _build_passive_internal_cues(self) -> list[dict[str, Any]]:
        cues: list[dict[str, Any]] = []
        if self._passive_notice_pending:
            self._passive_notice_pending = False
            cues.append(
                {
                    "type": "passive_mode_notice",
                    "amplitude": 0.8,
                    "description": (
                        "Passive mode is active. Thoughts stay internal unless you explicitly choose to communicate."
                    ),
                    "origin": "system_nervous_layer",
                }
            )

        fatigue_cue = self._build_fatigue_cue()
        if fatigue_cue is not None:
            cues.append(fatigue_cue)
        return cues

    def _build_passive_context_recap(self) -> dict[str, Any] | None:
        snippets: list[str] = []
        for event in reversed(self.context_events):
            if not isinstance(event, dict):
                continue
            if self._is_low_value_passive_event(event):
                continue
            description = self._compact_desc(event.get("description", ""))
            if not description:
                continue
            origin = self._compact_desc(event.get("origin", "unknown"), limit=32)
            snippets.append(f"{origin}: {description}")
            if len(snippets) >= 3:
                break

        if not snippets:
            return None

        snippets.reverse()
        return {
            "type": "context_recap",
            "amplitude": 0.35,
            "description": "Recent meaningful context: " + " | ".join(snippets),
            "origin": "memory_core",
        }

    def _build_conversation_anchor_cue(self) -> dict[str, Any] | None:
        anchors: list[str] = []
        for event in reversed(self.context_events):
            if not isinstance(event, dict):
                continue
            origin = str(event.get("origin", "")).strip().lower()
            event_type = str(event.get("type", "")).strip().lower()
            if origin not in {
                "communication_controller",
                "hyprgram",
                "hyprchan_agent",
            } and event_type not in {
                "communication_message",
                "agent_response",
            }:
                continue
            description = self._compact_desc(event.get("description", ""))
            if not description:
                continue
            role = (
                "user"
                if bool(event.get("is_user", False))
                or origin in {"communication_controller", "hyprgram"}
                else "assistant"
            )
            anchors.append(f"{role}: {description}")
            if len(anchors) >= 4:
                break

        if not anchors:
            return None

        anchors.reverse()
        return {
            "type": "conversation_anchor",
            "amplitude": 0.5,
            "description": "Recent thread anchor: " + " | ".join(anchors),
            "origin": "memory_core",
        }

    def _can_run_passive_cycle_now(self, now: float) -> bool:
        return (
            now - self._last_passive_inference_at
        ) >= self.passive_min_inference_gap_sec

    def _should_emit_autonomy_probe(self, now: float) -> bool:
        if not self._can_run_passive_cycle_now(now):
            return False
        if (now - self._last_passive_inference_at) < self.passive_autonomy_interval_sec:
            return False

        recent_cutoff = time.time() - 900.0
        for event in reversed(self.context_events):
            if not isinstance(event, dict):
                continue
            try:
                timestamp = float(event.get("timestamp", 0.0) or 0.0)
            except (TypeError, ValueError):
                timestamp = 0.0
            if timestamp and timestamp < recent_cutoff:
                break

            event_type = str(event.get("type", "")).strip().lower()
            origin = str(event.get("origin", "")).strip().lower()
            if event_type in {
                "communication_message",
                "agent_response",
                "tool_observation",
            }:
                return True
            if origin in {"communication_controller", "hyprgram", "linguistic_tools"}:
                return True
        return False

    @staticmethod
    def _autonomy_probe_event() -> dict[str, Any]:
        return {
            "type": "autonomy_probe",
            "amplitude": 0.5,
            "description": (
                "Quiet window detected. Review recent context and decide whether any low-risk proactive action is useful."
            ),
            "origin": "cognition_core",
        }

    async def _run_inference_cycle(
        self, inputs: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        self.logger.debug(
            "Inference cycle start phase=%s events=%s",
            self.states.phase.name,
            len(inputs),
        )
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

        if self.states.phase == Phases.ACTIVE:
            mode = "active_self" if self.active_reason == "SELF" else "active_user"
        else:
            mode = "passive"

        inference_payload = await self.hooks.fire(
            "on_ai_inference",
            {
                "phase": self.states.phase,
                "mode": mode,
                "inputs": list(inputs),
                "inference_count": int(self.linguistic_engine.inference_count),
                "model": None,
            },
        )
        updated_inputs = inference_payload.get("inputs", inputs)
        if isinstance(updated_inputs, list):
            inputs = list(updated_inputs)

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
            self.logger.debug("Inference cycle produced no result")
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
            await self._set_phase(Phases.MAINT, reason="fatigue_maint")

        if (
            self.states.phase == Phases.MAINT
            and self.states.f.value < self.f_max.value * 0.65
        ):
            await self._set_phase(Phases.PASSIVE, reason="fatigue_recovery")

        if self.states.f.value >= self.f_max.value:
            self.logger.debug("Fatigue reached max; entering sleep loop")
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

        response_payload = await self.hooks.fire(
            "on_ai_response",
            {
                "phase": self.states.phase,
                "mode": mode,
                "response": dict(payload),
                "latency_ms": None,
                "token_count": token_count,
            },
        )
        payload = dict(response_payload.get("response", payload))

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
        self.logger.debug(
            "Inference cycle complete phase=%s mood=%s tokens=%s",
            payload["phase"],  # pyright: ignore[reportArgumentType]
            payload["mood"],  # pyright: ignore[reportArgumentType]
            payload["total_tokens"],  # pyright: ignore[reportArgumentType]
        )
        return payload  # pyright: ignore[reportReturnType]

    async def communicate(
        self, text: str, *, timeout_sec: float = 20.0
    ) -> dict[str, Any]:
        message = text.strip()
        if not message:
            return {"status": "invalid", "error": "message is empty"}

        self.logger.debug(
            "Communicate called chars=%s timeout=%s", len(message), timeout_sec
        )

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
        memory_service_ready = self.memory_gate.memory is not None
        sleep_report = self.memory_gate.last_sleep_report
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
            "memory_gate": {
                "enabled": self.memory_gate.enabled,
                "sleep_enabled": self.memory_gate.sleep_enabled,
                "service_ready": memory_service_ready,
                "last_error": self.memory_gate.last_error,
                "last_sleep_report": (
                    {
                        "processed_items": sleep_report.processed_items,
                        "episodes_written": sleep_report.episodes_written,
                        "facts_written": sleep_report.facts_written,
                        "edges_written": sleep_report.edges_written,
                        "dreams_written": sleep_report.dreams_written,
                        "fatigue_spent": sleep_report.fatigue_spent,
                    }
                    if sleep_report is not None
                    else None
                ),
            },
        }

    def _register_voice_hook(self) -> None:
        if not self.voice_manager.enabled:
            return

        def _on_ai_response(payload: dict) -> None:
            response = payload.get("response", {})
            if not isinstance(response, dict):
                return
            output = str(response.get("output", "")).strip()
            phase = payload.get("phase")
            if output and isinstance(phase, Phases):
                self.voice_manager.speak(output, phase=phase)

        self.hooks.register("on_ai_response", _on_ai_response, priority=-10)
        self.logger.info("Voice output hook registered (engine=%s)", self.voice_manager._config.engine)

    async def _tool_sleep_digest(self) -> str:
        """Light consolidation triggered by the sleep_digest tool — no phase change."""
        if not self.memory_gate.enabled or not self.memory_gate.sleep_enabled:
            return "memory consolidation is disabled"

        budget = max(self.pending_memory_units, 1.0)
        try:
            report = await self.memory_gate.sleep_consolidate(budget_f=budget)
        except Exception as exc:
            return f"consolidation failed: {type(exc).__name__}: {exc}"

        if report is None:
            return "consolidation produced no report"

        fatigue_reduction = self.k_sleep.value * min(budget, self.states.f.value)
        self.states.f.value = max(0.0, self.states.f.value - fatigue_reduction)
        self.pending_memory_units = max(0.0, self.pending_memory_units - budget)

        self.logger.info(
            "Tool sleep digest complete items=%s episodes=%s facts=%s edges=%s fatigue_spent=%.2f",
            report.processed_items,
            report.episodes_written,
            report.facts_written,
            report.edges_written,
            report.fatigue_spent,
        )
        return (
            f"digest complete: {report.processed_items} items processed, "
            f"{report.episodes_written} episodes, {report.facts_written} facts, "
            f"{report.edges_written} edges formed"
        )

    async def bootup(self):
        if self._booted:
            return

        self._last_memory_save_at = time.monotonic()
        crashed = self._detect_crash_marker()
        self._load_agent_memory()
        self._load_stm_snapshot()
        if self.event_log:
            self._last_passive_scanned_event_id = int(
                self.event_log[-1].get("id", 0) or 0
            )
        if crashed:
            self._mark_crash_recovery()
        self._touch_crash_marker()
        self._schedule_next_passive_ponder()
        self.logger.info("Booting HyprAI OS kernel")
        self._booted = True
        self._shutting_down = False
        self.voice_manager.setup()
        self._register_voice_hook()
        self.linguistic_engine.tool_runtime.set_sleep_digest_callback(
            self._tool_sleep_digest
        )
        await self._set_phase(Phases.PASSIVE, reason="bootup")
        if EXTENSIONS_ENABLED:
            await self._load_enabled_extensions(list(EXTENSIONS_ENABLED))
        await self.start_awake_loop()

    async def _load_enabled_extensions(self, enabled: list[str]) -> None:
        from hyprchan.core.extensions.loader import ExtensionLoader

        loader = ExtensionLoader(self)
        for extension in enabled:
            name = str(extension).strip()
            if not name:
                continue
            try:
                await loader.load(name)
                self.logger.info("Loaded extension: %s", name)
            except Exception as exc:
                self.logger.exception("Extension load failed for %s: %s", name, exc)

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

        await self.voice_manager.teardown()
        self._booted = False
        await self._set_phase(Phases.MAINT, reason="shutdown")
        self._save_stm_snapshot()
        self._maybe_autosave_agent_memory(force=True)
        self._clear_crash_marker()

    async def start_awake_loop(self):
        if self._loop_task and not self._loop_task.done():
            self.logger.debug("Awake loop already running")
            return

        if self.states.phase == Phases.SLEEP:
            await self._set_phase(Phases.PASSIVE, reason="wakeup")
        self.logger.debug("Starting awake loop")
        self._loop_task = asyncio.create_task(self.main_loop.loop(self.on_loop))

    async def start_sleep_loop(self):
        if self.states.phase == Phases.SLEEP:
            self.logger.debug("Sleep loop requested while already sleeping")
            return
        if self._sleep_task and not self._sleep_task.done():
            self.logger.debug("Sleep loop already active")
            return

        await self._set_phase(Phases.SLEEP, reason="sleep")

        await self.main_loop.stop()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        self._sleep_task = asyncio.create_task(self._sleep_worker())
        self.logger.info(
            "Entering sleep loop pending_memory_units=%.2f", self.pending_memory_units
        )
        try:
            self.animations.load_animation("sit.falling_asleep")
        except Exception as exc:
            self.logger.warning("Sleep transition animation unavailable: %s", exc)
            try:
                self.animations.load_animation("sit.sleeping")
            except Exception:
                pass

    def _play_wakeup_animation(self) -> None:
        try:
            self.animations.load_animation("sit.startle_wakeup")
        except Exception as exc:
            self.logger.warning("Wake transition animation unavailable: %s", exc)
            try:
                self.animations.load_animation("sit.idle")
            except Exception:
                pass

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
            self.logger.debug(
                "Sleep worker progress processed=%.2f/%.2f fatigue=%.2f",
                processed,
                total,
                self.states.f.value,
            )
            await asyncio.sleep(self.sleep_dt)

        if consolidation_task is not None:
            try:
                report = await consolidation_task
                if report is not None:
                    self.logger.info(
                        "Sleep consolidation report items=%s episodes=%s facts=%s edges=%s dreams=%s fatigue_spent=%.2f",
                        report.processed_items,
                        report.episodes_written,
                        report.facts_written,
                        report.edges_written,
                        report.dreams_written,
                        report.fatigue_spent,
                    )
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
            await self._set_phase(Phases.PASSIVE, reason="sleep_complete")
            self.logger.info("Sleep loop finished; returning to PASSIVE")
            self._play_wakeup_animation()
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

        self.logger.debug(
            "Record perception id=%s type=%s origin=%s amplitude=%.3f force_active=%s",
            event_id,
            event_type,
            origin,
            amplitude,
            force_active,
        )

        if response_future is not None:
            self._response_waiters[event_id] = response_future

        try:
            signal = await self.perception_watcher.record_event(payload)
        except Exception:
            self._response_waiters.pop(event_id, None)
            raise
        signal["event_id"] = event_id

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
            await self._set_phase(Phases.ACTIVE, reason="force_active")
            self.active_reason = "USER"
            self._self_active_idle_ticks = 0
            self.logger.debug("Force active applied from origin=%s", origin)

            if prior_phase == Phases.SLEEP:
                if self._sleep_task and not self._sleep_task.done():
                    self._sleep_task.cancel()
                    try:
                        await self._sleep_task
                    except asyncio.CancelledError:
                        pass
                self._play_wakeup_animation()
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
            self.logger.debug(
                "Passive fatigue applied weight=%.3f fatigue=%.3f pending_memory=%.3f",
                weight,
                self.states.f.value,
                self.pending_memory_units,
            )

    def _apply_inference_fatigue(self, token_count: int):
        fatigue_delta = (self.k_tok.value * max(token_count, 0)) + self.k_inf.value
        if self.states.phase == Phases.ACTIVE and self.active_reason == "SELF":
            fatigue_delta += self.k_self.value

        divisor = max(1.0, self.fatigue_inference_divisor.value)
        fatigue_delta /= divisor

        self.states.f.value += fatigue_delta
        self.pending_memory_units += max(1.0, token_count / 40.0)
        self.logger.debug(
            "Inference fatigue delta=%.3f tokens=%s fatigue=%.3f pending_memory=%.3f",
            fatigue_delta,
            token_count,
            self.states.f.value,
            self.pending_memory_units,
        )

    async def _apply_idle_dynamics(self):
        self.states.a.value *= 0.92
        self.states.e.value = min(1.0, self.states.e.value + 0.01)

        if self.states.phase == Phases.ACTIVE and self.active_reason == "SELF":
            self._self_active_idle_ticks += 1
            if self._self_active_idle_ticks >= 2:
                await self._set_phase(Phases.PASSIVE, reason="self_idle")
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
            self.logger.debug(
                "Kernel loop tick phase=%s drained_events=%s",
                self.states.phase.name,
                len(events),
            )
            self._apply_passive_fatigue(events)
            await self._maybe_compact_context_events()

            user_events = [
                event
                for event in events
                if str(event.get("origin", "")) == "communication_controller"
            ]

            should_run_passive_ponder = False
            idle_seconds = 0.0
            if self.states.phase == Phases.PASSIVE:
                now = time.monotonic()
                idle_seconds = now - self.last_user_input_at
                live_meaningful = any(
                    self._is_meaningful_passive_event(event) for event in events
                )
                should_run_passive_ponder = live_meaningful or (
                    now >= self.next_passive_ponder_at
                )

            inputs_for_inference: list[dict[str, Any]] | None = None
            if user_events:
                await self._set_phase(Phases.ACTIVE, reason="user_events")
                self.active_reason = "USER"
                self._self_active_idle_ticks = 0
                inputs_for_inference = self._build_active_inputs(limit=90)
                self.logger.debug(
                    "User events detected count=%s; using context window=%s",
                    len(user_events),
                    len(inputs_for_inference),
                )
            elif should_run_passive_ponder:
                inputs_for_inference = self._build_passive_inputs()
                now = time.monotonic()
                can_run_now = self._can_run_passive_cycle_now(now)
                autonomy_probe = False
                if not inputs_for_inference and self._should_emit_autonomy_probe(now):
                    inputs_for_inference = [self._autonomy_probe_event()]
                    autonomy_probe = True
                ponder_payload = await self.hooks.fire(
                    "on_ponder",
                    {
                        "phase": self.states.phase,
                        "idle_seconds": idle_seconds,
                        "next_passive_ponder_at": self.next_passive_ponder_at,
                        "pending_memory_units": self.pending_memory_units,
                        "fatigue": float(self.states.f.value),
                        "context_window_size": len(inputs_for_inference),
                        "inputs": list(inputs_for_inference),
                        "trigger_reason": (
                            "autonomy_probe" if autonomy_probe else "meaningful_signals"
                        ),
                        "can_run_now": can_run_now,
                        "skip": False,
                    },
                )
                if ponder_payload.get("skip"):
                    self.logger.debug("Passive ponder skipped by hook")
                    inputs_for_inference = None
                else:
                    updated_inputs = ponder_payload.get("inputs", inputs_for_inference)
                    if isinstance(updated_inputs, list):
                        inputs_for_inference = list(updated_inputs)
                if inputs_for_inference and not can_run_now:
                    self.logger.debug("Passive ponder throttled by min gap")
                    inputs_for_inference = None
                self.logger.debug("Passive ponder triggered")

            if not inputs_for_inference:
                await self._apply_idle_dynamics()
                self._maybe_autosave_agent_memory()
                return

            response = await self._run_inference_cycle(inputs_for_inference)
            if response is None:
                self.logger.debug("Inference cycle returned None")
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

            if not user_events:
                self._last_passive_inference_at = time.monotonic()

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
                    self.logger.debug(
                        "Delivered response to %s waiter(s)",
                        len(trigger_ids),
                    )

            self._maybe_autosave_agent_memory()
