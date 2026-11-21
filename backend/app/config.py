"""JSON-backed settings: serial port, thresholds, camera config.

Loads backend/settings.json if present, otherwise falls back to defaults
and writes the defaults out so the file exists for teammates to edit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"

SUPPORTED_OBJECTS: List[str] = ["bottle", "cup", "cell phone"]


@dataclass
class Settings:
    serial_port: str = "COM3"
    baud_rate: int = 115200
    camera_index: int = 0
    joystick_deadzone: int = 60
    touch_long_press_ms: int = 600
    detection_confidence: float = 0.5
    supported_objects: List[str] = field(default_factory=lambda: list(SUPPORTED_OBJECTS))
    near_target_radius: float = 0.12
    instruction_persist_frames: int = 5
    instruction_repeat_delay_s: float = 4.0

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
