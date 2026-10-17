"""Face-relative palm targets, two-bone arm IK and actual finger poses.

Positions are metres: +X her left, +Y up, +Z forward. Targets follow the
animated head/chest. Solve before VRM sleeve/twist constraints, so the cloth
uses the same final arm pose as the hand. No extra model request is needed.
"""
import numpy as np

from .model import euler, from_to, rotation
from .emote_api import FINGERS


def unit(vector):
    return vector / max(1e-8, np.linalg.norm(vector))


def blend_rotation(start, end, weight):
    if weight >= .99999: return end
    if weight <= .00001: return start
    delta = end @ start.T
    angle = np.arccos(np.clip((np.trace(delta)-1)/2, -1, 1))
    if angle < 1e-6: return end
    axis = np.array([delta[2,1]-delta[1,2], delta[0,2]-delta[2,0], delta[1,0]-delta[0,1]])
    if np.linalg.norm(axis) < 1e-5:
        # Stable at 180 degrees, where the antisymmetric part vanishes.
        values, vectors = np.linalg.eigh((delta+delta.T)/2)
        axis = vectors[:, np.argmax(values)]
    half = angle*weight/2
    return rotation([*(unit(axis)*np.sin(half)), np.cos(half)])[:3,:3] @ start


def reference(model, world, space):
    if space == 'world': return np.eye(4)
    bone = 'head' if space == 'face' else 'chest'
    i = model.bones[bone]
    transform = world[i] @ model.inverse_bind_world[i]
    # Face centre is forward/up from the head pivot; the chest uses its pivot.
    origin = model.bind_world[i][:3,3].copy()
    if space == 'face': origin += [0, .065, .100]
    transform[:3,3] = (transform @ np.append(origin, 1))[:3]
    return transform


def palm_geometry(model, side):
    wrist = model.bones[side+'Hand']
    middle = model.bones[side+'MiddleProximal']
    a, b = model.bind_world[wrist][:3,3], model.bind_world[middle][:3,3]
    forward = unit(b-a)
    normal = unit(np.array([0., -1., 0.])-forward*np.dot(forward, [0,-1,0]))
    basis = np.column_stack((np.cross(forward, normal), forward, normal))
    centre = model.inverse_bind_world[wrist] @ np.append((a+b)/2, 1)
    return centre, basis


def shape_fingers(model, local, side, shape, weight):
    sign = 1 if side == 'left' else -1
    for finger, parts in FINGERS.items():
        folded = shape == 'fist' or (shape == 'peace' and finger in {'Ring', 'Little', 'Thumb'}) \
                 or (shape == 'point' and finger != 'Index')
        curls = (64, 85, 65) if folded else ((10, 15, 10) if shape == 'relaxed' else (0, 0, 0))
        if finger == 'Thumb': curls = (25, 35, 30) if folded else (0, 0, 0)
        for part, curl in zip(parts, curls):
            name = side+finger+part
            if name not in model.bones: continue
            spread = 0
            if part == 'Proximal' and shape in {'open', 'peace'}:
                spread = {'Index': -12, 'Middle': 5, 'Ring': 9, 'Little': 16}.get(finger, 0)*sign
            if finger == 'Thumb' and part == 'Metacarpal' and folded: spread = 35*sign
            i = model.bones[name]
            basis = model.bind_world[i][:3,:3]
            desired = model.local[i][:3,:3] @ basis.T @ euler([0, spread, -sign*curl])[:3,:3] @ basis
            local[i][:3,:3] = blend_rotation(local[i][:3,:3], desired, weight)


def solve_hands(model, local, world, hands, update):
    results = {}
    for side, target in hands.items():
        weight = target.get('weight', 1)
        if weight <= 0: continue
        upper, lower, wrist = [model.bones[side+name] for name in ('UpperArm','LowerArm','Hand')]
        ref = reference(model, world, target.get('space', 'face'))
        centre, rest_basis = palm_geometry(model, side)
        desired_palm = (ref @ np.append(target['position'], 1))[:3]
        # Fingers point up; palm faces forward. Roll waves the palm in its own
        # plane, rather than twisting the upper arm along its length.
        desired_rotation = ref[:3,:3] @ euler([0,0,target.get('roll',0)])[:3,:3] \
                           @ rest_basis.T @ model.bind_world[wrist][:3,:3]
        hand_rotation = blend_rotation(world[wrist][:3,:3], desired_rotation, weight)
        current_palm = (world[wrist] @ centre)[:3]
        palm = current_palm+(desired_palm-current_palm)*weight
        destination = palm-hand_rotation @ centre[:3]
        root, elbow, tip = [world[i][:3,3].copy() for i in (upper, lower, wrist)]
        a, b = np.linalg.norm(elbow-root), np.linalg.norm(tip-elbow)
        distance = np.linalg.norm(destination-root)
        reach = float(np.clip(distance, abs(a-b)+1e-5, a+b-1e-5))
        direction = unit(destination-root) if distance > 1e-8 else np.array([0.,0.,1.])
        destination = root+direction*reach
        along = (a*a-b*b+reach*reach)/(2*reach)
        sign = 1 if side == 'left' else -1
        body = reference(model, world, 'body')[:3,:3]
        pole = body @ np.array([sign*.18, -.22, .08])
        bend = pole-direction*np.dot(pole,direction)
        if np.linalg.norm(bend) < 1e-5:
            bend = np.cross(direction, [0,0,1] if abs(direction[2]) < .8 else [0,1,0])
        elbow_target = root+direction*along+unit(bend)*np.sqrt(max(0, a*a-along*along))
        for bone, child, point in ((upper, lower, elbow_target), (lower, wrist, destination)):
            turn = from_to(world[child][:3,3]-world[bone][:3,3], point-world[bone][:3,3])
            parent = world[model.parents[bone]][:3,:3]
            local[bone][:3,:3] = parent.T @ turn @ world[bone][:3,:3]
            update(bone)
        local[wrist][:3,:3] = world[model.parents[wrist]][:3,:3].T @ hand_rotation
        shape_fingers(model, local, side, target.get('shape','open'), weight)
        update(wrist)
        actual = (world[wrist] @ centre)[:3]
        face = reference(model, world, 'face')
        results[side] = {
            'space': target.get('space','face'), 'shape': target.get('shape','open'),
            'weight': round(float(weight),3),
            'palmFromFace': np.round((np.linalg.inv(face) @ np.append(actual,1))[:3],4).tolist(),
            'errorMm': round(float(np.linalg.norm(actual-palm))*1000,3),
            'reachClamped': bool(abs(distance-reach) > .0001),
        }
    return results
