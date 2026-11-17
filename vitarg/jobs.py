"""Background workers and progress window with Conversion Preview, Auto Rename, and Undo / Rollback."""
from __future__ import annotations
import os, subprocess, sys, threading, time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPainterPath, QBrush
from PySide6.QtWidgets import (QLabel, QPushButton, QTextEdit, QWidget, QHBoxLayout,
                               QVBoxLayout)

from . import engine
from .engine import Cancelled
from .estimator import estimate_conversion, format_size
from .theme import Panel, PURPLE
from .undo import undo_manager, notify_explorer


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
    """Custom-drawn royal purple progress bar (indeterminate until the first real value arrives)."""

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
        else:
            self.t.stop()

    def set_value(self, v):
        self.value = v
        if v >= 0:
            if self.t.isActive():
                self.t.stop()
        elif not self.t.isActive():
            self.t.start(30)
        self.update()

    def stop(self):
        if self.t.isActive():
            self.t.stop()

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(PURPLE)
        if self.value >= 0:
            p.drawRoundedRect(QRectF(0, 0, max(12.0, r.width() * min(1.0, self.value)), r.height()), 6, 6)
        else:
            w = r.width() * 0.3
            x = (r.width() + w) * self.phase - w
            path = QPainterPath(); path.addRoundedRect(QRectF(x, 0, w, r.height()), 6, 6)
            clip = QPainterPath(); clip.addRoundedRect(r, 6, 6)
            p.fillPath(path.intersected(clip), PURPLE)


