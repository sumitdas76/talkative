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
- output length must stay within sane bounds of the input;
- no "you" lost or invented, no "?" lost, no negation lost, and no words
  invented after the end of what was said (see each guard below).
"""

import re
import threading
from collections import Counter

from . import config, hardware, model_manager

_SYSTEM = (
    "You clean up dictated text. Fix grammar, punctuation, and "
    "capitalization only. Remove word repetitions, false starts, and spoken "
    "self-corrections (keep only what the speaker corrected themselves to). "
    "Do not reword anything: keep every word the speaker said, in their "
    "order, and never swap a word for a synonym or a different word, even "
    "if the sentence sounds odd or a plainer version occurs to you. Never "
    "drop a phrase, never add information, never change names or numbers. "
    "Keep every number exactly as the speaker said it: number words stay "
    "words and digits stay digits. Reply with only the cleaned text."
)
# Local only (2026-10-13): the July 2026 looser prompt ("reword a sentence
# when it is genuinely garbled") made the 1.5B model change meaning on real
# speech ("things move in a box" -> "stay in a box", "Painting, he tells
# us, is..." lost "he tells us"), so Local is back on a strict leash, with
# matching strict guards (validate(strict=True)). Cloud keeps the looser
# prompt in cloud/worker.js's SYSTEM -- they deliberately differ now.
# The number sentence (2026-09-27): the local model turned "three thirty"
# into "3:00 PM", which then failed the digit guard.

# Few-shot pairs demonstrating the leash; auditioned July 2026 against the
# debug.log corpus (they materially improve instruction-following in
# sub-1B models). The "honestly" pair (2026-10-13, replacing the July
# "reword a garbled sentence" example) shows informal phrasing kept as said.
_SHOTS = [
    ("the report the report needs to go out before the meeting starts",
     "The report needs to go out before the meeting starts."),
    ("send the file today, oh sorry, send the file by this evening.",
     "Send the file by this evening."),
    ("we should also check the numbers again before we send it because last "
     "time there was a mistake in the numbers and the client noticed it",
     "We should also check the numbers again before we send it, because last "
     "time there was a mistake in the numbers and the client noticed it."),
    ("honestly it's fine it's all good we can just push it to next week you know",
     "Honestly, it's fine, it's all good. We can just push it to next week, you know."),
    # Numbers stay as said (2026-09-27): the 1.5B model ignored the
    # instruction alone and kept writing "three thirty" as "3:00 PM".
    ("the call is at four fifteen and the budget is two point five million",
     "The call is at four fifteen, and the budget is two point five million."),
]

_DIGIT_RUN = re.compile(r"\d+")
_WORD = re.compile(r"[a-z0-9']+")

# Function words excluded from the per-sentence retention check below --
# without this, a dropped sentence can pass on pure coincidence (its only
# "surviving" words are stopwords that also happen to appear elsewhere in
# the output, e.g. "the" from a deleted sentence matching "the" in an
# unrelated surviving one), even though zero of its actual content
# survived.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "being", "this", "that",
    "these", "those", "it", "its", "for", "with", "as", "by", "from",
    "he", "she", "they", "we", "i", "you", "your", "my", "our", "their",
    "his", "her", "them", "us", "me", "him", "so", "if", "then", "than",
    "there", "here", "not", "no", "do", "does", "did", "will", "would",
    "can", "could", "should", "shall", "may", "might", "must", "have",
    "has", "had", "up", "out", "about", "into", "over", "after", "before",
    "just", "also",
})

_lock = threading.Lock()
_download_lock = threading.Lock()
_generator = None
_tokenizer = None
# Output tokens per second on this PC -- measured at load, then updated
# from real dictations (see apply()). None until measured.
_speed = None
device = "cpu"
# Why the last apply() skipped the pass (for debug.log), or None.
last_skip = None


def engine_dir():
    return model_manager.models_dir() / config.GRAMMAR_MODEL_DIR


def is_installed():
    d = engine_dir()
    return (d / "model.bin").is_file() and (d / "tokenizer.json").is_file()


def download():
    """Fetch the engine's files from config.GRAMMAR_HF_REPO into
    engine_dir(). Blocking, no progress callback -- same contract as
    model_manager.download() for the speech model; the UI shows an
    indeterminate progress bar, not a percentage. Raises on failure (empty
    GRAMMAR_HF_REPO, network error, etc.) -- callers must catch."""
    if not config.GRAMMAR_HF_REPO:
        raise RuntimeError("No grammar engine download source is configured.")
    from huggingface_hub import snapshot_download

    # One download at a time: Settings' Download button and the background
    # download from Local setup may overlap.
    with _download_lock:
        if not is_installed():
            snapshot_download(repo_id=config.GRAMMAR_HF_REPO, local_dir=str(engine_dir()))


def download_in_background():
    """Local setup's second stage: fetch the engine without blocking
    anything, then load it if this mode uses it. Dictation meanwhile runs
    with rules-only cleanup (apply() returns text unchanged with no
    engine). On failure the pending flag stays, and app.run() retries at
    the next start."""
    from . import settings

    def work():
        try:
            download()
        except Exception:
            return
        config.GRAMMAR_PENDING_DOWNLOAD = False
        settings.save({"grammar_pending_download": False})
        load_if_used()

    threading.Thread(target=work, daemon=True).start()


def load_if_used():
    """Load the engine when the current mode uses it (Local, or Cloud with
    grammar on this device). Call after any download: a download alone
    used to leave the new engine unused until the next restart."""
    if config.PROCESSING_MODE == "local" or config.GRAMMAR_SOURCE == "local":
        load()


def load():
    """Load the engine if installed. Idempotent, thread-safe, never raises.
    Returns True when the engine is ready. Call from a background thread at
    startup -- loading takes a moment and must not delay dictation."""
    global _generator, _tokenizer, _speed, device
    with _lock:
        if _generator is not None:
            return True
        if not config.ENABLE_GRAMMAR_ENGINE or not is_installed():
            return False
        try:
            import ctranslate2
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(engine_dir() / "tokenizer.json"))
        except Exception:
            return False
        # GPU first when there is one; the warm-up generation is the real
        # test (missing CUDA libraries often only fail on first use). The
        # warm-up also fills the static-prompt cache and measures speed.
        options = [("cpu", "int8", {"intra_threads": hardware.cpu_threads()})]
        if config.USE_GPU and hardware.cuda_devices():
            options.insert(0, ("cuda", "int8_float16", {}))
        for dev, compute, extra in options:
            try:
                generator = ctranslate2.Generator(str(engine_dir()), device=dev,
                                                  compute_type=compute, **extra)
                _generate(generator, tokenizer, "so the meeting is on friday")  # fills the cache
                n, secs, _ = _generate(generator, tokenizer, "i think we should ship it on monday")
            except Exception:
                continue
            _generator, _tokenizer, device = generator, tokenizer, dev
            _speed = n / secs if secs > 0 and n else None
            return True
        return False


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
    contract); download() (Settings -> Models) re-fetches it from
    config.GRAMMAR_HF_REPO any time."""
    import gc
    import shutil

    from . import settings

    unload()
    gc.collect()
    shutil.rmtree(engine_dir(), ignore_errors=True)
    # The user removed it on purpose: don't resume a background download.
    if config.GRAMMAR_PENDING_DOWNLOAD:
        config.GRAMMAR_PENDING_DOWNLOAD = False
        settings.save({"grammar_pending_download": False})


