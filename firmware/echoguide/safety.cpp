// Safety sensors (Person 3). See safety.h for the events this produces.
//
// Accelerometer: Grove 3-Axis Digital Accelerometer (±1.5 g), chip MMA7660FC,
// I2C address 0x4C, read with Seeed's MMA7660 library. Install it once in the
// Arduino IDE: Library Manager -> search "MMA7660" -> install the Seeed Studio one
// ("Accelerometer_MMA7660", https://github.com/Seeed-Studio/Accelerometer_MMA7660).
//   accelerometer.init()               wakes the chip, but at only 32 samples/s, so
//   setSampleRate(AUTO_SLEEP_120)      we then switch it to 120 samples/s (must be in standby)
// The X/Y/Z readings (6-bit, -32..31, about 21 counts per g) are read with our
// own readCounts() instead of the library's getXYZ(), which shuffles the axes
// when the chip is mid-update (see readCounts below).
//
// The chip can't measure more than ±1.5 g: a hard hit just reads as about
// ±1.45 g (±31 counts). So an impact shows up as an axis pinned at its limit, or
// as a big jump between two readings, not as a large number. Normal cane taps
// can do this too, so the backend only treats an impact as a drop if the cane
// then lies down and stays still (backend/app/cane_drop.py).
//
// Sound: the Grove sound sensor on A3 outputs the amplified sound wave. Loudness
// is its peak-to-peak size per 10 ms window, smoothed into an "envelope", and
// compared against the room's background level (see handleSoundWindow).
//
// All thresholds below are starting values; tune them on the real cane with
// the Serial Monitor / Plotter (see SAFETY_DEBUG).

#include "safety.h"
#include <Wire.h>
#include "MMA7660.h"

// Set to 1 to print "dbg accel/sound" lines for tuning (breaks JSON parsing, so
// only use it with the Serial Monitor/Plotter, not with the backend).
#define SAFETY_DEBUG 0

