import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gtk  # type: ignore[attr-defined]


class HyprchanWindow(Gtk.Window):
    def __init__(self):
        super().__init__()

        self.set_decorated(False)

        # Resize it to normal size
        self.set_default_size(112, 234)

        # Make it irresizable
        self.set_resizable(False)

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

        self.image = Gtk.Image()
        self.image.set_pixel_size(512)
        self.image.set_halign(Gtk.Align.CENTER)
        self.stack.append(self.image)

        self.set_child(self.stack)

    def set_image(self, image: GdkPixbuf.Pixbuf):
        self.image.set_from_pixbuf(image)
        self.image.queue_draw()

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
