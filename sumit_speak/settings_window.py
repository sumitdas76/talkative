"""
Tabbed settings window (tkinter), opened from the tray menu.

Reads current config values, writes settings.json via settings.save, then
re-applies with settings.load_into_config and notifies the app through the
on_applied callback. Runs in its own thread with its own Tk instance --
only that thread touches tkinter objects. A second open request while the
window exists is ignored.
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from pynput import keyboard

from . import __version__, config, model_manager, settings, updater

APP_NAME = "Sumit Speak"

_open_lock = threading.Lock()
_is_open = False

_EXAMPLE_SPOKEN = "“So um, send the file today — oh sorry, send the file by this evening.”"
_EXAMPLE_CLEAN = "Send the file by this evening."
_EXAMPLE_ASIS = "So um, send the file today — oh sorry, send the file by this evening."


def open_settings(on_applied=None, model_controller=None):
    global _is_open
    with _open_lock:
        if _is_open:
            return
        _is_open = True

    def _run():
        global _is_open
        try:
            _SettingsWindow(on_applied, model_controller).run()
        finally:
            with _open_lock:
                _is_open = False

    threading.Thread(target=_run, daemon=True).start()


def _hotkey_display(key):
    name = getattr(key, "name", None)
    if name:
        return name
    return getattr(key, "char", "?") or "?"


class _SettingsWindow:
    def __init__(self, on_applied, model_controller=None):
        self.on_applied = on_applied
        self.model_controller = model_controller
        self.pending_hotkey = None
        self._capturing = False

    def run(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} — Settings")
        self.root.geometry("600x480")
        self.root.minsize(520, 420)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        for name, builder in [
            ("General", self._tab_general),
            ("Dictionary", self._tab_dictionary),
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
        ttk.Button(bar, text="Close", command=self.root.destroy).pack(side="right")
        ttk.Button(bar, text="Save and apply", command=self._save).pack(side="right", padx=6)

        self.root.mainloop()

    # ---------------- tabs ----------------

    def _tab_general(self, f):
        self.var_autostart = tk.BooleanVar(value=config.START_WITH_WINDOWS)
        self.var_sounds = tk.BooleanVar(value=config.PLAY_SOUNDS)
        ttk.Checkbutton(
            f, text=f"Start “{APP_NAME}” when Windows starts",
            variable=self.var_autostart,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            f, text="Play a sound when recording starts and stops",
            variable=self.var_sounds,
        ).pack(anchor="w", pady=4)

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
        self.var_cleanup = tk.StringVar(value=config.CLEANUP_MODE)
        ttk.Radiobutton(
            f, text="Cleaned up — slips and repetitions removed. "
                    "Your meaning is never changed.",
            variable=self.var_cleanup, value="cleaned_up",
            command=self._update_example,
        ).pack(anchor="w", pady=4)
        ttk.Radiobutton(
            f, text="As spoken — exactly what you said, word for word.",
            variable=self.var_cleanup, value="as_spoken",
            command=self._update_example,
        ).pack(anchor="w", pady=4)

        box = ttk.LabelFrame(f, text="Example", padding=10)
        box.pack(fill="x", pady=12)
        ttk.Label(box, text="You said:").pack(anchor="w")
        ttk.Label(box, text=_EXAMPLE_SPOKEN, wraplength=500,
                  foreground="grey").pack(anchor="w", pady=(0, 6))
        ttk.Label(box, text="Appears on screen:").pack(anchor="w")
        self.example_label = ttk.Label(box, text="", wraplength=500)
        self.example_label.pack(anchor="w")
        self._update_example()

    def _update_example(self):
        clean = self.var_cleanup.get() == "cleaned_up"
        self.example_label.config(text=_EXAMPLE_CLEAN if clean else _EXAMPLE_ASIS)

    def _tab_hotkeys(self, f):
        ttk.Label(f, text="Dictation key (hold to talk):").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=6)
        self.hotkey_btn = ttk.Button(
            row, text=_hotkey_display(config.HOTKEY), command=self._capture_hotkey
        )
        self.hotkey_btn.pack(side="left")
        ttk.Label(row, text="  Click, then press the key you want to use.",
                  foreground="grey").pack(side="left")
        ttk.Label(
            f, wraplength=520, foreground="grey",
            text="\nHold the key while speaking; release to insert the text. "
                 "A press-to-toggle mode is planned for a later version.",
        ).pack(anchor="w")

    def _capture_hotkey(self):
        if self._capturing:
            return
        self._capturing = True
        self.hotkey_btn.config(text="Press a key…")

        def on_press(key):
            name = getattr(key, "name", None) or getattr(key, "char", None)
            if name:
                self.pending_hotkey = name
                self.root.after(0, lambda: self.hotkey_btn.config(text=name))
            self._capturing = False
            return False  # stop this capture listener

        keyboard.Listener(on_press=on_press).start()

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
        for tier, info in model_manager.MODELS.items():
            box = ttk.LabelFrame(
                f, text=f"{info['label']} — {info['tagline']}", padding=10
            )
            box.pack(fill="x", pady=(0, 10))
            ttk.Label(box, text=info["latency"], foreground="grey",
                      wraplength=500).pack(anchor="w")
            status = ttk.Label(box, text="")
            status.pack(anchor="w")
            bar = ttk.Progressbar(box, mode="indeterminate", length=240)
            row = ttk.Frame(box)
            row.pack(anchor="w", pady=(6, 0))
            action = ttk.Button(row)
            delete = ttk.Button(
                row, text="Delete",
                command=lambda t=tier, i=info: self._model_delete(t, i),
            )
            self._tiles[tier] = {
                "info": info, "status": status, "bar": bar,
                "action": action, "delete": delete, "state": None,
            }
        self.storage_label = ttk.Label(f, foreground="grey", text="")
        self.storage_label.pack(anchor="w", pady=(4, 0))
        self.update_label = ttk.Label(f, foreground="grey", text="")
        self.update_label.pack(anchor="w")
        self.undo_btn = ttk.Button(
            f, text="Undo last update", command=self._undo_update
        )
        self._undoing = False
        self._poll_models()

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
            status.config(text="In use ✓")
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

    def _poll_models(self):
        for tier in self._tiles:
            self._render_model_tile(tier)
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
        other_tier = next(t for t in model_manager.MODELS if t != tier)
        other = model_manager.MODELS[other_tier]

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

        if model_manager.is_downloaded(other["size"]):
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
                 "this PC. Audio is transcribed locally and never saved.",
        ).pack(anchor="w")

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
            "cleanup_mode": self.var_cleanup.get(),
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

        settings.save(values)
        settings.load_into_config()
        if self.on_applied:
            self.on_applied()

        self.saved_label.config(text="Saved ✓")
        self.root.after(2500, lambda: self.saved_label.config(text=""))
