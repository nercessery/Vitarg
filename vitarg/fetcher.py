"""In-app tool fetcher for Vitarg.
Automatically downloads and configures standalone statically linked Linux conversion tools
(FFmpeg, FFprobe, Pandoc) from the internet when they are not present on the host system.
Strictly avoids and purges Windows .exe binaries on Linux.
"""
from __future__ import annotations
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
WINDOWS_EXTENSIONS = (".exe", ".dll", ".bat", ".cmd", ".msi", ".ps1", ".vbs")


def get_linux_arch() -> str:
    """Return normalized Linux architecture ('arm64' or 'amd64')."""
    mach = platform.machine().lower()
    if mach in ("aarch64", "arm64", "armv8b", "armv8l"):
        return "arm64"
    return "amd64"


def is_windows_pe_file(path: Path) -> bool:
    """Return True if path has a Windows executable extension or starts with the DOS/PE 'MZ' header."""
    if not path.is_file():
        return False
    if path.suffix.lower() in WINDOWS_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            magic = f.read(2)
        return magic == b"MZ"
    except OSError:
        return False


def is_valid_linux_binary(path: Path) -> bool:
    """Return True if path is a valid Linux ELF executable or shebang script (never a Windows .exe/PE)."""
    if not path.is_file():
        return False
    if path.suffix.lower() in WINDOWS_EXTENSIONS:
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


def purge_windows_binaries(directory: Optional[Path] = None) -> int:
    """Remove any Windows .exe/.dll/.bat/.cmd files or PE ('MZ') binaries on Linux."""
    if sys.platform == "win32":
        return 0
    removed = 0
    dirs_to_check = []
    if directory is not None:
        dirs_to_check.append(Path(directory))
    try:
        from . import engine
        dirs_to_check.extend([
            engine.app_dir() / "tools",
            Path(sys.executable).parent / "tools",
            Path(sys.executable).parent / "_internal" / "tools",
            Path.home() / ".local" / "share" / "vitarg" / "tools",
            Path.home() / ".vitarg" / "tools",
        ])
    except Exception:
        pass

    seen = set()
    for d in dirs_to_check:
        try:
            rp = d.resolve()
        except OSError:
            continue
        if rp in seen or not rp.is_dir():
            continue
        seen.add(rp)
        try:
            for item in rp.iterdir():
                if item.is_file() and is_windows_pe_file(item):
                    try:
                        item.unlink(missing_ok=True)
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return removed


def get_default_tools_dir() -> Path:
    """Determine the best writable directory to store downloaded tools."""
    try:
        from . import engine
        base_app = engine.app_dir()
        t_dir = base_app / "tools"
        t_dir.mkdir(parents=True, exist_ok=True)
        test_file = t_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        purge_windows_binaries(t_dir)
        return t_dir
    except Exception:
        pass

    if sys.platform != "win32":
        user_dir = Path.home() / ".local" / "share" / "vitarg" / "tools"
        user_dir.mkdir(parents=True, exist_ok=True)
        purge_windows_binaries(user_dir)
        return user_dir

    fallback = Path(tempfile.gettempdir()) / "vitarg_tools"
    fallback.mkdir(parents=True, exist_ok=True)
    purge_windows_binaries(fallback)
    return fallback


def download_stream(url: str, dest_path: Path) -> None:
    """Download a file with user-agent and safe streaming. Blocks .exe URLs on Linux."""
    if sys.platform != "win32":
        low_url = url.lower().split("?", 1)[0]
        if low_url.endswith(WINDOWS_EXTENSIONS):
            raise RuntimeError(f"Refusing to download Windows executable on Linux: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
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


def _resolve_btbn_linux_ffmpeg_url(arch: str) -> Optional[str]:
    """Query GitHub API for the latest BtbN static Linux GPL FFmpeg build."""
    token = "linuxarm64" if arch == "arm64" else "linux64"
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest",
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for a in data.get("assets", []):
                name = a.get("name", "").lower()
                if (
                    token in name
                    and "gpl" in name
                    and "shared" not in name
                    and "lgpl" not in name
                    and name.endswith(".tar.xz")
                    and not name.endswith(WINDOWS_EXTENSIONS)
                ):
                    return a.get("browser_download_url")
    except Exception:
        pass
    return None


def fetch_linux_ffmpeg(target_dir: Optional[Path] = None) -> tuple[Path, Path]:
    """Download standalone static Linux FFmpeg and FFprobe ELF binaries."""
    if sys.platform == "win32":
        raise RuntimeError("fetch_linux_ffmpeg is only supported on Linux.")

    tools_dir = target_dir or get_default_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)
    purge_windows_binaries(tools_dir)

    ffmpeg_bin = tools_dir / "ffmpeg"
    ffprobe_bin = tools_dir / "ffprobe"

    if is_valid_linux_binary(ffmpeg_bin) and is_valid_linux_binary(ffprobe_bin):
        make_executable(ffmpeg_bin)
        make_executable(ffprobe_bin)
        return ffmpeg_bin, ffprobe_bin

    arch = get_linux_arch()
    urls: list[str] = []
    api_url = _resolve_btbn_linux_ffmpeg_url(arch)
    if api_url:
        urls.append(api_url)

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

    # Deduplicate while preserving order
    seen_urls = set()
    unique_urls = [u for u in urls if not (u in seen_urls or seen_urls.add(u))]

    tmp_dir = Path(tempfile.mkdtemp(prefix="vitarg_ffmpeg_dl_"))
    tar_path = tmp_dir / "ffmpeg-linux.tar.xz"
    success = False

    try:
        for url in unique_urls:
            try:
                if tar_path.exists():
                    tar_path.unlink(missing_ok=True)
                download_stream(url, tar_path)
                with tarfile.open(tar_path, "r:xz") as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        base = os.path.basename(member.name)
                        if base.lower().endswith(WINDOWS_EXTENSIONS):
                            continue
                        if base in ("ffmpeg", "ffprobe") and member.size > 100_000:
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                tmp_bin = tmp_dir / f".tmp_{base}"
                                tmp_bin.write_bytes(f_obj.read())
                                if is_valid_linux_binary(tmp_bin):
                                    target = tools_dir / base
                                    os.replace(tmp_bin, target)
                                    make_executable(target)
                                else:
                                    tmp_bin.unlink(missing_ok=True)
                if is_valid_linux_binary(ffmpeg_bin) and is_valid_linux_binary(ffprobe_bin):
                    success = True
                    break
            except Exception:
                if tar_path.exists():
                    tar_path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not success or not is_valid_linux_binary(ffmpeg_bin) or not is_valid_linux_binary(ffprobe_bin):
        raise RuntimeError("Failed to download Linux standalone FFmpeg/FFprobe ELF binaries from GitHub/mirror.")

    make_executable(ffmpeg_bin)
    make_executable(ffprobe_bin)
    return ffmpeg_bin, ffprobe_bin


