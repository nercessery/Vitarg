"""Background workers and the closable orange progress window."""
import os, sys, threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPainterPath, QBrush
from PySide6.QtWidgets import QLabel, QPushButton, QTextEdit, QWidget, QHBoxLayout

from .engine import Cancelled
from .theme import Panel, ORANGE


class Worker(QThread):
    progress = Signal(float)
    done = Signal(list, list)          # outputs, errors [(name, message)]
    crashed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        try:
            outs, errs = self.fn(self.progress.emit, self.cancel)
            self.done.emit([str(o) for o in outs], errs)
        except Cancelled:
            self.done.emit([], [])
        except Exception as e:
            self.crashed.emit(f"{type(e).__name__}: {e}")


class Bar(QWidget):
    """Custom-drawn orange progress bar (indeterminate until the first real value arrives)."""

    def __init__(self):
        super().__init__()
        self.value = -1.0
        self.phase = 0.0
        self.setFixedHeight(12)
        self.t = QTimer(self)
        self.t.timeout.connect(self._anim)
        self.t.start(30)

    def _anim(self):
        if self.value < 0:
            self.phase = (self.phase + 0.02) % 1.0
            self.update()

    def set_value(self, v):
        self.value = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(ORANGE)
        if self.value >= 0:
            p.drawRoundedRect(QRectF(0, 0, max(12.0, r.width() * min(1.0, self.value)), r.height()), 6, 6)
        else:
            w = r.width() * 0.3
            x = (r.width() + w) * self.phase - w
            path = QPainterPath(); path.addRoundedRect(QRectF(x, 0, w, r.height()), 6, 6)
            clip = QPainterPath(); clip.addRoundedRect(r, 6, 6)
            p.fillPath(path.intersected(clip), ORANGE)


def notify_explorer(paths):
    if sys.platform != "win32":
        return
    import ctypes
    for d in {str(Path(p).parent) for p in paths}:
        ctypes.windll.shell32.SHChangeNotify(0x00001000, 0x0005, ctypes.c_wchar_p(d), None)   # UPDATEDIR


class JobWindow(Panel):
    job_done = Signal(object)      # not 'finished': that name belongs to QDialog

    def __init__(self, title: str, subtitle: str, fn):
        super().__init__(title, 360)
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("hint")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setWordWrap(True)
        self.bar = Bar()
        self.body.addWidget(self.sub)
        self.body.addWidget(self.bar)
        self.err = None
        self.worker = Worker(fn)
        self.worker.progress.connect(lambda v: self.bar.set_value(v if v > 0 else -1.0))
        self.worker.done.connect(self._done)
        self.worker.crashed.connect(lambda m: self._fail([("Unexpected error", m)]))
        self.worker.finished.connect(lambda: None)

    def start(self):
        self.show()
        self.worker.start()

    def _done(self, outs, errs):
        if errs:
            self._fail(errs, bool(outs))
            return
        self.bar.set_value(1.0)
        notify_explorer(outs)
        self.close_and_release()

    def _fail(self, errs, partial=False):
        self.bar.hide()
        self.sub.setText("Some files could not be processed." if partial else "The operation failed.")
        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText("\n\n".join(f"{n}:\n{m}" for n, m in errs))
        box.setFixedHeight(150)
        self.body.addWidget(box)
        b = QPushButton("Close")
        b.setObjectName("primary")
        b.clicked.connect(self.close_and_release)
        self.body.addWidget(b)
        self.show()
        self.raise_()

    def close_and_release(self):
        self.hide()
        self.job_done.emit(self)

    def reject(self):          # the ✕ only hides the window; the operation keeps running
        self.hide()
