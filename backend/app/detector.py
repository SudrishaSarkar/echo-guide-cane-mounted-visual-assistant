"""Continuous YOLO detection on the latest camera frame.

Runs in its own thread at ~settings.detector_fps and publishes
`latest_detections` for everyone (hazards.py, P2's describer/reader):

    [{"label": str, "conf": float, "box": (x1,y1,x2,y2) px,
      "side": "left"|"center"|"right"}]

Also draws boxes on the frame and hands it to camera.set_annotated() so the
/video MJPEG stream shows detections.
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional

import cv2
import numpy as np

from .camera import camera
from .config import settings

# Shared, read by hazards.py / P2 modules without importing the detector.
latest_detections: List[dict] = []


def _side(cx: float, width: int) -> str:
    frac = cx / max(1, width)
    if frac < 1 / 3:
        return "left"
    if frac < 2 / 3:
        return "center"
    return "right"


def _person_plausible(det: dict, frame_height: int) -> bool:
    """Head-to-chest proxy: the box must be tall enough and portrait-shaped.
    Filters out cards/hands that YOLO mislabels as 'person'."""
    x1, y1, x2, y2 = det["box"]
    h, w = y2 - y1, x2 - x1
    if h <= 0 or w <= 0:
        return False
    if h / frame_height < settings.person_min_height_frac:
        return False
    return h / w >= settings.person_min_aspect


class Detector:
    def __init__(self, model_path: str = "") -> None:
        from ultralytics import YOLO  # lazy: backend must boot without it

        self.model = YOLO(model_path or settings.detector_model)
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        global latest_detections
        period = 1.0 / max(0.5, settings.detector_fps)
        while self._running:
            t0 = time.monotonic()
            frame = camera.latest_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            height, width = frame.shape[:2]
            results = self.model.predict(
                frame,
                conf=settings.detection_confidence,
                imgsz=settings.detector_imgsz,
                verbose=False,
            )[0]

            detections: List[dict] = []
            annotated = frame.copy()
            for box in results.boxes:
                label = results.names[int(box.cls[0])]
                conf = float(box.conf[0])
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                det = {"label": label, "conf": conf, "box": (x1, y1, x2, y2)}
                if label == "person" and not _person_plausible(det, height):
                    continue
                side = _side((x1 + x2) / 2, width)
                det["side"] = side
                detections.append(det)
                color = {"left": (255, 80, 80), "center": (80, 200, 80), "right": (80, 120, 255)}[side]
                cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                cv2.putText(
                    annotated, f"{label} {conf:.2f}", (int(x1), max(14, int(y1) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                )

            latest_detections = detections
            camera.set_annotated(annotated)

            elapsed = time.monotonic() - t0
            if elapsed < period:
                time.sleep(period - elapsed)
