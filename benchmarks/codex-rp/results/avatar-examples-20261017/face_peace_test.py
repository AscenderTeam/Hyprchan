from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def pose(t):
    w = ease(min(t/.22, (1-t)/.26))
    return {
        'expressions': {'smile': .5*w, 'blush': .2*w},
        'bones': {'head': [0, 0, 8*w]},
        'hands': {'right': hand_target([-.025, -.025, .14],
                    shape='peace', roll=-8, weight=w)}
    }

animate(4, pose)
