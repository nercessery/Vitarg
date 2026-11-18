#!/usr/bin/env python3
"""Cross-platform tool fetcher for Vitarg (FFmpeg, FFprobe, Pandoc).
Downloads standalone, statically linked binaries for Linux or Windows into the tools/ directory.
On Linux, strictly avoids and purges any Windows .exe / PE binaries.
"""
import argparse
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
WINDOWS_EXTENSIONS = (".exe", ".dll", ".bat", ".cmd", ".msi", ".ps1", ".vbs")


def log(msg: str) -> None:
    print(f"[fetch_tools] {msg}", flush=True)


def get_linux_arch() -> str:
    mach = platform.machine().lower()
    if mach in ("aarch64", "arm64", "armv8b", "armv8l"):
        return "arm64"
    return "amd64"


def is_windows_pe_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() in WINDOWS_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def is_valid_linux_binary(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() in WINDOWS_EXTENSIONS:
        return False
    try:
        if path.stat().st_size < 64:
            return False
        with open(path, "rb") as f:
            head = f.read(4)
        if head[:2] == b"MZ":
            return False
        return head == b"\x7fELF" or head[:2] == b"#!"
    except OSError:
        return False


def download_file(url: str, dest_path: Path, target_platform: str = "linux") -> None:
    if target_platform == "linux":
        low_url = url.lower().split("?", 1)[0]
        if low_url.endswith(WINDOWS_EXTENSIONS):
            raise RuntimeError(f"Refusing to download Windows executable for Linux target: {url}")
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
    """Fetch standalone, statically linked Linux ELF binaries for FFmpeg, FFprobe, and Pandoc."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    lic_dir = tools_dir / "licenses"
    lic_dir.mkdir(parents=True, exist_ok=True)

    # Strictly purge any Windows binaries (.exe or PE 'MZ' files) from tools_dir when targeting Linux
    for item in tools_dir.iterdir():
        if item.is_file() and is_windows_pe_file(item):
            item.unlink(missing_ok=True)
            log(f"Removed Windows artifact: {item.name}")

    ffmpeg_bin = tools_dir / "ffmpeg"
    ffprobe_bin = tools_dir / "ffprobe"
    pandoc_bin = tools_dir / "pandoc"
    arch = get_linux_arch()

    # 1. FFmpeg & FFprobe (BtbN static GPL build, with fallback to John Van Sickle)
    if not (is_valid_linux_binary(ffmpeg_bin) and is_valid_linux_binary(ffprobe_bin)):
        ffmpeg_archive = tmp_dir / "ffmpeg-linux.tar.xz"
        urls = []
        token = "linuxarm64" if arch == "arm64" else "linux64"
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest",
                headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for a in data.get("assets", []):
                    name = a.get("name", "").lower()
                    if (
                        token in name
                        and "gpl" in name
                        and "shared" not in name
                        and "lgpl" not in name
                        and name.endswith(".tar.xz")
                    ):
                        dl_url = a.get("browser_download_url")
                        if dl_url:
                            urls.append(dl_url)
                            break
        except Exception as e:
            log(f"GitHub API query failed for FFmpeg: {e}")

        if arch == "arm64":
            urls.extend([
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
                "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
            ])
        else:
            urls.extend([
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
                "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
            ])

        seen = set()
        unique_urls = [u for u in urls if not (u in seen or seen.add(u))]

        success = False
        for url in unique_urls:
            try:
                if ffmpeg_archive.exists():
                    ffmpeg_archive.unlink(missing_ok=True)
                download_file(url, ffmpeg_archive, target_platform="linux")
                log(f"Extracting FFmpeg from {ffmpeg_archive.name}...")
                with tarfile.open(ffmpeg_archive, "r:xz") as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        base = os.path.basename(member.name)
                        if base.lower().endswith(WINDOWS_EXTENSIONS):
                            continue
                        if base in ("ffmpeg", "ffprobe") and member.size > 100_000:
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
                if is_valid_linux_binary(ffmpeg_bin) and is_valid_linux_binary(ffprobe_bin):
                    success = True
                    break
            except Exception as e:
                log(f"Failed to fetch/extract from {url}: {e}")
                if ffmpeg_archive.exists():
                    ffmpeg_archive.unlink(missing_ok=True)

        if not success:
            raise RuntimeError("Failed to download usable Linux static FFmpeg/FFprobe ELF binaries.")

    # 2. Pandoc (official standalone static Linux tarball)
    if not is_valid_linux_binary(pandoc_bin):
        pandoc_archive = tmp_dir / "pandoc-linux.tar.gz"
        arch_token = f"linux-{arch}"
        pandoc_urls = []
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/jgm/pandoc/releases/latest",
                headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for a in data.get("assets", []):
                    name = a.get("name", "").lower()
                    if arch_token in name and name.endswith(".tar.gz") and not name.endswith(WINDOWS_EXTENSIONS):
                        dl_url = a.get("browser_download_url")
                        if dl_url:
                            pandoc_urls.append(dl_url)
                            break
        except Exception as e:
            log(f"GitHub API query failed for Pandoc: {e}")

        pandoc_urls.extend([
            f"https://github.com/jgm/pandoc/releases/download/3.14/pandoc-3.14-linux-{arch}.tar.gz",
            f"https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-{arch}.tar.gz",
        ])

        seen = set()
        unique_pandoc_urls = [u for u in pandoc_urls if not (u in seen or seen.add(u))]

        for pandoc_url in unique_pandoc_urls:
            try:
                if pandoc_archive.exists():
                    pandoc_archive.unlink(missing_ok=True)
                download_file(pandoc_url, pandoc_archive, target_platform="linux")
                log(f"Extracting Pandoc from {pandoc_archive.name}...")
                with tarfile.open(pandoc_archive, "r:gz") as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        base = os.path.basename(member.name)
                        if base == "pandoc" and member.size > 100_000:
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                pandoc_bin.write_bytes(f_obj.read())
                                make_executable(pandoc_bin)
                                log(f"Extracted pandoc -> {pandoc_bin}")
                        elif "COPYING" in base or "LICENSE" in base:
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                (lic_dir / "Pandoc-COPYING.txt").write_bytes(f_obj.read())
                if is_valid_linux_binary(pandoc_bin):
                    break
            except Exception as e:
                log(f"Failed to fetch/extract Pandoc from {pandoc_url}: {e}")
                if pandoc_archive.exists():
                    pandoc_archive.unlink(missing_ok=True)

    # Final verification
    for name in ("ffmpeg", "ffprobe", "pandoc"):
        p = tools_dir / name
        if not is_valid_linux_binary(p):
            raise RuntimeError(f"Tool {name} is missing, empty, or not a valid Linux ELF binary in {tools_dir}")
        make_executable(p)
        log(f"Verified Linux ELF tool: {p} ({p.stat().st_size // (1024*1024)} MB)")


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
        download_file(url, zip_path, target_platform="windows")
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
        download_file(url, zip_path, target_platform="windows")
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
    parser.add_argument("--allow-cross-win", action="store_true",
                        help="Explicitly allow downloading Windows .exe tools while running on Linux")
    args = parser.parse_args()

    target_platform = args.platform
    if sys.platform != "win32" and target_platform == "windows" and not args.allow_cross_win:
        log("Running on Linux: overriding target platform to 'linux' to avoid downloading .exe files.")
        target_platform = "linux"

    repo_root = Path(__file__).resolve().parent.parent
    tools_dir = args.dest or (repo_root / "tools")
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"vitarg_fetch_{target_platform}_"))

    log(f"Target platform: {target_platform}")
    log(f"Destination:     {tools_dir}")

    try:
        if target_platform == "linux":
            fetch_linux_tools(tools_dir, tmp_dir)
        else:
            fetch_windows_tools(tools_dir, tmp_dir)
        log("All tools fetched successfully!")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
