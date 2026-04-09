import asyncio
from dataclasses import replace
from logging import Logger
import sys
from typing import Annotated, Any

from ascender.common import Injectable
from ascender.core import Inject
from ascender.core.applications.application import Application

from hyprchan.core.hypraios.contracts import PerceptionEvent, PerceptionSource
from hyprchan.core.hypraios.kernel.kernel import HyprAIOSKernel
from hyprchan.core.hypraios.perception.multimodal_snapshot_source import (
    MultimodalSnapshotConfig,
    MultimodalSnapshotPerceptionSource,
)
from hyprchan.core.hypraios.perception.opencv_module import (
    OpenCVFrameSourceError,
    OpenCVPerceptionConfig,
    OpenCVPerceptionModule,
    OpenCVUnavailableError,
)
from hyprchan.settings import (
    WEBCAM_DEVICE_INDEX,
    WEBCAM_AUTO_INSTALL_OPENCV,
    WEBCAM_AUTO_FIND_DEVICE,
    WEBCAM_MIN_EMIT_INTERVAL_SEC,
    WEBCAM_MIN_FACE_RATIO,
    WEBCAM_MAX_DEVICE_INDEX,
    WEBCAM_MIN_MOTION_RATIO,
    WEBCAM_POLL_INTERVAL_SEC,
    WEBCAM_VISION_ENABLED,
    MULTIMODAL_SNAPSHOT_ENABLED,
    MULTIMODAL_SNAPSHOT_INTERVAL_SEC,
)
from hyprchan.shared.lifecycle import ServiceLifecycle


