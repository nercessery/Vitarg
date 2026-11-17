"""File tools for the second ('tools') wheel. Every tool does real work and never modifies the source."""
from __future__ import annotations
import math, shutil, threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import engine
from .engine import ConversionError, Cancelled, Workspace, fmt_of, family, run_ffmpeg, probe, need_tool

_noop = lambda f: None


@dataclass
class Tool:
    id: str
    label: str
    families: tuple            # source families this tool applies to
    multi: bool = False        # True: needs 2+ files and makes ONE combined result
    batch_ok: bool = True      # False: offered for a single file only
    form: list = field(default_factory=list)   # option form (None-> no dialog)
    custom: str = ""           # name of a custom dialog ("crop")


CHOICE, FLOAT, INT, COLOR = "choice", "float", "int", "color"
TOOLS = [
    Tool("compress", "COMPRESS", ("image", "audio", "video", "pdf"), form=[
        {"key": "preset", "label": "Compression", "kind": CHOICE, "choices": ["Balanced", "Strong"], "default": "Balanced"},
        {"key": "max_edge", "label": "Longest edge (images)", "kind": CHOICE,
         "choices": ["Original", "2560", "1920", "1280"], "default": "Original"}]),
    Tool("metadata", "METADATA", ("image", "audio", "video", "pdf")),            # remove all metadata
    Tool("edit", "EDIT", ("image",), batch_ok=False, form=[
        {"key": "brightness", "label": "Brightness", "kind": FLOAT, "min": 0.2, "max": 2.0, "default": 1.0},
        {"key": "contrast", "label": "Contrast", "kind": FLOAT, "min": 0.2, "max": 2.0, "default": 1.0},
        {"key": "saturation", "label": "Saturation", "kind": FLOAT, "min": 0.0, "max": 2.0, "default": 1.0},
        {"key": "sharpness", "label": "Sharpness", "kind": FLOAT, "min": 0.0, "max": 3.0, "default": 1.0}]),
    Tool("crop", "CROP", ("image",), batch_ok=False, custom="crop"),
    Tool("addbg", "ADD BG", ("image",), form=[
        {"key": "color", "label": "Background color", "kind": COLOR, "default": "#FFFFFF"},
        {"key": "padding", "label": "Padding (% of size)", "kind": FLOAT, "min": 0, "max": 50, "default": 8.0}]),
    Tool("normalize", "NORMALIZE", ("audio",)),
    Tool("trim", "TRIM", ("audio", "video"), batch_ok=False, form=[
        {"key": "start", "label": "Start (seconds)", "kind": FLOAT, "min": 0, "max": 86400, "default": 0.0},
        {"key": "end", "label": "End (seconds, 0 = end)", "kind": FLOAT, "min": 0, "max": 86400, "default": 0.0}]),
    Tool("remove_audio", "REMOVE AUDIO", ("video",)),
    Tool("speed", "SPEED", ("video",), batch_ok=False, form=[
        {"key": "factor", "label": "Speed factor", "kind": FLOAT, "min": 0.25, "max": 4.0, "default": 2.0}]),
    Tool("snapshot", "SNAPSHOT", ("video",), batch_ok=False, form=[
        {"key": "time", "label": "Time (seconds)", "kind": FLOAT, "min": 0, "max": 86400, "default": 0.0}]),
    Tool("split_pdf", "SPLIT", ("pdf",), batch_ok=False),
    Tool("resize", "RESIZE", ("image", "video", "pdf"), form=[
        {"key": "mode", "label": "Mode", "kind": CHOICE, "choices": ["Scale %", "Exact pixels"], "default": "Scale %"},
        {"key": "scale", "label": "Scale (%)", "kind": INT, "min": 10, "max": 800, "default": 100},
        {"key": "width", "label": "Width (px, 0 = auto)", "kind": INT, "min": 0, "max": 15360, "default": 0},
        {"key": "height", "label": "Height (px, 0 = auto)", "kind": INT, "min": 0, "max": 8640, "default": 0}]),
    Tool("target_compress", "TARGET SIZE", ("video",), form=[
        {"key": "preset", "label": "Target size", "kind": CHOICE,
         "choices": ["25 MB", "50 MB", "10 MB", "8 MB", "Custom MB"], "default": "25 MB"},
        {"key": "custom_mb", "label": "Custom size (MB)", "kind": INT, "min": 1, "max": 2000, "default": 25}]),
    Tool("volume", "VOLUME BOOST", ("audio", "video"), form=[
        {"key": "volume", "label": "Volume boost %", "kind": INT, "min": 10, "max": 600, "default": 150},
        {"key": "preset", "label": "Equalizer preset", "kind": CHOICE,
         "choices": ["Flat", "Bass Boost (+8dB)", "Ultra Bass (+14dB)", "Vocal Boost", "Treble Boost", "Loudness & Clarity"], "default": "Flat"}]),
    Tool("eq", "AUDIO EQUALIZER", ("audio", "video"), form=[
        {"key": "preset", "label": "Equalizer preset", "kind": CHOICE,
         "choices": ["Bass Boost (+8dB)", "Ultra Bass (+14dB)", "Vocal Boost", "Treble Boost", "Loudness & Clarity", "Flat"], "default": "Bass Boost (+8dB)"},
        {"key": "volume", "label": "Volume boost %", "kind": INT, "min": 10, "max": 600, "default": 100}]),
    Tool("extract_text", "EXTRACT TEXT", ("pdf", "image"), form=[
        {"key": "target", "label": "Output destination", "kind": CHOICE,
         "choices": [".txt File", "Copy to Clipboard", "Both"], "default": ".txt File"}]),
    Tool("extract", "EXTRACT", ("archive",)),
    Tool("merge_pdf", "MERGE PDF", ("pdf",), multi=True, custom="pdf_organizer"),
    Tool("create_pdf", "CREATE PDF", ("image",), multi=True, custom="pdf_organizer"),
    Tool("collage", "COLLAGE", ("image",), multi=True, form=[
        {"key": "cols", "label": "Columns", "kind": INT, "min": 1, "max": 8, "default": 2},
        {"key": "spacing", "label": "Spacing (px)", "kind": INT, "min": 0, "max": 100, "default": 16},
        {"key": "bg", "label": "Background", "kind": COLOR, "default": "#FFFFFF"}]),
    Tool("join", "JOIN VIDEOS", ("video",), multi=True),
    Tool("inspect", "INSPECTOR", ("image", "audio", "video", "pdf", "archive", "document", "doc"), batch_ok=False, custom="inspect"),
]
BY_ID = {t.id: t for t in TOOLS}


