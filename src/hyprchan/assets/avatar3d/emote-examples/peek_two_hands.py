from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.28, (1-t)/.3))
    return {'expressions': {'smile': .35*w, 'blush': .45*w},
            'bones': {'head': [0, 0, 7*w]},
            'hands': {'left': hand_target([.085, -.07, .13], shape='relaxed', roll=12, weight=w),
                      'right': hand_target([-.085, -.07, .13], shape='relaxed', roll=-12, weight=w)}}

animate(4.5, pose)
