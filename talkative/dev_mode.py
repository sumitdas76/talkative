"""
Developer English: dictations made with config.DEV_HOTKEY come out as
text that runs -- SQL, terminal/PowerShell commands, and code -- instead
of as sentences.

Each such dictation is first classified:

- **Command / code line** ("select star from users where id equals five",
  "git commit dash m quote fix bug quote", "def add open bracket a comma
  b close bracket colon"). These go through a deterministic rules pass
  only: spoken symbols become characters with code-style spacing, SQL
  keywords are uppercased, casing commands ("camel case user name") build
  identifiers, spoken numbers become digits, and NO sentence period and NO
  grammar model are applied. The grammar model was measured doing the
  right thing only some of the time (and once inventing "stars" for
  "star"); a command that's right 80% of the time is a command you have
  to proofread every time.
- **Prose that mentions tech** ("run it on localhost colon three
  thousand"). Goes through the normal cleanup pipeline (app.py), with a
  few extra, prose-safe fusions first (prose_symbols()).

Rules, not a model, because the same words must give the same output
every time. Pure and local: nothing here touches the network.

Tuned and measured against a 250-phrase spoken test set (SQL Server,
terminal/PowerShell, Python/JS/C#, tech prose) across five voices,
scoring a held-out third that was never used for tuning.
"""

import re

# Shown by Settings -> Hotkeys -> "How to say code…".
HELP_TEXT = """\
Say it                          You get
------------------------------  -------------------------------
star                            *        (count star -> COUNT(*))
equals / equals equals          =  ==    (triple equals ===)
not equal to                    !=
greater than / less than        >  <     (or equal to: >= <=)
plus  minus  times  divided by  +  -  *  /
plus equals / plus plus         +=  ++
open bracket / close bracket    (  )
open/close square bracket       [  ]
open/close curly bracket        {  }
open/close angle bracket        <  >     (List<int>)
quote hello world quote         'hello world' in SQL, "hello world" elsewhere
                                (or: quote hello world unquote)
comma  semicolon  colon         ,  ;  :
dot  underscore  slash          .  _  /
backslash  pipe  arrow          \\  |  =>
and and / or or                 &&  ||
dash m / dash dash force        -m  --force
my dash app                     my-app   (longer words join)
at id (SQL)                     @id      at at version -> @@version
hash temp / dollar env          #temp  $env
tilde                           ~
root at 10.0.0.5                root@10.0.0.5
camel case user name            userName
pascal case user service        UserService
snake case max retries          max_retries
constant case max retries       MAX_RETRIES

Numbers are typed as digits: "eight zero eight zero" -> 8080,
"fifty thousand" -> 50000, "one point five" -> 1.5.
SQL keywords are capitalized for you. Commands get no full stop."""

# ---------------------------------------------------------------------------
# Speech-to-text bias prompt. Whisper-family models copy the prompt's
# style: lowercase, literal symbol words, no sentence punctuation -- so
# spoken symbols come back as the words themselves (converted by the rules
# below) rather than a guessed mix of words and characters. The vocabulary
# covers measured mishearings (varchar -> "varcher", avg -> "average",
# kubectl, nginx, ...). Kept short: Groq caps the prompt at 224 tokens and
# the personal-dictionary vocabulary is appended after it.
# ---------------------------------------------------------------------------
STT_PROMPT = (
    "select star from users where id equals 5 order by name descending "
    "insert into orders open bracket id comma total close bracket "
    "exec sp underscore help varchar nvarchar avg getdate dateadd "
    "git commit dash m quote fix bug quote git push origin main "
    "npm install dash dash save dash dev typescript kubectl nginx docker "
    "cd dot dot pip install numpy pytest json venv winget ipconfig "
    "kubectl get pods dash n yaml github inner join cast len isnull "
    "def add open bracket a comma b close bracket colon "
    "const camel case user name equals await"
)

# ---------------------------------------------------------------------------
# Mishearings -- applied to developer dictations only, before anything
# else. Each one is something a person would essentially never mean
# literally while dictating code ("cube control"), so the fix is safe;
# fixes that only helped the synthetic test voices were not added.
# ---------------------------------------------------------------------------
_MISHEARD = [
    (r"\bexecsp\b", "exec sp"),
    (r"\b(camel|pascal|snake|kebab|constant)[ _-]?case\b", lambda m: m.group(1).lower() + " case"),
    (r"\b(cube|kube|coob) ?(control|ctl|cuttle|cuddle|c t l)\b", "kubectl"),
    (r"\bkube ?ctl\b", "kubectl"),
    (r"\b(engine ?x|en ?jinx|n ?jinx|engine next|anginx|an ?ginx)\b", "nginx"),
    (r"\bjason\b", "json"),
    (r"\bdata ?time\b", "datetime"),
    (r"\bpost ?(grace|gress|gres)\b", "Postgres"),
    (r"\bo ?auth\b", "OAuth"),
    (r"\b(num ?pie|numb ?pie|numpie)\b", "numpy"),
    (r"\bpie ?test\b", "pytest"),
    (r"\btype ?script\b", "typescript"),
    (r"\bjava ?script\b", "javascript"),
    (r"\bn p m\b", "npm"),
    (r"\bn p x\b", "npx"),
    (r"\bdot ?net\b(?= (run|new|build|test|add|restore))", "dotnet"),
    (r"\bwin ?get\b", "winget"),
    (r"\bi ?p ?config\b", "ipconfig"),
    (r"\bnet ?stat\b", "netstat"),
    (r"\btask ?kill\b", "taskkill"),
    (r"\bm ?k ?dir\b|\bmake ?dir\b", "mkdir"),
    (r"^(s s h)\b", "ssh"),
    (r"^(c d)\b", "cd"),
    (r"^(l s)\b", "ls"),
    (r"\bv ?env\b", "venv"),
    (r"\bnode underscore modules\b", "node underscore modules"),
]

