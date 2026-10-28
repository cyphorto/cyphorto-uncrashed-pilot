"""Paths shared by every droneai module.

V2 is self-contained: the flight stack (core/, pilot/, tools/, versions/)
was copied verbatim from the original project on 2026-10-27 and now lives
under V2_ROOT. Nothing here points at the original tree.
"""
from pathlib import Path
import sys

V2_ROOT = Path(__file__).resolve().parents[1]

if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))
