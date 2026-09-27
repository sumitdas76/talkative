"""Local speech-recognition benchmark: accuracy + latency per configuration.

usage: python stt_bench.py <config> [<config> ...]
  config = model:beam:threads   e.g. small.en:5:0  distil-large-v3:1:6
  (threads 0 = faster-whisper's default)
Set CT2_FORCE_CPU_ISA=AVX2 / GENERIC in the environment to emulate older
CPUs (read by CTranslate2 at import).

Audio: 41 code phrases (every 4th corpus4 TUNE non-prose) + 24 ordinary
sentences (prose_guard), voices zira (US) + ravi (Indian English),
synthesized once and cached as .npy. Results appended to stt_bench.jsonl.
"""
import json, os, re, sys, time
import numpy as np

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dev_mode_study")
SCRATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "..")); os.chdir(HERE)
from talkative import dev_mode, model_manager
from corpus4 import TUNE
from prose_guard import SENTENCES
from score4 import score

CODE = [c for c in TUNE if c[0] != "prose"][::4]
PROSE = SENTENCES[::2]
VOICES = ("zira", "ravi")
REPOS = {
    "small.en": "small.en",
    "base.en": "base.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
AUDIO = os.path.join(SCRATCH, "bench_audio")


def load_audio():
    os.makedirs(AUDIO, exist_ok=True)
    out = {}
    for v in VOICES:
        for k, text in enumerate([s for _, s, _ in CODE] + PROSE):
            p = os.path.join(AUDIO, f"{v}_{k}.npy")
            if not os.path.exists(p):
                import harness2
                np.save(p, harness2.speak(text, v, 0))
            out[(v, k)] = np.load(p)
    return out


def words(s):
    return re.sub(r"[^a-z0-9' ]", " ", s.lower().replace("-", " ")).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def main():
    from faster_whisper import WhisperModel
    audio = load_audio()
    code_prompt = " ".join([dev_mode.STT_PROMPT])
    prose_prompt = "Hello. How are you? I'm fine, thanks."   # like config.PUNCTUATION_PROMPT
    try:
        from talkative import config
        prose_prompt = config.PUNCTUATION_PROMPT or prose_prompt
    except Exception:
        pass
    for spec in sys.argv[1:]:
        name, beam, threads = spec.split(":")
        kw = dict(device="cpu", compute_type="int8", cpu_threads=int(threads))
        if name == "small.en":
            kw["download_root"] = str(model_manager.models_dir())
        t = time.perf_counter()
        m = WhisperModel(REPOS[name], **kw)
        load_s = time.perf_counter() - t
        lang = "en"
        m.transcribe(audio[(VOICES[0], 0)], language=lang, beam_size=int(beam), vad_filter=True)
        res = {"config": spec, "isa": os.environ.get("CT2_FORCE_CPU_ISA", "auto"), "load_s": round(load_s, 1)}
        secs = []
        for v in VOICES:
            ok = 0
            errs = total = 0
            for k in range(len(CODE) + len(PROSE)):
                code = k < len(CODE)
                t = time.perf_counter()
                segs, _ = m.transcribe(audio[(v, k)], language=lang, beam_size=int(beam), vad_filter=True,
                                       initial_prompt=code_prompt if code else prose_prompt)
                raw = "".join(s.text for s in segs).strip()
                secs.append(time.perf_counter() - t)
                if code:
                    cat, _, want = CODE[k]
                    got, is_code = dev_mode.process(raw)
                    ok += is_code and score(cat, got, want)
                else:
                    e, n = wer(PROSE[k - len(CODE)], raw)
                    errs += e; total += n
            res[f"{v}_code"] = f"{ok}/{len(CODE)}"
            res[f"{v}_wer"] = round(100 * errs / total, 1)
        secs.sort()
        res["median_s"] = round(secs[len(secs) // 2], 2)
        res["p90_s"] = round(secs[int(len(secs) * .9)], 2)
        print(json.dumps(res), flush=True)
        with open(os.path.join(SCRATCH, "stt_bench.jsonl"), "a") as f:
            f.write(json.dumps(res) + "\n")
        del m


if __name__ == "__main__":
    main()
