from unittest.mock import AsyncMock

import pytest

from core.hypraios.kernel.event_compaction import (
    EventCompactionRequest,
    GPT5NanoEventCompacter,
)
from core.hypraios.linguistic.inference_engine import InferenceResult


@pytest.mark.asyncio
async def test_gpt5_nano_compacter_normalizes_to_one_sentence() -> None:
    fake_engine = AsyncMock()
    fake_engine.infer = AsyncMock(
        return_value=InferenceResult(
            output="Windows changed rapidly. Camera stayed active.",
            model="gpt-5-nano",
            input_tokens=12,
            output_tokens=8,
            total_tokens=20,
            tool_calls=[],
            raw={},
        )
    )
    compacter = GPT5NanoEventCompacter(inference_engine=fake_engine)

    result = await compacter.compact(
        EventCompactionRequest(
            events=[
                {
                    "type": "window_focus",
                    "origin": "windows_controller",
                    "description": "focus changed",
                    "amplitude": 0.2,
                }
            ]
        )
    )

    assert result is not None
    assert result.summary == "Windows changed rapidly."
    assert result.compacted_count == 1


@pytest.mark.asyncio
async def test_gpt5_nano_compacter_falls_back_when_inference_fails() -> None:
    fake_engine = AsyncMock()
    fake_engine.infer = AsyncMock(side_effect=RuntimeError("boom"))
    compacter = GPT5NanoEventCompacter(inference_engine=fake_engine)

    result = await compacter.compact(
        EventCompactionRequest(
            events=[
                {
                    "type": "vision_motion",
                    "origin": "opencv_perception",
                    "description": "camera motion detected",
                    "amplitude": 0.4,
                },
                {
                    "type": "vision_motion",
                    "origin": "opencv_perception",
                    "description": "camera motion detected",
                    "amplitude": 0.5,
                },
            ]
        )
    )

    assert result is not None
    assert result.model == "gpt-5-nano"
    assert result.summary.endswith(".")
    assert result.compacted_count == 2
