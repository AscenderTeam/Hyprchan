from unittest.mock import AsyncMock

import pytest

from core.hypraios.contracts import PerceptionSource
from core.hypraios.perception.opencv_module import (
    OpenCVPerceptionConfig,
    OpenCVPerceptionModule,
)


class FakeFrameSource:
    def __init__(self, frames: list[object]) -> None:
        self._frames = list(frames)
        self.released = False

    def read(self) -> tuple[bool, object]:
        if not self._frames:
            return True, {"frame": "repeat"}
        return True, self._frames.pop(0)

    def release(self) -> None:
        self.released = True


class FakeMotionAnalyzer:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def analyze(self, previous_frame: object, current_frame: object) -> float:
        if not self._values:
            return 0.0
        return float(self._values.pop(0))


class FakeFaceAnalyzer:
    def __init__(self, values: list[tuple[int, float]]) -> None:
        self._values = list(values)

    def analyze(self, frame: object) -> tuple[int, float]:
        if not self._values:
            return 0, 0.0
        return self._values.pop(0)


@pytest.mark.asyncio
async def test_opencv_module_emits_face_presence_event() -> None:
    callback = AsyncMock()
    module = OpenCVPerceptionModule(
        callback,
        config=OpenCVPerceptionConfig(
            min_emit_interval_sec=0.0,
            min_face_ratio=0.001,
            max_amplitude=2.0,
        ),
        frame_source=FakeFrameSource([{"frame": 1}]),
        motion_analyzer=FakeMotionAnalyzer([0.0]),
        face_analyzer=FakeFaceAnalyzer([(1, 0.02)]),
    )

    event = await module.scan_once()

    assert event is not None
    assert event["type"] == "vision_face_presence"
    assert event["face_count"] == 1
    assert callback.await_count == 1


@pytest.mark.asyncio
async def test_opencv_module_emits_motion_event_when_no_face() -> None:
    callback = AsyncMock()
    module = OpenCVPerceptionModule(
        callback,
        config=OpenCVPerceptionConfig(
            min_emit_interval_sec=0.0,
            min_motion_ratio=0.05,
            amplitude_scale=4.0,
            max_amplitude=2.0,
        ),
        frame_source=FakeFrameSource([{"frame": 1}, {"frame": 2}]),
        motion_analyzer=FakeMotionAnalyzer([0.30]),
        face_analyzer=FakeFaceAnalyzer([(0, 0.0), (0, 0.0)]),
    )

    first = await module.scan_once()
    second = await module.scan_once()

    assert first is None
    assert second is not None
    assert second["type"] == "vision_motion"
    assert second["amplitude"] == pytest.approx(1.2)
    assert callback.await_count == 1


@pytest.mark.asyncio
async def test_opencv_module_suppresses_event_below_thresholds() -> None:
    callback = AsyncMock()
    module = OpenCVPerceptionModule(
        callback,
        config=OpenCVPerceptionConfig(
            min_emit_interval_sec=0.0,
            min_motion_ratio=0.2,
            min_face_ratio=0.02,
        ),
        frame_source=FakeFrameSource([{"frame": 1}, {"frame": 2}]),
        motion_analyzer=FakeMotionAnalyzer([0.05]),
        face_analyzer=FakeFaceAnalyzer([(0, 0.0), (1, 0.005)]),
    )

    await module.scan_once()
    event = await module.scan_once()

    assert event is None
    assert callback.await_count == 0


def test_opencv_module_implements_perception_contract() -> None:
    async def _callback(_: dict[str, object]) -> None:
        return None

    module = OpenCVPerceptionModule(
        _callback,
        frame_source=FakeFrameSource([{"frame": 1}]),
        motion_analyzer=FakeMotionAnalyzer([0.0]),
        face_analyzer=FakeFaceAnalyzer([(0, 0.0)]),
    )

    assert isinstance(module, PerceptionSource)
