import asyncio
import logging
import time
from unittest.mock import AsyncMock

import pytest

from core.hypraios.constants import Phases
from core.hypraios.kernel.event_compaction import EventCompactionResult
from core.hypraios.kernel.kernel import HyprAIOSKernel


class _FakeAnimationEngine:
    def __init__(self) -> None:
        self.loaded_animations: list[str] = []

    def load_animation(self, _name: str) -> None:
        self.loaded_animations.append(_name)
        return None


class _BrokenAnimationEngine:
    def load_animation(self, _name: str) -> None:
        raise ValueError("Animation not found")


class _FakeCompacter:
    def __init__(self) -> None:
        self.calls = 0

    async def compact(self, request):
        self.calls += 1
        return EventCompactionResult(
            summary=f"Background telemetry changed during window {self.calls}.",
            model="gpt-5-nano",
            compacted_count=len(getattr(request, "events", [])),
        )


@pytest.mark.asyncio
async def test_kernel_non_user_event_is_buffered_without_immediate_inference():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    kernel.linguistic_engine.feed = AsyncMock(
        return_value={
            "input": "mock input",
            "output": "<control>active self</control>mock output",
            "total_tokens": 40,
        }
    )
    kernel.phase_engine.after_inference = AsyncMock(
        return_value={
            "output": "mock output",
            "delta": 0.1,
            "rudeness": 0.0,
            "mood": "cheerful",
            "active_reason": "SELF",
        }
    )

    await kernel.record_perception(
        event_type="workspace_burst",
        description="rapid workspace toggles",
        origin="windows_controller",
        amplitude=7.0,
    )

    await kernel.on_loop()

    assert kernel.states.phase == Phases.PASSIVE
    assert kernel.states.f.value > 0
    assert kernel.linguistic_engine.feed.await_count == 0
    assert kernel.phase_engine.after_inference.await_count == 0
    assert len(kernel.context_events) >= 1


@pytest.mark.asyncio
async def test_force_active_user_path_from_sleep_state():
    fake_animations = _FakeAnimationEngine()
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), fake_animations)
    kernel.start_awake_loop = AsyncMock()
    kernel.states.phase = Phases.SLEEP

    await kernel.record_perception(
        event_type="communication_summon",
        description="user direct summon",
        origin="communication_controller",
        amplitude=1.0,
        force_active=True,
    )

    assert kernel.states.phase == Phases.ACTIVE
    assert kernel.active_reason == "USER"
    assert fake_animations.loaded_animations[-1] == "sit.startle_wakeup"
    assert kernel.start_awake_loop.await_count == 1


@pytest.mark.asyncio
async def test_start_sleep_loop_survives_missing_sleep_animation() -> None:
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _BrokenAnimationEngine())
    kernel.main_loop.stop = AsyncMock()
    kernel._sleep_worker = AsyncMock(return_value=None)

    await kernel.start_sleep_loop()

    assert kernel.states.phase == Phases.SLEEP
    assert kernel.main_loop.stop.await_count == 1
    if kernel._sleep_task is not None:
        await asyncio.wait_for(kernel._sleep_task, timeout=1.0)


@pytest.mark.asyncio
async def test_sleep_completion_plays_wakeup_animation() -> None:
    fake_animations = _FakeAnimationEngine()
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), fake_animations)
    kernel.start_awake_loop = AsyncMock()
    kernel.memory_gate.enabled = False
    kernel.states.f.value = 1.0
    kernel.pending_memory_units = 1.0
    kernel.sleep_dt = 0.0

    await kernel.start_sleep_loop()

    assert kernel._sleep_task is not None
    await asyncio.wait_for(kernel._sleep_task, timeout=1.0)

    assert "sit.falling_asleep" in fake_animations.loaded_animations
    assert fake_animations.loaded_animations[-1] == "sit.startle_wakeup"


@pytest.mark.asyncio
async def test_communicate_triggers_inference_and_returns_response():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    kernel.linguistic_engine.feed = AsyncMock(
        return_value={
            "input": "hello",
            "output": "Hi there.",
            "total_tokens": 12,
        }
    )
    kernel.phase_engine.after_inference = AsyncMock(
        return_value={
            "output": "Hi there.",
            "delta": 0.0,
            "rudeness": 0.0,
            "mood": "neutral",
            "active_reason": "USER",
        }
    )

    pending = asyncio.create_task(kernel.communicate("hello", timeout_sec=5))
    await asyncio.sleep(0)
    await kernel.on_loop()
    result = await pending

    assert result["status"] == "ok"
    assert result["response"]["output"] == "Hi there."
    assert kernel.linguistic_engine.feed.await_count == 1
    assert kernel.phase_engine.after_inference.await_count == 1


@pytest.mark.asyncio
async def test_passive_ponder_runs_after_idle_threshold_without_user_event():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    kernel.linguistic_engine.feed = AsyncMock(
        return_value={
            "input": "internal",
            "output": "passive output",
            "total_tokens": 9,
        }
    )
    kernel.phase_engine.after_inference = AsyncMock(
        return_value={
            "output": "passive output",
            "delta": 0.0,
            "rudeness": 0.0,
            "mood": "steady",
            "active_reason": "SELF",
        }
    )

    kernel.states.phase = Phases.PASSIVE
    kernel.passive_ponder_idle_threshold_sec = 0.0
    kernel.last_user_input_at = time.monotonic() - 5.0
    kernel.next_passive_ponder_at = time.monotonic() - 1.0

    await kernel.on_loop()

    assert kernel.linguistic_engine.feed.await_count == 1
    assert kernel.phase_engine.after_inference.await_count == 1


