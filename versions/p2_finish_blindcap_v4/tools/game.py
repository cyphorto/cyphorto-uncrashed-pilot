"""Look at and poke the Uncrashed window from the command line, without the screen.

    python tools/game.py status                 # is the game running, window size, focus
    python tools/game.py launch                 # start it through Steam, wait for the window
    python tools/game.py shot                   # save the game window to logs/shots/<time>.png
    python tools/game.py shot --out x.png --scale 0.5 --box 0.85 0.2 1 0.3
    python tools/game.py key T                  # focus the game and tap T (RestartRace)
    python tools/game.py click 960 540          # focus the game and click a client pixel
    python tools/game.py fps                    # capture rate over 3 s

shot reads the game window itself (Windows Graphics Capture), so other windows on
top of the game don't show in it. This is how Claude looks at the game without
computer-use screenshots, which pop the Claude window over the ALT readout.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ROOT, config as C  # noqa: E402
from core import window as W  # noqa: E402


def need_window():
    hwnd = W.find_game_window()
    if not hwnd:
        raise SystemExit("Uncrashed is not running (python tools/game.py launch)")
    return hwnd


def shot(hwnd, out=None, scale=1.0, box=None):
    cap = W.WindowCapture(hwnd)
    try:
        _, img, _ = cap.grab(timeout=3.0)
    finally:
        cap.close()
    if box:
        h, w = img.shape[:2]
        x0, y0, x1, y1 = box
        img = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if out is None:
        d = ROOT / "logs" / "shots"
        d.mkdir(parents=True, exist_ok=True)
        out = d / (time.strftime("%Y%m%d_%H%M%S") + ".png")
    cv2.imwrite(str(out), img)
    return Path(out), img.shape


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("launch")
    s = sub.add_parser("shot")
    s.add_argument("--out")
    s.add_argument("--scale", type=float, default=1.0)
    s.add_argument("--box", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                   help="crop, as fractions of the frame")
    k = sub.add_parser("key")
    k.add_argument("keys", nargs="+")
    k.add_argument("--gap", type=float, default=0.3)
    c = sub.add_parser("click")
    c.add_argument("x", type=int)
    c.add_argument("y", type=int)
    f = sub.add_parser("fps")
    f.add_argument("--seconds", type=float, default=3.0)
    a = p.parse_args()

    if a.cmd == "launch":
        hwnd = W.find_game_window()
        if not hwnd:
            os.startfile(C.load()["game"]["steam_url"])
            end = time.time() + 180
            while not hwnd and time.time() < end:
                time.sleep(2)
                hwnd = W.find_game_window()
            if not hwnd:
                raise SystemExit("no game window after 180 s")
            time.sleep(5)
        print(json.dumps(W.window_state(hwnd)))
    elif a.cmd == "status":
        hwnd = W.find_game_window()
        print(json.dumps(W.window_state(hwnd) if hwnd else {"running": False}))
    elif a.cmd == "shot":
        path, shape = shot(need_window(), a.out, a.scale, a.box)
        print(f"{path} {shape[1]}x{shape[0]}")
    elif a.cmd == "key":
        hwnd = need_window()
        for i, key in enumerate(a.keys):
            if i:
                time.sleep(a.gap)
            if not W.press(hwnd, key):
                raise SystemExit("could not bring the game to the front")
        print("ok")
    elif a.cmd == "click":
        if not W.click(need_window(), a.x, a.y):
            raise SystemExit("could not bring the game to the front")
        print("ok")
    elif a.cmd == "fps":
        cap = W.WindowCapture(need_window())
        try:
            _, img, n0 = cap.grab(timeout=3.0)
            t0 = time.perf_counter()
            time.sleep(a.seconds)
            _, img, n1 = cap.grab()
            print(f"{(n1 - n0) / (time.perf_counter() - t0):.1f} frames/s, {img.shape[1]}x{img.shape[0]}")
        finally:
            cap.close()


if __name__ == "__main__":
    main()
