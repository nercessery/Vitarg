"""GitHub Releases auto-updater for Vitarg: checks for updates, downloads setup, and launches installer."""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, time, zipfile
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error

from . import engine

GITHUB_REPOS = ["nercessery/Vitarg"]
USER_AGENT = "Vitarg-App/1.0.5"

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
    """Parse 'v2.1.0' or '1.0.3.2' into (2, 1, 0) or (1, 0, 3, 2)."""
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


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file efficiently in 64KB chunks."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def generate_manifest(app_root: Path, version: str = "1.0.5") -> dict:
    """Generate a manifest mapping relative file paths to their size and SHA-256 hash."""
    app_root = Path(app_root).resolve()
    manifest = {
        "version": version,
        "generated_at": int(time.time()),
        "files": {},
    }
    for item in sorted(app_root.rglob("*")):
        if not item.is_file():
            continue
        rel = str(item.relative_to(app_root)).replace("\\", "/")
        if any(part.startswith((".", "__pycache__")) for part in rel.split("/")):
            continue
        try:
            sz = item.stat().st_size
            sha = compute_file_sha256(item)
            manifest["files"][rel] = {"size": sz, "sha256": sha}
        except Exception:
            pass
    return manifest


def diff_local_with_manifest(app_root: Path, manifest: dict) -> dict:
    """Compare local installed files with remote release manifest.

    Returns:
        {
            "tools_intact": bool,
            "to_update": list[str],
            "unchanged": list[str],
            "stale_files": list[str],
        }
    """
    app_root = Path(app_root).resolve()
    files_map = manifest.get("files", {})

    # Check critical tools
    if sys.platform == "win32":
        crit_tools = ["tools/ffmpeg.exe", "tools/ffprobe.exe", "tools/pandoc.exe"]
    else:
        crit_tools = ["tools/ffmpeg", "tools/ffprobe", "tools/pandoc"]

    tools_intact = True
    for ct in crit_tools:
        local_tool = app_root / ct
        if not local_tool.exists() or local_tool.stat().st_size < 1000:
            tools_intact = False
            break

    to_update = []
    unchanged = []
    for rel_str, meta in files_map.items():
        lp = app_root / rel_str
        if not lp.exists():
            to_update.append(rel_str)
            continue
        try:
            if lp.stat().st_size != meta.get("size", 0):
                to_update.append(rel_str)
                continue
            if meta.get("sha256") and compute_file_sha256(lp) != meta["sha256"]:
                to_update.append(rel_str)
                continue
            unchanged.append(rel_str)
        except Exception:
            to_update.append(rel_str)

    # Detect stale files inside _internal (clean up old version leftovers)
    stale_files = []
    internal_dir = app_root / "_internal"
    if internal_dir.exists():
        for item in internal_dir.rglob("*"):
            if not item.is_file():
                continue
            rel_str = str(item.relative_to(app_root)).replace("\\", "/")
            if rel_str not in files_map:
                stale_files.append(rel_str)

    return {
        "tools_intact": tools_intact,
        "to_update": to_update,
        "unchanged": unchanged,
        "stale_files": stale_files,
    }


def clean_stale_temp_installers(max_age_seconds: int = 1800) -> int:
    """Clean up old downloaded installer executables and zip packages from %TEMP%."""
    temp_dir = Path(tempfile.gettempdir())
    now = time.time()
    removed = 0
    patterns = ("Vitarg-Setup*.exe", "Vitarg-*.zip", "vitarg_staged*")
    for pat in patterns:
        for p in temp_dir.glob(pat):
            try:
                if (now - p.stat().st_mtime) > max_age_seconds:
                    if p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        p.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                pass
    return removed


def check_github_update_detailed(current_version: str) -> tuple[Optional[dict], str]:
    """Check GitHub API for a newer release. Returns (release_dict or None, status_message)."""
    cur_v = parse_semver(current_version)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    last_err = ""
    for repo in GITHUB_REPOS:
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
                            manifest_asset = None
                            app_zip_asset = None
                            setup_asset = None

                            target_ext = ".exe" if sys.platform == "win32" else ".tar.gz"
                            for a in assets:
                                name = a.get("name", "").lower()
                                if name == "manifest.json":
                                    manifest_asset = a
                                elif name in ("vitarg-app.zip", "vitarg-update.zip") or name.endswith("-app.zip"):
                                    app_zip_asset = a
                                elif ("setup" in name or "vitarg" in name or "linux" in name) and name.endswith(target_ext):
                                    setup_asset = a

                            if not setup_asset and assets:
                                for a in assets:
                                    if a.get("name", "").lower().endswith(target_ext):
                                        setup_asset = a
                                        break
                            if not setup_asset and assets and sys.platform != "win32":
                                for a in assets:
                                    if a.get("name", "").lower().endswith((".tar.gz", ".zip", ".appimage")):
                                        setup_asset = a
                                        break

                            # Check local tools
                            has_local_tools = bool(engine.find_tool("ffmpeg") and engine.find_tool("ffprobe"))

                            is_delta = False
                            chosen_asset = None
                            if sys.platform == "win32" and app_zip_asset and has_local_tools:
                                is_delta = True
                                chosen_asset = app_zip_asset
                            elif setup_asset:
                                chosen_asset = setup_asset
                            elif app_zip_asset:
                                chosen_asset = app_zip_asset
                            elif assets:
                                chosen_asset = assets[0]

                            if chosen_asset:
                                return {
                                    "repo": repo,
                                    "version": tag,
                                    "name": data.get("name") or f"Vitarg {tag}",
                                    "notes": data.get("body", "").strip(),
                                    "download_url": chosen_asset.get("browser_download_url"),
                                    "asset_name": chosen_asset.get("name"),
                                    "size": chosen_asset.get("size", 0),
                                    "is_delta": is_delta,
                                    "manifest_url": manifest_asset.get("browser_download_url") if manifest_asset else None,
                                    "setup_url": setup_asset.get("browser_download_url") if setup_asset else None,
                                }, f"New release {tag} available!"
                            else:
                                return None, f"Release {tag} found, but release asset ({target_ext}) is still compiling."
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
            self.finished_check.emit(None, f"Update check failed: {e}")


