# EchoGuide interface contracts

Source of truth for how the three parts talk to each other. **Do not change
without telling the team** (changes go through Person 3). See `docs/plan.md`
for who owns what.

## 1. Arduino -> laptop (USB serial, 115200 baud, one JSON object per line)

### Input frame (~20 Hz)
```json
{"type":"input","seq":1,"joy_x":512,"joy_y":508,"touch":0,"button":0,
 "pan":90,"tilt":90,"dist_left":85,"dist_center":-1,"dist_right":142,
 "ax":0.0,"ay":0.0,"az":1.0,"light":610,"sound":120}
```
| Field | Type | Meaning |
|---|---|---|
| `seq` | int | Increments each frame |
| `joy_x`, `joy_y` | 0–1023 | Raw joystick |
| `touch`, `button` | 0/1 | Raw current state |
| `pan`, `tilt` | degrees | Current servo angles (pan 20–160, tilt 40–130) |
| `dist_*` | cm | **`-1` = unknown** (timeout/out of range). Never treat as clear |
| `ax`, `ay`, `az` | g | Accelerometer |
| `light`, `sound` | 0–1023 | Raw analog |

### Events (sent once, when detected on the Arduino)
```json
{"type":"event","name":"tap"}
```
| `name` | Trigger | Backend action |
|---|---|---|
| `tap` | Touch press < 1 s | Describe scene |
| `sos_hold` | Button held >= 2 s | Start SOS |
| `clap` | Sound spike over threshold | Find cane (buzz) |
| `impact` | Accel magnitude > ~2.5 g | Start cane-drop check |

## 2. Laptop -> Arduino (one JSON object per line)
| Command | Effect |
|---|---|
| `{"cmd":"buzz","ms":3000}` | Sound buzzer for `ms` (0 = stop) |
| `{"cmd":"freeze"}` | Ignore joystick, hold servos (during image capture) |
| `{"cmd":"unfreeze"}` | Resume joystick control |
| `{"cmd":"center"}` | Move servos to pan 90 / tilt 90 |

## 3. Backend -> frontend: `WS /ws`
Pushes the full `SessionState` (see `frontend/src/api.ts`) on every change.
Existing fields stay; added fields:

| Field | Type |
|---|---|
| `light` | number \| null |
| `find_cane_active` | boolean |
| `location` | `{lat, lng, accuracy, ts}` \| null |
| `profile_updated_at` | ISO string \| null |

Each item in `recent_events`: `{id, ts, type, payload, notify_status, chain_sig}`
- `type`: `SOS` \| `SOS_CANCELLED` \| `CANE_DROP` \| `DROP_OK` \| `DROP_HELP` \| `FIND_CANE` \| `DESCRIBE`
- `notify_status`: `pending` \| `delivered` \| `failed` \| `not_sent`
- `chain_sig`: Solana devnet transaction signature, or null (= unverified)

## 4. Frontend -> backend (REST, base `http://localhost:8000`)
| Method + path | Body | Notes |
|---|---|---|
| `POST /action` | `{"action": "DESCRIBE"\|"SOS"\|"SOS_CANCEL"\|"FIND_CANE"\|"DROP_OK"\|"DROP_HELP"}` | Same handlers as the hardware events |
| `POST /api/location` | `{"lat":0,"lng":0,"accuracy":0}` | From the care recipient's phone (`/me`) |
| `GET /api/profile` / `PUT /api/profile` | profile JSON (below) | Demo data only |
| `GET /api/events` | | Full history, newest first |
| `GET /video` | | MJPEG stream (exists, `backend/app/camera.py`) |

Profile JSON:
```json
{"name":"","age":null,"contacts":[{"name":"","relation":"","phone":""}],
 "medical_history":"","medications":[{"name":"","dose":""}],
 "allergies":[],"care_notes":""}
```

## 5. Solana incident log
- Devnet only. One Memo-program transaction per incident.
- Memo: `echoguide|<type>|<iso ts>|<sha256 of the event JSON>`. **No personal or health data on-chain.**
- Runs in the background; failure must never delay SOS or notification.

## 6. Arduino Uno pin map
| Pin | Part |
|---|---|
| A0 / A1 | Joystick X / Y |
| A2 | Light sensor |
| A3 | Sound sensor |
| A4 / A5 | Accelerometer SDA / SCL (I2C) |
| D2 / D3 / D4 | Ultrasonic left / centre / right (Grove single-pin) |
| D5 | Touch sensor |
| D6 | Button (SOS) |
| D7 | Buzzer |
| D9 / D10 | Servo pan / tilt (signal only; power from external 5 V, shared GND) |

## 7. Code ownership boundaries
**Firmware** (`firmware/echoguide/`, all files compiled together by the Arduino IDE):
```cpp
struct Frame;                 // defined in echoguide.ino (P1); one field per JSON key in section 1
void obstaclesSetup();  void obstaclesUpdate(Frame&);  bool obstaclesCommand(const String& cmd);   // P1
void cameraSetup();     void cameraUpdate(Frame&);     bool cameraCommand(const String& cmd);      // P2
void safetySetup();     void safetyUpdate(Frame&);     bool safetyCommand(const String& cmd);      // P3
void emitEvent(const char* name);   // in echoguide.ino; prints {"type":"event","name":...}
```
`*Command` returns true if it handled the command.

**Backend audio** (`backend/app/audio.py`, P1). The only way to make sound:
```python
audio.warn(side: "left"|"center"|"right", urgency: float)   # 0..1, interrupts speech
audio.say(text: str)                                          # replaces any pending speech
audio.chime(kind: "sos"|"ok"|"error")
```

**Backend routes:** P2 and P3 expose `router = APIRouter()` in their modules; `main.py` (P1) does `app.include_router(...)`.
Hardware events reach them via `state.on_event(name, handler)` registered at startup.
