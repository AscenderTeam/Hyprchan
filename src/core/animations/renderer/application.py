import asyncio
from typing import Callable

import gi
from ascender.core import inject

from core.animations.renderer.window import HyprchanWindow
from core.hyprland.socket import HyprlandSocket

gi.require_version("Gtk", "4.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # type: ignore[attr-defined]


class HyprchanApp(Gtk.Application):
    def __init__(
        self,
        on_update_callback: Callable[[], GdkPixbuf.Pixbuf | None],
        target_fps: int = 60,
    ):
        super().__init__(application_id="org.hyprland.hyprchan")
        self.on_update_callback = on_update_callback
        self.target_fps = target_fps
        self._pending_overlay_text = ""

    def do_activate(self) -> None:
        self.win = HyprchanWindow()
        self.win.set_application(self)

        title = "hyprchan-overlay"
        self.win.set_title(title)
        self._apply_overlay_window_rules(title)
        self.win.set_overlay_text(self._pending_overlay_text)
        self.win.present()
        return None

    def start_sprite(self):
        GLib.timeout_add(1000 // self.target_fps, self.update_loop)

    def update_loop(self):
        frame = self.on_update_callback()
        if frame:
            width, height = frame.get_width(), frame.get_height()
            overlay_extra = self.win.overlay_height_hint()

            self.win.set_default_size(width, height + overlay_extra)
            self.win.set_image(frame)
            return True

        self.win.hide()
        return False

    def set_overlay_text(self, text: str) -> None:
        self._pending_overlay_text = text
        if hasattr(self, "win"):
            self.win.set_overlay_text(text)

    def _apply_overlay_window_rules(self, title: str) -> None:
        fallback = object()
        hyprland = inject(HyprlandSocket, fallback=fallback)
        if hyprland is fallback:
            return

        match_expr = f"match:title ^({title})$"
        rules = [
            f"no_blur 1, {match_expr}",
            f"border_size 0, {match_expr}",
            f"no_shadow 1, {match_expr}",
        ]

        async def _apply_rules():
            for rule in rules:
                await hyprland.send_command(f"keyword windowrule {rule}")

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_apply_rules())
            return

        running_loop.create_task(_apply_rules())
