from unittest.mock import AsyncMock

import pytest

from core.hypraios.constants import Phases
from core.hypraios.kernel.states import KernelStates
from core.hypraios.linguistic.inference_engine import InferenceResult
from core.hypraios.linguistic.linguistic_engine import LinguisticEngine
from core.hypraios.linguistic.passive_inference import SYSTEM_INTRO_MESSAGE
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
    user_prompt = infer_call.kwargs["messages"][1]["content"]
    assert user_prompt == "Please respond now"
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
