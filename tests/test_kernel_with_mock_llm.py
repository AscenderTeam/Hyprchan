import logging
from unittest.mock import AsyncMock

import pytest

from core.hypraios.constants import Phases
from core.hypraios.kernel.kernel import HyprAIOSKernel


@pytest.mark.asyncio
async def test_kernel_on_loop_processes_event_with_mock_llm_output():
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

    assert kernel.states.phase == Phases.ACTIVE
    assert kernel.states.f.value > 0
    assert kernel.linguistic_engine.feed.await_count == 1
    assert kernel.phase_engine.after_inference.await_count == 1


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
