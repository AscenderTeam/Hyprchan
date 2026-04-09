import os

from hyprchan.core.animations.animation import Animation
from hyprchan.settings import SPRITES_BASE_DIR
from hyprchan.shared.utils.animations import load_animation_frames


class DepressedSitAnimation(Animation):
    def __init__(self):
        frames = load_animation_frames(
            os.path.join(SPRITES_BASE_DIR, "sit_depressed.png"),
        )
        super().__init__("sit.depressed", frames, False)
