import pytest

from core.hypraios.linguistic.tool_runtime import LinguisticToolRuntime


class FakeAnimationEngine:
    def __init__(self) -> None:
        self._available = ["sit.idle", "sit.depressed"]
        self.pose_commands: list[str] = []
        self.answer_commands: list[str] = []
        self.move_commands: list[tuple[str, int, float]] = []

    def available_animation_names(self) -> list[str]:
        return list(self._available)

    def enqueue_set_pose(self, pose: str) -> None:
        self.pose_commands.append(pose)

    def enqueue_answer_text(self, text: str) -> None:
        self.answer_commands.append(text)

    def enqueue_move_self(self, *, direction: str, delta: int, scale: float) -> None:
        self.move_commands.append((direction, delta, scale))


@pytest.mark.asyncio
async def test_tool_runtime_executes_pose_and_answer_tools() -> None:
    engine = FakeAnimationEngine()
    runtime = LinguisticToolRuntime(animation_engine_resolver=lambda: engine)

    runtime._capture_screenshot_file = lambda: {
        "kind": "screen",
        "mime": "image/jpeg",
        "path": "/tmp/tool_move.jpg",
    }
    runtime._image_path_to_data_url = (
        lambda path_value, mime_hint: "data:image/jpeg;base64,AAA="
    )

    result = await runtime.execute_tool_calls(
        [
            {"name": "set_animation_pose", "args": {"pose": "sit.idle"}},
            {"name": "answer_user", "args": {"text": "Hi from tool"}},
            {
                "name": "move_self",
                "args": {"direction": "up_right", "delta": 24, "scale": 1.2},
            },
        ]
    )

    assert result.executed_calls == 3
    assert result.answer_user_called is True
    assert engine.pose_commands == ["sit.idle"]
    assert engine.answer_commands == ["Hi from tool"]
    assert engine.move_commands == [("up_right", 24, 1.2)]
    assert len(result.followup_messages) == 3
    assert len(result.followup_events) == 3


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


@pytest.mark.asyncio
async def test_tool_runtime_clamps_move_self_scale_and_delta() -> None:
    engine = FakeAnimationEngine()
    runtime = LinguisticToolRuntime(animation_engine_resolver=lambda: engine)

    runtime._capture_screenshot_file = lambda: None

    message = await runtime._move_self(direction="down", delta=-5, scale=3.4)

    assert "scale set to 2.00" in message[0]
    assert engine.move_commands == [("down", 0, 2.0)]


@pytest.mark.asyncio
async def test_tool_runtime_screenshot_and_camera_produce_multimodal_followups() -> (
    None
):
    engine = FakeAnimationEngine()
    runtime = LinguisticToolRuntime(animation_engine_resolver=lambda: engine)

    runtime._capture_screenshot_file = lambda: {
        "kind": "screen",
        "mime": "image/jpeg",
        "path": "/tmp/screen.jpg",
    }
    runtime._capture_camera_file = lambda: {
        "kind": "webcam",
        "mime": "image/jpeg",
        "path": "/tmp/camera.jpg",
    }
    runtime._image_path_to_data_url = (
        lambda path_value, mime_hint: "data:image/jpeg;base64,AAA="
    )

    result = await runtime.execute_tool_calls(
        [
            {"name": "screenshot", "args": {}},
            {"name": "camera", "args": {}},
        ]
    )

    assert result.executed_calls == 2
    assert len(result.followup_messages) == 2
    assert len(result.followup_events) == 2
    first = result.followup_messages[0]
    second = result.followup_messages[1]
    assert first["role"] == "user"
    assert second["role"] == "user"
    assert isinstance(first["content"], list)
    assert isinstance(second["content"], list)
