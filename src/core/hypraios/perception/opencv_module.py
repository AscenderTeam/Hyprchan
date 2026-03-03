import asyncio
import inspect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.hypraios.contracts import (
    PerceptionEvent,
    PerceptionEventCallback,
    PerceptionStatus,
)


class FrameSource(Protocol):
    def read(self) -> tuple[bool, Any]: ...

    def release(self) -> None: ...


class MotionAnalyzer(Protocol):
    def analyze(self, previous_frame: Any, current_frame: Any) -> float: ...


class FaceAnalyzer(Protocol):
    def analyze(self, frame: Any) -> tuple[int, float]: ...


class OpenCVUnavailableError(RuntimeError):
    pass


class OpenCVFrameSourceError(RuntimeError):
    pass


def _load_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise OpenCVUnavailableError(
            "OpenCV is required for OpenCVPerceptionModule. Install opencv-python-headless."
        ) from exc
    return cv2


@dataclass(slots=True)
class OpenCVPerceptionConfig:
    device_index: int = 0
    poll_interval_sec: float = 0.25
    min_motion_ratio: float = 0.02
    min_face_ratio: float = 0.002
    motion_threshold: int = 24
    blur_kernel_size: int = 7
    dilate_iterations: int = 2
    face_scale_factor: float = 1.2
    face_min_neighbors: int = 5
    face_min_size_px: int = 40
    face_cascade_path: str | None = None
    amplitude_scale: float = 8.0
    face_amplitude_base: float = 0.8
    face_amplitude_per_face: float = 0.3
    face_area_amplitude_scale: float = 6.0
    max_amplitude: float = 2.0
    min_emit_interval_sec: float = 1.2
    event_type: str = "vision_motion"
    face_event_type: str = "vision_face_presence"
    origin: str = "opencv_perception"
    description_template: str = "camera motion detected (ratio={ratio:.3f})"
    face_description_template: str = "camera sees {count} face(s)"

    def __post_init__(self) -> None:
        self.poll_interval_sec = max(0.01, float(self.poll_interval_sec))
        self.min_motion_ratio = max(0.0, float(self.min_motion_ratio))
        self.min_face_ratio = max(0.0, float(self.min_face_ratio))
        self.motion_threshold = max(1, int(self.motion_threshold))
        self.blur_kernel_size = max(1, int(self.blur_kernel_size))
        if self.blur_kernel_size % 2 == 0:
            self.blur_kernel_size += 1
        self.dilate_iterations = max(1, int(self.dilate_iterations))
        self.face_scale_factor = max(1.01, float(self.face_scale_factor))
        self.face_min_neighbors = max(1, int(self.face_min_neighbors))
        self.face_min_size_px = max(10, int(self.face_min_size_px))
        self.amplitude_scale = max(0.0, float(self.amplitude_scale))
        self.face_amplitude_base = max(0.0, float(self.face_amplitude_base))
        self.face_amplitude_per_face = max(0.0, float(self.face_amplitude_per_face))
        self.face_area_amplitude_scale = max(0.0, float(self.face_area_amplitude_scale))
        self.max_amplitude = max(0.0, float(self.max_amplitude))
        self.min_emit_interval_sec = max(0.0, float(self.min_emit_interval_sec))


@dataclass(slots=True)
class OpenCVObservation:
    motion_ratio: float
    face_count: int
    face_ratio: float
    timestamp: float


