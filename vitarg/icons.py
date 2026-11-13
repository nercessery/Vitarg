"""Vector icons for the tools wheel, drawn with QPainter (no image files needed)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPainterPath, QColor


def _arrow(p, x0, y0, x1, y1, s):
    import math
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    a = math.atan2(y1 - y0, x1 - x0)
    for off in (0.55, -0.55):
        p.drawLine(QPointF(x1, y1), QPointF(x1 - s * math.cos(a + off), y1 - s * math.sin(a + off)))


def draw_icon(p: QPainter, name: str, cx: float, cy: float, size: float, color: QColor):
    p.save()
    p.translate(cx, cy)
    u = size / 24.0
    p.scale(u, u)
    pen = QPen(color, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    R = lambda x, y, w, h, r=2.5: p.drawRoundedRect(QRectF(x, y, w, h), r, r)
    L = lambda a, b, c, d: p.drawLine(QPointF(a, b), QPointF(c, d))
    if name == "compress":
        _arrow(p, -9, -9, -2, -2, 5); _arrow(p, 9, 9, 2, 2, 5)
        _arrow(p, 9, -9, 2, -2, 5); _arrow(p, -9, 9, -2, 2, 5)
    elif name == "metadata":
        path = QPainterPath()
        path.moveTo(-9, -2); path.lineTo(-1, -10); path.lineTo(9, -10); path.lineTo(9, 0); path.lineTo(1, 8); path.closeSubpath()
        p.drawPath(path); p.drawEllipse(QPointF(4, -5), 1.6, 1.6)
    elif name == "edit":
        for i, (y, k) in enumerate(((-6, -3), (0, 4), (6, -1))):
            L(-9, y, 9, y); p.setBrush(color); p.drawEllipse(QPointF(k, y), 2.4, 2.4); p.setBrush(Qt.NoBrush)
    elif name == "crop":
        L(-5, -10, -5, 5); L(-10, -5, 5, -5); L(5, -5, 5, 10); L(-5, 5, 10, 5)
    elif name == "addbg":
        R(-10, -8, 20, 16); p.drawEllipse(QPointF(-4, -3), 1.8, 1.8)
        path = QPainterPath(); path.moveTo(-10, 6); path.lineTo(-3, 0); path.lineTo(2, 4); path.lineTo(5, 1); path.lineTo(10, 6); p.drawPath(path)
    elif name == "normalize":
        for x, h in ((-8, 3), (-4, 8), (0, 12), (4, 6), (8, 3)):
            L(x, -h / 2, x, h / 2)
    elif name == "trim":
        L(-8, -8, 8, 8); L(-8, 8, 8, -8); p.drawEllipse(QPointF(-8, -8), 0.01, 0.01)
        L(-10, 0, 10, 0)
    elif name == "remove_audio":
        path = QPainterPath(); path.moveTo(-9, -3); path.lineTo(-5, -3); path.lineTo(0, -8); path.lineTo(0, 8); path.lineTo(-5, 3); path.lineTo(-9, 3); path.closeSubpath()
        p.drawPath(path); L(4, -5, 10, 5); L(10, -5, 4, 5)
    elif name == "speed":
        for dx in (-5, 3):
            path = QPainterPath(); path.moveTo(dx, -7); path.lineTo(dx + 6, 0); path.lineTo(dx, 7); p.drawPath(path)
    elif name == "snapshot":
        R(-10, -6, 20, 14); p.drawEllipse(QPointF(0, 1), 4, 4); L(-4, -6, -2, -9); L(-2, -9, 2, -9); L(2, -9, 4, -6)
    elif name == "split_pdf":
        R(-9, -9, 18, 18); L(0, -9, 0, 9)
    elif name == "extract":
        R(-9, 2, 18, 8); _arrow(p, 0, -10, 0, 3, 5)
    elif name == "merge_pdf":
        R(-10, -8, 10, 13); R(0, -5, 10, 13)
    elif name == "create_pdf":
        path = QPainterPath(); path.moveTo(-7, -10); path.lineTo(3, -10); path.lineTo(8, -5); path.lineTo(8, 10); path.lineTo(-7, 10); path.closeSubpath()
        p.drawPath(path); L(3, -10, 3, -5); L(3, -5, 8, -5)
    elif name == "collage":
        R(-10, -10, 9, 9, 1.5); R(1, -10, 9, 9, 1.5); R(-10, 1, 9, 9, 1.5); R(1, 1, 9, 9, 1.5)
    elif name == "join":
        R(-11, -5, 9, 10); R(2, -5, 9, 10); L(-2, 0, 2, 0)
    elif name == "resize":
        R(-9, -9, 18, 18, 2)
        _arrow(p, 5, 5, 10, 10, 4); _arrow(p, -5, -5, -10, -10, 4)
    else:
        p.drawEllipse(QPointF(0, 0), 8, 8)
    p.restore()
