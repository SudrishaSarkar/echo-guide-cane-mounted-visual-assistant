
import cv2

# Logitech webcam
camera = cv2.VideoCapture(1, cv2.CAP_DSHOW)

# Request a reasonable resolution
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

if not camera.isOpened():
    print("Could not open Logitech camera")
    exit()

print("Logitech camera connected!")
print("Press Q to close.")

while True:
    success, frame = camera.read()

    if not success:
        print("Unable to receive video frame")
        break

    cv2.imshow("EchoGuide - Logitech Live Feed", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()
