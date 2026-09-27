# Grammar model evaluation

Compares local grammar-engine candidates (CTranslate2 int8) on speed,
guard rejections and meaning changes, using the app's own `_SYSTEM`,
`_SHOTS` and `validate()`.

- `hard_cases.py` -- 35 hand-written inputs aimed at known failure modes
  (idioms, I/you swaps, negation, modals, questions, numbers, names,
  repeats, garbled and long unpunctuated text), each with words that must
  survive and rewrites that must not appear.
- `extract_log_cases.py` -- adds real dictations from this machine's
  `debug.log` as `log_cases.json` (private, gitignored).
- `evaluate.py <key>` -- runs one model, prints every case, writes
  `results_<key>.json` (gitignored). Always with the shipped speed settings
  (physical-core threads + static prompt) so models compare fairly.

Reading the numbers: rejections are safe (the text is pasted uncleaned),
while a meaning flag on an *accepted* output is the real damage. Read the
side-by-side outputs before deciding -- a model can score well by barely
changing anything.

## Converting a candidate

Use a separate venv, not the app's:

    python -m venv convvenv
    convvenv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
    convvenv\Scripts\pip install transformers ctranslate2==<app's version> accelerate
    convvenv\Scripts\ct2-transformers-converter --model <hf id> --quantization int8 ^
        --output_dir ct2\<key> --copy_files tokenizer.json tokenizer_config.json

then add `<key>` to `MODELS` in `evaluate.py` with its chat format.

## Results, 2026-09-27 (Ryzen 5 8500G, 68 cases: 35 hand-written + 33 real)

| Model | median | p90 | max | rejected | meaning flags |
|---|---|---|---|---|---|
| Qwen2.5-1.5B (shipped) | 1.19s | 4.41s | 7.3s | 7 | 5 |
| Qwen2.5-0.5B | 0.47s | 1.96s | 9.1s | 8 | 2 |
| Gemma-3-1B-it | 0.72s | 2.15s | 10.8s | 26 | 8 |
| Llama-3.2-1B-Instruct | 1.23s | 3.73s | 17.2s | 31 | 11 |

Kept Qwen2.5-1.5B. Qwen2.5-0.5B's low flag count is from doing little:
it left a long unpunctuated dictation as one run-on sentence (1.5B split it
into five) and its accepted outputs dropped or garbled words the guards
can't see ("very old dear friend" -> "very old friend"; "who joined
recently" -> "who is recently joined"). Gemma emitted an emoji. Not
testable: Qwen3.5 (Feb 2026) -- its linear-attention layers aren't
supported by CTranslate2 4.8.

The speedup shipped instead: physical-core threads + static prompt made
the same model 40% faster over all 68 cases (short dictation 3.2s ->
1.7s, long 9.8s -> 6.4s) with equivalent quality (24 vs 25 left
unchanged, 3 vs 3 meaning flags). Outputs aren't bit-identical -- greedy
decoding flips on near-ties when float math changes -- so compare
quality, not strings, after any such change.

## Restraint experiment, 2026-09-27 (`variants.py V0|V1|V2`)

Cloud's grammar model (gpt-oss-20b) mostly leaves the speaker's words
alone; the local 1.5B rewords. Prompt changes tried on the 68 cases:

| Variant | changed | rejected | meaning flags | reworded words |
|---|---|---|---|---|
| V0 shipped prompt | 43 | 7 | 3 | 17 |
| V1 + two "leave it alone" shots | 40 | 11 | 4 | 22 |
| V2 strict "never reword" prompt | 47 | 4 | 1 | 19 |

Not shipped: V2 traded rewording for silent deletion -- it dropped a whole
question ("...Or maybe he is doing a lot in his company regarding AI
implementation?") that the per-sentence guard let through at 0.2. Shipped
instead: that guard at 0.5 (config.GRAMMAR_MIN_SENTENCE_RETENTION), which
rejects that output and none of 130+ good local or 119 good Cloud outputs.
Prompting a 1.5B model moved errors around rather than removing them.

## Local speech recognition, 2026-09-27 (`stt_bench.py model:beam:threads`)

41 code phrases + 24 sentences, synthetic US (Zira) and Indian English
(Ravi) voices. WER on the sentences; code = exact code-dictation matches.

| Config | WER US | WER Ind. | code US/Ind. | median |
|---|---|---|---|---|
| small.en beam 5, default threads (shipped) | 1.8% | 4.3% | 37/35 | 1.38s |
| small.en beam 5, 6 threads | 1.8% | 4.3% | 37/35 | 1.32s |
| small.en beam 1, 6 threads | 1.8% | 4.9% | 37/34 | 1.25s |
| base.en beam 5, 6 threads | 3.1% | 4.3% | 35/28 | 0.41s |
| distil-small.en beam 1 | 3.7% | 5.5% | 0/0 | 1.06s |
| distil-large-v3 beam 1 | 2.5% | 3.1% | 20/20 | 5.11s |
| large-v3-turbo beam 1 (Groq's model) | 1.8% | 3.1% | 39/34 | 5.19s |
| simulated older PC (2 cores, AVX2): small.en | 1.8% | 4.3% | 37/35 | 1.65s |
| simulated older PC: base.en | 3.1% | 4.3% | 35/28 | 0.81s |

Whisper encodes a fixed 30 s window, so beam and threads barely matter;
model size is the lever. small.en stays the default everywhere (fine even
on the simulated older PC). large-v3-turbo is worth it only where it's
fast (an NVIDIA GPU): 4x slower here for fewer Indian English errors.
Grammar on the simulated older PC: ~6 tok/s vs ~13 here, long dictation
~19 s, which config.GRAMMAR_MAX_SECONDS now skips. The simulation can't
reproduce DDR4 memory bandwidth, so real old PCs will be slower still.
