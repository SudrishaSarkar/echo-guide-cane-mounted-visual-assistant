# Wiring notes — Person 1 (vision alerts + core)

Pin map is the contract in `docs/contracts.md` section 6. P1 owns **A2
(light sensor)** and **D7 (buzzer)**; the webcam and stereo earbuds are USB.

## P1 connections

| Part | Pin(s) | Notes |
|---|---|---|
| Webcam | USB -> laptop/Pi | Mount facing forward, angled slightly down, ~knee-to-chest height, rigid (no wobble when cane swings) |
| Stereo earbuds | USB/audio jack -> laptop | All user audio comes from the backend (Pygame + pyttsx3) |
| Light sensor | A2 -> Arduino | Analog out; raw 0-1023 in `Frame.light` |
| Buzzer | D7 -> Arduino | Driven by `feedback.cpp` (`buzz`/`beep` commands) |
| Arduino -> laptop | USB data | 115200 baud; close Serial Monitor first |

P2 owns A0/A1 (joystick), D5 (touch), D6 (button). P3 owns A3
(sound), A4/A5 (accel I2C). A2 is **light** — do not confuse.

## Webcam mounting (P1)

- Rigid mount on the sensing module below the handle, facing forward.
- Tilt slightly down (~15-30 deg) so obstacles at knee/chest height fill the
  lower frame — hazard heuristics key off box height and bottom-edge
  position.
- Keep the lens clean and the cable strain-relieved; the cane swings, so
  prefer tape/zip-ties + hot glue over loose tape.

## Test without the cane Arduino

`python backend/tools/fake_arduino.py` then set `serial_port` in
`backend/settings.json` to `"tcp:localhost:8765"`.
