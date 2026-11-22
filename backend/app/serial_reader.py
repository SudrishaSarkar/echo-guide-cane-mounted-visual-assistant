"""Reads EchoGuide Arduino JSON over USB serial, both directions.

Input frame (~20 Hz, contract section 1):
    {"type":"input","seq":1,"joy_x":512,"joy_y":508,"touch":0,"button":0,
     "ax":0.0,"ay":0.0,"az":1.0,"light":610,"sound":120}

Event (once, when detected on the Arduino):
    {"type":"event","name":"joy_up"}

Commands laptop -> Arduino (contract section 2):
    {"cmd":"buzz","ms":3000}   {"cmd":"beep","pattern":"find"}

Auto-reconnects on serial errors. Only one program can own the COM port —
use tools/fake_arduino.py for hardware-free testing.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from typing import Optional

import serial

from .config import settings
from .state import state_manager


class _TcpSerial:
    """Minimal pyserial-like wrapper over a TCP socket, for fake_arduino.py.

    Set settings.serial_port to "tcp:host:port" (e.g. tcp:localhost:8765).
    """

    def __init__(self, address: str) -> None:
        host, _, port = address.partition(":")
        self._sock = socket.create_connection((host, int(port)), timeout=1)
        self._sock.settimeout(1)
        self._reader = self._sock.makefile("rb")
        self._writer = self._sock.makefile("wb")
        self.is_open = True

    def readline(self) -> bytes:
        try:
            return self._reader.readline()
        except (socket.timeout, TimeoutError):
            return b""

    def write(self, data: bytes) -> int:
        self._writer.write(data)
        self._writer.flush()
        return len(data)

    def close(self) -> None:
        self.is_open = False
        try:
            self._sock.close()
        except OSError:
            pass


def _open_port():
    port = settings.serial_port
    if port.startswith("tcp:"):
        return _TcpSerial(port[4:])
    return serial.Serial(port, settings.baud_rate, timeout=1)

# Newest raw input frame, for modules that need accel/sound/etc. (P3).
latest_input: dict = {}


class SerialReader:
    def __init__(self) -> None:
        self._ser: Optional[serial.Serial] = None
        self._write_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def send(self, cmd: dict) -> bool:
        """Send one command object to the Arduino. Returns False if offline."""
        with self._write_lock:
            if self._ser is None or not self._ser.is_open:
                return False
            try:
                self._ser.write((json.dumps(cmd) + "\n").encode("utf-8"))
                return True
            except Exception:
                return False

    def _run(self) -> None:
        while self._running:
            try:
                self._ser = _open_port()
                state_manager.update(arduino_connected=True)
                self._read_loop()
            except serial.SerialException:
                state_manager.update(arduino_connected=False)
                time.sleep(1.0)
            except Exception as exc:
                print(f"[serial] error: {exc}")
                state_manager.update(arduino_connected=False)
                time.sleep(1.0)

    def _read_loop(self) -> None:
        assert self._ser is not None
        empty_reads = 0
        while self._running:
            line = self._ser.readline()
            if not line:
                empty_reads += 1
                if empty_reads >= 3:
                    state_manager.update(arduino_connected=False)
                continue
            empty_reads = 0
            state_manager.update(arduino_connected=True)
            try:
                payload = json.loads(line.decode("utf-8", errors="ignore").strip())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            ptype = payload.get("type")
            if ptype == "input":
                self._handle_input(payload)
            elif ptype == "event":
                name = payload.get("name")
                if name:
                    print(f"[arduino] event {name}", flush=True)
                    state_manager.emit_event(name)

    def _handle_input(self, payload: dict) -> None:
        global latest_input
        latest_input = payload
        # P1 owns `light`; everything else stays available via latest_input.
        if "light" in payload:
            state_manager.update(light=payload["light"])
        state_manager.emit_frame(payload)


serial_reader = SerialReader()


if __name__ == "__main__":
    serial_reader.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        serial_reader.stop()
