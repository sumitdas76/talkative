import datetime
import os
import threading
import time
from pathlib import Path

from pynput import keyboard

from . import config
from .audio_recorder import AudioRecorder
from .autostart import sync_autostart
from .cleanup import collapse_repeats, remove_fillers
from .dictionary import apply_dictionary, vocabulary_prompt
from .focus_check import is_focus_editable
from .self_correction import apply_self_corrections
from .settings import load_into_config as load_settings
from .text_inserter import insert_text
from .transcriber import Transcriber
from .tray import TrayApp, show_error_popup

NO_TARGET_MESSAGE = (
    "No editable text field is focused.\n\n"
    "Click into a text box, document, or address bar first, then hold "
    "Right Ctrl to dictate."
)


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
        load_settings()
        self.recorder = AudioRecorder(
            sample_rate=config.SAMPLE_RATE, device=config.INPUT_DEVICE
        )
        self.transcriber = None
        self._recording = False
        self._record_start_time = None
        self._running = True
        self._listener = None
        self.tray = TrayApp(on_quit=self.quit, on_settings=self.open_settings)

    def open_settings(self):
        from .settings_window import open_settings

        open_settings(on_applied=self._apply_settings)

    def _apply_settings(self):
        sync_autostart()
        self.recorder.device = config.INPUT_DEVICE
        self.tray.notify("Settings saved.")

    def _beep(self, start):
        if not config.PLAY_SOUNDS:
            return

        def _play():
            try:
                import winsound

                winsound.Beep(880 if start else 440, 70)
            except Exception:
                pass

        threading.Thread(target=_play, daemon=True).start()

    def _load_model_async(self):
        def _load():
            try:
                self.transcriber = Transcriber(
                    config.MODEL_SIZE, config.DEVICE, config.COMPUTE_TYPE
                )
                self.tray.set_idle()
                self.tray.notify("Ready. Hold Right Ctrl to dictate.")
            except Exception as exc:
                show_error_popup(f"Failed to load speech model:\n{exc}")

        threading.Thread(target=_load, daemon=True).start()

    def _on_press(self, key):
        if key != config.HOTKEY or self._recording:
            return

        if self.transcriber is None:
            self.tray.notify("Still loading the speech model, please wait...")
            return

        if not is_focus_editable():
            show_error_popup(NO_TARGET_MESSAGE)
            return

        try:
            self.recorder.start()
        except Exception as exc:
            show_error_popup(f"Could not start recording:\n{exc}")
            return

        self._recording = True
        self._record_start_time = time.time()
        self.tray.set_recording()
        self._beep(start=True)

    def _on_release(self, key):
        if key != config.HOTKEY or not self._recording:
            return

        self._recording = False
        self.tray.set_idle()
        self._beep(start=False)
        audio = self.recorder.stop()
        duration = time.time() - self._record_start_time

        if duration < config.MIN_RECORDING_SECONDS:
            return

        threading.Thread(target=self._process_audio, args=(audio,), daemon=True).start()

    def _process_audio(self, audio):
        try:
            text = self.transcriber.transcribe(
                audio, config.SAMPLE_RATE, initial_prompt=vocabulary_prompt()
            )
        except Exception as exc:
            show_error_popup(f"Transcription failed:\n{exc}")
            return

        raw = text
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
        else:
            after_fillers = after_corrections = after_collapse = text

        text = apply_dictionary(text)
        _debug_log(
            raw=raw,
            fillers=after_fillers,
            corrections=after_corrections,
            collapse=after_collapse,
            final=text,
        )

        if not text:
            return

        if not is_focus_editable():
            show_error_popup(NO_TARGET_MESSAGE)
            return

        insert_text(text)
        if config.INSERT_MODE == "clipboard":
            self.tray.notify("Copied to clipboard — press Ctrl+V to paste.")

    def run(self):
        sync_autostart()
        self._load_model_async()
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
