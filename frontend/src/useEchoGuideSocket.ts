import { useEffect, useRef, useState } from "react";
import { INITIAL_STATE, wsUrl, type SessionState } from "./api";

/** Subscribes to backend /ws state updates and reconnects if the socket drops. */
export function useEchoGuideSocket() {
  const [state, setState] = useState<SessionState>(INITIAL_STATE);
  const [wsConnected, setWsConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let socket: WebSocket;
    let cancelled = false;

    const connect = () => {
      socket = new WebSocket(wsUrl());
      socket.onopen = () => setWsConnected(true);
      // Merge over the defaults so fields the backend doesn't send yet keep safe values.
      socket.onmessage = (event) => setState({ ...INITIAL_STATE, ...JSON.parse(event.data) });
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
