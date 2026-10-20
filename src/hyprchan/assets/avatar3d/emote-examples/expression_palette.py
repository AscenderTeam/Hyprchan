from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

FACES = [
    {'smile': .65, 'brow_happy': .4, 'eyes_happy': .1, 'mouth_up': .3},
    {'joy': .6, 'mouth_a': .3, 'blush': .3},
    {'sad': .65, 'brow_sad': .5, 'mouth_down': .3},
    {'angry': .6, 'brow_angry': .6, 'mouth_small': .5},
    {'surprised': .7, 'eyes_wide': .5, 'brow_up': .4, 'mouth_o': .3},
    {'relaxed': .6, 'blink': .6, 'mouth_close': .6},
    {'wink_left': .9, 'smile': .6},
    {'wink_right': .9, 'smile': .6},
]

def pose(t):
    i = min(len(FACES)-1, int(t*len(FACES)))
    u = t*len(FACES)-i
    w = ease(min(u/.25, (1-u)/.25))
    return {'expressions': {name: value*w for name, value in FACES[i].items()}}

animate(12, pose)
