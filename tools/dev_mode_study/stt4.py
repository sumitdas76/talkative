"""Transcribe corpus4 with synthetic SAPI voices -- Local mode's speech
model (faster-whisper small.en) by default, no Groq requests.

usage: python stt4.py [--cloud] <voice> [<voice> ...]   (zira mark ravi heera)

--cloud uses Groq via the Worker instead (harness2's budget counter and
pacing apply -- the key is shared with real users).

One cache file per voice (stt_cache4_<voice>.json) so voices can run in
parallel; score4.py reads them all.
"""
import json, sys
from pathlib import Path

import harness2
from corpus4 import CASES

HERE = Path(__file__).parent
RATE = 0
ENGINE = "cloud" if "--cloud" in sys.argv else "local"

for voice in [a for a in sys.argv[1:] if not a.startswith("--")]:
    path = HERE / f"stt_cache4_{voice}{'_cloud' if ENGINE == 'cloud' else ''}.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    prompt = harness2.dev_prompt()
    new = 0
    for _, spoken, _ in CASES:
        key = f"{ENGINE}:{voice}:{RATE}|{spoken}"
        if key in cache:
            continue
        cache[key] = harness2.transcribe(harness2.speak(spoken, voice, RATE), ENGINE, prompt)
        new += 1
        if new % 20 == 0:
            path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{voice}: {new} new transcripts, {len(cache)} total")
