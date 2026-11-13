"""Pure geometry for the radial wheel (no Qt): petals start at 12 o'clock and run clockwise."""
import math


def petal_center(i: int, n: int) -> float:
    """Centre angle of petal i in degrees, clockwise from 12 o'clock."""
    return i * 360.0 / n


def angle_of(dx: float, dy: float) -> float:
    """Clockwise-from-top angle in [0, 360) for a screen-space offset (y grows downward)."""
    return math.degrees(math.atan2(dx, -dy)) % 360.0


def hit_test(n: int, dx: float, dy: float, r_inner: float, r_outer: float) -> int:
    """Index of the petal under offset (dx, dy) from the wheel centre, or -1."""
    if n <= 0:
        return -1
    r = math.hypot(dx, dy)
    if r < r_inner or r > r_outer:
        return -1
    a = angle_of(dx, dy)
    return int(((a + 180.0 / n) % 360.0) // (360.0 / n))


def label_pos(i: int, n: int, r_mid: float):
    """Offset (dx, dy) of the label anchor for petal i."""
    a = math.radians(petal_center(i, n))
    return r_mid * math.sin(a), -r_mid * math.cos(a)
