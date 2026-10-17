#!/usr/bin/env python3
"""Measure real output at an isolated sink, phrase streaming, and cancellation."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    module = recorder = worker = None
    events = queue.Queue()
    levels = []
    rows = []
    audio_ready = threading.Event()
    passed = False
    defaults = {kind: subprocess.check_output(["pactl", f"get-default-{kind}"], text=True).strip()
                for kind in ["sink", "source"]}
    def send(command):
        worker.stdin.write(json.dumps(command) + "\n"); worker.stdin.flush()
    def wait(kind, identity, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = events.get(timeout=max(.01, deadline-time.monotonic()))
            if event["type"] == "error":
                raise RuntimeError(event)
            if event["type"] == kind and (identity is None or event.get("id") == identity):
                return event
        raise TimeoutError(kind)
    try:
        module = subprocess.check_output(["pactl", "load-module", "module-null-sink",
            "sink_name=hyprchan_tts_test", "channels=1", "rate=22050"], text=True).strip()
        recorder = subprocess.Popen(["pw-record", "--raw", "--format", "s16", "--rate", "22050",
            "--channels", "1", "--latency", "20ms", "--target", "hyprchan_tts_test",
            "-P", json.dumps({"stream.capture.sink": True, "application.name": "Hyprchan TTS test recorder"}), "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        def read_audio():
            while raw := os.read(recorder.stdout.fileno(), 4096):
                samples = np.frombuffer(raw[:len(raw)//2*2], dtype="<i2").astype(np.float32) / 32768
                levels.append((time.monotonic(), float(np.sqrt(np.mean(samples * samples)))))
                audio_ready.set()
        threading.Thread(target=read_audio, daemon=True).start()
        worker = subprocess.Popen([sys.executable, "scripts/desktop_tts_worker.py"], cwd=ROOT,
            env={**os.environ, "HYPRCHAN_TTS_SINK": "hyprchan_tts_test"},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def read_events():
            for line in worker.stdout:
                event = json.loads(line)
                event["observedAt"] = time.monotonic()
                events.put(event)
        threading.Thread(target=read_events, daemon=True).start()
        wait("ready", None, 20)
        assert audio_ready.wait(3), "Silent sink monitor produced no samples"
        for identity, text in [(1, "Hi!"), (2, "Привет, я уже тут!")]:
            start = time.monotonic()
            send({"type": "begin", "id": identity})
            send({"type": "text", "id": identity, "text": text})
            send({"type": "end", "id": identity})
            generated = wait("generated", identity)
            done = wait("done", identity)
            audible = next(t for t, rms in levels if t >= start and rms > .002)
            rows.append({"case": "greeting", "text": text, "firstPcmMs": generated["firstPcmMs"],
                "synthMs": generated["synthMs"], "firstOutputMs": round((audible-start)*1000, 1),
                "firstWriteMs": done["firstWriteMs"], "completedMs": done["elapsedMs"]})
            time.sleep(.15)

        start = time.monotonic()
        send({"type": "begin", "id": 3})
        send({"type": "text", "id": 3, "text": "Hello!"})
        wait("playing", 3)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not any(t >= start and rms > .002 for t, rms in levels):
            time.sleep(.01)
        assert any(t >= start and rms > .002 for t, rms in levels), "First phrase waited for end of reply"
        send({"type": "text", "id": 3, "text": "Tiny victory!"})
        send({"type": "end", "id": 3})
        wait("done", 3)
        rows.append({"case": "phrase_streaming", "playedBeforeEnd": True})
        time.sleep(.2)

        send({"type": "begin", "id": 4})
        send({"type": "text", "id": 4, "text": "This is a long spoken sentence that should stop immediately when the user starts speaking or presses the stop button."})
        wait("playing", 4)
        time.sleep(.15)
        stopped = time.monotonic()
        send({"type": "stop"})
        cancelled = wait("cancelled", 4)
        time.sleep(.4)
        tail = [t for t, rms in levels if t >= stopped and rms > .002]
        tail_ms = max(0, (max(tail)-stopped)*1000) if tail else 0
        children = subprocess.run(["ps", "-o", "comm=", "--ppid", str(worker.pid)], capture_output=True, text=True).stdout
        assert "pw-play" not in children, "Player survived cancellation"
        assert tail_ms < 300, tail_ms
        rows.append({"case": "cancellation", "ackMs": round((cancelled["observedAt"]-stopped)*1000, 1),
                     "outputTailMs": round(tail_ms, 1), "playerExited": True})
        # A cancelled in-flight synthesis must not leak into the next utterance.
        send({"type": "begin", "id": 5})
        send({"type": "text", "id": 5, "text": "This old sentence must never be spoken after cancellation."})
        send({"type": "stop"})
        send({"type": "begin", "id": 6})
        send({"type": "text", "id": 6, "text": "Привет!"})
        send({"type": "end", "id": 6})
        old_played = False
        while True:
            event = events.get(timeout=10)
            if event["type"] == "error":
                raise RuntimeError(event)
            old_played |= event["type"] == "playing" and event.get("id") == 5
            if event["type"] == "done" and event.get("id") == 6:
                break
        assert not old_played
        rows.append({"case": "cancel_before_audio", "oldPlayed": old_played, "nextCompleted": True})
        passed = True
        print(json.dumps({"passed": passed, "rows": rows}, ensure_ascii=False, indent=2))
    finally:
        if worker and worker.poll() is None:
            send({"type": "quit"})
            try: worker.wait(timeout=5)
            except subprocess.TimeoutExpired: worker.kill(); worker.wait()
        if recorder and recorder.poll() is None:
            recorder.terminate(); recorder.wait(timeout=3)
        if module:
            subprocess.run(["pactl", "unload-module", module], check=True)
        for kind, original in defaults.items():
            current = subprocess.check_output(["pactl", f"get-default-{kind}"], text=True).strip()
            if current.startswith("hyprchan_tts_test"):
                subprocess.run(["pactl", f"set-default-{kind}", original], check=True)
        Path(sys.argv[1]).write_text(json.dumps({"syntheticTextOnly": True, "silentTestSink": True,
            "passed": passed, "rows": rows}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
