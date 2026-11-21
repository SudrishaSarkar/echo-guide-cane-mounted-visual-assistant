# EchoGuide: 24-hour implementation plan (3 people, using Claude)

## Context
EchoGuide is a detachable cane attachment:
- Fixed ultrasonic sensors give left/centre/right obstacle warnings.
- A joystick pans and tilts a webcam on two servos.
- Tap the touch sensor for a spoken description of what the camera sees.
- Hold a button for SOS; a dropped cane triggers a check-in.
- A clap or the app makes the cane beep so it can be found.
- A caregiver app shows the live feed, location, incidents and the care profile.

The team is also entering **MLH Best Use of Solana**. Each incident is logged **tamper-evidently** on Solana devnet. Only a hash goes on-chain, never health data.

**Current repo state:**
- `backend/app/camera.py` works: capture plus the `/video` MJPEG stream.
- The other backend modules are one-line stubs: `main, config, state, serial_reader, warnings, audio, detector, describer, events, cane_drop`.
- The firmware is a header comment only.
- The frontend (`App.tsx`, `api.ts`, `useEchoGuideSocket.ts`, `useSpeech.ts`) is a working dashboard skeleton that talks to `/ws`, `/video` and `/action`.

**Hardware:** borrow 3× Grove Ultrasonic, 2× Grove Servo, Button and Buzzer from MLH. Add the team's own joystick, touch, accelerometer, light and sound sensors, the webcam, an Arduino Uno and the laptop. The laptop runs everything; the MLH "Pi" is a Pico and isn't needed.

## Decisions locked for everyone
- **All user audio comes from the backend.** Pygame plays stereo beeps and `pyttsx3` handles speech, through wired stereo earbuds. Warnings interrupt speech, and only the latest description is kept, never a queue. The dashboard only *shows* text. Remove the call to `useSpeech` in `App.tsx`.
- **SOS = Grove Button held 2 s. Touch sensor = tap to describe.** They're separate so SOS can't fire by accident.
- **No stair detection and no turn-by-turn cane finding.** Find-cane is just the buzzer.
- **Location comes from the care recipient's phone** (browser geolocation). It tracks the person, not the cane.
- **Demo data only.** Use a fake profile and medical info, and only a SHA-256 hash goes on-chain.
- Rename "GuardianCane" to **EchoGuide** everywhere in the pitch.

## Interface contracts (agree in hour 0–1, then don't change without telling the team)
Commit these to `docs/contracts.md` so every teammate's Claude reads the same spec.

**Arduino → laptop** (USB serial at 115200 baud, one JSON line per message):
- About 20 Hz:
  `{"type":"input","seq":1,"joy_x":512,"joy_y":508,"touch":0,"button":0,"pan":90,"tilt":90,"dist_left":85,"dist_center":-1,"dist_right":142,"ax":0.0,"ay":0.0,"az":1.0,"light":610,"sound":120}`
- `-1` means unknown (out of range or invalid), never "clear".
- Events are detected on the Arduino and sent as `{"type":"event","name":"tap"|"sos_hold"|"clap"|"impact"}`.

**Laptop → Arduino:**
- `{"cmd":"buzz","ms":3000}`
- `{"cmd":"freeze"}` and `{"cmd":"unfreeze"}`, which hold the servos still during image capture
- `{"cmd":"center"}`

**Backend → frontend:**
- `WS /ws` pushes `SessionState`. Keep the existing fields in `frontend/src/api.ts` and add `light`, `find_cane_active`, `location {lat,lng,accuracy,ts}|null` and `profile_updated_at`.
- Events in `recent_events` gain `chain_sig` and `notify_status`.

**Frontend → backend (REST):**
- `POST /action {action}`, where `action` is one of `DESCRIBE | SOS | SOS_CANCEL | FIND_CANE | DROP_OK | DROP_HELP`. This replaces `TOUCH_SHORT/TOUCH_LONG`.
- `POST /api/location {lat,lng,accuracy}`
- `GET/PUT /api/profile` (contacts, medical history, meds/allergies, personal info, care notes)
- `GET /api/events`
- `GET /video` (already exists)

**Arduino Uno pins:**
- A0/A1 joystick, A2 light, A3 sound, A4/A5 accelerometer (I²C)
- D2/D3/D4 ultrasonic L/C/R, D5 touch, D6 button, D7 buzzer, D9/D10 servos
- Servos get an external 5 V supply with a ground shared with the Arduino.

## Split: one feature per person, from sensor to screen

Each person owns a complete feature: the parts and wiring, their firmware file, the backend module, and the dashboard panel.

