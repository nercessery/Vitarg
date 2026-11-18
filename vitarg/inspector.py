"""File Inspector: analyzes and displays detailed metadata, resolution, size, codecs, and EXIF tags."""
from __future__ import annotations
import datetime, hashlib, math, os, subprocess, sys, threading
from pathlib import Path
from typing import Optional

from . import engine
from .estimator import format_size

try:
    from PySide6.QtCore import Qt, QPointF, QRectF, QThread, Signal
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap
    from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                                   QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
                                   QTextEdit, QMessageBox)
    from .theme import Panel, PURPLE, TEXT, OPACITY
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    class Panel:
        def __init__(self, *a, **k): pass
    class QThread:
        def __init__(self, parent=None): pass
        def start(self): pass
        def isRunning(self): return False
        def wait(self, ms=0): pass
    def Signal(*a, **k):
        class _Sig:
            def connect(self, fn): pass
            def emit(self, *a, **k): pass
        return _Sig()
    PURPLE = None
    TEXT = None
    OPACITY = 0.75


def compute_sha256(path: Path, max_bytes: int = 25 * 1024 * 1024, cancel_event: Optional[threading.Event] = None) -> str:
    """Compute SHA-256 hash (up to max_bytes for speed on huge files)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            read = 0
            while chunk := f.read(65536):
                if cancel_event and cancel_event.is_set():
                    return "Calculation cancelled"
                h.update(chunk)
                read += len(chunk)
                if read >= max_bytes:
                    return f"{h.hexdigest()} (first {format_size(max_bytes)})"
        return h.hexdigest()
    except Exception as e:
        return f"Error: {e}"


class HashThread(QThread):
    finished = Signal(str)

    def __init__(self, path: Path, max_bytes: int = 25 * 1024 * 1024, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        result = compute_sha256(self.path, self.max_bytes, self.cancel_event)
        self.finished.emit(result)


def get_file_info(file_path: str | Path, compute_hash: bool = True) -> dict:
    """Collect deep metadata, resolution, codecs, and format properties."""
    p = Path(file_path).resolve()
    if not p.exists():
        return {"error": f"File does not exist: {p}"}

    stat = p.stat()
    src_fmt = engine.fmt_of(p).lower()
    fam = engine.family(src_fmt)

    info = {
        "name": p.name,
        "path": str(p),
        "folder": str(p.parent),
        "extension": p.suffix.lower(),
        "format": src_fmt.upper() or "UNKNOWN",
        "family": fam.capitalize(),
        "size_bytes": stat.st_size,
        "size_str": f"{format_size(stat.st_size)} ({stat.st_size:,} bytes)",
        "created": datetime.datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "sha256": compute_sha256(p) if compute_hash else "Computing in background...",
        "media": {},
        "metadata": {},
    }

    # Image info
    if fam == "image" or src_fmt in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico"):
        try:
            from PIL import Image, ImageOps, ExifTags
            with Image.open(p) as im:
                w, h = im.width, im.height
                mp = (w * h) / 1_000_000.0
                gcd = math.gcd(w, h)
                ratio = f"{w // gcd}:{h // gcd}" if gcd > 0 else "N/A"
                if w / max(1, h) in (16 / 9, 1.7777777777777777): ratio = "16:9"
                elif w / max(1, h) in (4 / 3, 1.3333333333333333): ratio = "4:3"
                elif w == h: ratio = "1:1"

                info["media"]["Dimensions"] = f"{w} × {h} pixels"
                info["media"]["Megapixels"] = f"{mp:.2f} MP"
                info["media"]["Aspect Ratio"] = ratio
                info["media"]["Color Mode"] = im.mode
                info["media"]["Format Spec"] = im.format_description or im.format or src_fmt.upper()
                if hasattr(im, "n_frames"):
                    info["media"]["Frames"] = str(im.n_frames)

                # EXIF tags
                ex = im.getexif()
                if ex:
                    for tag_id, val in ex.items():
                        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                        if isinstance(val, (bytes, bytearray)):
                            continue
                        info["metadata"][str(tag_name)] = str(val)
        except Exception as e:
            info["media"]["Error"] = f"Image analysis failed: {e}"

    # Audio/Video info
    if fam in ("audio", "video") or src_fmt in ("mp4", "mp3", "mkv", "avi", "mov", "webm", "wav", "flac", "m4a", "ogg", "aac"):
        try:
            pr = engine.probe(p)
            dur = pr.get("duration", 0.0)
            if dur > 0:
                mins, secs = divmod(int(dur), 60)
                hrs, mins = divmod(mins, 60)
                dur_str = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
                info["media"]["Duration"] = f"{dur_str} ({dur:.2f}s)"
            if pr.get("video"):
                w, h = pr.get("width", 0), pr.get("height", 0)
                if w and h:
                    info["media"]["Video Resolution"] = f"{w} × {h}"
                    gcd = math.gcd(w, h)
                    info["media"]["Aspect Ratio"] = f"{w//gcd}:{h//gcd}" if gcd > 0 else "N/A"
            info["media"]["Has Video Stream"] = "Yes" if pr.get("video") else "No"
            info["media"]["Has Audio Stream"] = "Yes" if pr.get("audio") else "No"
        except Exception as e:
            info["media"]["Probe"] = str(e)

    # PDF info
    if src_fmt == "pdf":
        try:
            import fitz
            with fitz.open(p) as doc:
                info["media"]["Page Count"] = str(len(doc))
                info["media"]["PDF Version"] = str(doc.metadata.get("format", "PDF"))
                for k, v in doc.metadata.items():
                    if v and str(v).strip():
                        info["metadata"][k.capitalize()] = str(v)
        except Exception:
            try:
                import pypdf
                reader = pypdf.PdfReader(str(p))
                info["media"]["Page Count"] = str(len(reader.pages))
                if reader.metadata:
                    for k, v in reader.metadata.items():
                        if v and str(v).strip():
                            info["metadata"][str(k).lstrip("/").capitalize()] = str(v)
            except Exception:
                pass

    return info


class InspectorDialog(Panel):
    """File Inspector modal dialog."""

    def __init__(self, file_path: str | Path, parent=None):
        super().__init__("File Inspector", 560, parent)
        self.file_path = Path(file_path)
        self.hash_thread: Optional[HashThread] = None
        self.info = get_file_info(self.file_path, compute_hash=False)

        # File header card
        header_card = QWidget()
        h_lay = QVBoxLayout(header_card)
        h_lay.setContentsMargins(10, 8, 10, 8)
        h_lay.setSpacing(4)

        title_lbl = QLabel(f"📄 {self.info.get('name', 'File')}")
        title_font = QFont("Segoe UI Variable Display", 13, QFont.Bold)
        title_lbl.setFont(title_font)
        title_lbl.setWordWrap(True)

        meta_sub = QLabel(f"{self.info.get('format', '')} • {self.info.get('size_str', '')} • {self.info.get('family', '')}")
        meta_sub.setObjectName("hint")
        meta_sub.setStyleSheet("color: #7C3AED; font-weight: bold;")

        h_lay.addWidget(title_lbl)
        h_lay.addWidget(meta_sub)
        self.body.addWidget(header_card)

        # Tab widget for organizing sections
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px; background: rgba(18, 17, 26, 0.6); }
            QTabBar::tab { background: rgba(255, 255, 255, 0.05); color: #A0A0AB; padding: 6px 14px; border-radius: 6px; margin: 2px; }
            QTabBar::tab:selected { background: #7C3AED; color: #FFFFFF; font-weight: bold; }
        """)

        # 1. General Tab
        tab_gen = QWidget()
        t_lay1 = QVBoxLayout(tab_gen)
        t_lay1.setContentsMargins(8, 8, 8, 8)
        table1 = self._make_table([
            ("File Name", self.info.get("name", "")),
            ("Directory", self.info.get("folder", "")),
            ("Format / Type", f"{self.info.get('format', '')} ({self.info.get('family', '')})"),
            ("File Size", self.info.get("size_str", "")),
            ("Date Created", self.info.get("created", "")),
            ("Date Modified", self.info.get("modified", "")),
            ("SHA-256 Checksum", self.info.get("sha256", "")),
        ])
        t_lay1.addWidget(table1)
        self._sha_item = table1.item(6, 1)
        self.tabs.addTab(tab_gen, "General")

        # 2. Dimensions & Stream Details Tab
        tab_media = QWidget()
        t_lay2 = QVBoxLayout(tab_media)
        t_lay2.setContentsMargins(8, 8, 8, 8)
        media_items = list(self.info.get("media", {}).items())
        if not media_items:
            media_items = [("Status", "No audio/video or graphic streams detected")]
        table2 = self._make_table(media_items)
        t_lay2.addWidget(table2)
        self.tabs.addTab(tab_media, "Media & Resolution")

        # 3. Metadata & Tags Tab
        tab_tags = QWidget()
        t_lay3 = QVBoxLayout(tab_tags)
        t_lay3.setContentsMargins(8, 8, 8, 8)
        tag_items = list(self.info.get("metadata", {}).items())
        if not tag_items:
            tag_items = [("Metadata", "No embedded EXIF or document tags found")]
        table3 = self._make_table(tag_items)
        t_lay3.addWidget(table3)
        self.tabs.addTab(tab_tags, "EXIF & Tags")

        self.body.addWidget(self.tabs)

        # Bottom Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        copy_btn = QPushButton("📋 Copy Info")
        copy_btn.clicked.connect(self._copy_info)

        open_btn = QPushButton("📂 Open Folder")
        open_btn.clicked.connect(self._open_folder)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(copy_btn)
        btn_row.addWidget(open_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        self.body.addLayout(btn_row)

        if _HAS_QT and self.file_path.is_file():
            self.hash_thread = HashThread(self.file_path)
            self.hash_thread.finished.connect(self._on_hash_computed)
            self.hash_thread.start()

    def _on_hash_computed(self, digest: str):
        self.info["sha256"] = digest
        if hasattr(self, "_sha_item") and self._sha_item is not None:
            self._sha_item.setText(digest)
            self._sha_item.setToolTip(digest)

    def closeEvent(self, e):
        if hasattr(self, "hash_thread") and self.hash_thread and self.hash_thread.isRunning():
            self.hash_thread.cancel()
            self.hash_thread.wait(1000)
        super().closeEvent(e)

    def reject(self):
        if hasattr(self, "hash_thread") and self.hash_thread and self.hash_thread.isRunning():
            self.hash_thread.cancel()
            self.hash_thread.wait(1000)
        super().reject()

    def accept(self):
        if hasattr(self, "hash_thread") and self.hash_thread and self.hash_thread.isRunning():
            self.hash_thread.cancel()
            self.hash_thread.wait(1000)
        super().accept()

    def _make_table(self, items: list[tuple[str, str]]) -> QTableWidget:
        tbl = QTableWidget(len(items), 2)
        tbl.setHorizontalHeaderLabels(["Property", "Value"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(False)
        tbl.setAlternatingRowColors(True)
        tbl.setStyleSheet("""
            QTableWidget { background: transparent; border: none; color: #F5F5F7; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:alternate { background: rgba(255, 255, 255, 0.03); }
            QHeaderView::section { background: rgba(0, 0, 0, 0.4); color: #7C3AED; font-weight: bold; border: none; padding: 4px; }
        """)
        for r, (k, v) in enumerate(items):
            k_item = QTableWidgetItem(str(k))
            k_item.setFlags(k_item.flags() & ~Qt.ItemIsEditable)
            k_item.setForeground(QColor("#A0A0AB"))
            v_item = QTableWidgetItem(str(v))
            v_item.setFlags(v_item.flags() & ~Qt.ItemIsEditable)
            v_item.setToolTip(str(v))
            tbl.setItem(r, 0, k_item)
            tbl.setItem(r, 1, v_item)
        tbl.setFixedHeight(230)
        return tbl

    def _copy_info(self):
        lines = [f"File: {self.info.get('name')}", f"Path: {self.info.get('path')}",
                 f"Format: {self.info.get('format')} ({self.info.get('family')})",
                 f"Size: {self.info.get('size_str')}", f"Created: {self.info.get('created')}",
                 f"Modified: {self.info.get('modified')}", f"SHA-256: {self.info.get('sha256')}"]
        if self.info.get("media"):
            lines.append("\n[Media & Resolution]")
            for k, v in self.info["media"].items():
                lines.append(f"  {k}: {v}")
        if self.info.get("metadata"):
            lines.append("\n[EXIF & Metadata]")
            for k, v in self.info["metadata"].items():
                lines.append(f"  {k}: {v}")
        text = "\n".join(lines)
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "File information copied to clipboard!")

    def _open_folder(self):
        try:
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{self.file_path}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.file_path.parent)])
            else:
                subprocess.Popen(["xdg-open", str(self.file_path.parent)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder: {e}")
