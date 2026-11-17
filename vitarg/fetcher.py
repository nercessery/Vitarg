"""In-app tool fetcher for Vitarg.
Automatically downloads and configures standalone statically linked Linux conversion tools
(FFmpeg, FFprobe, Pandoc) from the internet when they are not present on the host system.
"""
from __future__ import annotations
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def get_default_tools_dir() -> Path:
    """Determine the best directory to store downloaded tools."""
    # Check if app directory tools/ is writable
    try:
        from . import engine
        base_app = engine.app_dir()
        t_dir = base_app / "tools"
        t_dir.mkdir(parents=True, exist_ok=True)
        test_file = t_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return t_dir
    except Exception:
        pass

    if sys.platform != "win32":
        user_dir = Path.home() / ".local" / "share" / "vitarg" / "tools"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    fallback = Path(tempfile.gettempdir()) / "vitarg_tools"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def download_stream(url: str, dest_path: Path) -> None:
    """Download a file with user-agent and safe streaming."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest_path, "wb") as out:
        while True:
            chunk = resp.read(1024 * 512)
            if not chunk:
                break
            out.write(chunk)


def make_executable(p: Path) -> None:
    if sys.platform != "win32":
        try:
            mode = p.stat().st_mode
            p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass


def fetch_linux_ffmpeg(target_dir: Optional[Path] = None) -> tuple[Path, Path]:
    """Download standalone static Linux FFmpeg and FFprobe binaries."""
    tools_dir = target_dir or get_default_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = tools_dir / "ffmpeg"
    ffprobe_bin = tools_dir / "ffprobe"

    if ffmpeg_bin.exists() and ffprobe_bin.exists():
        make_executable(ffmpeg_bin)
        make_executable(ffprobe_bin)
        return ffmpeg_bin, ffprobe_bin

    tmp_dir = Path(tempfile.gettempdir()) / "vitarg_ffmpeg_dl"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tar_path = tmp_dir / "ffmpeg-linux.tar.xz"

    urls = [
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    ]

    success = False
    for url in urls:
        try:
            download_stream(url, tar_path)
            with tarfile.open(tar_path, "r:xz") as tf:
                for member in tf.getmembers():
                    base = os.path.basename(member.name)
                    if base in ("ffmpeg", "ffprobe"):
                        f_obj = tf.extractfile(member)
                        if f_obj:
                            target = tools_dir / base
                            target.write_bytes(f_obj.read())
                            make_executable(target)
            if ffmpeg_bin.exists() and ffprobe_bin.exists():
                success = True
                break
        except Exception:
            if tar_path.exists():
                tar_path.unlink()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if not success or not ffmpeg_bin.exists() or not ffprobe_bin.exists():
        raise RuntimeError("Failed to download Linux standalone FFmpeg/FFprobe binaries from GitHub/mirror.")

    make_executable(ffmpeg_bin)
    make_executable(ffprobe_bin)
    return ffmpeg_bin, ffprobe_bin


def fetch_linux_pandoc(target_dir: Optional[Path] = None) -> Path:
    """Download standalone static Linux Pandoc binary."""
    tools_dir = target_dir or get_default_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)
    pandoc_bin = tools_dir / "pandoc"

    if pandoc_bin.exists():
        make_executable(pandoc_bin)
        return pandoc_bin

    tmp_dir = Path(tempfile.gettempdir()) / "vitarg_pandoc_dl"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tar_path = tmp_dir / "pandoc-linux.tar.gz"

    pandoc_url = None
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/jgm/pandoc/releases/latest",
            headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for a in data.get("assets", []):
                name = a.get("name", "")
                if "linux-amd64" in name and name.endswith(".tar.gz"):
                    pandoc_url = a.get("browser_download_url")
                    break
    except Exception:
        pass

    if not pandoc_url:
        pandoc_url = "https://github.com/jgm/pandoc/releases/download/3.14/pandoc-3.14-linux-amd64.tar.gz"

    try:
        download_stream(pandoc_url, tar_path)
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                base = os.path.basename(member.name)
                if base == "pandoc":
                    f_obj = tf.extractfile(member)
                    if f_obj:
                        pandoc_bin.write_bytes(f_obj.read())
                        make_executable(pandoc_bin)
                        break
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not pandoc_bin.exists() or pandoc_bin.stat().st_size == 0:
        raise RuntimeError("Failed to download Linux standalone Pandoc binary.")

    make_executable(pandoc_bin)
    return pandoc_bin


def ensure_linux_tool(name: str) -> Optional[str]:
    """Ensure a tool is available on Linux by fetching it from the internet if missing."""
    if sys.platform == "win32":
        return None

    clean_name = name.lower().removesuffix(".exe")
    tools_dir = get_default_tools_dir()

    if clean_name in ("ffmpeg", "ffprobe"):
        try:
            ff, fp = fetch_linux_ffmpeg(tools_dir)
            target = ff if clean_name == "ffmpeg" else fp
            if target.exists():
                return str(target)
        except Exception:
            return None
    elif clean_name == "pandoc":
        try:
            pd = fetch_linux_pandoc(tools_dir)
            if pd.exists():
                return str(pd)
        except Exception:
            return None

    return None
