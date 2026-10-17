from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.2, (1-t)/.24))
    return {'expressions': {'smile': .4*w},
            'bones': {'head': [0, 20*sin(t*2*pi)*w, 0]},
            'hands': {'right': hand_target([0, 1.43, .21],
                       space='world', shape='open', roll=-5, weight=w)}}

animate(5, pose)
