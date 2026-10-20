from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.22, (1-t)/.25))
    bones = {'rightUpperArm': [0, 55*w, 72-62*w],
             'rightLowerArm': [0, 8*(1-w), 8-118*w],
             'rightHand': [0, 0, -8*w],
             'rightIndexProximal': [0, 12*w, 0],
             'rightMiddleProximal': [0, -5*w, 0]}
    for finger in ('Ring', 'Little'):
        for part, angle in zip(('Proximal', 'Intermediate', 'Distal'), (64, 85, 65)):
            bones['right'+finger+part] = [0, 0, angle*w]
    bones['rightThumbMetacarpal'] = [0, -35*w, 25*w]
    bones['rightThumbProximal'] = [0, 0, 35*w]
    bones['rightThumbDistal'] = [0, 0, 30*w]
    return {'expressions': {'smile': .5*w}, 'bones': bones}

animate(4, pose)
