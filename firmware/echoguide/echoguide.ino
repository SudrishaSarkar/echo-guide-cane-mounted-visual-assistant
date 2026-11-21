/*
 * EchoGuide firmware (skeleton).
 *
 * Responsibilities:
 *  - Read 3 ultrasonic sensors (left / centre / right), triggered sequentially
 *  - Read thumb joystick + touch sensor + 3-axis accelerometer
 *  - Drive pan/tilt servos directly from joystick deflection (responsive,
 *    independent of the Pi)
 *  - Emit one JSON line per reading over USB serial (~20 Hz):
 *      {"type":"input","seq":42,"joy_x":512,"joy_y":508,"touch":0,
 *       "pan":90,"tilt":45,
 *       "dist_left":85,"dist_center":-1,"dist_right":142,
 *       "ax":0,"ay":0,"az":16384}
 *
 * Pin map TBD in docs/wiring.md.
 */
