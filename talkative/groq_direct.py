"""Cloud processing on the user's own free Groq key (Settings > General >
Cloud, optional; 2026-11-22, Backlog own-groq-key).

Every Talkative Cloud user shares one free Groq key. A user who pastes
their own gets Groq's full free limits for themselves: the app then calls
api.groq.com directly with the same models, settings and prompt as
cloud/worker.js, and Talkative Cloud is used only when the key fails
(cloud_client.py decides). The key is stored DPAPI-encrypted
(secret_store.py), is sent only to GROQ_API_BASE, and is never logged.

Errors: KeyRefused (401/403), KeyLimited (429), GroqError (anything else
Groq answers with), or a network exception -- callers fall back on all of
them.
"""

import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import cloud_prompt, config, secret_store

GROQ_HOST = "api.groq.com"
_BASE = "/openai/v1"
STT_MODEL = "whisper-large-v3-turbo"
GRAMMAR_MODEL = "openai/gpt-oss-20b"
KEY_PATTERN = re.compile(r"gsk_[A-Za-z0-9]{20,200}")
_MAX_REPLY = 1_000_000
REWRITE_MAX_TOKENS = 4096
_UA = "Talkative"


class GroqError(RuntimeError):
    pass


class KeyRefused(GroqError):
    pass


class KeyLimited(GroqError):
    pass


# Requests left today on the user's key, per model, from Groq's
# x-ratelimit-remaining-requests header on the last answer (None = unknown).
left_today = {}

_cache = {"stored": None, "key": ""}
_cache_lock = threading.Lock()


def valid_format(key):
    return bool(KEY_PATTERN.fullmatch(key or ""))


def key():
    """The saved key in plain text, or "" when none is saved (or it can't
    be decrypted, e.g. settings.json copied from another PC)."""
    stored = config.GROQ_KEY_DPAPI
    with _cache_lock:
        if stored != _cache["stored"]:
            plain = secret_store.unprotect(stored) if stored else ""
            _cache["stored"], _cache["key"] = stored, plain if valid_format(plain) else ""
        return _cache["key"]


def active():
    return bool(key())


# One reused HTTPS connection (as cloud_client does for the Worker): a new
# TLS handshake costs 0.2 s or more from India.
_idle = []
_idle_lock = threading.Lock()
_RETRYABLE = (http.client.RemoteDisconnected, http.client.BadStatusLine,
              http.client.CannotSendRequest, ConnectionResetError,
              ConnectionAbortedError, BrokenPipeError)


def _proxied():
    try:
        return bool(urllib.request.getproxies().get("https"))
    except Exception:
        return True


def _take(timeout):
    now = time.monotonic()
    with _idle_lock:
        while _idle:
            conn, last = _idle.pop()
            if now - last < config.CLOUD_CONN_MAX_IDLE and conn.sock is not None:
                conn.timeout = timeout
                conn.sock.settimeout(timeout)
                return conn, True
            conn.close()
    return http.client.HTTPSConnection(GROQ_HOST, 443, timeout=timeout), False


def _give_back(conn):
    with _idle_lock:
        if len(_idle) < 2:
            _idle.append((conn, time.monotonic()))
            return
    conn.close()


def warm():
    """Open a connection to Groq ahead of the next request. True if Groq
    could be reached (or nothing was tested), False otherwise. Never raises."""
    if _proxied():
        return True
    try:
        conn, reused = _take(config.CLOUD_WARM_TIMEOUT)
        if not reused:
            conn.connect()
        _give_back(conn)
        return True
    except Exception:
        return False


