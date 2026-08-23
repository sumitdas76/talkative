"""In-app feedback channel (spec queue #4): a two-way, $0/no-server path
for the user to send a message to Sumit and later see the reply, with no
app-owned backend.

Send: POST to FormSubmit.co's AJAX endpoint -- no signup, no API key.
Sumit's very first submission needs a one-time confirmation click in Gmail
before FormSubmit starts forwarding; every Send after that just works.
This is the app's only outbound network path, and only ever runs when the
user clicks Send (see the About tab's privacy note).

Receive: replies are not pushed anywhere -- Sumit publishes them by hand as
JSON in the public sumit-speak-updates repo (the same repo/workflow as the
update manifest), keyed by this install's anonymous id. The app polls that
file at most once a day, alongside the update check, and surfaces a new
reply exactly once.
"""

import json
import threading
import time
import urllib.request
import uuid
from datetime import date

from . import config, settings

FORM_ENDPOINT = "https://formsubmit.co/ajax/sumitdas76@gmail.com"
# FormSubmit's AJAX endpoint sits behind Cloudflare and rejects requests
# two ways that only showed up against the real endpoint, not in any local
# test: (1) Cloudflare bans Python's default urllib User-Agent outright, so
# a browser-like one is required; (2) FormSubmit itself refuses requests
# with no page-origin context ("open this page through a web server"), so
# a stable Referer/Origin is required too. Keep these two exactly as they
# were when the account was activated -- FormSubmit may bind activation to
# whatever origin first triggered it.
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://github.com/sumitdas76/sumit-speak",
    "Origin": "https://github.com",
}


def install_id():
    """Random, anonymous per-install id, created once and persisted."""
    if config.INSTALL_ID:
        return config.INSTALL_ID
    new_id = uuid.uuid4().hex
    config.INSTALL_ID = new_id
    settings.save({"install_id": new_id})
    return new_id


def send(message, on_done=None):
    """POST `message` to Sumit. Runs on a background thread; on_done(ok,
    error) is called from that same thread when done (callers touching Tk
    widgets must hop back via root.after)."""

    def work():
        ok, error = False, None
        try:
            body = json.dumps({
                "message": message,
                "install_id": install_id(),
                "_subject": "Talkative feedback",
            }).encode("utf-8")
            req = urllib.request.Request(FORM_ENDPOINT, data=body, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read().decode("utf-8"))
            if str(result.get("success", "")).lower() != "true":
                raise ValueError(result.get("message", "send failed"))
            ok = True
        except Exception as exc:
            error = str(exc)
        if on_done:
            on_done(ok, error)

    threading.Thread(target=work, daemon=True).start()


def check_for_reply():
    """Fetch the public replies file; return (reply_id, text) for a new,
    unseen reply addressed to this install, or None."""
    url = config.FEEDBACK_REPLIES_URL
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get("replies", {})
    entry = entry.get(install_id()) if isinstance(entry, dict) else None
    if not isinstance(entry, dict):
        return None
    reply_id = str(entry.get("reply_id", "")).strip()
    text = str(entry.get("text", "")).strip()
    if not reply_id or not text or reply_id == config.FEEDBACK_LAST_SEEN:
        return None
    return reply_id, text


def mark_seen(reply_id, text):
    config.FEEDBACK_LAST_SEEN = reply_id
    config.FEEDBACK_LAST_REPLY = text
    settings.save({"feedback_last_seen": reply_id, "feedback_last_reply": text})


def start_background_check(on_reply):
    """Call once at startup. Waits for things to settle, then does the
    at-most-once-a-day reply check and calls on_reply(text) if there's a
    new one."""

    def run():
        time.sleep(12)  # after the update check's own 10s settle
        today = date.today().isoformat()
        if config.FEEDBACK_LAST_CHECK == today:
            return
        config.FEEDBACK_LAST_CHECK = today
        settings.save({"feedback_last_check": today})
        found = check_for_reply()
        if not found:
            return
        reply_id, text = found
        mark_seen(reply_id, text)
        on_reply(text)

    threading.Thread(target=run, daemon=True).start()
