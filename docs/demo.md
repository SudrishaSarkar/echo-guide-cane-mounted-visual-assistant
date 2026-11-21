# Demo script and test log

## Demo script

1. Connect Arduino + webcam, start backend (`uvicorn`) and frontend (`npm run dev`).
2. Open the frontend, click **Enable audio**.
3. Confirm connection indicators: Arduino connected, camera connected.
4. Touch (short) while idle -> scene description is spoken.
5. Joystick left/right -> cycle through bottle / cup / cell phone, each spoken.
6. Joystick up -> start finding the selected object.
7. Move hand on the table -> spoken directional guidance.
8. Hide hand or target briefly -> guidance pauses, then resumes on reacquisition.
9. Get hand near target -> "Your hand is near the object".
10. Touch (short) -> confirm found.
11. Touch (long) at any point -> cancel, return to idle.

## Definition of done checklist

- [ ] A teammate can connect the hardware and start both apps from this README.
- [ ] Joystick selects an object.
- [ ] Selected object's location is spoken.
- [ ] Hand guidance is useful across at least one full approach.
- [ ] Guidance recovers after briefly hiding the hand or the target.
- [ ] Confirmation works and a new search can start immediately after.

## Test log (10 object placements)

| # | Object | Placement | Found? | Time (s) | Failure notes |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |
| 7 | | | | | |
| 8 | | | | | |
| 9 | | | | | |
| 10 | | | | | |

## Backup demo recording

Location/link: _record a backup video before the live demo in case live
hardware fails._
