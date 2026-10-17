"""Bounded per-stream capture for the speech worker; never defaults to a microphone."""
from __future__ import annotations
import json
import os
import selectors
import subprocess
import time


def listen_plan(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 1 <= seconds <= 20:
        raise ValueError("listen_in duration must be between 1 and 20 seconds")
    chunks = 5 if seconds > 10 else 1
    return chunks, round(seconds * 16000 / chunks) * 4


def playback_node(serial):
    if not str(serial).isdigit():
        raise ValueError("listen_in requires a known playback stream serial")
    for node in json.loads(subprocess.check_output(["pw-dump"], timeout=3)):
        props = node.get("info", {}).get("props", {})
        if (str(props.get("object.serial")) == str(serial) and
                props.get("media.class") == "Stream/Output/Audio"):
            return node
    raise ValueError("That playback stream is no longer available")


def capture_stream(serial, seconds, cancelled, on_process):
    """Yield up to five PCM chunks, bounded by a wall-clock capture deadline."""
    count, size = listen_plan(seconds)
    playback_node(serial)
    props = {"application.name": "Hyprchan listen_in", "node.name": "hyprchan-listen-in",
             "stream.capture.sink": True, "node.dont-reconnect": True, "node.passive": True}
    child = subprocess.Popen(["pw-record", "--raw", "--rate", "16000", "--channels", "1",
                              "--format", "f32", "--latency", "50ms", "--target", str(serial),
                              "--properties", json.dumps(props), "-"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    on_process(child)
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    started = time.monotonic()
    buffer = bytearray()
    index = 0
    try:
        while not cancelled() and index < count:
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            if not selector.select(min(.1, remaining)):
                continue
            data = os.read(child.stdout.fileno(), 65536)
            if not data:
                break
            buffer.extend(data)
            while len(buffer) >= size and index < count:
                index += 1
                yield index, count, bytes(buffer[:size])
                del buffer[:size]
        if buffer and index < count and not cancelled():
            yield index + 1, count, bytes(buffer[:len(buffer) // 4 * 4])
    finally:
        selector.close()
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        on_process(None)
