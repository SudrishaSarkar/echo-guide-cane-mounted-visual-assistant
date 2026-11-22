# EchoGuide hardware test cases (laptop-tethered)

Run these before moving anything off the laptop. Every expected result below
comes from the current code (firmware in `firmware/echoguide`, backend in
`backend/app`). If a result differs, write what you saw in the **Result log**
at the bottom.

**Setup used:** Grove sensors -> classic Uno (COM7) -> laptop USB.
Logitech Brio 101 -> laptop USB (`camera_index: 1`). Earbuds = Windows default
audio output. Dashboard at http://localhost:5173, phone page at `/me`.

**Rule:** only one program can own COM7.
- Part A uses the **Arduino IDE Serial Monitor**, so the backend must be **stopped**.
- Parts B–E use the **backend**, so the Serial Monitor must be **closed**.

---

## Part A: Arduino IDE (each sensor on its own)

Open `firmware/echoguide/echoguide.ino`, Board = Arduino Uno, Port = COM7,
Upload, then Serial Monitor at **115200 baud**, line ending **Newline**.
Keep the joystick untouched for the first second after reset (it calibrates
its rest position).

### A1. Power and data stream
| # | Do | Expect |
|---|---|---|
| A1.1 | Open the Serial Monitor, touch nothing | ~20 lines/s of `{"type":"input","seq":...}`; `seq` counts up with no jumps |
| A1.2 | Press the Uno's reset button | Stream restarts at `seq` 0 within ~2 s |
| A1.3 | Watch for 30 s untouched | **No** `event` lines at all (no phantom joystick/touch/clap) |

### A2. Joystick (A0/A1)
| # | Do | Expect |
|---|---|---|
| A2.1 | Rest | `joy_x` and `joy_y` ≈ 500–520 |
| A2.2 | Flick **up**, release | Exactly **one** `joy_up` |
| A2.3 | Flick **down**, release | Exactly **one** `joy_down` (if you get `joy_up`, flip `JOY_UP_IS_HIGH` in `controls.cpp`) |
| A2.4 | Flick **left**, release | Exactly **one** `joy_left` (if reversed, flip `JOY_RIGHT_IS_HIGH`) |
| A2.5 | Flick **right**, release | Exactly **one** `joy_right` |
| A2.6 | Press the stick straight in | One `joy_press`; one raw value jumps to ~1023 |
| A2.7 | Hold the stick fully up for 3 s | Still only **one** `joy_up` (no repeats while held) |
| A2.8 | Flick down 5 times quickly | One event per flick, never a `joy_up` from the spring-back |
| A2.9 | Push diagonally (up-left) | One event for the stronger direction only |
| A2.10 | Gently nudge (less than half travel) | **No** event (deadzone) |

### A3. Touch sensor (D5)
| # | Do | Expect |
|---|---|---|
| A3.1 | Tap quickly (< 1 s) | `touch` goes 1 then 0; one `tap` event |
| A3.2 | Hold 1 s+ | `hold_start` after ~1 s (and no `tap`) |
| A3.3 | Release after A3.2 | `hold_release` |
| A3.4 | Hold for 10 s | Only one `hold_start`, then one `hold_release` on letting go |
| A3.5 | Hover a finger near it without touching | No events |

### A4. Push button (D6), only if fitted
| # | Do | Expect |
|---|---|---|
| A4.1 | Press briefly | `button` 1 then 0, **no** event |
| A4.2 | Hold 2 s+ | One `button_hold` |
| A4.3 | Not fitted | `button` stays 0 forever |

### A5. Light sensor (A2)
| # | Do | Expect |
|---|---|---|
| A5.1 | Normal room | Note the `light` value: ______ |
| A5.2 | Cover with a finger | `light` drops a lot (toward 0) |
| A5.3 | Phone torch on it | `light` rises a lot |
| A5.4 | Mounted position (enclosure) | Still above **150** in a normally lit room. Below 150 the backend says "Too dark to describe" |

### A6. Sound sensor (A3)
| # | Do | Expect |
|---|---|---|
| A6.1 | Quiet room | `sound` ≈ 0–10 |
| A6.2 | Talk normally next to it | `sound` rises, **no** `clap` |
| A6.3 | **Double clap** (two sharp claps, ~0.3 s apart) | One `clap` |
| A6.4 | Single clap | **No** `clap` (it needs two) |
| A6.5 | Double clap from 1 m, then from 2 m | Note the furthest distance that still works: ______ |
| A6.6 | Play loud music / shout for 1 s+ | One `loud` (then at most one per 5 s) |
| A6.7 | Close a door / drop a book | Ideally no `clap` (it is one spike, not two) |

