"""Fake Arduino for hardware-free development (P1 tool).

Streams fake input frames at ~20 Hz and turns keystrokes into contract
events, so P2/P3 can build without hardware. The backend connects by setting
`serial_port` in backend/settings.json to:

    "tcp:localhost:8765"

Run:  python backend/tools/fake_arduino.py
Then start the backend normally (uvicorn). Only ONE backend client is
supported at a time.

Keys (press Enter after typing the key):
    q       quit
    u d l r joystick flick -> joy_up / joy_down / joy_left / joy_right
    p       joystick press  -> joy_press
    t       touch tap       -> tap
    h       touch hold      -> hold_start
    j       touch release   -> hold_release
    b       button hold     -> button_hold
    i       accel spike     -> impact
    c       sharp sound     -> clap
    n       loud noise      -> loud
    [ ]     lower / raise the fake light-sensor reading
"""
from __future__ import annotations

import socket
import sys
import threading
import time

HOST, PORT = "127.0.0.1", 8765
FRAME_INTERVAL = 0.05  # 20 Hz

KEY_EVENTS = {
    "u": "joy_up",
    "d": "joy_down",
    "l": "joy_left",
    "r": "joy_right",
    "p": "joy_press",
    "t": "tap",
    "h": "hold_start",
    "j": "hold_release",
    "b": "button_hold",
    "i": "impact",
    "c": "clap",
    "n": "loud",
}

_state = {"light": 610, "seq": 0, "client": None}
_lock = threading.Lock()


def _frame() -> str:
    _state["seq"] += 1
    return (
        '{"type":"input","seq":%d,"joy_x":512,"joy_y":508,"touch":0,"button":0,'
        '"ax":0.0,"ay":0.0,"az":1.0,"light":%d,"sound":120}'
        % (_state["seq"], _state["light"])
    )


def _broadcast(line: str) -> None:
    with _lock:
        client = _state["client"]
    if client is None:
        return
    try:
        client.sendall((line + "\n").encode("utf-8"))
    except OSError:
        with _lock:
            _state["client"] = None


def _frame_loop() -> None:
    while True:
        _broadcast(_frame())
        time.sleep(FRAME_INTERVAL)


def _key_loop() -> None:
    print("fake_arduino ready — connect backend with serial_port='tcp:localhost:8765'")
    print("keys: u/d/l/r joy · p press · t tap · h hold · j release · b button · "
          "i impact · c clap · n loud · [ ] light · q quit")
    while True:
        try:
            key = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if key == "q":
            break
        if key in ("[", "]"):
            _state["light"] = max(0, min(1023, _state["light"] + (-40 if key == "[" else 40)))
            print(f"light -> {_state['light']}")
            continue
        name = KEY_EVENTS.get(key)
        if name:
            _broadcast('{"type":"event","name":"%s"}' % name)
            print(f"event -> {name}")
        else:
            print("unknown key")
    _broadcast('{{"type":"event","name":"quit"}}')
    sys.exit(0)


def _serve() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f"listening on {HOST}:{PORT} — start the backend now")
    while True:
        client, addr = server.accept()
        print(f"backend connected from {addr}")
        with _lock:
            _state["client"] = client


if __name__ == "__main__":
    threading.Thread(target=_serve, daemon=True).start()
    threading.Thread(target=_frame_loop, daemon=True).start()
    _key_loop()
