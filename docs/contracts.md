# EchoGuide interface contracts

Source of truth for how the three parts talk to each other. **Do not change
without telling the team** (changes go through Person 3). See `docs/plan.md`
for who owns what.

Hardware: fixed webcam, thumb joystick, touch sensor, (optional push button),
accelerometer, sound sensor, light sensor, buzzer. **No servos, no ultrasonics.**

## 1. Arduino -> laptop (USB serial, 115200 baud, one JSON object per line)

### Input frame (~20 Hz)
```json
{"type":"input","seq":1,"joy_x":512,"joy_y":508,"touch":0,"button":0,
 "ax":0.0,"ay":0.0,"az":1.0,"light":610,"sound":120}
```
| Field | Type | Meaning |
|---|---|---|
| `seq` | int | Increments each frame |
| `joy_x`, `joy_y` | 0–1023 | Raw joystick (X ≈ 1023 when pressed in on the Grove joystick) |
| `touch`, `button` | 0/1 | Raw current state (`button` stays 0 if not fitted) |
| `ax`, `ay`, `az` | g | Accelerometer |
| `light`, `sound` | 0–1023 | Raw analog |

### Events (sent once, when detected on the Arduino)
```json
{"type":"event","name":"joy_up"}
```
| `name` | Trigger | Owner | Backend action |
|---|---|---|---|
| `joy_up` | Joystick flicked up | P2 | Describe scene |
| `joy_down` | Joystick flicked down | P2 | Read text (OCR) |
| `joy_left` / `joy_right` | Joystick flicked left / right | P2 | Describe that third only |
| `joy_press` | Joystick pressed in | P2 | Repeat last message |
| `tap` | Touch < 1 s | P2 | Describe; or cancel active SOS / dismiss drop prompt |
| `hold_start` | Touch held 1 s | P2 | Start SOS countdown (3 s) |
| `hold_release` | Touch released after `hold_start` | P2 | Cancel countdown if not finished |
| `button_hold` | Push button held >= 2 s (if fitted) | P2 | Trigger SOS immediately |
| `impact` | Accel magnitude > ~2.5 g | P3 | Start cane-drop check |
| `clap` | Short sharp sound spike | P3 | Find cane (buzz 5 s) |
| `loud` | Sound above threshold >= 0.5 s | P3 | Log `LOUD_NOISE` event |

Joystick events are edge-triggered (one per flick) with ~400 ms debounce.

## 2. Laptop -> Arduino (one JSON object per line)
| Command | Effect |
|---|---|
| `{"cmd":"buzz","ms":3000}` | Buzz continuously for `ms` (0 = stop) |
| `{"cmd":"beep","pattern":"find"}` | Pattern: `find` (repeating), `sos` (3 long), `ok` (1 short), `error` (2 short) |

## 3. Backend -> frontend: `WS /ws`
Pushes the full `SessionState` on every change. **Removed** from the old
`frontend/src/api.ts`: `dist_left`, `dist_center`, `dist_right`, `pan`,
`tilt`, `scanning`. Mode values: `IDLE | DESCRIBING | READING | SOS_COUNTDOWN | SOS_ACTIVE`.

| Field | Type | Owner |
|---|---|---|
| `hazards` | `[{label, side: "left"\|"center"\|"right", closeness: 0..1, approaching: bool}]` | P1 |
| `warning`, `warning_id`, `warning_side`, `warning_urgent` | as before | P1 |
| `light` | number \| null | P1 |
| `camera_connected`, `arduino_connected` | boolean | P1 |
| `instruction`, `instruction_id` | last spoken text (for display only) | P1 (`audio.say`) |
| `last_description`, `last_text_read` | string | P2 |
| `focus` | `"all"\|"left"\|"right"` | P2 |
| `sos_active`, `sos_event_id`, `sos_status`, `sos_triggered_at`, `sos_countdown` | as before, + countdown seconds or null | P3 |
| `cane_drop_prompt`, `find_cane_active` | boolean | P3 |
| `activity` | `{moving_minutes_last_hour, last_motion_ts}` | P3 |
| `location` | `{lat, lng, accuracy, ts}` \| null | P3 |
| `recent_events` | event list (below) | P3 |

Each event: `{id, ts, type, payload, notify_status, chain_sig}`
- `type`: `SOS` \| `SOS_CANCELLED` \| `CANE_DROP` \| `DROP_OK` \| `DROP_HELP` \| `FIND_CANE` \| `LOUD_NOISE` \| `NO_MOVEMENT`
- `notify_status`: `pending` \| `delivered` \| `failed` \| `not_sent`
- `chain_sig`: Solana devnet signature, or null (= unverified)

## 4. Frontend -> backend (REST, base `http://localhost:8000`)
| Method + path | Body | Notes |
|---|---|---|
| `POST /action` | `{"action": ...}` | `DESCRIBE`, `READ_TEXT`, `FOCUS_LEFT`, `FOCUS_RIGHT`, `REPEAT`, `SOS`, `SOS_CANCEL`, `FIND_CANE`, `DROP_OK`, `DROP_HELP`. Same handlers as hardware events |
| `POST /api/location` | `{"lat":0,"lng":0,"accuracy":0}` | From the user's phone (`/me`) |
| `GET /api/profile` / `PUT /api/profile` | profile JSON (below) | Demo data only |
| `GET /api/events` | | Full history, newest first |
| `GET /video` | | MJPEG stream with detection boxes drawn (exists, `backend/app/camera.py`) |

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
| Pin | Part | Owner |
|---|---|---|
| A0 / A1 | Joystick X / Y | P2 |
| A2 | Light sensor | P1 |
| A3 | Sound sensor | P3 |
| A4 / A5 | Accelerometer SDA / SCL (I2C) | P3 |
| D5 | Touch sensor | P2 |
| D6 | Push button (optional) | P2 |
| D7 | Buzzer | P1 |

## 7. Code ownership boundaries
**Firmware** (`firmware/echoguide/`, all files compiled together by the Arduino IDE):
```cpp
struct Frame;                 // defined in echoguide.ino (P1); one field per JSON key in section 1
void feedbackSetup(); void feedbackUpdate(Frame&); bool feedbackCommand(const String& cmd);  // P1
void controlsSetup(); void controlsUpdate(Frame&); bool controlsCommand(const String& cmd);  // P2
void safetySetup();   void safetyUpdate(Frame&);   bool safetyCommand(const String& cmd);    // P3
void emitEvent(const char* name);   // in echoguide.ino; prints {"type":"event","name":...}
```
`*Command` returns true if it handled the command.

**Backend shared APIs (P1).** Everyone uses these; nobody else plays sound or opens the camera:
```python
audio.warn(side: "left"|"center"|"right", urgency: float)   # 0..1, interrupts speech
audio.say(text: str)                                          # replaces any pending speech
audio.chime(kind: "sos"|"ok"|"error")
detector.latest_detections   # [{label, conf, box:(x1,y1,x2,y2), side}] from the newest frame
camera.latest_frame()        # np.ndarray | None, for OCR
serial_reader.send(cmd: dict)
state.on_event(name, handler) / state.update(**fields)
```

**Backend routes:** P2 and P3 expose `router = APIRouter()` in their modules; `main.py` (P1) does `app.include_router(...)`.
