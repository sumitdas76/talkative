"""Open the real Settings window from source, visit every tab, and check
the window's actual size fits what each tab needs (the Save/Close bar
getting squeezed was a real shipped bug). Also screenshots the Hotkeys tab
and the "How to say code" help window."""
import ctypes, os, sys, time
ctypes.windll.shcore.SetProcessDpiAwareness(1)
sys.path.insert(0, r"C:\Users\sumit\Projects\Talkative")
from PIL import ImageGrab
from talkative import settings, config, overlay_thread
settings.load_into_config()
from talkative import settings_window as sw

out = os.path.dirname(os.path.abspath(__file__))
ov = overlay_thread.get()
ov._ready.wait(5)
sw.open_settings()
time.sleep(2.5)

res = {}


def run(fn):
    done = []
    def wrap():
        try:
            fn()
        finally:
            done.append(1)
    ov.build(wrap)
    for _ in range(50):
        if done:
            return
        time.sleep(0.1)


def find_win():
    for w in ov.root.winfo_children():
        if "Settings" in w.title():
            res["win"] = w
run(find_win)
win = res["win"]


def walk(w, cls):
    for c in w.winfo_children():
        if c.winfo_class() == cls:
            yield c
        yield from walk(c, cls)


def tabs():
    nb = next(walk(win, "TNotebook"))
    res["nb"] = nb
    res["tabs"] = [nb.tab(t, "text") for t in nb.tabs()]
run(tabs)
print("tabs:", res["tabs"])

for i, name in enumerate(res["tabs"]):
    def check(i=i, name=name):
        nb = res["nb"]
        nb.select(i)
        win.update_idletasks()
        win.update()
        bars = [b for b in walk(win, "TButton") if b["text"] == "Close"]
        bar_h = bars[0].winfo_height() if bars else -1
        res[name] = (win.winfo_reqwidth(), win.winfo_reqheight(),
                     win.winfo_width(), win.winfo_height(), bar_h)
    run(check)
    time.sleep(0.4)
    rw, rh, aw, ah, bh = res[name]
    ok = aw >= rw and ah >= rh and bh > 15
    print(f"  {name:10} needs {rw}x{rh}  has {aw}x{ah}  Close button h={bh}  {'OK' if ok else 'PROBLEM'}")


def shoot(name):
    def geo():
        win.lift(); win.attributes("-topmost", True); win.update()
        res["box"] = (win.winfo_rootx(), win.winfo_rooty(),
                      win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height())
    run(geo)
    time.sleep(0.6)
    ImageGrab.grab(res["box"]).save(os.path.join(out, name))

run(lambda: res["nb"].select(res["tabs"].index("Hotkeys")))
time.sleep(0.6)
shoot("settings_hotkeys.png")


def open_help():
    link = next(b for b in walk(win, "TLabel") if "How to say code" in str(b["text"]))
    link.event_generate("<Button-1>")
run(open_help)
time.sleep(1.0)


def help_geo():
    hw = next(w for w in win.winfo_children() if w.winfo_class() == "Toplevel")
    hw.lift(); hw.attributes("-topmost", True); hw.update()
    res["hbox"] = (hw.winfo_rootx(), hw.winfo_rooty(),
                   hw.winfo_rootx() + hw.winfo_width(), hw.winfo_rooty() + hw.winfo_height())
    res["hreq"] = (hw.winfo_reqwidth(), hw.winfo_reqheight(), hw.winfo_width(), hw.winfo_height())
run(help_geo)
time.sleep(0.6)
ImageGrab.grab(res["hbox"]).save(os.path.join(out, "settings_devhelp.png"))
print("help window needs/has:", res["hreq"])
sys.stdout.flush(); os._exit(0)

