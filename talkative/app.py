import datetime
import logging
import threading
import time

from pynput import keyboard

from . import cloud_client, cloud_notice, config, dev_mode, error_toast, feedback, grammar_engine, history, model_manager, onboarding, pill, settings, try_it_now, updater
from .audio_recorder import AudioRecorder
from .autostart import sync_autostart
from .cleanup import collapse_repeats, finish_sentence, remove_fillers
from .dictionary import apply_dictionary, vocabulary_prompt
from .focus_check import is_focus_editable
from .keynames import friendly as friendly_key
from .self_correction import apply_self_corrections
from .spoken_symbols import apply_spoken_symbols
from .text_inserter import insert_text
from .transcriber import Transcriber
from .tray import TrayApp, show_error_popup


# Placeholder assigned to self.transcriber in cloud mode so the existing
# "self.transcriber is None" readiness gate in _on_press still works, even
# though nothing ever calls .transcribe() on it -- _process_audio_inner
# branches on _cloud_active() before it would.
_CLOUD_TRANSCRIBER = object()

_TONE_RATE = 16000

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


def _tone_samples(freq, seconds, volume, rate=_TONE_RATE):
    """A soft mono sine tone as float32 samples in [-1, 1], with a 5ms fade
    in/out so it doesn't click. Played via sounddevice (not winsound, which
    always uses the system default output regardless of OUTPUT_DEVICE)."""
    import numpy as np

    n = int(rate * seconds)
    fade = max(1, int(rate * 0.005))
    t = np.arange(n)
    env = np.minimum(1.0, np.minimum(t / fade, (n - t) / fade))
    amp = max(0.0, min(1.0, volume))
    return (amp * env * np.sin(2 * np.pi * freq * t / rate)).astype("float32")


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


