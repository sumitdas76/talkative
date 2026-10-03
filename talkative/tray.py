import ctypes
import logging
import threading
import time

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
        self._mode_label = ""
        self._lock = threading.RLock()
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
            "talkative",
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

    def set_hotkey_label(self, label, dev_label="", verb="hold"):
        """verb: "hold" or "tap", matching config.HOTKEY_MODE."""
        self._hotkey_label = label
        self._dev_hotkey_label = dev_label
        self._hotkey_verb = verb

    def set_mode_label(self, label):
        """label: "Cloud", "Local", or "" to omit it from the tooltip."""
        self._mode_label = label

    def _mode_prefix(self):
        return f"{self._mode_label} — " if self._mode_label else ""

    def _set(self, image, title):
        """Every icon/tooltip change goes through here. pystray isn't
        thread-safe and these are called from the hotkey listener, model
        loading, updater and Settings threads: two overlapping icon swaps
        can DestroyIcon one handle twice (pystray raises) or hand the
        shell a destroyed handle (blank icon). Errors are logged, never
        raised -- a raise here inside the hotkey listener's callback
        would stop the listener and dictation with it."""
        try:
            with self._lock:
                self.icon.icon = image
                self.icon.title = title
        except Exception:
            logging.getLogger(__name__).exception("tray icon update failed")

    def set_idle(self):
        dev = getattr(self, "_dev_hotkey_label", "")
        self._set(
            self._idle_image,
            f"Talkative ({self._mode_prefix()}{getattr(self, '_hotkey_verb', 'hold')} "
            f"{self._hotkey_label} to dictate"
            + (f", {dev} for code" if dev else "") + ")",
        )

    def set_loading(self, note="loading model..."):
        self._set(self._loading_image, f"Talkative ({self._mode_prefix()}{note})")

    def set_recording(self):
        self._set(self._recording_image, "Talkative (listening...)")

    def notify(self, message, title="Talkative"):
        try:
            with self._lock:
                self.icon.notify(message, title)
        except Exception:
            pass

    def run_detached(self):
        self.icon.run_detached()
        threading.Thread(target=self._keep_icon_alive, daemon=True).start()

    def _keep_icon_alive(self):
        """Put the icon back if Windows has lost it. A user saw dictation
        keep working with no tray icon (2026-10-03). pystray ignores
        Shell_NotifyIcon's result, so an add that fails is never retried:
        at login before the taskbar is ready, or when Explorer restarts
        and pystray's WM_TASKBARCREATED re-add fails. NIM_MODIFY fails
        exactly when our icon isn't in the tray, so it doubles as the
        check; NIM_ADD on an icon that is there fails harmlessly."""
        from pystray._util import win32

        time.sleep(5)
        while True:
            try:
                with self._lock:
                    icon = self.icon
                    hwnd = getattr(icon, "_hwnd", None)
                    if icon.visible and hwnd:
                        present = win32.Shell_NotifyIcon(win32.NIM_MODIFY, win32.NOTIFYICONDATAW(
                            cbSize=ctypes.sizeof(win32.NOTIFYICONDATAW),
                            hWnd=hwnd, hID=id(icon), uFlags=win32.NIF_TIP,
                            szTip=icon.title))
                        if not present:
                            logging.getLogger(__name__).warning("tray icon missing, re-adding")
                            icon._show()
            except Exception:
                logging.getLogger(__name__).exception("tray icon check failed")
            time.sleep(15)

    def stop(self):
        self.icon.stop()
