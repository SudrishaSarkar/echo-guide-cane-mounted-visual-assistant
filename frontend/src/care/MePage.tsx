// /me: the care recipient's phone page. Big, screen-reader-friendly controls:
// SOS (3 s cancellable countdown), find my cane, answer the cane-drop
// check-in, and sharing the phone's location with the caregiver. It vibrates on
// obstacle alerts (Android). It never marks events as seen: only caregiver
// screens do that.
//
// Voice assistant: "Talk" records a short clip and sends it to Gemini
// (/api/assistant), e.g. "take me to the nearest pharmacy". Turn-by-turn
// directions then arrive as SessionState.phone_say and are spoken here with
// the browser's speech synthesis (and on the cane earbuds by the backend).
import { useEffect, useRef, useState } from "react";
import { askAssistant, postAction, sendJson, type SessionState } from "../api";
import { sosIsRecent } from "./format";
import { blobToBase64, startRecording, type Recording } from "./recorder";

const COUNTDOWN_S = 3;
// Navigation needs frequent fixes: one every 2 s is enough at walking speed.
const MIN_SEND_INTERVAL_MS = 2000;
const MAX_LISTEN_MS = 8000;

type Listen = "idle" | "listening" | "thinking";

/** Compass heading in degrees (0 = north), or null if the phone has no compass. */
function useCompass() {
  const heading = useRef<number | null>(null);
  const start = async () => {
    const DOE = window.DeviceOrientationEvent as unknown as
      | { requestPermission?: () => Promise<string> }
      | undefined;
    try {
      if (DOE?.requestPermission && (await DOE.requestPermission()) !== "granted") return;
    } catch {
      return;
    }
    const onOrient = (e: DeviceOrientationEvent) => {
      const ios = (e as DeviceOrientationEvent & { webkitCompassHeading?: number }).webkitCompassHeading;
      if (typeof ios === "number") heading.current = ios;
      else if (e.absolute && e.alpha !== null) heading.current = (360 - e.alpha) % 360;
    };
    window.addEventListener("deviceorientationabsolute", onOrient as EventListener);
    window.addEventListener("deviceorientation", onOrient);
  };
  return { heading, start };
}

function speakAloud(text: string) {
  if (!("speechSynthesis" in window) || !text) return;
  window.speechSynthesis.cancel(); // only the latest message matters
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05;
  window.speechSynthesis.speak(u);
}

