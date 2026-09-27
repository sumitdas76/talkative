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
