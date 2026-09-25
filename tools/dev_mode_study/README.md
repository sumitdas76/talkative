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
