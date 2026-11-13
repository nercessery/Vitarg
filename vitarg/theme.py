"""Colours, fonts and the shared rounded 'glass' panel used by every dialog."""
from PySide6.QtCore import Qt, QPoint, QRectF, QObject, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QBrush, QPen
from . import glass
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget

PURPLE = QColor("#7C3AED")          # royal deep purple accent
PURPLE_DARK = QColor("#5B21B6")
ORANGE = PURPLE
ORANGE_DARK = PURPLE_DARK
OPACITY = 0.75          # live value: updated instantly by apply_appearance()
TINT = QColor("#12111A")        # soft obsidian black glass tint
HIGHLIGHT = QColor("#7C3AED")   # hovered wheel petal (deep purple)
TEXT = QColor("#F5F5F7")
RADIUS = 28


class _Bus(QObject):
    changed = Signal()          # every open window listens and repaints


bus = _Bus()


def apply_appearance(d: dict) -> None:
    """Apply an appearance dict (see Settings.appearance()) to the whole UI immediately, no save needed."""
    global OPACITY, TINT, HIGHLIGHT, TEXT, RADIUS
    OPACITY = max(0.0, min(1.0, d.get("opacity", 70) / 100.0))
    for name, key in (("TINT", "tint"), ("HIGHLIGHT", "highlight"), ("TEXT", "text_color")):
        c = QColor(d.get(key, ""))
        if c.isValid():
            globals()[name] = c
    RADIUS = int(d.get("radius", 28))
    bus.changed.emit()


def tint(a: int = 255, shade: int = 100) -> QColor:
    """Glass tint with its alpha scaled by the glass opacity; shade >100 lightens, <100 darkens."""
    c = TINT.lighter(shade) if shade > 100 else TINT.darker(int(10000 / shade)) if shade < 100 else QColor(TINT)
    c.setAlpha(alpha(a))
    return c


def is_dark() -> bool:
    return TINT.lightnessF() < 0.5


def alpha(full: int = 255) -> int:
    """Scale a colour alpha by the glass opacity (Settings → General)."""
    return max(0, min(255, int(full * OPACITY)))


FONT_FAMILY = "Segoe UI Variable Display, Segoe UI, Arial"

def style() -> str:
    t = TEXT.name()
    r, g, bl = TEXT.red(), TEXT.green(), TEXT.blue()
    dark = is_dark()
    f = 0.28 if dark else 1.0          # white overlays are calmer on dark tints
    w = lambda n: f"rgba(255,255,255,{int(n * f)})"
    pop = TINT.name()
    primary_bg = "#7C3AED" if dark else w(225)
    primary_border = "#8B5CF6" if dark else w(255)
    primary_fg = "#FFFFFF" if dark else t
    primary_hover = "#6D28D9" if dark else w(255)
    tab_sel_bg = "#7C3AED" if dark else w(230)
    tab_sel_fg = "#FFFFFF" if dark else t
    slider_knob = "#A855F7" if dark else "#FFFFFF"
    input_bg = "rgba(255,255,255,22)" if dark else w(170)
    input_border = "rgba(255,255,255,42)" if dark else w(210)
    btn_bg = "rgba(255,255,255,26)" if dark else w(80)
    btn_border = "rgba(255,255,255,45)" if dark else w(120)
    btn_hover = "rgba(255,255,255,46)" if dark else w(170)
    return f"""
QLabel {{ color: {t}; font-family: 'Segoe UI Variable Display','Segoe UI'; font-size: 14px; }}
QLabel#title {{ font-size: 19px; font-weight: 600; color: {t}; }}
QLabel#hint {{ color: rgba({r},{g},{bl},170); font-size: 12px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {input_bg}; border: 1px solid {input_border}; border-radius: 8px;
    padding: 5px 8px; font-size: 14px; color: {t}; min-height: 22px; }}
QComboBox QAbstractItemView {{ background: {pop}; color: {t}; selection-background-color: {w(120)}; selection-color: {t}; }}
QPushButton {{ background: {btn_bg}; border: 1px solid {btn_border}; border-radius: 9px; padding: 8px 18px;
    font-size: 14px; font-weight: 600; color: {t}; }}
QPushButton:hover {{ background: {btn_hover}; }}
QPushButton#primary {{ background: {primary_bg}; color: {primary_fg}; border: 1px solid {primary_border}; }}
QPushButton#primary:hover {{ background: {primary_hover}; }}
QPushButton#primary:disabled {{ background: {w(90)}; color: rgba({r},{g},{bl},110); }}
QCheckBox, QRadioButton {{ color: {t}; font-size: 14px; spacing: 8px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {btn_bg}; color: {t}; padding: 7px 16px; border-radius: 9px; margin-right: 6px; font-weight: 600; }}
QTabBar::tab:selected {{ background: {tab_sel_bg}; color: {tab_sel_fg}; }}
QGroupBox {{ border: 1px solid {w(140)}; border-radius: 12px; margin-top: 14px; padding: 12px 10px 8px 10px; color: {t}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
QTextEdit {{ background: {input_bg}; border: 1px solid {input_border}; border-radius: 8px; color: {t}; font-family: Consolas; font-size: 12px; }}
QSlider::groove:horizontal {{ height: 6px; background: {w(110)}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {slider_knob}; width: 18px; margin: -6px 0; border-radius: 9px; border: 1px solid rgba(0,0,0,50); }}
"""


