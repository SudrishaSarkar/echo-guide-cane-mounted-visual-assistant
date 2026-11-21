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

## Split

### Person 1: hardware, firmware, physical build
- Collect the MLH parts in hour 0. Check whether there's a Grove Base Shield; if not, get Grove-to-jumper cables.
- `firmware/echoguide/echoguide.ino`:
  - Read the ultrasonics one at a time (Grove ranger, single signal pin, about 30 ms per sensor).
  - Joystick to servos with a deadzone and speed that scales with how far the stick is pushed; release holds the position. Software limits: pan 20–160°, tilt 40–130°.
  - Tap vs 2 s hold detection, clap from a sound-level threshold, impact from acceleration magnitude above about 2.5 g.
  - Handle the buzz/freeze/center commands and emit the JSON above.
- Build the pan–tilt bracket: stack the tilt servo on the pan servo's horn and remove the webcam's clip to save weight. Clamp or strap the attachment to the cane, away from the grip and tip. Wire the power.
- Calibrate distances against a tape measure and record thresholds for `settings.example.json`.
- Write `docs/wiring.md` with the pin table and photos. Own the physical demo and the hardware photos for Devpost.

### Person 2: backend core (Python, FastAPI)
- `serial_reader.py`: background thread with PySerial, parses lines, reconnects automatically. Also add **`backend/tools/fake_arduino.py`**, which replays fake JSON so Person 3 can work without hardware.
- `config.py` (JSON settings, reusing the keys in `settings.example.json`), plus `state.py` (SessionState and WebSocket broadcast).
- `warnings.py` (rename to `obstacle_warnings.py` to avoid clashing with Python's built-in `warnings`): distance → side and urgency. The beep interval shrinks as obstacles get closer.
- `audio.py`: one audio manager. Stereo-panned Pygame beeps plus `pyttsx3` speech, with warnings taking priority and interrupting speech.
- `detector.py` and `describer.py`: Ultralytics `yolo11n.pt`. On a tap: send `freeze`, grab a frame, detect, bucket objects into left/centre/right thirds, take the top 3, speak "A chair in the centre, a table on the right", then `unfreeze`. If the light reading is low, say "Too dark to describe."
- `events.py`: SQLite event history. SOS state machine: triggered → cancel window → notified/failed/pending. Cane-drop check-in in `cane_drop.py`: impact, then about 10 s of no motion, then the prompt.
- `main.py`: all the routes above and the startup threads. Update `requirements.txt` (`pyttsx3`, `httpx`).

### Person 3: app, notifications, Solana, integration lead
- `frontend/` caregiver view, with simple routes and no real authentication:
  - live feed, the three distances, pan/tilt, connection status
  - SOS banner with cancel and delivery status, incident log with "Verified on Solana" explorer links
  - map with the recipient's location (Leaflet + OpenStreetMap, no API key)
  - profile/care-notes page (`/api/profile`), seeded with fake data
- Care-recipient view at `/me`, for the phone: large SOS and Find-my-cane buttons, plus location sharing via `navigator.geolocation.watchPosition` → `POST /api/location`.
- `backend/app/notify.py`: Discord webhook for caregiver alerts (free, instant). Returns delivered/failed for `events.py`.
- `backend/app/solana_log.py`: on each incident, send a devnet transaction using the **Memo program**. The memo holds `sha256(event json)` plus the event type and time, using the `solana` + `solders` libraries and a devnet keypair funded from the faucet. Store the transaction signature on the event, and the dashboard links to the Solana Explorer (devnet). It must not slow down SOS: run it in the background, and if it fails, just show "unverified".
- Remote caregiver access through a Cloudflare Tunnel or ngrok, which also gives the phone the HTTPS it needs to share location.
- Merges to `main` at each checkpoint, and drafts the Devpost write-up.

## Timeline (hours from now)
| Hours | All / milestone |
|---|---|
| 0–1 | Borrow hardware, commit `docs/contracts.md`, each person makes a branch |
| 1–7 | Build in parallel. P2 ships `fake_arduino.py` by hour 3 so P3 isn't blocked |
| **7** | **Checkpoint 1:** real Arduino → backend → dashboard shows live distances and pan/tilt; warnings beep |
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
- Merge only at checkpoints, through Person 3. Don't put API keys, wallet keypairs or `settings.json` in git.

## Verification
- **Without hardware:** run `python backend/tools/fake_arduino.py`, `uvicorn app.main:app` and `npm run dev`. The dashboard should update and the beeps should pan left/right.
- **Describe:** tap with a chair in view → the camera freezes and the right sentence is spoken within about 2 s. A warning during speech interrupts it.
- **SOS:** hold the button 2 s → beep → event on the dashboard → cancel works within the window. Without cancelling → Discord message arrives, `notify_status=delivered`, and the Solana signature opens in the Explorer.
- **Cane drop:** drop it on a cushion and leave it still for 10 s → prompt; "I'm OK" dismisses it.
- **Find cane:** clap, or press the button on the `/me` page → buzzer sounds.
- **Location:** `/me` on the phone through the tunnel → its pin appears on the caregiver map.
- **Judge demo** (rehearsed): obstacle approaches from the left → left beep; joystick visibly aims the camera; tap → description; hold → SOS on the dashboard with the Solana link; clap → cane beeps.
