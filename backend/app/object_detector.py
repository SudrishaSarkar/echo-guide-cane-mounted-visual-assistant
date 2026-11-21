"""Ultralytics YOLO wrapper restricted to EchoGuide's supported objects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
from ultralytics import YOLO

from .config import settings


@dataclass
class Detection:
    label: str
    confidence: float
    cx: float  # normalized 0-1, image coordinates
    cy: float
    x1: float
    y1: float
    x2: float
    y2: float


class ObjectDetector:
    def __init__(self, model_path: str = "yolo11n.pt") -> None:
        self.model = YOLO(model_path)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        height, width = frame.shape[:2]
        results = self.model.predict(
            frame, conf=settings.detection_confidence, verbose=False
        )[0]

        detections: List[Detection] = []
        for box in results.boxes:
            label = results.names[int(box.cls[0])]
            if label not in settings.supported_objects:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(
                Detection(
                    label=label,
                    confidence=float(box.conf[0]),
                    cx=(x1 + x2) / 2 / width,
                    cy=(y1 + y2) / 2 / height,
                    x1=x1 / width,
                    y1=y1 / height,
                    x2=x2 / width,
                    y2=y2 / height,
                )
            )
        return detections

    def best_match(self, frame: np.ndarray, label: str) -> Detection | None:
        candidates = [d for d in self.detect(frame) if d.label == label]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.confidence)
