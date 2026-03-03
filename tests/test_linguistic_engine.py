from unittest.mock import AsyncMock
from pathlib import Path

import pytest

from core.hypraios.constants import Phases
from core.hypraios.kernel.states import KernelStates
from core.hypraios.linguistic.inference_engine import InferenceResult
from core.hypraios.linguistic.linguistic_engine import LinguisticEngine
from core.hypraios.linguistic.passive_inference import SYSTEM_INTRO_MESSAGE
from core.hypraios.linguistic.tool_runtime import ToolExecutionResult
from core.hypraios.utils.dynamic_variable import DynamicVariable


def _build_states(phase: Phases) -> KernelStates:
    return KernelStates(
        f=DynamicVariable(value=5, min_val=0, max_val=100),
        v=DynamicVariable(value=0.3, min_val=-1, max_val=1),
        e=DynamicVariable(value=0.7, min_val=0, max_val=1),
        a=DynamicVariable(value=0.25, min_val=0, max_val=1),
        c=DynamicVariable(value=0.1, min_val=0, max_val=10),
        phase=phase,
    )


@pytest.mark.asyncio
async def test_feed_active_uses_mock_llm_and_communication_prompt():
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="<control>active user</control>Acknowledged.",
            model="openai/gpt-5.3",
            input_tokens=8,
            output_tokens=5,
            total_tokens=13,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "type": "communication_summon",
            "amplitude": 1.0,
            "description": "Please respond now",
            "origin": "communication_controller",
        },
        {
            "type": "window_focus",
            "amplitude": 0.4,
            "description": "window changed",
            "origin": "windows_controller",
        },
    ]

    result = await engine.feed(inputs, states)

    assert result is not None
    assert result["output"] == "<control>active user</control>Acknowledged."
    assert result["total_tokens"] == 13

    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    messages = infer_call.kwargs["messages"]
    assert messages[1]["role"] == "user"
    context_blob = messages[1]["content"]
    assert isinstance(context_blob, str)
    assert "Supporting perception context (passive inference format):" in context_blob
    assert "type=window_focus" in context_blob
    assert "Full event context window (last 90 events, raw data):" in context_blob
    assert '"origin":"windows_controller"' in context_blob
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "Please respond now"
    assert infer_call.kwargs["logit_bias"]
    assert result["bias_profile"] in {
        "sparkly",
        "cheerful",
        "irritated",
        "angry",
        "neutral",
    }


@pytest.mark.asyncio
async def test_feed_passive_uses_mock_llm_and_aggregated_prompt():
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="Passive digest complete.",
            model="openai/gpt-5.3",
            input_tokens=20,
            output_tokens=9,
            total_tokens=29,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.PASSIVE)
    inputs = [
        {
            "type": "workspace_switch",
            "amplitude": 0.3,
            "description": "workspace switched to coding",
            "origin": "windows_controller",
        },
        {
            "type": "workspace_switch",
            "amplitude": 0.6,
            "description": "workspace switched again",
            "origin": "windows_controller",
        },
    ]

    result = await engine.feed(inputs, states)

    assert result is not None
    assert result["output"] == "Passive digest complete."
    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    passive_prompt = infer_call.kwargs["messages"][1]["content"]
    assert SYSTEM_INTRO_MESSAGE in passive_prompt
    assert "System telemetry update:" in passive_prompt
    assert "type=workspace_switch" in passive_prompt
    assert infer_call.kwargs["logit_bias"]


@pytest.mark.asyncio
async def test_feed_passive_neutral_state_produces_no_logit_bias():
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="Neutral response.",
            model="openai/gpt-5.3",
            input_tokens=6,
            output_tokens=4,
            total_tokens=10,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.PASSIVE)
    states.v.value = 0.0
    states.e.value = 0.4
    inputs = [
        {
            "type": "window_focus",
            "amplitude": 0.2,
            "description": "window changed",
            "origin": "windows_controller",
        }
    ]

    result = await engine.feed(inputs, states)
    assert result is not None
    assert result["bias_profile"] == "neutral"
    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    assert infer_call.kwargs["logit_bias"] == {}


