// Shared between all firmware modules. Person 1 owns this file; fields match
// docs/contracts.md section 1 (one field per JSON key in the input frame).
//
// .cpp modules can't see types defined inside echoguide.ino, so Frame lives
// here. echoguide.ino defines emitEvent() and prints the Frame as JSON.
#pragma once
#include <Arduino.h>

struct Frame {
  uint32_t seq = 0;
  int joyX = 512, joyY = 512;   // P2 (controls)
  uint8_t touch = 0;            // P2
  uint8_t button = 0;           // P2
  float ax = 0, ay = 0, az = 0; // P3 (safety), in g
  int light = 0;                // P1 (feedback)
  int sound = 0;                // P3 (safety), 0-1023
};

// Prints {"type":"event","name":"<name>"} on its own line. Defined in echoguide.ino.
void emitEvent(const char* name);