def _static_prompt():
    """The system prompt + few-shot turns: identical on every call, so
    they go to CTranslate2 as static_prompt, whose model state it caches
    after the first call instead of re-reading ~330 tokens per dictation
    (measured 2026-09-27: short dictations 3.2s -> 1.7s with physical-core threads)."""
    p = f"<|im_start|>system\n{_SYSTEM}<|im_end|>\n"
    for spoken, cleaned in _SHOTS:
        p += (f"<|im_start|>user\n{spoken}<|im_end|>\n"
              f"<|im_start|>assistant\n{cleaned}<|im_end|>\n")
    return p


def _user_turn(text):
    return f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"


def _generate(generator, tokenizer, text):
    """One cleanup generation -> (output tokens, seconds, text). Threads:
    hardware.cpu_threads() (physical cores) measured faster than
    CTranslate2's default 4 on a 6-core Ryzen (2026-09-27: long dictation
    8.4s -> 6.4s together with the static prompt)."""
    import time

    static = tokenizer.encode(_static_prompt()).tokens
    tokens = tokenizer.encode(_user_turn(text)).tokens
    start = time.perf_counter()
    result = generator.generate_batch(
        [tokens],
        static_prompt=static,
        max_length=len(tokens) + 250,
        sampling_temperature=0,
        include_prompt_in_result=False,
        end_token="<|im_end|>",
    )[0]
    secs = time.perf_counter() - start
    ids = result.sequences_ids[0]
    return len(ids), secs, tokenizer.decode(ids, skip_special_tokens=True).strip()


