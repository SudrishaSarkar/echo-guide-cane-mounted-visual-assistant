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
| `light` | 0–1023 | Raw analog |
| `sound` | 0–~1000 | Smoothed loudness (peak-to-peak size of the sound wave): ~0 in silence |

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
| `impact` | ±1.5 g sensor: any axis at its limit (≥ ~1.4 g) or a > ~1 g jump between readings (~125 reads/s, 2 s cooldown). Also fires on normal cane taps | P3 | Start cane-drop check (only prompts if then lying down + still) |
| `hard_impact` | Same as `impact`, but only when an axis is pinned at the sensor limit (a real hit, e.g. the cane hitting the floor). Sent just before the matching `impact` | P3 | Instant fall alarm + SOS + logged fall (`fall_instant_sos`) |
| `clap` | **Double clap**: two sharp spikes within ~0.6 s | P3 | Find cane (buzz 5 s) |
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
| `sos_active`, `sos_event_id`, `sos_triggered_at` | as before | P3 |
| `sos_status` | `idle` \| `active` \| `delivered` \| `acknowledged` \| `cancelled` | P3 |
| `sos_notify_status` | `pending` \| `delivered` \| `not_sent` | P3 |
| `sos_countdown` | seconds left in the hold countdown, or null | P2 |
| `cane_drop_prompt`, `find_cane_active` | boolean | P3 |
| `activity` | `{moving_minutes_last_hour, last_motion_ts}` | P3 |
| `location` | `{lat, lng, accuracy, ts}` \| null | P3 |
| `recent_events` | event list (below) | P3 |

Each event: `{id, ts, type, payload, notify_status, severity, notification}`
- `severity`: `alert` (SOS, DROP_HELP, CANE_DROP) \| `warning` (NO_MOVEMENT) \| `update` (SOS_CANCELLED, DROP_OK, the all-clear after a cane-drop alert) \| `info` (everything else)
- `notification`: `{title, body, tag, require_interaction}` or null for `info`. Built by the backend (`backend/app/alerts.py`); the title is prefixed `ALERT:` / `WARNING:` / `UPDATE:`. When the event is `pending`, the caregiver dashboard shows it as an **operating-system notification** (`new Notification(title, {body, tag, requireInteraction})`) as well as the in-app banner. An SOS_CANCELLED reuses its SOS's `tag`, so it replaces the SOS notification on screen
- `type`: `SOS` \| `SOS_ACKNOWLEDGED` \| `SOS_CANCELLED` \| `CANE_DROP` \| `DROP_OK` \| `DROP_HELP` \| `FIND_CANE` \| `LOUD_NOISE` \| `NO_MOVEMENT`
- `notify_status` (in-app caregiver alerts only, no external messaging):
  - `pending`: needs caregiver attention and hasn't been shown on a caregiver dashboard yet. The dashboard alerts (banner, sound, browser notification) and then calls `POST /api/events/{id}/seen`
  - `delivered`: shown on a caregiver dashboard
  - `not_sent`: informational, no alert needed

## 4. Frontend -> backend (REST)
The frontend uses **relative URLs** (`/api/...`, `/action`, `/ws`, `/video`).
In development, `vite.config.ts` proxies them to `http://localhost:8000`, so
a single tunnel on port 5173 serves the whole app over HTTPS.

| Method + path | Body | Notes |
|---|---|---|
| `POST /action` | `{"action": ...}` | `DESCRIBE`, `READ_TEXT`, `FOCUS_LEFT`, `FOCUS_RIGHT`, `REPEAT`, `SOS`, `SOS_CANCEL`, `SOS_ACK`, `FIND_CANE`, `DROP_OK`, `DROP_HELP`. Same handlers as hardware events |
| `POST /api/sos` | `{"source":"dashboard"\|"me"}` | Trigger SOS |
| `POST /api/sos/cancel` | `{"source":...}` | User cancels; false-alarm follow-up if already delivered |
| `POST /api/sos/ack` | `{"by":"caregiver"}` | Caregiver acknowledges; the cane tells the user |
| `POST /api/events/{id}/seen` | `{"by":"caregiver"}` | **Caregiver views only.** Marks a `pending` event `delivered`; for the open SOS, the cane says "Your caregiver has been alerted." Idempotent |
| `POST /api/location` | `{"lat":0,"lng":0,"accuracy":0}` | From the user's phone (`/me`) |
| `GET /api/profile` / `PUT /api/profile` | profile JSON (below) | Demo data only |
| `GET /api/location` | | Latest phone fix `{lat, lng, accuracy, ts}` or null |
| `GET /api/events` | | Full history, newest first |
| `GET /api/activity` | | Same object as `SessionState.activity` |
| `GET /video` | | MJPEG stream with detection boxes drawn (exists, `backend/app/camera.py`) |

Profile JSON:
```json
{"name":"","age":null,"contacts":[{"name":"","relation":"","phone":""}],
 "medical_history":"","medications":[{"name":"","dose":""}],
 "allergies":[],"care_notes":""}
```

