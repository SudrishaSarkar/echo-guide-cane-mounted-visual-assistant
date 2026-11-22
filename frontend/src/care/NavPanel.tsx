// Caregiver view of walking navigation: where the user is heading, the next
// direction and what the cane last said. The route itself is drawn on the map.
// The text box sends a typed request to the same Gemini assistant the user
// talks to on /me (handy for testing and for judges without a phone).
import { useState, type FormEvent } from "react";
import { askAssistant, postAction, type NavState } from "../api";

export function NavPanel({ nav }: { nav: NavState | null }) {
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const status = nav?.status ?? "idle";
  const active = status === "navigating" || status === "routing";

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try {
      const r = await askAssistant({ text: text.trim() });
      setReply(r.reply);
      setText("");
    } catch {
      setReply("Couldn't reach the assistant.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="care-card" aria-label="Navigation">
      <h2>Navigation</h2>
      {status === "navigating" && nav?.destination ? (
        <>
          <p>
            Heading to <strong>{nav.destination.name}</strong>
            {nav.remaining_m !== null && ` · ${nav.remaining_m} m to go`}
            {nav.off_route && " · off route"}
          </p>
          <p className="nav-next">
            Next: {nav.next_instruction}
            {nav.distance_to_next_m !== null && ` (in ${nav.distance_to_next_m} m)`}
          </p>
        </>
      ) : (
        <p className="hint">
          {status === "routing"
            ? "Finding a route…"
            : status === "arrived" && nav?.destination
              ? `Arrived near ${nav.destination.name}.`
              : status === "error"
                ? nav?.message
                : "Not navigating. The user can say “take me to…” on their phone."}
        </p>
      )}
      {nav?.message && status === "navigating" && <p className="hint">Last said: “{nav.message}”</p>}
      {nav?.demo_maps && <p className="hint">Demo routes: no Google Maps key is set.</p>}
      {active && <button onClick={() => postAction("NAV_STOP")}>Stop navigation</button>}

      <form className="nav-ask" onSubmit={ask}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Test the assistant: take me to the nearest pharmacy"
          aria-label="Typed request to the assistant"
          maxLength={500}
        />
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Ask"}
        </button>
      </form>
      {reply && <p className="hint">Assistant: {reply}</p>}
    </section>
  );
}
