/*
 * EchoGuide firmware: reads the joystick and touch sensor and emits one
 * JSON line per reading over USB serial, ~20 Hz:
 *   {"type":"input","seq":42,"joy_x":512,"joy_y":508,"touch":0}
 *
 * Joystick centering, dead zone, and touch debounce are handled on the
 * Python side (backend/app/serial_reader.py), not here — this sketch only
 * reports raw readings.
 *
 * Wiring (Grove Thumb Joystick on an Uno + Grove Base Shield A0 socket):
 *   joystick X -> A0, joystick Y -> A1, touch sensor signal -> D2
 * See docs/wiring.md for exact pins if you're not using a Grove shield.
 */

const int PIN_JOY_X = A0;
const int PIN_JOY_Y = A1;
const int PIN_TOUCH = 2;

const unsigned long SAMPLE_INTERVAL_MS = 50; // ~20 Hz

unsigned long lastSampleAt = 0;
unsigned long seq = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TOUCH, INPUT);
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleAt < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleAt = now;

  int joyX = analogRead(PIN_JOY_X);
  int joyY = analogRead(PIN_JOY_Y);
  int touch = digitalRead(PIN_TOUCH);

  Serial.print("{\"type\":\"input\",\"seq\":");
  Serial.print(seq++);
  Serial.print(",\"joy_x\":");
  Serial.print(joyX);
  Serial.print(",\"joy_y\":");
  Serial.print(joyY);
  Serial.print(",\"touch\":");
  Serial.print(touch);
  Serial.println("}");
}
