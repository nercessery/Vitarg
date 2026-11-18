"""Tray application: wires the drag monitor, wheel, dialogs and background jobs together."""
from __future__ import annotations
import json, os, sys, tempfile, threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QLockFile, QTimer, Qt, QPoint
from PySide6.QtGui import (
    QAction, QColor, QIcon, QPainter, QPixmap, QBrush, QPen,
    QRadialGradient, QCursor, QGuiApplication
)
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon, QFileDialog, QWidget
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import engine, tools, theme, keys, __version__
from .dialogs import CropDialog, FormDialog, ActionConfirmDialog, ClipboardConvertDialog, PdfOrganizerDialog
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


class DropTargetWidget(QWidget):
    """Floating desktop widget allowing native drag-and-drop on Linux (X11 & Wayland)."""
    def __init__(self, ctl: Controller):
        super().__init__(None, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.ctl = ctl
        self.hover = False
        self._drag_pos = None
        self.setAcceptDrops(True)
        self.resize(72, 72)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip(
            "Vitarg Drop Target\n"
            "• Drag files here to Convert (hold Alt for Tools)\n"
            "• Double-click to select files\n"
            "• Right-click for options"
        )
        scr = QGuiApplication.primaryScreen()
        if scr:
            geom = scr.availableGeometry()
            self.move(geom.right() - 88, geom.bottom() - 96)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(40, 40, 50, 240) if self.hover else QColor(76, 29, 149, 210)
        border = QColor(138, 43, 226, 255) if self.hover else QColor(138, 43, 226, 200)
        p.setBrush(bg)
        p.setPen(QPen(border, 2.0 if self.hover else 1.2))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 16, 16)
        p.setPen(QColor(255, 255, 255, 230))
        font = p.font()
        font.setPointSize(18)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, "+")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.hover = True
            self.update()
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.hover = False
        self.update()
        e.accept()

    def dropEvent(self, e):
        self.hover = False
        self.update()
        urls = e.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths:
            mods = e.modifiers()
            uni = keys.universe_for(self.ctl.s.conv_trigger, self.ctl.s.tools_trigger)
            pressed = keys.pressed_set(uni)
            use_tools = bool(mods & Qt.AltModifier) or keys.matches(pressed, self.ctl.s.tools_trigger)
            self.ctl.present_files(paths, kind="tools" if use_tools else "conv")
        e.acceptProposedAction()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        elif e.button() == Qt.RightButton:
            menu = QMenu(self)
            menu.addAction("🔄 Convert Files…", lambda: self.ctl.select_files_dialog(kind="conv"))
            menu.addAction("🛠️ Open Tools for Files…", lambda: self.ctl.select_files_dialog(kind="tools"))
            menu.addAction("📋 Convert Clipboard Image…", self.ctl.convert_clipboard_action)
            menu.addSeparator()
            menu.addAction("Settings…", self.ctl.open_settings)
            menu.addAction("Hide Drop Target", lambda: self.ctl.act_drop.setChecked(False))
            menu.exec(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._drag_pos and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.ctl.select_files_dialog(kind="conv")


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

        self.drop_target = DropTargetWidget(self)

        self.tray = QSystemTrayIcon(make_icon(), app)
        self.tray.setToolTip("Vitarg")
        menu = QMenu()
        self.act_enabled = QAction("Active", menu, checkable=True, checked=settings.enabled)
        self.act_enabled.toggled.connect(self._toggle)
        self.info = QAction("", menu); self.info.setEnabled(False)

        self.act_select = QAction("🔄 Select Files to Convert…", menu)
        self.act_select.triggered.connect(lambda: self.select_files_dialog(kind="conv"))

        self.act_tools = QAction("🛠️ Select Files for Tools…", menu)
        self.act_tools.triggered.connect(lambda: self.select_files_dialog(kind="tools"))

        self.act_clip = QAction("📋 Convert Clipboard Image…", menu)
        self.act_clip.triggered.connect(self.convert_clipboard_action)

        self.act_drop = QAction("Floating Drop Target", menu, checkable=True)
        self.act_drop.setChecked(False)
        self.act_drop.toggled.connect(self._toggle_drop_target)

        self.act_undo = QAction("↩ Undo Last Operation", menu)
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self._tray_undo)
        st = QAction("Settings…", menu); st.triggered.connect(self.open_settings)
        upd = QAction("Check for Updates…", menu); upd.triggered.connect(lambda: self.check_for_updates(True))
        quit_ = QAction("Quit Vitarg", menu); quit_.triggered.connect(self.quit)
        for a in (self.info, self.act_enabled, self.act_select, self.act_tools, self.act_clip, self.act_drop, self.act_undo, st, upd):
            menu.addAction(a)
        menu.addSeparator(); menu.addAction(quit_)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.open_settings() if r == QSystemTrayIcon.Trigger else None)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if sys.platform != "win32":
            self.drop_target.show()
            self.act_drop.setChecked(True)

        self.ipc_server = QLocalServer(self.app)
        self.ipc_server.newConnection.connect(self._on_ipc_connection)
        server_name = f"vitarg-ipc-{os.getenv('USER') or os.getenv('USERNAME') or 'default'}"
        QLocalServer.removeServer(server_name)
        self.ipc_server.listen(server_name)

        self.refresh_info()
        self.wheel.update()
        self.monitor.start()
        if settings.auto_update:
            QTimer.singleShot(4000, lambda: self.check_for_updates(interactive=False))

    def _on_ipc_connection(self):
        sock = self.ipc_server.nextPendingConnection()
        if not sock:
            return
        if not sock.waitForReadyRead(500):
            sock.disconnectFromServer()
            return
        data = sock.readAll().data().decode("utf-8", errors="ignore")
        sock.disconnectFromServer()
        try:
            payload = json.loads(data)
            action = payload.get("action")
            kind = payload.get("kind", "conv")
            if action == "open":
                files = payload.get("files", [])
                if files:
                    self.present_files(files, kind=kind)
            elif action == "select":
                self.select_files_dialog(payload.get("initial_dir"), kind=kind)
            elif action == "activate":
                self.open_settings()
        except Exception:
            pass

    def _toggle_drop_target(self, on: bool):
        if on:
            self.drop_target.show()
            self.drop_target.raise_()
        else:
            self.drop_target.hide()

    def _get_invocation_pos(self) -> tuple[int, int]:
        screen = self.app.primaryScreen() or (self.app.screens()[0] if self.app.screens() else None)
        is_wayland = sys.platform != "win32" and (
            bool(os.environ.get("WAYLAND_DISPLAY"))
            or os.environ.get("XDG_SESSION_TYPE") == "wayland"
            or (QGuiApplication.platformName() and "wayland" in QGuiApplication.platformName().lower())
        )
        if is_wayland or screen is None:
            if screen:
                c = screen.availableGeometry().center()
                return c.x(), c.y()
            return 400, 300
        pos = QCursor.pos()
        if any(s.geometry().contains(pos) for s in self.app.screens()):
            return pos.x(), pos.y()
        if screen:
            c = screen.availableGeometry().center()
            return c.x(), c.y()
        return pos.x(), pos.y()

    def present_files(self, paths: list[str], kind: str = "conv"):
        valid = [str(Path(p)) for p in paths if os.path.exists(p)]
        if not valid:
            return
        gx, gy = self._get_invocation_pos()
        self.wheel.present(kind, valid, gx, gy, interactive=True)

    def select_files_dialog(self, initial_dir: Optional[str] = None, kind: str = "conv"):
        start_dir = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else ""
        title = "Select Files for Vitarg Tools" if kind == "tools" else "Select Files to Convert with Vitarg"
        files, _ = QFileDialog.getOpenFileNames(None, title, start_dir)
        if files:
            self.present_files(files, kind=kind)

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
        if hasattr(self, "ipc_server"):
            self.ipc_server.close()
        self.monitor.stop()
        self.wheel.dismiss()
        self.drop_target.hide()
        self.tray.hide()
        self.app.quit()

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

    def convert_clipboard_action(self):
        qimg = QGuiApplication.clipboard().image()
        if qimg.isNull():
            QMessageBox.information(
                None, "Vitarg Clipboard",
                "No image found in clipboard.\n\n"
                "Copy an image or take a screenshot first\n"
                "(e.g. Win+Shift+S or PrtScn) and try again."
            )
            return
        dlg = ClipboardConvertDialog(qimg, self.s)
        dlg.show(); dlg.raise_(); dlg.activateWindow()
        if dlg.exec() and dlg.saved_path:
            import subprocess
            try:
                if sys.platform == "win32":
                    subprocess.Popen(f'explorer /select,"{dlg.saved_path}"')
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(Path(dlg.saved_path).parent)])
                else:
                    subprocess.Popen(["xdg-open", str(Path(dlg.saved_path).parent)])
            except Exception:
                pass

    # -------------------------------------------------------------
    def on_choice(self, kind: str, ident: str, paths: list):
        paths = [str(Path(p)) for p in paths]
        custom_name = ""

        if kind == "conv":
            src_fmt = "/".join(sorted({engine.fmt_of(p).upper() for p in paths}))
            title = f"Converting {src_fmt} → {ident.upper()}"

            if ident == "pdf" and len(paths) > 1:
                dlg = PdfOrganizerDialog(paths)
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                if not dlg.exec():
                    return
                paths = dlg.ordered_paths()
                if not paths:
                    return
                custom_name = dlg.output_name()
                is_all_pdf = all(engine.fmt_of(p) == "pdf" for p in paths)
                tool_to_run = "merge_pdf" if is_all_pdf else "create_pdf"
                fn = lambda prog, cancel: tools.run_tool(tool_to_run, paths, {"custom_name": custom_name}, self.s, prog, cancel)
                target_or_tool = "pdf"
            else:
                params = {}
                if getattr(self.s, "prompt_rename", True):
                    dlg = ActionConfirmDialog(f"{src_fmt} → {ident.upper()}", paths, ident, is_conv=True, settings=self.s)
                    dlg.show(); dlg.raise_(); dlg.activateWindow()
                    if not dlg.exec():
                        return
                    params = dlg.values() if hasattr(dlg, "values") else {}
                    custom_name = params.get("custom_name", "") or dlg.output_name()

                fn = lambda prog, cancel: engine.convert_batch(paths, ident, self.s, prog, cancel, custom_name=custom_name, params=params)
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
            elif tool.custom == "pdf_organizer":
                dlg = PdfOrganizerDialog(paths)
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                if not dlg.exec():
                    return
                paths = dlg.ordered_paths()
                if not paths:
                    return
                custom_name = dlg.output_name()
                params["custom_name"] = custom_name
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
    if sys.platform != "win32":
        try:
            from . import fetcher
            fetcher.purge_windows_binaries()
        except Exception:
            pass
    missing = [t for t in ("ffmpeg", "ffprobe", "pandoc") if not engine.find_tool(t)]
    try:
        import fitz, docx, PIL, PySide6, py7zr, urllib.request  # noqa
        if sys.platform == "win32":
            import win32com.client  # noqa
    except ImportError as e:
        report.write_text(f"MISSING MODULE: {e}")
        return 3
    report.write_text(f"selftest ok; missing tools: {missing or 'none'}")
    return 0 if not missing else 4