class OpenCVFrameSource:
    def __init__(self, device_index: int = 0, cv2_module: Any | None = None) -> None:
        self.device_index = int(device_index)
        self.cv2 = cv2_module or _load_cv2()
        self._capture: Any | None = None

    def read(self) -> tuple[bool, Any]:
        if self._capture is None:
            capture = self.cv2.VideoCapture(self.device_index)
            if capture is None or not capture.isOpened():
                raise OpenCVFrameSourceError(
                    f"Unable to open camera device index {self.device_index}."
                )
            self._capture = capture

        capture = self._capture
        if capture is None:
            raise OpenCVFrameSourceError(
                f"Camera capture was not initialized for device index {self.device_index}."
            )

        ok, frame = capture.read()
        return bool(ok), frame

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class OpenCVMotionAnalyzer:
    def __init__(
        self,
        config: OpenCVPerceptionConfig,
        cv2_module: Any | None = None,
    ) -> None:
        self.config = config
        self.cv2 = cv2_module or _load_cv2()

    def analyze(self, previous_frame: Any, current_frame: Any) -> float:
        if previous_frame is None or current_frame is None:
            return 0.0

        gray_previous = self.cv2.cvtColor(previous_frame, self.cv2.COLOR_BGR2GRAY)
        gray_current = self.cv2.cvtColor(current_frame, self.cv2.COLOR_BGR2GRAY)

        blurred_previous = self.cv2.GaussianBlur(
            gray_previous,
            (self.config.blur_kernel_size, self.config.blur_kernel_size),
            0,
        )
        blurred_current = self.cv2.GaussianBlur(
            gray_current,
            (self.config.blur_kernel_size, self.config.blur_kernel_size),
            0,
        )

        frame_delta = self.cv2.absdiff(blurred_previous, blurred_current)
        threshold_type = getattr(self.cv2, "THRESH_BINARY", 0)
        _, thresholded = self.cv2.threshold(
            frame_delta,
            self.config.motion_threshold,
            255,
            threshold_type,
        )
        dilated = self.cv2.dilate(
            thresholded,
            None,
            iterations=self.config.dilate_iterations,
        )

        changed_pixels = float(self.cv2.countNonZero(dilated))
        total_pixels = float(self._frame_size(dilated))
        if total_pixels <= 0:
            return 0.0

        return max(0.0, min(1.0, changed_pixels / total_pixels))

    @staticmethod
    def _frame_size(frame: Any) -> int:
        size = getattr(frame, "size", None)
        if isinstance(size, int) and size > 0:
            return size

        shape = getattr(frame, "shape", None)
        if isinstance(shape, tuple) and len(shape) >= 2:
            try:
                return int(shape[0]) * int(shape[1])
            except (TypeError, ValueError):
                return 0

        return 0


class OpenCVFaceAnalyzer:
    def __init__(
        self,
        config: OpenCVPerceptionConfig,
        cv2_module: Any | None = None,
    ) -> None:
        self.config = config
        self.cv2 = cv2_module or _load_cv2()
        cascade_path = self.config.face_cascade_path
        if not cascade_path:
            cascade_root = Path(self.cv2.data.haarcascades)
            cascade_path = str(cascade_root / "haarcascade_frontalface_default.xml")

        self._classifier = self.cv2.CascadeClassifier(cascade_path)
        if self._classifier.empty():
            raise OpenCVUnavailableError(
                "Unable to load face cascade for OpenCV face detection."
            )

    def analyze(self, frame: Any) -> tuple[int, float]:
        if frame is None:
            return 0, 0.0

        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        faces = self._classifier.detectMultiScale(
            gray,
            scaleFactor=self.config.face_scale_factor,
            minNeighbors=self.config.face_min_neighbors,
            minSize=(self.config.face_min_size_px, self.config.face_min_size_px),
        )

        face_count = int(len(faces))
        if face_count <= 0:
            return 0, 0.0

        total_pixels = float(gray.shape[0] * gray.shape[1]) if gray is not None else 0.0
        if total_pixels <= 0:
            return face_count, 0.0

        largest_ratio = 0.0
        for _, _, width, height in faces:
            area = float(width * height)
            largest_ratio = max(largest_ratio, area / total_pixels)

        return face_count, max(0.0, min(1.0, largest_ratio))


