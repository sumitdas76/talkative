"""
First-run "Cloud or Local" onboarding screen.

Shown once, before cloud_notice.py's Cloud explainer and try_it_now.py's
dictation demo, so every user -- a fresh install or someone upgrading from
before this existed -- makes an explicit, informed choice between Cloud
and Local instead of silently inheriting config.PROCESSING_MODE's "cloud"
default. Non-blocking by design: the app starts up under whatever
PROCESSING_MODE is already configured (Cloud, normally) while this screen
is open, so dictation works immediately even before the user answers it.
If they pick Local, both models are downloaded right here (blocking this
window with a progress bar) so onboarding hands off a fully working
offline setup, not a half-configured one requiring a second trip to
Settings for the grammar engine.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real crashes),
not its own Tk instance. Closing it (X button) is treated the same as
clicking Continue with whatever's currently selected -- it never blocks
the app waiting for an answer.
"""

import threading

from . import app_icon, config, grammar_engine, model_manager, overlay_thread, settings

_opened = False
_lock = threading.Lock()


def maybe_show(on_choice=None):
    """Show the screen if onboarding hasn't happened yet; otherwise no-op.
    on_choice(mode) is called with "cloud" or "local" once the user
    finishes, so the caller can re-sync processing/model state to match."""
    global _opened
    if config.ONBOARDING_DONE:
        return
    with _lock:
        if _opened:
            return
        _opened = True

    overlay = overlay_thread.get()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        _mark_done()
        return
    overlay.build(lambda: _build(overlay, on_choice))


def _mark_done():
    try:
        config.ONBOARDING_DONE = True
        settings.save({"onboarding_done": True})
    except Exception:
        pass


