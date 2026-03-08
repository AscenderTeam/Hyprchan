import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from core.hypraios.constants import Phases
from core.hypraios.kernel.states import KernelStates
from core.hypraios.linguistic.inference_engine import InferenceEngine, InferenceResult
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
    engine = InferenceEngine(model="gpt-4o-mini")
    engine.provider.inference = AsyncMock(
        side_effect=[
            RuntimeError("model rejected logit_bias"),
            InferenceResult(
                output="Mock fallback answer",
                model="gpt-4o-mini",
                input_tokens=12,
                output_tokens=6,
                total_tokens=18,
                tool_calls=[],
                raw={},
            ),
        ]
    )

    result = await engine.infer(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.2,
        top_p=0.9,
        logit_bias={"42": 5},
    )

    assert result.output == "Mock fallback answer"
    assert result.total_tokens == 18
    assert engine.provider.inference.await_count == 2
    assert engine.provider.inference.await_args_list[0].args[0].logit_bias == {"42": 5}
    assert engine.provider.inference.await_args_list[1].args[0].logit_bias is None


@pytest.mark.asyncio
async def test_inference_engine_uses_chat_path_when_logit_bias_provided():
    engine = InferenceEngine(model="gpt-4o-mini")
    engine.provider.inference = AsyncMock(
        return_value=InferenceResult(
            output="Biased response",
            model="gpt-4o-mini",
            input_tokens=5,
            output_tokens=3,
            total_tokens=8,
            tool_calls=[],
            raw={},
        )
    )

    result = await engine.infer(
        messages=[{"role": "user", "content": "test"}],
        temperature=0.2,
        top_p=0.9,
        logit_bias={"42": 5},
    )

    assert result.output == "Biased response"
    assert engine.provider.inference.await_count == 1
    request = engine.provider.inference.await_args_list[0].args[0]
    assert request.logit_bias == {"42": 5}


@pytest.mark.asyncio
async def test_inference_engine_allows_empty_output_when_tool_calls_present():
    engine = InferenceEngine(model="gpt-4o-mini")
    engine.provider.inference = AsyncMock(
        return_value=InferenceResult(
            output="",
            model="gpt-4o-mini",
            input_tokens=3,
            output_tokens=1,
            total_tokens=4,
            tool_calls=[{"name": "answer_user", "args": {"text": "hi"}}],
            raw={},
        )
    )

    result = await engine.infer(
        messages=[{"role": "user", "content": "test"}],
        temperature=0.2,
        top_p=0.9,
        tools=[object()],
    )

    assert result.output == ""
    assert result.tool_calls == [{"name": "answer_user", "args": {"text": "hi"}}]


def test_inference_engine_disables_top_p_for_gpt5_models():
    assert InferenceEngine._supports_top_p("gpt-4o-mini") is True
    assert InferenceEngine._supports_top_p("gpt-5-nano") is False
    assert InferenceEngine._supports_top_p("openai/gpt-5") is False


def test_inference_engine_disables_logit_bias_for_gpt5_models():
    assert InferenceEngine._supports_logit_bias("gpt-4o-mini") is True
    assert InferenceEngine._supports_logit_bias("gpt-5-nano") is False
    assert InferenceEngine._supports_logit_bias("openai/gpt-5") is False


@pytest.mark.asyncio
async def test_inference_engine_invocation_uses_max_tokens_not_max_completion_tokens(
    monkeypatch,
):
    captured_kwargs: dict[str, object] = {}

    class _DummyLLM:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def ainvoke(self, _messages):
            return AIMessage(content="ok")

    monkeypatch.setattr(
        "core.hypraios.linguistic.inference_engine.ChatOpenAI",
        _DummyLLM,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "token")

    engine = InferenceEngine(model="gpt-4o-mini")
    result = await engine.infer(
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.1,
        top_p=0.8,
        max_output_tokens=120,
    )

    assert result.output == "ok"
    assert captured_kwargs.get("max_tokens") == 120
    model_kwargs = captured_kwargs.get("model_kwargs")
    if isinstance(model_kwargs, dict):
        assert "max_completion_tokens" not in model_kwargs