# Command-only fixes: never applied to prose ("washed the dish", "you and me").
_MISHEARD_CODE = [
    (r"\b(varcher|warchar|war char|var char|varchard)\b", "varchar"),
    (r"\bn ?varchar\b", "nvarchar"),
    # "exec" said as a word is very often heard as "executive"/"exact"
    # (measured with Indian and US voices) -- never meant literally as the
    # first word of a SQL line, or right after docker/kubectl.
    (r"^(executiv\w*|exact|exeq|exec\.)\b", "exec"),
    (r"\b(docker|kubectl) (executiv\w*|exact)\b", r"\1 exec"),
    # Indian English "dash" is regularly heard as "dish" -- never a word in
    # a command.
    (r"\bdish\b", "dash"),
    # Words run together by fast speech.
    (r"\bgit(merge|push|pull|status|add|commit|checkout|branch|log|diff|stash|"
     r"rebase|reset|clone|fetch|tag|init|remote|switch|restore)\b", r"git \1"),
    (r"\b(npm|yarn|pnpm) run(build|start|test|dev|lint|serve)\b", r"\1 run \2"),
    (r"\bhardhead\b", "hard head"),
    (r"\batversion\b", "at version"),
    (r"\b(get|git)pods\b", "get pods"),
    # "add" heard as "and" right after a package manager / git.
    (r"^(yarn|pnpm|git|dotnet|poetry|cargo) and\b", r"\1 add"),
    (r"\b(geethub|git hub|get hub|gethub|getthub|git hob)\b", "github"),
    # ".txt" is *said* "dot text".
    (r"\bdot text\b", "dot txt"),
    (r"\bdot (yumla|yamel|yammel|yamul)\b", "dot yaml"),
    # Whisper hyphen-fuses a word onto a spoken "quote": "non-quote".
    (r"\b(\w+)-quote\b", r"\1 quote"),
    (r"\bclosed (bracket|paren|parenthesis|brace|square bracket|curly bracket|angle bracket)\b",
     r"close \1"),
    (r"\bopened (bracket|paren|parenthesis|brace|square bracket|curly bracket|angle bracket)\b",
     r"open \1"),
    # Python's "def" heard as "definite"/"deaf" -- only in the def shape.
    (r"^(async )?(definite|deaf|death|diff)\b(?= (\w+ )?(open bracket|underscore))", r"\1def"),
    # "git dash X" is never a git command (flags follow the subcommand):
    # it's PowerShell's Get-X.
    (r"^git dash\b", "get dash"),
    (r"\b(camel|pascal) case git (?!hub\b)", r"\1 case get "),
    (r"\bdata ?time\b", "datetime"),
    (r"\blay (open bracket|\()", r"len \1"),
    (r"\bdollar (nv|n v|and v)\b", "dollar env"),
    (r"\bwin ?jet\b", "winget"),
    # Indian English "close" heard as "clause".
    (r"\bclause (bracket|paren|parenthesis|brace|square bracket|curly bracket|angle bracket)\b",
     r"close \1"),
    # than/then: "less then", "greater then" are never meant in code.
    (r"\b(less|greater|list) then\b", lambda m: ("less" if m.group(1).lower() == "list" else m.group(1)) + " than"),
    # "add" heard as "and" where "and" can't be the word.
    (r"^(const|let|var|function|def|public \w+) and\b", r"\1 add"),
    (r"\band (open bracket|\()", r"add \1"),
    (r"\bpipe ?(grep|grip|sort|where|select|more|findstr|head|tail|wc)\b",
     lambda m: "pipe " + ("grep" if m.group(1).lower() == "grip" else m.group(1))),
    (r"\bdocker compose app\b", "docker compose up"),
    (r"\bdot (jess|jay ess|j s)\b", "dot js"),
    (r"^tri colon\b", "try colon"),
    (r"^use muster\b", "use master"),
    # Indian English "git" is heard as "get" by the large Cloud model, even
    # with the prompt (measured: status/push/merge/stash/pull). PowerShell's
    # Get-X always has its dash, so "get <git subcommand>" is safe.
    # Only command-shaped lines: at most 3 more words, or flags/remotes --
    # so "get status updates from the team every Friday" stays English.
    (r"^get (status|push|pull|merge|stash(ed)?|commit|checkout|branch|log|diff|rebase|"
     r"reset|clone|fetch|add|init|remote|tag|switch|restore|cherry-pick|show)\b"
     r"(?=(\s+\S+){0,3}\s*[.]?$|.*\b(dash|origin|head)\b)",
     lambda m: "git " + ("stash" if m.group(1).lower().startswith("stash") else m.group(1))),
    (r"\bgrouped by\b", "group by"),
    (r"\bdash dash one line\b", "dash dash oneline"),
    (r"\bdash dash dry run\b", "dash dash dry dash run"),
    # Indian English v/w and d/th: "dash we" (-v), "dash the" (-d), "war x".
    (r"\bdash we\b", "dash v"),
    (r"\bdash the\b", "dash d"),
    (r"^war (?=\w+ equals\b)", "var "),
    # Homophones.
    (r"\b(console dot|pascal case) right line\b", r"\1 write line"),
    (r"\bright line open bracket\b", "write line open bracket"),
    (r"^(grab|grip) (?=dash|dish)", "grep "),
    (r"^tusk ?kill\b", "taskkill"),
    (r"^get a dot$", "git add dot"),
    (r"^(get|git) a (?=dash|dot)", "git add "),
    (r"^(asint|a sink|a sync|asynch)\b", "async"),
    (r"^async (definite|deaf|death|diff)\b", "async def"),
    (r"^cdc\b", "cd c"),
    (r"\bdash recurs\b", "dash recurse"),
    # "x times to" -- "two" after an operator.
    (r"\b(times|plus|minus|divided by|equals|equals equals) to\b", r"\1 two"),
    (r"^(ssh|scp)\b(.*)\broute at\b", r"\1\2root at"),
    # More run-together words.
    (r"^use(master|tempdb|msdb)\b", r"use \1"),
    (r"^ping(google|localhost)\b", r"ping \1"),
    (r"^dot ?net ?(run|build|test|new|restore)\b", r"dotnet \1"),
    (r"^tricolon\b", "try colon"),
    (r"^(public|private|protected)-(class|static|void|int|string|async)\b", r"\1 \2"),
    (r"\bgit ?stache?\b", "git stash"),
    (r"\bpipe (grep|grip)(\w{2,})\b", r"pipe grep \2"),
    (r"\bdev(typescript|eslint|prettier|jest|vite|webpack)\b", r"dev \1"),
    (r"^(ch)?mod plus x\b", "chmod plus x"),
    # Quote words: "quotes"/"quota" heard for "quote"; "unquote" / "end
    # quote" / "close quote" close a string, as people naturally say it.
    (r"\bquot(es|a)\b", "quote"),
    (r"\b(unquote|end quote|close quote)\b", "quote"),
    (r"\bopen brackets\b", "open bracket"),
    (r"\bclose brackets\b", "close bracket"),
    # "-p8080": a flag letter fused onto its number.
    (r"\bdash ([a-z])(\d{2,})\b", r"dash \1 \2"),
]


