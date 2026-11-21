// Shared API types and helpers. Field names follow docs/contracts.md sections 3-4.
//
// URLs are relative: in development vite.config.ts proxies /api, /action, /ws
// and /video to the backend on :8000, so one tunnel on :5173 (HTTPS) serves
// everything, including the /me phone page.

export const VIDEO_URL = "/video";

export function wsUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}

export type Mode = "IDLE" | "DESCRIBING" | "READING" | "SOS_COUNTDOWN" | "SOS_ACTIVE";
export type Side = "left" | "center" | "right";
export type WarningSide = Side | null;

export interface Hazard {
  label: string;
  side: Side;
  closeness: number;
  approaching: boolean;
}

export type SosStatus = "idle" | "active" | "delivered" | "acknowledged" | "cancelled";
export type NotifyStatus = "pending" | "delivered" | "not_sent";
export type Severity = "alert" | "warning" | "update" | "info";

export interface SystemNotification {
  title: string;
  body: string;
  tag: string;
  require_interaction: boolean;
}

export interface EventItem {
  id: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
  notify_status: NotifyStatus;
  severity: Severity;
  notification: SystemNotification | null;
}

export interface Location {
  lat: number;
  lng: number;
  accuracy: number | null;
  ts: string;
}

export interface Activity {
  moving_minutes_last_hour: number;
  last_motion_ts: string | null;
  still_for_s: number | null;
  hourly: { hour_start: string; moving_minutes: number }[];
}

export interface SessionState {
  mode: Mode;
  hazards: Hazard[];
  warning: string;
  warning_id: number;
  warning_side: WarningSide;
  warning_urgent: boolean;
  light: number | null;
  camera_connected: boolean;
  arduino_connected: boolean;
  instruction: string;
  instruction_id: number;
  last_description: string;
  last_text_read: string;
  focus: "all" | "left" | "right";
  sos_active: boolean;
  sos_event_id: number | null;
  sos_status: SosStatus;
  sos_notify_status: NotifyStatus | null;
  sos_triggered_at: string | null;
  sos_countdown: number | null;
  cane_drop_prompt: boolean;
  find_cane_active: boolean;
  activity: Activity | null;
  location: Location | null;
  recent_events: EventItem[];
  profile_updated_at: string | null;
}

export const INITIAL_STATE: SessionState = {
  mode: "IDLE",
  hazards: [],
  warning: "",
  warning_id: 0,
  warning_side: null,
  warning_urgent: false,
  light: null,
  camera_connected: false,
  arduino_connected: false,
  instruction: "",
  instruction_id: 0,
  last_description: "",
  last_text_read: "",
  focus: "all",
  sos_active: false,
  sos_event_id: null,
  sos_status: "idle",
  sos_notify_status: null,
  sos_triggered_at: null,
  sos_countdown: null,
  cane_drop_prompt: false,
  find_cane_active: false,
  activity: null,
  location: null,
  recent_events: [],
  profile_updated_at: null,
};

export type Action =
  | "DESCRIBE"
  | "READ_TEXT"
  | "FOCUS_LEFT"
  | "FOCUS_RIGHT"
  | "REPEAT"
  | "SOS"
  | "SOS_CANCEL"
  | "SOS_ACK"
  | "FIND_CANE"
  | "DROP_OK"
  | "DROP_HELP";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function postAction(action: Action): Promise<void> {
  await request("/action", { method: "POST", body: JSON.stringify({ action }) });
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function sendJson<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  return request<T>(path, { method, body: JSON.stringify(body) });
}
