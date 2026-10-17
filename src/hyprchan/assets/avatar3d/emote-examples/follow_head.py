from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.2, (1-t)/.22))
    return {'expressions': {'smile': .4*w, 'brow_up': .3*w},
            'bones': {'head': [5*w, 20*sin(t*2*pi)*w, 8*w], 'chest': [0, 8*w, 0]},
            'hands': {'right': hand_target([-.025, -.03, .14], shape='peace', weight=w)}}

animate(5, pose)
