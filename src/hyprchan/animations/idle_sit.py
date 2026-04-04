import os

from core.animations.animation import Animation
from settings import SPRITES_BASE_DIR
from shared.utils.animations import load_animation_frames


class IdleSitAnimation(Animation):
    def __init__(self):
        frames = load_animation_frames(
            os.path.join(SPRITES_BASE_DIR, "sit_idle.png")
        )

        super().__init__("sit.idle", frames, True)
