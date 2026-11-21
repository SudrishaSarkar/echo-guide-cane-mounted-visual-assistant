# EchoGuide

A cane-mounted visual assistant that detaches for tabletop object finding.

EchoGuide helps a user locate one of a small set of supported tabletop objects
(**bottle**, **cup**, **cell phone**) and guides their hand to it with spoken
directions. It also has a scene mode that describes which supported objects
are currently visible.

**EchoGuide does not provide safe walking routes or dependable obstacle
distances.** Scene mode only describes visible objects.

## Architecture

```
Arduino (joystick + touch) --USB serial--> Python/FastAPI backend
                                                 |
                                   webcam --> OpenCV --> YOLO (objects)
                                                      --> MediaPipe (hand)
                                                 |
                                         guidance rules --> session state
                                                 |
                                   WebSocket /ws + MJPEG /video
                                                 |
                                         React/TypeScript frontend
                                                 |
                                   browser speech synthesis (audio out)
```

Only the Python backend opens the webcam and serial port. The React frontend
only ever talks to the backend over HTTP/WebSocket — it never touches the
camera or serial port directly, so the two programs never compete for the
same hardware.

## Repository layout

```
echoguide/
  backend/
    app/
      __init__.py
      main.py            # FastAPI app, routes, CORS
      config.py           # JSON-backed settings (serial port, thresholds, camera)
      state.py             # Session state machine (IDLE..CONFIRMED) + pub/sub
      serial_reader.py     # Reads Arduino JSON lines, calibrates joystick, debounces touch
      camera.py            # OpenCV capture + MJPEG streaming helpers
      object_detector.py   # Ultralytics YOLO wrapper (bottle/cup/cell phone)
      hand_tracker.py       # MediaPipe Hand Landmarker wrapper
      guidance.py           # Turns target/hand positions into spoken instructions
    requirements.txt
  frontend/               # React + TypeScript + Vite demo UI
  firmware/
    echoguide/
      echoguide.ino        # Arduino sketch: joystick + touch -> JSON over serial
  models/
    hand_landmarker.task   # downloaded, not committed (see below)
  docs/
    wiring.md              # hardware wiring notes
    demo.md                # demo script / test log
  .gitignore
  README.md
```

## Prerequisites

- Git
- Python 3.11
- Node.js 22.12+ (or a newer supported LTS) — required by Vite
- Arduino IDE
- VS Code (recommended)

Check installations:

```powershell
git --version
py -3.11 --version
node --version
npm.cmd --version
```

## Backend setup (Windows PowerShell)

From the project root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

You don't need to activate the virtual environment — invoking its `python.exe`
directly avoids PowerShell execution-policy issues with `Activate.ps1`.

Run the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

Then open:

- API status: http://localhost:8000/health
- Interactive docs: http://localhost:8000/docs

List available serial ports:

```powershell
.\.venv\Scripts\python.exe -m serial.tools.list_ports
```

### Downloading models (not committed to git)

Model weights are large binaries and are excluded via `.gitignore`
(`*.pt`, `*.task`). Each teammate downloads them locally:

- **YOLO nano weights** download automatically on first run of
  `yolo predict model=yolo11n.pt ...` or when `object_detector.py` loads
  `YOLO("yolo11n.pt")`.
- **MediaPipe Hand Landmarker**: download the current Hand Landmarker task
  bundle from the MediaPipe docs and save it to `models/hand_landmarker.task`.

## Frontend setup

```powershell
npm.cmd create vite@latest frontend -- --template react-ts
cd frontend
npm.cmd install
npm.cmd run dev
```

Then open http://localhost:5173.

## Quick pipeline checks (do these before wiring anything)

1. **Object detection** — point the webcam at a bottle, cup, and phone:

   ```powershell
   .\.venv\Scripts\yolo.exe predict model=yolo11n.pt source=0 imgsz=640 show=True
   ```

2. **Hand tracking** — verify the MediaPipe Hand Landmarker Python sample
   runs against `models/hand_landmarker.task`.

3. **Speech** — open the frontend, click **Enable audio**, and confirm the
   exact browser/device you'll use for the demo actually speaks.

4. **Arduino input** — open the sketch, confirm one JSON line per reading is
   printed over serial, then confirm `serial_reader.py` can parse it
   (close the Arduino Serial Monitor first — only one program can own the
   port at a time).

## Supported objects

**bottle**, **cup**, **cell phone** — chosen because common pretrained
detectors support them well. Keys and wallets are not promised; do not add
them without first validating detection or a separate recognition approach.

## Definition of done

See `docs/demo.md` for the test log format: ten object placements, with
success/failure, completion time, and a recorded backup demo video.

## Raspberry Pi deployment

Deploy to the Raspberry Pi only after the full laptop interaction works
end-to-end. See `docs/wiring.md` and the Pi section of the build guide for
setup commands. Resolve Pi package compatibility in its own virtual
environment — don't copy a Windows dependency lock. Benchmark the full
vision loop on the Pi; treat performance as a result to measure, not an
assumption.
