import datetime
import os
import threading
import time
from pathlib import Path

from pynput import keyboard

from . import config, error_toast, feedback, grammar_engine, history, model_manager, pill, settings, try_it_now, updater
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


_TONE_RATE = 16000


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
        folder = Path(os.environ.get("LOCALAPPDATA", ".")) / "SumitSpeak"
        folder.mkdir(exist_ok=True)
        with open(folder / "debug.log", "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat(timespec="seconds") + "\n")
            for name, value in stages.items():
                f.write(f"  {name}: {value!r}\n")
    except Exception:
        pass


class SumitSpeakApp:
    def __init__(self):
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
        self._swapping = False  # model swap in progress (update install/undo)
        self._hotkey_pressed = set()  # currently-held keys that are part of config.HOTKEY
        self._chord_active = False  # chord already handled for this press-hold, ignore OS key-repeat
        self.tray = TrayApp(
            on_quit=self.quit, on_settings=self.open_settings,
            hotkey_label=friendly_key(config.HOTKEY),
        )

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
        self.tray.set_hotkey_label(friendly_key(config.HOTKEY))
        if self.transcriber is not None and not self._recording:
            self.tray.set_idle()  # refresh the tooltip with the new hotkey
        self.tray.notify("Settings saved.")

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
                self.transcriber = Transcriber(
                    config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE,
                    download_root=str(model_manager.models_dir()),
                )
                self._no_model = False
                self.tray.set_idle()
                self.tray.notify(
                    f"Ready. Hold {friendly_key(config.HOTKEY)} to dictate."
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

        self.transcriber = None
        self._no_model = True
        gc.collect()
        self.tray.set_loading("no model — open Settings, then Models")

    def updater_controller(self):
        """The narrow surface updater.py drives a model swap through.
        Synchronous on purpose: the updater thread owns the sequencing."""
        import gc

        from types import SimpleNamespace

        def unload_speech():
            self.transcriber = None
            gc.collect()  # release the model.bin mapping so files can move

        def reload_speech():
            try:
                self.transcriber = Transcriber(
                    config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE,
                    download_root=str(model_manager.models_dir()),
                )
            except Exception as exc:
                show_error_popup(f"Failed to load speech model:\n{exc}")

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
            begin_swap=begin_swap,
            end_swap=end_swap,
        )

    def _on_press(self, key):
        if key not in config.HOTKEY:
            return
        self._hotkey_pressed.add(key)
        if self._hotkey_pressed != set(config.HOTKEY):
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
        if self._recording:
            return

        if self._swapping:
            self.tray.notify("Updating — ready in a moment.")
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
        self._record_start_time = time.time()
        self.tray.set_recording()
        pill.show(lambda: self.recorder.level)
        self._beep("start")

    def _on_release(self, key):
        if key not in config.HOTKEY:
            return
        self._hotkey_pressed.discard(key)
        self._chord_active = False
        if not self._recording:
            return

        self._recording = False
        self.tray.set_idle()
        pill.hide()
        self._beep("stop")
        audio = self.recorder.stop()
        duration = time.time() - self._record_start_time

        if duration < config.MIN_RECORDING_SECONDS:
            return

        threading.Thread(target=self._process_audio, args=(audio,), daemon=True).start()

    def _process_audio(self, audio):
        self._jobs += 1
        try:
            self._process_audio_inner(audio)
        finally:
            self._jobs -= 1

    def _process_audio_inner(self, audio):
        prompt = " ".join(
            p for p in (config.PUNCTUATION_PROMPT, vocabulary_prompt()) if p
        ) or None
        t0 = time.time()
        try:
            text = self.transcriber.transcribe(
                audio, config.SAMPLE_RATE, initial_prompt=prompt
            )
        except Exception as exc:
            show_error_popup(f"Transcription failed:\n{exc}")
            return
        transcribe_secs = time.time() - t0

        raw = text
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
            text = grammar_engine.apply(text)
            grammar_secs = time.time() - t0
            after_grammar = text
            text = finish_sentence(text)
        else:
            after_fillers = after_corrections = after_collapse = after_grammar = text
            grammar_secs = 0.0

        text = apply_dictionary(text)
        _debug_log(
            raw=raw,
            fillers=after_fillers,
            corrections=after_corrections,
            collapse=after_collapse,
            grammar=after_grammar,
            final=text,
            timing=f"transcribe {transcribe_secs:.1f}s, grammar {grammar_secs:.1f}s"
            + (f" [{config.GRAMMAR_MODEL_DIR}]" if grammar_secs else ""),
        )

        if not text:
            return

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
        self._load_model_async()
        # Separate thread: the grammar engine must never delay dictation
        # readiness; until (unless) it loads, cleaned_up mode is rules-only.
        threading.Thread(target=grammar_engine.load, daemon=True).start()
        updater.start_background_check(self.updater_controller())
        feedback.start_background_check(
            on_reply=lambda text: self.tray.notify(
                text if len(text) <= 200 else text[:197] + "…",
                title="Sumit replied",
            )
        )
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
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
