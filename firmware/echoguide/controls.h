// EchoGuide controls module (P2): thumb joystick menu, touch sensor, optional push button.
// See docs/contracts.md sections 1, 6 and 7.
#pragma once

#include <Arduino.h>

struct Frame;

void controlsSetup();
void controlsUpdate(Frame& frame);
bool controlsCommand(const String& cmd);
