#!/usr/bin/env python3
"""Exercise real PipeWire disconnect/fallback behavior with zero-valued PCM only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from desktop_speech_output import playback_properties, playback_target


def graph():
    return json.loads(subprocess.check_output(["pw-dump"], text=True, timeout=3))


def destinations(pid):
    objects = graph()
    clients = {node["id"] for node in objects if str(node.get("info", {}).get("props", {}).get(
        "application.process.id")) == str(pid) and node["type"] == "PipeWire:Interface:Client"}
    sources = {node["id"] for node in objects if node.get("info", {}).get("props", {}).get(
        "client.id") in clients and node["type"] == "PipeWire:Interface:Node"}
    sinks = {node["id"] for node in objects if node.get("info", {}).get("props", {}).get(
        "media.class") == "Audio/Sink"}
    return {node["info"]["input-node-id"] for node in objects
            if node["type"] == "PipeWire:Interface:Link" and node.get("info", {}).get("output-node-id") in sources
            and node["info"].get("input-node-id") in sinks}


def start_silent_player(target):
    process = subprocess.Popen(["pw-play", "--raw", "--format", "s16", "--rate", "48000",
        "--channels", "1", "--target", target, "--volume", "0",
        "-P", json.dumps(playback_properties()), "-"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def zeros():
        try:
            while process.poll() is None:
                process.stdin.write(bytes(4096))
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
    thread = threading.Thread(target=zeros, daemon=True)
    thread.start()
    return process, thread


def stop_player(process, thread):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    thread.join(timeout=2)
    try:
        process.stdin.close()
    except BrokenPipeError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    name = f"hyprchan_route_check_{os.getpid()}"
    default = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
    module = player = thread = None
    rows = []
    try:
        module = subprocess.check_output(["pactl", "load-module", "module-null-sink",
                                          f"sink_name={name}", "channels=1", "rate=48000"], text=True).strip()
        _, serial, _ = playback_target(name)
        sink_id = next(node["id"] for node in graph() if str(node.get("info", {}).get("props", {}).get(
            "object.serial")) == serial and node["type"] == "PipeWire:Interface:Node")
        player, thread = start_silent_player(serial)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline and not destinations(player.pid):
            time.sleep(.05)
        linked = destinations(player.pid)
        assert linked, "Test stream did not link to its silent sink"
        assert linked == {sink_id}, "Test stream linked outside its silent sink"
        subprocess.run(["pactl", "unload-module", module], check=True)
        module = None
        deadline = time.monotonic()+3
        while time.monotonic() < deadline and player.poll() is None:
            assert not destinations(player.pid), "Disconnected stream moved to another output"
            time.sleep(.05)
        assert player.poll() is not None, "Disconnected player did not terminate"
        rows.append({"case": "disconnect", "initialTargetWasNullSink": True,
                     "movedToAnotherSink": False, "playerExited": True})
        stop_player(player, thread)
        player = None
        # Reuse the now-missing serial: the session manager must reject it,
        # including the race between Python's target lookup and pw-play startup.
        player, thread = start_silent_player(serial)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline and player.poll() is None:
            assert not destinations(player.pid), "Missing target fell back to another output"
            time.sleep(.05)
        assert player.poll() is not None and player.returncode != 0
        rows.append({"case": "target_missing_at_start", "linkedToAnySink": False,
                     "playerRejected": True})
        current = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        assert current == default, "System default changed during test"
        report = {"passed": True, "allPcmSamplesZero": True, "streamVolume": 0,
                  "physicalPlaybackUsed": False, "systemDefaultUnchanged": True, "rows": rows}
        args.output.write_text(json.dumps(report, indent=2)+"\n")
        print(json.dumps(report))
    finally:
        if player:
            stop_player(player, thread)
        if module:
            subprocess.run(["pactl", "unload-module", module], check=True)


if __name__ == "__main__":
    main()
