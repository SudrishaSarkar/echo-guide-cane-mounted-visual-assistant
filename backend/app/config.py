"""JSON-backed settings: serial port, camera, hazard thresholds, audio.

Loads backend/settings.json if present, otherwise falls back to defaults
and writes the defaults out so the file exists for teammates to edit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"

# YOLO-COCO classes that count as obstacles for hazard alerts.
DEFAULT_OBSTACLE_CLASSES: List[str] = [
    "person", "chair", "couch", "bench", "dining table", "bed",
    "bicycle", "car", "truck", "bus", "motorcycle",
    "dog", "cat", "suitcase", "backpack", "handbag", "tie",
    "potted plant", "vase", "book", "laptop", "cell phone",
    "bottle", "cup", "bowl", "banana", "apple", "orange",
    "sandwich", "cake", "chair",
]


@dataclass
class Settings:
    serial_port: str = "COM3"
    baud_rate: int = 115200
    camera_index: int = 0

    # Vision model (COCO-80 classes). Swap for a bigger/better model here —
    # e.g. "yolo11m.pt" for accuracy, or a custom-trained weights file.
    detector_model: str = "yolo11s.pt"
    detection_confidence: float = 0.35
    detector_fps: float = 5.0
    detector_imgsz: int = 960

    # Descriptions ignore weak detections (fewer false positives like "cat").
    describe_min_confidence: float = 0.45

    # A "person" only counts when the box looks like head-to-chest is visible:
    # tall enough relative to the frame and portrait-shaped. Stops a card or
    # hand held up close from being announced as a person.
    person_min_height_frac: float = 0.18
    person_min_aspect: float = 1.0  # box height / width must be >= this
    hazard_poll_hz: float = 10.0

    # Hazard heuristics (fractions of frame size)
    hazard_close_box_height_frac: float = 0.45
    hazard_close_bottom_frac: float = 0.15
    hazard_close_min_area_frac: float = 0.12
    hazard_approach_window_s: float = 1.0
    hazard_cooldown_s: float = 2.5

    obstacle_classes: List[str] = field(default_factory=lambda: list(DEFAULT_OBSTACLE_CLASSES))

    # Audio
    audio_sample_rate: int = 44100
    tts_enabled: bool = True

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text())
            return cls(**{**asdict(cls()), **data})
        settings = cls()
        settings.save()
        return settings

    def save(self) -> None:
        SETTINGS_PATH.write_text(json.dumps(asdict(self), indent=2))


settings = Settings.load()
