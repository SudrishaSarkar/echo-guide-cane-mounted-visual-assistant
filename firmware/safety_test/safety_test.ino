// Standalone test for safety.cpp (Person 3), for use before P1's echoguide.ino exists.
//
// 1. Copy the three shared files next to this sketch (the copies are gitignored;
//    always edit the originals in ../echoguide). From the firmware/ folder:
//      PowerShell:  Copy-Item echoguide\frame.h,echoguide\safety.h,echoguide\safety.cpp safety_test\ -Force
//      Git Bash:    cp echoguide/{frame.h,safety.h,safety.cpp} safety_test/
// 2. Plug the Grove ±1.5 g accelerometer (MMA7660FC) into an I2C socket, or wire
//    SDA=A4, SCL=A5 on an Uno, and the sound sensor into A3.
//    Install Seeed's MMA7660 library once: Library Manager -> search "MMA7660".
// 3. Upload, open the Serial Monitor at 115200 baud.
//
// It prints the same JSON as the real firmware (docs/contracts.md section 1),
// 20 frames a second plus event lines. Try: hold upright (one axis ~1.00),
// lay flat, tap the table hard ("impact"), double clap ("clap"), play loud
// music for a second ("loud"). For graphs, set SAFETY_DEBUG to 1 in safety.cpp
// and use the Serial Plotter instead.

#include "frame.h"
#include "safety.h"

Frame frame;
unsigned long lastPrintMs = 0;

void emitEvent(const char* name) {
  Serial.print(F("{\"type\":\"event\",\"name\":\""));
  Serial.print(name);
  Serial.println(F("\"}"));
}

void setup() {
  Serial.begin(115200);
  safetySetup();
  Serial.println(safetyAccelOk() ? F("# accelerometer OK")
                                 : F("# accelerometer NOT FOUND (no MMA7660 at 0x4C): check SDA/SCL and power"));
}

void loop() {
  safetyUpdate(frame);
  unsigned long now = millis();
  if (now - lastPrintMs >= 50) {
    lastPrintMs = now;
    frame.seq++;
    Serial.print(F("{\"type\":\"input\",\"seq\":"));
    Serial.print(frame.seq);
    Serial.print(F(",\"ax\":"));
    Serial.print(frame.ax, 2);
    Serial.print(F(",\"ay\":"));
    Serial.print(frame.ay, 2);
    Serial.print(F(",\"az\":"));
    Serial.print(frame.az, 2);
    Serial.print(F(",\"sound\":"));
    Serial.print(frame.sound);
    Serial.println(F("}"));
  }
}
