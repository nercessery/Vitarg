"""Real-conversion tests. Run: python -m unittest discover -s tests -v
PDF/SVG cases are skipped automatically when PyMuPDF is not installed."""
import os, subprocess, sys, tempfile, unittest, zipfile, tarfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
from vitarg import engine, settings as S

try:
    import fitz  # noqa
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False
HAS_FF = bool(engine.find_tool("ffmpeg") and engine.find_tool("ffprobe"))
HAS_PANDOC = bool(engine.find_tool("pandoc"))


def ff(*a):
    exe = engine.find_tool("ffmpeg") or "ffmpeg"
    subprocess.run([exe, "-loglevel", "error", "-y", *a], check=True)


class Base(unittest.TestCase):
    def setUp(self):
        self._orig_appdata = os.environ.get("APPDATA")
        self.tmp = Path(tempfile.mkdtemp())
        self.st = S.Settings()

    def tearDown(self):
        import shutil
        if self._orig_appdata is not None:
            os.environ["APPDATA"] = self._orig_appdata
        else:
            os.environ.pop("APPDATA", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conv(self, src, tgt):
        return engine.convert(src, tgt, self.st)


class ImageTests(Base):
    def test_all_pairs(self):
        im = Image.new("RGBA", (120, 80), (255, 128, 0, 200))
        for sf in ("png", "jpg", "webp", "bmp", "tiff", "gif", "ico"):
            src = self.tmp / f"a.{sf}"
            (im.convert("RGB") if sf in ("jpg", "bmp") else im).save(src)
            for tf in engine.targets_for_format(sf):
                if tf == "docx" or (tf in ("mp4", "mov", "mkv", "webm") and not HAS_FF):
                    continue
                out = self.conv(src, tf)[0]
                self.assertGreater(out.stat().st_size, 50, f"{sf}->{tf}")
                if tf == "pdf":
                    self.assertTrue(out.read_bytes().startswith(b"%PDF"))
                elif tf in ("mp4", "mov", "mkv", "webm"):
                    self.assertTrue(engine.probe(out)["video"], f"{sf}->{tf}")
                else:
                    with Image.open(out) as im_chk:
                        im_chk.load()
                self.assertNotEqual(out, src)

    def test_collision_naming(self):
        src = self.tmp / "cat.png"; Image.new("RGB", (10, 10)).save(src)
        a = self.conv(src, "jpg")[0]; b = self.conv(src, "jpg")[0]; c = self.conv(src, "jpg")[0]
        self.assertEqual([a.name, b.name, c.name], ["cat.jpg", "cat 2.jpg", "cat 3.jpg"])
        self.assertTrue(src.exists())
        self.assertFalse([p for p in self.tmp.iterdir() if p.name.startswith(".vitarg-")])

    def test_overwrite_mode(self):
        src = self.tmp / "cat.png"; Image.new("RGB", (10, 10)).save(src)
        self.st.overwrite = "overwrite"
        self.conv(src, "jpg"); self.conv(src, "jpg")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["cat.jpg", "cat.png"])

    def test_docx_from_image(self):
        src = self.tmp / "a.png"; Image.new("RGB", (200, 100), "red").save(src)
        out = self.conv(src, "docx")[0]
        with zipfile.ZipFile(out) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(any(n.startswith("word/media/") for n in z.namelist()))

    def test_animated_gif_to_webp(self):
        src = self.tmp / "an.gif"
        fr = [Image.new("RGB", (40, 40), c) for c in ("red", "green", "blue")]
        fr[0].save(src, save_all=True, append_images=fr[1:], duration=100, loop=0)
        out = self.conv(src, "webp")[0]
        with Image.open(out) as im_out:
            self.assertEqual(im_out.n_frames, 3)

    def test_custom_output_folder(self):
        src = self.tmp / "a.png"; Image.new("RGB", (10, 10)).save(src)
        self.st.output_mode, self.st.output_folder = "folder", str(self.tmp / "out")
        out = self.conv(src, "bmp")[0]
        self.assertEqual(out.parent, self.tmp / "out")

    def test_errors(self):
        bad = self.tmp / "bad.png"; bad.write_bytes(b"not an image")
        with self.assertRaises(engine.ConversionError):
            self.conv(bad, "jpg")
        with self.assertRaises(engine.ConversionError):
            self.conv(self.tmp / "missing.png", "jpg")
        ok = self.tmp / "ok.png"; Image.new("RGB", (4, 4)).save(ok)
        with self.assertRaises(engine.ConversionError):
            self.conv(ok, "mp3")
        outs, errs = engine.convert_batch([bad, ok], "jpg", self.st)
        self.assertEqual(len(outs), 1); self.assertEqual(errs[0][0], "bad.png")


