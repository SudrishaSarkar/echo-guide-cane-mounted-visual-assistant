import { useEffect } from "react";
import "./App.css";
import { VIDEO_URL, postAction } from "./api";
import { HazardPanel } from "./HazardPanel";
import { useEchoGuideSocket } from "./useEchoGuideSocket";

function Indicator({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className={`indicator ${ok ? "indicator-ok" : "indicator-bad"}`}>
      {label}: {ok ? "connected" : "disconnected"}
    </span>
  );
}

// P1 layout shell: camera feed + hazard panel + status. P2/P3 add their own
// panel components (CameraPanel, SafetyPanel, ...) next to these.
function App() {
  const { state, wsConnected } = useEchoGuideSocket();

  useEffect(() => {
    document.title = state.warning ? `EchoGuide — ${state.warning}` : "EchoGuide";
  }, [state.warning]);

  return (
    <div className="app">
      <header>
        <h1>EchoGuide</h1>
        <div className="indicators">
          <Indicator label="Server" ok={wsConnected} />
          <Indicator label="Camera" ok={state.camera_connected} />
          <Indicator label="Arduino" ok={state.arduino_connected} />
          <span className="indicator">
            Light: {state.light === null ? "unknown" : state.light}
          </span>
        </div>
      </header>

      <main>
        <div className="video-pane">
          <img src={VIDEO_URL} alt="Camera feed" className="video-feed" />
          <div className="status-row">
            <span className="status-label">Mode</span>
            <span className="status-value">{state.mode}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Last spoken</span>
            <span className="status-value status-instruction">
              {state.instruction || "..."}
            </span>
          </div>
        </div>

        <div className="status-pane">
          <HazardPanel hazards={state.hazards} warning={state.warning} />

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
      </main>
    </div>
  );
}

export default App;
