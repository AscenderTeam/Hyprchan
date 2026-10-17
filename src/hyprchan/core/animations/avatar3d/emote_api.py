"""Tiny animation SDK for full-access Python emotes, running outside GTK.

Example: animate(4, lambda t: {'expressions': {'puff': sin(pi*t)**2}}).
Scripts can import any other Python module; this is a protocol, not a sandbox.
"""
import json
import math
import os
import time

HAND_SHAPES = {'open', 'relaxed', 'fist', 'peace', 'point'}
FINGERS = {
    'Thumb': ('Metacarpal', 'Proximal', 'Distal'),
    **{name: ('Proximal', 'Intermediate', 'Distal') for name in ('Index', 'Middle', 'Ring', 'Little')},
}
FINGER_BONES = {side+finger+part for side in ('left', 'right')
                for finger, parts in FINGERS.items() for part in parts}


def frame(expressions=None, bones=None, hands=None):
    print(json.dumps({'expressions': expressions or {}, 'bones': bones or {}, 'hands': hands or {}}, allow_nan=False), flush=True)


def hand_target(position=(0, -.02, .14), *, space='face', shape='open', roll=0, weight=1):
    """Palm position in metres relative to the animated face (or body/world).

    +X her left/viewer's right, +Y up, +Z in front. Palm faces forward and
    fingers point up. Shapes: open, relaxed, fist, peace, point. Roll is degrees.
    Use weight 0..1 for a soft reach/return. Example:
    {'hands': {'right': hand_target([0, -.02, .14], shape='peace')}}
    """
    return {'position': list(position), 'space': space, 'shape': shape, 'roll': roll, 'weight': weight}


def duration(default=4):
    """The model-selected duration, or a standalone script's own 3–30s default."""
    seconds = float(os.environ.get('HYPRCHAN_EMOTE_SECONDS', default))
    if not math.isfinite(seconds): raise ValueError('Animation duration must be finite')
    return max(3, min(30, seconds))


def animate(seconds, sample, fps=30):
    """Call sample(progress 0..1); emit its pose at a paced frame rate."""
    seconds = duration(seconds)
    fps = max(1, min(60, float(fps)))
    start = time.monotonic()
    index = 0
    while True:
        progress = min(1, (time.monotonic() - start) / seconds)
        pose = sample(progress)
        frame(pose.get('expressions'), pose.get('bones'), pose.get('hands'))
        if progress >= 1: break
        index += 1
        time.sleep(max(0, start + index / fps - time.monotonic()))


def ease(t):
    t = max(0, min(1, t))
    return t*t*(3-2*t)
