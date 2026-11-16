import math, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vitarg import geometry as g, cropmath as c, keys


class Geo(unittest.TestCase):
    def test_four_petals_match_screenshot_layout(self):
        # petal 0 top (DOCX), 1 right (JPG), 2 bottom (PNG), 3 left (TXT)
        R0, R1 = 60, 150
        self.assertEqual(g.hit_test(4, 0, -100, R0, R1), 0)
        self.assertEqual(g.hit_test(4, 100, 0, R0, R1), 1)
        self.assertEqual(g.hit_test(4, 0, 100, R0, R1), 2)
        self.assertEqual(g.hit_test(4, -100, 0, R0, R1), 3)
        self.assertEqual(g.hit_test(4, 0, 0, R0, R1), -1)       # centre capsule
        self.assertEqual(g.hit_test(4, 0, -200, R0, R1), -1)    # outside
        self.assertEqual(g.hit_test(4, 70, -70, R0, R1), 1)     # diagonal belongs to next petal

    def test_seven_petals_cover_circle(self):
        seen = set()
        for deg in range(0, 360, 3):
            a = math.radians(deg)
            seen.add(g.hit_test(7, 100 * math.sin(a), -100 * math.cos(a), 50, 150))
        self.assertEqual(seen, set(range(7)))
        self.assertEqual(g.hit_test(7, 0, -100, 50, 150), 0)

    def test_label_pos(self):
        x, y = g.label_pos(1, 4, 100)
        self.assertAlmostEqual(x, 100); self.assertAlmostEqual(y, 0, places=6)


class Crop(unittest.TestCase):
    B = (0, 0, 2550, 1877)

    def test_ratio_and_bounds(self):
        r = c.fit_ratio(self.B, 1.0, self.B)
        self.assertAlmostEqual(r[2] - r[0], r[3] - r[1]); self.assertEqual(r[3] - r[1], 1877)
        r = c.fit_ratio(self.B, 16 / 9, self.B)
        self.assertAlmostEqual((r[2] - r[0]) / (r[3] - r[1]), 16 / 9)
        self.assertTrue(r[0] >= 0 and r[2] <= 2550)

    def test_resize_free_and_locked(self):
        r = c.resize((100, 100, 400, 300), "br", (700, 500), None, self.B)
        self.assertEqual(r, (100, 100, 700, 500))
        r = c.resize((100, 100, 400, 300), "br", (700, 900), 1.0, self.B)
        self.assertAlmostEqual(r[2] - r[0], r[3] - r[1])
        r = c.resize((100, 100, 400, 300), "tl", (-50, -50), None, self.B)
        self.assertEqual((r[0], r[1]), (0, 0))
        r = c.resize((100, 100, 400, 300), "r", (9999, 0), 4 / 3, self.B)
        self.assertTrue(r[2] <= 2550 and r[3] <= 1877 and r[1] >= 0)
        r = c.resize((100, 100, 400, 300), "l", (399, 0), None, self.B)
        self.assertGreaterEqual(r[2] - r[0], c.MIN)

    def test_move_and_size(self):
        self.assertEqual(c.move((10, 10, 110, 110), -50, 5000, self.B)[0], 0)
        self.assertEqual(c.move((10, 10, 110, 110), 0, 5000, self.B)[3], 1877)
        r = c.set_size((0, 0, 100, 100), 200, None, 2.0, self.B, "w")
        self.assertEqual((r[2] - r[0], r[3] - r[1]), (200, 100))
        r = c.set_size((0, 0, 100, 100), 99999, None, None, self.B, "w")
        self.assertEqual(r[2] - r[0], 2550)

    def test_hit_handle(self):
        rect = (100, 100, 300, 200)
        self.assertEqual(c.hit_handle(rect, (101, 99), 8), "tl")
        self.assertEqual(c.hit_handle(rect, (200, 101), 8), "t")
        self.assertEqual(c.hit_handle(rect, (200, 150), 8), "move")
        self.assertIsNone(c.hit_handle(rect, (50, 50), 8))