class JobWindow(Panel):
    job_done = Signal(object)      # not 'finished': that name belongs to QDialog

    def __init__(self, title: str, subtitle: str, fn, sources: list[str] = None,
                 target_or_tool: str = "", custom_name: str = ""):
        super().__init__(title, 420)
        self.sources = [str(Path(s)) for s in (sources or [])]
        self.target = target_or_tool
        self.custom_name = custom_name
        self.outputs: list[str] = []
        self._auto_close_timer = None
        self._countdown = 8
        self._released = False

        self.sub = QLabel(subtitle)
        self.sub.setObjectName("hint")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setWordWrap(True)
        self.body.addWidget(self.sub)

        # 1. Conversion Preview & Output Size Estimator
        self.preview_lbl = None
        if self.sources and self.target and self.target not in ("crop", "edit", "metadata", "inspect"):
            try:
                est = estimate_conversion(self.sources[0], self.target)
                self.preview_lbl = QLabel(f"📊 {est['summary']}")
                self.preview_lbl.setStyleSheet(
                    "background: rgba(124, 58, 237, 0.15); border: 1px solid rgba(124, 58, 237, 0.35); "
                    "border-radius: 6px; padding: 5px 8px; color: #E0E7FF; font-size: 11px;"
                )
                self.preview_lbl.setWordWrap(True)
                self.preview_lbl.setAlignment(Qt.AlignCenter)
                self.body.addWidget(self.preview_lbl)
            except Exception:
                pass

        # Progress bar
        self.bar = Bar()
        self.body.addWidget(self.bar)

        # 2. Show chosen output name (read-only info badge, rename already handled by engine/tools)
        self.rename_container = QWidget()
        ren_lay = QVBoxLayout(self.rename_container)
        ren_lay.setContentsMargins(0, 4, 0, 4)
        ren_lay.setSpacing(4)
        if custom_name:
            name_lbl = QLabel(f"🏷️ Output name: <b>{custom_name}</b>")
            name_lbl.setStyleSheet("color: #A0A0AB; font-size: 11px;")
            ren_lay.addWidget(name_lbl)
        self.body.addWidget(self.rename_container)
        if not custom_name:
            self.rename_container.hide()

        # 3. CPU Mode Status Text (User requested: clean text badge, no selector buttons)
        self.cpu_container = QWidget()
        cpu_lay = QHBoxLayout(self.cpu_container)
        cpu_lay.setContentsMargins(0, 2, 0, 4)
        cpu_lay.setSpacing(6)

        mode = engine.get_cpu_mode()
        badge_text = "🍃 CPU: Eco Modu" if mode == "eco" else "⚡ CPU: Standart Mod"
        self.cpu_lbl = QLabel(badge_text)
        self.cpu_lbl.setStyleSheet(
            "color: #C4B5FD; background: rgba(124, 58, 237, 0.2); border: 1px solid rgba(139, 92, 246, 0.35); "
            "border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 500;"
        )
        cpu_lay.addWidget(self.cpu_lbl)
        cpu_lay.addStretch(1)
        self.body.addWidget(self.cpu_container)

        # Worker initialization
        self.err = None
        self.worker = Worker(fn)
        self.worker.progress.connect(lambda v: self.bar.set_value(v if v > 0 else -1.0))
        self.worker.done.connect(self._done)
        self.worker.crashed.connect(lambda m: self._fail([("Unexpected error", m)]))

    def start(self):
        self.show()
        self.worker.start()

    def _set_cpu_mode(self, mode: str):
        engine.set_cpu_mode(mode)
        mode_now = engine.get_cpu_mode()
        badge_text = "🍃 CPU: Eco Modu" if mode_now == "eco" else "⚡ CPU: Standart Mod"
        if hasattr(self, "cpu_lbl"):
            self.cpu_lbl.setText(badge_text)

    def _done(self, outs, errs):
        if hasattr(self, "cpu_container"):
            self.cpu_container.hide()
        if errs:
            self._fail(errs, bool(outs))
            return

        self.outputs = list(outs)
        self.bar.set_value(1.0)
        self.bar.hide()
        self.rename_container.hide()
        notify_explorer(outs)

        # Record to Undo Manager
        undo_manager.record(self.windowTitle(), outs)

        # Update Subtitle & Show result details
        out_names = [Path(o).name for o in outs[:3]]
        if len(outs) > 3:
            out_names.append(f"... +{len(outs)-3} more")
        self.sub.setText(f"✅ Success! Generated: {', '.join(out_names)}")
        self.sub.setStyleSheet("color: #34D399; font-weight: bold;")

        # Size Comparison & Visual Stats Card
        try:
            def _item_sz(p):
                try:
                    p = Path(p)
                    if not p.exists():
                        return 0
                    if p.is_dir():
                        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    return p.stat().st_size
                except OSError:
                    return 0

            in_sz = sum(_item_sz(s) for s in self.sources)
            out_sz = sum(_item_sz(o) for o in outs)
            if in_sz > 0 and out_sz > 0:
                diff = out_sz - in_sz
                pct = (abs(diff) / in_sz) * 100.0
                in_str, out_str = format_size(in_sz), format_size(out_sz)
                if diff < 0:
                    saved_str = format_size(abs(diff))
                    card_txt = f"📉 <b>{in_str}</b> ➔ <b>{out_str}</b> &nbsp;({pct:.1f}% smaller, saved {saved_str})"
                    card_style = (
                        "background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); "
                        "border-radius: 6px; padding: 6px 10px; color: #6EE7B7; font-size: 11px;"
                    )
                elif diff > 0:
                    card_txt = f"📈 <b>{in_str}</b> ➔ <b>{out_str}</b> &nbsp;(+{pct:.1f}%)"
                    card_style = (
                        "background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.4); "
                        "border-radius: 6px; padding: 6px 10px; color: #93C5FD; font-size: 11px;"
                    )
                else:
                    card_txt = f"📊 <b>{in_str}</b> ➔ <b>{out_str}</b> &nbsp;(same size)"
                    card_style = (
                        "background: rgba(107, 114, 128, 0.15); border: 1px solid rgba(107, 114, 128, 0.4); "
                        "border-radius: 6px; padding: 6px 10px; color: #D1D5DB; font-size: 11px;"
                    )
                stats_lbl = QLabel(card_txt)
                stats_lbl.setStyleSheet(card_style)
                stats_lbl.setAlignment(Qt.AlignCenter)
                self.body.addWidget(stats_lbl)
        except Exception:
            pass

        # Action Buttons Row (Undo / Rollback, Open Folder, Close)
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)

        self.undo_btn = QPushButton("↩ Undo / Rollback")
        self.undo_btn.setToolTip("Delete generated files and revert this operation")
        self.undo_btn.setStyleSheet(
            "background: rgba(239, 68, 68, 0.25); border: 1px solid rgba(239, 68, 68, 0.6); "
            "color: #FCA5A5; font-weight: bold; border-radius: 6px; padding: 6px 12px;"
        )
        self.undo_btn.clicked.connect(self._on_undo)
        actions_row.addWidget(self.undo_btn)

        open_btn = QPushButton("📂 Open Folder")
        open_btn.setStyleSheet("background: rgba(255, 255, 255, 0.1); border-radius: 6px; padding: 6px 10px;")
        open_btn.clicked.connect(self._open_folder)
        actions_row.addWidget(open_btn)

        actions_row.addStretch(1)

        self.close_btn = QPushButton(f"Done ({self._countdown}s)")
        self.close_btn.setObjectName("primary")
        self.close_btn.clicked.connect(self.close_and_release)
        actions_row.addWidget(self.close_btn)

        self.body.addLayout(actions_row)

        # Start graceful auto-close countdown
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.timeout.connect(self._on_countdown_tick)
        self._auto_close_timer.start(1000)

    def _on_countdown_tick(self):
        self._countdown -= 1
        if self._countdown <= 0:
            if self._auto_close_timer:
                self._auto_close_timer.stop()
            self.close_and_release()
        else:
            self.close_btn.setText(f"Done ({self._countdown}s)")

    def enterEvent(self, e):
        # Hovering stops countdown so user has unlimited time to use Undo
        if self._auto_close_timer and self._auto_close_timer.isActive():
            self._auto_close_timer.stop()
            self.close_btn.setText("Done")
        super().enterEvent(e)

    def _on_undo(self):
        if self._auto_close_timer:
            self._auto_close_timer.stop()
        success, msg, _ = undo_manager.undo()
        if success:
            self.sub.setText("↩ Reverted! Output file(s) removed.")
            self.sub.setStyleSheet("color: #F87171; font-weight: bold;")
            self.undo_btn.setEnabled(False)
            self.undo_btn.setText("Undone ✓")
            self.close_btn.setText("Close")
        else:
            self.sub.setText(f"Undo failed: {msg}")

    def _open_folder(self):
        if self._auto_close_timer:
            self._auto_close_timer.stop()
        if self.outputs:
            target = Path(self.outputs[0])
            try:
                if sys.platform == "win32":
                    subprocess.Popen(f'explorer /select,"{target}"')
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target.parent)])
                else:
                    subprocess.Popen(["xdg-open", str(target.parent)])
            except Exception:
                pass

    def _fail(self, errs, partial=False):
        if hasattr(self, "cpu_container"):
            self.cpu_container.hide()
        self.bar.hide()
        self.rename_container.hide()
        self.sub.setText("Some files could not be processed." if partial else "The operation failed.")
        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText("\n\n".join(f"{n}:\n{m}" for n, m in errs))
        box.setFixedHeight(140)
        self.body.addWidget(box)
        b = QPushButton("Close")
        b.setObjectName("primary")
        b.clicked.connect(self.close_and_release)
        self.body.addWidget(b)
        self.show()
        self.raise_()

    def close_and_release(self):
        if self._auto_close_timer:
            self._auto_close_timer.stop()
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            engine.kill_active_processes()
            self.worker.wait(1500)
        self.hide()
        if not getattr(self, "_released", False):
            self._released = True
            self.job_done.emit(self)

    def closeEvent(self, e):
        if self._auto_close_timer:
            self._auto_close_timer.stop()
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            engine.kill_active_processes()
            self.worker.wait(1500)
        if not getattr(self, "_released", False):
            self._released = True
            self.job_done.emit(self)
        super().closeEvent(e)

    def reject(self):
        self.close_and_release()
