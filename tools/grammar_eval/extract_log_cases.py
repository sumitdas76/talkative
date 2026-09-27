"""Build log_cases.json from this machine's debug.log.

Each entry's "collapse" line is exactly what the grammar stage received.
The output holds real dictated text, so it is gitignored -- never commit
it. Needs debug_log on in settings.json while dictating to have anything
to read (and turn it off again afterwards).
"""
import ast
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
log = open(os.path.expandvars(r"%LOCALAPPDATA%\Talkative\debug.log"), encoding="utf-8").read()

cases, seen = [], set()
for entry in re.split(r"\n(?=\d{4}-\d\d-\d\dT)", log):
    fields = {}
    for line in entry.splitlines():
        m = re.match(r"\s+(\w+): (.*)$", line)
        if m:
            try:
                fields[m.group(1)] = ast.literal_eval(m.group(2))
            except Exception:
                fields[m.group(1)] = m.group(2)
    text = fields.get("collapse", "")
    if len(text.split()) >= 4 and text not in seen:
        seen.add(text)
        cases.append({"input": text, "cloud_ref": fields.get("grammar", ""),
                      "timing": fields.get("timing", "")})

json.dump(cases, open(os.path.join(HERE, "log_cases.json"), "w", encoding="utf-8"),
          indent=1, ensure_ascii=False)
print(len(cases), "cases written")
