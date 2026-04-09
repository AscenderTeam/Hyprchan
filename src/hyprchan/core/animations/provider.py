from ascender.core import Provider

from hyprchan.core.animations.animation import Animation
from hyprchan.core.animations.engine import AnimationEngine


def provideAnimations(animations: list[Animation], target_fps: int = 60) -> Provider:
    return [
        {
            "provide": AnimationEngine,
            "use_factory": lambda: AnimationEngine(
                animations, target_fps=target_fps
            ),
        },
    ]