@unittest.skipUnless(HAS_FF, "ffmpeg/ffprobe not available")
class MediaTests(Base):
    def test_audio_pairs(self):
        src = self.tmp / "tone.wav"
        ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(src))
        for tf in engine.targets_for_format("wav"):
            out = self.conv(src, tf)[0]
            info = engine.probe(out)
            self.assertTrue(info["audio"], tf)
            self.assertAlmostEqual(info["duration"], 2, delta=0.3, msg=tf)
        mp3 = self.conv(src, "mp3")[0]
        for tf in ("flac", "ogg", "m4a", "aac", "wav"):
            self.assertTrue(engine.probe(self.conv(mp3, tf)[0])["audio"], tf)

    def test_video_pairs_and_progress(self):
        src = self.tmp / "v.mp4"
        ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2",
           "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
        seen = []
        for tf in engine.targets_for_format("mp4"):
            out = engine.convert(src, tf, self.st, seen.append)[0]
            info = engine.probe(out)
            if tf in ("mp3", "m4a", "wav", "aac"):
                self.assertTrue(info["audio"] and not info["video"], tf)
            else:
                self.assertTrue(info["video"], tf)
        self.assertTrue(seen and seen[-1] == 1.0)
        gif = self.tmp / "v.gif"
        for tf in ("mp4", "webm"):
            self.assertTrue(engine.probe(self.conv(gif if gif.exists() else self.conv(src, "gif")[0], tf)[0])["video"])

    def test_odd_dimensions(self):
        src = self.tmp / "odd.avi"
        ff("-f", "lavfi", "-i", "testsrc=size=321x241:rate=10:duration=1", "-c:v", "mpeg4", str(src))
        for tf in ("mp4", "webm", "mkv"):
            self.assertTrue(engine.probe(self.conv(src, tf)[0])["video"], tf)

    def test_no_audio_extraction_error(self):
        src = self.tmp / "silent.mp4"
        ff("-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1", "-pix_fmt", "yuv420p", str(src))
        with self.assertRaises(engine.ConversionError):
            self.conv(src, "mp3")

    def test_corrupt_media(self):
        bad = self.tmp / "bad.mp3"; bad.write_bytes(b"garbage" * 100)
        with self.assertRaises(engine.ConversionError):
            self.conv(bad, "wav")


class ArchiveTests(Base):
    def test_pairwise(self):
        d = self.tmp / "d"; d.mkdir(); (d / "a.txt").write_text("hello")
        (d / "sub").mkdir(); (d / "sub" / "b.txt").write_text("world")
        z = self.tmp / "pack.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(d / "a.txt", "a.txt"); zf.write(d / "sub" / "b.txt", "sub/b.txt")
        tgz = self.conv(z, "gz")[0]
        self.assertEqual(tgz.name, "pack.tar.gz")
        with tarfile.open(tgz) as t:
            self.assertEqual(sorted(m.name for m in t.getmembers() if m.isfile()), ["a.txt", "sub/b.txt"])
        tar = self.conv(tgz, "tar")[0]
        z2 = self.conv(tar, "zip")[0]
        with zipfile.ZipFile(z2) as zf:
            self.assertEqual(zf.read("sub/b.txt"), b"world")

    def test_zip_slip_rejected(self):
        z = self.tmp / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../escape.txt", "x")
        with self.assertRaises(engine.ConversionError):
            self.conv(z, "tar")


