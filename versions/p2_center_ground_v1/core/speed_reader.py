"""Read Uncrashed's speed readout (the bold number under "km/h", top right).

Same method as core.alt_reader (white top-hat, Otsu, full-height glyphs, NCC against
templates, None when unsure), with its own templates: the speed digits are a bolder
font, and the ALT templates matched them at only 0.63-0.79.

Templates in data/speed_templates/ were cut from the 1 Hz view frames of the
2026-10-24 flights, grouped by similarity and labelled by eye.
"""
import re

from .alt_reader import AltReader

SPEED_BOX = (0.90, 0.15, 0.985, 0.205)  # fractions of the frame
_INT = re.compile(r"^\d{1,3}$")


class SpeedReader(AltReader):
    def __init__(self, templates_dir, box=SPEED_BOX, **kw):
        super().__init__(templates_dir, box=box, fmt=_INT, **kw)

    def read_ms(self, frame):
        """Speed in m/s, or None."""
        kmh, _, _ = self.read(frame)
        return None if kmh is None else kmh / 3.6
