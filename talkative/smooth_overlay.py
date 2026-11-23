"""A small always-on-top window that shows a PIL RGBA image with true
per-pixel transparency (a Windows layered window fed by
UpdateLayeredWindow), so anti-aliased edges blend into whatever is behind.

Why (2026-11-23, user: the Pulse listening style looked "very
pixelated"): Tk's canvas draws circles without anti-aliasing, and the
listening line's window is see-through by a key color, which only allows
fully-on or fully-off pixels. A ring of radius 7-14 px came out as a
jagged octagon. pill.py draws Pulse with PIL (at 4x, scaled down) and
shows it through this window instead.

Built on the shared overlay thread (overlay_thread.py) like every other
Tk window here; all methods must be called on that thread. Never takes
focus (WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW). Any failure raises, and
pill.py then falls back to the canvas drawing.
"""

import ctypes
from ctypes import wintypes

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TRANSPARENT = 0x00000020   # clicks go through to the window below
_ULW_ALPHA = 2
_AC_SRC_ALPHA = 1
_DIB_RGB_COLORS = 0

_u = ctypes.windll.user32
_g = ctypes.windll.gdi32
_H = ctypes.c_void_p


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_u.GetDC.restype = _H
_u.GetDC.argtypes = [_H]
_u.ReleaseDC.argtypes = [_H, _H]
_u.GetParent.restype = _H
_u.GetParent.argtypes = [_H]
_u.GetWindowLongW.argtypes = [_H, ctypes.c_int]
_u.SetWindowLongW.argtypes = [_H, ctypes.c_int, ctypes.c_long]
_u.UpdateLayeredWindow.argtypes = [
    _H, _H, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE), _H,
    ctypes.POINTER(wintypes.POINT), wintypes.DWORD, ctypes.POINTER(_BLEND), wintypes.DWORD]
_u.UpdateLayeredWindow.restype = wintypes.BOOL
_g.CreateCompatibleDC.restype = _H
_g.CreateCompatibleDC.argtypes = [_H]
_g.CreateDIBSection.restype = _H
_g.CreateDIBSection.argtypes = [_H, ctypes.c_void_p, ctypes.c_uint,
                                ctypes.POINTER(ctypes.c_void_p), _H, wintypes.DWORD]
_g.SelectObject.restype = _H
_g.SelectObject.argtypes = [_H, _H]
_g.DeleteObject.argtypes = [_H]
_g.DeleteDC.argtypes = [_H]


class SmoothWindow:
    def __init__(self, parent, width, height):
        import tkinter as tk
        self.w, self.h = width, height
        self.x = self.y = 0
        self.top = tk.Toplevel(parent)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.geometry(f"{width}x{height}+0+0")
        self._hwnd = None
        self._visible = False
        # Styles (no-activate, layered, click-through) set now, while
        # hidden, so the first show can never take focus from the window
        # the user is dictating into.
        self._window()

    def _window(self):
        if self._hwnd is None:
            self.top.update_idletasks()
            own = self.top.winfo_id()
            self._hwnd = _u.GetParent(own) or own
            style = _u.GetWindowLongW(self._hwnd, _GWL_EXSTYLE)
            _u.SetWindowLongW(self._hwnd, _GWL_EXSTYLE,
                              style | _WS_EX_LAYERED | _WS_EX_NOACTIVATE
                              | _WS_EX_TOOLWINDOW | _WS_EX_TRANSPARENT)
        return self._hwnd

    def place(self, x, y):
        self.x, self.y = x, y
        self.top.geometry(f"{self.w}x{self.h}+{x}+{y}")

    def show(self, image):
        """Show (or keep showing) with this RGBA image."""
        if not self._visible:
            self.top.deiconify()
            self._visible = True
        self.update(image)

    def hide(self):
        if self._visible:
            self.top.withdraw()
            self._visible = False

    def update(self, image):
        """Put a PIL RGBA image of exactly width x height on screen."""
        hwnd = self._window()
        w, h = self.w, self.h
        # Premultiplied BGRA, top-down rows, as UpdateLayeredWindow wants.
        r, g, b, a = image.split()
        from PIL import Image, ImageChops
        r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
        data = Image.merge("RGBA", (b, g, r, a)).tobytes()

        screen = _u.GetDC(None)
        mem = _g.CreateCompatibleDC(screen)
        bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = _g.CreateDIBSection(screen, ctypes.byref(bih), _DIB_RGB_COLORS,
                                  ctypes.byref(bits), None, 0)
        try:
            if not bmp:
                raise OSError("CreateDIBSection failed")
            ctypes.memmove(bits, data, len(data))
            old = _g.SelectObject(mem, bmp)
            blend = _BLEND(0, 0, 255, _AC_SRC_ALPHA)
            ok = _u.UpdateLayeredWindow(
                hwnd, screen, ctypes.byref(wintypes.POINT(self.x, self.y)),
                ctypes.byref(wintypes.SIZE(w, h)), mem,
                ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), _ULW_ALPHA)
            _g.SelectObject(mem, old)
            if not ok:
                raise OSError(f"UpdateLayeredWindow failed ({ctypes.GetLastError()})")
        finally:
            if bmp:
                _g.DeleteObject(bmp)
            _g.DeleteDC(mem)
            _u.ReleaseDC(None, screen)
