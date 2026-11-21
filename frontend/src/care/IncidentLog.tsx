// Incident history: what happened, when, and whether a caregiver screen showed it.
import type { EventItem } from "../api";
import { clockTime, eventTitle } from "./format";

const STATUS_TEXT: Record<string, string> = {
  pending: "not seen yet",
  delivered: "seen",
  not_sent: "",
};

export function IncidentLog({ events }: { events: EventItem[] }) {
  return (
    <section className="care-card" aria-label="Incident log">
      <h2>Incidents</h2>
      {events.length === 0 ? (
        <p className="hint">Nothing yet.</p>
      ) : (
        <ul className="incidents">
          {events.map((event) => (
            <li key={event.id} className={`sev-${event.severity}`}>
              <span className="time">{clockTime(event.ts)}</span>
              <span className="what">
                {eventTitle(event)}
                {STATUS_TEXT[event.notify_status] && (
                  <span className={`status status-${event.notify_status}`}>
                    {STATUS_TEXT[event.notify_status]}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
