import os

from hyprchan.core.animations.animation import Animation
from hyprchan.settings import SPRITES_BASE_DIR
from hyprchan.shared.utils.animations import load_animation_frames


class FallingAsleepSitAnimation(Animation):
    def __init__(self):
        self.next = "sit.sleeping"
        frames = load_animation_frames(
            os.path.join(SPRITES_BASE_DIR, "sit_fall_asleep.png")
        )
        # since our animation has 7 frames, we need to slow down the animation
        self.ticks_per_frame = 2
        self.tick_counter = 0

        super().__init__("sit.falling_asleep", frames, True)

    def update(self):
        self.tick_counter += 1

        if self.tick_counter < self.ticks_per_frame:
            return

        self.tick_counter = 0

        # is last frame?
        if self.current_frame == len(self.frames) - 1:
            self.load_animation(self.next)
            return

        return self.next_frame()
