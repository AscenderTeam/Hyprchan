import os

from hyprchan.core.animations.animation import Animation
from hyprchan.shared.utils.animations import load_animation_frames


class DepressedSitAnimation(Animation):
    def __init__(self):
        frames = load_animation_frames(
            os.path.abspath(
                os.path.join("public", "assets", "sprites", "sit_depressed.png")
            ),
        )
        super().__init__("sit.depressed", frames, False)
