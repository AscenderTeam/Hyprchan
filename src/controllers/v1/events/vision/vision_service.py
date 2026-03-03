from logging import Logger
from typing import Annotated, Any

from ascender.common import Injectable
from ascender.core import Inject
from ascender.core.applications.application import Application

from core.hypraios.kernel.kernel import HyprAIOSKernel
from core.hypraios.perception.opencv_module import (
    OpenCVFrameSourceError,
    OpenCVPerceptionConfig,
    OpenCVPerceptionModule,
    OpenCVUnavailableError,
)
from settings import (
    WEBCAM_DEVICE_INDEX,
    WEBCAM_MIN_EMIT_INTERVAL_SEC,
    WEBCAM_MIN_FACE_RATIO,
    WEBCAM_MIN_MOTION_RATIO,
    WEBCAM_POLL_INTERVAL_SEC,
    WEBCAM_VISION_ENABLED,
)
from shared.lifecycle import ServiceLifecycle


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
        self._module: OpenCVPerceptionModule | None = None
        self._startup_error: str | None = None

    async def on_startup(self) -> None:
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

        try:
            self._module = OpenCVPerceptionModule(self._record_event, config=config)
            await self._module.start()
        except (OpenCVUnavailableError, OpenCVFrameSourceError) as exc:
            self._startup_error = str(exc)
            self._module = None
            self.logger.warning("Webcam perception unavailable: %s", exc)
            return

        self.logger.info(
            "Webcam perception active on camera index %s", config.device_index
        )

    async def on_shutdown(self) -> None:
        if self._module is not None:
            await self._module.stop()

    async def _record_event(self, event: dict[str, Any]) -> None:
        amplitude_raw = event.get("amplitude", 0.0)
        try:
            amplitude = max(0.0, float(amplitude_raw))
        except (TypeError, ValueError):
            amplitude = 0.0

        await self.kernel.record_perception(
            event_type=str(event.get("type", "vision_motion")),
            description=str(event.get("description", "camera perception event")),
            origin=str(event.get("origin", "opencv_perception")),
            amplitude=amplitude,
        )

    def status(self) -> dict[str, Any]:
        if not WEBCAM_VISION_ENABLED:
            return {
                "enabled": False,
                "running": False,
                "message": "WEBCAM_VISION_ENABLED is false",
            }

        if self._module is None:
            return {
                "enabled": True,
                "running": False,
                "error": self._startup_error,
            }

        return {
            "enabled": True,
            "running": self._module.is_running,
            "last_error": self._module.last_error,
            "last_observation": self._module.last_observation,
        }

    async def scan_once(self) -> dict[str, Any]:
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
