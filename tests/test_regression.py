"""Dedicated Bug Regression Test Suite (Milestone M5).
Programmatic tests for confirmed bugs BUG-01 through BUG-14.
All tests execute in isolated temporary directories with sandboxed environments."""
import hashlib, os, shutil, sys, tempfile, threading, time, unittest
from pathlib import Path

# Ensure application root is in python search path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from vitarg import engine, settings as S

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

os.environ["QT_QPA_PLATFORM"] = "offscreen"
try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    HAS_QT = True
except ImportError:
    HAS_QT = False


class RegressionBase(unittest.TestCase):
    """Base class ensuring isolated temporary directory and sandboxed APPDATA."""
    def setUp(self):
        self._orig_appdata = os.environ.get("APPDATA")
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["APPDATA"] = str(self.tmp)
        self.st = S.Settings()

    def tearDown(self):
        if self._orig_appdata is not None:
            os.environ["APPDATA"] = self._orig_appdata
        else:
            os.environ.pop("APPDATA", None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBug01EstimatorZeroByte(RegressionBase):
    """BUG-01: ZeroDivisionError on 0-byte file in estimator."""
    def test_zero_byte_estimator(self):
        from vitarg.estimator import estimate_conversion
        empty_file = self.tmp / "empty.png"
        empty_file.write_bytes(b"")
        self.assertEqual(empty_file.stat().st_size, 0)

        for target in ("jpg", "pdf", "docx", "mp4"):
            res = estimate_conversion(empty_file, target)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["src_size"], 0)
            self.assertEqual(res["src_size_str"], "0 B")
            self.assertEqual(res["ratio_pct"], 0.0)
            self.assertIn("Original: 0 B", res["summary"])


@unittest.skipUnless(HAS_QT, "PySide6 Qt required for JobWindow lifecycle test")
class TestBug02JobWindowLifecycle(RegressionBase):
    """BUG-02: JobWindow QThread cancellation and wait on window close."""
    def test_job_window_cancellation_and_wait_on_close(self):
        from vitarg.jobs import JobWindow

        worker_started = threading.Event()

        def slow_worker_fn(progress, cancel):
            worker_started.set()
            while not cancel.is_set():
                time.sleep(0.01)
            return [], []

        win = JobWindow("Test Window", "Processing...", slow_worker_fn)
        win.worker.start()
        self.assertTrue(worker_started.wait(timeout=2.0))
        self.assertTrue(win.worker.isRunning())

        # Simulate user closing the window
        win.close_and_release()

        self.assertTrue(win.worker.cancel.is_set())
        self.assertFalse(win.worker.isRunning())
        win.deleteLater()

    def test_job_window_close_event_cancellation(self):
        from vitarg.jobs import JobWindow
        from PySide6.QtGui import QCloseEvent

        worker_started = threading.Event()

        def slow_worker_fn(progress, cancel):
            worker_started.set()
            while not cancel.is_set():
                time.sleep(0.01)
            return [], []

        win = JobWindow("Test CloseEvent", "Processing...", slow_worker_fn)
        win.worker.start()
        self.assertTrue(worker_started.wait(timeout=2.0))
        self.assertTrue(win.worker.isRunning())

        ev = QCloseEvent()
        win.closeEvent(ev)

        self.assertTrue(win.worker.cancel.is_set())
        self.assertFalse(win.worker.isRunning())
        win.deleteLater()


