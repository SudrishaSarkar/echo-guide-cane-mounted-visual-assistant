/*
 * feedback.h — P1: light sensor state + buzzer patterns.
 *
 * Contract (docs/contracts.md section 7):
 *   void feedbackSetup();
 *   void feedbackUpdate(Frame& f);
 *   bool feedbackCommand(const String& cmd);   // true if handled
 *
 * Commands handled here:
 *   {"cmd":"buzz","ms":3000}        continuous buzz for ms (0 = stop)
 *   {"cmd":"beep","pattern":"find"} find | sos | ok | error
 */
#pragma once

struct Frame;  // defined in echoguide.ino

void feedbackSetup();
void feedbackUpdate(Frame &f);
bool feedbackCommand(const String &cmd);
