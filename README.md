# EchoGuide

A detachable smart cane attachment that detects nearby obstacles, gives
directional audio warnings, and lets the user move a camera with a joystick
to inspect their surroundings. It also provides an accessible SOS control
and a connected caregiver dashboard.

## Repository layout

```
backend/
  app/
    main.py            # FastAPI app, routes, WebSocket
    config.py          # JSON-backed settings
    state.py           # Session state + pub/sub to dashboard
    serial_reader.py   # Arduino JSON lines -> actions/sensors/accel
    camera.py          # OpenCV capture + MJPEG stream
    warnings.py        # Obstacle distances -> directional warning cues
    detector.py        # YOLO wrapper (on-demand scene description)
    describer.py       # Detections -> short spoken description
    events.py          # SQLite event history + SOS + webhook notify
    audio.py           # Pygame stereo warning cues
    cane_drop.py       # Cane-drop check-in (stretch goal)
  requirements.txt
  settings.example.json
frontend/              # React + TypeScript + Vite caregiver dashboard
  src/
    App.tsx
    api.ts
    useEchoGuideSocket.ts
    useSpeech.ts
firmware/
  echoguide/
    echoguide.ino  # Sensors + joystick->servos + touch + accel -> serial JSON
docs/
  wiring.md
  demo.md
models/                # Model weights (downloaded, not committed)
```

Setup and implementation are in progress — see `docs/` for wiring and demo
notes.