def predicted_seconds(text):
    """How long a pass over `text` should take on this PC, from its
    measured speed; None before the engine has measured itself. Output is
    about as long as the input, so input tokens are a fair estimate."""
    if not _speed or _tokenizer is None:
        return None
    return (len(_tokenizer.encode(text).tokens) * 1.15 + 8) / _speed


def _digits_ok(inp, out):
    return sorted(_DIGIT_RUN.findall(inp)) == sorted(_DIGIT_RUN.findall(out))


def _retention_ok(inp, out, strict=False):
    src = _WORD.findall(inp.lower())
    if not src:
        return True
    dst = set(_WORD.findall(out.lower()))
    if strict:
        # Strict (Local): count each occurrence, so "I'm okay, I'm fine."
        # -> "I'm okay." loses an "I'm" instead of hiding behind the other.
        left = Counter(_WORD.findall(out.lower()))
        kept = 0
        for w in src:
            if left[w]:
                left[w] -= 1
                kept += 1
        if kept / len(src) < config.GRAMMAR_LOCAL_MIN_RETENTION:
            return False
    elif sum(1 for w in src if w in dst) / len(src) < config.GRAMMAR_MIN_RETENTION:
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
    # 2026-09-27: per-sentence tightened back to 0.5 (now content words
    # only, so less strict than the July 0.5) after a dropped question got
    # through -- see config.GRAMMAR_MIN_SENTENCE_RETENTION.
    for sentence in re.split(r"(?<=[.!?])\s+", inp):
        words = _WORD.findall(sentence.lower())
        if len(words) < 2:
            continue
        # Content words only for the ratio itself -- a stopword
        # coincidentally surviving elsewhere in the output must not count
        # as this sentence having survived. Falls back to all words for an
        # all-stopword sentence (e.g. "So there it is.") so it isn't
        # trivially exempted instead. The >=2 length gate above stays on
        # the *raw* word count, not this filtered one: a short sentence
        # like "Thank you." is 2 raw words but only 1 content word once
        # "you" is filtered, and gating on the filtered count would drop
        # it below the gate and exempt it from the check entirely -- the
        # exact "whole sentence silently vanishes" failure this guard
        # exists to catch (confirmed live 2026-09-20: a Cloud grammar pass
        # dropped a trailing "Thank you." sentence outright and only
        # happened to get caught by the unrelated second-person guard,
        # since "you" is also a second-person pronoun -- not by this one,
        # which is the actual guard meant to catch a dropped sentence).
        content = [w for w in words if w not in _STOPWORDS] or words
        if sum(1 for w in content if w in dst) / len(content) < config.GRAMMAR_MIN_SENTENCE_RETENTION:
            return False
    return True


def _same_words_ok(inp, out):
    """Strict (Local) only: the output's content words must be the input's,
    give or take an ending ("add" -> "adds"): none new, none lost. Catches a
    swapped word or a dropped phrase the retention ratios can't see in a
    long sentence ("things move in a box" -> "things stay in a box",
    "Painting, he tells us, is..." -> "Painting is...", both 2026-10-11)."""
    a = {w.replace("'", "") for w in _WORD.findall(inp.lower())}
    b = {w.replace("'", "") for w in _WORD.findall(out.lower())}

    def covered(words, other):
        stems = {w[:4] for w in other if len(w) >= 4}
        return all(w in other or w in _STOPWORDS or w.isdigit()
                   or (len(w) >= 4 and w[:4] in stems) for w in words)

    return covered(b, a) and covered(a, b)


