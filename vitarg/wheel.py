"""The radial picker: a translucent always-on-top window that is a drop target for files.

Behavior:
- Opens when triggered (Shift / Alt+Shift during drag, Floating Drop Target, CLI, or Tray).
- Stays open even after releasing Shift / Alt+Shift or releasing the mouse button.
- Clicking (or dropping on) the CENTER circle switches between Conversion Wheel and Tools Wheel (in both directions).
- Clicking (or dropping on) a PETAL executes that conversion or tool and closes the wheel.
- Clicking OUTSIDE the wheel ring or pressing ESC closes the wheel.
"""
import math, os, shutil, subprocess, sys, time
from pathlib import Path

from PySide6.QtCore import (Qt, QPoint, QPointF, QRectF, QSize, Signal, Property,
                            QPropertyAnimation, QEasingCurve, QTimer, QEvent)
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen, QBrush,
                           QLinearGradient, QRadialGradient, QGuiApplication, QCursor)
from PySide6.QtWidgets import QWidget, QApplication

from . import engine, tools, geometry as geo, keys
from .icons import draw_icon
from .engine import app_dir
from . import glass
from . import theme
from .theme import alpha, tint

SIZE = 440                         # window edge in device-independent pixels
R_RING = 212.0                     # outer glass ring
R_OUT = 190.0                      # outer edge of petals
R_IN = 88.0                        # inner edge of petals
R_CORE = 82.0                      # centre disc (clicking inside R_CORE toggles Convert <-> Tools)
GAP_PX = 9.0                       # visual gap between petals
ROUND = 13.0                       # petal corner rounding

DEFAULT_CONV_FALLBACK = ["mp4", "mp3", "jpg", "png", "webp", "pdf", "wav", "docx", "zip"]


