from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.25, (1-t)/.25))
    return {'expressions': {'smile': .4*w, 'blush': .3*w},
            'bones': {'head': [5*w, 0, -5*w]},
            'hands': {'right': hand_target([-.03, .10, .24],
                       space='body', shape='relaxed', roll=15, weight=w)}}

animate(4, pose)