STYLE = style()         # kept for any importer; windows use style() so they follow live changes



def paint_panel(w: QWidget, p: QPainter, radius: float | None = None):
    radius = RADIUS if radius is None else radius
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(w.rect()).adjusted(1, 1, -1, -1), radius, radius)
    g = QLinearGradient(0, 0, 0, w.height())
    for pos, shade, a in ((0.0, 104, 255), (0.5, 100, 245), (1.0, 97, 235)):
        g.setColorAt(pos, tint(a, shade))
    p.fillPath(path, QBrush(g))
    edge = QColor(255, 255, 255, 150 if not is_dark() else 60)           # hairline edge like iOS materials
    p.setPen(QPen(edge, 1.2))
    p.drawPath(path)
    p.setPen(QPen(QColor(255, 255, 255, 90 if not is_dark() else 40), 1))
    p.drawLine(0, 62, w.width(), 62)


class Panel(QDialog):
    """Frameless rounded dialog: circular close button at left, centred title, body layout below."""

    def __init__(self, title: str, width: int = 400, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(style())
        self.setFixedWidth(width)
        self._drag = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar = QWidget()
        bar.setFixedHeight(62)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        close = QPushButton("✕")
        close.setFixedSize(34, 34)
        self._close_btn = close
        self._restyle_close()
        close.clicked.connect(self.reject)
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignCenter)
        spacer = QWidget()
        spacer.setFixedSize(34, 34)
        bl.addWidget(close)
        bl.addWidget(self.title, 1)
        bl.addWidget(spacer)
        root.addWidget(bar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(22, 14, 22, 18)
        self.body.setSpacing(12)
        root.addLayout(self.body)

        bus.changed.connect(self._on_theme)

    def _restyle_close(self):
        self._close_btn.setStyleSheet("QPushButton{background:rgba(255,255,255,110);border-radius:17px;padding:0;font-size:15px;"
                                      f"color:{TEXT.name()};}}QPushButton:hover{{background:rgba(255,255,255,190);}}")

    def _on_theme(self):
        self.setStyleSheet(style())
        self._restyle_close()
        if self.isVisible():
            glass.apply(self, "round", RADIUS)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        paint_panel(self, p)

    def showEvent(self, e):
        super().showEvent(e)
        glass.apply(self, "round", RADIUS)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.isVisible():
            glass.apply(self, "round", RADIUS)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 62:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
