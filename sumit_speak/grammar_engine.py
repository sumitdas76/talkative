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
    "the speaker corrected themselves to). If a sentence is garbled or "
    "unclear, reword it so it reads clearly, staying as close to the "
    "speaker's own words and phrasing as you reasonably can. Never add "
    "information or invent claims the speaker didn't make, never change "
    "names or numbers, and never drop something the speaker actually said. "
    "Reply with only the cleaned text."
)

# Few-shot pairs demonstrating the leash; auditioned July 2026 against the
# debug.log corpus (they materially improve instruction-following in
# sub-1B models). The last pair demonstrates rewording a garbled/unclear
# sentence (added 2026-07-20, at the user's request, alongside loosening
# the retention guards below to match -- deliberately accepts more risk of
# the model guessing wrong than the original strict leash did).
_SHOTS = [
    ("the report the report needs to go out before the meeting starts",
     "The report needs to go out before the meeting starts."),
    ("send the file today, oh sorry, send the file by this evening.",
     "Send the file by this evening."),
    ("we should also check the numbers again before we send it because last "
     "time there was a mistake in the numbers and the client noticed it",
     "We should also check the numbers again before we send it, because last "
     "time there was a mistake in the numbers and the client noticed it."),
    ("there's this issue where when the user clicks the button nothing "
     "happens sometimes it's kind of random",
     "There's an issue where clicking the button sometimes does nothing; "
     "it seems random."),
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


def delete():
    """Remove the engine's files from disk. Unloads first and forces a GC
    pass so ctranslate2 releases its file handles before rmtree -- otherwise
    the delete fails on Windows with the engine still loaded. Cleaned-up
    mode silently falls back to rules-only afterward (the graceful-absence
    contract); there is currently no in-app re-download, only reinstalling
    Talkative."""
    import gc
    import shutil

    unload()
    gc.collect()
    shutil.rmtree(engine_dir(), ignore_errors=True)


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
    # Both thresholds were loosened 2026-07-20 (0.7->GRAMMAR_MIN_RETENTION,
    # per-sentence 0.5->0.2) at the user's request, to let the model
    # genuinely reword garbled/unclear sentences rather than only fix
    # grammar/punctuation -- real rewording legitimately swaps out most of
    # a sentence's words, which the old, stricter bars were tuned to
    # reject. This trades away some of the original protection against the
    # engine quietly changing what was said; watch debug.log for bad
    # rewrites and tighten back up if it misfires in practice.
    for sentence in re.split(r"(?<=[.!?])\s+", inp):
        words = _WORD.findall(sentence.lower())
        if len(words) >= 2 and sum(1 for w in words if w in dst) / len(words) < 0.2:
            return False
    return True


def _length_ok(inp, out):
    return 0.4 * len(inp) <= len(out) <= 1.5 * len(inp) + 20


_SECOND_PERSON = re.compile(r"\byou(?:'re|r|rs|rself)?\b", re.IGNORECASE)


def _second_person_ok(inp, out):
    """A "you" in the input must not silently vanish. Word-retention
    guards don't catch this: rewording that drops "you" can flip who a
    sentence is about ("I want you to do X" -> "I will do X", seen live
    2026-07-20 with the loosened retention guards above) while still
    passing a >=40% word-overlap check, since the rest of the sentence's
    words survive fine. Pronoun swaps are a uniquely dangerous case
    because they change who's responsible for something, not just how
    it's worded."""
    if _SECOND_PERSON.search(inp) and not _SECOND_PERSON.search(out):
        return False
    return True


def _no_invented_second_person(inp, out):
    """The mirror-image bug, and far more common in practice: the model
    turning the speaker's own first-person statement/question into one
    about the listener -- "If I create videos..., will there be a
    difference?" -> "If you create videos..., there will be a
    difference." Confirmed live 2026-08-23: roughly a dozen "If I..."
    dictations in one debug.log sample all got rewritten this way, all
    passing every other guard since the rest of each sentence's words
    survive (only the subject changes).

    Counts rather than just checking presence, because a subtler variant
    of the same bug survives a presence-only check: a sentence with "you"
    in one clause can still get a *second*, invented "you" planted on a
    different clause that was actually about "I" -- "before I do that,
    what I want you to do is explain..." -> "before you do that, what I
    want you to do is..." (found live 2026-08-23 during the faster-model
    evaluation). The input already has one "you", so a presence check
    passes; a count check (2 > 1) catches it. A legitimate rewrite that
    merely repeats or keeps an existing "you" never needs to *increase*
    the count, so this doesn't have to special-case the zero-"you"
    case separately -- it's the same rule (0 -> >=1 is also an
    increase)."""
    if len(_SECOND_PERSON.findall(out)) > len(_SECOND_PERSON.findall(inp)):
        return False
    return True


def _question_ok(inp, out):
    """A "?" in the input must not silently vanish. Retention/length guards
    don't catch a question turned into an asserted answer -- the rest of
    the sentence's words survive fine, only the question mark and the
    interrogative framing are gone. Seen live 2026-08-16: "will there be
    any difference in sound quality?" -> "there will be no difference in
    sound quality." (a fabricated answer to an unasked question, not a
    grammar fix). Doesn't require the same count -- merging two questions
    into one ("Can I check X? Are they Y?" -> "Can I check X to see if
    they're Y?") is a legitimate rewrite and only needs at least one "?"
    to survive."""
    if "?" in inp and "?" not in out:
        return False
    return True


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
    if not (_digits_ok(text, out) and _retention_ok(text, out)
             and _length_ok(text, out) and _second_person_ok(text, out)
             and _question_ok(text, out) and _no_invented_second_person(text, out)):
        return text
    return out
