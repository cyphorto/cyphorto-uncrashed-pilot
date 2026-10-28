"""ANGLE-mode pitch calibration from the x8 simulator probe, 2026-10-26."""
import math


def attitude_deg(stick):
    """Measured pitch fit; roll has not been calibrated with this probe."""
    return 25.2 * stick + 23.3 * stick ** 3


def pitch_degrees(stick, linear=50.0, calibrated=False):
    return attitude_deg(stick) if calibrated else linear * stick


def pitch_stick(degrees, linear=50.0, calibrated=False):
    """Invert the monotonic pitch curve, bounded to the controller range."""
    if not calibrated:
        return max(-1.0, min(1.0, degrees / linear)) if linear else 0.0
    lo, hi = -1.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if attitude_deg(mid) < degrees:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
