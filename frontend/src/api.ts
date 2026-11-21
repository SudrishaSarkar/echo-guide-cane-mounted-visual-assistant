export const API_BASE = "http://localhost:8000";
export const WS_URL = "ws://localhost:8000/ws";
export const VIDEO_URL = `${API_BASE}/video`;

export type Mode =
  | "IDLE"
  | "DESCRIBING"
  | "SEARCHING"
  | "GUIDING"
  | "NEAR_TARGET"
  | "PAUSED"
  | "CONFIRMED";

export type Action =
  | "PREV_OBJECT"
  | "NEXT_OBJECT"
  | "START"
  | "REPEAT"
  | "TOUCH_SHORT"
  | "TOUCH_LONG";

export interface SessionState {
  mode: Mode;
  selected_object: string | null;
  target_visible: boolean;
  hand_visible: boolean;
  instruction: string;
  instruction_id: number;
  camera_connected: boolean;
  arduino_connected: boolean;
}

export async function postAction(action: Action): Promise<void> {
  await fetch(`${API_BASE}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
