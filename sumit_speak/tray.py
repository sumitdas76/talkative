import ctypes
import threading

import pystray
from PIL import Image, ImageDraw

MB_ICONERROR = 0x10
MB_SYSTEMMODAL = 0x1000


def show_error_popup(message, title="Sumit Speak"):
    """Show a blocking Windows message box on its own thread so it never
    freezes the hotkey listener or tray loop."""

    def _show():
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONERROR | MB_SYSTEMMODAL)

    threading.Thread(target=_show, daemon=True).start()


def _make_icon_image(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=color)
    return img


class TrayApp:
    def __init__(self, on_quit, on_settings=None):
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
            "Sumit Speak (loading model...)",
            menu=pystray.Menu(*menu_items),
        )

    def _settings(self):
        if self._on_settings is not None:
            self._on_settings()

    def _quit(self):
        self._on_quit()
        self.icon.stop()

    def set_idle(self):
        self.icon.icon = self._idle_image
        self.icon.title = "Sumit Speak (hold Right Ctrl to dictate)"

    def set_recording(self):
        self.icon.icon = self._recording_image
        self.icon.title = "Sumit Speak (listening...)"

    def notify(self, message, title="Sumit Speak"):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def run_detached(self):
        self.icon.run_detached()

    def stop(self):
        self.icon.stop()
