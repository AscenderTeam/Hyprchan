import math
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    weight = ease(min(t / 0.22, (1 - t) / 0.22))
    wave = math.sin(t * 2 * math.pi * 3.2)
    return {
        "expressions": {"smile": 0.45},
        "hands": {
            "right": hand_target([0.018 * wave, -0.025, 0.14], space="face", shape="open",
                                 roll=16 * wave, weight=weight)
        }
    }

animate(4, pose)