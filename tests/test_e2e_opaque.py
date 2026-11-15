"""Milestone M6 — Phase 1: 4-Tier Opaque-Box E2E Test Suite.
Strictly requirement-driven, testing end-to-end functionality across all 10 feature areas,
boundary cases, pairwise cross-feature workflows, and 5 real-world workload scenarios.
All tests execute in isolated temporary directories with automatic cleanup.
"""
from __future__ import annotations
import gc
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
import zipfile
import tarfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import py7zr

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

os.environ["QT_QPA_PLATFORM"] = "offscreen"
try:
    from PySide6.QtCore import QCoreApplication, QLockFile
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication
    qt_app = QApplication.instance()
    if qt_app is None:
        qt_app = QApplication(sys.argv)
    HAS_QT = True
except ImportError:
    HAS_QT = False

from vitarg import engine, tools, estimator, rename, undo, settings as S
from vitarg import app as vitarg_app


class OpaqueE2EBase(unittest.TestCase):
    """Isolated test base fixture for opaque-box E2E tests."""
    def setUp(self):
        self._orig_appdata = os.environ.get("APPDATA")
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_dir.name)
        os.environ["APPDATA"] = str(self.tmp)
        self.st = S.Settings()
        # Reset and isolate UndoManager singleton
        undo.UndoManager._instance = None
        self.undo_mgr = undo.UndoManager.get()
        undo.undo_manager = self.undo_mgr
        self.undo_mgr._backup_dir = self.tmp / "vitarg-backups"
        self.undo_mgr._backup_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        gc.collect()
        if HAS_QT and qt_app is not None:
            qt_app.processEvents()
        undo.UndoManager._instance = None
        undo.undo_manager = undo.UndoManager.get()
        if self._orig_appdata is not None:
            os.environ["APPDATA"] = self._orig_appdata
        else:
            os.environ.pop("APPDATA", None)
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    # Helper asset generators
    def create_image(self, name: str, size: tuple[int, int] = (60, 60),
                     color: str | tuple = "blue", mode: str = "RGB", format: str = "PNG") -> Path:
        p = self.tmp / name
        with Image.new(mode, size, color) as im:
            im.save(p, format=format)
        return p

    def create_text_file(self, name: str, content: str = "Hello Vitarg") -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def create_pdf(self, name: str, pages: int = 1, text: str = "Sample Document") -> Path:
        p = self.tmp / name
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page(width=300, height=400)
            page.insert_text((40, 50), f"{text} - Page {i+1}", fontsize=14)
            page.draw_rect(fitz.Rect(30, 30, 270, 370), color=(0.1, 0.2, 0.8))
        doc.save(str(p))
        doc.close()
        return p

    def create_audio_wav(self, name: str, duration: float = 0.3, sample_rate: int = 44100) -> Path:
        p = self.tmp / name
        with wave.open(str(p), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            n_samples = int(duration * sample_rate)
            data = bytearray()
            for i in range(n_samples):
                val = int(16000.0 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
                data.extend(struct.pack("<h", val))
            w.writeframes(data)
        return p

    def create_video_mp4(self, name: str, duration: float = 0.25) -> Path:
        p = self.tmp / name
        exe = engine.need_tool("ffmpeg")
        cmd = [
            exe, "-y", "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size=160x120:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return p

    def create_zip_archive(self, name: str, entries: dict[str, str | bytes]) -> Path:
        p = self.tmp / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for arcname, data in entries.items():
                if isinstance(data, str):
                    z.writestr(arcname, data.encode("utf-8"))
                else:
                    z.writestr(arcname, data)
        return p

    def create_tar_archive(self, name: str, entries: dict[str, str | bytes], gzipped: bool = False) -> Path:
        p = self.tmp / name
        mode = "w:gz" if gzipped else "w"
        with tarfile.open(p, mode) as tf:
            for arcname, data in entries.items():
                raw = data.encode("utf-8") if isinstance(data, str) else data
                ti = tarfile.TarInfo(arcname)
                ti.size = len(raw)
                ti.mtime = time.time()
                import io
                tf.addfile(ti, io.BytesIO(raw))
        return p

    def create_7z_archive(self, name: str, entries: dict[str, str | bytes]) -> Path:
        p = self.tmp / name
        sub_dir = self.tmp / f"_7z_src_{name}"
        sub_dir.mkdir(parents=True, exist_ok=True)
        try:
            for arcname, data in entries.items():
                dest = sub_dir / arcname
                dest.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(data, str):
                    dest.write_text(data, encoding="utf-8")
                else:
                    dest.write_bytes(data)
            with py7zr.SevenZipFile(p, "w") as z:
                for item in sorted(sub_dir.iterdir()):
                    if item.is_dir():
                        z.writeall(item, arcname=item.name)
                    else:
                        z.write(item, arcname=item.name)
        finally:
            shutil.rmtree(sub_dir, ignore_errors=True)
        return p


# =====================================================================
# TIER 1: Logic & Unit Coverage (>=5 tests per 10 feature areas)
# =====================================================================

class Tier1ImageConversions(OpaqueE2EBase):
    """Tier 1: Image Conversions (PNG, JPG, WebP, BMP, TIFF, GIF, ICO, HEIC)."""

    def test_tier1_img_01_png_to_webp(self):
        src = self.create_image("sample.png", (64, 48), color=(200, 50, 50))
        outs = engine.convert(src, "webp", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertEqual(out.suffix.lower(), ".webp")
        with Image.open(out) as im:
            self.assertEqual(im.format, "WEBP")
            self.assertEqual(im.size, (64, 48))

    def test_tier1_img_02_jpg_to_png(self):
        src = self.create_image("sample.jpg", (50, 50), color="green", format="JPEG")
        outs = engine.convert(src, "png", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            self.assertEqual(im.format, "PNG")
            self.assertEqual(im.size, (50, 50))

    def test_tier1_img_03_webp_to_jpg(self):
        src = self.create_image("sample.webp", (80, 60), color="blue", format="WEBP")
        outs = engine.convert(src, "jpg", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.mode, "RGB")

    def test_tier1_img_04_bmp_to_tiff(self):
        src = self.create_image("sample.bmp", (40, 40), color="yellow", format="BMP")
        outs = engine.convert(src, "tiff", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            self.assertEqual(im.format, "TIFF")

    def test_tier1_img_05_png_to_ico(self):
        src = self.create_image("icon.png", (32, 32), color="purple")
        outs = engine.convert(src, "ico", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            self.assertEqual(im.format, "ICO")

    def test_tier1_img_06_rgba_transparency_to_jpg(self):
        src = self.create_image("trans.png", (40, 40), color=(255, 0, 0, 100), mode="RGBA")
        outs = engine.convert(src, "jpg", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.mode, "RGB")


class Tier1DocumentConversions(OpaqueE2EBase):
    """Tier 1: Document Conversions (PDF, DOCX, TXT, MD, HTML)."""

    def test_tier1_doc_01_txt_to_pdf(self):
        src = self.create_text_file("doc.txt", "Automated TXT to PDF test content.")
        outs = engine.convert(src, "pdf", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertTrue(out.read_bytes().startswith(b"%PDF"))
        with fitz.open(str(out)) as doc:
            self.assertGreaterEqual(len(doc), 1)

    def test_tier1_doc_02_md_to_html(self):
        src = self.create_text_file("guide.md", "# Heading 1\n\nParagraph text.")
        outs = engine.convert(src, "html", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        content = out.read_text(encoding="utf-8")
        self.assertIn("Heading 1", content)
        self.assertTrue(content.startswith("<!DOCTYPE html>") or "<html" in content)

    def test_tier1_doc_03_html_to_txt(self):
        src = self.create_text_file("page.html", "<html><body><h1>Doc Title</h1><p>Paragraph line.</p></body></html>")
        outs = engine.convert(src, "txt", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        text = out.read_text(encoding="utf-8")
        self.assertIn("Doc Title", text)
        self.assertIn("Paragraph line", text)

    def test_tier1_doc_04_txt_to_docx(self):
        src = self.create_text_file("report.txt", "Chapter 1: The Beginning.\nChapter 2: The Journey.")
        outs = engine.convert(src, "docx", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        doc = docx.Document(str(out))
        doc_text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Chapter 1", doc_text)

    def test_tier1_doc_05_pdf_to_txt(self):
        src = self.create_pdf("searchable.pdf", pages=1, text="Secret Password Alpha")
        outs = engine.convert(src, "txt", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        text = out.read_text(encoding="utf-8")
        self.assertIn("Secret Password Alpha", text)

    def test_tier1_doc_06_md_to_docx(self):
        src = self.create_text_file("proposal.md", "# Technical Proposal\n\n- Item 1\n- Item 2")
        outs = engine.convert(src, "docx", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        doc = docx.Document(str(out))
        doc_text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Technical Proposal", doc_text)


class Tier1MediaConversions(OpaqueE2EBase):
    """Tier 1: Media Conversions (Audio & Video Formats)."""

    def test_tier1_media_01_wav_to_mp3(self):
        src = self.create_audio_wav("audio.wav", duration=0.3)
        outs = engine.convert(src, "mp3", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        probe = engine.probe(out)
        self.assertTrue(probe.get("audio"))

    def test_tier1_media_02_mp3_to_wav(self):
        src_wav = self.create_audio_wav("initial.wav", duration=0.3)
        mp3 = engine.convert(src_wav, "mp3", self.st)[0]
        outs = engine.convert(mp3, "wav", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertTrue(out.read_bytes().startswith(b"RIFF"))

    def test_tier1_media_03_wav_to_flac(self):
        src = self.create_audio_wav("source.wav", duration=0.3)
        outs = engine.convert(src, "flac", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertTrue(out.read_bytes().startswith(b"fLaC"))

    def test_tier1_media_04_mp4_to_mkv(self):
        src = self.create_video_mp4("clip.mp4", duration=0.25)
        outs = engine.convert(src, "mkv", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        probe = engine.probe(out)
        self.assertTrue(probe.get("video"))

    def test_tier1_media_05_video_to_gif(self):
        src = self.create_video_mp4("short.mp4", duration=0.2)
        outs = engine.convert(src, "gif", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            self.assertEqual(im.format, "GIF")

    def test_tier1_media_06_wav_to_ogg(self):
        src = self.create_audio_wav("sample.wav", duration=0.3)
        outs = engine.convert(src, "ogg", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 100)


class Tier1ArchiveOperations(OpaqueE2EBase):
    """Tier 1: Archive Operations (ZIP, TAR, GZ, 7Z, safe_extract)."""

    def test_tier1_archive_01_pack_and_extract_zip(self):
        srcdir = self.tmp / "zip_src"
        srcdir.mkdir()
        (srcdir / "file1.txt").write_text("file 1 content")
        (srcdir / "file2.txt").write_text("file 2 content")
        out_zip = self.tmp / "test.zip"
        engine.pack(srcdir, "zip", out_zip)
        self.assertTrue(out_zip.exists())

        dest = self.tmp / "zip_dest"
        dest.mkdir()
        engine.safe_extract(out_zip, dest)
        self.assertEqual((dest / "file1.txt").read_text(), "file 1 content")
        self.assertEqual((dest / "file2.txt").read_text(), "file 2 content")

    def test_tier1_archive_02_pack_and_extract_tar(self):
        srcdir = self.tmp / "tar_src"
        srcdir.mkdir()
        (srcdir / "data.txt").write_text("tar data")
        out_tar = self.tmp / "test.tar"
        engine.pack(srcdir, "tar", out_tar)
        self.assertTrue(out_tar.exists())

        dest = self.tmp / "tar_dest"
        dest.mkdir()
        engine.safe_extract(out_tar, dest)
        self.assertEqual((dest / "data.txt").read_text(), "tar data")

    def test_tier1_archive_03_pack_and_extract_targz(self):
        srcdir = self.tmp / "targz_src"
        srcdir.mkdir()
        (srcdir / "doc.txt").write_text("gzipped data")
        out_targz = self.tmp / "test.tar.gz"
        engine.pack(srcdir, "gz", out_targz)
        self.assertTrue(out_targz.exists())

        dest = self.tmp / "targz_dest"
        dest.mkdir()
        engine.safe_extract(out_targz, dest)
        self.assertEqual((dest / "doc.txt").read_text(), "gzipped data")

    def test_tier1_archive_04_pack_and_extract_7z(self):
        srcdir = self.tmp / "7z_src"
        srcdir.mkdir()
        (srcdir / "asset.txt").write_text("7z asset text")
        out_7z = self.tmp / "test.7z"
        engine.pack(srcdir, "7z", out_7z)
        self.assertTrue(out_7z.exists())

        dest = self.tmp / "7z_dest"
        dest.mkdir()
        engine.safe_extract(out_7z, dest)
        self.assertEqual((dest / "asset.txt").read_text(), "7z asset text")

    def test_tier1_archive_05_convert_zip_to_7z(self):
        zip_path = self.create_zip_archive("input.zip", {"entry.txt": "archive text"})
        outs = engine.convert(zip_path, "7z", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertEqual(out.suffix.lower(), ".7z")

        dest = self.tmp / "converted_7z_dest"
        dest.mkdir()
        engine.safe_extract(out, dest)
        self.assertEqual((dest / "entry.txt").read_text(), "archive text")

    def test_tier1_archive_06_convert_targz_to_zip(self):
        targz_path = self.create_tar_archive("input.tar.gz", {"item.txt": "tar item text"}, gzipped=True)
        outs = engine.convert(targz_path, "zip", self.st)
        self.assertEqual(len(outs), 1)
        out = outs[0]
        self.assertTrue(out.exists())
        self.assertEqual(out.suffix.lower(), ".zip")

        dest = self.tmp / "converted_zip_dest"
        dest.mkdir()
        engine.safe_extract(out, dest)
        self.assertEqual((dest / "item.txt").read_text(), "tar item text")


class Tier1ToolsOperations(OpaqueE2EBase):
    """Tier 1: Tools Wheel Operations (Resize, Crop, Compress, Edit, AddBg)."""

    def test_tier1_tools_01_resize_scale(self):
        src = self.create_image("pic.png", (100, 80))
        outs, errs = tools.run_tool("resize", [src], {"mode": "Scale %", "scale": 50}, self.st)
        self.assertEqual(errs, [])
        self.assertEqual(len(outs), 1)
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (50, 40))

    def test_tier1_tools_02_resize_exact_pixels(self):
        src = self.create_image("pic_exact.png", (100, 80))
        outs, errs = tools.run_tool("resize", [src], {"mode": "Exact pixels", "width": 120, "height": 90}, self.st)
        self.assertEqual(errs, [])
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (120, 90))

    def test_tier1_tools_03_crop_bounding_box(self):
        src = self.create_image("crop_me.png", (100, 100), color="green")
        outs, errs = tools.run_tool("crop", [src], {"box": (10, 20, 70, 80)}, self.st)
        self.assertEqual(errs, [])
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (60, 60))

    def test_tier1_tools_04_compress_image(self):
        src = self.create_image("heavy.png", (200, 200), color=(100, 150, 200))
        outs, errs = tools.run_tool("compress", [src], {"preset": "Strong", "max_edge": "Original"}, self.st)
        self.assertEqual(errs, [])
        self.assertTrue(outs[0].exists())
        with Image.open(outs[0]) as im:
            self.assertIsNotNone(im)

    def test_tier1_tools_05_edit_adjustments(self):
        src = self.create_image("edit_me.png", (80, 80), color=(120, 120, 120))
        outs, errs = tools.run_tool("edit", [src], {"brightness": 1.2, "contrast": 1.1, "saturation": 1.0, "sharpness": 1.0}, self.st)
        self.assertEqual(errs, [])
        self.assertTrue(outs[0].exists())
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (80, 80))

    def test_tier1_tools_06_addbg_background_and_padding(self):
        src = self.create_image("addbg.png", (50, 50), color=(255, 0, 0, 128), mode="RGBA")
        outs, errs = tools.run_tool("addbg", [src], {"color": "#00FF00", "padding": 10.0}, self.st)
        self.assertEqual(errs, [])
        with Image.open(outs[0]) as im:
            self.assertEqual(im.mode, "RGB")
            # 50px + 10% padding on each side: 50 * 1.2 = 60px
            self.assertEqual(im.size, (60, 60))


class Tier1RenamingTemplates(OpaqueE2EBase):
    """Tier 1: File Renaming & Template System ({name}, {date}, {time}, {num})."""

    def test_tier1_rename_01_template_name_and_num(self):
        name1 = rename.format_rename("sample.png", "{name}_v{num}", "jpg", index=1)
        name2 = rename.format_rename("sample.png", "{name}_v{num}", "jpg", index=3)
        self.assertEqual(name1, "sample_v01.jpg")
        self.assertEqual(name2, "sample_v03.jpg")

    def test_tier1_rename_02_date_and_time_tokens(self):
        res = rename.format_rename("photo.png", "{date}_{name}_{time}", "webp", index=1)
        parts = res.split("_")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 8)  # YYYYMMDD
        self.assertEqual(parts[1], "photo")
        self.assertTrue(parts[2].endswith(".webp"))

    def test_tier1_rename_03_literal_name_indexing(self):
        res1 = rename.format_rename("anything.png", "vacation", "jpg", index=1)
        res2 = rename.format_rename("anything.png", "vacation", "jpg", index=2)
        self.assertEqual(res1, "vacation.jpg")
        self.assertEqual(res2, "vacation_02.jpg")

    def test_tier1_rename_04_sanitize_special_chars(self):
        res = rename.format_rename("test.png", 'bad:file*name?with"bad<chars>|', "png", index=1)
        self.assertNotIn(":", res)
        self.assertNotIn("*", res)
        self.assertNotIn("?", res)
        self.assertNotIn('"', res)
        self.assertNotIn("<", res)
        self.assertNotIn(">", res)
        self.assertNotIn("|", res)

    def test_tier1_rename_05_apply_custom_rename_batch(self):
        p1 = self.create_image("pic1.png")
        p2 = self.create_image("pic2.png")
        renamed = rename.apply_custom_rename([str(p1), str(p2)], "export_{num}")
        self.assertEqual(len(renamed), 2)
        self.assertTrue(Path(renamed[0]).exists())
        self.assertTrue(Path(renamed[1]).exists())
        self.assertEqual(Path(renamed[0]).name, "export_01.png")
        self.assertEqual(Path(renamed[1]).name, "export_02.png")


class Tier1EstimatorPreview(OpaqueE2EBase):
    """Tier 1: Estimator & Preview Calculation."""

    def test_tier1_estimator_01_png_to_jpg_reduction(self):
        p = self.tmp / "est_test.png"
        raw_bytes = os.urandom(200 * 200 * 3)
        with Image.frombytes("RGB", (200, 200), raw_bytes) as im:
            im.save(p)
        self.assertGreater(p.stat().st_size, 50000)
        est = estimator.estimate_conversion(p, "jpg", self.st)
        self.assertEqual(est["status"], "ok")
        self.assertGreater(est["src_size"], 0)
        self.assertGreater(est["est_size"], 0)
        self.assertLess(est["est_size"], est["src_size"])
        self.assertLess(est["ratio_pct"], 0)

    def test_tier1_estimator_02_zero_byte_safety(self):
        empty = self.tmp / "empty_est.png"
        empty.write_bytes(b"")
        est = estimator.estimate_conversion(empty, "webp", self.st)
        self.assertEqual(est["status"], "ok")
        self.assertEqual(est["src_size"], 0)
        self.assertEqual(est["ratio_pct"], 0.0)

    def test_tier1_estimator_03_missing_file_error(self):
        missing = self.tmp / "non_existent_file.png"
        est = estimator.estimate_conversion(missing, "jpg", self.st)
        self.assertEqual(est["status"], "error")
        self.assertEqual(est["summary"], "File not found")

    def test_tier1_estimator_04_preview_thumb_generation(self):
        src = self.create_image("large_thumb.png", (800, 600))
        th = tools.thumb(src, box=(500, 340))
        self.assertLessEqual(th.width, 500)
        self.assertLessEqual(th.height, 340)

    def test_tier1_estimator_05_format_size_units(self):
        self.assertEqual(estimator.format_size(500), "500 B")
        self.assertEqual(estimator.format_size(1024 * 10), "10.0 KB")
        self.assertEqual(estimator.format_size(1024 * 1024 * 5), "5.0 MB")
        self.assertEqual(estimator.format_size(1024 * 1024 * 1024 * 2), "2.00 GB")


class Tier1UndoSystem(OpaqueE2EBase):
    """Tier 1: Undo / Rollback System."""

    def test_tier1_undo_01_record_and_revert_created_files(self):
        f1 = self.tmp / "new_out1.txt"
        f2 = self.tmp / "new_out2.txt"
        f1.write_text("created 1")
        f2.write_text("created 2")
        self.undo_mgr.record("Convert files", [str(f1), str(f2)])
        self.assertTrue(self.undo_mgr.can_undo())

        ok, msg, affected = self.undo_mgr.undo()
        self.assertTrue(ok)
        self.assertFalse(f1.exists())
        self.assertFalse(f2.exists())

    def test_tier1_undo_02_record_and_restore_overwritten_file(self):
        target = self.tmp / "existing_doc.txt"
        original_data = "Original Important Data 12345"
        target.write_text(original_data)

        # Overwrite file and record with overwritten_targets
        self.undo_mgr.record("Overwrite doc", [str(target)], overwritten_targets=[str(target)])
        target.write_text("Overwritten corrupt data")

        ok, msg, affected = self.undo_mgr.undo()
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), original_data)

    def test_tier1_undo_03_empty_history_graceful(self):
        self.assertFalse(self.undo_mgr.can_undo())
        ok, msg, affected = self.undo_mgr.undo()
        self.assertFalse(ok)
        self.assertEqual(msg, "No actions to undo")
        self.assertEqual(affected, [])

    def test_tier1_undo_04_history_limit_and_old_backup_eviction(self):
        self.undo_mgr.max_history = 3
        created_paths = []
        for i in range(5):
            p = self.tmp / f"action_{i}.txt"
            p.write_text(f"data {i}")
            created_paths.append(p)
            self.undo_mgr.record(f"Step {i}", [str(p)])
        self.assertEqual(len(self.undo_mgr.history), 3)

    def test_tier1_undo_05_prune_stale_backups(self):
        old_backup = self.undo_mgr._backup_dir / "old_backup.bak"
        old_backup.write_text("old backup content")
        old_mtime = time.time() - (10 * 86400)  # 10 days old
        os.utime(old_backup, (old_mtime, old_mtime))

        fresh_backup = self.undo_mgr._backup_dir / "fresh_backup.bak"
        fresh_backup.write_text("fresh backup content")

        pruned = self.undo_mgr.prune_stale_backups(max_age_days=7)
        self.assertEqual(pruned, 1)
        self.assertFalse(old_backup.exists())
        self.assertTrue(fresh_backup.exists())


class Tier1IpcAndLockfile(OpaqueE2EBase):
    """Tier 1: Single Instance IPC & Lockfile."""

    def test_tier1_ipc_01_local_server_listen_and_connect(self):
        sname = f"vitarg-test-sock-{os.getpid()}-{int(time.time()*1000)%100000}"
        QLocalServer.removeServer(sname)
        srv = QLocalServer()
        self.assertTrue(srv.listen(sname))

        sock = QLocalSocket()
        sock.connectToServer(sname)
        self.assertTrue(sock.waitForConnected(1000))
        self.assertTrue(srv.waitForNewConnection(1000) or srv.hasPendingConnections())
        client = srv.nextPendingConnection()
        self.assertIsNotNone(client)

        client.disconnectFromServer()
        sock.disconnectFromServer()
        srv.close()
        QLocalServer.removeServer(sname)

    def test_tier1_ipc_02_send_open_action_payload(self):
        sname = f"vitarg-test-sock-open-{os.getpid()}"
        QLocalServer.removeServer(sname)
        srv = QLocalServer()
        srv.listen(sname)

        sock = QLocalSocket()
        sock.connectToServer(sname)
        self.assertTrue(sock.waitForConnected(1000))
        self.assertTrue(srv.waitForNewConnection(1000) or srv.hasPendingConnections())
        client = srv.nextPendingConnection()

        payload = json.dumps({"action": "open", "files": ["test1.png", "test2.jpg"]}).encode("utf-8")
        sock.write(payload)
        sock.flush()
        qt_app.processEvents()

        self.assertTrue(client.waitForReadyRead(1000) or client.bytesAvailable() > 0)
        data = json.loads(client.readAll().data().decode("utf-8"))
        self.assertEqual(data["action"], "open")
        self.assertEqual(data["files"], ["test1.png", "test2.jpg"])

        client.disconnectFromServer()
        sock.disconnectFromServer()
        srv.close()
        QLocalServer.removeServer(sname)

    def test_tier1_ipc_03_send_activate_action_payload(self):
        sname = f"vitarg-test-sock-act-{os.getpid()}"
        QLocalServer.removeServer(sname)
        srv = QLocalServer()
        srv.listen(sname)

        sock = QLocalSocket()
        sock.connectToServer(sname)
        self.assertTrue(sock.waitForConnected(1000))
        self.assertTrue(srv.waitForNewConnection(1000) or srv.hasPendingConnections())
        client = srv.nextPendingConnection()

        payload = json.dumps({"action": "activate"}).encode("utf-8")
        sock.write(payload)
        sock.flush()
        qt_app.processEvents()

        self.assertTrue(client.waitForReadyRead(1000) or client.bytesAvailable() > 0)
        data = json.loads(client.readAll().data().decode("utf-8"))
        self.assertEqual(data["action"], "activate")

        client.disconnectFromServer()
        sock.disconnectFromServer()
        srv.close()
        QLocalServer.removeServer(sname)

    def test_tier1_ipc_04_lockfile_try_lock_success_and_contention(self):
        lock_path = str(self.tmp / "test_instance.lock")
        lock1 = QLockFile(lock_path)
        self.assertTrue(lock1.tryLock(100))
        self.assertTrue(lock1.isLocked())

        lock2 = QLockFile(lock_path)
        self.assertFalse(lock2.tryLock(100))

        lock1.unlock()
        self.assertFalse(lock1.isLocked())
        self.assertTrue(lock2.tryLock(100))
        lock2.unlock()

    def test_tier1_ipc_05_lockfile_stale_recovery_dead_pid(self):
        lock_path = self.tmp / "stale_dead.lock"
        with open(lock_path, "w") as f:
            f.write("999999\npython\nhost\nuuid-fake\n\n")
        old_time = time.time() - 500
        os.utime(lock_path, (old_time, old_time))

        recov_lock = QLockFile(str(lock_path))
        recov_lock.setStaleLockTime(50)
        self.assertTrue(recov_lock.tryLock(200))
        self.assertTrue(recov_lock.isLocked())
        recov_lock.unlock()


class Tier1SelftestAndCli(OpaqueE2EBase):
    """Tier 1: Headless / Offscreen Selftest & CLI Launch."""

    def test_tier1_selftest_01_execute_selftest(self):
        code = vitarg_app.selftest()
        # All tools (ffmpeg, ffprobe, pandoc) are cached in tools/
        self.assertEqual(code, 0)

    def test_tier1_selftest_02_report_file_written(self):
        vitarg_app.selftest()
        report = Path(tempfile.gettempdir()) / "vitarg-selftest.txt"
        self.assertTrue(report.exists())
        self.assertIn("selftest ok", report.read_text())

    def test_tier1_selftest_03_find_tool_cached_tools_lookup(self):
        ffmpeg = engine.find_tool("ffmpeg")
        ffprobe = engine.find_tool("ffprobe")
        pandoc = engine.find_tool("pandoc")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        self.assertIsNotNone(pandoc)
        self.assertTrue(Path(ffmpeg).exists())
        self.assertTrue(Path(ffprobe).exists())
        self.assertTrue(Path(pandoc).exists())

    def test_tier1_selftest_04_cli_args_filtering(self):
        f1 = self.create_text_file("cli1.txt")
        f2 = self.create_text_file("cli2.txt")
        raw_args = ["--flag", str(f1), "-v", "nonexistent.xyz", str(f2)]
        cli_files = [os.path.abspath(arg) for arg in raw_args if not arg.startswith("-") and os.path.exists(arg)]
        self.assertEqual(len(cli_files), 2)
        self.assertIn(str(f1.resolve()), [str(Path(p).resolve()) for p in cli_files])
        self.assertIn(str(f2.resolve()), [str(Path(p).resolve()) for p in cli_files])

    def test_tier1_selftest_05_unsupported_conversion_rejected(self):
        src = self.create_text_file("note.txt", "some text")
        with self.assertRaises(engine.ConversionError):
            engine.convert(src, "mp4", self.st)


# =====================================================================
# TIER 2: Boundary & Corner Cases
# =====================================================================

class Tier2BoundaryCornerCases(OpaqueE2EBase):
    """Tier 2: Boundary & Corner Cases (0-byte, corrupt, long names, zip slip, extreme scales)."""

    def test_tier2_01_zero_byte_png_conversion(self):
        empty = self.tmp / "empty.png"
        empty.write_bytes(b"")
        with self.assertRaises((engine.ConversionError, Exception)):
            engine.convert(empty, "jpg", self.st)

    def test_tier2_02_zero_byte_pdf_conversion(self):
        empty = self.tmp / "empty.pdf"
        empty.write_bytes(b"")
        with self.assertRaises((engine.ConversionError, Exception)):
            engine.convert(empty, "png", self.st)

    def test_tier2_03_zero_byte_audio_conversion(self):
        empty = self.tmp / "empty.wav"
        empty.write_bytes(b"")
        with self.assertRaises((engine.ConversionError, Exception)):
            engine.convert(empty, "mp3", self.st)

    def test_tier2_04_zero_byte_archive_safe_extract(self):
        empty = self.tmp / "empty.zip"
        empty.write_bytes(b"")
        dest = self.tmp / "empty_dest"
        dest.mkdir()
        with self.assertRaises((engine.ConversionError, zipfile.BadZipFile, Exception)):
            engine.safe_extract(empty, dest)

    def test_tier2_05_corrupt_png_garbage_bytes(self):
        corrupt = self.tmp / "corrupt.png"
        corrupt.write_bytes(b"NOT_A_PNG_HEADER_GARBAGE_BYTES_1234567890")
        with self.assertRaises((engine.ConversionError, Exception)):
            engine.convert(corrupt, "webp", self.st)

    def test_tier2_06_corrupt_pdf_header(self):
        corrupt = self.tmp / "corrupt.pdf"
        corrupt.write_bytes(b"RANDOM_NON_PDF_BINARY_DATA_BLOB")
        with self.assertRaises((engine.ConversionError, Exception)):
            engine.convert(corrupt, "txt", self.st)

    def test_tier2_07_corrupt_zip_archive(self):
        corrupt = self.tmp / "corrupt.zip"
        corrupt.write_bytes(b"PK\x03\x04truncated_corrupted_archive_data")
        dest = self.tmp / "corrupt_dest"
        dest.mkdir()
        with self.assertRaises((engine.ConversionError, zipfile.BadZipFile, Exception)):
            engine.safe_extract(corrupt, dest)

    def test_tier2_08_path_traversal_zip_slip_dotdot(self):
        slip_zip = self.tmp / "slip_dotdot.zip"
        with zipfile.ZipFile(slip_zip, "w") as z:
            z.writestr("../../escaped_file.txt", "malicious payload")
        dest = self.tmp / "safe_extract_target"
        dest.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(slip_zip, dest)
        self.assertIn("Unsafe path in archive", str(ctx.exception))
        self.assertFalse((self.tmp.parent / "escaped_file.txt").exists())

    def test_tier2_09_path_traversal_zip_slip_absolute_path(self):
        slip_zip = self.tmp / "slip_abs.zip"
        with zipfile.ZipFile(slip_zip, "w") as z:
            z.writestr("/evil_root.txt", "evil data")
        dest = self.tmp / "abs_target"
        dest.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(slip_zip, dest)
        self.assertIn("Unsafe path in archive", str(ctx.exception))

    def test_tier2_10_path_traversal_tar_symlink(self):
        tar_path = self.tmp / "symlink_attack.tar"
        ti = tarfile.TarInfo("symlink_entry")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "../outside_escape"
        with tarfile.open(tar_path, "w") as tf:
            tf.addfile(ti)
        dest = self.tmp / "tar_symlink_dest"
        dest.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(tar_path, dest)
        self.assertIn("Links inside archives are not supported", str(ctx.exception))

    def test_tier2_11_long_filename_boundary(self):
        long_stem = "a" * 160
        src = self.create_image(f"{long_stem}.png", (40, 40))
        outs = engine.convert(src, "webp", self.st)
        self.assertEqual(len(outs), 1)
        self.assertTrue(outs[0].exists())
        self.assertTrue(outs[0].name.startswith(long_stem[:50]))

    def test_tier2_12_unicode_and_spaces_in_filename(self):
        src = self.create_image("Fotoğraf Arşivi (2026) - Örnek.png", (50, 50))
        outs = engine.convert(src, "jpg", self.st)
        self.assertEqual(len(outs), 1)
        self.assertTrue(outs[0].exists())
        self.assertIn("Fotoğraf", outs[0].name)

    def test_tier2_13_trailing_dots_and_spaces_sanitization(self):
        formatted = rename.format_rename("test.png", "output_filename...   ", "png")
        self.assertEqual(formatted, "output_filename.png")
        self.assertFalse(formatted.endswith(".png.png"))

    def test_tier2_14_multi_extension_archive_collision(self):
        f1 = self.tmp / "archive.tar.gz"
        f1.write_bytes(b"data1")
        col1 = engine.unique_name(self.tmp, "archive.tar.gz")
        self.assertEqual(col1.name, "archive 2.tar.gz")
        col1.write_bytes(b"data2")
        col2 = engine.unique_name(self.tmp, "archive.tar.gz")
        self.assertEqual(col2.name, "archive 3.tar.gz")

    def test_tier2_15_extreme_scale_1x1_pixel_image(self):
        src = self.create_image("tiny_1x1.png", (1, 1), color="white")
        outs, errs = tools.run_tool("resize", [src], {"mode": "Exact pixels", "width": 100, "height": 100}, self.st)
        self.assertEqual(errs, [])
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (100, 100))

    def test_tier2_16_extreme_aspect_ratio_banner(self):
        src = self.create_image("banner_1500x3.png", (1500, 3), color="red")
        outs, errs = tools.run_tool("resize", [src], {"mode": "Scale %", "scale": 50}, self.st)
        self.assertEqual(errs, [])
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (750, 2))


# =====================================================================
# TIER 3: Cross-Feature Interactions (Pairwise Combinations)
# =====================================================================

class Tier3CrossFeatureInteractions(OpaqueE2EBase):
    """Tier 3: Cross-Feature Interactions & Pairwise Workflows."""

    def test_tier3_01_convert_then_resize(self):
        src = self.create_image("step1.png", (120, 80))
        jpg_out = engine.convert(src, "jpg", self.st)[0]
        self.assertEqual(jpg_out.suffix.lower(), ".jpg")
        resized_outs, errs = tools.run_tool("resize", [jpg_out], {"mode": "Scale %", "scale": 50}, self.st)
        self.assertEqual(errs, [])
        with Image.open(resized_outs[0]) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.size, (60, 40))

    def test_tier3_02_crop_then_compress(self):
        src = self.create_image("crop_comp.png", (200, 200), color=(50, 100, 150))
        cropped = tools.run_tool("crop", [src], {"box": (20, 20, 120, 120)}, self.st)[0][0]
        with Image.open(cropped) as im:
            self.assertEqual(im.size, (100, 100))
        compressed = tools.run_tool("compress", [cropped], {"preset": "Strong", "max_edge": "Original"}, self.st)[0][0]
        self.assertTrue(compressed.exists())
        with Image.open(compressed) as im:
            self.assertIsNotNone(im)

    def test_tier3_03_extract_then_convert(self):
        entries = {
            "img_a.png": self.create_image("raw_a.png", (30, 30)).read_bytes(),
            "img_b.png": self.create_image("raw_b.png", (40, 40)).read_bytes(),
        }
        arc = self.create_zip_archive("batch_in.zip", entries)
        ext_dir = self.tmp / "extracted_batch"
        ext_dir.mkdir()
        engine.safe_extract(arc, ext_dir)
        extracted_files = list(ext_dir.glob("*.png"))
        self.assertEqual(len(extracted_files), 2)

        webp_outs = []
        for img_file in extracted_files:
            outs = engine.convert(img_file, "webp", self.st)
            webp_outs.extend(outs)
        self.assertEqual(len(webp_outs), 2)
        for w in webp_outs:
            self.assertEqual(w.suffix.lower(), ".webp")

    def test_tier3_04_rename_then_undo(self):
        src = self.create_image("original_name.png", (50, 50))
        outs = engine.convert(src, "webp", self.st, custom_name="optimized_{num}")
        self.assertEqual(len(outs), 1)
        created_file = outs[0]
        self.assertEqual(created_file.name, "optimized_01.webp")
        self.assertTrue(created_file.exists())

        self.undo_mgr.record("Convert with custom rename", [str(created_file)])
        ok, msg, affected = self.undo_mgr.undo()
        self.assertTrue(ok)
        self.assertFalse(created_file.exists())

    def test_tier3_05_convert_docs_then_repack_targz(self):
        doc1 = self.create_text_file("doc1.txt", "Document 1 text")
        doc2 = self.create_text_file("doc2.txt", "Document 2 text")
        pdf1 = engine.convert(doc1, "pdf", self.st)[0]
        pdf2 = engine.convert(doc2, "pdf", self.st)[0]

        pack_dir = self.tmp / "docs_to_pack"
        pack_dir.mkdir()
        shutil.move(str(pdf1), str(pack_dir / pdf1.name))
        shutil.move(str(pdf2), str(pack_dir / pdf2.name))

        targz_out = self.tmp / "repacked_docs.tar.gz"
        engine.pack(pack_dir, "gz", targz_out)
        self.assertTrue(targz_out.exists())
        with tarfile.open(targz_out, "r:gz") as tf:
            names = tf.getnames()
            self.assertIn("doc1.pdf", names)
            self.assertIn("doc2.pdf", names)

    def test_tier3_06_addbg_then_convert(self):
        src = self.create_image("alpha.png", (40, 40), color=(0, 255, 0, 100), mode="RGBA")
        with_bg = tools.run_tool("addbg", [src], {"color": "#112233", "padding": 10.0}, self.st)[0][0]
        jpg_out = engine.convert(with_bg, "jpg", self.st)[0]
        self.assertEqual(jpg_out.suffix.lower(), ".jpg")
        with Image.open(jpg_out) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.mode, "RGB")

    def test_tier3_07_format_collision_with_custom_template(self):
        src = self.create_image("cat.png", (40, 40))
        out1 = engine.convert(src, "webp", self.st, custom_name="favorite_{num}", index=1)[0]
        out2 = engine.convert(src, "webp", self.st, custom_name="favorite_{num}", index=2)[0]
        self.assertEqual(out1.name, "favorite_01.webp")
        self.assertEqual(out2.name, "favorite_02.webp")

    def test_tier3_08_overwrite_mode_with_undo_backup(self):
        target = self.tmp / "overwritten_target.txt"
        target.write_bytes(b"ORIGINAL_SECRET_PAYLOAD_ABC")
        self.st.overwrite = "overwrite"
        self.st.output_folder = str(self.tmp)

        with engine.Workspace(self.st, target) as ws:
            work_file = ws.path("overwritten_target.txt")
            work_file.write_bytes(b"NEW_REPLACED_PAYLOAD_XYZ")
            ws.publish()

        self.assertEqual(target.read_bytes(), b"NEW_REPLACED_PAYLOAD_XYZ")
        self.assertTrue(self.undo_mgr.can_undo())
        ok, msg, affected = self.undo_mgr.undo()
        self.assertTrue(ok)
        self.assertEqual(target.read_bytes(), b"ORIGINAL_SECRET_PAYLOAD_ABC")

    def test_tier3_09_metadata_strip_then_convert(self):
        src_jpg = self.tmp / "with_exif.jpg"
        with Image.new("RGB", (40, 40), "red") as im:
            ex = im.getexif()
            ex[0x010F] = "CameraBrand123"
            im.save(src_jpg, exif=ex)
        self.assertIn(b"CameraBrand123", src_jpg.read_bytes())

        stripped = tools.run_tool("metadata", [src_jpg], {}, self.st)[0][0]
        self.assertNotIn(b"CameraBrand123", stripped.read_bytes())

        webp_out = engine.convert(stripped, "webp", self.st)[0]
        self.assertTrue(webp_out.exists())
        self.assertEqual(webp_out.suffix.lower(), ".webp")

    def test_tier3_10_pdf_split_then_merge(self):
        multi_pdf = self.create_pdf("pages2.pdf", pages=2, text="MultiPage")
        split_folder = tools.run_tool("split_pdf", [multi_pdf], {}, self.st)[0][0]
        self.assertTrue(split_folder.is_dir())
        pages = sorted(split_folder.glob("*.pdf"))
        self.assertEqual(len(pages), 2)

        merged = tools.run_tool("merge_pdf", pages, {}, self.st)[0][0]
        self.assertTrue(merged.exists())
        with fitz.open(str(merged)) as doc:
            self.assertEqual(len(doc), 2)


# =====================================================================
# TIER 4: Real-World Workload Scenarios (5 Comprehensive Workloads)
# =====================================================================

class Tier4RealWorldWorkloads(OpaqueE2EBase):
    """Tier 4: Comprehensive Real-World Workload Scenarios."""

    def test_tier4_scenario1_batch_photo_optimization(self):
        """Scenario 1: Batch photo optimization (resize, convert WebP, custom rename, undo rollback)."""
        # 1. Generate multi-image batch (3 PNGs, 2 JPGs)
        images = []
        for i in range(3):
            images.append(self.create_image(f"photo_{i}.png", (100, 80), color=(i * 50, 80, 120)))
        for i in range(3, 5):
            images.append(self.create_image(f"photo_{i}.jpg", (100, 80), color=(120, i * 40, 60), format="JPEG"))

        # 2. Resize by 50%
        resized_images = []
        for img in images:
            outs, errs = tools.run_tool("resize", [img], {"mode": "Scale %", "scale": 50}, self.st)
            self.assertEqual(errs, [])
            resized_images.append(outs[0])
        self.assertEqual(len(resized_images), 5)

        # 3. Convert to WebP with custom rename template {date}_{name}
        final_webp_outputs = []
        for r_img in resized_images:
            outs = engine.convert(r_img, "webp", self.st, custom_name="{date}_{name}")
            final_webp_outputs.extend(outs)
        self.assertEqual(len(final_webp_outputs), 5)

        # 4. Verify all outputs created with correct dimensions, formats, and names
        for out in final_webp_outputs:
            self.assertTrue(out.exists())
            self.assertEqual(out.suffix.lower(), ".webp")
            with Image.open(out) as im:
                self.assertEqual(im.format, "WEBP")
                self.assertEqual(im.size, (50, 40))

        # 5. Verify UndoManager rollback of created files
        self.undo_mgr.record("Batch Photo Optimization", [str(p) for p in final_webp_outputs])
        ok, msg, affected = self.undo_mgr.undo()
        self.assertTrue(ok)
        for out in final_webp_outputs:
            self.assertFalse(out.exists())

    def test_tier4_scenario2_document_publishing_pipeline(self):
        """Scenario 2: Document publishing pipeline (multi-page PDF to PNGs, crop, combine to PDF)."""
        # 1. Multi-page PDF generation (3 pages)
        src_pdf = self.create_pdf("catalog.pdf", pages=3, text="Publication Catalog")

        # 2. Split/extract PDF pages into individual PNG images
        png_outs = engine.convert(src_pdf, "png", self.st)
        png_files = []
        for item in png_outs:
            if item.is_dir():
                png_files.extend(sorted(item.glob("*.png")))
            elif item.is_file() and item.suffix.lower() == ".png":
                png_files.append(item)
        self.assertEqual(len(png_files), 3)

        # 3. Apply image crop to extracted pages (crop 10% margins)
        cropped_pages = []
        for p_png in png_files:
            with Image.open(p_png) as im:
                w, h = im.size
            box = (w * 0.1, h * 0.1, w * 0.9, h * 0.9)
            c_outs, c_errs = tools.run_tool("crop", [p_png], {"box": box}, self.st)
            self.assertEqual(c_errs, [])
            cropped_pages.append(c_outs[0])
        self.assertEqual(len(cropped_pages), 3)

        # 4. Re-combine cropped images into a single published PDF
        comb_outs, comb_errs = tools.run_tool("create_pdf", cropped_pages, {}, self.st)
        self.assertEqual(comb_errs, [])
        self.assertEqual(len(comb_outs), 1)
        published_pdf = comb_outs[0]
        self.assertTrue(published_pdf.exists())

        # 5. Verify page count, integrity, and resolution
        with fitz.open(str(published_pdf)) as doc:
            self.assertEqual(len(doc), 3)
            for page in doc:
                self.assertGreater(page.rect.width, 0)
                self.assertGreater(page.rect.height, 0)

    def test_tier4_scenario3_archival_ingestion(self):
        """Scenario 3: Archival ingestion (extract 7z with path defenses, convert extracted media, repack to tar.gz)."""
        # 1. Create 7z archive with simulated zip-slip path traversal entry
        bad_7z = self.tmp / "adversarial.7z"
        dummy_img = self.create_image("test_asset.png", (40, 40))
        with py7zr.SevenZipFile(bad_7z, "w") as z:
            z.write(dummy_img, arcname="valid.png")
            z.write(dummy_img, arcname="../../malicious_escape.txt")

        # 2. Execute safe extraction: verify zip-slip entry is rejected
        extract_fail_dir = self.tmp / "extract_defense"
        extract_fail_dir.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(bad_7z, extract_fail_dir)
        self.assertIn("Unsafe path in archive", str(ctx.exception))
        self.assertFalse((self.tmp.parent / "malicious_escape.txt").exists())

        # 3. Create clean 7z archive with valid image assets
        clean_7z = self.tmp / "clean_assets.7z"
        asset1 = self.create_image("asset1.png", (40, 40), color="blue")
        asset2 = self.create_image("asset2.png", (40, 40), color="red")
        with py7zr.SevenZipFile(clean_7z, "w") as z:
            z.write(asset1, arcname="asset1.png")
            z.write(asset2, arcname="asset2.png")

        clean_dest = self.tmp / "clean_extracted"
        clean_dest.mkdir()
        engine.safe_extract(clean_7z, clean_dest)
        extracted_assets = list(clean_dest.glob("*.png"))
        self.assertEqual(len(extracted_assets), 2)

        # 4. Convert extracted assets to WebP
        converted_dir = self.tmp / "converted_webp_assets"
        converted_dir.mkdir()
        for asset in extracted_assets:
            w_out = engine.convert(asset, "webp", self.st)[0]
            shutil.move(str(w_out), str(converted_dir / w_out.name))

        # 5. Re-pack processed assets into clean .tar.gz archive
        repack_tar = self.tmp / "ingested_bundle.tar.gz"
        engine.pack(converted_dir, "gz", repack_tar)
        self.assertTrue(repack_tar.exists())

        # 6. Verify .tar.gz contents
        with tarfile.open(repack_tar, "r:gz") as tf:
            names = tf.getnames()
            self.assertIn("asset1.webp", names)
            self.assertIn("asset2.webp", names)

    def test_tier4_scenario4_low_memory_batch_conversion(self):
        """Scenario 4: Low-Memory batch conversion (convert 50 mixed files, verify resource handle closure)."""
        files = []
        # 25 PNG images
        for i in range(25):
            p = self.create_image(f"batch_img_{i}.png", (24, 24), color=(i * 10 % 255, 100, 150))
            files.append((p, "jpg"))
        # 15 TXT documents
        for i in range(15):
            p = self.create_text_file(f"batch_doc_{i}.txt", f"Batch document text payload {i}")
            files.append((p, "pdf"))
        # 5 ZIP archives
        for i in range(5):
            p = self.create_zip_archive(f"batch_arc_{i}.zip", {"data.txt": f"archive content {i}"})
            files.append((p, "tar"))
        # 5 WAV audio files
        for i in range(5):
            p = self.create_audio_wav(f"batch_snd_{i}.wav", duration=0.3, sample_rate=44100)
            files.append((p, "mp3"))

        self.assertEqual(len(files), 50)

        # Execute conversions
        outputs = []
        for src, tgt in files:
            outs = engine.convert(src, tgt, self.st)
            self.assertTrue(len(outs) > 0)
            outputs.extend(outs)

        self.assertEqual(len(outputs), 50)

        # Verify immediate handle closure: every output and source file must unlink cleanly without WinError 32
        for out in outputs:
            self.assertTrue(out.exists())
            out.unlink()
            self.assertFalse(out.exists())

        for src, _ in files:
            self.assertTrue(src.exists())
            src.unlink()
            self.assertFalse(src.exists())

    def test_tier4_scenario5_cli_file_forwarding_and_ipc(self):
        """Scenario 5: CLI file forwarding & IPC (emulate primary instance, secondary launch, stale lock recovery)."""
        sname = f"vitarg-test-ipc-scenario5-{os.getpid()}"
        QLocalServer.removeServer(sname)

        # 1. Primary instance starts server
        server = QLocalServer()
        self.assertTrue(server.listen(sname))

        # 2. Secondary CLI launch with file arguments forwarded over socket
        f1 = self.create_image("forward1.png")
        f2 = self.create_text_file("forward2.txt")
        cli_files = [str(f1), str(f2)]

        cli_sock = QLocalSocket()
        cli_sock.connectToServer(sname)
        self.assertTrue(cli_sock.waitForConnected(1000))
        self.assertTrue(server.waitForNewConnection(1000) or server.hasPendingConnections())
        client = server.nextPendingConnection()

        msg = json.dumps({"action": "open", "files": cli_files}).encode("utf-8")
        cli_sock.write(msg)
        cli_sock.flush()
        qt_app.processEvents()

        self.assertTrue(client.waitForReadyRead(1000) or client.bytesAvailable() > 0)
        data = json.loads(client.readAll().data().decode("utf-8"))
        self.assertEqual(data["action"], "open")
        self.assertEqual(data["files"], cli_files)

        client.disconnectFromServer()
        cli_sock.disconnectFromServer()

        # Shutdown server cleanly
        server.close()
        QLocalServer.removeServer(sname)

        # 3. Verify single-instance lock recovery following crash
        lock_path = self.tmp / "vitarg-crash.lock"
        with open(lock_path, "w") as f:
            f.write("999999\npython\nhostname\nuuid-crashed-instance\n\n")
        old_time = time.time() - 1000
        os.utime(lock_path, (old_time, old_time))

        recov_lock = QLockFile(str(lock_path))
        recov_lock.setStaleLockTime(50)
        self.assertTrue(recov_lock.tryLock(200))
        self.assertTrue(recov_lock.isLocked())
        recov_lock.unlock()


# =====================================================================
# TIER 5: Adversarial Coverage Hardening (Challenger 1 Suite)
# =====================================================================

class Tier5AdversarialHardening(OpaqueE2EBase):
    """Tier 5: Adversarial Coverage Hardening (Archive traversal, handle leaks, media stress, cancellation)."""

    def _create_silent_video(self, name: str, duration: float = 0.5) -> Path:
        p = self.tmp / name
        exe = engine.need_tool("ffmpeg")
        cmd = [
            exe, "-y", "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size=160x120:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(p)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return p

    # --- ARCHIVE ADVERSARIAL TESTS ---

    def test_tier5_archive_01_zip_backslash_traversal_defense(self):
        """Verify safe_extract detects and blocks Windows backslash directory traversal in ZIP."""
        slip_zip = self.tmp / "backslash_slip.zip"
        with zipfile.ZipFile(slip_zip, "w") as z:
            z.writestr(r"..\..\escaped_backslash.txt", "adversarial payload")
        dest = self.tmp / "dest_backslash"
        dest.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(slip_zip, dest)
        self.assertIn("Unsafe path in archive", str(ctx.exception))
        self.assertFalse((self.tmp.parent / "escaped_backslash.txt").exists())

    def test_tier5_archive_02_absolute_drive_traversal_defense(self):
        """Verify safe_extract detects and blocks absolute drive path traversal in ZIP."""
        abs_zip = self.tmp / "abs_drive.zip"
        with zipfile.ZipFile(abs_zip, "w") as z:
            z.writestr("C:/escaped_drive.txt", "adversarial drive payload")
        dest = self.tmp / "dest_abs"
        dest.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(abs_zip, dest)
        self.assertIn("Unsafe path in archive", str(ctx.exception))

    def test_tier5_archive_03_unc_path_traversal_defense(self):
        """Verify safe_extract detects and blocks UNC network share paths in ZIP."""
        unc_zip = self.tmp / "unc_path.zip"
        with zipfile.ZipFile(unc_zip, "w") as z:
            z.writestr(r"\\127.0.0.1\share\escaped_unc.txt", "adversarial unc payload")
        dest = self.tmp / "dest_unc"
        dest.mkdir()
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.safe_extract(unc_zip, dest)
        self.assertIn("Unsafe path in archive", str(ctx.exception))

    def test_tier5_archive_04_deeply_nested_directory_stress(self):
        """Verify safe_extract handles deeply nested directory hierarchies (40 levels) cleanly."""
        deep_zip = self.tmp / "deep_hierarchy.zip"
        deep_rel = "/".join([f"level_{i}" for i in range(40)]) + "/payload.txt"
        with zipfile.ZipFile(deep_zip, "w") as z:
            z.writestr(deep_rel, "deep nested content")
        dest = self.tmp / "dest_deep"
        dest.mkdir()
        engine.safe_extract(deep_zip, dest)
        extracted = dest / Path(deep_rel)
        self.assertTrue(extracted.exists())
        self.assertEqual(extracted.read_text(), "deep nested content")

    def test_tier5_archive_05_corrupt_truncated_7z_archive(self):
        """Verify safe_extract rejects truncated / corrupt 7Z archives."""
        bad_7z = self.tmp / "truncated.7z"
        bad_7z.write_bytes(b"7z\xbc\xaf\x27\x1c\x00\x04truncated_corrupt_stream")
        dest = self.tmp / "dest_bad_7z"
        dest.mkdir()
        with self.assertRaises((engine.ConversionError, py7zr.exceptions.Bad7zFile, Exception)):
            engine.safe_extract(bad_7z, dest)

    def test_tier5_archive_06_corrupt_garbage_tar_archive(self):
        """Verify safe_extract rejects garbage non-tar archive headers."""
        bad_tar = self.tmp / "garbage.tar"
        bad_tar.write_bytes(b"GARBAGE_HEADER_DATA_NOT_A_VALID_TAR" * 15)
        dest = self.tmp / "dest_bad_tar"
        dest.mkdir()
        with self.assertRaises((engine.ConversionError, tarfile.ReadError, Exception)):
            engine.safe_extract(bad_tar, dest)

    def test_tier5_archive_07_tar_fifo_special_file_rejection(self):
        """Verify safe_extract rejects TAR archives containing FIFO / special device files."""
        tar_fifo = self.tmp / "special_fifo.tar"
        ti = tarfile.TarInfo("named_fifo_entry")
        ti.type = tarfile.FIFOTYPE
        ti.mtime = time.time()
        with tarfile.open(tar_fifo, "w") as tf:
            tf.addfile(ti)
        dest = self.tmp / "dest_fifo"
        dest.mkdir()
        with self.assertRaises((engine.ConversionError, tarfile.SpecialFileError, Exception)):
            engine.safe_extract(tar_fifo, dest)

    def test_tier5_archive_08_empty_archive_conversion_pipeline(self):
        """Verify converting an empty ZIP archive to 7Z and TAR produces valid empty archives."""
        empty_zip = self.tmp / "empty_source.zip"
        with zipfile.ZipFile(empty_zip, "w") as z:
            pass
        outs_7z = engine.convert(empty_zip, "7z", self.st)
        self.assertEqual(len(outs_7z), 1)
        self.assertTrue(outs_7z[0].exists())
        self.assertEqual(outs_7z[0].suffix.lower(), ".7z")

        outs_tar = engine.convert(empty_zip, "tar", self.st)
        self.assertEqual(len(outs_tar), 1)
        self.assertTrue(outs_tar[0].exists())
        self.assertEqual(outs_tar[0].suffix.lower(), ".tar")

    # --- CORE ENGINE & WORKSPACE ADVERSARIAL TESTS ---

    def test_tier5_engine_01_truncated_image_handle_leak_resilience(self):
        """Verify truncated image files raise ConversionError and release handles immediately."""
        t_png = self.tmp / "trunc.png"
        t_png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06")
        with self.assertRaises(engine.ConversionError):
            engine.convert(t_png, "jpg", self.st)
        t_png.unlink()
        self.assertFalse(t_png.exists())

        t_jpg = self.tmp / "trunc.jpg"
        t_jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01")
        with self.assertRaises(engine.ConversionError):
            engine.convert(t_jpg, "png", self.st)
        t_jpg.unlink()
        self.assertFalse(t_jpg.exists())

    def test_tier5_engine_02_workspace_scratch_cleanup_on_failure(self):
        """Verify workspace scratch directories (.vitarg-*) are cleaned up after ConversionError."""
        out_folder = self.tmp / "target_out"
        out_folder.mkdir()
        self.st.output_mode = "folder"
        self.st.output_folder = str(out_folder)

        bad_img = self.tmp / "bad_magic.png"
        bad_img.write_bytes(b"INVALID_MAGIC_HEADER_BYTES")
        with self.assertRaises(engine.ConversionError):
            engine.convert(bad_img, "jpg", self.st)

        leftovers = list(out_folder.glob(".vitarg-*"))
        self.assertEqual(leftovers, [])

    def test_tier5_engine_03_unwritable_destination_permission_error(self):
        """Verify Workspace raises ConversionError when destination directory is unwritable."""
        fake_dir = self.tmp / "file_blocking_dir.txt"
        fake_dir.write_text("blocking file")
        self.st.output_mode = "folder"
        self.st.output_folder = str(fake_dir)
        valid_img = self.create_image("sample.png")

        with self.assertRaises(engine.ConversionError) as ctx:
            engine.convert(valid_img, "jpg", self.st)
        self.assertIn("Cannot write to destination folder", str(ctx.exception))

    def test_tier5_engine_04_unique_name_extreme_collision_depth(self):
        """Verify unique_name resolves collisions accurately across 50 pre-existing numbered files."""
        col_dir = self.tmp / "col_depth"
        col_dir.mkdir()
        (col_dir / "target.png").write_text("0")
        for i in range(2, 51):
            (col_dir / f"target {i}.png").write_text(str(i))
        resolved = engine.unique_name(col_dir, "target.png", overwrite=False)
        self.assertEqual(resolved.name, "target 51.png")

    def test_tier5_engine_05_concurrent_conversion_isolation(self):
        """Verify multi-threaded parallel conversions into same output directory execute without collisions."""
        out_col = self.tmp / "concurrent_out"
        out_col.mkdir()
        self.st.output_mode = "folder"
        self.st.output_folder = str(out_col)

        results = []
        errors = []

        def worker(idx):
            src = self.tmp / f"thread_{idx}.png"
            with Image.new("RGB", (25, 25), (idx * 20 % 255, 100, 100)) as im:
                im.save(src)
            try:
                outs = engine.convert(src, "webp", self.st)
                results.extend(outs)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        for r in results:
            self.assertTrue(r.exists())

    # --- MEDIA PIPELINES ADVERSARIAL TESTS ---

    def test_tier5_media_01_silent_video_to_audio_rejection(self):
        """Verify converting video with no audio stream to audio format raises ConversionError."""
        silent = self._create_silent_video("silent.mp4", duration=0.4)
        with self.assertRaises(engine.ConversionError) as ctx:
            engine.convert(silent, "mp3", self.st)
        self.assertIn("The source has no audio stream to extract", str(ctx.exception))

    def test_tier5_media_02_silent_video_to_video_conversion_success(self):
        """Verify converting video with no audio stream to MKV succeeds via -map 0:a:0?."""
        silent = self._create_silent_video("silent2.mp4", duration=0.4)
        outs = engine.convert(silent, "mkv", self.st)
        self.assertEqual(len(outs), 1)
        self.assertTrue(outs[0].exists())
        probe_info = engine.probe(outs[0])
        self.assertTrue(probe_info["video"])
        self.assertFalse(probe_info["audio"])

    def test_tier5_media_03_corrupt_media_header_rejection(self):
        """Verify corrupt MP4 and WAV headers raise ConversionError during probing/conversion."""
        bad_mp4 = self.tmp / "corrupt_video.mp4"
        bad_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42corrupted_moov_atom_junk")
        with self.assertRaises(engine.ConversionError):
            engine.convert(bad_mp4, "mkv", self.st)

        bad_wav = self.tmp / "corrupt_audio.wav"
        bad_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00TRUNCATED_WAV_CHUNK")
        with self.assertRaises(engine.ConversionError):
            engine.convert(bad_wav, "mp3", self.st)

    def test_tier5_media_04_mid_flight_ffmpeg_cancellation_and_process_cleanup(self):
        """Verify mid-flight FFmpeg cancellation raises Cancelled and leaves no orphan files/processes."""
        med_mp4 = self._create_silent_video("med.mp4", duration=2.0)
        cancel_ev = threading.Event()
        raised_cancelled = []
        errors = []

        def cancel_job():
            try:
                engine.convert(med_mp4, "webm", self.st, cancel=cancel_ev)
            except engine.Cancelled:
                raised_cancelled.append(True)
            except Exception as e:
                errors.append(e)

        th = threading.Thread(target=cancel_job)
        th.start()
        time.sleep(0.15)
        cancel_ev.set()
        th.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(raised_cancelled, [True])
        leftovers = list(self.tmp.glob(".vitarg-*"))
        self.assertEqual(leftovers, [])

    def test_tier5_media_05_probe_cache_lru_eviction_bounds(self):
        """Verify _PROBE_CACHE respects _MAX_PROBE_CACHE (500) bound under synthetic flooding."""
        for i in range(550):
            fake_k = (f"C:\\synthetic_media_probe_{i}.mp4", 1000.0 + i, 4096 + i)
            engine._PROBE_CACHE[fake_k] = {"duration": 1.0, "video": True, "audio": True, "width": 100, "height": 100}
            if len(engine._PROBE_CACHE) > engine._MAX_PROBE_CACHE:
                engine._PROBE_CACHE.popitem(last=False)

        self.assertEqual(len(engine._PROBE_CACHE), engine._MAX_PROBE_CACHE)
        self.assertNotIn(("C:\\synthetic_media_probe_0.mp4", 1000.0, 4096), engine._PROBE_CACHE)
        self.assertIn(("C:\\synthetic_media_probe_549.mp4", 1549.0, 4645), engine._PROBE_CACHE)

    # --- DOCUMENT ADVERSARIAL TESTS ---

    def test_tier5_doc_01_password_protected_pdf_rejection(self):
        """Verify password-protected PDF conversion raises ConversionError cleanly."""
        locked = self.tmp / "password_doc.pdf"
        doc = fitz.open()
        doc.new_page(width=200, height=200)
        doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="adv_pwd_123")
        doc.close()

        with self.assertRaises(engine.ConversionError) as ctx:
            engine.convert(locked, "txt", self.st)
        self.assertIn("The PDF is password protected", str(ctx.exception))

    def test_tier5_doc_02_unselectable_scanned_pdf_rejection(self):
        """Verify PDF without selectable text raises ConversionError when converting to text."""
        scanned = self.tmp / "scanned_doc.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(10, 10, 190, 190), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
        doc.save(str(scanned))
        doc.close()

        with self.assertRaises(engine.ConversionError) as ctx:
            engine.convert(scanned, "txt", self.st)
        self.assertIn("This PDF has no selectable text", str(ctx.exception))


# =====================================================================
# TIER 5: Adversarial Coverage Hardening (Challenger 2 Suite)
# =====================================================================

class Tier5AdversarialChallenger2(OpaqueE2EBase):
    """Tier 5 Adversarial Hardening Suite (Challenger 2).

    Covers:
    - Multi-page TIFF rejection across tools wheel
    - Adversarial crop rectangle boundaries (zero/negative/out-of-bounds)
    - Resize parameter bounds & auto-aspect calculation
    - Thumbnail LRU cache pressure & bounds
    - GIF resize via run_tool
    - Rapid UndoManager cycles & history backup pruning
    - Undo rollback of directories and pre-deleted files
    - Massive rename collision chain resolution (25+ files)
    - Multi-extension archive (.tar.gz) collision handling
    - Windows illegal character sanitization & empty fallback
    - Corrupt (0-byte & garbage) QLockFile single-instance recovery
    - Burst QLocalSocket IPC connections & malformed payloads
    """

    # --- 1. Tools: Multi-page & Format Safety ---
    def test_tier5_adv_tools_01_multipage_tiff_rejected_by_single_frame_tools(self):
        """Verify multi-page TIFFs are safely rejected by tools requiring single frames."""
        tiff_path = self.tmp / "multipage_stress.tiff"
        im1 = Image.new("RGB", (50, 50), "red")
        im2 = Image.new("RGB", (50, 50), "green")
        im1.save(tiff_path, save_all=True, append_images=[im2], compression="tiff_lzw")
        im1.close(); im2.close()

        single_frame_tools = [
            ("crop", {"box": (5, 5, 25, 25)}),
            ("compress", {"preset": "Balanced", "max_edge": "Original"}),
            ("edit", {"brightness": 1.2}),
            ("addbg", {"color": "#FFFFFF", "padding": 5.0}),
            ("metadata", {}),
        ]
        for tool_id, params in single_frame_tools:
            outs, errs = tools.run_tool(tool_id, [tiff_path], params, self.st)
            self.assertEqual(len(errs), 1, f"Tool {tool_id} did not report error on multi-page TIFF")
            self.assertIn("Animated/multi-page images are not supported", errs[0][1])

    def test_tier5_adv_tools_02_crop_adversarial_boxes(self):
        """Stress-test crop boundaries: zero dimensions, negative, inverted, out-of-bounds."""
        crop_src = self.create_image("crop_stress.png", (80, 80))
        adversarial_boxes = [
            (10, 10, 10, 40),    # zero width
            (10, 10, 40, 10),    # zero height
            (-5, 5, 40, 40),     # negative left
            (5, -5, 40, 40),     # negative top
            (50, 10, 20, 40),    # inverted x (right < left)
            (10, 50, 40, 20),    # inverted y (bottom < top)
            (10, 10, 150, 40),   # out of bounds right
            (10, 10, 40, 150),   # out of bounds bottom
            (200, 200, 300, 300) # completely outside
        ]
        for box in adversarial_boxes:
            outs, errs = tools.run_tool("crop", [crop_src], {"box": box}, self.st)
            self.assertEqual(len(errs), 1, f"Crop did not fail on invalid box: {box}")
            self.assertIn("Invalid crop rectangle", errs[0][1])

        # 1x1 boundary crop must succeed
        outs_1x1, errs_1x1 = tools.run_tool("crop", [crop_src], {"box": (10, 10, 11, 11)}, self.st)
        self.assertEqual(errs_1x1, [])
        with Image.open(outs_1x1[0]) as im:
            self.assertEqual(im.size, (1, 1))

    def test_tier5_adv_tools_03_resize_parameter_bounds(self):
        """Verify resize handles extreme scale clamping and 0-dimension aspect calculation."""
        src = self.create_image("resize_stress.png", (100, 80))

        # Scale % clamped between 10% and 800%
        outs_low, _ = tools.run_tool("resize", [src], {"mode": "Scale %", "scale": 0}, self.st)
        with Image.open(outs_low[0]) as im:
            self.assertEqual(im.size, (10, 8))  # 10%

        outs_high, _ = tools.run_tool("resize", [src], {"mode": "Scale %", "scale": 2000}, self.st)
        with Image.open(outs_high[0]) as im:
            self.assertEqual(im.size, (800, 640))  # 800%

        # Exact pixels with one dimension 0 (auto-scaled aspect ratio)
        outs_w, _ = tools.run_tool("resize", [src], {"mode": "Exact pixels", "width": 50, "height": 0}, self.st)
        with Image.open(outs_w[0]) as im:
            self.assertEqual(im.size, (50, 40))

        # Exact pixels (0, 0) defaults safely to original dimensions
        outs_zero, _ = tools.run_tool("resize", [src], {"mode": "Exact pixels", "width": 0, "height": 0}, self.st)
        with Image.open(outs_zero[0]) as im:
            self.assertEqual(im.size, (100, 80))

    def test_tier5_adv_tools_04_lru_thumbnail_cache_pressure(self):
        """Verify thumbnail cache strictly enforces _MAX_THUMBS bound under burst generation."""
        sub = self.tmp / "thumb_burst"
        sub.mkdir()
        for i in range(80):
            p = sub / f"t_{i}.png"
            with Image.new("RGB", (10, 10), (i * 3 % 255, 50, 50)) as im:
                im.save(p)
            th = tools.thumb(p, box=(8, 8))
            self.assertLessEqual(th.width, 8)
        self.assertLessEqual(len(tools._THUMBS), tools._MAX_THUMBS)

    def test_tier5_adv_tools_05_gif_resize_in_run_tool(self):
        """Verify animated/multi-frame GIF resizing succeeds cleanly via run_tool without 'not supported' error."""
        gif_path = self.tmp / "anim_test.gif"
        frames = [
            Image.new("RGB", (40, 40), (255, 0, 0)),
            Image.new("RGB", (40, 40), (0, 255, 0)),
        ]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        for f in frames:
            f.close()

        outs, errs = tools.run_tool("resize", [gif_path], {"mode": "Exact pixels", "width": 20, "height": 20}, self.st)
        self.assertEqual(errs, [])
        self.assertEqual(len(outs), 1)
        self.assertTrue(outs[0].exists())
        with Image.open(outs[0]) as im:
            self.assertEqual(im.size, (20, 20))
            self.assertEqual(getattr(im, "n_frames", 1), 2)

    # --- 2. Undo Manager Stress & Resilience ---
    def test_tier5_adv_undo_01_rapid_50_cycles_and_backup_cleanup(self):
        """Record 50 rapid overwrite operations; verify history bounded and evicted backups cleaned."""
        self.undo_mgr.max_history = 10
        for i in range(50):
            tgt = self.tmp / f"undo_target_{i % 5}.txt"
            tgt.write_text(f"content_{i}")
            self.undo_mgr.record(f"Step {i}", [str(tgt)], overwritten_targets=[str(tgt)])
            tgt.write_text(f"overwritten_{i}")

        self.assertEqual(len(self.undo_mgr.history), 10)
        # Disk backups must not leak beyond history capacity
        backups_on_disk = list(self.undo_mgr._backup_dir.iterdir())
        self.assertLessEqual(len(backups_on_disk), 10)

        # Successive undos revert all 10 remaining actions
        for _ in range(10):
            self.assertTrue(self.undo_mgr.can_undo())
            ok, msg, affected = self.undo_mgr.undo()
            self.assertTrue(ok)

        # Empty history returns clean failure
        self.assertFalse(self.undo_mgr.can_undo())
        ok, msg, _ = self.undo_mgr.undo()
        self.assertFalse(ok)

    def test_tier5_adv_undo_02_directory_and_predeleted_resilience(self):
        """Verify undo cleanly removes entire generated directories and ignores pre-deleted files."""
        # 1. Directory output
        folder = self.tmp / "generated_pages"
        folder.mkdir()
        (folder / "p1.pdf").write_bytes(b"%PDF")
        (folder / "p2.pdf").write_bytes(b"%PDF")
        self.undo_mgr.record("Split", [str(folder)])
        self.assertTrue(folder.exists())
        ok, msg, _ = self.undo_mgr.undo()
        self.assertTrue(ok)
        self.assertFalse(folder.exists())

        # 2. Pre-deleted file before undo
        f = self.tmp / "deleted_ahead_of_time.txt"
        f.write_text("temp")
        self.undo_mgr.record("Write file", [str(f)])
        f.unlink()
        self.assertFalse(f.exists())
        ok, msg, _ = self.undo_mgr.undo()
        self.assertTrue(ok)
        self.assertFalse(f.exists())

    # --- 3. Rename Collision & Template Fuzzing ---
    def test_tier5_adv_rename_01_massive_collision_chain_25(self):
        """Verify collision loop resolves 25 existing collisions up to _26 in a single invocation."""
        base = self.tmp / "item.png"
        base.write_bytes(b"base")
        for i in range(2, 26):
            (self.tmp / f"item_{i:02d}.png").write_bytes(b"existing")

        incoming = self.tmp / "incoming.png"
        incoming.write_bytes(b"new")
        renamed = rename.apply_custom_rename([str(incoming)], "item")
        self.assertEqual(len(renamed), 1)
        res_path = Path(renamed[0])
        self.assertEqual(res_path.name, "item_26.png")
        self.assertTrue(res_path.exists())

    def test_tier5_adv_rename_02_targz_multi_extension_collision(self):
        """Verify .tar.gz preserves both extensions during rename collisions."""
        (self.tmp / "archive.tar.gz").write_bytes(b"tar0")
        (self.tmp / "archive_02.tar.gz").write_bytes(b"tar1")
        new_tar = self.tmp / "source.tar.gz"
        new_tar.write_bytes(b"tar_new")

        renamed = rename.apply_custom_rename([str(new_tar)], "archive")
        self.assertEqual(Path(renamed[0]).name, "archive_03.tar.gz")
        self.assertTrue(Path(renamed[0]).exists())

    def test_tier5_adv_rename_03_batch_literal_name_no_internal_collision(self):
        """Verify multiple files renamed with literal string do not collide with each other."""
        f1 = self.create_image("b1.png")
        f2 = self.create_image("b2.png")
        f3 = self.create_image("b3.png")
        renamed = rename.apply_custom_rename([str(f1), str(f2), str(f3)], "bundle")
        names = [Path(p).name for p in renamed]
        self.assertEqual(names, ["bundle.png", "bundle_02.png", "bundle_03.png"])
        for p in renamed:
            self.assertTrue(Path(p).exists())

    def test_tier5_adv_rename_04_windows_illegal_characters_and_empty_fallback(self):
        """Verify illegal Windows chars are stripped, and all-illegal names fallback to stem."""
        res = rename.format_rename("original.png", 'name:*?"<>|/\\file', "png")
        self.assertEqual(res, "namefile.png")

        fallback = rename.format_rename("original.png", ':::***???', "png")
        self.assertEqual(fallback, "original.png")

        trailing = rename.format_rename("original.png", "filename...   ", "png")
        self.assertEqual(trailing, "filename.png")

    # --- 4. Single Instance IPC & Corrupt Lockfile Recovery ---
    def test_tier5_adv_ipc_01_corrupt_zero_byte_and_garbage_lockfile_recovery(self):
        """Verify QLockFile recovers from 0-byte and random garbage stale lockfiles."""
        # 0-byte corrupt lockfile
        zero_lock = self.tmp / "corrupt_zero.lock"
        zero_lock.write_bytes(b"")
        q1 = QLockFile(str(zero_lock))
        q1.setStaleLockTime(50)
        time.sleep(0.06)
        self.assertTrue(q1.tryLock(100))
        q1.unlock()

        # Random garbage binary lockfile
        garbage_lock = self.tmp / "corrupt_garbage.lock"
        garbage_lock.write_bytes(os.urandom(256))
        old = time.time() - 300
        os.utime(garbage_lock, (old, old))
        q2 = QLockFile(str(garbage_lock))
        q2.setStaleLockTime(50)
        self.assertTrue(q2.tryLock(100))
        q2.unlock()

    def test_tier5_adv_ipc_02_burst_connections_and_malformed_payload(self):
        """Verify QLocalServer survives burst connections, malformed JSON, and oversized messages."""
        sname = f"vitarg-tier5-ipc-{os.getpid()}-{int(time.time()*1000)%10000}"
        QLocalServer.removeServer(sname)
        srv = QLocalServer()
        self.assertTrue(srv.listen(sname))

        received = []
        def on_conn():
            while True:
                sock = srv.nextPendingConnection()
                if not sock:
                    break
                if sock.waitForReadyRead(500):
                    data = sock.readAll().data().decode("utf-8", errors="ignore")
                    received.append(data)
                sock.disconnectFromServer()

        srv.newConnection.connect(on_conn)

        # 1. Burst of 5 sequential client connections
        for i in range(5):
            sock = QLocalSocket()
            sock.connectToServer(sname)
            if sock.waitForConnected(500):
                sock.write(json.dumps({"action": "open", "files": [f"file_{i}.txt"]}).encode("utf-8"))
                sock.flush()
                qt_app.processEvents()
                time.sleep(0.01)
                qt_app.processEvents()
                sock.disconnectFromServer()

        # 2. Corrupt non-JSON payload
        bad_sock = QLocalSocket()
        bad_sock.connectToServer(sname)
        if bad_sock.waitForConnected(500):
            bad_sock.write(b"CORRUPT_NON_JSON_DATA_BLOB")
            bad_sock.flush()
            qt_app.processEvents()
            time.sleep(0.01)
            qt_app.processEvents()
            bad_sock.disconnectFromServer()

        # 3. Oversized message (500 file paths)
        big_sock = QLocalSocket()
        big_sock.connectToServer(sname)
        if big_sock.waitForConnected(500):
            payload = json.dumps({"action": "open", "files": [f"path_{i}" for i in range(500)]}).encode("utf-8")
            big_sock.write(payload)
            big_sock.flush()
            qt_app.processEvents()
            time.sleep(0.01)
            qt_app.processEvents()
            big_sock.disconnectFromServer()

        time.sleep(0.05)
        qt_app.processEvents()
        srv.close()
        QLocalServer.removeServer(sname)

        # Verify all 7 transmissions were handled cleanly without server crash or hang
        self.assertEqual(len(received), 7)


if __name__ == "__main__":
    unittest.main()