def tools_for(paths) -> list[Tool]:
    fams = {family(fmt_of(p)) for p in paths}
    fams = {("image" if f == "gif" else f) for f in fams}
    if len(fams) != 1 or "" in fams:
        return []
    fam = next(iter(fams))
    n = len(paths)
    out = []
    for t in TOOLS:
        if fam not in t.families:
            continue
        if t.multi and n < 2:
            continue
        if not t.multi and n > 1 and not t.batch_ok:
            continue
        out.append(t)
    return out


# ------------------------------------------------------------------ helpers
def _out(ws: Workspace, src: Path, suffix: str, ext: Optional[str] = None) -> Path:
    e = ext or src.suffix.lstrip(".")
    return ws.path(f"{src.stem} {suffix}.{e}")


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _single_frame(im, path):
    if getattr(im, "n_frames", 1) > 1:
        try:
            im.close()
        except Exception:
            pass
        raise ConversionError("Animated/multi-page images are not supported by this tool.")


# ------------------------------------------------------------------ image
def _save_same(im, out: Path, fmt: str, quality=92):
    from PIL import Image
    if fmt == "jpg":
        engine._flatten(im).save(out, "JPEG", quality=quality, optimize=True)
    elif fmt == "png":
        im.save(out, "PNG", optimize=True)
    elif fmt == "webp":
        im.save(out, "WEBP", quality=quality, method=6)
    elif fmt == "tiff":
        im.save(out, "TIFF", compression="tiff_lzw")
    elif fmt == "bmp":
        engine._flatten(im).save(out, "BMP")
    elif fmt == "gif":
        im.save(out, "GIF")
    else:
        raise ConversionError(f"This tool supports JPG, PNG, WebP, TIFF and BMP images, not .{fmt}.")


def compress_image(src: Path, ws: Workspace, p: dict, settings) -> Path:
    from PIL import Image, ImageOps
    fmt = fmt_of(src)
    if fmt not in ("jpg", "png", "webp", "tiff"):
        raise ConversionError(f"Compress supports JPG, PNG, WebP and TIFF images, not .{fmt}.")
    strong = p.get("preset") == "Strong"
    target = 0.5 if strong else 0.8                    # fraction of original size
    orig = src.stat().st_size
    raw = engine.load_image(src)
    try:
        _single_frame(raw, src)
        im = ImageOps.exif_transpose(raw)
        edge = p.get("max_edge", "Original")
        if edge != "Original" and max(im.size) > int(edge):
            im.thumbnail((int(edge), int(edge)), Image.LANCZOS)
        out = _out(ws, src, "Compressed")
        tmp = ws.path("_c." + fmt)
        if fmt in ("jpg", "webp"):
            for q in range(88, (29 if strong else 39), -6):
                _save_same(im, tmp, fmt, q)
                if tmp.stat().st_size <= orig * target:
                    break
            if tmp.exists():
                shutil.copyfile(tmp, out)
        elif fmt == "png":
            _save_same(im, out, "png")
            if out.stat().st_size > orig * target and strong and im.mode in ("RGB", "RGBA"):
                q = im.quantize(256, method=Image.FASTOCTREE if im.mode == "RGBA" else Image.MEDIANCUT)
                q.save(tmp, "PNG", optimize=True)
                if tmp.stat().st_size < out.stat().st_size:
                    shutil.copyfile(tmp, out)
        else:
            _save_same(im, out, "tiff")
        tmp.unlink(missing_ok=True)
        if out.stat().st_size >= orig:                      # never make it bigger
            shutil.copyfile(src, out)
        return out
    finally:
        try:
            raw.close()
        except Exception:
            pass
        if "im" in locals() and im is not raw:
            try:
                im.close()
            except Exception:
                pass


def strip_image(src: Path, ws: Workspace) -> Path:
    from PIL import Image, ImageOps
    fmt = fmt_of(src)
    raw = engine.load_image(src)
    try:
        _single_frame(raw, src)
        icc = raw.info.get("icc_profile")
        im = ImageOps.exif_transpose(raw)
        clean = Image.new(im.mode, im.size)
        clean.putdata(list(im.getdata())) if im.mode != "P" else clean.paste(im)
        if im.mode == "P":
            clean.putpalette(im.getpalette())
        out = _out(ws, src, "No Metadata")
        if fmt == "jpg":
            clean.save(out, "JPEG", quality=95, optimize=True, icc_profile=icc)
        elif fmt == "png":
            clean.save(out, "PNG", optimize=True, icc_profile=icc)
        elif fmt == "webp":
            clean.save(out, "WEBP", lossless=True, icc_profile=icc)
        elif fmt == "tiff":
            clean.save(out, "TIFF", compression="tiff_lzw", icc_profile=icc)
        else:
            raise ConversionError(f"Metadata removal supports JPG, PNG, WebP and TIFF, not .{fmt}.")
        return out
    finally:
        try:
            raw.close()
        except Exception:
            pass
        if "im" in locals() and im is not raw:
            try:
                im.close()
            except Exception:
                pass
        if "clean" in locals():
            try:
                clean.close()
            except Exception:
                pass


def crop_image(src: Path, ws: Workspace, box, settings) -> Path:
    from PIL import ImageOps
    raw = engine.load_image(src)
    try:
        _single_frame(raw, src)
        im = ImageOps.exif_transpose(raw)
        l, t, r, b = [int(round(v)) for v in box]
        if r - l < 1 or b - t < 1 or l < 0 or t < 0 or r > im.width or b > im.height:
            raise ConversionError("Invalid crop rectangle.")
        out = _out(ws, src, "Cropped")
        _save_same(im.crop((l, t, r, b)), out, fmt_of(src), settings.jpg_quality)
        return out
    finally:
        try:
            raw.close()
        except Exception:
            pass
        if "im" in locals() and im is not raw:
            try:
                im.close()
            except Exception:
                pass


def apply_edit(im, p: dict):
    """Brightness / contrast / saturation / sharpness. Used by the live preview AND the saved file."""
    from PIL import ImageEnhance
    alpha = im.getchannel("A") if im.mode in ("RGBA", "LA") else None
    rgb = im.convert("RGB")
    for cls, key in ((ImageEnhance.Brightness, "brightness"), (ImageEnhance.Contrast, "contrast"),
                     (ImageEnhance.Color, "saturation"), (ImageEnhance.Sharpness, "sharpness")):
        rgb = cls(rgb).enhance(float(p.get(key, 1.0)))
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def apply_bg(im, p: dict):
    """Place the image on a solid background layer, optionally with padding. Returns RGB."""
    from PIL import Image
    im = im.convert("RGBA")
    pad = int(max(im.size) * max(0.0, float(p.get("padding", 0))) / 100.0)
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), _hex(p.get("color", "#FFFFFF")) + (255,))
    canvas.alpha_composite(im, (pad, pad))
    return canvas.convert("RGB")


