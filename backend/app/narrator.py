"""What the webcam says on its own (no joystick needed).

Default mode "hazards" (settings.narration_mode): the webcam only speaks about
obstacles that are getting close, using the nearest hazard from hazards.py,
with a rough distance and stress words that rise with the danger:

    level 1  "Chair ahead, about 2 metres."
    level 2  "Careful! Chair ahead, 1 metre."
    level 3  "Stop! Chair right in front of you."   (interrupts anything)

Levels 1-2 wait while a joystick answer is playing (joystick = calm, safe
mode). Level 3 always speaks, even over the joystick. It never says the path
is clear: with no hazard it stays quiet.

Mode "all" keeps the older always-on narration described below.


Every ~0.2 s it reads detector.latest_detections, keeps only objects that have
been seen steadily (in at least 3 of the last 4 samples, so a one-frame
misdetection is never spoken), and builds a short sentence such as
"Person on your right. Chair ahead, close."

It speaks:
- as soon as the steady scene changes, and
- every narration_repeat_s while the scene stays the same.

Narration has the lowest priority. It waits while anything else is speaking
(joystick describe/read results, SOS, drop prompts) and pauses entirely while
the user is in a describe/read/SOS flow or a cane-drop prompt is open.
It never says the path is clear or safe, and never guesses at the light:
with nothing in view it stays quiet.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Deque, List, Optional, Tuple

from . import detector
from .audio import audio
from .config import settings
from .state import Mode, state_manager

SAMPLE_PERIOD_S = 0.15
HISTORY = 4          # samples kept (~0.6 s)
STEADY_MIN = 3       # an object must appear in this many of them

_WHERE = {"left": "on your left", "center": "ahead", "right": "on your right"}
_PLURALS = {"person": "people", "bus": "buses", "couch": "couches", "knife": "knives",
            "mouse": "mice", "sheep": "sheep", "glass": "glasses", "bench": "benches"}
_NUMBERS = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}

Item = Tuple[str, str]  # (label, side)


def _urgency(det: dict, width: int, height: int) -> float:
    # Same closeness measure hazards.py uses for the beeps.
    x1, y1, x2, y2 = det["box"]
    box_h = (y2 - y1) / height
    area = ((x2 - x1) * (y2 - y1)) / (width * height)
    return min(1.0, max(box_h * 1.2, area * 4.0))


class Narrator:
    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._history: Deque[Counter] = deque(maxlen=HISTORY)
        self._last_text = ""
        self._last_spoken_at = 0.0
        self._quiet_since = 0.0
        # hazard mode
        self._hz_candidate: Optional[tuple] = None
        self._hz_seen = 0
        self._hz_last_key: Optional[tuple] = None
        self._hz_last_at = 0.0

    def start(self) -> None:
        if not getattr(settings, "narration_enabled", True):
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # --- main loop ---
    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as exc:  # never let narration kill itself
                print(f"[narrator] {exc}")
            time.sleep(SAMPLE_PERIOD_S)

    def _tick(self) -> None:
        if getattr(settings, "narration_mode", "hazards") == "hazards":
            self._tick_hazards()
            return
        sample, close = self._sample()
        self._history.append(sample)

        now = time.monotonic()
        if audio.speaking():
            self._quiet_since = now
            return
        if now - self._quiet_since < settings.narration_gap_s:
            return
        if self._paused():
            return

        text, repeat = self._sentence(self._steady(), close), settings.narration_repeat_s
        if not text:
            self._last_text = ""
            return
        if text == self._last_text and now - self._last_spoken_at < repeat:
            return
        if audio.narrate(text):
            self._last_text = text
            self._last_spoken_at = now
            state_manager.set_instruction(text)

    # --- hazard mode ---
    HAZARD_REPEAT_S = {1: 6.0, 2: 3.5, 3: 2.0}
    HAZARD_STEADY_TICKS = 2  # ~0.3 s: ignore one-frame misdetections

    def _tick_hazards(self) -> None:
        from .hazards import hazard_monitor

        h = hazard_monitor.nearest
        now = time.monotonic()
        if not h or h.get("level", 0) <= 0:
            self._hz_candidate, self._hz_seen = None, 0
            self._hz_last_key = None  # next hazard is announced straight away
            return

        key = (h["label"], h["side"], h["level"])
        if key == self._hz_candidate:
            self._hz_seen += 1
        else:
            self._hz_candidate, self._hz_seen = key, 1
        if self._hz_seen < self.HAZARD_STEADY_TICKS:
            return

        level = h["level"]
        changed = key != self._hz_last_key
        rose = self._hz_last_key is None or level > self._hz_last_key[2]
        due = now - self._hz_last_at >= self.HAZARD_REPEAT_S.get(level, 4.0)
        if not (changed or due):
            return

        text = hazard_sentence(h["label"], h["side"], level, h.get("distance_m"))
        if level >= 3:
            # Real danger: speak now, over anything (even a joystick answer).
            audio.say(text)
            spoken = True
        else:
            if self._paused() or audio.priority_speaking():
                return  # joystick answer / SOS / prompt playing: wait
            spoken = audio.narrate(text)
        if spoken:
            self._hz_last_key = key
            self._hz_last_at = now
            state_manager.set_instruction(text)

    # --- helpers ---
    @staticmethod
    def _paused() -> bool:
        s = state_manager.state
        return (s.mode != Mode.IDLE and s.mode != Mode.SOS_ACTIVE) or bool(s.cane_drop_prompt)

    @staticmethod
    def _sample() -> Tuple[Counter, set]:
        """Counts of (label, side) in the current detections, plus which of
        them are close enough to beep."""
        from .camera import camera

        min_conf = getattr(settings, "describe_min_confidence", 0.45)
        dets = [d for d in list(detector.latest_detections) if d.get("conf", 1.0) >= min_conf]
        frame = camera.latest_frame()
        counts: Counter = Counter()
        close: set = set()
        for d in dets:
            key = (d["label"], d.get("side", "center"))
            counts[key] += 1
            if frame is not None:
                h, w = frame.shape[:2]
                if _urgency(d, w, h) >= settings.beep_single_at:
                    close.add(key)
        return counts, close

    def _steady(self) -> List[Tuple[Item, int]]:
        """Objects seen in at least STEADY_MIN of the last samples, with the
        count most often seen, ordered by how often they appeared."""
        seen: Counter = Counter()
        for sample in self._history:
            for key in sample:
                seen[key] += 1
        steady = [k for k, n in seen.items() if n >= STEADY_MIN]
        result = []
        for key in steady:
            counts = Counter(s[key] for s in self._history if key in s)
            result.append((key, counts.most_common(1)[0][0]))
        # Centre first (most relevant for walking), then left/right.
        order = {"center": 0, "left": 1, "right": 2}
        result.sort(key=lambda kc: (order.get(kc[0][1], 3), -kc[1]))
        return result[: max(1, int(settings.narration_max_objects))]

    @staticmethod
    def _sentence(items: List[Tuple[Item, int]], close: set) -> str:
        parts = []
        for (label, side), count in items:
            if count == 1:
                noun = label
            else:
                noun = f"{_NUMBERS.get(count, str(count))} {_PLURALS.get(label, label + 's')}"
            phrase = f"{noun[0].upper()}{noun[1:]} {_WHERE.get(side, '')}".strip()
            if (label, side) in close:
                phrase += ", close"
            parts.append(phrase + ".")
        return " ".join(parts)


def say_distance(distance_m: Optional[float]) -> str:
    """'about 2 metres', 'about 1.5 metres', 'about 1 metre', or ''."""
    if distance_m is None or distance_m < 0.75:
        return ""
    if distance_m < 3:
        d = round(distance_m * 2) / 2
    else:
        d = float(round(distance_m))
    num = str(int(d)) if d == int(d) else f"{d:g}"
    unit = "metre" if d == 1 else "metres"
    return f"about {num} {unit}"


def hazard_sentence(label: str, side: str, level: int, distance_m: Optional[float]) -> str:
    """Words get more urgent with the level so the user stops in time."""
    noun = label[0].upper() + label[1:]
    where = _WHERE.get(side, "ahead")
    dist = say_distance(distance_m)
    if level >= 3:
        if side == "center":
            return f"Stop! {noun} right in front of you."
        return f"Watch out! {noun} very close {where}."
    if level == 2:
        return f"Careful! {noun} {where}, {dist}." if dist else f"Careful! {noun} close {where}."
    return f"{noun} {where}, {dist}." if dist else f"{noun} {where}."


narrator = Narrator()
