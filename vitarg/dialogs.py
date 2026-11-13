"""Tool option dialogs: generic form dialog and the crop editor (matches the reference screenshot)."""
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush, QCursor, QIntValidator
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QComboBox, QSpinBox,
                               QDoubleSpinBox, QLineEdit, QColorDialog, QButtonGroup, QGridLayout, QSlider)

from . import cropmath as cm, engine
from . import theme
from .theme import Panel, ORANGE
from .tools import CHOICE, FLOAT, INT, COLOR


from .tools import PREVIEW_TOOLS, make_preview


def pil_image_to_qimage(im) -> QImage:
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4, QImage.Format_RGBA8888)
    return q.copy()


def checkerboard(size, cell=12):
    from PIL import Image
    bg = Image.new("RGBA", size, (255, 255, 255, 255))
    d = Image.new("RGBA", (cell, cell), (205, 205, 205, 255))
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                bg.paste(d, (x, y))
    return bg


class FormDialog(Panel):
    def __init__(self, tool, settings, parent=None, preview_paths=None):
        self.paths = list(preview_paths or [])
        has_prev = bool(self.paths) and tool.id in PREVIEW_TOOLS
        super().__init__(tool.label.title(), 540 if has_prev else 380, parent)
        self.tool = tool
        self.widgets = {}
        self.has_prev = has_prev
        self.preview_label = None
        self.info = None
        self.duration = 0.0
        if has_prev and tool.id in ("trim", "speed", "snapshot"):
            try:
                self.duration = engine.probe(self.paths[0])["duration"]
            except Exception:
                self.duration = 0.0
        if has_prev:
            self.preview_label = QLabel()
            self.preview_label.setAlignment(Qt.AlignCenter)
            self.preview_label.setFixedHeight(350)
            self.preview_label.setWordWrap(True)
            self.info = QLabel("")
            self.info.setObjectName("hint")
            self.info.setAlignment(Qt.AlignCenter)
            self.info.setWordWrap(True)
            self.body.addWidget(self.preview_label)
            self.body.addWidget(self.info)
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._render)
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        for r, f in enumerate(tool.form):
            grid.addWidget(QLabel(f["label"]), r, 0)
            k, d = f["kind"], f["default"]
            if f["key"] == "preset":
                d = settings.compress_preset
            if k == CHOICE:
                w = QComboBox(); w.addItems(f["choices"]); w.setCurrentText(str(d))
                w.currentTextChanged.connect(self._refresh)
            elif k == FLOAT:
                lo, hi = f["min"], f["max"]
                if self.duration and f["key"] in ("start", "end", "time"):
                    hi = self.duration
                    if f["key"] == "end":
                        d = self.duration
                w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(2); w.setSingleStep(0.1 if hi <= 10 else 0.5); w.setValue(d)
                w.valueChanged.connect(self._refresh)
                if has_prev:                                      # slider linked to the spin box (range read lazily)
                    sl = QSlider(Qt.Horizontal); sl.setRange(0, 1000)
                    rng = lambda w=w: (w.minimum(), w.maximum())
                    sl.setValue(int((w.value() - lo) / max(1e-9, hi - lo) * 1000))
                    sl.valueChanged.connect(lambda v, w=w, rng=rng: w.setValue(rng()[0] + (rng()[1] - rng()[0]) * v / 1000.0))
                    w.valueChanged.connect(lambda v, sl=sl, rng=rng: (sl.blockSignals(True),
                                           sl.setValue(int((v - rng()[0]) / max(1e-9, rng()[1] - rng()[0]) * 1000)), sl.blockSignals(False)))
                    grid.addWidget(sl, r, 1)
                    grid.addWidget(w, r, 2)
                    self.widgets[f["key"]] = w
                    continue
            elif k == INT:
                w = QSpinBox(); w.setRange(f["min"], f["max"]); w.setValue(d); w.valueChanged.connect(self._refresh)
            else:
                w = QPushButton(d); w.setProperty("hex", d)
                w.clicked.connect(lambda _=False, b=w: self._pick(b))
                self._paint(w, d)
            self.widgets[f["key"]] = w
            grid.addWidget(w, r, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        if tool.id == "resize" and "mode" in self.widgets:
            def _on_mode_change(m):
                is_scale = (m == "Scale %")
                if "scale" in self.widgets:
                    self.widgets["scale"].setEnabled(is_scale)
                if "width" in self.widgets:
                    self.widgets["width"].setEnabled(not is_scale)
                if "height" in self.widgets:
                    self.widgets["height"].setEnabled(not is_scale)
            self.widgets["mode"].currentTextChanged.connect(_on_mode_change)
            _on_mode_change(self.widgets["mode"].currentText())

        # Output Name section
        self.rename_edit = None
        if self.paths:
            ren_box = QWidget()
            rb_lay = QVBoxLayout(ren_box)
            rb_lay.setContentsMargins(0, 6, 0, 4)
            rb_lay.setSpacing(4)
            rb_lbl = QLabel("🏷️ Output File Name (Optional):")
            rb_lbl.setStyleSheet("color: #A0A0AB; font-size: 11px; font-weight: bold;")
            rb_lay.addWidget(rb_lbl)

            p0 = Path(self.paths[0])
            def_name = p0.stem if len(self.paths) == 1 else "{name}"
            self.rename_edit = QLineEdit(def_name)
            self.rename_edit.setStyleSheet(
                "background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.15); "
                "border-radius: 6px; padding: 4px 8px; color: #FFFFFF;"
            )
            self.rename_edit.returnPressed.connect(self.accept)
            rb_lay.addWidget(self.rename_edit)

            # Quick template buttons
            t_row = QHBoxLayout()
            t_row.setSpacing(4)
            for lbl, tag in (("+ Date", f"{def_name}_{{date}}"), ("+ 01", f"{def_name}_{{num}}"), ("-vitarg", f"{def_name}-vitarg"), ("Original", def_name)):
                b = QPushButton(lbl)
                b.setFixedHeight(22)
                b.setStyleSheet("background: rgba(255, 255, 255, 0.08); font-size: 10px; padding: 2px 6px; border-radius: 4px;")
                b.clicked.connect(lambda _=False, t=tag: self.rename_edit.setText(t))
                t_row.addWidget(b)
            t_row.addStretch(1)
            rb_lay.addLayout(t_row)
            self.body.addWidget(ren_box)

        row = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Apply"); ok.setObjectName("primary"); ok.clicked.connect(self.accept)
        row.addWidget(cancel); row.addStretch(1); row.addWidget(ok)
        self.body.addLayout(row)
        if has_prev:
            self._render()

    def _refresh(self, *_):
        if self.has_prev:
            self._timer.start(180)            # debounce: slow previews (video frames, compression) run once you pause

    def _render(self):
        try:
            im, text = make_preview(self.tool.id, self.paths, self.values())
        except Exception as e:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(f"Preview unavailable: {e}")
            self.info.setText("")
            return
        self.info.setText(text)
        if im is None:
            self.preview_label.setText("No preview for this file type")
            return
        im = im.convert("RGBA")
        base = checkerboard(im.size)
        base.alpha_composite(im)
        pm = QPixmap.fromImage(pil_image_to_qimage(base))
        self.preview_label.setPixmap(pm.scaled(500, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _paint(self, b, hexv):
        c = QColor(hexv)
        b.setStyleSheet(f"background:{hexv};color:{'#000' if c.lightness() > 128 else '#fff'};")

    def _pick(self, b):
        c = QColorDialog.getColor(QColor(b.property("hex")), self, "Choose color")
        if c.isValid():
            b.setProperty("hex", c.name().upper()); b.setText(c.name().upper()); self._paint(b, c.name())
            self._refresh()

    def values(self):
        out = {}
        for k, w in self.widgets.items():
            out[k] = (w.currentText() if isinstance(w, QComboBox) else w.value() if hasattr(w, "value") else w.property("hex"))
        if getattr(self, "rename_edit", None) and self.rename_edit.text().strip():
            out["custom_name"] = self.rename_edit.text().strip()
        return out


# ---------------------------------------------------------------------------- crop
def pil_to_qimage_crop(path, max_dim=1200) -> tuple[QImage, tuple[int, int]]:
    from PIL import ImageOps, Image
    im = ImageOps.exif_transpose(engine.load_image(path)).convert("RGBA")
    orig_w, orig_h = im.width, im.height
    if max(orig_w, orig_h) > max_dim:
        im.thumbnail((max_dim, max_dim), Image.BILINEAR)
    data = im.tobytes("raw", "RGBA")
    q = QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888)
    return q.copy(), (orig_w, orig_h)


class CropCanvas(QWidget):
    changed = Signal()
    HANDLE = 7

    def __init__(self, image: QImage, orig_size: tuple[int, int] | None = None, w=456, h=420):
        super().__init__()
        self.img = image
        orig_w, orig_h = orig_size if orig_size else (image.width(), image.height())
        self.bounds = (0.0, 0.0, float(orig_w), float(orig_h))
        self.sel = self.bounds
        self.ratio = None
        self.drag = None
        s = min(w / orig_w, h / orig_h)
        self.scale = s
        self.setFixedSize(int(orig_w * s), int(orig_h * s))
        self.setMouseTracking(True)

    def to_w(self, x, y):
        return QPointF(x * self.scale, y * self.scale)

    def to_i(self, pt):
        return (pt.x() / self.scale, pt.y() / self.scale)

    def set_sel(self, r):
        self.sel = r; self.update(); self.changed.emit()

    def set_ratio(self, ratio):
        self.ratio = ratio
        self.set_sel(cm.fit_ratio(self.sel, ratio, self.bounds))

    def reset(self):
        self.ratio = None
        self.set_sel(self.bounds)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.drawImage(self.rect(), self.img)
        l, t, r, b = self.sel
        full = QRectF(self.rect())
        sel = QRectF(self.to_w(l, t), self.to_w(r, b))
        dim = QColor(70, 70, 70, 170)
        for rc in (QRectF(0, 0, full.width(), sel.top()), QRectF(0, sel.bottom(), full.width(), full.height() - sel.bottom()),
                   QRectF(0, sel.top(), sel.left(), sel.height()), QRectF(sel.right(), sel.top(), full.width() - sel.right(), sel.height())):
            p.fillRect(rc, dim)
        p.setPen(QPen(ORANGE, 2)); p.setBrush(Qt.NoBrush); p.drawRect(sel)
        p.setPen(QPen(QColor(0, 0, 0, 110), 1)); p.setBrush(ORANGE)
        cx, cy = sel.center().x(), sel.center().y()
        for x, y in ((sel.left(), sel.top()), (sel.right(), sel.top()), (sel.left(), sel.bottom()), (sel.right(), sel.bottom())):
            p.drawRoundedRect(QRectF(x - 7, y - 7, 14, 14), 2, 2)
        for x, y, w, h in ((cx - 18, sel.top() - 3, 36, 6), (cx - 18, sel.bottom() - 3, 36, 6),
                           (sel.left() - 3, cy - 18, 6, 36), (sel.right() - 3, cy - 18, 6, 36)):
            p.drawRoundedRect(QRectF(x, y, w, h), 3, 3)

    CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
               "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
               "move": Qt.SizeAllCursor}

    def _hit(self, pos):
        return cm.hit_handle(self.sel, self.to_i(pos), 11 / self.scale)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            h = self._hit(e.position())
            if h:
                self.drag = (h, self.to_i(e.position()))

    def mouseMoveEvent(self, e):
        if self.drag is None:
            self.setCursor(self.CURSORS.get(self._hit(e.position()), Qt.ArrowCursor))
            return
        h, last = self.drag
        cur = self.to_i(e.position())
        if h == "move":
            self.set_sel(cm.move(self.sel, cur[0] - last[0], cur[1] - last[1], self.bounds))
            self.drag = (h, cur)
        else:
            self.set_sel(cm.resize(self.sel, h, cur, self.ratio, self.bounds))

    def mouseReleaseEvent(self, e):
        self.drag = None


class CropDialog(Panel):
    def __init__(self, path, parent=None):
        super().__init__("Crop Image", 520, parent)
        qimg, orig_sz = pil_to_qimage_crop(path)
        self.canvas = CropCanvas(qimg, orig_size=orig_sz)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(self.canvas); row.addStretch(1)
        self.body.addLayout(row)
        # aspect ratio segmented control
        seg = QHBoxLayout()
        seg.addWidget(QLabel("Aspect ratio")); seg.addStretch(1)
        self.group = QButtonGroup(self); self.group.setExclusive(True)
        holder = QWidget(); hl = QHBoxLayout(holder); hl.setContentsMargins(3, 3, 3, 3); hl.setSpacing(0)
        holder.setStyleSheet("background:rgba(255,255,255,70);border-radius:11px;")
        for name in cm.RATIOS:
            b = QPushButton(name); b.setCheckable(True); b.setChecked(name == "Free")
            b.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:8px;padding:6px 11px;color:" + theme.TEXT.name() + ";font-weight:600;}"
                            "QPushButton:checked{background:rgba(255,255,255,240);color:" + theme.TEXT.name() + ";}")
            b.clicked.connect(lambda _=False, n=name: self.canvas.set_ratio(cm.RATIOS[n]))
            self.group.addButton(b); hl.addWidget(b)
        seg.addWidget(holder)
        self.body.addLayout(seg)
        # size row
        sz = QHBoxLayout()
        self.w_edit, self.h_edit = QLineEdit(), QLineEdit()
        for e in (self.w_edit, self.h_edit):
            e.setValidator(QIntValidator(1, 1_000_000)); e.setFixedWidth(92)
        self.w_edit.editingFinished.connect(lambda: self._typed("w"))
        self.h_edit.editingFinished.connect(lambda: self._typed("h"))
        sz.addWidget(QLabel("W")); sz.addWidget(self.w_edit); sz.addSpacing(8)
        sz.addWidget(QLabel("H")); sz.addWidget(self.h_edit); sz.addWidget(QLabel("px")); sz.addStretch(1)
        self.body.addLayout(sz)
        btns = QHBoxLayout()
        reset = QPushButton("Reset"); reset.clicked.connect(self._reset)
        ok = QPushButton("Apply"); ok.setObjectName("primary"); ok.clicked.connect(self.accept)
        btns.addWidget(reset); btns.addStretch(1); btns.addWidget(ok)
        self.body.addLayout(btns)
        self.canvas.changed.connect(self._sync)
        self._sync()

    def _reset(self):
        self.group.buttons()[0].setChecked(True)
        self.canvas.reset()

    def _sync(self):
        l, t, r, b = self.canvas.sel
        self.w_edit.setText(str(round(r - l))); self.h_edit.setText(str(round(b - t)))

    def _typed(self, which):
        try:
            w, h = int(self.w_edit.text()), int(self.h_edit.text())
        except ValueError:
            return self._sync()
        self.canvas.set_sel(cm.set_size(self.canvas.sel, w, h, self.canvas.ratio, self.canvas.bounds, which))

    def box(self):
        return tuple(round(v) for v in self.canvas.sel)