def preview_image(tool_id: str, im, p: dict):
    """Render the dialog preview (im is a small RGBA copy)."""
    return apply_edit(im, p) if tool_id == "edit" else apply_bg(im, p)


def edit_image(src: Path, ws: Workspace, p: dict, settings) -> Path:
    from PIL import ImageOps
    raw = engine.load_image(src)
    try:
        _single_frame(raw, src)
        im = ImageOps.exif_transpose(raw)
        out = _out(ws, src, "Edited")
        _save_same(apply_edit(im, p), out, fmt_of(src), settings.jpg_quality)
        return out
    finally:
        try:
            raw.close()
        except Exception:
            pass
        if "im" in locals() and im is not raw:
            try:
                im.close()
            except Exception:
                pass


def add_background(src: Path, ws: Workspace, p: dict, settings) -> Path:
    from PIL import ImageOps
    raw = engine.load_image(src)
    try:
        _single_frame(raw, src)
        im = ImageOps.exif_transpose(raw)
        fmt = fmt_of(src)
        out = _out(ws, src, "With Background", "jpg" if fmt == "jpg" else "png")
        _save_same(apply_bg(im, p), out, "jpg" if fmt == "jpg" else "png", settings.jpg_quality)
        return out
    finally:
        try:
            raw.close()
        except Exception:
            pass
        if "im" in locals() and im is not raw:
            try:
                im.close()
            except Exception:
                pass


def build_collage(ims, p: dict, cell: int = 800):
    from PIL import Image, ImageOps
    cols = max(1, int(p.get("cols", 2)))
    gap = int(int(p.get("spacing", 16)) * cell / 800)
    bg = _hex(p.get("bg", "#FFFFFF"))
    rows = -(-len(ims) // cols)
    canvas = Image.new("RGB", (cols * cell + (cols + 1) * gap, rows * cell + (rows + 1) * gap), bg)
    for i, im in enumerate(ims):
        im = ImageOps.contain(im.convert("RGBA"), (cell, cell))
        x = gap + (i % cols) * (cell + gap) + (cell - im.width) // 2
        y = gap + (i // cols) * (cell + gap) + (cell - im.height) // 2
        canvas.paste(im, (x, y), im)
    return canvas


def collage(srcs, ws: Workspace, p: dict) -> Path:
    from PIL import ImageOps
    raws = []
    try:
        ims = []
        for s in srcs:
            raw = engine.load_image(s)
            raws.append(raw)
            ims.append(ImageOps.exif_transpose(raw).convert("RGBA"))
        out = ws.path("Photo Collage.png")
        build_collage(ims, p, 800).save(out, "PNG", optimize=True)
        return out
    finally:
        for r in raws:
            try:
                r.close()
            except Exception:
                pass


def images_to_pdf(srcs, ws: Workspace) -> Path:
    if not srcs:
        raise ConversionError("No files selected to convert.")
    from PIL import ImageOps
    raws = []
    try:
        ims = []
        for s in srcs:
            raw = engine.load_image(s)
            raws.append(raw)
            ims.append(engine._flatten(ImageOps.exif_transpose(raw)))
        out = ws.path("Images.pdf")
        ims[0].save(out, "PDF", save_all=True, append_images=ims[1:], resolution=150.0)
        return out
    finally:
        for r in raws:
            try:
                r.close()
            except Exception:
                pass


# ------------------------------------------------------------------ media
def _opt(args, info, src, out, progress, cancel):
    run_ffmpeg(args, info["duration"], progress, cancel)


def compress_media(src: Path, ws: Workspace, p: dict, progress, cancel) -> Path:
    fmt, info = fmt_of(src), probe(src)
    strong = p.get("preset") == "Strong"
    out = _out(ws, src, "Compressed")
    if family(fmt) == "video":
        vf = ["-vf", "scale=-2:'min(1080,ih)'"] if strong else ["-vf", engine.EVEN]
        args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "medium",
                "-crf", "30" if strong else "26", "-pix_fmt", "yuv420p", *vf, "-c:a", "aac", "-b:a", "128k"]
        if fmt in ("mp4", "mov", "m4v"):
            args += ["-movflags", "+faststart"]
        if fmt in ("avi", "webm", "wmv", "flv"):
            out = _out(ws, src, "Compressed", "mp4")
        run_ffmpeg(args + [str(out)], info["duration"], progress, cancel)
    else:
        br = "96k" if strong else "128k"
        codec = {"mp3": ["-c:a", "libmp3lame", "-b:a", br], "m4a": ["-c:a", "aac", "-b:a", br],
                 "aac": ["-c:a", "aac", "-b:a", br, "-f", "adts"], "ogg": ["-c:a", "libvorbis", "-b:a", br],
                 "flac": ["-c:a", "flac", "-compression_level", "12"]}.get(fmt)
        if not codec:
            raise ConversionError(f".{fmt} cannot be compressed in place. Convert it to FLAC, MP3 or M4A instead.")
        run_ffmpeg(["-i", str(src), "-map", "0:a:0", "-vn", *codec, str(out)], info["duration"], progress, cancel)
    if out.stat().st_size >= src.stat().st_size and out.suffix == src.suffix:
        shutil.copyfile(src, out)
    return out


def strip_media(src: Path, ws: Workspace, progress, cancel) -> Path:
    out = _out(ws, src, "No Metadata")
    info = probe(src)
    run_ffmpeg(["-i", str(src), "-map", "0", "-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy",
                "-fflags", "+bitexact", "-flags:a", "+bitexact", "-flags:v", "+bitexact", str(out)],
               info["duration"], progress, cancel)
    return out


def remove_audio(src: Path, ws: Workspace, progress, cancel) -> Path:
    out = _out(ws, src, "No Audio")
    run_ffmpeg(["-i", str(src), "-map", "0:v", "-an", "-c:v", "copy", str(out)], probe(src)["duration"], progress, cancel)
    return out


def normalize_audio(src: Path, ws: Workspace, progress, cancel) -> Path:
    fmt = fmt_of(src)
    codec = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "m4a": ["-c:a", "aac", "-b:a", "192k"],
             "aac": ["-c:a", "aac", "-b:a", "192k", "-f", "adts"], "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
             "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"]}.get(fmt)
    if not codec:
        raise ConversionError(f"Normalize does not support .{fmt}.")
    out = _out(ws, src, "Normalized")
    run_ffmpeg(["-i", str(src), "-map", "0:a:0", "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *codec, str(out)],
               probe(src)["duration"], progress, cancel)
    return out


def trim_media(src: Path, ws: Workspace, p: dict, progress, cancel) -> Path:
    info = probe(src)
    s, e = float(p.get("start", 0)), float(p.get("end", 0)) or info["duration"]
    if s < 0 or e <= s or s >= info["duration"]:
        raise ConversionError("Invalid trim range: the end must be after the start and inside the file.")
    fmt = fmt_of(src)
    out = _out(ws, src, "Trimmed")
    if family(fmt) == "video":
        args = ["-ss", str(s), "-to", str(e), "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                "-crf", "20", "-pix_fmt", "yuv420p", "-vf", engine.EVEN, "-c:a", "aac", "-b:a", "192k"]
    else:
        codec = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "m4a": ["-c:a", "aac", "-b:a", "192k"],
                 "aac": ["-c:a", "aac", "-b:a", "192k", "-f", "adts"], "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
                 "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"]}.get(fmt, ["-c:a", "pcm_s16le"])
        args = ["-ss", str(s), "-to", str(e), "-i", str(src), "-map", "0:a:0", "-vn", *codec]
    run_ffmpeg(args + [str(out)], e - s, progress, cancel)
    return out


