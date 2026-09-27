"""Cloud transcription: Groq vs the Workers AI fallback, on identical audio.

usage: python fallback_bench.py [groq|fallback|both]

Uses the synthetic clips stt_bench.py caches (41 code phrases + 24 plain
sentences, voices zira and ravi) and the Worker's X-Force-Fallback: 1
switch. Reports WER on the sentences, exact code-dictation matches, median
latency, and which service answered. Groq calls are paced (shared key)
and counted in tools/dev_mode_study/groq_requests_today.txt.
"""
import json, os, statistics, sys, time, urllib.error, urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
STUDY = ROOT / "tools" / "dev_mode_study"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(STUDY)); sys.path.insert(0, str(HERE))
from talkative import cloud_client, config, dev_mode, feedback, settings
settings.load_into_config()
feedback.install_id = lambda: "fallback-bench-20260927"
import stt_bench                                   # clip list, wer()
from score4 import score

AUDIO = Path(os.environ.get("BENCH_AUDIO", ""))    # folder of <voice>_<k>.npy from stt_bench.py
GROQ_COUNTER = STUDY / "groq_requests_today.txt"
GROQ_BUDGET = 750


def transcribe(audio, prompt, force):
    headers = cloud_client._headers("audio/wav")
    headers["X-Prompt-B64"] = __import__("base64").b64encode(prompt.encode()).decode()
    if force:
        headers["X-Force-Fallback"] = "1"
    req = urllib.request.Request(config.CLOUD_ENDPOINT_URL.rstrip("/") + "/transcribe",
                                 data=cloud_client._wav_bytes(audio, 16000), headers=headers)
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode())
    return body, time.perf_counter() - t


def run(force):
    prose_prompt = config.PUNCTUATION_PROMPT
    rows, vias = [], {}
    for v in stt_bench.VOICES:
        ok = errs = total = 0
        for k in range(len(stt_bench.CODE) + len(stt_bench.PROSE)):
            code = k < len(stt_bench.CODE)
            if not force:
                n = int(GROQ_COUNTER.read_text()) if GROQ_COUNTER.exists() else 0
                if n >= GROQ_BUDGET:
                    raise SystemExit("Groq study budget reached")
                GROQ_COUNTER.write_text(str(n + 1))
            body, secs = transcribe(np.load(AUDIO / f"{v}_{k}.npy"),
                                    dev_mode.STT_PROMPT if code else prose_prompt, force)
            vias[body.get("via", "?")] = vias.get(body.get("via", "?"), 0) + 1
            rows.append(secs)
            raw = body.get("text", "")
            if code:
                cat, _, want = stt_bench.CODE[k]
                got, is_code = dev_mode.process(raw)
                ok += is_code and score(cat, got, want)
            else:
                e, n = stt_bench.wer(stt_bench.PROSE[k - len(stt_bench.CODE)], raw)
                errs += e; total += n
            time.sleep(1.0 if force else 6.5)
        print(f"  {v}: sentences WER {100 * errs / total:.1f}%, code {ok}/{len(stt_bench.CODE)}", flush=True)
    print(f"  median {statistics.median(rows):.2f}s | answered by {vias}", flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("fallback", "both"):
        print("Workers AI fallback (forced):", flush=True)
        run(True)
    if which in ("groq", "both"):
        print("Groq:", flush=True)
        run(False)
