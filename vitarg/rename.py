"""Auto-rename and custom naming utilities for Vitarg."""
from __future__ import annotations
import datetime, re
from pathlib import Path


def format_rename(original_path: str | Path, pattern_or_name: str, ext: str, index: int = 1) -> str:
    """Generate a clean new filename based on a pattern or custom name."""
    orig = Path(original_path)
    stem = orig.stem
    if orig.name.lower().endswith(".tar.gz"):
        stem = orig.name[:-7]

    now = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")
    clean_ext = ext if ext.startswith(".") else f".{ext}"

    p = pattern_or_name.strip()
    if not p:
        return f"{stem}{clean_ext}"

    # Replace template variables if present
    if any(k in p for k in ("{name}", "{date}", "{time}", "{num}", "{ext}")):
        name = p.replace("{name}", stem)
        name = name.replace("{date}", date_str)
        name = name.replace("{time}", time_str)
        name = name.replace("{num}", f"{index:02d}")
        name = name.replace("{ext}", clean_ext.lstrip("."))
    else:
        # User entered a literal name like "vacation_pic"
        # If multiple files, append index
        if index > 1:
            name = f"{p}_{index:02d}"
        else:
            name = p

    # Sanitize invalid Windows filename characters: \ / : * ? " < > |
    name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    if not name:
        name = stem

    if not name.lower().endswith(clean_ext.lower()):
        name = f"{name}{clean_ext}"
    return name


def apply_custom_rename(created_paths: list[str], custom_name: str) -> list[str]:
    """Rename newly created output files according to custom_name pattern."""
    if not custom_name or not custom_name.strip():
        return created_paths

    new_paths = []
    for i, p_str in enumerate(created_paths, start=1):
        p = Path(p_str)
        if not p.exists():
            new_paths.append(p_str)
            continue

        ext = ".tar.gz" if p.name.lower().endswith(".tar.gz") else p.suffix
        new_name = format_rename(p, custom_name, ext, index=i)
        target = p.parent / new_name

        # Avoid collision
        counter = 2
        stem = target.stem
        while target.exists() and target != p:
            target = p.parent / f"{stem}_{counter:02d}{ext}"
            counter += 1

        try:
            p.rename(target)
            new_paths.append(str(target))
        except Exception:
            new_paths.append(p_str)

    return new_paths
