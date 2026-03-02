import asyncio
from unittest.mock import AsyncMock

import pytest

from core.hypraios.constants import Phases
from core.hypraios.kernel.states import KernelStates
from core.hypraios.linguistic.inference_engine import InferenceEngine
from core.hypraios.mood.phase_engine import PhaseEngine
from core.hypraios.perception.activity_detector import AsyncActivityDetector
from core.hypraios.perception.watcher import PerceptionWatcher
from core.hypraios.utils.dynamic_variable import DynamicVariable


def _states() -> KernelStates:
    return KernelStates(
        f=DynamicVariable(value=12, min_val=0, max_val=100),
        v=DynamicVariable(value=0.1, min_val=-1, max_val=1),
        e=DynamicVariable(value=0.5, min_val=0, max_val=1),
        a=DynamicVariable(value=0.2, min_val=0, max_val=1),
        c=DynamicVariable(value=0.2, min_val=0, max_val=10),
        phase=Phases.PASSIVE,
    )


@pytest.mark.asyncio
async def test_phase_engine_parses_control_tag_and_updates_state():
    states = _states()
    engine = PhaseEngine(states)

    result = await engine.after_inference(
        input="thanks, this is great",
        output="<control>active user</control>Thanks for the prompt.",
    )

    assert states.phase == Phases.ACTIVE
    assert result["active_reason"] == "USER"
    assert "<control>" not in result["output"]
    assert -1 <= states.v.value <= 1
    assert 0 <= states.e.value <= 1


@pytest.mark.asyncio
async def test_perception_watcher_triggers_attention_callback():
    callback = AsyncMock()
    watcher = PerceptionWatcher(
        callback,
        activity_detector=AsyncActivityDetector(
            window_sec=8.0, attention_threshold=1.0
        ),
    )

    signal = await watcher.record_event(
        {
            "type": "workspace_toggle_burst",
            "description": "rapid toggles",
            "origin": "windows_controller",
            "amplitude": 1.1,
        }
    )

    await asyncio.sleep(0)
    drained = await watcher.drain_events()

    assert signal["attention_required"] is True
    assert callback.await_count == 1
    assert len(drained) == 1
    assert drained[0]["attention_required"] is True


@pytest.mark.asyncio
async def test_inference_engine_fallback_with_mock_llm_outputs():
    engine = InferenceEngine(model="openai/gpt-5.3")
    engine._post_json = AsyncMock(
        side_effect=[
            RuntimeError("responses endpoint unavailable"),
            {
                "model": "openai/gpt-5.3",
                "choices": [{"message": {"content": "Mock fallback answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        ]
    )

    result = await engine.infer(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.2,
        top_p=0.9,
    )

    assert result.output == "Mock fallback answer"
    assert result.total_tokens == 18

    first_endpoint = engine._post_json.await_args_list[0].args[0]
    second_endpoint = engine._post_json.await_args_list[1].args[0]
    assert first_endpoint == "/v1/responses"
    assert second_endpoint == "/v1/chat/completions"


@pytest.mark.asyncio
async def test_inference_engine_uses_chat_path_when_logit_bias_provided():
    engine = InferenceEngine(model="gpt-4o-mini")
    engine._post_json = AsyncMock(
        return_value={
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Biased response"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
    )

    result = await engine.infer(
        messages=[{"role": "user", "content": "test"}],
        temperature=0.2,
        top_p=0.9,
        logit_bias={"42": 5},
    )

    assert result.output == "Biased response"
    assert engine._post_json.await_count == 1
    endpoint = engine._post_json.await_args_list[0].args[0]
    payload = engine._post_json.await_args_list[0].args[1]
    assert endpoint == "/v1/chat/completions"
    assert payload["logit_bias"] == {"42": 5}