def _build(overlay, on_choice):
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Toplevel(overlay.root)
        root.title("Talkative")
        app_icon.set_window_icon(root)
        root.configure(bg=overlay_thread.bg_color())
        root.resizable(False, False)
        root.attributes("-topmost", True)

        ttk.Label(
            root, padding=(18, 16, 18, 6), font=("Segoe UI", 12, "bold"),
            text="Choose how Talkative processes your dictation",
        ).pack(anchor="w")

        def bullets(parent, items):
            for item in items:
                row = ttk.Frame(parent)
                row.pack(fill="x", anchor="w", pady=(4, 0))
                ttk.Label(row, text="•", foreground="grey").pack(side="left", anchor="n")
                ttk.Label(
                    row, wraplength=440, foreground="grey", text=item,
                ).pack(side="left", padx=(6, 0), anchor="w")

        mode = tk.StringVar(value=config.PROCESSING_MODE)

        cloud_box = ttk.LabelFrame(root, text="Cloud", padding=12)
        cloud_box.pack(fill="x", padx=18, pady=(6, 6))
        ttk.Radiobutton(
            cloud_box, text="Online",
            variable=mode, value="cloud",
        ).pack(anchor="w")
        bullets(cloud_box, [
            "Uses no extra RAM or disk.",
            "Your dictation audio is sent to a remote server to be processed.",
        ])

        local_box = ttk.LabelFrame(root, text="Local", padding=12)
        local_box.pack(fill="x", padx=18, pady=(6, 6))
        ttk.Radiobutton(
            local_box, text="Fully offline",
            variable=mode, value="local",
        ).pack(anchor="w")
        bullets(local_box, [
            "Everything stays private. Your voice and text never leave "
            "this device, and nothing is sent over the internet.",
            "Ready to dictate after a one-time 0.5 GB download. Optimize "
            "Narration (1.5 GB more) then finishes downloading in the "
            "background while you work.",
            "Uses about 2.3 GB of memory while Talkative runs: best with "
            "16 GB of RAM, works on 8 GB. No internet is needed after "
            "the downloads.",
        ])

        status = ttk.Label(root, padding=(18, 4, 18, 0), foreground="grey", wraplength=480)
        status.pack(anchor="w")
        bar = ttk.Progressbar(root, mode="indeterminate", length=300)

        button_frame = ttk.Frame(root, padding=(18, 12, 18, 14))
        button_frame.pack(fill="x", side="bottom")
        continue_btn = ttk.Button(button_frame, text="Continue")
        continue_btn.pack(side="right")

        state = {"busy": False}

        def finish(chosen_mode):
            config.PROCESSING_MODE = chosen_mode
            values = {"processing_mode": chosen_mode}
            if chosen_mode == "cloud":
                # This screen already explained Cloud -- don't show the
                # separate one-time cloud_notice.py notice on top of it.
                config.CLOUD_NOTICE_DONE = True
                values["cloud_notice_done"] = True
            settings.save(values)
            _mark_done()
            root.destroy()
            if on_choice:
                on_choice(chosen_mode)

        def finish_local():
            if not grammar_engine.is_installed():
                config.GRAMMAR_PENDING_DOWNLOAD = True
                settings.save({"grammar_pending_download": True})
            finish("local")
            if config.GRAMMAR_PENDING_DOWNLOAD:
                grammar_engine.download_in_background()

        def on_continue():
            if state["busy"]:
                # Changed their mind mid-download (slow connection, slow
                # laptop): let them go with Cloud now instead of being
                # stuck in this window until Local finishes -- a user
                # reported being unable to get back to Cloud (2026-10-04).
                # The download carries on in the background; nothing waits
                # for it.
                if mode.get() == "cloud":
                    state["busy"] = False
                    state["cancelled"] = True
                    finish("cloud")
                return
            chosen = mode.get()
            if chosen != "local":
                finish("cloud")
                return
            if model_manager.is_downloaded(config.MODEL_SIZE):
                finish_local()
                return

            # Only the voice model is waited for: with it, dictation works
            # (rules-only cleanup); the 1.5 GB grammar model follows in the
            # background (finish_local). Minutes sooner for someone who
            # needs to dictate now (2026-09-27).
            # Approximate size (measured live, 2026-09-19) -- used only as
            # a progress-bar denominator, not for exact accounting. Real
            # per-file byte callbacks would need hooking huggingface_hub's
            # internals; polling disk usage against a known rough total is
            # far simpler and good enough for a progress indicator.
            needed_mb = 464
            baseline_mb = model_manager.storage_used_mb()

            state["busy"] = True
            continue_btn.config(state="disabled", text="Downloading…")
            bar.config(mode="determinate", maximum=max(needed_mb, 1), value=0)
            bar.pack(fill="x", padx=18, pady=(0, 8), before=button_frame)

            def poll_progress():
                if not state["busy"]:
                    return
                done_mb = max(0.0, model_manager.storage_used_mb() - baseline_mb)
                done_mb = min(done_mb, needed_mb)
                bar.config(value=done_mb)
                pct = int(done_mb / needed_mb * 100) if needed_mb else 100
                status.config(
                    foreground="grey",
                    text=f"Getting dictation ready... {pct}% "
                         f"({int(done_mb)} MB of {needed_mb} MB). "
                         "Changed your mind? Choose Online above to "
                         "start with Cloud right away.",
                )
                root.after(500, poll_progress)

            poll_progress()

            def work():
                error = None
                try:
                    model_manager.download(config.MODEL_SIZE)
                except Exception as exc:
                    error = exc

                def done():
                    if state.get("cancelled"):
                        return  # the user went with Cloud; window is gone
                    state["busy"] = False
                    bar.pack_forget()
                    if error is not None:
                        continue_btn.config(state="normal", text="Continue")
                        status.config(
                            foreground="red",
                            text=f"Download failed: {error}. Check your "
                                 "connection and try again, or pick Cloud.",
                        )
                        return
                    finish_local()

                if state.get("cancelled"):
                    return
                try:
                    root.after(0, done)
                except Exception:
                    pass  # window already closed

            threading.Thread(target=work, daemon=True).start()

        def on_mode_change(*_):
            if not state["busy"]:
                return
            if mode.get() == "cloud":
                continue_btn.config(state="normal", text="Use Cloud instead")
            else:
                continue_btn.config(state="disabled", text="Downloading…")

        mode.trace_add("write", on_mode_change)
        continue_btn.config(command=on_continue)
        root.protocol("WM_DELETE_WINDOW", on_continue)
    except Exception:
        _mark_done()
