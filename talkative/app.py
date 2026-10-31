import datetime
import logging
import threading
import time
from types import SimpleNamespace

import numpy as np
from pynput import keyboard

from . import audio_devices, cloud_client, cloud_notice, config, continuation, dev_mode, diagnostics, error_toast, feedback, fix_learning, grammar_engine, history, mic_warmup, model_manager, onboarding, paste_target, pill, screen_context, settings, temp_cleanup, try_it_now, updater
from .audio_recorder import AudioRecorder
from .autostart import sync_autostart
from .cleanup import collapse_repeats, finish_sentence, remove_fillers
from .bullets import BULLET, format_bullets
from .numbers import format_numbers, restore_spoken_point
from .dictionary import apply_dictionary, vocabulary_prompt
from . import focus_check
from .focus_check import is_focus_editable
from .keynames import friendly as friendly_key
from .self_correction import apply_self_corrections
from .spoken_symbols import apply_spoken_symbols
from .text_inserter import copy_only, insert_text
from .transcriber import Transcriber
from .tray import TrayApp, show_error_popup


# Placeholder assigned to self.transcriber in cloud mode so the existing
# "self.transcriber is None" readiness gate in _on_press still works, even
# though nothing ever calls .transcribe() on it -- _process_audio_inner
# branches on _cloud_active() before it would.
_CLOUD_TRANSCRIBER = object()

# A hotkey chord containing a Windows or Alt key: Windows treats that key
# as "pressed alone" if nothing else was typed between its down and up,
# and on release opens the Start menu (Win) or puts the focused window in
# menu mode (Alt -- which then swallows the Ctrl+V paste). Tapping an
# unassigned virtual key while the chord is down marks it as used, the
# same trick AutoHotkey uses (its default mask key is also vk E8). Wispr
# Flow doesn't open Start on the same chords; Talkative did (user report
# 2026-10-03).
_MASK_KEY = keyboard.KeyCode.from_vk(0xE8)
_MASKED_KEYS = {
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr,
}
_mask_controller = keyboard.Controller()


def _physically_down(key):
    """Whether Windows says `key` is held right now. Key releases that
    happen on the lock screen, the Ctrl+Alt+Del screen or while the PC
    sleeps never reach the keyboard hook, so the app can believe a key is
    still held long after it was let go. Unknown keys count as down (the
    old behavior)."""
    import ctypes

    vk = getattr(getattr(key, "value", key), "vk", None)
    if vk is None:
        return True
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return True


