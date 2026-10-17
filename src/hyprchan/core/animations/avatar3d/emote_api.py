"""Tiny animation SDK for full-access Python emotes, running outside GTK.

Example: animate(4, lambda t: {'expressions': {'puff': sin(pi*t)**2}}).
Scripts can import any other Python module; this is a protocol, not a sandbox.
"""
import json
import time


def frame(expressions=None, bones=None):
    print(json.dumps({'expressions': expressions or {}, 'bones': bones or {}}, allow_nan=False), flush=True)


def animate(seconds, sample, fps=30):
    """Call sample(progress 0..1); emit its pose at a paced frame rate."""
    seconds = max(.05, min(30, float(seconds)))
    fps = max(1, min(60, float(fps)))
    start = time.monotonic()
    index = 0
    while True:
        progress = min(1, (time.monotonic() - start) / seconds)
        pose = sample(progress)
        frame(pose.get('expressions'), pose.get('bones'))
        if progress >= 1: break
        index += 1
        time.sleep(max(0, start + index / fps - time.monotonic()))


def ease(t):
    t = max(0, min(1, t))
    return t*t*(3-2*t)
