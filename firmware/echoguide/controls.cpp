/*
 * controls.cpp — P2 stub (no-op). See controls.h.
 * P2 owns: joystick flicks -> joy_* events, tap/hold/button -> events.
 */
#include "controls.h"
#include <Arduino.h>

void controlsSetup() {}
void controlsUpdate(Frame &) {}
bool controlsCommand(const String &) { return false; }
