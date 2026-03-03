import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GdkPixbuf, Gtk


class HyprchanWindow(Gtk.Window):
    def __init__(self):
        super().__init__()

        self.set_decorated(False)

        # Resize it to normal size
        self.set_default_size(112, 234)

        # Make it irresizable
        self.set_resizable(False)

        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(b"window { background: transparent; }")

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),  # type: ignore
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.image = Gtk.Image()
        self.image.set_pixel_size(512)
        self.set_child(self.image)

    def set_image(self, image: GdkPixbuf.Pixbuf):
        self.image.set_from_pixbuf(image)
        self.image.queue_draw()
