#!/usr/bin/env python3
"""Observe PipeWire names and state changes. This worker never captures audio."""
from __future__ import annotations
import json
import signal
import subprocess
import sys
import threading
import time


class JsonArrays:
    """Frame concatenated JSON arrays in linear time, including split strings."""
    def __init__(self):
        self.parts = []
        self.depth = 0
        self.quoted = False
        self.escaped = False
        self.size = 0

    def feed(self, text):
        start = 0
        for index, char in enumerate(text):
            if self.quoted:
                if self.escaped:
                    self.escaped = False
                elif char == "\\":
                    self.escaped = True
                elif char == '"':
                    self.quoted = False
            elif char == '"':
                self.quoted = True
            elif char in "[{":
                self.depth += 1
            elif char in "]}":
                self.depth -= 1
                if self.depth == 0:
                    self.parts.append(text[start:index + 1])
                    yield json.loads("".join(self.parts))
                    self.parts = []
                    self.size = 0
                    start = index + 1
        remainder = text[start:]
        self.parts.append(remainder)
        self.size += len(remainder)
        if self.size > 8_000_000:
            raise RuntimeError("PipeWire state exceeded the monitor buffer")


class AudioNodes:
    def __init__(self):
        self.nodes = {}
        self.initial = True

    def update(self, changes):
        events = []
        for item in changes:
            node_id = item.get("id")
            if item.get("info", {}) is None:
                self.nodes.pop(node_id, None)
                continue
            old = self.nodes.get(node_id, {})
            if item.get("type", old.get("type")) != "PipeWire:Interface:Node":
                continue
            info = item.get("info", {})
            props = {**old.get("props", {}), **info.get("props", {})}
            media_class = props.get("media.class", "")
            application = str(props.get("application.name", ""))[:100]
            media_name = str(props.get("media.name", ""))
            if media_name in {"-", "Playback", "Audio Stream"}:
                media_name = ""
            name = str(props.get("node.description") or
                       (f"{application} · {media_name}" if application and media_name else application or media_name) or
                       props.get("node.name") or "Audio channel")[:200]
            node = {"id": node_id, "serial": str(props.get("object.serial", node_id)),
                    "type": "PipeWire:Interface:Node", "props": props,
                    "name": name, "application": application,
                    "mediaClass": media_class, "state": info.get("state", old.get("state", "unknown"))}
            self.nodes[node_id] = node
            own = "hyprchan" in " ".join(str(props.get(k, "")) for k in ("node.name", "application.name", "media.name")).lower()
            audio = "Audio" in media_class and not own
            if audio and not self.initial and (not old or not old.get("mediaClass")):
                events.append({"event": "new_channel", **self.public(node)})
            elif (audio and not self.initial and media_class == "Stream/Output/Audio" and
                  node["state"] == "running" and old.get("state") != "running"):
                events.append({"event": "playback_started", **self.public(node)})
        # pw-dump emits core/client preambles before the initial node inventory.
        if not changes or any(item.get("type") == "PipeWire:Interface:Node" for item in changes):
            self.initial = False
        return events

    @staticmethod
    def public(node):
        return {key: node[key] for key in ("id", "serial", "name", "application", "mediaClass", "state")}

    def playback(self):
        return [self.public(node) for node in self.nodes.values()
                if node["mediaClass"] == "Stream/Output/Audio" and
                "hyprchan" not in (node["name"] + node["application"]).lower()]


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def main():
    child = subprocess.Popen(["pw-dump", "-m", "-N"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
    def stop(*_):
        if child.poll() is None:
            child.terminate()
    def commands():
        for line in sys.stdin:
            try:
                if json.loads(line).get("type") == "quit":
                    break
            except ValueError:
                pass
        stop()
    threading.Thread(target=commands, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    tracker = AudioNodes()
    previous_playback = None
    decoder = JsonArrays()
    try:
        for line in child.stdout:
            for changes in decoder.feed(line):
                first = tracker.initial
                events = tracker.update(changes)
                playback = tracker.playback()
                if playback != previous_playback:
                    emit({"type": "audio_state", "playback": playback})
                    previous_playback = playback
                if first and not tracker.initial:
                    emit({"type": "ready"})
                for event in events:
                    emit({"type": "audio_event", "observedAt": time.time(), **event})
    finally:
        stop()
        child.wait(timeout=3)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
