"""GitHub Releases auto-updater for Vitarg: checks for updates, downloads setup, and launches installer."""
from __future__ import annotations
import json, os, re, subprocess, sys, tempfile, threading
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error

GITHUB_REPOS = ["nercessery/Vitarg"]
USER_AGENT = "Vitarg-App/1.0.2"

try:
    from PySide6.QtCore import Qt, QThread, Signal, QTimer
    from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                                   QProgressBar, QTextEdit)
    from .theme import Panel
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    class QThread:
        def __init__(self, parent=None): pass
        def start(self): pass
    def Signal(*a, **k):
        class _Sig:
            def connect(self, fn): pass
            def emit(self, *a, **k): pass
        return _Sig()
    class Panel: pass


def parse_semver(tag: str) -> tuple[int, ...]:
    """Parse 'v2.1.0' or '2.1.0' into (2, 1, 0)."""
    clean = re.sub(r"^[vV]", "", tag.strip())
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            m = re.match(r"\d+", p)
            parts.append(int(m.group(0)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check_github_update_detailed(current_version: str) -> tuple[Optional[dict], str]:
    """Check GitHub API for a newer release. Returns (release_dict or None, status_message)."""
    cur_v = parse_semver(current_version)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    last_err = ""
    for repo in GITHUB_REPOS:
        # Check /releases/latest first, fallback to /releases list
        endpoints = [
            f"https://api.github.com/repos/{repo}/releases/latest",
            f"https://api.github.com/repos/{repo}/releases",
        ]
        for url in endpoints:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        raw = json.loads(resp.read().decode("utf-8"))
                        if isinstance(raw, list):
                            if not raw:
                                last_err = f"No releases published yet on {repo}."
                                continue
                            data = raw[0]
                        else:
                            data = raw

                        tag = data.get("tag_name", "")
                        remote_v = parse_semver(tag)
                        if remote_v > cur_v:
                            assets = data.get("assets", [])
                            setup_asset = None
                            for a in assets:
                                name = a.get("name", "").lower()
                                if ("setup" in name or "vitarg" in name) and name.endswith(".exe"):
                                    setup_asset = a
                                    break
                            if not setup_asset and assets:
                                for a in assets:
                                    if a.get("name", "").lower().endswith(".exe"):
                                        setup_asset = a
                                        break
                            if setup_asset:
                                return {
                                    "repo": repo,
                                    "version": tag,
                                    "name": data.get("name") or f"Vitarg {tag}",
                                    "notes": data.get("body", "").strip(),
                                    "download_url": setup_asset.get("browser_download_url"),
                                    "asset_name": setup_asset.get("name"),
                                    "size": setup_asset.get("size", 0),
                                }, f"New release {tag} available!"
                            else:
                                return None, f"Release {tag} found, but installer asset (.exe) is still compiling."
                        else:
                            return None, f"You are up to date (Latest release: {tag})."
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    last_err = f"No public releases found yet on {repo}."
                elif e.code == 403:
                    last_err = "GitHub API rate limit reached. Please wait a few minutes."
                else:
                    last_err = f"GitHub API error {e.code}: {e.reason}"
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = f"Network error checking GitHub: {e}"
            except Exception as e:
                last_err = f"Error checking GitHub: {e}"

    return None, (last_err or "No releases found on GitHub.")


def check_github_update(current_version: str) -> Optional[dict]:
    """Backward-compatible helper returning release dict or None."""
    rel, _ = check_github_update_detailed(current_version)
    return rel


class UpdateCheckThread(QThread):
    finished_check = Signal(object, str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            rel, msg = check_github_update_detailed(self.current_version)
            self.finished_check.emit(rel, msg)
        except Exception as e:
            self.finished_check.emit(None, f"Check failed: {e}")


class DownloadThread(QThread):
    progress = Signal(float, int, int)      # fraction (0.0..1.0), downloaded_bytes, total_bytes
    finished = Signal(str)                  # path to downloaded installer
    failed = Signal(str)                    # error message

    def __init__(self, download_url: str, filename: str):
        super().__init__()
        self.url = download_url
        self.filename = filename
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        target = Path(tempfile.gettempdir()) / self.filename
        try:
            headers = {"User-Agent": USER_AGENT}
            req = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 65536
                with open(target, "wb") as f:
                    while True:
                        if self._cancelled:
                            target.unlink(missing_ok=True)
                            self.failed.emit("Download cancelled")
                            return
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        frac = (downloaded / total) if total > 0 else 0.5
                        self.progress.emit(frac, downloaded, total)
            self.finished.emit(str(target))
        except Exception as e:
            target.unlink(missing_ok=True)
            self.failed.emit(str(e))


class UpdateDialog(Panel):
    """Sleek dark glass modal dialog notifying user of an available update and downloading it."""

    def __init__(self, release_info: dict, current_version: str, parent=None):
        super().__init__("Update Available", 500, parent)
        self.info = release_info
        self.cur_v = current_version
        self.dl_thread: Optional[DownloadThread] = None

        ver_label = QLabel(f"A new version of Vitarg is available: <b>{release_info['version']}</b> (Current: {current_version})")
        ver_label.setWordWrap(True)
        self.body.addWidget(ver_label)

        if release_info.get("notes"):
            notes_lbl = QLabel("Release Notes:")
            notes_lbl.setObjectName("hint")
            self.body.addWidget(notes_lbl)

            notes_box = QTextEdit()
            notes_box.setReadOnly(True)
            notes_box.setFixedHeight(120)
            notes_box.setText(release_info["notes"])
            self.body.addWidget(notes_box)

        self.status = QLabel("Ready to download and install.")
        self.status.setObjectName("hint")
        self.body.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setStyleSheet("QProgressBar { background: rgba(255,255,255,40); border-radius: 4px; }"
                               "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #A855F7); border-radius: 4px; }")
        self.bar.hide()
        self.body.addWidget(self.bar)

        btns = QHBoxLayout()
        self.btn_later = QPushButton("Later")
        self.btn_later.clicked.connect(self._on_later)
        self.btn_update = QPushButton("Update Now")
        self.btn_update.setObjectName("primary")
        self.btn_update.clicked.connect(self._start_download)
        btns.addWidget(self.btn_later)
        btns.addStretch(1)
        btns.addWidget(self.btn_update)
        self.body.addLayout(btns)

    def _on_later(self):
        if self.dl_thread and self.dl_thread.isRunning():
            self.dl_thread.cancel()
        self.reject()

    def _start_download(self):
        self.btn_update.setEnabled(False)
        self.btn_later.setText("Cancel")
        self.bar.show()
        self.status.setText("Connecting to GitHub...")

        filename = self.info.get("asset_name") or f"Vitarg-Setup-{self.info['version']}.exe"
        self.dl_thread = DownloadThread(self.info["download_url"], filename)
        self.dl_thread.progress.connect(self._on_progress)
        self.dl_thread.finished.connect(self._on_finished)
        self.dl_thread.failed.connect(self._on_failed)
        self.dl_thread.start()

    def _on_progress(self, frac: float, dl: int, total: int):
        pct = int(frac * 100)
        self.bar.setValue(pct)
        mb_dl = dl / 1048576.0
        mb_tot = total / 1048576.0 if total > 0 else 0.0
        if mb_tot > 0:
            self.status.setText(f"Downloading: {mb_dl:.1f} MB / {mb_tot:.1f} MB ({pct}%)")
        else:
            self.status.setText(f"Downloading: {mb_dl:.1f} MB...")

    def _on_finished(self, installer_path: str):
        self.status.setText("Download complete! Launching installer...")
        self.bar.setValue(100)
        # Start the installer and close Vitarg so files are replaced cleanly
        QTimer.singleShot(500, lambda: self._launch_installer_and_exit(installer_path))

    def _launch_installer_and_exit(self, installer_path: str):
        try:
            # Launch Inno Setup installer
            subprocess.Popen([installer_path], creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0)
        except Exception as e:
            self.status.setText(f"Could not launch installer: {e}")
            self.btn_update.setEnabled(True)
            return
        # Quit current Vitarg app immediately
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _on_failed(self, err: str):
        self.status.setText(f"Update failed: {err}")
        self.bar.hide()
        self.btn_update.setEnabled(True)
        self.btn_later.setText("Close")
