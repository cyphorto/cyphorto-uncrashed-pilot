"""Pick the screen box around the OSD altitude digits and save it as osd.region in config.json.

  python tools/pick_region.py              # 5 s countdown: switch to the game, then it screenshots
  python tools/pick_region.py --image shot.png   # pick from a saved full-screen screenshot

Drag a box around the altitude number. Leave a little margin and make it wide enough
for the largest number you'll fly at (e.g. '123.4'). Avoid other OSD text if you can.
Then press Enter (or Space). Press C to cancel.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ROOT  # noqa: E402
from core import config as C  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image")
    p.add_argument("--delay", type=float, default=5.0)
    a = p.parse_args()
    cfg = C.load()
    if a.image:
        img = cv2.imread(a.image)
        if img is None:
            raise SystemExit(f"can't read {a.image}")
        off_x = off_y = 0
    else:
        from core.capture import ScreenGrabber
        g = ScreenGrabber(None, cfg["capture"]["monitor"])
        for i in range(int(a.delay), 0, -1):
            print(f"Switch to the game (hover so the altitude shows)... {i}")
            time.sleep(1)
        img, mon = g.full_monitor()
        img = img.copy()
        off_x, off_y = mon["left"], mon["top"]
        (ROOT / "data").mkdir(exist_ok=True)
        cv2.imwrite(str(ROOT / "data" / "region_pick.png"), img)
    H, W = img.shape[:2]
    scale = min(1.0, 1600 / W, 900 / H)
    shown = cv2.resize(img, (int(W * scale), int(H * scale))) if scale < 1 else img
    x, y, w, h = cv2.selectROI("Drag a box around the altitude digits, then Enter", shown, showCrosshair=False)
    cv2.destroyAllWindows()
    if w == 0 or h == 0:
        raise SystemExit("cancelled, nothing saved")
    region = {"left": int(x / scale) + off_x, "top": int(y / scale) + off_y,
              "width": int(w / scale), "height": int(h / scale)}
    cfg["osd"]["region"] = region
    C.save(cfg)
    crop = img[region["top"] - off_y:region["top"] - off_y + region["height"],
               region["left"] - off_x:region["left"] - off_x + region["width"]]
    cv2.imwrite(str(ROOT / "data" / "osd_region_preview.png"), crop)
    print(f"Saved osd.region = {region}")
    print("Preview saved to data/osd_region_preview.png. Next: python tools/calibrate_osd.py")


if __name__ == "__main__":
    main()
