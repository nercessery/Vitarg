"""Tool option dialogs: generic form dialog and the crop editor (matches the reference screenshot)."""
from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal, QSize
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush, QCursor, QIntValidator
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QComboBox, QSpinBox,
                               QDoubleSpinBox, QLineEdit, QColorDialog, QButtonGroup, QGridLayout, QSlider,
                               QListWidget, QListWidgetItem, QAbstractItemView, QFileDialog, QMessageBox)

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
            if tool.id == "compress" and f["key"] == "preset":
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

        if tool.id == "target_compress" and "preset" in self.widgets:
            import math
            src = Path(preview_paths[0]) if preview_paths else None
            dur = getattr(self, "duration", 0.0)
            orig_mb = 0.0
            if src and src.is_file():
                try:
                    orig_mb = src.stat().st_size / (1024 * 1024)
                except OSError:
                    orig_mb = 0.0
                if not dur:
                    try:
                        from .engine import probe
                        dur = float(probe(src).get("duration", 0.0))
                    except Exception:
                        dur = 0.0

            # Calculate minimum realistic size
            min_mb = 1
            if dur > 0:
                # 20 kbps video + 32 kbps audio = 52 kbps min
                min_bits = 52000 * dur
                min_mb = max(1, math.ceil(min_bits / (8 * 1024 * 1024 * 0.95)))

            # Filter preset combo items based on achievable size and original size
            combo = self.widgets["preset"]
            std_options = [("8 MB", 8), ("10 MB", 10), ("25 MB", 25), ("50 MB", 50)]
            valid_items = []
            for label, mb_val in std_options:
                # Only include if >= min_mb and (if orig_mb > 0) < orig_mb
                if mb_val >= min_mb:
                    if orig_mb <= 0 or mb_val < orig_mb:
                        valid_items.append(label)

            valid_items.append("Custom MB")
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(valid_items)
            combo.blockSignals(False)

            # Restrict Custom MB spinbox range
            if "custom_mb" in self.widgets:
                sb = self.widgets["custom_mb"]
                max_mb = max(min_mb + 10, int(orig_mb) if orig_mb > 0 else 2000)
                sb.setRange(min_mb, max_mb)
                # Set initial value to default or first valid option
                def_preset = tool.form[0]["default"] if tool.form else "25 MB"
                if def_preset in valid_items:
                    chosen_preset = def_preset
                elif valid_items and valid_items[0] != "Custom MB":
                    chosen_preset = valid_items[0]
                else:
                    chosen_preset = "Custom MB"
                combo.setCurrentText(chosen_preset)
                if chosen_preset != "Custom MB" and chosen_preset.split()[0].isdigit():
                    sb.setValue(int(chosen_preset.split()[0]))
                else:
                    sb.setValue(min_mb)

            # Add helpful status badge if video size is known
            if orig_mb > 0 or min_mb > 1:
                limit_info = QLabel(
                    f"ℹ️ Original: <b>{orig_mb:.1f} MB</b> &nbsp;·&nbsp; Minimum achievable: <b>{min_mb} MB</b>"
                )
                limit_info.setStyleSheet(
                    "background: rgba(124, 58, 237, 0.15); border: 1px solid rgba(124, 58, 237, 0.35); "
                    "border-radius: 6px; padding: 4px 8px; color: #E0E7FF; font-size: 11px; margin-top: 4px;"
                )
                limit_info.setAlignment(Qt.AlignCenter)
                self.body.addWidget(limit_info)

            def _on_target_change(p):
                is_custom = (p == "Custom MB")
                if "custom_mb" in self.widgets:
                    self.widgets["custom_mb"].setEnabled(is_custom)
                    if not is_custom and p.split()[0].isdigit():
                        self.widgets["custom_mb"].setValue(int(p.split()[0]))
            self.widgets["preset"].currentTextChanged.connect(_on_target_change)
            _on_target_change(self.widgets["preset"].currentText())

        if has_prev and tool.id in ("volume", "eq"):
            self.play_btn = QPushButton("🔊 Listen Preview Sample (2s)")
            self.play_btn.setStyleSheet(
                "background: rgba(124, 58, 237, 0.25); border: 1px solid rgba(124, 58, 237, 0.5); "
                "color: #E0E7FF; font-weight: bold; padding: 6px 12px; border-radius: 6px; margin: 4px 0;"
            )
            self.play_btn.clicked.connect(self._play_audio_sample)
            self.body.addWidget(self.play_btn)

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

    def _play_audio_sample(self):
        if not self.paths:
            return
        import threading, tempfile, subprocess, os, shutil, sys
        src = self.paths[0]
        vals = self.values()
        tool_id = self.tool.id
        def _bg():
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                from .tools import build_audio_filter
                vol = int(vals.get("volume", 100 if tool_id == "eq" else 150))
                pr = vals.get("preset", "Flat" if tool_id == "volume" else "Bass Boost")
                af = build_audio_filter(vol, pr)
                cmd = [engine.need_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-t", "2", "-i", str(src)]
                if af:
                    cmd += ["-filter:a", af]
                cmd += ["-c:a", "pcm_s16le", tmp_wav]
                subprocess.run(cmd, capture_output=True, creationflags=engine.NOWIN)
                if os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 0:
                    if sys.platform == "win32":
                        import winsound
                        winsound.PlaySound(tmp_wav, winsound.SND_FILENAME)
                    else:
                        for player in ("paplay", "aplay", "pw-play", "ffplay"):
                            p = shutil.which(player)
                            if p:
                                cmd = [p, "-nodisp", "-autoexit", tmp_wav] if player == "ffplay" else [p, tmp_wav]
                                subprocess.run(cmd, capture_output=True)
                                break
            finally:
                try:
                    os.unlink(tmp_wav)
                except OSError:
                    pass
        threading.Thread(target=_bg, daemon=True).start()


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
    """Pre-action confirmation, parameter configuration, and file rename dialog."""

    def __init__(self, title: str, paths: list[str], target_or_tool: str, is_conv: bool = True,
                 parent=None, settings=None):
        super().__init__(f"Vitarg: {title}", 520, parent)
        self.paths = [Path(p) for p in paths]
        self.target = target_or_tool
        self.is_conv = is_conv
        from .settings import Settings
        self.settings = settings or Settings()
        p0 = self.paths[0] if self.paths else None
        n_files = len(self.paths)

        # 1. Source file header
        if n_files == 0:
            src_lbl = QLabel("📁 <b>No files selected</b>")
        elif n_files == 1:
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
        if is_conv and p0:
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

        # 3. Conversion Options Section (when is_conv and target is audio or video)
        target_lower = str(target_or_tool).lower().lstrip(".")
        self.is_audio_target = target_lower in engine.AUDIO_OUT
        self.is_video_target = target_lower in engine.VIDEO_OUT and target_lower != "gif"
        self.has_audio_options = is_conv and (self.is_audio_target or self.is_video_target)

        if self.has_audio_options:
            opts_box = QWidget()
            opts_lay = QVBoxLayout(opts_box)
            opts_lay.setContentsMargins(0, 4, 0, 4)
            opts_lay.setSpacing(6)

            opts_title = QLabel("⚙️ Conversion Audio & Quality Options:")
            opts_title.setStyleSheet("color: #A78BFA; font-weight: bold; font-size: 12px;")
            opts_lay.addWidget(opts_title)

            grid = QGridLayout()
            grid.setVerticalSpacing(8)
            grid.setHorizontalSpacing(10)

            # Volume row (Slider + Spinbox + Status label)
            vol_lbl = QLabel("🔊 Volume:")
            vol_lbl.setStyleSheet("font-weight: 500;")
            grid.addWidget(vol_lbl, 0, 0)

            vol_row = QHBoxLayout()
            vol_row.setSpacing(8)
            self.vol_slider = QSlider(Qt.Horizontal)
            self.vol_slider.setRange(10, 600)
            self.vol_slider.setValue(100)
            self.vol_slider.setSingleStep(5)
            self.vol_slider.setPageStep(25)

            self.vol_spin = QSpinBox()
            self.vol_spin.setRange(10, 600)
            self.vol_spin.setValue(100)
            self.vol_spin.setSingleStep(5)
            self.vol_spin.setSuffix("%")
            self.vol_spin.setFixedWidth(75)

            self.vol_status = QLabel("Normal (100%)")
            self.vol_status.setFixedWidth(95)
            self.vol_status.setStyleSheet("color: #9CA3AF; font-size: 11px;")

            def _on_vol_changed(v):
                self.vol_spin.blockSignals(True)
                self.vol_slider.blockSignals(True)
                self.vol_spin.setValue(v)
                self.vol_slider.setValue(v)
                self.vol_spin.blockSignals(False)
                self.vol_slider.blockSignals(False)
                if v == 100:
                    self.vol_status.setText("Normal (100%)")
                    self.vol_status.setStyleSheet("color: #9CA3AF; font-size: 11px;")
                elif v > 100:
                    self.vol_status.setText(f"+{v - 100}% Boost")
                    self.vol_status.setStyleSheet("color: #34D399; font-size: 11px; font-weight: bold;")
                else:
                    self.vol_status.setText(f"-{100 - v}% Lower")
                    self.vol_status.setStyleSheet("color: #F87171; font-size: 11px;")

            self.vol_slider.valueChanged.connect(_on_vol_changed)
            self.vol_spin.valueChanged.connect(_on_vol_changed)

            vol_row.addWidget(self.vol_slider, stretch=1)
            vol_row.addWidget(self.vol_spin)
            vol_row.addWidget(self.vol_status)
            grid.addLayout(vol_row, 0, 1)

            # Equalizer preset row
            eq_lbl = QLabel("🎛️ Equalizer:")
            eq_lbl.setStyleSheet("font-weight: 500;")
            grid.addWidget(eq_lbl, 1, 0)

            self.eq_combo = QComboBox()
            self.eq_combo.addItems([
                "Flat (Original)",
                "Bass Boost (+8dB)",
                "Ultra Bass (+14dB)",
                "Vocal Boost",
                "Treble Boost",
                "Loudness & Clarity"
            ])
            self.eq_combo.setCurrentText("Flat (Original)")
            grid.addWidget(self.eq_combo, 1, 1)

            # Bitrate row (for audio targets or general audio quality)
            next_row = 2
            if self.is_audio_target:
                bitrate_lbl = QLabel("🎵 Bitrate:")
                bitrate_lbl.setStyleSheet("font-weight: 500;")
                grid.addWidget(bitrate_lbl, next_row, 0)

                self.bitrate_combo = QComboBox()
                self.bitrate_combo.addItems([
                    "320 kbps (High Quality)",
                    "256 kbps",
                    "192 kbps (Standard)",
                    "128 kbps (Compact)",
                    "96 kbps (Voice)"
                ])
                def_bitrate = getattr(self.settings, "audio_bitrate_k", 192)
                matched = False
                for i in range(self.bitrate_combo.count()):
                    if str(def_bitrate) in self.bitrate_combo.itemText(i):
                        self.bitrate_combo.setCurrentIndex(i)
                        matched = True
                        break
                if not matched:
                    self.bitrate_combo.setCurrentText("192 kbps (Standard)")
                grid.addWidget(self.bitrate_combo, next_row, 1)
                next_row += 1

            opts_lay.addLayout(grid)

            # Audio Preview Button
            self.play_btn = QPushButton("🔊 Listen Preview Sample (2s)")
            self.play_btn.setStyleSheet(
                "background: rgba(124, 58, 237, 0.25); border: 1px solid rgba(124, 58, 237, 0.5); "
                "color: #E0E7FF; font-weight: bold; padding: 6px 12px; border-radius: 6px; margin: 2px 0;"
            )
            self.play_btn.clicked.connect(self._play_preview_sample)
            opts_lay.addWidget(self.play_btn)

            self.body.addWidget(opts_box)

        # 4. Rename Section
        ren_box = QWidget()
        r_lay = QVBoxLayout(ren_box)
        r_lay.setContentsMargins(0, 6, 0, 6)
        r_lay.setSpacing(4)

        r_title = QLabel("🏷️ Output File Name (Edit before converting):")
        r_title.setStyleSheet("color: #7C3AED; font-weight: bold; font-size: 12px;")
        r_lay.addWidget(r_title)

        ext = f".{target_or_tool.lower().lstrip('.')}" if is_conv else (p0.suffix if p0 else "")
        default_name = p0.stem if (p0 and n_files == 1) else "{name}"

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

        # 5. Action Buttons
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

    def _get_selected_bitrate_k(self) -> int:
        if hasattr(self, "bitrate_combo"):
            txt = self.bitrate_combo.currentText()
            try:
                return int(txt.split()[0])
            except (ValueError, IndexError):
                pass
        return getattr(self.settings, "audio_bitrate_k", 192)

    def _play_preview_sample(self):
        if not self.paths:
            return
        import threading, tempfile, subprocess, os, shutil, sys
        src = self.paths[0]
        try:
            inf = engine.probe(src)
            if not inf.get("audio"):
                return
        except Exception:
            pass

        vol = self.vol_spin.value()
        eq_pr = self.eq_combo.currentText()
        from .tools import build_audio_filter
        af = build_audio_filter(vol, eq_pr)

        def _bg():
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                cmd = [engine.need_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-t", "2", "-i", str(src)]
                if af:
                    cmd += ["-filter:a", af]
                cmd += ["-c:a", "pcm_s16le", tmp_wav]
                subprocess.run(cmd, capture_output=True, creationflags=engine.NOWIN)
                if os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 0:
                    if sys.platform == "win32":
                        import winsound
                        winsound.PlaySound(tmp_wav, winsound.SND_FILENAME)
                    else:
                        for player in ("paplay", "aplay", "pw-play", "ffplay"):
                            p = shutil.which(player)
                            if p:
                                cmd = [p, "-nodisp", "-autoexit", tmp_wav] if player == "ffplay" else [p, tmp_wav]
                                subprocess.run(cmd, capture_output=True)
                                break
            finally:
                try:
                    os.unlink(tmp_wav)
                except OSError:
                    pass
        threading.Thread(target=_bg, daemon=True).start()

    def output_name(self) -> str:
        return self.name_edit.text().strip()

    def values(self) -> dict:
        out = {
            "custom_name": self.output_name()
        }
        if getattr(self, "has_audio_options", False):
            out["volume"] = self.vol_spin.value()
            out["bass_preset"] = self.eq_combo.currentText()
            out["bitrate_k"] = self._get_selected_bitrate_k()
        return out


# ---------------------------------------------------------------------------- visual PDF organizer & merger
class PdfOrganizerDialog(Panel):
    """Visual drag-and-drop PDF organizer and merger: reorder pages/files before creating PDF."""
    def __init__(self, paths: list[str], parent=None):
        super().__init__("Vitarg: PDF Page & File Organizer", 520, parent)
        from pathlib import Path
        self.paths = [Path(p) for p in paths]

        info_lbl = QLabel(f"📄 <b>{len(self.paths)} files selected.</b> Drag items to reorder pages/files:")
        info_lbl.setWordWrap(True)
        self.body.addWidget(info_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.setIconSize(QSize(42, 42))
        self.list_widget.setStyleSheet(
            "QListWidget { background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255, 255, 255, 0.15); "
            "border-radius: 8px; padding: 6px; color: #FFFFFF; font-size: 12px; } "
            "QListWidget::item { padding: 6px; border-radius: 6px; margin: 2px 0; } "
            "QListWidget::item:selected { background: rgba(124, 58, 237, 0.45); border: 1px solid #7C3AED; } "
            "QListWidget::item:hover { background: rgba(255, 255, 255, 0.08); }"
        )
        self.list_widget.setMinimumHeight(240)
        self.body.addWidget(self.list_widget)

        self._populate_list(self.paths)

        # Control Row (Up, Down, Remove, Add More)
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(6)
        up_btn = QPushButton("▲ Move Up")
        up_btn.clicked.connect(self._move_up)
        dn_btn = QPushButton("▼ Move Down")
        dn_btn.clicked.connect(self._move_down)
        rm_btn = QPushButton("✖ Remove")
        rm_btn.clicked.connect(self._remove_selected)
        add_btn = QPushButton("➕ Add Files…")
        add_btn.clicked.connect(self._add_files)
        for b in (up_btn, dn_btn, rm_btn, add_btn):
            b.setStyleSheet("background: rgba(255, 255, 255, 0.08); font-size: 11px; padding: 4px 10px; border-radius: 4px;")
            btn_bar.addWidget(b)
        btn_bar.addStretch(1)
        self.body.addLayout(btn_bar)

        # Output Name section
        ren_box = QWidget()
        rb_lay = QVBoxLayout(ren_box)
        rb_lay.setContentsMargins(0, 8, 0, 4)
        rb_lay.setSpacing(4)
        rb_lbl = QLabel("🏷️ Output PDF Name:")
        rb_lbl.setStyleSheet("color: #7C3AED; font-weight: bold; font-size: 11px;")
        rb_lay.addWidget(rb_lbl)

        def_name = "Merged.pdf" if any(p.suffix.lower() == ".pdf" for p in self.paths) else "Images.pdf"
        self.name_edit = QLineEdit(Path(def_name).stem)
        self.name_edit.setStyleSheet(
            "background: rgba(0, 0, 0, 0.35); border: 1.5px solid #7C3AED; "
            "border-radius: 6px; padding: 6px 10px; color: #FFFFFF; font-size: 13px;"
        )
        self.name_edit.returnPressed.connect(self.accept)
        rb_lay.addWidget(self.name_edit)
        self.body.addWidget(ren_box)

        # Action Buttons
        row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton("Create PDF ⚡")
        self.ok_btn.setObjectName("primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(self.ok_btn)
        self.body.addLayout(row)
        self._update_ok_btn()

    def _update_ok_btn(self):
        if hasattr(self, "ok_btn"):
            self.ok_btn.setEnabled(self.list_widget.count() > 0)

    def _populate_list(self, paths):
        from pathlib import Path
        from .estimator import format_size
        from .tools import thumb
        for p in paths:
            p = Path(p)
            sz = ""
            try:
                sz = f" ({format_size(p.stat().st_size)})"
            except Exception:
                pass
            item = QListWidgetItem(f"📄 {p.name}{sz}")
            item.setData(Qt.UserRole, str(p))
            sf = engine.fmt_of(p)
            if sf in engine.IMAGE_IN:
                try:
                    im = thumb(p, (64, 64))
                    item.setIcon(QPixmap.fromImage(pil_image_to_qimage(im)))
                except Exception:
                    pass
            elif sf == "pdf":
                try:
                    fz = engine._fitz()
                    with fz.open(str(p)) as doc:
                        if len(doc) > 0:
                            pix = doc[0].get_pixmap(dpi=50, alpha=False)
                            qim = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                            item.setIcon(QPixmap.fromImage(qim))
                except Exception:
                    pass
            self.list_widget.addItem(item)
        self._update_ok_btn()

    def _move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.list_widget.currentRow()
        if 0 <= row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def _remove_selected(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)
            self._update_ok_btn()

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files to Add to PDF")
        if files:
            from pathlib import Path
            self._populate_list([Path(f) for f in files])

    def accept(self):
        if self.list_widget.count() == 0:
            QMessageBox.warning(self, "No files", "Please keep at least one file to create a PDF.")
            return
        super().accept()

    def ordered_paths(self) -> list[str]:
        res = []
        for i in range(self.list_widget.count()):
            res.append(self.list_widget.item(i).data(Qt.UserRole))
        return res

    def output_name(self) -> str:
        t = self.name_edit.text().strip()
        if t.lower().endswith(".pdf"):
            t = t[:-4]
        return t


# ---------------------------------------------------------------------------- clipboard quick convert dialog
class ClipboardConvertDialog(Panel):
    """Popup dialog when taking screenshot / copying image to clipboard: change filename, format, and save."""
    def __init__(self, qimg: QImage, settings, parent=None):
        super().__init__("Vitarg: Convert Clipboard Image", 460, parent)
        from pathlib import Path
        import time
        self.qimg = qimg
        self.s = settings

        self.prev_lbl = QLabel()
        self.prev_lbl.setAlignment(Qt.AlignCenter)
        self.prev_lbl.setFixedHeight(180)
        pm = QPixmap.fromImage(qimg.scaled(380, 170, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.prev_lbl.setPixmap(pm)
        self.body.addWidget(self.prev_lbl)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("File Name:"), 0, 0)
        def_name = f"Screenshot_{time.strftime('%Y%m%d_%H%M%S')}"
        self.name_edit = QLineEdit(def_name)
        self.name_edit.setStyleSheet(
            "background: rgba(0, 0, 0, 0.35); border: 1.5px solid #7C3AED; "
            "border-radius: 6px; padding: 5px 8px; color: #FFFFFF;"
        )
        self.name_edit.selectAll()
        grid.addWidget(self.name_edit, 0, 1)

        grid.addWidget(QLabel("Format:"), 1, 0)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["PNG", "JPG", "WebP", "PDF", "BMP"])
        self.fmt_combo.setCurrentText("PNG")
        grid.addWidget(self.fmt_combo, 1, 1)

        grid.addWidget(QLabel("Folder:"), 2, 0)
        f_row = QHBoxLayout()
        out_def = settings.output_folder or str(Path.home() / "Desktop")
        self.dir_edit = QLineEdit(out_def)
        br_btn = QPushButton("Browse…")
        br_btn.clicked.connect(self._browse)
        f_row.addWidget(self.dir_edit, 1)
        f_row.addWidget(br_btn)
        grid.addLayout(f_row, 2, 1)

        self.body.addLayout(grid)

        row = QHBoxLayout()
        cancel = QPushButton("Cancel (Esc)")
        cancel.clicked.connect(self.reject)
        save_btn = QPushButton("Save Image ⚡")
        save_btn.setObjectName("primary")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._do_save)
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(save_btn)
        self.body.addLayout(row)
        self.saved_path = None

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _do_save(self):
        from pathlib import Path
        name = self.name_edit.text().strip() or "Screenshot"
        fmt = self.fmt_combo.currentText().lower()
        out_dir = Path(self.dir_edit.text().strip() or (Path.home() / "Desktop"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = engine.unique_name(out_dir, f"{name}.{fmt}", overwrite=(self.s.overwrite == "overwrite"))

        try:
            from PIL import Image
            conv = self.qimg.convertToFormat(QImage.Format_ARGB32)
            buffer = conv.bits().tobytes()
            pil_im = Image.frombuffer("RGBA", (conv.width(), conv.height()), buffer, "raw", "BGRA", 0, 1)

            if fmt == "png":
                pil_im.save(out_path, "PNG", optimize=True)
            elif fmt in ("jpg", "jpeg"):
                engine._flatten(pil_im).save(out_path, "JPEG", quality=self.s.jpg_quality)
            elif fmt == "webp":
                pil_im.save(out_path, "WEBP", quality=self.s.webp_quality)
            elif fmt == "pdf":
                engine._flatten(pil_im).save(out_path, "PDF", resolution=150.0)
            elif fmt == "bmp":
                engine._flatten(pil_im).save(out_path, "BMP")
            else:
                pil_im.save(out_path)

            self.saved_path = str(out_path)
            from .undo import undo_manager, notify_explorer
            undo_manager.record("Clipboard Image", [self.saved_path])
            notify_explorer([self.saved_path])
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save clipboard image:\n{e}")
