"""Global key / mouse state via GetAsyncKeyState (no hooks, no admin rights)."""
import sys
from .settings import VK, MODIFIERS, normalize

_user32 = None
_PT = None
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _PT = wintypes.POINT()


def key_down(vk: int) -> bool:
    return bool(_user32 and (_user32.GetAsyncKeyState(vk) & 0x8000))


def primary_button_down() -> bool:
    """Respects swapped mouse buttons."""
    if not _user32:
        return False
    swapped = bool(_user32.GetSystemMetrics(23))            # SM_SWAPBUTTON
    return key_down(0x02 if swapped else 0x01)


def cursor_pos():
    if not _user32 or not _PT:
        return (0, 0)
    _user32.GetCursorPos(ctypes.byref(_PT))
    return (_PT.x, _PT.y)


def name_down(name: str) -> bool:
    return any(key_down(v) for v in VK[name])


def pressed_set(universe) -> set:
    return {n for n in universe if name_down(n)}


def universe_for(*triggers) -> set:
    u = set(MODIFIERS)
    for t in triggers:
        u |= set(normalize(t))
    return u


def matches(pressed, trigger) -> bool:
    """Exact match on the tracked key universe: Shift != Alt+Shift."""
    return set(pressed) == set(normalize(trigger)) and bool(trigger)