def _prefix_fixes(text, code=True):
    for pattern, repl in _MISHEARD + (_MISHEARD_CODE if code else []):
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
_STRONG_STARTERS = {
    "git", "npm", "npx", "pip", "pip3", "python", "python3", "py", "node",
    "cd", "ls", "dir", "mkdir", "rmdir", "rm", "cp", "mv", "cat", "echo",
    "grep", "docker", "kubectl", "ssh", "scp", "curl", "wget", "yarn",
    "pnpm", "dotnet", "cargo", "winget", "choco", "sudo", "chmod", "touch",
    "def", "const", "let", "var", "console", "elif", "exec", "execute",
    "truncate", "sqlcmd", "wsl", "javac", "java", "tsc", "pytest",
    "ipconfig", "netstat", "taskkill", "ping", "tracert", "nslookup",
    "self", "this", "lambda", "assert", "raise", "export", "public",
    "private", "protected", "static", "void", "except", "finally",
    "document", "window", "json", "os", "sys", "np", "pd", "kill",
}
# Commands that are also everyday verbs: only a command when the line has
# something command-like in it (a host, flag, path, number) or is short.
_ENGLISHY_COMMANDS = {"ping", "kill", "touch", "cat", "echo", "code"}
_WEAK_STARTERS = {
    "select", "insert", "update", "delete", "create", "alter", "drop",
    "begin", "commit", "rollback", "use", "declare", "with", "set", "if",
    "for", "while", "return", "import", "from", "print", "class", "function",
    "async", "await", "try", "else", "get", "new", "remove", "start",
    "stop", "invoke", "test", "list", "items", "code",
    "grant", "result", "data", "user", "total", "count", "sort", "where",
}
_CODE_SIGNAL = re.compile(
    r"\b(equals|open (square |curly |angle )?(bracket|paren|parenthesis|brace)|"
    r"close (square |curly |angle )?(bracket|paren|parenthesis|brace)|semicolon|"
    r"underscore|star|dash|camel case|pascal case|snake case|"
    r"constant case|plus equals|minus equals|not equal to|greater than|"
    r"less than|arrow|backslash|pipe|and and|or or)\b|[=(){}\[\];*]|"
    r"\bcolon[.]?$",
    re.IGNORECASE,
)
# Strong enough on its own, whatever the first word.
_STRONG_SIGNAL = re.compile(
    r"\b(open (square |curly |angle )?(bracket|paren|parenthesis|brace)|"
    r"close (square |curly |angle )?(bracket|paren|parenthesis|brace)|semicolon|"
    r"camel case|pascal case|snake case|constant case|kebab case|"
    r"equals equals|not equal to|plus equals|minus equals|dash dash|"
    r"plus plus|and and|or or|dollar env)\b|[(){};]|==|!=",
    re.IGNORECASE,
)
# "x equals x times two", "self dot name equals name", "total minus equals
# discount" -- an assignment is code whatever the variable is called.
_ASSIGNMENT = re.compile(
    r"^[a-z_][\w]*((\s+dot\s+|\.)[a-z_]\w*)*\s+(equals|plus equals|minus equals|times equals)\b",
    re.IGNORECASE,
)
_SQL_SHAPES = re.compile(
    r"^(select\b.*\bfrom\b|select (top|count|star|\*|distinct|getdate|newid|at at|@@)\b|"
    r"insert into\b|update \S+ set\b|delete from\b|"
    r"create (table|index|view|procedure|proc|database|unique)\b|"
    r"alter (table|view|procedure|database)\b|"
    r"drop (table|index|view|procedure|database)\b|"
    r"begin (transaction|tran)\b|(commit|rollback)( transaction| tran)?$|"
    r"use \S+$|declare (at |@)|set (nocount|ansi_nulls|quoted_identifier|xact_abort|"
    r"identity_insert|statistics|transaction)\b|grant \w+ on\b|print quote\b|with \w+ as\b)",
    re.IGNORECASE,
)
_SQL_STARTERS = {
    "select", "insert", "update", "delete", "create", "alter", "drop",
    "exec", "execute", "begin", "commit", "rollback", "truncate", "use",
    "declare", "with", "merge", "grant",
}
_SHORT_CODE = re.compile(r"^(import|from|return|print)\b", re.IGNORECASE)
# Python import shapes are code at any length.
_IMPORT_SHAPE = re.compile(r"^(from \S+ import \S+|import \S+( as \S+)?$)", re.IGNORECASE)
_PS_VERBS = {
    "get", "set", "new", "remove", "start", "stop", "restart", "invoke",
    "test", "import", "export", "add", "clear", "copy", "move", "rename",
    "select", "where", "write", "out", "format", "convert", "measure",
    "sort", "group", "enable", "disable", "install", "uninstall", "update",
    "push", "pop", "resolve", "split", "join", "wait", "show", "foreach",
}


def _first_word(text):
    m = re.match(r"\s*([A-Za-z][\w'-]*)", text)
    return m.group(1).lower() if m else ""


def is_code_line(raw):
    """Classify with prose-safe fixes only; the command-only fixes (dish ->
    dash, executive -> exec) count only when they turn the first word into
    a command -- otherwise "I washed the dish" would read as code."""
    safe = _prefix_fixes(raw.strip(), code=False)
    if _classify(safe):
        return True
    fixed = _prefix_fixes(raw.strip(), code=True)
    return _first_word(fixed) != _first_word(safe) and _classify(fixed)


def _classify(text):
    if _first_word(text) in _SQL_STARTERS and _SQL_SHAPES.match(_sql_fix_words(text).rstrip(".")):
        return True
    first = _first_word(text)
    if not first:
        return bool(_CODE_SIGNAL.search(text))
    head = first.split("-")[0]
    if "-" in first and head in _PS_VERBS:
        return True                                   # Get-ChildItem ...
    if first in _ENGLISHY_COMMANDS:
        # "ping me when it's green" is English; "ping google dot com" isn't.
        return bool(re.search(
            r"\b(dot|dash|slash|colon|localhost|pipe|greater than)\b|[.\-/:|]\S|\d", text))
    if first in _STRONG_STARTERS or head in _STRONG_STARTERS:
        return True
    body = text.rstrip(".")
    if _SQL_SHAPES.match(body) or _ASSIGNMENT.match(body) or _IMPORT_SHAPE.match(body):
        return True
    if _STRONG_SIGNAL.search(text):
        return True
    if first in _WEAK_STARTERS and _CODE_SIGNAL.search(text):
        return True
    if head in _PS_VERBS and re.match(r"(?i)^\w+ dash \w", text):
        return True                                   # get dash process
    if _SHORT_CODE.match(text) and len(text.split()) <= 5:
        return True
    return False


def is_sql(text):
    first = _first_word(text)
    if first == "print":                              # T-SQL PRINT 'x' vs print(x)
        return bool(re.match(r"(?i)^print (quote|')", text))
    if first == "with":                               # CTE vs Python's with open(...)
        return bool(re.match(r"(?i)^with \w+ as (open bracket|\()", text))
    return first in _SQL_STARTERS or bool(re.match(r"(?i)^set (nocount|xact_abort|ansi_nulls)", text))


