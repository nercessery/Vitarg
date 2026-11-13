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
    def test_slots_roundtrip_and_defaults(self):
        import os, tempfile
        from vitarg import settings as S
        os.environ["APPDATA"] = tempfile.mkdtemp()
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
        self.assertTrue(parse_semver("v1.0.1") > parse_semver("v1.0.0"))
        self.assertTrue(parse_semver("v1.1.0") > parse_semver("v1.0.0"))
        self.assertFalse(parse_semver("v1.0.0") > parse_semver("v1.0.0"))
        self.assertFalse(parse_semver("v0.9.9") > parse_semver("v1.0.0"))

    def test_vitarg_package_imports(self):
        import vitarg
        import vitarg.geometry as vg
        import vitarg.cropmath as vc
        import vitarg.keys as vk
        import vitarg.settings as vs
        self.assertEqual(vitarg.__version__, "1.0.2")
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


class NewFeaturesTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

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


if __name__ == "__main__":
    unittest.main()
