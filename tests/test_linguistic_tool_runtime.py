import pytest

from core.hypraios.linguistic.tool_runtime import LinguisticToolRuntime


class FakeAnimationEngine:
    def __init__(self) -> None:
        self._available = ["sit.idle", "sit.depressed"]
        self.pose_commands: list[str] = []
        self.answer_commands: list[str] = []

    def available_animation_names(self) -> list[str]:
        return list(self._available)

    def enqueue_set_pose(self, pose: str) -> None:
        self.pose_commands.append(pose)

    def enqueue_answer_text(self, text: str) -> None:
        self.answer_commands.append(text)


@pytest.mark.asyncio
async def test_tool_runtime_executes_pose_and_answer_tools() -> None:
    engine = FakeAnimationEngine()
    runtime = LinguisticToolRuntime(animation_engine_resolver=lambda: engine)

    result = await runtime.execute_tool_calls(
        [
            {"name": "set_animation_pose", "args": {"pose": "sit.idle"}},
            {"name": "answer_user", "args": {"text": "Hi from tool"}},
        ]
    )

    assert result.executed_calls == 2
    assert result.answer_user_called is True
    assert engine.pose_commands == ["sit.idle"]
    assert engine.answer_commands == ["Hi from tool"]


@pytest.mark.asyncio
async def test_tool_runtime_rejects_invalid_pose() -> None:
    engine = FakeAnimationEngine()
    runtime = LinguisticToolRuntime(animation_engine_resolver=lambda: engine)

    message = await runtime._set_animation_pose("sit.unknown")

    assert "invalid pose" in message
    assert engine.pose_commands == []


def test_tool_runtime_exposes_loaded_pose_names() -> None:
    engine = FakeAnimationEngine()
    runtime = LinguisticToolRuntime(animation_engine_resolver=lambda: engine)

    tools = runtime.build_tools()
    pose_tool = next(tool for tool in tools if tool.name == "set_animation_pose")

    assert "sit.idle" in pose_tool.description
    assert "sit.depressed" in pose_tool.description
