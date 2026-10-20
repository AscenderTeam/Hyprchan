import asyncio
import subprocess
import time

import pytest

from core.hypraios.perception.multimodal_snapshot_source import (
    MultimodalSnapshotConfig,
    MultimodalSnapshotPerceptionSource,
)


class _FakeFrame:
    shape = (10, 20, 3)


class _FakeCv2:
    IMWRITE_JPEG_QUALITY = 1

    @staticmethod
    def imencode(_ext, _frame, _params):
        return True, b"jpeg-bytes"


def test_webcam_capture_waits_for_warmup(monkeypatch, tmp_path):
    calls = {"supplier": 0}

    def _supplier():
        calls["supplier"] += 1
        return _FakeFrame()

    source = MultimodalSnapshotPerceptionSource(
        lambda _event: None,
        config=MultimodalSnapshotConfig(output_dir=tmp_path, webcam_warmup_sec=3.0),
        webcam_frame_supplier=_supplier,
    )

    monkeypatch.setattr(
        MultimodalSnapshotPerceptionSource,
        "_load_cv2_and_numpy",
        staticmethod(lambda: (_FakeCv2, object())),
    )

    source._webcam_ready_at = time.monotonic() + 5.0
    early = source._capture_webcam()
    assert early is None
    assert calls["supplier"] == 0

    source._webcam_ready_at = 0.0
    ready = source._capture_webcam()
    assert ready is not None
    assert ready["kind"] == "webcam"
    assert calls["supplier"] == 1


@pytest.mark.parametrize("failure", [FileNotFoundError("grim"), subprocess.TimeoutExpired("grim", 3)])
def test_unavailable_screenshot_does_not_discard_camera(monkeypatch, tmp_path, failure):
    events = []
    source = MultimodalSnapshotPerceptionSource(
        events.append,
        config=MultimodalSnapshotConfig(output_dir=tmp_path, webcam_warmup_sec=0),
        webcam_frame_supplier=lambda: _FakeFrame(),
    )

    def unavailable(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", unavailable)
    monkeypatch.setattr(MultimodalSnapshotPerceptionSource, "_load_cv2_and_numpy",
                        staticmethod(lambda: (_FakeCv2, object())))
    asyncio.run(source.scan_once())
    assert len(events) == 1
    assert [image["kind"] for image in events[0]["images"]] == ["webcam"]
    assert source.last_error is not None
