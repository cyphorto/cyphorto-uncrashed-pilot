"""Start Uncrashed through Steam (or bring it to the front if it's already running).

  python tools/launch_game.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config as C  # noqa: E402
from core.launcher import launch  # noqa: E402

if __name__ == "__main__":
    launch(C.load()["game"])
