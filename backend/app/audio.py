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
    # Buzzer is mono: no stereo pan, so direction is encoded as pitch band and
    # urgency as beep count instead of the laptop's pan+pitch scheme.
    _BUZZER_SIDE_FREQ = {"left": 620.0, "center": 880.0, "right": 1240.0}

    def __init__(self) -> None:
        self._tones = _TonePlayer()
        self._speaker = _Speaker(settings.tts_enabled)
        self._warn_lock = threading.Lock()
        self._output = settings.audio_output  # "laptop" | "buzzer" | "both"

    def _send_buzzer(self, cmd: dict) -> None:
        try:
            from .serial_reader import serial_reader
            serial_reader.send(cmd)
        except Exception:
            pass

    # --- 3-level urgency beeps ---
    # urgency 0..1 (from box size/area, ~closeness). Levels:
    #   L1 <0.35  : single low beep
    #   L2 0.35-0.7: double beep, mid pitch
    #   L3 >0.7   : rapid triple beep, high pitch (imminent)
    def warn(self, side: str, urgency: float) -> None:
        urgency = max(0.0, min(1.0, urgency))
        pan = {"left": -0.8, "center": 0.0, "right": 0.8}.get(side, 0.0)
        # Interrupt speech while an alert sounds.
        self._speaker.interrupt()
        with self._warn_lock:
            count = 1 if urgency < 0.35 else 2 if urgency < 0.7 else 3
            if self._output in ("buzzer", "both"):
                freq = int(self._BUZZER_SIDE_FREQ.get(side, 880.0))
                self._send_buzzer({"cmd": "beep", "freq": freq,
                                   "count": count, "dur": 120, "gap": 70})
            if self._output == "buzzer":
                return
            if urgency < 0.35:
                beeps = [(440.0, 0.09, pan)]
            elif urgency < 0.7:
                beeps = [(660.0, 0.09, pan), (660.0, 0.09, pan)]
            else:
                beeps = [(880.0, 0.12, pan), (880.0, 0.12, pan), (880.0, 0.12, pan)]
            self._tones.play_sequence(beeps)

    def say(self, text: str) -> None:
        # A buzzer cannot reproduce speech — voice always comes from laptop TTS
        # until real speaker hardware (e.g. UNO Q audio out / MP3 module) exists.
        self._speaker.say(text)

    def chime(self, kind: str) -> None:
        if self._output in ("buzzer", "both"):
            self._send_buzzer({"cmd": "beep", "pattern": kind})
        if self._output == "buzzer":
            return
        self._tones.pattern(kind)

    def close(self) -> None:
        self._tones.close()


audio = AudioOut()
