import { postAction, type Action, type SessionState } from "./api";

const BUTTONS: { action: Action; label: string; hint: string }[] = [
  { action: "DESCRIBE", label: "Describe", hint: "Joystick up" },
  { action: "READ_TEXT", label: "Read text", hint: "Joystick down" },
  { action: "FOCUS_LEFT", label: "Left", hint: "Joystick left" },
  { action: "FOCUS_RIGHT", label: "Right", hint: "Joystick right" },
  { action: "REPEAT", label: "Repeat", hint: "Joystick press" },
];

const FOCUS_LABELS = { all: "Whole scene", left: "Left side", right: "Right side" };

/** P2 panel: joystick menu buttons plus the last description and text read. */
export function CameraPanel({ state }: { state: SessionState }) {
  return (
    <section className="panel">
      <h2>Describe &amp; read</h2>
      <div className="controls">
        {BUTTONS.map(({ action, label, hint }) => (
          <button key={action} title={hint} onClick={() => postAction(action)}>
            {label}
          </button>
        ))}
      </div>
      <div className="status-row">
        <span className="status-label">Focus</span>
        <span className="status-value">{FOCUS_LABELS[state.focus ?? "all"]}</span>
      </div>
      <div className="status-row">
        <span className="status-label">Mode</span>
        <span className="status-value">{state.mode}</span>
      </div>
      <div className="status-row">
        <span className="status-label">Last description</span>
        <span className="status-value">{state.last_description || "—"}</span>
      </div>
      <div className="status-row">
        <span className="status-label">Last text read</span>
        <span className="status-value">{state.last_text_read || "—"}</span>
      </div>
    </section>
  );
}