@pytest.mark.asyncio
async def test_feed_passive_system_intro_is_sent_once_per_session():
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="ok",
            model="openai/gpt-4o-mini",
            input_tokens=3,
            output_tokens=2,
            total_tokens=5,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.PASSIVE)
    inputs = [
        {
            "type": "workspace_switch",
            "amplitude": 0.2,
            "description": "workspace changed",
            "origin": "windows_controller",
        }
    ]

    await engine.feed(inputs, states)
    first_call = engine.inference_engine.infer.await_args_list[0]
    first_prompt = first_call.kwargs["messages"][1]["content"]
    assert SYSTEM_INTRO_MESSAGE in first_prompt

    await engine.feed(inputs, states)
    second_call = engine.inference_engine.infer.await_args_list[1]
    second_prompt = second_call.kwargs["messages"][1]["content"]
    assert SYSTEM_INTRO_MESSAGE not in second_prompt


@pytest.mark.asyncio
async def test_feed_active_attaches_multimodal_images_when_present(tmp_path: Path):
    image_file = tmp_path / "snapshot.jpg"
    image_file.write_bytes(b"fake-image")

    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="ok",
            model="gpt-4o-mini",
            input_tokens=4,
            output_tokens=2,
            total_tokens=6,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "look at this",
            "origin": "communication_controller",
        },
        {
            "type": "perception_visual_snapshot",
            "amplitude": 0.2,
            "description": "periodic visual snapshot captured",
            "origin": "multimodal_snapshot_source",
            "images": [
                {
                    "kind": "screen",
                    "mime": "image/jpeg",
                    "path": str(image_file),
                }
            ],
        },
    ]

    await engine.feed(inputs, states)

    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    user_content = infer_call.kwargs["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "text"
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_feed_active_attaches_all_images_from_recent_context(tmp_path: Path):
    image_a = tmp_path / "a.jpg"
    image_b = tmp_path / "b.jpg"
    image_a.write_bytes(b"image-a")
    image_b.write_bytes(b"image-b")

    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="ok",
            model="gpt-4o-mini",
            input_tokens=6,
            output_tokens=2,
            total_tokens=8,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "attach all images",
            "origin": "communication_controller",
        },
        {
            "type": "perception_visual_snapshot",
            "amplitude": 0.2,
            "description": "snapshot 1",
            "origin": "multimodal_snapshot_source",
            "images": [{"kind": "screen", "mime": "image/jpeg", "path": str(image_a)}],
        },
        {
            "type": "perception_visual_snapshot",
            "amplitude": 0.2,
            "description": "snapshot 2",
            "origin": "multimodal_snapshot_source",
            "images": [{"kind": "webcam", "mime": "image/jpeg", "path": str(image_b)}],
        },
    ]

    await engine.feed(inputs, states)

    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    user_content = infer_call.kwargs["messages"][1]["content"]
    assert isinstance(user_content, list)
    image_blocks = [block for block in user_content if block.get("type") == "image_url"]
    assert len(image_blocks) == 2


@pytest.mark.asyncio
async def test_feed_active_keeps_previous_user_messages_separate() -> None:
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="ok",
            model="gpt-4o-mini",
            input_tokens=5,
            output_tokens=3,
            total_tokens=8,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "id": 11,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "first message",
            "origin": "communication_controller",
        },
        {
            "id": 12,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "latest message",
            "origin": "communication_controller",
        },
    ]

    await engine.feed(inputs, states)

    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    messages = infer_call.kwargs["messages"]
    assert messages[1]["role"] == "user"
    assert messages[2] == {"role": "user", "content": "first message"}
    assert messages[3] == {"role": "user", "content": "latest message"}


