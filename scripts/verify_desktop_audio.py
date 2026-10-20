#!/usr/bin/env python3
"""Real model tool -> per-stream capture -> five STT observations -> model replies.

Uses only a supplied public audio fixture on a temporary silent sink.
"""
import hashlib
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
    events = queue.Queue()
    children = {}
    rows = []
    module = None
    passed = False
    defaults = {kind: subprocess.check_output(["pactl", f"get-default-{kind}"], text=True).strip()
                for kind in ["sink", "source"]}

    def spawn(name, args, env=None):
        child = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True, bufsize=1)
        children[name] = child
        def read():
            for line in child.stdout:
                events.put((name, json.loads(line)))
            events.put((name, {"type": "error", "message": f"{name} exited"}))
        threading.Thread(target=read, daemon=True).start()
        return child

    def send(name, command):
        children[name].stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
        children[name].stdin.flush()

    try:
        spawn("model", ["node", "scripts/desktop_codex_bridge.mjs"],
              {**os.environ, "HYPRCHAN_MEMORY_PATH": ":memory:"})
        spawn("speech", [os.getenv("HYPRCHAN_SPEECH_PYTHON", str(Path.home() / ".local/share/hyprchan-codex/venv/bin/python")),
                         "scripts/desktop_speech_worker.py"])
        ready = set()
        while len(ready) < 2:
            name, event = events.get(timeout=60)
            if event["type"] == "error":
                raise RuntimeError(event)
            if event["type"] == "ready":
                ready.add(name)

        module = subprocess.check_output(["pactl", "load-module", "module-null-sink",
            "sink_name=codex_model_listen_test", "channels=1", "rate=16000"], text=True).strip()
        children["decoder"] = subprocess.Popen(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(fixture),
            "-t", "45", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        children["player"] = subprocess.Popen(["pw-play", "--raw", "--rate", "16000", "--channels", "1", "--format", "f32",
            "--target", "codex_model_listen_test", "-P", json.dumps({"application.name": "Codex model audio test",
            "node.name": "codex-model-audio-test"}), "-"], stdin=children["decoder"].stdout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        children["decoder"].stdout.close()
        serial = None
        for _ in range(40):
            for node in json.loads(subprocess.check_output(["pw-dump"])):
                props = (node.get("info") or {}).get("props", {})
                if props.get("node.name") == "codex-model-audio-test":
                    serial = str(props["object.serial"])
            if serial:
                break
            time.sleep(.05)
        assert serial
        send("model", {"type": "audio_state", "playback": [{"serial": serial, "name": "Public English speech demo",
              "application": "Codex model audio test", "mediaClass": "Stream/Output/Audio", "state": "running"}]})
        send("model", {"type": "chat", "id": 1, "text": "Use listen_in to listen to the public English speech demo for exactly 12 seconds. React if something is interesting as the chunks arrive.", "vision": {"enabled": False}})
        started = time.monotonic()
        pending = []
        busy = True
        listening_done = False
        request_count = 0
        identity = 1
        reaction_count = 0
        while time.monotonic() - started < 50:
            name, event = events.get(timeout=25)
            kind = event["type"]
            if kind in {"error", "listen_error"}:
                raise RuntimeError(event)
            if kind == "listen_request":
                request_count += 1
                assert request_count == 1, "Model started listening again from transcript events"
                assert event["seconds"] == 12 and event["serial"] == serial
                send("speech", {**event, "type": "listen_in"})
            elif name == "speech" and kind == "listen_chunk":
                pending.append(event)
            elif name == "speech" and kind == "listen_done":
                listening_done = True
                send("model", {"type": "listen_finished", "jobId": event["jobId"]})
            elif name == "model" and kind == "done":
                assert event["status"] == "completed", event
                busy = False
                if event["id"] > 1:
                    reaction_count += 1
            if kind in {"listen_request", "listen_started", "listen_chunk", "listen_done", "done"}:
                rows.append({"source": name, **event, "receivedMs": round((time.monotonic() - started) * 1000, 1)})
            if not busy and pending:
                identity += 1
                send("model", {"type": "react", "id": identity, "observation": pending.pop(0),
                               "language": "en", "vision": {"enabled": False}})
                busy = True
            if listening_done and reaction_count == 5 and not busy:
                break
        assert request_count == 1 and reaction_count == 5 and listening_done, rows
        assert any(row.get("id", 0) > 1 and row.get("text") for row in rows if row["type"] == "done"), "No reaction to recognized speech"
        passed = True
        print(json.dumps({"passed": passed, "rows": rows}, ensure_ascii=False, indent=2))
    finally:
        for name in ["player", "decoder", "speech", "model"]:
            child = children.get(name)
            if child and child.poll() is None:
                if name in {"speech", "model"}:
                    send(name, {"type": "quit"})
                else:
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()
        if module:
            subprocess.run(["pactl", "unload-module", module], check=True)
        for kind, value in defaults.items():
            current = subprocess.check_output(["pactl", f"get-default-{kind}"], text=True).strip()
            if current.startswith("codex_model_listen_test"):
                subprocess.run(["pactl", f"set-default-{kind}", value], check=True)
        output.write_text(json.dumps({"publicFixtureOnly": True, "silentTestSink": True, "passed": passed,
            "promptSha256": hashlib.sha256((ROOT / "benchmarks/codex-rp/persona.txt").read_bytes()).hexdigest(),
            "rows": rows}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
