// Alert tones generated with Web Audio, so no sound files are needed.
// Browsers only allow sound after a user gesture: call unlockSound() from a click.
import type { Severity } from "../api";

let context: AudioContext | null = null;

export function unlockSound(): void {
  context ??= new AudioContext();
  void context.resume();
}

export function soundUnlocked(): boolean {
  return context?.state === "running";
}

const PATTERNS: Record<Severity, { freq: number; beeps: number }> = {
  alert: { freq: 880, beeps: 3 },
  warning: { freq: 660, beeps: 2 },
  update: { freq: 520, beeps: 1 },
  info: { freq: 440, beeps: 0 },
};

export function playAlert(severity: Severity): void {
  if (!context || context.state !== "running") return;
  const { freq, beeps } = PATTERNS[severity];
  const start = context.currentTime + 0.05;
  for (let i = 0; i < beeps; i++) {
    const t = start + i * 0.35;
    const osc = context.createOscillator();
    const gain = context.createGain();
    osc.frequency.value = freq;
    osc.type = "square";
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    osc.connect(gain).connect(context.destination);
    osc.start(t);
    osc.stop(t + 0.3);
  }
}
