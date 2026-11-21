export const API_BASE = "http://localhost:8000";
export const WS_URL = "ws://localhost:8000/ws";
export const VIDEO_URL = `${API_BASE}/video`;

export type Mode = "IDLE" | "SCANNING" | "DESCRIBING" | "SOS_ACTIVE";

export type WarningSide = "left" | "center" | "right" | null;

export interface SosEvent {
  id: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
}

export interface SessionState {
  mode: Mode;
  dist_left: number | null;
  dist_center: number | null;
  dist_right: number | null;
  pan: number;
  tilt: number;
  scanning: boolean;
  warning: string;
  warning_id: number;
  warning_side: WarningSide;
  warning_urgent: boolean;
  instruction: string;
  instruction_id: number;
  sos_active: boolean;
  sos_event_id: number | null;
  sos_status: string;
  sos_triggered_at: string | null;
  last_description: string;
  cane_drop_prompt: boolean;
  recent_events: SosEvent[];
  camera_connected: boolean;
  arduino_connected: boolean;
}

export type Action = "TOUCH_SHORT" | "TOUCH_LONG" | "SOS_CANCEL" | "DESCRIBE";

export async function postAction(action: Action): Promise<void> {
  await fetch(`${API_BASE}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