def main():
    if "--selftest" in sys.argv:
        return selftest()

    # Extract CLI arguments
    select_mode = "--select" in sys.argv
    tools_mode = "--tools" in sys.argv
    kind = "tools" if tools_mode else "conv"
    cli_files = []
    initial_dir = None
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        p = os.path.abspath(arg)
        if os.path.isfile(p):
            cli_files.append(p)
        elif os.path.isdir(p) and initial_dir is None:
            initial_dir = p

    server_name = f"vitarg-ipc-{os.getenv('USER') or os.getenv('USERNAME') or 'default'}"
    app = QApplication(sys.argv)
    app.setApplicationName("Vitarg")
    app.setQuitOnLastWindowClosed(False)

    # Check for existing instance via IPC socket
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(200):
        if cli_files:
            msg = json.dumps({"action": "open", "files": cli_files, "kind": kind}).encode("utf-8")
        elif select_mode or initial_dir:
            msg = json.dumps({"action": "select", "initial_dir": initial_dir or "", "kind": kind}).encode("utf-8")
        else:
            msg = json.dumps({"action": "activate"}).encode("utf-8")
        sock.write(msg)
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0

    lock_name = "vitarg-win.lock" if sys.platform == "win32" else "vitarg.lock"
    lock = QLockFile(os.path.join(tempfile.gettempdir(), lock_name))
    lock.setStaleLockTime(30000)  # 30s stale lock recovery to prevent permanent lockout after crash
    if not lock.tryLock(100):
        QMessageBox.information(None, "Vitarg", "Vitarg is already running (look for its icon in the tray).")
        return 0

    first_run = not Settings.path().exists()
    settings = Settings.load()
    engine.set_cpu_mode(getattr(settings, "cpu_mode", "eco"))
    ctl = Controller(app, settings)
    app.ctl = ctl

    def _bg_housekeeping():
        try:
            from .updater import clean_stale_temp_installers
            clean_stale_temp_installers()
        except Exception:
            pass
        if sys.platform != "win32":
            try:
                from . import fetcher
                fetcher.purge_windows_binaries()
                # Proactively ensure native Linux tools are ready in background if missing from system PATH
                for tool_name in ("ffmpeg", "ffprobe", "pandoc"):
                    if not engine.find_tool(tool_name):
                        fetcher.ensure_linux_tool(tool_name)
            except Exception:
                pass

    threading.Thread(target=_bg_housekeeping, daemon=True).start()

    if getattr(settings, "context_menu", True):
        try:
            from .settings import set_context_menu
            set_context_menu(True)
        except Exception:
            pass

    if first_run:
        settings.save()
        try:
            from .settings import create_desktop_shortcut
            create_desktop_shortcut()
        except Exception:
            pass
        QTimer.singleShot(600, ctl.open_settings)       # first run: show where the triggers are configured

    if cli_files:
        QTimer.singleShot(250, lambda: ctl.present_files(cli_files, kind=kind))
    elif select_mode or initial_dir:
        QTimer.singleShot(250, lambda: ctl.select_files_dialog(initial_dir, kind=kind))

    return app.exec()
