# EchoGuide: 24-hour implementation plan (3 people, using Claude)

## Context
EchoGuide is a detachable cane attachment for a blind or low-vision user:
- A **fixed webcam** watches ahead and gives left/centre/right **approaching-object alerts** in stereo earbuds.
- A **thumb joystick** works as an audio menu: describe the scene, read text aloud, focus left or right, repeat.
- **Hold the touch sensor** for SOS (spoken countdown, cancellable).
- The **accelerometer** detects a dropped cane and reports activity to the caregiver.
- **Clap** and the cane **buzzes** so it can be found.
- A **caregiver app** shows the live feed, incidents, the user's phone location and the care profile.


**Hardware we have (and nothing else):** Grove thumb joystick, touch sensor, 3-axis accelerometer, sound sensor, light sensor, buzzer, Arduino kit + starter kit (check for a **push button**), breadboard, jumpers, webcam, plus the laptop and stereo earbuds. **No servos and no ultrasonic sensors.** The camera doesn't move, and "closeness" comes from vision, not measured distance.

**Current repo state:**
- `backend/app/camera.py` works: capture plus the `/video` MJPEG stream.
- The other backend modules are one-line stubs.
- The firmware is a header comment.
- The frontend (`App.tsx`, `api.ts`, `useEchoGuideSocket.ts`, `useSpeech.ts`) is a dashboard skeleton using `/ws`, `/video` and `/action`. It still has the old distance and pan/tilt fields, which need replacing.

## Decisions locked for everyone
- **All user audio comes from the backend** (Pygame stereo beeps + `pyttsx3` speech) through wired stereo earbuds. Warnings interrupt speech, and only the latest message is kept, never a queue. The dashboard only shows text. Remove the `useSpeech` call in `App.tsx`.
- **Vision alerts are "approaching object" cues, not distances.** Never say a path is clear or safe. No stair detection.
- **Continuous narration + proximity beeps (changed 2026-11-22).** `narrator.py` keeps speaking what the camera steadily sees ("Person on your right. Chair ahead, close."), re-announcing on change and every ~5 s. Beeps are parking-sensor style for the nearest obstacle only: silence → single → double → continuous. Beeps never interrupt speech; joystick/SOS/drop speech interrupts narration. This replaces "never narrate continuously" below.
- **SOS:** hold the touch sensor ≥ 1 s → "SOS in 3, 2, 1" → keep holding → SOS is **sent immediately** (no extra waiting window; the hold countdown is the accidental-press guard). Releasing during the countdown cancels. A tap after it's sent cancels it, and the caregiver's screen shows "SOS cancelled, false alarm". **Caregiver notifications come from the app itself**: a dashboard banner and alert sound, plus an **operating-system notification titled "ALERT: …"** (or "WARNING: …" / "UPDATE: …") for important events. There's no Discord, SMS or email. "Delivered" means a caregiver dashboard has actually shown the alert. The caregiver's **Acknowledge** button makes the cane say "Your caregiver has seen your alert." If the starter kit has a push button, a 2 s hold on it also triggers SOS.
- **Find cane = double clap or app button → buzzer.** No directions. **Location comes from the user's phone**, so it tracks the person, not the cane.
- **Demo data only.** The profile and medical info are fake. Everything stays on the laptop (SQLite + memory); no blockchain or external messaging.
- The name is **EchoGuide** everywhere.

Exact message formats, pins and file boundaries are in **`docs/contracts.md`**.

## Split: one feature per person, from sensor to screen

| | **P1: Vision alerts + core** | **P2: Joystick menu + describe/read** | **P3: Safety + care app** |
|---|---|---|---|
| **Parts** | Webcam, light sensor, buzzer, stereo earbuds | Thumb joystick, touch sensor (+ push button if available) | Accelerometer, sound sensor |
| **Physical build** | Forward-facing webcam mount on the cane (angled slightly down), cable routing | Control module beside the handle within thumb reach | Removable clamp/strap for the whole attachment, Arduino + breadboard housing, weight/balance check |
| **Firmware file** | `echoguide.ino` (main loop, `Frame`, JSON out, commands) + `feedback.cpp/.h` (light, buzzer patterns) | `controls.cpp/.h` | `safety.cpp/.h` |
| **Backend** | `serial_reader.py`, `tools/fake_arduino.py`, `config.py`, `state.py`, `main.py`, `audio.py`, `detector.py` (shared YOLO loop), `hazards.py` | `describer.py`, `reader.py` (OCR), `controls.py` (event → action mapping, countdown) | `db.py`, `events.py`, `alerts.py`, `cane_drop.py`, `activity.py`, `find_cane.py`, `care.py` (location/profile) |
| **Frontend** | Hazard panel, connection/light status, layout in `App.tsx` | Live feed panel with detection boxes, last description/text, test buttons | SOS banner, incidents, activity, map, profile, `/me` phone page |
| **Extra role** | Integrates the shared files (`.ino`, `main.py`, `App.tsx`) | Demo video + filming | Devpost write-up, merges to `main` |

