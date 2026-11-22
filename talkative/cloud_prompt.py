"""The Cloud grammar prompt, for calls the app makes to Groq itself (the
user's own key, groq_direct.py).

A copy of cloud/worker.js's SYSTEM, SHOTS and plainText(): own-key users
must get exactly what Talkative Cloud users get. tools/groq_prompt_drift_test.py
fails when the two differ -- change both together.
"""

SYSTEM = (
    "You clean up dictated text. Fix grammar and punctuation. Remove word "
    "repetitions, false starts, and spoken self-corrections (keep only what "
    "the speaker corrected themselves to). Most sentences are already "
    "clear and should only get grammar and punctuation fixes -- leave the "
    "speaker's own words, idioms, and phrasing alone even if a plainer or "
    "more formal version occurs to you. Only reword a sentence when it is "
    "genuinely garbled or hard to follow (missing words, tangled syntax), "
    "and even then stay as close to the speaker's own words as you "
    "reasonably can. Never add information or invent claims the speaker "
    "didn't make, never change names or numbers, and never drop something "
    "the speaker actually said. Keep every number exactly as the speaker "
    "said it: number words stay words and digits stay digits. Reply with "
    "only the cleaned text."
)

SHOTS = [
    ["the report the report needs to go out before the meeting starts",
     "The report needs to go out before the meeting starts."],
    ["send the file today, oh sorry, send the file by this evening.",
     "Send the file by this evening."],
    ["we should also check the numbers again before we send it because last "
     "time there was a mistake in the numbers and the client noticed it",
     "We should also check the numbers again before we send it, because last "
     "time there was a mistake in the numbers and the client noticed it."],
    ["there's this issue where when the user clicks the button nothing "
     "happens sometimes it's kind of random",
     "There's an issue where clicking the button sometimes does nothing; "
     "it seems random."],
    ["the call is at four fifteen and the budget is two point five million",
     "The call is at four fifteen, and the budget is two point five million."],
]

# worker.js plainText(): gpt-oss's typographic characters back to ASCII.
_PLAIN = str.maketrans({
    "‘": "'", "’": "'", "‛": "'",
    "“": '"', "”": '"',
    "\xa0": " ", " ": " ", " ": " ", " ": " ",
})


def plain_text(s):
    return s.translate(_PLAIN)


def messages(text):
    """The chat messages worker.js handleGrammar() sends for `text`."""
    out = [{"role": "system", "content": SYSTEM}]
    for spoken, cleaned in SHOTS:
        out.append({"role": "user", "content": spoken})
        out.append({"role": "assistant", "content": cleaned})
    out.append({"role": "user", "content": text})
    return out
