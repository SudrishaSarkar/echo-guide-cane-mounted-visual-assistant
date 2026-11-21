/*
 * controls.h — P2: joystick menu + touch/button events.
 * STUB: minimal no-op so the sketch compiles for P1 hardware testing.
 * P2 replaces this file with real joystick/touch/button handling.
 */
#pragma once

struct Frame;  // defined in echoguide.ino

void controlsSetup();
void controlsUpdate(Frame &f);
bool controlsCommand(const String &cmd);