@unittest.skipUnless(HAS_QT, "PySide6 Qt required for UpdateDialog lifecycle test")
class TestBug03UpdateDialogLifecycle(RegressionBase):
    """BUG-03: UpdateDialog DownloadThread cancellation on dismiss."""
    def test_update_dialog_cancel_on_dismiss(self):
        from vitarg.updater import UpdateDialog, DownloadThread

        info = {
            "version": "9.9.9",
            "notes": "Testing cancellation",
            "download_url": "http://127.0.0.1:65530/test.exe"
        }
        dlg = UpdateDialog(info, current_version="1.0.0")

        # Mock download thread with cancel flag
        dl_thread = DownloadThread(info["download_url"], "test.exe")
        dlg.dl_thread = dl_thread

        started = threading.Event()

        def mock_run():
            started.set()
            while not dl_thread._cancelled:
                time.sleep(0.01)

        dl_thread.run = mock_run
        dl_thread.start()
        self.assertTrue(started.wait(timeout=2.0))
        self.assertTrue(dl_thread.isRunning())

        # Dismiss via _on_later
        dlg._on_later()

        self.assertTrue(dl_thread._cancelled)
        self.assertFalse(dl_thread.isRunning())
        dlg.deleteLater()

    def test_update_dialog_cancel_on_close_event(self):
        from vitarg.updater import UpdateDialog, DownloadThread
        from PySide6.QtGui import QCloseEvent

        info = {
            "version": "9.9.9",
            "notes": "Testing cancellation",
            "download_url": "http://127.0.0.1:65530/test.exe"
        }
        dlg = UpdateDialog(info, current_version="1.0.0")

        dl_thread = DownloadThread(info["download_url"], "test.exe")
        dlg.dl_thread = dl_thread

        started = threading.Event()

        def mock_run():
            started.set()
            while not dl_thread._cancelled:
                time.sleep(0.01)

        dl_thread.run = mock_run
        dl_thread.start()
        self.assertTrue(started.wait(timeout=2.0))
        self.assertTrue(dl_thread.isRunning())

        ev = QCloseEvent()
        dlg.closeEvent(ev)

        self.assertTrue(dl_thread._cancelled)
        self.assertFalse(dl_thread.isRunning())
        dlg.deleteLater()


@unittest.skipUnless(HAS_QT, "PySide6 Qt required for QLockFile test")
class TestBug04QLockFileStaleTimeout(RegressionBase):
    """BUG-04: QLockFile stale timeout recovery after crash."""
    def test_lockfile_stale_time_configured(self):
        from PySide6.QtCore import QLockFile
        lock_path = self.tmp / "test.lock"
        lock = QLockFile(str(lock_path))
        lock.setStaleLockTime(30000)
        self.assertEqual(lock.staleLockTime(), 30000)
        self.assertTrue(lock.tryLock(100))
        self.assertTrue(lock.isLocked())
        lock.unlock()
        self.assertFalse(lock.isLocked())

    def test_app_stale_lock_constant_is_positive(self):
        import inspect
        from vitarg import app as vitarg_app
        src = inspect.getsource(vitarg_app.main)
        self.assertIn("lock.setStaleLockTime(30000)", src)
        self.assertNotIn("lock.setStaleLockTime(0)", src)


class TestBug05DragMonitorSynchronization(RegressionBase):
    """BUG-05: DragMonitor thread synchronization with _lock."""
    def test_drag_monitor_thread_synchronization(self):
        from vitarg.monitor import DragMonitor
        st = S.Settings()
        st.enabled = True
        mon = DragMonitor(st)
        self.assertTrue(hasattr(mon, "_lock"))
        self.assertIsNotNone(mon._lock)

        stop_event = threading.Event()
        errors = []

        def worker_query():
            counter = 0
            while not stop_event.is_set():
                counter += 1
                try:
                    with mon._lock:
                        mon.sel = [f"path_{counter}_{i}.txt" for i in range(5)]
                        mon.token = counter
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

        def worker_tick():
            while not stop_event.is_set():
                try:
                    with mon._lock:
                        current_sel = list(mon.sel)
                        token = mon.token
                    self.assertIsInstance(current_sel, list)
                    self.assertIsInstance(token, int)
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=worker_query)
        t2 = threading.Thread(target=worker_tick)
        t1.start()
        t2.start()

        time.sleep(0.2)
        stop_event.set()
        t1.join()
        t2.join()

        self.assertEqual(errors, [])


