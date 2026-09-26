"""Developer-English study, v2.

  python harness2.py stt <engine> <voice> <rate>   fill transcript cache
  python harness2.py score <split> <engine:voice:rate>[,...] [-v]
       split: tune | holdout | all

engine: cloud (Groq via the Worker) | local (faster-whisper small.en)
voice : zira david mark ravi heera   rate: SAPI rate, e.g. 0 or 2
Transcripts cache in stt_cache2.json keyed engine|voice|rate|spoken.
Scoring of prose runs the real normal pipeline (grammar call per case).
"""
import json, os, re, sys, tempfile, time, wave
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, r"C:\Users\sumit\Projects\Talkative")
import numpy as np

from talkative import settings, config, feedback
settings.load_into_config()
config.DEBUG_LOG = False
# Test-only install ids, rotated when the Worker's per-install daily cap
# (300) is hit -- so the study is bounded by Groq's real limit (as the user
# authorized), never by or against a real user's own allowance.
_id_n = [1]
feedback.install_id = lambda: f"devmode-study-20260925-{_id_n[0]}"
GROQ_USED = HERE / "groq_requests_today.txt"
# ~850 Groq transcriptions were used before this counter existed; stop at
# 750 more so ~400 of the ~2000/day free tier stay for real users.
GROQ_BUDGET = 750


def _count_request():
    n = int(GROQ_USED.read_text()) if GROQ_USED.exists() else 0
    if n >= GROQ_BUDGET:
        raise SystemExit(f"Groq study budget reached ({n}); stopping to leave headroom for users")
    GROQ_USED.write_text(str(n + 1))
    return n + 1
from talkative import cloud_client, dev_mode
from talkative.cleanup import collapse_repeats, finish_sentence, remove_fillers
from talkative.self_correction import apply_self_corrections
from talkative.dictionary import apply_dictionary, vocabulary_prompt
from talkative.spoken_symbols import apply_spoken_symbols
from corpus2 import CASES, TUNE, HOLDOUT
from corpus3 import FINAL

# One cache file per engine, so a local and a cloud run can go in parallel
# without overwriting each other.
CACHES = {"local": HERE / "stt_cache2.json", "cloud": HERE / "stt_cache2_cloud.json"}
cache = {}
for _p in CACHES.values():
    if _p.exists():
        cache.update(json.loads(_p.read_text(encoding="utf-8")))


def _save(engine):
    mine = {k: v for k, v in cache.items() if k.startswith(engine + "|")}
    if engine == "local" and CACHES["local"].exists():
        # keep whatever else a concurrent local run already wrote
        on_disk = json.loads(CACHES["local"].read_text(encoding="utf-8"))
        on_disk.update(mine)
        mine = on_disk
    CACHES[engine].write_text(json.dumps(mine, indent=1, ensure_ascii=False), encoding="utf-8")
GCACHE = HERE / "grammar_cache2.json"
gcache = json.loads(GCACHE.read_text(encoding="utf-8")) if GCACHE.exists() else {}

VOICE_NAMES = {"zira": "Zira", "david": "David", "mark": "Mark",
               "ravi": "Ravi", "heera": "Heera"}

_voice = None
_tokens = {}


