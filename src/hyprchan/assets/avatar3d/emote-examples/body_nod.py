from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = sin(pi*t)**2
    return {'expressions': {'smile': .45*w, 'brow_happy': .2*w},
            'bones': {'head': [8*sin(t*6*pi)*w, 0, 3*w], 'neck': [2*w, 0, 0],
                      'spine': [0, 0, -2*w], 'chest': [0, 0, 3*w],
                      'upperChest': [0, 3*w, 0],
                      'leftShoulder': [0, 0, 3*w], 'rightShoulder': [0, 0, -3*w]}}

animate(4, pose)