@pytest.mark.asyncio
async def test_feed_active_includes_assistant_reply_after_user_when_present() -> None:
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="ok",
            model="gpt-4o-mini",
            input_tokens=5,
            output_tokens=3,
            total_tokens=8,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "id": 11,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "hello",
            "origin": "communication_controller",
        },
        {
            "id": 12,
            "type": "agent_response",
            "amplitude": 0.0,
            "description": "hi there",
            "origin": "hyprchan_agent",
        },
        {
            "id": 13,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "latest user",
            "origin": "communication_controller",
        },
    ]

    await engine.feed(inputs, states)

    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    messages = infer_call.kwargs["messages"]
    assert messages[1]["role"] == "user"
    assert messages[2] == {"role": "user", "content": "hello"}
    assert messages[3] == {"role": "assistant", "content": "hi there"}
    assert messages[4] == {"role": "user", "content": "latest user"}


@pytest.mark.asyncio
async def test_feed_active_replays_tool_observation_before_assistant_reply() -> None:
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="ok",
            model="gpt-4o-mini",
            input_tokens=5,
            output_tokens=3,
            total_tokens=8,
            tool_calls=[],
            raw={},
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "id": 11,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "hello",
            "origin": "communication_controller",
        },
        {
            "id": 12,
            "type": "tool_observation",
            "amplitude": 0.15,
            "description": "Tool `screenshot` result: captured screenshot",
            "origin": "linguistic_tools",
            "images": [],
        },
        {
            "id": 13,
            "type": "agent_response",
            "amplitude": 0.0,
            "description": "here is what I saw",
            "origin": "hyprchan_agent",
        },
        {
            "id": 14,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "latest user",
            "origin": "communication_controller",
        },
    ]

    await engine.feed(inputs, states)

    infer_call = engine.inference_engine.infer.await_args
    assert infer_call is not None
    messages = infer_call.kwargs["messages"]
    assert messages[2] == {"role": "user", "content": "hello"}
    assert messages[3] == {
        "role": "user",
        "content": "Tool `screenshot` result: captured screenshot",
    }
    assert messages[4] == {"role": "assistant", "content": "here is what I saw"}
    assert messages[5] == {"role": "user", "content": "latest user"}


@pytest.mark.asyncio
async def test_run_inference_performs_followup_after_multimodal_tool_outputs() -> None:
    engine = LinguisticEngine()
    engine.inference_engine.infer = AsyncMock(
        side_effect=[
            InferenceResult(
                output="",
                model="gpt-4o-mini",
                input_tokens=10,
                output_tokens=1,
                total_tokens=11,
                tool_calls=[{"name": "screenshot", "args": {}}],
                raw={},
            ),
            InferenceResult(
                output="I can see the screenshot now.",
                model="gpt-4o-mini",
                input_tokens=12,
                output_tokens=6,
                total_tokens=18,
                tool_calls=[],
                raw={},
            ),
        ]
    )
    engine.tool_runtime.execute_tool_calls = AsyncMock(
        return_value=ToolExecutionResult(
            answer_user_called=False,
            executed_calls=1,
            followup_messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Tool `screenshot` result: captured"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64,AAA=",
                                "detail": "low",
                            },
                        },
                    ],
                }
            ],
            followup_events=[
                {
                    "type": "tool_observation",
                    "origin": "linguistic_tools",
                    "description": "Tool `screenshot` result: captured",
                    "images": [
                        {
                            "kind": "screen",
                            "mime": "image/jpeg",
                            "path": "/tmp/fake.jpg",
                        }
                    ],
                }
            ],
        )
    )

    states = _build_states(Phases.ACTIVE)
    inputs = [
        {
            "id": 1,
            "type": "communication_message",
            "amplitude": 1.0,
            "description": "what do you see",
            "origin": "communication_controller",
        }
    ]

    result = await engine.feed(inputs, states)

    assert result is not None
    assert result["output"] == "I can see the screenshot now."
    assert result["input_tokens"] == 22
    assert result["output_tokens"] == 7
    assert result["total_tokens"] == 29
    assert engine.inference_engine.infer.await_count == 2