### A7. Accelerometer (I2C, A4/A5)
| # | Do | Expect |
|---|---|---|
| A7.1 | Board flat on the table | One of `ax/ay/az` ≈ ±1.0, the other two ≈ 0 (now `az` ≈ 1.0) |
| A7.2 | Stand the board on each edge | A different axis reads ≈ ±1.0 each time |
| A7.3 | Tap the table hard next to it | One `impact` (at most one per 2 s) |
| A7.4 | Shake it | `impact` events, values jump around |
| A7.5 | **Cane axis**: hold the board how it'll sit on the cane, cane upright | Write the axis that reads ≈ ±1.0: ______. Put it in `settings.json` as `"cane_axis"` (default `"z"`) |

> If you see `accelerometer NOT FOUND` / all zeros: check SDA→A4, SCL→A5, power and GND.

### A8. Buzzer (D7): type into the Serial Monitor send box
| # | Send | Expect |
|---|---|---|
| A8.1 | `{"cmd":"beep","pattern":"ok"}` | 1 short beep |
| A8.2 | `{"cmd":"beep","pattern":"error"}` | 2 short beeps |
| A8.3 | `{"cmd":"beep","pattern":"sos"}` | 3 long beeps, then stops |
| A8.4 | `{"cmd":"beep","pattern":"find"}` | Repeating beeps that **don't stop on their own** |
| A8.5 | `{"cmd":"buzz","ms":0}` | Stops A8.4 immediately |
| A8.6 | `{"cmd":"buzz","ms":2000}` | Continuous tone for 2 s, then silence |
| A8.7 | `hello` (junk) | Nothing happens, stream continues |

### A9. Sensor conflicts
| # | Do | Expect |
|---|---|---|
| A9.1 | Send A8.4 (find) and watch the stream | **No** `clap`, ideally no `loud`. If either appears, move the buzzer away from the sound sensor |
| A9.2 | Flick the joystick hard while watching `ax/ay/az` | No `impact` from normal joystick use |
| A9.3 | Hold touch while flicking the joystick | Both work independently |

---

## Part B: Webcam, text reading, speech (backend running)

Start the backend (`uvicorn app.main:app --port 8000` from `backend/`) and
the dashboard (`npm run dev` in `frontend/`). Close the Serial Monitor first.
Use the dashboard buttons for Part B so the joystick isn't involved yet.

### B1. Camera
| # | Do | Expect |
|---|---|---|
| B1.1 | Open the dashboard | Live feed from the **Brio** (not the laptop camera), with detection boxes |
| B1.2 | Unplug the Brio, wait 5 s, plug back in | Camera shows disconnected, then recovers without restarting the backend |
| B1.3 | Cover the lens | Feed goes black, no crash |

### B2. Read text (dashboard **Read text** button)
| # | Do | Expect |
|---|---|---|
| B2.1 | First read after starting the backend | Slow (10–30 s, OCR loads once), then speaks |
| B2.2 | Printed page, large font, 20–30 cm away, good light | Reads the text correctly, biggest line first |
| B2.3 | Phone screen showing large text | Reads it (watch for glare) |
| B2.4 | Small text at 1 m | Partial or garbled: note the limit |
| B2.5 | Blank wall | "No readable text — try moving closer." |
| B2.6 | Text in a dark room | Garbled or "No readable text": note it |
| B2.7 | Two lines, one big heading and one small | Heading read first |
| B2.8 | Text held at 45° | Note whether it still reads |

### B3. Describe (dashboard **Describe** button)
| # | Do | Expect |
|---|---|---|
| B3.1 | Light sensor uncovered, room lit (> 150) | Sentence naming up to 3 objects with positions, e.g. "A chair in the centre…" |
| B3.2 | Cover the light sensor | "Too dark to describe." |
| B3.3 | Point at an empty wall | A "nothing detected"–style sentence, no made-up objects |
| B3.4 | Person stands left of frame | Mentions the person on the left |

### B4. Continuous narration and proximity beeps (no buttons, just watch and walk)
Narration (`narrator.py`) speaks whatever the camera steadily sees. Beeps
(`hazards.py`) are parking-sensor style, driven by the nearest obstacle only.

| # | Do | Expect |
|---|---|---|
| B4.1 | Point the Brio at a person on the right | Within ~1 s: "Person on your right." Repeated about every 5 s while nothing changes |
| B4.2 | Person moves to the centre | New sentence right away: "Person ahead." |
| B4.3 | Two objects in view (chair centre, person left) | "Chair ahead. Person on your left." (centre first, up to 3 objects) |
| B4.4 | Object flashes into view for under half a second | **Not** spoken (flicker filter) |
| B4.5 | Point at a blank wall | Quiet. Never "path clear". In a dark room: "Too dark to see clearly." about every 15 s |
| B4.6 | Chair far away | Narrated, **no beeps** |
| B4.7 | Walk slowly toward the chair | Silence, then **single** beeps, then **double** beeps, then **continuous** tone. Narration adds ", close" |
| B4.8 | Back away from the chair | The beeps step back down to silence |
| B4.9 | Chair close on the left / right | Beeps in the **left** / **right** ear |
| B4.10 | Joystick up / down while narrating | Narration is cut off and the describe / read result is spoken. Narration resumes afterwards |
| B4.11 | Continuous beeping while narration speaks | Both are heard; beeps do **not** cut off speech |

