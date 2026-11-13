"""Real file-conversion engine (FFmpeg, Pillow, PyMuPDF, python-docx, Pandoc, stdlib archives)."""
from __future__ import annotations
import gzip, html as _html, os, re, shutil, subprocess, sys, tarfile, tempfile, threading, zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

NOWIN = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW


class ConversionError(Exception):
    pass


class Cancelled(Exception):
    pass


Progress = Callable[[float], None]
_noop: Progress = lambda f: None


# ------------------------------------------------------------------ tools lookup
def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def find_tool(name: str) -> Optional[str]:
    exe = name + (".exe" if sys.platform == "win32" else "")
    for d in (app_dir() / "tools", Path(sys.executable).parent / "tools", app_dir()):
        p = d / exe
        if p.exists():
            return str(p)
    return shutil.which(name)


def need_tool(name: str) -> str:
    p = find_tool(name)
    if not p:
        raise ConversionError(f"Required tool '{name}' was not found (expected in the 'tools' folder).")
    return p


# ------------------------------------------------------------------ formats
ALIASES = {"jpeg": "jpg", "jpe": "jpg", "tif": "tiff", "htm": "html", "markdown": "md",
           "text": "txt", "log": "txt", "tgz": "gz", "heif": "heic", "oga": "ogg", "mpeg4": "mp4"}

IMAGE_IN = ["png", "jpg", "webp", "bmp", "tiff", "gif", "ico", "heic", "svg"]
IMAGE_OUT = ["jpg", "png", "webp", "bmp", "tiff", "gif", "ico", "pdf", "docx"]
AUDIO_IN = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma", "aiff"]
AUDIO_OUT = ["mp3", "wav", "flac", "aac", "ogg", "m4a"]
VIDEO_IN = ["mp4", "mkv", "mov", "avi", "webm", "m4v", "wmv", "flv"]
VIDEO_OUT = ["mp4", "mov", "mkv", "webm", "avi", "gif"]
ARCHIVES = ["zip", "tar", "gz", "7z"]
DOC_TARGETS = {
    "pdf": ["docx", "jpg", "png", "txt"],
    "txt": ["pdf", "docx", "jpg", "png", "html", "md"],
    "md": ["html", "docx", "pdf", "txt"],
    "html": ["md", "docx", "pdf", "txt"],
    "docx": ["pdf", "html", "md", "txt"],
}


def fmt_of(path) -> str:
    n = Path(path).name.lower()
    if n.endswith(".tar.gz"):
        return "gz"
    ext = n.rsplit(".", 1)[-1] if "." in n else ""
    return ALIASES.get(ext, ext)


def family(fmt: str) -> str:
    if fmt == "gif":
        return "gif"
    if fmt in IMAGE_IN:
        return "image"
    if fmt in AUDIO_IN:
        return "audio"
    if fmt in VIDEO_IN:
        return "video"
    if fmt in DOC_TARGETS:
        return "pdf" if fmt == "pdf" else "doc"
    if fmt in ARCHIVES:
        return "archive"
    return ""


def has_heif() -> bool:
    try:
        import pillow_heif  # noqa: F401
        return True
    except ImportError:
        return False


def targets_for_format(fmt: str) -> list[str]:
    fam = family(fmt)
    if fam == "image":
        t = [x for x in IMAGE_OUT if x != fmt]
        if has_heif() and fmt != "heic":
            t.append("heic")
        return t
    if fam == "gif":
        return [x for x in IMAGE_OUT if x != "gif"] + ["mp4", "mov", "mkv", "webm"]
    if fam == "audio":
        return [x for x in AUDIO_OUT if x != fmt]
    if fam == "video":
        return [x for x in VIDEO_OUT if x != fmt] + ["mp3", "m4a", "wav"]
    if fam in ("pdf", "doc"):
        return list(DOC_TARGETS[fmt])
    if fam == "archive":
        return [x for x in ARCHIVES if x != fmt and (x != "7z" or _has_py7zr())]
    return []


