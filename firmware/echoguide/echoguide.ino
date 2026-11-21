/*
 * EchoGuide firmware — main sketch (Person 1).
 *
 * Responsibilities (docs/contracts.md):
 *  - Fill a Frame struct from all sensors once per loop
 *  - Emit one JSON "input" frame per line over USB serial at ~20 Hz
 *  - Parse laptop->Arduino commands and dispatch to module handlers
 *  - emitEvent(name) for edge-triggered events detected on the Arduino
 *
 * Other modules (compiled together by the Arduino IDE, one .cpp/.h pair
 * each, owned by P2/P3) plug in via xxxSetup/xxxUpdate/xxxCommand:
 *   feedback.cpp/.h  (P1)  controls.cpp/.h (P2)  safety.cpp/.h (P3)
 */

#include <Wire.h>

// ---------------- Frame (contract section 1) ----------------
struct Frame {
  int      joy_x;
  int      joy_y;
  int      touch;    // 0/1 raw
  int      button;   // 0/1 raw (0 if not fitted)
  float    ax, ay, az; // g
  int      light;    // 0-1023
  int      sound;    // 0-1023
};

// ---------------- Pin map (contract section 6) ----------------
const int PIN_JOY_X   = A0;
const int PIN_JOY_Y   = A1;
const int PIN_LIGHT   = A2;
const int PIN_SOUND   = A3;
const int PIN_SDA     = A4;   // accel I2C (Wire handles these)
const int PIN_SCL     = A5;
const int PIN_TOUCH   = D5;
const int PIN_BUTTON  = D6;
const int PIN_BUZZER  = D7;   // driven by feedback.cpp

const unsigned long FRAME_INTERVAL_MS = 50; // ~20 Hz

// ---------------- Accelerometer (I2C) ----------------
// Grove 3-axis accelerometer is typically MPU6050 @ 0x68.
// If your module is an ADXL345, change ADDRESS/REGS below.
#define ACCEL_ADDR 0x68
#define ACCEL_REG_DATA 0x3B   // ACCEL_XOUT_H .. ACCEL_ZOUT_L (6 bytes)

bool accelOk = false;

int16_t readAccelAxis(uint8_t highReg) {
  Wire.beginTransmission(ACCEL_ADDR);
  Wire.write(highReg);
  Wire.endTransmission(false);
  Wire.requestFrom(ACCEL_ADDR, (uint8_t)2);
  if (Wire.available() < 2) return 0;
  return (Wire.read() << 8) | Wire.read();
}

void readAccel(float &ax, float &ay, float &az) {
  ax = readAccelAxis(ACCEL_REG_DATA)     / 16384.0f;
  ay = readAccelAxis(ACCEL_REG_DATA + 2) / 16384.0f;
  az = readAccelAxis(ACCEL_REG_DATA + 4) / 16384.0f;
}

// ---------------- Module hooks (P2/P3 provide these files) ----------------
void feedbackSetup();
void feedbackUpdate(Frame &f);
bool feedbackCommand(const String &cmd);

void controlsSetup();
void controlsUpdate(Frame &f);
bool controlsCommand(const String &cmd);

void safetySetup();
void safetyUpdate(Frame &f);
bool safetyCommand(const String &cmd);

// ---------------- Events + commands ----------------
void emitEvent(const char *name) {
  Serial.print("{\"type\":\"event\",\"name\":\"");
  Serial.print(name);
  Serial.println("\"}");
}

// Minimal JSON-ish parsing: pulls "key":"value" or "key":number out of a line.
String jsonValue(const String &line, const String &key) {
  String needle = "\"" + key + "\"";
  int i = line.indexOf(needle);
  if (i < 0) return "";
  i = line.indexOf(':', i + needle.length());
  if (i < 0) return "";
  i++;
  while (i < line.length() && (line[i] == ' ' || line[i] == '\"')) i++;
  int j = i;
  while (j < line.length() && line[j] != ',' && line[j] != '}' && line[j] != '\"') j++;
  return line.substring(i, j);
}

void handleCommand(const String &line) {
  String cmd = jsonValue(line, "cmd");
  if (cmd.length() == 0) return;
  bool handled = feedbackCommand(line)
              || controlsCommand(line)
              || safetyCommand(line);
  (void)handled;
}

// ---------------- Main ----------------
unsigned long lastFrameAt = 0;
unsigned long seq = 0;
String rxBuffer;

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);

  pinMode(PIN_TOUCH, INPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);   // button: pressed = LOW -> invert below
  pinMode(PIN_BUZZER, OUTPUT);         // also set in feedbackSetup

  // Probe the accelerometer once.
  Wire.beginTransmission(ACCEL_ADDR);
  accelOk = (Wire.endTransmission() == 0);

  feedbackSetup();
  controlsSetup();
  safetySetup();
}

void loop() {
  // --- laptop -> Arduino commands (non-blocking) ---
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (rxBuffer.length()) {
        handleCommand(rxBuffer);
        rxBuffer = "";
      }
    } else {
      rxBuffer += c;
      if (rxBuffer.length() > 256) rxBuffer = "";  // garbage guard
    }
  }

  // --- sensor read + module updates at ~20 Hz ---
  unsigned long now = millis();
  if (now - lastFrameAt < FRAME_INTERVAL_MS) return;
  lastFrameAt = now;

  Frame f;
  f.joy_x  = analogRead(PIN_JOY_X);
  f.joy_y  = analogRead(PIN_JOY_Y);
  f.touch  = digitalRead(PIN_TOUCH);
  f.button = digitalRead(PIN_BUTTON) == LOW ? 1 : 0;  // pullup: pressed=LOW
  f.light  = analogRead(PIN_LIGHT);
  f.sound  = analogRead(PIN_SOUND);
  if (accelOk) readAccel(f.ax, f.ay, f.az);
  else { f.ax = 0; f.ay = 0; f.az = 1; }

  feedbackUpdate(f);
  controlsUpdate(f);
  safetyUpdate(f);

  Serial.print("{\"type\":\"input\",\"seq\":");
  Serial.print(seq++);
  Serial.print(",\"joy_x\":");   Serial.print(f.joy_x);
  Serial.print(",\"joy_y\":");   Serial.print(f.joy_y);
  Serial.print(",\"touch\":");   Serial.print(f.touch);
  Serial.print(",\"button\":");  Serial.print(f.button);
  Serial.print(",\"ax\":");      Serial.print(f.ax, 3);
  Serial.print(",\"ay\":");      Serial.print(f.ay, 3);
  Serial.print(",\"az\":");      Serial.print(f.az, 3);
  Serial.print(",\"light\":");   Serial.print(f.light);
  Serial.print(",\"sound\":");   Serial.print(f.sound);
  Serial.println("}");
}
