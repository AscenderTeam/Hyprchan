from unittest.mock import AsyncMock

import pytest

from core.hypraios.constants import Phases
from core.hypraios.linguistic.inference_engine import InferenceResult
from core.hypraios.utils.tui import HyprRichTUI


@pytest.mark.asyncio
async def test_sleep_consolidation_step_generates_dream_and_reduces_fatigue():
    tui = HyprRichTUI(model="gpt-4o-mini")
    tui.linguistic_engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="*In sleep, I replay bright moments and scattered neon dreams.*",
            model="gpt-4o-mini",
            input_tokens=12,
            output_tokens=10,
            total_tokens=22,
            tool_calls=[],
            raw={},
        )
    )

    tui.pending_memory_units = 4.0
    tui.states.f.value = 100.0
    tui._enter_sleep("test-trigger")
    tui.sleep_next_step_at = 0.0

    await tui._run_sleep_consolidation_step()

    assert tui.sleep_memory_processed > 0
    assert tui.states.f.value == 80.0
    assert any("HyprAI" in line for line in tui.chat_lines)
    assert tui.sleep_step_interval_sec == 0.4
    assert len(tui.sleep_context_messages) >= 3
    assert len(tui.sleep_dream_archive) == 1

    infer_call = tui.linguistic_engine.inference_engine.infer.await_args
    assert infer_call is not None
    assert infer_call.kwargs["frequency_penalty"] >= 1.8
    assert infer_call.kwargs["presence_penalty"] >= 1.0


@pytest.mark.asyncio
async def test_sleep_consolidation_finishes_and_returns_to_passive():
    tui = HyprRichTUI(model="gpt-4o-mini")
    tui.linguistic_engine.inference_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="*A soft wakeful calm returns after dream replay.*",
            model="gpt-4o-mini",
            input_tokens=8,
            output_tokens=8,
            total_tokens=16,
            tool_calls=[],
            raw={},
        )
    )

    tui.pending_memory_units = 1.0
    tui.states.f.value = 8.0
    tui._enter_sleep("test-finish")
    tui.sleep_next_step_at = 0.0

    await tui._run_sleep_consolidation_step()

    assert tui.sleep_active is False
    assert tui.states.phase.name == "PASSIVE"


def test_finish_sleep_retains_two_random_sleep_fragments_in_context():
    tui = HyprRichTUI(model="gpt-4o-mini")
    tui.sleep_active = True
    tui.states.phase = Phases.SLEEP
    tui.sleep_dream_archive.extend(
        [
            "dream fragment one",
            "dream fragment two",
            "dream fragment three",
        ]
    )

    tui._finish_sleep()

    retained = [
        msg
        for msg in list(tui.context_messages)
        if msg.get("role") == "system"
        and str(msg.get("content", "")).startswith("Sleep memory fragment retained:")
    ]
    assert len(retained) == 2