| | Person 1: Obstacles + find cane | Person 2: Camera + describe | Person 3: Safety + care app |
|---|---|---|---|
| **Parts** | 3× ultrasonic, sound sensor, buzzer | 2× servos, joystick, touch sensor, light sensor, webcam | Button, accelerometer |
| **Physical build** | Forward-facing sensor bar, cane clamp, servo power supply | Pan–tilt camera mount | Control module beside the handle: joystick, touch and button, within thumb reach |
| **Firmware file** | `obstacles.cpp/.h` + `echoguide.ino` (main loop, JSON out, command parsing) | `camera_ctrl.cpp/.h` | `safety.cpp/.h` |
| **Backend** | `serial_reader.py`, `fake_arduino.py`, `config.py`, `state.py`, `main.py`, `obstacle_warnings.py`, `audio.py` | `camera.py` (exists), `detector.py`, `describer.py` | `events.py`, `cane_drop.py`, `notify.py`, `solana_log.py` |
| **Frontend** | Distances, connection status, find-cane button | Live feed, pan/tilt, last description | SOS banner, incident log, map, profile, `/me` phone page |
| **Extra role** | Integration of shared files (`.ino`, `main.py`, `api.ts`) | Demo video + calibration with P1 | Devpost write-up, merges to `main` |

### Avoid merge conflicts
- **Firmware:** the Arduino IDE compiles every `.cpp`/`.h` file in `firmware/echoguide/` together. Each module exposes `xxxSetup()`, `xxxUpdate(Frame&)` and `xxxCommand(cmd)`. Only P1 edits `echoguide.ino`, which calls the three modules and prints the shared `Frame` struct as JSON.
- **Backend:** P2 and P3 each put their routes in a FastAPI `APIRouter` inside their own module. P1's `main.py` just includes the routers. Everyone speaks through `audio.say(text)` and `audio.warn(side, urgency)` from `audio.py`.
- **Frontend:** each person builds their panel as its own component (`ObstaclePanel.tsx`, `CameraPanel.tsx`, `SafetyPanel.tsx`, …). P1 places them in `App.tsx`, and P3 adds the `/me` and `/profile` routes.
- **Hardware testing:** test your own sensors on a spare Arduino or the breadboard first, using the pins in `docs/contracts.md`. Move everything onto the single cane Arduino at checkpoint 1.

