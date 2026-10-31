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

from . import __version__, app_icon, audio_devices, config, dev_mode, feedback, fix_learning, grammar_engine, history, mic_warmup, model_manager, overlay_thread, palette, pill, settings, updater
from .keynames import friendly as _friendly_key_name

log = logging.getLogger(__name__)

APP_NAME = "Talkative"

_open_lock = threading.Lock()
_is_open = False

_EXAMPLE_SPOKEN = "“So um, send the file today, oh sorry, send the file by this evening.”"
_EXAMPLE_CLEAN = "Send the file by this evening."
_EXAMPLE_ASIS = "So um, send the file today, oh sorry, send the file by this evening."

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


# Sidebar item backgrounds (2026-10-30, user: highlighted on hover "just
# like Claude", no lines): rounded rectangles stretched behind the label
# via the image element's border, plain for normal, a soft fill on hover
# or keyboard focus, a stronger one for the chosen page. Same create-once
# rule as the checkbox.
_NAV_ELEMENT = "SumitNav.background"
_NAV_IMAGE = (40, 28)
_nav_images = None  # (normal, hover, chosen) photos once created


def _draw_nav_glyphs(sidebar, hover, chosen):
    scale = 4
    w, h = _NAV_IMAGE[0] * scale, _NAV_IMAGE[1] * scale
    out = []
    for fill in (sidebar, hover, chosen):
        img = Image.new("RGBA", (w, h), sidebar)
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), radius=7 * scale, fill=fill)
        out.append(img.resize(_NAV_IMAGE, Image.LANCZOS))
    return out