# ---------------------------------------------------------------------------
# Spoken numbers -> digits
# ---------------------------------------------------------------------------
_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES)


def _parse_number(words):
    """A run of number words -> digit string. Digit-by-digit runs ("eight
    zero eight zero", "zero one") become the digits concatenated; cardinal
    phrases ("fifty thousand", "two thousand twenty four") are summed;
    "fourteen thirty three" (two-digit pairs, as ports and years are said)
    concatenates."""
    if len(words) > 1 and all(w in _UNITS and _UNITS[w] < 10 for w in words):
        return "".join(str(_UNITS[w]) for w in words)
    if (len(words) >= 2 and words[0] in _UNITS and 10 <= _UNITS[words[0]] < 20
            and not any(w in _SCALES for w in words)):
        return str(_UNITS[words[0]]) + _parse_number(words[1:]).zfill(2)
    total = current = 0
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        else:  # thousand / million
            total += max(current, 1) * _SCALES[w]
            current = 0
    return str(total + current)


def _numbers(tokens):
    out, run = [], []

    def flush():
        if run:
            out.append(_parse_number(run))
            run.clear()

    for tok in tokens:
        low = tok.lower()
        if low in _NUMBER_WORDS and not (low == "oh" and not run):
            run.append(low)
        else:
            flush()
            out.append(tok)
    flush()
    # "1 point 5" / "1.2 point 3" -> 1.5 / 1.2.3 (versions, decimals)
    merged = []
    for tok in out:
        if (len(merged) >= 2 and merged[-1].lower() == "point"
                and re.fullmatch(r"[\d.]+", merged[-2]) and re.fullmatch(r"\d+", tok)):
            merged.pop()
            merged[-1] = merged[-1] + "." + tok
        else:
            merged.append(tok)
    # "v 1.3.5" -> v1.3.5
    final = []
    for tok in merged:
        if final and final[-1].lower() == "v" and re.fullmatch(r"\d[\d.]*", tok):
            final[-1] = final[-1] + tok
        else:
            final.append(tok)
    return final


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
# Marker kinds (first char of a marker token):
#   \x01 spaced operator      \x02 opener         \x03 closer
#   \x04 attaches left        \x05 fuses both      \x06 quote
#   \x07 dash (resolved later to flag/hyphen)      \x08 star
#   \x09 comma                \x0b colon           \x0d prefix (space
#   before, fuses after: -m, #temp, @id, ..)
_MARKERS = "\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0b\x0d"
_SYMBOL_PHRASES = [
    ("greater than or equal to", "\x01>="), ("less than or equal to", "\x01<="),
    ("open square bracket", "\x02["), ("close square bracket", "\x03]"),
    ("open curly bracket", "\x02{"), ("close curly bracket", "\x03}"),
    ("open curly brace", "\x02{"), ("close curly brace", "\x03}"),
    ("open angle bracket", "\x05<"), ("close angle bracket", "\x03>"),
    ("open parenthesis", "\x02("), ("close parenthesis", "\x03)"),
    ("open bracket", "\x02("), ("close bracket", "\x03)"),
    ("open paren", "\x02("), ("close paren", "\x03)"),
    ("open brace", "\x02{"), ("close brace", "\x03}"),
    ("not equal to", "\x01!="), ("not equals", "\x01!="),
    ("equals equals equals", "\x01==="), ("triple equals", "\x01==="),
    ("equals equals", "\x01=="), ("double equals", "\x01=="),
    ("is equal to", "\x01="), ("equal to", "\x01="),
    ("greater than", "\x01>"), ("less than", "\x01<"),
    ("plus equals", "\x01+="), ("minus equals", "\x01-="),
    ("times equals", "\x01*="), ("plus plus", "\x04++"),
    ("minus minus", "\x04--"),
    ("fat arrow", "\x01=>"), ("arrow", "\x01=>"),
    ("double ampersand", "\x01&&"), ("and and", "\x01&&"),
    ("double pipe", "\x01||"), ("or or", "\x01||"),
    ("forward slash", "\x05/"), ("back slash", "\x05\\"),
    ("single quote", "\x06'"), ("double quote", '\x06"'),
    ("at sign", "\x05@"), ("at symbol", "\x05@"),
    ("question mark", "\x04?"), ("exclamation mark", "\x04!"),
    ("dash dash", "\x07--"), ("double dash", "\x07--"),
    ("dot dot", "\x0d.."),
    ("divided by", "\x01/"),
    ("equals", "\x01="), ("equal", "\x01="), ("plus", "\x01+"),
    ("minus", "\x01-"), ("times", "\x01*"), ("star", "\x08*"),
    ("asterisk", "\x08*"), ("percent", "\x05%"), ("comma", "\x09,"),
    ("semicolon", "\x04;"), ("colon", "\x0b:"), ("dot", "\x05."),
    ("underscore", "\x05_"), ("slash", "\x05/"),
    ("backslash", "\x05\\"), ("pipe", "\x01|"), ("ampersand", "\x01&"),
    ("dash", "\x07-"), ("hyphen", "\x07-"), ("hash", "\x0d#"),
    ("dollar", "\x0d$"), ("tilde", "\x05~"), ("backtick", "\x06`"),
    ("quote", "\x06Q"),
]
_PHRASES = sorted(((p.split(), s) for p, s in _SYMBOL_PHRASES),
                  key=lambda ps: -len(ps[0]))


def _symbols(tokens):
    out, i = [], 0
    low = [t.lower() for t in tokens]
    while i < len(tokens):
        for words, sym in _PHRASES:
            n = len(words)
            if low[i:i + n] == words:
                out.append(sym)
                i += n
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def _is_marker(tok, kinds=_MARKERS):
    return bool(tok) and tok[0] in kinds


def _is_num(tok):
    return bool(re.fullmatch(r"\d[\d.]*", tok or ""))


def _is_word(tok):
    return bool(tok) and not _is_marker(tok)


# ---------------------------------------------------------------------------
# Casing commands
# ---------------------------------------------------------------------------
_CASINGS = {
    ("camel", "case"): lambda ws: ws[0].lower() + "".join(w.capitalize() for w in ws[1:]),
    ("pascal", "case"): lambda ws: "".join(w.capitalize() for w in ws),
    ("snake", "case"): lambda ws: "_".join(w.lower() for w in ws),
    ("constant", "case"): lambda ws: "_".join(w.upper() for w in ws),
    ("kebab", "case"): lambda ws: "-".join(w.lower() for w in ws),
}
# A casing command takes the following plain words, up to the next symbol
# word or code keyword -- "camel case get user open bracket" -> getUser(.
_CASING_STOP = {
    "await", "async", "return", "new", "const", "let", "var", "if", "else",
    "for", "while", "in", "of", "and", "or", "not", "is", "as", "from",
    "import", "def", "class", "function", "select", "where", "set", "into",
    "values", "on", "by", "then", "true", "false", "none", "null", "int",
    "string", "public", "private",
}
_CASING_STOP |= {p.split()[0] for p, _ in _SYMBOL_PHRASES}


