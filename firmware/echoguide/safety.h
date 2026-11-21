// Safety sensors (Person 3): Grove 3-Axis Digital Accelerometer ±1.5 g
// (MMA7660FC, I2C 0x4C, via Seeed's MMA7660 library) and Grove sound sensor (A3).
//
// Events (docs/contracts.md section 1):
//   "impact"  an axis pinned at the ±1.5 g limit, or a > 1 g jump between readings
//   "clap"    two short sharp sound spikes within 0.15-0.7 s (double clap)
//   "loud"    sound well above background for >= 0.5 s
// Frame fields: ax, ay, az (g), sound (smoothed loudness: ~0 silent, up to ~1000).
//
// echoguide.ino must call safetyUpdate() every loop() without long delay()s:
// the accelerometer is read ~125 times/s to catch impacts.
#pragma once
#include "frame.h"

void safetySetup();
void safetyUpdate(Frame& frame);
bool safetyCommand(const String& cmd);  // no commands yet; always false
bool safetyAccelOk();                   // false if the accelerometer isn't answering