### Person 1: obstacles + find cane (+ shared core)
- **Hardware:** collect the MLH parts in hour 0 (check for a Grove Base Shield; if there isn't one, get Grove-to-jumper cables). Wire the 3 ultrasonics, sound sensor and buzzer. Build the forward-facing sensor bar and the removable clamp/strap, keeping them clear of the grip and tip. Set up the external 5 V servo supply with a shared ground.
- **Firmware:** `obstacles.cpp`: read the ultrasonics one at a time (Grove single pin, about 30 ms each) and set `-1` when there's no echo. Clap detection gives a `clap` event; the buzz command drives the buzzer. `echoguide.ino`: main loop, the `Frame` struct, JSON output at 20 Hz, command parsing.
- **Backend:** `serial_reader.py` (thread, auto-reconnect, sending commands); **`backend/tools/fake_arduino.py` by hour 3**; `config.py`; `state.py` (SessionState + WebSocket broadcast); `main.py`. `obstacle_warnings.py` (renamed from `warnings.py`): distance → side and urgency, with the beep interval shrinking as obstacles get closer. `audio.py`: Pygame stereo beeps + `pyttsx3` speech; warnings interrupt speech and only the latest speech request is kept. Find-cane: `FIND_CANE` → buzz for 5 s.
- **Frontend:** obstacle panel (three distances, "unknown" shown as such, side highlight), connection status, find-cane button.
- Calibrate the thresholds with a tape measure and record them in `settings.example.json`. Write `docs/wiring.md` with the pin table and photos.

### Person 2: camera + describe
- **Hardware:** wire the 2 servos (signal to D9/D10, power from P1's supply), joystick, touch and light sensors. Build the pan–tilt mount: stack the tilt servo on the pan servo's horn and remove the webcam's clip to cut weight. Test early whether tilt can hold the webcam; if not, do pan only.
- **Firmware:** `camera_ctrl.cpp`: joystick to servos with a deadzone and speed that scales with how far the stick is pushed; release holds position. Limits: pan 20–160°, tilt 40–130°. Touch under 1 s gives a `tap` event. Handle `freeze`/`unfreeze`/`center`. Report `pan`, `tilt` and `light`.
- **Backend:** `detector.py` loads Ultralytics `yolo11n.pt` once. `describer.py`: on `tap`/`DESCRIBE`, send `freeze`, grab a frame (`camera.py`), detect, bucket into left/centre/right thirds, take the top 3, then `audio.say("A chair in the centre, a table on the right")` and `unfreeze`. If light is low, say "Too dark to describe." Never narrate continuously.
- **Frontend:** camera panel with the live `/video` feed, pan/tilt indicator, last description and a Describe button.
- Remove the `useSpeech` call from `App.tsx`, because speech now comes from the backend.

### Person 3: safety + care app
- **Hardware:** wire the button and the accelerometer (I²C, A4/A5). Build the control module beside the handle (joystick, touch and button within thumb reach) and check the cane's weight and balance with everything on it.
- **Firmware:** `safety.cpp`: button held ≥ 2 s gives `sos_hold`; acceleration magnitude above about 2.5 g gives `impact`. Report `button`, `ax`, `ay`, `az`.
- **Backend:** `events.py`: SQLite history and the SOS state machine (triggered → cancel window → notified/failed/pending), with spoken confirmation via `audio.say`. `cane_drop.py`: impact, then about 10 s still, then "The cane may have been dropped. Do you need help?" `notify.py`: Discord webhook, returns delivered/failed. `solana_log.py`: one devnet **Memo** transaction per incident (`sha256` of the event, no personal data) using `solana` + `solders`, run in the background, storing the signature. Location and profile routes (`/api/location`, `/api/profile`).
- **Frontend:** SOS banner with cancel and delivery status. Incident log with "Verified on Solana" Explorer links. Map with Leaflet + OpenStreetMap. Profile/care-notes page seeded with fake data. `/me` phone page with big SOS and Find-my-cane buttons and `navigator.geolocation.watchPosition`. Cloudflare Tunnel or ngrok for remote access and HTTPS.

## Timeline (hours from now)
| Hours | All / milestone |
|---|---|
| 0–1 | Borrow hardware, commit `docs/contracts.md`, each person makes a branch |
| 1–7 | Each person builds and tests their own sensors + firmware + backend module in parallel. P1 ships `fake_arduino.py` and a minimal `main.py`/`audio.py` by hour 3 so P2 and P3 can plug in |
| **7** | **Checkpoint 1:** all sensors on one Arduino, firmware modules merged → backend → dashboard shows live distances and pan/tilt; warnings beep; joystick moves the camera |
| 7–13 | Describe, SOS, cane drop, find cane, profile, location, Solana, Discord |
| 13–17 | Staggered sleep, about 3 h each, with at least one person always awake |
| **17** | **Checkpoint 2:** full demo flow works end-to-end on the mounted cane |
| 17–20 | **Feature freeze.** Bug fixes, calibration, rehearse the demo 3×, record a backup video |
| 20–23 | Devpost (mark the Solana track), slides, photos, 2-minute video |
| 23–24 | Buffer. **Submit by hour 23** |

Stretch goals, only after checkpoint 2: ElevenLabs voice, custom alert rules, showing alerts on the JBL speaker for the audience.

## How to use Claude
- Each person runs Claude Code in their own branch or worktree. Start with: "Read `docs/contracts.md` and this plan; implement Person N's section, starting with X."
- Keep requests small: one module, then test it, then commit. Ask Claude to add a quick runnable check for each module, like `python -m app.describer test.jpg`.
- Never let Claude change the contracts silently. Contract changes go through Person 3 and the team chat.
- Tell Claude which files you own (see the split table) and to leave everyone else's files alone. Shared files (`echoguide.ino`, `main.py`, `App.tsx`) are edited only by P1.
- Merge only at checkpoints, through Person 3. Don't put API keys, wallet keypairs or `settings.json` in git.

## Verification
- **Without hardware:** run `python backend/tools/fake_arduino.py`, `uvicorn app.main:app` and `npm run dev`. The dashboard should update and the beeps should pan left/right.
- **Describe:** tap with a chair in view → the camera freezes and the right sentence is spoken within about 2 s. A warning during speech interrupts it.
- **SOS:** hold the button 2 s → beep → event on the dashboard → cancel works within the window. Without cancelling → Discord message arrives, `notify_status=delivered`, and the Solana signature opens in the Explorer.
- **Cane drop:** drop it on a cushion and leave it still for 10 s → prompt; "I'm OK" dismisses it.
- **Find cane:** clap, or press the button on the `/me` page → buzzer sounds.
- **Location:** `/me` on the phone through the tunnel → its pin appears on the caregiver map.
- **Judge demo** (rehearsed): obstacle approaches from the left → left beep; joystick visibly aims the camera; tap → description; hold → SOS on the dashboard with the Solana link; clap → cane beeps.
