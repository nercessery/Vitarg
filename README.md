# 🔮 Vitarg

A fast, lightweight, and modern **drag-and-drop file converter & toolkit** for Windows and Linux. Hold a trigger key while dragging files in your file manager — a sleek obsidian dark glass radial wheel appears — drop on a wedge to convert, resize, or process files instantly.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Linux](https://img.shields.io/badge/platform-Linux%20(X11%20%2F%20Wayland)-orange)
![Theme](https://img.shields.io/badge/theme-Obsidian%20Glass%20%2B%20Royal%20Purple-7C3AED)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

### 🔄 File Conversion (Shift + Drag)
| Category | Formats |
|---|---|
| **Image** | PNG, JPG, WebP, BMP, TIFF, GIF, ICO, HEIC, SVG → each other, PDF, DOCX |
| **Audio** | MP3, WAV, FLAC, AAC, OGG, M4A, OPUS, WMA, AIFF, AC3, ALAC, AMR |
| **Video** | MP4, MKV, MOV, AVI, WebM, WMV, FLV (+ GIF output, audio extraction) |
| **Document** | PDF ↔ DOCX/JPG/PNG/TXT, TXT/MD/HTML/DOCX ↔ each other |
| **Archive** | ZIP, TAR, GZ, 7Z |

### 🛠️ Tools Wheel (Alt + Shift + Drag)
- **Inspector** — Deep file inspector: view metadata, resolution, aspect ratio, duration, codecs, SHA-256 hash, and EXIF tags.
- **Compress** — Multi-pass compression for images, audio, video, and PDFs (lossless & balanced modes).
- **Resize** — Scale resolution up/down for images, videos, and PDFs (by percentage or exact pixels with aspect ratio locking).
- **Metadata** — Strip all EXIF / ID3 / media metadata cleanly.
- **Edit** — Real-time brightness, contrast, saturation, and sharpness enhancement.
- **Crop** — High-performance 60 FPS visual crop editor with aspect ratio presets.
- **Add Background** — Place transparent images on custom solid color backgrounds with padding.
- **Normalize** — EBU R128 audio loudness normalization.
- **Trim** — Precise audio/video cutting with dual waveform and frame preview.
- **Remove Audio** — Strip audio stream from video with zero video re-encoding.
- **Speed** — High-quality video speed adjustment (0.25x – 4x) with pitch-corrected audio.
- **Snapshot** — Capture exact video frames at any timestamp into PNG.
- **Split/Merge PDF** — Split documents into separate pages or combine multiple PDFs.
- **Create PDF** — Merge multiple images into a multi-page PDF.
- **Collage** — Arrange photos into responsive grid collages.
- **Join Videos** — Concat multiple video files with automatic aspect matching.
- **Extract** — One-click unpack for ZIP, TAR, GZ, and 7Z archives.
- **Target Size (Target Compress)** — Target-size 2-pass H.264 video compression for Discord (<25 MB), Discord Nitro (<50 MB), Email (<10 MB), WhatsApp (<8 MB), or custom target MB limits.
- **Volume Boost** — Amplify audio volume from 10% up to 600% with live waveform preview and 2-second audio sample audition.
- **Audio Equalizer** — 6-preset audio equalization (Bass Boost, Ultra Bass, Vocal Boost, Treble Boost, Loudness & Clarity, Flat) with real-time waveform display.
- **Extract Text** — Extract text from PDF documents and images (with OCR support) directly to `.txt` files, clipboard, or both.

### ⚡ Smart Productivity Tools
- **Undo / Rollback (Ctrl+Z)** — Revert the last operation with one click from the completion dialog, tray menu, or Settings. Safely deletes generated files and restores any backed-up originals.
- **Pre-Action Rename & Custom Naming** — Review and customize output file names or apply smart templates (`{name}_{date}`, `{name}_{num}`, `{name}-vitarg`) before converting or running tools, with live output preview and automatic extension handling.
- **Conversion Preview & Size Estimator** — Real-time estimation of output file size and quality ratio before and during processing.
- **Visual PDF Organizer & Multi-File Drop** — Interactive visual reordering modal for merging PDFs and compiling images into PDF with drag-and-drop page sequencing, thumbnail previews, page deletion, and custom naming.
- **Clipboard Quick Convert Popup** — Convert and export image data directly from the system clipboard to any supported format (PNG, JPG, WebP, PDF) via the tray icon or drop target menu.
- **Size Difference & Visual Stats Card** — Post-conversion statistics card in the completion dialog displaying exact before/after file sizes, percentage savings, and saved disk space with color-coded feedback.
- **Desktop Context Menu Integration** — Seamless right-click file manager integration ("Convert with Vitarg") for Windows Explorer, GNOME/Nautilus scripts, and KDE Plasma/Dolphin ServiceMenus.
- **Live Audio Sample Preview** — Interactive 2-second audio sample audition directly inside tool configuration dialogs (Volume Boost, EQ) before applying conversion.

---

## 🎨 Design & Theme
- **Soft Obsidian Dark Glass**: Translucent, modern dark glass materials with continuous rounded corners.
- **Royal Deep Purple Accents**: Vibrant purple accents (`#7C3AED`) and glowing radial highlights.
- **Full Customization**: Live opacity, tint color, highlight color, and corner radius sliders in Settings.
- **Preset Slots**: 3 customizable and saveable look presets.

---

## ⚡ Auto-Update System
Vitarg features an **integrated GitHub Releases auto-updater**:
- Checks for new releases in the background on startup (or manually via tray / Settings).
- Shows release notes and downloads the update directly from GitHub with a live progress bar.
- Launches the installer automatically and restarts Vitarg with zero manual download hassle!

---

## 📥 Download & Installation

Visit the [**Releases**](../../releases) page:

### 🪟 Windows
Download **`Vitarg-Setup.exe`**:
- Installs to `Program Files\Vitarg`
- Automatically creates a desktop shortcut with the Vitarg purple icon
- Adds a Start Menu shortcut
- Registers a clean Windows uninstaller in Apps & Features

### 🐧 Linux (Ubuntu, Debian, Fedora, Arch)
Download **`Vitarg-linux-x86_64.tar.gz`**:
- Unpack and run `./Vitarg`
- Fully standalone PyInstaller distribution with all dependencies and Qt platform plugins bundled
- Out-of-the-box support for both **X11** and **Wayland** desktops (GNOME, KDE Plasma, XFCE, Cinnamon)

---

## 🚀 Usage

### On Windows:
1. Launch `Vitarg.exe` — a tray icon appears in the Windows system tray.
2. Drag any file in Windows Explorer or Desktop:
   - Hold **Shift** while dragging → **Conversion Wheel**
   - Hold **Alt + Shift** while dragging → **Tools Wheel**
3. Drop the file onto your desired action petal.
4. Output is generated cleanly in seconds without modifying the source file.

### On Linux (X11 & Wayland):
1. Launch `./Vitarg` — a system tray icon appears (or a floating drop target if system tray is unavailable in your desktop environment).
2. Multiple invocation methods:
   - **Floating Drop Target**: Drag files from Nautilus, Dolphin, Thunar, or Nemo onto the on-screen `+` target widget.
   - **System Tray**: Right-click the tray icon to select "Select Files to Convert…" or toggle the floating drop target.
   - **CLI / File Manager "Open With"**: Run `vitarg <file1> <file2>` from terminal or link Vitarg as a file handler. Single-instance socket IPC automatically forwards files to the running instance and displays the radial wheel.
   - **Wayland Center Fallback**: Automatically opens the radial action wheel at the screen center if global mouse coordinate tracking is restricted by your Wayland compositor.

---

## 🔧 Building from Source

### Prerequisites
- **Windows**: Windows 10/11 (x64), Python 3.10+ (3.12 recommended), Inno Setup (optional, for setup installer)
- **Linux**: Ubuntu 22.04+ / Fedora 38+ / Arch Linux, Python 3.10+, FFmpeg, Pandoc

### Windows Build
```powershell
git clone https://github.com/nercessery/Vitarg.git
cd Vitarg
.\scripts\build.ps1
```
The automated script will initialize the environment, bundle FFmpeg/Pandoc, execute the 194-test suite, and compile `dist\Vitarg-Setup.exe`.

### Linux Build
```bash
git clone https://github.com/nercessery/Vitarg.git
cd Vitarg
sudo apt-get update && sudo apt-get install -y ffmpeg pandoc \
  libgl1 libegl1 libxkbcommon-x11-0 libxcb*
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
pyinstaller --noconfirm --clean --windowed --name Vitarg \
  --add-data "assets:assets" \
  --collect-all pillow_heif --collect-all py7zr --collect-all fitz --collect-all pymupdf \
  run_vitarg.py
```

---

## 📄 License
MIT License. Free and open source.
