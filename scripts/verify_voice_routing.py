#!/usr/bin/env python3
"""Check normal and explicit PipeWire routing with zero-valued PCM only."""
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


def stream_nodes(pid, objects):
    clients = {node["id"] for node in objects if str(node.get("info", {}).get("props", {}).get(
        "application.process.id")) == str(pid) and node["type"] == "PipeWire:Interface:Client"}
    return {node["id"] for node in objects if node.get("info", {}).get("props", {}).get(
        "client.id") in clients and node["type"] == "PipeWire:Interface:Node"}


def destinations(pid):
    objects = graph()
    sources = stream_nodes(pid, objects)
    sinks = {node["id"] for node in objects if node.get("info", {}).get("props", {}).get(
        "media.class") == "Audio/Sink"}
    return {node["info"]["input-node-id"] for node in objects
            if node["type"] == "PipeWire:Interface:Link" and node.get("info", {}).get("output-node-id") in sources
            and node["info"].get("input-node-id") in sinks}


def output_reachable(pid, target):
    """Include paired processing nodes, e.g. the user's EasyEffects sink."""
    objects = graph()
    reached = stream_nodes(pid, objects)
    groups = {}
    edges = []
    for node in objects:
        info = node.get("info", {})
        props = info.get("props", {})
        if node["type"] == "PipeWire:Interface:Node" and props.get("node.link-group"):
            groups.setdefault(props["node.link-group"], set()).add(node["id"])
        elif node["type"] == "PipeWire:Interface:Link":
            edges.append((info["output-node-id"], info["input-node-id"]))
    while True:
        following = reached | {b for a, b in edges if a in reached}
        for group in groups.values():
            if group & reached:
                following |= group
        if following == reached:
            return target in reached
        reached = following


def start_silent_player(target, *, locked=True):
    properties = playback_properties(locked=locked)
    # Keep test stream routing/volume history separate from the real companion.
    properties.update({"application.name": "Hyprchan routing check",
                       "node.name": f"hyprchan-routing-check-{os.getpid()}"})
    process = subprocess.Popen(["pw-play", "--raw", "--format", "s16", "--rate", "48000",
        "--channels", "1", "--target", target, "--volume", "0",
        "-P", json.dumps(properties), "-"],
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
        _, default_serial, _ = playback_target()
        default_id = next(node["id"] for node in graph() if str(node.get("info", {}).get("props", {}).get(
            "object.serial")) == default_serial and node["type"] == "PipeWire:Interface:Node")
        player, thread = start_silent_player(default_serial, locked=False)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline and not output_reachable(player.pid, default_id):
            time.sleep(.05)
        assert output_reachable(player.pid, default_id), "Normal mode missed the current system output"
        rows.append({"case": "system_output", "currentDefaultReachable": True,
                     "processingFiltersAllowed": True,
                     "sessionManagerReroutedStream": destinations(player.pid) != {default_id}})
        stop_player(player, thread)
        player = None
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
                  "audiblePlaybackUsed": False, "physicalOutputLinkedWithSilence": True,
                  "systemDefaultUnchanged": True, "rows": rows}
        args.output.write_text(json.dumps(report, indent=2)+"\n")
        print(json.dumps(report))
    finally:
        if player:
            stop_player(player, thread)
        if module:
            subprocess.run(["pactl", "unload-module", module], check=True)


if __name__ == "__main__":
    main()
