import ctypes
import threading

import pystray
from PIL import Image, ImageDraw

MB_ICONERROR = 0x10
MB_SYSTEMMODAL = 0x1000


def show_error_popup(message, title="Talkative"):
    """Show a blocking Windows message box on its own thread so it never
    freezes the hotkey listener or tray loop."""

    def _show():
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONERROR | MB_SYSTEMMODAL)

    threading.Thread(target=_show, daemon=True).start()


def _round_line(d, p0, p1, fill, width):
    d.line([p0, p1], fill=fill, width=width)
    r = width / 2
    for x, y in (p0, p1):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _make_icon_image(color):
    # Squircle badge (rounded square) matching the app icon's silhouette,
    # with the same mic glyph inside it (redrawn here, not loaded from
    # assets/generate_icon.py's output -- keeps the tray code-drawn, no
    # --add-data). State is conveyed by the badge's fill color
    # (grey/blue/red); the mic glyph is always white. Drawn at 4x and
    # downsampled for crisp anti-aliased edges at the tiny tray size.
    scale = 4
    size = 64 * scale
    margin = 6 * scale
    cx = cy = size / 2

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=15 * scale, fill=color,
    )

    white = (255, 255, 255, 255)
    badge = size - 2 * margin
    glyph_h = badge * 0.80
    glyph_top = cy - glyph_h / 2

    head_w = glyph_h * 0.398
    head_h = glyph_h * 0.627
    d.rounded_rectangle(
        (cx - head_w / 2, glyph_top, cx + head_w / 2, glyph_top + head_h),
        radius=head_w / 2, fill=white,
    )
    arc_cy = glyph_top + glyph_h * 0.524
    arc_r = glyph_h * 0.325
    stroke = max(2, round(glyph_h * 0.075))
    d.arc(
        (cx - arc_r, arc_cy - arc_r, cx + arc_r, arc_cy + arc_r),
        start=25, end=155, fill=white, width=stroke,
    )
    stand_top = glyph_top + glyph_h * 0.831
    stand_bottom = glyph_top + glyph_h
    _round_line(d, (cx, stand_top), (cx, stand_bottom), white, stroke)
    base_half = glyph_h * 0.199
    _round_line(d, (cx - base_half, stand_bottom), (cx + base_half, stand_bottom), white, stroke)

    return img.resize((64, 64), Image.LANCZOS)


class TrayApp:
    def __init__(self, on_quit, on_settings=None, hotkey_label="Right Ctrl"):
        self._hotkey_label = hotkey_label
        self._idle_image = _make_icon_image((70, 130, 180, 255))  # steel blue
        self._recording_image = _make_icon_image((200, 40, 40, 255))  # red
        self._loading_image = _make_icon_image((150, 150, 150, 255))  # grey

        self._on_quit = on_quit
        self._on_settings = on_settings
        menu_items = []
        if on_settings is not None:
            menu_items.append(
                pystray.MenuItem("Settings…", self._settings, default=True)
            )
        menu_items.append(pystray.MenuItem("Quit", self._quit))
        self.icon = pystray.Icon(
            "sumit_speak",
            self._loading_image,
            "Talkative (loading model...)",
            menu=pystray.Menu(*menu_items),
        )

    def _settings(self):
        if self._on_settings is not None:
            self._on_settings()

    def _quit(self):
        self._on_quit()
        self.icon.stop()

    def set_hotkey_label(self, label):
        self._hotkey_label = label

    def set_idle(self):
        self.icon.icon = self._idle_image
        self.icon.title = f"Talkative (hold {self._hotkey_label} to dictate)"

    def set_loading(self, note="loading model..."):
        self.icon.icon = self._loading_image
        self.icon.title = f"Talkative ({note})"

    def set_recording(self):
        self.icon.icon = self._recording_image
        self.icon.title = "Talkative (listening...)"

    def notify(self, message, title="Talkative"):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def run_detached(self):
        self.icon.run_detached()

    def stop(self):
        self.icon.stop()
