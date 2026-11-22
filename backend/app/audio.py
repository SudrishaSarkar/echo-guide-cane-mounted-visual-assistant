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

    @staticmethod
    def _render_sequence(beeps: list, gap: float = 0.06) -> np.ndarray:
        """beeps: [(freq, seconds, pan), ...] -> one buffer with gaps."""
        parts = []
        gap_samples = int(_SAMPLE_RATE * gap)
        silence = np.zeros((gap_samples, 2), dtype=np.int16)
        for i, (freq, seconds, pan) in enumerate(beeps):
            if i:
                parts.append(silence)
            parts.append(_TonePlayer._render(freq, seconds, pan))
        return np.concatenate(parts, axis=0) if parts else np.zeros((1, 2), dtype=np.int16)

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

    def play_sequence(self, beeps: list) -> None:
        """beeps: [(freq, seconds, pan), ...] played back-to-back with gaps."""
        if not self._ok or not beeps:
            return
        try:
            sound = self._sndarray.make_sound(self._render_sequence(beeps))
            sound.play()
            self._sounds.append(sound)
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
    """Speech on one worker thread. Newest message wins; nothing is queued.

    Two priorities:
    - say(): important speech (joystick results, SOS, prompts). Cuts off
      whatever is playing, including narration.
    - narrate(): background scene narration. Only plays when nothing else is
      speaking or waiting, and never cuts anything off.

    On Windows this drives SAPI directly. pyttsx3 goes silent after its first
    runAndWait() on Windows, so it is only the fallback on other systems.
    """

    _ASYNC, _PURGE = 1, 2

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self._pending: Optional[str] = None
        self._pending_narration = False
        self._cond = threading.Condition()
        self._speaking = False
        self._narrating = False
        if enabled:
            threading.Thread(target=self._run, daemon=True).start()

    # --- public API ---
    def say(self, text: str) -> None:
        if self._enabled and text:
            self._push(text, narration=False)

    def narrate(self, text: str) -> bool:
        """Speak only if idle. Returns True if the text was accepted."""
        if not self._enabled or not text:
            return False
        with self._cond:
            if self._speaking or self._pending is not None:
                return False
        self._push(text, narration=True)
        return True

    def busy(self) -> bool:
        with self._cond:
            return self._speaking or self._pending is not None

    def interrupt(self) -> None:
        if self._enabled:
            self._push("", narration=False)

    # --- worker ---
    def _push(self, text: str, narration: bool) -> None:
        with self._cond:
            self._pending = text
            self._pending_narration = narration
            self._cond.notify()

    def _take(self, timeout: Optional[float]) -> Optional[tuple]:
        with self._cond:
            if self._pending is None:
                self._cond.wait(timeout)
            if self._pending is None:
                return None
            item = (self._pending, self._pending_narration)
            self._pending = None
            self._speaking = bool(item[0])
            self._narrating = item[1]
            return item

    def _done(self) -> None:
        with self._cond:
            self._speaking = False
            self._narrating = False

    def _run(self) -> None:
        import sys
        if sys.platform == "win32":
            try:
                self._run_sapi()
                return
            except Exception as exc:
                print(f"[audio] SAPI unavailable ({exc}); falling back to pyttsx3")
        self._run_pyttsx3()

    def _run_sapi(self) -> None:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        voice.Rate = int(getattr(settings, "speech_rate", 1))
        item = None
        while True:
            if item is None:
                item = self._take(None)
                if item is None:
                    continue
            text, _ = item
            item = None
            # Purge-before-speak: stops anything still playing.
            voice.Speak(text, self._ASYNC | self._PURGE)
            if not text:
                self._done()
                continue
            while not voice.WaitUntilDone(50):
                with self._cond:
                    newer = self._pending is not None
                if newer:
                    break  # newest message wins; it purges this one
            if newer:
                item = self._take(0)
                continue
            self._done()

    def _run_pyttsx3(self) -> None:
        try:
            import pyttsx3
        except Exception as exc:
            print(f"[audio] TTS unavailable: {exc}")
            self._enabled = False
            return
        while True:
            item = self._take(None)
            if item is None:
                continue
            text, _ = item
            if text:
                try:
                    # A fresh engine per sentence avoids the one-shot bug.
                    engine = pyttsx3.init()
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                except Exception as exc:
                    print(f"[audio] speech failed: {exc}")
            self._done()


class AudioOut:
    def __init__(self) -> None:
        self._tones = _TonePlayer()
        self._speaker = _Speaker(settings.tts_enabled)
        self._warn_lock = threading.Lock()

    # --- proximity beeps (hazards.py) ---
    # level 1 = single beep, 2 = double beep, 3 = one slice of the continuous
    # tone (hazards.py calls it back-to-back). Beeps never interrupt speech.
    def proximity(self, level: int, side: str) -> float:
        """Plays one beep group; returns how long it lasts in seconds."""
        pan = {"left": -0.8, "center": 0.0, "right": 0.8}.get(side, 0.0)
        with self._warn_lock:
            if level == 1:
                beeps = [(660.0, 0.10, pan)]
            elif level == 2:
                beeps = [(770.0, 0.09, pan), (770.0, 0.09, pan)]
            elif level >= 3:
                beeps = [(880.0, 0.25, pan)]
            else:
                return 0.0
            self._tones.play_sequence(beeps)
        return sum(b[1] for b in beeps) + 0.06 * (len(beeps) - 1)

    def warn(self, side: str, urgency: float) -> None:
        """Legacy one-shot warning (no speech interrupt)."""
        urgency = max(0.0, min(1.0, urgency))
        self.proximity(1 if urgency < 0.35 else 2 if urgency < 0.7 else 3, side)

    def say(self, text: str) -> None:
        """Important speech: cuts off narration and older messages."""
        self._speaker.say(text)

    def narrate(self, text: str) -> bool:
        """Background narration: only plays when nothing else is speaking."""
        return self._speaker.narrate(text)

    def speaking(self) -> bool:
        return self._speaker.busy()

    def chime(self, kind: str) -> None:
        self._tones.pattern(kind)

    def close(self) -> None:
        self._tones.close()


audio = AudioOut()
