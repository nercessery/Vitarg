"""Estimates output file size and quality for conversions and tool operations."""
from __future__ import annotations
import math, os
from pathlib import Path
from typing import Optional

from . import engine


def format_size(bytes_num: int | float) -> str:
    """Format bytes into readable string: 1.4 MB, 450 KB, etc."""
    if bytes_num < 1024:
        return f"{int(bytes_num)} B"
    elif bytes_num < 1024 * 1024:
        return f"{bytes_num / 1024:.1f} KB"
    elif bytes_num < 1024 * 1024 * 1024:
        return f"{bytes_num / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_num / (1024 * 1024 * 1024):.2f} GB"


def estimate_conversion(src: str | Path, target: str, settings=None) -> dict:
    """Estimate output size and quality for converting src to target format."""
    p = Path(src)
    if not p.is_file():
        return {
            "src_size": 0, "src_size_str": "0 B", "est_size": 0, "est_size_str": "Unknown",
            "ratio_pct": 0, "quality": "Standard", "summary": "File not found"
        }

    src_size = p.stat().st_size
    src_fmt = engine.fmt_of(p).lower()
    tgt = target.lower().lstrip(".")
    fam = engine.family(src_fmt)

    # Defaults
    factor = 1.0
    quality = "High Quality"

    if fam in ("image", "gif"):
        # Image conversion factors
        if src_fmt in ("png", "bmp", "tiff"):
            if tgt in ("jpg", "jpeg"):
                factor = 0.20  # PNG -> JPG is typically 75-85% smaller
                quality = "High (85% JPEG)"
            elif tgt == "webp":
                factor = 0.15  # WebP is even more compact
                quality = "Very High (WebP)"
            elif tgt == "pdf":
                factor = 1.02
                quality = "Lossless Document"
            elif tgt == "ico":
                factor = min(0.3, 100_000 / max(1, src_size))
                quality = "Multi-resolution Icon"
            elif tgt in ("bmp", "tiff"):
                factor = 1.5
                quality = "Uncompressed"
            elif tgt == "gif":
                factor = 0.4
                quality = "256 Colors"
        elif src_fmt in ("jpg", "jpeg", "webp"):
            if tgt in ("png", "bmp", "tiff"):
                factor = 2.5   # Decompressing JPEG to PNG often inflates file size
                quality = "Lossless RGB"
            elif tgt == "webp" and src_fmt != "webp":
                factor = 0.75
                quality = "High Quality WebP"
            elif tgt in ("jpg", "jpeg") and src_fmt == "webp":
                factor = 1.2
                quality = "High JPEG"
            elif tgt == "pdf":
                factor = 1.02
                quality = "Embedded PDF"

    elif fam in ("audio", "video"):
        try:
            info = engine.probe(p)
            dur = info.get("duration", 0.0)
        except Exception:
            dur = 0.0

        if tgt == "mp3":
            # MP3 ~ 192 kbps = 24 KB/s
            est_bytes = max(10_000, int(dur * 24_000)) if dur > 0 else int(src_size * 0.25)
            factor = est_bytes / max(1, src_size)
            quality = "192 kbps Stereo"
        elif tgt in ("wav", "flac"):
            # Lossless audio ~ 1.4 Mbps = 175 KB/s
            est_bytes = max(20_000, int(dur * 175_000)) if dur > 0 else int(src_size * 1.5)
            factor = est_bytes / max(1, src_size)
            quality = "Lossless Audio"
        elif tgt in ("mp4", "mkv", "mov"):
            # Typical crf 23 x264 video ~ 2 Mbps
            est_bytes = max(50_000, int(dur * 250_000)) if dur > 0 else int(src_size * 0.7)
            factor = est_bytes / max(1, src_size)
            quality = "H.264 / AAC (CRF 23)"
        elif tgt == "webm":
            factor = 0.65
            quality = "VP9 / Opus"

    elif fam == "archive":
        if tgt in ("gz", "tar.gz"):
            factor = 0.90
            quality = "Gzip Solid"
        elif tgt == "zip":
            factor = 1.0
            quality = "Standard Zip"
        elif tgt == "tar":
            factor = 1.3
            quality = "Uncompressed Tar"

    elif fam in ("pdf", "doc"):
        if tgt == "txt":
            factor = 0.05
            quality = "Plain Text UTF-8"
        elif tgt in ("docx", "pdf"):
            factor = 0.95
            quality = "Formatted Document"
        elif tgt in ("png", "jpg"):
            factor = 1.5
            quality = "300 DPI Render"

    est_size = max(1024, int(src_size * factor))
    diff_pct = ((est_size - src_size) / src_size) * 100.0

    if diff_pct < -5:
        diff_str = f"~{abs(int(diff_pct))}% smaller"
    elif diff_pct > 5:
        diff_str = f"~{int(diff_pct)}% larger"
    else:
        diff_str = "approx. same size"

    summary = (f"Original: {format_size(src_size)} ({src_fmt.upper()}) ➔ "
               f"Est. Output: ~{format_size(est_size)} ({tgt.upper()}, {diff_str}) • {quality}")

    return {
        "src_size": src_size,
        "src_size_str": format_size(src_size),
        "est_size": est_size,
        "est_size_str": format_size(est_size),
        "ratio_pct": diff_pct,
        "quality": quality,
        "summary": summary
    }
