#!/usr/bin/env python3
"""Cross-platform tool fetcher for Vitarg (FFmpeg, FFprobe, Pandoc).
Downloads standalone, statically linked binaries for Linux or Windows into the tools/ directory.
"""
import argparse
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def log(msg: str) -> None:
    print(f"[fetch_tools] {msg}", flush=True)


def download_file(url: str, dest_path: Path) -> None:
    log(f"Downloading: {url} -> {dest_path.name}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest_path, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        last_pct = -1
        while True:
            chunk = resp.read(1024 * 512)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = int((downloaded / total) * 100)
                if pct != last_pct and pct % 25 == 0:
                    log(f"  ... {pct}% ({downloaded // (1024*1024)} MB / {total // (1024*1024)} MB)")
                    last_pct = pct


def make_executable(p: Path) -> None:
    if sys.platform != "win32":
        try:
            mode = p.stat().st_mode
            p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass


def fetch_linux_tools(tools_dir: Path, tmp_dir: Path) -> None:
    """Fetch standalone, statically linked Linux x86_64 binaries for FFmpeg, FFprobe, and Pandoc."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    lic_dir = tools_dir / "licenses"
    lic_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = tools_dir / "ffmpeg"
    ffprobe_bin = tools_dir / "ffprobe"
    pandoc_bin = tools_dir / "pandoc"

    # 1. FFmpeg & FFprobe (BtbN static GPL build, with fallback to John Van Sickle)
    if not (ffmpeg_bin.exists() and ffprobe_bin.exists()):
        ffmpeg_archive = tmp_dir / "ffmpeg-linux.tar.xz"
        urls = [
            "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
            "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        ]
        success = False
        for url in urls:
            try:
                download_file(url, ffmpeg_archive)
                log(f"Extracting FFmpeg from {ffmpeg_archive.name}...")
                with tarfile.open(ffmpeg_archive, "r:xz") as tf:
                    for member in tf.getmembers():
                        base = os.path.basename(member.name)
                        if base in ("ffmpeg", "ffprobe"):
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                target = tools_dir / base
                                target.write_bytes(f_obj.read())
                                make_executable(target)
                                log(f"Extracted {base} -> {target}")
                        elif "LICENSE" in base or "GPL" in base:
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                (lic_dir / "FFmpeg-LICENSE.txt").write_bytes(f_obj.read())
                if ffmpeg_bin.exists() and ffprobe_bin.exists():
                    success = True
                    break
            except Exception as e:
                log(f"Failed to fetch/extract from {url}: {e}")
                if ffmpeg_archive.exists():
                    ffmpeg_archive.unlink()

        if not success:
            raise RuntimeError("Failed to download usable Linux static FFmpeg/FFprobe binaries.")

    # 2. Pandoc (official standalone static Linux amd64 tarball)
    if not pandoc_bin.exists():
        pandoc_archive = tmp_dir / "pandoc-linux.tar.gz"
        pandoc_url = None
        try:
            req = urllib.request.Request("https://api.github.com/repos/jgm/pandoc/releases/latest",
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for a in data.get("assets", []):
                    name = a.get("name", "")
                    if "linux-amd64" in name and name.endswith(".tar.gz"):
                        pandoc_url = a.get("browser_download_url")
                        break
        except Exception as e:
            log(f"GitHub API query failed for Pandoc: {e}")

        if not pandoc_url:
            pandoc_url = "https://github.com/jgm/pandoc/releases/download/3.14/pandoc-3.14-linux-amd64.tar.gz"

        try:
            download_file(pandoc_url, pandoc_archive)
            log(f"Extracting Pandoc from {pandoc_archive.name}...")
            with tarfile.open(pandoc_archive, "r:gz") as tf:
                for member in tf.getmembers():
                    base = os.path.basename(member.name)
                    if base == "pandoc":
                        f_obj = tf.extractfile(member)
                        if f_obj:
                            pandoc_bin.write_bytes(f_obj.read())
                            make_executable(pandoc_bin)
                            log(f"Extracted pandoc -> {pandoc_bin}")
                    elif "COPYING" in base or "LICENSE" in base:
                        f_obj = tf.extractfile(member)
                        if f_obj:
                            (lic_dir / "Pandoc-COPYING.txt").write_bytes(f_obj.read())
        except Exception as e:
            log(f"Failed to fetch/extract Pandoc: {e}")
            if pandoc_archive.exists():
                pandoc_archive.unlink()

    # Final verification
    for name in ("ffmpeg", "ffprobe", "pandoc"):
        p = tools_dir / name
        if not p.exists() or p.stat().st_size == 0:
            raise RuntimeError(f"Tool {name} is missing or empty in {tools_dir}")
        make_executable(p)
        log(f"Verified Linux tool: {p} ({p.stat().st_size // (1024*1024)} MB)")


def fetch_windows_tools(tools_dir: Path, tmp_dir: Path) -> None:
    """Fetch standalone Windows x86_64 binaries for FFmpeg, FFprobe, and Pandoc."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    lic_dir = tools_dir / "licenses"
    lic_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = tools_dir / "ffmpeg.exe"
    ffprobe_bin = tools_dir / "ffprobe.exe"
    pandoc_bin = tools_dir / "pandoc.exe"

    if not (ffmpeg_bin.exists() and ffprobe_bin.exists()):
        zip_path = tmp_dir / "ffmpeg-win.zip"
        url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        download_file(url, zip_path)
        log("Extracting Windows FFmpeg...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            for item in zf.namelist():
                base = os.path.basename(item)
                if base in ("ffmpeg.exe", "ffprobe.exe"):
                    (tools_dir / base).write_bytes(zf.read(item))
                    log(f"Extracted {base} -> {tools_dir / base}")
                elif "LICENSE" in base:
                    (lic_dir / "FFmpeg-LICENSE.txt").write_bytes(zf.read(item))

    if not pandoc_bin.exists():
        zip_path = tmp_dir / "pandoc-win.zip"
        url = "https://github.com/jgm/pandoc/releases/download/3.14/pandoc-3.14-windows-x86_64.zip"
        download_file(url, zip_path)
        log("Extracting Windows Pandoc...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            for item in zf.namelist():
                base = os.path.basename(item)
                if base == "pandoc.exe":
                    pandoc_bin.write_bytes(zf.read(item))
                    log(f"Extracted pandoc.exe -> {pandoc_bin}")
                elif "COPYING" in base or "LICENSE" in base:
                    (lic_dir / "Pandoc-COPYING.txt").write_bytes(zf.read(item))

    for name in ("ffmpeg.exe", "ffprobe.exe", "pandoc.exe"):
        p = tools_dir / name
        if not p.exists() or p.stat().st_size == 0:
            raise RuntimeError(f"Tool {name} is missing or empty in {tools_dir}")
        log(f"Verified Windows tool: {p} ({p.stat().st_size // (1024*1024)} MB)")


def main():
    parser = argparse.ArgumentParser(description="Fetch conversion tools for Vitarg.")
    parser.add_argument("--platform", choices=["linux", "windows"],
                        default="windows" if sys.platform == "win32" else "linux",
                        help="Target OS platform (default: detected OS)")
    parser.add_argument("--dest", type=Path, default=None,
                        help="Destination directory (default: <repo_root>/tools)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    tools_dir = args.dest or (repo_root / "tools")
    tmp_dir = Path(tempfile.gettempdir()) / f"vitarg_fetch_{args.platform}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    log(f"Target platform: {args.platform}")
    log(f"Destination:     {tools_dir}")

    try:
        if args.platform == "linux":
            fetch_linux_tools(tools_dir, tmp_dir)
        else:
            fetch_windows_tools(tools_dir, tmp_dir)
        log("All tools fetched successfully!")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
