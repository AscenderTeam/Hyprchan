from math import sin, pi
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

from time import sleep
from hyprchan.core.animations.avatar3d.emote_api import frame, duration

steps = round(duration(3)*30)
for i in range(steps+1):
    t = i/steps
    w = sin(pi*t)**2
    frame(expressions={'smile': .5*w, 'blush': .2*w},
          bones={'head': [0, 0, 6*w]},
          hands={'right': hand_target([-.03, -.025, .14], shape='peace', weight=w)})
    sleep(1/30)
frame(expressions={'smile': .1}, bones={'head': [0, 0, 0]}, hands={})
