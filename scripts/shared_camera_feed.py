#!/usr/bin/env python3
"""Copy one physical capture to independent OBS and Hyprchan loopbacks.

The camera runs only while either output has a reader. Frame bytes stay in
FFmpeg/kernel buffers; this supervisor handles process IDs and progress only.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time


def device_users(devices):
    result = subprocess.run(["fuser", *map(str, devices)], capture_output=True,
                            text=True, timeout=3)
    if result.returncode not in (0, 1):
        raise RuntimeError("Unable to check camera readers")
    return {int(pid) for pid in result.stdout.split() if pid.isdigit()}


def configure_outputs(outputs, width, height):
    for device in outputs:
        result = subprocess.run(["v4l2-ctl", "-d", device, "--get-fmt-video-out"],
                                check=True, capture_output=True, text=True, timeout=3)
        size = re.search(r"Width/Height\s*:\s*(\d+)/(\d+)", result.stdout)
        same = size and tuple(map(int, size.groups())) == (width, height)
        if not same or "'NV12'" not in result.stdout:
            subprocess.run(["v4l2-ctl", "-d", device,
                            f"--set-fmt-video-out=width={width},height={height},pixelformat=NV12"],
                           check=True, capture_output=True, timeout=3)
        # Keep capture discoverable with a stable format while idle. A stopped
        # producer turns black instead of retaining the last private frame.
        subprocess.run(["v4l2-ctl", "-d", device,
                        "--set-ctrl=keep_format=1,sustain_framerate=1,timeout=2000"],
                       check=True, capture_output=True, timeout=3)


def ffmpeg_command(source, outputs, width, height, fps):
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
               "-progress", "pipe:1", "-stats_period", "1",
               "-analyzeduration", "0", "-probesize", "32",
               "-f", "v4l2", "-input_format", "nv12", "-framerate", str(fps),
               "-video_size", f"{width}x{height}", "-i", source, "-an"]
    for output in outputs:
        command.extend(["-map", "0:v", "-c:v", "copy", "-f", "v4l2", output])
    return command


class SharedCamera:
    def __init__(self, source, outputs, width=1920, height=1080, fps=30, idle_seconds=5):
        self.source = source
        self.outputs = outputs
        self.width, self.height, self.fps = width, height, fps
        self.idle_seconds = idle_seconds
        self.process = None
        self.progress_thread = None
        self.last_frame_at = 0.0
        self.last_reader_at = 0.0
        self.retry_at = 0.0
        self.ready = False
        self.stopping = threading.Event()
        self.last_error = None

    def read_progress(self, process):
        previous = -1
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "frame" and value.strip().isdigit():
                frame = int(value)
                if frame > previous:
                    previous = frame
                    self.last_frame_at = time.monotonic()

    def stop_capture(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if self.progress_thread:
            self.progress_thread.join(timeout=2)
            self.progress_thread = None
        process.stdout.close()
        print("Physical camera released", flush=True)

    def tick(self, now):
        if self.process and (self.process.poll() is not None or now-self.last_frame_at > 15):
            print("Camera capture stopped or stalled; retrying after 5 seconds", flush=True)
            self.stop_capture()
            self.retry_at = now+5
        readers = device_users(self.outputs)-{os.getpid()}
        if self.process:
            readers.discard(self.process.pid)
        if readers:
            self.last_reader_at = now
            if self.process is None and now >= self.retry_at:
                # Never interrupt another app that still owns the physical ISP.
                if device_users([self.source]):
                    self.retry_at = now+5
                    return
                self.last_frame_at = now
                self.process = subprocess.Popen(
                    ffmpeg_command(self.source, self.outputs, self.width, self.height, self.fps),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
                self.progress_thread = threading.Thread(target=self.read_progress,
                                                        args=(self.process,), daemon=True)
                self.progress_thread.start()
                print("Shared camera capture started", flush=True)
        elif self.process and now-self.last_reader_at >= self.idle_seconds:
            self.stop_capture()

    def run(self):
        try:
            while not self.stopping.is_set():
                try:
                    if not self.ready:
                        if not all(Path(path).exists() for path in [self.source, *self.outputs]):
                            self.stopping.wait(2)
                            continue
                        configure_outputs(self.outputs, self.width, self.height)
                        self.ready = True
                    self.tick(time.monotonic())
                    self.last_error = None
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    if str(exc) != self.last_error:
                        print(f"Shared camera waiting: {exc}", flush=True)
                        self.last_error = str(exc)
                    self.stopping.wait(4)
                self.stopping.wait(1)
        finally:
            self.stop_capture()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Stable physical camera path")
    parser.add_argument("--outputs", nargs=2, default=["/dev/video2", "/dev/video3"])
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()
    paths = [Path(path).resolve() for path in [args.source, *args.outputs]]
    if len(set(paths)) != 3:
        parser.error("The physical camera and both loopbacks must be different devices")
    if min(args.width, args.height, args.fps) < 1:
        parser.error("Size and frame rate must be positive")
    camera = SharedCamera(args.source, args.outputs, args.width, args.height, args.fps)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: camera.stopping.set())
    camera.run()


if __name__ == "__main__":
    main()