def _casing(tokens):
    out, i = [], 0
    while i < len(tokens):
        pair = tuple(t.lower() for t in tokens[i:i + 2])
        fn = _CASINGS.get(pair)
        if fn is None:
            out.append(tokens[i])
            i += 1
            continue
        j = i + 2
        words = []
        while (j < len(tokens) and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", tokens[j])
               and (tokens[j].lower() not in _CASING_STOP
                    or (tokens[j].lower() in ("by", "id", "in", "on") and words))
               and tuple(t.lower() for t in tokens[j:j + 2]) not in _CASINGS):
            # "get element by id" is one identifier; stop words only end
            # it when they'd start a new clause.
            if tokens[j].lower() in ("in", "on") and words:
                break
            words.append(tokens[j])
            j += 1
        if words:
            out.append(fn(words))
        i = j
    return out


# ---------------------------------------------------------------------------
# Context-sensitive markers, resolved on the token list before assembly
# ---------------------------------------------------------------------------
_DOTFILES = {"env", "venv", "gitignore", "vscode", "github", "npmrc", "bashrc",
             "zshrc", "dockerignore", "editorconfig", "prettierrc", "eslintrc",
             "profile", "config"}
_SHORT_FLAGS = {"ano", "aux", "xvf", "xzf", "czf", "lah", "lrt", "ef"}
_NO_CALL = {"if", "while", "for", "switch", "catch", "return", "and", "or",
            "not", "in", "elif", "with", "using", "lock", "foreach", "when",
            "as", "is", "else", "yield", "await", "new"}
_UNDERSCORE_KEYWORDS = {"def", "class", "return", "import", "from", "const",
                        "let", "var", "new", "print", "self"}


def _resolve(tokens, sql, powershell):
    t = list(tokens)
    n = len(t)
    for k in range(n):
        tok = t[k]
        prev = t[k - 1] if k > 0 else None
        nxt = t[k + 1] if k + 1 < n else None

        if tok == "\x07-":
            # dash: hyphen inside a name vs a command-line flag. Real
            # short flags are 1-2 letters (-t -it -rf) or a known few
            # longer ones; a longer word after a dash is a name (my-app).
            if _is_num(prev) and _is_num(nxt):
                t[k] = "\x05-"                       # 2024-01-01
            elif (k >= 2 and t[k - 2] in ("\x07--", "\x0d--") and _is_word(prev)
                  and nxt and re.fullmatch(r"[A-Za-z]+", nxt)):
                t[k] = "\x05-"                       # --save-dev, --no-ff (not --oneline -5)
            elif (powershell and prev and prev.lower() in _PS_VERBS
                  and k >= 2 and t[k - 2] == "\x01|"):
                t[k] = "\x05-"                       # ... | Sort-Object
            elif powershell and k > 1:
                t[k] = "\x0d-"                       # -Recurse
            elif nxt and _is_word(nxt) and (len(nxt) <= 2 or _is_num(nxt)
                                            or nxt.lower() in _SHORT_FLAGS):
                t[k] = "\x0d-"                       # -it -m -5 -ano
            elif prev is None or _is_marker(prev, "\x01\x02\x09"):
                t[k] = "\x0d-"
            else:
                t[k] = "\x05-"                       # my-app old-feature
        elif tok == "\x07--":
            t[k] = "\x0d--"
        elif tok == "\x01-" and (prev is None or _is_marker(prev, "\x01\x02\x09")) and _is_num(nxt):
            t[k] = "\x0d-"                           # DATEADD(DAY, -7, ...)
        elif tok == "\x05_" and prev and prev.lower() in _UNDERSCORE_KEYWORDS:
            t[k] = "\x0d_"                           # def __init__
        elif tok == "\x05~":
            if k == 1 or (prev and prev.lower() in ("cd", "ls", "cat", "code")):
                t[k] = "\x0d~"                       # cd ~/projects
        elif tok == "\x05/":
            # Windows switches (ipconfig /all, taskkill /f /im) vs paths
            # (feature/login). A switch follows the command itself or
            # another switch's word.
            if k == 1 and _is_word(prev) and not sql and nxt and _is_word(nxt) and len(nxt) <= 4:
                t[k] = "\x0d/"
            elif (k >= 3 and t[k - 2] == "\x0d/" and _is_word(prev)
                  and nxt and _is_word(nxt) and len(nxt) <= 4):
                t[k] = "\x0d/"
        elif tok == "\x05.":
            if not sql and nxt is None and prev is not None and (_is_word(prev) or prev == "\x06Q"):
                t[k] = "\x0d."                       # git add .  docker build -t x .
            elif (nxt and nxt.lower() in _DOTFILES and prev is not None
                  and (_is_word(prev) or _is_marker(prev, "\x0d"))):
                t[k] = "\x0d."                       # .env .venv
            elif prev is None:
                t[k] = "\x0d."
    return t


def _at_signs(tokens, sql):
    """A spoken "at" becomes @:
    - SQL: "at id" -> @id, "at at version" -> @@version (variables);
    - "at types slash node" -> @types/node (scoped npm package);
    - right before an address: root at 192.168.1.10, ubuntu at 10.0.0.5,
      at gmail dot com, root at server colon -- fused both sides.
    Anything else ("created at") stays a word."""
    out = list(tokens)
    k = 0
    while k < len(out) - 1:
        tok = out[k]
        if tok.lower() != "at":
            k += 1
            continue
        nxt = out[k + 1]
        after = out[k + 2] if k + 2 < len(out) else ""
        address = (re.match(r"\d", nxt) or re.match(r"[A-Za-z][\w-]*\.[A-Za-z]", nxt)
                   or (re.fullmatch(r"[A-Za-z][\w-]*", nxt) and after in ("\x05.", "\x0b:")))
        if sql and nxt.lower() == "at":
            out[k] = "\x0d@@"
            del out[k + 1]
        elif address:
            out[k] = "\x05@"                         # sumit@example.com, root@10.0.0.5
        elif re.fullmatch(r"[A-Za-z][\w-]*", nxt) and after == "\x05/":
            out[k] = "\x0d@"                         # @types/node
        elif sql and re.fullmatch(r"[A-Za-z_]\w*", nxt) and nxt.lower() not in ("least",):
            out[k] = "\x0d@"                         # @id
        k += 1
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
_SQL_FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "getdate", "sysdatetime", "isnull",
    "coalesce", "len", "cast", "convert", "upper", "lower", "trim", "ltrim",
    "rtrim", "substring", "round", "abs", "newid", "datediff", "dateadd",
    "year", "month", "day", "format", "concat", "replace", "charindex",
    "row_number", "rank", "object_id", "scope_identity", "identity",
    "dense_rank", "lag", "lead", "iif", "try_cast", "try_convert",
}
_SQL_TYPES_WITH_ARGS = {"varchar", "nvarchar", "char", "nchar", "decimal",
                        "numeric", "varbinary", "datetime2", "float"}


