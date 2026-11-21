// SOS banner (with Acknowledge / Cancel), cane-drop status, find-my-cane, and
// the "Enable alerts" control for sound + system notifications.
import { postAction, type EventItem, type SessionState } from "../api";
import { clockTime, eventTitle, sosIsRecent } from "./format";
import type { Permission } from "./useCaregiverAlerts";

interface Props {
  state: SessionState;
  alertsEnabled: boolean;
  permission: Permission;
  onEnableAlerts: () => void;
  latest: EventItem | null;
  onDismissLatest: () => void;
}

function sosSource(state: SessionState): string {
  const sos = state.recent_events.find((e) => e.id === state.sos_event_id);
  const source = sos?.payload.source;
  return typeof source === "string" ? source.replace("_", " ") : "unknown";
}

export function SafetyPanel(props: Props) {
  const { state, latest } = props;
  const sosOpen = state.sos_status === "active" || state.sos_status === "delivered";
  // The SOS banner and its resolved message cover SOS events; the "latest" box is
  // for the other alerts (cane drop, no movement, all-clears).
  const showLatest = latest && latest.severity !== "info" && latest.type !== "SOS";

  return (
    <section className="care-card safety" aria-label="Safety">
      <h2>Safety</h2>

      {!props.alertsEnabled && (
        <button className="btn btn-primary" onClick={props.onEnableAlerts}>
          Enable alerts (sound + system notifications)
        </button>
      )}
      {props.permission === "denied" && (
        <p className="hint warn">
          System notifications are blocked for this site. Allow them in the browser's site
          settings to get "ALERT:" pop-ups. In-app alerts still work.
        </p>
      )}
      {props.permission === "unsupported" && (
        <p className="hint">This browser can't show system notifications; in-app alerts only.</p>
      )}

      {sosOpen && (
        <div className="sos-banner" role="alert">
          <div>
            <strong>SOS</strong> from {sosSource(state)} at {clockTime(state.sos_triggered_at)}
            <div className="hint">
              {state.sos_status === "delivered"
                ? "You've been alerted. Press Acknowledge so they know you've seen it."
                : "Waiting to show on a caregiver screen…"}
            </div>
          </div>
          <div className="row">
            <button className="btn btn-primary" onClick={() => postAction("SOS_ACK")}>
              Acknowledge
            </button>
            <button className="btn" onClick={() => postAction("SOS_CANCEL")}>
              Cancel (false alarm)
            </button>
          </div>
        </div>
      )}
      {state.sos_status === "acknowledged" && sosIsRecent(state) && (
        <p className="ok">SOS acknowledged. The cane told the user you've seen it.</p>
      )}

      {state.cane_drop_prompt && (
        <div className="drop-banner" role="status">
          The cane may have been dropped. Waiting for the user to answer…
        </div>
      )}

      {showLatest && (
        <div className={`latest latest-${latest.severity}`} role="status">
          <span>
            <strong>{latest.notification?.title ?? eventTitle(latest)}</strong>
            {latest.notification && <span className="hint"> {latest.notification.body}</span>}
          </span>
          <button className="btn btn-small" onClick={props.onDismissLatest} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      <div className="row">
        <button className="btn" onClick={() => postAction("FIND_CANE")}>
          {state.find_cane_active ? "Cane is beeping…" : "Find cane (beep)"}
        </button>
        {!sosOpen && (
          <button className="btn btn-danger" onClick={() => postAction("SOS")}>
            Test SOS
          </button>
        )}
      </div>
    </section>
  );
}
