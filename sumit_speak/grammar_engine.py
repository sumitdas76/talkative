"""
Invisible grammar engine: stage 2 of "Cleaned up" mode (spec §3, §6).

A small local instruction model (CTranslate2 int8 + tokenizers -- both
already shipped for faster-whisper, so no new runtime dependencies) fixes
grammar and punctuation in dictated text under a strict leash. Never
mentioned in the UI; its files live in <models>/grammar and its size is
folded into the storage total.

Graceful degradation is the contract: model folder missing, load failure,
generation failure, or a guard rejection all return the input text
unchanged, so "Cleaned up" silently falls back to rules-only. The guards
enforce the leash from outside the model (asymmetric-failure principle:
an engine output that loses the speaker's words or alters a number is
worse than no cleanup at all):

- every digit run in the input must survive verbatim (multiset compare);
- at least GRAMMAR_MIN_RETENTION of the input's words must appear in the
  output (loose enough for legitimate retraction removal, strict enough
  to reject summarization of long rambling input);
- output length must stay within sane bounds of the input.
"""

import re
import threading

from . import config, model_manager

_SYSTEM = (
    "You clean up dictated text. Fix grammar and punctuation. Remove word "
    "repetitions, false starts, and spoken self-corrections (keep only what "
    "the speaker corrected themselves to). Keep the speaker's own words - "
    "never substitute synonyms, never add information, never change names "
    "or numbers. Reply with only the cleaned text."
)

# Few-shot pairs demonstrating the leash; auditioned July 2026 against the
# debug.log corpus (they materially improve instruction-following in
# sub-1B models).
_SHOTS = [
    ("the report the report needs to go out before the meeting starts",
     "The report needs to go out before the meeting starts."),
    ("send the file today, oh sorry, send the file by this evening.",
     "Send the file by this evening."),
    ("we should also check the numbers again before we send it because last "
     "time there was a mistake in the numbers and the client noticed it",
     "We should also check the numbers again before we send it, because last "
     "time there was a mistake in the numbers and the client noticed it."),
]

_DIGIT_RUN = re.compile(r"\d+")
_WORD = re.compile(r"[a-z0-9']+")

_lock = threading.Lock()
_generator = None
_tokenizer = None


def engine_dir():
    return model_manager.models_dir() / config.GRAMMAR_MODEL_DIR


def is_installed():
    d = engine_dir()
    return (d / "model.bin").is_file() and (d / "tokenizer.json").is_file()


def load():
    """Load the engine if installed. Idempotent, thread-safe, never raises.
    Returns True when the engine is ready. Call from a background thread at
    startup -- loading takes a moment and must not delay dictation."""
    global _generator, _tokenizer
    with _lock:
        if _generator is not None:
            return True
        if not config.ENABLE_GRAMMAR_ENGINE or not is_installed():
            return False
        try:
            import ctranslate2
            from tokenizers import Tokenizer

            generator = ctranslate2.Generator(
                str(engine_dir()), device="cpu", compute_type="int8"
            )
            tokenizer = Tokenizer.from_file(str(engine_dir() / "tokenizer.json"))
        except Exception:
            return False
        _generator = generator
        _tokenizer = tokenizer
        return True


def unload():
    global _generator, _tokenizer
    with _lock:
        _generator = None
        _tokenizer = None


def _build_prompt(text):
    p = f"<|im_start|>system\n{_SYSTEM}<|im_end|>\n"
    for spoken, cleaned in _SHOTS:
        p += (f"<|im_start|>user\n{spoken}<|im_end|>\n"
              f"<|im_start|>assistant\n{cleaned}<|im_end|>\n")
    return p + f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"


def _digits_ok(inp, out):
    return sorted(_DIGIT_RUN.findall(inp)) == sorted(_DIGIT_RUN.findall(out))


def _retention_ok(inp, out):
    src = _WORD.findall(inp.lower())
    if not src:
        return True
    dst = set(_WORD.findall(out.lower()))
    kept = sum(1 for w in src if w in dst) / len(src)
    if kept < config.GRAMMAR_MIN_RETENTION:
        return False
    # Additionally, no whole input sentence may vanish. The rule stages
    # upstream already removed retractions and repeats, so the engine
    # deleting a full sentence is always damage -- and a short sentence
    # lost from a long dictation stays above the global bar (seen live:
    # Qwen2.5-0.5B dropped the opening sentence of a 75-word dictation).
    for sentence in re.split(r"(?<=[.!?])\s+", inp):
        words = _WORD.findall(sentence.lower())
        if len(words) >= 2 and sum(1 for w in words if w in dst) / len(words) < 0.5:
            return False
    return True


def _length_ok(inp, out):
    return 0.4 * len(inp) <= len(out) <= 1.5 * len(inp) + 20


def apply(text):
    """Clean `text` through the engine; on any failure or guard rejection
    return it unchanged. Blocking (seconds on CPU) -- call from the
    dictation worker thread only."""
    if not text or _generator is None:
        return text
    try:
        with _lock:
            generator, tokenizer = _generator, _tokenizer
            if generator is None:
                return text
            tokens = tokenizer.encode(_build_prompt(text)).tokens
            result = generator.generate_batch(
                [tokens],
                max_length=len(tokens) + 250,
                sampling_temperature=0,
                include_prompt_in_result=False,
                end_token="<|im_end|>",
            )[0]
            out = tokenizer.decode(
                result.sequences_ids[0], skip_special_tokens=True
            ).strip()
    except Exception:
        return text

    # A thinking-tuned model (Qwen3 family) may emit a reasoning block even
    # unprompted; keep only the answer.
    out = re.sub(r"^<think>.*?</think>\s*", "", out, flags=re.DOTALL).strip()

    if not out:
        return text
    if not (_digits_ok(text, out) and _retention_ok(text, out) and _length_ok(text, out)):
        return text
    return out