def _request(method, path, body, headers, timeout):
    """-> (status, response headers dict (lower-case), body bytes). Raises
    on network failure."""
    if _proxied():
        req = urllib.request.Request(f"https://{GROQ_HOST}{path}", data=body,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(_MAX_REPLY)
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read(_MAX_REPLY)
    for attempt in (0, 1):
        conn, reused = _take(timeout) if attempt == 0 else (
            http.client.HTTPSConnection(GROQ_HOST, 443, timeout=timeout), False)
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read(_MAX_REPLY + 1)
            if len(data) > _MAX_REPLY:
                conn.close()
                raise GroqError("Groq's answer was too long")
        except _RETRYABLE:
            conn.close()
            if reused:
                continue
            raise
        except Exception:
            conn.close()
            raise
        if resp.will_close:
            conn.close()
        else:
            _give_back(conn)
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data


def _call(method, path, body, content_type, timeout, api_key=None, model=None):
    api_key = api_key or key()
    if not api_key:
        raise KeyRefused("no key saved")
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": _UA}
    if content_type:
        headers["Content-Type"] = content_type
    status, rheaders, data = _request(method, _BASE + path, body, headers, timeout)
    if model:
        left = rheaders.get("x-ratelimit-remaining-requests")
        if left is not None and left.isdigit():
            left_today[model] = int(left)
    if status in (401, 403):
        raise KeyRefused(f"Groq refused the key (HTTP {status})")
    if status == 429:
        if model:
            left_today[model] = 0
        raise KeyLimited("Groq limit reached on your key")
    if status != 200:
        raise GroqError(f"Groq answered HTTP {status}")
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise GroqError("Groq's answer wasn't readable") from None


def check_key(candidate, timeout=10.0):
    """Try `candidate` against Groq's model list (costs no transcription).
    Returns None if it works, else a short reason for the user. Never raises."""
    candidate = (candidate or "").strip()
    if not valid_format(candidate):
        return "That doesn't look like a Groq key. It starts with gsk_."
    try:
        result = _call("GET", "/models", None, None, timeout, api_key=candidate)
    except KeyRefused:
        return "Groq refused this key. Copy it again from console.groq.com/keys."
    except KeyLimited:
        return None  # the key is real, it's just busy right now
    except GroqError:
        return "Groq had a problem checking the key. Try again in a minute."
    except Exception:
        return "Couldn't reach Groq. Check your internet connection."
    ids = {m.get("id") for m in result.get("data", []) if isinstance(m, dict)}
    if ids and STT_MODEL not in ids:
        return "This key can't use Groq's Whisper model."
    return None


def transcribe(wav_bytes, prompt, timeout, language="en"):
    """WAV bytes -> text, with the same request worker.js handleTranscribe
    makes to Groq."""
    boundary = uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                     f"\r\n\r\n{value}\r\n".encode("utf-8"))

    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode("ascii"))
    parts.append(wav_bytes)
    parts.append(b"\r\n")
    field("model", STT_MODEL)
    field("language", language)
    field("response_format", "json")
    prompt = (prompt or "")[-800:].strip()
    if prompt:
        field("prompt", prompt)
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    result = _call("POST", "/audio/transcriptions", b"".join(parts),
                   f"multipart/form-data; boundary={boundary}", timeout, model=STT_MODEL)
    return str(result.get("text", "")).strip()


def _chat(messages, timeout, max_tokens=2048):
    """gpt-oss-20b's reply to `messages`, with the settings worker.js uses."""
    body = json.dumps({
        "model": GRAMMAR_MODEL,
        "messages": messages,
        "temperature": 0,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    result = _call("POST", "/chat/completions", body, "application/json", timeout,
                   model=GRAMMAR_MODEL)
    try:
        out = result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        out = ""
    if not out.strip():
        raise GroqError("Groq returned no text")
    return cloud_prompt.plain_text(out).strip()


def grammar(text, timeout=20.0, language="en"):
    """Cleaned text from gpt-oss-20b, as worker.js handleGrammar asks for
    it. The caller runs grammar_engine.validate() on it."""
    return _chat(cloud_prompt.messages(text, language), timeout)


def rewrite(text, instruction, timeout=30.0):
    """`text` rewritten as the spoken `instruction` asks, as worker.js
    handleRewrite asks for it. rewrite.py checks the reply."""
    # Room for a 4,000-character answer plus the model's short reasoning.
    return _chat(cloud_prompt.rewrite_messages(text, instruction), timeout,
                 max_tokens=REWRITE_MAX_TOKENS)
