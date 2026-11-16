"""The radial picker: a translucent always-on-top window that is an OLE drop target for files."""
import math, os, sys, time
from pathlib import Path

from PySide6.QtCore import (Qt, QPoint, QPointF, QRectF, QSize, Signal, Property,
                            QPropertyAnimation, QEasingCurve, QTimer, QEvent)
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen, QBrush,
                           QLinearGradient, QRadialGradient, QGuiApplication, QFontMetricsF)
from PySide6.QtWidgets import QWidget, QApplication

from . import engine, tools, geometry as geo, keys
from .icons import draw_icon
from .engine import app_dir
from . import glass
from . import theme
from .theme import alpha, tint

SIZE = 440                         # window edge in device-independent pixels
R_RING = 212.0                     # outer gold ring
R_OUT = 190.0                      # outer edge of petals
R_IN = 88.0                        # inner edge of petals
R_CORE = 82.0                      # centre disc
GAP_PX = 9.0                       # visual gap between petals
ROUND = 13.0                       # petal corner rounding

DEFAULT_CONV_FALLBACK = ["mp4", "mp3", "jpg", "png", "webp", "pdf", "gif", "wav", "docx", "zip"]


class Wheel(QWidget):
    chosen = Signal(str, str, list)        # kind ("conv"/"tools"), id, [paths]

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.kind = "conv"
        self.paths: list[str] = []
        self.items: list[tuple[str, str, str]] = []     # (id, label, icon)
        self.hover = -1
        self._shape_cache = []
        self.interactive = False
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFixedSize(SIZE, SIZE)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setDuration(130)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self._scale = 0.9
        self.pop = QPropertyAnimation(self, b"scaleFactor", self)
        self.pop.setDuration(190)
        self.pop.setEasingCurve(QEasingCurve.OutBack)
        self._sound = app_dir() / "assets" / "HighlightSound.wav"
        self._font_label = QFont("Segoe UI Variable Display", 13, QFont.Bold)
        self._font_label.setFamilies([
            "Segoe UI Variable Display", "Segoe UI", "Inter", "Ubuntu",
            "Cantarell", "Noto Sans", "DejaVu Sans", "Arial"
        ])
        self._font_tool = QFont(self._font_label)
        self._font_tool.setPointSizeF(8.5)
        self._font_tool.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        self._font_cap_small = QFont(self._font_label)
        self._font_cap_small.setPointSizeF(11)
        self._font_cap_large = QFont(self._font_label)
        self._font_cap_large.setPointSizeF(13)
        self._layout_cache = []

        # Interactive dismissal & activation tracking
        self._shown_time = 0.0
        self._was_activated = False
        self._mouse_pressed_initial = False
        self._interactive_timer = QTimer(self)
        self._interactive_timer.setInterval(40)
        self._interactive_timer.timeout.connect(self._poll_interactive)

        theme.bus.changed.connect(self.update)          # appearance edits show up instantly

    def sizeHint(self):
        return QSize(SIZE, SIZE)

    # animatable property -------------------------------------------------
    def getScale(self): return self._scale
    def setScale(self, v): self._scale = v; self.update()
    scaleFactor = Property(float, getScale, setScale)

    # content ---------------------------------------------------------
    def set_content(self, kind: str, paths: list[str]):
        self.kind, self.paths, self.hover = kind, list(paths), -1
        if kind == "conv":
            targets = engine.common_targets(paths) if paths else DEFAULT_CONV_FALLBACK
            self.items = [(t, t.upper(), "") for t in targets][:16]
        else:
            tool_list = tools.tools_for(paths) if paths else [t for t in tools.TOOLS if not t.multi][:16]
            self.items = [(t.id, t.label, t.id) for t in tool_list][:16]
        self._rebuild()
        self.update()

    def _rebuild(self):
        n = len(self.items)
        self._shape_cache = []
        self._layout_cache = []
        c = QPointF(SIZE / 2, SIZE / 2)
        mid_r = (R_IN + R_OUT) / 2

        # Scale font dynamically when n > 8 to prevent label crowding
        if n > 8:
            self._font_tool.setPointSizeF(7.5)
            self._font_tool.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        else:
            self._font_tool.setPointSizeF(8.5)
            self._font_tool.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)

        for i in range(n):
            self._shape_cache.append(self._petal_path(c, i, n))
            ox, oy = geo.label_pos(i, n, mid_r + (4 if self.kind == "conv" else 0))
            lx, ly = c.x() + ox, c.y() + oy
            hot_pos = c + QPointF(*geo.label_pos(i, n, mid_r))
            self._layout_cache.append({
                "lx": lx,
                "ly": ly,
                "hot_pos": hot_pos,
                "rect_conv": QRectF(lx - 60, ly - 14, 120, 28),
                "rect_tool": QRectF(lx - 58, ly + 8, 116, 18),
            })

    def _petal_path(self, c: QPointF, i: int, n: int) -> QPainterPath:
        mid = geo.petal_center(i, n)
        half = 180.0 / n
        r0, r1 = R_IN + ROUND, R_OUT - ROUND
        pad_in = math.degrees((GAP_PX / 2 + ROUND) / (R_IN + ROUND))
        pad_out = math.degrees((GAP_PX / 2 + ROUND) / (R_OUT - ROUND))
        a0o, a1o = mid - half + pad_out, mid + half - pad_out       # outer arc (clockwise from top)
        a0i, a1i = mid - half + pad_in, mid + half - pad_in
        qt = lambda a: 90.0 - a                                       # to Qt's CCW-from-3-o'clock
        outer = QRectF(c.x() - r1, c.y() - r1, 2 * r1, 2 * r1)
        inner = QRectF(c.x() - r0, c.y() - r0, 2 * r0, 2 * r0)
        path = QPainterPath()
        path.arcMoveTo(outer, qt(a0o))
        path.arcTo(outer, qt(a0o), -(a1o - a0o))
        path.arcTo(inner, qt(a1i), (a1i - a0i))
        path.closeSubpath()
        st = QPainterPathStroker()
        st.setWidth(2 * ROUND)
        st.setJoinStyle(Qt.RoundJoin)
        return st.createStroke(path).united(path)

    def center_text(self) -> str:
        if 0 <= self.hover < len(self.items):
            return self.items[self.hover][1]
        if not self.items:
            return "NO OPTIONS"
        if not self.paths:
            return "DROP HERE"
        if len(self.paths) == 1:
            return engine.fmt_of(self.paths[0]).upper() or "FILE"
        return f"{len(self.paths)} FILES"

    # painting --------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        c = QPointF(SIZE / 2, SIZE / 2)
        p.translate(c); p.scale(self._scale, self._scale); p.translate(-c)
        # near-invisible base disc keeps the gaps hit-testable (layered windows ignore alpha 0)
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 6)); p.drawEllipse(c, R_RING, R_RING)
        # gold glass ring
        g = QRadialGradient(c, R_RING)
        g.setColorAt(0.80, tint(90, 104)); g.setColorAt(0.93, tint(170, 104)); g.setColorAt(1.0, tint(255, 96))
        p.setBrush(g); p.drawEllipse(c, R_RING, R_RING)
        p.setBrush(tint(45, 104)); p.drawEllipse(c, R_OUT + 8, R_OUT + 8)
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.6)); p.setBrush(Qt.NoBrush); p.drawEllipse(c, R_RING - 1, R_RING - 1)
        for i, path in enumerate(self._shape_cache):
            hot = i == self.hover
            layout = self._layout_cache[i]
            if hot:
                rg = QRadialGradient(layout["hot_pos"], 130)
                hl = QColor(theme.HIGHLIGHT)
                rg.setColorAt(0.0, hl); rg.setColorAt(0.6, hl.darker(102)); rg.setColorAt(1.0, hl.darker(106))
                p.setPen(QPen(QColor(255, 255, 255, 255), 2.0)); p.setBrush(rg)
            else:
                lg = QLinearGradient(0, c.y() - R_OUT, 0, c.y() + R_OUT)
                lg.setColorAt(0, tint(235, 104)); lg.setColorAt(1, tint(235, 94))
                p.setPen(QPen(QColor(255, 255, 255, 170), 1.0)); p.setBrush(lg)
            p.drawPath(path)
            lx, ly = layout["lx"], layout["ly"]
            col = QColor(theme.TEXT)
            if self.kind == "tools":
                draw_icon(p, self.items[i][2], lx, ly - 13, 28, col)
                p.setFont(self._font_tool); p.setPen(col)
                p.drawText(layout["rect_tool"], Qt.AlignCenter | Qt.TextDontClip, self.items[i][1])
            else:
                p.setFont(self._font_label); p.setPen(col)
                p.drawText(layout["rect_conv"], Qt.AlignCenter, self.items[i][1])
        # centre ring + disc + capsule
        cg = QRadialGradient(c, R_CORE + 12)
        cg.setColorAt(0, tint(150, 104)); cg.setColorAt(0.8, tint(170)); cg.setColorAt(1, tint(190, 94))
        p.setPen(QPen(QColor(255, 255, 255, 200), 7)); p.setBrush(cg); p.drawEllipse(c, R_CORE, R_CORE)
        cap = QRectF(c.x() - 58, c.y() - 29, 116, 58)
        capg = QLinearGradient(0, cap.top(), 0, cap.bottom())
        capg.setColorAt(0, tint(255, 106)); capg.setColorAt(1, tint(250, 98))
        p.setPen(QPen(QColor(255, 255, 255, 255), 1.4)); p.setBrush(capg); p.drawRoundedRect(cap, 29, 29)
        txt = self.center_text()
        p.setFont(self._font_cap_small if len(txt) > 6 else self._font_cap_large)
        p.setPen(QColor(theme.TEXT))
        p.drawText(cap, Qt.AlignCenter, txt)

    # showing / hiding ------------------------------------------------
    def present(self, kind: str, paths: list[str], gx: int, gy: int, interactive: bool = False):
        self.interactive = interactive
        self.set_content(kind, paths)
        if (gx == 0 and gy == 0) or gx is None or gy is None:
            scr = QGuiApplication.primaryScreen()
            if scr:
                center = scr.availableGeometry().center()
                gx, gy = center.x(), center.y()
        scr = QGuiApplication.screenAt(QPoint(gx, gy)) or QGuiApplication.primaryScreen()
        geom = scr.availableGeometry() if scr else QRectF(0, 0, 1920, 1080)
        x = min(max(gx - SIZE // 2, geom.left()), geom.right() - SIZE)
        y = min(max(gy - SIZE // 2, geom.top()), geom.bottom() - SIZE)
        self.move(int(x), int(y))

        # Window flags are permanent and stable; toggle WA_ShowWithoutActivating without HWND recreation
        self.setAttribute(Qt.WA_ShowWithoutActivating, not interactive)

        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.fade.stop(); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0); self.fade.start()
            self.pop.stop(); self.pop.setStartValue(0.88); self.pop.setEndValue(1.0); self.pop.start()
        else:
            self.show()

        if interactive:
            self._shown_time = time.monotonic()
            self._was_activated = False
            self._mouse_pressed_initial = bool(keys.primary_button_down() or keys.key_down(0x02))
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
            self.activateWindow()
            self.setFocus()
            self._interactive_timer.start()
        else:
            self._interactive_timer.stop()

        self.raise_()
        glass.apply(self, "ellipse", inset=(SIZE / 2 - R_RING))

    def dismiss(self):
        if hasattr(self, "_interactive_timer") and self._interactive_timer.isActive():
            self._interactive_timer.stop()
        app = QApplication.instance()
        if app:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        if self.isVisible():
            self.fade.stop()
            self.pop.stop()
            self.hide()
        self.hover = -1
        self._was_activated = False

    def eventFilter(self, watched, event):
        if getattr(self, "interactive", False) and self.isVisible():
            if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Escape, Qt.Key_Back):
                self.dismiss()
                return True
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                if watched is not self and not self.isAncestorOf(watched):
                    self.dismiss()
        return super().eventFilter(watched, event)

    def _poll_interactive(self):
        if not self.isVisible() or not getattr(self, "interactive", False):
            if hasattr(self, "_interactive_timer"):
                self._interactive_timer.stop()
            return

        # Global Esc key dismissal
        if keys.key_down(0x1B):
            self.dismiss()
            return

        lbutton = keys.primary_button_down()
        rbutton = keys.key_down(0x02)
        button_down = lbutton or rbutton

        # Wait until mouse is released if held during presentation
        if getattr(self, "_mouse_pressed_initial", False):
            if not button_down:
                self._mouse_pressed_initial = False
            return

        if not button_down:
            return

        # Global mouse press outside the wheel circle
        gx, gy = keys.cursor_pos()
        c = self.geometry().center()
        dist = math.hypot(gx - c.x(), gy - c.y())
        if dist > R_RING:
            self.dismiss()

    # Mouse & Keyboard interaction (interactive click & dismiss) --------
    def mouseMoveEvent(self, e):
        self._set_hover(self._hit(e.position()))

    def leaveEvent(self, e):
        self._set_hover(-1)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.dismiss()
            return
        if e.button() == Qt.LeftButton:
            i = self._hit(e.position())
            if 0 <= i < len(self.items):
                kind, ident, paths = self.kind, self.items[i][0], list(self.paths)
                self.dismiss()
                self.chosen.emit(kind, ident, paths)
                return
            # Clicked outside petals or on center capsule: dismiss
            self.dismiss()

    def mouseReleaseEvent(self, e):
        pass

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Back):
            self.dismiss()
        else:
            super().keyPressEvent(e)

    def changeEvent(self, e):
        if e.type() in (QEvent.ActivationChange, QEvent.WindowDeactivate):
            if getattr(self, "interactive", False):
                if self.isActiveWindow():
                    self._was_activated = True
                elif getattr(self, "_was_activated", False) and (time.monotonic() - getattr(self, "_shown_time", 0) > 0.35):
                    self.dismiss()
        super().changeEvent(e)

    def hideEvent(self, e):
        self.hover = -1
        super().hideEvent(e)

    # OLE drag & drop -------------------------------------------------
    @staticmethod
    def _paths(event) -> list[str]:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]

    def _hit(self, pos) -> int:
        if not self.items:
            return -1
        c = SIZE / 2
        s = self._scale or 1.0
        hit_idx = geo.hit_test(len(self.items), (pos.x() - c) / s, (pos.y() - c) / s, R_IN - 4, R_OUT + 4)
        if hit_idx >= 0:
            return min(hit_idx, len(self.items) - 1)
        return -1

    def _set_hover(self, i: int):
        if i != self.hover:
            self.hover = i
            if i >= 0 and self.settings.sound:
                if sys.platform == "win32" and self._sound.exists():
                    try:
                        import winsound
                        winsound.PlaySound(str(self._sound), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                    except Exception:
                        pass
                elif sys.platform != "win32":
                    try:
                        from PySide6.QtWidgets import QApplication
                        QApplication.beep()
                    except Exception:
                        pass
            self.update()

    def dragEnterEvent(self, e):
        paths = self._paths(e)
        if not paths:
            e.ignore(); return
        if paths != self.paths:                      # selection unknown/changed: rebuild petals from the real drag data
            self.set_content(self.kind, paths)
        e.setDropAction(Qt.CopyAction)               # always COPY so Explorer never treats the drop as a move
        e.accept()

    def dragMoveEvent(self, e):
        self._set_hover(self._hit(e.position()))
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def dragLeaveEvent(self, e):
        self._set_hover(-1)

    def dropEvent(self, e):
        paths = self._paths(e) or list(self.paths)
        i = self._hit(e.position())
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.hover = -1
        QTimer.singleShot(0, self.dismiss)
        if paths and 0 <= i < len(self.items):
            kind, ident = self.kind, self.items[i][0]
            # Deferred: dropEvent runs inside Explorer's drag-and-drop call; opening a modal dialog here would freeze Explorer.
            QTimer.singleShot(0, lambda: self.chosen.emit(kind, ident, paths))
