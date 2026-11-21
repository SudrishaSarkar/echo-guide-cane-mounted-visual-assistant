"""FastAPI app wiring: camera + serial + vision + guidance -> session state.

Only this process opens the webcam and the serial port (see README
"Architecture"). The frontend only ever talks to these routes.
"""
from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .camera import camera
from .config import settings
from .guidance import GuidanceEngine, Position
from .serial_reader import Action, SerialReader
from .state import Mode, state_manager

_object_detector = None
_hand_tracker = None


def _try_load_vision():
    """Loads YOLO/MediaPipe lazily so the server still boots without models downloaded."""
    global _object_detector, _hand_tracker
    try:
        from .object_detector import ObjectDetector

        _object_detector = ObjectDetector()
    except Exception as exc:  # model not downloaded yet, etc.
        print(f"[vision] object detector unavailable: {exc}")
    try:
        from .hand_tracker import HandTracker

        _hand_tracker = HandTracker()
    except Exception as exc:  # models/hand_landmarker.task missing, etc.
        print(f"[vision] hand tracker unavailable: {exc}")


guidance_engine = GuidanceEngine()
_latest_annotated_frame: Optional[np.ndarray] = None
_frame_lock = threading.Lock()
_processing_running = False


def _apply_action(action: Action) -> None:
    state = state_manager.state
    objects = settings.supported_objects

    if action in (Action.PREV_OBJECT, Action.NEXT_OBJECT):
        if state.mode not in (Mode.IDLE, Mode.SEARCHING, Mode.GUIDING, Mode.NEAR_TARGET, Mode.PAUSED):
            return
        current = objects.index(state.selected_object) if state.selected_object in objects else -1
        step = -1 if action == Action.PREV_OBJECT else 1
        next_object = objects[(current + step) % len(objects)]
        state_manager.update(selected_object=next_object, mode=Mode.IDLE)
    elif action == Action.START:
        if state.selected_object is None:
            return
        guidance_engine.reset()
        state_manager.update(mode=Mode.SEARCHING)
    elif action == Action.REPEAT:
        guidance_engine._last_spoken_at = 0.0  # force re-speak on next guidance tick
    elif action == Action.TOUCH_SHORT:
        if state.mode == Mode.IDLE:
            state_manager.update(mode=Mode.DESCRIBING)
        elif state.mode == Mode.NEAR_TARGET:
            state_manager.update(mode=Mode.CONFIRMED)
    elif action == Action.TOUCH_LONG:
        guidance_engine.reset()
        state_manager.update(mode=Mode.IDLE, selected_object=None, instruction="")


def _processing_loop() -> None:
    global _latest_annotated_frame
    while _processing_running:
        frame = camera.read()
        state_manager.update(camera_connected=camera.connected)
        if frame is None:
            time.sleep(0.05)
            continue

        annotated = frame.copy()
        state = state_manager.state

        if state.mode in (Mode.SEARCHING, Mode.GUIDING, Mode.NEAR_TARGET) and state.selected_object:
            target_pos = None
            if _object_detector is not None:
                detection = _object_detector.best_match(frame, state.selected_object)
                if detection is not None:
                    target_pos = Position(detection.cx, detection.cy)
                    cv2.rectangle(
                        annotated,
                        (int(detection.x1 * frame.shape[1]), int(detection.y1 * frame.shape[0])),
                        (int(detection.x2 * frame.shape[1]), int(detection.y2 * frame.shape[0])),
                        (0, 255, 0),
                        2,
                    )

            hand_pos = None
            if _hand_tracker is not None:
                hand = _hand_tracker.track(frame)
                if hand is not None:
                    hand_pos = Position(hand.x, hand.y)
                    cv2.circle(
                        annotated,
                        (int(hand.x * frame.shape[1]), int(hand.y * frame.shape[0])),
                        8,
                        (255, 0, 0),
                        -1,
                    )

            instruction, near_target = guidance_engine.step(target_pos, hand_pos)
            next_mode = Mode.NEAR_TARGET if near_target else Mode.GUIDING
            state_manager.update(
                target_visible=target_pos is not None,
                hand_visible=hand_pos is not None,
                mode=next_mode,
            )
            state_manager.set_instruction(instruction)

        with _frame_lock:
            _latest_annotated_frame = annotated

        time.sleep(1 / 30)


def _get_latest_frame() -> Optional[np.ndarray]:
    with _frame_lock:
        return None if _latest_annotated_frame is None else _latest_annotated_frame.copy()


serial_reader = SerialReader(
    on_action=_apply_action,
    on_connection_change=lambda connected: state_manager.update(arduino_connected=connected),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _processing_running
    _try_load_vision()
    camera.open()
    serial_reader.start()
    _processing_running = True
    threading.Thread(target=_processing_loop, daemon=True).start()
    yield
    _processing_running = False
    serial_reader.stop()
    camera.release()


app = FastAPI(title="EchoGuide", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "project": "EchoGuide"}


@app.get("/state")
def get_state():
    return state_manager.state.to_dict()


class ActionRequest(BaseModel):
    action: str


@app.post("/action")
def post_action(request: ActionRequest):
    try:
        action = Action(request.action)
    except ValueError:
        return {"status": "error", "detail": f"unknown action {request.action!r}"}
    _apply_action(action)
    return {"status": "ok"}


@app.get("/video")
def video():
    return StreamingResponse(
        camera.mjpeg_stream(_get_latest_frame),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws")
async def websocket_state(websocket: WebSocket):
    await websocket.accept()
    queue = state_manager.subscribe()
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        state_manager.unsubscribe(queue)
