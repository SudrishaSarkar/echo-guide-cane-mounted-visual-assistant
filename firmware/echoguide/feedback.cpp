/*
 * feedback.cpp — P1: light sensor reading + non-blocking buzzer patterns.
 * Buzzer is on D7 (contract pin map).
 */
#include "feedback.h"
#include <Arduino.h>

#define PIN_BUZZER 7

static int lastLight = -1;

// --- simple non-blocking pattern sequencer -------------------------------
// Each step: (freq Hz, duration ms, gap ms). freq 0 = silence step.
struct Step { int freq; unsigned long dur; unsigned long gap; };

static const Step PAT_FIND[]  = {{1200,120,80},{1200,120,80},{1200,120,400}};          // repeating
static const Step PAT_SOS[]   = {{880,300,150},{880,300,150},{880,300,600}};           // 3 long
static const Step PAT_OK[]    = {{1046,120,0}};
static const Step PAT_ERROR[] = {{330,120,120},{330,120,0}};

static const Step *activePattern = nullptr;
static int patternLen = 0;
static int patternIdx = 0;
static unsigned long stepStart = 0;
static unsigned long buzzUntil = 0;      // continuous-buzz mode (ms command)
static bool buzzing = false;
static int lastFreq = -1;                // freq currently driven on the buzzer

static void stopAll() {
  noTone(PIN_BUZZER);
  activePattern = nullptr;
  buzzing = false;
  buzzUntil = 0;
  lastFreq = -1;
}

static void startPattern(const Step *steps, int len) {
  stopAll();
  activePattern = steps;
  patternLen = len;
  patternIdx = 0;
  stepStart = millis();
}

void feedbackSetup() {
  pinMode(PIN_BUZZER, OUTPUT);
  noTone(PIN_BUZZER);
}

void feedbackUpdate(Frame &f) {
  lastLight = f.light;
  unsigned long now = millis();

  // Continuous buzz ("buzz" command) takes priority.
  if (buzzing) {
    if (now < buzzUntil) {
      // keep tone on — re-assert in case something else called noTone
      static unsigned long lastToneAt = 0;
      if (now - lastToneAt > 200) { tone(PIN_BUZZER, 1000); lastToneAt = now; }
      return;
    }
    noTone(PIN_BUZZER);
    buzzing = false;
    buzzUntil = 0;
    lastFreq = -1;
    return;
  }

  if (!activePattern) return;
  const Step &s = activePattern[patternIdx];
  if (now - stepStart < s.dur) {
    if (s.freq > 0 && lastFreq != s.freq) { tone(PIN_BUZZER, s.freq); lastFreq = s.freq; }
    return;
  }
  noTone(PIN_BUZZER);
  lastFreq = -1;   // next step must re-assert tone() even at the same freq
  stepStart = now + s.gap;
  patternIdx++;
  if (patternIdx >= patternLen) {
    if (activePattern == PAT_FIND) {
      patternIdx = 0;  // repeat find pattern while active
    } else {
      activePattern = nullptr;  // one-shot patterns end
    }
  }
}

static int jsonInt(const String &line, const String &key, int fallback) {
  String needle = "\"" + key + "\"";
  int i = line.indexOf(needle);
  if (i < 0) return fallback;
  i = line.indexOf(':', i + needle.length());
  if (i < 0) return fallback;
  return line.substring(i + 1).toInt();
}

static String jsonStr(const String &line, const String &key) {
  String needle = "\"" + key + "\"";
  int i = line.indexOf(needle);
  if (i < 0) return "";
  i = line.indexOf(':', i + needle.length());
  if (i < 0) return "";
  i = line.indexOf('\"', i + 1);
  if (i < 0) return "";
  int j = line.indexOf('\"', i + 1);
  if (j < 0) return "";
  return line.substring(i + 1, j);
}

bool feedbackCommand(const String &cmd) {
  if (!cmd.startsWith("{")) return false;

  String c = jsonStr(cmd, "cmd");
  if (c == "buzz") {
    int ms = jsonInt(cmd, "ms", 0);
    stopAll();
    if (ms > 0) {
      buzzing = true;
      buzzUntil = millis() + (unsigned long)ms;
      tone(PIN_BUZZER, 1000);
    }
    return true;
  }
  if (c == "beep") {
    String p = jsonStr(cmd, "pattern");
    if (p == "find")       { startPattern(PAT_FIND, 3); return true; }
    if (p == "sos")        { startPattern(PAT_SOS, 3);  return true; }
    if (p == "ok")         { startPattern(PAT_OK, 1);   return true; }
    if (p == "error")      { startPattern(PAT_ERROR, 2); return true; }
    // Parameterized beeps: {"cmd":"beep","freq":880,"count":3,"dur":120,"gap":70}
    int freq = jsonInt(cmd, "freq", 0);
    if (freq > 0) {
      static Step dyn[8];   // one parameterized pattern at a time
      int count = constrain(jsonInt(cmd, "count", 1), 1, 8);
      int dur   = constrain(jsonInt(cmd, "dur", 120), 20, 2000);
      int gap   = constrain(jsonInt(cmd, "gap", 60), 0, 1000);
      for (int i = 0; i < count; i++) {
        dyn[i] = { freq, (unsigned long)dur, (unsigned long)gap };
      }
      startPattern(dyn, count);
      return true;
    }
    return false;
  }
  return false;
}

// Accessor for other modules / diagnostics.
int feedbackLastLight() { return lastLight; }
