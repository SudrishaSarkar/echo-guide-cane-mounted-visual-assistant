/*
 * safety.cpp — P3 stub (no-op). See safety.h.
 * P3 owns: impact / clap / loud events from accel + sound sensor.
 */
#include "safety.h"
#include <Arduino.h>

void safetySetup() {}
void safetyUpdate(Frame &) {}
bool safetyCommand(const String &) { return false; }