export function MePage({ state, connected }: { state: SessionState; connected: boolean }) {
  const [started, setStarted] = useState(false);
  const [locationStatus, setLocationStatus] = useState("Location is not being shared.");
  const [countdown, setCountdown] = useState<number | null>(null);
  const [announce, setAnnounce] = useState("");
  const watchId = useRef<number | null>(null);
  const lastSent = useRef(0);
  const lastWarning = useRef(state.warning_id);
  const lastSay = useRef(state.phone_say_id);
  const compass = useCompass();
  const [listen, setListen] = useState<Listen>("idle");
  const [heard, setHeard] = useState("");
  const recording = useRef<Recording | null>(null);
  const listenTimer = useRef<number | null>(null);
  const nav = state.nav;
  const navigating = nav?.status === "navigating" || nav?.status === "routing";

  const sosOpen = state.sos_status === "active" || state.sos_status === "delivered";

  // Start: location sharing + vibration (both need a user gesture on phones).
  const start = () => {
    setStarted(true);
    lastSay.current = state.phone_say_id;
    navigator.vibrate?.(50);
    speakAloud("EchoGuide is ready. Tap Talk and tell me where you'd like to go.");
    void compass.start();
    if (!("geolocation" in navigator)) {
      setLocationStatus("This phone can't share its location.");
      return;
    }
    if (!window.isSecureContext) {
      setLocationStatus("Location needs HTTPS. Open this page through the tunnel link.");
      return;
    }
    watchId.current = navigator.geolocation.watchPosition(
      (pos) => {
        const now = Date.now();
        if (now - lastSent.current < MIN_SEND_INTERVAL_MS) return;
        lastSent.current = now;
        const { latitude: lat, longitude: lng, accuracy } = pos.coords;
        const raw = compass.heading.current ?? pos.coords.heading;
        const heading = raw === null || Number.isNaN(raw) ? null : raw % 360;
        sendJson("/api/location", "POST", { lat, lng, accuracy, heading })
          .then(() => setLocationStatus(`Sharing location with your caregiver (±${Math.round(accuracy)} m).`))
          .catch(() => setLocationStatus("Couldn't reach EchoGuide to share location."));
      },
      (err) =>
        setLocationStatus(
          err.code === err.PERMISSION_DENIED
            ? "Location permission was denied."
            : "Couldn't get a location fix yet.",
        ),
      { enableHighAccuracy: true, maximumAge: 2_000, timeout: 20_000 },
    );
  };

  useEffect(
    () => () => {
      if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current);
    },
    [],
  );

  // Vibrate on new obstacle warnings.
  useEffect(() => {
    if (state.warning_id === lastWarning.current) return;
    lastWarning.current = state.warning_id;
    if (started && state.warning_id) navigator.vibrate?.(state.warning_urgent ? [200, 100, 200] : 150);
  }, [state.warning_id, state.warning_urgent, started]);

  // Speak directions and assistant replies pushed by the backend.
  useEffect(() => {
    if (state.phone_say_id === lastSay.current) return;
    lastSay.current = state.phone_say_id;
    if (started) speakAloud(state.phone_say);
  }, [state.phone_say_id, state.phone_say, started]);

  // Voice assistant: tap to talk, tap again (or wait 8 s) to send.
  const stopListening = async () => {
    if (listenTimer.current !== null) clearTimeout(listenTimer.current);
    listenTimer.current = null;
    const rec = recording.current;
    recording.current = null;
    if (!rec) return;
    setListen("thinking");
    navigator.vibrate?.(30);
    try {
      const wav = await rec.stop();
      const reply = await askAssistant({ audio_b64: await blobToBase64(wav), mime_type: "audio/wav" });
      setHeard(reply.transcript ? `You said: "${reply.transcript}"` : "");
    } catch {
      speakAloud("Sorry, I couldn't reach EchoGuide.");
    } finally {
      setListen("idle");
    }
  };

  const talk = async () => {
    if (listen === "listening") return stopListening();
    if (listen === "thinking") return;
    window.speechSynthesis?.cancel();
    try {
      recording.current = await startRecording();
    } catch {
      speakAloud("I can't use the microphone. Allow microphone access for this page.");
      return;
    }
    setListen("listening");
    navigator.vibrate?.([30, 50, 30]);
    listenTimer.current = window.setTimeout(() => void stopListening(), MAX_LISTEN_MS);
  };

  useEffect(
    () => () => {
      recording.current?.cancel();
      if (listenTimer.current !== null) clearTimeout(listenTimer.current);
    },
    [],
  );

  // SOS countdown: each tick happens in the timer callback; at 0 the SOS is sent.
  useEffect(() => {
    if (countdown === null) return;
    const timer = setTimeout(() => {
      if (countdown > 1) {
        setCountdown(countdown - 1);
        return;
      }
      setCountdown(null);
      navigator.vibrate?.([400, 100, 400]);
      sendJson("/api/sos", "POST", { source: "me" })
        .then(() => setAnnounce("SOS sent to your caregiver."))
        .catch(() => setAnnounce("Couldn't send the SOS. Call for help another way."));
    }, 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  const spoken =
    countdown !== null ? `Sending SOS in ${countdown}. Press Stop to cancel.` : announce;

  const statusText = !connected
    ? "Not connected to EchoGuide."
    : state.sos_status === "delivered"
      ? "SOS: your caregiver has been alerted."
      : state.sos_status === "active"
        ? "SOS: sending to your caregiver…"
        : state.sos_status === "acknowledged" && sosIsRecent(state)
          ? "Your caregiver has seen your alert."
          : "Connected.";

  return (
    <div className="me">
      <h1>EchoGuide</h1>
      <p role="status" aria-live="polite" className="me-status">
        {statusText}
      </p>
      <p role="alert" aria-live="assertive" className="me-status">
        {spoken}
      </p>

      {!started && (
        <button className="me-btn me-start" onClick={start}>
          Start: share my location
        </button>
      )}
      {started && <p className="me-status">{locationStatus}</p>}

      {started && (
        <button
          className={`me-btn me-talk ${listen === "listening" ? "me-talk-on" : ""}`}
          onClick={() => void talk()}
          disabled={listen === "thinking"}
          aria-label={
            listen === "listening"
              ? "Listening. Tap again when you've finished speaking."
              : listen === "thinking"
                ? "Thinking"
                : "Talk to EchoGuide"
          }
        >
          {listen === "listening" ? "Listening… tap to send" : listen === "thinking" ? "Thinking…" : "Talk"}
        </button>
      )}
      {heard && <p className="me-status">{heard}</p>}

      {nav && nav.status !== "idle" && (
        <div className="me-group" role="group" aria-label="Directions">
          <p className="me-status">
            {nav.status === "routing"
              ? "Finding a route…"
              : nav.status === "navigating"
                ? `To ${nav.destination?.name}: ${nav.next_instruction ?? ""}` +
                  (nav.distance_to_next_m !== null ? ` in ${nav.distance_to_next_m} m` : "") +
                  (nav.remaining_m !== null ? `. ${nav.remaining_m} m to go.` : "")
                : nav.message}
          </p>
          {navigating && (
            <>
              <button className="me-btn me-ok" onClick={() => postAction("NAV_REPEAT")}>
                Repeat direction
              </button>
              <button className="me-btn me-cancel" onClick={() => postAction("NAV_STOP")}>
                Stop directions
              </button>
            </>
          )}
        </div>
      )}

      {state.cane_drop_prompt && (
        <div className="me-group" role="group" aria-label="Was your cane dropped?">
          <p className="me-status">Your cane may have been dropped.</p>
          <button className="me-btn me-ok" onClick={() => postAction("DROP_OK")}>
            I'm OK
          </button>
          <button className="me-btn me-sos" onClick={() => postAction("DROP_HELP")}>
            Get help
          </button>
        </div>
      )}

      {countdown !== null ? (
        <button
          className="me-btn me-cancel"
          onClick={() => {
            setCountdown(null);
            setAnnounce("SOS stopped. Nothing was sent.");
          }}
        >
          Stop SOS ({countdown})
        </button>
      ) : sosOpen ? (
        <button
          className="me-btn me-cancel"
          onClick={() =>
            sendJson("/api/sos/cancel", "POST", { source: "me" })
              .then(() => setAnnounce("SOS cancelled."))
              .catch(() => setAnnounce("Couldn't cancel the SOS."))
          }
        >
          Cancel SOS (false alarm)
        </button>
      ) : (
        <button className="me-btn me-sos" onClick={() => setCountdown(COUNTDOWN_S)}>
          SOS: get help
        </button>
      )}

      <button
        className="me-btn me-find"
        onClick={() =>
          postAction("FIND_CANE")
            .then(() => setAnnounce("Your cane is beeping."))
            .catch(() => setAnnounce("Couldn't reach the cane."))
        }
      >
        Find my cane
      </button>
    </div>
  );
}
