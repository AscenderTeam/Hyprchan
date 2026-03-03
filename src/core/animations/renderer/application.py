from typing import Callable

import gi

from core.animations.renderer.window import HyprchanWindow

gi.require_version("Gtk", "4.0")
from gi.repository import GdkPixbuf, GLib, Gtk


class HyprchanApp(Gtk.Application):
    def __init__(
        self,
        on_update_callback: Callable[[], GdkPixbuf.Pixbuf | None],
        target_fps: int = 60,
    ):
        super().__init__(application_id="org.hyprland.hyprchan")
        self.on_update_callback = on_update_callback
        self.target_fps = target_fps

    def do_activate(self) -> None:
        self.win = HyprchanWindow()
        self.win.set_application(self)

        self.win.set_title("hyprchan-overlay")
        self.win.present()
        return super().do_activate()

    def start_sprite(self):
        GLib.timeout_add(1000 // self.target_fps, self.update_loop)

    def update_loop(self):
        frame = self.on_update_callback()

        if frame:
            self.win.set_image(frame)
            return True

        self.win.hide()
        return False