_DOTTED = re.compile(r"\w+(?:\.\w+)+")


def _dotted_ok(inp, out):
    """A dotted name ("gmail.com", "settings.py", "2.3.1") must survive
    unbroken -- the strict local prompt made the model write "gmail.com."
    as "gmail. com." (2026-10-13), which every word-based guard accepts."""
    return all(d in out for d in _DOTTED.findall(inp))


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


_NEGATION = re.compile(
    r"\b(?:not|no|nor|never|neither|none|nobody|nothing|nowhere|cannot)\b|n't\b",
    re.IGNORECASE)


def _negation_ok(inp, out):
    """A negation must not vanish: "Nor is his manner less interesting"
    -> "His manner is less interesting" (Local, 2026-10-04) flips the
    meaning while keeping almost every word. Counted, so one "not" lost
    among several is caught too; a rewrite that adds one is fine."""
    norm = lambda s: s.replace("’", "'")
    return len(_NEGATION.findall(norm(out))) >= len(_NEGATION.findall(norm(inp)))


# Word pairs whose swap inverts a sentence while keeping every other word,
# as word-start stems so "postponed"/"postponing" count. Found in the QA
# run of 2026-10-11: Local turned "Please prepone the meeting" into
# "Please postpone the meeting" (Indian English "prepone" read as a typo).
_OPPOSITES = [(a, b) for a, b in (
    ("prepon", "postpon"), ("before", "after"), ("earlier", "later"),
    ("early", "late"), ("increas", "decreas"), ("maxim", "minim"),
    ("above", "below"), ("approv", "reject"), ("accept", "reject"),
    ("accept", "declin"), ("includ", "exclud"), ("enabl", "disabl"),
    ("buy", "sell"), ("bought", "sold"), ("upload", "download"),
    ("import", "export"), ("higher", "lower"), ("ascend", "descend"),
    ("credit", "debit"), ("profit", "loss"), ("allow", "deny"),
    ("tomorrow", "yesterday"), ("next", "previous"), ("more", "less"),
    ("more", "fewer"), ("open", "clos"), ("start", "stop"),
    ("add", "remov"), ("left", "right"), ("win", "los"), ("hire", "fire"),
)]


def _opposites_ok(inp, out):
    """The model must not swap a word for its opposite. For each pair, if
    the output has more of one side than the input did while the input
    used the other side, the rewrite is rejected."""
    lo_in, lo_out = inp.lower(), out.lower()

    def count(stem, s):
        return len(re.findall(r"\b" + stem + r"\w*", s))

    for a, b in _OPPOSITES:
        for x, y in ((a, b), (b, a)):
            if count(y, lo_out) > count(y, lo_in) and count(x, lo_in) > count(x, lo_out):
                return False
    return True


_ANSWER = re.compile(r"\b(?:yes|yeah|yep|yup|nope|please|kindly|thanks|thank)\b",
                     re.IGNORECASE)


def _answer_ok(inp, out):
    """A reply's "Yeah, ..." is the answer, not a filler: Cloud turned
    "Yeah, it's sunny after a rainy day" into "It's sunny..." (QA run
    2026-10-11). Politeness is the speaker's tone, not padding: the same
    run turned "Please prepone the meeting" into "Prepone the meeting"
    (0 of 14 cached outputs with please/thanks drop it, so no false
    alarms). A warm-up "okay so" may still go; it isn't listed."""
    return len(_ANSWER.findall(out)) >= len(_ANSWER.findall(inp))


_HEDGE = re.compile(
    r"\b(?:think|maybe|perhaps|probably|possibly|guess|might|seems?|"
    r"apparently|likely|suppose)\b", re.IGNORECASE)