Tuning in `backend/settings.json`: `beep_single_at` (0.45), `beep_double_at`
(0.62), `beep_continuous_at` (0.80), `narration_repeat_s` (5),
`narration_enabled`, `speech_rate` (-10..10), `describe_min_light` (150).

---|---|---|
| B4.1 | Walk toward a chair, centre of frame | Beeps in **both** ears, faster/higher as you get closer; speech "Object ahead: chair" then "Close ahead: chair" |
| B4.2 | Chair on the left third | Beeps mostly in the **left** ear; "…on your left…" |
| B4.3 | Chair on the right third | **Right** ear |
| B4.4 | Stand still in front of the chair | Beeps don't repeat nonstop (about one per 2.5 s per side) |
| B4.5 | Person walks toward the camera | Person alert |
| B4.6 | Nothing close | Silence: the system must **never** say the path is clear |
| B4.7 | Dark room | Note false alarms (we saw a phantom "cat" at light ≈ 105) |

---

## Part C: Joystick and webcam together (backend running)

| # | Do | Expect |
|---|---|---|
| C1 | Joystick **up** | Same as the Describe button (B3) |
| C2 | Joystick **down** at a page | Same as the Read text button (B2), spoken aloud |
| C3 | Joystick **left** | Describes **only the left third**, and says so: "A person on the left." |
| C4 | Joystick **right** | Describes **only the right third**, and says so: "Four chairs on the right." |
| C5 | Joystick **press** right after C2 | Repeats the text just read |
| C6 | Press before anything has been said | "Nothing to repeat yet." |
| C7 | **Tap** touch (no SOS, no drop prompt) | Describes the scene (same as up) |
| C8 | Down, then up 1 s later | Only the **describe** is spoken (newest request wins, the read is dropped) |
| C9 | Down, wait for the speech to finish, then up | Both are spoken, in order |
| C10 | Joystick up while walking toward a chair | Description is spoken **while** the proximity beeps continue (beeps no longer cut off speech) |
| C11 | Dashboard Describe / Read text / Repeat buttons | Each does exactly what its joystick direction does |
| C12 | Flick in all 4 directions, 1 s apart | 4 separate results, no missing or extra ones |

---

## Part D: Safety features end to end (backend and dashboard running)

On the dashboard, click **Enable alerts** once first (browsers block sound and
notifications until you click).

### D1. SOS with the touch sensor
| # | Do | Expect |
|---|---|---|
| D1.1 | Hold touch and keep holding | ~1 s: "SOS in 3", "2", "1", then "Sending SOS to your caregiver." The dashboard shows an SOS banner, an alert sound, and a system notification "ALERT: SOS from …" |
| D1.2 | Dashboard **Acknowledge** | Earbuds: "Your caregiver has seen your alert." |
| D1.3 | Hold touch, release at "2" | "SOS cancelled", and **no** SOS on the dashboard |
| D1.4 | After an SOS is sent, **tap** touch | "SOS cancelled. Your caregiver will see it was a false alarm." Dashboard shows the false alarm |
| D1.5 | While an SOS is active, hold touch again | "SOS is already active.", no second SOS |
| D1.6 | Send an SOS with the dashboard closed, wait | Spoken warning: "Your alert hasn't reached a caregiver screen yet…" |
| D1.7 | Push button held 2 s (if fitted) | SOS sent immediately, no countdown |
| D1.8 | Dashboard **Cancel SOS** | Same as D1.4 |

### D2. Falls and impacts (accelerometer)

**How it works now.** The Uno sends two kinds of impact:
- `hard_impact`: an axis pinned at the sensor limit (about 1.4 g or more), i.e. a real hit such as the cane hitting the floor. **Instant**: buzzer alarm (30 s), SOS to the caregiver and a logged fall incident, all in the same moment.
- `impact` only: a smaller jolt (handling, joystick use, a bump). **No instant SOS.** It only escalates if the cane then lies still for `cane_drop_inactivity_s` (5 s demo / 10 s default) **and** nobody answers "Are you OK?" within `cane_drop_response_s` (5 s demo / 20 s default).

One **tap** on the touch sensor cancels everything (SOS cancelled, fall resolved, buzzer stops). Picking the cane up does **not** cancel an instant fall alert.

