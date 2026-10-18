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


def frame(expressions=None, bones=None, hands=None, root=None):
    pose = {'expressions': expressions or {}, 'bones': bones or {}, 'hands': hands or {}}
    if root is not None: pose['root'] = root
    print(json.dumps(pose, allow_nan=False), flush=True)


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
        frame(pose.get('expressions'), pose.get('bones'), pose.get('hands'), pose.get('root'))
        if progress >= 1: break
        index += 1
        time.sleep(max(0, start + index / fps - time.monotonic()))


def ease(t):
    t = max(0, min(1, t))
    return t*t*(3-2*t)


def jump(t, height=.10):
    """One VRM hop: crouch, takeoff, flight, landing and a neutral return.

    t is animate() progress 0..1; height is 0.02..0.16 metres. Translation is
    applied to the humanoid hips before skinning, hand IK and hair contact.
    The whole sequence follows the model-selected animation duration.
    """
    t, height = float(t), float(height)
    if not math.isfinite(t) or not math.isfinite(height) or not .02 <= height <= .16:
        raise ValueError('Jump progress must be finite and height must be 0.02–0.16 metres')
    t = max(0, min(1, t))
    crouch = lift = flight = 0.0
    if t < .20:
        crouch = ease(t/.20)
    elif t < .30:
        crouch = 1-ease((t-.20)/.10)
    elif t < .50:
        u = (t-.30)/.20
        flight = 4*u*(1-u)
        lift = height*flight
    elif t < .70:
        crouch = .7*math.sin(math.pi*(t-.50)/.20)**2
    lift -= (.015+.2*height)*crouch
    expression = ease(min(t/.22, (1-t)/.26))
    # Drive both hands fully overhead at takeoff, hold through the apex, then
    # lower them during landing. Sweep forward rather than through a T-pose.
    arms = ease((t-.16)/.18)*(1-ease((t-.46)/.28))
    forward = 35*(math.sin(math.pi*arms)+arms)
    return {
        'root': [0, lift, 0],
        'expressions': {'smile': .65*expression, 'brow_happy': .3*expression, 'blush': .2*expression},
        'bones': {
            'chest': [10*crouch-3*flight, 0, 0], 'head': [-3*flight, 0, 0],
            'leftUpperArm': [-8*crouch, -forward, -72+142*arms],
            'rightUpperArm': [-8*crouch, forward, 72-142*arms],
            'leftLowerArm': [0, -8+43*arms, -8+18*arms],
            'rightLowerArm': [0, 8-43*arms, 8-18*arms],
            'leftUpperLeg': [-16*crouch-7*flight, 0, 0],
            'rightUpperLeg': [-16*crouch-7*flight, 0, 0],
            'leftLowerLeg': [32*crouch+14*flight, 0, 0],
            'rightLowerLeg': [32*crouch+14*flight, 0, 0],
            'leftFoot': [-16*crouch-7*flight, 0, 0],
            'rightFoot': [-16*crouch-7*flight, 0, 0],
        },
    }
