from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.2, (1-t)/.24))
    return {'expressions': {'smile': .6*w, 'wink_left': .8*w, 'blush': .25*w},
            'hands': {'right': hand_target([-.025, -.025, .14],
                       shape='peace', roll=-8, weight=w)}}

animate(4, pose)
