"""OpenCV webcam capture: latest raw frame for vision modules, annotated
frame for the /video MJPEG stream.

Only this process opens the webcam. detector.py publishes detection boxes by
calling set_annotated(); OCR (P2) reads latest_frame().
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Generator, Optional

import cv2
import numpy as np

from .config import settings
from .state import state_manager


class Camera:
    def __init__(self) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._annotated: Optional[np.ndarray] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def open(self) -> bool:
        # DSHOW is reliable for UVC webcams on Windows; MSMF (the default)
        # intermittently fails to grab frames. Other platforms use the default.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(settings.camera_index, backend)
        # 720p gives the detector noticeably better small-object accuracy;
        # still cheap enough for ~5 fps YOLO on CPU.
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        ok = self._cap.isOpened()
        state_manager.update(camera_connected=ok)
        if ok:
            self._running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
        return ok

    def _capture_loop(self) -> None:
        while self._running and self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                state_manager.update(camera_connected=False)
                time.sleep(0.1)
                continue
            state_manager.update(camera_connected=True)
            with self._lock:
                self._latest = frame
            time.sleep(0)  # capture runs as fast as the driver allows

    def latest_frame(self) -> Optional[np.ndarray]:
        """Newest raw frame (for detector, OCR)."""
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def set_annotated(self, frame: np.ndarray) -> None:
        """Called by detector.py with boxes drawn."""
        with self._lock:
            self._annotated = frame

    def stream_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            frame = self._annotated if self._annotated is not None else self._latest
            return None if frame is None else frame.copy()

    def release(self) -> None:
        self._running = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        state_manager.update(camera_connected=False)

    def mjpeg_stream(self) -> Generator[bytes, None, None]:
        while self._running or self.stream_frame() is not None:
            frame = self.stream_frame()
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