def common_targets(paths) -> list[str]:
    lists = [targets_for_format(fmt_of(p)) for p in paths]
    if not lists or any(not l for l in lists):
        return []
    # Mixed families (image + audio ...) share nothing; same family intersects.
    out = [t for t in lists[0] if all(t in l for l in lists[1:])]
    return out


def _has_py7zr() -> bool:
    try:
        import py7zr  # noqa: F401
        return True
    except ImportError:
        return False


# ------------------------------------------------------------------ output handling
def unique_name(directory: Path, name: str, overwrite: bool = False) -> Path:
    """'cat.jpg' -> 'cat 2.jpg' -> 'cat 3.jpg' ... (folders get 'Name 2')."""
    p = directory / name
    if overwrite or not p.exists():
        return p
    if name.lower().endswith(".tar.gz"):
        stem, ext = name[:-7], ".tar.gz"
    elif p.is_dir() or "." not in name:
        stem, ext = name, ""
    else:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    i = 2
    while (directory / f"{stem} {i}{ext}").exists():
        i += 1
    return directory / f"{stem} {i}{ext}"


class Workspace:
    """Hidden scratch folder beside the destination so the final move is a same-volume rename."""

    def __init__(self, settings, src: Path):
        self.settings = settings
        if settings.output_mode == "folder" and settings.output_folder:
            self.outdir = Path(settings.output_folder)
        else:
            self.outdir = Path(src).resolve().parent
        try:
            self.outdir.mkdir(parents=True, exist_ok=True)
            self.work = Path(tempfile.mkdtemp(prefix=".vitarg-", dir=self.outdir))
        except OSError as e:
            raise ConversionError(f"Cannot write to destination folder '{self.outdir}': {e.strerror or e}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.work, ignore_errors=True)

    def path(self, name: str) -> Path:
        return self.work / name

    def publish(self) -> list[Path]:
        results = []
        over = self.settings.overwrite == "overwrite"
        for item in sorted(self.work.iterdir()):
            final = unique_name(self.outdir, item.name, over)
            if over and final.exists():
                shutil.rmtree(final) if final.is_dir() else final.unlink()
            os.replace(item, final)
            if not final.exists():                       # confirm with a fresh read
                raise ConversionError(f"Could not confirm that '{final.name}' was saved.")
            results.append(final)
        if not results:
            raise ConversionError("Conversion produced no output.")
        return results


# ------------------------------------------------------------------ ffmpeg
_PROBE_CACHE: OrderedDict = OrderedDict()
_MAX_PROBE_CACHE = 500


def probe(path) -> dict:
    """Return {'duration': float, 'video': bool, 'audio': bool, 'width': int, 'height': int} using ffprobe with LRU caching."""
    p = Path(path)
    try:
        st = p.stat()
        cache_key = (str(p.resolve()), st.st_mtime, st.st_size)
        if cache_key in _PROBE_CACHE:
            _PROBE_CACHE.move_to_end(cache_key)
            return _PROBE_CACHE[cache_key].copy()
    except OSError:
        cache_key = None

    import json
    ffprobe = need_tool("ffprobe")
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                        "-of", "json", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    if r.returncode != 0:
        raise ConversionError(f"Unreadable media file: {r.stderr.strip()[-300:]}")
    d = json.loads(r.stdout or "{}")
    kinds = {s.get("codec_type") for s in d.get("streams", [])}
    try:
        dur = float(d.get("format", {}).get("duration") or 0)
    except ValueError:
        dur = 0.0

    w, h = 0, 0
    for s in d.get("streams", []):
        if s.get("codec_type") == "video":
            w = int(s.get("width") or 0)
            h = int(s.get("height") or 0)
            break

    res = {"duration": dur, "video": "video" in kinds, "audio": "audio" in kinds, "width": w, "height": h}
    if cache_key:
        _PROBE_CACHE[cache_key] = res
        if len(_PROBE_CACHE) > _MAX_PROBE_CACHE:
            _PROBE_CACHE.popitem(last=False)
    return res.copy()


def run_ffmpeg(args: list[str], duration: float = 0, progress: Progress = _noop,
               cancel: Optional[threading.Event] = None) -> None:
    cmd = [need_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", *args]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", creationflags=NOWIN)
    err: list[str] = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t.start()
    try:
        for line in p.stdout:
            if cancel is not None and cancel.is_set():
                p.kill()
                p.wait()
                raise Cancelled()
            if line.startswith(("out_time_us=", "out_time_ms=")) and duration > 0:
                try:
                    us = int(line.split("=")[1])
                    progress(max(0.0, min(0.99, us / 1e6 / duration)))
                except ValueError:
                    pass
        p.wait()
    finally:
        try:
            p.stdout.close()
        except Exception:
            pass
        try:
            p.stderr.close()
        except Exception:
            pass
    t.join(2)
    if p.returncode != 0:
        msg = (err[0] if err else "").strip()
        raise ConversionError("FFmpeg failed:\n" + (msg[-1500:] or f"exit code {p.returncode}"))


AUDIO_CODEC = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "aac": ["-c:a", "aac", "-b:a", "{abr}k", "-f", "adts"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "m4a": ["-c:a", "aac", "-b:a", "{abr}k", "-movflags", "+faststart"],
}
EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _video_args(target: str, crf: int) -> list[str]:
    x264 = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vf", EVEN]
    if target in ("mp4", "mov"):
        return x264 + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    if target == "mkv":
        return x264 + ["-c:a", "aac", "-b:a", "192k"]
    if target == "avi":
        return ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-vf", EVEN, "-c:a", "libmp3lame", "-q:a", "3"]
    if target == "webm":
        return ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p",
                "-c:a", "libopus", "-b:a", "128k"]
    raise ConversionError(f"Unsupported video target {target}")


