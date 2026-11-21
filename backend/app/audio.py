"""All user-facing audio: stereo warning beeps, spoken text, and chimes.

- warn(side, urgency): short stereo-panned beep; rate/pitch rise with urgency
  (0..1) and it interrupts any speech in progress.
- say(text): pyttsx3 speech on a dedicated thread; only the latest message
  is kept — pending speech is replaced, never queued.
- chime(kind): "sos" | "ok" | "error" beep patterns.

Only P1 modules call this; P2/P3 go through these functions too (contract
section 7). Safe to call from any thread.
"""
from __future__ import annotations

import queue
import threading
from typing import Optional

import numpy as np

from .config import settings

_SAMPLE_RATE = 44100
_BEEP_SECONDS = 0.15


class _TonePlayer:
    """Plays generated stereo PCM buffers through Pygame (non-blocking)."""

    def __init__(self) -> None:
        self._sounds = []
        try:
            import pygame
            from pygame import sndarray

            pygame.mixer.pre_init(_SAMPLE_RATE, -16, 2, 512)
            pygame.mixer.init()
            sndarray.use("numpy")
            self._pygame = pygame
            self._sndarray = sndarray
            self._ok = True
        except Exception as exc:
            print(f"[audio] tone output unavailable: {exc}")
            self._ok = False

    @staticmethod
    def _render(freq: float, seconds: float, pan: float) -> np.ndarray:
        """pan: -1.0 (left) .. 0.0 (centre) .. +1.0 (right)."""
        t = np.arange(int(_SAMPLE_RATE * seconds)) / _SAMPLE_RATE
        env = np.minimum(1.0, np.minimum(t, seconds - t) * 60)
        wave = (np.sin(2 * np.pi * freq * t) * env * 0.5 * 32767).astype(np.int16)
        left_gain = max(0.0, 1.0 - max(0.0, pan))
        right_gain = max(0.0, 1.0 + min(0.0, pan))
        left = (wave * left_gain).astype(np.int16)
        right = (wave * right_gain).astype(np.int16)
        return np.stack([left, right], axis=1)

    def play(self, freq: float, seconds: float = _BEEP_SECONDS, pan: float = 0.0) -> None:
        if not self._ok:
            return
        try:
            sound = self._sndarray.make_sound(self._render(freq, seconds, pan))
            sound.play()
            self._sounds.append(sound)  # keep ref until played out
            if len(self._sounds) > 32:
                self._sounds = self._sounds[-16:]
        except Exception:
            pass

    def pattern(self, kind: str) -> None:
        """Blocking pattern player on a daemon thread."""
        def _run() -> None:
            import time

            if kind == "sos":
                for _ in range(3):
                    self.play(660.0, 0.35, 0.0)
                    time.sleep(0.45)
            elif kind == "ok":
                self.play(880.0, 0.12, 0.0)
            elif kind == "error":
                self.play(220.0, 0.12, 0.0)
                time.sleep(0.18)
                self.play(220.0, 0.12, 0.0)
            else:  # "find" handled by firmware buzzer; fallback double beep
                self.play(1046.0, 0.1, 0.0)
                time.sleep(0.15)
                self.play(1046.0, 0.1, 0.0)

        threading.Thread(target=_run, daemon=True).start()

    def close(self) -> None:
        try:
            self._pygame.mixer.quit()
        except Exception:
            pass


class _Speaker:
    """pyttsx3 speech on one worker thread; latest message wins."""

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self._latest: queue.Queue[str] = queue.Queue(maxsize=1)
        self._engine = None
        self._ready = threading.Event()
        if enabled:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 170)
        except Exception as exc:
            print(f"[audio] TTS unavailable: {exc}")
            self._enabled = False
        self._ready.set()
        while True:
            try:
                item = self._latest.get(timeout=0.5)
            except queue.Empty:
                continue
            if item == "__STOP__":
                # Warning interrupt: drop pending speech and stop current.
                while True:
                    try:
                        self._latest.get_nowait()
                    except queue.Empty:
                        break
                if self._engine is not None:
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                continue
            while True:  # drain to latest only
                try:
                    nxt = self._latest.get_nowait()
                    if nxt == "__STOP__":
                        item = "__STOP__"
                        break
                    item = nxt
                except queue.Empty:
                    break
            if item == "__STOP__":
                if self._engine is not None:
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                continue
            if self._engine is not None:
                try:
                    self._engine.stop()
                    self._engine.say(item)
                    self._engine.runAndWait()
                except Exception:
                    pass

    def say(self, text: str) -> None:
        if not self._enabled or not text:
            return
        self._push(text)

    def interrupt(self) -> None:
        if self._enabled:
            self._push("__STOP__")

    def _push(self, item: str) -> None:
        try:
            self._latest.get_nowait()  # drop pending, newest wins
        except queue.Empty:
            pass
        try:
            self._latest.put_nowait(item)
        except queue.Full:
            pass


class AudioOut:
    def __init__(self) -> None:
        self._tones = _TonePlayer()
        self._speaker = _Speaker(settings.tts_enabled)
        self._warn_lock = threading.Lock()

    # --- warnings: rate 2..6 Hz and pitch 500..1400 Hz scale with urgency ---
    def warn(self, side: str, urgency: float) -> None:
        urgency = max(0.0, min(1.0, urgency))
        freq = 500.0 + urgency * 900.0
        seconds = 0.08 + urgency * 0.12
        pan = {"left": -0.8, "center": 0.0, "right": 0.8}.get(side, 0.0)
        # Interrupt speech while an alert sounds.
        self._speaker.interrupt()
        with self._warn_lock:
            self._tones.play(freq, seconds, pan)

    def say(self, text: str) -> None:
        self._speaker.say(text)

    def chime(self, kind: str) -> None:
        self._tones.pattern(kind)

    def close(self) -> None:
        self._tones.close()


audio = AudioOut()