class TestBug06InspectorAsyncSha256(RegressionBase):
    """BUG-06: Inspector async SHA-256 non-blocking execution & cancellation."""
    def test_compute_sha256_matches_standard_hashlib(self):
        from vitarg.inspector import compute_sha256
        test_file = self.tmp / "sample_hash.bin"
        data = b"Arbitrary data for hash verification " * 1024
        test_file.write_bytes(data)

        expected_hash = hashlib.sha256(data).hexdigest()
        actual_hash = compute_sha256(test_file)
        self.assertEqual(actual_hash, expected_hash)

    def test_compute_sha256_cancellation(self):
        from vitarg.inspector import compute_sha256
        test_file = self.tmp / "sample_cancel.bin"
        test_file.write_bytes(b"x" * 65536)

        cancel_ev = threading.Event()
        cancel_ev.set()  # Cancel immediately

        result = compute_sha256(test_file, cancel_event=cancel_ev)
        self.assertEqual(result, "Calculation cancelled")

    @unittest.skipUnless(HAS_QT, "PySide6 Qt required for HashThread test")
    def test_hash_thread_execution_and_cancellation(self):
        from vitarg.inspector import HashThread
        test_file = self.tmp / "thread_hash.bin"
        data = b"Hash thread background test content"
        test_file.write_bytes(data)
        expected_hash = hashlib.sha256(data).hexdigest()

        # Test normal completion
        ht = HashThread(test_file)
        results = []
        ht.finished.connect(results.append)
        ht.start()
        self.assertTrue(ht.wait(2000))
        QCoreApplication.processEvents()
        self.assertEqual(results, [expected_hash])

        # Test cancellation
        large_file = self.tmp / "large_cancel.bin"
        large_file.write_bytes(b"A" * (2 * 1024 * 1024))
        ht2 = HashThread(large_file)
        ht2.cancel()
        results2 = []
        ht2.finished.connect(results2.append)
        ht2.start()
        self.assertTrue(ht2.wait(2000))
        QCoreApplication.processEvents()
        self.assertEqual(results2, ["Calculation cancelled"])


class TestBug07ResizePreviewOriginalDimensions(RegressionBase):
    """BUG-07: Resize preview calculation from original image."""
    def test_resize_preview_calculated_from_original_dimensions(self):
        from vitarg import tools
        img_path = self.tmp / "orig_image.png"
        with Image.new("RGB", (800, 600), (100, 150, 200)) as im:
            im.save(img_path)

        # Scale 50%: original 800x600 -> 400x300
        prev, txt = tools.make_preview("resize", [img_path], {"mode": "Scale %", "scale": 50})
        self.assertIsNotNone(prev)
        self.assertEqual(txt, "Output: 400 × 300 px")

        # Scale 200%: original 800x600 -> 1600x1200
        prev2, txt2 = tools.make_preview("resize", [img_path], {"mode": "Scale %", "scale": 200})
        self.assertIsNotNone(prev2)
        self.assertEqual(txt2, "Output: 1600 × 1200 px")

        # Exact pixels: 640x480
        prev3, txt3 = tools.make_preview("resize", [img_path], {"mode": "Exact pixels", "width": 640, "height": 480})
        self.assertIsNotNone(prev3)
        self.assertEqual(txt3, "Output: 640 × 480 px")


class TestBug08DynamicToolLookup(RegressionBase):
    """BUG-08: Dynamic tool lookup in test environment."""
    def test_engine_find_tool(self):
        # Tools bundled in Vitarg_work/tools or system PATH
        ffmpeg = engine.find_tool("ffmpeg")
        self.assertIsNotNone(ffmpeg)
        self.assertTrue(Path(ffmpeg).exists())

        ffprobe = engine.find_tool("ffprobe")
        self.assertIsNotNone(ffprobe)
        self.assertTrue(Path(ffprobe).exists())

        pandoc = engine.find_tool("pandoc")
        self.assertIsNotNone(pandoc)
        self.assertTrue(Path(pandoc).exists())

        missing = engine.find_tool("nonexistent_binary_xyz_12345")
        self.assertIsNone(missing)