def speed_video(src: Path, ws: Workspace, p: dict, progress, cancel) -> Path:
    f = float(p.get("factor", 2.0))
    if not 0.25 <= f <= 4:
        raise ConversionError("Speed must be between 0.25x and 4x.")
    info = probe(src)
    chain, x = [], f
    while x > 2.0:
        chain.append("atempo=2.0"); x /= 2
    while x < 0.5:
        chain.append("atempo=0.5"); x /= 0.5
    chain.append(f"atempo={x:.4f}")
    out = _out(ws, src, f"{f:g}x")
    args = ["-i", str(src), "-filter_complex", f"[0:v]setpts=PTS/{f},{engine.EVEN}[v];[0:a]{','.join(chain)}[a]" if info["audio"]
            else f"[0:v]setpts=PTS/{f},{engine.EVEN}[v]", "-map", "[v]"]
    if info["audio"]:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(out)]
    run_ffmpeg(args, info["duration"] / f, progress, cancel)
    return out


def snapshot(src: Path, ws: Workspace, p: dict, progress, cancel) -> Path:
    t = float(p.get("time", 0))
    info = probe(src)
    if t < 0 or t > info["duration"]:
        raise ConversionError("Snapshot time is outside the video.")
    out = _out(ws, src, f"Snapshot {t:g}s", "png")
    run_ffmpeg(["-ss", str(t), "-i", str(src), "-frames:v", "1", str(out)], 0, progress, cancel)
    if not out.exists():
        raise ConversionError("No frame could be extracted at that time.")
    return out


def join_videos(srcs, ws: Workspace, progress, cancel) -> Path:
    infos = [probe(s) for s in srcs]
    st_w = infos[0].get("width") or 1920
    st_h = infos[0].get("height") or 1080
    scale = min(1.0, 1920 / max(st_w, st_h))
    W, H = int(st_w * scale) // 2 * 2, int(st_h * scale) // 2 * 2
    args, parts, ins = [], [], []
    for i, (s, inf) in enumerate(zip(srcs, infos)):
        args += ["-i", str(s)]
        parts.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}]")
        if inf["audio"]:
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={max(inf['duration'], 0.1)}[a{i}]")
        ins.append(f"[v{i}][a{i}]")
    parts.append("".join(ins) + f"concat=n={len(srcs)}:v=1:a=1[v][a]")
    out = ws.path("Joined Video.mp4")
    run_ffmpeg([*args, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
               sum(i["duration"] for i in infos), progress, cancel)
    return out


# ------------------------------------------------------------------ pdf / archive
def pdf_compress(src: Path, ws: Workspace) -> Path:
    fz = engine._fitz()
    with fz.open(str(src)) as doc:
        if doc.needs_pass:
            raise ConversionError("The PDF is password protected.")
        out = _out(ws, src, "Compressed")
        doc.save(str(out), garbage=4, deflate=True, clean=True)
        if out.stat().st_size >= src.stat().st_size:
            shutil.copyfile(src, out)
        return out


def pdf_strip(src: Path, ws: Workspace) -> Path:
    fz = engine._fitz()
    with fz.open(str(src)) as doc:
        if doc.needs_pass:
            raise ConversionError("The PDF is password protected.")
        doc.set_metadata({})
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
        out = _out(ws, src, "No Metadata")
        doc.save(str(out), garbage=3, deflate=True)
        return out


def pdf_split(src: Path, ws: Workspace) -> Path:
    fz = engine._fitz()
    with fz.open(str(src)) as doc:
        if doc.needs_pass:
            raise ConversionError("The PDF is password protected.")
        folder = ws.path(f"{src.stem} Pages")
        folder.mkdir()
        for i in range(len(doc)):
            with fz.open() as part:
                part.insert_pdf(doc, from_page=i, to_page=i)
                part.save(str(folder / f"Page {i + 1:03d}.pdf"))
        return folder


def pdf_merge(srcs, ws: Workspace) -> Path:
    if not srcs:
        raise ConversionError("No files selected to merge.")
    fz = engine._fitz()
    with fz.open() as merged:
        for s in srcs:
            with fz.open(str(s)) as d:
                if d.needs_pass:
                    raise ConversionError(f"{Path(s).name} is password protected.")
                merged.insert_pdf(d)
        out = ws.path("Merged.pdf")
        merged.save(str(out), garbage=3, deflate=True)
        return out


def extract_archive(src: Path, ws: Workspace) -> Path:
    stem = src.name[:-7] if src.name.lower().endswith(".tar.gz") else src.stem
    folder = ws.path(stem)
    folder.mkdir()
    engine.safe_extract(src, folder)
    return folder


# ------------------------------------------------------------------ resize (scale / resolution change)
def _resolve_resize(p: dict, orig_w: int, orig_h: int) -> tuple[int, int]:
    """Compute target (w, h) from the resize form parameters."""
    mode = p.get("mode", "Scale %")
    if mode == "Scale %":
        s = max(10, min(800, int(p.get("scale", 100)))) / 100.0
        w, h = int(round(orig_w * s)), int(round(orig_h * s))
    else:
        w = int(p.get("width", 0))
        h = int(p.get("height", 0))
        if w <= 0 and h <= 0:
            w, h = orig_w, orig_h
        elif w <= 0:
            w = int(round(orig_w * h / orig_h))
        elif h <= 0:
            h = int(round(orig_h * w / orig_w))
    return max(1, w), max(1, h)


def resize_image(src: Path, ws: Workspace, p: dict, settings) -> Path:
    from PIL import Image, ImageOps
    raw = engine.load_image(src)
    try:
        n = getattr(raw, "n_frames", 1)
        fmt = fmt_of(src)
        tw, th = _resolve_resize(p, raw.width, raw.height)
        suffix = f"{tw}x{th}"
        out = _out(ws, src, suffix)

        if n > 1 and fmt in ("gif", "webp"):
            frames, durs = [], []
            for i in range(n):
                raw.seek(i)
                durs.append(raw.info.get("duration", 100))
                fr = ImageOps.exif_transpose(raw).convert("RGBA")
                frames.append(fr.resize((tw, th), Image.LANCZOS))
            kw = {"save_all": True, "append_images": frames[1:], "duration": durs, "loop": 0}
            if fmt == "gif":
                kw["disposal"] = 2
            frames[0].save(out, fmt.upper(), **kw)
        else:
            im = ImageOps.exif_transpose(raw)
            resized = im.resize((tw, th), Image.LANCZOS)
            _save_same(resized, out, fmt, settings.jpg_quality)
        return out
    finally:
        try:
            raw.close()
        except Exception:
            pass


def resize_video(src: Path, ws: Workspace, p: dict, progress, cancel) -> Path:
    info = probe(src)
    if not info["video"]:
        raise ConversionError("The source has no video stream.")
    ow = info.get("width") or 1920
    oh = info.get("height") or 1080
    tw, th = _resolve_resize(p, ow, oh)
    tw, th = tw // 2 * 2, th // 2 * 2
    tw, th = max(2, tw), max(2, th)
    suffix = f"{tw}x{th}"
    out = _out(ws, src, suffix)
    vf = f"scale={tw}:{th}:flags=lanczos"
    args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-vf", vf,
            "-c:a", "aac", "-b:a", "192k"]
    fmt = fmt_of(src)
    if fmt in ("mp4", "mov", "m4v"):
        args += ["-movflags", "+faststart"]
    run_ffmpeg(args + [str(out)], info["duration"], progress, cancel)
    return out