@pytest.mark.asyncio
async def test_user_inference_uses_compacted_context_window_when_telemetry_is_large():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    kernel.linguistic_engine.feed = AsyncMock(
        return_value={
            "input": "hello",
            "output": "ok",
            "total_tokens": 4,
        }
    )
    kernel.phase_engine.after_inference = AsyncMock(
        return_value={
            "output": "ok",
            "delta": 0.0,
            "rudeness": 0.0,
            "mood": "neutral",
            "active_reason": "USER",
        }
    )

    for idx in range(120):
        await kernel.record_perception(
            event_type="vision_motion",
            description=f"motion-{idx}",
            origin="opencv_perception",
            amplitude=0.2,
        )

    await kernel.record_perception(
        event_type="communication_message",
        description="hello user",
        origin="communication_controller",
        amplitude=1.0,
        force_active=True,
    )

    await kernel.on_loop()

    assert kernel.linguistic_engine.feed.await_count == 1
    infer_call = kernel.linguistic_engine.feed.await_args
    assert infer_call is not None
    infer_inputs = infer_call.args[0]
    assert len(infer_inputs) <= 90
    assert infer_inputs[-1]["origin"] == "communication_controller"
    assert any(
        str(event.get("type", "")) == "context_compaction" for event in infer_inputs
    )


@pytest.mark.asyncio
async def test_compaction_replaces_50_non_user_events_with_single_context_event() -> (
    None
):
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    fake_compacter = _FakeCompacter()
    kernel.event_compacter = fake_compacter
    kernel.event_compaction_keep_tail = 0
    kernel.event_compaction_batch_size = 50

    for idx in range(50):
        await kernel.record_perception(
            event_type="window_focus",
            description=f"focus-{idx}",
            origin="windows_controller",
            amplitude=0.2,
        )

    await kernel.on_loop()

    context = list(kernel.context_events)
    assert fake_compacter.calls == 1
    assert len(context) == 1
    assert context[0]["type"] == "context_compaction"
    assert context[0]["origin"] == "memory_compacter"
    assert context[0]["compacted_count"] == 50


@pytest.mark.asyncio
async def test_compaction_preserves_user_communication_events() -> None:
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    fake_compacter = _FakeCompacter()
    kernel.event_compacter = fake_compacter
    kernel.event_compaction_keep_tail = 0
    kernel.event_compaction_batch_size = 50

    for idx in range(50):
        await kernel.record_perception(
            event_type="vision_motion",
            description=f"motion-a-{idx}",
            origin="opencv_perception",
            amplitude=0.2,
        )

    await kernel.record_perception(
        event_type="communication_message",
        description="do not compact me",
        origin="communication_controller",
        amplitude=1.0,
    )

    for idx in range(50):
        await kernel.record_perception(
            event_type="window_focus",
            description=f"focus-b-{idx}",
            origin="windows_controller",
            amplitude=0.2,
        )

    await kernel.on_loop()

    context = list(kernel.context_events)
    assert fake_compacter.calls == 2
    communication_events = [
        event
        for event in context
        if str(event.get("origin", "")) == "communication_controller"
    ]
    assert len(communication_events) == 1
    assert communication_events[0]["description"] == "do not compact me"
    compactions = [
        event for event in context if str(event.get("type", "")) == "context_compaction"
    ]
    assert len(compactions) == 2


@pytest.mark.asyncio
async def test_tool_observation_saved_before_agent_response_event() -> None:
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"), _FakeAnimationEngine())
    kernel.linguistic_engine.feed = AsyncMock(
        return_value={
            "input": "hello",
            "output": "final reply",
            "total_tokens": 8,
            "tool_events": [
                {
                    "type": "tool_observation",
                    "origin": "linguistic_tools",
                    "description": "Tool `screenshot` result: captured screenshot",
                    "images": [
                        {
                            "kind": "screen",
                            "mime": "image/jpeg",
                            "path": "/tmp/screen.jpg",
                        }
                    ],
                }
            ],
        }
    )
    kernel.phase_engine.after_inference = AsyncMock(
        return_value={
            "output": "final reply",
            "delta": 0.0,
            "rudeness": 0.0,
            "mood": "neutral",
            "active_reason": "USER",
        }
    )

    await kernel.record_perception(
        event_type="communication_message",
        description="trigger",
        origin="communication_controller",
        amplitude=1.0,
        force_active=True,
    )

    await kernel.on_loop()

    tool_events = [
        e for e in kernel.context_events if e.get("origin") == "linguistic_tools"
    ]
    agent_events = [
        e for e in kernel.context_events if e.get("origin") == "hyprchan_agent"
    ]

    assert len(tool_events) >= 1
    assert len(agent_events) >= 1
    assert int(tool_events[-1]["id"]) < int(agent_events[-1]["id"])
    assert isinstance(tool_events[-1].get("images"), list)
