"""Real-gate detection for Mavic Air 2 footage, reusing the Uncrashed detector."""
from .detector import Detection, RealGateDetector, draw_overlay

__all__ = ["Detection", "RealGateDetector", "draw_overlay"]
