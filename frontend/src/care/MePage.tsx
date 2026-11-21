// /me: the care recipient's phone page. Big, screen-reader-friendly controls:
// SOS (3 s cancellable countdown), find my cane, answer the cane-drop
// check-in, and sharing the phone's location with the caregiver. It vibrates on
// obstacle alerts (Android). It never marks events as seen: only caregiver
// screens do that.
import { useEffect, useRef, useState } from "react";
import { postAction, sendJson, type SessionState } from "../api";
import { sosIsRecent } from "./format";

const COUNTDOWN_S = 3;
const MIN_SEND_INTERVAL_MS = 5000;

export function MePage({ state, connected }: { state: SessionState; connected: boolean }) {
  const [started, setStarted] = useState(false);
  const [locationStatus, setLocationStatus] = useState("Location is not being shared.");
  const [countdown, setCountdown] = useState<number | null>(null);
  const [announce, setAnnounce] = useState("");
  const watchId = useRef<number | null>(null);
  const lastSent = useRef(0);
  const lastWarning = useRef(state.warning_id);

  const sosOpen = state.sos_status === "active" || state.sos_status === "delivered";

  // Start: location sharing + vibration (both need a user gesture on phones).
  const start = () => {
    setStarted(true);
    navigator.vibrate?.(50);
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
        sendJson("/api/location", "POST", { lat, lng, accuracy })
          .then(() => setLocationStatus(`Sharing location with your caregiver (±${Math.round(accuracy)} m).`))
          .catch(() => setLocationStatus("Couldn't reach EchoGuide to share location."));
      },
      (err) =>
        setLocationStatus(
          err.code === err.PERMISSION_DENIED
            ? "Location permission was denied."
            : "Couldn't get a location fix yet.",
        ),
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 },
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
