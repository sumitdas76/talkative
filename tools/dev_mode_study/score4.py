"""Score dev_mode.py on corpus4 (.NET / JS-TS / full stack).

usage: python score4.py tune|final [ideal|local:<voice>:<rate>] [-v]

  ideal   -- the spoken text itself (rules only, perfect transcript)
  local   -- cached faster-whisper small.en transcripts (stt4.py makes them)
  e.g. local:ravi:0

Offline: prose cases are scored on classification alone (a prose line must
not be treated as code), so no grammar requests are made.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
from talkative import dev_mode
from corpus4 import TUNE, FINAL



def _norm(s):
    s = s.replace("‑", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s.strip())
    return re.sub(r"\s*,\s*", ", ", s)


def score(cat, got, want):
    g, w = _norm(got), _norm(want)
    return g.lower() == w.lower() if cat == "shell" else g == w


def main():
    split = {"tune": TUNE, "final": FINAL}[sys.argv[1]]
    source = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else "ideal"
    verbose = "-v" in sys.argv
    cache = {}
    for f in HERE.glob("stt_cache4_*.json"):
        cache.update(json.loads(f.read_text(encoding="utf-8")))
    tally = {}
    for cat, spoken, want in split:
        raw = spoken if source == "ideal" else cache.get(f"{source}|{spoken}")
        if raw is None:
            continue
        got, is_code = dev_mode.process(raw)
        ok = (not is_code) if cat == "prose" else (is_code and score(cat, got, want))
        t = tally.setdefault(cat, [0, 0]); t[0] += 1; t[1] += ok
        if not ok and verbose:
            why = "CODE (should be prose)" if cat == "prose" else ("PROSE (should be code)" if not is_code else "")
            print(f"[{cat}] {why}\n  said: {spoken}\n  raw : {raw}\n  got : {got}\n  want: {want}")
    n = sum(v[0] for v in tally.values()); w = sum(v[1] for v in tally.values())
    parts = "  ".join(f"{c} {ok}/{tot}" for c, (tot, ok) in tally.items())
    print(f"{source} [{sys.argv[1]}]: {w}/{n} = {100 * w / max(n, 1):.1f}%   {parts}")


if __name__ == "__main__":
    main()
