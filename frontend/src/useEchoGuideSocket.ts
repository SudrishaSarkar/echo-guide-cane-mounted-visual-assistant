import { useEffect, useRef, useState } from "react";
import { WS_URL, type SessionState } from "./api";

const INITIAL_STATE: SessionState = {
  mode: "IDLE",
  selected_object: null,
  target_visible: false,
  hand_visible: false,
  instruction: "",
  instruction_id: 0,
  camera_connected: false,
  arduino_connected: false,
};

/** Subscribes to backend /ws state updates and reconnects if the socket drops. */
export function useEchoGuideSocket() {
  const [state, setState] = useState<SessionState>(INITIAL_STATE);
  const [wsConnected, setWsConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let socket: WebSocket;
    let cancelled = false;

    const connect = () => {
      socket = new WebSocket(WS_URL);
      socket.onopen = () => setWsConnected(true);
      socket.onmessage = (event) => setState(JSON.parse(event.data));
      socket.onclose = () => {
        setWsConnected(false);
        if (!cancelled) {
          reconnectTimer.current = setTimeout(connect, 1500);
        }
      };
      socket.onerror = () => socket.close();
    };

    connect();
    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer.current);
      socket?.close();
    };
  }, []);

  return { state, wsConnected };
}
