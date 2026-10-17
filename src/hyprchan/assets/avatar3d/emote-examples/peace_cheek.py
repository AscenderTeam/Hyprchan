from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.2, (1-t)/.24))
    return {'expressions': {'smile': .5*w, 'blush': .25*w},
            'bones': {'head': [0, -5*w, -7*w]},
            'hands': {'right': hand_target([-.10, -.025, .14],
                       shape='peace', roll=-12, weight=w)}}

animate(4, pose)