## 5. Privacy
- Profile and medical info are **demo data only**.
- Events and the profile live in SQLite on the laptop (`backend/echoguide.db`, gitignored); the phone location is kept in memory only.
- Nothing goes to an outside service except OpenStreetMap map tiles. No blockchain, no SMS, email or Discord.

## 6. Arduino Uno pin map
| Pin | Part | Owner |
|---|---|---|
| A0 / A1 | Joystick X / Y | P2 |
| A2 | Light sensor | P1 |
| A3 | Sound sensor | P3 |
| A4 / A5 | Accelerometer SDA / SCL (I2C, Grove 3-Axis Digital Accelerometer ±1.5 g, MMA7660FC, address `0x4C`) | P3 |
| D5 | Touch sensor | P2 |
| D6 | Push button (optional) | P2 |
| D7 | Buzzer | P1 |

## 7. Code ownership boundaries
**Firmware** (`firmware/echoguide/`, all files compiled together by the Arduino IDE):
```cpp
// frame.h (P1 owns; a starting version exists): struct Frame + emitEvent declaration.
// It must be a header: .cpp files can't see types defined inside echoguide.ino.
// loop() must not block (no long delay()): safety.cpp samples the accelerometer at ~125 Hz.
void feedbackSetup(); void feedbackUpdate(Frame&); bool feedbackCommand(const String& cmd);  // P1
void controlsSetup(); void controlsUpdate(Frame&); bool controlsCommand(const String& cmd);  // P2
void safetySetup();   void safetyUpdate(Frame&);   bool safetyCommand(const String& cmd);    // P3
void emitEvent(const char* name);   // declared in frame.h, defined in echoguide.ino; prints {"type":"event","name":...}
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
state.on_frame(handler)      # handler(frame: dict) for every {"type":"input"} frame (P3's cane_drop needs ax/ay/az)
```

**Backend events/SOS API (P3)**, called by P2's controls and P3's other modules:
```python
events.trigger_sos(source: str) -> dict        # idempotent while an SOS is open
events.cancel_sos(source: str) -> dict | None  # None if nothing to cancel
events.acknowledge_sos(by: str) -> dict | None
events.sos_open() -> bool                      # True while active/delivered
events.record(type: str, payload: dict, notify: bool = False) -> dict   # notify=True -> "pending" in-app alert
events.mark_seen(event_id: int, by: str) -> dict | None

cane_drop.register()               # main.py calls once at startup: subscribes to impact + frames
cane_drop.prompt_active() -> bool  # True while "Tap if you're OK, or hold for help" is pending
cane_drop.respond_ok(source) -> bool
cane_drop.respond_help(source) -> bool   # records DROP_HELP and triggers SOS
cane_drop.ACTIONS                  # DROP_OK / DROP_HELP handlers for POST /action
```

**P2's controls, while `cane_drop.prompt_active()`:** `tap` → `cane_drop.respond_ok("touch")`
and `hold_start` → `cane_drop.respond_help("touch")` (straight to SOS, with no 3 s countdown,
because the user was just asked). Otherwise use the normal mappings.

**Settings (P3 keys in `settings.json`):** `cane_axis` (`"x"` \| `"y"` \| `"z"`: the
accelerometer axis that runs along the cane, set after mounting), `cane_drop_enabled`
(**must be `true`**; the old example file has `false`), `cane_drop_inactivity_s` (10).

**Backend routes:** P2 and P3 expose `router = APIRouter()` in their modules; `main.py` (P1) does `app.include_router(...)`.

## 8. Integration checklist for Person 1 (from Person 3)
Person 3's modules are done and tested (`backend/tests/`). To wire them into the real backend:

1. **`state.py`:** provide `update(**fields)`, `on_event(name, handler)` and
   `on_frame(handler)` (several handlers per name/frame).
2. **`main.py` at startup:**
   ```python
   from app import activity, cane_drop, care, events, find_cane
   for m in (events, care, activity):
       app.include_router(m.router)
   care.register(); cane_drop.register(); activity.register(); find_cane.register()
   ACTIONS.update({**events.ACTIONS, **cane_drop.ACTIONS, **find_cane.ACTIONS})  # POST /action
   ```
3. **`audio.py`:** `say`, `chime`, `warn` as in section 7. **`serial_reader.py`:** `send(cmd)`.
4. **Shared frontend files changed by P3:** `api.ts` (contract types, relative URLs,
   `INITIAL_STATE`), `useEchoGuideSocket.ts` (merges over `INITIAL_STATE`) and
   `App.tsx` (routes `/`, `/profile`, `/me`; care panels; old distance/pan/tilt UI and
   `useSpeech` removed). P1 and P2 add their panels to `App.tsx` as before.
5. **Until then:** `backend/tools/p3_dev_server.py` runs P3's features alone
   (`python -m uvicorn tools.p3_dev_server:app --port 8000` from `backend/`), with fake
   accelerometer poses and events at `POST /dev/pose/...` and `POST /dev/event/...`
   (call port 8000 directly; Vite doesn't proxy `/dev`).