def _assemble(tokens, sql):
    parts = []  # [text, kind]
    for tok in tokens:
        if _is_marker(tok):
            parts.append([tok[1:], tok[0]])
        else:
            parts.append([tok, "w"])

    # Quote pairing: "quote shipped quote" -> 'shipped'. SQL strings use
    # single quotes, everything else double; an unpaired quote stays.
    qchar = "'" if sql else '"'
    qidx = [k for k, (_, kind) in enumerate(parts) if kind == "\x06"]
    for a, b in zip(qidx[0::2], qidx[1::2]):
        ch = qchar if parts[a][0] == "Q" else parts[a][0]
        inner = _assemble_raw(parts[a + 1:b], sql)
        kind = "w"
        # f"hello", r"\d+", b"bytes" -- a string prefix fuses to its quote.
        # (Not after a flag dash: in grep -r "todo" the r is the flag.)
        if (a > 0 and parts[a - 1] and parts[a - 1][1] == "w"
                and parts[a - 1][0] in ("f", "r", "b", "rb", "fr")
                and not (a > 1 and parts[a - 2] and parts[a - 2][1] == "\x0d")):
            parts[a - 1][0] += ch + inner + ch
            parts[a] = None
        else:
            parts[a] = [ch + inner + ch, kind]
        for k in range(a + 1, b + 1):
            parts[k] = None
    parts = [p for p in parts if p is not None]
    for p in parts:
        if p[1] == "\x06":  # unpaired
            p[0], p[1] = (qchar if p[0] == "Q" else p[0]), "\x05"
    return _assemble_raw(parts, sql)


def _assemble_raw(parts, sql=False):
    out = ""
    prev_kind = None
    prev_text = ""
    for text, kind in parts:
        if not out:
            out = text
        else:
            space = True
            if kind in ("\x04", "\x09"):                  # ; , ++ attach left
                space = False
            elif kind == "\x03":
                # closers attach left, except "}" which is spaced ("{ get; }")
                # unless it closes an empty pair ("{}").
                space = text == "}" and prev_text != "{"
            elif kind == "\x05" or prev_kind == "\x05":   # fuses both sides
                space = False
            elif prev_kind == "\x0d":                     # after a prefix
                space = False
            elif prev_kind == "\x02":                     # after an opener
                space = prev_text == "{"
            elif kind == "\x02":
                # "(" / "[" attach to a function or variable name: range(10),
                # getUser(id), COUNT(*), items[0]. In SQL only known
                # functions/types take it -- "products (name, price)" and
                # "FROM [order]" keep their space. "{" is always spaced.
                prev_low = prev_text.lower()
                if text == "{":
                    space = True
                elif prev_kind == "w" and re.fullmatch(r"[A-Za-z_][\w.]*", prev_text):
                    if sql:
                        space = not (text == "(" and (prev_low in _SQL_FUNCTIONS
                                                      or prev_low in _SQL_TYPES_WITH_ARGS))
                    else:
                        space = prev_low in _NO_CALL
                elif prev_kind in ("\x03", "\x04") and not sql and prev_text != "}":
                    space = False
            elif kind == "\x0b":
                space = False                              # colon attaches left
            elif prev_kind == "\x0b":
                # ...and right only for ports, drives, URLs, and $env:path
                space = not (re.match(r"[\d\\/]", text) or out.lower().endswith("$env:"))
            elif kind == "\x08" and prev_kind == "\x02":
                space = False
            out += (" " if space else "") + text
        prev_kind, prev_text = kind, text
    return out


# ---------------------------------------------------------------------------
# SQL finishing
# ---------------------------------------------------------------------------
_SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "null", "is", "in", "like",
    "order", "by", "group", "having", "top", "desc", "asc", "insert", "into",
    "values", "update", "set", "delete", "create", "table", "index", "view",
    "procedure", "proc", "alter", "add", "drop", "if", "exists", "exec",
    "execute", "begin", "transaction", "tran", "commit", "rollback",
    "truncate", "use", "join", "inner", "left", "right", "outer", "full",
    "cross", "on", "as", "distinct", "primary", "key", "foreign",
    "references", "default", "unique", "constraint", "check", "between",
    "case", "when", "then", "else", "end", "union", "all", "offset", "fetch",
    "next", "rows", "only", "declare", "with", "int", "bigint", "smallint",
    "tinyint", "bit", "decimal", "numeric", "float", "real", "varchar",
    "nvarchar", "char", "nchar", "text", "date", "datetime", "datetime2",
    "time", "uniqueidentifier", "identity", "column", "database", "go",
    "output", "merge", "grant", "nocount", "to", "print", "max", "cascade",
    "nolock", "clustered", "nonclustered", "over", "partition", "return",
    "returns", "function", "trigger", "after", "instead", "of", "for",
} | _SQL_FUNCTIONS
_SQL_MISHEARD = {
    "var char": "varchar", "average": "avg", "descending": "desc",
    "ascending": "asc", "get date": "getdate", "exec sp-": "exec sp_",
    "date add": "dateadd", "date diff": "datediff", "is null": "is null",
}