@Injectable(provided_in="root")
class VisionService(ServiceLifecycle):
    def __init__(
        self,
        application: Application,
        kernel: HyprAIOSKernel,
        logger: Annotated[Logger, Inject("ASC_LOGGER")],
    ) -> None:
        super().__init__(application)
        self.kernel = kernel
        self.logger = logger
        self._module: PerceptionSource | None = None
        self._opencv_module: OpenCVPerceptionModule | None = None
        self._snapshot_source: PerceptionSource | None = None
        self._startup_error: str | None = None
        self._opencv_install_attempted = False
        self._active_device_index: int | None = None

    async def on_startup(self) -> None:
        self._module = None
        self._opencv_module = None
        self._snapshot_source = None
        self._active_device_index = None
        self._startup_error = None
        self.logger.debug("VisionService startup begin")

        if not WEBCAM_VISION_ENABLED:
            self.logger.info("Webcam perception disabled by configuration")
            return

        config = OpenCVPerceptionConfig(
            device_index=WEBCAM_DEVICE_INDEX,
            poll_interval_sec=WEBCAM_POLL_INTERVAL_SEC,
            min_motion_ratio=WEBCAM_MIN_MOTION_RATIO,
            min_face_ratio=WEBCAM_MIN_FACE_RATIO,
            min_emit_interval_sec=WEBCAM_MIN_EMIT_INTERVAL_SEC,
        )
        self.logger.debug(
            "Vision config device=%s poll=%s min_motion=%s min_face=%s",
            config.device_index,
            config.poll_interval_sec,
            config.min_motion_ratio,
            config.min_face_ratio,
        )

        active_config: OpenCVPerceptionConfig | None = None
        try:
            active_config = await self._start_with_device_autofind(config)
        except OpenCVUnavailableError as exc:
            if await self._attempt_opencv_autoinstall(exc):
                try:
                    active_config = await self._start_with_device_autofind(config)
                except (OpenCVUnavailableError, OpenCVFrameSourceError) as retry_exc:
                    self._startup_error = str(retry_exc)
                    self._module = None
                    self.logger.warning("Webcam perception unavailable: %s", retry_exc)
            else:
                self._startup_error = str(exc)
                self._module = None
                self.logger.warning("Webcam perception unavailable: %s", exc)
        except OpenCVFrameSourceError as exc:
            self._startup_error = str(exc)
            self._module = None
            self.logger.warning("Webcam perception unavailable: %s", exc)

        if active_config is not None:
            self._active_device_index = active_config.device_index
            self.logger.info(
                "Webcam perception active on camera index %s",
                active_config.device_index,
            )

        if MULTIMODAL_SNAPSHOT_ENABLED:
            snapshot_config = MultimodalSnapshotConfig(
                interval_sec=MULTIMODAL_SNAPSHOT_INTERVAL_SEC
            )
            self.logger.debug(
                "Starting multimodal snapshot source interval=%s",
                snapshot_config.interval_sec,
            )
            self._snapshot_source = MultimodalSnapshotPerceptionSource(
                self._record_event,
                config=snapshot_config,
                webcam_frame_supplier=(
                    self._opencv_module.get_last_frame
                    if self._opencv_module is not None
                    else None
                ),
            )
            await self._snapshot_source.start()
            if self._opencv_module is None:
                self.logger.warning(
                    "Multimodal snapshots running without webcam frames (screen only)."
                )

    async def _start_with_device_autofind(
        self, base_config: OpenCVPerceptionConfig
    ) -> OpenCVPerceptionConfig:
        candidate_indices = [base_config.device_index]
        if WEBCAM_AUTO_FIND_DEVICE:
            candidate_indices = self._build_candidate_indices(
                preferred=base_config.device_index,
                max_index=WEBCAM_MAX_DEVICE_INDEX,
            )
        self.logger.debug("Vision candidate device indices=%s", candidate_indices)

        last_error: OpenCVFrameSourceError | None = None
        for index in candidate_indices:
            config = replace(base_config, device_index=index)
            try:
                await self._start_module(config)
                return config
            except OpenCVFrameSourceError as exc:
                last_error = exc
                self.logger.warning(
                    "Webcam device index %s unavailable: %s",
                    index,
                    exc,
                )

        if last_error is not None:
            raise last_error

        raise OpenCVFrameSourceError("No webcam device candidates to probe.")

    @staticmethod
    def _build_candidate_indices(preferred: int, max_index: int) -> list[int]:
        normalized_preferred = max(0, int(preferred))
        normalized_max = max(normalized_preferred, max(0, int(max_index)))

        candidates: list[int] = [normalized_preferred]
        for idx in range(normalized_max + 1):
            if idx not in candidates:
                candidates.append(idx)
        return candidates

    async def _start_module(self, config: OpenCVPerceptionConfig) -> None:
        self.logger.debug(
            "Starting OpenCV module on device index %s", config.device_index
        )
        module = OpenCVPerceptionModule(self._record_event, config=config)
        try:
            await module.start()
        except Exception:
            await module.stop()
            raise

        self._module = module
        self._opencv_module = module

    async def _attempt_opencv_autoinstall(self, error: Exception) -> bool:
        if not WEBCAM_AUTO_INSTALL_OPENCV:
            return False
        if self._opencv_install_attempted:
            return False

        self._opencv_install_attempted = True
        self.logger.warning(
            "OpenCV unavailable (%s). Attempting auto-install via pip...", error
        )

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                "opencv-python-headless",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=240)
        except Exception as install_exc:
            self.logger.warning("OpenCV auto-install failed: %s", install_exc)
            return False

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            self.logger.warning(
                "OpenCV auto-install returned non-zero exit code %s: %s",
                process.returncode,
                stderr_text or "unknown error",
            )
            return False

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        if stdout_text:
            self.logger.info("OpenCV auto-install output: %s", stdout_text)

        self.logger.info("OpenCV auto-install completed successfully.")
        return True

    async def on_shutdown(self) -> None:
        self.logger.debug("VisionService shutdown begin")
        if self._snapshot_source is not None:
            await self._snapshot_source.stop()
        if self._module is not None:
            await self._module.stop()

    async def _record_event(self, event: PerceptionEvent) -> None:
        self.logger.debug(
            "Vision event received type=%s origin=%s",
            event.get("type", "vision_motion"),
            event.get("origin", "opencv_perception"),
        )
        amplitude_raw = event.get("amplitude", 0.0)
        try:
            amplitude = max(0.0, float(amplitude_raw))
        except (TypeError, ValueError):
            amplitude = 0.0

        metadata = {
            key: value
            for key, value in event.items()
            if key not in {"type", "description", "origin", "amplitude"}
        }

        await self.kernel.record_perception(
            event_type=str(event.get("type", "vision_motion")),
            description=str(event.get("description", "camera perception event")),
            origin=str(event.get("origin", "opencv_perception")),
            amplitude=amplitude,
            metadata=metadata,
        )

    def status(self) -> dict[str, Any]:
        self.logger.debug("VisionService status requested")
        if not WEBCAM_VISION_ENABLED:
            return {
                "enabled": False,
                "running": False,
                "message": "WEBCAM_VISION_ENABLED is false",
            }

        snapshot_status: dict[str, Any] | None = None
        if self._snapshot_source is not None:
            snapshot_status = self._snapshot_source.status()

        if self._module is None:
            return {
                "enabled": True,
                "running": False,
                "device_index": self._active_device_index,
                "error": self._startup_error,
                "snapshot": snapshot_status,
            }

        return {
            "enabled": True,
            "device_index": self._active_device_index,
            "snapshot": snapshot_status,
            **self._module.status(),
        }

    async def scan_once(self) -> dict[str, Any]:
        self.logger.debug("VisionService manual scan requested")
        if self._module is None:
            return {
                "status": "unavailable",
                "error": self._startup_error,
            }

        event = await self._module.scan_once()
        return {
            "status": "ok",
            "event": event,
            "observation": self._module.last_observation,
        }