class Keys(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(keys.matches({"SHIFT"}, ["SHIFT"]))
        self.assertFalse(keys.matches({"SHIFT", "ALT"}, ["SHIFT"]))
        self.assertTrue(keys.matches({"ALT", "SHIFT"}, ["SHIFT", "ALT"]))
        self.assertFalse(keys.matches(set(), []))
        self.assertTrue(keys.matches({"CTRL", "Q"}, ["Q", "CTRL"]))
        self.assertEqual(keys.universe_for(["CTRL", "Q"]) >= {"Q", "CTRL", "SHIFT", "ALT", "WIN"}, True)


class AppearanceSlots(unittest.TestCase):
    def setUp(self):
        import os, tempfile
        self._orig_appdata = os.environ.get("APPDATA")
        self.tmp = tempfile.mkdtemp()
        os.environ["APPDATA"] = self.tmp

    def tearDown(self):
        import os, shutil
        if self._orig_appdata is not None:
            os.environ["APPDATA"] = self._orig_appdata
        else:
            os.environ.pop("APPDATA", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_slots_roundtrip_and_defaults(self):
        from vitarg import settings as S
        s = S.Settings()
        self.assertEqual((s.tint, s.opacity), ("#12111A", 75))          # dark glass default
        self.assertEqual(len(s.appearance_slots), 3)
        s.opacity, s.tint = 45, "#102030"
        s.appearance_slots[1] = {"name": "Night", **s.appearance()}
        s.active_slot = 1; s.save()
        t = S.Settings.load()
        self.assertEqual(t.appearance_slots[1]["tint"], "#102030")
        self.assertEqual(t.appearance_slots[0], {})
        t.reset_appearance()
        self.assertEqual((t.opacity, t.tint), (75, "#12111A"))
        self.assertEqual(t.appearance_slots[1]["opacity"], 45)           # reset never touches saved looks


class ResizeResolution(unittest.TestCase):
    def test_scale_mode(self):
        from vitarg.tools import _resolve_resize
        w, h = _resolve_resize({"mode": "Scale %", "scale": 50}, 1920, 1080)
        self.assertEqual((w, h), (960, 540))
        w, h = _resolve_resize({"mode": "Scale %", "scale": 200}, 800, 600)
        self.assertEqual((w, h), (1600, 1200))
        w, h = _resolve_resize({"mode": "Scale %", "scale": 5}, 100, 100)      # clamps to min 10%
        self.assertEqual((w, h), (10, 10))

    def test_exact_pixels_mode(self):
        from vitarg.tools import _resolve_resize
        # Both specified
        w, h = _resolve_resize({"mode": "Exact pixels", "width": 1280, "height": 720}, 1920, 1080)
        self.assertEqual((w, h), (1280, 720))
        # Width only, auto height preserves aspect ratio
        w, h = _resolve_resize({"mode": "Exact pixels", "width": 960, "height": 0}, 1920, 1080)
        self.assertEqual((w, h), (960, 540))
        # Height only, auto width preserves aspect ratio
        w, h = _resolve_resize({"mode": "Exact pixels", "width": 0, "height": 540}, 1920, 1080)
        self.assertEqual((w, h), (960, 540))
        # Neither specified: keeps original
        w, h = _resolve_resize({"mode": "Exact pixels", "width": 0, "height": 0}, 1920, 1080)
        self.assertEqual((w, h), (1920, 1080))


class CacheLRU(unittest.TestCase):
    def test_ordered_dict_lru_bounding(self):
        from collections import OrderedDict
        cache = OrderedDict()
        max_size = 5
        for i in range(10):
            cache[f"key_{i}"] = i
            if len(cache) > max_size:
                cache.popitem(last=False)
        self.assertEqual(len(cache), 5)
        self.assertEqual(list(cache.keys()), ["key_5", "key_6", "key_7", "key_8", "key_9"])

        # Accessing an existing key moves it to end
        cache.move_to_end("key_5")
        cache["key_10"] = 10
        if len(cache) > max_size:
            cache.popitem(last=False)
        # key_6 should have been evicted instead of key_5
        self.assertNotIn("key_6", cache)
        self.assertIn("key_5", cache)


class VitargUpdaterSemver(unittest.TestCase):
    def test_semver_parsing_and_comparison(self):
        from vitarg.updater import parse_semver
        self.assertEqual(parse_semver("v1.0.0"), (1, 0, 0))
        self.assertEqual(parse_semver("1.0.1"), (1, 0, 1))
        self.assertEqual(parse_semver("v2.0.0-beta"), (2, 0, 0))
        self.assertEqual(parse_semver("1.0.3.2"), (1, 0, 3, 2))
        self.assertTrue(parse_semver("v1.0.1") > parse_semver("v1.0.0"))
        self.assertTrue(parse_semver("v1.1.0") > parse_semver("v1.0.0"))
        self.assertTrue(parse_semver("v1.0.3.2") > parse_semver("v1.0.3"))
        self.assertFalse(parse_semver("v1.0.0") > parse_semver("v1.0.0"))
        self.assertFalse(parse_semver("v0.9.9") > parse_semver("v1.0.0"))

    def test_vitarg_package_imports(self):
        import vitarg
        import vitarg.geometry as vg
        import vitarg.cropmath as vc
        import vitarg.keys as vk
        import vitarg.settings as vs
        self.assertEqual(vitarg.__version__, "1.0.3.2")
        s = vs.Settings()
        self.assertEqual(s.tint, "#12111A")
        self.assertEqual(s.highlight, "#7C3AED")
        self.assertTrue(s.auto_update)
        self.assertTrue(s.prompt_rename)
        try:
            import PySide6
            from vitarg.app import selftest
            self.assertTrue(callable(selftest))
        except ImportError:
            pass

    def test_manifest_generation_and_diff(self):
        import tempfile
        from vitarg.updater import generate_manifest, diff_local_with_manifest
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "Vitarg.exe").write_bytes(b"MZ_fake_exe_12345")
            (p / "_internal").mkdir()
            (p / "_internal" / "lib1.dll").write_text("lib1")
            (p / "_internal" / "stale.dll").write_text("old_stale")
            (p / "tools").mkdir()
            tool_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
            (p / "tools" / tool_name).write_bytes(b"F" * 2000)

            # Generate manifest without stale.dll
            manifest = {
                "version": "1.0.3.2",
                "files": {
                    "Vitarg.exe": {"size": (p / "Vitarg.exe").stat().st_size, "sha256": ""},
                    "_internal/lib1.dll": {"size": (p / "_internal" / "lib1.dll").stat().st_size, "sha256": ""},
                    "_internal/new.dll": {"size": 50, "sha256": ""},
                }
            }
            diff = diff_local_with_manifest(p, manifest)
            self.assertIn("_internal/stale.dll", diff["stale_files"])
            self.assertIn("_internal/new.dll", diff["to_update"])
            self.assertIn("Vitarg.exe", diff["unchanged"])


class NewFeaturesTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_undo_manager_delete_created(self):
        from vitarg.undo import UndoManager
        mgr = UndoManager()
        f1 = self.tmp / "test_out.txt"
        f1.write_text("created file")
        self.assertTrue(f1.exists())
        mgr.record("Test create", [str(f1)])
        self.assertTrue(mgr.can_undo())
        ok, msg, affected = mgr.undo()
        self.assertTrue(ok)
        self.assertFalse(f1.exists())
        self.assertTrue(any(Path(f1).resolve() == Path(a).resolve() for a in affected))

    def test_undo_manager_restore_overwritten(self):
        from vitarg.undo import UndoManager
        mgr = UndoManager()
        orig = self.tmp / "existing.txt"
        orig.write_text("original content")
        mgr.record("Test overwrite", [str(orig)], overwritten_targets=[str(orig)])
        # Now simulate file being overwritten
        orig.write_text("overwritten content")
        self.assertEqual(orig.read_text(), "overwritten content")
        ok, msg, affected = mgr.undo()
        self.assertTrue(ok)
        self.assertEqual(orig.read_text(), "original content")

    def test_auto_rename_templates(self):
        from vitarg.rename import format_rename, apply_custom_rename
        src = self.tmp / "mypicture.png"
        src.write_text("dummy")
        # Template with {name} and {num}
        res = format_rename(src, "{name}_{num}", ".jpg", index=2)
        self.assertEqual(res, "mypicture_02.jpg")
        # Literal name
        res_lit = format_rename(src, "custom_vacation", ".webp", index=1)
        self.assertEqual(res_lit, "custom_vacation.webp")
        # Strip conflicting extension when user types old ext
        res_ext = format_rename(src, "custom_vacation.png", ".jpg", index=1)
        self.assertEqual(res_ext, "custom_vacation.jpg")
        # Apply rename on existing file
        new_paths = apply_custom_rename([str(src)], "final_photo")
        self.assertEqual(Path(new_paths[0]).name, "final_photo.png")
        self.assertTrue(Path(new_paths[0]).exists())
        # Renaming to same name does not fail or error
        same_paths = apply_custom_rename(new_paths, "final_photo")
        self.assertEqual(same_paths, new_paths)

    def test_auto_rename_directory_and_extensionless_no_trailing_dot(self):
        from vitarg.rename import format_rename, apply_custom_rename
        # Extensionless file or directory has ext=""
        res = format_rename(self.tmp / "folder", "TargetDir", "")
        self.assertEqual(res, "TargetDir")
        self.assertFalse(res.endswith("."))

        # Trailing dot in custom name itself is stripped
        res_dot = format_rename(self.tmp / "folder", "TargetDir.", "")
        self.assertEqual(res_dot, "TargetDir")

        # In apply_custom_rename for directory
        d = self.tmp / "SubDir"
        d.mkdir()
        renamed = apply_custom_rename([str(d)], "NewSubDir")
        self.assertEqual(Path(renamed[0]).name, "NewSubDir")
        self.assertTrue(Path(renamed[0]).is_dir())

    def test_auto_rename_targz_collision(self):
        from vitarg.rename import format_rename, apply_custom_rename
        t1 = self.tmp / "archive.tar.gz"
        t1.write_bytes(b"1")
        t2 = self.tmp / "other.tar.gz"
        t2.write_bytes(b"2")
        # Renaming t2 to "archive" should produce "archive_02.tar.gz", not "archive.tar_02.tar.gz"
        renamed = apply_custom_rename([str(t2)], "archive")
        self.assertEqual(Path(renamed[0]).name, "archive_02.tar.gz")
        self.assertTrue(Path(renamed[0]).exists())

    def test_undo_manager_prune_stale_backups(self):
        import time, os
        from vitarg.undo import UndoManager
        mgr = UndoManager()
        stale_file = mgr._backup_dir / "stale_test.bak"
        stale_file.write_text("old")
        old_mtime = time.time() - (8 * 86400)  # 8 days old
        os.utime(stale_file, (old_mtime, old_mtime))
        recent_file = mgr._backup_dir / "recent_test.bak"
        recent_file.write_text("new")
        pruned = mgr.prune_stale_backups(max_age_days=7)
        self.assertGreaterEqual(pruned, 1)
        self.assertFalse(stale_file.exists())
        self.assertTrue(recent_file.exists())
        recent_file.unlink(missing_ok=True)

    def test_workspace_publish_overwrite_backup(self):
        from vitarg import engine, settings as S
        from vitarg.undo import undo_manager
        st = S.Settings()
        st.overwrite = "overwrite"
        st.output_folder = str(self.tmp)
        target = self.tmp / "overwritable.txt"
        target.write_text("original before overwrite")

        with engine.Workspace(st, target) as ws:
            p = ws.path("overwritable.txt")
            p.write_text("new content overwriting original")
            pub = ws.publish()

        self.assertEqual(target.read_text(), "new content overwriting original")
        self.assertTrue(undo_manager.can_undo())
        ok, msg, affected = undo_manager.undo()
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), "original before overwrite")

    def test_job_window_accepts_custom_name(self):
        try:
            import PySide6
            import inspect
            from vitarg.jobs import JobWindow
            sig = inspect.signature(JobWindow.__init__)
            self.assertIn("custom_name", sig.parameters)
        except ImportError:
            import ast
            p = Path(__file__).resolve().parent.parent / "vitarg" / "jobs.py"
            tree = ast.parse(p.read_text(encoding="utf-8"))
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "JobWindow":
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                            arg_names = [a.arg for a in item.args.args]
                            self.assertIn("custom_name", arg_names)
                            found = True
            self.assertTrue(found)

    def test_estimator_size_and_quality(self):
        from vitarg.estimator import format_size, estimate_conversion
        self.assertEqual(format_size(500), "500 B")
        self.assertEqual(format_size(2048), "2.0 KB")
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 MB")
        sample = self.tmp / "sample.png"
        sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
        est = estimate_conversion(sample, "jpg")
        self.assertIn("Original:", est["summary"])
        self.assertIn("Est. Output:", est["summary"])
        self.assertGreater(est["src_size"], 0)

    def test_file_inspector_info(self):
        from vitarg.inspector import get_file_info
        f = self.tmp / "doc.txt"
        f.write_text("hello world inspector test")
        info = get_file_info(f)
        self.assertEqual(info["name"], "doc.txt")
        self.assertEqual(info["format"], "TXT")
        self.assertIn("bytes", info["size_str"])
        self.assertGreater(len(info["sha256"]), 10)


class LinuxPlatformTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_path_linux_xdg(self):
        import os
        from unittest.mock import patch
        from vitarg import settings as S
        with patch("sys.platform", "linux"), patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp), "APPDATA": ""}):
            p = S.Settings.path()
            self.assertEqual(p, self.tmp / "Vitarg" / "settings.json")

    def test_settings_path_linux_fallback(self):
        import os
        from unittest.mock import patch
        from vitarg import settings as S
        with patch("sys.platform", "linux"), patch.dict(os.environ, {}, clear=True), patch("pathlib.Path.home", return_value=self.tmp):
            p = S.Settings.path()
            self.assertEqual(p, self.tmp / ".config" / "Vitarg" / "settings.json")

    def test_linux_autostart_and_shortcut(self):
        import os
        from unittest.mock import patch
        from vitarg import settings as S
        config_dir = self.tmp / ".config"
        desktop_dir = self.tmp / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        local_share = self.tmp / ".local" / "share"

        with patch("sys.platform", "linux"), \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_dir), "XDG_DATA_HOME": str(local_share)}), \
             patch("pathlib.Path.home", return_value=self.tmp):
            # Test enable autostart
            S.set_launch_at_login(True)
            autostart_file = config_dir / "autostart" / "vitarg.desktop"
            self.assertTrue(autostart_file.exists())
            self.assertIn("Name=Vitarg", autostart_file.read_text(encoding="utf-8"))

            # Test disable autostart
            S.set_launch_at_login(False)
            self.assertFalse(autostart_file.exists())

            # Test create desktop shortcut
            ok = S.create_desktop_shortcut()
            self.assertTrue(ok)
            self.assertTrue((desktop_dir / "vitarg.desktop").exists())
            self.assertTrue((local_share / "applications" / "vitarg.desktop").exists())

    def test_folder_reveal_linux_uses_xdg_open(self):
        try:
            import PySide6
            from unittest.mock import patch, MagicMock
            with patch("sys.platform", "linux"), patch("subprocess.Popen") as mock_popen:
                import vitarg.jobs as jobs
                dummy_self = MagicMock()
                dummy_self._auto_close_timer = None
                dummy_self.outputs = [str(self.tmp / "output.png")]
                jobs.JobWindow._open_folder(dummy_self)
                mock_popen.assert_called_once_with(["xdg-open", str(self.tmp)])

            with patch("sys.platform", "linux"), patch("subprocess.Popen") as mock_popen:
                import vitarg.inspector as inspector
                dummy_insp = MagicMock()
                dummy_insp.file_path = self.tmp / "sample.txt"
                inspector.InspectorDialog._open_folder(dummy_insp)
                mock_popen.assert_called_once_with(["xdg-open", str(self.tmp)])
        except ImportError:
            for filename in ("jobs.py", "inspector.py"):
                p = Path(__file__).resolve().parent.parent / "vitarg" / filename
                code = p.read_text(encoding="utf-8")
                self.assertIn("xdg-open", code)
                self.assertIn('sys.platform == "win32"', code)

    def test_monitor_inactivity_on_linux(self):
        try:
            import PySide6
            from unittest.mock import patch, MagicMock
            from vitarg import monitor
            s = MagicMock()
            s.enabled = True
            with patch("sys.platform", "linux"):
                m = monitor.DragMonitor(s)
                m.start()
                self.assertFalse(m.timer.isActive())
        except ImportError:
            p = Path(__file__).resolve().parent.parent / "vitarg" / "monitor.py"
            code = p.read_text(encoding="utf-8")
            self.assertIn('if sys.platform != "win32":', code)


