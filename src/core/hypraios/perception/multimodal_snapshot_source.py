import asyncio
import inspect
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.hypraios.contracts import (
    PerceptionEvent,
    PerceptionEventCallback,
    PerceptionStatus,
)


@dataclass(slots=True)
class MultimodalSnapshotConfig:
    interval_sec: float = 120.0
    screenshot_downscale: float = 2.0
    jpeg_quality: int = 85
    output_dir: Path = Path(__file__).resolve().parents[4] / "runtime" / "perception"
    origin: str = "multimodal_snapshot_source"
    event_type: str = "perception_visual_snapshot"
    webcam_warmup_sec: float = 3.0

    def __post_init__(self) -> None:
        self.interval_sec = max(10.0, float(self.interval_sec))
        self.screenshot_downscale = max(1.0, float(self.screenshot_downscale))
        self.jpeg_quality = max(60, min(95, int(self.jpeg_quality)))
        self.output_dir = Path(self.output_dir)
        self.webcam_warmup_sec = max(0.0, float(self.webcam_warmup_sec))


class MultimodalSnapshotPerceptionSource:
    def __init__(
        self,
        event_callback: PerceptionEventCallback,
        *,
        config: MultimodalSnapshotConfig | None = None,
        webcam_frame_supplier: Callable[[], Any | None] | None = None,
    ) -> None:
        self.event_callback = event_callback
        self.config = config or MultimodalSnapshotConfig()
        self.webcam_frame_supplier = webcam_frame_supplier

        self._running = False
        self._task: asyncio.Task | None = None
        self._last_error: str | None = None
        self._last_observation: dict[str, Any] | None = None
        self._last_emit_at = 0.0
        self._started_at = 0.0
        self._webcam_ready_at = 0.0

    @property
    def source_name(self) -> str:
        return self.config.origin

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_observation(self) -> dict[str, Any] | None:
        return self._last_observation

    async def start(self) -> None:
        if self._task and not self._task.done():
            return

        self._started_at = time.monotonic()
        self._webcam_ready_at = self._started_at + self.config.webcam_warmup_sec
        self._running = True
        self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def scan_once(self, *, emit: bool = True) -> PerceptionEvent | None:
        screenshot = await asyncio.to_thread(self._capture_screenshot)
        webcam = await asyncio.to_thread(self._capture_webcam)

        images: list[dict[str, Any]] = []
        if screenshot:
            images.append(screenshot)
        if webcam:
            images.append(webcam)

        observation = {
            "timestamp": time.time(),
            "image_count": len(images),
            "has_screenshot": bool(screenshot),
            "has_webcam": bool(webcam),
        }
        self._last_observation = observation

        if not emit or not images:
            return None

        event: PerceptionEvent = {
            "type": self.config.event_type,
            "origin": self.config.origin,
            "amplitude": 0.25,
            "description": "periodic visual snapshot captured",
            "images": images,
            "captured_at": observation["timestamp"],
        }

        callback_result = self.event_callback(event)
        if inspect.isawaitable(callback_result):
            await callback_result

        self._last_emit_at = time.monotonic()
        return event

    def status(self) -> PerceptionStatus:
        return {
            "source": self.source_name,
            "running": self.is_running,
            "last_error": self.last_error,
            "last_observation": self.last_observation,
            "interval_sec": self.config.interval_sec,
            "webcam_warmup_sec": self.config.webcam_warmup_sec,
        }

    async def _worker(self) -> None:
        while self._running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
            await asyncio.sleep(self.config.interval_sec)

    def _capture_screenshot(self) -> dict[str, Any] | None:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        process = subprocess.run(
            ["grim", "-"],
            capture_output=True,
            check=False,
        )
        if process.returncode != 0 or not process.stdout:
            return None

        try:
            cv2, np = self._load_cv2_and_numpy()
            raw = np.frombuffer(process.stdout, dtype=np.uint8)
            image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if image is None:
                return None

            if self.config.screenshot_downscale > 1.0:
                downscale = self.config.screenshot_downscale
                width = max(1, int(image.shape[1] / downscale))
                height = max(1, int(image.shape[0] / downscale))
                image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

            timestamp = int(time.time() * 1000)
            output_path = self.config.output_dir / f"screen_{timestamp}.jpg"
            ok, encoded = cv2.imencode(
                ".jpg",
                image,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(self.config.jpeg_quality)],
            )
            if not ok:
                return None
            output_path.write_bytes(bytes(encoded))
            return {
                "kind": "screen",
                "mime": "image/jpeg",
                "path": str(output_path),
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            }
        except Exception:
            return None

    def _capture_webcam(self) -> dict[str, Any] | None:
        if time.monotonic() < self._webcam_ready_at:
            return None

        supplier = self.webcam_frame_supplier
        if supplier is None:
            return None

        frame = supplier()
        if frame is None:
            return None

        try:
            cv2, _ = self._load_cv2_and_numpy()
            timestamp = int(time.time() * 1000)
            output_path = self.config.output_dir / f"webcam_{timestamp}.jpg"
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(self.config.jpeg_quality)],
            )
            if not ok:
                return None
            output_path.write_bytes(bytes(encoded))
            shape = getattr(frame, "shape", None)
            width = int(shape[1]) if isinstance(shape, tuple) and len(shape) >= 2 else 0
            height = (
                int(shape[0]) if isinstance(shape, tuple) and len(shape) >= 2 else 0
            )
            return {
                "kind": "webcam",
                "mime": "image/jpeg",
                "path": str(output_path),
                "width": width,
                "height": height,
            }
        except Exception:
            return None

    @staticmethod
    def _load_cv2_and_numpy() -> tuple[Any, Any]:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        return cv2, np
