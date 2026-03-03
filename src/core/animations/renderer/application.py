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
        self._window_title = "hyprchan-overlay"
        self._sprite_scale = 1.0
        self._overlay_position: tuple[int, int] | None = None

    def do_activate(self) -> None:
        self.win = HyprchanWindow()
        self.win.set_application(self)

        title = self._window_title
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
            scale = max(0.0, min(2.0, float(self._sprite_scale)))
            scaled_width = max(1, int(round(width * scale)))
            scaled_height = max(1, int(round(height * scale)))

            if scaled_width != width or scaled_height != height:
                scaled_frame = frame.scale_simple(
                    scaled_width,
                    scaled_height,
                    GdkPixbuf.InterpType.BILINEAR,
                )
                if scaled_frame is not None:
                    frame = scaled_frame
                    width = scaled_width
                    height = scaled_height

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

    def set_sprite_scale(self, scale: float) -> None:
        self._sprite_scale = max(0.0, min(2.0, float(scale)))

    def move_overlay(self, *, direction: str, delta: int) -> None:
        step = max(0, int(delta))
        if step <= 0:
            return

        offsets: dict[str, tuple[int, int]] = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0),
            "up_left": (-1, -1),
            "up_right": (1, -1),
            "down_left": (-1, 1),
            "down_right": (1, 1),
        }
        if direction not in offsets:
            return

        dx_unit, dy_unit = offsets[direction]
        dx = dx_unit * step
        dy = dy_unit * step

        current = self._query_overlay_position_sync()
        if current is None:
            return

        target_x = max(0, int(current[0] + dx))
        target_y = max(0, int(current[1] + dy))
        moved = self._move_overlay_to_sync(target_x, target_y)
        if moved:
            self._overlay_position = (target_x, target_y)

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

    def _resolve_hyprland(self) -> HyprlandSocket | None:
        fallback = object()
        hyprland = inject(HyprlandSocket, fallback=fallback)
        if hyprland is fallback:
            return None
        return hyprland

    def _query_overlay_position_sync(self) -> tuple[int, int] | None:
        if self._overlay_position is not None:
            return self._overlay_position

        hyprland = self._resolve_hyprland()
        if hyprland is None:
            return None

        async def _query() -> tuple[int, int] | None:
            clients = await hyprland.send_command("clients", is_json=True)
            if not isinstance(clients, list):
                return None

            for client in clients:
                if not isinstance(client, dict):
                    continue
                title = str(client.get("title", ""))
                if title != self._window_title:
                    continue
                at = client.get("at")
                if not (isinstance(at, list) and len(at) >= 2):
                    continue
                try:
                    return int(at[0]), int(at[1])
                except (TypeError, ValueError):
                    return None
            return None

        try:
            position = asyncio.run(_query())
        except Exception:
            return None

        self._overlay_position = position
        return position

    def _move_overlay_to_sync(self, x: int, y: int) -> bool:
        hyprland = self._resolve_hyprland()
        if hyprland is None:
            return False

        command = (
            f"dispatch movewindowpixel exact {int(x)} {int(y)},"
            f"title:^({self._window_title})$"
        )

        async def _move() -> bool:
            result = await hyprland.send_command(command)
            return isinstance(result, str) and "ok" in result.lower()

        try:
            return bool(asyncio.run(_move()))
        except Exception:
            return False
