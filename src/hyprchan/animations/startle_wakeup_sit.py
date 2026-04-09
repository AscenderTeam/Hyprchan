import os

from hyprchan.core.animations.animation import Animation
from hyprchan.settings import SPRITES_BASE_DIR
from hyprchan.shared.utils.animations import load_animation_frames


class StartleWakeupSitAnimation(Animation):
    def __init__(self):
        self.next = "sit.idle"
        frames = load_animation_frames(
            os.path.join(SPRITES_BASE_DIR, "sit_startle_wakeup.png")
        )

        super().__init__("sit.startle_wakeup", frames, True)

    def update(self):
        if self.current_frame == len(self.frames) - 1:
            self.load_animation(self.next)

        return self.next_frame()