def resize_pdf(src: Path, ws: Workspace, p: dict) -> Path:
    """Re-render every page of a PDF at a different resolution (scale % or exact width/height)."""
    fz = engine._fitz()
    with fz.open(str(src)) as doc:
        if doc.needs_pass:
            raise ConversionError("The PDF is password protected.")
        if len(doc) == 0:
            raise ConversionError("The PDF has no pages.")

        first_page = doc[0]
        pw, ph = first_page.rect.width, first_page.rect.height
        mode = p.get("mode", "Scale %")
        if mode == "Scale %":
            scale_pct = max(10, min(800, int(p.get("scale", 100))))
            zoom = scale_pct / 100.0
            suffix = f"{scale_pct}pct"
        else:
            tw, th = _resolve_resize(p, int(pw), int(ph))
            zoom = tw / pw if pw > 0 else 1.0
            suffix = f"{tw}x{th}"

        dpi = max(36, min(600, int(round(72 * zoom))))
        with fz.open() as new_doc:
            for page in doc:
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                img_rect = fz.Rect(0, 0, page.rect.width, page.rect.height)
                new_page = new_doc.new_page(width=img_rect.width, height=img_rect.height)
                new_page.insert_image(img_rect, stream=pix.tobytes("png"))
            out = _out(ws, src, suffix, "pdf")
            new_doc.save(str(out), garbage=4, deflate=True)
        return out


def target_compress_video(src: Path, ws: Workspace, params: dict, progress, cancel) -> Path:
    info = probe(src)
    dur = float(info.get("duration") or 0)
    if dur <= 0:
        raise ConversionError("Cannot determine video duration for target compression.")

    preset = params.get("preset", "25 MB")
    preset_map = {
        "25 MB": 24.5,
        "50 MB": 49.0,
        "10 MB": 9.5,
        "8 MB": 7.5,
        "<25 MB": 24.5,
        "<50 MB": 49.0,
        "<10 MB": 9.5,
        "<8 MB": 7.5,
        "<25 MB (Discord)": 24.5,
        "<50 MB (Nitro)": 49.0,
        "<10 MB (Email)": 9.5,
        "<8 MB (WhatsApp)": 7.5,
    }
    target_mb = preset_map.get(preset, float(params.get("custom_mb", 25)))
    target_bits = target_mb * 8 * 1024 * 1024 * 0.95

    has_audio = info.get("audio", False)
    # Dynamically scale audio bitrate down to 48k/64k if target is tight
    if has_audio:
        target_total_kbps = (target_bits / dur) / 1000
        if target_total_kbps < 150:
            a_bitrate_k = 48
        elif target_total_kbps < 300:
            a_bitrate_k = 64
        else:
            a_bitrate_k = 128
    else:
        a_bitrate_k = 0

    total_audio_bits = a_bitrate_k * 1000 * dur if has_audio else 0

    total_video_bits = target_bits - total_audio_bits
    min_video_bps = 20000  # 20 kbps floor
    if total_video_bits < min_video_bps * dur:
        min_mb = max(1, math.ceil(((min_video_bps + (32000 if has_audio else 0)) * dur) / (8 * 1024 * 1024 * 0.95)))
        raise ConversionError(f"Target size ({target_mb:g} MB) is too small for a {dur:.0f}s video. Minimum achievable size is {min_mb} MB.")

    v_bitrate_k = max(20, int((total_video_bits / dur) / 1000))
    out = _out(ws, src, f"Target_{int(target_mb)}MB", "mp4")

    import sys
    log_prefix = ws.path("_ff2pass")
    pass1_args = [
        "-i", str(src), "-c:v", "libx264", "-b:v", f"{v_bitrate_k}k",
        "-pass", "1", "-passlogfile", str(log_prefix), "-an", "-f", "null",
        ("NUL" if sys.platform == "win32" else "/dev/null")
    ]
    pass2_args = [
        "-i", str(src), "-c:v", "libx264", "-b:v", f"{v_bitrate_k}k",
        "-pass", "2", "-passlogfile", str(log_prefix),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt", "yuv420p"
    ]
    if has_audio:
        pass2_args += ["-c:a", "aac", "-b:a", f"{a_bitrate_k}k"]
    else:
        pass2_args += ["-an"]
    pass2_args += ["-movflags", "+faststart", str(out)]

    run_ffmpeg(pass1_args, dur, lambda f: progress(f * 0.45), cancel)
    run_ffmpeg(pass2_args, dur, lambda f: progress(0.45 + f * 0.55), cancel)

    for p in ws.work.glob("_ff2pass*"):
        try:
            p.unlink()
        except OSError:
            pass
    return out



EQ_PRESETS = [
    "Flat",
    "Bass Boost (+8dB)",
    "Ultra Bass (+14dB)",
    "Vocal Boost",
    "Treble Boost",
    "Loudness & Clarity",
]

