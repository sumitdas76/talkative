"""
Dictation languages on Cloud (Backlog cloud-languages, PROJECT_CHECKS
"Feature 2026-11-23" item 3). The Cloud choice in Settings is one list:
English with a US or Indian accent (as before), then other languages
Whisper transcribes well. One language at a time, never auto-detect: the
Hinglish test (CLAUDE.md, 2026-10-13) showed Whisper's detection labelling
mixed speech English and dropping words. Local stays English (small.en).

The choice is stored in config.SPEECH_SERVICE (settings key
"speech_service"), which already held the accent. cloud/worker.js
LANGUAGES is the server's allow-list for the codes here.

For a language other than English the app skips every rule written for
English -- fillers, spoken corrections, repeat collapsing, number and
bullet formatting, a/an, spoken symbols, lowercasing a continuation (it
would lowercase German nouns) -- and keeps the personal dictionary. Grammar
runs with a line naming the language and only the guards that don't read
English words (grammar_engine.validate(language=...)).
"""

from . import config

# id (stored), label (Settings), Whisper language code, bias prompt.
# Each prompt is the English PUNCTUATION_PROMPT's idea in that language:
# plain sentences with commas and full stops, so Whisper punctuates.
_LIST = [
    ("us_english", "English (US accent)", "en", None),
    ("indian_english", "English (Indian accent)", "en", None),
    ("spanish", "Spanish", "es",
     "Bien, aquí va mi siguiente nota. Dicto frases completas, con comas "
     "donde hacen falta, y cada frase termina con un punto."),
    ("french", "French", "fr",
     "Bon, voici ma prochaine note. Je dicte des phrases complètes, avec des "
     "virgules quand il le faut, et chaque phrase se termine par un point."),
    ("german", "German", "de",
     "Also, hier ist meine nächste Notiz. Ich diktiere ganze Sätze, mit "
     "Kommas, wo sie nötig sind, und jeder Satz endet mit einem Punkt."),
    ("portuguese", "Portuguese", "pt",
     "Bom, aqui vai a minha próxima nota. Eu dito frases completas, com "
     "vírgulas onde é preciso, e cada frase termina com um ponto final."),
    ("italian", "Italian", "it",
     "Allora, ecco la mia prossima nota. Detto frasi complete, con le "
     "virgole dove servono, e ogni frase finisce con un punto."),
    ("dutch", "Dutch", "nl",
     "Oké, hier is mijn volgende notitie. Ik dicteer hele zinnen, met "
     "komma's waar dat nodig is, en elke zin eindigt met een punt."),
]

IDS = [row[0] for row in _LIST]
LABELS = {row[0]: row[1] for row in _LIST}
_CODE = {row[0]: row[2] for row in _LIST}
_PROMPT = {row[0]: row[3] for row in _LIST}
NAMES = {"es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
         "it": "Italian", "nl": "Dutch"}


def code(cloud=True, dev=False):
    """The Whisper language code this dictation uses. Local and the
    developer key (code is English) are always "en"."""
    if not cloud or dev:
        return "en"
    return _CODE.get(config.SPEECH_SERVICE, "en")


def english(cloud=True, dev=False):
    return code(cloud, dev) == "en"


def stt_prompt(cloud=True, dev=False):
    """The bias sentence for this language, or None for English (the caller
    keeps config.PUNCTUATION_PROMPT)."""
    if english(cloud, dev):
        return None
    return _PROMPT.get(config.SPEECH_SERVICE)


# Languages typed without Cloud grammar: on 20 FLEURS clips each
# (tools/lang_eval, 2026-11-23) grammar made Portuguese worse (WER 5.5% ->
# 7.5%: it merged sentences and dropped words along with real accent
# fixes). The others were equal or better (es 3.4/3.4, fr 5.8/5.8,
# de 4.1/4.1, it 3.7/3.4, nl 6.0/5.7).
NO_GRAMMAR = {"pt"}


def grammar_on(language):
    return language not in NO_GRAMMAR


def valid(value):
    return value in IDS
