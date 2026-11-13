"""Settings window: customizable triggers (with live test, recording, conflict detection, reset) + options."""
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QSpinBox, QTabWidget, QSlider, QVBoxLayout, QWidget, QGridLayout, QButtonGroup,
                               QColorDialog)

from . import keys, settings as S, theme, __version__
from .theme import Panel
from .updater import check_github_update, UpdateDialog


class TriggerEditor(QGroupBox):
    def __init__(self, title, current, on_change):
        super().__init__(title)
        self.on_change = on_change
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.mods = {}
        for m in S.MODIFIERS:
            cb = QCheckBox(m.capitalize())
            cb.setChecked(m in current)
            cb.toggled.connect(lambda _=False: on_change())
            self.mods[m] = cb
            row.addWidget(cb)
        row.addWidget(QLabel("+"))
        self.extra = QComboBox()
        self.extra.addItem("(no extra key)", "")
        for k in S.EXTRA_KEYS:
            self.extra.addItem(k.capitalize() if len(k) > 1 and k not in S.FKEYS else k, k)
        ex = next((k for k in current if k in S.EXTRA_KEYS), "")
        self.extra.setCurrentIndex(max(0, self.extra.findData(ex)))
        self.extra.currentIndexChanged.connect(lambda _=0: on_change())
        row.addWidget(self.extra)
        lay.addLayout(row)
        r2 = QHBoxLayout()
        self.rec = QPushButton("Record…")
        self.rec.setToolTip("Click, then press and release the key combination you want")
        self.rec.clicked.connect(self._start_rec)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        r2.addWidget(self.rec); r2.addWidget(self.status, 1)
        lay.addLayout(r2)
        self.recording = False
        self.seen: set = set()

    def keys(self):
        k = [m for m, cb in self.mods.items() if cb.isChecked()]
        if self.extra.currentData():
            k.append(self.extra.currentData())
        return S.normalize(k)

    def set_keys(self, ks):
        ks = S.normalize(ks)
        for m, cb in self.mods.items():
            cb.blockSignals(True); cb.setChecked(m in ks); cb.blockSignals(False)
        ex = next((k for k in ks if k in S.EXTRA_KEYS), "")
        self.extra.blockSignals(True); self.extra.setCurrentIndex(max(0, self.extra.findData(ex))); self.extra.blockSignals(False)
        self.on_change()

    def _start_rec(self):
        self.recording, self.seen = True, set()
        self.rec.setText("Press keys…")

    def feed(self, pressed: set):
        """Called by the dialog timer with currently pressed key names (all tracked keys)."""
        if self.recording:
            if pressed:
                self.seen |= pressed
            elif self.seen:
                extras = [k for k in S.normalize(self.seen) if k in S.EXTRA_KEYS][:1]
                self.set_keys([k for k in self.seen if k in S.MODIFIERS] + extras)
                self.recording = False
                self.rec.setText("Record…")
            return
        mine = set(self.keys())
        tracked = pressed & (mine | set(S.MODIFIERS))          # same rule the drag monitor uses
        self.status.setText("✔ detected" if mine and tracked == mine else "")


