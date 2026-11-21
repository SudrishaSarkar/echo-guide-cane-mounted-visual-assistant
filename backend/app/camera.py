"""OpenCV webcam capture and MJPEG frame streaming for GET /video."""
from __future__ import annotations

import threading
import time
from typing import Generator, Optional

import cv2
import numpy as np

from .config import settings


class Camera:
    def __init__(self) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self.connected = False

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(settings.camera_index)
        self.connected = self._cap.isOpened()
        return self.connected

    def read(self) -> Optional[np.ndarray]:
        if self._cap is None:
            return None
        with self._lock:
            ok, frame = self._cap.read()
        if not ok:
            self.connected = False
            return None
        self.connected = True
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()

    def mjpeg_stream(self, get_annotated_frame) -> Generator[bytes, None, None]:
        """get_annotated_frame() -> np.ndarray | None, called once per frame."""
        while True:
            frame = get_annotated_frame()
            if frame is None:
                time.sleep(0.05)
                continue
            ok, jpeg = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )


camera = Camera()
