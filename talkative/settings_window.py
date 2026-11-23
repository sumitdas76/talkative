"""
Settings window (tkinter), opened from the tray menu: a sidebar of
pages on the left, the chosen page on the right.

Reads current config values, writes settings.json via settings.save, then
re-applies with settings.load_into_config and notifies the app through the
on_applied callback. Built as a tk.Toplevel on the shared overlay thread
(see overlay_thread.py -- multiple independent tk.Tk() roots across
threads caused real crashes), not its own Tk instance; only that thread
touches tkinter objects. A second open request while the window exists is
ignored.
"""

import logging
import os
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pynput import keyboard
from PIL import Image, ImageDraw, ImageTk

from . import __version__, app_icon, audio_devices, config, dev_mode, error_toast, feedback, fix_learning, grammar_engine, groq_direct, history, languages, mic_warmup, model_manager, overlay_thread, packaging, palette, pill, secret_store, settings, try_it_now, updater
from .keynames import friendly as _friendly_key_name

log = logging.getLogger(__name__)

APP_NAME = "Talkative"

_open_lock = threading.Lock()
_is_open = False

_CHECKBOX_SIZE = 16  # on-screen box size; drawn at 4x and downscaled for crisp anti-aliasing

# A name of our own, not "Checkbutton.indicator" -- that name is already
# taken the moment the clam theme is activated (it's clam's own built-in
# element), so creating an element with that exact name always fails with
# "Duplicate element", even on the very first call in a fresh interpreter.
# Overriding a built-in glyph means a differently-named custom element
# plus redefining TCheckbutton's layout to reference it instead (done in
# _apply_theme, every call -- layout reassignment, unlike element
# creation, is idempotent and meant to be called repeatedly).
_CHECKBOX_ELEMENT = "SumitCheck.indicator"

# Module-level, not per-window: every Settings window now shares one
# persistent Tcl interpreter (overlay_thread.py), so a custom ttk element
# registered by one window's _apply_theme() is still registered the next
# time ANY window opens -- style.element_create errors on a duplicate
# name, it can't just be called again. The PhotoImage handles must
# likewise outlive any single _SettingsWindow instance (Tk drops a
# PhotoImage once nothing references it), so they're kept here and
# repainted in place via .paste() on every theme apply instead of being
# recreated.
_checkbox_images = None  # (unchecked_photo, checked_photo) once created


def _draw_checkbox_glyphs(field, border, accent, accent_fg):
    """Draw the checkbox indicator glyphs ourselves (same approach as the
    tray icons and app icon) instead of relying on the clam theme's
    built-in checkbutton bitmap, which renders as an X rather than a
    checkmark on this Tcl/Tk build and isn't something style.map colors
    can fix -- the glyph shape itself is baked into the theme resource.
    Returns (unchecked_image, checked_image) as plain PIL Images at final
    display size."""
    scale = 4
    size = _CHECKBOX_SIZE * scale
    radius = size // 5

    unchecked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(unchecked)
    d.rounded_rectangle(
        (scale, scale, size - scale, size - scale), radius=radius,
        fill=field, outline=border, width=scale,
    )

    checked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(checked)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=accent)
    d.line(
        [(size * 0.22, size * 0.52), (size * 0.42, size * 0.72), (size * 0.8, size * 0.26)],
        fill=accent_fg, width=scale * 2, joint="curve",
    )

    small = (_CHECKBOX_SIZE, _CHECKBOX_SIZE)
    return unchecked.resize(small, Image.LANCZOS), checked.resize(small, Image.LANCZOS)


def _apply_checkbox_glyphs(style, field, border, accent, accent_fg):
    global _checkbox_images
    unchecked_pil, checked_pil = _draw_checkbox_glyphs(field, border, accent, accent_fg)
    if _checkbox_images is None:
        unchecked_photo = ImageTk.PhotoImage(unchecked_pil)
        checked_photo = ImageTk.PhotoImage(checked_pil)
        _checkbox_images = (unchecked_photo, checked_photo)
        style.element_create(
            _CHECKBOX_ELEMENT, "image", unchecked_photo,
            ("selected", checked_photo),
        )
    else:
        unchecked_photo, checked_photo = _checkbox_images
        unchecked_photo.paste(unchecked_pil)
        checked_photo.paste(checked_pil)

    # Swap clam's built-in indicator sub-element for ours in the layout
    # tree; everything else (padding, focus ring, label) stays exactly as
    # clam defines it. Safe to call every time -- unlike element_create,
    # layout reassignment is meant to be repeatable.
    style.layout("TCheckbutton", [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            (_CHECKBOX_ELEMENT, {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"}),
            ]}),
        ]}),
    ])


# Toggle switches (2026-10-30, modern Settings): a second custom
# indicator, same trap and same fix as the checkbox above -- own element
# name, a layout that references it, created once per interpreter.
_SWITCH_SIZE = (36, 20)
_SWITCH_ELEMENT = "SumitSwitch.indicator"
_switch_images = None  # (off_photo, on_photo) once created


def _draw_switch_glyphs(line, accent, accent_fg):
    """Off: an outlined track with the knob on the left. On: an accent
    track with the knob on the right."""
    scale = 4
    w, h = _SWITCH_SIZE[0] * scale, _SWITCH_SIZE[1] * scale
    pad = scale  # room for the focus ring around the track
    knob = h - 2 * pad - 5 * scale

    off = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(off)
    d.rounded_rectangle((pad, pad, w - pad, h - pad), radius=(h - 2 * pad) // 2,
                        outline=line, width=round(1.5 * scale))
    x = pad + 5 * scale // 2
    d.ellipse((x, (h - knob) // 2, x + knob, (h + knob) // 2), fill=line)

    on = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(on)
    d.rounded_rectangle((pad, pad, w - pad, h - pad), radius=(h - 2 * pad) // 2, fill=accent)
    x = w - pad - 5 * scale // 2 - knob
    d.ellipse((x, (h - knob) // 2, x + knob, (h + knob) // 2), fill=accent_fg)

    return off.resize(_SWITCH_SIZE, Image.LANCZOS), on.resize(_SWITCH_SIZE, Image.LANCZOS)


def _apply_switch_glyphs(style, line, accent, accent_fg):
    global _switch_images
    off_pil, on_pil = _draw_switch_glyphs(line, accent, accent_fg)
    if _switch_images is None:
        off_photo, on_photo = ImageTk.PhotoImage(off_pil), ImageTk.PhotoImage(on_pil)
        _switch_images = (off_photo, on_photo)
        style.element_create(_SWITCH_ELEMENT, "image", off_photo, ("selected", on_photo))
    else:
        _switch_images[0].paste(off_pil)
        _switch_images[1].paste(on_pil)
    # Just the switch inside clam's focus ring; the setting's name is a
    # separate label to its left (see _setting_row).
    style.layout("Switch.TCheckbutton", [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                (_SWITCH_ELEMENT, {"sticky": ""}),
            ]}),
        ]}),
    ])


# Radio buttons (2026-11-23, user: "more prominent", a cleaner look):
# drawn like the checkbox, same create-once rule. Unselected: a clear ring
# that darkens on hover; selected: an accent disc with a white dot (as in
# Windows 11). The image is wider than the circle: the gap before the text.
_RADIO_SIZE = 18
_RADIO_IMAGE = (_RADIO_SIZE + 8, _RADIO_SIZE)
_RADIO_ELEMENT = "SumitRadio.indicator"
_radio_images = None  # photos once created, in _RADIO_STATES order
_RADIO_STATES = ("normal", "hover", "selected", "disabled", "disabled_selected")


def _draw_radio_glyphs(ring, ring_hover, fill, accent, accent_fg, faint):
    scale = 4
    w, h = _RADIO_IMAGE[0] * scale, _RADIO_IMAGE[1] * scale
    d0 = _RADIO_SIZE * scale
    pad = scale  # anti-aliased edge room
    box = (pad, pad, d0 - pad, d0 - pad)
    dot = d0 * 0.2
    c = d0 / 2
    inner = (c - dot, c - dot, c + dot, c + dot)
    width = round(1.6 * scale)
    out = []
    for state in _RADIO_STATES:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if state == "selected":
            d.ellipse(box, fill=accent)
            d.ellipse(inner, fill=accent_fg)
        elif state == "disabled_selected":
            d.ellipse(box, fill=faint)
            d.ellipse(inner, fill=fill)
        else:
            outline = {"normal": ring, "hover": ring_hover, "disabled": faint}[state]
            d.ellipse(box, fill=fill, outline=outline, width=width)
        out.append(img.resize(_RADIO_IMAGE, Image.LANCZOS))
    return out


def _apply_radio_glyphs(style, ring, ring_hover, fill, accent, accent_fg, faint):
    global _radio_images
    pils = _draw_radio_glyphs(ring, ring_hover, fill, accent, accent_fg, faint)
    if _radio_images is None:
        _radio_images = tuple(ImageTk.PhotoImage(i) for i in pils)
        normal, hover, sel, dis, dis_sel = _radio_images
        style.element_create(
            _RADIO_ELEMENT, "image", normal,
            ("disabled selected", dis_sel), ("disabled", dis),
            ("selected", sel), ("active", hover),
        )
    else:
        for photo, pil in zip(_radio_images, pils):
            photo.paste(pil)
    for name in ("TRadiobutton", "Card.TRadiobutton"):
        style.layout(name, [
            ("Radiobutton.padding", {"sticky": "nswe", "children": [
                (_RADIO_ELEMENT, {"side": "left", "sticky": ""}),
                ("Radiobutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Radiobutton.label", {"sticky": "nswe"}),
                ]}),
            ]}),
        ])


# Section cards (2026-11-23): each settings section is a rounded surface on
# the page's canvas color, instead of sections split by lines. The image
# element's border keeps the corners while it stretches.
_SECTION_ELEMENT = "SumitSection.background"
_SECTION_IMAGE = (40, 40)
_section_image = None


def _draw_section_glyph(canvas, card, edge):
    scale = 4
    w, h = _SECTION_IMAGE[0] * scale, _SECTION_IMAGE[1] * scale
    img = Image.new("RGBA", (w, h), canvas)
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, w - 1, h - 1), radius=10 * scale, fill=card, outline=edge, width=scale)
    return img.resize(_SECTION_IMAGE, Image.LANCZOS)


def _apply_section_glyph(style, canvas, card, edge):
    global _section_image
    pil = _draw_section_glyph(canvas, card, edge)
    if _section_image is None:
        _section_image = ImageTk.PhotoImage(pil)
        style.element_create(_SECTION_ELEMENT, "image", _section_image,
                             border=14, sticky="nsew")
    else:
        _section_image.paste(pil)
    style.layout("Section.TFrame", [(_SECTION_ELEMENT, {"sticky": "nswe"})])


def _window_picture(hwnd, x, y, w, h):
    """What the window `hwnd` shows inside the screen rectangle x, y, w, h
    (its client area), as a PIL image, via PrintWindow: works even where
    another window overlaps it. None on failure. Same logical pixels as Tk
    (the app isn't DPI-aware)."""
    import ctypes
    from ctypes import wintypes
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    H = ctypes.c_void_p
    for f in (u.GetWindowDC, g.CreateCompatibleDC, g.CreateCompatibleBitmap, g.SelectObject):
        f.restype = H
    u.GetWindowDC.argtypes = [H]
    g.CreateCompatibleDC.argtypes = [H]
    g.CreateCompatibleBitmap.argtypes = [H, ctypes.c_int, ctypes.c_int]
    g.SelectObject.argtypes = [H, H]
    u.PrintWindow.argtypes = [H, H, ctypes.c_uint]
    g.GetDIBits.argtypes = [H, H, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_uint]
    g.DeleteObject.argtypes = [H]
    g.DeleteDC.argtypes = [H]
    u.ReleaseDC.argtypes = [H, H]
    u.GetWindowRect.argtypes = [H, ctypes.c_void_p]

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("a", ctypes.c_long),
                    ("b", ctypes.c_long), ("c", wintypes.DWORD), ("d", wintypes.DWORD)]

    r = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    ww, wh = r.right - r.left, r.bottom - r.top
    if ww <= 0 or wh <= 0:
        return None
    hdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, ww, wh)
    try:
        g.SelectObject(mdc, bmp)
        if not u.PrintWindow(hwnd, mdc, 2):  # PW_RENDERFULLCONTENT
            return None
        buf = ctypes.create_string_buffer(ww * wh * 4)
        bih = BIH(ctypes.sizeof(BIH), ww, -wh, 1, 32, 0, 0, 0, 0, 0, 0)
        if not g.GetDIBits(mdc, bmp, 0, wh, buf, ctypes.byref(bih), 0):
            return None
        whole = Image.frombuffer("RGBA", (ww, wh), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(hwnd, hdc)
    left, top = x - r.left, y - r.top
    if left < 0 or top < 0 or left + w > ww or top + h > wh:
        return None
    return whole.crop((left, top, left + w, top + h))


def _fonts(root):
    """Windows 11's UI font (Segoe UI Variable) when it's installed, else
    Segoe UI (Windows 10)."""
    import tkinter.font as tkfont
    have = set(tkfont.families(root))

    def pick(*names):
        return next((n for n in names if n in have), names[-1])
    return {
        "text": pick("Segoe UI Variable Text", "Segoe UI"),
        "semi": pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold"),
        "display": pick("Segoe UI Variable Display Semib", "Segoe UI Semibold"),
    }


# Sidebar item backgrounds (2026-10-30, user: highlighted on hover "just
# like Claude", no lines): rounded rectangles stretched behind the label
# via the image element's border, plain for normal, a soft fill on hover
# or keyboard focus, a stronger one for the chosen page. Same create-once
# rule as the checkbox.
_NAV_ELEMENT = "SumitNav.background"
_NAV_IMAGE = (40, 32)
_nav_images = None  # (normal, hover, chosen) photos once created


def _draw_nav_glyphs(sidebar, hover, chosen, edge, bar):
    """The chosen page (2026-11-23, user: a better light-mode menu): a
    raised pill with a hairline edge and a short accent bar on its left,
    as in Windows 11 Settings. The bar sits inside the image's fixed
    border with only straight rows in the stretched middle, so it stays one
    piece when the pill stretches."""
    scale = 4
    w, h = _NAV_IMAGE[0] * scale, _NAV_IMAGE[1] * scale
    out = []
    for fill in (sidebar, hover, chosen):
        img = Image.new("RGBA", (w, h), sidebar)
        d = ImageDraw.Draw(img)
        if fill == chosen:
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=7 * scale, fill=fill,
                                outline=edge, width=scale)
            d.rounded_rectangle((3 * scale, 7 * scale, 6 * scale, h - 7 * scale),
                                radius=2 * scale, fill=bar)
        else:
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=7 * scale, fill=fill)
        out.append(img.resize(_NAV_IMAGE, Image.LANCZOS))
    return out


