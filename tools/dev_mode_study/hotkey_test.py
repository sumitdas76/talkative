"""Drive TalkativeApp._on_press/_on_release with simulated keys (no real
keyboard, recorder, or model) and check which dictations start, and in
which mode."""
import sys, types
sys.path.insert(0, r"C:\Users\sumit\Projects\Talkative")
from pynput import keyboard
from talkative import app as appmod, config

K = keyboard.Key
started = []


class FakeThread:
    def __init__(self, target, args, daemon):
        self.args = args
    def start(self):
        started.append(self.args[1])        # the dev flag handed to _process_audio


appmod.threading = types.SimpleNamespace(Thread=FakeThread)
toasts = []
appmod.error_toast = types.SimpleNamespace(show=toasts.append)
# A user who has answered the first-run Cloud/Local question (since 1.3.7
# nothing records before that -- tested separately at the end).
config.ONBOARDING_DONE = True
appmod.is_focus_editable = lambda: True
appmod.pill = types.SimpleNamespace(show=lambda f: None, hide=lambda: None)
t = [0.0]
appmod.time = types.SimpleNamespace(time=lambda: t[0])


def fresh():
    a = appmod.TalkativeApp.__new__(appmod.TalkativeApp)
    a._hotkey_pressed = set(); a._chord_active = False; a._dev_dictation = False
    a._recording = False; a._swapping = False; a._no_model = False
    a.transcriber = object(); a._record_start_time = 0
    a.recorder = types.SimpleNamespace(start=lambda: None, stop=lambda: b"", level=0)
    a.tray = types.SimpleNamespace(set_recording=lambda: None, set_idle=lambda: None, notify=print)
    a._beep = lambda k: None
    return a


def hold(a, *keys, repeat=3, secs=1.0):
    """Press keys in order (with OS auto-repeat on the last one), then
    release them in reverse order."""
    for k in keys:
        a._on_press(k)
    for _ in range(repeat):
        a._on_press(keys[-1])
    t[0] += secs
    for k in reversed(keys):
        a._on_release(k)


def case(name, hotkey, dev_hotkey, *keys, expect):
    config.HOTKEY, config.DEV_HOTKEY = hotkey, dev_hotkey
    started.clear()
    hold(fresh(), *keys)
    got = ["dev" if d else "normal" for d in started]
    print(f"{'OK ' if got == expect else 'BAD'} {name}: {got} (expected {expect})")


USER = ((K.ctrl_l, K.alt_l), (K.ctrl_r,))
DEFAULT = ((K.ctrl_r,), (K.ctrl_r, K.shift_r))

case("your normal key", *USER, K.ctrl_l, K.alt_l, expect=["normal"])
case("your normal key, other order", *USER, K.alt_l, K.ctrl_l, expect=["normal"])
case("your developer key", *USER, K.ctrl_r, expect=["dev"])
case("default normal key", *DEFAULT, K.ctrl_r, expect=["normal"])
case("default: hold Right Ctrl, add Right Shift (upgrade)", *DEFAULT, K.ctrl_r, K.shift_r, expect=["dev"])
case("default: Right Shift first, then Right Ctrl", *DEFAULT, K.shift_r, K.ctrl_r, expect=["dev"])
case("typing a capital with Right Shift alone", *DEFAULT, K.shift_r, expect=[])
case("developer key turned off", (K.ctrl_r,), (), K.ctrl_r, expect=["normal"])

# Two dictations back to back must not leak the dev flag into the next one.
config.HOTKEY, config.DEV_HOTKEY = DEFAULT
started.clear()
a = fresh()
hold(a, K.ctrl_r, K.shift_r)
hold(a, K.ctrl_r)
got = ["dev" if d else "normal" for d in started]
print(f"{'OK ' if got == ['dev', 'normal'] else 'BAD'} dev then normal: {got}")

# First-run gate: until Cloud/Local is chosen, the hotkey records nothing
# and says why.
config.ONBOARDING_DONE = False
case("before the first-run choice", *DEFAULT, K.ctrl_r, expect=[])
print(f"{'OK ' if toasts else 'BAD'} ...and a notice was shown: {toasts[-1:]}")
config.ONBOARDING_DONE = True
