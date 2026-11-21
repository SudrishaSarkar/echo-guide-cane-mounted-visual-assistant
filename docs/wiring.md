# Wiring notes (skeleton)

To be filled in once exact component models are confirmed.

## Modules

- Control module (beside handle): joystick, touch sensor / SOS button
- Sensing module (below handle, facing forward): 3x ultrasonic sensors,
  movable webcam on pan-tilt bracket, Arduino, Pi, power supply

## Connections

| Connection | Pins | Notes |
|---|---|---|
| Arduino -> laptop/Pi | USB data cable | |
| Webcam -> Pi | USB | |
| Joystick -> Arduino | 2 analog + power + gnd | |
| Touch sensor -> Arduino | 1 digital + power + gnd | |
| Ultrasonic x3 -> Arduino | trig/echo pairs + power + gnd | Trigger sequentially |
| Servos x2 -> Arduino + supply | PWM signal + external PSU + common gnd | Do NOT power servos from Arduino 5V/GPIO |
| Accelerometer -> Arduino | I2C (SDA/SCL) | |

## Serial format

See `firmware/echoguide/echoguide.ino` header comment.