def convert_media(src: Path, target: str, out: Path, settings, progress, cancel) -> None:
    info = probe(src)
    sf = fmt_of(src)
    if target in AUDIO_OUT:
        if not info["audio"]:
            raise ConversionError("The source has no audio stream to extract.")
        codec = [a.replace("{abr}", str(settings.audio_bitrate_k)) for a in AUDIO_CODEC[target]]
        args = ["-i", str(src), "-map", "0:a:0", "-vn", *codec, str(out)]
    elif target == "gif":
        if not info["video"]:
            raise ConversionError("The source has no video stream.")
        vf = "fps=15,scale='min(960,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"
        args = ["-i", str(src), "-an", "-vf", vf, "-loop", "0", str(out)]
    else:
        if not info["video"]:
            raise ConversionError("The source has no video stream.")
        args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *_video_args(target, settings.video_crf), str(out)]
    run_ffmpeg(args, info["duration"], progress, cancel)
    chk = probe(out)
    if target in AUDIO_OUT and not chk["audio"]:
        raise ConversionError("Validation failed: output has no audio stream.")
    if target not in AUDIO_OUT and not chk["video"]:
        raise ConversionError("Validation failed: output has no video stream.")
    if info["duration"] > 3 and sf != "gif" and chk["duration"] and abs(chk["duration"] - info["duration"]) > max(2, info["duration"] * 0.05):
        raise ConversionError(f"Validation failed: output duration {chk['duration']:.1f}s differs from source {info['duration']:.1f}s.")


# ------------------------------------------------------------------ images
def _fitz():
    try:
        import fitz
        return fitz
    except ImportError:
        try:
            import pymupdf as fitz
            return fitz
        except ImportError:
            raise ConversionError("PDF/SVG support needs the PyMuPDF library, which is not installed.")


