import asyncio
import base64
import logging
import mimetypes
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine, Literal

from ascender.core import inject
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hyprchan.core.animations.engine import AnimationEngine
from hyprchan.core.hypraios.constants import Phases
from hyprchan.core.hypraios.perception.opencv_module import OpenCVPerceptionModule
from hyprchan.core.hypraios.tools.constants import (
    TOOL_ANSWER_USER,
    TOOL_CAMERA,
    TOOL_EPISODIC_RECALL,
    TOOL_HYPRCTL_COMMAND,
    TOOL_LIST_SKILLS,
    TOOL_MEMORIZE,
    TOOL_MEMORY_RECALL,
    TOOL_MOVE_SELF,
    TOOL_PATCH_SKILL,
    TOOL_RECALL_SKILL,
    TOOL_SAVE_SKILL,
    TOOL_SCREENSHOT,
    TOOL_SET_ANIMATION_POSE,
    TOOL_SLEEP_DIGEST,
)
from hyprchan.core.hypraios.tools.registry import ToolRegistry
from hyprchan.core.hypraios.tools.types import ToolContext, ToolSpec
from hyprchan.core.hyprland.exceptions import UnknownRequestError
from hyprchan.core.hyprland.socket import HyprlandSocket
from hyprchan.core.hyprmemory import HyprMemoryService
from hyprchan.core.hyprmemory.models import MemoryState
from hyprchan.settings import (
    WEBCAM_AUTO_FIND_DEVICE,
    WEBCAM_DEVICE_INDEX,
    WEBCAM_MAX_DEVICE_INDEX,
)

logger = logging.getLogger(__name__)


class SetAnimationPoseInput(BaseModel):
    pose: str = Field(
        description="Animation pose name to set on Hyprchan overlay.",
        min_length=1,
    )


class AnswerUserInput(BaseModel):
    text: str = Field(
        description="User-facing answer text shown on top of Hyprchan figure.",
        min_length=1,
        max_length=280,
    )


class MoveSelfInput(BaseModel):
    direction: Literal[
        "up",
        "down",
        "left",
        "right",
        "up_left",
        "up_right",
        "down_left",
        "down_right",
    ] = Field(description="Direction to move Hyprchan on screen.")
    delta: int = Field(
        description="Movement delta in screen pixels.",
        ge=0,
        le=1200,
    )
    scale: float = Field(
        default=1.0,
        description=(
            "Sprite scale coefficient in range 0..2. 1.2 means 20% size increase."
        ),
        ge=0.0,
        le=2.0,
    )


class ScreenshotInput(BaseModel):
    pass


class CameraInput(BaseModel):
    pass


class MemoryRecallInput(BaseModel):
    query: str = Field(
        description=(
            "Semantic recall query. Use a short phrase or question to retrieve "
            "relevant episodes, facts, and concept anchors from associative memory."
        ),
        min_length=1,
        max_length=400,
    )


class EpisodicRecallInput(BaseModel):
    period: str = Field(
        default="recent",
        description=(
            "Time window to retrieve episodes from. "
            "Examples: 'today', 'yesterday', 'last 3 hours', 'last 2 days', 'last week', 'recent' (no filter)."
        ),
    )
    limit: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Max episodes to return.",
    )


class HyprctlCommandInput(BaseModel):
    command: str = Field(
        description=(
            "Raw hyprctl command body to execute through Hyprland IPC. "
            "Do not include the `hyprctl` prefix; e.g. `dispatch workspace 2`."
        ),
        min_length=1,
        max_length=600,
    )


class SaveSkillInput(BaseModel):
    name: str = Field(
        description="Stable unique skill name.", min_length=1, max_length=160
    )
    content: str = Field(
        description="Skill description with how/when to use it.",
        min_length=1,
        max_length=2000,
    )
    tags: list[str] = Field(default_factory=list, description="Optional lookup tags.")
    success_score: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_sequence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional ordered tool calls used by this skill.",
    )


class RecallSkillInput(BaseModel):
    query: str = Field(
        description="Lexical query for skill name, description, or tags.",
        min_length=1,
        max_length=400,
    )
    max: int = Field(default=20, ge=1, le=50)


class ListSkillsInput(BaseModel):
    max: int = Field(default=20, ge=1, le=50)


class PatchSkillInput(BaseModel):
    name: str = Field(
        description="Existing skill name to patch.", min_length=1, max_length=160
    )
    content: str = Field(
        description="Updated/corrected skill narrative.",
        min_length=1,
        max_length=2000,
    )
    failure_notes: list[str] = Field(
        default_factory=list,
        description="Known failures and what to avoid.",
    )
    success_score: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_sequence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional updated tool sequence.",
    )


