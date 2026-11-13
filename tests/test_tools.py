import subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
import random
from vitarg import engine, tools, settings as S


def ff(*a):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *a], check=True)


class T(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); self.st = S.Settings()

    def photo(self, name="p.jpg", size=(800, 600)):
        random.seed(1)
        im = Image.effect_noise(size, 40).convert("RGB")
        p = self.d / name; im.save(p, quality=97); return p

    def run_t(self, tid, srcs, **params):
        outs, errs = tools.run_tool(tid, srcs, params, self.st)
        self.assertEqual(errs, [], errs)
        return outs

    def test_menu_selection(self):
        a, b = self.photo("a.jpg"), self.photo("b.png")
        ids = lambda ps: [t.id for t in tools.tools_for(ps)]
        self.assertIn("crop", ids([a]))
        self.assertNotIn("crop", ids([a, b]))
        self.assertIn("collage", ids([a, b]))
        self.assertNotIn("collage", ids([a]))
        self.assertEqual(tools.tools_for([a, self.d / "x.mp3"]), [])

    def test_compress_and_meta(self):
        p = self.photo()
        out = self.run_t("compress", [p], preset="Strong", max_edge="Original")[0]
        self.assertLess(out.stat().st_size, p.stat().st_size)
        im = Image.open(p); ex = im.getexif(); ex[0x010F] = "SecretCam"; im.save(self.d / "m.jpg", exif=ex)
        self.assertIn(b"SecretCam", (self.d / "m.jpg").read_bytes())
        o = self.run_t("metadata", [self.d / "m.jpg"])[0]
        self.assertNotIn(b"SecretCam", o.read_bytes()); Image.open(o).load()

    def test_crop_edit_bg_collage_pdf(self):
        p = self.photo("a.png")
        c = self.run_t("crop", [p], box=(10, 20, 410, 320))[0]
        self.assertEqual(Image.open(c).size, (400, 300))
        _, errs = tools.run_tool("crop", [p], {"box": (0, 0, 9999, 9999)}, self.st)
        self.assertTrue(errs)
        e = self.run_t("edit", [p], brightness=1.5, contrast=1, saturation=1, sharpness=1)[0]
        self.assertGreater(sum(Image.open(e).convert("L").getdata()), sum(Image.open(p).convert("L").getdata()))
        t = self.d / "t.png"; Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(t)
        b = self.run_t("addbg", [t], color="#FF0000")[0]
        self.assertEqual(Image.open(b).convert("RGB").getpixel((5, 5)), (255, 0, 0))
        # background layer with padding: visible even on an opaque photo, and the preview matches the saved result
        bp = self.run_t("addbg", [p], color="#00FF00", padding=10)[0]
        self.assertEqual(Image.open(bp).size, (800 + 160, 600 + 160))
        self.assertEqual(Image.open(bp).getpixel((2, 2)), (0, 255, 0))
        prev = tools.preview_image("addbg", Image.open(p).convert("RGBA"), {"color": "#00FF00", "padding": 10})
        self.assertEqual(prev.size, Image.open(bp).size)
        pe = tools.preview_image("edit", Image.open(p).convert("RGBA"), {"brightness": 1.5})
        ee = Image.open(self.run_t("edit", [p], brightness=1.5, contrast=1, saturation=1, sharpness=1)[0])
        self.assertEqual(pe.convert("RGB").getpixel((100, 100)), ee.convert("RGB").getpixel((100, 100)))
        col = self.run_t("collage", [p, self.photo("b.jpg")], cols=2, spacing=10, bg="#000000")[0]
        self.assertEqual(Image.open(col).size, (1630, 820))
        pdf = self.run_t("create_pdf", [p, self.photo("c.jpg")])[0]
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    def test_media(self):
        v = self.d / "v.mp4"
        ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=4", "-f", "lavfi", "-i", "sine=duration=4",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-metadata", "title=Secret", str(v))
        silent = self.run_t("remove_audio", [v])[0]
        self.assertFalse(engine.probe(silent)["audio"])
        tr = self.run_t("trim", [v], start=1, end=3)[0]
        self.assertAlmostEqual(engine.probe(tr)["duration"], 2, delta=0.3)
        sp = self.run_t("speed", [v], factor=2)[0]
        self.assertAlmostEqual(engine.probe(sp)["duration"], 2, delta=0.4)
        snap = self.run_t("snapshot", [v], time=1)[0]
        self.assertEqual(Image.open(snap).size, (320, 240))
        co = self.run_t("compress", [v], preset="Balanced")[0]; self.assertTrue(engine.probe(co)["video"])
        m = self.run_t("metadata", [v])[0]
        self.assertNotIn(b"Secret", m.read_bytes())
        j = self.run_t("join", [v, silent])[0]
        info = engine.probe(j); self.assertTrue(info["audio"] and info["video"])
        self.assertAlmostEqual(info["duration"], 8, delta=0.6)
        a = self.d / "a.wav"; ff("-f", "lavfi", "-i", "sine=duration=3", str(a))
        n = self.run_t("normalize", [a])[0]; self.assertTrue(engine.probe(n)["audio"])
        at = self.run_t("trim", [a], start=0.5, end=1.5)[0]; self.assertAlmostEqual(engine.probe(at)["duration"], 1, delta=0.2)
        _, errs = tools.run_tool("trim", [a], {"start": 2, "end": 1}, self.st); self.assertTrue(errs)

    def test_previews(self):
        a, b = self.photo("a.jpg"), self.photo("b.png", (300, 500))
        im, _ = tools.make_preview("edit", [a], {"brightness": 1.4}); self.assertEqual(im.mode in ("RGB", "RGBA"), True)
        im, info = tools.make_preview("compress", [a], {"preset": "Strong", "max_edge": "Original"})
        self.assertIn("smaller", info)
        im, info = tools.make_preview("collage", [a, b], {"cols": 2, "spacing": 16, "bg": "#000000"})
        self.assertEqual(info, "2 images"); self.assertGreater(im.width, 300)
        v = self.d / "v.mp4"
        ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=4", "-f", "lavfi", "-i", "sine=duration=4",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(v))
        im, info = tools.make_preview("snapshot", [v], {"time": 1.5}); self.assertEqual(im.width, 480); self.assertIn("1.50s", info)
        im, info = tools.make_preview("speed", [v], {"factor": 2}); self.assertIn("4.0s → 2.0s", info)
        im, info = tools.make_preview("trim", [v], {"start": 1, "end": 3}); self.assertIn("2.00s", info); self.assertGreater(im.width, 600)
        au = self.d / "a.wav"; ff("-f", "lavfi", "-i", "sine=duration=3", str(au))
        im, info = tools.make_preview("trim", [au], {"start": 0.5, "end": 2}); self.assertEqual(im.size[1], 120)
        im, info = tools.make_preview("compress", [v], {"preset": "Balanced"}); self.assertIn("Original", info)
        im, info = tools.make_preview("compress", [au], {"preset": "Balanced"}); self.assertIsNotNone(im)

    def test_extract(self):
        z = self.d / "box.zip"
        with zipfile.ZipFile(z, "w") as zf: zf.writestr("x/y.txt", "hi")
        o = self.run_t("extract", [z])[0]
        self.assertEqual((o / "x" / "y.txt").read_text(), "hi")
        o2 = self.run_t("extract", [z])[0]; self.assertEqual(o2.name, "box 2")

    def test_resize(self):
        p = self.photo("orig.jpg", size=(800, 600))
        # Scale % test: 50%
        r50 = self.run_t("resize", [p], mode="Scale %", scale=50)[0]
        self.assertEqual(Image.open(r50).size, (400, 300))
        # Scale % test: 200%
        r200 = self.run_t("resize", [p], mode="Scale %", scale=200)[0]
        self.assertEqual(Image.open(r200).size, (1600, 1200))
        # Exact pixels test: 640x480
        rexact = self.run_t("resize", [p], mode="Exact pixels", width=640, height=480)[0]
        self.assertEqual(Image.open(rexact).size, (640, 480))
        # Exact pixels: width only (aspect ratio preserved)
        rauto = self.run_t("resize", [p], mode="Exact pixels", width=400, height=0)[0]
        self.assertEqual(Image.open(rauto).size, (400, 300))
        # Preview check
        prev, txt = tools.make_preview("resize", [p], {"mode": "Scale %", "scale": 50})
        self.assertIsNotNone(prev)
        self.assertIn("400 × 300", txt)


if __name__ == "__main__":
    unittest.main()