def _apply_nav_glyphs(style, sidebar, hover, chosen, edge, bar):
    global _nav_images
    pils = _draw_nav_glyphs(sidebar, hover, chosen, edge, bar)
    if _nav_images is None:
        _nav_images = tuple(ImageTk.PhotoImage(p) for p in pils)
        normal, over, picked = _nav_images
        style.element_create(
            _NAV_ELEMENT, "image", normal,
            ("selected", picked), ("active", over), ("focus", over),
            border=10, sticky="nsew",
        )
    else:
        for photo, pil in zip(_nav_images, pils):
            photo.paste(pil)
    style.layout("Nav.TLabel", [
        (_NAV_ELEMENT, {"sticky": "nswe", "children": [
            ("Label.padding", {"sticky": "nswe", "children": [
                ("Label.label", {"sticky": "w"}),
            ]}),
        ]}),
    ])


def _swatch(pal):
    """A small rounded chip: the accent, then the listening line's color."""
    scale, w, h = 4, 44, 14
    colors = [pal["accent"], pal["line"]]
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    part = w * scale / len(colors)
    for i, color in enumerate(colors):
        draw.rectangle((round(i * part), 0, round((i + 1) * part), h * scale), fill=color)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, w * scale - 1, h * scale - 1), radius=4 * scale, fill=255)
    img.putalpha(mask)
    return img.resize((w, h), Image.LANCZOS)


# The open window, for test scripts (tools/dev_mode_study/settings_layout.py).
_window = None

# Sidebar pages, top to bottom; About sits at the bottom of the sidebar.
# Feedback got its own page on 2026-10-30 (was the bottom of About).
# Audio and Output share one page since 2026-10-31 (user request), which
# also shows the devices in use. Dictation became History on 2026-11-23.
_PAGES = ["General", "Auto Text", "History", "Hotkeys", "Audio & Output",
          "Feedback", "About"]
# General > Processing: the Cloud column's text width (beside Local).
_CLOUD_COL_W = 300
# About's two columns: text width in each.
_ABOUT_WRAP = 440


def _on_closed():
    global _is_open, _window
    _window = None
    # Revert any unsaved preview mutations (e.g. the live theme preview
    # writes config.THEME before Save).
    settings.load_into_config()
    with _open_lock:
        _is_open = False


def open_settings(on_applied=None, model_controller=None):
    global _is_open
    with _open_lock:
        if _is_open:
            return
        _is_open = True

    overlay = overlay_thread.get()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        with _open_lock:
            _is_open = False
        return

    def _build():
        try:
            _SettingsWindow(on_applied, model_controller, overlay).build()
        except Exception:
            _on_closed()

    overlay.build(_build)


# Keys people type with. A hotkey made only of these would start (in tap
# mode: toggle) dictation in the middle of ordinary typing.
_TYPING_KEYS = {"space", "enter", "tab", "backspace"}


def _key_names(keys):
    return [getattr(k, "name", None) or getattr(k, "char", None) for k in keys]


def _hotkey_problem(normal, dev, rewrite=()):
    """Why these hotkeys can't be saved, or None. All are lists of key
    names (settings.json format); dev and rewrite may be [] (that key off)."""
    def typing_only(names):
        # Shift counts too: Shift + A is a capital A, and Shift alone goes
        # down with every capital letter.
        return names and all(
            n in _TYPING_KEYS or len(n) == 1 or n.startswith("shift") for n in names)

    if typing_only(normal) or typing_only(dev) or typing_only(rewrite):
        return ("A hotkey can't be only letters, numbers, Shift, Space or Enter -- "
                "dictation would start while you type. Pick a key like "
                "Right Ctrl, or a pair such as Ctrl + Alt. Your previous "
                "hotkeys are kept.")
    if dev and set(dev) == set(normal):
        return ("The dictation key and the code dictation key are the same, "
                "so every dictation would come out as code. Pick a different "
                "key for one of them. Your previous hotkeys are kept.")
    if rewrite and set(rewrite) in (set(normal), set(dev or ())):
        return ("The rewrite key is the same as another hotkey. Pick a "
                "different key for it. Your previous hotkeys are kept.")
    return None


def _hotkey_display(key):
    return _friendly_key_name(key)


def _card_points(parent, lines):
    """Short bullet lines for a model card: a frame of '•' + text rows,
    the text wrapping under itself rather than under the bullet."""
    box = ttk.Frame(parent, style="CardBody.TFrame")
    box.columnconfigure(1, weight=1)
    for row, line in enumerate(lines):
        ttk.Label(box, text="•", style="CardMuted.TLabel").grid(
            row=row, column=0, sticky="nw", padx=(0, 6))
        ttk.Label(box, text=line, style="CardMuted.TLabel", wraplength=185).grid(
            row=row, column=1, sticky="w")
    return box