# ---------------------------------------------------------------------------- action confirm / rename
class ActionConfirmDialog(Panel):
    """Pre-action confirmation and file rename dialog: let user edit file name before converting."""

    def __init__(self, title: str, paths: list[str], target_or_tool: str, is_conv: bool = True, parent=None):
        super().__init__(f"Vitarg: {title}", 480, parent)
        from pathlib import Path
        self.paths = [Path(p) for p in paths]
        self.target = target_or_tool
        self.is_conv = is_conv
        p0 = self.paths[0]
        n_files = len(self.paths)

        # 1. Source file header
        if n_files == 1:
            from .estimator import format_size
            try:
                sz = format_size(p0.stat().st_size)
            except Exception:
                sz = ""
            src_lbl = QLabel(f"📄 <b>{p0.name}</b> {f'({sz})' if sz else ''}")
        else:
            names = ", ".join(p.name for p in self.paths[:3])
            if n_files > 3:
                names += f"... (+{n_files - 3} more)"
            src_lbl = QLabel(f"📁 <b>{n_files} files selected:</b> {names}")
        src_lbl.setWordWrap(True)
        self.body.addWidget(src_lbl)

        # 2. Conversion / Action Preview badge
        if is_conv:
            try:
                from .estimator import estimate_conversion
                est = estimate_conversion(p0, target_or_tool)
                prev_badge = QLabel(f"📊 {est['summary']}")
                prev_badge.setStyleSheet(
                    "background: rgba(124, 58, 237, 0.15); border: 1px solid rgba(124, 58, 237, 0.35); "
                    "border-radius: 6px; padding: 6px 10px; color: #E0E7FF; font-size: 11px;"
                )
                prev_badge.setWordWrap(True)
                self.body.addWidget(prev_badge)
            except Exception:
                pass

        # 3. Rename Section
        ren_box = QWidget()
        r_lay = QVBoxLayout(ren_box)
        r_lay.setContentsMargins(0, 6, 0, 6)
        r_lay.setSpacing(4)

        r_title = QLabel("🏷️ Output File Name (Edit before converting):")
        r_title.setStyleSheet("color: #7C3AED; font-weight: bold; font-size: 12px;")
        r_lay.addWidget(r_title)

        ext = f".{target_or_tool.lower().lstrip('.')}" if is_conv else p0.suffix
        default_name = p0.stem if n_files == 1 else "{name}"

        self.name_edit = QLineEdit(default_name)
        self.name_edit.setStyleSheet(
            "background: rgba(0, 0, 0, 0.4); border: 1.5px solid #7C3AED; "
            "border-radius: 6px; padding: 6px 10px; color: #FFFFFF; font-size: 13px;"
        )
        self.name_edit.selectAll()
        self.name_edit.returnPressed.connect(self.accept)
        r_lay.addWidget(self.name_edit)

        # Template buttons
        t_row = QHBoxLayout()
        t_row.setSpacing(6)
        for label, pattern in (
            ("Original", default_name),
            ("+ Date", f"{default_name}_{{date}}"),
            ("+ 01", f"{default_name}_{{num}}"),
            ("-vitarg", f"{default_name}-vitarg")
        ):
            b = QPushButton(label)
            b.setFixedHeight(24)
            b.setStyleSheet("background: rgba(255, 255, 255, 0.08); font-size: 11px; padding: 2px 8px; border-radius: 4px;")
            b.clicked.connect(lambda _=False, p=pattern: self.name_edit.setText(p))
            t_row.addWidget(b)
        t_row.addStretch(1)
        r_lay.addLayout(t_row)

        hint = QLabel(f"Extension <b>{ext}</b> will be preserved automatically. Press Enter to proceed.")
        hint.setObjectName("hint")
        r_lay.addWidget(hint)
        self.body.addWidget(ren_box)

        # 4. Action Buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel (Esc)")
        cancel_btn.clicked.connect(self.reject)

        action_txt = f"Convert to {target_or_tool.upper()} ⚡" if is_conv else "Start Action ⚡"
        ok_btn = QPushButton(action_txt)
        ok_btn.setObjectName("primary")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(ok_btn)
        self.body.addLayout(btn_row)

    def output_name(self) -> str:
        return self.name_edit.text().strip()