class OpenCVPerceptionModule:
    """
    OOP perception source for webcam signals.

    This module emits raw perception events only. It never mutates kernel state,
    changes phases, or triggers inference directly.
    """

    def __init__(
        self,
        event_callback: PerceptionEventCallback,
        *,
        config: OpenCVPerceptionConfig | None = None,
        frame_source: FrameSource | None = None,
        motion_analyzer: MotionAnalyzer | None = None,
        face_analyzer: FaceAnalyzer | None = None,
    ) -> None:
        self.config = config or OpenCVPerceptionConfig()
        self.event_callback = event_callback
        self.frame_source = frame_source or OpenCVFrameSource(
            device_index=self.config.device_index
        )
        self.motion_analyzer = motion_analyzer or OpenCVMotionAnalyzer(self.config)
        self.face_analyzer = face_analyzer or OpenCVFaceAnalyzer(self.config)

        self._previous_frame: Any | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_emit_at = 0.0
        self._last_observation: OpenCVObservation | None = None
        self._last_error: str | None = None
        self._last_frame: Any | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def source_name(self) -> str:
        return self.config.origin

    @property
    def last_observation(self) -> dict[str, Any] | None:
        if self._last_observation is None:
            return None

        return {
            "motion_ratio": self._last_observation.motion_ratio,
            "face_count": self._last_observation.face_count,
            "face_ratio": self._last_observation.face_ratio,
            "timestamp": self._last_observation.timestamp,
        }

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_last_frame(self) -> Any | None:
        frame = self._last_frame
        if frame is None:
            return None

        copier = getattr(frame, "copy", None)
        if callable(copier):
            return copier()
        return frame

    async def start(self) -> None:
        if self._task and not self._task.done():
            return

        await self.scan_once(emit=False)
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
        self._previous_frame = None
        self._last_frame = None
        self.frame_source.release()

    async def scan_once(self, *, emit: bool = True) -> PerceptionEvent | None:
        ok, frame = self.frame_source.read()
        if not ok:
            raise OpenCVFrameSourceError(
                f"Camera read failed for device index {self.config.device_index}."
            )

        face_count, face_ratio = self.face_analyzer.analyze(frame)

        motion_ratio = 0.0
        if self._previous_frame is not None:
            motion_ratio = self.motion_analyzer.analyze(self._previous_frame, frame)

        self._previous_frame = frame
        self._last_frame = frame

        self._last_observation = OpenCVObservation(
            motion_ratio=motion_ratio,
            face_count=face_count,
            face_ratio=face_ratio,
            timestamp=time.monotonic(),
        )

        if not emit or not self._can_emit():
            return None

        event = self._build_event(
            motion_ratio=motion_ratio,
            face_count=face_count,
            face_ratio=face_ratio,
        )
        if event is None:
            return None

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
        }

    def _can_emit(self) -> bool:
        now = time.monotonic()
        return (now - self._last_emit_at) >= self.config.min_emit_interval_sec

    def _build_event(
        self,
        *,
        motion_ratio: float,
        face_count: int,
        face_ratio: float,
    ) -> PerceptionEvent | None:
        if face_count > 0 and face_ratio >= self.config.min_face_ratio:
            amplitude = min(
                self.config.max_amplitude,
                self.config.face_amplitude_base
                + (face_count * self.config.face_amplitude_per_face)
                + (face_ratio * self.config.face_area_amplitude_scale),
            )
            return {
                "type": self.config.face_event_type,
                "description": self.config.face_description_template.format(
                    count=face_count
                ),
                "origin": self.config.origin,
                "amplitude": amplitude,
                "face_count": face_count,
                "face_ratio": face_ratio,
                "motion_ratio": motion_ratio,
            }

        if motion_ratio < self.config.min_motion_ratio:
            return None

        amplitude = min(
            self.config.max_amplitude, motion_ratio * self.config.amplitude_scale
        )
        return {
            "type": self.config.event_type,
            "description": self.config.description_template.format(ratio=motion_ratio),
            "origin": self.config.origin,
            "amplitude": amplitude,
            "motion_ratio": motion_ratio,
            "face_count": face_count,
            "face_ratio": face_ratio,
        }

    async def _worker(self) -> None:
        while self._running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                self._running = False
                self.frame_source.release()
                break
            await asyncio.sleep(self.config.poll_interval_sec)
