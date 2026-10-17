import math
from hyprchan.core.animations.avatar3d.emote_api import animate, frame, ease

def pose(t):
    # 0.00-0.18 anticipation, 0.18-0.58 puff, 0.58-1.00 soften and smile
    if t < 0.18:
        p = ease(t / 0.18)
        return {
            "expressions": {"surprised": 0.25 * p, "puff": 0.15 * p, "mouth_close": 1, "smile": 0},
            "bones": {"head": [0, 0, -3 * p], "neck": [0, 0, -2 * p]}
        }
    if t < 0.58:
        p = ease((t - 0.18) / 0.40)
        return {
            "expressions": {"puff": 1, "eyes_wide": 0.18, "blink": 0, "mouth_close": 1, "smile": 0, "surprised": 0.15},
            "bones": {"head": [0, 0, -3 - 9 * p], "neck": [0, 0, -2 - 3 * p]}
        }
    p = ease((t - 0.58) / 0.42)
    return {
        "expressions": {"puff": 1 - p, "eyes_wide": 0.18 * (1 - p), "mouth_close": 1 - p, "smile": 0.65 * p, "joy": 0.2 * p},
        "bones": {"head": [0, 0, -12 * (1 - p)], "neck": [0, 0, -5 * (1 - p)]}
    }

animate(4.0, lambda t: pose(t))