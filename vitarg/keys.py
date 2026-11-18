"""Global key / mouse state across Windows (GetAsyncKeyState) and Linux (X11 XQueryKeymap/XQueryPointer + Qt fallback)."""
from __future__ import annotations
import os
import sys
import threading
from .settings import VK, MODIFIERS, normalize

_user32 = None
_PT = None
_x11 = None
_x11_dpy = None
_x11_root = None
_x11_lock = threading.Lock()
_qt_pressed_vks: set[int] = set()

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _PT = wintypes.POINT()
elif sys.platform.startswith("linux"):
    # Initialize X11 connection if DISPLAY is available (works on X11 and XWayland)
    if os.environ.get("DISPLAY"):
        try:
            import ctypes
            import ctypes.util
            x11_path = ctypes.util.find_library("X11") or "libX11.so.6"
            _lib = ctypes.cdll.LoadLibrary(x11_path)
            try:
                _lib.XInitThreads()
            except Exception:
                pass
            _lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            _lib.XOpenDisplay.restype = ctypes.c_void_p
            _lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            _lib.XDefaultRootWindow.restype = ctypes.c_ulong
            _lib.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_char * 32]
            _lib.XQueryKeymap.restype = ctypes.c_int
            _lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            _lib.XKeysymToKeycode.restype = ctypes.c_ubyte
            _lib.XQueryPointer.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_uint),
            ]
            _lib.XQueryPointer.restype = ctypes.c_int
            dpy = _lib.XOpenDisplay(None)
            if dpy:
                _x11 = _lib
                _x11_dpy = dpy
                _x11_root = _lib.XDefaultRootWindow(dpy)
        except Exception:
            _x11 = None
            _x11_dpy = None


# Map Windows virtual-key codes to X11 KeySyms for Linux XQueryKeymap
_VK_TO_X11_KEYSYMS: dict[int, tuple[int, ...]] = {
    0x10: (0xFFE1, 0xFFE2),          # Shift_L, Shift_R
    0x11: (0xFFE3, 0xFFE4),          # Control_L, Control_R
    0x12: (0xFFE9, 0xFFEA, 0xFE03),  # Alt_L, Alt_R, ISO_Level3_Shift
    0x5B: (0xFFEB,),                 # Super_L
    0x5C: (0xFFEC,),                 # Super_R
    0x1B: (0xFF1B,),                 # Escape
    0x20: (0x0020,),                 # Space
    0x14: (0xFFE5,),                 # Caps_Lock
}
for _c in range(ord("A"), ord("Z") + 1):
    _VK_TO_X11_KEYSYMS[_c] = (_c, _c + 32)  # Uppercase and lowercase ASCII KeySyms
for _i in range(1, 13):
    _VK_TO_X11_KEYSYMS[0x6F + _i] = (0xFFBE + _i - 1,)  # XK_F1 (0xFFBE) .. XK_F12 (0xFFC9)


def set_qt_key_state(vk: int, is_down: bool) -> None:
    """Record Qt key press/release events (used for Wayland and in-window hotkey recording)."""
    if is_down:
        _qt_pressed_vks.add(vk)
    else:
        _qt_pressed_vks.discard(vk)


def clear_qt_key_states() -> None:
    _qt_pressed_vks.clear()


def _x11_pointer_state() -> tuple[int, int, int] | None:
    """Return (root_x, root_y, mask) via XQueryPointer, or None if unavailable."""
    if not (_x11 and _x11_dpy and _x11_root):
        return None
    import ctypes
    with _x11_lock:
        try:
            root_ret = ctypes.c_ulong()
            child_ret = ctypes.c_ulong()
            rx = ctypes.c_int()
            ry = ctypes.c_int()
            wx = ctypes.c_int()
            wy = ctypes.c_int()
            mask = ctypes.c_uint()
            ok = _x11.XQueryPointer(
                _x11_dpy, _x11_root,
                ctypes.byref(root_ret), ctypes.byref(child_ret),
                ctypes.byref(rx), ctypes.byref(ry),
                ctypes.byref(wx), ctypes.byref(wy),
                ctypes.byref(mask),
            )
            if ok:
                return (rx.value, ry.value, mask.value)
        except Exception:
            pass
    return None


def _x11_vk_down(vk: int) -> bool:
    if not (_x11 and _x11_dpy):
        return False
    # Mouse buttons via pointer mask: Button1Mask = (1<<8), Button3Mask = (1<<10)
    if vk in (0x01, 0x02):
        pt = _x11_pointer_state()
        if pt is not None:
            mask = pt[2]
            return bool(mask & (1 << 8)) if vk == 0x01 else bool(mask & (1 << 10))
        return False

    keysyms = _VK_TO_X11_KEYSYMS.get(vk, ())
    if not keysyms:
        return False
    import ctypes
    with _x11_lock:
        try:
            keymap = (ctypes.c_char * 32)()
            _x11.XQueryKeymap(_x11_dpy, keymap)
            raw = bytes(keymap)
            for ks in keysyms:
                kc = _x11.XKeysymToKeycode(_x11_dpy, ks)
                if kc and (raw[kc >> 3] & (1 << (kc & 7))):
                    return True
        except Exception:
            pass
    return False


def _qt_vk_down(vk: int) -> bool:
    if vk in _qt_pressed_vks:
        return True
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if not app:
            return False
        if vk == 0x01:
            return bool(QGuiApplication.mouseButtons() & Qt.LeftButton)
        if vk == 0x02:
            return bool(QGuiApplication.mouseButtons() & Qt.RightButton)
        mods = QGuiApplication.queryKeyboardModifiers() | QGuiApplication.keyboardModifiers()
        if vk == 0x10:
            return bool(mods & Qt.ShiftModifier)
        if vk == 0x11:
            return bool(mods & Qt.ControlModifier)
        if vk == 0x12:
            return bool(mods & Qt.AltModifier)
        if vk in (0x5B, 0x5C):
            return bool(mods & Qt.MetaModifier)
    except Exception:
        pass
    return False


def key_down(vk: int) -> bool:
    if _user32:
        return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
    if _x11_vk_down(vk):
        return True
    return _qt_vk_down(vk)


def primary_button_down() -> bool:
    """Respects swapped mouse buttons on Windows; checks X11/Qt left button on Linux."""
    if _user32:
        swapped = bool(_user32.GetSystemMetrics(23))            # SM_SWAPBUTTON
        return key_down(0x02 if swapped else 0x01)
    return key_down(0x01)


def cursor_pos() -> tuple[int, int]:
    if _user32 and _PT:
        import ctypes
        _user32.GetCursorPos(ctypes.byref(_PT))
        return (_PT.x, _PT.y)
    pt = _x11_pointer_state()
    if pt is not None:
        return (pt[0], pt[1])
    try:
        from PySide6.QtGui import QCursor
        p = QCursor.pos()
        return (p.x(), p.y())
    except Exception:
        return (0, 0)


def name_down(name: str) -> bool:
    return any(key_down(v) for v in VK.get(name, ()))


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
