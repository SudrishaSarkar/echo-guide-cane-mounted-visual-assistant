"""JSON-backed settings: serial port, camera, hazard thresholds, audio.

Loads backend/settings.json if present, otherwise falls back to defaults
and writes the defaults out so the file exists for teammates to edit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, asdict
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
    camera_mirror: bool = False  # True = selfie-style flip (desk demos only)
    camera_rotate_180: bool = False  # True if the camera is mounted upside down

    # Vision model (COCO-80 classes). Swap for a bigger/better model here —
    # e.g. "yolo11m.pt" for accuracy, or a custom-trained weights file.
    detector_model: str = "yolo11s.pt"
    detection_confidence: float = 0.35
    detector_fps: float = 8.0   # upper bound; the model speed is the real limit
    detector_imgsz: int = 640   # 960 = ~400 ms/frame on a laptop CPU, 640 = ~200 ms

    # Descriptions ignore weak detections (fewer false positives like "cat").
    describe_min_confidence: float = 0.45
    # Light-sensor reading (0-1023) below which describe/narration say it is too dark.
    describe_min_light: int = 40

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
    speech_rate: int = 2  # SAPI rate, -10 (slow) .. 10 (fast)

    # Continuous narration (narrator.py): speaks what the camera sees.
    narration_enabled: bool = True
    narration_repeat_s: float = 5.0   # repeat an unchanged scene this often
    narration_gap_s: float = 0.3      # pause between sentences
    narration_max_objects: int = 3

    # Proximity beeps (hazards.py), parking-sensor style. Closeness 0..1 of
    # the nearest obstacle: below single_at = silence, then single beeps,
    # double beeps, and a continuous tone at continuous_at and above.
    beep_single_at: float = 0.45
    beep_double_at: float = 0.62
    beep_continuous_at: float = 0.80

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text())
            # settings.json also holds keys other modules read via
            # hooks.setting() (gemini_api_key, cane_axis, ...), plus stale
            # keys from older versions. Only pass the ones Settings defines.
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        settings = cls()
        settings.save()
        return settings

    def save(self) -> None:
        SETTINGS_PATH.write_text(json.dumps(asdict(self), indent=2))


settings = Settings.load()
