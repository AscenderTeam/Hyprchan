from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.2, (1-t)/.25))
    puff = w if t < .7 else w*min(1, max(0, (1-t)/.3))
    return {'expressions': {'puff': .9*puff, 'mouth_small': .6*puff,
                           'mouth_down': .3*puff, 'mouth_close': puff,
                           'smile': .4*(1-puff), 'brow_angry': .55*puff,
                           'blush': .35*w, 'joy': 0, 'eyes_happy': 0},
            'bones': {'head': [-3*w, 5*w, 8*w]}}

animate(4, pose)