def _sapi():
    global _voice
    import win32com.client
    if _voice is None:
        _voice = win32com.client.Dispatch("SAPI.SpVoice")
        for cat_id in (r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
                       r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices"):
            cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
            cat.SetId(cat_id, False)
            toks = cat.EnumerateTokens()
            for i in range(toks.Count):
                t = toks.Item(i)
                desc = t.GetDescription()
                for key, name in VOICE_NAMES.items():
                    if name in desc and key not in _tokens:
                        _tokens[key] = t
    return _voice


def speak(text, voice, rate):
    import win32com.client
    v = _sapi()
    v.Voice = _tokens[voice]
    v.Rate = int(rate)
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18  # 16 kHz 16-bit mono
    # per-process file: two runs sharing one path collided (SAPI Open failed)
    path = os.path.join(tempfile.gettempdir(), f"talkative_devmode2_{os.getpid()}.wav")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Format = fmt
    stream.Open(path, 3)
    v.AudioOutputStream = stream
    v.Speak(text)
    stream.Close()
    with wave.open(path) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


_local = None


def transcribe(audio, engine, prompt):
    global _local
    if engine == "local":
        if _local is None:
            from talkative import model_manager
            from talkative.transcriber import Transcriber
            _local = Transcriber(config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE,
                                 download_root=str(model_manager.models_dir()))
        return _local.transcribe(audio, config.SAMPLE_RATE, initial_prompt=prompt)
    import urllib.error
    for attempt in range(8):
        try:
            _count_request()
            text = cloud_client.transcribe(audio, config.SAMPLE_RATE, initial_prompt=prompt)
            # Groq free tier is ~20 requests/minute on a key shared with real
            # users; at 3.2s the study alone hit it and live dictations got
            # "Cloud is busy" (2026-09-26). Stay at ~half.
            time.sleep(6.5)
            return text
        except RuntimeError:
            # 429: either our per-install cap (rotate id) or Groq's own
            # per-minute limit (wait). Try a fresh id first; if that also
            # 429s it's Groq, so back off.
            _id_n[0] += 1
            time.sleep(20 if attempt else 1)
    raise RuntimeError("cloud STT kept failing -- Groq limit likely reached")


def dev_prompt():
    return " ".join(p for p in (dev_mode.STT_PROMPT, vocabulary_prompt()) if p)


def key(engine, voice, rate, spoken):
    return f"{engine}|{voice}|{rate}|{spoken}"


def fill(engine, voice, rate, cases=CASES):
    prompt = dev_prompt()
    n = 0
    for _, spoken, _ in cases:
        k = key(engine, voice, rate, spoken)
        if k in cache:
            continue
        cache[k] = transcribe(speak(spoken, voice, rate), engine, prompt)
        n += 1
        if n % 10 == 0:
            _save(engine)
    _save(engine)
    print(f"{engine}/{voice}/{rate}: {n} new transcripts")


def normal_pipeline(text):
    t = apply_spoken_symbols(text)
    t = remove_fillers(t)
    t = apply_self_corrections(t)
    t = collapse_repeats(t)
    if t in gcache:
        g = gcache[t]
    else:
        # grammar_apply returns the input unchanged on any failure (429
        # included), so only a changed result is known-good to cache.
        g = cloud_client.grammar_apply(t)
        if g != t:
            gcache[t] = g
            GCACHE.write_text(json.dumps(gcache, indent=1, ensure_ascii=False), encoding="utf-8")
        time.sleep(2.2)
    t = dev_mode.strip_backticks(g)
    return apply_dictionary(finish_sentence(t))


def dev_pipeline(raw):
    text, is_code = dev_mode.process(raw)
    return (text, "code") if is_code else (normal_pipeline(text), "prose")


def _norm(s):
    s = s.replace("\u2011", "-").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"\s*,\s*", ", ", s)
    return s


def score(cat, got, want):
    """works: SQL & Windows shell case-insensitive; code case-sensitive;
    prose ignores commas/semicolons, final ./?/! and case (style, not
    correctness -- tech tokens like app.ts must still match exactly)."""
    g, w = _norm(got), _norm(want)
    if cat in ("sql", "shell"):
        return g.lower() == w.lower()
    if cat == "prose":
        f = lambda s: re.sub(r"[.?!]$", "", re.sub(r"[,;]", "", s)).lower().strip()
        return f(g) == f(w)
    return g == w


def main():
    if sys.argv[1] == "stt":
        cases = FINAL if "final" in sys.argv[5:] else CASES
        fill(sys.argv[2], sys.argv[3], sys.argv[4], cases)
        return
    split = {"tune": TUNE, "holdout": HOLDOUT, "all": CASES, "final": FINAL}[sys.argv[2]]
    combos = [c.split(":") for c in sys.argv[3].split(",")]
    verbose = "-v" in sys.argv
    overall = [0, 0]
    for engine, voice, rate in combos:
        tally = {}
        for cat, spoken, want in split:
            raw = spoken if engine == "ideal" else cache.get(key(engine, voice, rate, spoken))
            if raw is None:
                continue
            got, path = dev_pipeline(raw)
            ok = score(cat, got, want)
            wrong_path = (path == "prose") != (cat == "prose")
            t = tally.setdefault(cat, [0, 0]); t[0] += 1; t[1] += ok
            if not ok and verbose:
                print(f"[{cat}{' MISCLASSIFIED' if wrong_path else ''}] said: {spoken}\n"
                      f"    raw : {raw}\n    got : {got}\n    want: {want}")
        line = "  ".join(f"{c} {w}/{n}" for c, (n, w) in tally.items())
        n = sum(v[0] for v in tally.values()); w = sum(v[1] for v in tally.values())
        overall[0] += n; overall[1] += w
        print(f"{engine}/{voice}/{rate} [{sys.argv[2]}]: {w}/{n} = {100*w/max(n,1):.1f}%   {line}")
    if len(combos) > 1:
        print(f"OVERALL: {overall[1]}/{overall[0]} = {100*overall[1]/max(overall[0],1):.1f}%")


if __name__ == "__main__":
    main()