def _hedge_ok(inp, out):
    """Uncertainty must survive: "For me, I think it's Harry Potter" ->
    "For me, it's Harry Potter" (Local) and "...going forward I think we
    need a check" -> "Going forward, we need a check" (Cloud) turn an
    opinion into a statement (QA run 2026-10-11; 2 of 275 cached outputs,
    both real)."""
    return len(_HEDGE.findall(out)) >= len(_HEDGE.findall(inp))


def _ending_ok(inp, out):
    """No words invented after the end of what was said. A dictation cut
    off mid-sentence (the key released before the thought ended, often to
    go on in the next one) gets "finished" by the model: "...and also the"
    -> "...as well as the file?", "Tell Mr. Bajaj that the Kubernetes" ->
    "...the Kubernetes deployment is ready." (Local, 2026-10-04).

    The output's last word must be one of the input's last three, or the
    same word in another form ("homes" -> "home", "doc" -> "document",
    "did not" -> "didn't"), or a content word from the input's last
    twelve words (reordering a sentence's end: "...wait Sunday morning for one
    hour of G.I. Joe" -> "...one hour of G.I. Joe on Sunday morning").
    Function words like "it" don't count for that last case: "...then we
    cleared" -> "...cleared it." is exactly the invention this catches.
    Measured with tools/grammar_eval/guard_eval.py."""
    norm = lambda s: s.lower().replace("’", "'")
    src = _WORD.findall(norm(inp))
    dst = _WORD.findall(norm(out))
    if len(src) < 3 or not dst:
        return True
    last = dst[-1]

    def same(a, b):
        return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))

    if any(same(last, w) for w in src[-3:]):
        return True
    return last not in _STOPWORDS and last in src[-12:]


def validate(inp, out, strict=False):
    """Run all twelve deterministic guards (thirteen with `strict`, the local
    engine's tighter leash: same words, higher retention) against an (input, output) pair.
    True only if `out` is safe to use in place of `inp`. Shared by the local
    engine's apply() below and cloud_client.grammar_apply() (same leash
    applied to a remote model's output -- see grammar_engine.py's module
    docstring for why the guards exist)."""
    if not out:
        return False
    if strict and not _same_words_ok(inp, out):
        return False
    return (_digits_ok(inp, out) and _dotted_ok(inp, out)
            and _retention_ok(inp, out, strict)
            and _length_ok(inp, out) and _second_person_ok(inp, out)
            and _question_ok(inp, out) and _no_invented_second_person(inp, out)
            and _negation_ok(inp, out) and _ending_ok(inp, out)
            and _opposites_ok(inp, out) and _answer_ok(inp, out)
            and _hedge_ok(inp, out))


def apply(text):
    """Clean `text` through the engine; on any failure or guard rejection
    return it unchanged. Blocking (seconds on CPU) -- call from the
    dictation worker thread only. Skipped (text returned unchanged) when
    this PC's measured speed predicts it would take longer than
    config.GRAMMAR_MAX_SECONDS."""
    global _speed, last_skip
    last_skip = None
    if not text or _generator is None:
        return text
    predicted = predicted_seconds(text)
    if predicted is not None and predicted > config.GRAMMAR_MAX_SECONDS:
        last_skip = f"predicted {predicted:.1f}s > {config.GRAMMAR_MAX_SECONDS:g}s"
        return text
    try:
        with _lock:
            generator, tokenizer = _generator, _tokenizer
            if generator is None:
                return text
            n, secs, out = _generate(generator, tokenizer, text)
            if n and secs > 0:
                # Follow the machine's real speed (thermal throttling,
                # battery saver, other load) rather than one warm-up.
                _speed = n / secs if _speed is None else 0.7 * _speed + 0.3 * (n / secs)
    except Exception:
        return text

    # A thinking-tuned model (Qwen3 family) may emit a reasoning block even
    # unprompted; keep only the answer.
    out = re.sub(r"^<think>.*?</think>\s*", "", out, flags=re.DOTALL).strip()

    if not validate(text, out, strict=True):
        return text
    return out
