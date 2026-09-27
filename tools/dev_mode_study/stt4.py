"""Transcribe corpus4 with Local mode's speech model (faster-whisper
small.en) using synthetic SAPI voices. Local only: no Groq requests.

usage: python stt4.py <voice> [<voice> ...]     (zira mark ravi heera)

One cache file per voice (stt_cache4_<voice>.json) so voices can run in
parallel; score4.py reads them all.
"""
import json, sys
from pathlib import Path

import harness2
from corpus4 import CASES

HERE = Path(__file__).parent
RATE = 0

for voice in sys.argv[1:]:
    path = HERE / f"stt_cache4_{voice}.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    prompt = harness2.dev_prompt()
    new = 0
    for _, spoken, _ in CASES:
        key = f"local:{voice}:{RATE}|{spoken}"
        if key in cache:
            continue
        cache[key] = harness2.transcribe(harness2.speak(spoken, voice, RATE), "local", prompt)
        new += 1
        if new % 20 == 0:
            path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{voice}: {new} new transcripts, {len(cache)} total")
