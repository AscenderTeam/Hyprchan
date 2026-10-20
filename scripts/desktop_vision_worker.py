#!/usr/bin/env python3
"""Automatic visual context using Hyprchan's existing perception providers.

Private JSON-lines transport. Images are delivered to the parent in memory;
temporary provider files live in a private runtime directory and are removed.
No model calls or transcript/image logging happen in this worker.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hyprchan.core.hypraios.perception.multimodal_snapshot_source import (
    MultimodalSnapshotConfig, MultimodalSnapshotPerceptionSource,
)
from hyprchan.core.hypraios.perception.opencv_module import (
    OpenCVPerceptionConfig, OpenCVPerceptionModule,
)


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def camera_device(sysfs=Path("/sys/class/video4linux")):
    override = os.getenv("HYPRCHAN_CAMERA_INDEX", os.getenv("WEBCAM_DEVICE_INDEX"))
    cameras = sorted(sysfs.glob("video*"))
    if override is not None:
        index = int(override)
        name_file = sysfs / f"video{index}" / "name"
        return index, name_file.read_text().strip() if name_file.exists() else f"Camera {index}"
    for camera in cameras:
        name = (camera / "name").read_text().strip()
        if name == "Hyprchan Camera Context":
            return int(camera.name.removeprefix("video")), name
    for camera in cameras:
        name = (camera / "name").read_text().strip()
        # Never silently send an OBS scene in place of the physical camera.
        if "virtual" not in name.lower() and "obs" not in name.lower():
            return int(camera.name.removeprefix("video")), name
    return None, None


def encode_snapshot(event):
    images = []
    for image in event["images"]:
        path = Path(image["path"])
        try:
            url = "data:" + image["mime"] + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")
            images.append({key: image[key] for key in ("kind", "width", "height") } | {"url": url})
        finally:
            path.unlink(missing_ok=True)
    return {"captured_at": event["captured_at"], "images": images}


class VisionWorker:
    def __init__(self, directory):
        self.directory = directory
        self.camera = None
        self.camera_name = None
        self.camera_error = None
        self.camera_ready_at = 0.0
        self.camera_retry_at = 0.0
        self.enabled = False
        self.generation = 0
        self.task = None
        self.refresh = asyncio.Event()
        self.requests = []
        self.capture_started = 0.0
        self.refresh_requested = False
        self.capture_reason = "periodic"
        self.source = MultimodalSnapshotPerceptionSource(
            self.snapshot,
            config=MultimodalSnapshotConfig(
                interval_sec=float(os.getenv("MULTIMODAL_SNAPSHOT_INTERVAL_SEC", "60")),
                output_dir=directory,
                webcam_warmup_sec=0,
            ),
            webcam_frame_supplier=self.webcam_frame,
        )

    def webcam_frame(self):
        if self.camera and not self.camera.last_error and time.monotonic() >= self.camera_ready_at:
            return self.camera.get_last_frame()
        return None

    async def ensure_camera(self):
        if self.camera and self.camera.last_error:
            await self.camera.stop()
            self.camera = None
        if self.camera or time.monotonic() < self.camera_retry_at:
            return
        self.camera_retry_at = time.monotonic() + 5
        camera = None
        try:
            index, self.camera_name = camera_device()
            if index is None:
                raise RuntimeError("No physical camera found")
            # Probing an occupied physical Asahi camera can disrupt its owner.
            # The shared feed has a producer by design, so only guard hardware.
            if self.camera_name != "Hyprchan Camera Context":
                owners = await asyncio.to_thread(subprocess.run, ["fuser", f"/dev/video{index}"],
                                                 capture_output=True, timeout=2)
                if owners.stdout.strip():
                    raise RuntimeError("Camera is already in use; select the shared camera feed")
            camera = OpenCVPerceptionModule(lambda event: None,
                                           config=OpenCVPerceptionConfig(device_index=index))
            await camera.start()
            self.camera = camera
            self.camera_ready_at = time.monotonic() + 3
            self.camera_error = None
        except Exception as exc:
            if camera:
                await camera.stop()
            self.camera_error = str(exc)

    def snapshot(self, event):
        snapshot = encode_snapshot(event)
        emit({"type": "snapshot", "generation": self.generation,
              "snapshot": snapshot, "requestIds": self.requests,
              "camera": self.camera_name, "cameraError": self.camera_error,
              "reason": self.capture_reason,
              "captureMs": round((time.monotonic() - self.capture_started) * 1000, 1)})
        self.requests = []

    async def capture_loop(self):
        while self.enabled:
            self.refresh.clear()
            self.capture_reason = "requested" if self.refresh_requested else "periodic"
            self.refresh_requested = False
            try:
                await self.ensure_camera()
                self.capture_started = time.monotonic()
                event = await self.source.scan_once()
                if not event:
                    emit({"type": "notice", "generation": self.generation,
                          "message": self.camera_error or "No camera or screen image is available"})
            except Exception as exc:
                emit({"type": "notice", "generation": self.generation, "message": str(exc)})
            # Complete the first camera snapshot after warmup, not one interval later.
            warmup = self.camera_ready_at - time.monotonic()
            delay = warmup if warmup > 0 else (5 if not self.camera else self.source.config.interval_sec)
            delay = max(0.05, delay)
            try:
                await asyncio.wait_for(self.refresh.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def set_enabled(self, enabled, generation):
        self.enabled = False
        if self.task:
            # Let the current capture finish before removing its temporary files.
            self.refresh.set()
            await self.task
            self.task = None
        if self.camera:
            await self.camera.stop()
            self.camera = None
        self.requests = []
        self.refresh_requested = False
        self.generation = generation
        self.enabled = enabled
        if enabled:
            self.camera_retry_at = 0
            self.task = asyncio.create_task(self.capture_loop())
        emit({"type": "vision", "active": enabled, "generation": generation})


async def main():
    loop = asyncio.get_running_loop()
    commands = asyncio.Queue()
    def read_commands():
        for line in sys.stdin:
            try:
                command = json.loads(line)
            except ValueError:
                continue
            loop.call_soon_threadsafe(commands.put_nowait, command)
        loop.call_soon_threadsafe(commands.put_nowait, {"type": "quit"})
    threading.Thread(target=read_commands, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, commands.put_nowait, {"type": "quit"})
    runtime = Path(os.getenv("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    with tempfile.TemporaryDirectory(prefix="hyprchan-vision-", dir=runtime) as directory:
        worker = VisionWorker(Path(directory))
        emit({"type": "ready", "intervalSec": worker.source.config.interval_sec})
        try:
            while True:
                command = await commands.get()
                kind = command.get("type")
                if kind == "quit":
                    break
                if kind == "enable":
                    await worker.set_enabled(bool(command["active"]), command["generation"])
                elif kind == "refresh" and worker.enabled:
                    if command.get("id") is not None:
                        worker.requests.append(command["id"])
                    worker.refresh_requested = command.get("reason") != "periodic"
                    worker.refresh.set()
        finally:
            await worker.set_enabled(False, worker.generation)


if __name__ == "__main__":
    asyncio.run(main())
