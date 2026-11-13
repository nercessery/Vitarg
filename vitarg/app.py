"""Tray application: wires the drag monitor, wheel, dialogs and background jobs together."""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QLockFile, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QBrush, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import engine, tools, theme, __version__
from .dialogs import CropDialog, FormDialog, ActionConfirmDialog
from .inspector import InspectorDialog
from .jobs import JobWindow
from .monitor import DragMonitor
from .settings import Settings, label
from .settingsdialog import SettingsDialog
from .wheel import Wheel
from .updater import check_github_update, UpdateDialog, UpdateCheckThread
from .undo import undo_manager


def make_icon() -> QIcon:
    p = engine.app_dir() / "assets" / "vitarg.png"
    if p.exists():
        return QIcon(str(p))
    pm = QPixmap(64, 64); pm.fill(Qt.transparent)
    q = QPainter(pm); q.setRenderHint(QPainter.Antialiasing)
    g = QRadialGradient(24, 22, 40); g.setColorAt(0, QColor("#8A2BE2")); g.setColorAt(1, QColor("#4C1D95"))
    q.setBrush(QBrush(g)); q.setPen(Qt.NoPen); q.drawEllipse(6, 8, 52, 52); q.end()
    return QIcon(pm)


class Controller:
    def __init__(self, app: QApplication, settings: Settings):
        self.app, self.s = app, settings
        self.jobs: set = set()
        self.settings_dlg = None
        self.wheel = Wheel(settings)
        self.monitor = DragMonitor(settings)
        self.monitor.trigger.connect(self.wheel.present)
        self.monitor.released.connect(lambda: QTimer.singleShot(350, self.wheel.dismiss))
        self.monitor.cancelled.connect(self.wheel.dismiss)
        self.wheel.chosen.connect(self.on_choice)
        self.tray = QSystemTrayIcon(make_icon(), app)
        self.tray.setToolTip("Vitarg")
        menu = QMenu()
        self.act_enabled = QAction("Active", menu, checkable=True, checked=settings.enabled)
        self.act_enabled.toggled.connect(self._toggle)
        self.info = QAction("", menu); self.info.setEnabled(False)
        self.act_undo = QAction("↩ Undo Last Operation", menu)
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self._tray_undo)
        st = QAction("Settings…", menu); st.triggered.connect(self.open_settings)
        upd = QAction("Check for Updates…", menu); upd.triggered.connect(lambda: self.check_for_updates(True))
        quit_ = QAction("Quit Vitarg", menu); quit_.triggered.connect(self.quit)
        for a in (self.info, self.act_enabled, self.act_undo, st, upd):
            menu.addAction(a)
        menu.addSeparator(); menu.addAction(quit_)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.open_settings() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.refresh_info()
        self.wheel.update()
        self.monitor.start()
        if settings.auto_update:
            QTimer.singleShot(4000, lambda: self.check_for_updates(interactive=False))

    # -------------------------------------------------------------
    def refresh_info(self):
        theme.apply_appearance(self.s.appearance())
        self.info.setText(f"Convert: {label(self.s.conv_trigger)}  ·  Tools: {label(self.s.tools_trigger)}")
        self.act_enabled.blockSignals(True); self.act_enabled.setChecked(self.s.enabled); self.act_enabled.blockSignals(False)

    def _toggle(self, on):
        self.s.enabled = on
        self.s.save()

    def open_settings(self):
        if self.settings_dlg is not None and self.settings_dlg.isVisible():
            self.settings_dlg.raise_(); self.settings_dlg.activateWindow(); return
        self.settings_dlg = SettingsDialog(self.s, self.refresh_info)
        self.settings_dlg.show(); self.settings_dlg.raise_(); self.settings_dlg.activateWindow()

    def quit(self):
        self.monitor.stop(); self.wheel.dismiss(); self.tray.hide(); self.app.quit()

    def check_for_updates(self, interactive: bool = True):
        self._upd_thread = UpdateCheckThread(__version__, self.app)
        self._upd_thread.finished_check.connect(lambda rel, err: self._on_update_result(rel, interactive, err))
        self._upd_thread.start()

    def _on_update_result(self, rel: Optional[dict], interactive: bool, status_msg: str = ""):
        if rel:
            dlg = UpdateDialog(rel, __version__)
            dlg.show(); dlg.raise_(); dlg.activateWindow()
            dlg.exec()
        elif interactive:
            msg = status_msg or f"You are running the latest version of Vitarg (v{__version__})."
            QMessageBox.information(None, "Vitarg", msg)

    def _tray_undo(self):
        if not undo_manager.can_undo():
            QMessageBox.information(None, "Vitarg", "No recent operations to undo.")
            return
        desc = undo_manager.last_description()
        success, msg, _ = undo_manager.undo()
        if success:
            QMessageBox.information(None, "Vitarg Undo", f"Operation reverted:\n{desc}")
        else:
            QMessageBox.warning(None, "Vitarg Undo", f"Undo failed: {msg}")

    # -------------------------------------------------------------
    def on_choice(self, kind: str, ident: str, paths: list):
        paths = [str(Path(p)) for p in paths]
        custom_name = ""

        if kind == "conv":
            src_fmt = "/".join(sorted({engine.fmt_of(p).upper() for p in paths}))
            title = f"Converting {src_fmt} → {ident.upper()}"

            if getattr(self.s, "prompt_rename", True):
                dlg = ActionConfirmDialog(f"{src_fmt} → {ident.upper()}", paths, ident, is_conv=True)
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                if not dlg.exec():
                    return
                custom_name = dlg.output_name()

            fn = lambda prog, cancel: engine.convert_batch(paths, ident, self.s, prog, cancel, custom_name=custom_name)
            target_or_tool = ident
        else:
            tool = tools.BY_ID[ident]
            if tool.custom == "inspect":
                dlg = InspectorDialog(paths[0])
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                dlg.exec()
                return
            params = {}
            if tool.custom == "crop":
                dlg = CropDialog(paths[0])
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                if not dlg.exec():
                    return
                params["box"] = dlg.box()
            elif tool.form:
                dlg = FormDialog(tool, self.s, preview_paths=paths)
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                if not dlg.exec():
                    return
                params = dlg.values()
                custom_name = params.get("custom_name", "")
            else:
                if getattr(self.s, "prompt_rename", True):
                    dlg = ActionConfirmDialog(tool.label.title(), paths, ident, is_conv=False)
                    dlg.show(); dlg.raise_(); dlg.activateWindow()
                    if not dlg.exec():
                        return
                    custom_name = dlg.output_name()
                    params["custom_name"] = custom_name

            title = tool.label.title()
            fn = lambda prog, cancel: tools.run_tool(ident, paths, params, self.s, prog, cancel)
            target_or_tool = ident
        sub = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} files"
        win = JobWindow(title, sub, fn, sources=paths, target_or_tool=target_or_tool, custom_name=custom_name)
        self.jobs.add(win)
        win.job_done.connect(lambda w: (self.jobs.discard(w), w.deleteLater()))
        win.start()


