# 🔮 Vitarg

A fast, lightweight, and modern **drag-and-drop file converter & toolkit** for Windows and Linux. Hold a trigger key while dragging files in your file manager — a sleek obsidian dark glass radial wheel appears — drop on a wedge to convert, resize, or process files instantly.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Linux](https://img.shields.io/badge/platform-Linux-orange)
![Theme](https://img.shields.io/badge/theme-Obsidian%20Glass%20%2B%20Royal%20Purple-7C3AED)

---

## ✨ Features

### 🔄 File Conversion (Shift + Drag)
| Category | Formats |
|---|---|
| **Image** | PNG, JPG, WebP, BMP, TIFF, ICO, HEIC, SVG → each other, PDF, DOCX |
| **Audio** | MP3, WAV, FLAC, AAC, OGG, M4A, OPUS, WMA, AIFF, AC3, ALAC, AMR |
| **Video** | MP4, MKV, MOV, AVI, WebM, WMV, FLV (audio extraction) |
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
- **Target Size (Target Compress)** — Target-size 2-pass H.264 video compression for 25 MB, 50 MB, 10 MB, 8 MB, or custom target MB limits.
- **Volume Boost** — Amplify audio volume from 10% up to 600% with live waveform preview and 2-second audio sample audition.
- **Audio Equalizer** — 6-preset audio equalization (Bass Boost, Ultra Bass, Vocal Boost, Treble Boost, Loudness & Clarity, Flat) with real-time waveform display.
- **Extract Text** — Extract text from PDF documents and images (with OCR support) directly to `.txt` files, clipboard, or both.

### ⚡ Smart Productivity Tools
- **CPU Throttling Switch (Eco Mode)** — Smooth background CPU Eco Mode preserves system performance and prevents game/PC lag during conversions.
- **Undo / Rollback (Ctrl+Z)** — Revert the last operation with one click from the completion dialog, tray menu, or Settings. Safely deletes generated files and restores any backed-up originals.
- **Pre-Action Rename & Custom Naming** — Review and customize output file names or apply smart templates (`{name}_{date}`, `{name}_{num}`, `{name}-vitarg`) before converting or running tools, with live output preview and automatic extension handling.
- **Conversion Preview & Size Estimator** — Real-time estimation of output file size and quality ratio before and during processing.
- **Visual PDF Organizer & Multi-File Drop** — Interactive visual reordering modal for merging PDFs and compiling images into PDF with drag-and-drop page sequencing, thumbnail previews, page deletion, and custom naming.
- **Clipboard Quick Convert Popup** — Convert and export image data directly from the system clipboard to any supported format (PNG, JPG, WebP, PDF) via the tray icon or drop target menu.
- **Size Difference & Visual Stats Card** — Post-conversion statistics card in the completion dialog displaying exact before/after file sizes, percentage savings, and saved disk space with color-coded feedback.
- **Desktop Context Menu Integration** — Seamless right-click file manager integration ("Convert with Vitarg") for Windows Explorer and Linux desktop environments.
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

### 🐧 Linux
Download **`Vitarg-linux-x86_64.tar.gz`**:
- Unpack and run `./Vitarg`
- Standalone distribution with all native dependencies and statically-linked ELF conversion tools bundled.

Or run the interactive Linux Setup Wizard from source:
```bash
chmod +x install.sh
./install.sh
```

---

## 🚀 Usage

### 🎯 The Interactive Radial Wheel
- **Trigger**: Drag any file in your file manager and press **Shift** (Conversion Wheel) or **Alt + Shift** (Tools Wheel) — or drag onto the **Floating Drop Target**.
- **Persistent Latching**: Once the wheel appears, releasing Shift or the mouse button keeps the wheel open. Take your time to review options!
- **Interactive Center Toggle**: Click or drop files onto the center circle (or press `Tab`) to instantly flip between **Convert ↔ Tools**.
- **Execute**: Drop or click on any petal to run that action.
- **Dismiss**: Click outside the wheel or press `Esc`.

### On Windows:
1. Launch `Vitarg.exe` — a tray icon appears in the Windows system tray.
2. Drag any file in Windows Explorer or Desktop:
   - Hold **Shift** while dragging → **Conversion Wheel**
   - Hold **Alt + Shift** while dragging → **Tools Wheel**
3. Right-click context menu: Right-click files in Windows Explorer → "Convert with Vitarg".

### On Linux (X11 & Wayland):
1. Launch `./Vitarg` (or `./vitarg.sh`) — a tray icon appears.
2. Drag files in Nautilus, Dolphin, Nemo, Caja or onto the Floating Drop Target.
3. Right-click context menu: Native scripts integrated into GNOME Nautilus, KDE Dolphin, Nemo, and Caja.

---

## 🔧 Building from Source

### Prerequisites
- **Windows**: Windows 10/11 (x64), Python 3.10+ (3.12 recommended), Inno Setup (optional, for setup installer)
- **Linux**: Linux 64-bit (Ubuntu, Fedora, Arch, etc.), Python 3.10+

### Windows Build
```powershell
git clone https://github.com/nercessery/Vitarg.git
cd Vitarg
.\scripts\build.ps1
```
The automated script will initialize the environment, bundle FFmpeg/Pandoc, and compile `dist\Vitarg-Setup.exe`.

### Linux Build
```bash
git clone https://github.com/nercessery/Vitarg.git
cd Vitarg
chmod +x build.sh
./build.sh
```
The one-step Linux build script handles virtual environment setup, standalone Linux ELF tool fetching, PyInstaller compilation, offscreen self-test, and packages `dist/Vitarg-linux-x86_64.tar.gz`.
```
