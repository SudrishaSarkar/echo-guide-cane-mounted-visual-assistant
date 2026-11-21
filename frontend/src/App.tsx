import { useEffect } from "react";
import "./App.css";
import { VIDEO_URL, postAction, type Action } from "./api";
import { useEchoGuideSocket } from "./useEchoGuideSocket";
import { useSpeech } from "./useSpeech";

const KEY_TO_ACTION: Record<string, Action> = {
  ArrowLeft: "PREV_OBJECT",
  ArrowRight: "NEXT_OBJECT",
  ArrowUp: "START",
  ArrowDown: "REPEAT",
  " ": "TOUCH_SHORT",
  Enter: "TOUCH_SHORT",
  Escape: "TOUCH_LONG",
};

function Indicator({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className={`indicator ${ok ? "indicator-ok" : "indicator-bad"}`}>
      {label}: {ok ? "connected" : "disconnected"}
    </span>
  );
}

function App() {
  const { state, wsConnected } = useEchoGuideSocket();
  const { enabled, enable, speakOnChange } = useSpeech();

  useEffect(() => {
    speakOnChange(state.instruction_id, state.instruction);
  }, [state.instruction_id, state.instruction, speakOnChange]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const action = KEY_TO_ACTION[event.key];
      if (!action) return;
      event.preventDefault();
      postAction(action);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

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
          <img src={VIDEO_URL} alt="Annotated camera feed" className="video-feed" />
        </div>

        <div className="status-pane">
          <div className="status-row">
            <span className="status-label">Mode</span>
            <span className="status-value">{state.mode}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Selected object</span>
            <span className="status-value">{state.selected_object ?? "(none)"}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Instruction</span>
            <span className="status-value status-instruction">{state.instruction || "..."}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Target visible</span>
            <span className="status-value">{state.target_visible ? "yes" : "no"}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Hand visible</span>
            <span className="status-value">{state.hand_visible ? "yes" : "no"}</span>
          </div>

          {!enabled && (
            <button className="enable-audio" onClick={enable}>
              Enable audio
            </button>
          )}

          <div className="controls">
            <button onClick={() => postAction("PREV_OBJECT")}>&larr; Previous</button>
            <button onClick={() => postAction("NEXT_OBJECT")}>Next &rarr;</button>
            <button onClick={() => postAction("START")}>Start</button>
            <button onClick={() => postAction("REPEAT")}>Repeat</button>
            <button onClick={() => postAction("TOUCH_SHORT")}>Confirm / Describe</button>
            <button onClick={() => postAction("TOUCH_LONG")} className="cancel">
              Cancel
            </button>
          </div>

          <p className="keyboard-hint">
            Keyboard: ← previous · → next · ↑ start · ↓ repeat · space/enter confirm · esc cancel
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;
