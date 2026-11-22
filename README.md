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
    assistant.py       # Gemini voice assistant ("take me to the nearest pharmacy")
    navigation.py      # Real-time turn-by-turn walking guidance from phone GPS
    maps.py            # Google Places / Routes / Geocoding (fake routes without a key)
    geo.py             # Distance, bearing, polyline and clock-direction helpers
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

## Voice assistant + walking navigation

On the `/me` phone page, press **Start**, then **Talk** and say where you want
to go ("Take me to the nearest pharmacy", "Take me home", "How far is it?",
"Where am I?", "Stop directions"). Gemini understands the spoken request;
Google Maps finds the place and a walking route; the phone's GPS and compass
then drive spoken turn-by-turn directions ("In 40 metres, turn left onto King
Street", "Turn to face your 3 o'clock") on the cane earbuds and the phone,
with automatic re-routing. The caregiver dashboard shows the route on the map.

Keys (both optional for a demo): set `GEMINI_API_KEY` and `GOOGLE_MAPS_API_KEY`
(or `gemini_api_key` / `google_maps_api_key` in `backend/settings.json`). In
Google Cloud, enable Places API (New), Routes API and Geocoding API.

Try it without a phone or keys (from `backend/`):

```
..\.venv\Scripts\python -m uvicorn tools.p3_dev_server:app --port 8000
curl -X POST localhost:8000/dev/location
curl -X POST localhost:8000/api/assistant -H "Content-Type: application/json" -d "{\"text\":\"take me to the nearest pharmacy\"}"
curl -X POST "localhost:8000/dev/walk?speed=3"      # add &detour=1 to test re-routing
```

GPS is only accurate to about 5–15 m, so directions are approximate and never
say a path or crossing is safe. The cane stays the primary mobility aid.
