"""Small secrets kept in settings.json, encrypted with Windows DPAPI.

CryptProtectData in the current user's scope: only this Windows account
on this PC can decrypt the value, so a copied settings.json (feedback
attachment, backup, another PC) is useless to anyone else. Stdlib ctypes
only -- no new package. Used for the user's own Groq key (groq_direct.py).
"""

import base64
import ctypes
from ctypes import wintypes

_ENTROPY = b"talkative-secret-v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _take(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


_UI_FORBIDDEN = 0x1  # CRYPTPROTECT_UI_FORBIDDEN


def protect(text):
    """str -> base64 str of the DPAPI-encrypted UTF-8 bytes. Raises OSError."""
    data_in, _keep = _blob(text.encode("utf-8"))
    entropy, _keep2 = _blob(_ENTROPY)
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
            _UI_FORBIDDEN, ctypes.byref(out)):
        raise ctypes.WinError()
    return base64.b64encode(_take(out)).decode("ascii")


def unprotect(stored):
    """protect()'s output -> the original str, or "" when it can't be
    decrypted (another user/PC, damaged value). Never raises."""
    if not stored:
        return ""
    try:
        data_in, _keep = _blob(base64.b64decode(stored, validate=True))
        entropy, _keep2 = _blob(_ENTROPY)
        out = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
                _UI_FORBIDDEN, ctypes.byref(out)):
            return ""
        return _take(out).decode("utf-8")
    except Exception:
        return ""