def _sql_fix_words(text):
    for wrong, right in _SQL_MISHEARD.items():
        text = re.sub(r"\b" + re.escape(wrong) + r"\b", right, text, flags=re.IGNORECASE)
    # "isnull open bracket" said as "is null open bracket" is the function.
    text = re.sub(r"(?i)\bis null (open bracket|\()", r"isnull \1", text)
    text = re.sub(r"(?i)\b(git date|gitdate|get date|getdate)\b", "getdate", text)
    # CAST( heard as "cost (": only with the CAST ... AS shape, so a real
    # "cost" column is untouched.
    text = re.sub(r"(?i)\bcost (open bracket|\()(?=[^()]*\bas\b)", r"cast \1", text)
    # INNER JOIN heard as "in the join" / "in a join".
    text = re.sub(r"(?i)\bin (the|a|er) join\b", "inner join", text)
    text = re.sub(r"(?i)\bconstrain\b", "constraint", text)
    text = re.sub(r"(?i)(open bracket |\()elect\b", r"\1select", text)
    text = re.sub(r"(?i)\bbrackets elect\b", "bracket select", text)
    # Column types heard as other words, inside CREATE/ALTER TABLE only:
    # "id and primary key" (int), "message and varchar" (n + varchar),
    # and CAST(x AS "in").
    if re.match(r"(?i)^(create|alter) table\b", text):
        text = re.sub(r"(?i)\b(\w+) (and|in) (primary key|not null|identity|null)\b", r"\1 int \3", text)
        text = re.sub(r"(?i)\b(\w+) and varchar\b", r"\1 nvarchar", text)
    text = re.sub(r"(?i)\bas in\b(?= (close bracket|\)))", "as int", text)
    # Type names as heard from Indian English speakers, only right before
    # a size ("name virtue 50", "message navature 255/max").
    text = re.sub(r"(?i)\b(navature|n virtue|nav char|en varchar|and virtue)\b(?= (\d+|max)\b)", "nvarchar", text)
    text = re.sub(r"(?i)\b(virtue|virture|vachar|varcha)\b(?= (\d+|max)\b)", "varchar", text)
    # Homophone function names, only as calls.
    text = re.sub(r"(?i)\bsome (?=open bracket|\()", "sum ", text)
    text = re.sub(r"(?i)\b(colis|coalish|co ?lease|coalis|coal esce)\s(?=open bracket|\()", "coalesce ", text)
    text = re.sub(r"(?i)^select new id$", "select newid", text)
    text = re.sub(r"(?i)^set (knockout|no count|now count)\b", "set nocount", text)
    text = re.sub(r"(?i)^use v?master\b", "use master", text)
    text = re.sub(r"(?i)\bcomma to\b(?= close bracket|\))", "comma two", text)
    # Table aliases heard as words, only between a table and JOIN/ON/WHERE:
    # "roles are on" -> roles r on, "users you inner join" -> users u.
    aliases = {"you": "u", "are": "r", "see": "c", "sea": "c", "oh": "o",
               "or": "o", "bee": "b", "pee": "p", "tea": "t", "tee": "t"}
    seen = {}

    def alias(m):
        word = m.group(3).lower()
        seen[word] = aliases[word]
        return f"{m.group(1)} {m.group(2)} {aliases[word]} "

    text = re.sub(
        r"(?i)\b(from|join) (\w+) (you|are|see|sea|oh|or|bee|pee|tea|tee) "
        r"(?=(inner|left|right|full|cross|join|on|where|comma|group|order)\b)",
        alias, text)
    # ...and that alias's later uses: "you dot role" -> u dot role
    for word, letter in seen.items():
        text = re.sub(rf"(?i)\b{word} (?=dot\b)", letter + " ", text)
    # "50 000" -> 50000 (thousands written with a space)
    text = re.sub(r"\b(\d{1,3}) (000)\b", r"\1\2", text)
    text = re.sub(r"(?i)^(alter table \S+) and\b", r"\1 add", text)
    text = re.sub(r"(?i)\b(isnel|is nel|isnul)\b", "isnull", text)
    # "alter table orders at discount" -- "add" misheard, right after ALTER TABLE <name>.
    text = re.sub(r"(?i)^(alter table \S+) at\b", r"\1 add", text)
    # "create index 9 underscore ..." -- "ix" heard as the digit.
    text = re.sub(r"(?i)^(create (unique )?index) 9 (underscore\b|_)", r"\1 ix \3", text)
    return text


def _sql_finish(text):
    def up(m):
        w = m.group(0)
        return w.upper() if w.lower() in _SQL_KEYWORDS else w

    # Keywords uppercased outside 'strings' and [bracketed names] only.
    pieces = re.split(r"('[^']*'|\[[^\]]*\])", text)
    for k in range(0, len(pieces), 2):
        pieces[k] = re.sub(r"(?<![@#\w])[A-Za-z_][A-Za-z0-9_]*", up, pieces[k])
    text = "".join(pieces)
    text = re.sub(r"\bCOUNT \*", "COUNT(*)", text)
    text = re.sub(r"\b(GETDATE|SYSDATETIME|NEWID|SCOPE_IDENTITY)\b(?!\()", r"\1()", text)
    text = re.sub(r"\b(VARCHAR|NVARCHAR|CHAR|NCHAR|VARBINARY)\s+(\d+|MAX)\b(?!\s*,)",
                  r"\1(\2)", text)
    text = re.sub(r"\b(DECIMAL|NUMERIC)\s+(\d+)\s*,\s*(\d+)\b", r"\1(\2, \3)", text)
    text = re.sub(r"\b(DECIMAL|NUMERIC)\s+(\d+)\b(?!\s*[,(])", r"\1(\2)", text)
    return text


# ---------------------------------------------------------------------------
# PowerShell: Get-ChildItem -Recurse, Get-Process | Sort-Object cpu
# ---------------------------------------------------------------------------
_PS_NOUNS = {  # multi-word nouns, joined into one PascalCase noun
    ("child", "item"), ("item", "property"), ("execution", "policy"),
    ("net", "adapter"), ("net", "ip", "address"), ("web", "request"),
    ("rest", "method"), ("local", "user"), ("scheduled", "task"),
    ("event", "log"), ("win", "event"), ("computer", "info"),
    ("select", "string"), ("location",), ("content",),
}


def _powershell(text):
    def cmdlet(m):
        verb, rest = m.group(1), m.group(2)
        words = rest.split()
        for size in (3, 2):
            if tuple(w.lower() for w in words[:size]) in _PS_NOUNS:
                noun = "".join(w.capitalize() for w in words[:size])
                return f"{verb.capitalize()}-{noun}" + "".join(" " + w for w in words[size:])
        return f"{verb.capitalize()}-{words[0].capitalize()}" + "".join(" " + w for w in words[1:])

    verbs = "|".join(sorted(_PS_VERBS, key=len, reverse=True))
    # Everything up to the first parameter/pipe is noun + arguments;
    # cmdlet() takes a known multi-word noun or else just the first word.
    text = re.sub(rf"(?i)(?:^|(?<=\| ))({verbs})-([A-Za-z]+(?: [A-Za-z]+)*)(?![A-Za-z])",
                  cmdlet, text)
    # Parameters after a cmdlet: -recurse -> -Recurse
    if re.match(r"^[A-Z][a-z]+-[A-Z]", text):
        text = re.sub(r"(?<=\s)-([a-z])", lambda x: "-" + x.group(1).upper(), text)
    return text


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
_THOUSANDS = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")


def _join_spelled(tokens):
    """"i n i t" -> "init": a run of 3+ single letters is a spelled word.
    ("a", "i" alone, or two letters, stay: "x y" could be two variables.)"""
    out, run = [], []

    def flush():
        if len(run) >= 3:
            out.append("".join(run))
        else:
            out.extend(run)
        run.clear()

    for tok in tokens:
        if re.fullmatch(r"[A-Za-z]", tok):
            run.append(tok.lower())
        else:
            flush()
            out.append(tok)
    flush()
    return out


