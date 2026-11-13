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
        self.assertEqual(vitarg.__version__, "1.0.0")
        s = vs.Settings()
        self.assertEqual(s.tint, "#12111A")
        self.assertEqual(s.highlight, "#7C3AED")
        self.assertTrue(s.auto_update)


if __name__ == "__main__":
    unittest.main()