def load_image(path):
    from PIL import Image, ImageOps
    path = Path(path)
    f = fmt_of(path)
    if f == "svg":
        fz = _fitz()
        data = path.read_bytes()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        doc = fz.open(stream=data, filetype="svg")
        pix = doc[0].get_pixmap(alpha=True)
        im = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        return im
    if f == "heic":
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise ConversionError("HEIC support needs pillow-heif, which is not installed.")
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        raise ConversionError(f"Cannot read image: {e}")
    return im


def _flatten(im, bg=(255, 255, 255)):
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.getchannel("A"))
        return base
    return im.convert("RGB")


def convert_image(src: Path, target: str, out: Path, settings) -> None:
    from PIL import Image, ImageOps
    im = load_image(src)
    n = getattr(im, "n_frames", 1)
    sf = fmt_of(src)
    animated_ok = target in ("gif", "webp", "tiff") and n > 1
    if not animated_ok:
        try:
            im.seek(0)
        except Exception:
            pass
    if target == "docx":
        _images_to_docx([im], out)
        return
    if animated_ok:
        frames, durs = [], []
        for i in range(n):
            im.seek(i)
            durs.append(im.info.get("duration", 100))
            fr = ImageOps.exif_transpose(im).convert("RGBA")
            frames.append(fr if target != "tiff" else _flatten(fr))
        kw = {"save_all": True, "append_images": frames[1:], "duration": durs, "loop": 0}
        if target == "gif":
            kw["disposal"] = 2
        if target == "webp":
            kw["quality"] = settings.webp_quality
        if target == "tiff":
            kw = {"save_all": True, "append_images": frames[1:], "compression": "tiff_lzw"}
        frames[0].save(out, target.upper() if target != "tiff" else "TIFF", **kw)
    else:
        im = ImageOps.exif_transpose(im)
        if target == "jpg":
            _flatten(im).save(out, "JPEG", quality=settings.jpg_quality, optimize=True, subsampling=0 if settings.jpg_quality >= 90 else 2)
        elif target == "png":
            (im if im.mode in ("RGB", "RGBA", "L", "LA", "P") else im.convert("RGBA")).save(out, "PNG", optimize=True)
        elif target == "webp":
            im.convert("RGBA").save(out, "WEBP", quality=settings.webp_quality, method=6)
        elif target == "bmp":
            _flatten(im).save(out, "BMP")
        elif target == "tiff":
            (im if im.mode in ("RGB", "RGBA", "L") else im.convert("RGBA")).save(out, "TIFF", compression="tiff_lzw")
        elif target == "gif":
            im.convert("RGBA").save(out, "GIF")
        elif target == "ico":
            ic = im.convert("RGBA")
            ic.thumbnail((256, 256))
            sizes = [s for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(ic.size)] or [ic.size[0]]
            ic.save(out, "ICO", sizes=[(s, s) for s in sizes])
        elif target == "pdf":
            _flatten(im).save(out, "PDF", resolution=float(im.info.get("dpi", (150, 150))[0] or 150))
        elif target == "heic":
            import pillow_heif
            pillow_heif.register_heif_opener()
            im.convert("RGBA").save(out, "HEIF", quality=90)
        else:
            raise ConversionError(f"Unsupported image target {target}")
    # validate by decoding again
    try:
        if target == "pdf":
            if out.stat().st_size < 100:
                raise ConversionError("Validation failed: PDF is empty.")
        elif target != "docx":
            chk = Image.open(out)
            chk.load()
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Validation failed: output image is unreadable ({e}).")


def _images_to_docx(images, out: Path) -> None:
    import io
    try:
        from docx import Document
        from docx.shared import Inches
    except ImportError:
        raise ConversionError("DOCX output needs python-docx, which is not installed.")
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Inches(0.75)
    maxw = (sec.page_width - sec.left_margin - sec.right_margin)
    maxh = (sec.page_height - sec.top_margin - sec.bottom_margin)
    for i, im in enumerate(images):
        buf = io.BytesIO()
        _flatten(im).save(buf, "PNG")
        buf.seek(0)
        ratio = im.size[0] / im.size[1]
        w = maxw if maxw / ratio <= maxh else int(maxh * ratio)
        doc.add_picture(buf, width=w)
        if i < len(images) - 1:
            doc.add_page_break()
    doc.save(out)


