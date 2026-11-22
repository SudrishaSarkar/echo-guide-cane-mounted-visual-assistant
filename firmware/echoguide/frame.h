// Shared between all firmware modules. Person 1 owns this file; fields match
// docs/contracts.md section 1 (one field per JSON key in the input frame).
//
// .cpp modules can't see types defined inside echoguide.ino, so Frame lives
// here. echoguide.ino defines emitEvent() and prints the Frame as JSON.
#pragma once
#include <Arduino.h>

struct Frame {
  int      joy_x = 512;
  int      joy_y = 512;
  int      touch = 0;    // 0/1 raw
  int      button = 0;   // 0/1 raw (0 if not fitted)
  float    ax = 0, ay = 0, az = 1;  // g
  int      light = 0;    // 0-1023
  int      sound = 0;    // 0-1023
};

// Prints {"type":"event","name":"<name>"} on its own line. Defined in echoguide.ino.
void emitEvent(const char* name);
