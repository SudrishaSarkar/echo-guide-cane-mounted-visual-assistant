// Caregiver alerts: for each `pending` event, play a sound, show an
// operating-system notification ("ALERT: SOS from Alex"), then tell the backend
// it was seen (POST /api/events/{id}/seen). That call is what makes the cane
// say "Your caregiver has been alerted", so only mark an event seen when it was
// really shown: either a system notification appeared, or this page is
// visible on screen. Never use this hook on the /me phone page.
import { useCallback, useEffect, useRef, useState } from "react";
import { sendJson, type EventItem } from "../api";
import { playAlert, soundUnlocked, unlockSound } from "./alertSound";

export type Permission = NotificationPermission | "unsupported";

function currentPermission(): Permission {
  return "Notification" in window ? Notification.permission : "unsupported";
}

function showSystemNotification(event: EventItem): boolean {
  if (!event.notification || currentPermission() !== "granted") return false;
  const { title, body, tag, require_interaction } = event.notification;
  try {
    const n = new Notification(title, { body, tag, requireInteraction: require_interaction });
    n.onclick = () => {
      window.focus();
      n.close();
    };
    return true;
  } catch {
    return false; // e.g. mobile browsers that only allow service-worker notifications
  }
}

export function useCaregiverAlerts(events: EventItem[]) {
  const [permission, setPermission] = useState<Permission>(currentPermission);
  const [soundOn, setSoundOn] = useState(soundUnlocked);
  const [latest, setLatest] = useState<EventItem | null>(null);
  const handled = useRef(new Set<number>());

  const enable = useCallback(async () => {
    unlockSound();
    setSoundOn(true);
    if ("Notification" in window && Notification.permission === "default") {
      setPermission(await Notification.requestPermission());
    }
  }, []);

  const process = useCallback(() => {
    // Oldest first, so notifications appear in the order things happened.
    const pending = events
      .filter((e) => e.notify_status === "pending" && !handled.current.has(e.id))
      .reverse();
    for (const event of pending) {
      const shownAsSystem = showSystemNotification(event);
      const onScreen = document.visibilityState === "visible";
      if (!shownAsSystem && !onScreen) continue; // retry when the tab becomes visible
      handled.current.add(event.id);
      playAlert(event.severity);
      setLatest(event);
      sendJson(`/api/events/${event.id}/seen`, "POST", { by: "caregiver" }).catch(() => {
        handled.current.delete(event.id); // try again on the next update
      });
    }
  }, [events]);

  useEffect(() => {
    process();
    document.addEventListener("visibilitychange", process);
    return () => document.removeEventListener("visibilitychange", process);
  }, [process]);

  return {
    enabled: soundOn && permission !== "default",
    permission,
    enable,
    latest,
    dismissLatest: () => setLatest(null),
  };
}
