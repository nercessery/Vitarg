"""Watches for 'File Manager drag + trigger keys' and tells the UI to show a wheel.

Supports both Windows (Explorer via GetAsyncKeyState) and Linux X11/XWayland (file managers & desktop).
On Linux Wayland or any desktop environment, users can also drop files onto the Floating Drop Target."""
import os, subprocess, sys, threading, time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QCursor

from . import keys
from .settings import normalize

EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW"}
LINUX_FILE_MANAGERS = {
    "nautilus", "org.gnome.nautilus", "nemo", "dolphin", "org.kde.dolphin",
    "thunar", "pcmanfm", "pcmanfm-qt", "caja", "konqueror", "krusader",
    "spacefm", "xfdesktop", "plasmashell", "desktop_window", "ding",
}
DRAG_THRESHOLD_PX = 8

_user32 = None
if sys.platform == "win32":
    import ctypes
    _user32 = ctypes.windll.user32
    _buf = ctypes.create_unicode_buffer(256)


def _fg_info() -> tuple[int, str]:
    if _user32:
        hwnd = _user32.GetForegroundWindow()
        _user32.GetClassNameW(hwnd, _buf, 256)
        return hwnd, _buf.value
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        # Check active X11 window class using xprop if available (fast, non-blocking)
        try:
            r = subprocess.run(
                ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                capture_output=True, text=True, timeout=0.15,
            )
            if r.returncode == 0 and "#" in r.stdout:
                win_id = r.stdout.split("#")[-1].strip().split()[0]
                if win_id and win_id != "0x0":
                    r2 = subprocess.run(
                        ["xprop", "-id", win_id, "WM_CLASS"],
                        capture_output=True, text=True, timeout=0.15,
                    )
                    if r2.returncode == 0:
                        return int(win_id, 16), r2.stdout.lower()
        except Exception:
            pass
    return 0, ""


def _is_linux_fm_or_desktop(cls_info: str) -> bool:
    if not cls_info:
        # When xprop is not installed, allow X11 drag trigger to arm so Shift+Drag still works
        return True
    low = cls_info.lower()
    if "vitarg" in low:
        return False
    return any(fm in low for fm in LINUX_FILE_MANAGERS)


def _drag_image_present() -> bool:
    if not _user32:
        return False
    return bool(_user32.FindWindowW("SysDragImage", None))


def explorer_selection(hwnd: int, cls: str) -> list[str]:
    """Selected file paths of the Explorer window / desktop (best effort; [] if unavailable)."""
    if sys.platform != "win32":
        return []
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
        self._lock = threading.Lock()
        self.s = settings
        self.timer = QTimer(self)
        self.timer.setInterval(33)                 # 30 FPS when idle, ramps up to 60 FPS during drags
        self.timer.timeout.connect(self._tick)
        self._reset()
        self.last_pressed: set = set()          # exposed for the settings 'test' panel

    def start(self):
        if sys.platform == "win32" or (sys.platform.startswith("linux") and os.environ.get("DISPLAY")):
            self.timer.start()

    def stop(self):
        self.timer.stop()

    def _reset(self):
        with self._lock:
            self.armed = False
            self.shown = None                        # kind currently shown
            self.origin = (0, 0)
            self.sel: list[str] = []
            self.suppressed = False
            self.token = 0

    def _query(self, hwnd, cls, token):
        if sys.platform != "win32":
            return
        # Quick poll: try immediately first, then retry after brief intervals if empty
        for delay in (0.0, 0.04, 0.08):
            if delay > 0:
                time.sleep(delay)
            with self._lock:
                if token != self.token:
                    return
            paths = explorer_selection(hwnd, cls)
            if paths:
                with self._lock:
                    if token == self.token:
                        self.sel = list(paths)
                        if self.shown:
                            p = QCursor.pos()
                            self.trigger.emit(self.shown, list(paths), p.x(), p.y())
                return

    def _tick(self):
        s = self.s
        if not s.enabled:
            return
        down = keys.primary_button_down()
        if not down:
            if self.timer.interval() != 33:
                self.timer.setInterval(33)          # return to battery-saving idle frequency
            if self.armed or self.shown:
                if self.shown:
                    self.released.emit()
                self._reset()
            return
        if self.suppressed:
            return
        if not self.armed and self.shown is None:             # rising edge
            hwnd, cls = _fg_info()
            if sys.platform == "win32":
                self.armed = cls in EXPLORER_CLASSES
            else:
                self.armed = _is_linux_fm_or_desktop(cls)
            self.origin = keys.cursor_pos()
            with self._lock:
                self.sel = []
                self.token += 1
                curr_token = self.token
            if self.armed:
                if self.timer.interval() != 16:
                    self.timer.setInterval(16)
                if sys.platform == "win32":
                    threading.Thread(target=self._query, args=(hwnd, cls, curr_token), daemon=True).start()
            return
        if not self.armed and self.shown is None:
            return
        if self.timer.interval() != 16:
            self.timer.setInterval(16)
        if keys.key_down(0x1B):                               # Esc
            self.suppressed = True
            self.cancelled.emit()
            self.shown = None
            return
        uni = keys.universe_for(s.conv_trigger, s.tools_trigger)
        pressed = keys.pressed_set(uni)
        kind = "conv" if keys.matches(pressed, s.conv_trigger) else "tools" if keys.matches(pressed, s.tools_trigger) else None
        if kind is None:
            if self.shown is not None:
                self.cancelled.emit()
                self.shown = None
            return
        if kind == self.shown:
            return
        x, y = keys.cursor_pos()
        moved = max(abs(x - self.origin[0]), abs(y - self.origin[1]))
        with self._lock:
            current_sel = list(self.sel)
        is_drag = (_drag_image_present() or self.armed) and (
            (bool(current_sel) and moved >= DRAG_THRESHOLD_PX)
            or (moved >= 24)
        )
        if self.shown is None and not is_drag:
            return
        self.shown = kind
        gx, gy = keys.cursor_pos()
        if gx == 0 and gy == 0:
            p = QCursor.pos()
            gx, gy = p.x(), p.y()
        self.trigger.emit(kind, current_sel, gx, gy)
