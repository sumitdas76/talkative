"""Run the real app._process_audio_inner with a faked transcript and
capture what would be pasted, for both modes, and which STT prompt was
used."""
import sys, types
sys.path.insert(0, r"C:\Users\sumit\Projects\Talkative")
from talkative import app as appmod, config, dev_mode, settings
settings.load_into_config()
config.DEBUG_LOG = False

pasted, prompts = [], []
appmod.insert_text = lambda t: pasted.append(t)
appmod.is_focus_editable = lambda: True
appmod.updater = types.SimpleNamespace(note_words=lambda n: None)
appmod.cloud_client = types.SimpleNamespace(
    transcribe=lambda audio, sr, initial_prompt=None: (prompts.append(initial_prompt), FAKE[0])[1],
    grammar_apply=lambda t: t,
)

a = appmod.TalkativeApp.__new__(appmod.TalkativeApp)
a._beep = lambda k: None
a._cloud_active = lambda: True
a._grammar_uses_local = lambda: False
a.tray = types.SimpleNamespace(notify=print)
FAKE = [""]

for dev, text in [
    (True, "select star from users where id equals five"),
    (True, "git commit dash m quote fix login bug quote"),
    (True, "the API returns JSON with a 200 status"),
    (False, "select star from users where id equals five"),
    (False, "I think AI will help."),
    (True, "I think AI will help."),
]:
    FAKE[0] = text
    pasted.clear(); prompts.clear()
    a._process_audio_inner(b"", dev)
    which = "dev" if prompts[0].startswith(dev_mode.STT_PROMPT[:20]) else "normal"
    print(f"{'DEV   ' if dev else 'NORMAL'} {text!r}\n        -> {pasted[0]!r}   (STT prompt: {which})")
