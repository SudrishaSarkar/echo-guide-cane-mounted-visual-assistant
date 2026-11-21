import type { EventItem, SessionState } from "../api";

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
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
  CANE_DROP: "Cane may have been dropped",
  DROP_OK: "Cane drop resolved",
  DROP_HELP: "Help requested after cane drop",
  FIND_CANE: "Find-my-cane beeps",
  LOUD_NOISE: "Loud noise nearby",
  NO_MOVEMENT: "No cane movement",
};

export function eventTitle(event: EventItem): string {
  return TITLES[event.type] ?? event.type.replaceAll("_", " ").toLowerCase();
}

const RECENT_SOS_MS = 10 * 60 * 1000;

/** True if the current SOS was triggered in the last 10 minutes. */
export function sosIsRecent(state: SessionState, now = Date.now()): boolean {
  if (!state.sos_triggered_at) return false;
  return now - new Date(state.sos_triggered_at).getTime() < RECENT_SOS_MS;
}
