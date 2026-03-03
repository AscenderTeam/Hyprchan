from ascender.core import Provider, provideLifecycle

from core.animations.animation import Animation
from core.animations.engine import AnimationEngine


def provideAnimations(animations: list[Animation], target_fps: int = 60) -> Provider:
    return [
        {
            "provide": AnimationEngine,
            "value": AnimationEngine(animations, target_fps=target_fps),
        },
        provideLifecycle([AnimationEngine]),
    ]
