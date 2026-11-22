"""Approaching-object hazard detection from detector.latest_detections.

Vision gives *closeness cues*, never distances — we never say a path is
clear or safe. An object counts as a hazard for a side when:

- "close": box height >= hazard_close_box_height_frac of frame height, OR
  its bottom edge sits in the lowest hazard_close_bottom_frac AND its area
  >= hazard_close_min_area_frac; or
- "approaching": its box area grew over ~hazard_approach_window_s.

Only obstacle-type classes (settings.obstacle_classes) at or above
describe_min_confidence count, so weak guesses don't beep.

Beeping works like a parking sensor, driven by the closeness (0..1) of the
nearest obstacle: silence, then single beeps, double beeps, and a continuous
tone as it gets closer (settings.beep_*_at). Beeps pan to the obstacle's side
and never interrupt speech; narrator.py does the talking. Publishes `hazards`
+ `warning*` in the session state for the dashboard.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from . import detector
from .audio import audio
from .config import settings
from .state import state_manager


# Typical real heights (metres) for distance estimates from box height.
TYPICAL_HEIGHT_M = {
    "person": 1.7, "chair": 0.9, "couch": 0.85, "bench": 0.8, "dining table": 0.75,
    "bed": 0.6, "bicycle": 1.0, "motorcycle": 1.1, "car": 1.5, "truck": 3.0, "bus": 3.0,
    "dog": 0.55, "cat": 0.3, "suitcase": 0.65, "backpack": 0.5, "handbag": 0.3,
    "potted plant": 0.6, "vase": 0.3, "bottle": 0.25, "cup": 0.12, "bowl": 0.08,
    "laptop": 0.25, "tv": 0.6, "fire hydrant": 0.8, "stop sign": 0.75, "toilet": 0.75,
    "refrigerator": 1.7, "parking meter": 1.3,
}


def estimate_distance_m(det: dict, frame_h: int) -> Optional[float]:
    """Rough distance from the camera (pinhole model): real height x focal
    length / box height. None when the object type is unknown or the box is
    cut off at the top/bottom edge (the visible part is then too short and the
    estimate would come out too far, which is the unsafe direction)."""
    real = TYPICAL_HEIGHT_M.get(det["label"])
    x1, y1, x2, y2 = det["box"]
    box_h = y2 - y1
    if real is None or box_h <= 1:
        return None
    edge = 0.02 * frame_h
    if y1 <= edge or y2 >= frame_h - edge:
        return None
    focal = (frame_h / 2) / math.tan(math.radians(settings.camera_vfov_deg) / 2)
    return real * focal / box_h


def _box_metrics(det: dict, width: int, height: int) -> dict:
    x1, y1, x2, y2 = det["box"]
    box_h = (y2 - y1) / height
    box_area = ((x2 - x1) * (y2 - y1)) / (width * height)
    bottom_frac = y2 / height
    return {"box_h": box_h, "area": box_area, "bottom": bottom_frac}


class HazardMonitor:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # Per side: last alert time, area history for approach detection.
        self._last_alert: Dict[str, float] = defaultdict(float)
        self._area_history: Dict[str, List[tuple[float, float]]] = defaultdict(list)
        self._active: Dict[str, dict] = {}
        self._beep_lock = threading.Lock()
        self._beep_level = 0       # 0 silence, 1 single, 2 double, 3 continuous
        self._beep_side = "center"
        self._beep_thread: Optional[threading.Thread] = None
        self.nearest: Optional[dict] = None  # read by narrator.py
        # Recent raw levels (one per poll) so one-frame detections don't beep.
        self._level_history: List[int] = []

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._beep_thread = threading.Thread(target=self._beep_loop, daemon=True)
        self._beep_thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        period = 1.0 / max(1.0, settings.hazard_poll_hz)
        while self._running:
            self._update()
            time.sleep(period)

    def _update(self) -> None:
        min_conf = getattr(settings, "describe_min_confidence", 0.45)
        detections = [d for d in detector.latest_detections
                      if d["label"] in settings.obstacle_classes
                      and d.get("conf", 1.0) >= min_conf]
        # Need frame size for fractions — infer from max box coords is wrong;
        # boxes are px, so use the annotated frame shape via camera.
        from .camera import camera
        frame = camera.latest_frame()
        if frame is None:
            return
        height, width = frame.shape[:2]

        now = time.monotonic()
        hazards: List[dict] = []
        nearest: Optional[dict] = None

        for side in ("left", "center", "right"):
            side_dets = [d for d in detections if d["side"] == side]
            if not side_dets:
                self._area_history[side].clear()
                self._active.pop(side, None)
                continue

            # Strongest candidate on this side = largest box area.
            best = max(side_dets, key=lambda d: _box_metrics(d, width, height)["area"])
            m = _box_metrics(best, width, height)
            area = m["area"]

            is_close = (
                m["box_h"] >= settings.hazard_close_box_height_frac
                or (m["bottom"] >= 1.0 - settings.hazard_close_bottom_frac
                    and area >= settings.hazard_close_min_area_frac)
            )

            # Approaching: area grew over the window.
            hist = self._area_history[side]
            hist.append((now, area))
            cutoff = now - settings.hazard_approach_window_s
            hist[:] = [(t, a) for t, a in hist if t >= cutoff]
            approaching = False
            if len(hist) >= 2 and hist[0][1] > 0:
                growth = (area - hist[0][1]) / hist[0][1]
                approaching = growth >= 0.25 and area >= 0.02

            urgency = min(1.0, max(m["box_h"] * 1.2, area * 4.0))
            distance = estimate_distance_m(best, height)
            level = max(self._level_for(urgency), self._level_for_distance(distance))
            hazard = {
                "label": best["label"],
                "side": side,
                "closeness": round(min(1.0, m["box_h"] * 1.5), 2),
                "approaching": approaching,
                "distance_m": round(distance, 1) if distance is not None else None,
                "level": level,
            }
            if is_close or approaching or level > 0:
                hazards.append(hazard)

            # Nearest = highest level; ties go to the centre (in your path),
            # then the shorter distance.
            rank = (level, side == "center", -(distance if distance is not None else 99.0))
            if level > 0 and (nearest is None or rank > nearest["_rank"]):
                nearest = dict(hazard, _rank=rank)
            self._active[side] = hazard

        raw_level = nearest["level"] if nearest else 0
        level = self._steady_level(raw_level)
        if nearest is not None and level != nearest["level"]:
            nearest = dict(nearest, level=level) if level > 0 else None
        with self._beep_lock:
            raised = level > self._beep_level
            self._beep_level = level
            self._beep_side = nearest["side"] if nearest else "center"
            self.nearest = ({k: v for k, v in nearest.items() if k != "_rank"}
                            if nearest else None)
        warned = raised and level > 0

        state_manager.update(
            hazards=hazards,
            warning=self._warning_text(hazards) if hazards else "",
            warning_id=state_manager.state.warning_id + 1 if warned else state_manager.state.warning_id,
            warning_side=(hazards[0]["side"] if hazards else None),
            warning_urgent=bool(hazards and hazards[0]["closeness"] > 0.6),
        )

    @staticmethod
    def _warning_text(hazards: List[dict]) -> str:
        h = hazards[0]
        where = {"left": "on your left", "center": "ahead", "right": "on your right"}[h["side"]]
        return f"{h['label'].capitalize()} {where}"

    STEADY_WINDOW = 5  # polls (~0.5 s at 10 Hz)
    STEADY_MIN = 3     # a level must show up in this many of them

    def _steady_level(self, raw_level: int) -> int:
        """Highest level seen in at least STEADY_MIN of the last STEADY_WINDOW
        polls: a hazard has to last ~0.3 s before it beeps, and a one-frame
        dropout doesn't silence a real one."""
        hist = self._level_history
        hist.append(raw_level)
        del hist[:-self.STEADY_WINDOW]
        for level in (3, 2, 1):
            if sum(1 for v in hist if v >= level) >= self.STEADY_MIN:
                return level
        return 0

    @staticmethod
    def _level_for_distance(distance: Optional[float]) -> int:
        if distance is None:
            return 0
        if distance <= settings.beep_continuous_m:
            return 3
        if distance <= settings.beep_double_m:
            return 2
        if distance <= settings.beep_single_m:
            return 1
        return 0

    @staticmethod
    def _joystick_busy() -> bool:
        """The user asked something with the joystick and the answer is being
        worked out or spoken. Joystick use is the 'safe' mode: no beeps."""
        from .state import Mode
        mode = state_manager.state.mode
        return mode in (Mode.DESCRIBING, Mode.READING) or audio.priority_speaking()

    @staticmethod
    def _level_for(urgency: float) -> int:
        if urgency >= settings.beep_continuous_at:
            return 3
        if urgency >= settings.beep_double_at:
            return 2
        if urgency >= settings.beep_single_at:
            return 1
        return 0

    def _beep_loop(self) -> None:
        """Plays the current proximity pattern. Gaps shrink as the level
        rises; level 3 plays tone slices back-to-back (continuous)."""
        gaps = {1: 0.9, 2: 0.6, 3: 0.0}
        while self._running:
            with self._beep_lock:
                level, side = self._beep_level, self._beep_side
            # Joystick answers play without beeps; only "very close" (3)
            # still beeps, because that is a real danger.
            if level < 3 and self._joystick_busy():
                level = 0
            if level == 0:
                time.sleep(0.05)
                continue
            length = audio.proximity(level, side)
            # Sleep in small steps so a level change takes effect quickly.
            end = time.monotonic() + length + gaps[level]
            while self._running and time.monotonic() < end:
                with self._beep_lock:
                    if self._beep_level != level and time.monotonic() >= end - gaps[level]:
                        break
                time.sleep(0.02)


hazard_monitor = HazardMonitor()