class TestBug09DirectoryRenameTrailingDot(RegressionBase):
    """BUG-09: Directory custom rename without trailing dot or space."""
    def test_format_rename_directory_and_extensionless(self):
        from vitarg.rename import format_rename, apply_custom_rename

        # Extensionless directory
        res1 = format_rename(self.tmp / "folder", "TargetDir", "")
        self.assertEqual(res1, "TargetDir")
        self.assertFalse(res1.endswith("."))

        # Custom name ending with period
        res2 = format_rename(self.tmp / "folder", "TargetDir.", "")
        self.assertEqual(res2, "TargetDir")
        self.assertFalse(res2.endswith("."))

        # Custom name ending with spaces
        res3 = format_rename(self.tmp / "folder", "TargetDir   ", "")
        self.assertEqual(res3, "TargetDir")
        self.assertFalse(res3.endswith(" "))

        # Apply custom rename to actual folder on disk
        target_dir = self.tmp / "SourceFolder"
        target_dir.mkdir()
        renamed = apply_custom_rename([str(target_dir)], "FinalFolder.")
        self.assertEqual(len(renamed), 1)
        renamed_path = Path(renamed[0])
        self.assertEqual(renamed_path.name, "FinalFolder")
        self.assertTrue(renamed_path.is_dir())
        self.assertFalse(renamed_path.name.endswith("."))


class TestBug10TarGzMultiDotCollision(RegressionBase):
    """BUG-10: Tar.gz multi-dot collision formatting."""
    def test_targz_collision_formatting(self):
        from vitarg.rename import apply_custom_rename
        t1 = self.tmp / "archive.tar.gz"
        t1.write_bytes(b"content 1")
        t2 = self.tmp / "other.tar.gz"
        t2.write_bytes(b"content 2")
        t3 = self.tmp / "third.tar.gz"
        t3.write_bytes(b"content 3")

        # Renaming t2 to "archive" must produce archive_02.tar.gz, NOT archive.tar_02.tar.gz
        res2 = apply_custom_rename([str(t2)], "archive")
        self.assertEqual(Path(res2[0]).name, "archive_02.tar.gz")
        self.assertTrue(Path(res2[0]).exists())

        # Renaming t3 to "archive" must produce archive_03.tar.gz
        res3 = apply_custom_rename([str(t3)], "archive")
        self.assertEqual(Path(res3[0]).name, "archive_03.tar.gz")
        self.assertTrue(Path(res3[0]).exists())


class TestBug11ImageHandleClosureAndCleanDeletion(RegressionBase):
    """BUG-11 / BUG-11b: Image file handle closures and tempdir deletion without locks."""
    def test_image_handle_closure_on_conversion(self):
        src = self.tmp / "test_handle.png"
        with Image.new("RGBA", (100, 100), (255, 0, 0, 128)) as im:
            im.save(src)

        # Convert to ICO and GIF
        for tgt in ("ico", "gif"):
            out = engine.convert(src, tgt, self.st)[0]
            self.assertTrue(out.exists())
            # Immediate deletion must succeed without WinError 32
            out.unlink()
            self.assertFalse(out.exists())

    def test_multipage_tiff_error_handle_closure(self):
        from vitarg import tools
        tiff_path = self.tmp / "multi_test.tiff"
        with Image.new("RGB", (32, 32), "red") as f1, Image.new("RGB", (32, 32), "blue") as f2:
            f1.save(tiff_path, save_all=True, append_images=[f2])

        # Test preview throws ConversionError and closes file handle
        with self.assertRaises(engine.ConversionError):
            tools.make_preview("compress", [tiff_path], {"preset": "Balanced"})

        # Immediate unlink must succeed without sharing violation
        tiff_path.unlink()
        self.assertFalse(tiff_path.exists())