EQ_PRESET_FILTERS = {
    "Bass Boost": "bass=g=8:f=100",
    "Bass Boost (+8dB)": "bass=g=8:f=100",
    "Ultra Bass": "bass=g=14:f=80,volume=1.2",
    "Ultra Bass (+14dB)": "bass=g=14:f=80,volume=1.2",
    "Vocal Boost": "equalizer=f=1000:t=q:w=1:g=5,equalizer=f=3000:t=q:w=1:g=4",
    "Treble Boost": "treble=g=8:f=4000",
    "Loudness & Clarity": "loudnorm=I=-16:TP=-1.5:LRA=11",
    "Flat": "anull",
    "Flat (Original)": "anull",
}


def resolve_eq_filter(preset: str) -> str:
    """Normalize EQ preset name and return its FFmpeg audio filter string."""
    if not preset:
        return "anull"
    p = str(preset).strip()
    if p in EQ_PRESET_FILTERS:
        return EQ_PRESET_FILTERS[p]
    p_low = p.lower()
    if "ultra" in p_low:
        return EQ_PRESET_FILTERS["Ultra Bass (+14dB)"]
    if "bass" in p_low:
        return EQ_PRESET_FILTERS["Bass Boost (+8dB)"]
    if "vocal" in p_low:
        return EQ_PRESET_FILTERS["Vocal Boost"]
    if "treble" in p_low:
        return EQ_PRESET_FILTERS["Treble Boost"]
    if "loudness" in p_low:
        return EQ_PRESET_FILTERS["Loudness & Clarity"]
    if "flat" in p_low:
        return "anull"
    prefix = p.split(" (")[0]
    return EQ_PRESET_FILTERS.get(prefix, "anull" if prefix == "Flat" else "bass=g=8:f=100")


def build_audio_filter(vol_pct: int = 100, eq_preset: str = "Flat") -> str:
    """Build a combined FFmpeg audio filter string from volume percentage and EQ preset."""
    filters = []
    eq_af = resolve_eq_filter(eq_preset)
    if eq_af and eq_af != "anull":
        filters.append(eq_af)
    vol_pct = max(10, min(600, int(vol_pct)))
    if vol_pct != 100:
        filters.append(f"volume={vol_pct / 100.0:.2f}")
    return ",".join(filters)


def volume_boost(src: Path, ws: Workspace, params: dict, progress, cancel) -> Path:
    info = probe(src)
    if not info.get("audio"):
        raise ConversionError("The source has no audio stream to amplify.")

    vol_pct = int(params.get("volume", 150))
    vol_pct = max(10, min(600, vol_pct))
    factor = vol_pct / 100.0

    preset = params.get("preset", "Flat")
    eq_af = resolve_eq_filter(preset)

    filters = []
    if eq_af and eq_af != "anull":
        filters.append(eq_af)
    filters.append(f"volume={factor:.2f}")
    af = ",".join(filters)

    sf = fmt_of(src)
    fam = family(sf)
    slug = preset.split()[0] if preset and preset not in ("Flat", "Flat (Original)") else ""
    suffix = f"Vol_{vol_pct}pct_{slug}" if slug else f"Vol_{vol_pct}pct"
    out = _out(ws, src, suffix)

    if fam == "video":
        a_codec = ["-c:a", "libopus", "-b:a", "128k"] if sf == "webm" else ["-c:a", "aac", "-b:a", "192k"]
        args = ["-i", str(src), "-c:v", "copy", "-filter:a", af, *a_codec, str(out)]
    else:
        if sf == "mp3":
            args = ["-i", str(src), "-filter:a", af, "-c:a", "libmp3lame", "-q:a", "2", str(out)]
        elif sf in engine.AUDIO_CODEC:
            codec = [a.replace("{abr}", "192") for a in engine.AUDIO_CODEC[sf]]
            args = ["-i", str(src), "-filter:a", af, *codec, str(out)]
        else:
            args = ["-i", str(src), "-filter:a", af, str(out)]
    run_ffmpeg(args, info.get("duration", 0), progress, cancel)
    return out


def audio_equalizer(src: Path, ws: Workspace, params: dict, progress, cancel) -> Path:
    info = probe(src)
    if not info.get("audio"):
        raise ConversionError("The source has no audio stream for equalizer.")

    preset = params.get("preset", "Bass Boost")
    eq_af = resolve_eq_filter(preset)

    vol_pct = int(params.get("volume", 100))
    vol_pct = max(10, min(600, vol_pct))

    filters = []
    if eq_af and eq_af != "anull":
        filters.append(eq_af)
    if vol_pct != 100:
        filters.append(f"volume={vol_pct / 100.0:.2f}")

    af = ",".join(filters) if filters else "anull"
    sf = fmt_of(src)
    fam = family(sf)
    slug = preset.split()[0]
    suffix = f"EQ_{slug}_{vol_pct}pct" if vol_pct != 100 else f"EQ_{slug}"
    out = _out(ws, src, suffix)

    if fam == "video":
        a_codec = ["-c:a", "libopus", "-b:a", "128k"] if sf == "webm" else ["-c:a", "aac", "-b:a", "192k"]
        args = ["-i", str(src), "-c:v", "copy", "-filter:a", af, *a_codec, str(out)]
    else:
        if sf == "mp3":
            args = ["-i", str(src), "-filter:a", af, "-c:a", "libmp3lame", "-q:a", "2", str(out)]
        elif sf in engine.AUDIO_CODEC:
            codec = [a.replace("{abr}", "192") for a in engine.AUDIO_CODEC[sf]]
            args = ["-i", str(src), "-filter:a", af, *codec, str(out)]
        else:
            args = ["-i", str(src), "-filter:a", af, str(out)]
    run_ffmpeg(args, info.get("duration", 0), progress, cancel)
    return out


def extract_text_tool(src: Path, ws: Workspace, params: dict) -> Path:
    sf = fmt_of(src)
    text = ""
    if sf == "pdf":
        text = engine.pdf_to_text(src)
    elif sf in engine.IMAGE_IN:
        try:
            import pytesseract
            from PIL import Image
            with Image.open(src) as im:
                text = pytesseract.image_to_string(im)
        except Exception:
            from .inspector import get_file_info
            info = get_file_info(src)
            dims = info.get("media", {}).get("Dimensions", "N/A")
            text = f"File: {info['name']}\nDimensions: {dims}\nFormat: {info['format']}\nSHA256: {info['sha256']}\n"

    if not text or not text.strip():
        raise ConversionError("No text could be extracted from this file.")

    target = params.get("target", ".txt File")
    if target in ("Copy to Clipboard", "Both"):
        try:
            from PySide6.QtCore import QTimer, QThread
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                def _copy():
                    c = app.clipboard()
                    if c:
                        c.setText(text)

                if QThread.currentThread() == app.thread():
                    _copy()
                else:
                    QTimer.singleShot(0, app, _copy)
        except Exception:
            pass

    out = _out(ws, src, "Extracted", "txt")
    out.write_text(text, encoding="utf-8")
    return out


