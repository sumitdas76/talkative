"""Audio devices for the tray menu's Microphone and Headphones submenus.

Microphones come from sounddevice (the same list and indexes the recorder
uses; config.INPUT_DEVICE stores the index). Playback devices come from
the Windows audio API (MMDevice), because picking one changes the Windows
default playback device for every app -- Talkative itself plays no sound
since 1.3.13; the user asked for a quick switch in the tray (2026-10-13).
Switching uses IPolicyConfig, the undocumented interface Windows' own
Sound settings and tools like SoundSwitch use (stable since Windows 7).

Every function here swallows errors and returns an empty list / False:
a broken audio stack must never break the tray menu.
"""

import ctypes
import logging
from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p, wintypes

_E_RENDER = 0
_E_CAPTURE = 1
_DEVICE_STATE_ACTIVE = 1
_ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications
_VT_LPWSTR = 31

_com = None   # lazily built comtypes interfaces


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", ctypes.c_byte * 16), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    # Only VT_LPWSTR is read; the union is padded to its full size.
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD),
                ("r3", wintypes.WORD), ("val", c_void_p), ("pad", c_void_p)]


def _interfaces():
    global _com
    if _com is not None:
        return _com
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IPropertyStore(IUnknown):
        _iid_ = GUID("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD))),
            COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD), (["out"], POINTER(_PROPERTYKEY))),
            COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(_PROPERTYKEY)),
                      (["in"], POINTER(_PROPVARIANT))),
        ]

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID)), (["in"], wintypes.DWORD),
                      (["in"], c_void_p), (["out"], POINTER(c_void_p))),
            COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], wintypes.DWORD),
                      (["out"], POINTER(POINTER(IPropertyStore)))),
            COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p))),
            COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(wintypes.DWORD))),
        ]

    class IMMDeviceCollection(IUnknown):
        _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint))),
            COMMETHOD([], HRESULT, "Item", (["in"], c_uint), (["out"], POINTER(POINTER(IMMDevice)))),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_uint), (["in"], wintypes.DWORD),
                      (["out"], POINTER(POINTER(IMMDeviceCollection)))),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_uint), (["in"], c_uint),
                      (["out"], POINTER(POINTER(IMMDevice)))),
        ]

    # Only SetDefaultEndpoint is called; the ten methods before it are
    # declared so it lands on the right vtable slot.
    class IPolicyConfig(IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [COMMETHOD([], HRESULT, name) for name in (
            "GetMixFormat", "GetDeviceFormat", "ResetDeviceFormat", "SetDeviceFormat",
            "GetProcessingPeriod", "SetProcessingPeriod", "GetShareMode", "SetShareMode",
            "GetPropertyValue", "SetPropertyValue")] + [
            COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], c_wchar_p), (["in"], c_uint)),
        ]

    _com = {
        "comtypes": comtypes,
        "enumerator_clsid": GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
        "policy_clsid": GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"),
        "IMMDeviceEnumerator": IMMDeviceEnumerator,
        "IPolicyConfig": IPolicyConfig,
    }
    return _com


def _friendly_name(device):
    key = _PROPERTYKEY()
    # PKEY_Device_FriendlyName {a45c254e-df1c-4efd-8020-67d146a850e0}, 14
    ctypes.memmove(key.fmtid, bytes.fromhex("4e255ca41cdffd4e802067d146a850e0"), 16)
    key.pid = 14
    store = device.OpenPropertyStore(0)  # STGM_READ
    var = _PROPVARIANT()
    store.GetValue(byref(key), byref(var))
    try:
        if var.vt == _VT_LPWSTR and var.val:
            return ctypes.wstring_at(var.val)
        return ""
    finally:
        ctypes.windll.ole32.PropVariantClear(byref(var))


def outputs():
    """[(device_id, name, is_default)] for active playback devices."""
    try:
        com = _interfaces()
        com["comtypes"].CoInitialize()
        enum = com["comtypes"].CoCreateInstance(
            com["enumerator_clsid"], interface=com["IMMDeviceEnumerator"])
        try:
            default_id = enum.GetDefaultAudioEndpoint(_E_RENDER, 0).GetId()
        except Exception:
            default_id = None
        found = []
        coll = enum.EnumAudioEndpoints(_E_RENDER, _DEVICE_STATE_ACTIVE)
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            dev_id = dev.GetId()
            found.append((dev_id, _friendly_name(dev) or dev_id, dev_id == default_id))
        return sorted(found, key=lambda d: d[1].lower())
    except Exception:
        logging.warning("Could not list playback devices", exc_info=True)
        return []


def capture_state():
    """(Windows' default microphone id, frozenset of connected microphone
    ids), or None if Windows can't be asked. Cheap enough to poll: it
    changes when a microphone is plugged in, unplugged, or made the
    default in Windows."""
    try:
        com = _interfaces()
        com["comtypes"].CoInitialize()
        enum = com["comtypes"].CoCreateInstance(
            com["enumerator_clsid"], interface=com["IMMDeviceEnumerator"])
        try:
            default_id = enum.GetDefaultAudioEndpoint(_E_CAPTURE, 0).GetId()
        except Exception:
            default_id = None  # no microphone at all
        coll = enum.EnumAudioEndpoints(_E_CAPTURE, _DEVICE_STATE_ACTIVE)
        ids = frozenset(coll.Item(i).GetId() for i in range(coll.GetCount()))
        return default_id, ids
    except Exception:
        logging.warning("Could not read the microphone list", exc_info=True)
        return None


def set_default_output(device_id):
    """Make `device_id` Windows' default playback device (all roles, so
    calls switch too). True on success."""
    try:
        com = _interfaces()
        com["comtypes"].CoInitialize()
        policy = com["comtypes"].CoCreateInstance(
            com["policy_clsid"], interface=com["IPolicyConfig"])
        for role in _ROLES:
            policy.SetDefaultEndpoint(device_id, role)
        return True
    except Exception:
        logging.warning("Could not switch the playback device", exc_info=True)
        return False


def inputs():
    """[(sounddevice index, name)] for microphones, one entry per device:
    sounddevice lists each microphone once per Windows audio system (MME,
    DirectSound, WASAPI...), so only the default input's system is shown.
    MME cuts names at 31 characters; the WASAPI name is used when it
    starts with the same text."""
    try:
        import sounddevice as sd

        from .audio_recorder import PA_LOCK

        with PA_LOCK:  # PortAudio isn't thread-safe; see audio_recorder
            devices = sd.query_devices()
            default_in = sd.default.device[0]
            apis = sd.query_hostapis()
        if default_in is None or default_in < 0:
            default_in = next((i for i, d in enumerate(devices)
                               if d.get("max_input_channels", 0) > 0), None)
        if default_in is None:
            return []
        api = devices[default_in]["hostapi"]
        wasapi = next((i for i, a in enumerate(apis) if "WASAPI" in a["name"]), None)
        long_names = [d["name"] for d in devices
                      if d["hostapi"] == wasapi and d.get("max_input_channels", 0) > 0]
        found = []
        for index, dev in enumerate(devices):
            if dev["hostapi"] != api or dev.get("max_input_channels", 0) <= 0:
                continue
            name = dev["name"]
            if "Microsoft Sound Mapper" in name or "Primary Sound Capture" in name:
                continue
            name = next((n for n in long_names if n.startswith(name)), name)
            found.append((index, name))
        return found
    except Exception:
        logging.warning("Could not list microphones", exc_info=True)
        return []
