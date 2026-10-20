#!/usr/bin/env python3
"""Real PipeWire -> local STT test, routed to a temporary silent sink.

Supply the public faster-whisper JFK fixture. No microphone audio is used.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    fixture, output = map(Path, sys.argv[1:3])
    interpreter = os.getenv("HYPRCHAN_SPEECH_PYTHON", str(Path.home() / ".local/share/hyprchan-codex/venv/bin/python"))
    speech = monitor = player = decoder = None
    module = None
    events = queue.Queue()
    observed = []
    rows = []
    passed = False
    cancellation = None
    defaults = {kind: subprocess.check_output(["pactl", f"get-default-{kind}"], text=True).strip() for kind in ["sink", "source"]}
    def read(child, source):
        for line in child.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if source == "pipewire":
                if event.get("type") == "audio_event" and event.get("application") == "Codex audio probe":
                    observed.append(event)
            else:
                events.put(event)
    def wait_for(kind, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = events.get(timeout=max(.01, deadline-time.monotonic()))
            if event["type"] in {"error", "listen_error"}:
                raise RuntimeError(event.get("message", "Speech worker failed"))
            if event["type"] == kind:
                return event
        raise TimeoutError(kind)
    try:
        monitor = subprocess.Popen([sys.executable, "scripts/desktop_pipewire_worker.py"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        threading.Thread(target=read, args=(monitor, "pipewire"), daemon=True).start()
        speech = subprocess.Popen([interpreter, "scripts/desktop_speech_worker.py"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        threading.Thread(target=read, args=(speech, "speech"), daemon=True).start()
        wait_for("ready", 60)
        module = subprocess.check_output(["pactl", "load-module", "module-null-sink",
            "sink_name=codex_listen_in_test", "sink_properties=device.description=Codex_audio_probe_sink",
            "channels=1", "rate=16000"], text=True).strip()
        decoder = subprocess.Popen(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(fixture),
            "-t", "25", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        player = subprocess.Popen(["pw-play", "--raw", "--rate", "16000", "--channels", "1", "--format", "f32",
            "--target", "codex_listen_in_test", "-P", json.dumps({"application.name": "Codex audio probe",
                "node.name": "codex-audio-probe-player"}), "-"], stdin=decoder.stdout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        decoder.stdout.close()
        serial = None
        for _ in range(40):
            for node in json.loads(subprocess.check_output(["pw-dump"])):
                props = (node.get("info") or {}).get("props", {})
                if props.get("node.name") == "codex-audio-probe-player":
                    serial = str(props["object.serial"])
            if serial:
                break
            time.sleep(.05)
        assert serial, "Playback stream not found"
        # Deliberately wrong legacy hint: playback must detect English from the
        # audio, even if an older caller guessed Russian before hearing it.
        command = {"type": "listen_in", "jobId": "fixture", "serial": serial, "name": "Codex audio probe",
                   "seconds": 12, "language": "ru"}
        started = time.monotonic()
        speech.stdin.write(json.dumps(command) + "\n"); speech.stdin.flush()
        while time.monotonic() - started < 20:
            event = events.get(timeout=20)
            if event["type"] in {"listen_error", "error"}:
                raise RuntimeError(event.get("message", "Listening failed"))
            if event["type"].startswith("listen_"):
                rows.append({**event, "receivedMs": round((time.monotonic()-started)*1000, 1)})
            if event["type"] == "listen_done":
                break
        chunks = [row for row in rows if row["type"] == "listen_chunk"]
        assert [row["index"] for row in chunks] == [1, 2, 3, 4, 5], rows
        assert sum(bool(row["text"]) for row in chunks) >= 3, "Public speech was not recognized"
        assert all(row["languageMode"] == "auto" for row in chunks)
        assert all(row["language"] == "en" for row in chunks if row["text"]), "Wrong legacy hint overrode English audio"
        assert chunks[0]["receivedMs"] < 5000 and chunks[-1]["receivedMs"] < 15000
        assert observed, "PipeWire did not report the new playback channel"
        # Cancel a second, longer capture after its first real transcript.
        speech.stdin.write(json.dumps({**command, "jobId": "cancel-test", "seconds": 20}) + "\n"); speech.stdin.flush()
        wait_for("listen_chunk", 8)
        stopped = time.monotonic()
        speech.stdin.write('{"type":"stop_listening"}\n'); speech.stdin.flush()
        cancelled = wait_for("listen_done", 2)
        assert cancelled.get("cancelled") and cancelled["jobId"] == "cancel-test"
        cancellation = {"ackMs": round((time.monotonic() - stopped) * 1000, 1)}
        time.sleep(.3)
        child_names = subprocess.run(["ps", "-o", "comm=", "--ppid", str(speech.pid)], capture_output=True, text=True).stdout
        assert "pw-record" not in child_names, "Capture process survived cancellation"
        while not events.empty():
            assert events.get_nowait()["type"] != "listen_chunk", "Cancelled transcript escaped"
        cancellation["captureStopped"] = True
        passed = True
        print(json.dumps({"passed": passed, "chunks": chunks, "audioEvents": observed, "cancellation": cancellation}, indent=2))
    finally:
        for child in [player, decoder]:
            if child and child.poll() is None:
                child.terminate(); child.wait(timeout=3)
        for child in [speech, monitor]:
            if child and child.poll() is None:
                child.stdin.write('{"type":"quit"}\n'); child.stdin.flush()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
        if module:
            subprocess.run(["pactl", "unload-module", module], check=True)
        for kind, name in defaults.items():
            current = subprocess.check_output(["pactl", f"get-default-{kind}"], text=True).strip()
            if current.startswith("codex_listen_in_test"):
                subprocess.run(["pactl", f"set-default-{kind}", name], check=True)
        output.write_text(json.dumps({"publicFixtureOnly": True, "silentTestSink": True, "passed": passed,
            "durationSec": 12, "rows": rows, "audioEvents": observed, "cancellation": cancellation}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
