#!/usr/bin/env python3
"""Vitarg Linux Setup Wizard (GUI with automatic terminal fallback).
Installs Vitarg natively on Linux:
- Copies Vitarg to ~/.local/share/vitarg (or custom directory)
- Creates isolated Python venv and installs Linux dependencies
- Downloads native Linux ELF binaries (ffmpeg, ffprobe, pandoc)
- Creates ~/.local/bin/vitarg launcher, Desktop shortcut, App Menu entry,
  File Manager right-click integration (GNOME/KDE/Nemo/Caja), and Autostart entry.
"""
from __future__ import annotations
import os
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "share" / "vitarg"
BIN_DIR = Path.home() / ".local" / "bin"


def _get_desktop_dir() -> Path:
    home = Path.home()
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config")) / "user-dirs.dirs"
    if cfg.is_file():
        try:
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("XDG_DESKTOP_DIR="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    val = val.replace("$HOME", str(home)).replace("${HOME}", str(home))
                    p = Path(val)
                    if p.is_dir():
                        return p
        except Exception:
            pass
    for cand in (home / "Desktop", home / "Masaüstü"):
        if cand.is_dir():
            return cand
    return home / "Desktop"


def perform_install(
    install_dir: Path,
    create_desktop: bool = True,
    create_context_menu: bool = True,
    enable_autostart: bool = False,
    fetch_linux_tools: bool = True,
    log_cb=print,
    progress_cb=lambda pct: None,
) -> Path:
    """Execute the full Linux installation pipeline and return the launcher path."""
    install_dir = Path(install_dir).expanduser().resolve()
    progress_cb(5)
    log_cb(f"Hedef kurulum dizini: {install_dir}")

    # 1. Copy application files
    install_dir.mkdir(parents=True, exist_ok=True)
    for rel in ("vitarg", "assets", "scripts", "installer", "run_vitarg.py", "README.md"):
        src = SOURCE_ROOT / rel
        dst = install_dir / rel
        if not src.exists():
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
    progress_cb(20)
    log_cb("Uygulama dosyaları kopyalandı.")

    # 2. Create Python virtual environment and install Linux packages
    venv_dir = install_dir / ".venv"
    venv_py = venv_dir / "bin" / "python3"
    if not venv_py.exists():
        log_cb("Python sanal ortamı (.venv) oluşturuluyor...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    progress_cb(35)

    log_cb("Linux Python bağımlılıkları kuruluyor (PySide6, Pillow, PyMuPDF, pypdf, python-docx, py7zr)...")
    subprocess.run(
        [
            str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "--quiet",
        ],
        check=False,
    )
    subprocess.run(
        [
            str(venv_py), "-m", "pip", "install", "--quiet",
            "PySide6", "pillow", "pillow_heif", "py7zr", "python-docx", "pymupdf", "pypdf", "requests",
        ],
        check=True,
    )
    progress_cb(65)
    log_cb("Python kütüphaneleri hazır.")

    # 3. Fetch standalone Linux ELF tools (ffmpeg, ffprobe, pandoc)
    tools_dir = install_dir / "tools"
    if fetch_linux_tools:
        log_cb("Linux ELF dönüştürme araçları (ffmpeg, ffprobe, pandoc) indiriliyor...")
        try:
            subprocess.run(
                [str(venv_py), str(install_dir / "scripts" / "fetch_tools.py"), "--dest", str(tools_dir)],
                check=True,
            )
            log_cb("Linux ELF araçları doğrulandı ve kuruldu.")
        except Exception as e:
            log_cb(f"Uyarı: Araçlar indirilemedi ({e}). Sistemdeki ffmpeg/pandoc kullanılacak.")
    progress_cb(85)

    # 4. Create ~/.local/bin/vitarg Linux launcher script
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    launcher = BIN_DIR / "vitarg"
    launcher.write_text(
        "#!/bin/bash\n"
        f'exec "{venv_py}" "{install_dir / "run_vitarg.py"}" "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    log_cb(f"Linux başlatıcısı oluşturuldu: {launcher}")

    # 5. Desktop entry & Application Menu
    icon_path = install_dir / "assets" / "vitarg.png"
    mime_types = (
        "image/png;image/jpeg;image/webp;image/bmp;image/tiff;image/svg+xml;image/heic;"
        "audio/mpeg;audio/wav;audio/flac;audio/ogg;audio/aac;audio/mp4;audio/opus;"
        "video/mp4;video/x-matroska;video/quicktime;video/x-msvideo;video/webm;"
        "application/pdf;application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
        "text/plain;text/markdown;text/html;application/zip;application/x-tar;application/gzip;application/x-7z-compressed;"
    )
    desktop_entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Vitarg\n"
        "Comment=Vitarg Linux File Converter & Toolkit\n"
        f'Exec="{launcher}" %F\n'
        f"Icon={icon_path}\n"
        "Terminal=false\n"
        "Categories=Utility;AudioVideo;Graphics;\n"
        f"MimeType={mime_types}\n"
    )
    apps_dir = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    app_desktop = apps_dir / "vitarg.desktop"
    app_desktop.write_text(desktop_entry, encoding="utf-8")
    app_desktop.chmod(0o755)

    if create_desktop:
        ddir = _get_desktop_dir()
        if ddir.exists():
            dfile = ddir / "vitarg.desktop"
            dfile.write_text(desktop_entry, encoding="utf-8")
            dfile.chmod(0o755)
            log_cb(f"Masaüstü kısayolu oluşturuldu: {dfile}")

    # 6. Autostart
    autostart_dir = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "autostart"
    autostart_file = autostart_dir / "vitarg.desktop"
    if enable_autostart:
        autostart_dir.mkdir(parents=True, exist_ok=True)
        autostart_file.write_text(
            desktop_entry.replace(f'Exec="{launcher}" %F', f'Exec="{launcher}"')
            + "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        autostart_file.chmod(0o755)
        log_cb("Otomatik başlatma (autostart) etkinleştirildi.")
    elif autostart_file.exists():
        autostart_file.unlink(missing_ok=True)

    # 7. Linux File Manager Context Menu (Nautilus, Nemo, Caja, Dolphin/KDE)
    if create_context_menu:
        script_content = (
            "#!/bin/bash\n"
            "files=()\n"
            'if [ "$#" -gt 0 ]; then\n'
            '    for f in "$@"; do [ -e "$f" ] && files+=("$f"); done\n'
            "fi\n"
            'if [ "${#files[@]}" -eq 0 ] && [ -n "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" ]; then\n'
            '    while IFS= read -r f; do [ -n "$f" ] && [ -e "$f" ] && files+=("$f"); done <<< "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"\n'
            "fi\n"
            f'exec "{launcher}" "${{files[@]}}"\n'
        )
        for sdir in (
            Path.home() / ".local" / "share" / "nautilus" / "scripts",
            Path.home() / ".local" / "share" / "nemo" / "scripts",
            Path.home() / ".config" / "caja" / "scripts",
        ):
            try:
                sdir.mkdir(parents=True, exist_ok=True)
                sp = sdir / "Convert with Vitarg"
                sp.write_text(script_content, encoding="utf-8")
                sp.chmod(0o755)
            except Exception:
                pass

        kde_content = (
            "[Desktop Entry]\n"
            "Type=Service\n"
            "ServiceTypes=KonqPopupMenu/Plugin\n"
            "X-KDE-ServiceTypes=KonqPopupMenu/Plugin\n"
            "MimeType=all/allfiles;\n"
            "Actions=VitargConvert;VitargTools;\n\n"
            "[Desktop Action VitargConvert]\n"
            "Name=Convert with Vitarg\n"
            f"Icon={icon_path}\n"
            f'Exec="{launcher}" %F\n\n'
            "[Desktop Action VitargTools]\n"
            "Name=Vitarg Tools\n"
            f"Icon={icon_path}\n"
            f'Exec="{launcher}" --tools %F\n'
        )
        for kdir in (
            Path.home() / ".local" / "share" / "kio" / "servicemenus",
            Path.home() / ".local" / "share" / "kservices5" / "ServiceMenus",
        ):
            try:
                kdir.mkdir(parents=True, exist_ok=True)
                kp = kdir / "vitarg.desktop"
                kp.write_text(kde_content, encoding="utf-8")
                kp.chmod(0o755)
            except Exception:
                pass
        log_cb("Dosya yöneticisi sağ tık menüsü entegrasyonu tamamlandı.")

    progress_cb(100)
    log_cb("Kurulum başarıyla tamamlandı! 'vitarg' komutu veya uygulama menüsüyle başlatabilirsiniz.")
    return launcher


def run_tk_wizard() -> bool:
    """Run sleek Obsidian Dark + Royal Purple Linux GUI Setup Wizard using stdlib tkinter."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except Exception:
        return False

    root = tk.Tk()
    root.title("Vitarg Linux Setup Wizard")
    root.geometry("560x480")
    root.resizable(False, False)
    root.configure(bg="#12111A")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TProgressbar", troughcolor="#1E1B2E", background="#7C3AED", bordercolor="#12111A")

    tk.Label(
        root, text="🔮 Vitarg — Linux Kurulum Sihirbazı",
        bg="#12111A", fg="#F5F5F7", font=("Sans", 15, "bold"),
    ).pack(pady=(18, 4))
    tk.Label(
        root, text="Tamamen Linux'a özel kurulum (ELF ikilileri, .desktop kısayolları ve sağ tık menüsü)",
        bg="#12111A", fg="#A78BFA", font=("Sans", 9),
    ).pack(pady=(0, 14))

    dir_frame = tk.Frame(root, bg="#12111A")
    dir_frame.pack(fill="x", padx=24, pady=4)
    tk.Label(dir_frame, text="Kurulum Dizini:", bg="#12111A", fg="#E5E7EB", font=("Sans", 10)).pack(anchor="w")
    path_row = tk.Frame(dir_frame, bg="#12111A")
    path_row.pack(fill="x", pady=(4, 0))
    dir_var = tk.StringVar(value=str(DEFAULT_INSTALL_DIR))
    entry = tk.Entry(path_row, textvariable=dir_var, bg="#1E1B2E", fg="#FFFFFF", insertbackground="#FFFFFF", relief="flat", bd=6)
    entry.pack(side="left", fill="x", expand=True)

    def _browse():
        d = filedialog.askdirectory(initialdir=dir_var.get())
        if d:
            dir_var.set(d)

    tk.Button(
        path_row, text="Gözat…", command=_browse,
        bg="#2D2844", fg="#FFFFFF", activebackground="#7C3AED", relief="flat", padx=12, pady=4,
    ).pack(side="left", padx=(8, 0))

    opts = tk.Frame(root, bg="#12111A")
    opts.pack(fill="x", padx=24, pady=12)
    v_desktop = tk.BooleanVar(value=True)
    v_ctx = tk.BooleanVar(value=True)
    v_auto = tk.BooleanVar(value=False)
    v_tools = tk.BooleanVar(value=True)
    v_launch = tk.BooleanVar(value=True)

    for text, var in (
        ("Masaüstü kısayolu oluştur (.desktop)", v_desktop),
        ("Dosya yöneticisi sağ tık menüsüne ekle (GNOME/KDE/Nemo/Caja)", v_ctx),
        ("Linux açılışında otomatik başlat (Autostart)", v_auto),
        ("Linux ELF FFmpeg, FFprobe ve Pandoc ikililerini indir", v_tools),
        ("Kurulum bitince Vitarg'ı başlat", v_launch),
    ):
        tk.Checkbutton(
            opts, text=text, variable=var,
            bg="#12111A", fg="#E5E7EB", selectcolor="#2D2844",
            activebackground="#12111A", activeforeground="#FFFFFF", font=("Sans", 10),
        ).pack(anchor="w", pady=2)

    bar = ttk.Progressbar(root, orient="horizontal", length=510, mode="determinate", maximum=100)
    bar.pack(padx=24, pady=(4, 6))

    log_box = tk.Text(root, height=7, bg="#0B0A10", fg="#C4B5FD", relief="flat", font=("Monospace", 9), state="disabled")
    log_box.pack(fill="x", padx=24, pady=(0, 12))

    def append_log(msg: str):
        def _do():
            log_box.configure(state="normal")
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        root.after(0, _do)

    def set_prog(val: int):
        root.after(0, lambda: bar.configure(value=val))

    btn_frame = tk.Frame(root, bg="#12111A")
    btn_frame.pack(fill="x", padx=24)

    install_btn = tk.Button(
        btn_frame, text="Kurulumu Başlat ⚡", bg="#7C3AED", fg="#FFFFFF",
        activebackground="#6D28D9", relief="flat", font=("Sans", 10, "bold"), padx=18, pady=7,
    )
    close_btn = tk.Button(
        btn_frame, text="Kapat", command=root.destroy, bg="#2D2844", fg="#FFFFFF",
        activebackground="#3F385C", relief="flat", font=("Sans", 10), padx=14, pady=7,
    )
    close_btn.pack(side="left")
    install_btn.pack(side="right")

    def start_install():
        install_btn.configure(state="disabled", text="Kuruluyor…")

        def _worker():
            try:
                launcher = perform_install(
                    Path(dir_var.get()),
                    create_desktop=v_desktop.get(),
                    create_context_menu=v_ctx.get(),
                    enable_autostart=v_auto.get(),
                    fetch_linux_tools=v_tools.get(),
                    log_cb=append_log,
                    progress_cb=set_prog,
                )
                def _done():
                    install_btn.configure(text="Kuruldu ✓", state="disabled")
                    if v_launch.get():
                        subprocess.Popen([str(launcher)], start_new_session=True)
                    messagebox.showinfo("Vitarg Linux", "Vitarg kurulumu başarıyla tamamlandı!")
                    root.destroy()
                root.after(0, _done)
            except Exception as exc:
                append_log(f"HATA: {exc}")
                root.after(0, lambda: (
                    install_btn.configure(state="normal", text="Tekrar Dene"),
                    messagebox.showerror("Kurulum Hatası", str(exc)),
                ))

        threading.Thread(target=_worker, daemon=True).start()

    install_btn.configure(command=start_install)
    root.mainloop()
    return True


def run_cli_wizard() -> int:
    print("==============================================")
    print("   🔮 Vitarg — Linux Kurulum Sihirbazı (CLI)  ")
    print("==============================================")
    if "--yes" in sys.argv or "-y" in sys.argv:
        install_dir = DEFAULT_INSTALL_DIR
        create_desktop, create_ctx, autostart, fetch_tools = True, True, False, True
    else:
        raw_dir = input(f"Kurulum dizini [{DEFAULT_INSTALL_DIR}]: ").strip()
        install_dir = Path(raw_dir) if raw_dir else DEFAULT_INSTALL_DIR
        create_desktop = input("Masaüstü kısayolu oluşturulsun mu? [E/h]: ").strip().lower() != "h"
        create_ctx = input("Dosya yöneticisi sağ tık menüsüne eklensin mi? [E/h]: ").strip().lower() != "h"
        autostart = input("Linux açılışında otomatik başlasın mı? [e/H]: ").strip().lower() == "e"
        fetch_tools = input("Linux ELF ffmpeg/ffprobe/pandoc indirilsin mi? [E/h]: ").strip().lower() != "h"

    perform_install(
        install_dir,
        create_desktop=create_desktop,
        create_context_menu=create_ctx,
        enable_autostart=autostart,
        fetch_linux_tools=fetch_tools,
    )
    return 0


def main() -> int:
    if "--cli" not in sys.argv and "--yes" not in sys.argv and "-y" not in sys.argv:
        if run_tk_wizard():
            return 0
    return run_cli_wizard()


if __name__ == "__main__":
    sys.exit(main())
