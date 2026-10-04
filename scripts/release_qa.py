"""Automated release checks -- the "auto" rows of docs/RELEASE_QA.md.

usage (from the project root, with the project venv):
  .venv\\Scripts\\python scripts\\release_qa.py --exe <Talkative.exe> [--grammar] [--no-gui]

  --exe      the EXE to test; use the CI-built one for a release
             (default: dist\\Talkative.exe)
  --grammar  also run the grammar-guard evaluation (D5, ~3 min, needs the
             local grammar model)
  --no-gui   skip checks that open windows (F1, W1, W2, D12, F6)

Prints a PASS/FAIL/SKIP table and exits 1 if anything failed. Offline:
no Groq or Worker requests (prose is scored on classification only).
Needs a desktop session for the window checks.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
STUDY = ROOT / "tools" / "dev_mode_study"
E2E = ROOT / "tools" / "e2e"
BASELINE = Path(__file__).with_name("release_qa_baseline.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

results = []


def record(check_id, name, status, detail=""):
    results.append((check_id, name, status, detail))
    print(f"  {status:4}  {check_id:3} {name}" + (f" -- {detail}" if detail else ""), flush=True)


def run_py(args, cwd, timeout=600):
    p = subprocess.run([PY, *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, p.stdout + p.stderr


# --------------------------------------------------------------------- B
def check_version():
    app = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "talkative" / "__init__.py").read_text(encoding="utf-8")).group(1)
    iss = re.search(r'#define MyAppVersion "([^"]+)"', (ROOT / "installer" / "Talkative.iss").read_text(encoding="utf-8-sig")).group(1)
    record("B1", "Version matches in app and installer", "PASS" if app == iss else "FAIL", f"app {app}, installer {iss}")


def check_tcl(exe):
    if not exe.exists():
        record("B2", "EXE bundles Tcl/Tk data", "SKIP", f"{exe} not found")
        return
    code, out = run_py(["-m", "PyInstaller.utils.cliutils.archive_viewer", "-l", str(exe)], ROOT)
    n = len(re.findall(r"_tcl_data|_tk_data", out))
    record("B2", "EXE bundles Tcl/Tk data", "PASS" if n >= 100 else "FAIL", f"{n} files")


def check_single_tk_root():
    """Real calls only (parsed, not grepped): docstrings mention tk.Tk()
    while explaining why there must be just one."""
    import ast

    hits = []
    for p in (ROOT / "talkative").glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            f = getattr(node, "func", None) if isinstance(node, ast.Call) else None
            if (isinstance(f, ast.Attribute) and f.attr == "Tk" and isinstance(f.value, ast.Name)
                    and f.value.id in ("tk", "tkinter")):
                hits.append(f"{p.name}:{node.lineno}")
    record("B4", "Only one tk.Tk() root", "PASS" if len(hits) == 1 else "FAIL", ", ".join(hits))


# --------------------------------------------------------------------- F1 / B3
def _run_values():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        out, i = {}, 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(k, i)
            except OSError:
                return out
            out[name] = value
            i += 1


def _windows_of(exe_path):
    import win32gui
    import win32process

    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         f"Get-Process Talkative -ErrorAction SilentlyContinue | "
                         f"Where-Object {{ $_.Path -eq '{exe_path}' }} | ForEach-Object {{ $_.Id }}"],
                        capture_output=True, text=True).stdout.split()
    pids = {int(p) for p in ps}
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32process.GetWindowThreadProcessId(h)[1] in pids:
            l, t, r, b = win32gui.GetWindowRect(h)
            if r - l > 50 and b - t > 50:
                found.append(win32gui.GetWindowText(h))
    win32gui.EnumWindows(cb, None)
    return pids, found


def check_fresh_launch(exe):
    if not exe.exists():
        record("F1", "Fresh launch: one window, no crash", "SKIP", f"{exe} not found")
        return
    box = Path(tempfile.mkdtemp(prefix="talkative_qa_"))
    copy = box / "Talkative.exe"      # own path, so it can't be mistaken for the real app
    copy.write_bytes(exe.read_bytes())
    before = _run_values()
    subprocess.Popen([str(copy)], cwd=box, env=dict(os.environ, LOCALAPPDATA=str(box)))
    wins = []
    try:
        for _ in range(90):
            time.sleep(1)
            _, wins = _windows_of(str(copy))
            if wins:
                break
        time.sleep(4)                  # let any second window appear too
        _, wins = _windows_of(str(copy))
    finally:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-Process Talkative -ErrorAction SilentlyContinue | "
                        f"Where-Object {{ $_.Path -eq '{copy}' }} | Stop-Process -Force"], capture_output=True)
    after = _run_values()
    crashed = [w for w in wins if "exception" in w.lower()]
    record("B3", "EXE starts without a crash dialog", "FAIL" if crashed or not wins else "PASS",
           crashed[0] if crashed else ("no window within 90 s" if not wins else ""))
    ok = wins == ["Talkative"] and before == after
    detail = f"windows {wins}" + ("" if before == after else "; Windows startup list CHANGED")
    record("F1", "Fresh launch: exactly one window, startup list untouched", "PASS" if ok else "FAIL", detail)


# --------------------------------------------------------------------- D1 / F4
def check_hotkeys():
    code, out = run_py(["hotkey_test.py"], STUDY, timeout=120)
    ok = len(re.findall(r"^OK ", out, re.M))
    bad = re.findall(r"^BAD (.*)$", out, re.M)
    gate = "before the first-run choice" in out and not any("first-run" in b for b in bad)
    record("D1", "Hotkeys, chord upgrade, key repeat", "PASS" if code == 0 and ok and not bad else "FAIL",
           f"{ok} OK" + (f", BAD: {bad}" if bad else ""))
    record("F4", "Nothing recorded before the first-run choice", "PASS" if gate else "FAIL")


def check_tap_mode():
    code, out = run_py(["toggle_test.py"], E2E, timeout=120)
    passed = len(re.findall(r"^PASS ", out, re.M))
    bad = re.findall(r"^FAIL (.*)$", out, re.M)
    record("D8", "Tap mode: tap on/off, hold, shortcut dropped, auto-stop",
           "PASS" if code == 0 and passed and not bad else "FAIL",
           f"{passed} passed" + (f", FAIL: {bad}" if bad else ""))


def check_tray():
    code, out = run_py(["tray_test.py"], E2E, timeout=120)
    passed = len(re.findall(r"^PASS ", out, re.M))
    bad = re.findall(r"^FAIL (.*)$", out, re.M)
    record("W2", "Tray icon: lost icon comes back, concurrent updates safe, errors.log works",
           "PASS" if code == 0 and passed and not bad else "FAIL",
           f"{passed} passed" + (f", FAIL: {bad}" if bad else ""))


def check_defaults():
    sys.path.insert(0, str(ROOT))
    from talkative import config
    texts = {
        "LICENSE": (ROOT / "LICENSE").read_text(encoding="utf-8"),
        "version_info.py": (ROOT / "scripts" / "version_info.py").read_text(encoding="utf-8"),
        "Talkative.iss": (ROOT / "installer" / "Talkative.iss").read_text(encoding="utf-8"),
    }
    old_name = [n for n, t in texts.items() if "Chatterjee" in t]
    ok = config.DICTIONARY == {} and not old_name
    record("B7", "New installs: empty dictionary, publisher/copyright Sumit Das",
           "PASS" if ok else "FAIL",
           ("" if config.DICTIONARY == {} else f"default dictionary has {len(config.DICTIONARY)} entries; ")
           + (f"old name in {old_name}" if old_name else ""))


def check_mode_switch():
    """Local -> Cloud while the local model is still loading, and deleting
    the local voice model while in Cloud. Needs the local models on this PC."""
    problems = []
    for scenario in ("during", "delete", "update"):
        code, out = run_py(["mode_switch_test.py", scenario], E2E, timeout=180)
        last = [l for l in out.splitlines() if l.startswith(("25 s later:", "after deleting", "after a model update"))]
        if code != 0 or not last or "transcriber=CLOUD" not in last[-1] or "(Cloud" not in last[-1]:
            problems.append(f"{scenario}: {last[-1].split('transcriber=')[-1][:40] if last else 'no output'}")
        if scenario == "delete" and "dictation blocked: False" not in out:
            problems.append("delete: dictation blocked")
    record("D10", "Local -> Cloud sticks (mid-load too); deleting or updating local models leaves Cloud alone",
           "PASS" if not problems else "FAIL", "; ".join(problems))


def _script_check(check_id, name, script, timeout=180):
    code, out = run_py([script], E2E, timeout=timeout)
    passed = len(re.findall(r"^PASS ", out, re.M))
    bad = re.findall(r"^(?:FAIL |ABORT)(.*)$", out, re.M)
    record(check_id, name, "PASS" if code == 0 and passed and not bad else "FAIL",
           f"{passed} passed" + (f", FAIL: {bad}" if bad else ""))


def check_hotkey_rules():
    sys.path.insert(0, str(ROOT))
    from talkative.settings_window import _hotkey_problem as p
    must_pass = [(["ctrl_r"], ["ctrl_r", "shift_r"]), (["ctrl_l", "alt_l"], ["ctrl_r"]), (["f9"], [])]
    must_block = [(["a"], []), (["space"], []), (["shift", "a"], []), (["shift_r"], []),
                  (["ctrl_r"], ["ctrl_r"]), (["alt_l", "ctrl_l"], ["ctrl_l", "alt_l"])]
    wrong = [c for c in must_pass if p(*c)] + [c for c in must_block if not p(*c)]
    record("W3", "Settings refuses typing-key hotkeys and identical normal/code keys",
           "PASS" if not wrong else "FAIL", f"wrong: {wrong}" if wrong else "")


def check_pipeline():
    code, out = run_py(["pipeline_test.py"], STUDY, timeout=300)
    want = [
        ("SELECT * FROM users WHERE id = 5", "(STT prompt: dev)"),
        ('git commit -m "fix login bug"', "(STT prompt: dev)"),
    ]
    lines = out.splitlines()
    missing = [w for w, p in want if not any(w in l and p in l for l in lines)]
    normal_prompt = sum("(STT prompt: normal)" in l for l in lines)
    ok = code == 0 and not missing and normal_prompt == 2
    record("D2", "Dictation pipeline: code as code, right speech prompt", "PASS" if ok else "FAIL",
           (f"missing {missing}; " if missing else "") + f"normal-prompt lines {normal_prompt}/2"
           + ("" if code == 0 else f"; exit {code}"))


def check_layout():
    code, out = run_py(["settings_layout.py"], STUDY, timeout=180)
    tabs = re.findall(r"^\s+(\S[^\n]*?)\s+needs .*?(OK|PROBLEM)$", out, re.M)
    probs = [t for t, s in tabs if s == "PROBLEM"]
    m = re.search(r"help window needs/has: \((\d+), (\d+), (\d+), (\d+)\)", out)
    help_ok = bool(m) and int(m.group(3)) >= int(m.group(1)) and int(m.group(4)) >= int(m.group(2))
    ok = code == 0 and tabs and not probs and help_ok
    record("W1", "Settings tabs and help window fit", "PASS" if ok else "FAIL",
           f"{len(tabs)} tabs" + (f", PROBLEM: {probs}" if probs else "") + ("" if help_ok else ", help window doesn't fit"))


def check_audio_race():
    """Rapid mic start/stop while another thread lists devices: the
    pattern that crashed on PortAudio (2026-10-03/04). Real microphone."""
    code, out = run_py(["audio_race_test.py", "30"], E2E, timeout=200)
    ok = code == 0 and "exit code 0 " in out
    record("D14", "Microphone start/stop under load doesn't crash", "PASS" if ok else "FAIL",
           out.strip().splitlines()[-1][:120] if out.strip() else f"exit {code}")


def check_guard_eval():
    """Invented endings / lost negations (2026-10-04): the cached model
    outputs in guard_eval.json must still be caught, with no new false
    alarms on the hand-written and everyday sets."""
    code, out = run_py(["guard_eval.py"], ROOT / "tools" / "grammar_eval", timeout=1800)
    rows = {m[0]: tuple(int(x) for x in m[1:]) for m in
            re.findall(r"^(\S+/\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$", out, re.M)}
    cut, hard, prose = rows.get("local/cut"), rows.get("local/hard"), rows.get("local/prose")
    ok = (code == 0 and cut and hard and prose and cut[4] >= 9
          and hard[3] + hard[4] == 0 and prose[3] + prose[4] == 0)
    record("D15", "Grammar: invented endings caught, no new false alarms", "PASS" if ok else "FAIL",
           f"cut endings caught {cut[4] if cut else '?'} (min 9), hard {hard[3:] if hard else '?'}, "
           f"prose {prose[3:] if prose else '?'}")


# --------------------------------------------------------------------- D3
def check_corpora():
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(STUDY))
    from talkative import dev_mode
    import corpus2, corpus3, corpus4

    # prose_guard.py runs its check on import; take only its sentence list.
    src = (STUDY / "prose_guard.py").read_text(encoding="utf-8").split("\nbad = ")[0]
    ns = {"__file__": str(STUDY / "prose_guard.py")}  # it locates the project from its own path
    exec(compile(src, "prose_guard.py", "exec"), ns)
    sentences = ns["SENTENCES"]

    def norm(s):
        s = s.replace("‑", "-").replace("’", "'").replace("“", '"').replace("”", '"')
        return re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", s.strip()))

    def score(cases):
        ok = 0
        for cat, spoken, want in cases:
            got, is_code = dev_mode.process(spoken)
            if cat == "prose":
                ok += not is_code
            elif is_code:
                g, w = norm(got), norm(want)
                ok += (g.lower() == w.lower()) if cat in ("sql", "shell") else g == w
        return ok

    base = json.loads(BASELINE.read_text(encoding="utf-8"))["code_dictation"]
    now = {
        "corpus2_all": score(corpus2.CASES),
        "corpus3_final": score(corpus3.FINAL),
        "corpus4_tune": score(corpus4.TUNE),
        "corpus4_final": score(corpus4.FINAL),
        "prose_guard": sum(not dev_mode.process(s)[1] for s in sentences),
    }
    totals = {"corpus2_all": len(corpus2.CASES), "corpus3_final": len(corpus3.FINAL),
              "corpus4_tune": len(corpus4.TUNE), "corpus4_final": len(corpus4.FINAL),
              "prose_guard": len(sentences)}
    worse = {k: (now[k], base[k]) for k in now if now[k] < base.get(k, 0)}
    better = [k for k in now if now[k] > base.get(k, 0)]
    detail = ", ".join(f"{k} {now[k]}/{totals[k]}" for k in now)
    if worse:
        detail += " | BELOW BASELINE: " + ", ".join(f"{k} {a} < {b}" for k, (a, b) in worse.items())
    elif better:
        detail += " | improved: raise the baseline for " + ", ".join(better)
    record("D3", "Code-dictation scores vs baseline", "FAIL" if worse else "PASS", detail)


# --------------------------------------------------------------------- D5
def check_grammar():
    grammar_dir = ROOT / "tools" / "grammar_eval"
    code, out = run_py(["evaluate.py", "qwen25-1.5b"], grammar_dir, timeout=1800)
    m = re.search(r"(\d+) cases \| guard rejections (\d+) \| meaning flags (\d+)", out)
    if not m:
        record("D5", "Grammar guards vs baseline", "FAIL", "evaluation didn't finish: " + out[-300:])
        return
    n, rej, flags = (int(x) for x in m.groups())
    base = json.loads(BASELINE.read_text(encoding="utf-8"))["grammar"]
    # The baseline is for the committed hand-written cases only; a machine
    # with the private log_cases.json runs more and isn't comparable.
    if n != base["cases"]:
        record("D5", "Grammar guards vs baseline", "SKIP",
               f"ran {n} cases, baseline is for {base['cases']} (private log_cases.json present?)")
        return
    ok = rej <= base["max_rejections"] and flags <= base["max_meaning_flags"]
    record("D5", "Grammar guards vs baseline", "PASS" if ok else "FAIL",
           f"{n} cases: rejections {rej} (max {base['max_rejections']}), "
           f"meaning flags {flags} (max {base['max_meaning_flags']})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(ROOT / "dist" / "Talkative.exe"))
    ap.add_argument("--grammar", action="store_true")
    ap.add_argument("--no-gui", action="store_true")
    a = ap.parse_args()
    exe = Path(a.exe).resolve()
    print(f"Release QA -- {exe}\n", flush=True)
    check_version()
    check_tcl(exe)
    check_single_tk_root()
    check_defaults()
    if a.no_gui:
        record("F1", "Fresh launch: one window, no crash", "SKIP", "--no-gui")
        record("W1", "Settings tabs and help window fit", "SKIP", "--no-gui")
        record("W2", "Tray icon checks", "SKIP", "--no-gui")
        record("D12", "Overlapping pastes keep the clipboard", "SKIP", "--no-gui")
        record("F6", "First-run switch to Cloud mid-download", "SKIP", "--no-gui")
    else:
        check_fresh_launch(exe)
    check_hotkeys()
    check_tap_mode()
    check_mode_switch()
    _script_check("D11", "Overlapping dictations are typed in spoken order", "order_test.py")
    _script_check("D13", "Cloud busy/offline: Local fallback or retry, never lost", "cloud_busy_test.py", 300)
    _script_check("P4", "Leftover temp copies removed, a copy in use never touched", "temp_cleanup_test.py", 60)
    check_audio_race()
    check_hotkey_rules()
    check_pipeline()
    if not a.no_gui:
        check_layout()
        check_tray()
        _script_check("D12", "Overlapping pastes keep the user's clipboard", "clipboard_race_test.py", 90)
        _script_check("F6", "First-run setup: switching to Cloud mid Local download works", "onboarding_cloud_test.py", 150)
    check_corpora()
    if a.grammar:
        check_grammar()
        check_guard_eval()
    else:
        record("D5", "Grammar guards vs baseline", "SKIP", "add --grammar")
        record("D15", "Grammar: invented endings caught", "SKIP", "add --grammar")
    failed = [r for r in results if r[2] == "FAIL"]
    print(f"\n{len(results)} checks: {sum(r[2] == 'PASS' for r in results)} passed, "
          f"{len(failed)} failed, {sum(r[2] == 'SKIP' for r in results)} skipped."
          "\nManual items: see docs/RELEASE_QA.md.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
