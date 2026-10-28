"""Hold zero throttle without changing flight mode; stop before starting any pilot."""
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.gamepad import Gamepad
from core import config as C, window as W
pad=Gamepad(C.load()['controls'])
try:
    while True:
        pad.send(0.0)
        time.sleep(.02)
finally:
    pad.min_throttle()
