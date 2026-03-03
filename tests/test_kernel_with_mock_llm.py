import asyncio
import logging
import time
from unittest.mock import AsyncMock

import pytest

from core.hypraios.constants import Phases
from core.hypraios.kernel.kernel import HyprAIOSKernel


@pytest.mark.asyncio
async def test_kernel_non_user_event_is_buffered_without_immediate_inference():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"))
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
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"))
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
    assert kernel.start_awake_loop.await_count == 1


@pytest.mark.asyncio
async def test_communicate_triggers_inference_and_returns_response():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"))
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
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"))
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
async def test_user_inference_uses_recent_90_event_context_window():
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"))
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
    assert len(infer_inputs) == 90
    assert infer_inputs[-1]["origin"] == "communication_controller"


@pytest.mark.asyncio
async def test_tool_observation_saved_before_agent_response_event() -> None:
    kernel = HyprAIOSKernel(logging.getLogger("kernel-test"))
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