def _apply_nav_glyphs(style, sidebar, hover, chosen):
    global _nav_images
    pils = _draw_nav_glyphs(sidebar, hover, chosen)
    if _nav_images is None:
        _nav_images = tuple(ImageTk.PhotoImage(p) for p in pils)
        normal, over, picked = _nav_images
        style.element_create(
            _NAV_ELEMENT, "image", normal,
            ("selected", picked), ("active", over), ("focus", over),
            border=8, sticky="nsew",
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
# also shows the devices in use.
_PAGES = ["General", "Auto Text", "Dictation", "Hotkeys", "Audio & Output",
          "Feedback", "About"]


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


def _hotkey_problem(normal, dev):
    """Why this pair of hotkeys can't be saved, or None. Both are lists of
    key names (settings.json format); dev may be [] (code key off)."""
    def typing_only(names):
        # Shift counts too: Shift + A is a capital A, and Shift alone goes
        # down with every capital letter.
        return names and all(
            n in _TYPING_KEYS or len(n) == 1 or n.startswith("shift") for n in names)

    if typing_only(normal) or typing_only(dev):
        return ("A hotkey can't be only letters, numbers, Shift, Space or Enter -- "
                "dictation would start while you type. Pick a key like "
                "Right Ctrl, or a pair such as Ctrl + Alt. Your previous "
                "hotkeys are kept.")
    if dev and set(dev) == set(normal):
        return ("The dictation key and the code dictation key are the same, "
                "so every dictation would come out as code. Pick a different "
                "key for one of them. Your previous hotkeys are kept.")
    return None


def _hotkey_display(key):
    return _friendly_key_name(key)


class _SettingsWindow:
    def __init__(self, on_applied, model_controller, overlay):
        self.on_applied = on_applied
        self.model_controller = model_controller
        self.overlay = overlay
        self.pending_hotkey = None
        self.pending_dev_hotkey = None
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
        content = ttk.Frame(self.root)
        content.pack(side="left", fill="both", expand=True)
        area = ttk.Frame(content)
        area.pack(fill="both", expand=True)
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        builders = {
            "General": self._tab_general,
            "Auto Text": self._tab_dictionary,
            "Dictation": self._tab_dictation,
            "Hotkeys": self._tab_hotkeys,
            "Audio & Output": self._tab_audio_output,
            "Feedback": self._build_feedback_section,
            "About": self._tab_about,
        }
        self._pages = {}
        for name in _PAGES:
            page = ttk.Frame(area, padding=(28, 20, 28, 8))
            page.grid(row=0, column=0, sticky="nsew")
            ttk.Label(page, text=name, style="PageTitle.TLabel").pack(anchor="w", pady=(0, 12))
            body = ttk.Frame(page)
            body.pack(fill="both", expand=True)
            builders[name](body)
            self._pages[name] = page

        ttk.Separator(content).pack(fill="x")
        bar = ttk.Frame(content, padding=(28, 10, 28, 12))
        bar.pack(fill="x")
        self.saved_label = ttk.Label(bar, text="")
        self.saved_label.pack(side="left")
        ttk.Button(bar, text="Close", command=self._close).pack(side="right")
        ttk.Button(bar, text="Save and apply", command=self._save,
                   style="Accent.TButton").pack(side="right", padx=8)

        self.select_page("General")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        _window = self

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
        self._pages[name].tkraise()
        for n, label in self._nav.items():
            label.state(["selected" if n == name else "!selected"])
        self.page = name

    def _section(self, parent, title, first=False):
        """A page section: a divider (not above the first), a colored
        heading, and the frame its settings go in."""
        if not first:
            ttk.Separator(parent).pack(fill="x", pady=(14, 12))
        ttk.Label(parent, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        body = ttk.Frame(parent)
        body.pack(fill="x")
        return body

    def _setting_row(self, parent, title, desc=None):
        """A row with the setting's name (and a muted line under it) on
        the left; the caller grids its control at column 1, on the right."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        row.columnconfigure(0, weight=1)
        text = ttk.Frame(row)
        text.grid(row=0, column=0, sticky="w")
        ttk.Label(text, text=title).pack(anchor="w")
        if desc:
            ttk.Label(text, text=desc, style="Muted.TLabel").pack(anchor="w")
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
        sidebar = pill._mix(bg, raised, 0.5)
        nav_hover = pill._mix(sidebar, raised, 0.45)

        self.root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg,
                        fieldbackground=field, bordercolor=border,
                        lightcolor=bg, darkcolor=bg, font=("Segoe UI", 10))
        style.configure("Sidebar.TFrame", background=sidebar)
        style.configure("SidebarTitle.TLabel", background=sidebar, foreground=fg,
                        font=("Segoe UI Semibold", 14))
        style.configure("SidebarMuted.TLabel", background=sidebar, foreground=muted)
        style.configure("Nav.TLabel", foreground=fg, padding=(12, 6))
        _apply_nav_glyphs(style, sidebar, nav_hover, pill._mix(raised, hover, 0.5))
        style.configure("PageTitle.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Section.TLabel", foreground=title, font=("Segoe UI Semibold", 11))
        style.configure("Sub.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("TSeparator", background=border)
        # Cards (the model boxes): a field-colored panel with a thin border.
        style.configure("Card.TFrame", background=field, bordercolor=border,
                        lightcolor=border, darkcolor=border, relief="solid", borderwidth=1)
        style.configure("CardBody.TFrame", background=field)
        style.configure("Card.TLabel", background=field)
        style.configure("CardTitle.TLabel", background=field, font=("Segoe UI Semibold", 10))
        style.configure("CardMuted.TLabel", background=field, foreground=muted)
        # Flat buttons: clam's light/dark edge colors set to the face
        # color remove its bevel.
        style.configure("TButton", background=raised, lightcolor=raised, darkcolor=raised,
                        bordercolor=border, padding=(14, 4))
        style.map(
            "TButton",
            background=[("disabled", raised), ("active", hover)],
            lightcolor=[("active", hover)], darkcolor=[("active", hover)],
            foreground=[("disabled", border)],
        )
        # The main action ("Save and apply") in the accent color.
        style.configure("Accent.TButton", background=accent, foreground=accent_fg,
                        bordercolor=accent, lightcolor=accent, darkcolor=accent,
                        font=("Segoe UI Semibold", 10))
        style.map(
            "Accent.TButton",
            background=[("disabled", raised), ("active", accent_hover)],
            lightcolor=[("active", accent_hover)], darkcolor=[("active", accent_hover)],
            foreground=[("disabled", border)],
        )
        # Section titles ("Dictation style", "Feedback"...) in color.
        style.configure("TLabelframe", background=bg, bordercolor=border)
        style.configure("TLabelframe.Label", background=bg, foreground=title,
                        font=("Segoe UI Semibold", 10))
        # Radiobutton/checkbutton row background was never mapped for the
        # "active" (hover) state, so clam's built-in light default painted
        # every row white on hover regardless of theme.
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.map(
            "TCheckbutton",
            background=[("active", bg)],
            foreground=[("disabled", border)],
        )
        _apply_checkbox_glyphs(style, field, border, accent, accent_fg)
        _apply_switch_glyphs(style, muted, accent, accent_fg)
        style.map(
            "TRadiobutton",
            background=[("active", bg)],
            foreground=[("disabled", border)],
        )
        # clam's radio dot was white on an unselected button in dark mode,
        # so the chosen option looked like the only empty one. Now: an
        # empty field-colored circle, and a title-colored dot when selected
        # (the accent is too dark to see on dark backgrounds).
        style.configure("TRadiobutton", indicatorbackground=field,
                        indicatorforeground=title, bordercolor=border,
                        upperbordercolor=border, lowerbordercolor=border)
        style.map(
            "TRadiobutton",
            indicatorbackground=[("pressed", hover), ("selected", field)],
            indicatorforeground=[("disabled", border), ("selected", title)],
        )
        # Flat tables: taller rows for 10pt text, headings without bevels.
        style.configure("Treeview", background=field, foreground=fg,
                        fieldbackground=field, rowheight=26, bordercolor=border,
                        lightcolor=field, darkcolor=field)
        style.configure("Treeview.Heading", background=raised, foreground=fg,
                        lightcolor=raised, darkcolor=raised, bordercolor=border,
                        padding=(8, 4), font=("Segoe UI Semibold", 10))
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
        start = self._section(f, "Startup", first=True)
        row = self._setting_row(start, "Start with Windows",
                                f"Open {APP_NAME} when you sign in to Windows.")
        ttk.Checkbutton(row, variable=self.var_autostart,
                        style="Switch.TCheckbutton").grid(row=0, column=1, sticky="e")

        look = self._section(f, "Appearance")
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
        ttk.Label(proc, text="Cloud", style="Sub.TLabel").pack(anchor="w")
        cloud_box = ttk.Frame(proc, padding=(4, 2, 0, 0))
        cloud_box.pack(fill="x")
        ttk.Label(proc, text="Local", style="Sub.TLabel").pack(anchor="w", pady=(10, 0))
        local_box = ttk.Frame(proc, padding=(4, 2, 0, 0))
        local_box.pack(fill="x")
        self.var_processing = tk.StringVar(value=config.PROCESSING_MODE)
        self.var_speech_service = tk.StringVar(value=config.SPEECH_SERVICE)
        # One choice across both sections (2026-10-27, user request: no
        # separate "Cloud" button): an accent under Cloud selects Cloud
        # with that speech service -- US English = Groq's Whisper, Indian
        # English = Azure en-IN via the Worker -- or Local's own button.
        self.var_engine = tk.StringVar(
            value=config.SPEECH_SERVICE if config.PROCESSING_MODE == "cloud" else "local")
        for label, value in (("US English", "us_english"),
                             ("Indian English", "indian_english")):
            ttk.Radiobutton(
                cloud_box, text=label, variable=self.var_engine, value=value,
                command=self._engine_changed,
            ).pack(anchor="w", pady=1)

        self.local_radio = ttk.Radiobutton(
            local_box, text="Fully offline. Nothing leaves this PC.",
            variable=self.var_engine, value="local",
            command=self._engine_changed,
        )
        self.local_radio.pack(anchor="w", pady=1)

        self._local_op = None    # None | "downloading"
        self._local_error = []   # messages appended by the worker, shown by the poll
        local_row = ttk.Frame(local_box)
        local_row.pack(fill="x")
        self.local_status = ttk.Label(local_row, text="")
        self.local_bar = ttk.Progressbar(local_row, mode="indeterminate", length=240)
        self.local_download_btn = ttk.Button(
            local_row, command=self._download_local_models
        )

        self._render_local_download()
        models = ttk.Frame(local_box)
        models.pack(fill="x", pady=(6, 0))
        self._build_models(models)

    def _engine_changed(self):
        engine = self.var_engine.get()
        if engine == "local":
            self.var_processing.set("local")
        else:
            self.var_processing.set("cloud")
            self.var_speech_service.set(engine)
        self._render_local_download()

    def _download_local_models(self):
        self._local_op = "downloading"

        def work():
            try:
                if not model_manager.is_downloaded(config.MODEL_SIZE):
                    model_manager.download(config.MODEL_SIZE)
                if not grammar_engine.is_installed():
                    grammar_engine.download()
                grammar_engine.load_if_used()
            except Exception as exc:
                self._local_error.append(f"Could not download local models:\n{exc}")
            finally:
                self._local_op = None

        threading.Thread(target=work, daemon=True).start()

    def _render_local_download(self):
        installed = (
            model_manager.is_downloaded(config.MODEL_SIZE)
            and grammar_engine.is_installed()
        )
        if self._local_op == "downloading" or grammar_engine.is_downloading():
            self.local_status.config(text="Downloading… this can take a few minutes.")
            self.local_download_btn.pack(anchor="w", pady=(4, 4))
            self.local_status.pack(anchor="w", before=self.local_download_btn)
            self.local_bar.pack(anchor="w", pady=(0, 4), before=self.local_download_btn)
            self.local_bar.start(12)
            self.local_download_btn.config(state="disabled", text="Downloading…")
        else:
            self.local_bar.stop()
            self.local_bar.pack_forget()
            if installed:
                # The model boxes below say "Downloaded": no status line or
                # greyed-out button, to keep General short.
                self.local_status.pack_forget()
                self.local_download_btn.pack_forget()
            else:
                self.local_status.config(
                    text="Local mode needs the voice and grammar models "
                         "downloaded first (about 2 GB total)."
                )
                self.local_download_btn.config(
                    state="normal", text="Download local models (~2 GB)"
                )
                self.local_download_btn.pack(anchor="w", pady=(4, 4))
                self.local_status.pack(anchor="w", before=self.local_download_btn)
        while self._local_error:
            messagebox.showerror(APP_NAME, self._local_error.pop(0), parent=self.root)

    def _theme_changed(self):
        config.THEME = self.var_theme.get()
        config.COLOR_SCHEME = self.var_scheme.get()
        self._apply_theme()

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

    def _tab_dictation(self, f):
        cleanup_box = self._section(f, "Dictation style", first=True)
        self.var_cleanup = tk.StringVar(value=config.CLEANUP_MODE)
        ttk.Radiobutton(
            cleanup_box, text="Cleaned up: removes fillers, slips and "
                    "repetitions. Keeps the meaning unchanged.",
            variable=self.var_cleanup, value="cleaned_up",
            command=self._update_example,
        ).pack(anchor="w", pady=2)
        ttk.Radiobutton(
            cleanup_box, text="As spoken: types every word exactly as spoken.",
            variable=self.var_cleanup, value="as_spoken",
            command=self._update_example,
        ).pack(anchor="w", pady=2)

        example_box = ttk.Frame(cleanup_box, style="Card.TFrame", padding=(14, 10))
        example_box.pack(fill="x", pady=(10, 0))
        ttk.Label(example_box, text="Example", style="CardTitle.TLabel").pack(
            anchor="w", pady=(0, 4))
        ttk.Label(example_box, text="You said:", style="Card.TLabel").pack(anchor="w")
        ttk.Label(example_box, text=_EXAMPLE_SPOKEN, wraplength=520,
                  style="CardMuted.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(example_box, text="Appears on screen:", style="Card.TLabel").pack(anchor="w")
        self.example_label = ttk.Label(example_box, text="", wraplength=520,
                                       style="Card.TLabel")
        self.example_label.pack(anchor="w")
        self._update_example()

        history_box = self._section(f, "History")
        self.var_history = tk.BooleanVar(value=config.ENABLE_HISTORY)
        row = self._setting_row(history_box, "Keep a history of what I've dictated",
                                "Saved only on this device. Nothing is sent anywhere.")
        ttk.Checkbutton(row, variable=self.var_history,
                        style="Switch.TCheckbutton").grid(row=0, column=1, sticky="e")
        ttk.Button(
            history_box, text="View history…", command=self._open_history_viewer,
        ).pack(anchor="w", pady=(8, 0))

    def _update_example(self):
        clean = self.var_cleanup.get() == "cleaned_up"
        self.example_label.config(text=_EXAMPLE_CLEAN if clean else _EXAMPLE_ASIS)

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

        bar = ttk.Frame(win, padding=(12, 4, 12, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Clear history", command=clear).pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")

    def _tab_hotkeys(self, f):
        # Two keys: which one you hold picks the kind of dictation, every
        # time -- no mode to switch or turn off.
        keys = self._section(f, "Keys", first=True)
        ttk.Label(keys, style="Muted.TLabel",
                  text="Click a key to change it, then hold the key(s) you want.").pack(
            anchor="w", pady=(0, 4))
        row = self._setting_row(keys, "Regular dictation",
                                "For emails, messages and anything in sentences.")
        self.hotkey_btn = ttk.Button(
            row, text=_hotkey_display(config.HOTKEY), command=self._capture_hotkey
        )
        self.hotkey_btn.grid(row=0, column=1, sticky="e")
        row = self._setting_row(keys, "Code dictation",
                                "For SQL, terminal commands and code.")
        self.dev_hotkey_btn = ttk.Button(
            row,
            text=_hotkey_display(config.DEV_HOTKEY) if config.DEV_HOTKEY else "Not set",
            command=lambda: self._capture_hotkey("dev"),
        )
        self.dev_hotkey_btn.grid(row=0, column=1, sticky="e")
        ttk.Label(
            keys, wraplength=560, style="Muted.TLabel",
            text="“select star from users where id equals five” types "
                 "SELECT * FROM users WHERE id = 5.",
        ).pack(anchor="w", pady=(4, 0))
        help_link = ttk.Label(keys, text="How to say code…", cursor="hand2",
                              foreground=self._link, takefocus=True)
        help_link.pack(anchor="w", pady=(4, 0))
        for seq in ("<Button-1>", "<Return>", "<space>"):
            help_link.bind(seq, lambda e: self._show_dev_help())

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
        btn = self.dev_hotkey_btn if which == "dev" else self.hotkey_btn
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
        # Column count follows however many tiers exist (just Fast right
        # now, since Accurate was removed) rather than assuming two, so a
        # single tile spans the full width instead of leaving an awkward
        # empty half.
        # The grammar model sits in the same row, after the voice models,
        # to keep General's height down now that the models live there.
        n_tiles = len(model_manager.MODELS)
        for col in range(n_tiles + 1):
            tiles_row.columnconfigure(col, weight=1, uniform="tile")
        for col, (tier, info) in enumerate(model_manager.MODELS.items()):
            box = ttk.Frame(tiles_row, style="Card.TFrame", padding=(12, 10))
            box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0))
            ttk.Label(box, text=f"{info['label']} - {info['tagline']}",
                      style="CardTitle.TLabel").pack(anchor="w")
            latency = ttk.Label(box, text=info["latency"], style="CardMuted.TLabel",
                                 wraplength=225)
            latency.pack(anchor="w")
            # Status and version share a line ("Downloaded.  Version 1").
            state_row = ttk.Frame(box, style="CardBody.TFrame")
            state_row.pack(anchor="w")
            status = ttk.Label(state_row, text="", style="Card.TLabel")
            status.pack(side="left")
            version_label = ttk.Label(state_row, text="", style="CardMuted.TLabel")
            version_label.pack(side="left", padx=(8, 0))
            bar = ttk.Progressbar(box, mode="indeterminate", length=180)
            btn_row = ttk.Frame(box, style="CardBody.TFrame")
            btn_row.pack(anchor="w", pady=(6, 0))
            action = ttk.Button(btn_row)
            delete = ttk.Button(
                btn_row, text="Delete",
                command=lambda t=tier, i=info: self._model_delete(t, i),
            )
            self._tiles[tier] = {
                "info": info, "box": box, "latency": latency,
                "version_label": version_label,
                "status": status, "bar": bar,
                "action": action, "delete": delete, "state": None,
            }

        self._build_grammar_section(tiles_row).grid(
            row=0, column=n_tiles, sticky="nsew", padx=(12, 0))

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
        box = ttk.Frame(f, style="Card.TFrame", padding=(12, 10))
        ttk.Label(box, text="Optimize Narration", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            box,
            text="Fix grammar and punctuation",
            style="CardMuted.TLabel", wraplength=220,
        ).pack(anchor="w")
        status = ttk.Label(box, text="", wraplength=225, style="Card.TLabel")
        status.pack(anchor="w")
        bar = ttk.Progressbar(box, mode="indeterminate", length=240)
        btn_row = ttk.Frame(box, style="CardBody.TFrame")
        btn_row.pack(anchor="w", pady=(6, 0))
        download = ttk.Button(
            btn_row, text="Download", command=self._grammar_download
        )
        delete = ttk.Button(btn_row, text="Delete", command=self._grammar_delete)
        self._grammar_tile = {
            "box": box, "status": status, "bar": bar,
            "download": download, "delete": delete, "state": None,
        }
        self._grammar_op = None
        return box

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
        if state in ("in_use", "not_in_use"):
            ver = updater.installed_version(f"speech-{tier}")
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
            status.config(text="Downloading… this can take a few minutes.")
            bar.pack(anchor="w", pady=(4, 0))
            bar.start(12)
            return
        bar.stop()
        bar.pack_forget()

        if state == "none":
            status.config(text=f"Not downloaded ({info['approx']}).")
            action.config(
                text="Download",
                command=lambda: self._model_download(tier, info),
            )
            action.pack(side="left")
        elif state == "load":
            status.config(text="Loading…")
        elif state == "delete":
            status.config(text="Deleting…")
        elif state == "in_use":
            # No "in use" badge/border -- there's only one voice model now,
            # so highlighting which one is active is meaningless clutter.
            status.config(text="Downloaded.")
            delete.pack(side="left")
        else:  # not_in_use
            status.config(text="Downloaded, not in use.")
            action.config(
                text="Use this model",
                state="normal" if self.model_controller else "disabled",
                command=lambda: self._model_use(tier, info),
            )
            action.pack(side="left")
            delete.pack(side="left", padx=6)

    def _grammar_tile_state(self):
        if self._grammar_op is not None:
            return self._grammar_op
        if grammar_engine.is_downloading():
            return "download"   # started elsewhere (Local setup's background stage)
        return "installed" if grammar_engine.is_installed() else "none"

    def _render_grammar_tile(self):
        tile = self._grammar_tile
        state = self._grammar_tile_state()
        if state == tile["state"]:
            return
        tile["state"] = state

        bar, status = tile["bar"], tile["status"]
        download, delete = tile["download"], tile["delete"]
        download.pack_forget()
        delete.pack_forget()
        if state in ("download", "delete"):
            status.config(text="Downloading…" if state == "download" else "Deleting…")
            bar.pack(anchor="w", pady=(4, 0))
            bar.start(12)
            return
        bar.stop()
        bar.pack_forget()

        if state == "none":
            status.config(
                text="Not installed. Cleaned-up dictations use basic rules only."
            )
            download.pack(side="left")
        else:  # installed
            status.config(text="Installed.")
            delete.pack(side="left")

    def _grammar_download(self):
        self._grammar_op = "download"

        def work():
            try:
                grammar_engine.download()
                grammar_engine.load_if_used()
            except Exception as exc:
                self._model_errors.append(
                    f"Could not download the grammar engine:\n{exc}"
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
            "any time from this tab.",
            icon="warning", parent=self.root,
        ):
            return
        self._grammar_op = "delete"

        def work():
            try:
                grammar_engine.delete()
            finally:
                self._grammar_op = None

        threading.Thread(target=work, daemon=True).start()

    def _poll_models(self):
        for tier in self._tiles:
            self._render_model_tile(tier)
        self._render_grammar_tile()
        self._render_local_download()
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
        ver = self._section(f, "Version", first=True)
        row = ttk.Frame(ver)
        row.pack(fill="x")
        row.columnconfigure(0, weight=1)
        text = ttk.Frame(row)
        text.grid(row=0, column=0, sticky="w")
        ttk.Label(text, text=f"{APP_NAME} {__version__}").pack(anchor="w")
        self.check_updates_label = ttk.Label(
            text, style="Muted.TLabel", text="", wraplength=380
        )
        self.check_updates_label.pack(anchor="w")
        self.check_updates_btn = ttk.Button(
            row, text="Check for updates", command=self._check_updates
        )
        self.check_updates_btn.grid(row=0, column=1, sticky="e")

        box = self._section(f, "Privacy")
        # Short on purpose (2026-10-27, user request); the details --
        # history, feedback, diagnostics -- are in PRIVACY.md.
        ttk.Label(
            box, wraplength=560,
            text="Cloud sends your audio, and the text just before the "
                 "cursor, to a server for processing. Nothing is kept unless "
                 "you turn on diagnostic data below. Local keeps everything "
                 "on this PC.",
        ).pack(anchor="w")
        link = ttk.Label(box, text="Read the privacy policy", cursor="hand2",
                         foreground=self._link, takefocus=True)
        link.pack(anchor="w", pady=(4, 0))
        open_policy = lambda e=None: webbrowser.open(config.PRIVACY_URL)  # noqa: E731
        for seq in ("<Button-1>", "<Return>", "<space>"):
            link.bind(seq, open_policy)

        diag = self._section(f, "Diagnostic data")
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
            diag, wraplength=560, style="Muted.TLabel",
            text="Diagnostic data is what you said, what was typed, and the "
                 "recording of each dictation. It goes to Sumit only, is "
                 "kept for 30 days, then deleted. Your diagnostic ID: "
                 + feedback.install_id()[:8],
        ).pack(anchor="w", pady=(4, 0))

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
            "cleanup_mode": self.var_cleanup.get(),
            "enable_history": self.var_history.get(),
            "insert_mode": self.var_insert.get(),
            "append_space": self.var_space.get(),
            "press_enter_after": self.var_enter.get(),
            "hotkey_mode": self.var_hotkey_mode.get(),
            "dictionary": dictionary,
        }
        problem = _hotkey_problem(
            self.pending_hotkey or _key_names(config.HOTKEY),
            self.pending_dev_hotkey if self.pending_dev_hotkey is not None
            else _key_names(config.DEV_HOTKEY),
        )
        if problem:
            # Keep the current keys; everything else still saves.
            messagebox.showwarning(APP_NAME, problem, parent=self.root)
            self.pending_hotkey = None
            self.pending_dev_hotkey = None
            self.hotkey_btn.config(text=_hotkey_display(config.HOTKEY))
            self.dev_hotkey_btn.config(
                text=_hotkey_display(config.DEV_HOTKEY) if config.DEV_HOTKEY else "Not set")
        if self.pending_hotkey:
            values["hotkey"] = self.pending_hotkey
        if self.pending_dev_hotkey is not None:
            values["dev_hotkey"] = self.pending_dev_hotkey
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