# ------------------------------------------------------------------ dispatcher
class ToolResult(tuple):
    """Tuple of (outputs, errors) that also behaves as a PathLike pointing to the first output."""
    def __new__(cls, outs, errs):
        return super().__new__(cls, (outs, errs))

    def __fspath__(self):
        if self and self[0]:
            return str(self[0][0])
        return ""

    @property
    def name(self):
        return self[0][0].name if (self and self[0]) else ""

    @property
    def stem(self):
        return self[0][0].stem if (self and self[0]) else ""

    def exists(self):
        return self[0][0].exists() if (self and self[0]) else False


def run_tool(tool_id: str, sources, params: dict, settings, progress=_noop,
             cancel: Optional[threading.Event] = None):
    """Run a tool. Returns (outputs, errors[(name, message)])."""
    t = BY_ID[tool_id]
    sources = [Path(s) for s in sources]
    for s in sources:
        if not s.is_file():
            raise ConversionError(f"Source file not found: {s}")
    outs, errs = [], []
    if t.multi:
        if not sources:
            raise ConversionError("No source files provided.")
        with Workspace(settings, sources[0]) as ws:
            if tool_id == "merge_pdf":
                pdf_merge(sources, ws)
            elif tool_id == "create_pdf":
                images_to_pdf(sources, ws)
            elif tool_id == "collage":
                collage(sources, ws, params)
            elif tool_id == "join":
                join_videos(sources, ws, progress, cancel)
            progress(1.0)
            published = ws.publish()
            if params.get("custom_name"):
                from .rename import apply_custom_rename
                published = [Path(p) for p in apply_custom_rename([str(p) for p in published], params["custom_name"])]
            return ToolResult(published, [])
    n = len(sources)
    for i, s in enumerate(sources):
        sub = lambda f, i=i: progress((i + f) / n)
        try:
            with Workspace(settings, s) as ws:
                fam = family(fmt_of(s))
                if fam == "gif":
                    fam = "image"
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if tool_id == "compress":
                    (compress_image(s, ws, params, settings) if fam == "image" else
                     pdf_compress(s, ws) if fam == "pdf" else compress_media(s, ws, params, sub, cancel))
                elif tool_id == "metadata":
                    (strip_image(s, ws) if fam == "image" else pdf_strip(s, ws) if fam == "pdf"
                     else strip_media(s, ws, sub, cancel))
                elif tool_id == "edit":
                    edit_image(s, ws, params, settings)
                elif tool_id == "crop":
                    crop_image(s, ws, params["box"], settings)
                elif tool_id == "addbg":
                    add_background(s, ws, params, settings)
                elif tool_id == "normalize":
                    normalize_audio(s, ws, sub, cancel)
                elif tool_id == "trim":
                    trim_media(s, ws, params, sub, cancel)
                elif tool_id == "remove_audio":
                    remove_audio(s, ws, sub, cancel)
                elif tool_id == "speed":
                    speed_video(s, ws, params, sub, cancel)
                elif tool_id == "snapshot":
                    snapshot(s, ws, params, sub, cancel)
                elif tool_id == "split_pdf":
                    pdf_split(s, ws)
                elif tool_id == "extract":
                    extract_archive(s, ws)
                elif tool_id == "resize":
                    if fam == "image":
                        resize_image(s, ws, params, settings)
                    elif fam == "video":
                        resize_video(s, ws, params, sub, cancel)
                    elif fam == "pdf":
                        resize_pdf(s, ws, params)
                    else:
                        raise ConversionError(f"Resize does not support .{fmt_of(s)} files.")
                elif tool_id == "target_compress":
                    target_compress_video(s, ws, params, sub, cancel)
                elif tool_id == "volume":
                    volume_boost(s, ws, params, sub, cancel)
                elif tool_id == "eq":
                    audio_equalizer(s, ws, params, sub, cancel)
                elif tool_id == "extract_text":
                    extract_text_tool(s, ws, params)
                else:
                    raise ConversionError(f"Unknown tool {tool_id}")
                outs += ws.publish()
        except Cancelled:
            raise
        except ConversionError as e:
            errs.append((s.name, str(e)))
        except Exception as e:
            errs.append((s.name, f"{type(e).__name__}: {e}"))
        progress((i + 1) / n)
    if params.get("custom_name"):
        from .rename import apply_custom_rename
        outs = [Path(p) for p in apply_custom_rename([str(p) for p in outs], params["custom_name"])]
    return ToolResult(outs, errs)


# ------------------------------------------------------------------ live previews (used by the option dialogs)
PREVIEW_TOOLS = ("edit", "addbg", "compress", "collage", "trim", "speed", "snapshot", "resize", "target_compress", "volume", "eq")
_THUMBS: OrderedDict = OrderedDict()
_MAX_THUMBS = 64


def thumb(path, box=(500, 340)):
    """Cached, orientation-corrected RGBA thumbnail of an image file (LRU bounded)."""
    key = (str(path), box)
    if key in _THUMBS:
        _THUMBS.move_to_end(key)
        return _THUMBS[key].copy()
    from PIL import ImageOps
    raw = engine.load_image(path)
    try:
        im = ImageOps.exif_transpose(raw).convert("RGBA")
    finally:
        try:
            raw.close()
        except Exception:
            pass
    im.thumbnail(box)
    _THUMBS[key] = im
    if len(_THUMBS) > _MAX_THUMBS:
        _THUMBS.popitem(last=False)
    return im.copy()


