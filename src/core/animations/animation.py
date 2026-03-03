from typing import TYPE_CHECKING, Any, final

if TYPE_CHECKING:
    from gi.repository import GdkPixbuf

    from core.animations.engine import AnimationEngine


class Animation:
    def __init__(self, name: str, frames: list["GdkPixbuf.Pixbuf"], loop: bool = True):
        self.name = name
        self.frames = frames
        self.current_frame = 0
        self.loop = loop
        self._engine = None

        if not frames:
            raise ValueError("Animation must have at least one frame")

    @property
    def engine(self):
        if not self._engine:
            raise RuntimeError(
                "Cannot perform action before engine is set. Is animation is active right now?"
            )
        return self._engine

    @final
    def next_frame(self):
        if self.current_frame == len(self.frames) - 1:
            if not self.loop:
                return

            self.current_frame = 0
            return

        self.current_frame = (self.current_frame + 1) % len(self.frames)

    @final
    def prev_frame(self):
        if self.current_frame == 0:
            if not self.loop:
                return

            self.current_frame = len(self.frames) - 1
            return

        self.current_frame = (self.current_frame - 1) % len(self.frames)

    @final
    def set_engine(self, engine: "AnimationEngine"):
        self._engine = engine

    @final
    def reset_engine(self):
        self._engine = None

    def load_animation(self, name: str | None = None, is_next: bool = True):
        self.engine.load_animation(name, is_next)

    def update(self):
        return self.next_frame()
