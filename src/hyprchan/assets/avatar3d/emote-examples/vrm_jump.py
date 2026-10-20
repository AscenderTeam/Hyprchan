"""One cheerful rigged hop, including anticipation and a grounded final frame."""
from hyprchan.core.animations.avatar3d.emote_api import animate, jump


def pose(t):
    result = jump(t, height=.10)
    # Add your own face or hand acting to the returned root/bone pose.
    result['expressions']['eyes_happy'] = .2 * max(0, 1-abs(t-.40)/.20)
    return result


animate(3, pose)
