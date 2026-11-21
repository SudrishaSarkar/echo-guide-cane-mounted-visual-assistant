"""MediaPipe Hand Landmarker (Tasks API) wrapper.

Uses the index fingertip (landmark 8) as the single reference point for
guidance, per the build guide's "single designated hand, single reference
point" rule. Requires models/hand_landmarker.task to be downloaded first
(see README.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "hand_landmarker.task"

INDEX_FINGERTIP = 8


@dataclass
class HandPosition:
    x: float  # normalized 0-1
    y: float


class HandTracker:
    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=1,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self._timestamp_ms = 0

    def track(self, frame: np.ndarray) -> Optional[HandPosition]:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        self._timestamp_ms += 33  # ~30 fps; replace with a real clock if frame rate varies
        result = self._landmarker.detect_for_video(mp_image, self._timestamp_ms)
        if not result.hand_landmarks:
            return None
        landmark = result.hand_landmarks[0][INDEX_FINGERTIP]
        return HandPosition(x=landmark.x, y=landmark.y)

    def close(self) -> None:
        self._landmarker.close()
