// EchoGuide controls module (P2).
//
// Fills joy_x, joy_y, touch, button in the Frame and emits contract events:
//   joy_up / joy_down / joy_left / joy_right / joy_press  (edge-triggered, ~400 ms debounce)
//   tap (touch < 1 s), hold_start (touch held 1 s), hold_release (released after hold_start)
//   button_hold (push button held >= 2 s, only if fitted)

#include "controls.h"

#include "frame.h"

void emitEvent(const char* name);

namespace {

const uint8_t PIN_JOY_X = A0;
const uint8_t PIN_JOY_Y = A1;
const uint8_t PIN_TOUCH = 5;
const uint8_t PIN_BUTTON = 6;

// Tune these after printing raw values. The Grove thumb joystick rests near 512,
// reaches roughly 200..800 at full deflection, and X jumps to ~1023 when pressed in.
const int JOY_FLICK_THRESHOLD = 180;   // offset from rest that counts as a flick
const int JOY_REARM_THRESHOLD = 80;    // stick must return within this offset to re-arm
const int JOY_PRESS_X = 950;           // raw X at or above this = pressed in
// Mounting as calibrated: X is the up/down axis (down = ~762, up = ~262) and
// Y is the left/right axis (right = ~774, left = ~247). Pressing in still drives X to ~1023.
const bool JOY_AXES_SWAPPED = true;    // true: X = up/down, Y = left/right
const bool JOY_UP_IS_HIGH = false;     // flip if "up" reads as joy_down
const bool JOY_RIGHT_IS_HIGH = true;   // flip if "right" reads as joy_left
const unsigned long JOY_CONFIRM_MS = 40;
const unsigned long JOY_DEBOUNCE_MS = 400;

const bool TOUCH_ACTIVE_HIGH = true;   // Grove touch sensor outputs HIGH when touched
const bool BUTTON_ACTIVE_LOW = true;   // plain button to GND with INPUT_PULLUP
const unsigned long INPUT_DEBOUNCE_MS = 20;
const unsigned long TOUCH_HOLD_MS = 1000;
const unsigned long BUTTON_HOLD_MS = 2000;

enum JoyDir { DIR_NONE, DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT, DIR_PRESS };

int restX = 512;
int restY = 512;

bool joyArmed = true;
JoyDir pendingDir = DIR_NONE;
unsigned long pendingSince = 0;
unsigned long lastJoyEventAt = 0;
bool joyEventSent = false;

struct DebouncedInput {
  bool stable = false;
  bool lastRaw = false;
  unsigned long rawChangedAt = 0;
  unsigned long pressedAt = 0;

  // Returns true when the stable state changed on this call.
  bool update(bool raw, unsigned long now) {
    if (raw != lastRaw) {
      lastRaw = raw;
      rawChangedAt = now;
    }
    if (raw != stable && now - rawChangedAt >= INPUT_DEBOUNCE_MS) {
      stable = raw;
      if (stable) pressedAt = now;
      return true;
    }
    return false;
  }
};

DebouncedInput touchInput;
bool touchHoldSent = false;

DebouncedInput buttonInput;
bool buttonHoldSent = false;

int readRest(uint8_t pin) {
  long sum = 0;
  for (int i = 0; i < 16; i++) {
    sum += analogRead(pin);
    delay(2);
  }
  int rest = sum / 16;
  // Fall back to mid-scale if the stick was deflected or pressed at power-up.
  if (rest < 512 - JOY_REARM_THRESHOLD || rest > 512 + JOY_REARM_THRESHOLD) rest = 512;
  return rest;
}

JoyDir classify(int x, int y) {
  if (x >= JOY_PRESS_X) return DIR_PRESS;

  int dx = JOY_AXES_SWAPPED ? y - restY : x - restX;  // + = right
  int dy = JOY_AXES_SWAPPED ? x - restX : y - restY;  // + = up
  if (!JOY_RIGHT_IS_HIGH) dx = -dx;
  if (!JOY_UP_IS_HIGH) dy = -dy;

  int adx = abs(dx);
  int ady = abs(dy);
  if (adx < JOY_FLICK_THRESHOLD && ady < JOY_FLICK_THRESHOLD) return DIR_NONE;
  if (ady >= adx) return dy > 0 ? DIR_UP : DIR_DOWN;
  return dx > 0 ? DIR_RIGHT : DIR_LEFT;
}

bool nearRest(int x, int y) {
  return x < JOY_PRESS_X && abs(x - restX) <= JOY_REARM_THRESHOLD &&
         abs(y - restY) <= JOY_REARM_THRESHOLD;
}

const char* eventName(JoyDir dir) {
  switch (dir) {
    case DIR_UP: return "joy_up";
    case DIR_DOWN: return "joy_down";
    case DIR_LEFT: return "joy_left";
    case DIR_RIGHT: return "joy_right";
    case DIR_PRESS: return "joy_press";
    default: return nullptr;
  }
}

void updateJoystick(int x, int y, unsigned long now) {
  if (!joyArmed) {
    if (nearRest(x, y)) joyArmed = true;
    return;
  }

  JoyDir dir = classify(x, y);
  if (dir != pendingDir) {
    pendingDir = dir;
    pendingSince = now;
  }
  if (dir == DIR_NONE) return;
  // Pressing in is a clean switch, so it fires without waiting; flicks must hold briefly.
  if (dir != DIR_PRESS && now - pendingSince < JOY_CONFIRM_MS) return;
  if (joyEventSent && now - lastJoyEventAt < JOY_DEBOUNCE_MS) return;

  emitEvent(eventName(dir));
  lastJoyEventAt = now;
  joyEventSent = true;
  joyArmed = false;
  pendingDir = DIR_NONE;
}

void updateTouch(bool raw, unsigned long now) {
  if (touchInput.update(raw, now) && !touchInput.stable) {
    emitEvent(touchHoldSent ? "hold_release" : "tap");
    touchHoldSent = false;
  }
  if (touchInput.stable && !touchHoldSent && now - touchInput.pressedAt >= TOUCH_HOLD_MS) {
    emitEvent("hold_start");
    touchHoldSent = true;
  }
}

void updateButton(bool raw, unsigned long now) {
  if (buttonInput.update(raw, now) && !buttonInput.stable) buttonHoldSent = false;
  if (buttonInput.stable && !buttonHoldSent && now - buttonInput.pressedAt >= BUTTON_HOLD_MS) {
    emitEvent("button_hold");
    buttonHoldSent = true;
  }
}

}  // namespace

void controlsSetup() {
  pinMode(PIN_TOUCH, INPUT);
  pinMode(PIN_BUTTON, BUTTON_ACTIVE_LOW ? INPUT_PULLUP : INPUT);
  restX = readRest(PIN_JOY_X);
  restY = readRest(PIN_JOY_Y);
}

void controlsUpdate(Frame& frame) {
  unsigned long now = millis();
  int x = analogRead(PIN_JOY_X);
  int y = analogRead(PIN_JOY_Y);
  bool touchRaw = digitalRead(PIN_TOUCH) == (TOUCH_ACTIVE_HIGH ? HIGH : LOW);
  bool buttonRaw = digitalRead(PIN_BUTTON) == (BUTTON_ACTIVE_LOW ? LOW : HIGH);

  updateJoystick(x, y, now);
  updateTouch(touchRaw, now);
  updateButton(buttonRaw, now);

  frame.joy_x = x;
  frame.joy_y = y;
  frame.touch = touchInput.stable ? 1 : 0;
  frame.button = buttonInput.stable ? 1 : 0;
}

bool controlsCommand(const String& cmd) {
  (void)cmd;
  return false;
}
