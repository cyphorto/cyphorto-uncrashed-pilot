"""Make synthetic 'Mavic-style' footage with a moving gate, for offline demos.

    .\\.venv\\Scripts\\python.exe -m real_gate_detector.make_sample
Writes real_gate_detector/sample/sample_gate.mp4 (orange gate drifting
across a sky/ground background). Judges can run the detector on it with
no real footage needed.
"""
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    out = Path(__file__).parent / "sample" / "sample_gate.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h, fps, n = 1280, 720, 30, 90
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(n):
        frame = np.zeros((h, w, 3), np.uint8)
        frame[: h // 2] = (200, 160, 90)    # sky (BGR)
        frame[h // 2:] = (70, 110, 60)      # ground
        cx = int(w * (0.25 + 0.5 * i / n))
        cy, size = h // 2, 90 + i          # gate grows as if approaching
        orange = (0, 140, 255)
        cv2.rectangle(frame, (cx - size, cy - size), (cx + size, cy + size), orange, 18)
        writer.write(frame)
    writer.release()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
