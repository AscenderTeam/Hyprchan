from dataclasses import dataclass
from typing import Any, Callable

from ascender.core import inject
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.animations.engine import AnimationEngine


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


@dataclass
class ToolExecutionResult:
    answer_user_called: bool
    executed_calls: int


class LinguisticToolRuntime:
    def __init__(
        self,
        animation_engine_resolver: Callable[[], AnimationEngine | None] | None = None,
    ) -> None:
        self._resolve_animation_engine = (
            animation_engine_resolver or self._resolve_animation_engine_from_di
        )
        self.last_answer_text = ""

    def build_tools(self) -> list[StructuredTool]:
        available = self.available_animations()
        available_text = ", ".join(available) if available else "none"

        return [
            StructuredTool.from_function(
                coroutine=self._set_animation_pose,
                name="set_animation_pose",
                description=(
                    "Set Hyprchan animation pose from loaded animations. "
                    f"Available poses right now: {available_text}."
                ),
                args_schema=SetAnimationPoseInput,
            ),
            StructuredTool.from_function(
                coroutine=self._answer_user,
                name="answer_user",
                description=(
                    "Display text response in white on top of Hyprchan figure. "
                    "Use for user-visible response output."
                ),
                args_schema=AnswerUserInput,
            ),
        ]

    def available_animations(self) -> list[str]:
        engine = self._resolve_animation_engine()
        if engine is None:
            return []
        return engine.available_animation_names()

    async def execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> ToolExecutionResult:
        answer_called = False
        executed = 0
        for tool_call in tool_calls:
            name = str(tool_call.get("name", "")).strip()
            args = tool_call.get("args")
            if not isinstance(args, dict):
                args = {}

            if name == "set_animation_pose":
                pose = str(args.get("pose", "")).strip()
                if not pose:
                    continue
                await self._set_animation_pose(pose)
                executed += 1
                continue

            if name == "answer_user":
                text = str(args.get("text", "")).strip()
                if not text:
                    continue
                await self._answer_user(text)
                answer_called = True
                executed += 1

        return ToolExecutionResult(
            answer_user_called=answer_called,
            executed_calls=executed,
        )

    async def answer_user(self, text: str) -> None:
        await self._answer_user(text)

    async def _set_animation_pose(self, pose: str) -> str:
        engine = self._resolve_animation_engine()
        if engine is None:
            return "animation engine unavailable"

        normalized = pose.strip()
        if not normalized:
            return "pose is empty"

        available = engine.available_animation_names()
        if normalized not in available:
            return f"invalid pose. available poses: {', '.join(available)}"

        engine.enqueue_set_pose(normalized)
        return f"pose set to {normalized}"

    async def _answer_user(self, text: str) -> str:
        engine = self._resolve_animation_engine()
        message = text.strip()
        if not message:
            return "answer text is empty"

        self.last_answer_text = message
        if engine is None:
            return "animation engine unavailable"

        engine.enqueue_answer_text(message)
        return "answer rendered"

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