@unittest.skipUnless(HAS_FITZ, "PyMuPDF fitz required for PDF handle closure test")
class TestBug12PyMuPdfDocumentHandleClosure(RegressionBase):
    """BUG-12: PyMuPDF document handle closures in engine and tools."""
    def test_pdf_handles_closed_after_engine_and_tools_operations(self):
        from vitarg import tools
        pdf_path = self.tmp / "test_doc.pdf"
        with fitz.open() as doc:
            p1 = doc.new_page(width=595, height=842)
            p1.insert_text((50, 50), "PDF Handle Test Page 1")
            p2 = doc.new_page(width=595, height=842)
            p2.insert_text((50, 50), "PDF Handle Test Page 2")
            doc.save(str(pdf_path))

        # 1. Text extraction
        txt = engine.pdf_to_text(pdf_path)
        self.assertIn("Page 1", txt)

        # 2. Convert to images
        img_outs = engine.convert(pdf_path, "png", self.st)
        self.assertTrue(len(img_outs) > 0)

        # 3. PDF tool split
        split_outs, errs = tools.run_tool("split_pdf", [pdf_path], {}, self.st)
        self.assertEqual(errs, [])
        self.assertTrue(len(split_outs) > 0)

        # 4. Immediate unlink of original PDF without file lock
        pdf_path.unlink()
        self.assertFalse(pdf_path.exists())


class TestBug13OverwriteModeBackupAndUndo(RegressionBase):
    """BUG-13: Overwrite mode backup and bit-for-bit restoration via UndoManager."""
    def test_workspace_publish_overwrite_preserves_original(self):
        from vitarg.undo import undo_manager
        target = self.tmp / "important_document.txt"
        original_bytes = b"EXACT_ORIGINAL_CONTENT_PRESERVED_12345"
        target.write_bytes(original_bytes)

        st = S.Settings()
        st.overwrite = "overwrite"
        st.output_folder = str(self.tmp)

        with engine.Workspace(st, target) as ws:
            work_file = ws.path("important_document.txt")
            work_file.write_bytes(b"NEW_OVERWRITTEN_CONTENT_67890")
            pub = ws.publish()

        self.assertEqual(target.read_bytes(), b"NEW_OVERWRITTEN_CONTENT_67890")
        self.assertTrue(undo_manager.can_undo())

        # Undo the overwrite operation
        ok, msg, affected = undo_manager.undo()
        self.assertTrue(ok)
        self.assertEqual(target.read_bytes(), original_bytes)


class TestBug14StaleBackupPruning(RegressionBase):
    """BUG-14: Stale backup pruning in UndoManager."""
    def test_prune_stale_backups_older_than_max_age(self):
        from vitarg.undo import UndoManager
        mgr = UndoManager()

        # Direct test backups to isolated directory inside self.tmp
        test_backup_dir = self.tmp / "vitarg_backups_test"
        test_backup_dir.mkdir()
        mgr._backup_dir = test_backup_dir

        old_file = test_backup_dir / "old_backup.bak"
        old_file.write_text("old data")
        old_mtime = time.time() - (10 * 86400)  # 10 days old
        os.utime(old_file, (old_mtime, old_mtime))

        old_dir = test_backup_dir / "old_dir_backup"
        old_dir.mkdir()
        (old_dir / "sub.txt").write_text("sub")
        os.utime(old_dir, (old_mtime, old_mtime))

        recent_file = test_backup_dir / "recent_backup.bak"
        recent_file.write_text("recent data")

        pruned = mgr.prune_stale_backups(max_age_days=7)
        self.assertEqual(pruned, 2)
        self.assertFalse(old_file.exists())
        self.assertFalse(old_dir.exists())
        self.assertTrue(recent_file.exists())


if __name__ == "__main__":
    unittest.main()
