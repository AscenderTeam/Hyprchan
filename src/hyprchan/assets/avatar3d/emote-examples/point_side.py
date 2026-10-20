from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.2, (1-t)/.25))
    return {'expressions': {'brow_up': .4*w, 'smile': .35*w},
            'hands': {'right': hand_target([-.12, -.045, .15],
                       shape='point', roll=90, weight=w)}}

animate(4, pose)
