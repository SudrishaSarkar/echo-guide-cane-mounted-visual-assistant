"""P2: short spoken scene description from detector.latest_detections (no extra capture).

Up to three detected objects, largest first, with their position:
"A chair in the centre, a person on the left." Focus "left"/"right" only
describes that third of the frame. Runs only when asked, never continuously.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional

from .config import settings
from .state import state_manager

MAX_OBJECTS = 3
DARK_LIGHT_THRESHOLD = 150  # raw light sensor (0-1023); tune on site

_SIDE_PHRASES = {"left": "on the left", "center": "in the centre", "right": "on the right"}
_IRREGULAR_PLURALS = {"person": "people", "bus": "buses", "couch": "couches", "glass": "glasses",
                      "knife": "knives", "mouse": "mice", "sheep": "sheep", "skis": "skis"}
_NUMBER_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}


def describe(focus: str = "all", detections: Optional[List[dict]] = None,
             light: Optional[float] = None) -> str:
    if light is None:
        light = state_manager.state.light
    if light is not None and light < getattr(settings, "describe_min_light", DARK_LIGHT_THRESHOLD):
        return "Too dark to describe."

    if detections is None:
        from . import detector
        detections = list(detector.latest_detections)

    if focus in ("left", "right"):
        detections = [d for d in detections if d.get("side") == focus]
    if not detections:
        if focus in ("left", "right"):
            return f"I don't see anything I recognise on the {focus}."
        return "I don't see any objects I recognise."

    detections = sorted(detections, key=_area, reverse=True)
    groups: "OrderedDict[tuple, int]" = OrderedDict()
    for det in detections:
        key = (det["label"], det.get("side", "center"))
        groups[key] = groups.get(key, 0) + 1

    phrases = [_phrase(label, side, count, focus)
               for (label, side), count in list(groups.items())[:MAX_OBJECTS]]
    sentence = ", ".join(phrases)
    return sentence[0].upper() + sentence[1:] + "."


def _area(det: dict) -> float:
    x1, y1, x2, y2 = det["box"]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _phrase(label: str, side: str, count: int, focus: str) -> str:
    if count == 1:
        article = "an" if label[0] in "aeiou" else "a"
        noun = f"{article} {label}"
    else:
        plural = _IRREGULAR_PLURALS.get(label, label + "s")
        noun = f"{_NUMBER_WORDS.get(count, str(count)).lower()} {plural}"
    if focus in ("left", "right"):
        return noun
    return f"{noun} {_SIDE_PHRASES.get(side, '')}".strip()


if __name__ == "__main__":
    import sys

    import cv2
    from ultralytics import YOLO

    image = cv2.imread(sys.argv[1])
    if image is None:
        sys.exit(f"could not read {sys.argv[1]}")
    width = image.shape[1]
    result = YOLO("yolo11n.pt").predict(image, conf=settings.detection_confidence, verbose=False)[0]
    dets = []
    for box in result.boxes:
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
        cx = (x1 + x2) / 2 / width
        side = "left" if cx < 1 / 3 else "center" if cx < 2 / 3 else "right"
        dets.append({"label": result.names[int(box.cls[0])], "box": (x1, y1, x2, y2), "side": side})
    for focus in ("all", "left", "right"):
        print(f"{focus:>5}: {describe(focus, dets, light=1023)}")
