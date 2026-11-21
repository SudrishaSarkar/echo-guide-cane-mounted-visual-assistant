/*
 * safety.h — P3: accelerometer impact + sound sensor events.
 * STUB: minimal no-op so the sketch compiles for P1 hardware testing.
 * P3 replaces this file with real impact/clap/loud detection.
 */
#pragma once

struct Frame;  // defined in echoguide.ino

void safetySetup();
void safetyUpdate(Frame &f);
bool safetyCommand(const String &cmd);