### Person 1: vision alerts + core
- **Hardware:** mount the webcam facing forward and slightly down at about knee-to-chest height, firmly, so it doesn't wobble when the cane swings. Wire the light sensor (A2) and buzzer (D7). Plug in the stereo earbuds.
- **Firmware:** `echoguide.ino` has the main loop, the `Frame` struct, 20 Hz JSON output, command parsing and `emitEvent()`. `feedback.cpp` reads the light sensor and plays buzzer patterns (`find`, `sos`, `ok`).
- **Backend core (minimal version by hour 3):** `serial_reader.py` (thread, auto-reconnect, `send(cmd)`); `tools/fake_arduino.py` (fake frames plus keyboard-triggered events, so P2 and P3 can work without hardware); `config.py`; `state.py` (SessionState, WebSocket broadcast, `on_event` registry); `main.py` (startup threads, includes routers).
- **`audio.py`:** `warn(side, urgency)` plays stereo-panned beeps with rate and pitch rising with urgency. `say(text)` uses `pyttsx3` on its own thread and replaces pending speech. `chime(kind)`. Warnings interrupt speech.
- **`detector.py`:** loads `yolo11n.pt` once and runs continuously on the latest frame (aim for ≥ 5 fps). It publishes `latest_detections` for everyone: label, confidence, box and side (left/centre/right third).
- **`hazards.py`:** an object is "close" when its box height is ≥ about 45 % of the frame, or its bottom edge is in the lowest 15 % and its area is ≥ about 12 %. It's "approaching" when its box area grows over about 1 s. Only obstacle-type classes count (person, chair, bench, bicycle, car, dog, suitcase, potted plant, …). Each side has a cooldown so it doesn't beep nonstop. It calls `audio.warn()` and puts `hazards` in the state. Thresholds go in settings; tune them by walking toward real chairs and people.
- **Frontend:** hazard panel (current hazards per side, last alert), camera/Arduino/light status, `App.tsx` layout.
- Update `settings.example.json` with the new keys. Write `docs/wiring.md` (pin table, photos).

### Person 2: joystick menu + describe/read
- **Hardware:** wire the joystick (A0/A1; the Grove thumb joystick reads X ≈ 1023 when pressed in) and the touch sensor (D5), plus the push button (D6) if there is one. Build the control module beside the handle so everything is reachable with the thumb without letting go of the grip.
- **Firmware:** `controls.cpp` turns joystick flicks into `joy_up/down/left/right/press` events, with a deadzone, edge-triggered so one push sends one event, and about 400 ms of debounce. The touch sensor sends `tap` (< 1 s), `hold_start` (held 1 s) and `hold_release`. The button sends `button_hold` (≥ 2 s).
- **`controls.py`:** maps events to actions: up → describe, down → read text, left/right → focus, press → repeat, tap → describe (or cancel an active SOS). It also runs the **SOS hold countdown** (hold_start → speak "SOS in 3, 2, 1" → still held → `events.trigger_sos()`; release first → "SOS cancelled") and keeps the last spoken message for repeat.
- **`describer.py`:** builds a sentence from `detector.latest_detections`, so no extra capture is needed: top 3 objects by size, with position ("A chair in the centre, a door on the right"). Focus left or right only describes that third. If the light reading is low, say "Too dark to describe." Never narrate continuously.
- **`reader.py`:** OCR with EasyOCR on the current frame, returning the lines read top to bottom with the biggest text first. If nothing is found, say "No readable text — try moving closer." Stretch goal: a vision-language API for richer descriptions.
- **Frontend:** live `/video` feed with detection boxes drawn by the backend, last description and last text read, buttons that mimic each joystick action (for testing and for judges).
- Remove `useSpeech` from `App.tsx`, coordinating with P1.