def _debug_log(**stages):
    if not config.DEBUG_LOG:
        return
    try:
        folder = settings.settings_dir()
        folder.mkdir(exist_ok=True)
        with open(folder / "debug.log", "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat(timespec="seconds") + "\n")
            for name, value in stages.items():
                f.write(f"  {name}: {value!r}\n")
    except Exception:
        pass


def _ready_note(recorder, cold):
    """debug.log: when a cold microphone first sent sound (the mic-ready
    cue lit up then)."""
    if not cold:
        return ""
    ready = getattr(recorder, "ready_after", None)
    return ", mic sound after " + ("?" if ready is None else f"{ready * 1000:.0f} ms")


def _audio_summary(audio, sample_rate, reason):
    """One debug.log line about the recording itself: length, speech level
    (90th-percentile 30 ms RMS) and what stopped it. Added 2026-10-20 for
    dictations typed only partly -- the text alone couldn't tell a short
    recording from audio lost later."""
    try:
        frame = int(sample_rate * 0.03)
        n = audio.size // frame
        level = 0.0
        if n:
            rms = np.sqrt(np.mean(audio[:n * frame].reshape(n, frame) ** 2, axis=1))
            level = float(np.percentile(rms, 90))
        return f"{audio.size / sample_rate:.1f}s, level {level:.3f}, stopped by {reason}"
    except Exception:
        return f"stopped by {reason}"


def _debug_save_audio(audio):
    """With the debug log on, keep this dictation's audio (newest
    DEBUG_AUDIO_KEEP only) and return the file name for debug.log."""
    if not config.DEBUG_LOG or not config.DEBUG_AUDIO_KEEP or not getattr(audio, "size", 0):
        return ""
    try:
        folder = settings.settings_dir() / "debug_audio"
        folder.mkdir(parents=True, exist_ok=True)
        name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".wav"
        (folder / name).write_bytes(cloud_client._wav_bytes(audio, config.SAMPLE_RATE))
        for old in sorted(folder.glob("*.wav"))[:-config.DEBUG_AUDIO_KEEP]:
            old.unlink(missing_ok=True)
        return name
    except Exception:
        logging.getLogger(__name__).exception("could not save debug audio")
        return ""


class TalkativeApp:
    def __init__(self):
        # Must run before anything else touches the data folder -- the
        # very next line reads settings.json out of it.
        settings.migrate_data_folder()
        settings.load_into_config()
        settings.remove_old_examples()
        self.recorder = AudioRecorder(
            sample_rate=config.SAMPLE_RATE, device=config.INPUT_DEVICE
        )
        self.transcriber = None
        self._recording = False
        self._record_start_time = None
        self._live_warned = False  # a live problem was shown this dictation
        self._running = True
        self._mic_event = threading.Event()  # devices changed / blank recording
        self._mic_blank = False
        self._listener = None
        self._no_model = False  # active model was deleted; not merely still loading
        self._jobs = 0  # dictations currently in the pipeline (updater idle check)
        # Dictations are typed in the order they were spoken: each gets a
        # number when recording stops and waits for its turn to paste. Two
        # quick dictations are processed side by side, so a short second
        # one could otherwise be typed before a long first one.
        self._order = threading.Condition()
        self._next_seq = 0       # number for the next dictation
        self._turn = 0           # the dictation whose turn it is to paste
        self._finished = set()   # finished early, waiting for earlier ones
        self._job_seq = threading.local()
        self._job_blank = threading.local()  # this dictation's mic sent silence
        self._job_target = threading.local()  # where this dictation pastes
        self._job_report = threading.local()  # diagnostics, sent once the outcome is known
        self._target = None  # paste_target.Target captured at the hotkey press
        self._swapping = False  # model swap in progress (update install/undo)
        self._hotkey_pressed = set()  # currently-held keys that are part of HOTKEY or DEV_HOTKEY
        self._chord_active = False  # chord already handled for this press-hold, ignore OS key-repeat
        self._dev_dictation = False  # current recording is developer English (DEV_HOTKEY)
        self._latched = False  # toggle mode: recording stays on after a tap, until the next one
        self._lost_release_checks = 0  # see _check_lost_release
        self._recording_id = 0  # bumped per recording, so a stale auto-stop timer can't stop a later one
        self._stop_lock = threading.Lock()
        self._mode_lock = threading.Lock()  # transcriber swaps vs. a finishing background load
        self._fallback = None  # Local model borrowed while Cloud is busy (_cloud_transcribe)
        self._fallback_timer = None
        self._fallback_lock = threading.Lock()
        self._cloud_down = threading.local()  # .value: this dictation's Cloud transcription failed
        self._masked = False  # mask key already sent for the chord currently held
        self._chord_engaged = False  # full chord was down since all its keys were last up
        self._context = None  # screen_context.Pending for the current recording, or None
        self._press = None  # continuation.press_info() of the current recording
        self._azure_notice = 0.0  # when the last "Indian English is busy" message was shown
        self.tray = TrayApp(
            on_quit=self.quit, on_settings=self.open_settings,
            hotkey_label=friendly_key(config.HOTKEY),
            on_input_device=self._set_input_device,
        )
        self._refresh_hotkey_label()

    def _refresh_hotkey_label(self):
        self.tray.set_hotkey_label(
            friendly_key(config.HOTKEY),
            friendly_key(config.DEV_HOTKEY) if config.DEV_HOTKEY else "",
            verb="tap" if self._toggle_mode() else "hold",
        )

    def _ready_hint(self):
        key = friendly_key(config.HOTKEY)
        if self._toggle_mode():
            return f"Tap {key} to start dictating, tap again to stop."
        return f"Hold {key} to dictate."

    def open_settings(self):
        from types import SimpleNamespace

        from .settings_window import open_settings

        controller = SimpleNamespace(
            reload=self.reload_model,
            unload=self.unload_model,
            has_model=lambda: self.transcriber is not None,
            undo_update=lambda: updater.undo_last_update(self.updater_controller()),
        )
        open_settings(on_applied=self._apply_settings, model_controller=controller)

    def _onboarding_done(self, mode):
        """First-run Cloud/Local choice made: set up that mode, and check
        how fast the microphone starts now (not allowed before the choice),
        so the try-it-now box can show it."""
        self._sync_processing_mode()
        threading.Thread(target=self._probe_mic, daemon=True).start()
        # Local opens the box once its model has loaded; Cloud has nothing
        # to wait for. Before 2026-10-31 Cloud never opened it, so most new
        # users missed the mic check (found in the 1.3.21 fresh-install
        # test). Only here, not in _enter_cloud_mode: existing Cloud users
        # never had the box and shouldn't get it popping up after an update.
        if self._cloud_active():
            try_it_now.maybe_show()

    def _set_input_device(self, index):
        """Tray menu -> Microphone. Same effect as Settings -> Audio: saved,
        and used from the next dictation."""
        config.INPUT_DEVICE = index
        self._use_mic(index)
        settings.save({"input_device": index})

    def _use_mic(self, index):
        """Switch the recorder to another mic and check how fast that one
        starts (a stream still open for the old one is closed first)."""
        if self.recorder.device == index:
            return
        self.recorder.device = index
        if self.recorder.lingering():
            self.recorder.close()
        threading.Thread(target=self._probe_mic, daemon=True).start()

    def _apply_settings(self):
        sync_autostart()
        self._use_mic(config.INPUT_DEVICE)
        self._hotkey_pressed.clear()
        self._chord_active = False
        self._refresh_hotkey_label()
        self._sync_processing_mode()
        if self.transcriber is not None and not self._recording:
            self.tray.set_idle()  # refresh the tooltip with the new hotkey
        self.tray.notify("Settings saved.")

    def _cloud_active(self):
        return config.PROCESSING_MODE == "cloud" and bool(config.CLOUD_ENDPOINT_URL)

    def _grammar_uses_local(self):
        """True when the grammar cleanup stage runs on the local engine:
        Local mode. (Cloud with on-device grammar was an option until
        2026-10-23; removed at the user's request.)"""
        return not self._cloud_active()

    def _enter_cloud_mode(self):
        self.transcriber = _CLOUD_TRANSCRIBER
        self._no_model = False
        self.tray.set_mode_label("Cloud")
        self.tray.set_idle()
        self.tray.notify(f"Ready (cloud). {self._ready_hint()}")
        cloud_notice.maybe_show()

    def _sync_processing_mode(self):
        """Switch local <-> cloud model state after Settings is saved. A
        no-op when the mode didn't actually change -- called on every save,
        not just ones that touch Processing."""
        import gc

        if self._cloud_active():
            with self._mode_lock:
                switched = self.transcriber is not _CLOUD_TRANSCRIBER
                if switched:
                    self.transcriber = _CLOUD_TRANSCRIBER
            if switched:
                gc.collect()  # release the local model.bin mapping, if any
                self._enter_cloud_mode()
            grammar_engine.unload()  # Cloud never uses the local grammar engine
        elif self.transcriber is _CLOUD_TRANSCRIBER:
            self.transcriber = None
            self._load_model_async()
            threading.Thread(target=self._load_grammar, daemon=True).start()

    def _load_grammar(self):
        """Load the local grammar engine, then drop it again if the mode
        changed while it loaded and no longer wants it -- it's ~1.5 GB of
        memory, which matters on 8 GB laptops."""
        def wanted():
            return not self._cloud_active()

        if not wanted():
            return
        grammar_engine.load()
        if not wanted():
            grammar_engine.unload()

    def _no_target_cue(self):
        """Nothing editable is focused. An on-screen error instead of a
        blocking popup -- the user's hands are mid-dictation, not reaching
        for a mouse to dismiss a dialog. It's a floating, always-on-top box
        (error_toast) rather than a Windows tray balloon, which can be
        silently suppressed or routed straight to Action Center."""
        error_toast.show("Error! Select a text field before typing.")

    def _load_model_async(self):
        def _load():
            try:
                model_manager.migrate_from_hf_cache()
                model = Transcriber(
                    config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE,
                    download_root=str(model_manager.models_dir()),
                )
                # Loading takes seconds (longer on slow PCs). If the user
                # switched to Cloud meanwhile, drop the model instead of
                # installing it over Cloud -- that left the tray saying
                # Local and the model in memory, so switching back to
                # Cloud looked like it never worked (user report
                # 2026-10-04, reproduced by tools/e2e/mode_switch_test.py).
                with self._mode_lock:
                    if self._cloud_active():
                        return
                    self.transcriber = model
                self._no_model = False
                self.tray.set_mode_label("Local")
                self.tray.set_idle()
                self.tray.notify(
                    f"Ready. {self._ready_hint()}"
                )
                try_it_now.maybe_show()
            except Exception as exc:
                show_error_popup(f"Failed to load speech model:\n{exc}")

        threading.Thread(target=_load, daemon=True).start()

    def reload_model(self, size, on_done=None):
        """Background model swap driven by the settings window. Dictation is
        blocked during the swap; on failure the previous model is restored.
        The choice is persisted only on success."""

        def _reload():
            if self._cloud_active():
                # Cloud doesn't use the local model: remember the choice
                # for Local mode, but don't install it over Cloud.
                config.MODEL_SIZE = size
                settings.save({"model_size": size})
                if on_done is not None:
                    on_done(True)
                return
            old = self.transcriber
            self.transcriber = None
            self.tray.set_loading("switching model...")
            ok = False
            try:
                self.transcriber = Transcriber(
                    size, config.DEVICE, config.COMPUTE_TYPE,
                    download_root=str(model_manager.models_dir()),
                )
                config.MODEL_SIZE = size
                settings.save({"model_size": size})
                self._no_model = False
                ok = True
            except Exception as exc:
                self.transcriber = old
                show_error_popup(f"Could not switch the speech model:\n{exc}")
            if self.transcriber is not None:
                self.tray.set_idle()
            else:
                self.tray.set_loading("no model")
            if on_done is not None:
                on_done(ok)

        threading.Thread(target=_reload, daemon=True).start()

    def unload_model(self):
        """Drop the loaded model (the settings window calls this before
        deleting the only downloaded model). Dictation stays disabled until
        another model is loaded. gc.collect() releases CTranslate2's mapping
        of model.bin so the file can actually be deleted."""
        import gc

        self._drop_fallback()
        if self._cloud_active():
            # Cloud dictation doesn't need the local model: deleting it
            # used to turn Cloud dictation off too, until a restart.
            gc.collect()
            return
        self.transcriber = None
        self._no_model = True
        gc.collect()
        self.tray.set_loading("no model: open Settings, then General")

    def updater_controller(self):
        """The narrow surface updater.py drives a model swap through.
        Synchronous on purpose: the updater thread owns the sequencing."""
        import gc

        from types import SimpleNamespace

        # In Cloud mode the local models aren't in use: an update to them
        # (for someone who tried Local once) must not block Cloud dictation
        # during the swap, nor load the local model over Cloud afterwards.
        def unload_speech():
            if not self._cloud_active():
                self.transcriber = None
            self._drop_fallback()
            gc.collect()  # release the model.bin mapping so files can move

        def reload_speech():
            if self._cloud_active():
                return
            try:
                model = Transcriber(
                    config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE,
                    download_root=str(model_manager.models_dir()),
                )
            except Exception as exc:
                show_error_popup(f"Failed to load speech model:\n{exc}")
                return
            with self._mode_lock:
                if not self._cloud_active():
                    self.transcriber = model

        def begin_swap():
            self._swapping = True
            self.tray.set_loading("updating...")

        def end_swap(ok):
            self._swapping = False
            if self.transcriber is not None:
                self.tray.set_idle()
            if ok:
                self.tray.notify("Update installed.")

        return SimpleNamespace(
            is_busy=lambda: self._recording or self._jobs > 0,
            unload_speech=unload_speech,
            reload_speech=reload_speech,
            reload_grammar=self._load_grammar,
            begin_swap=begin_swap,
            end_swap=end_swap,
            quit_app=lambda: (self.quit(), self.tray.stop()),
        )

    def _toggle_mode(self):
        return config.HOTKEY_MODE == "toggle"

    def _on_press(self, key):
        if getattr(key, "vk", None) == _MASK_KEY.vk:
            return  # our own mask keystroke, see _MASK_KEY
        if key not in config.HOTKEY and key not in config.DEV_HOTKEY:
            # Esc throws the current dictation away, nothing typed (backlog
            # 2026-10-03, mainly for tap mode, where the stop tap always
            # types). Esc still reaches the focused app too.
            if key == keyboard.Key.esc and self._recording:
                self._stop_recording(process=False)
                return
            # Toggle mode: another key pressed while the hotkey is still
            # down means the hotkey was part of a shortcut (Right Ctrl+C),
            # not a tap -- drop the recording that press started instead
            # of leaving it latched on. Hold mode is unchanged.
            if (self._toggle_mode() and self._recording and not self._latched
                    and self._hotkey_pressed):
                self._stop_recording(process=False)
            return
        self._drop_stale_keys(key)
        self._hotkey_pressed.add(key)
        dev = bool(config.DEV_HOTKEY) and self._hotkey_pressed == set(config.DEV_HOTKEY)
        # Once per physical chord press (key-repeat re-fires on_press), and
        # only for the complete chord -- the Windows key pressed on its
        # own must still open Start.
        complete = dev or self._hotkey_pressed == set(config.HOTKEY)
        if complete:
            self._chord_engaged = True
        # A Win/Alt key still held after the rest of the chord was let go
        # auto-repeats, and each repeat counts as a fresh press -- so the
        # one mask sent when the chord completed no longer covers its
        # release, and Notepad's menu lit up (user report 2026-10-15,
        # Ctrl+Alt released Ctrl-first). Mask every such repeat too.
        lingering = (self._chord_engaged and not complete
                     and key in _MASKED_KEYS)
        if lingering or (not self._masked and complete
                         and self._hotkey_pressed & _MASKED_KEYS):
            self._masked = True
            try:
                _mask_controller.press(_MASK_KEY)
                _mask_controller.release(_MASK_KEY)
            except Exception:
                pass
        if self._recording and self._latched:
            # Toggle mode, recording left on by an earlier tap: a fresh
            # press of either chord stops it. _chord_active stays set until
            # release so OS key-repeat can't start a new recording.
            if self._chord_active:
                return
            if self._hotkey_pressed == set(config.HOTKEY) or dev:
                self._chord_active = True
                self._stop_recording(reason="stop tap")
            return
        if self._recording:
            # The developer chord may contain the normal one (default: Right
            # Ctrl, + Right Shift for developer English). Completing it
            # mid-recording upgrades this dictation instead of being ignored
            # -- same audio, only the processing differs.
            if dev:
                self._dev_dictation = True
            return
        if not dev and self._hotkey_pressed != set(config.HOTKEY):
            return
        # Windows re-fires on_press at the OS key-repeat rate for as long as
        # the chord is held. Without this guard, holding the hotkey over an
        # unfocused window replayed the whole body (including
        # _no_target_cue's SAPI/COM call) dozens of times concurrently,
        # which crashed the app with heap corruption (STATUS_HEAP_CORRUPTION
        # in ntdll, from concurrent win32com dispatch) -- confirmed via
        # Windows crash dump 2026-07-22. Only the first physical press of
        # the chord should be handled; released keys re-arm it.
        if self._chord_active:
            return
        self._chord_active = True
        self._dev_dictation = dev

        if self._swapping:
            self.tray.notify("Updating. Ready in a moment.")
            return

        # Nothing is recorded (so nothing is sent to Cloud) until the user
        # has picked Cloud or Local on the first-run screen -- a network
        # transfer the user explicitly chose, as PRIVACY.md promises and
        # SignPath's signing policy expects. onboarding marks itself done
        # if its window can't open, so this can't lock dictation out.
        if not config.ONBOARDING_DONE:
            error_toast.show("Choose Cloud or Local in the setup window first.")
            return

        if self.transcriber is None:
            if self._no_model:
                self.tray.notify(
                    "No speech model is installed. Open Settings, then the "
                    "General tab, to download one under Local."
                )
            else:
                self.tray.notify("Still loading the speech model, please wait...")
            return

        if not is_focus_editable():
            self._no_target_cue()
            return
        self._target = paste_target.capture()

        try:
            self.recorder.preroll = config.PREROLL_SECONDS
            self.recorder.start()
        except Exception as exc:
            logging.warning("Could not start recording: %s", exc)
            self._mic_blank = True  # check the microphones again
            self._mic_event.set()
            self._not_typed("Couldn't open the microphone. Check that one is "
                            "connected and allowed in Windows' privacy settings.")
            return

        self._context = (screen_context.Pending()
                         if screen_context.enabled(self._cloud_active()) else None)
        self._press = continuation.press_info()
        # Moving on to the next dictation: any fix to the last one is done.
        fix_learning.check()
        self._recording = True
        self._latched = False
        self._recording_id += 1
        self._record_start_time = time.time()
        self._live_warned = False
        self.tray.set_recording()
        pill.show(lambda: self.recorder.level, getattr(self.recorder, "is_ready", None))
        self._slow_mic_hint()
        threading.Thread(target=self._check_mute, args=(self._recording_id,),
                         daemon=True).start()
        if self._cloud_active():
            # Open the Cloud connection while the user speaks, not after --
            # and if Cloud can't be reached, say so now, not after.
            threading.Thread(target=self._warm_cloud,
                             args=(self._recording_id,), daemon=True).start()

    def _warm_cloud(self, rec_id):
        if cloud_client.warm() or self._recording_id != rec_id or not self._recording:
            return
        if model_manager.is_downloaded(config.MODEL_SIZE):
            self._live_problem("Can't reach Talkative Cloud. Keep talking: this one "
                               "will be transcribed on this PC instead.")
        else:
            self._live_problem("Can't reach Talkative Cloud. Check your internet; "
                               "Talkative will keep trying when you let go.")

    def _check_mute(self, rec_id):
        """When the hotkey goes down: a microphone muted in Windows is
        reported at once. Only for the Windows default microphone (a mic
        picked in the tray is a PortAudio index, not a Windows device)."""
        if config.INPUT_DEVICE is not None or not audio_devices.default_mic_muted():
            return
        if self._recording_id == rec_id and self._recording:
            self._live_problem("Your microphone is muted in Windows. Let go, "
                               "unmute it, and try again.")

    def _check_live_mic(self):
        """Called from the main loop (every 0.2 s) while recording: a
        microphone that sends nothing at all, or stops sending, is
        reported while the user is still speaking, not after (2026-10-27,
        user request). Only certain signals -- never "too quiet" or
        "silent": a pause before speaking looks like both, and a noise-
        suppressing headset sends digital silence then (see BLANK_PEAK)."""
        if not self._recording or self._live_warned or self._record_start_time is None:
            return
        if time.time() - self._record_start_time < config.LIVE_CHECK_SECONDS:
            return
        rec = self.recorder
        if not rec.chunks or time.monotonic() - rec.last_chunk > config.LIVE_STALL_SECONDS:
            self._live_problem("The microphone isn't sending any sound. Let go, "
                               "then check that it's connected.")
        else:
            return
        self._mic_blank = True  # check the microphones once this one ends
        self._mic_event.set()

    def _live_problem(self, message):
        """Once per dictation: red line and the reason, while recording."""
        if self._live_warned:
            return
        self._live_warned = True
        _debug_log(live_problem=message)
        pill.alert()
        error_toast.show(message, seconds=config.NOT_TYPED_SECONDS)

    def _drop_stale_keys(self, key):
        """Forget hotkey keys whose release the hook never saw (lock screen,
        Ctrl+Alt+Del, sleep), and the hold-mode recording they kept open.
        Without this, a lost release left _chord_active or _recording set
        and every later press was ignored until a restart (user report
        2026-10-11: "sometimes stops working after sleep"). `key` is the
        one being pressed now; Windows hasn't marked it down yet."""
        stale = {k for k in self._hotkey_pressed if k != key and not _physically_down(k)}
        if not stale:
            return
        self._hotkey_pressed -= stale
        self._chord_active = False
        self._masked = False
        self._chord_engaged = False
        held = self._hotkey_pressed | {key}
        chord_held = set(config.HOTKEY) <= held or (
            bool(config.DEV_HOTKEY) and set(config.DEV_HOTKEY) <= held)
        if self._recording and not self._latched and not chord_held:
            logging.warning("Dropping a recording whose hotkey release was lost")
            self._stop_recording(process=False)

    def _check_lost_release(self):
        """Called from the main loop every 0.2 s. A hold-mode recording whose
        hotkey Windows says is no longer physically held means the release
        was lost -- Ctrl+Alt+Del, the lock screen and UAC prompts swallow it
        -- and the pill would keep recording until the next press (user
        report 2026-10-13, the first sleep/lock test of _drop_stale_keys,
        which only runs on that next press). After LOST_RELEASE_CHECKS
        checks in a row, drop the recording: the audio ran on into that
        screen, and pasting it into whatever has focus afterwards would be
        worse than losing it."""
        if not self._recording or self._latched:
            self._lost_release_checks = 0
            return
        try:
            held = {k for k in list(self._hotkey_pressed) if _physically_down(k)}
        except Exception:
            return
        chord_held = set(config.HOTKEY) <= held or (
            bool(config.DEV_HOTKEY) and set(config.DEV_HOTKEY) <= held)
        if chord_held:
            self._lost_release_checks = 0
            return
        self._lost_release_checks += 1
        if self._lost_release_checks < config.LOST_RELEASE_CHECKS:
            return
        self._lost_release_checks = 0
        logging.warning("Hotkey no longer held but its release was never seen; "
                        "dropping the recording")
        self._hotkey_pressed -= {k for k in list(self._hotkey_pressed) if k not in held}
        self._chord_active = False
        self._masked = False
        self._chord_engaged = False
        self._stop_recording(process=False)

    def _on_resume(self):
        """The PC just woke from sleep or hibernation. Start clean: a
        recording that was open when it slept is dropped, held-key state
        is forgotten, PortAudio is restarted (the microphone it knew about
        may be gone or renumbered -- Bluetooth headsets reconnect after
        wake), and the keyboard hook is reinstalled, since Windows can
        remove a low-level hook without telling the app."""
        logging.warning("Resumed from sleep; resetting hotkey and audio state")
        if self._recording:
            self._stop_recording(process=False)
        self._hotkey_pressed.clear()
        self._chord_active = False
        self._masked = False
        self._chord_engaged = False
        self._latched = False
        self.recorder.reset()
        self._start_listener()

    def _watch_microphones(self):
        """PortAudio reads the device list once, so a microphone plugged
        in or made the Windows default later was never used until a
        restart (user report 2026-10-26). Restart it when Windows' list
        or default changes -- between dictations only: a change seen
        mid-dictation is applied after it. Windows says when that happens
        (audio_devices.watch_devices), so this thread sleeps otherwise;
        a blank recording (_check_blank) also wakes it, and then PortAudio
        is restarted even if Windows' list looks the same."""
        if audio_devices.watch_devices(self._mic_event.set):
            wait = None
        else:
            wait = config.MIC_CHECK_SECONDS  # fall back to asking
        applied = audio_devices.capture_state()
        threading.Thread(target=self._probe_mic, daemon=True).start()
        while self._running:
            self._mic_event.wait(wait)
            if not self._running:
                return
            if self._mic_event.is_set():
                time.sleep(config.MIC_SETTLE_SECONDS)
                self._mic_event.clear()
            while self._recording and self._running:
                time.sleep(0.2)
            state = audio_devices.capture_state()
            force, self._mic_blank = self._mic_blank, False
            if state is None or (state == applied and not force):
                continue
            try:
                chosen = config.INPUT_DEVICE
                if not self.recorder.reset():
                    self._mic_blank = force
                    self._mic_event.set()  # recording again: retry after
                    continue
                applied = state
                logging.getLogger(__name__).info(
                    "Device list reloaded (%s)", "blank recording" if force else "microphones changed")
                if chosen is not None and self.recorder.device != chosen:
                    # Renumbered, or gone (None: back to the Windows default).
                    config.INPUT_DEVICE = self.recorder.device
                    settings.save({"input_device": self.recorder.device})
                if not force:
                    # A different mic may start differently.
                    threading.Thread(target=self._probe_mic, daemon=True).start()
            except Exception:
                logging.getLogger(__name__).exception("microphone reload failed")

    def _test_box_report(self, audio, cold):
        """The microphone test box is open (first run, or Settings >
        Test microphone): show what this dictation says about the mic. A
        cut-off start seen there marks the mic slow at once -- the box
        already explains it, so no tray notice on top."""
        try:
            found = try_it_now.report(audio, config.SAMPLE_RATE, cold)
            if not found or "cut" not in [kind for kind, _ in found]:
                return
            device = self.recorder.device
            ms = mic_warmup.leading_silence_ms(audio, config.SAMPLE_RATE)
            mic_warmup.mark_slow(device, ms, "test dictation")
            name = mic_warmup.device_key(device)
            if name and name not in config.SLOW_MIC_NOTIFIED:
                config.SLOW_MIC_NOTIFIED = list(config.SLOW_MIC_NOTIFIED) + [name]
                settings.save({"slow_mic_notified": config.SLOW_MIC_NOTIFIED})
        except Exception:
            logging.getLogger(__name__).exception("microphone test report failed")

    def _observe_mic(self, audio, cold):
        """Did this dictation show the mic sending silence at first
        (cut-off first word)? Two of three cold starts that did: slow."""
        try:
            mic_warmup.observe(self.recorder.device, audio, cold, config.SAMPLE_RATE)
        except Exception:
            logging.getLogger(__name__).exception("slow mic check failed")

    def _probe_mic(self):
        """Measure how fast the mic Talkative uses starts (mic_warmup):
        at startup and after a microphone change, never before the user
        has chosen Cloud or Local (nothing is recorded until then)."""
        if not config.ONBOARDING_DONE or not self._running:
            return
        try:
            # Another app holding the mic open (or a stream of our own)
            # makes it look fast, so a fast result is checked once more.
            for attempt in range(2):
                if attempt:
                    time.sleep(config.SLOW_MIC_RECHECK_SECONDS)
                    if not self._running:
                        return
                mic_warmup.probe(
                    self.recorder.device,
                    recorder_busy=lambda: self._recording or self.recorder._stream is not None)
                if mic_warmup.is_slow(self.recorder.device):
                    return  # said at the next press (_slow_mic_hint)
        except Exception:
            logging.getLogger(__name__).exception("microphone start-up check failed")

    def _slow_mic_hint(self):
        """First press with a microphone found slow: say so right above
        the listening line, where the user is looking as they start to
        talk (user request 2026-10-31; was a tray notice when the mic was
        found slow, easy to miss and away from the moment it matters).
        Once per microphone. Never breaks the press."""
        try:
            device = self.recorder.device
            if not mic_warmup.is_slow(device):
                return
            name = mic_warmup.device_key(device)
            if not name or name in config.SLOW_MIC_NOTIFIED:
                return
            ms = mic_warmup.slow_ms(device) or config.SLOW_MIC_MS
            config.SLOW_MIC_NOTIFIED = list(config.SLOW_MIC_NOTIFIED) + [name]
            settings.save({"slow_mic_notified": config.SLOW_MIC_NOTIFIED})
            error_toast.show(
                f"This microphone takes {ms / 1000:.1f} s to pick up sound. "
                "Start speaking when the line below lights up.",
                seconds=config.SLOW_MIC_HINT_SECONDS, info=True, at_line=True)
        except Exception:
            logging.getLogger(__name__).exception("slow mic hint failed")

    def _check_blank(self, audio):
        """A recording with no signal at all means the microphone gave
        nothing (gone, muted, the wrong one): check the devices now
        rather than wait for Windows to say something changed."""
        try:
            if audio.size and float(np.max(np.abs(audio))) < config.BLANK_PEAK:
                logging.getLogger(__name__).warning("Blank recording; checking microphones")
                self._mic_blank = True
                self._mic_event.set()
        except Exception:
            logging.getLogger(__name__).exception("blank check failed")

    def _start_listener(self):
        # pynput stops the listener for good when a callback raises, which
        # silently ends dictation until a restart. Log and carry on.
        def guarded(handler):
            def call(key):
                try:
                    handler(key)
                except Exception:
                    logging.getLogger(__name__).exception("hotkey handler failed")
            return call

        old, self._listener = self._listener, keyboard.Listener(
            on_press=guarded(self._on_press), on_release=guarded(self._on_release)
        )
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        self._listener.start()

    def _on_release(self, key):
        if key not in config.HOTKEY and key not in config.DEV_HOTKEY:
            return
        self._hotkey_pressed.discard(key)
        self._masked = False
        if not self._hotkey_pressed:
            self._chord_engaged = False
        if self._latched:
            # Only re-arm once every hotkey key is up, so the second key of
            # a two-key tap being released (or still held) can't count as
            # the stopping press.
            if not self._hotkey_pressed:
                self._chord_active = False
            return
        self._chord_active = False
        if not self._recording:
            return

        # Toggle mode: a quick tap leaves recording on until the next tap.
        # A longer press behaves like hold mode and stops here.
        if (self._toggle_mode()
                and time.time() - self._record_start_time < config.TAP_MAX_SECONDS):
            self._latched = True
            self._chord_active = bool(self._hotkey_pressed)
            timer = threading.Timer(
                config.TOGGLE_MAX_SECONDS, self._auto_stop, args=(self._recording_id,)
            )
            timer.daemon = True
            timer.start()
            return

        still = ", ".join(friendly_key(k) for k in self._hotkey_pressed)
        self._stop_recording(reason=f"releasing {friendly_key(key)}"
                             + (f" ({still} still held)" if still else ""))

    def _auto_stop(self, rec_id):
        if self._recording_id != rec_id:
            return
        if self._stop_recording(reason="time limit"):
            self.tray.notify(
                f"Stopped listening after {config.TOGGLE_MAX_SECONDS // 60} minutes."
            )

    def _stop_recording(self, process=True, reason="?"):
        """Stop the current recording and, unless process=False, send it
        down the pipeline. Returns False if nothing was recording. Locked:
        toggle mode's auto-stop timer can race a key press."""
        with self._stop_lock:
            if not self._recording:
                return False
            self._recording = False
            self._latched = False
        self.tray.set_idle()
        # A dictation that will be typed keeps the mic open for a quick
        # re-press (audio_recorder: the first word of a continuation).
        # A slow-starting mic stays open longer (mic_warmup), so the next
        # dictation doesn't lose its first word to the mic waking up.
        cold = getattr(self.recorder, "cold", False)
        linger = 0
        if process:
            slow = mic_warmup.is_slow(getattr(self.recorder, "device", None))
            linger = config.SLOW_MIC_KEEP_SECONDS if slow else config.CONTINUE_SECONDS
        audio = self.recorder.stop(linger=linger)
        duration = time.time() - self._record_start_time
        if process and duration >= config.MIN_RECORDING_SECONDS:
            self._test_box_report(audio, cold)
            self._observe_mic(audio, cold)

        if not process or duration < config.MIN_RECORDING_SECONDS:
            pill.hide()
            return True
        # The line stays, as "processing", until this dictation is typed
        # or the reason it wasn't is shown (_process_audio).
        pill.busy()
        self._check_blank(audio)

        with self._order:
            seq = self._next_seq
            self._next_seq += 1
        threading.Thread(
            target=self._process_audio, daemon=True,
            args=(audio, self._dev_dictation, seq,
                  _audio_summary(audio, config.SAMPLE_RATE, reason)
                  + _ready_note(self.recorder, cold), self._context,
                  self._press, paste_target.at_release(self._target)),
        ).start()
        return True

    def _process_audio(self, audio, dev=False, seq=None, info="", context=None, press=None,
                       target=None):
        with self._order:
            self._jobs += 1
        self._job_seq.value = seq
        self._job_target.value = target
        self._job_report.value = None
        try:
            self._job_blank.value = bool(
                audio.size and float(np.max(np.abs(audio))) < config.BLANK_PEAK)
        except Exception:
            self._job_blank.value = False
        # Taking long (Cloud slow, a fallback loading): say so once, so the
        # user isn't left wondering whether anything is happening.
        slow = threading.Timer(config.SLOW_NOTICE_SECONDS, lambda: error_toast.show(
            "Still working on it…" + (" Talkative Cloud is slower than usual right now."
                                      if self._cloud_active() else ""),
            seconds=4, info=True))
        slow.daemon = True
        slow.start()
        try:
            self._process_audio_inner(audio, dev, info, context, press)
        except Exception:
            logging.exception("Dictation failed")
            self._not_typed("Something went wrong, so nothing was typed. "
                            "The details are in errors.log.")
        finally:
            slow.cancel()
            self._report("finished without a paste")
            with self._order:
                self._jobs -= 1
                idle = self._jobs == 0
                if seq is not None:
                    self._finished.add(seq)
                    while self._turn in self._finished:
                        self._finished.remove(self._turn)
                        self._turn += 1
                    self._order.notify_all()
            if idle:
                pill.done()

    def _not_typed(self, reason):
        """A dictation that won't be typed says why, near the cursor, long
        enough to read -- never silently, never a blocking popup."""
        _debug_log(not_typed=reason)
        self._report("not typed: " + reason)
        error_toast.show(reason, seconds=config.NOT_TYPED_SECONDS)

    def _wait_for_turn(self):
        """Block until every earlier dictation has pasted (or finished
        without text). Capped, so one stuck dictation can't hold the rest
        back for ever."""
        seq = getattr(self._job_seq, "value", None)
        if seq is None:
            return
        with self._order:
            self._order.wait_for(lambda: self._turn >= seq, timeout=30)

    def _process_audio_inner(self, audio, dev=False, info="", context=None, press=None):
        # Developer English swaps the sentence-style bias prompt for one
        # that keeps spoken symbols as literal words (see dev_mode.py).
        base_prompt = dev_mode.STT_PROMPT if dev else config.PUNCTUATION_PROMPT
        # The text before the cursor goes last: Whisper reads the prompt as
        # what was said just before, so this dictation continues it
        # (screen_context.py). Re-checked here in case the mode changed
        # while recording.
        on_screen = ""
        if context is not None and not dev and screen_context.enabled(self._cloud_active()):
            on_screen = context.get()
        prompt = " ".join(p for p in (base_prompt, vocabulary_prompt(), on_screen) if p) or None
        t0 = time.time()
        self._cloud_down.value = False
        transcriber = self.transcriber
        if not self._cloud_active() and (
                transcriber is None or transcriber is _CLOUD_TRANSCRIBER):
            # Switched to Local while this one was being recorded, and the
            # local model isn't loaded yet. Never fall back to Cloud here:
            # the user just chose Local.
            self.tray.notify("Local mode is still getting ready, so that "
                             "dictation was skipped. Try again in a moment.")
            return
        try:
            if self._cloud_active():
                text = self._cloud_transcribe(audio, prompt, dev)
            else:
                text = transcriber.transcribe(
                    audio, config.SAMPLE_RATE, initial_prompt=prompt
                )
        except Exception as exc:
            logging.warning("Transcription failed: %s", exc)
            if self._cloud_active():
                why = cloud_client.friendly_error(exc)
            else:
                why = "The speech model couldn't transcribe it."
            self._not_typed(f"{why} Nothing was typed. Please try again.")
            return
        if on_screen and screen_context.suspect(text, len(audio) / config.SAMPLE_RATE):
            text, retried = self._retry_without_context(
                audio, text, " ".join(p for p in (base_prompt, vocabulary_prompt()) if p),
                dev, transcriber)
            if retried:
                info = f"{info}, retried without screen context" if info else \
                    "retried without screen context"
        transcribe_secs = time.time() - t0
        saved = _debug_save_audio(audio)
        if saved:
            info = f"{info}, {saved}" if info else saved
        last_trim = getattr(cloud_client, "last_trim", None)
        trim = getattr(last_trim, "secs", 0.0) if self._cloud_active() else 0.0
        if last_trim is not None:
            last_trim.secs = 0.0
        if info and trim:
            info += f", {trim:.1f}s silence trimmed"

        raw = text
        if dev:
            text, is_code = dev_mode.process(text)
            if is_code:
                # A command/code line is final after the rules pass: no
                # filler/correction/repeat rules, no grammar model, no
                # sentence period, and no personal dictionary (an expansion
                # like "AI" -> "artificial intelligence" would corrupt code).
                self._record(audio, audio_info=info, raw=raw, final=text,
                             timing=f"transcribe {transcribe_secs:.1f}s [developer: code]")
                # Not watched for corrections: Auto Text never applies to
                # code, so a learned pair could never help here.
                self._insert_final(text, learn=False)
                return
        # Symbol words ("underscore", "dot") first, before anything else
        # sees the text -- this fixes literal-word transcription
        # ("settings dot py") into the intended identifier
        # ("settings.py"), and doing it early means the grammar engine's
        # word-retention guard checks against the already-fused text
        # instead of expecting "dot" to survive verbatim.
        text = apply_spoken_symbols(text)
        if config.ENABLE_NUMBER_FORMAT and config.CLEANUP_MODE == "cleaned_up":
            # Before grammar, which would turn ".1" into "0.1".
            text = restore_spoken_point(text)
        # Fillers first: "sorry, um, I mean" must become "sorry I mean"
        # before the correction triggers run.
        if config.CLEANUP_MODE == "cleaned_up":
            text = remove_fillers(text)
            after_fillers = text
            if config.ENABLE_SELF_CORRECTION:
                text = apply_self_corrections(text)
            after_corrections = text
            text = collapse_repeats(text)
            after_collapse = text
            pre_grammar = text
            t0 = time.time()
            grammar_used_local = self._grammar_uses_local()
            if grammar_used_local:
                text = grammar_engine.apply(text)
            elif not self._cloud_down.value:
                # Skipped when Cloud just refused the transcription: it
                # would most likely refuse this too, maybe after a 20 s
                # timeout. The rule-based cleanup above still ran.
                text = self._cloud_grammar(
                    text, corrected=after_corrections != after_fillers
                )
            grammar_secs = time.time() - t0
            if dev:
                # The grammar model likes to wrap paths in backticks
                # ("`/api/v2/users`"); plain text is wanted here.
                text = dev_mode.strip_backticks(text)
            after_grammar = text
            text = finish_sentence(text)
            if config.ENABLE_NUMBER_FORMAT and not dev:
                # After grammar: its digit guard keeps numbers as heard,
                # and this picks the written form with fixed rules.
                text = format_numbers(text)
            if config.ENABLE_BULLETS and not dev:
                listed = format_bullets(text)
                if BULLET not in listed:
                    # The grammar model can fold spoken points into one
                    # sentence ("...three things: book the hall, send the
                    # invites, and order the food", Local, QA 2026-10-11).
                    # If the words as spoken were a list, keep the list.
                    spoken = finish_sentence(pre_grammar)
                    if config.ENABLE_NUMBER_FORMAT:
                        spoken = format_numbers(spoken)
                    spoken = format_bullets(spoken)
                    if BULLET in spoken:
                        listed = spoken
                text = listed
        else:
            after_fillers = after_corrections = after_collapse = after_grammar = text
            grammar_secs = 0.0
            grammar_used_local = False

        text = apply_dictionary(text)
        self._record(
            audio,
            audio_info=info,
            context=on_screen,
            raw=raw,
            fillers=after_fillers,
            corrections=after_corrections,
            collapse=after_collapse,
            grammar=after_grammar,
            final=text,
            timing=f"transcribe {transcribe_secs:.1f}s, grammar {grammar_secs:.1f}s"
            + (f" [{config.GRAMMAR_MODEL_DIR if grammar_used_local else 'cloud'}]"
               if grammar_secs else "")
            + (f" [grammar skipped: {grammar_engine.last_skip}]"
               if grammar_used_local and grammar_engine.last_skip else "")
            + (" [developer: prose]" if dev else ""),
        )
        self._insert_final(text, press=press)

    def _cloud_grammar(self, text, corrected=False):
        """Cloud grammar. For Indian English (Azure) it first tries Azure's
        unpunctuated words: Azure ends a sentence at every pause
        ("...the user of the software. Stop between a sentence..."), and
        punctuating the plain words fixes that. The model is unreliable on
        unpunctuated text (it once answered a question instead of
        punctuating it), so if the guards reject that attempt, the
        punctuated text is cleaned up as usual. Measured on 20 real
        dictations, 2026-10-23: never worse, often better.

        Not when a spoken correction was applied to the punctuated text
        (`corrected`): without sentence breaks the correction rule can't
        find what to retract, and the model kept "Monday sorry I mean
        Tuesday" (live test 2026-10-25)."""
        itn = getattr(cloud_client.last_stt, "itn", "") if self._cloud_active() else ""
        if corrected:
            itn = ""
        if itn:
            plain = apply_spoken_symbols(itn)
            if config.CLEANUP_MODE == "cleaned_up":
                plain = remove_fillers(plain)
                if config.ENABLE_SELF_CORRECTION:
                    plain = apply_self_corrections(plain)
                plain = collapse_repeats(plain)
            cleaned = cloud_client.grammar_apply(plain)
            if cleaned != plain:
                return cleaned
        return cloud_client.grammar_apply(text)

    def _record(self, audio, **stages):
        """One dictation's stages to debug.log (if on) and, if the user
        turned on Send diagnostic data, to Talkative's server."""
        stages["audio"] = stages.pop("audio_info")
        _debug_log(**stages)
        # Sent by _report once the paste is done or refused, so the report
        # says what happened to the text (2026-10-28: a user's failed
        # pastes were invisible in their reports).
        self._job_report.value = (audio, self._cloud_active(), stages)

    def _report(self, outcome):
        """Send this dictation's diagnostic report (once) with `outcome`."""
        pending = getattr(self._job_report, "value", None)
        if pending is None:
            return
        self._job_report.value = None
        audio, cloud, stages = pending
        stages["paste"] = outcome
        diagnostics.send(audio, cloud, stages)

    def _retry_without_context(self, audio, text, prompt, dev, transcriber):
        """A transcript made with screen context looked broken
        (screen_context.suspect): transcribe the same audio once more
        without it and keep whichever has more words. Returns (text,
        whether the retry's text was used). A failed retry keeps the
        first result -- it already counted as a success."""
        try:
            if self._cloud_active():
                again = self._cloud_transcribe(audio, prompt or None, dev)
            else:
                again = transcriber.transcribe(audio, config.SAMPLE_RATE,
                                               initial_prompt=prompt or None)
        except Exception as exc:
            logging.warning("Retry without screen context failed: %s", exc)
            return text, False
        if len((again or "").split()) > len((text or "").split()):
            return again, True
        return text, False

    def _cloud_transcribe(self, audio, prompt, dev=False):
        """Cloud transcription that doesn't lose the dictation when Cloud
        is busy or unreachable (both Groq and the Workers AI fallback
        refused, the per-install daily cap, no internet). If the Local
        voice model is downloaded, that dictation is transcribed on this
        PC instead -- the audio never leaves it, so nothing new for
        PRIVACY.md. Without it, Cloud is retried twice (Groq's limit is
        per minute, so seconds later usually works) before giving up.
        Windows' own recognizer is no fallback: the one apps can call
        (SAPI dictation) got 85% of words wrong on the 59 real recordings
        Cloud gets 14.6% on (2026-10-04); Win+H voice typing has no API.

        Indian English (config.SPEECH_SERVICE) asks the Worker for Azure;
        when Azure is busy or its free hours are used up, the Worker uses
        Groq instead, and the user hears about it at most every 10 minutes.
        Developer English always uses Groq: its literal-symbol prompt
        needs Whisper."""
        indian = config.SPEECH_SERVICE == "indian_english" and not dev
        try:
            text = cloud_client.transcribe(audio, config.SAMPLE_RATE,
                                           initial_prompt=prompt, indian_english=indian)
            if (indian and text and getattr(cloud_client.last_stt, "via", "") != "azure"
                    and time.time() - self._azure_notice > 600):
                self._azure_notice = time.time()
                self.tray.notify("Indian English is busy right now, so US English "
                                 "transcribed this one.")
            return text
        except Exception as exc:
            first_error = exc
        self._cloud_down.value = True
        logging.warning("Cloud transcription failed (%s); falling back", first_error)
        local = self._fallback_transcriber()
        if local is not None:
            text = local.transcribe(audio, config.SAMPLE_RATE, initial_prompt=prompt)
            self.tray.notify("Cloud was busy, so this dictation was "
                             "transcribed on this PC instead.")
            return text
        for delay in config.CLOUD_RETRY_DELAYS:
            time.sleep(delay)
            if not self._cloud_active():
                break
            try:
                text = cloud_client.transcribe(audio, config.SAMPLE_RATE,
                                               initial_prompt=prompt)
                self._cloud_down.value = False
                return text
            except Exception as exc:
                logging.warning("Cloud retry failed (%s)", exc)
        raise first_error

    def _fallback_transcriber(self):
        """The Local voice model for a Cloud-busy dictation, loaded on
        first need and dropped again after FALLBACK_IDLE_SECONDS unused
        (~0.5 GB of memory a Cloud user didn't ask for). None when it
        isn't downloaded or won't load, or while an update swaps it."""
        if self._swapping or not model_manager.is_downloaded(config.MODEL_SIZE):
            return None
        with self._fallback_lock:
            if self._fallback is None:
                try:
                    self._fallback = Transcriber(
                        config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE,
                        download_root=str(model_manager.models_dir()),
                    )
                except Exception as exc:
                    logging.warning("Local fallback model failed to load: %s", exc)
                    return None
            model = self._fallback
            if self._fallback_timer is not None:
                self._fallback_timer.cancel()
            self._fallback_timer = threading.Timer(
                config.FALLBACK_IDLE_SECONDS, self._drop_fallback)
            self._fallback_timer.daemon = True
            self._fallback_timer.start()
        return model

    def _drop_fallback(self):
        import gc

        with self._fallback_lock:
            self._fallback = None
            if self._fallback_timer is not None:
                self._fallback_timer.cancel()
                self._fallback_timer = None
        gc.collect()  # release the model.bin mapping (updates move the files)

    def _insert_final(self, text, learn=True, press=None):
        if not text:
            if getattr(self._job_blank, "value", False):
                self._not_typed("No words were heard, so nothing was typed. If you "
                                "spoke, check that your microphone isn't muted.")
            else:
                self._not_typed("No words were heard, so nothing was typed.")
            return
        self._wait_for_turn()
        # The user may have switched windows since letting go of the key:
        # paste where they dictated, then give them their window back
        # (paste_target.py; their choice, 2026-10-27).
        target = getattr(self._job_target, "value", None)
        back = None
        if config.INSERT_MODE != "clipboard":
            try:
                back = paste_target.bring_back(target)
            except paste_target.Lost as exc:
                logging.getLogger(__name__).info("paste target lost: %s", exc)
                copy_only(text)
                self._not_typed("The window you dictated into was closed or couldn't "
                                "be brought back, so the text is on the clipboard. "
                                "Click where it goes and press Ctrl+V.")
                return
        try:
            self._insert_here(text, learn, press)
        finally:
            paste_target.return_to(back, target)

    def _still_in_target(self):
        """The window this dictation was spoken into, checked editable at
        the press, is the one in front. A target without its control is a
        window the user moved to while speaking (paste_target.at_release):
        never checked, so not trusted."""
        target = getattr(self._job_target, "value", None)
        try:
            return bool(target is not None and target.hwnd and target.control is not None
                        and paste_target.user32.GetForegroundWindow() == target.hwnd)
        except Exception:
            return False

    def _insert_here(self, text, learn, press):
        editable, why, kind = focus_check.focus_state()
        trusted = False
        if not editable and why in focus_check.UNSEEN and self._still_in_target():
            # UIA can't see the focused control, but the window the user
            # dictated into (checked editable at the press) is still in
            # front: a UIA glitch, not a move. Seen 2026-10-28 in Claude
            # Code's input box, repeatedly, until Talkative was restarted.
            # A warning so errors.log shows how often this happens.
            logging.warning("Focus check said %s (%s) in the dictation's own window; "
                            "pasting anyway", why, kind)
            editable = trusted = True
        if not editable:
            # Focus moved while it was processed: keep the words.
            copy_only(text)
            self._report(f"not typed: no text box ({why}: {kind})")
            self._not_typed("No text box was selected, so the text is on the "
                            "clipboard. Click where it goes and press Ctrl+V.")
            return

        take_back = 0
        # Carrying on the last dictation's sentence (continuation.py). The
        # text before the cursor is read here only to check that what was
        # just typed is still there; it never leaves this PC.
        if (learn and press is not None and config.INSERT_MODE != "clipboard"
                and continuation.joins(press, screen_context.capture())):
            take_back = continuation.chars_to_delete()
            text = " " + continuation.lowercase_start(text)
        if learn and press is not None and continuation.last_check:
            _debug_log(continuation=continuation.last_check)
            continuation.last_check = None
        # Typed into the middle of a sentence (a wrong word deleted, the
        # right one dictated): no capital, no full stop before the rest of
        # it. Read here, on this PC only; nothing is sent.
        space = None
        if (learn and not take_back and config.FIT_TO_CURSOR
                and config.INSERT_MODE != "clipboard"):
            around = screen_context.around_caret()
            if around is not None:
                fitted, space = continuation.fit_to_cursor(text, *around)
                if fitted != text or space is not None:
                    _debug_log(cursor=f"{around[0][-20:]!r} | {around[1][:20]!r} -> {fitted!r}")
                text = fitted
        insert_text(text, take_back=take_back, append_space=space)
        if config.INSERT_MODE == "clipboard":
            self._report("copied (clipboard mode)")
        else:
            self._report(f"pasted into {kind}"
                         + (f" (focus check said {why}; same window, pasted anyway)"
                            if trusted else ""))
        if config.INSERT_MODE != "clipboard":
            appended = config.APPEND_SPACE if space is None else space
            continuation.note_paste(text + (" " if appended else ""))
        if learn and config.INSERT_MODE != "clipboard":
            fix_learning.watch(text, on_new=self._fixes_noticed)
        if config.ENABLE_HISTORY:
            history.add(text)
        updater.note_words(len(text.split()))
        if config.INSERT_MODE == "clipboard":
            self.tray.notify("Copied to clipboard. Press Ctrl+V to paste.")

    def _fixes_noticed(self, pairs):
        heard, typed = pairs[0]
        more = f" (and {len(pairs) - 1} more)" if len(pairs) > 1 else ""
        self.tray.notify(
            f"You corrected “{heard}” to “{typed}”{more}. To fix it every time, "
            "add it in Settings → Auto Text.")

    def run(self):
        sync_autostart()
        if self._cloud_active():
            self._enter_cloud_mode()
            grammar_engine.unload()
        else:
            self._load_model_async()
            # Separate thread: the grammar engine must never delay dictation
            # readiness; until (unless) it loads, cleaned_up mode is rules-only.
            threading.Thread(target=self._load_grammar, daemon=True).start()
        # Models load above as usual, but _on_press refuses to record until
        # this screen is answered. on_choice re-syncs everything (model
        # loading, grammar source) if the user picks something different
        # from the configured default.
        try_it_now.controller = SimpleNamespace(
            get=lambda: self.recorder.device, set=self._set_input_device)
        onboarding.maybe_show(on_choice=self._onboarding_done)
        # Local setup's background grammar download, if Talkative was
        # closed before it finished (see onboarding.finish_local).
        if config.GRAMMAR_PENDING_DOWNLOAD:
            grammar_engine.download_in_background()
        updater.start_background_check(self.updater_controller())
        # A minute in, so it never competes with startup or the first
        # dictation; see temp_cleanup.py for why the folders pile up.
        cleanup = threading.Timer(60, temp_cleanup.sweep)
        cleanup.daemon = True
        cleanup.start()
        feedback.start_background_check(
            on_reply=lambda text: self.tray.notify(
                text if len(text) <= 200 else text[:197] + "…",
                title="Sumit replied",
            )
        )
        threading.Thread(target=self._watch_microphones, daemon=True).start()
        self._start_listener()
        self.tray.run_detached()

        # Sleep shows up as this loop's 0.2 s nap taking far longer by the
        # wall clock. (A clock change can look the same; a needless reset
        # is harmless.)
        last = time.time()
        try:
            while self._running:
                time.sleep(0.2)
                now = time.time()
                if abs(now - last) > config.RESUME_GAP_SECONDS:
                    try:
                        self._on_resume()
                    except Exception:
                        logging.getLogger(__name__).exception("resume reset failed")
                last = now
                try:
                    self._check_lost_release()
                except Exception:
                    logging.getLogger(__name__).exception("lost-release check failed")
                try:
                    self._check_live_mic()
                except Exception:
                    logging.getLogger(__name__).exception("live microphone check failed")
        except KeyboardInterrupt:
            pass

    def quit(self):
        self._running = False
        self._mic_event.set()
        if self._listener:
            self._listener.stop()
        self.recorder.close()
