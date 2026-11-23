"""Anonymous count of active installs (Backlog usage-count, 2026-11-23;
PRIVACY.md "Counting installs").

Only with the user's yes (config.USAGE_COUNT): asked once, on the first-run
screen or, for installs from before this existed, in a small window after
the update. Nothing is sent before an answer or after a no.

Once a UTC day the check-in posts to the Worker's /usage route: a random
code made for this count alone (config.USAGE_ID, never sent with
dictation, feedback or diagnostics -- not the install ID, which the Worker
could link to Cloud requests and feedback), the version, Cloud / own key /
Local, and installer / store / source. No X-Install-Id header.

TALKATIVE_NO_USAGE=1 turns it off for tests and release QA, so throwaway
first-run folders aren't counted.
"""

import json
import logging
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timezone

from . import __version__, config, packaging, settings

log = logging.getLogger(__name__)

_START_DELAY = 15     # seconds after startup, after the update check's 10
_POLL_SECONDS = 1800  # how often a running app looks whether a check-in is due
_TIMEOUT = 10
_asked_this_run = False
_lock = threading.Lock()

QUESTION = ("Help count how many people use Talkative? Once a day it sends a "
            "random code made only for this count, the app version, and "
            "Cloud or Local. Nothing you dictate. Change it any time in "
            "Settings > About.")
YES = "Yes, count me"
NO = "No thanks"


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def disabled_by_env():
    return os.environ.get("TALKATIVE_NO_USAGE") == "1"


def set_answer(yes):
    """Record the user's answer (first-run screen, the one-time window, or
    the Settings switch). A yes makes the random code if there isn't one."""
    values = {"usage_asked": True, "usage_count": bool(yes)}
    config.USAGE_ASKED = True
    config.USAGE_COUNT = bool(yes)
    if yes and not config.USAGE_ID:
        config.USAGE_ID = secrets.token_hex(32)
        values["usage_id"] = config.USAGE_ID
    settings.save(values)


def short_code():
    """First 8 characters of the code, for Settings > About (deletion
    requests), or "" before there is one."""
    return config.USAGE_ID[:8]


def mode():
    if config.PROCESSING_MODE != "cloud":
        return "local"
    try:
        from . import groq_direct
        if groq_direct.active():
            return "own-key"
    except Exception:
        pass
    return "cloud"


def channel():
    if packaging.is_store_build():
        return "store"
    return "installer" if getattr(sys, "frozen", False) else "source"


def body():
    return {"id": config.USAGE_ID, "version": __version__,
            "mode": mode(), "channel": channel()}


def due():
    return (config.USAGE_COUNT and config.USAGE_ASKED and config.ONBOARDING_DONE
            and len(config.USAGE_ID) == 64 and not disabled_by_env()
            and bool(config.CLOUD_ENDPOINT_URL)
            and config.USAGE_LAST_DAY != _today())


def _mark_sent():
    config.USAGE_LAST_DAY = _today()
    settings.save({"usage_last_day": config.USAGE_LAST_DAY})


def send_if_due():
    """One check-in if one is due. Returns True when the day is done (sent,
    or refused by the server, which a retry wouldn't change). Network
    failures return False and are retried on the next look. Never raises."""
    with _lock:
        if not due():
            return False
        from . import cloud_client
        headers = cloud_client._headers("application/json")
        headers.pop("X-Install-Id", None)
        try:
            status, data = cloud_client._post(
                "/usage", json.dumps(body()).encode(), headers, _TIMEOUT)
        except Exception as exc:
            log.info("usage check-in: no connection (%s), will retry", type(exc).__name__)
            return False
        if status >= 500:
            log.info("usage check-in: server error %s, will retry", status)
            return False
        if status != 200:
            log.warning("usage check-in refused: %s %s", status, data[:200])
        _mark_sent()
        return True


def start():
    """Call once at startup, after settings are loaded."""
    def run():
        time.sleep(_START_DELAY)
        while True:
            try:
                send_if_due()
            except Exception:
                log.exception("usage check-in failed")
            time.sleep(_POLL_SECONDS)
    threading.Thread(target=run, daemon=True, name="usage-ping").start()


def maybe_ask(overlay_get=None):
    """For installs that finished setup before this existed (or left the
    first-run question unanswered): ask once, in a small window. Closing it
    counts as no. Does nothing during a run that showed the first-run
    screen, so two windows never stack."""
    global _asked_this_run
    if (config.USAGE_ASKED or not config.ONBOARDING_DONE or _asked_this_run
            or disabled_by_env()):
        return
    _asked_this_run = True
    from . import overlay_thread
    overlay = (overlay_get or overlay_thread.get)()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        return
    overlay.build(lambda: _build_question(overlay))


def skip_this_run():
    """The first-run screen is showing; don't ask in a second window."""
    global _asked_this_run
    _asked_this_run = True


def _build_question(overlay):
    import tkinter as tk
    from tkinter import ttk

    from . import app_icon, overlay_thread
    try:
        root = tk.Toplevel(overlay.root)
        root.title("Talkative")
        app_icon.set_window_icon(root)
        root.configure(bg=overlay_thread.bg_color())
        root.resizable(False, False)
        root.attributes("-topmost", True)
        ttk.Label(root, padding=(18, 16, 18, 6), font=("Segoe UI", 12, "bold"),
                  text="One quick question").pack(anchor="w")
        ttk.Label(root, padding=(18, 0, 18, 0), wraplength=440,
                  text=QUESTION).pack(anchor="w")
        buttons = ttk.Frame(root, padding=(18, 14, 18, 14))
        buttons.pack(fill="x")

        def answer(yes):
            set_answer(yes)
            root.destroy()

        no_btn = ttk.Button(buttons, text=NO, command=lambda: answer(False))
        yes_btn = ttk.Button(buttons, text=YES, command=lambda: answer(True))
        # Equal weight: same style, side by side, neither the default.
        no_btn.pack(side="right")
        yes_btn.pack(side="right", padx=(0, 8))
        root.protocol("WM_DELETE_WINDOW", lambda: answer(False))
        root.bind("<Escape>", lambda e: answer(False))
    except Exception:
        log.exception("usage question window failed")
