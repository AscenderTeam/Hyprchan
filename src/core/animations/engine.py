from queue import Empty, Queue
from threading import Thread
from typing import Any

from gi.repository import GLib

from core.animations.animation import Animation
from core.animations.renderer.application import HyprchanApp


class AnimationEngine:
    queue: Queue[Any]

    def __init__(self, animations: list[Animation], target_fps: int = 60) -> None:
        self.target_fps = target_fps
        self.queue = Queue()
        self.current_animation = None
        self.animations = animations
        self.application = HyprchanApp(self.on_frame_update, self.target_fps)

        self.load_animation("sit.depressed")

        self.start()

    def load_animation(self, name: str | None = None, is_next: bool = False):
        """
        Loads an animation by given `name` if `name` is present.

        If not then it loads the next animation if `is_next` is True, if either `is_next` isn't set or is False then it loads the first animation
        """
        print(self.animations)
        if self.current_animation:
            self.current_animation.reset_engine()
        if name:
            self.current_animation = next(
                (a for a in self.animations if a.name == name), None
            )

        elif is_next:
            if self.current_animation:
                self.current_animation = self.animations[
                    (self.animations.index(self.current_animation) + 1)
                    % len(self.animations)
                ]
            self.current_animation = self.animations[0]

        else:
            self.current_animation = self.animations[0]

        if self.current_animation:
            self.current_animation.set_engine(self)  # type: ignore
            return

        raise ValueError("Animation not found")

    def on_frame_update(self):
        print("ASD")
        new_command = None
        try:
            new_command = self.queue.get_nowait()
        except Empty:
            pass

        if not self.current_animation:
            # wait for a new animation
            return

        self.current_animation.update()

        frame_idx = self.current_animation.current_frame
        print(frame_idx)
        return self.current_animation.frames[frame_idx]

    def stop(self):
        self.application.quit()

    def start(self):
        """
        Start the hyprchan's application.

        NOTE: Start this function in a separate thread.
        And load an animation BEFORE starting the application.
        """
        GLib.idle_add(self.application.start_sprite)
        self.application.run(None)
