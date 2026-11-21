export const API_BASE = "http://localhost:8000";
export const WS_URL = "ws://localhost:8000/ws";
export const VIDEO_URL = `${API_BASE}/video`;

export type Mode =
  | "IDLE"
  | "DESCRIBING"
  | "READING"
  | "SOS_COUNTDOWN"
  | "SOS_ACTIVE";

export type HazardSide = "left" | "center" | "right";

export interface Hazard {
  label: string;
  side: HazardSide;
  closeness: number; // 0..1
  approaching: boolean;
}

export interface EventItem {
  id: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
  notify_status?: string | null;
  chain_sig?: string | null;
}

// Mirrors docs/contracts.md section 3. Fields owned by P2/P3 are optional
// until their modules land.
export interface SessionState {
  mode: Mode;
  // P1
  hazards: Hazard[];
  warning: string;
  warning_id: number;
  warning_side: HazardSide | null;
  warning_urgent: boolean;
  light: number | null;
  camera_connected: boolean;
  arduino_connected: boolean;
  instruction: string;
  instruction_id: number;
  // P2
  last_description?: string;
  last_text_read?: string;
  focus?: "all" | "left" | "right";
  // P3
  sos_active?: boolean;
  sos_event_id?: number | null;
  sos_status?: string;
  sos_triggered_at?: string | null;
  sos_countdown?: number | null;
  cane_drop_prompt?: boolean;
  find_cane_active?: boolean;
  activity?: { moving_minutes_last_hour?: number; last_motion_ts?: string | null };
  location?: { lat: number; lng: number; accuracy: number; ts: string } | null;
  recent_events?: EventItem[];
}

// POST /action names (contract section 4)
export type Action =
  | "DESCRIBE"
  | "READ_TEXT"
  | "FOCUS_LEFT"
  | "FOCUS_RIGHT"
  | "REPEAT"
  | "SOS"
  | "SOS_CANCEL"
  | "FIND_CANE"
  | "DROP_OK"
  | "DROP_HELP";

export async function postAction(action: Action): Promise<void> {
  await fetch(`${API_BASE}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
