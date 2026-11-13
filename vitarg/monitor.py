"""Watches for 'Explorer drag + trigger keys' and tells the UI to show a wheel.

No keyboard/mouse hooks and no admin rights are used: it polls GetAsyncKeyState, like the original polls
modifier state. A drag counts when the primary button is held, the pointer moved, the foreground window is
Explorer/desktop, and a file drag is in progress (Explorer's 'SysDragImage' window, or a known selection)."""
import sys, threading, time

from PySide6.QtCore import QObject, QTimer, Signal, QPoint
from PySide6.QtGui import QCursor

from . import keys
from .settings import normalize

EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW"}
DRAG_THRESHOLD_PX = 8

_user32 = None
if sys.platform == "win32":
    import ctypes
    _user32 = ctypes.windll.user32
    _buf = ctypes.create_unicode_buffer(256)


def _fg_info():
    if not _user32:
        return 0, ""
    hwnd = _user32.GetForegroundWindow()
    _user32.GetClassNameW(hwnd, _buf, 256)
    return hwnd, _buf.value


def _drag_image_present() -> bool:
    if not _user32:
        return False
    return bool(_user32.FindWindowW("SysDragImage", None))


def explorer_selection(hwnd: int, cls: str) -> list[str]:
    """Selected file paths of the Explorer window / desktop (best effort; [] if unavailable)."""
    try:
        import pythoncom, win32com.client
    except ImportError:
        return []
    pythoncom.CoInitialize()
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        doc = None
        if cls in ("Progman", "WorkerW"):
            try:
                v = win32com.client.VARIANT
                sw = shell.Windows().FindWindowSW(v(pythoncom.VT_VARIANT, 0), v(pythoncom.VT_VARIANT, ""), 8, 0, 1)
                doc = sw.Document
            except Exception:
                doc = None
        else:
            for w in shell.Windows():
                try:
                    if int(w.HWND) == int(hwnd):
                        doc = w.Document
                        break
                except Exception:
                    continue
        if doc is None:
            return []
        import os
        return [i.Path for i in doc.SelectedItems() if os.path.isfile(i.Path)]
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


class DragMonitor(QObject):
    trigger = Signal(str, list, int, int)      # kind, paths, x, y (Qt logical coordinates)
    released = Signal()                        # primary button released (UI hides after a short delay)
    cancelled = Signal()                       # Esc pressed during a drag

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.timer = QTimer(self)
        self.timer.setInterval(33)                 # 30 FPS when idle, ramps up to 60 FPS during drags
        self.timer.timeout.connect(self._tick)
        self._reset()
        self.last_pressed: set = set()          # exposed for the settings 'test' panel

    def start(self):
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def _reset(self):
        self.armed = False
        self.shown = None                        # kind currently shown
        self.origin = (0, 0)
        self.sel: list[str] = []
        self.suppressed = False
        self.token = 0

    def _query(self, hwnd, cls, token):
        time.sleep(0.12)                         # let Explorer update the selection after mouse-down
        paths = explorer_selection(hwnd, cls)
        if token == self.token:
            self.sel = paths

    def _tick(self):
        s = self.s
        down = keys.primary_button_down()
        if not s.enabled or sys.platform != "win32":
            return
        if not down:
            if self.timer.interval() != 33:
                self.timer.setInterval(33)          # return to battery-saving idle frequency
            if self.armed or self.shown:
                if self.shown:
                    self.released.emit()
                self._reset()
            return
        if self.timer.interval() != 16:
            self.timer.setInterval(16)              # 60 FPS for responsive dragging
        if self.suppressed:
            return
        if not self.armed and self.shown is None:             # rising edge
            hwnd, cls = _fg_info()
            self.armed = cls in EXPLORER_CLASSES
            self.origin = keys.cursor_pos()
            self.sel = []
            self.token += 1
            if self.armed:
                threading.Thread(target=self._query, args=(hwnd, cls, self.token), daemon=True).start()
            return
        if not self.armed:
            return
        if keys.key_down(0x1B):                               # Esc
            self.suppressed = True
            self.cancelled.emit()
            self.shown = None
            return
        uni = keys.universe_for(s.conv_trigger, s.tools_trigger)
        pressed = keys.pressed_set(uni)
        kind = "conv" if keys.matches(pressed, s.conv_trigger) else "tools" if keys.matches(pressed, s.tools_trigger) else None
        if kind is None or kind == self.shown:
            return
        x, y = keys.cursor_pos()
        moved = max(abs(x - self.origin[0]), abs(y - self.origin[1]))
        file_drag = _drag_image_present() and moved >= DRAG_THRESHOLD_PX
        known = bool(self.sel) and moved >= 40
        if self.shown is None and not (file_drag or known):
            return
        self.shown = kind
        p = QCursor.pos()
        self.trigger.emit(kind, list(self.sel), p.x(), p.y())