class _SettingsWindow:
    def __init__(self, on_applied, model_controller, overlay):
        self.on_applied = on_applied
        self.model_controller = model_controller
        self.overlay = overlay
        self.pending_hotkey = None
        self.pending_dev_hotkey = None
        self.pending_rewrite_hotkey = None
        self._capturing = False

    def build(self):
        global _window
        self.root = tk.Toplevel(self.overlay.root)
        self.root.title(f"{APP_NAME} Settings")
        app_icon.set_window_icon(self.root)
        # No explicit .geometry() call -- same fix as onboarding.py's
        # Continue-button clipping (2026-09-19): a hardcoded WxH doesn't
        # account for actual content height, and content has grown since
        # 600x480 was chosen (confirmed live 2026-09-20: the General tab's
        # Processing box, added in 1.3.0, pushed the real required height
        # to 531px, squeezing the Save/Close bar down to ~1px on every
        # tab). Leaving geometry() uncalled keeps Tk's own pack-based
        # propagation active, so the window sizes to its actual content
        # and keeps re-sizing correctly as content changes later (e.g. the
        # Models tab's download progress bar appearing).
        self.root.minsize(720, 460)
        self._apply_theme()

        # Sidebar of pages on the left, the chosen page on the right
        # (2026-10-30: the top tab strip read as "Windows XP"). Every page
        # is gridded into the same cell and raised when chosen, so the
        # window sizes to the largest page and doesn't jump on a switch.
        self._build_sidebar()
        content = ttk.Frame(self.root, style="Canvas.TFrame")
        content.pack(side="left", fill="both", expand=True)
        self._content = content

        # The Save bar is packed first, at the bottom, so it always shows;
        # the page above it scrolls when the screen is too short for it
        # (2026-11-18, user report: on 1366x768 screens Save and Close
        # were off the bottom -- the General page alone needs ~850 px).
        bar = ttk.Frame(content, padding=(28, 8, 28, 12), style="Canvas.TFrame")
        bar.pack(side="bottom", fill="x")
        self.saved_label = ttk.Label(bar, text="", style="Canvas.TLabel")
        self.saved_label.pack(side="left")
        ttk.Button(bar, text="Close", command=self._close).pack(side="right")
        ttk.Button(bar, text="Save and apply", command=self._save,
                   style="Accent.TButton").pack(side="right", padx=8)

        viewport = ttk.Frame(content, style="Canvas.TFrame")
        viewport.pack(fill="both", expand=True)
        self._scroll_canvas = canvas = tk.Canvas(
            viewport, bg=self._bg, highlightthickness=0, bd=0, yscrollincrement=20,
            width=0, height=0)
        self._scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=self._scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        area = ttk.Frame(canvas, style="Canvas.TFrame")
        self._area = area
        self._area_item = canvas.create_window(0, 0, window=area, anchor="nw")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        builders = {
            "General": self._tab_general,
            "Auto Text": self._tab_dictionary,
            "History": self._tab_history,
            "Hotkeys": self._tab_hotkeys,
            "Audio & Output": self._tab_audio_output,
            "Feedback": lambda f: self._build_feedback_section(
                self._section(f, "Send feedback", first=True)),
            "About": self._tab_about,
        }
        self._pages = {}
        self._wide_columns = []  # (second column, gap above it when stacked)
        for name in _PAGES:
            page = ttk.Frame(area, padding=(28, 16, 28, 8), style="Canvas.TFrame")
            page.grid(row=0, column=0, sticky="nsew")
            ttk.Label(page, text=name, style="PageTitle.TLabel").pack(anchor="w", pady=(0, 10))
            body = ttk.Frame(page, style="Canvas.TFrame")
            body.pack(fill="both", expand=True)
            builders[name](body)
            self._pages[name] = page

        self._page_cap = None
        self.page = "General"
        canvas.bind("<Configure>", lambda e: self._fit_scroll())
        # Bound on the window itself, so it covers every widget in it
        # (each one's bindtags include its toplevel), not the shared root.
        self.root.bind("<MouseWheel>", self._on_wheel)
        self.root.bind("<FocusIn>", self._scroll_to_focus)
        self.select_page("General")
        self._place_on_screen()
        self._watch_page_size()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        _window = self

    # ---------------- fitting small screens ----------------

    def _place_on_screen(self):
        """Cap the page height to the screen's work area (minus the Save
        bar and the title bar), then put the window where all of it shows."""
        self.root.update_idletasks()
        self._fit_scroll()  # page sizes are known only now
        self.root.update_idletasks()
        try:
            x, y = self.root.winfo_pointerxy()
            left, top, right, bottom = error_toast._work_area(x, y)
        except Exception:
            left, top = 0, 0
            right, bottom = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        # The title bar and frame aren't part of Tk's size; ~40 px on
        # Windows 11 at any scale (Tk works in the same logical pixels).
        frame = 40
        # Everything in the right-hand column that isn't the page: the bar.
        fixed = self._content.winfo_reqheight() - int(self._scroll_canvas["height"])
        self._page_cap = max(200, bottom - top - frame - fixed)
        self._fit_scroll()
        self.root.update_idletasks()
        # Too wide for this screen (1366x768 at 125% is 1093 wide here):
        # General's side-by-side columns go back to one above the other.
        if self.root.winfo_reqwidth() + 16 > right - left:
            self._stack_general()
            self._fit_scroll()
            self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight() + frame
        x = left + max(0, (right - left - w) // 2)
        y = top + max(0, (bottom - top - h) // 2)
        self.root.geometry(f"+{x}+{y}")

    def _stack_general(self):
        """The side-by-side columns (General: Startup | Appearance, Cloud |
        Local; About: its two halves) one above the other, for screens too
        narrow for them."""
        for second, gap in self._wide_columns:
            second.grid(row=1, column=0, columnspan=2, sticky="new", pady=(gap, 0))
            # An emptied column in a "uniform" group would keep its width.
            second.master.columnconfigure(1, weight=0, uniform="")
        self._cloud_spacer.configure(width=1)

    def _fit_scroll(self):
        """Size the page area: as tall as the tallest page (so the window
        doesn't jump on a page switch) but no taller than the screen
        allows; a scrollbar shows only when the chosen page doesn't fit."""
        canvas = self._scroll_canvas
        page = self._pages[self.page]
        need = page.winfo_reqheight()
        # Only the chosen page is on screen (select_page), so the widest
        # page sets the width, as the tallest sets the height.
        want_w = max(p.winfo_reqwidth() for p in self._pages.values())
        want_h = max(p.winfo_reqheight() for p in self._pages.values())
        if self._page_cap:
            want_h = min(want_h, self._page_cap)
        if int(canvas["width"]) != want_w or int(canvas["height"]) != want_h:
            canvas.configure(width=want_w, height=want_h)
        ch = canvas.winfo_height() if canvas.winfo_ismapped() else want_h
        cw = canvas.winfo_width() if canvas.winfo_ismapped() else want_w
        h = max(ch, need)
        canvas.itemconfigure(self._area_item, width=cw, height=h)
        canvas.configure(scrollregion=(0, 0, cw, h))
        # Shown while the tallest page doesn't fit, even on a page that
        # does, so the window's width doesn't jump on a page switch.
        tallest = max(p.winfo_reqheight() for p in self._pages.values())
        if tallest > ch + 1:
            if not self._scrollbar.winfo_ismapped():
                self._scrollbar.pack(side="right", fill="y")
        elif self._scrollbar.winfo_ismapped():
            self._scrollbar.pack_forget()
            canvas.yview_moveto(0)

    def _watch_page_size(self):
        # Pages grow and shrink as they change (a download bar appears, a
        # card's text changes); there's no event for a requested-size
        # change, so check a few times a second while the window is open.
        try:
            if not self.root.winfo_exists():
                return
            self._fit_scroll()
            self.root.after(300, self._watch_page_size)
        except tk.TclError:
            pass

    def _on_wheel(self, event):
        # Tables, text boxes and dropdowns scroll themselves.
        if event.widget.winfo_class() in ("Treeview", "Text", "TCombobox", "Listbox"):
            return
        if not self._scrollbar.winfo_ismapped():
            return
        if self._pages[self.page].winfo_reqheight() <= self._scroll_canvas.winfo_height() + 1:
            return
        self._scroll_canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    def _scroll_to_focus(self, event):
        """Tab onto a control below the fold scrolls it into view."""
        w, canvas = event.widget, self._scroll_canvas
        if not self._scrollbar.winfo_ismapped() or not isinstance(w, tk.Misc):
            return
        if not str(w).startswith(str(self._area) + "."):
            return
        y = w.winfo_rooty() - self._area.winfo_rooty()
        top = canvas.canvasy(0)
        view = canvas.winfo_height()
        total = float(canvas.cget("scrollregion").split()[3])
        if y < top:
            canvas.yview_moveto(max(0, y - 12) / total)
        elif y + w.winfo_height() > top + view:
            canvas.yview_moveto((y + w.winfo_height() + 12 - view) / total)

    def _build_sidebar(self):
        # The side padding is the margin around each item's highlight
        # (2026-10-30, user: highlights "less wide").
        side = ttk.Frame(self.root, style="Sidebar.TFrame", padding=(16, 18, 16, 12))
        side.pack(side="left", fill="y")
        ttk.Label(side, text=APP_NAME, style="SidebarTitle.TLabel").pack(
            anchor="w", padx=(12, 32))
        ttk.Label(side, text="Settings", style="SidebarMuted.TLabel").pack(
            anchor="w", padx=12, pady=(0, 16))
        self._nav = {}
        for name in _PAGES:
            label = ttk.Label(side, text=name, style="Nav.TLabel", takefocus=True)
            label.pack(side="bottom" if name == "About" else "top", fill="x", pady=1)
            pick = lambda e, n=name: self.select_page(n)
            label.bind("<Button-1>", pick)
            label.bind("<Return>", pick)
            label.bind("<space>", pick)
            # Up/Down move through the pages, as in Windows' own Settings.
            label.bind("<Up>", lambda e, n=name: self._nav_step(n, -1))
            label.bind("<Down>", lambda e, n=name: self._nav_step(n, 1))
            for event, state in (("<Enter>", "active"), ("<Leave>", "!active"),
                                 ("<FocusIn>", "focus"), ("<FocusOut>", "!focus")):
                label.bind(event, lambda e, l=label, s=state: l.state([s]))
            self._nav[name] = label

    def _nav_step(self, name, step):
        i = min(max(_PAGES.index(name) + step, 0), len(_PAGES) - 1)
        self.select_page(_PAGES[i])
        self._nav[_PAGES[i]].focus_set()
        return "break"

    def select_page(self, name):
        # Only the chosen page is gridded (was: all seven stacked in one
        # cell and the chosen one raised). Hidden pages stacked underneath
        # were restyled and repainted too, so a Light/Dark switch took ~0.9 s
        # and the window changed color piece by piece (user, 2026-11-23).
        for n, page in self._pages.items():
            if n != name:
                page.grid_remove()
        self._pages[name].grid()
        for n, label in self._nav.items():
            label.state(["selected" if n == name else "!selected"])
        self.page = name
        self._scroll_canvas.yview_moveto(0)
        self._fit_scroll()

    def _section(self, parent, title, first=False, grow=False):
        """A page section: a rounded card on the page (2026-11-23; was a
        divider line and a heading), its heading, and the frame its
        settings go in. `grow`: fill the parent's height (side-by-side
        cards line up)."""
        card = ttk.Frame(parent, style="Section.TFrame", padding=(18, 10, 18, 12))
        card.pack(fill="both" if grow else "x", expand=grow, pady=(0 if first else 10, 0))
        ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        body = ttk.Frame(card)
        body.pack(fill="x")
        return body

    def _setting_row(self, parent, title, desc=None, wrap=None):
        """A row with the setting's name (and a muted line under it) on
        the left; the caller grids its control at column 1, on the right."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        row.columnconfigure(0, weight=1)
        text = ttk.Frame(row)
        text.grid(row=0, column=0, sticky="w")
        ttk.Label(text, text=title).pack(anchor="w")
        if desc:
            ttk.Label(text, text=desc, style="Muted.TLabel",
                      wraplength=wrap or 0, justify="left").pack(anchor="w")
        return row

    def _close(self):
        self.root.destroy()
        _on_closed()

    # ---------------- theme ----------------

    def _effective_theme(self):
        if config.THEME in ("light", "dark"):
            return config.THEME
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if light else "dark"
        except Exception:
            return "light"

    def _apply_theme(self):
        # clam in both modes: the native vista theme draws tabs itself and
        # ignores color styling, and the active tab must stand out.
        style = ttk.Style(self.root)
        if style.theme_use() != "clam":
            style.theme_use("clam")
        # Colors from palette.py (2026-10-26, user request: "more
        # colorful", then "not the generic AI look").
        pal = palette.get()
        m = pal["dark" if self._effective_theme() == "dark" else "light"]
        bg, fg, field, raised = m["bg"], m["fg"], m["field"], m["raised"]
        border, hover, title = m["border"], m["hover"], m["title"]
        accent, accent_fg, accent_hover = pal["accent"], pal["accent_fg"], pal["accent_hover"]

        muted = m["muted"]
        # The sidebar sits between the page and the raised color; the
        # chosen page's item is raised, hover halfway to it.
        dark = self._effective_theme() == "dark"
        if dark:
            sidebar = pill._mix(bg, raised, 0.5)
            nav_hover = pill._mix(sidebar, raised, 0.45)
            nav_chosen = pill._mix(raised, hover, 0.5)
        else:
            # Light (2026-11-23): a quiet sidebar close to the page, the
            # chosen page a white pill, hover halfway between.
            sidebar = pill._mix(bg, raised, 0.28)
            nav_chosen = field
            nav_hover = pill._mix(sidebar, raised, 0.35)

        # Cards on a canvas (2026-11-23): the page is `bg`, each section
        # a `card` surface (the theme's field color) with a hairline edge;
        # boxes inside a card (model cards, examples) are `inset`.
        canvas, card = bg, field
        inset = pill._mix(field, raised, 0.45)
        edge = pill._mix(card, border, 0.45)
        fonts = _fonts(self.root)
        text_font, semi = fonts["text"], fonts["semi"]

        self.root.configure(bg=canvas)
        style.configure(".", background=card, foreground=fg,
                        fieldbackground=field, bordercolor=border,
                        lightcolor=card, darkcolor=card, font=(text_font, 10))
        style.configure("Canvas.TFrame", background=canvas)
        style.configure("Canvas.TLabel", background=canvas)
        _apply_section_glyph(style, canvas, card, edge)
        style.configure("Sidebar.TFrame", background=sidebar)
        style.configure("SidebarTitle.TLabel", background=sidebar, foreground=fg,
                        font=(fonts["display"], 14))
        style.configure("SidebarMuted.TLabel", background=sidebar, foreground=muted)
        style.configure("Nav.TLabel", foreground=muted, padding=(16, 7))
        style.map("Nav.TLabel", foreground=[("selected", fg), ("active", fg), ("focus", fg)],
                  font=[("selected", (semi, 10))])
        _apply_nav_glyphs(style, sidebar, nav_hover, nav_chosen,
                          edge=pill._mix(nav_chosen, border, 0.5),
                          bar=title if dark else accent)
        style.configure("PageTitle.TLabel", background=canvas,
                        font=(fonts["display"], 20))
        style.configure("Section.TLabel", foreground=title, font=(semi, 11))
        style.configure("Sub.TLabel", font=(semi, 10))
        style.configure("TSeparator", background=edge)
        # Boxes inside a section (the model cards, the dictation example):
        # a slightly tinted panel with a hairline edge.
        style.configure("Card.TFrame", background=inset, bordercolor=edge,
                        lightcolor=edge, darkcolor=edge, relief="solid", borderwidth=1)
        style.configure("CardBody.TFrame", background=inset)
        style.configure("Card.TLabel", background=inset)
        style.configure("CardTitle.TLabel", background=inset, font=(semi, 10))
        style.configure("CardMuted.TLabel", background=inset, foreground=muted)
        # A switch inside a card (Optimize Narration): the layout comes from
        # Switch.TCheckbutton, only the background differs.
        style.configure("Card.Switch.TCheckbutton", background=inset)
        style.map("Card.Switch.TCheckbutton", background=[("active", inset)])
        # The voice model choice in each card (Fast / Accurate).
        style.configure("Card.TRadiobutton", background=inset, font=(semi, 10))
        style.map("Card.TRadiobutton", background=[("active", inset)],
                  foreground=[("disabled", muted)])
        # Flat buttons: clam's light/dark edge colors set to the face
        # color remove its bevel.
        style.configure("TButton", background=raised, lightcolor=raised, darkcolor=raised,
                        bordercolor=border, padding=(16, 5))
        style.map(
            "TButton",
            background=[("disabled", raised), ("active", hover)],
            lightcolor=[("active", hover)], darkcolor=[("active", hover)],
            foreground=[("disabled", border)],
        )
        # The main action ("Save and apply") in the accent color.
        style.configure("Accent.TButton", background=accent, foreground=accent_fg,
                        bordercolor=accent, lightcolor=accent, darkcolor=accent,
                        font=(semi, 10))
        style.map(
            "Accent.TButton",
            background=[("disabled", raised), ("active", accent_hover)],
            lightcolor=[("active", accent_hover)], darkcolor=[("active", accent_hover)],
            foreground=[("disabled", border)],
        )
        # Section titles ("Dictation style", "Feedback"...) in color.
        style.configure("TLabelframe", background=card, bordercolor=border)
        style.configure("TLabelframe.Label", background=card, foreground=title,
                        font=(semi, 10))
        # Radiobutton/checkbutton row background was never mapped for the
        # "active" (hover) state, so clam's built-in light default painted
        # every row white on hover regardless of theme.
        style.configure("TCheckbutton", background=card, foreground=fg)
        style.configure("TRadiobutton", background=card, foreground=fg, padding=(0, 1))
        style.map(
            "TCheckbutton",
            background=[("active", card)],
            foreground=[("disabled", border)],
        )
        _apply_checkbox_glyphs(style, field, border, accent, accent_fg)
        _apply_switch_glyphs(style, muted, accent, accent_fg)
        style.map(
            "TRadiobutton",
            background=[("active", card)],
            foreground=[("disabled", border)],
        )
        # Our own radio glyph (see _draw_radio_glyphs). In dark mode the
        # accent is dark, so the selected disc uses the heading color with
        # the page color as its dot, which stays clear on both themes.
        dark = self._effective_theme() == "dark"
        _apply_radio_glyphs(
            style, ring=pill._mix(border, fg, 0.35), ring_hover=fg, fill=field,
            accent=title if dark else accent, accent_fg=canvas if dark else accent_fg,
            faint=pill._mix(card, border, 0.6))
        # Flat tables: taller rows for 10pt text, headings without bevels.
        style.configure("Treeview", background=field, foreground=fg,
                        fieldbackground=field, rowheight=26, bordercolor=border,
                        lightcolor=field, darkcolor=field)
        style.configure("Treeview.Heading", background=raised, foreground=fg,
                        lightcolor=raised, darkcolor=raised, bordercolor=border,
                        padding=(8, 4), font=(semi, 10))
        style.map("Treeview.Heading", background=[("active", hover)],
                  lightcolor=[("active", hover)], darkcolor=[("active", hover)])
        style.configure("TCombobox", lightcolor=field, darkcolor=field, padding=(6, 3),
                        arrowcolor=fg)
        style.configure("TEntry", lightcolor=field, darkcolor=field, padding=(6, 3))
        style.map(
            "Treeview",
            background=[("selected", accent)],
            foreground=[("selected", accent_fg)],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", field), ("disabled", raised)],
            foreground=[("readonly", fg), ("disabled", border)],
            background=[("active", hover), ("readonly", field)],
            arrowcolor=[("disabled", border)],
        )
        # The dropdown list popup is a plain Tk Listbox, not a ttk widget --
        # styled via the option database, not style.configure. Left
        # unmapped it stays white-on-black in dark mode.
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", fg)
        self.root.option_add("*TCombobox*Listbox.selectBackground", accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", accent_fg)
        style.map(
            "TEntry",
            fieldbackground=[("disabled", raised), ("readonly", field)],
            foreground=[("disabled", border)],
            bordercolor=[("focus", accent)],
        )
        style.configure("TProgressbar", background=accent, troughcolor=field,
                        bordercolor=border, lightcolor=accent, darkcolor=accent)
        self._accent, self._accent_fg = accent, accent_fg
        # Text in the accent color was unreadable on dark backgrounds;
        # links and code samples use the heading color (checked by D38).
        self._link = title
        self._bg, self._fg, self._field = bg, fg, field
        self._border = border
        # Secondary text that must stay readable on this theme's background
        # (plain "grey" is faint on dark and nearly invisible on light).
        self._muted = m["muted"]
        # Hint text everywhere in Settings uses this style (was a fixed
        # "grey"), so it is readable on both themes and follows a live
        # Light/Dark switch.
        style.configure("Muted.TLabel", foreground=self._muted)
        # feedback_text is a raw tk.Text (not ttk), so it needs its colors
        # reapplied by hand on every theme switch, not just at creation.
        style.configure("Vertical.TScrollbar", background=border, troughcolor=canvas,
                        bordercolor=canvas, lightcolor=border, darkcolor=border,
                        arrowcolor=muted)
        style.map("Vertical.TScrollbar", background=[("active", hover)])
        if hasattr(self, "_scroll_canvas"):
            self._scroll_canvas.configure(bg=bg)
        if hasattr(self, "feedback_text"):
            self.feedback_text.configure(
                bg=field, fg=fg, insertbackground=fg,
                selectbackground=accent, selectforeground=accent_fg,
                highlightbackground=border, highlightcolor=title,
            )

    # ---------------- pages ----------------

    def _tab_general(self, f):
        self.var_autostart = tk.BooleanVar(value=config.START_WITH_WINDOWS)
        self.var_theme = tk.StringVar(value=config.THEME)
        # Wide rather than tall (2026-11-23, user request: 1366x768
        # screens): Startup beside Appearance, Cloud beside Local, so the
        # own-key block opens into the space next to the model cards
        # instead of making the page taller.
        top = ttk.Frame(f, style="Canvas.TFrame")
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        start_col = ttk.Frame(top, style="Canvas.TFrame")
        start_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        look_col = ttk.Frame(top, style="Canvas.TFrame")
        look_col.grid(row=0, column=1, sticky="nsew")
        start = self._section(start_col, "Startup", first=True, grow=True)
        row = self._setting_row(start, "Start with Windows",
                                f"Open {APP_NAME} when you sign in to Windows.")
        ttk.Checkbutton(row, variable=self.var_autostart,
                        style="Switch.TCheckbutton").grid(row=0, column=1, sticky="e",
                                                          padx=(24, 0))

        look = self._section(look_col, "Appearance", first=True, grow=True)
        row = self._setting_row(look, "Theme")
        modes = ttk.Frame(row)
        modes.grid(row=0, column=1, sticky="e")
        for label, value in [("Light", "light"), ("Dark", "dark"),
                             ("Follow Windows setting", "system")]:
            ttk.Radiobutton(
                modes, text=label, variable=self.var_theme, value=value,
                command=self._theme_changed,
            ).pack(side="left", padx=(16, 0))
        # Color schemes (2026-10-26: the user chose to let people pick),
        # each shown with a swatch of its accent and pill colors.
        self.var_scheme = tk.StringVar(value=config.COLOR_SCHEME)
        row = self._setting_row(look, "Color scheme")
        schemes = ttk.Frame(row)
        schemes.grid(row=0, column=1, sticky="e")
        self._swatches = []
        for name, pal in palette.PALETTES.items():
            swatch = ImageTk.PhotoImage(_swatch(pal))
            self._swatches.append(swatch)
            ttk.Radiobutton(
                schemes, text=pal["label"], image=swatch, compound="left",
                variable=self.var_scheme, value=name, command=self._theme_changed,
            ).pack(side="left", padx=(16, 0))

        # Cloud and Local as two parts, the local models under Local
        # (2026-10-27, user request: the Models tab folded in here).
        proc = self._section(f, "Processing")
        cols = ttk.Frame(proc)
        cols.pack(fill="x")
        cols.columnconfigure(1, weight=1)
        cloud_col = ttk.Frame(cols, width=_CLOUD_COL_W)
        cloud_col.grid(row=0, column=0, sticky="nw", padx=(0, 32))
        local_col = ttk.Frame(cols)
        local_col.grid(row=0, column=1, sticky="new")
        # Fixed width, so opening the key block doesn't widen the window.
        self._cloud_spacer = ttk.Frame(cloud_col, width=_CLOUD_COL_W, height=1)
        self._cloud_spacer.pack(side="bottom")
        self._wide_columns += [(look_col, 10), (local_col, 14)]
        ttk.Label(cloud_col, text="Cloud", style="Sub.TLabel").pack(anchor="w")
        cloud_box = ttk.Frame(cloud_col, padding=(4, 2, 0, 0))
        cloud_box.pack(fill="x")
        ttk.Label(local_col, text="Local", style="Sub.TLabel").pack(anchor="w")
        local_box = ttk.Frame(local_col, padding=(4, 2, 0, 0))
        local_box.pack(fill="x")
        self.var_processing = tk.StringVar(value=config.PROCESSING_MODE)
        self.var_speech_service = tk.StringVar(value=config.SPEECH_SERVICE)
        # One choice across both sections (2026-10-27, user request: no
        # separate "Cloud" button): an accent under Cloud selects Cloud
        # with that speech service -- US English = Groq's Whisper, Indian
        # English = Azure en-IN via the Worker -- or Local's own button.
        # Since 2026-11-23 the accent is one entry of a language list
        # (languages.py): "Speak in" + the list; picking from the list picks
        # Cloud too. var_engine is now "cloud" or "local".
        self.var_engine = tk.StringVar(
            value="cloud" if config.PROCESSING_MODE == "cloud" else "local")
        lang_row = ttk.Frame(cloud_box)
        lang_row.pack(anchor="w", fill="x", pady=1)
        ttk.Radiobutton(
            lang_row, text="Speak in", variable=self.var_engine, value="cloud",
            command=self._engine_changed,
        ).pack(side="left")
        self.language_combo = ttk.Combobox(
            lang_row, values=[languages.LABELS[i] for i in languages.IDS],
            state="readonly", width=24)
        self.language_combo.set(languages.LABELS.get(
            config.SPEECH_SERVICE, languages.LABELS["us_english"]))
        self.language_combo.pack(side="left", padx=(6, 0))
        self.language_combo.bind("<<ComboboxSelected>>", self._language_picked)
        self._build_own_key(cloud_box)

        self.local_radio = ttk.Radiobutton(
            local_box, text="Fully offline. Nothing leaves this PC.",
            variable=self.var_engine, value="local",
            command=self._engine_changed,
        )
        self.local_radio.pack(anchor="w", pady=1)

        # No general "Download voice model" button here any more (2026-11-23,
        # user: it didn't say whether it was Fast or Accurate; it fetched
        # whichever was selected). The Fast and Accurate cards below each
        # have their own Download; this line only says which one Local
        # still needs.
        self._local_error = []
        self.local_status = ttk.Label(local_box, text="", style="Muted.TLabel",
                                      wraplength=640)
        self._render_local_download()
        models = ttk.Frame(local_box)
        models.pack(fill="x", pady=(6, 0))
        self._build_models(models)

    # ---------------- own Groq key (2026-11-22) ----------------

    def _build_own_key(self, parent):
        """Under the Cloud language: which Groq key Cloud uses. Talkative's
        shared key needs nothing; your own free key (groq_direct.py) gets a
        step-by-step guide and a box to paste it in (2026-11-23, user
        request: two clear choices instead of a folded link). Acts at once,
        like the grammar switch: no Save needed."""
        self._key_result = []   # (reason or None, blob) from the check thread
        wrap = _CLOUD_COL_W - 24
        self.var_key_choice = tk.StringVar(
            value="own" if groq_direct.active() else "shared")
        choices = ttk.Frame(parent, padding=(22, 4, 0, 0))
        choices.pack(anchor="w", fill="x")
        self.key_shared_radio = ttk.Radiobutton(
            choices, text="Talkative's shared key (ready to use)",
            variable=self.var_key_choice, value="shared", command=self._key_choice_changed)
        self.key_shared_radio.pack(anchor="w", pady=1)
        self.key_own_radio = ttk.Radiobutton(
            choices, text="My own free Groq key", variable=self.var_key_choice,
            value="own", command=self._key_choice_changed)
        self.key_own_radio.pack(anchor="w", pady=1)
        self.key_status = ttk.Label(choices, text="", wraplength=wrap, justify="left")
        self.key_status.pack(anchor="w", side="bottom", pady=(4, 0))

        self.key_box = ttk.Frame(choices, padding=(22, 2, 0, 0))
        ttk.Label(
            self.key_box, wraplength=wrap - 22, justify="left", style="Muted.TLabel",
            text="Your own key has its own daily limit, and your audio goes "
                 "straight to Groq. If it stops working, the shared key is used.",
        ).pack(anchor="w")
        # The guide: what to click on console.groq.com, step by step.
        self.key_guide = ttk.Frame(self.key_box)
        self.key_guide.columnconfigure(1, weight=1)
        steps = [
            None,  # 1: the link, below
            "Sign in with Google.",
            "Click Create API Key.",
            "Type a name, such as Talkative. You can leave the description empty.",
            "Create it, then copy the key. Groq shows it only once.",
            "Paste it below and click Check and use.",
        ]
        for i, step in enumerate(steps):
            ttk.Label(self.key_guide, text=f"{i + 1}.", style="Muted.TLabel").grid(
                row=i, column=0, sticky="nw", padx=(0, 6))
            if step is None:
                link = ttk.Label(self.key_guide, text="Open console.groq.com/keys",
                                 cursor="hand2", foreground=self._link, takefocus=True)
                for seq in ("<Button-1>", "<Return>", "<space>"):
                    link.bind(seq, lambda e: webbrowser.open("https://console.groq.com/keys"))
                link.grid(row=i, column=1, sticky="w")
            else:
                ttk.Label(self.key_guide, text=step, wraplength=wrap - 44,
                          justify="left").grid(row=i, column=1, sticky="w")
        self.key_card_note = ttk.Label(
            self.key_box, wraplength=wrap - 22, justify="left", style="Muted.TLabel",
            text="The free plan is plenty, so there's no need to add a credit card.")

        self.key_entry_row = ttk.Frame(self.key_box)
        ttk.Label(self.key_entry_row, text="Your key:").pack(anchor="w")
        self.var_groq_key = tk.StringVar()
        self.key_entry = ttk.Entry(self.key_entry_row, textvariable=self.var_groq_key,
                                   show="•", width=18)
        self.key_entry.pack(side="left", padx=(0, 6), pady=(2, 0))
        self.key_entry.bind("<Return>", lambda e: self._check_own_key())
        self.key_check_btn = ttk.Button(self.key_entry_row, text="Check and use",
                                        command=self._check_own_key)
        self.key_check_btn.pack(side="left")
        self.key_saved_row = ttk.Frame(self.key_box)
        self.key_left = ttk.Label(self.key_saved_row, text="", wraplength=wrap - 22,
                                  justify="left")
        self.key_left.pack(anchor="w")
        ttk.Button(self.key_saved_row, text="Remove key",
                   command=self._remove_own_key).pack(anchor="w", pady=(4, 0))
        self._render_own_key()

    def _key_choice_changed(self):
        # Acts at once. The saved key is kept when the shared key is
        # picked: people swap between the two to have enough for the day.
        own = self.var_key_choice.get() == "own"
        config.USE_OWN_GROQ_KEY = own
        settings.save({"use_own_groq_key": own})
        status = ""
        if groq_direct.saved():
            status = ("Your key is in use again." if own else
                      "Using the shared key. Your own key is kept: pick it "
                      "again to switch back.")
        self._render_own_key(status)
        self._fit_scroll()

    def _render_own_key(self, status=None):
        saved = groq_direct.saved()
        own = self.var_key_choice.get() == "own"
        if status is not None:
            self.key_status.config(text=status)
        if not own:
            self.key_box.pack_forget()
            return
        self.key_box.pack(anchor="w", fill="x", after=self.key_own_radio)
        if saved:
            # The guide is for getting a key; with one in use it's noise.
            self.key_guide.pack_forget()
            self.key_card_note.pack_forget()
            self.key_entry_row.pack_forget()
            left = groq_direct.left_today.get(groq_direct.STT_MODEL)
            text = "Using your key."
            if left is not None:
                text += f" About {left:,} transcriptions left today."
            if config.SPEECH_SERVICE == "indian_english":
                text += " Indian English still uses Talkative Cloud; cleanup uses your key."
            self.key_left.config(text=text)
            self.key_saved_row.pack(anchor="w", pady=(6, 0))
        else:
            self.key_saved_row.pack_forget()
            self.key_guide.pack(anchor="w", fill="x", pady=(6, 0))
            self.key_card_note.pack(anchor="w", pady=(6, 0))
            self.key_entry_row.pack(anchor="w", pady=(6, 0))

    def _check_own_key(self):
        candidate = self.var_groq_key.get().strip()
        if not candidate:
            self._render_own_key("Paste your key first.")
            return
        self.key_check_btn.state(["disabled"])
        self._render_own_key("Checking with Groq…")

        def work():
            reason = groq_direct.check_key(candidate)
            blob = None
            if reason is None:
                try:
                    blob = secret_store.protect(candidate)
                except Exception:
                    reason = "Couldn't store the key safely on this PC."
            self._key_result.append((reason, blob))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(150, self._poll_own_key)

    def _poll_own_key(self):
        if not self._key_result:
            self.root.after(150, self._poll_own_key)
            return
        reason, blob = self._key_result.pop()
        self.key_check_btn.state(["!disabled"])
        if reason:
            self._render_own_key(reason)
            return
        config.GROQ_KEY_DPAPI = blob
        config.USE_OWN_GROQ_KEY = True
        settings.save({"groq_key_dpapi": blob, "use_own_groq_key": True})
        self.var_groq_key.set("")
        self._render_own_key("Key works. Your dictations now use it.")

    def _remove_own_key(self):
        config.GROQ_KEY_DPAPI = ""
        settings.save({"groq_key_dpapi": ""})
        groq_direct.left_today.clear()
        self.var_key_choice.set("shared")
        self._render_own_key("Key removed. The shared key is used again.")
        self._fit_scroll()

    def _engine_changed(self):
        engine = self.var_engine.get()
        if engine == "local":
            self.var_processing.set("local")
        else:
            self.var_processing.set("cloud")
        self._render_local_download()

    def _language_picked(self, _event=None):
        label = self.language_combo.get()
        picked = next((i for i in languages.IDS if languages.LABELS[i] == label), None)
        if picked:
            self.var_speech_service.set(picked)
        self.language_combo.selection_clear()
        self.var_engine.set("cloud")
        self._engine_changed()

    def _local_need_text(self):
        """What Local still needs, naming the model; "" when the chosen
        voice model is downloaded (the cards then say "Downloaded")."""
        if model_manager.is_downloaded(config.MODEL_SIZE):
            return ""
        chosen = model_manager.MODELS.get(
            model_manager.tier_for_size(config.MODEL_SIZE) or "fast",
            model_manager.MODELS["fast"])["label"]
        others = [info["label"] for info in model_manager.MODELS.values()
                  if info["label"] != chosen and model_manager.is_downloaded(info["size"])]
        if others:
            return (f"The {chosen} voice model isn't downloaded. Download it below, "
                    f"or pick {others[0]}.")
        names = " or ".join(info["label"] for info in model_manager.MODELS.values())
        return f"Local needs a voice model. Download {names} below."

    def _render_local_download(self):
        text = self._local_need_text()
        if text:
            self.local_status.config(text=text)
            # Right under the Local radio, also when shown again later.
            self.local_status.pack(anchor="w", pady=(2, 0), after=self.local_radio)
        else:
            self.local_status.pack_forget()
        while self._local_error:
            messagebox.showerror(APP_NAME, self._local_error.pop(0), parent=self.root)

    def _theme_changed(self):
        config.THEME = self.var_theme.get()
        config.COLOR_SCHEME = self.var_scheme.get()
        # A cross-fade (2026-11-23, user: the switch "looks very jagged"):
        # a picture of the window as it was covers it while every control
        # restyles underneath, then fades out. Without a picture (it
        # couldn't be taken), the switch is applied as before.
        cover = self._cover_with_snapshot()
        self._apply_theme()
        if cover is not None:
            self.root.update_idletasks()
            self._fade_out(cover)

    def _cover_with_snapshot(self):
        """A borderless window over the Settings window's inside, showing
        what it looks like now; None if that couldn't be done."""
        try:
            self.root.update_idletasks()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            shot = _window_picture(int(self.root.wm_frame(), 16), x, y, w, h)
            if shot is None:
                return None
            cover = tk.Toplevel(self.root)
            cover.overrideredirect(True)
            cover.geometry(f"{w}x{h}+{x}+{y}")
            cover.attributes("-alpha", 1.0)
            cover._photo = ImageTk.PhotoImage(shot)  # kept while it shows
            tk.Label(cover, image=cover._photo, bd=0, highlightthickness=0).pack()
            cover.update()
            return cover
        except Exception:
            log.debug("theme cross-fade: no snapshot", exc_info=True)
            return None

    def _fade_out(self, cover, step=0):
        steps = 12  # ~200 ms at 16 ms a step
        try:
            if step >= steps or not cover.winfo_exists():
                cover.destroy()
                return
            t = (step + 1) / steps
            cover.attributes("-alpha", (1 - t) ** 2)  # fast at first, gentle at the end
            self.root.after(16, lambda: self._fade_out(cover, step + 1))
        except tk.TclError:
            pass

    def _tab_dictionary(self, f):
        words = self._section(f, "Your Auto Text", first=True)
        ttk.Label(
            words, wraplength=560, style="Muted.TLabel",
            text=f"When you say the word on the left, “{APP_NAME}” "
                 "types the text on the right.",
        ).pack(anchor="w")

        self.dict_tree = ttk.Treeview(
            words, columns=("spoken", "typed"), show="headings", height=7
        )
        self.dict_tree.heading("spoken", text="Spoken")
        self.dict_tree.heading("typed", text="Typed")
        self.dict_tree.column("spoken", width=180)
        self.dict_tree.column("typed", width=360)
        self.dict_tree.pack(fill="both", expand=True, pady=8)
        for spoken, typed in config.DICTIONARY.items():
            self.dict_tree.insert("", "end", values=(spoken, typed))

        row = ttk.Frame(words)
        row.pack(fill="x")
        self.dict_spoken = ttk.Entry(row, width=18)
        self.dict_spoken.pack(side="left")
        ttk.Label(row, text=" → ").pack(side="left")
        self.dict_typed = ttk.Entry(row, width=32)
        self.dict_typed.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Add", command=self._dict_add).pack(side="left", padx=8)
        ttk.Button(row, text="Remove selected", command=self._dict_remove).pack(side="left")

        # Pairs fix_learning.py noticed the user correcting. Add puts one in
        # the table above (saved with Save, like a typed entry).
        box = self._section(f, "Suggested from your corrections")
        self.fix_empty = ttk.Label(
            box, style="Muted.TLabel", wraplength=560,
            text="None yet. When you correct a name or term Talkative typed, "
                 "it's suggested here.",
        )
        self.fix_tree = ttk.Treeview(
            box, columns=("heard", "typed", "times"), show="headings", height=3
        )
        self.fix_tree.heading("heard", text="Typed as")
        self.fix_tree.heading("typed", text="You corrected it to")
        self.fix_tree.heading("times", text="Times")
        self.fix_tree.column("heard", width=190)
        self.fix_tree.column("typed", width=270)
        self.fix_tree.column("times", width=60, anchor="center")
        self.fix_buttons = ttk.Frame(box)
        ttk.Button(self.fix_buttons, text="Add to Auto Text",
                   command=self._fix_add).pack(side="left")
        ttk.Button(self.fix_buttons, text="Dismiss",
                   command=self._fix_dismiss).pack(side="left", padx=8)
        self._fix_render()

    def _dict_add(self):
        spoken = self.dict_spoken.get().strip()
        typed = self.dict_typed.get().strip()
        if not spoken or not typed:
            return
        self.dict_tree.insert("", "end", values=(spoken, typed))
        self.dict_spoken.delete(0, "end")
        self.dict_typed.delete(0, "end")

    def _dict_remove(self):
        for item in self.dict_tree.selection():
            self.dict_tree.delete(item)

    def _fix_render(self):
        self.fix_tree.delete(*self.fix_tree.get_children())
        items = fix_learning.pending()
        for s in items:
            self.fix_tree.insert("", "end", values=(s["heard"], s["typed"], s.get("count", 1)))
        if items:
            self.fix_empty.pack_forget()
            self.fix_tree.pack(fill="x")
            self.fix_buttons.pack(anchor="w", pady=(6, 0))
        else:
            self.fix_tree.pack_forget()
            self.fix_buttons.pack_forget()
            self.fix_empty.pack(anchor="w")

    def _fix_selected(self):
        return [self.fix_tree.item(i, "values")[:2] for i in self.fix_tree.selection()]

    def _fix_add(self):
        picked = self._fix_selected()
        if not picked:
            return
        for heard, typed in picked:
            self.dict_tree.insert("", "end", values=(heard, typed))
        # Saved now, not with the window's Save: the suggestion is gone
        # from its list, so closing without saving would lose it.
        config.DICTIONARY = dict(config.DICTIONARY, **dict(picked))
        settings.save({"dictionary": config.DICTIONARY})
        for heard, typed in picked:
            fix_learning.remove(heard, typed)
        self._fix_render()

    def _fix_dismiss(self):
        for heard, typed in self._fix_selected():
            fix_learning.remove(heard, typed, dismiss=True)
        self._fix_render()

    def _tab_history(self, f):
        # Was the "Dictation" page until 2026-11-23: its Dictation style
        # choice (Cleaned up / As spoken) was removed from Settings at the
        # user's request; a saved cleanup_mode still applies.
        history_box = self._section(f, "History", first=True)
        self.var_history = tk.BooleanVar(value=config.ENABLE_HISTORY)
        row = self._setting_row(history_box, "Keep a history of what I've dictated",
                                "Saved only on this device. Nothing is sent anywhere.")
        ttk.Checkbutton(row, variable=self.var_history,
                        style="Switch.TCheckbutton").grid(row=0, column=1, sticky="e")
        buttons = ttk.Frame(history_box)
        buttons.pack(anchor="w", pady=(8, 0))
        ttk.Button(
            buttons, text="View history…", command=self._open_history_viewer,
        ).pack(side="left")
        self.history_delete_btn = ttk.Button(
            buttons, text="Delete history", command=self._history_delete)
        self.history_delete_btn.pack(side="left", padx=(8, 0))
        self.history_status = ttk.Label(history_box, text="", style="Muted.TLabel")
        self.history_status.pack(anchor="w", pady=(6, 0))
        self._history_refresh()

    def _history_refresh(self):
        """Delete is only offered when something is saved; the line below
        the buttons says how much (history keeps the last
        history.MAX_ENTRIES dictations)."""
        n = len(history.load())
        self.history_delete_btn.state(["!disabled"] if n else ["disabled"])
        self.history_status.config(
            text=(f"{n} saved dictation{'s' if n != 1 else ''}." if n
                  else "Nothing saved."))

    def _history_delete(self):
        n = len(history.load())
        if not n or not messagebox.askyesno(
            "Delete history",
            f"Delete all {n} saved dictation{'s' if n != 1 else ''} from this "
            "PC? This can't be undone.",
            parent=self.root,
        ):
            return
        history.clear()
        self._history_refresh()

    def _open_history_viewer(self):
        win = tk.Toplevel(self.root)
        win.title("Dictation history")
        app_icon.set_window_icon(win)
        win.geometry("480x360")
        win.transient(self.root)

        ttk.Label(
            win, padding=(12, 10, 12, 4),
            text="What you've dictated, most recent first.",
        ).pack(anchor="w")

        tree = ttk.Treeview(
            win, columns=("when", "text"), show="headings", height=10,
        )
        tree.heading("when", text="When")
        tree.heading("text", text="What you said")
        tree.column("when", width=130)
        tree.column("text", width=320)
        tree.pack(fill="both", expand=True, padx=12, pady=4)

        def refresh():
            tree.delete(*tree.get_children())
            entries = list(reversed(history.load()))
            if not entries:
                tree.insert("", "end", values=("", "No history yet."))
                return
            for entry in entries:
                tree.insert("", "end", values=(entry.get("time", ""), entry.get("text", "")))

        refresh()

        def clear():
            if messagebox.askyesno(
                "Clear history", "Delete all saved dictation history? "
                "This can't be undone."
            ):
                history.clear()
                refresh()
                self._history_refresh()

        bar = ttk.Frame(win, padding=(12, 4, 12, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Clear history", command=clear).pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")

    def _tab_hotkeys(self, f):
        # Two keys: which one you hold picks the kind of dictation, every
        # time -- no mode to switch or turn off. Each in its own section, so
        # the code example and help link clearly belong to the code key
        # (user request 2026-11-23: the two looked like one block).
        regular = self._section(f, "Regular typing", first=True)
        ttk.Label(regular, wraplength=560, style="Muted.TLabel",
                  text="For emails, messages and anything in sentences.").pack(
            anchor="w", pady=(0, 4))
        row = self._setting_row(regular, "Hotkey",
                                "Click it, then hold the key(s) you want.")
        self.hotkey_btn = ttk.Button(
            row, text=_hotkey_display(config.HOTKEY), command=self._capture_hotkey
        )
        self.hotkey_btn.grid(row=0, column=1, sticky="e")

        code = self._section(f, "Code typing")
        ttk.Label(code, wraplength=560, style="Muted.TLabel",
                  text="For SQL, terminal commands and code. “select star from users "
                       "where id equals five” types SELECT * FROM users WHERE id = 5.").pack(
            anchor="w", pady=(0, 4))
        row = self._setting_row(code, "Hotkey",
                                "Click it, then hold the key(s) you want.")
        self.dev_hotkey_btn = ttk.Button(
            row,
            text=_hotkey_display(config.DEV_HOTKEY) if config.DEV_HOTKEY else "Not set",
            command=lambda: self._capture_hotkey("dev"),
        )
        self.dev_hotkey_btn.grid(row=0, column=1, sticky="e")
        help_link = ttk.Label(code, text="How to say code…", cursor="hand2",
                              foreground=self._link, takefocus=True)
        help_link.pack(anchor="w", pady=(4, 0))
        for seq in ("<Button-1>", "<Return>", "<space>"):
            help_link.bind(seq, lambda e: self._show_dev_help())

        rewrite_box = self._section(f, "Rewrite selected text")
        ttk.Label(rewrite_box, wraplength=560, style="Muted.TLabel",
                  text="Select text, hold this key and say what to change, like "
                       "“make it shorter” or “turn this into a list”. Needs Cloud. "
                       "Press Ctrl+Z to get the original back.").pack(
            anchor="w", pady=(0, 4))
        row = self._setting_row(rewrite_box, "Hotkey",
                                "Click it, then hold the key(s) you want.")
        self.rewrite_hotkey_btn = ttk.Button(
            row,
            text=_hotkey_display(config.REWRITE_HOTKEY) if config.REWRITE_HOTKEY else "Not set",
            command=lambda: self._capture_hotkey("rewrite"),
        )
        self.rewrite_hotkey_btn.grid(row=0, column=1, sticky="e")

        # Applies to both hotkeys. Toggle is for long dictations where
        # holding a key the whole time gets tiring.
        style_box = self._section(f, "How the hotkeys work")
        self.var_hotkey_mode = tk.StringVar(
            value="toggle" if config.HOTKEY_MODE == "toggle" else "hold"
        )
        ttk.Radiobutton(
            style_box, variable=self.var_hotkey_mode, value="hold",
            text="Hold to talk: hold the key while speaking, release to insert",
        ).pack(anchor="w", pady=2)
        ttk.Radiobutton(
            style_box, variable=self.var_hotkey_mode, value="toggle",
            text="Tap to start, tap again to stop and insert",
        ).pack(anchor="w", pady=2)
        ttk.Label(
            style_box, wraplength=560, style="Muted.TLabel",
            text="Holding still works in tap mode. Listening stops by itself "
                 f"after {config.TOGGLE_MAX_SECONDS // 60} minutes. Press Esc "
                 "to cancel a dictation without typing it.",
        ).pack(anchor="w", pady=(6, 0))

    def _show_dev_help(self):
        """A table, not a text dump (2026-10-13): what to say in the
        normal font, what gets typed in a code font in the accent colour,
        notes in grey; sections in two columns so the window stays short."""
        win = tk.Toplevel(self.root)
        win.title("How to say code")
        app_icon.set_window_icon(win)
        win.transient(self.root)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=(18, 16, 18, 8))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="How to say code",
                  font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, style="Muted.TLabel",
                  text="Hold the code dictation key and say it like this.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))

        # One grid per side, so the "you get" column lines up across that
        # side's sections.
        cols = [ttk.Frame(body), ttk.Frame(body)]
        cols[0].grid(row=2, column=0, sticky="nw", padx=(0, 32))
        cols[1].grid(row=2, column=1, sticky="nw")
        split = 2   # Operators + Brackets left, Symbols + Names right
        rows_used = [0, 0]
        for i, (title, rows) in enumerate(dev_mode.HELP_SECTIONS):
            side = 0 if i < split else 1
            col, r = cols[side], rows_used[side]
            ttk.Label(col, text=title, font=("Segoe UI", 10, "bold")).grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(12 if r else 0, 4))
            r += 1
            for say, get, note in rows:
                ttk.Label(col, text=say).grid(row=r, column=0, sticky="nw", padx=(0, 16))
                cell = ttk.Frame(col)
                cell.grid(row=r, column=1, sticky="nw")
                ttk.Label(cell, text=get, font=("Consolas", 10),
                          foreground=self._link).pack(side="left")
                if note:
                    ttk.Label(cell, text="  " + note, style="Muted.TLabel",
                              font=("Segoe UI", 9)).pack(side="left")
                r += 1
            rows_used[side] = r

        notes = ttk.Frame(body)
        notes.grid(row=3, column=0, columnspan=2, sticky="we", pady=(14, 4))
        ttk.Label(notes, text="Good to know", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        for line in dev_mode.HELP_NOTES:
            ttk.Label(notes, text="•  " + line, wraplength=820,
                      justify="left").pack(anchor="w", pady=(3, 0))
        # Themed footer: the button straight on the Toplevel showed its
        # unthemed (white) background as a strip.
        footer = ttk.Frame(win, padding=(18, 4, 18, 14))
        footer.pack(fill="x")
        ttk.Button(footer, text="Close", command=win.destroy).pack(anchor="e")

    def _capture_hotkey(self, which="normal"):
        if self._capturing:
            return
        self._capturing = True
        btn = {"dev": self.dev_hotkey_btn,
               "rewrite": self.rewrite_hotkey_btn}.get(which, self.hotkey_btn)
        btn.config(text="Hold 1 or 2 keys…")

        pressed = []   # currently-held key names during this capture, max 2
        chosen = []    # the largest simultaneous combination seen so far

        def refresh():
            shown = " + ".join(_friendly_key_name(n) for n in pressed)
            text = shown if shown else "Hold 1 or 2 keys…"
            self.root.after(0, lambda: btn.config(text=text))

        def on_press(key):
            name = getattr(key, "name", None) or getattr(key, "char", None)
            if not name or name in pressed or len(pressed) >= 2:
                return
            pressed.append(name)
            if len(pressed) > len(chosen):
                chosen[:] = pressed
            refresh()

        def on_release(key):
            name = getattr(key, "name", None) or getattr(key, "char", None)
            if name in pressed:
                pressed.remove(name)
            if pressed or not chosen:
                return
            if which == "dev":
                self.pending_dev_hotkey = list(chosen)
            elif which == "rewrite":
                self.pending_rewrite_hotkey = list(chosen)
            else:
                self.pending_hotkey = list(chosen)
            self._capturing = False
            return False  # stop this capture listener

        keyboard.Listener(on_press=on_press, on_release=on_release).start()

    def _tab_audio_output(self, f):
        self._tab_audio(f)
        self._tab_output(f)
        self._refresh_devices()

    def _tab_audio(self, f):
        mic = self._section(f, "Microphone", first=True)
        # One entry per microphone (audio_devices.inputs, as in the tray
        # menu), not one per Windows audio system.
        self._audio_values = [None]
        names = ["System default"]
        for index, name in audio_devices.inputs():
            self._audio_values.append(index)
            names.append(name)
        if config.INPUT_DEVICE not in self._audio_values:
            # Saved from an older list (another audio system): keep it.
            self._audio_values.append(config.INPUT_DEVICE)
            names.append(mic_warmup.device_key(config.INPUT_DEVICE) or str(config.INPUT_DEVICE))

        self.audio_combo = ttk.Combobox(mic, values=names, state="readonly", width=52)
        self.audio_combo.current(self._audio_values.index(config.INPUT_DEVICE))
        self.audio_combo.pack(anchor="w", pady=(2, 4))
        self.mic_in_use = ttk.Label(mic, wraplength=560, text="")
        self.mic_in_use.pack(anchor="w", pady=(0, 2))
        self._input_seen = config.INPUT_DEVICE
        ttk.Button(mic, text="Test microphone", command=try_it_now.open_check).pack(
            anchor="w", pady=(2, 6))
        ttk.Label(
            mic, wraplength=560, style="Muted.TLabel",
            text="If dictation hears nothing, the wrong microphone is "
                 "selected. Takes effect from the next dictation.",
        ).pack(anchor="w")

        out = self._section(f, "Headphones")
        self._output_devices = audio_devices.outputs()
        self.output_combo = ttk.Combobox(
            out, values=[n for _, n, _ in self._output_devices] or ["No playback devices found"],
            state="readonly", width=52)
        current = next((i for i, d in enumerate(self._output_devices) if d[2]), 0)
        self.output_combo.current(current)
        self._output_start = current
        self.output_combo.pack(anchor="w", pady=(2, 4))
        self.output_in_use = ttk.Label(out, wraplength=560, text="")
        self.output_in_use.pack(anchor="w", pady=(0, 2))
        ttk.Label(
            out, wraplength=560, style="Muted.TLabel",
            text="Talkative plays no sound. This switches the Windows "
                 "playback device for every app, like the tray menu.",
        ).pack(anchor="w")

    def _mic_status(self):
        """'In use now: <mic> -- starts instantly' (what the recorder uses:
        the saved choice, or the Windows default)."""
        device = config.INPUT_DEVICE
        name = mic_warmup.device_key(device)
        if name is None:
            return "In use now: no microphone found"
        long_names = [n for _, n in audio_devices.inputs()]
        name = next((n for n in long_names if n.startswith(name)), name)
        if device is None:
            name += " (Windows default)"
        slow = mic_warmup.slow_ms(device)
        measured = mic_warmup.measured_ms(device)
        if slow is not None:
            minutes = round(config.SLOW_MIC_KEEP_SECONDS / 60)
            speed = (f"starts in {slow / 1000:.1f} s, so Talkative keeps it ready "
                     f"for {minutes} minutes after each dictation")
        elif measured is not None:
            speed = "starts instantly"
        elif mic_warmup.is_bluetooth(device):
            speed = "Bluetooth, start-up speed not checked"
        else:
            speed = "start-up speed not checked yet"
        return f"In use now: {name}, {speed}."

    def _refresh_devices(self):
        """Keep the "In use now" lines current while Settings is open
        (a mic plugged in, the Windows default changed, the check done)."""
        try:
            if not self.root.winfo_exists():
                return
            if getattr(self, "page", None) == "Audio & Output":
                if config.INPUT_DEVICE != self._input_seen:
                    # Changed in the Test microphone box (or the tray):
                    # follow it, so Save doesn't put the old one back.
                    self._input_seen = config.INPUT_DEVICE
                    if config.INPUT_DEVICE in self._audio_values:
                        self.audio_combo.current(self._audio_values.index(config.INPUT_DEVICE))
                self.mic_in_use.config(text=self._mic_status())
                default = next((n for _, n, d in audio_devices.outputs() if d), None)
                self.output_in_use.config(
                    text=f"In use now: {default}." if default else "In use now: none found.")
        except Exception:
            logging.getLogger(__name__).debug("device refresh failed", exc_info=True)
        self.root.after(2000, self._refresh_devices)

    def _tab_output(self, f):
        self.var_insert = tk.StringVar(value=config.INSERT_MODE)
        self.var_space = tk.BooleanVar(value=config.APPEND_SPACE)
        self.var_enter = tk.BooleanVar(value=config.PRESS_ENTER_AFTER)

        box1 = self._section(f, "Typed text goes")
        ttk.Radiobutton(box1, text="Type into the active application",
                        variable=self.var_insert, value="type").pack(anchor="w", pady=2)
        ttk.Radiobutton(box1, text="Copy to clipboard only",
                        variable=self.var_insert, value="clipboard").pack(anchor="w", pady=2)

        box2 = self._section(f, "After dictation")
        for text, var in (("Add a space after the inserted text", self.var_space),
                          ("Press Enter after inserting the text", self.var_enter)):
            row = self._setting_row(box2, text)
            ttk.Checkbutton(row, variable=var,
                            style="Switch.TCheckbutton").grid(row=0, column=1, sticky="e")
        ttk.Label(
            box2, wraplength=560, style="Muted.TLabel",
            text="Undo: press Ctrl+Z in the target application. Each "
                 "dictation is inserted as a single edit.",
        ).pack(anchor="w", pady=(10, 0))

    # Local models (General > Processing > Local). Worker threads only write _model_ops / _model_errors;
    # a ~300ms poll loop on the Tk thread reads them and is the only thing
    # that touches widgets.

    def _build_models(self, f):
        self._model_ops = {}     # tier -> "download" | "load" | "delete"
        self._model_errors = []  # messages appended by workers, shown by the poll
        self._tiles = {}

        tiles_row = ttk.Frame(f)
        tiles_row.pack(fill="x", pady=(2, 6))
        # Voice models on the left (pick one), the grammar model on the
        # right (optional), each card with its download size, RAM and our
        # advice (2026-11-11, user request). Column count follows however
        # many tiers exist.
        n_tiles = len(model_manager.MODELS)
        for col in range(n_tiles + 1):
            tiles_row.columnconfigure(col, weight=1, uniform="tile")
        ttk.Label(tiles_row, text="Voice model: pick one", style="Muted.TLabel").grid(
            row=0, column=0, columnspan=n_tiles, sticky="w", pady=(0, 4))
        ttk.Label(tiles_row, text="Grammar: optional", style="Muted.TLabel").grid(
            row=0, column=n_tiles, sticky="w", padx=(12, 0), pady=(0, 4))
        # One radio per voice card: picking one switches at once (no Save),
        # like the grammar switch; disabled until that model is downloaded.
        self.var_voice = tk.StringVar(
            value=model_manager.tier_for_size(config.MODEL_SIZE) or "fast")
        for col, (tier, info) in enumerate(model_manager.MODELS.items()):
            box = ttk.Frame(tiles_row, style="Card.TFrame", padding=(12, 10))
            box.grid(row=1, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0))
            radio = ttk.Radiobutton(
                box, text=f"{info['label']} - {info['tagline']}",
                variable=self.var_voice, value=tier, style="Card.TRadiobutton",
                command=lambda t=tier, i=info: self._voice_picked(t, i),
            )
            radio.pack(anchor="w")
            points = _card_points(box, info["points"] + [
                f"{info['download_gb']} GB download",
                f"Uses about {model_manager.gb(info['ram_mb'])} of RAM"])
            points.pack(anchor="w", fill="x", pady=(2, 0))
            ttk.Label(box, text=info["advice"], style="Card.TLabel",
                      wraplength=200).pack(anchor="w", pady=(6, 0))
            # Status and buttons packed from the bottom: the three cards
            # stretch to one height, so the buttons line up.
            btn_row = ttk.Frame(box, style="CardBody.TFrame")
            btn_row.pack(side="bottom", anchor="w", pady=(6, 0))
            # Status and version share a line ("In use.  Version 1").
            state_row = ttk.Frame(box, style="CardBody.TFrame")
            state_row.pack(side="bottom", anchor="w", pady=(8, 0))
            status = ttk.Label(state_row, text="", style="Card.TLabel", wraplength=200)
            status.pack(side="left")
            version_label = ttk.Label(state_row, text="", style="CardMuted.TLabel")
            version_label.pack(side="left", padx=(8, 0))
            bar = ttk.Progressbar(box, mode="indeterminate", length=180)
            latency = points
            action = ttk.Button(btn_row)
            delete = ttk.Button(
                btn_row, text="Delete",
                command=lambda t=tier, i=info: self._model_delete(t, i),
            )
            self._tiles[tier] = {
                "info": info, "box": box, "latency": latency, "radio": radio,
                "btn_row": btn_row,
                "version_label": version_label,
                "status": status, "bar": bar,
                "action": action, "delete": delete, "state": None,
            }

        self._build_grammar_section(tiles_row).grid(
            row=1, column=n_tiles, sticky="nsew", padx=(12, 0))

        # Total for the chosen combination, only while Local is picked
        # (Cloud keeps no model in memory).
        self.ram_label = ttk.Label(f, text="", wraplength=640)
        self._ram_text = None

        notes = ttk.Frame(f)
        notes.pack(anchor="w")
        self.storage_label = ttk.Label(notes, style="Muted.TLabel", text="")
        self.storage_label.pack(side="left")
        self.update_label = ttk.Label(notes, style="Muted.TLabel", text="")
        self.update_label.pack(side="left", padx=(12, 0))
        self.undo_btn = ttk.Button(
            f, text="Undo last update", command=self._undo_update
        )
        self._undoing = False
        self._poll_models()

    def _build_grammar_section(self, f):
        # Opt-in since 2026-11-11 (measured: rarely helps, often more than
        # half of Local's wait). Like the voice model card, it acts at once
        # -- the switch doesn't wait for Save -- and it only shows once the
        # model is downloaded, so it never claims "on" for a missing model.
        box = ttk.Frame(f, style="Card.TFrame", padding=(12, 10))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text="Optimize Narration", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w")
        self.var_local_grammar = tk.BooleanVar(value=config.ENABLE_GRAMMAR_ENGINE)
        switch = ttk.Checkbutton(box, variable=self.var_local_grammar,
                                 style="Card.Switch.TCheckbutton",
                                 command=self._grammar_switched)
        _card_points(box, [
            "Fixes small grammar slips",
            "Each dictation 2 to 6 seconds slower",
            "1.5 GB download",
            f"Uses about {model_manager.gb(model_manager.GRAMMAR_RAM_MB)} of RAM",
        ]).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        ttk.Label(
            box, text="Optional. Most dictations don't need it.",
            style="Card.TLabel", wraplength=200,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        # Row 3 takes the spare height, so status and buttons sit at the
        # bottom, level with the voice cards'.
        box.rowconfigure(3, weight=1)
        status = ttk.Label(box, text="", wraplength=200, style="Card.TLabel")
        status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        bar = ttk.Progressbar(box, mode="indeterminate", length=180)
        btn_row = ttk.Frame(box, style="CardBody.TFrame")
        btn_row.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        download = ttk.Button(
            btn_row, text="Download and turn on", command=self._grammar_download
        )
        delete = ttk.Button(btn_row, text="Delete", command=self._grammar_delete)
        self._grammar_tile = {
            "box": box, "status": status, "bar": bar, "switch": switch,
            "download": download, "delete": delete, "state": None,
        }
        self._grammar_op = None
        return box

    def _grammar_switched(self):
        on = self.var_local_grammar.get()
        config.ENABLE_GRAMMAR_ENGINE = on
        settings.save({"local_grammar": on})
        self._grammar_tile["state"] = None  # re-render the status line

        def work():
            if on:
                grammar_engine.load_if_used()
            else:
                grammar_engine.unload()

        threading.Thread(target=work, daemon=True).start()

    def _model_tile_state(self, tier, size):
        op = self._model_ops.get(tier)
        if op is not None:
            return op
        if not model_manager.is_downloaded(size):
            return "none"
        if size == config.MODEL_SIZE and (
            self.model_controller is None or self.model_controller.has_model()
        ):
            return "in_use"
        return "not_in_use"

    def _render_model_tile(self, tier):
        tile = self._tiles[tier]
        info = tile["info"]
        state = self._model_tile_state(tier, info["size"])

        # Refreshed every poll regardless of whether the overall state
        # changed, so it updates live if a background update swaps the
        # files in without the tile ever passing through "download".
        key = f"speech-{tier}"
        if state in ("in_use", "not_in_use") and key in updater.MANAGED:
            # Accurate isn't in the update manifest: fixed Hugging Face repo.
            ver = updater.installed_version(key)
            tile["version_label"].config(text=f"Version {ver}" if ver else "")
        else:
            tile["version_label"].config(text="")

        if state == tile["state"]:
            return
        tile["state"] = state

        bar, status = tile["bar"], tile["status"]
        action, delete = tile["action"], tile["delete"]
        action.pack_forget()
        delete.pack_forget()
        if state == "download":
            bar.config(mode="determinate", maximum=100, value=0)
            # Packed from the bottom just above the buttons: under the
            # status line, as in the grammar card.
            bar.pack(side="bottom", anchor="w", pady=(4, 0), after=tile["btn_row"])
            self._show_download_progress(tier)
            return
        if state == "load":
            # How long a load takes can't be measured as it goes (unlike a
            # download's bytes), so a moving bar plus the usual time.
            status.config(text=f"Loading the {info['label']} model… "
                               f"this takes {info['load_note']}.")
            bar.config(mode="indeterminate")
            bar.pack(side="bottom", anchor="w", pady=(4, 0), after=tile["btn_row"])
            bar.start(12)
            return
        bar.stop()
        bar.pack_forget()

        if state == "none":
            status.config(text="Not downloaded.")
            action.config(
                text="Download",
                command=lambda: self._model_download(tier, info),
            )
            action.pack(side="left")
        elif state == "delete":
            status.config(text="Deleting…")
        elif state == "in_use":
            status.config(text="In use.")
            delete.pack(side="left")
        else:  # not_in_use: picked with the card's radio button
            # Short: it shares a line with "Version N", and a longer text
            # widened all three cards (window 908 -> 1055 px).
            status.config(text="Downloaded.")
            delete.pack(side="left")

    def _grammar_tile_state(self):
        if self._grammar_op is not None:
            return self._grammar_op
        if grammar_engine.is_downloading():
            return "download"   # started elsewhere (Local setup's background stage)
        return "installed" if grammar_engine.is_installed() else "none"

    def _render_grammar_tile(self):
        tile = self._grammar_tile
        state = self._grammar_tile_state()
        if state == "installed":
            state = "on" if config.ENABLE_GRAMMAR_ENGINE else "off"
        if state == tile["state"]:
            return
        tile["state"] = state

        bar, status, switch = tile["bar"], tile["status"], tile["switch"]
        download, delete = tile["download"], tile["delete"]
        download.pack_forget()
        delete.pack_forget()
        switch.grid_remove()
        if state == "download":
            bar.config(mode="determinate", maximum=100, value=0)
            bar.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
            self._show_download_progress(None)
            return
        if state == "delete":
            status.config(text="Deleting…")
            bar.config(mode="indeterminate")
            bar.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
            bar.start(12)
            return
        bar.stop()
        bar.grid_remove()

        if state == "none":
            status.config(text="Not downloaded. Off.")
            download.pack(side="left")
            return
        self.var_local_grammar.set(state == "on")
        switch.grid(row=0, column=1, sticky="e")
        status.config(text="On." if state == "on" else
                      "Off. Delete frees 1.5 GB.")
        delete.pack(side="left")

    def _grammar_download(self):
        self._grammar_op = "download"

        def work():
            try:
                grammar_engine.download()
                # The button says "Download and turn on".
                config.ENABLE_GRAMMAR_ENGINE = True
                settings.save({"local_grammar": True})
                grammar_engine.load_if_used()
            except Exception as exc:
                self._model_errors.append(
                    f"Could not download Optimize Narration:\n{exc}"
                )
            finally:
                self._grammar_op = None

        threading.Thread(target=work, daemon=True).start()

    def _grammar_delete(self):
        if not messagebox.askyesno(
            APP_NAME,
            "Remove the Optimize Narration files?\n\n"
            "This frees about 1.5 GB. “Cleaned up” dictations will keep "
            "working with basic rules only. You can download it again "
            "any time from here.",
            icon="warning", parent=self.root,
        ):
            return
        self._grammar_op = "delete"

        def work():
            try:
                grammar_engine.delete()
            finally:
                config.ENABLE_GRAMMAR_ENGINE = False
                settings.save({"local_grammar": False})
                self._grammar_op = None

        threading.Thread(target=work, daemon=True).start()

    def _poll_models(self):
        for tier in self._tiles:
            self._render_model_tile(tier)
            if self._tiles[tier]["state"] == "download":
                self._show_download_progress(tier)
        self._sync_voice_radios()
        self._render_grammar_tile()
        if self._grammar_tile["state"] == "download":
            self._show_download_progress(None)
        self._render_local_download()
        self._render_ram()
        while self._model_errors:
            messagebox.showerror(APP_NAME, self._model_errors.pop(0), parent=self.root)
        self.storage_label.config(
            text=f"Models use {model_manager.storage_used_mb():.0f} MB."
        )
        status = updater.get_status()
        if status["downloading"]:
            self.update_label.config(text="An update is downloading in the background…")
        elif status["last_check"]:
            self.update_label.config(text=f"Last checked for updates: {status['last_check']}")
        else:
            self.update_label.config(text="Updates are checked automatically.")
        grace = status["grace"]
        if grace and not self._undoing:
            self.undo_btn.config(
                text=f"Undo last update (available for your next "
                     f"{max(0, grace.get('words_left', 0))} words)",
                state="normal",
            )
            self.undo_btn.pack(anchor="w", pady=(6, 0))
        elif self._undoing:
            self.undo_btn.config(text="Undoing…", state="disabled")
        else:
            self.undo_btn.pack_forget()
        self.root.after(300, self._poll_models)

    def _render_ram(self):
        """'With Fast and Optimize Narration on, Talkative uses about 2.3 GB
        of RAM.' -- for the voice model in use and the grammar switch, shown
        only while Local is picked."""
        text = ""
        if self.var_engine.get() == "local":
            size = config.MODEL_SIZE
            tier = model_manager.tier_for_size(size) or "fast"
            grammar = config.ENABLE_GRAMMAR_ENGINE and grammar_engine.is_installed()
            label = model_manager.MODELS[tier]["label"]
            combo = f"{label} voice model and Optimize Narration {'on' if grammar else 'off'}"
            text = (f"With the {combo}, {APP_NAME} uses about "
                    f"{model_manager.gb(model_manager.ram_mb(size, grammar))} of RAM.")
        if text == self._ram_text:
            return
        self._ram_text = text
        if text:
            self.ram_label.config(text=text)
            self.ram_label.pack(anchor="w", pady=(0, 4), before=self.storage_label.master)
        else:
            self.ram_label.pack_forget()

    def _undo_update(self):
        if self._undoing or self.model_controller is None:
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Go back to the previous version? This update will not be "
            "offered again.",
            parent=self.root,
        ):
            return
        self._undoing = True

        def work():
            try:
                self.model_controller.undo_update()
            finally:
                self._undoing = False

        threading.Thread(target=work, daemon=True).start()

    def _model_download(self, tier, info):
        self._model_ops[tier] = "download"

        def work():
            try:
                model_manager.download(info["size"])
            except Exception as exc:
                self._model_errors.append(
                    f"Could not download the {info['label']} model:\n{exc}"
                )
            finally:
                self._model_ops.pop(tier, None)

        threading.Thread(target=work, daemon=True).start()

    def _show_download_progress(self, tier):
        """'Downloading… 37% (530 of 1446 MB)' and the bar's value, for a
        voice model `tier` or (None) the grammar model. Measured from the
        model's own folder, so two downloads at once don't mix."""
        if tier is None:
            tile = self._grammar_tile
            done = model_manager.folder_mb(grammar_engine.engine_dir())
            needed = model_manager.GRAMMAR_DOWNLOAD_MB
        else:
            tile = self._tiles[tier]
            done = model_manager.speech_download_mb(tile["info"]["size"])
            needed = tile["info"]["download_mb"]
        pct = model_manager.download_percent(done, needed)
        tile["bar"].config(value=pct)
        tile["status"].config(
            text=f"Downloading… {pct}% ({min(int(done), needed)} of {needed} MB)")

    def _sync_voice_radios(self):
        """Radios follow the model actually in use (so a failed switch
        snaps back), and can only pick a downloaded model while nothing
        is downloading, loading or deleting."""
        busy = bool(self._model_ops) or self.model_controller is None
        if not busy:
            in_use = model_manager.tier_for_size(config.MODEL_SIZE)
            if in_use and self.var_voice.get() != in_use:
                self.var_voice.set(in_use)
        for tier, tile in self._tiles.items():
            ok = not busy and model_manager.is_downloaded(tile["info"]["size"])
            want = "normal" if ok else "disabled"
            if str(tile["radio"].cget("state")) != want:
                tile["radio"].config(state=want)

    def _voice_picked(self, tier, info):
        if info["size"] == config.MODEL_SIZE or self._model_ops:
            return
        self._model_use(tier, info)

    def _model_use(self, tier, info):
        if self.model_controller is None:
            return
        self._model_ops[tier] = "load"
        self.model_controller.reload(
            info["size"], on_done=lambda ok: self._model_ops.pop(tier, None)
        )

    def _model_delete_worker(self, tier, size):
        self._model_ops[tier] = "delete"

        def work():
            try:
                model_manager.delete(size)
            finally:
                self._model_ops.pop(tier, None)

        threading.Thread(target=work, daemon=True).start()

    def _model_delete(self, tier, info):
        size = info["size"]
        # Not guaranteed to exist -- there's only one tier since Accurate
        # was removed, but this stays tier-count-agnostic in case another
        # tier is ever added back.
        other_tiers = [t for t in model_manager.MODELS if t != tier]
        other_tier = other_tiers[0] if other_tiers else None
        other = model_manager.MODELS[other_tier] if other_tier else None

        if size != config.MODEL_SIZE:
            if messagebox.askyesno(
                APP_NAME,
                f"Delete the {info['label']} model?\n\n"
                "You can download it again at any time.",
                parent=self.root,
            ):
                self._model_delete_worker(tier, size)
            return

        if self.model_controller is None:
            messagebox.showinfo(
                APP_NAME, "The model currently in use can't be deleted.",
                parent=self.root,
            )
            return

        if other is not None and model_manager.is_downloaded(other["size"]):
            if not messagebox.askyesno(
                APP_NAME,
                f"The {info['label']} model is currently in use.\n\n"
                f"“{APP_NAME}” will switch to the {other['label']} model "
                f"first, then delete {info['label']}. Continue?",
                parent=self.root,
            ):
                return
            self._model_ops[other_tier] = "load"
            self._model_ops[tier] = "delete"

            def done(ok):
                self._model_ops.pop(other_tier, None)
                if ok:
                    try:
                        model_manager.delete(size)
                    finally:
                        self._model_ops.pop(tier, None)
                else:
                    self._model_ops.pop(tier, None)

            self.model_controller.reload(other["size"], on_done=done)
            return

        if config.PROCESSING_MODE == "cloud":
            question = (
                f"Delete the {info['label']} model?\n\n"
                "Cloud dictation keeps working. Local mode needs it, so "
                "you'd download it again before switching to Local."
            )
        else:
            question = (
                f"The {info['label']} model is the only model downloaded.\n\n"
                "Deleting it turns dictation off until you download a model "
                "again. Delete anyway?"
            )
        if messagebox.askyesno(
            APP_NAME, question, icon="warning", parent=self.root,
        ):
            self.model_controller.unload()
            self._model_delete_worker(tier, size)

    def _tab_about(self, f):
        self._star_card(f)
        # Two columns under the star card (2026-11-23, user request, like
        # General): Version and Privacy left, the two sending choices right.
        cols = ttk.Frame(f, style="Canvas.TFrame")
        cols.pack(fill="x", pady=(10, 0))
        cols.columnconfigure(0, weight=1, uniform="about")
        cols.columnconfigure(1, weight=1, uniform="about")
        left = ttk.Frame(cols, style="Canvas.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(cols, style="Canvas.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        self._wide_columns.append((right, 10))
        ver = self._section(left, "Version", first=True)
        row = ttk.Frame(ver)
        row.pack(fill="x")
        row.columnconfigure(0, weight=1)
        text = ttk.Frame(row)
        text.grid(row=0, column=0, sticky="w")
        ttk.Label(text, text=f"{APP_NAME} {__version__}").pack(anchor="w")
        self.check_updates_label = ttk.Label(
            text, style="Muted.TLabel", wraplength=380,
            text=("Updates come from the Microsoft Store."
                  if packaging.is_store_build() else ""),
        )
        self.check_updates_label.pack(anchor="w")
        self.check_updates_btn = ttk.Button(
            row, text="Check for updates", command=self._check_updates
        )
        self.check_updates_btn.grid(row=0, column=1, sticky="e")

        box = self._section(left, "Privacy")
        # Short on purpose (2026-10-27, user request); the details --
        # history, feedback, diagnostics -- are in PRIVACY.md.
        ttk.Label(
            box, wraplength=_ABOUT_WRAP,
            text="Cloud sends your audio, and the text just before the "
                 "cursor, to a server for processing. Nothing you dictate is kept unless "
                 "you turn on diagnostic data below. Local keeps everything "
                 "on this PC.",
        ).pack(anchor="w")
        link = ttk.Label(box, text="Read the privacy policy", cursor="hand2",
                         foreground=self._link, takefocus=True)
        link.pack(anchor="w", pady=(4, 0))
        open_policy = lambda e=None: webbrowser.open(config.PRIVACY_URL)  # noqa: E731
        for seq in ("<Button-1>", "<Return>", "<space>"):
            link.bind(seq, open_policy)

        diag = self._section(right, "Diagnostic data", first=True)
        self.var_diagnostics = tk.BooleanVar(value=config.SEND_DIAGNOSTICS)
        ttk.Radiobutton(
            diag, text="Send diagnostic data to help fix problems",
            variable=self.var_diagnostics, value=True,
            command=self._diagnostics_changed,
        ).pack(anchor="w", pady=2)
        ttk.Radiobutton(
            diag, text="Don't send diagnostic data",
            variable=self.var_diagnostics, value=False,
        ).pack(anchor="w", pady=2)
        ttk.Label(
            diag, wraplength=_ABOUT_WRAP, style="Muted.TLabel",
            text="Diagnostic data is what you said, what was typed, and the "
                 "recording of each dictation. It goes to Sumit only, is "
                 "kept for 30 days, then deleted. Your diagnostic ID: "
                 + feedback.install_id()[:8],
        ).pack(anchor="w", pady=(4, 0))

        # Anonymous usage count (usage_ping.py): on by default and disclosed
        # (user's decision, 2026-11-23); no identifier is sent.
        count = self._section(right, "Anonymous usage count")
        self.var_usage = tk.BooleanVar(value=config.USAGE_COUNT)
        row = self._setting_row(
            count, "Send the anonymous usage count",
            "Once a day: version, Cloud or Local, and roughly how many "
            "dictations. No ID and nothing you dictate.", wrap=_ABOUT_WRAP - 60)
        ttk.Checkbutton(row, variable=self.var_usage,
                        style="Switch.TCheckbutton").grid(row=0, column=1, sticky="e")

    def _star_card(self, f):
        """A quiet request for a GitHub star (user's request, 2026-11-23):
        one card here, never a popup or a reminder."""
        card = ttk.Frame(f, style="Section.TFrame", padding=(20, 16))
        card.pack(fill="x")
        card.columnconfigure(0, weight=1)
        text = ttk.Frame(card)
        text.grid(row=0, column=0, sticky="w")
        # In Sumit's own voice, person to person (user's request).
        ttk.Label(text, text=f"Enjoying {APP_NAME}?",
                  style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            text, wraplength=480, style="Muted.TLabel",
            text=f"If {APP_NAME} saves you some typing, I'd be grateful for a "
                 "star on GitHub. It helps more people find it, and more "
                 "people means more of the features you ask for.",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(text, text="Thanks, Sumit", style="Muted.TLabel").pack(
            anchor="w", pady=(4, 0))
        open_repo = lambda e=None: webbrowser.open(config.REPO_URL)  # noqa: E731
        repo = ttk.Label(text, text=config.REPO_URL.replace("https://", ""),
                         foreground=self._link, cursor="hand2",
                         takefocus=True)
        repo.pack(anchor="w", pady=(4, 0))
        for seq in ("<Button-1>", "<Return>", "<space>"):
            repo.bind(seq, open_repo)
        ttk.Button(card, text="★  Star on GitHub", style="Accent.TButton",
                   command=open_repo).grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _check_updates(self):
        self.check_updates_btn.config(state="disabled")
        self.check_updates_label.config(text="Checking…")

        def show(text):
            if self.check_updates_btn.winfo_exists():
                self.check_updates_btn.config(state="normal")
                self.check_updates_label.config(text=text)

        def work():
            try:
                text = updater.check_now()
            except Exception:
                logging.getLogger(__name__).exception("manual update check failed")
                text = "Something went wrong while checking. Please try again."
            self.overlay.build(lambda: show(text))

        threading.Thread(target=work, daemon=True).start()

    def _diagnostics_changed(self):
        if config.SEND_DIAGNOSTICS:
            return
        ok = messagebox.askyesno(
            APP_NAME,
            "Send diagnostic data?\n\n"
            "From now on, every dictation sends Sumit:\n"
            "• the recording of what you said\n"
            "• what was heard, each cleanup step, and what was typed\n"
            "• your Talkative settings and version\n\n"
            "It's kept for 30 days to find and fix problems, then deleted. "
            "It's never shared or sold. You can turn this off here at any time.\n\n"
            "Don't turn this on if you dictate things you wouldn't want "
            "someone else to read or hear.",
            parent=self.root,
        )
        if not ok:
            self.var_diagnostics.set(False)

    def _build_feedback_section(self, f):
        box = f
        ttk.Label(
            box, wraplength=500, style="Muted.TLabel",
            text="Send a message straight to Sumit. A reply, if there is "
                 "one, will show up here.",
        ).pack(anchor="w")
        self.feedback_text = tk.Text(
            box, height=8, wrap="word", font=("Segoe UI", 10),
            bg=self._field, fg=self._fg, insertbackground=self._fg,
            selectbackground=self._accent, selectforeground=self._accent_fg,
            relief="flat", borderwidth=0, padx=8, pady=6,
            highlightthickness=1, highlightbackground=self._border,
            highlightcolor=self._link,
        )
        self.feedback_text.pack(fill="x", pady=(8, 8))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        self.feedback_send_btn = ttk.Button(
            row, text="Send", command=self._send_feedback
        )
        self.feedback_send_btn.pack(side="left")
        # A screenshot can go with the message (2026-10-26, user request).
        self.feedback_image = None
        self.feedback_attach_btn = ttk.Button(
            row, text="Attach image…", command=self._attach_feedback_image
        )
        self.feedback_attach_btn.pack(side="left", padx=(8, 0))
        self.feedback_status = ttk.Label(row, text="", style="Muted.TLabel")
        self.feedback_status.pack(side="left", padx=8)
        self.feedback_image_row = ttk.Frame(box)
        self.feedback_image_label = ttk.Label(
            self.feedback_image_row, text="", style="Muted.TLabel"
        )
        self.feedback_image_label.pack(side="left")
        ttk.Button(
            self.feedback_image_row, text="Remove",
            command=lambda: self._set_feedback_image(None),
        ).pack(side="left", padx=8)

        if config.FEEDBACK_LAST_REPLY:
            reply_box = ttk.Frame(box)
            reply_box.pack(fill="x", pady=(10, 0))
            ttk.Label(reply_box, text="Sumit replied:",
                      style="Sub.TLabel").pack(anchor="w")
            ttk.Label(reply_box, text=config.FEEDBACK_LAST_REPLY,
                      wraplength=500).pack(anchor="w")

    def _attach_feedback_image(self):
        types = " ".join("*" + ext for ext in config.FEEDBACK_IMAGE_TYPES)
        path = filedialog.askopenfilename(
            parent=self.root, title="Attach an image",
            filetypes=[("Images", types)],
        )
        if not path:
            return
        problem = feedback.image_problem(path)
        if problem:
            self.feedback_status.config(text=problem)
            return
        self._set_feedback_image(path)

    def _set_feedback_image(self, path):
        self.feedback_image = path
        self.feedback_status.config(text="")
        if path:
            self.feedback_image_label.config(text="Attached: " + os.path.basename(path))
            self.feedback_image_row.pack(anchor="w", pady=(4, 0))
        else:
            self.feedback_image_row.pack_forget()

    def _send_feedback(self):
        message = self.feedback_text.get("1.0", "end").strip()
        image = self.feedback_image
        if not message and not image:
            return
        self.feedback_send_btn.config(state="disabled")
        self.feedback_attach_btn.config(state="disabled")
        # FormSubmit is slow with a file (40 s measured), so say so.
        self.feedback_status.config(
            text="Sending… (an image can take up to a minute)" if image else "Sending…"
        )

        def done(ok, error):
            def update():
                self.feedback_send_btn.config(state="normal")
                self.feedback_attach_btn.config(state="normal")
                if ok:
                    self.feedback_text.delete("1.0", "end")
                    self._set_feedback_image(None)
                    self.feedback_status.config(text="Sent ✓")
                else:
                    log.warning("feedback send failed: %s", error)
                    self.feedback_status.config(
                        text="Could not send. Please try again later."
                    )
            self.root.after(0, update)

        feedback.send(message or "(image only)", on_done=done, image=image)

    # ---------------- save ----------------

    def _save(self):
        dictionary = {}
        for item in self.dict_tree.get_children():
            spoken, typed = self.dict_tree.item(item, "values")
            if spoken and typed:
                dictionary[spoken] = typed

        values = {
            "start_with_windows": self.var_autostart.get(),
            "theme": self.var_theme.get(),
            "color_scheme": self.var_scheme.get(),
            "processing_mode": self.var_processing.get(),
            "send_diagnostics": self.var_diagnostics.get(),
            "speech_service": self.var_speech_service.get(),
            "enable_history": self.var_history.get(),
            "insert_mode": self.var_insert.get(),
            "append_space": self.var_space.get(),
            "press_enter_after": self.var_enter.get(),
            "hotkey_mode": self.var_hotkey_mode.get(),
            "dictionary": dictionary,
        }
        values["usage_count"] = self.var_usage.get()
        problem = _hotkey_problem(
            self.pending_hotkey or _key_names(config.HOTKEY),
            self.pending_dev_hotkey if self.pending_dev_hotkey is not None
            else _key_names(config.DEV_HOTKEY),
            self.pending_rewrite_hotkey if self.pending_rewrite_hotkey is not None
            else _key_names(config.REWRITE_HOTKEY),
        )
        if problem:
            # Keep the current keys; everything else still saves.
            messagebox.showwarning(APP_NAME, problem, parent=self.root)
            self.pending_hotkey = None
            self.pending_dev_hotkey = None
            self.pending_rewrite_hotkey = None
            self.hotkey_btn.config(text=_hotkey_display(config.HOTKEY))
            self.rewrite_hotkey_btn.config(
                text=_hotkey_display(config.REWRITE_HOTKEY) if config.REWRITE_HOTKEY
                else "Not set")
            self.dev_hotkey_btn.config(
                text=_hotkey_display(config.DEV_HOTKEY) if config.DEV_HOTKEY else "Not set")
        if self.pending_hotkey:
            values["hotkey"] = self.pending_hotkey
        if self.pending_dev_hotkey is not None:
            values["dev_hotkey"] = self.pending_dev_hotkey
        if self.pending_rewrite_hotkey is not None:
            values["rewrite_hotkey"] = self.pending_rewrite_hotkey
        try:
            values["input_device"] = self._audio_values[self.audio_combo.current()]
        except Exception:
            pass
        try:
            pick = self.output_combo.current()
            if self._output_devices and pick != self._output_start:
                if audio_devices.set_default_output(self._output_devices[pick][0]):
                    self._output_start = pick
                else:
                    messagebox.showwarning(APP_NAME, "Couldn't switch the playback device.",
                                           parent=self.root)
        except Exception:
            logging.getLogger(__name__).exception("playback device switch failed")

        settings.save(values)
        settings.load_into_config()
        if self.on_applied:
            self.on_applied()

        self.saved_label.config(text="Saved ✓")
        self.root.after(2500, lambda: self.saved_label.config(text=""))