class MemorizeInput(BaseModel):
    content: str = Field(
        description=(
            "The fact, experience, or insight to permanently remember. "
            "Write it as a self-contained statement — it will be stored with maximum salience."
        ),
        min_length=1,
        max_length=1000,
    )
    note: str = Field(
        default="",
        description="Optional context note explaining why this is important.",
        max_length=400,
    )


class SleepDigestInput(BaseModel):
    pass


@dataclass
class ToolExecutionResult:
    answer_user_called: bool
    executed_calls: int
    followup_messages: list[dict[str, Any]]
    followup_events: list[dict[str, Any]]


class LinguisticToolRuntime:
    OVERLAY_TITLE = "hyprchan-overlay"
    OVERLAY_CLASS = "org.hyprland.hyprchan"

    def __init__(
        self,
        animation_engine_resolver: Callable[[], AnimationEngine | None] | None = None,
        memory_service: "HyprMemoryService | None" = None,
    ) -> None:
        self._resolve_animation_engine = (
            animation_engine_resolver or self._resolve_animation_engine_from_di
        )
        self.last_answer_text = ""
        self.tool_registry = ToolRegistry(logger=logger)
        self._camera_fallback_last_attempt_at = 0.0
        self._camera_fallback_cooldown_sec = 5.0
        self._memory_state: MemoryState | None = None
        self._memory_phase: Phases | None = None
        self._memory_service: HyprMemoryService | None = memory_service
        self._sleep_digest_callback: Callable[[], Coroutine[Any, Any, str]] | None = (
            None
        )
        self._register_builtin_tools()

    def set_sleep_digest_callback(
        self, callback: Callable[[], Coroutine[Any, Any, str]]
    ) -> None:
        self._sleep_digest_callback = callback

    def build_tools(self) -> list[StructuredTool]:
        self._refresh_builtin_tool_descriptions()
        context = ToolContext(
            phase=self._memory_phase,
            memory_enabled=self._memory_service is not None,
            animation_poses=self.available_animations(),
        )
        return self.tool_registry.build(context)

    def _refresh_builtin_tool_descriptions(self) -> None:
        available = self.available_animations()
        available_text = ", ".join(available) if available else "none"
        spec = self.tool_registry._tools.get(TOOL_SET_ANIMATION_POSE)
        if spec is None:
            return
        tool = spec.tool
        tool.description = (
            "Set Hyprchan animation pose from loaded animations. "
            f"Available poses right now: {available_text}."
        )

    def _register_builtin_tools(self) -> None:
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_SET_ANIMATION_POSE,
                tool=StructuredTool.from_function(
                    coroutine=self._set_animation_pose,
                    name=TOOL_SET_ANIMATION_POSE,
                    description=(
                        "Set Hyprchan animation pose from loaded animations. "
                        "Available poses right now: {available_poses}."
                    ),
                    args_schema=SetAnimationPoseInput,
                ),
                priority=50,
                marker="mandatory",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_ANSWER_USER,
                tool=StructuredTool.from_function(
                    coroutine=self._answer_user,
                    name=TOOL_ANSWER_USER,
                    description=(
                        "Display text response in white on top of Hyprchan figure. "
                        "Use for user-visible response output."
                    ),
                    args_schema=AnswerUserInput,
                ),
                priority=40,
                marker="mandatory",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_MOVE_SELF,
                tool=StructuredTool.from_function(
                    coroutine=self._move_self,
                    name=TOOL_MOVE_SELF,
                    description=(
                        "Move Hyprchan overlay window by a directional delta using Hyprland, "
                        "and set sprite scale when supported. "
                        "Scale is a direct multiplier in [0,2], where 1.2 means +20% size."
                    ),
                    args_schema=MoveSelfInput,
                ),
                priority=30,
                marker="mandatory",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_SCREENSHOT,
                tool=StructuredTool.from_function(
                    coroutine=self._screenshot,
                    name=TOOL_SCREENSHOT,
                    description=(
                        "Capture a screenshot right now and return it as multimodal context."
                    ),
                    args_schema=ScreenshotInput,
                ),
                priority=20,
                marker="optional",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_CAMERA,
                tool=StructuredTool.from_function(
                    coroutine=self._camera,
                    name=TOOL_CAMERA,
                    description=(
                        "Capture a webcam photo right now and return it as multimodal context."
                    ),
                    args_schema=CameraInput,
                ),
                priority=20,
                marker="optional",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_MEMORY_RECALL,
                tool=StructuredTool.from_function(
                    coroutine=self._memory_recall,
                    name=TOOL_MEMORY_RECALL,
                    description=(
                        "Semantic+associative recall from HyprMemory. "
                        "Use a short query to retrieve relevant facts, concept anchors, and episode gists."
                    ),
                    args_schema=MemoryRecallInput,
                ),
                priority=10,
                marker="optional",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_EPISODIC_RECALL,
                tool=StructuredTool.from_function(
                    coroutine=self._episodic_recall,
                    name=TOOL_EPISODIC_RECALL,
                    description=(
                        "Retrieve the most recent episodic memories in time order — "
                        "what actually happened, with emotional context, entities, and topics. "
                        "Use when you want to know *what occurred* recently, not search for a fact."
                    ),
                    args_schema=EpisodicRecallInput,
                ),
                priority=10,
                marker="optional",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_HYPRCTL_COMMAND,
                tool=StructuredTool.from_function(
                    coroutine=self._hyprctl_command,
                    name=TOOL_HYPRCTL_COMMAND,
                    description=(
                        "Run a Hyprland command over IPC socket (no shell). "
                        "Available only on Hyprland systems. "
                        "For syntax/help use `hyprctl --help` and `hyprctl dispatch --help` in terminal. "
                        "Pass only the command body, for example: `dispatch workspace 2`."
                    ),
                    args_schema=HyprctlCommandInput,
                ),
                priority=25,
                marker="optional",
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_SAVE_SKILL,
                tool=StructuredTool.from_function(
                    coroutine=self._save_skill,
                    name=TOOL_SAVE_SKILL,
                    description=(
                        "Save a procedural skill in HyprMemory with optional tags and tool sequence."
                        "If you are defining tool sequence, define it in this schema: {'name': (name of the tool), 'arguments': (what arguments you passed)}"
                    ),
                    args_schema=SaveSkillInput,
                ),
                priority=15,
                marker="mandatory",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_RECALL_SKILL,
                tool=StructuredTool.from_function(
                    coroutine=self._recall_skill,
                    name=TOOL_RECALL_SKILL,
                    description=(
                        "Find your procedural skills by lexical query over name, description, and tags."
                        " Use this EVERYTIME when you have no clue what to do or if you failing to do something."
                    ),
                    args_schema=RecallSkillInput,
                ),
                priority=15,
                marker="mandatory",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_LIST_SKILLS,
                tool=StructuredTool.from_function(
                    coroutine=self._list_skills,
                    name=TOOL_LIST_SKILLS,
                    description="List most relevant saved procedural skills added by you or user.",
                    args_schema=ListSkillsInput,
                ),
                priority=15,
                marker="mandatory",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_PATCH_SKILL,
                tool=StructuredTool.from_function(
                    coroutine=self._patch_skill,
                    name=TOOL_PATCH_SKILL,
                    description=(
                        "Patch an existing procedural skill with corrected guidance and failure notes."
                    ),
                    args_schema=PatchSkillInput,
                ),
                priority=15,
                marker="mandatory",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_MEMORIZE,
                tool=StructuredTool.from_function(
                    coroutine=self._memorize,
                    name=TOOL_MEMORIZE,
                    description=(
                        "Permanently mark something as critically important memory with maximum salience. "
                        "Use when the user shares something that must never be forgotten, "
                        "or when you form an insight worth keeping forever."
                    ),
                    args_schema=MemorizeInput,
                ),
                priority=12,
                marker="optional",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )
        self.tool_registry.register(
            ToolSpec(
                name=TOOL_SLEEP_DIGEST,
                tool=StructuredTool.from_function(
                    coroutine=self._sleep_digest,
                    name=TOOL_SLEEP_DIGEST,
                    description=(
                        "Voluntarily digest and consolidate accumulated short-term memories into "
                        "long-term storage right now. Use after absorbing a lot of new information "
                        "or when you want to solidify recent experiences before continuing."
                    ),
                    args_schema=SleepDigestInput,
                ),
                priority=11,
                marker="optional",
                predicate=lambda ctx: ctx.memory_enabled,
            ),
            replace=True,
        )

    def available_animations(self) -> list[str]:
        engine = self._resolve_animation_engine()
        if engine is None:
            return []

        list_available = getattr(engine, "available_animation_names", None)
        if not callable(list_available):
            return []

        try:
            names = list_available()
        except Exception:
            return []

        if not isinstance(names, list):
            return []
        return [str(name) for name in names]

    def update_memory_context(
        self,
        *,
        memory_state: MemoryState | None,
        phase: Phases | None,
    ) -> None:
        self._memory_state = memory_state
        self._memory_phase = phase

    def _resolve_hyprland(self) -> HyprlandSocket | None:
        fallback = object()
        try:
            socket = inject(HyprlandSocket, fallback=fallback)
        except Exception:
            return None
        if socket is fallback:
            return None
        return socket

    @staticmethod
    def _direction_delta(direction: str, delta: int) -> tuple[int, int]:
        mapping = {
            "up": (0, -delta),
            "down": (0, delta),
            "left": (-delta, 0),
            "right": (delta, 0),
            "up_left": (-delta, -delta),
            "up_right": (delta, -delta),
            "down_left": (-delta, delta),
            "down_right": (delta, delta),
        }
        return mapping.get(direction, (0, 0))

    async def _find_overlay_client(
        self, hyprland: HyprlandSocket
    ) -> dict[str, Any] | None:
        try:
            clients = await hyprland.send_command("clients", is_json=True)
        except Exception:
            return None

        if isinstance(clients, dict):
            payload = clients.get("data", clients.get("clients", []))
        else:
            payload = clients

        if not isinstance(payload, list):
            return None

        title_target = self.OVERLAY_TITLE.lower()
        class_target = self.OVERLAY_CLASS.lower()
        for client in payload:
            if not isinstance(client, dict):
                continue
            title = str(client.get("title", "")).strip().lower()
            initial_title = str(client.get("initialTitle", "")).strip().lower()
            clazz = str(client.get("class", "")).strip().lower()
            if title == title_target or initial_title == title_target:
                return client
            if clazz == class_target:
                return client
            if title_target and title_target in title:
                return client
        return None

    async def _move_overlay_window(
        self,
        *,
        direction: str,
        delta: int,
    ) -> tuple[bool, str, bool]:
        hyprland = self._resolve_hyprland()
        if hyprland is None:
            return False, "hyprland socket unavailable", False

        client = await self._find_overlay_client(hyprland)
        if not client:
            return False, "overlay window not found", True

        at = client.get("at")
        if not (isinstance(at, list) and len(at) >= 2):
            return False, "overlay position unavailable", True

        try:
            base_x, base_y = int(at[0]), int(at[1])
        except (TypeError, ValueError):
            return False, "overlay position invalid", True

        dx, dy = self._direction_delta(direction, delta)
        new_x, new_y = base_x + dx, base_y + dy

        target = ""
        address = client.get("address")
        if isinstance(address, str) and address.strip():
            target = f"address:{address.strip()}"
        else:
            title = client.get("title") or self.OVERLAY_TITLE
            if isinstance(title, str) and title.strip():
                target = f"title:{title.strip()}"

        cmd_base = f"dispatch movewindowpixel exact {new_x} {new_y}"
        candidates = [
            f"{cmd_base},{target}" if target else cmd_base,
            f"dispatch movewindowpixel {new_x} {new_y},{target}"
            if target
            else f"dispatch movewindowpixel {new_x} {new_y}",
            cmd_base,
            f"dispatch movewindowpixel {new_x} {new_y}",
        ]

        last_err: Exception | None = None
        for cmd in candidates:
            try:
                await hyprland.send_command(cmd)
                return True, f"moved overlay to {new_x},{new_y}", True
            except UnknownRequestError as exc:
                last_err = exc
                continue
            except Exception as exc:
                last_err = exc
                continue

        if last_err is not None:
            return (
                False,
                f"hyprland move failed: {type(last_err).__name__}: {last_err}",
                True,
            )
        return False, "hyprland move failed", True

    async def _memory_recall(self, query: str) -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"

        state = self._memory_state or MemoryState(f=0.0, v=0.0, e=0.0, a=0.0)
        phase = self._memory_phase
        try:
            blocks = await memory.recall_working_memory(
                query_text=query.strip(),
                state=state,
                phase=phase,
            )
        except Exception as exc:
            return f"hyprmemory recall failed: {type(exc).__name__}: {exc}"

        if not blocks:
            return "no relevant memories found"
        return "HyprMemory recall:\n\n" + "\n\n".join(blocks)

    @staticmethod
    def _parse_period(period: str) -> tuple[Any, Any]:
        """Parse a natural language period into (ts_from, ts_to). Returns (None, None) for 'recent'."""
        import re
        from datetime import datetime, timedelta, timezone

        now = datetime.now(tz=timezone.utc)
        p = period.strip().lower()

        if p in ("recent", ""):
            return None, None

        if p == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now

        if p == "yesterday":
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = today_start - timedelta(days=1)
            return start, today_start

        if p in ("last week", "this week"):
            return now - timedelta(weeks=1), now

        m = re.fullmatch(r"last\s+(\d+)\s+(hour|hours|hr|hrs)", p)
        if m:
            return now - timedelta(hours=int(m.group(1))), now

        m = re.fullmatch(r"last\s+(\d+)\s+(day|days)", p)
        if m:
            return now - timedelta(days=int(m.group(1))), now

        m = re.fullmatch(r"last\s+(\d+)\s+(week|weeks)", p)
        if m:
            return now - timedelta(weeks=int(m.group(1))), now

        return None, None

    async def _episodic_recall(self, period: str = "recent", limit: int = 8) -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"

        ts_from, ts_to = self._parse_period(period)
        try:
            blocks = await memory.recall_episodic(ts_from=ts_from, ts_to=ts_to, limit=limit)
        except Exception as exc:
            return f"episodic recall failed: {type(exc).__name__}: {exc}"

        if not blocks:
            return "no episodic memories found"
        return "Episode log:\n\n" + "\n\n".join(blocks)

    async def _memorize(self, content: str, note: str = "") -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"

        state = self._memory_state or MemoryState(f=0.0, v=0.0, e=0.0, a=0.0)
        try:
            await memory.memorize_important(
                content=content.strip(), state=state, note=note.strip() if note else ""
            )
        except Exception as exc:
            return f"memorize failed: {type(exc).__name__}: {exc}"

        snippet = content.strip()[:80]
        return (
            f'memorized (salience=1.0): "{snippet}{"..." if len(content) > 80 else ""}"'
        )

    async def _sleep_digest(self) -> str:
        callback = self._sleep_digest_callback
        if callback is None:
            return "sleep digest unavailable (kernel callback not wired)"
        try:
            return await callback()
        except Exception as exc:
            return f"sleep digest failed: {type(exc).__name__}: {exc}"

    async def _save_skill(
        self,
        name: str,
        content: str,
        tags: list[str] | None = None,
        success_score: float = 0.1,
        tool_sequence: list[dict[str, Any]] | None = None,
    ) -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"
        procedural = getattr(memory, "procedural_memory", None)
        if procedural is None:
            return "procedural memory unavailable"
        try:
            result = await procedural.save_skill(
                name=name.strip(),
                content=content.strip(),
                tags=tags,
                success_score=success_score,
                tool_sequence=tool_sequence,
            )
        except Exception as exc:
            return f"save_skill failed: {type(exc).__name__}: {exc}"
        return str(result)

    async def _recall_skill(self, query: str, max: int = 20) -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"
        procedural = getattr(memory, "procedural_memory", None)
        if procedural is None:
            return "procedural memory unavailable"
        try:
            result = await procedural.recall_skill(query=query.strip(), max=max)
        except Exception as exc:
            return f"recall_skill failed: {type(exc).__name__}: {exc}"
        return str(result)

    async def _list_skills(self, max: int = 20) -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"
        procedural = getattr(memory, "procedural_memory", None)
        if procedural is None:
            return "procedural memory unavailable"
        try:
            result = await procedural.list_skills(max=max)
        except Exception as exc:
            return f"list_skills failed: {type(exc).__name__}: {exc}"
        return str(result)

    async def _patch_skill(
        self,
        name: str,
        content: str,
        failure_notes: list[str],
        success_score: float | None = None,
        tool_sequence: list[dict[str, Any]] | None = None,
    ) -> str:
        memory = self._memory_service
        if memory is None:
            return "hyprmemory unavailable"
        procedural = getattr(memory, "procedural_memory", None)
        if procedural is None:
            return "procedural memory unavailable"
        try:
            result = await procedural.patch_skill(
                name=name.strip(),
                content=content.strip(),
                failure_notes=failure_notes,
                success_score=success_score,
                tool_sequence=tool_sequence,
            )
        except Exception as exc:
            return f"patch_skill failed: {type(exc).__name__}: {exc}"
        return str(result)

    async def _hyprctl_command(self, command: str) -> str:
        hyprland = self._resolve_hyprland()
        if hyprland is None:
            return "hyprland socket unavailable"

        normalized = self._normalize_hyprctl_input(command)
        if not normalized:
            return "hyprctl command is empty"

        candidates = [normalized]
        if normalized.startswith("/"):
            candidates.append(normalized.lstrip("/"))
        else:
            candidates.append(f"/{normalized}")

        response: str | Any = ""
        last_exc: Exception | None = None
        try:
            for candidate in candidates:
                try:
                    response = await hyprland.send_command(candidate)
                    normalized = candidate
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    continue
            if last_exc is not None:
                raise last_exc
        except Exception as exc:
            return f"hyprctl command failed: {type(exc).__name__}: {exc}"

        if self._hyprctl_modifies_runtime(normalized):
            notice = "Hypr-chan made modifications to Hyprland Runtime"
            notify_command = f'notify 1 3000 "rgb(00ffaa)" "{notice}"'
            try:
                await hyprland.send_command(notify_command)
            except Exception:
                # Best-effort UX signal for local user; command already succeeded.
                pass

        output = str(response).strip() or "ok"
        if len(output) > 450:
            output = f"{output[:450]}..."
        return f"hyprctl executed: {normalized}\nresult: {output}"

    @staticmethod
    def _normalize_hyprctl_input(command: str) -> str:
        normalized = " ".join(command.split()).strip()
        if not normalized:
            return ""

        if normalized.lower().startswith("hyprctl "):
            normalized = normalized[8:].strip()

        while normalized.startswith("-"):
            parts = normalized.split(maxsplit=1)
            if len(parts) == 1:
                return ""
            normalized = parts[1].strip()

        return normalized

    @staticmethod
    def _hyprctl_modifies_runtime(command: str) -> bool:
        normalized = " ".join(command.split()).strip().lower()
        if not normalized:
            return False

        if "--help" in normalized or normalized == "help":
            return False

        # Be conservative: notify only for known mutating operations.
        mutating_prefixes = (
            "dispatch",
            "keyword",
            "reload",
            "output",
            "setcursor",
            "seterror",
            "switchxkblayout",
        )
        for prefix in mutating_prefixes:
            if normalized == prefix or normalized.startswith(f"{prefix} "):
                return True

        return False

    async def execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> ToolExecutionResult:
        logger.debug("Executing tool calls count=%s", len(tool_calls))
        answer_called = False
        executed = 0
        followup_messages: list[dict[str, Any]] = []
        followup_events: list[dict[str, Any]] = []

        for tool_call in tool_calls:
            name = str(tool_call.get("name", "")).strip()
            args = tool_call.get("args")
            if not isinstance(args, dict):
                args = {}

            if name == "set_animation_pose":
                pose = str(args.get("pose", "")).strip()
                if not pose:
                    continue
                result = await self._set_animation_pose(pose)
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=result,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "answer_user":
                text = str(args.get("text", "")).strip()
                if not text:
                    continue
                result = await self._answer_user(text)
                answer_called = True
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=result,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "move_self":
                direction = str(args.get("direction", "")).strip().lower()
                try:
                    delta = int(args.get("delta", 0))
                except (TypeError, ValueError):
                    delta = 0
                try:
                    scale = float(args.get("scale", 1.0))
                except (TypeError, ValueError):
                    scale = 1.0

                summary, images = await self._move_self(
                    direction=direction,
                    delta=delta,
                    scale=scale,
                )
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=images,
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "screenshot":
                summary, images = await self._screenshot()
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=images,
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "camera":
                summary, images = await self._camera()
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=images,
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "memory_recall":
                query = str(args.get("query", "")).strip()
                if not query:
                    continue
                summary = await self._memory_recall(query)
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "episodic_recall":
                period = str(args.get("period", "recent")).strip()
                try:
                    limit = int(args.get("limit", 8))
                except (TypeError, ValueError):
                    limit = 8
                summary = await self._episodic_recall(period=period, limit=limit)
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "memorize":
                content = str(args.get("content", "")).strip()
                if not content:
                    continue
                note = str(args.get("note", "")).strip()
                summary = await self._memorize(content, note)
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "sleep_digest":
                summary = await self._sleep_digest()
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            if name == "hyprctl_command":
                command = str(args.get("command", "")).strip()
                if not command:
                    summary = (
                        "hyprctl_command failed: missing required argument `command`"
                    )
                    self._append_followup_message(
                        followup_messages,
                        followup_events,
                        tool_name=name,
                        summary=summary,
                        images=[],
                    )
                    executed += 1
                    logger.debug(
                        "Tool executed name=%s with invalid args=%s", name, args
                    )
                    continue
                summary = await self._hyprctl_command(command)
                self._append_followup_message(
                    followup_messages,
                    followup_events,
                    tool_name=name,
                    summary=summary,
                    images=[],
                )
                executed += 1
                logger.debug("Tool executed name=%s", name)
                continue

            dynamic_spec = self.tool_registry.get(name)
            if dynamic_spec is None:
                logger.debug("Unknown tool call skipped name=%s", name)
                continue

            try:
                dynamic_result = await dynamic_spec.tool.ainvoke(args)
                summary = self._summarize_dynamic_tool_result(name, dynamic_result)
            except Exception as exc:
                summary = f"{name} failed: {type(exc).__name__}: {exc}"

            self._append_followup_message(
                followup_messages,
                followup_events,
                tool_name=name,
                summary=summary,
                images=[],
            )
            executed += 1
            logger.debug("Tool executed name=%s", name)

        logger.debug(
            "Tool call execution complete executed=%s answer_called=%s",
            executed,
            answer_called,
        )
        return ToolExecutionResult(
            answer_user_called=answer_called,
            executed_calls=executed,
            followup_messages=followup_messages,
            followup_events=followup_events,
        )

    async def answer_user(self, text: str) -> None:
        await self._answer_user(text)

    async def _set_animation_pose(self, pose: str) -> str:
        engine = self._resolve_animation_engine()
        if engine is None:
            return "animation engine unavailable"

        set_pose = getattr(engine, "enqueue_set_pose", None)
        if not callable(set_pose):
            return "animation engine unavailable"

        normalized = pose.strip()
        if not normalized:
            return "pose is empty"

        available = engine.available_animation_names()
        if normalized not in available:
            return f"invalid pose. available poses: {', '.join(available)}"

        set_pose(normalized)
        return f"pose set to {normalized}"

    async def _answer_user(self, text: str) -> str:
        engine = self._resolve_animation_engine()
        message = text.strip()
        if not message:
            return "answer text is empty"

        self.last_answer_text = message
        if engine is None:
            return "animation engine unavailable"

        answer_user = getattr(engine, "enqueue_answer_text", None)
        if not callable(answer_user):
            return "animation engine unavailable"

        answer_user(message)
        return "answer rendered"

    async def _move_self(
        self,
        direction: str,
        delta: int,
        scale: float,
    ) -> tuple[str, list[dict[str, Any]]]:
        normalized_direction = direction.strip().lower()
        allowed = {
            "up",
            "down",
            "left",
            "right",
            "up_left",
            "up_right",
            "down_left",
            "down_right",
        }
        if normalized_direction not in allowed:
            return "invalid direction", []

        safe_delta = max(0, int(delta))
        safe_scale = max(0.0, min(2.0, float(scale)))

        moved, move_summary, hyprland_available = await self._move_overlay_window(
            direction=normalized_direction,
            delta=safe_delta,
        )

        if not moved and not hyprland_available:
            engine = self._resolve_animation_engine()
            move_self = getattr(engine, "enqueue_move_self", None) if engine else None
            if callable(move_self):
                move_self(
                    direction=normalized_direction,
                    delta=safe_delta,
                    scale=safe_scale,
                )
                move_summary = "moved via animation engine fallback"
            else:
                move_summary = f"{move_summary}; animation engine unavailable"

        await asyncio.sleep(0.35)
        screenshot = await asyncio.to_thread(self._capture_screenshot_file)
        summary = f"{move_summary}; scale set to {safe_scale:.2f}"
        images = [screenshot] if screenshot else []
        return summary, images

    async def _screenshot(self) -> tuple[str, list[dict[str, Any]]]:
        screenshot = await asyncio.to_thread(self._capture_screenshot_file)
        if screenshot is None:
            return "failed to capture screenshot", []
        return "captured screenshot", [screenshot]

    async def _camera(self) -> tuple[str, list[dict[str, Any]]]:
        camera = await asyncio.to_thread(self._capture_camera_file)
        if camera is None:
            return "failed to capture camera photo", []
        return "captured camera photo", [camera]

    @staticmethod
    def _runtime_output_dir() -> Path:
        path = Path(__file__).resolve().parents[5] / "runtime" / "perception"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _capture_screenshot_file(self) -> dict[str, Any] | None:
        process = subprocess.run(["grim", "-"], capture_output=True, check=False)
        if process.returncode != 0 or not process.stdout:
            return None

        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return None

        raw = np.frombuffer(process.stdout, dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if image is None:
            return None

        output_path = (
            self._runtime_output_dir() / f"tool_screen_{int(time.time() * 1000)}.jpg"
        )
        ok, encoded = cv2.imencode(
            ".jpg",
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), 85],
        )
        if not ok:
            return None

        output_path.write_bytes(bytes(encoded))
        return {
            "kind": "screen",
            "mime": "image/jpeg",
            "path": str(output_path),
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        }

    def _capture_camera_file(self) -> dict[str, Any] | None:
        shared_capture = self._capture_camera_from_shared_module()
        if shared_capture is not None:
            return shared_capture

        now = time.monotonic()
        if (
            now - self._camera_fallback_last_attempt_at
            < self._camera_fallback_cooldown_sec
        ):
            return None
        self._camera_fallback_last_attempt_at = now

        try:
            import cv2  # type: ignore
        except Exception:
            return None

        candidates = [int(WEBCAM_DEVICE_INDEX)]
        if WEBCAM_AUTO_FIND_DEVICE:
            for idx in range(max(0, int(WEBCAM_MAX_DEVICE_INDEX)) + 1):
                if idx not in candidates:
                    candidates.append(idx)

        for candidate in candidates:
            capture = cv2.VideoCapture(candidate)
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                continue

            ok, frame = capture.read()
            capture.release()
            if not ok or frame is None:
                continue

            return self._encode_camera_frame(frame)

        return None

    def _capture_camera_from_shared_module(self) -> dict[str, Any] | None:
        module = OpenCVPerceptionModule.latest_instance()
        if module is None or not module.is_running:
            return None

        frame = module.get_last_frame()
        if frame is None:
            return None

        return self._encode_camera_frame(frame)

    def _encode_camera_frame(self, frame: Any) -> dict[str, Any] | None:
        try:
            import cv2  # type: ignore
        except Exception:
            return None

        output_path = (
            self._runtime_output_dir() / f"tool_camera_{int(time.time() * 1000)}.jpg"
        )
        ok_encode, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 85],
        )
        if not ok_encode:
            return None

        output_path.write_bytes(bytes(encoded))
        shape = getattr(frame, "shape", None)
        width = int(shape[1]) if isinstance(shape, tuple) and len(shape) >= 2 else 0
        height = int(shape[0]) if isinstance(shape, tuple) and len(shape) >= 2 else 0
        return {
            "kind": "webcam",
            "mime": "image/jpeg",
            "path": str(output_path),
            "width": width,
            "height": height,
        }

    def _append_followup_message(
        self,
        out_messages: list[dict[str, Any]],
        out_events: list[dict[str, Any]],
        *,
        tool_name: str,
        summary: str,
        images: list[dict[str, Any]],
    ) -> None:
        lines = [f"Tool `{tool_name}` result: {summary}"]
        if images:
            image_kinds = ", ".join(str(item.get("kind", "image")) for item in images)
            lines.append(f"Attached images: {image_kinds}")
        text_block = "\n".join(lines)

        blocks: list[dict[str, Any]] = [{"type": "text", "text": text_block}]
        for image in images:
            data_url = self._image_path_to_data_url(
                path_value=image.get("path"),
                mime_hint=image.get("mime"),
            )
            if not data_url:
                continue
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "low"},
                }
            )

        content: Any
        if len(blocks) == 1:
            content = text_block
        else:
            content = blocks
        out_messages.append({"role": "user", "content": content})

        event_payload: dict[str, Any] = {
            "type": "tool_observation",
            "description": text_block,
            "origin": "linguistic_tools",
            "amplitude": 0.15,
            "tool_name": tool_name,
            "captured_at": time.time(),
        }
        if images:
            event_payload["images"] = images
        out_events.append(event_payload)

    @staticmethod
    def _summarize_dynamic_tool_result(name: str, result: Any) -> str:
        if result is None:
            return f"{name} completed"

        if isinstance(result, str):
            text = result.strip()
            return text or f"{name} completed"

        if isinstance(result, dict):
            status = str(result.get("status", "ok")).strip()
            detail = result.get("result", result.get("message", ""))
            detail_text = str(detail).strip() if detail is not None else ""
            if detail_text:
                return f"{name} [{status}]: {detail_text}"
            return f"{name} [{status}]"

        return f"{name}: {result}"

    @staticmethod
    def _image_path_to_data_url(path_value: Any, mime_hint: Any) -> str | None:
        if not isinstance(path_value, str) or not path_value.strip():
            return None

        path = Path(path_value)
        if not path.exists() or not path.is_file():
            return None

        try:
            raw = path.read_bytes()
        except OSError:
            return None

        if not raw:
            return None

        mime = ""
        if isinstance(mime_hint, str):
            mime = mime_hint.strip()
        if not mime:
            guessed, _ = mimetypes.guess_type(path.name)
            mime = guessed or "image/jpeg"

        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _resolve_animation_engine_from_di() -> AnimationEngine | None:
        fallback = object()
        try:
            maybe_engine = inject(AnimationEngine, fallback=fallback)
        except AssertionError:
            return None
        if maybe_engine is fallback:
            return None
        return maybe_engine
