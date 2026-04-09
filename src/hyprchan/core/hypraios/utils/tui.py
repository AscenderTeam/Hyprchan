from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import random
from queue import Empty, Queue
import threading
import time
from typing import Deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.kernel.states import KernelStates
from hyprchan.core.hypraios.linguistic.inference_engine import InferenceEngine
from hyprchan.core.hypraios.linguistic.linguistic_engine import LinguisticEngine
from hyprchan.core.hypraios.linguistic.passive_inference import SYSTEM_INTRO_MESSAGE
from hyprchan.core.hypraios.mood.phase_engine import PhaseEngine
from hyprchan.core.hypraios.utils.dynamic_variable import DynamicVariable


@dataclass
class TurnDiagnostics:
    turn: int = 0
    timestamp: str = "-"
    phase_before: str = "PASSIVE"
    phase_after: str = "PASSIVE"
    active_reason: str = "USER"
    model: str = "gpt-4o-mini"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    fatigue_delta: float = 0.0
    interaction_delta: float = 0.0
    rudeness: float = 0.0
    mood: str = "neutral"
    bias_profile: str = "neutral"
    token_bias_count: int = 0
    note: str = "Session initialized"


class HyprRichTUI:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        max_history: int = 16,
        screen_mode: bool = False,
    ) -> None:
        self.console = Console()

        self.states = KernelStates(
            f=DynamicVariable(value=0.0, min_val=0.0, max_val=100.0),
            v=DynamicVariable(
                value=0.35, min_val=-1.0, max_val=1.0, clamp_on_write=True
            ),
            e=DynamicVariable(
                value=0.65, min_val=0.0, max_val=1.0, clamp_on_write=True
            ),
            a=DynamicVariable(
                value=0.20, min_val=0.0, max_val=1.0, clamp_on_write=True
            ),
            c=DynamicVariable(
                value=0.05, min_val=0.0, max_val=120.0, clamp_on_write=True
            ),
            phase=Phases.PASSIVE,
        )

        self.k_tok = 0.015
        self.k_inf = 0.40
        self.k_self = 0.80
        self.fatigue_inference_divisor = 10.0
        self.f_max = 100.0

        self.linguistic_engine = LinguisticEngine()
        self.linguistic_engine.inference_engine = InferenceEngine(model=model)
        self.phase_engine = PhaseEngine(self.states)

        self.model = model
        self.screen_mode = screen_mode
        self.turn = 0
        self.status_line = "Ready"
        self.chat_lines: Deque[str] = deque(maxlen=200)
        self.chat_window_lines = 40
        self.chat_scroll_offset = 0
        self.chat_auto_follow = True
        self.context_messages: Deque[dict[str, str]] = deque(maxlen=max_history)
        self.last_diag = TurnDiagnostics(model=model)
        self._last_bias_profile = "neutral"
        self._last_token_bias_count = 0
        self.passive_ponder_idle_threshold_sec = 40.0
        self.passive_ponder_interval_sec = self.passive_ponder_idle_threshold_sec
        self.next_passive_ponder_at = (
            time.monotonic() + self.passive_ponder_interval_sec
        )
        self.last_user_input_at = time.monotonic()
        self._input_queue: Queue[str] = Queue(maxsize=64)
        self._stop_input = threading.Event()
        self._input_thread: threading.Thread | None = None

        self.pending_memory_units = 0.0
        self.k_sleep = 1.0
        self.sleep_memory_step = 2.0
        self.sleep_step_interval_sec = 0.4
        self.sleep_fatigue_reduction_per_inference = 20.0
        self.sleep_active = False
        self.sleep_memory_total = 0.0
        self.sleep_memory_processed = 0.0
        self.sleep_next_step_at = 0.0
        self.sleep_frequency_penalty = 1.95
        self.sleep_presence_penalty = 1.30
        self.sleep_recent_dreams: Deque[str] = deque(maxlen=8)
        self.sleep_dream_archive: Deque[str] = deque(maxlen=24)
        self.sleep_context_messages: Deque[dict[str, str]] = deque(maxlen=24)
        self.sleep_retained_fragments = 2

        self._append_system(
            "HyprAI OS rich session online. Commands: /help, /state, /memory, /scroll, /follow, /clear, /quit"
        )
        self._append_system(SYSTEM_INTRO_MESSAGE)
        self._schedule_next_passive_ponder()

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _compute_passive_ponder_interval(self) -> float:
        interval = self.passive_ponder_idle_threshold_sec
        if self.states.phase == Phases.SLEEP:
            interval = 120.0

        return self._clamp(interval, 2.0, 120.0)

    def _schedule_next_passive_ponder(self):
        self.passive_ponder_interval_sec = self._compute_passive_ponder_interval()
        self.next_passive_ponder_at = (
            time.monotonic() + self.passive_ponder_interval_sec
        )

    def _seconds_until_next_passive_ponder(self) -> float:
        if self.states.phase == Phases.SLEEP:
            return 0.0
        return max(0.0, self.next_passive_ponder_at - time.monotonic())

    def _build_day_recap_for_sleep(self, limit: int = 8) -> str:
        items = list(self.context_messages)[-limit:]
        if not items:
            return "- quiet day: no major interaction records yet"

        recap_lines: list[str] = []
        for item in items:
            role = str(item.get("role", "unknown")).lower()
            content = str(item.get("content", "")).replace("\n", " ").strip()
            if not content:
                continue
            short = content[:180]
            recap_lines.append(f"- {role}: {short}")

        if not recap_lines:
            return "- interaction records present but unavailable for recap"
        return "\n".join(recap_lines)

    def _seed_sleep_story_context(self, cause: str):
        self.sleep_context_messages.clear()
        day_recap = self._build_day_recap_for_sleep(limit=10)
        trait_snapshot = self.linguistic_engine.persona_memory.trait_snapshot()
        self.sleep_context_messages.append(
            {
                "role": "user",
                "content": (
                    "Sleep story seed.\n"
                    f"cause={cause}\n"
                    f"traits={trait_snapshot}\n"
                    "day_recap:\n"
                    f"{day_recap}\n"
                    "Continue one coherent dream storyline across sleep steps; evolve it gradually from the day recap."
                ),
            }
        )

    def _retain_sleep_fragments_into_awake_context(self):
        if not self.sleep_dream_archive:
            return

        sample_size = min(self.sleep_retained_fragments, len(self.sleep_dream_archive))
        chosen = random.sample(list(self.sleep_dream_archive), sample_size)
        for fragment in chosen:
            compact = fragment.replace("\n", " ").strip()[:220]
            self.context_messages.append(
                {
                    "role": "system",
                    "content": f"Sleep memory fragment retained: {compact}",
                }
            )

        self._append_system(
            (
                "<system>Wake memory retention complete: "
                f"{sample_size} sleep fragments kept for future context. "
                "One-way telemetry.</system>"
            )
        )

    def _enter_sleep(self, cause: str):
        if not self.sleep_active:
            self.sleep_active = True
            self.sleep_memory_total = max(self.pending_memory_units, 1.0)
            self.sleep_memory_processed = 0.0
            self.sleep_next_step_at = time.monotonic() + 0.03
            self.sleep_recent_dreams.clear()
            self.sleep_dream_archive.clear()
            self._seed_sleep_story_context(cause)
            self._append_system(
                (
                    "<system>SLEEP entered: memory consolidation started. "
                    f"cause={cause}, backlog={self.sleep_memory_total:.1f} units. "
                    "One-way telemetry.</system>"
                )
            )
        self.states.phase = Phases.SLEEP
        self.status_line = "Sleep consolidation in progress"

    def _finish_sleep(self):
        self._retain_sleep_fragments_into_awake_context()
        self.sleep_active = False
        self.sleep_memory_total = 0.0
        self.sleep_memory_processed = 0.0
        self.sleep_next_step_at = 0.0
        self.sleep_recent_dreams.clear()
        self.sleep_dream_archive.clear()
        self.sleep_context_messages.clear()
        self.pending_memory_units = max(0.0, self.pending_memory_units)

        self.phase_engine.reset_after_sleep()
        self.states.phase = Phases.PASSIVE
        self._append_system(
            "<system>SLEEP consolidation complete. Wake-up sequence finished. Returning to PASSIVE.</system>"
        )
        self.last_diag.note = "sleep consolidation complete"
        self.last_user_input_at = time.monotonic()
        self._schedule_next_passive_ponder()
        self.status_line = "Waiting for input"

    def _build_sleep_prompt(self, delta_m: float) -> str:
        progress = 0.0
        if self.sleep_memory_total > 1e-9:
            progress = self.sleep_memory_processed / self.sleep_memory_total

        if self.sleep_recent_dreams:
            recent_dreams = "\n".join(
                f"- {item}" for item in list(self.sleep_recent_dreams)[-6:]
            )
        else:
            recent_dreams = "- (none yet)"

        return (
            "Sleep consolidation cycle.\n"
            f"delta_memory={delta_m:.2f}, processed={self.sleep_memory_processed:.2f}/{self.sleep_memory_total:.2f}, "
            f"progress={progress:.2%}.\n"
            f"fatigue={self.states.f.value:.3f}, valence={self.states.v.value:.3f}, "
            f"energy={self.states.e.value:.3f}, arousal={self.states.a.value:.3f}.\n"
            "Recent dream outputs (avoid repeating exact words/phrases from these):\n"
            f"{recent_dreams}\n"
            "Use recent memory and first_startup continuity. Generate 1-2 lines of dream-like consolidation: "
            "mix happy moments, small regrets, and strange symbolic imagery."
            " Use fresh wording each step with minimal phrase overlap."
            " Continue the same sleep storyline instead of restarting each step."
        )

    async def _run_sleep_consolidation_step(self):
        if not self.sleep_active:
            return

        if self.states.f.value <= 0:
            self._finish_sleep()
            return

        if self.sleep_memory_processed >= self.sleep_memory_total:
            self._finish_sleep()
            return

        now = time.monotonic()
        if now < self.sleep_next_step_at:
            return

        remaining = max(0.0, self.sleep_memory_total - self.sleep_memory_processed)
        delta_m = min(self.sleep_memory_step, remaining)
        self.sleep_memory_processed += delta_m
        self.pending_memory_units = max(0.0, self.pending_memory_units - delta_m)

        fatigue_reduction = min(
            self.sleep_fatigue_reduction_per_inference,
            self.states.f.value,
        )
        self.states.f.value = max(0.0, self.states.f.value - fatigue_reduction)
        self.states.a.value = self._clamp(self.states.a.value * 0.92, 0.0, 1.0)
        self.states.e.value = self._clamp(self.states.e.value * 0.95, 0.0, 1.0)

        self._append_system(
            (
                "<system>Sleep consolidation step: "
                f"processed={self.sleep_memory_processed:.1f}/{self.sleep_memory_total:.1f}, "
                f"fatigue={self.states.f.value:.2f}, reduced={fatigue_reduction:.1f}. "
                "One-way telemetry.</system>"
            )
        )

        sleep_prompt = self._build_sleep_prompt(delta_m)
        self.linguistic_engine._update_sampling_params(self.states)
        bias_profile, token_logit_bias, _ = (
            self.linguistic_engine.logit_bias_builder.build_token_logit_bias(
                v=self.states.v.value,
                e=self.states.e.value,
                model=self.linguistic_engine.inference_engine.model,
            )
        )

        try:
            messages = [
                {
                    "role": "system",
                    "content": self.linguistic_engine._build_system_prompt("PASSIVE"),
                },
                *list(self.sleep_context_messages),
                {"role": "user", "content": sleep_prompt},
            ]
            result = await self.linguistic_engine.inference_engine.infer(
                messages=messages,
                temperature=self.linguistic_engine.temperature.value,
                top_p=self.linguistic_engine.top_p.value,
                max_output_tokens=140,
                logit_bias=token_logit_bias,
                frequency_penalty=self.sleep_frequency_penalty,
                presence_penalty=self.sleep_presence_penalty,
            )
            dream = result.output.strip() or "(sleep dream fragment unavailable)"
            self._append_ai(dream)
            self.sleep_recent_dreams.append(dream[:220])
            self.sleep_dream_archive.append(dream)
            self.sleep_context_messages.append(
                {"role": "user", "content": sleep_prompt}
            )
            self.sleep_context_messages.append({"role": "assistant", "content": dream})
            self.linguistic_engine.persona_memory.remember_turn("[sleep]", dream)

            self.turn += 1
            self.last_diag = TurnDiagnostics(
                turn=self.turn,
                timestamp=datetime.now().strftime("%H:%M:%S"),
                phase_before="SLEEP",
                phase_after="SLEEP",
                active_reason="SELF",
                model=self.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                fatigue_delta=-fatigue_reduction,
                interaction_delta=0.0,
                rudeness=self.phase_engine.r,
                mood="sleep-consolidation",
                bias_profile=bias_profile,
                token_bias_count=len(token_logit_bias),
                note=(
                    f"sleep consolidation step complete ({self.sleep_memory_processed:.1f}/"
                    f"{self.sleep_memory_total:.1f})"
                ),
            )
        except Exception as err:
            self._append_system(f"<system>Sleep dream synthesis failed: {err}</system>")
            self.last_diag.note = "sleep consolidation step failed"

        self.sleep_next_step_at = time.monotonic() + self.sleep_step_interval_sec

        if (
            self.states.f.value <= 0
            or self.sleep_memory_processed >= self.sleep_memory_total
        ):
            self._finish_sleep()

    def _build_passive_inputs(self) -> list[dict[str, str | float]]:
        return [
            {
                "type": "internal_fatigue_state",
                "amplitude": max(0.1, self.states.f.value / max(self.f_max, 1e-6)),
                "description": (
                    f"fatigue={self.states.f.value:.3f}/{self.f_max:.0f}, "
                    f"energy={self.states.e.value:.3f}, arousal={self.states.a.value:.3f}"
                ),
                "origin": "system_nervous_layer",
            },
            {
                "type": "internal_mood_state",
                "amplitude": max(0.1, abs(self.states.v.value)),
                "description": (
                    f"valence={self.states.v.value:.3f}, phase={self.states.phase.name}, "
                    f"cooldown_eta={self._seconds_until_next_passive_ponder():.1f}s"
                ),
                "origin": "system_nervous_layer",
            },
            {
                "type": "memory_anchor",
                "amplitude": 0.2,
                "description": "Preserve first_startup narrative continuity with adaptive playful personality",
                "origin": "memory_core",
            },
        ]

    async def _run_passive_ponder(self):
        if self.states.phase != Phases.PASSIVE:
            self._schedule_next_passive_ponder()
            return

        self.status_line = "Passive pondering: running inference"
        self._append_system(
            (
                "<system>Passive pondering trigger: "
                f"f={self.states.f.value:.3f}, v={self.states.v.value:.3f}, "
                f"e={self.states.e.value:.3f}, a={self.states.a.value:.3f}. "
                "One-way telemetry.</system>"
            )
        )

        inputs = self._build_passive_inputs()
        try:
            inference_result = await self.linguistic_engine.feed_passive(
                inputs, self.states
            )
        except Exception as err:
            self._append_system(f"<system>Passive pondering failed: {err}</system>")
            self.last_diag.note = "passive pondering failed"
            self._schedule_next_passive_ponder()
            self.status_line = "Waiting for input"
            return

        if not inference_result:
            self.last_diag.note = "passive pondering skipped"
            self._schedule_next_passive_ponder()
            self.status_line = "Waiting for input"
            return

        post = await self.phase_engine.after_inference(
            input=inference_result["input"],
            output=inference_result["output"],
        )
        ai_output = (
            str(post.get("output", "")).strip() or "(empty passive pondering output)"
        )
        self._append_ai(ai_output)
        self.context_messages.append({"role": "assistant", "content": ai_output})

        active_reason = str(post.get("active_reason", "SELF"))
        total_tokens = int(inference_result.get("total_tokens", 0))
        fatigue_delta = self.k_tok * total_tokens + self.k_inf
        if active_reason == "SELF":
            fatigue_delta += self.k_self
        fatigue_delta /= max(1.0, self.fatigue_inference_divisor)
        self.states.f.value += fatigue_delta
        self.pending_memory_units += max(1.0, total_tokens / 40.0)

        if self.states.f.value >= self.f_max:
            self._enter_sleep("passive pondering fatigue saturation")
            note = "passive pondering pushed fatigue to SLEEP"
        elif self.states.f.value >= self.f_max * 0.85:
            self.states.phase = Phases.MAINT
            note = "passive pondering pushed fatigue to MAINT"
        elif self.states.phase == Phases.PASSIVE:
            note = "passive pondering completed"
        else:
            note = f"passive pondering completed with phase={self.states.phase.name}"

        self.turn += 1
        self.last_diag = TurnDiagnostics(
            turn=self.turn,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            phase_before="PASSIVE",
            phase_after=self.states.phase.name,
            active_reason=active_reason,
            model=self.model,
            input_tokens=int(inference_result.get("input_tokens", 0)),
            output_tokens=int(inference_result.get("output_tokens", 0)),
            total_tokens=total_tokens,
            fatigue_delta=fatigue_delta,
            interaction_delta=float(post.get("delta", 0.0)),
            rudeness=float(post.get("rudeness", 0.0)),
            mood=str(post.get("mood", "steady")),
            bias_profile=str(
                inference_result.get("bias_profile", self._last_bias_profile)
            ),
            token_bias_count=int(
                inference_result.get("token_bias_count", self._last_token_bias_count)
            ),
            note=note,
        )
        self._last_bias_profile = self.last_diag.bias_profile
        self._last_token_bias_count = self.last_diag.token_bias_count
        self._schedule_next_passive_ponder()
        self.status_line = "Waiting for input"

    def _append_system(self, message: str):
        self.chat_lines.append(f"[bold yellow]System[/bold yellow]: {message}")
        if self.chat_auto_follow:
            self.chat_scroll_offset = 0

    def _append_user(self, message: str):
        self.chat_lines.append(f"[bold cyan]You[/bold cyan]: {message}")
        if self.chat_auto_follow:
            self.chat_scroll_offset = 0

    def _append_ai(self, message: str):
        self.chat_lines.append(f"[bold magenta]HyprAI[/bold magenta]: {message}")
        if self.chat_auto_follow:
            self.chat_scroll_offset = 0

    def _max_chat_offset(self) -> int:
        return max(0, len(self.chat_lines) - self.chat_window_lines)

    def _clamp_chat_offset(self):
        self.chat_scroll_offset = int(
            self._clamp(self.chat_scroll_offset, 0, self._max_chat_offset())
        )

    def _scroll_chat(self, direction: str, amount: int = 1):
        if direction in {"up", "pageup", "top"}:
            self.chat_auto_follow = False

        if direction == "up":
            self.chat_scroll_offset += max(1, amount)
        elif direction == "down":
            self.chat_scroll_offset -= max(1, amount)
        elif direction == "pageup":
            self.chat_scroll_offset += max(5, amount)
        elif direction == "pagedown":
            self.chat_scroll_offset -= max(5, amount)
        elif direction == "top":
            self.chat_scroll_offset = self._max_chat_offset()
        elif direction == "bottom":
            self.chat_scroll_offset = 0
            self.chat_auto_follow = True

        self._clamp_chat_offset()

    def _chat_view_meta(self) -> str:
        total = len(self.chat_lines)
        if total == 0:
            return "follow=ON view=0/0"

        self._clamp_chat_offset()
        if self.chat_auto_follow:
            end = total
        else:
            end = max(0, total - self.chat_scroll_offset)
        start = max(0, end - self.chat_window_lines)

        follow_mode = "ON" if self.chat_auto_follow else "OFF"
        return f"follow={follow_mode} view={start + 1}-{end}/{total}"

    def _phase_explanation(self) -> str:
        if self.states.phase == Phases.PASSIVE:
            return "PASSIVE: low-rate background awareness"
        if self.states.phase == Phases.ACTIVE:
            return "ACTIVE: engaged interaction path"
        if self.states.phase == Phases.MAINT:
            return "MAINT: load-shedding and cooldown pressure"
        if self.states.phase == Phases.SLEEP:
            return "SLEEP: halted loop with consolidation priority"
        return "Unknown phase"

    def _render_chat_panel(self) -> Panel:
        if not self.chat_lines:
            body = Text("No interaction yet.")
        else:
            lines = list(self.chat_lines)
            self._clamp_chat_offset()
            if self.chat_auto_follow:
                end = len(lines)
            else:
                end = max(0, len(lines) - self.chat_scroll_offset)
            start = max(0, end - self.chat_window_lines)
            visible = lines[start:end]
            body = Text.from_markup("\n".join(visible))

        return Panel(
            body,
            title=f"Live Interaction ({self._chat_view_meta()})",
            border_style="cyan",
        )

    def _render_state_panel(self) -> Panel:
        passive_eta = self._seconds_until_next_passive_ponder()

        table = Table(show_header=True, header_style="bold green", expand=True)
        table.add_column("Scalar")
        table.add_column("Value", justify="right")
        table.add_column("Range")
        table.add_column("Meaning")

        table.add_row(
            "phase", self.states.phase.name, "enum", self._phase_explanation()
        )
        table.add_row(
            "f (fatigue)",
            f"{self.states.f.value:.3f}",
            f"[0,{self.f_max:.0f}]",
            "load and wear",
        )
        table.add_row(
            "v (valence)", f"{self.states.v.value:.3f}", "[-1,1]", "tone direction"
        )
        table.add_row(
            "e (energy)", f"{self.states.e.value:.3f}", "[0,1]", "response vigor"
        )
        table.add_row(
            "a (arousal)", f"{self.states.a.value:.3f}", "[0,1]", "activation"
        )
        table.add_row(
            "c (cooldown)", f"{self.states.c.value:.3f}", ">=0", "loop pacing gate"
        )
        if self.states.phase == Phases.SLEEP:
            ponder_value = "paused"
        else:
            ponder_value = f"{passive_eta:.1f}s"
        table.add_row(
            "next passive ponder",
            ponder_value,
            "seconds",
            "eta until next passive pondering cycle",
        )

        if self.states.phase == Phases.SLEEP:
            if self.sleep_memory_total > 1e-9:
                sleep_progress = self.sleep_memory_processed / self.sleep_memory_total
            else:
                sleep_progress = 0.0
            table.add_row(
                "sleep memory",
                f"{self.sleep_memory_processed:.1f}/{self.sleep_memory_total:.1f}",
                "units",
                "consolidation backlog progress",
            )
            table.add_row(
                "sleep progress",
                f"{sleep_progress * 100:.1f}%",
                "percent",
                "memory replay completion",
            )

        self.states.c.value = passive_eta
        return Panel(table, title="Kernel State", border_style="green")

    def _render_diagnostics_panel(self) -> Panel:
        diag = self.last_diag
        lines = [
            f"turn={diag.turn} time={diag.timestamp}",
            f"model={diag.model}",
            f"phase transition: {diag.phase_before} -> {diag.phase_after} ({diag.active_reason})",
            (
                "fatigue formula: f += (k_tok*tokens + k_inf + k_self(if SELF)) / div | "
                f"k_tok={self.k_tok:.3f}, k_inf={self.k_inf:.3f}, k_self={self.k_self:.3f}, "
                f"div={self.fatigue_inference_divisor:.0f}"
            ),
            f"token usage: in={diag.input_tokens} out={diag.output_tokens} total={diag.total_tokens}",
            f"fatigue delta this turn: {diag.fatigue_delta:+.3f}",
            f"interaction delta d={diag.interaction_delta:.3f}, rudeness r={diag.rudeness:.3f}",
            f"logit bias profile={diag.bias_profile}, token_bias_count={diag.token_bias_count}",
            f"next passive pondering eta={self._seconds_until_next_passive_ponder():.1f}s",
            f"sleep consolidation={self.sleep_memory_processed:.1f}/{self.sleep_memory_total:.1f} units",
            f"sleep story buffer={len(self.sleep_context_messages)} msgs, retained fragments={self.sleep_retained_fragments}",
            f"persona traits: {self.linguistic_engine.persona_memory.trait_snapshot()}",
            (
                "stability note: perception preempts timing; no forced cognition, "
                "no enum feedback, bounded scalar updates"
            ),
            f"mood view={diag.mood} | note={diag.note}",
        ]

        body = Text("\n".join(lines))
        return Panel(body, title="Verbose State Explanation", border_style="magenta")

    def _render_footer_panel(self) -> Panel:
        footer = (
            f"Status: {self.status_line} | "
            "Commands: /help /state /memory /scroll /follow /clear /quit | "
            f"Model: {self.model}"
        )
        return Panel(footer, border_style="blue")

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=3),
        )

        header_text = Text.from_markup(
            "[bold white]HyprAI OS Rich TUI[/bold white]"
            "\n"
            "[dim]Perception -> Timing preemption -> Inference -> Mood dynamics[/dim]"
        )
        layout["header"].update(Panel(header_text, border_style="white"))

        layout["body"].split_row(
            Layout(self._render_chat_panel(), name="chat", ratio=3),
            Layout(name="right", ratio=2),
        )
        layout["right"].split_column(
            Layout(self._render_state_panel(), name="state", ratio=3),
            Layout(self._render_diagnostics_panel(), name="diag", ratio=4),
        )

        layout["footer"].update(self._render_footer_panel())
        return layout

    def _reset_to_baseline(self):
        self.states.f.value = 0.0
        self.states.v.value = 0.35
        self.states.e.value = 0.65
        self.states.a.value = 0.20
        self.states.c.value = 0.05
        self.states.phase = Phases.PASSIVE
        self.phase_engine.r = 0.0
        self.phase_engine.active_reason = "USER"
        self.context_messages.clear()
        self.pending_memory_units = 0.0
        self.sleep_active = False
        self.sleep_memory_total = 0.0
        self.sleep_memory_processed = 0.0
        self.sleep_next_step_at = 0.0
        self.sleep_recent_dreams.clear()
        self.sleep_dream_archive.clear()
        self.sleep_context_messages.clear()
        self.last_user_input_at = time.monotonic()
        self._schedule_next_passive_ponder()

    async def _run_llm_turn(self, user_text: str):
        self.context_messages.append({"role": "user", "content": user_text})

        self.linguistic_engine._update_sampling_params(self.states)
        system_prompt = self.linguistic_engine._build_system_prompt("ACTIVE")
        bias_profile, token_logit_bias, _ = (
            self.linguistic_engine.logit_bias_builder.build_token_logit_bias(
                v=self.states.v.value,
                e=self.states.e.value,
                model=self.linguistic_engine.inference_engine.model,
            )
        )
        self._last_bias_profile = bias_profile
        self._last_token_bias_count = len(token_logit_bias)

        messages = [
            {"role": "system", "content": system_prompt},
            *list(self.context_messages),
        ]

        result = await self.linguistic_engine.inference_engine.infer(
            messages=messages,
            temperature=self.linguistic_engine.temperature.value,
            top_p=self.linguistic_engine.top_p.value,
            max_output_tokens=500,
            logit_bias=token_logit_bias,
        )
        return result

    async def handle_input(self, user_text: str):
        text = user_text.strip()
        if not text:
            return True

        self.last_user_input_at = time.monotonic()
        self._schedule_next_passive_ponder()

        if text.lower() in {"/quit", "/exit", "quit", "exit"}:
            self.status_line = "Exiting"
            self._append_system("Session closed by user command")
            return False

        if text.lower() == "/help":
            self._append_system(
                "Use natural language for live inference. Commands: /state, /memory, /scroll <up|down|pageup|pagedown|top|bottom> [n], /follow <on|off>, /clear, /quit"
            )
            self.status_line = "Help displayed"
            return True

        if text.lower().startswith("/follow"):
            parts = text.split()
            if len(parts) == 1:
                self.chat_auto_follow = not self.chat_auto_follow
            else:
                mode = parts[1].strip().lower()
                if mode in {"on", "true", "1"}:
                    self.chat_auto_follow = True
                elif mode in {"off", "false", "0"}:
                    self.chat_auto_follow = False
                else:
                    self.status_line = "Invalid /follow mode. Use on|off"
                    return True

            if self.chat_auto_follow:
                self.chat_scroll_offset = 0
            self.status_line = (
                f"Chat auto-follow {'enabled' if self.chat_auto_follow else 'disabled'}"
            )
            return True

        if text.lower().startswith("/scroll"):
            parts = text.split()
            if len(parts) < 2:
                self.status_line = (
                    "Usage: /scroll <up|down|pageup|pagedown|top|bottom> [n]"
                )
                return True

            direction = parts[1].strip().lower()
            amount = 1
            if len(parts) >= 3:
                try:
                    amount = max(1, int(parts[2]))
                except ValueError:
                    self.status_line = "Scroll amount must be an integer"
                    return True

            valid = {"up", "down", "pageup", "pagedown", "top", "bottom"}
            if direction not in valid:
                self.status_line = "Invalid scroll direction"
                return True

            self._scroll_chat(direction, amount)
            self.status_line = f"Chat scrolled {direction}; {self._chat_view_meta()}"
            return True

        if text.lower() == "/state":
            self._append_system(
                (
                    f"phase={self.states.phase.name}, f={self.states.f.value:.3f}, "
                    f"v={self.states.v.value:.3f}, e={self.states.e.value:.3f}, a={self.states.a.value:.3f}, "
                    f"idle={(time.monotonic() - self.last_user_input_at):.1f}s, "
                    f"next_passive_ponder={self._seconds_until_next_passive_ponder():.1f}s, "
                    f"chat={self._chat_view_meta()}"
                )
            )
            self.status_line = "State snapshot appended to log"
            return True

        if text.lower() == "/memory":
            self._append_system(
                "Recent memory:\n"
                + self.linguistic_engine.persona_memory.recent_memory(limit=8)
            )
            self.status_line = "Memory snapshot appended to log"
            return True

        if text.lower() == "/clear":
            self.chat_lines.clear()
            self._append_system("Conversation cleared")
            self.chat_scroll_offset = 0
            self.chat_auto_follow = True
            self.status_line = "Conversation cleared"
            return True

        if text.lower() == "/reset":
            self._reset_to_baseline()
            self.chat_lines.clear()
            self._append_system("Session state reset to baseline")
            self.status_line = "State reset"
            return True

        self._append_user(text)

        phase_before = self.states.phase.name
        if self.states.phase in {Phases.SLEEP, Phases.MAINT}:
            self._append_system(
                "CommunicationController override: forcing ACTIVE USER path"
            )
            if self.states.phase == Phases.SLEEP:
                self._retain_sleep_fragments_into_awake_context()
                self.sleep_active = False
                self.sleep_memory_total = 0.0
                self.sleep_memory_processed = 0.0
                self.sleep_next_step_at = 0.0
                self.sleep_recent_dreams.clear()
                self.sleep_dream_archive.clear()
                self.sleep_context_messages.clear()

        self.states.phase = Phases.ACTIVE
        self.phase_engine.active_reason = "USER"
        self.status_line = "Running live inference against OpenAI"

        try:
            llm_result = await self._run_llm_turn(text)
        except Exception as err:
            self.status_line = "Inference error"
            self._append_system(f"Inference failed: {err}")
            return True

        post = await self.phase_engine.after_inference(
            input=text, output=llm_result.output
        )
        ai_output = str(post.get("output", "")).strip() or "(empty model output)"
        self.linguistic_engine.persona_memory.remember_turn(text, ai_output)
        self._append_ai(ai_output)
        self.context_messages.append({"role": "assistant", "content": ai_output})

        active_reason = str(post.get("active_reason", "USER"))
        fatigue_delta = self.k_tok * llm_result.total_tokens + self.k_inf
        if active_reason == "SELF":
            fatigue_delta += self.k_self
        fatigue_delta /= max(1.0, self.fatigue_inference_divisor)
        self.states.f.value += fatigue_delta
        self.pending_memory_units += max(1.0, llm_result.total_tokens / 40.0)

        if self.states.f.value >= self.f_max:
            self._enter_sleep("fatigue saturation reached threshold")
            note = "fatigue saturation reached SLEEP threshold"
        elif self.states.f.value >= self.f_max * 0.85:
            self.states.phase = Phases.MAINT
            note = "fatigue exceeded maintenance threshold"
        else:
            self.states.phase = Phases.PASSIVE
            note = "stable update; returned to PASSIVE wait state"

        self._schedule_next_passive_ponder()

        self.turn += 1
        self.last_diag = TurnDiagnostics(
            turn=self.turn,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            phase_before=phase_before,
            phase_after=self.states.phase.name,
            active_reason=active_reason,
            model=self.model,
            input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
            total_tokens=llm_result.total_tokens,
            fatigue_delta=fatigue_delta,
            interaction_delta=float(post.get("delta", 0.0)),
            rudeness=float(post.get("rudeness", 0.0)),
            mood=str(post.get("mood", "steady")),
            bias_profile=self._last_bias_profile,
            token_bias_count=self._last_token_bias_count,
            note=note,
        )
        self.status_line = "Inference complete"
        return True

    def _input_worker(self):
        while not self._stop_input.is_set():
            try:
                user_text = input("You > ")
            except (EOFError, KeyboardInterrupt):
                user_text = "/quit"

            if self._stop_input.is_set():
                break

            try:
                self._input_queue.put_nowait(user_text)
            except Exception:
                pass

            if user_text.strip().lower() in {"/quit", "/exit", "quit", "exit"}:
                break

    def _start_input_thread(self):
        if self._input_thread and self._input_thread.is_alive():
            return

        self._stop_input.clear()
        self._input_thread = threading.Thread(
            target=self._input_worker,
            name="hypr-tui-input",
            daemon=True,
        )
        self._input_thread.start()

    def _stop_input_thread(self):
        self._stop_input.set()

    async def run(self):
        self._start_input_thread()
        with Live(
            self._build_layout(),
            console=self.console,
            refresh_per_second=12,
            screen=self.screen_mode,
            auto_refresh=True,
        ) as live:
            running = True
            self.status_line = "Waiting for input"
            while running:
                live.update(self._build_layout(), refresh=True)
                try:
                    user_text = self._input_queue.get_nowait()
                except Empty:
                    user_text = None

                if user_text is not None:
                    running = await self.handle_input(user_text)
                    if running:
                        self.status_line = "Waiting for input"
                    live.update(self._build_layout(), refresh=True)
                    await asyncio.sleep(0.08)
                    continue

                idle_seconds = time.monotonic() - self.last_user_input_at
                if self.states.phase == Phases.SLEEP and not self.sleep_active:
                    self._enter_sleep("resume sleep consolidation")

                if self.states.phase == Phases.SLEEP and self.sleep_active:
                    await self._run_sleep_consolidation_step()
                    live.update(self._build_layout(), refresh=True)
                    await asyncio.sleep(0.08)
                    continue

                if (
                    self.states.phase == Phases.PASSIVE
                    and self._seconds_until_next_passive_ponder() <= 0
                    and idle_seconds >= self.passive_ponder_idle_threshold_sec
                ):
                    await self._run_passive_ponder()
                    live.update(self._build_layout(), refresh=True)

                await asyncio.sleep(0.08)

        self._stop_input_thread()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HyprAI OS Rich live interaction TUI")
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model to use for live interaction (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--max-history",
        type=int,
        default=16,
        help="Conversation context window size (default: 16 messages)",
    )
    parser.add_argument(
        "--screen",
        action="store_true",
        help="Use alternate full-screen mode (default: off for input compatibility)",
    )
    return parser.parse_args()


async def amain():
    args = parse_args()
    app = HyprRichTUI(
        model=args.model,
        max_history=max(4, args.max_history),
        screen_mode=bool(args.screen),
    )
    await app.run()


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