### Person 3: safety + care app
- **Hardware:** wire the accelerometer (I²C, A4/A5) and sound sensor (A3). Build the removable clamp or strap and a housing for the Arduino and breadboard, clear of the grip and tip. Check the full attachment's weight and balance on a real cane.
- **Firmware:** `safety.cpp` sends `clap` on a **double clap** (two sharp spikes within about 0.6 s, to avoid false triggers from voices and doors) and `loud` for sound above the threshold for ≥ 0.5 s. It reports `ax`, `ay`, `az` and `sound` in each frame.
- **Accelerometer: Grove 3-Axis Digital Accelerometer ±1.5 g (MMA7660FC).** I²C address `0x4C`, read with **Seeed's MMA7660 library** (install via Library Manager → "MMA7660"; everyone who compiles the firmware needs it), 6-bit readings (about 0.047 g per step, 21 counts per g), 120 samples/s. It **can't measure hard hits**, because any jolt over 1.5 g just reads as about 1.45 g. So `impact` = an axis at its limit (|reading| ≥ ~1.4 g) **or** a jump of > ~1 g between two readings, read ~125 times/s, with a 2 s cooldown. Normal cane tapping also causes impacts, so an impact alone must never mean "dropped" (see `cane_drop.py`).
- **`db.py` + `events.py`:** SQLite history. SOS state machine: `active` (sent immediately, buzzer + spoken confirmation) → `delivered` (a caregiver dashboard has shown it) → `acknowledged` (caregiver pressed Acknowledge) or `cancelled` (user). If no caregiver screen has shown the alert after 30 s, the cane says so, so the user can get help another way. A `router` handles `/api/events`, `/api/events/{id}/seen`, `/api/sos`, `/api/sos/cancel` and `/api/sos/ack`.
- **`cane_drop.py`:** impact → the cane is **lying down** (gravity across the cane rather than along it, more than about 60° from upright) → **still** for 10 s (every reading within about ±0.1 g of the last). Only then: "The cane may have been dropped. Tap if you're OK, or hold for help", plus buzzer beeps so the cane can be found on the floor. No answer within 30 s puts a `CANE_DROP` alert on the caregiver dashboard (not a full SOS). Which board axis runs along the cane depends on how it's mounted, so record it in settings (`cane_axis`) after building the clamp. **`activity.py`:** cane movement minutes per hour; a `NO_MOVEMENT` event if there's been no motion for X hours during the day (shorten this for the demo). **Double clap → `FIND_CANE`** → buzz for 5 s.
- **Location/profile routes:** `/api/location`, `/api/profile`. Profile data is stored in SQLite, seeded with fake data.
- **Frontend:** **in-app alerts.** When an event arrives with `notify_status: "pending"`, the caregiver dashboard shows a banner, plays an alert sound (needs one click on "Enable alerts" first, because browsers block autoplay), and, if the event has a `notification` (SOS, cane drop, no movement, SOS cancelled), shows an **operating-system notification** with the backend-built title such as "ALERT: SOS from Alex" (`Notification` API; ALERTs stay on screen until clicked; clicking focuses the dashboard). It then calls `POST /api/events/{id}/seen`. Ask for notification permission from the "Enable alerts" button. This works while the dashboard is open in any tab, even in the background or minimized; alerts with the browser fully closed would need Web Push (a stretch goal). Only caregiver views call `seen`; the `/me` page never does. SOS banner with delivery status and **Acknowledge** / Cancel buttons. Incident log showing whether each alert was seen. Activity chart. Map (Leaflet + OpenStreetMap). Profile page (contacts, medical history, meds/allergies, personal info, care notes). **`/me`** phone page with big SOS and Find-my-cane buttons, `watchPosition` → `/api/location`, and `navigator.vibrate` on hazard alerts (Android only, after one tap on a Start button).
- **Relative URLs + Vite proxy:** switch `frontend/src/api.ts` from `http://localhost:8000` to relative paths, and have `vite.config.ts` proxy `/api`, `/action`, `/ws` and `/video` to port 8000. Then one `cloudflared tunnel --url http://localhost:5173` serves the whole app over HTTPS (phones need HTTPS to share location). Tell P1 before changing `api.ts`.

