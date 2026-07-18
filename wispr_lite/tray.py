import ctypes
import threading

import pystray
from PIL import Image, ImageDraw

MB_ICONERROR = 0x10
MB_SYSTEMMODAL = 0x1000


def show_error_popup(message, title="Wispr Lite"):
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
    def __init__(self, on_quit):
        self._idle_image = _make_icon_image((70, 130, 180, 255))  # steel blue
        self._recording_image = _make_icon_image((200, 40, 40, 255))  # red
        self._loading_image = _make_icon_image((150, 150, 150, 255))  # grey

        self._on_quit = on_quit
        self.icon = pystray.Icon(
            "wispr_lite",
            self._loading_image,
            "Wispr Lite (loading model...)",
            menu=pystray.Menu(pystray.MenuItem("Quit", self._quit)),
        )

    def _quit(self):
        self._on_quit()
        self.icon.stop()

    def set_idle(self):
        self.icon.icon = self._idle_image
        self.icon.title = "Wispr Lite (hold Right Ctrl to dictate)"

    def set_recording(self):
        self.icon.icon = self._recording_image
        self.icon.title = "Wispr Lite (listening...)"

    def notify(self, message, title="Wispr Lite"):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def run_detached(self):
        self.icon.run_detached()

    def stop(self):
        self.icon.stop()
