# Wiring notes

Fill in once the exact Arduino, joystick, and touch-sensor models are
confirmed. A model name/number or a clear photo of each module is enough to
pin down the correct pins and voltage.

## Components

| Component | Model | Notes |
|---|---|---|
| Arduino board | TBD | |
| Joystick | TBD (e.g. Grove Thumb Joystick) | |
| Touch sensor | TBD | |
| Base shield (if any) | TBD | |

## Connections

| Connection | Pins | Notes |
|---|---|---|
| Arduino -> laptop | USB data cable | Must support data, not just charging |
| Webcam -> laptop | USB | |
| Joystick -> Arduino | 2 analog signals + power + ground | A0/A1 if using Grove Base Shield's A0 socket |
| Touch sensor -> Arduino | 1 digital signal + power + ground | D2 in firmware/echoguide/echoguide.ino |

Before connecting power, read each module's voltage and pin labels — do not
assume 5V logic.

Leave the light sensor and accelerometer disconnected until the main loop
(joystick + touch -> Python -> guidance) works end-to-end.

## Serial format

```json
{"type":"input","seq":42,"joy_x":512,"joy_y":508,"touch":0}
```

ADC ranges are not assumed to be 0-1023 — `backend/app/serial_reader.py`
calibrates the joystick centre from the first readings at startup rather than
hardcoding it.
