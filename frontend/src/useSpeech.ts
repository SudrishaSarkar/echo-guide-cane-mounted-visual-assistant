import { useCallback, useRef, useState } from "react";

/** Wraps browser speech synthesis. Must be unlocked by a user gesture (Enable audio). */
export function useSpeech() {
  const [enabled, setEnabled] = useState(false);
  const lastSpokenId = useRef<number | null>(null);

  const enable = useCallback(() => {
    const utterance = new SpeechSynthesisUtterance(" ");
    window.speechSynthesis.speak(utterance);
    setEnabled(true);
  }, []);

  const speak = useCallback((text: string) => {
    window.speechSynthesis.cancel();
    if (!text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    window.speechSynthesis.speak(utterance);
  }, []);

  /** Call on every state update; only speaks when instruction_id actually changes. */
  const speakOnChange = useCallback(
    (instructionId: number, text: string) => {
      if (!enabled) return;
      if (lastSpokenId.current === instructionId) return;
      lastSpokenId.current = instructionId;
      speak(text);
    },
    [enabled, speak]
  );

  return { enabled, enable, speak, speakOnChange };
}