# ------------------------------------------------------------------ text / documents
def read_text(path: Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def text_to_image(text: str, out: Path, fmt: str, settings) -> None:
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for name in ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"):
        for d in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"):
            p = Path(d) / name
            if p.exists():
                font = ImageFont.truetype(str(p), 28)
                break
        if font:
            break
    font = font or ImageFont.load_default()
    cols = 100
    lines = []
    import textwrap
    for ln in text.expandtabs(4).splitlines() or [""]:
        lines.extend(textwrap.wrap(ln, cols, replace_whitespace=False, drop_whitespace=False) or [""])
    lh = int(font.size * 1.35) if hasattr(font, "size") else 14
    cw = int(font.getlength("M")) if hasattr(font, "getlength") else 8
    pad = 60
    w, h = cols * cw + pad * 2, min(len(lines) * lh + pad * 2, 60000)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        if pad + i * lh > h - pad:
            break
        d.text((pad, pad + i * lh), ln, fill="black", font=font)
    if fmt == "jpg":
        img.save(out, "JPEG", quality=settings.jpg_quality)
    else:
        img.save(out, "PNG", optimize=True)


def html_to_pdf(html_text: str, out: Path, archive_dir: Optional[Path] = None) -> None:
    fz = _fitz()
    story = fz.Story(html=html_text, archive=fz.Archive(str(archive_dir)) if archive_dir else None)
    writer = fz.DocumentWriter(str(out))
    media = fz.paper_rect("letter")
    where = media + (54, 54, -54, -54)
    more = 1
    while more:
        dev = writer.begin_page(media)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


def text_to_html(text: str) -> str:
    rows = []
    for ln in text.expandtabs(4).splitlines():
        ln = _html.escape(ln)
        ln = re.sub(r"^( +)", lambda m: "&nbsp;" * len(m.group(1)), ln)
        rows.append(f"<p style='margin:0'>{ln or '&nbsp;'}</p>")
    return ("<html><body style=\"font-family:monospace;font-size:10pt\">" + "".join(rows) + "</body></html>")


def pandoc(args: list[str], cwd=None) -> None:
    r = subprocess.run([need_tool("pandoc"), *args], capture_output=True, text=True, cwd=cwd,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    if r.returncode != 0:
        raise ConversionError("Pandoc failed:\n" + r.stderr.strip()[-1500:])


def pdf_to_text(src: Path) -> str:
    fz = _fitz()
    try:
        doc = fz.open(str(src))
    except Exception as e:
        raise ConversionError(f"Cannot open PDF: {e}")
    if doc.needs_pass:
        raise ConversionError("The PDF is password protected.")
    pages = [p.get_text("text") for p in doc]
    if not any(t.strip() for t in pages):
        raise ConversionError("This PDF has no selectable text (it looks scanned). OCR is required and not supported.")
    return "\n\n".join(pages)


def pdf_to_images(src: Path, fmt: str, ws: Workspace, settings, progress) -> None:
    from PIL import Image
    fz = _fitz()
    doc = fz.open(str(src))
    if doc.needs_pass:
        raise ConversionError("The PDF is password protected.")
    n = len(doc)
    if n == 0:
        raise ConversionError("The PDF has no pages.")
    target_dir = ws.work if n == 1 else ws.path(f"{src.stem} {fmt.upper()} Pages")
    if n > 1:
        target_dir.mkdir()
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=300, alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        name = f"{src.stem}.{fmt}" if n == 1 else f"Page {i + 1:03d}.{fmt}"
        if fmt == "jpg":
            im.save(target_dir / name, "JPEG", quality=settings.jpg_quality, dpi=(300, 300))
        else:
            im.save(target_dir / name, "PNG", optimize=True, dpi=(300, 300))
        progress((i + 1) / n)


def pdf_to_docx(src: Path, out: Path) -> None:
    import io
    fz = _fitz()
    from docx import Document
    from docx.shared import Inches
    doc = fz.open(str(src))
    if doc.needs_pass:
        raise ConversionError("The PDF is password protected.")
    d = Document()
    for i, page in enumerate(doc):
        txt = page.get_text("text").strip()
        if txt:
            for para in re.split(r"\n\s*\n", txt):
                d.add_paragraph(" ".join(para.split("\n")))
        else:
            pix = page.get_pixmap(dpi=150)
            d.add_picture(io.BytesIO(pix.tobytes("png")), width=Inches(6.5))
        if i < len(doc) - 1:
            d.add_page_break()
    d.save(out)


def convert_document(src: Path, sf: str, target: str, ws: Workspace, settings, progress) -> None:
    stem = src.stem
    out = ws.path(f"{stem}.{target}")
    if sf == "pdf":
        if target in ("jpg", "png"):
            return pdf_to_images(src, target, ws, settings, progress)
        if target == "txt":
            out.write_text(pdf_to_text(src), encoding="utf-8")
        elif target == "docx":
            pdf_to_docx(src, out)
        return
    if sf == "txt":
        text = read_text(src)
        if target == "pdf":
            html_to_pdf(text_to_html(text), out)
        elif target in ("jpg", "png"):
            text_to_image(text, out, target, settings)
        elif target == "docx":
            from docx import Document
            d = Document()
            for ln in text.splitlines():
                d.add_paragraph(ln)
            d.save(out)
        elif target == "html":
            out.write_text("<!doctype html><meta charset=utf-8><pre style='font-family:monospace;white-space:pre-wrap'>"
                           + _html.escape(text) + "</pre>", encoding="utf-8")
        elif target == "md":
            out.write_text(text, encoding="utf-8")
        return
    # md / html / docx via pandoc
    pf = {"md": "markdown", "html": "html", "docx": "docx"}[sf]
    if target == "pdf":
        media = ws.work / "_media"
        htmlf = ws.work / "_tmp.html"
        # relative paths + cwd=work so <img src> resolves against the Story archive (the work folder)
        args = [str(src), "-f", pf, "-t", "html", "--standalone", "-o", "_tmp.html"]
        if sf == "docx":
            args += ["--extract-media", "_media"]
        pandoc(args, cwd=str(ws.work))
        try:
            html_to_pdf(htmlf.read_text(encoding="utf-8"), out, ws.work)
        finally:
            htmlf.unlink(missing_ok=True)
            shutil.rmtree(media, ignore_errors=True)
        return
    tf = {"md": "gfm", "html": "html", "docx": "docx", "txt": "plain"}[target]
    args = [str(src), "-f", pf, "-t", tf, "-o", str(out)]
    if target == "html":
        args += ["--standalone", "--embed-resources"]
    if target in ("md", "txt"):
        args += ["--wrap=none"]
    pandoc(args)


# ------------------------------------------------------------------ archives
def safe_extract(src: Path, dest: Path) -> None:
    f = fmt_of(src)
    root = dest.resolve()

    def check(name):
        p = (dest / name).resolve()
        if root != p and root not in p.parents:
            raise ConversionError(f"Unsafe path in archive: {name}")
    if f == "zip":
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                check(n)
            z.extractall(dest)
    elif f == "tar" or (f == "gz" and src.name.lower().endswith((".tar.gz", ".tgz"))):
        with tarfile.open(src) as t:
            for m in t.getmembers():
                check(m.name)
                if m.issym() or m.islnk():
                    raise ConversionError(f"Links inside archives are not supported: {m.name}")
            t.extractall(dest)
    elif f == "gz":
        name = src.name[:-3] if src.name.lower().endswith(".gz") else src.stem
        with gzip.open(src, "rb") as gi, open(dest / name, "wb") as go:
            shutil.copyfileobj(gi, go)
    elif f == "7z":
        import py7zr
        with py7zr.SevenZipFile(src) as z:
            for n in z.getnames():
                check(n)
            z.extractall(dest)
    else:
        raise ConversionError(f"Cannot extract .{f}")


def pack(srcdir: Path, target: str, out: Path) -> None:
    items = sorted(srcdir.iterdir())
    if target == "zip":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for it in items:
                if it.is_dir():
                    z.write(it, it.name + "/")
                    for sub in sorted(it.rglob("*")):
                        z.write(sub, str(sub.relative_to(srcdir)) + ("/" if sub.is_dir() else ""))
                else:
                    z.write(it, it.name)
    elif target in ("tar", "gz"):
        with tarfile.open(out, "w:gz" if target == "gz" else "w") as t:
            for it in items:
                t.add(it, arcname=it.name)
    elif target == "7z":
        import py7zr
        with py7zr.SevenZipFile(out, "w") as z:
            for it in items:
                z.writeall(it, arcname=it.name)


def convert_archive(src: Path, sf: str, target: str, ws: Workspace) -> None:
    tmp = ws.path("_x")
    tmp.mkdir()
    safe_extract(src, tmp)
    stem = src.name[:-7] if src.name.lower().endswith(".tar.gz") else src.stem
    ext = "tar.gz" if target == "gz" else target
    pack(tmp, target, ws.path(f"{stem}.{ext}"))
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ public API
def convert(src, target: str, settings, progress: Progress = _noop,
            cancel: Optional[threading.Event] = None,
            custom_name: str = "", index: int = 1) -> list[Path]:
    src = Path(src)
    if not src.is_file():
        raise ConversionError(f"Source file not found: {src}")
    sf = fmt_of(src)
    if target not in targets_for_format(sf):
        raise ConversionError(f"Unsupported conversion: {sf.upper() or 'unknown'} → {target.upper()}")
    fam = family(sf)
    with Workspace(settings, src) as ws:
        ext = "tar.gz" if target == "gz" else target
        out = ws.path(f"{src.stem if not src.name.lower().endswith('.tar.gz') else src.name[:-7]}.{ext}")
        if fam in ("audio", "video") or (fam == "gif" and target in ("mp4", "mov", "mkv", "webm")):
            convert_media(src, target, out, settings, progress, cancel)
        elif fam in ("image", "gif"):
            convert_image(src, target, out, settings)
        elif fam in ("pdf", "doc"):
            convert_document(src, sf, target, ws, settings, progress)
        elif fam == "archive":
            convert_archive(src, sf, target, ws)
        else:
            raise ConversionError(f"Unsupported source format: .{sf}")
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        progress(1.0)
        published = ws.publish()
        if custom_name and custom_name.strip():
            from .rename import apply_custom_rename
            published = [Path(p) for p in apply_custom_rename([str(p) for p in published], custom_name, start_index=index)]
        return published


def convert_batch(sources, target: str, settings, progress: Progress = _noop,
                  cancel: Optional[threading.Event] = None,
                  custom_name: str = ""):
    """Convert several files. Returns (outputs, errors[(source, message)])."""
    outs, errs = [], []
    n = len(sources)
    for i, s in enumerate(sources):
        try:
            outs += convert(s, target, settings, lambda f, i=i: progress((i + f) / n), cancel,
                            custom_name=custom_name, index=i+1)
        except Cancelled:
            raise
        except ConversionError as e:
            errs.append((Path(s).name, str(e)))
        except Exception as e:  # unexpected: still report with the file name
            errs.append((Path(s).name, f"{type(e).__name__}: {e}"))
        progress((i + 1) / n)
    return outs, errs
