from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.25, (1-t)/.25))
    return {'expressions': {'smile': .4*w, 'brow_happy': .3*w},
            'hands': {'right': hand_target([-.08, .17, .29+.035*sin(pi*t)],
                       space='body', shape='open', weight=w)}}

animate(4, pose)
