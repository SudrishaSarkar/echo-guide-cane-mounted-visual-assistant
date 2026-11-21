import { useEffect } from "react";
import "./App.css";
import { VIDEO_URL, postAction } from "./api";
import { useEchoGuideSocket } from "./useEchoGuideSocket";
import { useSpeech } from "./useSpeech";

function Indicator({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className={`indicator ${ok ? "indicator-ok" : "indicator-bad"}`}>
      {label}: {ok ? "connected" : "disconnected"}
    </span>
  );
}

function Distance({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="status-row">
      <span className="status-label">{label}</span>
      <span className="status-value">
        {value === null ? "unknown" : `${Math.round(value)} cm`}
      </span>
    </div>
  );
}

function App() {
  const { state, wsConnected } = useEchoGuideSocket();
  const { enabled, enable, speakOnChange } = useSpeech();

  useEffect(() => {
    speakOnChange(state.instruction_id, state.instruction);
  }, [state.instruction_id, state.instruction, speakOnChange]);

  return (
    <div className="app">
      <header>
        <h1>EchoGuide</h1>
        <div className="indicators">
          <Indicator label="Server" ok={wsConnected} />
          <Indicator label="Camera" ok={state.camera_connected} />
          <Indicator label="Arduino" ok={state.arduino_connected} />
        </div>
      </header>

      <main>
        <div className="video-pane">
          <img src={VIDEO_URL} alt="Camera feed" className="video-feed" />
        </div>

        <div className="status-pane">
          <div className="status-row">
            <span className="status-label">Mode</span>
            <span className="status-value">{state.mode}</span>
          </div>

          <Distance label="Left" value={state.dist_left} />
          <Distance label="Centre" value={state.dist_center} />
          <Distance label="Right" value={state.dist_right} />

          <div className="status-row">
            <span className="status-label">Camera aim</span>
            <span className="status-value">
              pan {state.pan} / tilt {state.tilt}
              {state.scanning ? " (scanning)" : ""}
            </span>
          </div>

          <div className="status-row">
            <span className="status-label">Warning</span>
            <span className="status-value status-warning">
              {state.warning || "none"}
            </span>
          </div>

          <div className="status-row">
            <span className="status-label">Instruction</span>
            <span className="status-value status-instruction">
              {state.instruction || "..."}
            </span>
          </div>

          {state.sos_active && (
            <div className="status-row sos-active">
              <span className="status-label">SOS</span>
              <span className="status-value">
                {state.sos_status} — cancel within the window
              </span>
            </div>
          )}

          {!enabled && (
            <button className="enable-audio" onClick={enable}>
              Enable audio
            </button>
          )}

          <div className="controls">
            <button onClick={() => postAction("DESCRIBE")}>Describe</button>
            <button onClick={() => postAction("TOUCH_LONG")} className="sos">
              SOS
            </button>
            <button onClick={() => postAction("SOS_CANCEL")} className="cancel">
              Cancel SOS
            </button>
          </div>

          <p className="keyboard-hint">
            Hardware: tap = describe · hold = SOS · tap during SOS window =
            cancel
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;
