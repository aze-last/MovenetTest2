"""Quick script to detect which camera indices are available."""
import cv2

print("Scanning camera indices 0-5...")
for i in range(6):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"  Index {i}: AVAILABLE  ({w}x{h}, read={'OK' if ret else 'FAIL'})")
        cap.release()
    else:
        print(f"  Index {i}: not found")

print("\nDone. Use the available indices as Source in CellWatch.")
