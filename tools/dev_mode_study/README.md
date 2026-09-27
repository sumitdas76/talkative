# Developer English study

Measures `talkative/dev_mode.py` (the developer-English hotkey) against
spoken test phrases. Dev tool only; nothing here ships in the app.

Run from this folder with the project venv:

```powershell
$py = "..\..\.venv\Scripts\python"
& $py harness2.py score all ideal:x:0          # rules only (perfect transcript)
& $py harness2.py score all cloud:ravi:0 -v    # one voice/engine, show failures
& $py harness2.py score all "cloud:ravi:0,local:mark:0"
& $py harness2.py score final cloud:zira:0     # the untouched final set
& $py harness2.py stt cloud zira 0             # transcribe what's missing
& $py harness2.py stt cloud heera 2 final      # ...for the final set
& $py prose_guard.py      # ordinary sentences must stay prose -- run after classifier changes
& $py hotkey_test.py      # both hotkeys, upgrade, key-repeat
& $py pipeline_test.py    # the real app._process_audio_inner, faked STT
& $py settings_layout.py  # Settings window fits on every tab + screenshots
```

- `corpus2.py` -- 250 phrases (80 SQL, 70 terminal, 70 code, 30 prose).
  Its `HOLDOUT` third has since been looked at, so it's tuning data now.
- `corpus3.py` -- `FINAL`, 80 phrases written after tuning. **Never tune
  on it**; its score is the honest number.
- Voices: SAPI/OneCore zira, david, mark (US), ravi, heera (Indian
  English); rate 0 or 2. Engines: `cloud` (Groq via the Worker), `local`
  (faster-whisper small.en), `ideal` (the spoken text itself).
- Caches: `stt_cache2.json` (local), `stt_cache2_cloud.json` (cloud),
  `grammar_cache2.json` -- scoring is free; only `stt` spends requests.
- **Groq budget**: the free tier (~2000 transcriptions/day) is shared with
  real users. `harness2.py` counts its own requests in
  `groq_requests_today.txt` and stops at `GROQ_BUDGET`. Reset that file
  to `0` on a new day. It rotates throwaway install ids because the
  Worker caps each id at 300/day.

## .NET / JavaScript / full stack (2026-09-27)

```powershell
& $py score4.py tune              # rules only, perfect transcript
& $py score4.py final local:ravi:0 -v
& $py stt4.py zira mark ravi heera   # Local (small.en) transcripts; no Groq
```

- `corpus4.py` -- `TUNE` (178): dotnet CLI / EF Core / NuGet / Package
  Manager Console, C#, npm/yarn/pnpm/npx, React/TS/Express, docker,
  kubectl, az, git, curl -- the same command said several ways ("dash u",
  "hyphen u", "minus u"; "open curly bracket", "open brace", "left
  curly"), plus 16 tech-sounding sentences that must stay prose. `FINAL`
  (61) was written before tuning; scored once at 95.1% rules-only, then
  two gaps it exposed were fixed via *new* TUNE cases, so its later
  numbers are no longer independent.
- `score4.py` is offline: prose is scored on classification only.
- `stt_cache4_<voice>.json` -- Local transcripts per voice.

Results after tuning (rules only 178/178 tune, 60/61 final): Local
small.en tune Zira 85.4%, Mark 81.5%, Ravi 76.4%, Heera 74.2%; final
80.3 / 72.1 / 65.6 / 59.0%. The remaining gap is almost all STT (lodash ->
"laddash", res -> "residential"). Not fixable by rules: C# vs JS casing of
member names (order.Id vs order.id) and "not user" (! in JS, not in Python).
Cloud (Groq, `stt4.py --cloud zira ravi`, 479 requests on 2026-09-27):
tune Zira 88.8%, Ravi 84.8%; final 83.6 / 68.9% (before the Cloud-derived
fixes: tune 87.1 / 78.1%, final 83.6 / 65.6%). On every cached corpus2
transcript (all voices, local and cloud) the 2026-09-27 rules are better
on 13 and worse on none.