class V103FeatureTests(unittest.TestCase):
    def test_expanded_audio_codecs(self):
        from vitarg import engine
        for fmt in ("opus", "wma", "aiff", "ac3", "alac", "amr"):
            self.assertIn(fmt, engine.AUDIO_IN)
        for fmt in ("opus", "wma", "aiff", "ac3", "alac"):
            self.assertIn(fmt, engine.AUDIO_OUT)
            self.assertIn(fmt, engine.AUDIO_CODEC)

    def test_v103_new_tools_registration(self):
        from vitarg import tools
        for tid in ("target_compress", "volume", "eq", "extract_text"):
            self.assertIn(tid, tools.BY_ID)

        # Check volume tool options
        vol_tool = tools.BY_ID["volume"]
        vol_field = next(f for f in vol_tool.form if f["key"] == "volume")
        self.assertEqual(vol_field["max"], 600)
        self.assertEqual(vol_field["min"], 10)

        # Check target size tool options
        tc_tool = tools.BY_ID["target_compress"]
        preset_field = next(f for f in tc_tool.form if f["key"] == "preset")
        self.assertIn("<25 MB (Discord)", preset_field["choices"])
        self.assertIn("<50 MB (Nitro)", preset_field["choices"])

        # Check PDF tools have custom organizer
        self.assertEqual(tools.BY_ID["merge_pdf"].custom, "pdf_organizer")
        self.assertEqual(tools.BY_ID["create_pdf"].custom, "pdf_organizer")

    def test_context_menu_settings_default(self):
        from vitarg import settings as S
        st = S.Settings()
        self.assertFalse(st.context_menu)

    def test_context_menu_registration_linux(self):
        import os, tempfile, shutil
        from unittest.mock import patch
        from vitarg import settings as S
        tmp = Path(tempfile.mkdtemp())
        try:
            with patch("sys.platform", "linux"), patch("pathlib.Path.home", return_value=tmp):
                # Enable
                ok = S.set_context_menu(True)
                self.assertTrue(ok)
                script_path = tmp / ".local" / "share" / "nautilus" / "scripts" / "Convert with Vitarg"
                kde_path = tmp / ".local" / "share" / "kio" / "servicemenus" / "vitarg.desktop"
                self.assertTrue(script_path.exists())
                self.assertTrue(kde_path.exists())
                self.assertIn("Convert with Vitarg", kde_path.read_text(encoding="utf-8"))

                # Disable
                ok_off = S.set_context_menu(False)
                self.assertTrue(ok_off)
                self.assertFalse(script_path.exists())
                self.assertFalse(kde_path.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_size_diff_formatting(self):
        from vitarg.estimator import format_size
        s1 = 25 * 1024 * 1024
        s2 = 4 * 1024 * 1024
        diff = s2 - s1
        pct = abs(diff) / s1 * 100.0
        self.assertAlmostEqual(pct, 84.0, places=0)
        self.assertEqual(format_size(s1), "25.0 MB")
        self.assertEqual(format_size(s2), "4.0 MB")


if __name__ == "__main__":
    unittest.main()