class Wheel(QWidget):
    chosen = Signal(str, str, list)        # kind ("conv"/"tools"), id, [paths]

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.kind = "conv"
        self.paths: list[str] = []
        self.items: list[tuple[str, str, str]] = []     # (id, label, icon)
        self.hover = -1
        self.hover_center = False
        self._shape_cache = []
        self.interactive = False
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFixedSize(SIZE, SIZE)
        self.setToolTip("Click a petal to run · Click center circle (or press Tab) to switch Convert ↔ Tools · Click outside or press Esc to close")
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setDuration(130)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self._scale = 0.9
        self.pop = QPropertyAnimation(self, b"scaleFactor", self)
        self.pop.setDuration(190)
        self.pop.setEasingCurve(QEasingCurve.OutBack)
        self._sound = app_dir() / "assets" / "HighlightSound.wav"
        self._linux_player = None
        if sys.platform != "win32":
            for pl in ("pw-play", "paplay", "aplay"):
                found = shutil.which(pl)
                if found:
                    self._linux_player = found
                    break
        self._font_label = QFont("Segoe UI Variable Display", 13, QFont.Bold)
        self._font_label.setFamilies([
            "Segoe UI Variable Display", "Segoe UI", "Inter", "Ubuntu",
            "Cantarell", "Noto Sans", "DejaVu Sans", "Arial"
        ])
        self._font_tool = QFont(self._font_label)
        self._font_tool.setPointSizeF(8.5)
        self._font_tool.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        self._font_cap_small = QFont(self._font_label)
        self._font_cap_small.setPointSizeF(10.5)
        self._font_cap_large = QFont(self._font_label)
        self._font_cap_large.setPointSizeF(12.5)
        self._font_cap_sub = QFont(self._font_label)
        self._font_cap_sub.setPointSizeF(7.5)
        self._font_cap_sub.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        self._layout_cache = []

        # Interactive dismissal & mouse-releaselatching state
        self._shown_time = 0.0
        self._mouse_pressed_initial = False
        self._last_outside_down = False
        self._interactive_timer = QTimer(self)
        self._interactive_timer.setInterval(30)
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

    def toggle_kind(self):
        """Switch between Conversion wheel ('conv') and Tools wheel ('tools')."""
        new_kind = "tools" if self.kind == "conv" else "conv"
        self.set_content(new_kind, self.paths)
        self._play_highlight_sound()

    def _rebuild(self):
        n = len(self.items)
        self._shape_cache = []
        self._layout_cache = []
        c = QPointF(SIZE / 2, SIZE / 2)
        mid_r = (R_IN + R_OUT) / 2

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
        if self.hover_center:
            return "TOOLS" if self.kind == "conv" else "CONVERT"
        if not self.items:
            return "NO OPTIONS"
        if not self.paths:
            return "CONVERT" if self.kind == "conv" else "TOOLS"
        if len(self.paths) == 1:
            return engine.fmt_of(self.paths[0]).upper() or "FILE"
        return f"{len(self.paths)} FILES"

    def center_subtext(self) -> str:
        """Secondary label inside the center capsule indicating click-to-switch mode."""
        if 0 <= self.hover < len(self.items):
            return "CONVERT" if self.kind == "conv" else "TOOL"
        return "↻ TOOLS" if self.kind == "conv" else "↻ CONVERT"

    # painting --------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        c = QPointF(SIZE / 2, SIZE / 2)
        p.translate(c); p.scale(self._scale, self._scale); p.translate(-c)
        # near-invisible base disc keeps the gaps hit-testable (layered windows ignore alpha 0)
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 6)); p.drawEllipse(c, R_RING, R_RING)
        # outer glass ring
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

        # centre ring + disc + interactive toggle capsule
        cg = QRadialGradient(c, R_CORE + 12)
        if self.hover_center:
            hl = QColor(theme.HIGHLIGHT)
            cg.setColorAt(0, hl.lighter(115)); cg.setColorAt(0.8, hl); cg.setColorAt(1, hl.darker(115))
            p.setPen(QPen(QColor(255, 255, 255, 245), 7))
        else:
            cg.setColorAt(0, tint(150, 104)); cg.setColorAt(0.8, tint(170)); cg.setColorAt(1, tint(190, 94))
            p.setPen(QPen(QColor(255, 255, 255, 200), 7))
        p.setBrush(cg); p.drawEllipse(c, R_CORE, R_CORE)

        cap = QRectF(c.x() - 60, c.y() - 30, 120, 60)
        capg = QLinearGradient(0, cap.top(), 0, cap.bottom())
        if self.hover_center:
            hl = QColor(theme.HIGHLIGHT)
            capg.setColorAt(0, hl.lighter(110)); capg.setColorAt(1, hl.darker(110))
            p.setPen(QPen(QColor(255, 255, 255, 255), 2.0))
        else:
            capg.setColorAt(0, tint(255, 106)); capg.setColorAt(1, tint(250, 98))
            p.setPen(QPen(QColor(255, 255, 255, 255), 1.4))
        p.setBrush(capg); p.drawRoundedRect(cap, 30, 30)

        txt = self.center_text()
        sub = self.center_subtext()
        p.setFont(self._font_cap_small if len(txt) > 6 else self._font_cap_large)
        p.setPen(QColor(theme.TEXT))
        top_rect = QRectF(cap.left(), cap.top() + 5, cap.width(), 30)
        p.drawText(top_rect, Qt.AlignCenter, txt)

        sub_col = QColor(theme.TEXT)
        sub_col.setAlpha(210 if self.hover_center else 155)
        p.setFont(self._font_cap_sub)
        p.setPen(sub_col)
        sub_rect = QRectF(cap.left(), cap.top() + 33, cap.width(), 18)
        p.drawText(sub_rect, Qt.AlignCenter, sub)

    # showing / hiding / latching -------------------------------------
    def present(self, kind: str, paths: list[str], gx: int, gy: int, interactive: bool = True):
        # If already visible and only selection paths resolved dynamically, update content in place
        already_visible = self.isVisible() and self.windowOpacity() >= 0.5
        if already_visible and paths and not self.paths:
            self.set_content(self.kind, paths)
            return

        self.interactive = True
        self.hover_center = False
        self.set_content(kind, paths)

        if not already_visible:
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

        # Keep WA_ShowWithoutActivating while mouse button is held so OS drag-and-drop is never interrupted
        down_now = bool(keys.primary_button_down() or keys.key_down(0x02))
        self.setAttribute(Qt.WA_ShowWithoutActivating, down_now)

        if not self.isVisible() or self.windowOpacity() < 0.95:
            self.setWindowOpacity(0.0)
            self.show()
            self.fade.stop(); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0); self.fade.start()
            self.pop.stop(); self.pop.setStartValue(0.88); self.pop.setEndValue(1.0); self.pop.start()
        else:
            self.show()

        self._shown_time = time.monotonic()
        self._mouse_pressed_initial = down_now
        self._last_outside_down = down_now
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
        if not down_now:
            self.activateWindow()
            self.setFocus()
        self._interactive_timer.start()

        self.raise_()
        glass.apply(self, "ellipse", inset=(SIZE / 2 - R_RING))

    def latch_interactive(self):
        """Called when initial drag mouse button is released without dropping on a petal.
        Keeps the wheel open and interactive until the user clicks outside, presses Esc, or picks a petal.
        """
        if not self.isVisible():
            return
        self.interactive = True
        self._mouse_pressed_initial = False
        self._last_outside_down = False
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        if not self._interactive_timer.isActive():
            self._interactive_timer.start()
        self.raise_()

    def dismiss(self):
        if hasattr(self, "_interactive_timer") and self._interactive_timer.isActive():
            self._interactive_timer.stop()
        app = QApplication.instance()
        if app:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        self.fade.stop()
        self.pop.stop()
        self.setWindowOpacity(0.0)
        self.hide()
        self.hover = -1
        self.hover_center = False
        self.setCursor(Qt.ArrowCursor)
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def eventFilter(self, watched, event):
        if self.isVisible():
            if event.type() == QEvent.KeyPress:
                if event.key() in (Qt.Key_Escape, Qt.Key_Back):
                    self.dismiss()
                    return True
                if event.key() == Qt.Key_Tab:
                    self.toggle_kind()
                    return True
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                if watched is not self and not self.isAncestorOf(watched):
                    self.dismiss()
        return super().eventFilter(watched, event)

    def _poll_interactive(self):
        if not self.isVisible():
            if hasattr(self, "_interactive_timer"):
                self._interactive_timer.stop()
            return

        # 1. Global Esc key dismissal
        if keys.key_down(0x1B):
            self.dismiss()
            return

        lbutton = keys.primary_button_down()
        rbutton = keys.key_down(0x02)
        button_down = lbutton or rbutton

        # 2. Wait until the initial mouse button (held when the wheel first appeared) is released
        if self._mouse_pressed_initial:
            if not button_down:
                self._mouse_pressed_initial = False
                self._last_outside_down = False
            return

        # 3. Detect a new mouse press outside the wheel ring (dist > R_RING)
        if button_down and not self._last_outside_down:
            self._last_outside_down = True
            gx, gy = keys.cursor_pos()
            c = self.geometry().center()
            dist = math.hypot(gx - c.x(), gy - c.y())
            if dist > R_RING:
                self.dismiss()
                return
        elif not button_down:
            self._last_outside_down = False

    # Mouse & Keyboard interaction (interactive click, center toggle & dismiss) --------
    def _is_center_pos(self, pos) -> bool:
        c = SIZE / 2
        s = self._scale or 1.0
        dx, dy = (pos.x() - c) / s, (pos.y() - c) / s
        return math.hypot(dx, dy) <= R_CORE

    def _is_outside_ring(self, pos) -> bool:
        c = SIZE / 2
        s = self._scale or 1.0
        dx, dy = (pos.x() - c) / s, (pos.y() - c) / s
        return math.hypot(dx, dy) > R_RING

    def mouseMoveEvent(self, e):
        if not self.isVisible() or (self.windowOpacity() <= 0.05 and self.fade.state() != QPropertyAnimation.Running):
            return
        hit_i = self._hit(e.position())
        in_center = (hit_i < 0) and self._is_center_pos(e.position())
        if in_center != self.hover_center:
            self.hover_center = in_center
            self.setCursor(Qt.PointingHandCursor if in_center else Qt.ArrowCursor)
            self.update()
        self._set_hover(hit_i)

    def leaveEvent(self, e):
        if self.hover_center:
            self.hover_center = False
            self.setCursor(Qt.ArrowCursor)
        self._set_hover(-1)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.dismiss()
            return
        if e.button() == Qt.LeftButton:
            # 1. Clicked on a conversion/tool petal -> run action
            i = self._hit(e.position())
            if 0 <= i < len(self.items):
                kind, ident, paths = self.kind, self.items[i][0], list(self.paths)
                self.dismiss()
                if paths:
                    self.chosen.emit(kind, ident, paths)
                return
            # 2. Clicked on the center circle -> toggle between Convert and Tools views!
            if self._is_center_pos(e.position()):
                self.toggle_kind()
                return
            # 3. Clicked outside the outer ring -> dismiss
            if self._is_outside_ring(e.position()):
                self.dismiss()
                return
            # (Clicks on the narrow gap between petals inside R_RING are ignored so the wheel stays open)

    def mouseReleaseEvent(self, e):
        pass

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Back):
            self.dismiss()
        elif e.key() == Qt.Key_Tab:
            self.toggle_kind()
        else:
            super().keyPressEvent(e)

    def hideEvent(self, e):
        self.hover = -1
        self.hover_center = False
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        super().hideEvent(e)

    # OLE / XDND drag & drop ------------------------------------------
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

    def _play_highlight_sound(self):
        if not self.settings.sound:
            return
        if sys.platform == "win32" and self._sound.exists():
            try:
                import winsound
                winsound.PlaySound(str(self._sound), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except Exception:
                pass
        elif sys.platform != "win32" and self._sound.exists() and self._linux_player:
            try:
                subprocess.Popen(
                    [self._linux_player, str(self._sound)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def _set_hover(self, i: int):
        if not self.isVisible() or (self.windowOpacity() <= 0.05 and self.fade.state() != QPropertyAnimation.Running):
            self.hover = -1
            return
        if i != self.hover:
            self.hover = i
            if i >= 0:
                self._play_highlight_sound()
            self.update()

    def dragEnterEvent(self, e):
        paths = self._paths(e)
        if not paths:
            e.ignore(); return
        if paths != self.paths:                      # selection unknown/changed: rebuild petals from the real drag data
            self.set_content(self.kind, paths)
        e.setDropAction(Qt.CopyAction)               # always COPY so file manager never treats the drop as a move
        e.accept()

    def dragMoveEvent(self, e):
        hit_i = self._hit(e.position())
        in_center = (hit_i < 0) and self._is_center_pos(e.position())
        if in_center != self.hover_center:
            self.hover_center = in_center
            self.update()
        self._set_hover(hit_i)
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def dragLeaveEvent(self, e):
        self.hover_center = False
        self._set_hover(-1)

    def dropEvent(self, e):
        paths = self._paths(e) or list(self.paths)
        if paths and paths != self.paths:
            self.set_content(self.kind, paths)
        i = self._hit(e.position())
        in_center = (i < 0) and self._is_center_pos(e.position())
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.hover = -1
        self.hover_center = False

        # If dropped onto the center circle, toggle Convert <-> Tools and keep the wheel open!
        if in_center:
            self.toggle_kind()
            self.latch_interactive()
            return

        # If dropped onto a petal, close the wheel and execute the chosen conversion/tool
        if paths and 0 <= i < len(self.items):
            kind, ident = self.kind, self.items[i][0]
            QTimer.singleShot(0, self.dismiss)
            QTimer.singleShot(0, lambda: self.chosen.emit(kind, ident, paths))
            return

        # Otherwise (dropped on the ring/gap without selecting a petal), keep the wheel latched open
        self.latch_interactive()
