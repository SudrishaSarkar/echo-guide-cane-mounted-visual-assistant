"""Approaching-object hazard detection from detector.latest_detections.

Vision gives *closeness cues*, never distances — we never say a path is
clear or safe. An object counts as a hazard for a side when:

- "close": box height >= hazard_close_box_height_frac of frame height, OR
  its bottom edge sits in the lowest hazard_close_bottom_frac AND its area
  >= hazard_close_min_area_frac; or
- "approaching": its box area grew over ~hazard_approach_window_s.

Only obstacle-type classes (settings.obstacle_classes) count. Each side has
its own cooldown so alerts don't beep nonstop. Fires audio.warn() and
publishes `hazards` + `warning*` in the session state.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from . import detector
from .audio import audio
from .config import settings
from .state import state_manager


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

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        period = 1.0 / max(1.0, settings.hazard_poll_hz)
        while self._running:
            self._update()
            time.sleep(period)

    def _update(self) -> None:
        detections = [d for d in detector.latest_detections
                      if d["label"] in settings.obstacle_classes]
        # Need frame size for fractions — infer from max box coords is wrong;
        # boxes are px, so use the annotated frame shape via camera.
        from .camera import camera
        frame = camera.latest_frame()
        if frame is None:
            return
        height, width = frame.shape[:2]

        now = time.monotonic()
        hazards: List[dict] = []
        warned = False

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
            hazard = {
                "label": best["label"],
                "side": side,
                "closeness": round(min(1.0, m["box_h"] * 1.5), 2),
                "approaching": approaching,
            }
            if is_close or approaching:
                hazards.append(hazard)

            # Alert with per-side cooldown.
            due = now - self._last_alert[side] >= settings.hazard_cooldown_s
            if (is_close or approaching) and due:
                self._last_alert[side] = now
                audio.warn(side, urgency)
                self._announce(side, best["label"], urgency)
                warned = True
            self._active[side] = hazard

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

    @staticmethod
    def _announce(side: str, label: str, urgency: float) -> None:
        where = {"left": "on your left", "center": "ahead", "right": "on your right"}[side]
        prefix = "Close" if urgency > 0.6 else "Object"
        audio.say(f"{prefix} {where}: {label}")
        state_manager.set_instruction(f"{prefix} {where}: {label}")


hazard_monitor = HazardMonitor()