class SettingsDialog(Panel):
    def __init__(self, settings: S.Settings, on_saved, parent=None):
        super().__init__("Vitarg Settings", 560, parent)
        self.s, self.on_saved = settings, on_saved
        tabs = QTabWidget()
        # ---------------- triggers
        t = QWidget(); tl = QVBoxLayout(t)
        self.conv = TriggerEditor("Conversion wheel — hold while dragging a file", settings.conv_trigger, self._validate)
        self.tools = TriggerEditor("Tools wheel — hold while dragging a file", settings.tools_trigger, self._validate)
        self.msg = QLabel(""); self.msg.setWordWrap(True); self.msg.setTextFormat(Qt.RichText)
        reset = QPushButton("Reset triggers to defaults (Shift / Alt + Shift)")
        reset.clicked.connect(lambda: (self.conv.set_keys(S.DEFAULT_CONV), self.tools.set_keys(S.DEFAULT_TOOLS)))
        for w in (self.conv, self.tools, self.msg, reset):
            tl.addWidget(w)
        tl.addStretch(1)
        tabs.addTab(t, "Triggers")
        # ---------------- output
        o = QWidget(); ol = QVBoxLayout(o)
        self.r_src = QRadioButton("Save next to the original file")
        self.r_dir = QRadioButton("Save to this folder:")
        (self.r_dir if settings.output_mode == "folder" else self.r_src).setChecked(True)
        self.folder = QLineEdit(settings.output_folder)
        br = QPushButton("Browse…"); br.clicked.connect(self._browse)
        fr = QHBoxLayout(); fr.addWidget(self.folder, 1); fr.addWidget(br)
        self.over = QComboBox(); self.over.addItem("Never overwrite (cat 2.jpg, cat 3.jpg …)", "never"); self.over.addItem("Overwrite existing files", "overwrite")
        self.over.setCurrentIndex(self.over.findData(settings.overwrite))
        for w in (self.r_src, self.r_dir):
            ol.addWidget(w)
        ol.addLayout(fr); ol.addWidget(QLabel("If the destination file already exists:")); ol.addWidget(self.over); ol.addStretch(1)
        tabs.addTab(o, "Output")
        # ---------------- formats
        f = QWidget(); fl = QGridLayout(f)
        def spin(lo, hi, v):
            sp = QSpinBox(); sp.setRange(lo, hi); sp.setValue(v); return sp
        self.jq, self.wq, self.crf, self.abr = spin(30, 100, settings.jpg_quality), spin(30, 100, settings.webp_quality), spin(0, 40, settings.video_crf), spin(64, 320, settings.audio_bitrate_k)
        self.preset = QComboBox(); self.preset.addItems(["Balanced", "Strong"]); self.preset.setCurrentText(settings.compress_preset)
        for i, (lab, w) in enumerate((("JPG quality", self.jq), ("WebP quality", self.wq), ("Video quality (CRF, lower = better)", self.crf),
                                       ("AAC audio bitrate (kbps)", self.abr), ("Default compression preset", self.preset))):
            fl.addWidget(QLabel(lab), i, 0); fl.addWidget(w, i, 1)
        fl.setRowStretch(5, 1)
        tabs.addTab(f, "Formats")
        # ---------------- general
        g = QWidget(); gl = QVBoxLayout(g)
        self.enabled = QCheckBox("Vitarg is active (watch for drags)"); self.enabled.setChecked(settings.enabled)
        self.sound = QCheckBox("Play a sound when a wheel option is highlighted"); self.sound.setChecked(settings.sound)
        self.login = QCheckBox("Start Vitarg when I sign in to Windows"); self.login.setChecked(settings.launch_at_login)
        self.auto_upd = QCheckBox("Automatically check for updates from GitHub"); self.auto_upd.setChecked(settings.auto_update)
        self.opacity = QSlider(Qt.Horizontal); self.opacity.setRange(30, 100); self.opacity.setValue(settings.opacity)
        self.btn_shortcut = QPushButton("Create Desktop Shortcut")
        self.btn_shortcut.clicked.connect(self._create_desktop_shortcut)
        self.btn_update = QPushButton(f"Check for Updates (v{__version__})")
        self.btn_update.clicked.connect(self._check_updates)
        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setObjectName("hint")
        for w in (self.enabled, self.sound, self.login, self.auto_upd, self.btn_shortcut, self.btn_update, self.lbl_update_status,
                  QLabel("Glass opacity (left = more see-through, applies instantly)"), self.opacity):
            gl.addWidget(w)
        gl.addStretch(1)
        tabs.addTab(g, "General")
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        self.opacity.valueChanged.connect(lambda v: self._appearance_edited(opacity=v))
        self.body.addWidget(tabs)
        row = QHBoxLayout()
        ra = QPushButton("Reset all"); ra.clicked.connect(self._reset_all)
        cancel = QPushButton("Close"); cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save"); self.save_btn.setObjectName("primary"); self.save_btn.clicked.connect(self._save)
        row.addWidget(ra); row.addStretch(1); row.addWidget(cancel); row.addWidget(self.save_btn)
        self.body.addLayout(row)
        self.timer = QTimer(self); self.timer.timeout.connect(self._poll); self.timer.start(30)
        self._autosave = QTimer(self); self._autosave.setSingleShot(True); self._autosave.setInterval(400)
        self._autosave.timeout.connect(self._flush_appearance)
        self._validate()

    # ---------------- appearance (live, no Save needed) -----------------
    def _build_appearance_tab(self):
        s = self.s
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Changes apply instantly and are remembered automatically."))
        grid = QGridLayout()
        self.ap_opacity = QSlider(Qt.Horizontal); self.ap_opacity.setRange(30, 100); self.ap_opacity.setValue(s.opacity)
        self.ap_opacity_lbl = QLabel(f"{s.opacity}%")
        self.ap_radius = QSlider(Qt.Horizontal); self.ap_radius.setRange(8, 40); self.ap_radius.setValue(s.radius)
        self.ap_radius_lbl = QLabel(f"{s.radius}px")
        self.ap_opacity.valueChanged.connect(lambda v: self._appearance_edited(opacity=v))
        self.ap_radius.valueChanged.connect(lambda v: self._appearance_edited(radius=v))
        grid.addWidget(QLabel("Opacity"), 0, 0); grid.addWidget(self.ap_opacity, 0, 1); grid.addWidget(self.ap_opacity_lbl, 0, 2)
        grid.addWidget(QLabel("Corner radius"), 1, 0); grid.addWidget(self.ap_radius, 1, 1); grid.addWidget(self.ap_radius_lbl, 1, 2)
        self.color_btns = {}
        for row, (key, text) in enumerate((("tint", "Glass tint"), ("highlight", "Highlight (hovered petal)"),
                                           ("text_color", "Text colour")), start=2):
            b = QPushButton(); b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, k=key: self._pick_color(k))
            self.color_btns[key] = b
            grid.addWidget(QLabel(text), row, 0); grid.addWidget(b, row, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        rs = QPushButton("Reset look to iOS default"); rs.clicked.connect(self._reset_look)
        lay.addWidget(rs)
        box = QGroupBox("Saved looks"); bl = QVBoxLayout(box)
        self.slot_rows = []
        for i in range(3):
            r = QHBoxLayout()
            tag = QLabel(f"{i + 1}"); tag.setFixedWidth(18)
            name = QLineEdit(); name.setPlaceholderText(f"Look {i + 1}")
            name.setText((s.appearance_slots[i] or {}).get("name", ""))
            sv = QPushButton("Save here"); sv.clicked.connect(lambda _=False, k=i: self._slot_save(k))
            ld = QPushButton("Load"); ld.clicked.connect(lambda _=False, k=i: self._slot_load(k))
            for x in (tag, name, sv, ld):
                r.addWidget(x) if x is not name else r.addWidget(x, 1)
            bl.addLayout(r)
            self.slot_rows.append((tag, name, sv, ld))
        lay.addWidget(box); lay.addStretch(1)
        self._sync_appearance_controls()
        return w

    def _sync_appearance_controls(self):
        s = self.s
        for sl, lbl, v in ((self.ap_opacity, self.ap_opacity_lbl, s.opacity), (self.opacity, None, s.opacity),
                           (self.ap_radius, self.ap_radius_lbl, s.radius)):
            sl.blockSignals(True); sl.setValue(v); sl.blockSignals(False)
        self.ap_opacity_lbl.setText(f"{s.opacity}%"); self.ap_radius_lbl.setText(f"{s.radius}px")
        for key, b in self.color_btns.items():
            c = QColor(getattr(s, key))
            fg = "#000" if c.lightnessF() > 0.5 else "#fff"
            b.setText(c.name().upper())
            b.setStyleSheet(f"QPushButton{{background:{c.name()};color:{fg};border:1px solid rgba(0,0,0,60);border-radius:8px;}}")
        for i, (tag, name, sv, ld) in enumerate(self.slot_rows):
            filled = bool(s.appearance_slots[i])
            ld.setEnabled(filled)
            tag.setText("●" if s.active_slot == i else f"{i + 1}")
            tag.setToolTip("Currently active look" if s.active_slot == i else "")

    def _appearance_edited(self, **kw):
        self.s.set_appearance(kw)
        self._apply_appearance()

    def _apply_appearance(self):
        theme.apply_appearance(self.s.appearance())
        self._sync_appearance_controls()
        self._autosave.start()

    def _flush_appearance(self):
        try:
            self.s.save()
        except OSError:
            pass
        self.on_saved()

    def _pick_color(self, key):
        original = getattr(self.s, key)
        dlg = QColorDialog(QColor(original), self)
        dlg.setOption(QColorDialog.DontUseNativeDialog, True)
        dlg.setWindowTitle("Choose colour")
        dlg.currentColorChanged.connect(lambda c: self._appearance_edited(**{key: c.name().upper()}))
        dlg.rejected.connect(lambda: self._appearance_edited(**{key: original}))
        dlg.open()
        self._color_dlg = dlg

    def _reset_look(self):
        self.s.reset_appearance(); self.s.active_slot = -1
        self._apply_appearance()

    def _slot_save(self, i):
        name = self.slot_rows[i][1].text().strip() or f"Look {i + 1}"
        self.s.appearance_slots[i] = {"name": name, **self.s.appearance()}
        self.s.active_slot = i
        self._sync_appearance_controls()
        self._flush_appearance()

    def _slot_load(self, i):
        slot = self.s.appearance_slots[i]
        if not slot:
            return
        self.s.set_appearance(slot); self.s.active_slot = i
        self._apply_appearance()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.folder.text())
        if d:
            self.folder.setText(d); self.r_dir.setChecked(True)

    def _poll(self):
        if sys.platform != "win32":
            return
        pressed = keys.pressed_set(set(S.VK))
        for ed in (self.conv, self.tools):
            ed.feed(pressed)

    def _validate(self):
        errs, warns = S.validate(self.conv.keys(), self.tools.keys())
        html = "".join(f"<div style='color:#a40000'>⛔ {e}</div>" for e in errs)
        html += "".join(f"<div style='color:#6b4a00'>⚠ {w}</div>" for w in warns)
        if not errs:
            html = f"<div style='color:#1b5e20'>✔ Conversion: <b>{S.label(self.conv.keys())}</b> &nbsp; Tools: <b>{S.label(self.tools.keys())}</b></div>" + html
        self.msg.setText(html)
        self.save_btn.setEnabled(not errs)

    def _create_desktop_shortcut(self):
        ok = S.create_desktop_shortcut()
        if ok:
            self.btn_shortcut.setText("Desktop Shortcut Created ✓")
            QTimer.singleShot(1500, lambda: self.btn_shortcut.setText("Create Desktop Shortcut"))

    def _check_updates(self):
        self.btn_update.setEnabled(False)
        self.lbl_update_status.setText("Checking GitHub for updates...")
        import threading
        def worker():
            rel = check_github_update(__version__)
            QTimer.singleShot(0, lambda: self._on_update_result(rel))
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_result(self, rel):
        self.btn_update.setEnabled(True)
        if rel:
            self.lbl_update_status.setText(f"Update available: {rel['version']}!")
            dlg = UpdateDialog(rel, __version__, self)
            dlg.exec()
        else:
            self.lbl_update_status.setText(f"You have the latest version (v{__version__}).")

    def _reset_all(self):
        d = S.Settings()
        self.conv.set_keys(d.conv_trigger); self.tools.set_keys(d.tools_trigger)
        self.r_src.setChecked(True); self.folder.setText(""); self.over.setCurrentIndex(0)
        self.jq.setValue(d.jpg_quality); self.wq.setValue(d.webp_quality); self.crf.setValue(d.video_crf); self.abr.setValue(d.audio_bitrate_k)
        self.preset.setCurrentText(d.compress_preset); self.enabled.setChecked(True); self.sound.setChecked(True); self.login.setChecked(False)
        self.auto_upd.setChecked(True)
        self.s.reset_appearance(); self._apply_appearance()

    def _save(self):
        s = self.s
        s.conv_trigger, s.tools_trigger = self.conv.keys(), self.tools.keys()
        s.output_mode = "folder" if self.r_dir.isChecked() and self.folder.text().strip() else "source"
        s.output_folder = self.folder.text().strip()
        s.overwrite = self.over.currentData()
        s.jpg_quality, s.webp_quality, s.video_crf, s.audio_bitrate_k = self.jq.value(), self.wq.value(), self.crf.value(), self.abr.value()
        s.compress_preset, s.enabled, s.sound = self.preset.currentText(), self.enabled.isChecked(), self.sound.isChecked()
        s.auto_update = self.auto_upd.isChecked()
        if s.launch_at_login != self.login.isChecked():
            s.launch_at_login = self.login.isChecked()
            try:
                S.set_launch_at_login(s.launch_at_login)
            except OSError:
                pass
        s.save()
        self.on_saved()
        self.save_btn.setText("Saved ✓")                      # stay open: closing is what threw focus to another window
        QTimer.singleShot(1200, lambda: self.save_btn.setText("Save"))
