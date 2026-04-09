import os

from hyprchan.core.animations.animation import Animation
from hyprchan.settings import SPRITES_BASE_DIR
from hyprchan.shared.utils.animations import load_animation_frames


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
