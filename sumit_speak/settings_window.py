"""
Tabbed settings window (tkinter), opened from the tray menu.

Reads current config values, writes settings.json via settings.save, then
re-applies with settings.load_into_config and notifies the app through the
on_applied callback. Built as a tk.Toplevel on the shared overlay thread
(see overlay_thread.py -- multiple independent tk.Tk() roots across
threads caused real crashes), not its own Tk instance; only that thread
touches tkinter objects. A second open request while the window exists is
ignored.
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from pynput import keyboard
from PIL import Image, ImageDraw, ImageTk

from . import __version__, app_icon, config, feedback, grammar_engine, history, model_manager, overlay_thread, settings, updater
from .keynames import friendly as _friendly_key_name

APP_NAME = "Sumit Speak"

_open_lock = threading.Lock()
_is_open = False

_EXAMPLE_SPOKEN = "“So um, send the file today — oh sorry, send the file by this evening.”"
_EXAMPLE_CLEAN = "Send the file by this evening."
_EXAMPLE_ASIS = "So um, send the file today — oh sorry, send the file by this evening."

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


def _on_closed():
    global _is_open
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


def _hotkey_display(key):
    return _friendly_key_name(key)


class _SettingsWindow:
    def __init__(self, on_applied, model_controller, overlay):
        self.on_applied = on_applied
        self.model_controller = model_controller
        self.overlay = overlay
        self.pending_hotkey = None
        self._capturing = False

    def build(self):
        self.root = tk.Toplevel(self.overlay.root)
        self.root.title(f"{APP_NAME} — Settings")
        app_icon.set_window_icon(self.root)
        self.root.geometry("600x480")
        self.root.minsize(520, 420)
        self._apply_theme()

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        for name, builder in [
            ("General", self._tab_general),
            ("Auto Text", self._tab_dictionary),
            ("Dictation", self._tab_dictation),
            ("Hotkeys", self._tab_hotkeys),
            ("Audio", self._tab_audio),
            ("Output", self._tab_output),
            ("Models", self._tab_models),
            ("About", self._tab_about),
        ]:
            frame = ttk.Frame(nb, padding=14)
            nb.add(frame, text=name)
            builder(frame)

        bar = ttk.Frame(self.root, padding=(10, 4, 10, 10))
        bar.pack(fill="x")
        self.saved_label = ttk.Label(bar, text="")
        self.saved_label.pack(side="left")
        ttk.Button(bar, text="Close", command=self._close).pack(side="right")
        ttk.Button(bar, text="Save and apply", command=self._save).pack(side="right", padx=6)

        self.root.protocol("WM_DELETE_WINDOW", self._close)

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
        if self._effective_theme() == "dark":
            bg, fg, field, raised = "#2b2b2b", "#e6e6e6", "#3c3c3c", "#454545"
            border, hover = "#555555", "#5a5a5a"
        else:
            bg, fg, field, raised = "#f0f0f0", "#1a1a1a", "#ffffff", "#dcdcdc"
            border, hover = "#b0b0b0", "#cccccc"
        accent, accent_fg = "#4682b4", "#ffffff"  # steel blue, matches the tray icon

        self.root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg,
                        fieldbackground=field, bordercolor=border,
                        lightcolor=bg, darkcolor=bg)
        # The selected tab: accent color, white bold label, slightly taller.
        style.configure("TNotebook.Tab", background=raised, foreground=fg,
                        padding=(12, 5), font=("Segoe UI", 9))
        style.map(
            "TNotebook.Tab",
            background=[("selected", accent), ("active", hover)],
            foreground=[("selected", accent_fg)],
            font=[("selected", ("Segoe UI", 9, "bold"))],
            expand=[("selected", (1, 1, 1, 0))],
        )
        style.configure("TButton", background=raised)
        style.map(
            "TButton",
            background=[("disabled", raised), ("active", hover)],
            foreground=[("disabled", border)],
        )
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
        style.map(
            "TRadiobutton",
            background=[("active", bg)],
            foreground=[("disabled", border)],
        )
        style.configure("Treeview", background=field, foreground=fg,
                        fieldbackground=field)
        style.configure("Treeview.Heading", background=raised, foreground=fg)
        style.map("Treeview.Heading", background=[("active", hover)])
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
        self._bg, self._fg, self._field = bg, fg, field
        # feedback_text is a raw tk.Text (not ttk), so it needs its colors
        # reapplied by hand on every theme switch, not just at creation.
        if hasattr(self, "feedback_text"):
            self.feedback_text.configure(
                bg=field, fg=fg, insertbackground=fg,
                selectbackground=accent, selectforeground=accent_fg,
            )

    # ---------------- tabs ----------------

    def _tab_general(self, f):
        self.var_autostart = tk.BooleanVar(value=config.START_WITH_WINDOWS)
        self.var_sounds = tk.BooleanVar(value=config.PLAY_SOUNDS)
        self.var_theme = tk.StringVar(value=config.THEME)
        ttk.Checkbutton(
            f, text=f"Start “{APP_NAME}” when Windows starts",
            variable=self.var_autostart,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            f, text="Play sounds when recording starts, stops, and when "
                    "text is inserted",
            variable=self.var_sounds,
        ).pack(anchor="w", pady=4)

        box = ttk.LabelFrame(f, text="Appearance", padding=10)
        box.pack(fill="x", pady=(10, 0))
        for label, value in [("Light", "light"), ("Dark", "dark"),
                             ("Follow Windows setting", "system")]:
            ttk.Radiobutton(
                box, text=label, variable=self.var_theme, value=value,
                command=self._theme_changed,
            ).pack(anchor="w", pady=2)

    def _theme_changed(self):
        config.THEME = self.var_theme.get()
        self._apply_theme()

    def _tab_dictionary(self, f):
        ttk.Label(
            f, wraplength=520,
            text=f"When you say the word on the left, “{APP_NAME}” "
                 "types the text on the right.",
        ).pack(anchor="w")

        self.dict_tree = ttk.Treeview(
            f, columns=("spoken", "typed"), show="headings", height=8
        )
        self.dict_tree.heading("spoken", text="Spoken")
        self.dict_tree.heading("typed", text="Typed")
        self.dict_tree.column("spoken", width=160)
        self.dict_tree.column("typed", width=300)
        self.dict_tree.pack(fill="both", expand=True, pady=8)
        for spoken, typed in config.DICTIONARY.items():
            self.dict_tree.insert("", "end", values=(spoken, typed))

        row = ttk.Frame(f)
        row.pack(fill="x")
        self.dict_spoken = ttk.Entry(row, width=18)
        self.dict_spoken.pack(side="left")
        ttk.Label(row, text=" → ").pack(side="left")
        self.dict_typed = ttk.Entry(row, width=32)
        self.dict_typed.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Add", command=self._dict_add).pack(side="left", padx=6)
        ttk.Button(row, text="Remove selected", command=self._dict_remove).pack(side="left")

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

    def _tab_dictation(self, f):
        cleanup_box = ttk.LabelFrame(f, text="Dictation style", padding=10)
        cleanup_box.pack(fill="x")
        self.var_cleanup = tk.StringVar(value=config.CLEANUP_MODE)
        ttk.Radiobutton(
            cleanup_box, text="Cleaned up — slips and repetitions removed. "
                    "Your meaning is never changed.",
            variable=self.var_cleanup, value="cleaned_up",
            command=self._update_example,
        ).pack(anchor="w", pady=4)
        ttk.Radiobutton(
            cleanup_box, text="As spoken — exactly what you said, word for word.",
            variable=self.var_cleanup, value="as_spoken",
            command=self._update_example,
        ).pack(anchor="w", pady=4)

        example_box = ttk.LabelFrame(cleanup_box, text="Example", padding=10)
        example_box.pack(fill="x", pady=(8, 0))
        ttk.Label(example_box, text="You said:").pack(anchor="w")
        ttk.Label(example_box, text=_EXAMPLE_SPOKEN, wraplength=480,
                  foreground="grey").pack(anchor="w", pady=(0, 6))
        ttk.Label(example_box, text="Appears on screen:").pack(anchor="w")
        self.example_label = ttk.Label(example_box, text="", wraplength=480)
        self.example_label.pack(anchor="w")
        self._update_example()

        history_box = ttk.LabelFrame(f, text="History", padding=10)
        history_box.pack(fill="x", pady=(16, 0))
        self.var_history = tk.BooleanVar(value=config.ENABLE_HISTORY)
        ttk.Checkbutton(
            history_box, text="Keep a history of what I've dictated",
            variable=self.var_history,
        ).pack(anchor="w")
        ttk.Label(
            history_box, foreground="grey",
            text="Saved only on this device. Nothing is sent anywhere.",
        ).pack(anchor="w", pady=(2, 8))
        ttk.Button(
            history_box, text="View history…", command=self._open_history_viewer,
        ).pack(anchor="w")

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
        ttk.Label(f, text="Dictation key(s) (hold to talk):").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=6)
        self.hotkey_btn = ttk.Button(
            row, text=_hotkey_display(config.HOTKEY), command=self._capture_hotkey
        )
        self.hotkey_btn.pack(side="left")
        ttk.Label(row, text="  Click, then hold the key (or two keys "
                            "together) you want to use.",
                  foreground="grey").pack(side="left")
        ttk.Label(
            f, wraplength=520, foreground="grey",
            text="\nHold the key (or key combination) while speaking; "
                 "release to insert the text.",
        ).pack(anchor="w")

    def _capture_hotkey(self):
        if self._capturing:
            return
        self._capturing = True
        self.hotkey_btn.config(text="Hold 1 or 2 keys…")

        pressed = []   # currently-held key names during this capture, max 2
        chosen = []    # the largest simultaneous combination seen so far

        def refresh():
            shown = " + ".join(_friendly_key_name(n) for n in pressed)
            text = shown if shown else "Hold 1 or 2 keys…"
            self.root.after(0, lambda: self.hotkey_btn.config(text=text))

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
            self.pending_hotkey = list(chosen)
            self._capturing = False
            return False  # stop this capture listener

        keyboard.Listener(on_press=on_press, on_release=on_release).start()

    def _tab_audio(self, f):
        ttk.Label(f, text="Microphone:").pack(anchor="w")
        self._audio_values = [None]
        names = ["System default"]
        try:
            import sounddevice as sd

            for index, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0:
                    self._audio_values.append(index)
                    names.append(f"{dev['name']}")
        except Exception:
            pass

        self.audio_combo = ttk.Combobox(f, values=names, state="readonly", width=48)
        try:
            self.audio_combo.current(self._audio_values.index(config.INPUT_DEVICE))
        except ValueError:
            self.audio_combo.current(0)
        self.audio_combo.pack(anchor="w", pady=6)
        ttk.Label(
            f, wraplength=520, foreground="grey",
            text="If dictation hears nothing, the wrong microphone is "
                 "selected. Takes effect from the next dictation.",
        ).pack(anchor="w")

        ttk.Label(f, text="Output device:").pack(anchor="w", pady=(14, 0))
        self._output_values = [None]
        out_names = ["System default"]
        try:
            import sounddevice as sd

            for index, dev in enumerate(sd.query_devices()):
                if dev.get("max_output_channels", 0) > 0:
                    self._output_values.append(index)
                    out_names.append(f"{dev['name']}")
        except Exception:
            pass

        self.output_combo = ttk.Combobox(f, values=out_names, state="readonly", width=48)
        try:
            self.output_combo.current(self._output_values.index(config.OUTPUT_DEVICE))
        except ValueError:
            self.output_combo.current(0)
        self.output_combo.pack(anchor="w", pady=6)
        ttk.Label(
            f, wraplength=520, foreground="grey",
            text="Where dictation tones and spoken messages play — "
                 "headphones, Bluetooth earphones, speakers.",
        ).pack(anchor="w")

    def _tab_output(self, f):
        self.var_insert = tk.StringVar(value=config.INSERT_MODE)
        self.var_space = tk.BooleanVar(value=config.APPEND_SPACE)
        self.var_enter = tk.BooleanVar(value=config.PRESS_ENTER_AFTER)

        box1 = ttk.LabelFrame(f, text="Destination", padding=10)
        box1.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(box1, text="Type into the active application",
                        variable=self.var_insert, value="type").pack(anchor="w", pady=2)
        ttk.Radiobutton(box1, text="Copy to clipboard only",
                        variable=self.var_insert, value="clipboard").pack(anchor="w", pady=2)

        box2 = ttk.LabelFrame(f, text="After dictation", padding=10)
        box2.pack(fill="x")
        ttk.Checkbutton(box2, text="Add a space after the inserted text",
                        variable=self.var_space).pack(anchor="w", pady=2)
        ttk.Checkbutton(box2, text="Press Enter after inserting the text",
                        variable=self.var_enter).pack(anchor="w", pady=2)
        ttk.Label(
            f, wraplength=520, foreground="grey",
            text="\nUndo: press Ctrl+Z in the target application — each "
                 "dictation is inserted as a single edit.",
        ).pack(anchor="w")

    # Models tab. Worker threads only write _model_ops / _model_errors;
    # a ~300ms poll loop on the Tk thread reads them and is the only thing
    # that touches widgets.

    def _tab_models(self, f):
        self._model_ops = {}     # tier -> "download" | "load" | "delete"
        self._model_errors = []  # messages appended by workers, shown by the poll
        self._tiles = {}

        tiles_row = ttk.Frame(f)
        tiles_row.pack(fill="x", pady=(0, 10))
        # Column count follows however many tiers exist (just Fast right
        # now, since Accurate was removed) rather than assuming two, so a
        # single tile spans the full width instead of leaving an awkward
        # empty half.
        n_tiles = len(model_manager.MODELS)
        for col in range(max(n_tiles, 1)):
            tiles_row.columnconfigure(col, weight=1)
        for col, (tier, info) in enumerate(model_manager.MODELS.items()):
            box = ttk.LabelFrame(
                tiles_row, text=f"{info['label']} - {info['tagline']}", padding=10
            )
            pad = 0 if n_tiles == 1 else ((0, 6) if col == 0 else (6, 0))
            box.grid(row=0, column=col, sticky="nsew", padx=pad)
            latency = ttk.Label(box, text=info["latency"], foreground="grey",
                                 wraplength=220)
            latency.pack(anchor="w")
            version_label = ttk.Label(box, text="", foreground="grey")
            version_label.pack(anchor="w")
            status = ttk.Label(box, text="")
            status.pack(anchor="w")
            bar = ttk.Progressbar(box, mode="indeterminate", length=180)
            btn_row = ttk.Frame(box)
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

        self._build_grammar_section(f)

        self.storage_label = ttk.Label(f, foreground="grey", text="")
        self.storage_label.pack(anchor="w", pady=(4, 0))
        self.update_label = ttk.Label(f, foreground="grey", text="")
        self.update_label.pack(anchor="w")
        self.undo_btn = ttk.Button(
            f, text="Undo last update", command=self._undo_update
        )
        self._undoing = False
        self._poll_models()

    def _build_grammar_section(self, f):
        box = ttk.LabelFrame(f, text="Optimize Narration", padding=10)
        box.pack(fill="x", pady=(0, 10))
        ttk.Label(
            box,
            text="Fix grammar and punctuation",
            foreground="grey", wraplength=500,
        ).pack(anchor="w")
        status = ttk.Label(box, text="")
        status.pack(anchor="w")
        bar = ttk.Progressbar(box, mode="indeterminate", length=240)
        btn_row = ttk.Frame(box)
        btn_row.pack(anchor="w", pady=(6, 0))
        delete = ttk.Button(btn_row, text="Delete", command=self._grammar_delete)
        self._grammar_tile = {
            "box": box, "status": status, "bar": bar, "delete": delete, "state": None,
        }
        self._grammar_op = None

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

        box = tile["box"]
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
        return "installed" if grammar_engine.is_installed() else "none"

    def _render_grammar_tile(self):
        tile = self._grammar_tile
        state = self._grammar_tile_state()
        if state == tile["state"]:
            return
        tile["state"] = state

        bar, status, delete = tile["bar"], tile["status"], tile["delete"]
        delete.pack_forget()
        if state == "delete":
            status.config(text="Deleting…")
            bar.pack(anchor="w", pady=(4, 0))
            bar.start(12)
            return
        bar.stop()
        bar.pack_forget()

        if state == "none":
            status.config(
                text="Not installed. Cleaned-up dictations use basic rules "
                     "only. Reinstalling Sumit Speak restores this."
            )
        else:  # installed
            status.config(text="Installed.")
            delete.pack(side="left")

    def _grammar_delete(self):
        if not messagebox.askyesno(
            APP_NAME,
            "Remove the Optimize Narration files?\n\n"
            "This frees about 1.5 GB. “Cleaned up” dictations will keep "
            "working with basic rules only. There is no in-app way to "
            "bring this back — you would need to reinstall Sumit Speak.",
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
        while self._model_errors:
            messagebox.showerror(APP_NAME, self._model_errors.pop(0), parent=self.root)
        self.storage_label.config(
            text=f"Storage used by models: {model_manager.storage_used_mb():.0f} MB"
        )
        status = updater.get_status()
        if status["downloading"]:
            self.update_label.config(text="An update is downloading in the background…")
        elif status["last_check"]:
            self.update_label.config(text=f"Last checked for updates: {status['last_check']}")
        else:
            self.update_label.config(text="Updates are checked automatically at startup.")
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

        if messagebox.askyesno(
            APP_NAME,
            f"The {info['label']} model is the only model downloaded.\n\n"
            "Deleting it turns dictation off until you download a model "
            "again. Delete anyway?",
            icon="warning", parent=self.root,
        ):
            self.model_controller.unload()
            self._model_delete_worker(tier, size)

    def _tab_about(self, f):
        ttk.Label(f, text=f"“{APP_NAME}”").pack(anchor="w")
        ttk.Label(f, text=f"Version {__version__}").pack(anchor="w", pady=(0, 10))
        box = ttk.LabelFrame(f, text="Privacy", padding=10)
        box.pack(fill="x")
        ttk.Label(
            box, wraplength=500,
            text="Dictation is fully offline — your voice never leaves "
                 "this PC. Audio is transcribed locally and never saved. "
                 "Dictation history, if you turn it on in the Dictation "
                 "tab, is also stored only on this device. The one "
                 "exception is the Feedback box below: nothing is sent "
                 "unless you type a message and click Send.",
        ).pack(anchor="w")

        self._build_feedback_section(f)

    def _build_feedback_section(self, f):
        box = ttk.LabelFrame(f, text="Feedback", padding=10)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(
            box, wraplength=500, foreground="grey",
            text="Send a message straight to Sumit. A reply, if there is "
                 "one, will show up here.",
        ).pack(anchor="w")
        self.feedback_text = tk.Text(
            box, height=4, wrap="word", font=("Segoe UI", 9),
            bg=self._field, fg=self._fg, insertbackground=self._fg,
            selectbackground=self._accent, selectforeground=self._accent_fg,
            relief="solid", borderwidth=1,
        )
        self.feedback_text.pack(fill="x", pady=(6, 4))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        self.feedback_send_btn = ttk.Button(
            row, text="Send", command=self._send_feedback
        )
        self.feedback_send_btn.pack(side="left")
        self.feedback_status = ttk.Label(row, text="", foreground="grey")
        self.feedback_status.pack(side="left", padx=8)

        if config.FEEDBACK_LAST_REPLY:
            reply_box = ttk.Frame(box)
            reply_box.pack(fill="x", pady=(10, 0))
            ttk.Label(reply_box, text="Sumit replied:",
                      font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Label(reply_box, text=config.FEEDBACK_LAST_REPLY,
                      wraplength=500).pack(anchor="w")

    def _send_feedback(self):
        message = self.feedback_text.get("1.0", "end").strip()
        if not message:
            return
        self.feedback_send_btn.config(state="disabled")
        self.feedback_status.config(text="Sending…")

        def done(ok, error):
            def update():
                self.feedback_send_btn.config(state="normal")
                if ok:
                    self.feedback_status.config(text="Sent ✓")
                    self.feedback_text.delete("1.0", "end")
                else:
                    self.feedback_status.config(
                        text="Could not send. Please try again later."
                    )
            self.root.after(0, update)

        feedback.send(message, on_done=done)

    # ---------------- save ----------------

    def _save(self):
        dictionary = {}
        for item in self.dict_tree.get_children():
            spoken, typed = self.dict_tree.item(item, "values")
            if spoken and typed:
                dictionary[spoken] = typed

        values = {
            "start_with_windows": self.var_autostart.get(),
            "play_sounds": self.var_sounds.get(),
            "theme": self.var_theme.get(),
            "cleanup_mode": self.var_cleanup.get(),
            "enable_history": self.var_history.get(),
            "insert_mode": self.var_insert.get(),
            "append_space": self.var_space.get(),
            "press_enter_after": self.var_enter.get(),
            "dictionary": dictionary,
        }
        if self.pending_hotkey:
            values["hotkey"] = self.pending_hotkey
        try:
            values["input_device"] = self._audio_values[self.audio_combo.current()]
        except Exception:
            pass
        try:
            values["output_device"] = self._output_values[self.output_combo.current()]
        except Exception:
            pass

        settings.save(values)
        settings.load_into_config()
        if self.on_applied:
            self.on_applied()

        self.saved_label.config(text="Saved ✓")
        self.root.after(2500, lambda: self.saved_label.config(text=""))