### Avoid merge conflicts
- **Firmware:** the Arduino IDE compiles every `.cpp`/`.h` file in `firmware/echoguide/` together. Each module exposes `xxxSetup()`, `xxxUpdate(Frame&)` and `xxxCommand(cmd)`. Only P1 edits `echoguide.ino`.
- **Backend:** P2 and P3 put their routes in an `APIRouter` in their own modules and subscribe to hardware events with `state.on_event()`. All sound goes through `audio.py`, and all vision through `detector.latest_detections`.
- **Frontend:** one component per panel (`HazardPanel.tsx`, `CameraPanel.tsx`, `SafetyPanel.tsx`, `ProfilePage.tsx`, `MePage.tsx`, …). P1 places them in `App.tsx`.
- **Hardware testing:** test your own sensors on a spare Arduino (you have two kits) using the pins in `docs/contracts.md`. Move everything onto the cane Arduino at checkpoint 1.

## Timeline (hours from now)
| Hours | All / milestone |
|---|---|
| 0–1 | Read this plan and `docs/contracts.md`; each person makes a branch and checks their parts work |
| 1–7 | Build in parallel. P1 ships `fake_arduino.py` and minimal `main.py`, `state.py`, `audio.py` and `detector.py` by hour 3 |
| **7** | **Checkpoint 1:** all sensors on one Arduino → backend → dashboard. Joystick up speaks a description; a chair close on the left makes a left beep; clap buzzes |
| 7–13 | Read text, focus, SOS countdown, cane drop, activity, profile, location, in-app alerts |
| 13–17 | Staggered sleep, about 3 h each, with at least one person always awake |
| **17** | **Checkpoint 2:** full demo flow works on the mounted cane |
| 17–20 | **Feature freeze.** Tune hazard thresholds, fix bugs, rehearse the demo 3×, record a backup video |
| 20–23 | Devpost, slides, photos, 2-minute video |
| 23–24 | Buffer. **Submit by hour 23** |

Stretch goals, only after checkpoint 2: vision-language API descriptions, depth model for better closeness, ElevenLabs voice, custom caregiver alert rules.

## How to use Claude
- Each person runs Claude Code in their own branch or worktree. Start with: "Read `docs/contracts.md` and `docs/plan.md`; implement Person N's section, starting with X. Only edit files I own."
- Keep requests small: one module, then test, then commit. Ask for a quick runnable check per module (e.g. `python -m app.describer test.jpg`, `python -m app.reader sign.jpg`).
- Contract changes go through P3 and the team chat. Never let Claude change `docs/contracts.md` silently.
- Merge only at checkpoints, through P3. Don't put API keys or `settings.json` in git.

## Verification
- **Without hardware:** `python backend/tools/fake_arduino.py` + `uvicorn app.main:app` + `npm run dev`. Keyboard events trigger speech and the dashboard updates.
- **Vision alerts:** walk toward the camera from the left → left beeps that speed up as you get closer. Speech is interrupted by the alert. An empty room gives no beeps.
- **Joystick:** up → description within about 1 s; down at a printed sign → text read aloud; left → only the left third is described; press → repeat.
- **SOS:** hold touch → countdown → keep holding → buzzer + "Sending SOS" → the dashboard shows the banner, plays the sound and shows a browser notification → cane says "Your caregiver has been alerted" (`delivered`). Releasing during the countdown cancels. Caregiver presses Acknowledge → cane says "Your caregiver has seen your alert." A tap after sending → "SOS cancelled" + false-alarm notice on the dashboard. With the dashboard closed, the cane warns after 30 s that no caregiver screen has the alert.
- **Cane drop:** tapping the cane on the floor while walking → no prompt. Lay it flat on the floor and leave it 10 s → prompt + beeps. Hold it upright and still → no prompt.
- **Find cane:** a single clap or talking does nothing; a double clap buzzes.
- **Cane drop:** drop onto a cushion, leave it still 10 s → prompt; a tap dismisses it.
- **Find cane:** clap, or press the button on `/me` → buzzer sounds.
- **Location:** `/me` on the phone through the tunnel → pin appears on the caregiver map.
- **Judge demo** (rehearsed): someone walks toward the cane from the left → left beep; joystick up → "A person on the left, a chair in the centre"; joystick down at a medicine-box label → read aloud; hold touch → SOS appears on the dashboard as an "ALERT:" system notification; clap → cane buzzes.
