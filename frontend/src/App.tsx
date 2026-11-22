import "./App.css";
import "./care/care.css";
import { useEffect } from "react";
import { VIDEO_URL, postAction } from "./api";
import { HazardPanel } from "./HazardPanel";
import { CameraPanel } from "./CameraPanel";
import { ActivityChart } from "./care/ActivityChart";
import { IncidentLog } from "./care/IncidentLog";
import { MapPanel } from "./care/MapPanel";
import { MePage } from "./care/MePage";
import { ProfilePage } from "./care/ProfilePage";
import { SafetyPanel } from "./care/SafetyPanel";
import { useCaregiverAlerts } from "./care/useCaregiverAlerts";
import { navigate, usePath } from "./router";
import { useEchoGuideSocket } from "./useEchoGuideSocket";

// Layout owner: Person 1. Panels: camera/status (P1, P2), care (P3, ./care).
// Speech comes from the backend now, so useSpeech is no longer used here.

function Indicator({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className={`indicator ${ok ? "indicator-ok" : "indicator-bad"}`}>
      {label}: {ok ? "connected" : "disconnected"}
    </span>
  );
}

function NavLink({ to, label, path }: { to: string; label: string; path: string }) {
  return (
    <a
      href={to}
      aria-current={path === to ? "page" : undefined}
      onClick={(e) => {
        e.preventDefault();
        navigate(to);
      }}
    >
      {label}
    </a>
  );
}

function CaregiverApp({ path }: { path: string }) {
  const { state, wsConnected } = useEchoGuideSocket();
  const alerts = useCaregiverAlerts(state.recent_events);

  useEffect(() => {
    document.title = state.warning ? `EchoGuide — ${state.warning}` : "EchoGuide";
  }, [state.warning]);

  return (
    <div className="app">
      <header>
        <h1>EchoGuide</h1>
        <nav className="nav">
          <NavLink to="/" label="Dashboard" path={path} />
          <NavLink to="/profile" label="Care profile" path={path} />
        </nav>
        <div className="indicators">
          <Indicator label="Server" ok={wsConnected} />
          <Indicator label="Camera" ok={state.camera_connected} />
          <Indicator label="Arduino" ok={state.arduino_connected} />
          <span className="indicator">
            Light: {state.light === null ? "unknown" : state.light}
          </span>
        </div>
      </header>

      {path === "/profile" ? (
        <ProfilePage />
      ) : (
        <main>
          <div className="video-pane">
            <img src={VIDEO_URL} alt="Camera feed" className="video-feed" />
          </div>

          <div className="status-pane">
            <SafetyPanel
              state={state}
              alertsEnabled={alerts.enabled}
              permission={alerts.permission}
              onEnableAlerts={alerts.enable}
              latest={alerts.latest}
              onDismissLatest={alerts.dismissLatest}
            />

            <HazardPanel hazards={state.hazards} warning={state.warning} />
            <CameraPanel state={state} />

            <div className="status-row">
              <span className="status-label">Mode</span>
              <span className="status-value">{state.mode}</span>
            </div>
            <div className="status-row">
              <span className="status-label">Warning</span>
              <span className="status-value status-warning">{state.warning || "none"}</span>
            </div>
            <div className="status-row">
              <span className="status-label">Last spoken</span>
              <span className="status-value status-instruction">{state.instruction || "..."}</span>
            </div>
            <div className="controls">
              <button onClick={() => postAction("DESCRIBE")}>Describe</button>
              <button onClick={() => postAction("READ_TEXT")}>Read text</button>
              <button onClick={() => postAction("REPEAT")}>Repeat</button>
              <button onClick={() => postAction("SOS")} className="sos">
                SOS
              </button>
              <button onClick={() => postAction("SOS_CANCEL")} className="cancel">
                Cancel SOS
              </button>
              <button onClick={() => postAction("FIND_CANE")}>Find cane</button>
            </div>
            <p className="keyboard-hint">
              Test buttons mirror joystick/touch hardware actions.
            </p>
          </div>

          <div className="care-grid">
            <MapPanel location={state.location} />
            <ActivityChart activity={state.activity} />
            <IncidentLog events={state.recent_events} />
          </div>
        </main>
      )}
    </div>
  );
}

function PhoneApp() {
  const { state, wsConnected } = useEchoGuideSocket();
  return <MePage state={state} connected={wsConnected} />;
}

function App() {
  const path = usePath();
  return path === "/me" ? <PhoneApp /> : <CaregiverApp path={path} />;
}

export default App;
