"""EchoGuide FastAPI app: camera + serial + detector + hazards -> /ws state.

Only this process opens the webcam and the serial port (see README
"Architecture" and docs/contracts.md). P2/P3 routers are included here when
their modules exist.
"""
from __future__ import annotations

import asyncio
import importlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .audio import audio
from .camera import camera
from .hazards import hazard_monitor
from .narrator import narrator
from .serial_reader import serial_reader
from .state import Mode, state_manager

_detector = None

# REST actions -> event names handlers subscribe to (contract section 4).
_ACTION_TO_EVENT = {
    "DESCRIBE": "describe",
    "READ_TEXT": "read_text",
    "FOCUS_LEFT": "focus_left",
    "FOCUS_RIGHT": "focus_right",
    "REPEAT": "repeat",
    "SOS": "sos",
    "SOS_CANCEL": "sos_cancel",
    "FIND_CANE": "find_cane",
    "DROP_OK": "drop_ok",
    "DROP_HELP": "drop_help",
    "SIMULATE_FALL": "hard_impact",  # test/demo: same event the Uno sends on a hard hit
}

# Modules owned by P2/P3 that may expose `router = APIRouter()`.
_OPTIONAL_ROUTE_MODULES = (
    "controls", "describer", "reader",
    "events", "cane_drop", "activity", "notify",
)


def _try_start_detector() -> None:
    global _detector
    try:
        from .detector import Detector

        _detector = Detector()
        _detector.start()
    except Exception as exc:
        print(f"[vision] detector unavailable: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state_manager.bind_loop(asyncio.get_running_loop())
    camera.open()
    serial_reader.start()
    _try_start_detector()
    hazard_monitor.start()
    narrator.start()
    _start_safety_modules()
    yield
    narrator.stop()
    hazard_monitor.stop()
    if _detector is not None:
        _detector.stop()
    serial_reader.stop()
    camera.release()
    audio.close()


def _start_safety_modules() -> None:
    """Wire P3's safety modules into the live backend: accelerometer frames,
    impact/clap/loud events, and the sos/drop/find events that controls.py
    and POST /action emit. (Before this, only tools/p3_dev_server.py did it.)"""
    from . import activity, cane_drop, care, events, find_cane

    care.register()        # phone location on alerts + demo profile
    cane_drop.register()   # impact event + frames -> fall check-in
    activity.register()    # frames -> activity chart / no-movement
    find_cane.register()   # clap / loud events -> buzzer / log

    routes = {
        "sos": lambda **_: events.trigger_sos("cane"),
        "sos_cancel": lambda **_: events.cancel_sos("cane"),
        "drop_ok": lambda **_: cane_drop.respond_ok("touch"),
        "drop_help": lambda **_: cane_drop.respond_help("touch"),
        "find_cane": lambda **_: find_cane.ACTIONS["FIND_CANE"](),
    }
    for name, handler in routes.items():
        state_manager.on_event(name, handler)
    events.publish()


app = FastAPI(title="EchoGuide", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    action = request.action.upper()
    event = _ACTION_TO_EVENT.get(action)
    if event is None:
        return {"status": "error", "detail": f"unknown action {request.action!r}"}
    state_manager.emit_event(event)
    return {"status": "ok"}


class ArduinoCommand(BaseModel):
    cmd: str
    ms: int = 0
    pattern: str = ""


@app.post("/api/arduino")
def arduino_command(request: ArduinoCommand):
    """P1 debug/test endpoint: forward a raw command to the Arduino
    (e.g. {"cmd":"beep","pattern":"ok"} or {"cmd":"buzz","ms":3000}).
    P2/P3 features should use state.emit_event + their own handlers instead."""
    payload = {"cmd": request.cmd}
    if request.ms:
        payload["ms"] = request.ms
    if request.pattern:
        payload["pattern"] = request.pattern
    ok = serial_reader.send(payload)
    return {"status": "ok" if ok else "offline"}


@app.get("/video")
def video():
    return StreamingResponse(
        camera.mjpeg_stream(),
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


# Include P2/P3 routers when their modules land (contract section 7).
for _mod_name in _OPTIONAL_ROUTE_MODULES:
    try:
        _mod = importlib.import_module(f".{_mod_name}", __package__)
        _router = getattr(_mod, "router", None)
        if _router is not None:
            app.include_router(_router)
    except ImportError:
        pass
