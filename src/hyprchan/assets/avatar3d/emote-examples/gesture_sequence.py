from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    if t < .2:
        w = sin(pi*t/.2)**2
        return {'expressions': {'brow_up': .5*w, 'blush': .25*w},
                'bones': {'head': [0, 0, -6*w]}}
    if t < .6:
        u = (t-.2)/.4
        w = ease(min(u/.2, (1-u)/.2))
        return {'expressions': {'smile': .5*w},
                'hands': {'right': hand_target([-.035, -.025, .14], shape='peace', weight=w)}}
    u = (t-.6)/.4
    w = ease(min(u/.2, (1-u)/.2))
    return {'expressions': {'smile': .65*w},
            'hands': {'left': hand_target([.02*sin(u*20), -.025, .14],
                      roll=-16*sin(u*24), weight=w)}}

animate(7, pose)
