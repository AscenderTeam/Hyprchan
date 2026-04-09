from queue import Empty, Queue
from threading import Thread
from typing import Any

from gi.repository import GLib  # type: ignore[attr-defined]

from hyprchan.core.animations.animation import Animation
from hyprchan.core.animations.renderer.application import HyprchanApp


class AnimationEngine:
    queue: Queue[Any]

    def __init__(self, animations: list[Animation], target_fps: int = 60) -> None:
        self.target_fps = target_fps
        self.queue = Queue()
        self.current_animation = None
        self.animations = animations
        self.application = HyprchanApp(self.on_frame_update, self.target_fps)
        self._thread: Thread | None = None

        self.load_animation("sit.idle")

        self.start()

    def load_animation(self, name: str | None = None, is_next: bool = False):
        """
        Loads an animation by given `name` if `name` is present.

        If not then it loads the next animation if `is_next` is True, if either `is_next` isn't set or is False then it loads the first animation
        """
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
            else:
                self.current_animation = self.animations[0]

        else:
            self.current_animation = self.animations[0]

        if self.current_animation:
            self.current_animation.set_engine(self)  # type: ignore
            return

        raise ValueError("Animation not found")

    def on_frame_update(self):
        self._process_command_queue()

        if not self.current_animation:
            # wait for a new animation
            return

        self.current_animation.update()

        frame_idx = self.current_animation.current_frame
        return self.current_animation.frames[frame_idx]

    def _process_command_queue(self) -> None:
        while True:
            try:
                command = self.queue.get_nowait()
            except Empty:
                break

            if not isinstance(command, dict):
                continue

            command_type = str(command.get("type", "")).strip()
            if command_type == "set_pose":
                pose = str(command.get("pose", "")).strip()
                if pose:
                    try:
                        self.load_animation(pose)
                    except ValueError:
                        continue
                continue

            if command_type == "answer_user":
                text = str(command.get("text", "")).strip()
                self.application.set_overlay_text(text)  # pyright: ignore[reportAttributeAccessIssue]
                continue

            if command_type == "move_self":
                direction = str(command.get("direction", "")).strip().lower()
                try:
                    delta = int(command.get("delta", 0))
                except (TypeError, ValueError):
                    delta = 0
                try:
                    scale = float(command.get("scale", 1.0))
                except (TypeError, ValueError):
                    scale = 1.0

                self.application.move_overlay(direction=direction, delta=delta)  # pyright: ignore[reportAttributeAccessIssue]
                self.application.set_sprite_scale(scale)  # pyright: ignore[reportAttributeAccessIssue]

    def available_animation_names(self) -> list[str]:
        return [animation.name for animation in self.animations]

    def enqueue_set_pose(self, pose: str) -> None:
        self.queue.put({"type": "set_pose", "pose": pose})

    def enqueue_answer_text(self, text: str) -> None:
        self.queue.put({"type": "answer_user", "text": text})

    def enqueue_move_self(self, *, direction: str, delta: int, scale: float) -> None:
        self.queue.put(
            {
                "type": "move_self",
                "direction": direction,
                "delta": delta,
                "scale": scale,
            }
        )

    def stop(self):
        self.application.quit()

    def start(self):
        """
        Start the hyprchan's application.

        NOTE: Start this function in a separate thread.
        And load an animation BEFORE starting the application.
        """
        if self._thread and self._thread.is_alive():
            return

        self._thread = Thread(target=self._run_application, daemon=True)
        self._thread.start()

    def _run_application(self) -> None:
        GLib.idle_add(self.application.start_sprite)
        self.application.run(None)