class DownloadThread(QThread):
    progress = Signal(float, int, int)       # fraction (0.0 - 1.0), bytes_dl, bytes_total
    finished = Signal(str)                  # path to downloaded file
    failed = Signal(str)                    # error message

    def __init__(self, download_url: str, filename: str, parent=None):
        super().__init__(parent)
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

        mb = self.info.get("size", 0) / 1048576.0
        delta_tag = ""
        if self.info.get("is_delta"):
            delta_tag = f'<br><span style="color: #34D399; font-weight: bold;">⚡ Smart Delta Update ({mb:.1f} MB) — existing tools preserved, fast update</span>'
        else:
            delta_tag = f'<br><span style="color: #60A5FA;">📦 Full Package ({mb:.1f} MB)</span>'

        ver_label = QLabel(f"A new version of Vitarg is available: <b>{release_info['version']}</b> (Current: {current_version}){delta_tag}")
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
            self.dl_thread.wait(1000)
        self.reject()

    def reject(self):
        if self.dl_thread and self.dl_thread.isRunning():
            self.dl_thread.cancel()
            self.dl_thread.wait(1000)
        super().reject()

    def closeEvent(self, e):
        if self.dl_thread and self.dl_thread.isRunning():
            self.dl_thread.cancel()
            self.dl_thread.wait(1000)
        super().closeEvent(e)

    def _start_download(self):
        self.btn_update.setEnabled(False)
        self.btn_later.setText("Cancel")
        self.bar.show()
        self.status.setText("Connecting to GitHub...")

        default_name = f"Vitarg-Setup-{self.info['version']}.exe" if sys.platform == "win32" else f"Vitarg-linux-x86_64.tar.gz"
        filename = self.info.get("asset_name") or default_name
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

    def _on_finished(self, downloaded_path: str):
        if sys.platform == "win32":
            self.status.setText("Download complete! Applying update...")
            self.bar.setValue(100)
            QTimer.singleShot(500, lambda: self._apply_update_and_exit(downloaded_path))
        else:
            self.status.setText(f"Download complete!\nSaved to: {downloaded_path}")
            self.bar.setValue(100)
            self.btn_later.setText("Close")
            self.btn_update.setText("Open Folder")
            self.btn_update.setEnabled(True)
            try:
                self.btn_update.clicked.disconnect()
            except Exception:
                pass
            self.btn_update.clicked.connect(lambda: subprocess.Popen(["xdg-open", str(Path(downloaded_path).parent)]))

    def _apply_update_and_exit(self, downloaded_path: str):
        dl_p = Path(downloaded_path)
        try:
            if dl_p.suffix.lower() == ".zip":
                # Smart Delta Update: extract to staging folder and apply
                staging_dir = Path(tempfile.gettempdir()) / f"vitarg_staged_{int(time.time())}"
                staging_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(dl_p, "r") as zf:
                    zf.extractall(staging_dir)

                target_dir = engine.app_dir()
                target_exe = target_dir / "Vitarg.exe"
                bat_path = Path(tempfile.gettempdir()) / "vitarg_apply_delta.bat"

                # Batch script to overwrite changed files, clean staging + zip, and restart
                bat_content = (
                    "@echo off\r\n"
                    "setlocal\r\n"
                    f'set "STAGING={staging_dir}"\r\n'
                    f'set "TARGET={target_dir}"\r\n'
                    f'set "EXE={target_exe}"\r\n'
                    f'set "ZIP={dl_p}"\r\n'
                    "\r\n"
                    ":: Wait 2 seconds for Vitarg process to terminate cleanly\r\n"
                    "timeout /t 2 /nobreak >nul\r\n"
                    "\r\n"
                    ":: Robocopy new files into target directory\r\n"
                    'robocopy "%STAGING%" "%TARGET%" /E /NP /NFL /NDL /NJH /NJS >nul\r\n'
                    "\r\n"
                    ":: Clean up staging folder and temporary zip\r\n"
                    'rmdir /S /Q "%STAGING%" >nul 2>&1\r\n'
                    'del /F /Q "%ZIP%" >nul 2>&1\r\n'
                    "\r\n"
                    ":: Restart updated Vitarg\r\n"
                    'start "" "%EXE%"\r\n'
                    "exit\r\n"
                )
                bat_path.write_text(bat_content, encoding="utf-8")
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=subprocess.DETACHED_PROCESS)
            else:
                # Full Inno Setup installer
                subprocess.Popen(
                    [str(dl_p), "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                    creationflags=subprocess.DETACHED_PROCESS
                )
        except Exception as e:
            self.status.setText(f"Could not apply update: {e}")
            self.btn_update.setEnabled(True)
            return

        # Clean quit current Vitarg app immediately
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _on_failed(self, err: str):
        self.status.setText(f"Update failed: {err}")
        self.bar.hide()
        self.btn_update.setEnabled(True)
        self.btn_later.setText("Close")