class TalkativeApp:
    def __init__(self):
        # Must run before anything else touches the data folder -- the
        # very next line reads settings.json out of it.
        settings.migrate_data_folder()
        settings.load_into_config()
        self.recorder = AudioRecorder(
            sample_rate=config.SAMPLE_RATE, device=config.INPUT_DEVICE
        )
        self.transcriber = None
        self._recording = False
        self._record_start_time = None
        self._running = True
        self._listener = None
        self._no_model = False  # active model was deleted; not merely still loading
        self._tones = {}  # (freq, seconds) -> generated sample array, cached
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
        self._swapping = False  # model swap in progress (update install/undo)
        self._hotkey_pressed = set()  # currently-held keys that are part of HOTKEY or DEV_HOTKEY
        self._chord_active = False  # chord already handled for this press-hold, ignore OS key-repeat
        self._dev_dictation = False  # current recording is developer English (DEV_HOTKEY)
        self._latched = False  # toggle mode: recording stays on after a tap, until the next one
        self._recording_id = 0  # bumped per recording, so a stale auto-stop timer can't stop a later one
        self._stop_lock = threading.Lock()
        self._mode_lock = threading.Lock()  # transcriber swaps vs. a finishing background load
        self._masked = False  # mask key already sent for the chord currently held
        self.tray = TrayApp(
            on_quit=self.quit, on_settings=self.open_settings,
            hotkey_label=friendly_key(config.HOTKEY),
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

    def _apply_settings(self):
        sync_autostart()
        self.recorder.device = config.INPUT_DEVICE
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
        """True when the grammar cleanup stage should run on the local
        engine -- always in Local processing mode, and also in Cloud mode
        when GRAMMAR_SOURCE == "local" and the local model is actually
        installed (falls back to Cloud grammar otherwise)."""
        if not self._cloud_active():
            return True
        return config.GRAMMAR_SOURCE == "local" and grammar_engine.is_installed()

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
            self._sync_grammar_source()
        elif self.transcriber is _CLOUD_TRANSCRIBER:
            self.transcriber = None
            self._load_model_async()
            threading.Thread(target=self._load_grammar, daemon=True).start()

    def _load_grammar(self):
        """Load the local grammar engine, then drop it again if the mode
        changed while it loaded and no longer wants it -- it's ~1.5 GB of
        memory, which matters on 8 GB laptops."""
        def wanted():
            return not self._cloud_active() or config.GRAMMAR_SOURCE == "local"

        if not wanted():
            return
        grammar_engine.load()
        if not wanted():
            grammar_engine.unload()

    def _sync_grammar_source(self):
        """While Cloud transcription is active, load or unload the local
        grammar engine to match GRAMMAR_SOURCE -- independent of whether
        the transcriber itself just switched, so toggling GRAMMAR_SOURCE
        alone (without touching PROCESSING_MODE) still takes effect. Local
        transcribe mode always wants the engine loaded and is handled by
        the other branch of _sync_processing_mode, so this only runs from
        the Cloud branch."""
        if config.GRAMMAR_SOURCE == "local":
            threading.Thread(target=self._load_grammar, daemon=True).start()
        else:
            grammar_engine.unload()

    # kind -> sequence of (freq_hz, seconds). "done" is a rising two-note
    # chime, distinct from the single start/stop tones, played after the
    # text lands in the target application.
    _SOUNDS = {
        "start": [(880, 0.07)],
        "stop": [(440, 0.07)],
        "done": [(660, 0.08), (880, 0.10)],
    }

    def _beep(self, kind):
        if not config.PLAY_SOUNDS:
            return

        def _play():
            try:
                import sounddevice as sd

                for freq, seconds in self._SOUNDS[kind]:
                    # Cached: building the samples isn't free.
                    tone = self._tones.get((freq, seconds))
                    if tone is None:
                        tone = _tone_samples(freq, seconds, config.SOUND_VOLUME)
                        self._tones[(freq, seconds)] = tone
                    # Blocking playback so multi-note sequences chain.
                    sd.play(tone, samplerate=_TONE_RATE,
                            device=config.OUTPUT_DEVICE, blocking=True)
            except Exception:
                pass

        threading.Thread(target=_play, daemon=True).start()

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

        if self._cloud_active():
            # Cloud dictation doesn't need the local model: deleting it
            # used to turn Cloud dictation off too, until a restart.
            gc.collect()
            return
        self.transcriber = None
        self._no_model = True
        gc.collect()
        self.tray.set_loading("no model — open Settings, then Models")

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
            # Toggle mode: another key pressed while the hotkey is still
            # down means the hotkey was part of a shortcut (Right Ctrl+C),
            # not a tap -- drop the recording that press started instead
            # of leaving it latched on. Hold mode is unchanged.
            if (self._toggle_mode() and self._recording and not self._latched
                    and self._hotkey_pressed):
                self._stop_recording(process=False)
            return
        self._hotkey_pressed.add(key)
        dev = bool(config.DEV_HOTKEY) and self._hotkey_pressed == set(config.DEV_HOTKEY)
        # Once per physical chord press (key-repeat re-fires on_press), and
        # only for the complete chord -- the Windows key pressed on its
        # own must still open Start.
        if (not self._masked and self._hotkey_pressed & _MASKED_KEYS
                and (dev or self._hotkey_pressed == set(config.HOTKEY))):
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
                self._stop_recording()
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
            self.tray.notify("Updating — ready in a moment.")
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
                    "Models tab, to download one."
                )
            else:
                self.tray.notify("Still loading the speech model, please wait...")
            return

        if not is_focus_editable():
            self._no_target_cue()
            return

        try:
            self.recorder.start()
        except Exception as exc:
            show_error_popup(f"Could not start recording:\n{exc}")
            return

        self._recording = True
        self._latched = False
        self._recording_id += 1
        self._record_start_time = time.time()
        self.tray.set_recording()
        pill.show(lambda: self.recorder.level)
        self._beep("start")

    def _on_release(self, key):
        if key not in config.HOTKEY and key not in config.DEV_HOTKEY:
            return
        self._hotkey_pressed.discard(key)
        self._masked = False
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

        self._stop_recording()

    def _auto_stop(self, rec_id):
        if self._recording_id != rec_id:
            return
        if self._stop_recording():
            self.tray.notify(
                f"Stopped listening after {config.TOGGLE_MAX_SECONDS // 60} minutes."
            )

    def _stop_recording(self, process=True):
        """Stop the current recording and, unless process=False, send it
        down the pipeline. Returns False if nothing was recording. Locked:
        toggle mode's auto-stop timer can race a key press."""
        with self._stop_lock:
            if not self._recording:
                return False
            self._recording = False
            self._latched = False
        self.tray.set_idle()
        pill.hide()
        self._beep("stop")
        audio = self.recorder.stop()
        duration = time.time() - self._record_start_time

        if not process or duration < config.MIN_RECORDING_SECONDS:
            return True

        with self._order:
            seq = self._next_seq
            self._next_seq += 1
        threading.Thread(
            target=self._process_audio, args=(audio, self._dev_dictation, seq), daemon=True
        ).start()
        return True

    def _process_audio(self, audio, dev=False, seq=None):
        with self._order:
            self._jobs += 1
        self._job_seq.value = seq
        try:
            self._process_audio_inner(audio, dev)
        finally:
            with self._order:
                self._jobs -= 1
                if seq is not None:
                    self._finished.add(seq)
                    while self._turn in self._finished:
                        self._finished.remove(self._turn)
                        self._turn += 1
                    self._order.notify_all()

    def _wait_for_turn(self):
        """Block until every earlier dictation has pasted (or finished
        without text). Capped, so one stuck dictation can't hold the rest
        back for ever."""
        seq = getattr(self._job_seq, "value", None)
        if seq is None:
            return
        with self._order:
            self._order.wait_for(lambda: self._turn >= seq, timeout=30)

    def _process_audio_inner(self, audio, dev=False):
        # Developer English swaps the sentence-style bias prompt for one
        # that keeps spoken symbols as literal words (see dev_mode.py).
        base_prompt = dev_mode.STT_PROMPT if dev else config.PUNCTUATION_PROMPT
        prompt = " ".join(p for p in (base_prompt, vocabulary_prompt()) if p) or None
        t0 = time.time()
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
                text = cloud_client.transcribe(
                    audio, config.SAMPLE_RATE, initial_prompt=prompt
                )
            else:
                text = transcriber.transcribe(
                    audio, config.SAMPLE_RATE, initial_prompt=prompt
                )
        except Exception as exc:
            show_error_popup(f"Transcription failed:\n{exc}")
            return
        transcribe_secs = time.time() - t0

        raw = text
        if dev:
            text, is_code = dev_mode.process(text)
            if is_code:
                # A command/code line is final after the rules pass: no
                # filler/correction/repeat rules, no grammar model, no
                # sentence period, and no personal dictionary (an expansion
                # like "AI" -> "artificial intelligence" would corrupt code).
                _debug_log(raw=raw, final=text,
                           timing=f"transcribe {transcribe_secs:.1f}s [developer: code]")
                self._insert_final(text)
                return
        # Symbol words ("underscore", "dot") first, before anything else
        # sees the text -- this fixes literal-word transcription
        # ("settings dot py") into the intended identifier
        # ("settings.py"), and doing it early means the grammar engine's
        # word-retention guard checks against the already-fused text
        # instead of expecting "dot" to survive verbatim.
        text = apply_spoken_symbols(text)
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
            t0 = time.time()
            grammar_used_local = self._grammar_uses_local()
            if grammar_used_local:
                text = grammar_engine.apply(text)
            else:
                text = cloud_client.grammar_apply(text)
            grammar_secs = time.time() - t0
            if dev:
                # The grammar model likes to wrap paths in backticks
                # ("`/api/v2/users`"); plain text is wanted here.
                text = dev_mode.strip_backticks(text)
            after_grammar = text
            text = finish_sentence(text)
        else:
            after_fillers = after_corrections = after_collapse = after_grammar = text
            grammar_secs = 0.0
            grammar_used_local = False

        text = apply_dictionary(text)
        _debug_log(
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
        self._insert_final(text)

    def _insert_final(self, text):
        if not text:
            return
        self._wait_for_turn()

        if not is_focus_editable():
            self._no_target_cue()
            return

        insert_text(text)
        self._beep("done")
        if config.ENABLE_HISTORY:
            history.add(text)
        updater.note_words(len(text.split()))
        if config.INSERT_MODE == "clipboard":
            self.tray.notify("Copied to clipboard — press Ctrl+V to paste.")

    def run(self):
        sync_autostart()
        if self._cloud_active():
            self._enter_cloud_mode()
            self._sync_grammar_source()
        else:
            self._load_model_async()
            # Separate thread: the grammar engine must never delay dictation
            # readiness; until (unless) it loads, cleaned_up mode is rules-only.
            threading.Thread(target=self._load_grammar, daemon=True).start()
        # Models load above as usual, but _on_press refuses to record until
        # this screen is answered. on_choice re-syncs everything (model
        # loading, grammar source) if the user picks something different
        # from the configured default.
        onboarding.maybe_show(on_choice=lambda mode: self._sync_processing_mode())
        # Local setup's background grammar download, if Talkative was
        # closed before it finished (see onboarding.finish_local).
        if config.GRAMMAR_PENDING_DOWNLOAD:
            grammar_engine.download_in_background()
        updater.start_background_check(self.updater_controller())
        feedback.start_background_check(
            on_reply=lambda text: self.tray.notify(
                text if len(text) <= 200 else text[:197] + "…",
                title="Sumit replied",
            )
        )
        # pynput stops the listener for good when a callback raises, which
        # silently ends dictation until a restart. Log and carry on.
        def guarded(handler):
            def call(key):
                try:
                    handler(key)
                except Exception:
                    logging.getLogger(__name__).exception("hotkey handler failed")
            return call

        self._listener = keyboard.Listener(
            on_press=guarded(self._on_press), on_release=guarded(self._on_release)
        )
        self._listener.start()
        self.tray.run_detached()

        try:
            while self._running:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass

    def quit(self):
        self._running = False
        if self._listener:
            self._listener.stop()
