import os

from core.animations.animation import Animation
from settings import SPRITES_BASE_DIR
from shared.utils.animations import load_animation_frames


class SleepingSitAnimation(Animation):
    def __init__(self):
        frames = load_animation_frames(
            os.path.join(SPRITES_BASE_DIR, "sit_sleeping.png")
        )

        self.loop_cycle = 0

        self.tick_per_frame = 4
        self.tick_counter = 0

        super().__init__("sit.sleeping", frames, True)

    def update(self):
        self.tick_counter += 1
        self.next_frame()

        if self.tick_counter == self.tick_per_frame:
            self.tick_counter = 0
            self.loop_cycle += 1

        if self.loop_cycle == 5:
            self.load_animation("sit.startle_wakeup")
            self.loop_cycle = 0
