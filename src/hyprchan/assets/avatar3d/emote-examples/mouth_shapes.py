from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

VOWELS = ['mouth_a', 'mouth_i', 'mouth_u', 'mouth_e', 'mouth_o']

def pose(t):
    i = min(len(VOWELS)-1, int(t*len(VOWELS)))
    u = t*len(VOWELS)-i
    return {'expressions': {VOWELS[i]: .65*sin(pi*u)**2, 'smile': 0, 'mouth_close': 0}}

animate(5, pose)