**Setup.** Backend + dashboard running, **Enable alerts** clicked. Watch the backend log for `[arduino] event hard_impact` / `[arduino] event impact`.
With `cane_axis: "z"`: board **flat** = cane upright, board **on its edge** = cane lying down.

| # | Do | Expect (hear / see) | Log shows |
|---|---|---|---|
| D2.1 | Use the joystick normally for 1 min: all 4 flicks + clicks | Descriptions only. **No** beeping, **no** SOS | joystick events; maybe `impact`, **never** `hard_impact` |
| D2.2 | Pick the board up, turn it, put it down normally | Nothing | at most `impact` |
| D2.3 | Tap the table firmly next to the board | Nothing (board stays upright) | maybe `impact` |
| D2.4 | **Throw / drop the board onto the floor** | **Instantly**: loud buzzer, "Fall detected. SOS sent to your caregiver. Tap if you're OK.", SOS banner, **"Fall detected: no response, SOS sent"** in Incidents with date/time | `hard_impact` then `impact` |
| D2.5 | After D2.4, **tap** touch once | "SOS cancelled…", buzzer stops; dashboard shows "SOS cancelled (false alarm)" + "Cane drop resolved" | `tap` |
| D2.6 | After D2.4, pick the board up instead of tapping | Alert **stays** (a bystander picking it up doesn't mean the person is OK) | – |
| D2.7 | Throw it again while an alert is still active | **No** second SOS | `hard_impact` |
| D2.8 | Bump the board (soft `impact`), then lay it on its edge and leave it still | After ~5 s: "The cane may have been dropped. Tap if you're OK, or hold for help." + find beeps. After ~5 s more with no answer: alarm + SOS + fall incident | `impact` only |
| D2.9 | As D2.8, but **tap** at the question | "OK, glad you're all right." No SOS | `tap` |
| D2.10 | As D2.8, but **hold** touch at the question | SOS sent immediately (no 3-2-1 countdown) | `hold_start` |
| D2.11 | No hardware: `curl -X POST http://127.0.0.1:8000/action -H "content-type: application/json" -d "{\"action\":\"SIMULATE_FALL\"}"` | Same as D2.4 (sends a `hard_impact`) | – |

**If something's wrong:**
- D2.1–D2.3 sends an SOS → the log shows `hard_impact` from handling. Raise `SATURATED_COUNTS` in `firmware/echoguide/safety.cpp` (30 → 31) or mount the board more softly.
- D2.4 only shows `impact` (no `hard_impact`) → the throw wasn't hard enough to pin an axis. Throw harder, or lower `SATURATED_COUNTS` (30 → 28). D2.8's check-in still catches it.
- To go back to "always ask first", set `"fall_instant_sos": false` in `backend/settings.json`.

### D3. Find my cane
| # | Do | Expect |
|---|---|---|
| D3.1 | Double clap | Buzzer find beeps for **5 s**, then stops |
| D3.2 | Double clap again while beeping | The 5 s restarts |
| D3.3 | Dashboard **Find cane** button | Same 5 s beeping |
| D3.4 | `/me` page Find-my-cane button (phone) | Same |
| D3.5 | Find beeping does **not** trigger another find (buzzer → sound sensor loop) | Stops after 5 s |

---

## Part E: Real-use run (everything at once)

| # | Do | Expect |
|---|---|---|
| E1 | Hold the board and webcam like a cane, walk for 2 min, tapping and swinging normally | **No** SOS, **no** drop prompt, **no** stray joystick actions. Hazard beeps only near real obstacles |
| E2 | During E1: flick up, flick down at a sign, press | Each works mid-walk |
| E3 | During E1: someone double-claps behind you | Buzzer beeps |
| E4 | Run the full demo script in `docs/demo.md` start to finish | No restarts needed |
| E5 | Leave everything running 15 min | Still connected (`arduino_connected`, `camera_connected`), no growing lag |

---

## Result log

| Test | Pass/Fail | What happened / value noted | Date |
|---|---|---|---|
| | | | |

**Known so far (2026-11-22):**
- The joystick up/down was reversed for the current orientation, so `JOY_UP_IS_HIGH` was flipped to `true`. Re-check A2 after mounting on the cane.
- The room light read ≈ 105, below the 150 describe cut-off, which caused "Too dark to describe" and phantom "cat" hazards. Retest B3/B4 in good light.
- First OCR read is slow (model load); later ones are quick.
- pyttsx3 only spoke the **first** sentence on Windows, then went silent. Speech now uses Windows SAPI directly.
- Hazard alerts changed: no more cooldown beeps or "Close ahead: …" speech. Continuous narration plus parking-sensor beeps instead (B4).