def fetch_linux_pandoc(target_dir: Optional[Path] = None) -> Path:
    """Download standalone static Linux Pandoc ELF binary."""
    if sys.platform == "win32":
        raise RuntimeError("fetch_linux_pandoc is only supported on Linux.")

    tools_dir = target_dir or get_default_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)
    purge_windows_binaries(tools_dir)

    pandoc_bin = tools_dir / "pandoc"

    if is_valid_linux_binary(pandoc_bin):
        make_executable(pandoc_bin)
        return pandoc_bin

    arch = get_linux_arch()
    arch_token = f"linux-{arch}"
    urls: list[str] = []

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/jgm/pandoc/releases/latest",
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for a in data.get("assets", []):
                name = a.get("name", "").lower()
                if arch_token in name and name.endswith(".tar.gz") and not name.endswith(WINDOWS_EXTENSIONS):
                    dl_url = a.get("browser_download_url")
                    if dl_url:
                        urls.append(dl_url)
                        break
    except Exception:
        pass

    urls.extend([
        f"https://github.com/jgm/pandoc/releases/download/3.14/pandoc-3.14-linux-{arch}.tar.gz",
        f"https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-{arch}.tar.gz",
    ])

    seen_urls = set()
    unique_urls = [u for u in urls if not (u in seen_urls or seen_urls.add(u))]

    tmp_dir = Path(tempfile.mkdtemp(prefix="vitarg_pandoc_dl_"))
    tar_path = tmp_dir / "pandoc-linux.tar.gz"
    success = False

    try:
        for pandoc_url in unique_urls:
            try:
                if tar_path.exists():
                    tar_path.unlink(missing_ok=True)
                download_stream(pandoc_url, tar_path)
                with tarfile.open(tar_path, "r:gz") as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        base = os.path.basename(member.name)
                        if base == "pandoc" and member.size > 100_000:
                            f_obj = tf.extractfile(member)
                            if f_obj:
                                tmp_bin = tmp_dir / ".tmp_pandoc"
                                tmp_bin.write_bytes(f_obj.read())
                                if is_valid_linux_binary(tmp_bin):
                                    os.replace(tmp_bin, pandoc_bin)
                                    make_executable(pandoc_bin)
                                    success = True
                                    break
                                else:
                                    tmp_bin.unlink(missing_ok=True)
                if success and is_valid_linux_binary(pandoc_bin):
                    break
            except Exception:
                if tar_path.exists():
                    tar_path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not success or not is_valid_linux_binary(pandoc_bin):
        raise RuntimeError("Failed to download Linux standalone Pandoc ELF binary.")

    make_executable(pandoc_bin)
    return pandoc_bin


def ensure_linux_tool(name: str) -> Optional[str]:
    """Ensure a tool is available on Linux by fetching its native Linux ELF binary if missing."""
    if sys.platform == "win32":
        return None

    clean_name = name.lower()
    for ext in WINDOWS_EXTENSIONS:
        if clean_name.endswith(ext):
            clean_name = clean_name[: -len(ext)]
            break

    tools_dir = get_default_tools_dir()
    purge_windows_binaries(tools_dir)

    if clean_name in ("ffmpeg", "ffprobe"):
        try:
            ff, fp = fetch_linux_ffmpeg(tools_dir)
            target = ff if clean_name == "ffmpeg" else fp
            if is_valid_linux_binary(target):
                return str(target)
        except Exception:
            return None
    elif clean_name == "pandoc":
        try:
            pd = fetch_linux_pandoc(tools_dir)
            if is_valid_linux_binary(pd):
                return str(pd)
        except Exception:
            return None

    return None
