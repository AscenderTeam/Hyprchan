import math
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    # Raise into a gentle hold, then lower smoothly.
    weight = ease(min(t / 0.24, (1 - t) / 0.24))
    # Slight head tilt settles in during the hold and eases away at the end.
    tilt = 12 * math.sin(math.pi * min(t / 0.38, 1.0)) if t < 0.38 else 12 * ease(min((1 - t) / 0.24, 1.0))
    return {
        "expressions": {"smile": 0.5, "wink_left": 0.18},
        "bones": {"head": [0, 0, tilt]},
        "hands": {
            "right": hand_target([0, -0.022, 0.14], space="face", shape="peace",
                                 roll=-8, weight=weight)
        }
    }

animate(4, pose)