namespace {

// --- pins and addresses ---
const uint8_t ACCEL_I2C_ADDR = 0x4C;
const uint8_t SOUND_PIN = A3;

MMA7660 accelerometer;

// --- accelerometer tuning ---
const float COUNTS_PER_G = 21.0f;          // same scale as the library's getAcceleration()
const int SATURATED_COUNTS = 30;           // |reading| >= ~1.41 g counts as "at the limit"
const float JUMP_G = 1.0f;                 // change between two readings that counts as a hit
const unsigned long ACCEL_PERIOD_MS = 8;   // ~125 reads/s (the chip updates 120 times/s)
const unsigned long IMPACT_COOLDOWN_MS = 2000;

// --- sound tuning ---
// The Grove sound sensor outputs the amplified sound *wave* (it sits at ~130
// in silence and swings up and down with sound), so loudness is measured as
// the wave's peak-to-peak size in each 10 ms window ("amplitude", 0-1023).
const unsigned long SOUND_WINDOW_MS = 10;
const float ENVELOPE_DECAY = 0.75f;        // smoothed level fades to ~5% in 100 ms
const float QUIET_FLOOR = 8.0f;            // background is never taken as quieter than this
const int CLAP_MIN_AMP = 300;              // a clap must reach this amplitude...
const float CLAP_MIN_RATIO = 4.0f;         // ...and be this many times the room's background
const unsigned long CLAP_MAX_LEN_MS = 250; // still loud after this (incl. echo) = not a clap
const unsigned long CLAP_GAP_MIN_MS = 150; // second clap's start, after the first's start
const unsigned long CLAP_GAP_MAX_MS = 800;
const unsigned long CLAP_COOLDOWN_MS = 1500;
const int LOUD_MIN_AMP = 200;              // a window counts as loud above this amplitude...
const float LOUD_MIN_RATIO = 3.0f;         // ...and this many times the background
const uint8_t LOUD_WINDOWS = 50;           // look at the last 0.5 s (50 x 10 ms)
const uint8_t LOUD_MIN_COUNT = 35;         // "loud" if 70% of those windows were loud
const unsigned long LOUD_COOLDOWN_MS = 5000;

// --- state ---
bool accelOk = false;
unsigned long lastAccelMs = 0;
float lastX = 0, lastY = 0, lastZ = 1;
bool haveLast = false;
unsigned long lastImpactMs = 0;
uint8_t failedReads = 0;

unsigned long windowStartMs = 0;
int windowMin = 1023, windowMax = 0;  // raw readings in the current 10 ms window
float envelope = 0;                   // smoothed loudness
float background = -1;                // room's usual amplitude; < 0 until the first window
bool inSpike = false;
unsigned long spikeStartMs = 0;
unsigned long firstClapMs = 0;        // 0 = no pending first clap
unsigned long lastClapEventMs = 0;
bool loudHistory[LOUD_WINDOWS] = {};  // was each of the last 50 windows loud?
uint8_t loudIndex = 0, loudCount = 0;
unsigned long lastLoudEventMs = 0;

// True if the chip answers on the I2C bus. Checked before each library call,
// because the library can't tell us when the sensor is unplugged.
bool accelPresent() {
  Wire.beginTransmission(ACCEL_I2C_ADDR);
  return Wire.endTransmission() == 0;
}

// Points the chip's register pointer at XOUT (0x00) and checks it answered.
bool selectXout() {
  Wire.beginTransmission(ACCEL_I2C_ADDR);
  Wire.write((uint8_t)0x00);
  return Wire.endTransmission() == 0;
}

int toSigned6(uint8_t raw) {
  int v = raw & 0x3F;
  return (v & 0x20) ? v - 64 : v;
}

// Reads X/Y/Z counts. Returns false if the chip didn't answer.
//
// We don't use the library's getXYZ() here: when the chip flags a byte as
// "mid-update" (alert bit 0x40), getXYZ() reads the *next* byte into the same
// slot, so the axes shift and Z comes back as 0. In testing that gave readings
// like ay=1.05 az=0.00 on a board lying flat, and a false "impact" every 2-3 s.
// Here, if any byte has the alert bit, all three are thrown away and read again.
bool readCounts(int& x, int& y, int& z) {
  for (uint8_t attempt = 0; attempt < 4; attempt++) {
    if (!selectXout()) return false;
    if (Wire.requestFrom(ACCEL_I2C_ADDR, (uint8_t)3) != 3) return false;
    uint8_t rx = Wire.read(), ry = Wire.read(), rz = Wire.read();
    if ((rx | ry | rz) & 0x40) continue;  // chip was updating; read all three again
    x = toSigned6(rx);
    y = toSigned6(ry);
    z = toSigned6(rz);
    return true;
  }
  return false;  // alert on every attempt: skip this sample
}

bool initAccel() {
  if (!accelPresent()) return false;
  accelerometer.init();                          // leaves it at 32 samples/s
  accelerometer.setMode(MMA7660_STAND_BY);       // the rate can only change in standby
  accelerometer.setSampleRate(AUTO_SLEEP_120);   // 120 samples/s, to catch short hits
  accelerometer.setMode(MMA7660_ACTIVE);
  return true;
}

void updateAccel(Frame& frame, unsigned long now) {
  if (now - lastAccelMs < ACCEL_PERIOD_MS) return;
  lastAccelMs = now;

  int cx, cy, cz;
  if (!readCounts(cx, cy, cz)) {
    if (failedReads < 255) failedReads++;
    if (failedReads >= 10) {
      accelOk = false;
      frame.ax = frame.ay = frame.az = 0;  // backend treats ~0 g as "sensor offline"
      if (failedReads == 10 || failedReads == 255) {
        initAccel();                        // try to wake it up
        failedReads = 11;                   // ...and again about every 2 s
      }
    }
    return;
  }
  failedReads = 0;
  accelOk = true;

  float x = cx / COUNTS_PER_G, y = cy / COUNTS_PER_G, z = cz / COUNTS_PER_G;
  frame.ax = x;
  frame.ay = y;
  frame.az = z;

  bool saturated = abs(cx) >= SATURATED_COUNTS || abs(cy) >= SATURATED_COUNTS ||
                   abs(cz) >= SATURATED_COUNTS;
  bool jumped = false;
  if (haveLast) {
    float dx = x - lastX, dy = y - lastY, dz = z - lastZ;
    jumped = (dx * dx + dy * dy + dz * dz) > JUMP_G * JUMP_G;
  }
  lastX = x;
  lastY = y;
  lastZ = z;
  haveLast = true;

  if ((saturated || jumped) && now - lastImpactMs >= IMPACT_COOLDOWN_MS) {
    lastImpactMs = now;
    emitEvent("impact");
  }

#if SAFETY_DEBUG
  Serial.print(F("dbg accel "));
  Serial.print(x); Serial.print(' ');
  Serial.print(y); Serial.print(' ');
  Serial.print(z); Serial.print(' ');
  Serial.println(saturated ? F("LIMIT") : jumped ? F("JUMP") : F("-"));
#endif
}

// Called once per 10 ms window with that window's peak-to-peak amplitude.
void handleSoundWindow(int amp, unsigned long now) {
  if (background < 0) background = amp;
  // Smoothed level: jumps up instantly, fades over ~100 ms, so the dips inside
  // one sound wave don't split a clap or a scream into pieces.
  envelope = max((float)amp, envelope * ENVELOPE_DECAY);
  float bg = max(background, QUIET_FLOOR);

  // Claps: a sudden loud spike that fades (echo included) within 250 ms.
  bool clapLevel = amp >= CLAP_MIN_AMP && amp >= bg * CLAP_MIN_RATIO;
  if (!inSpike && clapLevel) {
    inSpike = true;
    spikeStartMs = now;
  } else if (inSpike && envelope < CLAP_MIN_AMP / 2) {
    inSpike = false;
    bool shortSpike = now - spikeStartMs <= CLAP_MAX_LEN_MS;
    if (shortSpike && now - lastClapEventMs >= CLAP_COOLDOWN_MS) {
      unsigned long gap = spikeStartMs - firstClapMs;
      if (firstClapMs != 0 && gap >= CLAP_GAP_MIN_MS && gap <= CLAP_GAP_MAX_MS) {
        emitEvent("clap");
        lastClapEventMs = now;
        firstClapMs = 0;
      } else {
        firstClapMs = spikeStartMs;  // this could be the first of a pair
      }
    } else if (!shortSpike) {
      firstClapMs = 0;
    }
  }
  if (firstClapMs != 0 && now - firstClapMs > CLAP_GAP_MAX_MS + CLAP_MAX_LEN_MS) {
    firstClapMs = 0;  // single clap: ignore it
  }

  // Loud: most of the last 0.5 s was loud (short dips don't reset it).
  bool loudLevel = amp >= LOUD_MIN_AMP && amp >= bg * LOUD_MIN_RATIO;
  loudCount -= loudHistory[loudIndex];
  loudHistory[loudIndex] = loudLevel;
  loudCount += loudLevel;
  loudIndex = (loudIndex + 1) % LOUD_WINDOWS;
  if (loudCount >= LOUD_MIN_COUNT && now - lastLoudEventMs >= LOUD_COOLDOWN_MS) {
    emitEvent("loud");
    lastLoudEventMs = now;
  }

  // Background follows the room slowly, and only while it's calm.
  if (!inSpike && loudCount < LOUD_WINDOWS / 4) {
    background += (amp - background) * 0.02f;
  }

#if SAFETY_DEBUG
  Serial.print(F("dbg sound amp="));
  Serial.print(amp);
  Serial.print(F(" env="));
  Serial.print((int)envelope);
  Serial.print(F(" bg="));
  Serial.print((int)background);
  Serial.print(F(" loud="));
  Serial.println(loudCount);
#endif
}

void updateSound(Frame& frame, unsigned long now) {
  int level = analogRead(SOUND_PIN);
  if (level < windowMin) windowMin = level;
  if (level > windowMax) windowMax = level;
  if (now - windowStartMs >= SOUND_WINDOW_MS) {
    handleSoundWindow(windowMax - windowMin, now);
    windowMin = 1023;
    windowMax = 0;
    windowStartMs = now;
  }
  frame.sound = (int)envelope;  // smoothed loudness: ~0 silent, up to ~1000
}

}  // namespace

void safetySetup() {
  Wire.begin();  // the library also calls this; calling it twice is harmless
  accelOk = initAccel();
  windowStartMs = lastAccelMs = millis();
}

void safetyUpdate(Frame& frame) {
  unsigned long now = millis();
  updateAccel(frame, now);
  updateSound(frame, now);
}

bool safetyCommand(const String&) {
  return false;
}

bool safetyAccelOk() {
  return accelOk;
}
