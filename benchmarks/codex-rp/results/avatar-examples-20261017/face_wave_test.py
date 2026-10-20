from math import sin
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.22, (1-t)/.24))
    return {
        'expressions': {'smile': .45*w},
        'hands': {'right': hand_target([.018*sin(t*20), -.025, .14],
                    shape='open', roll=16*sin(t*32), weight=w)}
    }

animate(4, pose)