def selftest() -> int:
    """Used by the build script: proves the frozen bundle has its libraries and external tools."""
    report = Path(tempfile.gettempdir()) / "vitarg-selftest.txt"     # windowed exe has no console
    missing = [t for t in ("ffmpeg", "ffprobe", "pandoc") if not engine.find_tool(t)]
    try:
        import fitz, docx, PIL, PySide6, win32com.client, py7zr, urllib.request  # noqa
    except ImportError as e:
        report.write_text(f"MISSING MODULE: {e}")
        return 3
    report.write_text(f"selftest ok; missing tools: {missing or 'none'}")
    return 0 if not missing else 4


def main():
    if "--selftest" in sys.argv:
        return selftest()
    app = QApplication(sys.argv)
    app.setApplicationName("Vitarg")
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "vitarg-win.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Vitarg", "Vitarg is already running (look for its icon in the tray).")
        return 0
    first_run = not Settings.path().exists()
    settings = Settings.load()
    ctl = Controller(app, settings)
    app.ctl = ctl
    if first_run:
        settings.save()
        try:
            from .settings import create_desktop_shortcut
            create_desktop_shortcut()
        except Exception:
            pass
        QTimer.singleShot(600, ctl.open_settings)       # first run: show where the triggers are configured
    return app.exec()
