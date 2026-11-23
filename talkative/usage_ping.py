"""Anonymous usage count (Backlog usage-count, 2026-11-23; PRIVACY.md
"Anonymous usage count").

On by default and disclosed, not asked (user's decision, 2026-11-23); the
off switch is in Settings > About (config.USAGE_COUNT). No identifier of
any kind is sent -- no install ID, no hash, no random code -- so the count
can't be tied to an install or a person. Instead the check-in carries
flags that let the Worker count exactly:

  - active installs per UTC day (one check-in per install per day),
  - per ISO week / month ("week_first" / "month_first": this install's
    first check-in of that week / month),
  - new installs ("new_install": the first check-in after the first-run
    setup, not existing installs updating to this version),

plus the version, Cloud / own key / Local, installer / store / source, and
how many dictations since the last check-in, as a range ("6-20").

TALKATIVE_NO_USAGE=1 turns it off for tests and release QA, so throwaway
first-run folders aren't counted.
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone

from . import __version__, config, packaging, settings

log = logging.getLogger(__name__)

_START_DELAY = 15     # seconds after startup, after the update check's 10
_POLL_SECONDS = 1800  # how often a running app looks whether a check-in is due
_TIMEOUT = 10
_SAVE_EVERY = 300     # seconds between saving the dictation tally
_lock = threading.Lock()
_last_saved = 0.0

BUCKETS = ((0, "0"), (5, "1-5"), (20, "6-20"), (50, "21-50"))


def _now():
    return datetime.now(timezone.utc)


def keys(now=None):
    """(day, ISO week, month) in UTC, e.g. ("2026-11-23", "2026-W48", "2026-11")."""
    now = now or _now()
    year, week, _ = now.isocalendar()
    return now.strftime("%Y-%m-%d"), f"{year}-W{week:02d}", now.strftime("%Y-%m")


def bucket(n):
    for top, label in BUCKETS:
        if n <= top:
            return label
    return "50+"


def disabled_by_env():
    return os.environ.get("TALKATIVE_NO_USAGE") == "1"


def mark_new_install():
    """Called when the first-run setup finishes: the next check-in counts
    this install as new (once)."""
    config.USAGE_NEW_INSTALL = True
    settings.save({"usage_new_install": True})


def note_dictation():
    """One dictation typed. Kept in memory, saved now and then so a
    restart loses at most a few minutes of tally."""
    global _last_saved
    config.USAGE_DICTATIONS += 1
    if time.monotonic() - _last_saved > _SAVE_EVERY:
        _last_saved = time.monotonic()
        try:
            settings.save({"usage_dictations": config.USAGE_DICTATIONS})
        except Exception:
            pass


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


def body(now=None):
    day, week, month = keys(now)
    return {
        "version": __version__, "mode": mode(), "channel": channel(),
        "new_install": bool(config.USAGE_NEW_INSTALL),
        "week_first": config.USAGE_LAST_WEEK != week,
        "month_first": config.USAGE_LAST_MONTH != month,
        "dictations": bucket(config.USAGE_DICTATIONS),
    }


def due(now=None):
    return (config.USAGE_COUNT and config.ONBOARDING_DONE and not disabled_by_env()
            and bool(config.CLOUD_ENDPOINT_URL)
            and config.USAGE_LAST_DAY != keys(now)[0])


def _mark_sent(now):
    day, week, month = keys(now)
    config.USAGE_LAST_DAY, config.USAGE_LAST_WEEK, config.USAGE_LAST_MONTH = day, week, month
    config.USAGE_NEW_INSTALL = False
    config.USAGE_DICTATIONS = 0
    settings.save({"usage_last_day": day, "usage_last_week": week,
                   "usage_last_month": month, "usage_new_install": False,
                   "usage_dictations": 0})


def send_if_due(now=None):
    """One check-in if one is due. Returns True when the day is done (sent,
    or refused by the server, which a retry wouldn't change). Network
    failures and server errors return False and are retried on the next
    look. Never raises."""
    with _lock:
        now = now or _now()
        if not due(now):
            return False
        from . import cloud_client
        headers = cloud_client._headers("application/json")
        headers.pop("X-Install-Id", None)
        try:
            status, data = cloud_client._post(
                "/usage", json.dumps(body(now)).encode(), headers, _TIMEOUT)
        except Exception as exc:
            log.info("usage check-in: no connection (%s), will retry", type(exc).__name__)
            return False
        if status >= 500:
            log.info("usage check-in: server error %s, will retry", status)
            return False
        if status != 200:
            log.warning("usage check-in refused: %s %s", status, data[:200])
        _mark_sent(now)
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