def media_frame(src, t: float, width: int = 480):
    import os, subprocess, tempfile
    from PIL import Image
    fd, out = tempfile.mkstemp(suffix=".png"); os.close(fd)
    try:
        subprocess.run([need_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, t):.3f}",
                        "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", out],
                       capture_output=True, creationflags=engine.NOWIN)
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            raise ConversionError("No frame at that time.")
        with Image.open(out) as im:
            im.load()
            return im.convert("RGB")
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def waveform_image(src, w: int = 500, h: int = 120):
    import os, subprocess, tempfile
    from PIL import Image
    fd, out = tempfile.mkstemp(suffix=".png"); os.close(fd)
    try:
        subprocess.run([need_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-filter_complex",
                        f"aformat=channel_layouts=mono,showwavespic=s={w}x{h}:colors=white", "-frames:v", "1", out],
                       capture_output=True, creationflags=engine.NOWIN)
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            raise ConversionError("Could not draw the waveform.")
        with Image.open(out) as im:
            im.load()
            return im.convert("RGB")
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def draw_trim_markers(im, start: float, end: float, dur: float):
    from PIL import Image, ImageDraw
    im = im.convert("RGBA")
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    x0 = int(im.width * max(0.0, min(1.0, start / dur))) if dur else 0
    x1 = int(im.width * max(0.0, min(1.0, end / dur))) if dur else im.width
    d.rectangle([0, 0, x0, im.height], fill=(0, 0, 0, 170))
    d.rectangle([x1, 0, im.width, im.height], fill=(0, 0, 0, 170))
    d.rectangle([x0 - 1, 0, x0 + 1, im.height], fill=(255, 255, 255, 255))
    d.rectangle([x1 - 1, 0, x1 + 1, im.height], fill=(255, 255, 255, 255))
    return Image.alpha_composite(im, ov)


def _hsize(n: int) -> str:
    return f"{n / 1e6:.2f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def make_preview(tool_id: str, paths, p: dict):
    """Return (PIL image or None, info text) for the option dialogs. Never modifies any file."""
    import shutil, tempfile
    from PIL import Image, ImageDraw
    src = Path(paths[0])
    fam = family(fmt_of(src))
    if fam == "gif":
        fam = "image"
    if tool_id in ("edit", "addbg"):
        im = thumb(src)
        out = preview_image(tool_id, im, p)
        return out, ""
    if tool_id == "resize":
        if fam in ("image", "pdf"):
            if fam == "pdf":
                try:
                    fz = engine._fitz()
                    with fz.open(str(src)) as doc:
                        if len(doc) > 0:
                            orig_w, orig_h = int(round(doc[0].rect.width)), int(round(doc[0].rect.height))
                        else:
                            orig_w, orig_h = 595, 842
                except Exception:
                    orig_w, orig_h = 595, 842
            else:
                try:
                    with engine.load_image(src) as full_im:
                        orig_w, orig_h = full_im.width, full_im.height
                except Exception:
                    im_tmp = thumb(src)
                    orig_w, orig_h = im_tmp.width, im_tmp.height

            tw, th = _resolve_resize(p, orig_w, orig_h)
            im = thumb(src)
            from PIL import Image
            preview = im.resize((max(1, min(tw, 500)), max(1, min(th, 340))), Image.LANCZOS)
            return preview, f"Output: {tw} × {th} px"
        if fam == "video":
            v_info = probe(src)
            ow, oh = v_info.get("width") or 1920, v_info.get("height") or 1080
            tw, th = _resolve_resize(p, ow, oh)
            tw, th = tw // 2 * 2, th // 2 * 2
            return media_frame(src, 0.5), f"Original: {ow} × {oh} px → Target: {tw} × {th} px"
        return None, ""
    if tool_id == "collage":
        ims = [thumb(x, (170, 170)) for x in paths]
        return build_collage(ims, p, 170), f"{len(ims)} images"
    if tool_id == "compress":
        note = f" (previewing the first of {len(paths)} files)" if len(paths) > 1 else ""
        orig = src.stat().st_size
        if fam == "image":
            tmpdir = Path(tempfile.mkdtemp())
            try:
                class _W:
                    def path(self, n): return tmpdir / n
                out = compress_image(src, _W(), p, None)
                new = out.stat().st_size
                with Image.open(out) as raw_im:
                    im = raw_im.convert("RGBA")
                    im.thumbnail((500, 340))
                    im.load()
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
            return im, f"Original {_hsize(orig)} → {_hsize(new)} ({(1 - new / orig) * 100:.0f}% smaller){note}"
        if fam == "video":
            return media_frame(src, 0.5), f"Original {_hsize(orig)}. The exact size is known after compressing{note}"
        if fam == "audio":
            return waveform_image(src), f"Original {_hsize(orig)}. The exact size is known after compressing{note}"
        return None, f"Original {_hsize(orig)}. The exact size is known after compressing{note}"
    info = engine.probe(src)
    dur = info["duration"]
    if tool_id == "snapshot":
        t = float(p.get("time", 0))
        return media_frame(src, min(t, max(0.0, dur - 0.05))), f"Frame at {t:.2f}s of {dur:.2f}s"
    if tool_id == "speed":
        f = float(p.get("factor", 2.0))
        return media_frame(src, dur / 2), f"{f:g}× speed: {dur:.1f}s → {dur / f:.1f}s"
    if tool_id == "trim":
        s0 = max(0.0, float(p.get("start", 0)))
        e0 = float(p.get("end", 0)) or dur
        e0 = min(e0, dur)
        txt = f"Keeping {max(0.0, e0 - s0):.2f}s of {dur:.2f}s  ({s0:.2f}s → {e0:.2f}s)"
        if fam == "audio":
            return draw_trim_markers(waveform_image(src), s0, e0, dur), txt
        a = media_frame(src, s0, 300)
        b = media_frame(src, max(s0, e0 - 0.1), 300)
        canvas = Image.new("RGB", (a.width + b.width + 12, max(a.height, b.height) + 22), (20, 22, 26))
        canvas.paste(a, (0, 22)); canvas.paste(b, (a.width + 12, 22))
        d = ImageDraw.Draw(canvas)
        d.text((6, 5), f"START {s0:.2f}s", fill="white"); d.text((a.width + 18, 5), f"END {e0:.2f}s", fill="white")
        return canvas, txt
    if tool_id == "target_compress":
        preset = p.get("preset", "<25 MB (Discord)")
        return media_frame(src, dur * 0.25 if dur else 0.5), f"Target: {preset} · Duration: {dur:.1f}s (Optimized H.264)"
    if tool_id == "volume":
        vol = int(p.get("volume", 150))
        factor = vol / 100.0
        preset = p.get("preset", "Flat")
        txt = f"Volume: {vol}% ({factor:.2f}x boost)"
        if preset and preset not in ("Flat", "Flat (Original)"):
            txt += f" · EQ: {preset}"
        if fam == "video":
            return media_frame(src, dur * 0.25 if dur else 0.5), txt + " · Video stream copied lossless"
        else:
            return waveform_image(src), txt
    if tool_id == "eq":
        preset = p.get("preset", "Bass Boost")
        vol = int(p.get("volume", 100))
        txt = f"Equalizer preset: {preset}"
        if vol != 100:
            txt += f" · Volume: {vol}% ({vol / 100.0:.2f}x)"
        if fam == "video":
            return media_frame(src, dur * 0.25 if dur else 0.5), txt
        else:
            return waveform_image(src), txt
    return None, ""
