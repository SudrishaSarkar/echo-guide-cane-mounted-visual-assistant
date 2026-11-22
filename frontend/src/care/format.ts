import type { EventItem, SessionState } from "../api";

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** e.g. "Sat, Nov 22, 2026, 3:42:10 PM" for the incident log. */
export function fullDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString([], {
        weekday: "short", year: "numeric", month: "short", day: "numeric",
        hour: "numeric", minute: "2-digit", second: "2-digit",
      });
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

const TITLES: Record<string, string> = {
  SOS: "SOS",
  SOS_ACKNOWLEDGED: "SOS acknowledged",
  SOS_CANCELLED: "SOS cancelled (false alarm)",
  CANE_DROP: "Fall detected: no response, SOS sent",
  DROP_OK: "Cane drop resolved",
  DROP_HELP: "Help requested after cane drop",
  FIND_CANE: "Find-my-cane beeps",
  LOUD_NOISE: "Loud noise nearby",
  NO_MOVEMENT: "No cane movement",
};

export function eventTitle(event: EventItem): string {
  if (event.type === "SOS" && event.payload?.source === "fall") return "SOS (automatic, after a fall)";
  return TITLES[event.type] ?? event.type.replaceAll("_", " ").toLowerCase();
}

/** Extra lines for incidents that carry details (falls, SOS). */
export function eventDetails(event: EventItem): string[] {
  const p = (event.payload ?? {}) as Record<string, unknown>;
  const lines: string[] = [];
  if (event.type === "CANE_DROP") {
    if (p.impact_ts) lines.push(`Impact: ${fullDateTime(String(p.impact_ts))}`);
    if (p.alert_ts) lines.push(`SOS sent: ${fullDateTime(String(p.alert_ts))}`);
    if (p.still_s != null) lines.push(`Lay still for ${p.still_s} s; no answer for ${p.no_answer_s ?? "?"} s`);
    if (p.tilt_deg != null) lines.push(`Cane angle: ${p.tilt_deg}° from upright`);
  }
  if (event.type === "SOS" && p.source) lines.push(`Triggered by: ${String(p.source).replaceAll("_", " ")}`);
  const loc = p.location as { lat?: number; lng?: number } | undefined;
  if (loc && loc.lat != null && loc.lng != null) {
    lines.push(`Location: ${loc.lat.toFixed(5)}, ${loc.lng.toFixed(5)}`);
  }
  return lines;
}

const RECENT_SOS_MS = 10 * 60 * 1000;

/** True if the current SOS was triggered in the last 10 minutes. */
export function sosIsRecent(state: SessionState, now = Date.now()): boolean {
  if (!state.sos_triggered_at) return false;
  return now - new Date(state.sos_triggered_at).getTime() < RECENT_SOS_MS;
}