def code_line(raw):
    text = _prefix_fixes(raw.strip().replace("‑", "-").replace("’", "'"))
    # Whisper sometimes writes a spoken "dot dot" as "..." ("cd...") --
    # before the sentence-end strip below would eat it.
    text = re.sub(r"(?<=\w)\.\.\.?(?=\s|$)", " dot dot", text)
    text = re.sub(r"[.!?]+$", "", text).strip()           # Whisper's sentence end
    text = _THOUSANDS.sub(lambda m: m.group(0).replace(",", ""), text)
    sql = is_sql(text)
    if sql:
        text = _sql_fix_words(text)
    # Split symbols Whisper already wrote as characters off their words.
    text = text.replace(",", " comma ")
    text = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " dash ", text)
    tokens = _join_spelled(text.split())
    plain = set(tokens)
    tokens = _casing(tokens)
    built = set(tokens) - plain                       # identifiers from casing commands
    tokens = _numbers(tokens)
    tokens = _symbols(tokens)
    tokens = _at_signs(tokens, sql)
    if not sql:
        # "Git status", "SSH root", "For I in" -- Whisper's sentence casing,
        # not the developer's: commands and keywords are lowercase, and a
        # lone "I" in code is the loop variable i.
        head = tokens[0].split(".")[0].lower() if tokens else ""
        if head in _STRONG_STARTERS | _WEAK_STARTERS | _PS_VERBS and tokens[0] not in built:
            tokens[0] = head + tokens[0][len(head):]
        tokens = ["i" if tk == "I" else tk for tk in tokens]
    powershell = (not sql and len(tokens) > 2 and tokens[0].lower() in _PS_VERBS
                  and tokens[1] == "\x07-")
    if powershell:
        tokens[1] = "\x05-"                          # Get-ChildItem: the verb's dash fuses
    tokens = _resolve(tokens, sql, powershell)
    out = _assemble(tokens, sql)
    out = re.sub(r"\s+", " ", out).strip()
    if sql:
        return _sql_finish(out)
    out = _powershell(out)
    # Python imports: "import Json" / "from Datetime import ..." -- module
    # names are lowercase (Whisper capitalizes). JS "import React from
    # 'react'" has a quote and is left alone.
    if re.match(r"^(import|from) ", out) and '"' not in out and "'" not in out:
        out = re.sub(r"\b[A-Z][a-z]+\b", lambda m: m.group(0) if m.group(0) in built else m.group(0).lower(), out)
    if re.match(r"^git\b", out):
        out = re.sub(r"\bhead\b", "HEAD", out, flags=re.IGNORECASE)
    out = re.sub(r"^chmod \+ (\w)", r"chmod +\1", out)
    return out


_UNIT_WORDS = {
    "seconds", "second", "milliseconds", "ms", "minutes", "minute", "hours",
    "days", "bytes", "kilobytes", "megabytes", "gigabytes", "terabytes", "kb",
    "mb", "gb", "tb", "percent", "status", "rows", "requests", "users",
    "threads", "cores", "pixels", "px", "items", "records", "errors",
    "retries", "times", "lines", "files", "commits", "tests",
}
_NUM_WORD = r"(?:" + "|".join(sorted(_NUMBER_WORDS - {"oh"}, key=len, reverse=True)) + r")"
_NUM_RUN = rf"{_NUM_WORD}(?:\s+{_NUM_WORD})*"


def _prose_numbers(text):
    """Spoken numbers in tech prose, only where they're unmistakably a
    value: after version/port/v, before a unit ("thirty seconds", "a two
    hundred status"), and in dotted IPs/versions ("ten dot zero dot zero
    dot five", "one point two point three"). "one of the tests" stays."""
    conv = lambda m: _parse_number(m.group(0).lower().split())
    # dotted: IP addresses / versions
    def dotted(m):
        parts = re.split(r"\s+(?:dot|point)\s+", m.group(0), flags=re.IGNORECASE)
        return ".".join(re.sub(_NUM_RUN, conv, p, flags=re.IGNORECASE) for p in parts)
    text = re.sub(rf"(?i)\b(?:{_NUM_RUN}|\d+)(?:\s+(?:dot|point)\s+(?:{_NUM_RUN}|\d+))+\b", dotted, text)
    text = re.sub(rf"(?i)\b(\w+) colon ({_NUM_RUN})\b",
                  lambda m: m.group(1) + ":" + conv(re.match(r".*", m.group(2))), text)
    text = re.sub(rf"(?i)\b(version|port|v|line|row|column|issue)\s+({_NUM_RUN})\b",
                  lambda m: m.group(1) + " " + conv(re.match(r".*", m.group(2))), text)
    units = "|".join(sorted(_UNIT_WORDS, key=len, reverse=True))
    text = re.sub(rf"(?i)\b({_NUM_RUN})(?=\s+(?:{units})\b)",
                  lambda m: conv(m) if m.group(0).lower() not in ("one", "a") else m.group(0), text)
    return text


# Prose: only fusions that are unambiguous even in ordinary sentences.
def prose_symbols(text):
    text = _prefix_fixes(text, code=False)
    text = _prose_numbers(text)
    # "localhost colon 3000" -> localhost:3000 (colon + number = a port)
    text = re.sub(r"(?i)\b(\w+) colon (\d+)\b", r"\1:\2", text)
    text = re.sub(r"(?i)\b(localhost|127\.0\.0\.1)\s*:\s*(three|3) thousand\b", r"\1:3000", text)
    # "slash api slash v two slash users" -> /api/v2/users
    text = re.sub(r"(?i)\bv (two|2)\b", "v2", text)
    text = re.sub(r"(?i)(?<=\w)\s+slash\s+(?=\w)", "/", text)   # api slash v2
    text = re.sub(r"(?i)(?:^|(?<=\s))slash\s+(?=\w)", "/", text)  # leading: /api
    # "the dot env file" -> "the .env file" (a dotfile, not "the.env")
    text = re.sub(r"(?i)\b(the|a|your|my|in|from|to) dot (" + "|".join(_DOTFILES) + r")\b",
                  r"\1 .\2", text)
    # "sumit at example.com" / "sumit at example dot com" -> sumit@example.com
    text = re.sub(r"(?i)\b(\w+) at (?=[A-Za-z][\w-]*(\.| dot )(com|org|net|io|dev|in|co)\b)",
                  r"\1@", text)
    return text


def strip_backticks(text):
    """`/api/v2/users` -> /api/v2/users (the grammar model's markdown habit)."""
    return re.sub(r"`([^`\n]+)`", r"\1", text)


def process(raw):
    """Developer-English entry point. Returns (text, is_code): code lines
    are final; prose still goes through the normal cleanup in app.py."""
    if is_code_line(raw):
        return code_line(raw), True
    return prose_symbols(raw), False
