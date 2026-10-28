"""Teach the OSD reader the game's digit font, then test it.

  python tools/calibrate_osd.py                # live: capture with F9 in game, type what it showed
  python tools/calibrate_osd.py --test         # live: print readings 10x per second (Ctrl+C to stop)
  python tools/calibrate_osd.py --image crop.png --text 12.3    # learn from a saved image
  python tools/calibrate_osd.py --image crop.png --test         # read a saved image
  python tools/calibrate_osd.py --clear        # forget all templates

Live calibration: fly or hover so different numbers show. Each capture teaches the characters
in it. Keep going until every digit 0-9 has been seen (the script tells you what's missing).
If characters are merged/split, adjust osd.threshold (0 = automatic) or osd.text_is_dark in config.json.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ROOT  # noqa: E402
from core import config as C  # noqa: E402
from core.osd_reader import OSDReader, binarize, save_template, segment  # noqa: E402

SAMPLES = ROOT / "data" / "osd_samples"


def show(img, cfg):
    try:
        b = cv2.cvtColor(binarize(img, cfg["osd"]), cv2.COLOR_GRAY2BGR)
        both = np.vstack([img, b])
        k = max(1, 400 // max(1, both.shape[1]))
        cv2.imshow("OSD crop (top) / what the reader sees (bottom)", cv2.resize(both, None, fx=k, fy=k,
                                                                                    interpolation=cv2.INTER_NEAREST))
        cv2.waitKey(1)
    except cv2.error:
        pass  # no display available


def learn(img, text, cfg, tdir):
    text = text.replace(" ", "")
    segs = segment(img, cfg["osd"])
    if len(segs) != len(text):
        kinds = "".join("." if k == "dot" else "-" if k == "minus" else "#" for k, _ in segs)
        print(f"  found {len(segs)} characters ({kinds}) but you typed {len(text)} ('{text}'). Skipped. "
              "Try again, or tweak osd.threshold / the region.")
        return 0
    n = 0
    for (kind, g), ch in zip(segs, text):
        if kind == "glyph":
            if ch in ".-":
                print(f"  '{ch}' was seen as a full-size character; skipped this capture.")
                return n
            n += save_template(tdir, ch, g)
        elif (kind == "dot" and ch != ".") or (kind == "minus" and ch != "-"):
            print(f"  position of '{ch}' looked like '{'.' if kind == 'dot' else '-'}'; skipped.")
            return n
    SAMPLES.mkdir(parents=True, exist_ok=True)
    safe = text.replace(".", "p").replace("-", "m")
    cv2.imwrite(str(SAMPLES / f"{safe}_{int(time.time() * 1000)}.png"), img)
    return n


def wait_hotkey(vk=0x78):  # F9
    if sys.platform != "win32":
        input("Press Enter to capture...")
        return
    import ctypes
    u = ctypes.windll.user32
    while u.GetAsyncKeyState(vk) & 0x8000:
        time.sleep(0.01)
    while not (u.GetAsyncKeyState(vk) & 0x8000):
        time.sleep(0.01)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image")
    p.add_argument("--text")
    p.add_argument("--test", action="store_true")
    p.add_argument("--clear", action="store_true")
    a = p.parse_args()
    cfg = C.load()
    tdir = C.resolve(cfg["osd"]["templates_dir"])

    if a.clear:
        shutil.rmtree(tdir, ignore_errors=True)
        tdir.mkdir(parents=True, exist_ok=True)
        print("templates cleared")
        return

    if a.image:
        img = cv2.imread(a.image)
        if img is None:
            raise SystemExit(f"can't read {a.image}")
        r = cfg["osd"]["region"]
        if img.shape[0] > r.get("height", 0) * 2 and r.get("width", 0) > 0:  # a full screenshot: crop it
            img = img[r["top"]:r["top"] + r["height"], r["left"]:r["left"] + r["width"]]
        if a.test:
            reader = OSDReader(cfg["osd"], tdir)
            text, score = reader.read_text(img)
            print(f"text '{text}'  score {score:.2f}  ->  height {reader.read_height(img)}")
        elif a.text is not None:
            print(f"learned {learn(img, a.text, cfg, tdir)} new templates")
            missing = OSDReader(cfg["osd"], tdir).missing()
            print("all digits known" if not missing else f"still missing: {' '.join(missing)}")
        else:
            raise SystemExit("--image needs --text (to learn) or --test (to read)")
        return

    from core.capture import ScreenGrabber
    grab = ScreenGrabber(cfg["osd"]["region"], cfg["capture"]["monitor"])

    if a.test:
        reader = OSDReader(cfg["osd"], tdir)
        if not reader.ready:
            raise SystemExit("missing digits: " + " ".join(reader.missing()))
        n = bad = 0
        try:
            while True:
                t, img = grab.grab()
                text, score = reader.read_text(img)
                h = reader.read_height(img)
                n += 1
                bad += h is None
                print(f"\r{text:>10s}  score {score:.2f}  ->  {h}   (unreadable {bad}/{n})   ", end="", flush=True)
                show(img, cfg)
                time.sleep(0.1)
        except KeyboardInterrupt:
            print()
        return

    print(__doc__.split("Live calibration:")[1].split("If characters")[0].strip())
    while True:
        missing = OSDReader(cfg["osd"], tdir).missing()
        if not missing:
            print("\nAll digits 0-9 learned. Check it with: python tools/calibrate_osd.py --test")
            break
        print(f"\nStill missing: {' '.join(missing)}")
        print("Switch to the game and press F9 to capture the OSD...")
        wait_hotkey()
        _, img = grab.grab()
        show(img, cfg)
        text = input("Type exactly what the altitude showed (Enter = skip, q = quit): ").strip()
        if text.lower() == "q":
            break
        if text:
            print(f"  learned {learn(img, text, cfg, tdir)} new templates")
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
