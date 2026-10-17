from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

SHAPES = ['open', 'relaxed', 'fist', 'peace', 'point']

def pose(t):
    i = min(len(SHAPES)-1, int(t*len(SHAPES)))
    u = t*len(SHAPES)-i
    w = ease(min(u/.25, (1-u)/.25))
    return {'expressions': {'smile': .45*w},
            'hands': {'right': hand_target([-.035, -.03, .14],
                       shape=SHAPES[i], weight=w)}}

animate(10, pose)
