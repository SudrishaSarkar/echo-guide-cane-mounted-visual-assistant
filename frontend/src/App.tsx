import { useEffect } from "react";
import "./App.css";
import { VIDEO_URL, postAction } from "./api";
import { useGuardianSocket } from "./useGuardianSocket";
import { useSpeech } from "./useSpeech";

// GuardianCane caregiver dashboard: camera view, obstacle distances,
// camera aim, SOS events, and controls.
function App() {
  const { state, wsConnected } = useGuardianSocket();
  const { enabled, enable, speakOnChange } = useSpeech();

  useEffect(() => {
    speakOnChange(state.instruction_id, state.instruction);
  }, [state.instruction_id, state.instruction, speakOnChange]);

  return (
    <div className="app">
      <header>
        <h1>GuardianCane</h1>
      </header>
      <main>
        <div className="video-pane">
          <img src={VIDEO_URL} alt="Camera feed" className="video-feed" />
        </div>
        <div className="status-pane">
          <p>Dashboard UI to be implemented.</p>
        </div>
      </main>
    </div>
  );
}

export default App;
