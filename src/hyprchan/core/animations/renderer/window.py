import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GdkPixbuf, Graphene, Gsk, Gtk  # type: ignore[attr-defined]


class PixelArtImage(Gtk.Widget):
    def __init__(self) -> None:
        super().__init__()
        self._pixbuf: GdkPixbuf.Pixbuf | None = None
        self._texture: Gdk.Texture | None = None

    def set_from_pixbuf(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        self._pixbuf = pixbuf
        self._texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        self.queue_resize()
        self.queue_draw()

    def do_measure(
        self,
        orientation: Gtk.Orientation,
        for_size: int,
    ) -> tuple[int, int, int, int]:
        _ = for_size
        if self._pixbuf is None:
            return 0, 0, -1, -1

        if orientation == Gtk.Orientation.HORIZONTAL:
            size = self._pixbuf.get_width()
        else:
            size = self._pixbuf.get_height()

        return size, size, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if self._pixbuf is None or self._texture is None:
            return

        width = max(1, self.get_width())
        height = max(1, self.get_height())
        source_width = max(1, self._pixbuf.get_width())
        source_height = max(1, self._pixbuf.get_height())

        scale = min(width / source_width, height / source_height)
        draw_width = max(1, int(round(source_width * scale)))
        draw_height = max(1, int(round(source_height * scale)))

        offset_x = (width - draw_width) / 2
        offset_y = (height - draw_height) / 2

        bounds = Graphene.Rect()
        bounds.init(
            float(offset_x), float(offset_y), float(draw_width), float(draw_height)
        )

        if hasattr(snapshot, "append_scaled_texture"):
            snapshot.append_scaled_texture(
                self._texture,
                Gsk.ScalingFilter.NEAREST,
                bounds,
            )
            return

        scaled = self._pixbuf.scale_simple(
            draw_width,
            draw_height,
            GdkPixbuf.InterpType.NEAREST,
        )
        if scaled is None:
            return

        snapshot.append_texture(Gdk.Texture.new_for_pixbuf(scaled), bounds)


class HyprchanWindow(Gtk.Window):
    def __init__(self):
        super().__init__()

        self._resize_margin_px = 14

        self.set_decorated(False)

        # Resize it to normal size
        self.set_default_size(112, 234)

        self.set_resizable(True)

        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(
            b"window { background: transparent; }"
            b"label.hyprchan-answer-text {"
            b"color: #ffffff;"
            b"font-size: 13px;"
            b"font-weight: 600;"
            b"padding: 6px 10px;"
            b"border-radius: 8px;"
            b"background-color: rgba(0, 0, 0, 0.45);"
            b"}"
        )

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),  # type: ignore
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self.answer_label = Gtk.Label(label="")
        self.answer_label.add_css_class("hyprchan-answer-text")
        self.answer_label.set_halign(Gtk.Align.CENTER)
        self.answer_label.set_valign(Gtk.Align.START)
        self.answer_label.set_wrap(True)
        self.answer_label.set_justify(Gtk.Justification.CENTER)
        self.answer_label.set_margin_top(6)
        self.answer_label.set_margin_bottom(2)
        self.answer_label.set_margin_start(8)
        self.answer_label.set_margin_end(8)
        self.answer_label.set_max_width_chars(32)
        self.answer_label.set_visible(False)
        self.stack.append(self.answer_label)

        self.image = PixelArtImage()
        self.image.set_halign(Gtk.Align.FILL)
        self.image.set_valign(Gtk.Align.FILL)
        self.image.set_hexpand(True)
        self.image.set_vexpand(True)
        self.stack.append(self.image)

        self.set_child(self.stack)

        self._drag_gesture = Gtk.GestureClick.new()
        self._drag_gesture.set_button(1)
        self._drag_gesture.connect("pressed", self._on_drag_pressed)
        self.add_controller(self._drag_gesture)

    def set_image(self, image: GdkPixbuf.Pixbuf):
        self.image.set_from_pixbuf(image)

    def set_overlay_text(self, text: str) -> None:
        normalized = text.strip()
        self.answer_label.set_label(normalized)
        self.answer_label.set_visible(bool(normalized))

    def overlay_height_hint(self) -> int:
        if not self.answer_label.get_visible():
            return 0

        text = self.answer_label.get_label() or ""
        char_count = len(text)
        line_count = max(1, min(6, (char_count + 31) // 32))
        return 20 + (line_count * 24)

    def _edge_from_point(self, x: float, y: float) -> Gdk.SurfaceEdge | None:
        width = max(1, self.get_width())
        height = max(1, self.get_height())

        left = x <= self._resize_margin_px
        right = x >= (width - self._resize_margin_px)
        top = y <= self._resize_margin_px
        bottom = y >= (height - self._resize_margin_px)

        if top and left:
            return Gdk.SurfaceEdge.NORTH_WEST
        if top and right:
            return Gdk.SurfaceEdge.NORTH_EAST
        if bottom and left:
            return Gdk.SurfaceEdge.SOUTH_WEST
        if bottom and right:
            return Gdk.SurfaceEdge.SOUTH_EAST
        if left:
            return Gdk.SurfaceEdge.WEST
        if right:
            return Gdk.SurfaceEdge.EAST
        if top:
            return Gdk.SurfaceEdge.NORTH
        if bottom:
            return Gdk.SurfaceEdge.SOUTH

        return None

    def _on_drag_pressed(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
    ) -> None:
        _ = n_press

        surface = self.get_surface()
        if surface is None:
            return

        event = gesture.get_current_event()
        if event is None:
            return

        button = int(gesture.get_current_button())
        device = event.get_device()
        timestamp = int(event.get_time())
        if button <= 0 or device is None:
            return

        edge = self._edge_from_point(x, y)
        if edge is not None and hasattr(surface, "begin_resize"):
            surface.begin_resize(edge, device, button, x, y, timestamp)  # type: ignore[attr-defined]
            return

        if hasattr(surface, "begin_move"):
            surface.begin_move(device, button, x, y, timestamp)  # type: ignore[attr-defined]
