"""Dev harness for Person 3's features, usable before P1's main.py/state.py exist.

Runs the safety + care modules with a minimal stand-in for P1's shared state:
an in-memory SessionState, a /ws WebSocket, POST /action, and a simulated
accelerometer so cane drop / activity work without hardware. Speech and
Arduino commands are printed instead of played or sent.

Run from backend/:
    ..\\.venv\\Scripts\\python -m uvicorn tools.p3_dev_server:app --port 8000
then `npm run dev` in frontend/ and open http://localhost:5173 (and /me).

Simulate hardware:
    POST /dev/pose/upright | lying | walking   (accelerometer)
    POST /dev/event/impact | clap | loud        (Arduino events)
e.g. a dropped cane:  POST /dev/event/impact, then POST /dev/pose/lying, wait 10 s.

This is NOT the real backend; P1's main.py replaces it.
"""
from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app import activity, cane_drop, care, events, find_cane, hooks

STATE: dict[str, Any] = {
    "mode": "IDLE", "hazards": [], "warning": "", "warning_id": 0, "warning_side": None,
    "warning_urgent": False, "light": None, "camera_connected": False, "arduino_connected": True,
    "instruction": "", "instruction_id": 0, "last_description": "", "last_text_read": "",
    "focus": "all", "sos_countdown": None, "cane_drop_prompt": False, "find_cane_active": False,
    "activity": None, "location": None, "recent_events": [], "profile_updated_at": None,
    **events.sos_snapshot(),
}
_state_lock = threading.Lock()
_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None
_pose = "upright"


def update_state(**fields: Any) -> None:
    with _state_lock:
        STATE.update(fields)
        snapshot = json.dumps(STATE, default=str)
    if _loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(snapshot), _loop)


async def _broadcast(message: str) -> None:
    for ws in list(_clients):
        try:
            await ws.send_text(message)
        except Exception:
            _clients.discard(ws)


def say(text: str) -> None:
    print(f"[cane says] {text}", flush=True)
    with _state_lock:
        n = STATE["instruction_id"] + 1
    update_state(instruction=text, instruction_id=n)


# Stand in for P1's hooks.
hooks.update_state = update_state
hooks.say = say
hooks.chime = lambda kind: print(f"[chime] {kind}", flush=True)
hooks.send_cmd = lambda cmd: print(f"[arduino] {cmd}", flush=True)

HANDLERS = {"impact": cane_drop.on_impact, "clap": find_cane.on_clap, "loud": find_cane.on_loud}
ACTIONS = {**events.ACTIONS, **cane_drop.ACTIONS, **find_cane.ACTIONS}


def _frames() -> None:
    """20 Hz simulated accelerometer frames for the current pose."""
    i = 0
    while True:
        i += 1
        if _pose == "lying":
            vec = (1.0, 0.0, 0.0)
        elif _pose == "walking":
            vec = (0.3 * math.sin(i / 2), 0.2 * math.cos(i / 3), 1.0)
        else:
            vec = (0.0, 0.0, 1.0)
        frame = {"type": "input", "seq": i, "ax": vec[0], "ay": vec[1], "az": vec[2], "sound": 100}
        cane_drop.on_frame(frame)
        activity.on_frame(frame)
        time.sleep(0.05)


app = FastAPI(title="EchoGuide P3 dev harness")
for module in (events, care, activity):
    app.include_router(module.router)


@app.on_event("startup")
async def startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    care.register()
    threading.Thread(target=_frames, daemon=True).start()

    def ticker() -> None:
        while True:
            time.sleep(0.5)
            cane_drop.get_detector().tick()
            activity.get_tracker().tick()

    threading.Thread(target=ticker, daemon=True).start()
    events.publish()


class ActionBody(BaseModel):
    action: str


@app.post("/action")
def action(body: ActionBody) -> dict:
    handler = ACTIONS.get(body.action)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"{body.action} isn't handled by the P3 harness")
    handler()
    return {"ok": True}


@app.post("/dev/pose/{pose}")
def dev_pose(pose: str) -> dict:
    global _pose
    if pose not in ("upright", "lying", "walking"):
        raise HTTPException(status_code=400, detail="pose: upright | lying | walking")
    _pose = pose
    return {"pose": pose}


@app.post("/dev/event/{name}")
def dev_event(name: str) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        raise HTTPException(status_code=400, detail="event: impact | clap | loud")
    handler()
    return {"event": name}


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    _clients.add(socket)
    with _state_lock:
        await socket.send_text(json.dumps(STATE, default=str))
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        _clients.discard(socket)