@unittest.skipUnless(HAS_PANDOC, "pandoc not available")
class DocTests(Base):
    def test_md_html_docx_txt(self):
        md = self.tmp / "n.md"; md.write_text("# Title\n\nHello **world**.\n")
        html = self.conv(md, "html")[0]
        self.assertIn("Hello", html.read_text(encoding="utf-8"))
        docx = self.conv(md, "docx")[0]
        self.assertTrue(zipfile.is_zipfile(docx))
        txt = self.conv(docx, "txt")[0]
        self.assertIn("Hello world", txt.read_text(encoding="utf-8"))
        back = self.conv(html, "md")[0]
        self.assertIn("Title", back.read_text(encoding="utf-8"))


class TextTests(Base):
    def test_txt_to_images_docx(self):
        t = self.tmp / "t.txt"; t.write_text("line one\n    indented\n" * 30, encoding="utf-8")
        for tf in ("png", "jpg"):
            with Image.open(self.conv(t, tf)[0]) as im:
                im.load()
                self.assertGreater(im.size[1], 300)
        docx = self.conv(t, "docx")[0]
        import docx as dx
        self.assertEqual(dx.Document(str(docx)).paragraphs[0].text, "line one")


@unittest.skipUnless(HAS_FITZ, "PyMuPDF not installed")
class PdfTests(Base):
    def make_pdf(self, pages=2):
        with fitz.open() as d:
            for i in range(pages):
                d.new_page(width=612, height=792).insert_text((72, 100), f"Hello page {i + 1}")
            p = self.tmp / "Report.pdf"
            d.save(p)
            return p

    def test_pdf_routes(self):
        p = self.make_pdf()
        txt = self.conv(p, "txt")[0].read_text(encoding="utf-8")
        self.assertIn("Hello page 2", txt)
        folder = self.conv(p, "png")[0]
        self.assertEqual(folder.name, "Report PNG Pages")
        with Image.open(folder / "Page 001.png") as im:
            self.assertEqual(im.size, (2550, 3300))
        self.assertTrue(zipfile.is_zipfile(self.conv(p, "docx")[0]))
        t = self.tmp / "t.txt"; t.write_text("alpha\nbeta\n")
        pdf = self.conv(t, "pdf")[0]
        with fitz.open(pdf) as doc:
            self.assertIn("alpha", doc[0].get_text())
        im = self.tmp / "i.png"; Image.new("RGB", (100, 100), "blue").save(im)
        with fitz.open(self.conv(im, "pdf")[0]) as doc:
            self.assertEqual(len(doc), 1)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._orig_appdata = os.environ.get("APPDATA")
        self.tmp = tempfile.mkdtemp()
        os.environ["APPDATA"] = self.tmp

    def tearDown(self):
        import shutil
        if self._orig_appdata is not None:
            os.environ["APPDATA"] = self._orig_appdata
        else:
            os.environ.pop("APPDATA", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validate_and_persist(self):
        self.assertEqual(S.validate(["SHIFT"], ["ALT", "SHIFT"])[0], [])
        self.assertTrue(S.validate(["SHIFT"], ["SHIFT"])[0])                  # identical
        self.assertTrue(S.validate([], ["SHIFT"])[0])                         # empty
        self.assertTrue(S.validate(["WIN"], ["SHIFT"])[0])                    # Start menu
        self.assertTrue(S.validate(["CTRL", "C"], ["SHIFT"])[0])              # reserved
        self.assertTrue(S.validate(["A"], ["SHIFT"])[0])                      # no modifier
        self.assertTrue(S.validate(["CTRL", "A", "B"], ["SHIFT"])[0])         # two extras
        self.assertEqual(S.validate(["CTRL", "SHIFT", "Q"], ["ALT", "Q"])[0], [])
        self.assertTrue(S.validate(["SHIFT"], ["ALT", "SHIFT"])[1])           # subset warning
        s = S.Settings(); s.conv_trigger = ["CTRL", "SHIFT"]; s.jpg_quality = 77; s.save()
        l = S.Settings.load()
        self.assertEqual((l.conv_trigger, l.jpg_quality), (["CTRL", "SHIFT"], 77))
        l.reset_triggers(); self.assertEqual(l.conv_trigger, ["SHIFT"]); self.assertEqual(l.tools_trigger, ["ALT", "SHIFT"])
        S.Settings.path().write_text("{broken")                                # corrupt file -> defaults
        self.assertEqual(S.Settings.load().conv_trigger, ["SHIFT"])


if __name__ == "__main__":
    unittest.main()
