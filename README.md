# 🔮 Vitarg

A fast, lightweight, and modern **drag-and-drop file converter & toolkit** for Windows. Hold a trigger key while dragging files in Explorer — a sleek obsidian dark glass radial wheel appears — drop on a wedge to convert, resize, or process files instantly.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Theme](https://img.shields.io/badge/theme-Obsidian%20Glass%20%2B%20Royal%20Purple-7C3AED)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

### 🔄 File Conversion (Shift + Drag)
| Category | Formats |
|---|---|
| **Image** | PNG, JPG, WebP, BMP, TIFF, GIF, ICO, HEIC, SVG → each other, PDF, DOCX |
| **Audio** | MP3, WAV, FLAC, AAC, OGG, M4A, OPUS, WMA, AIFF |
| **Video** | MP4, MKV, MOV, AVI, WebM, WMV, FLV (+ GIF output, audio extraction) |
| **Document** | PDF ↔ DOCX/JPG/PNG/TXT, TXT/MD/HTML/DOCX ↔ each other |
| **Archive** | ZIP, TAR, GZ, 7Z |

### 🛠️ Tools Wheel (Alt + Shift + Drag)
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

Visit the [**Releases**](../../releases) page and download **`Vitarg-Setup.exe`**.

The official installer:
- Installs to `Program Files\Vitarg`
- Automatically creates a desktop shortcut with the Vitarg purple icon
- Adds a Start Menu shortcut
- Registers a clean Windows uninstaller in Apps & Features

---

## 🚀 Usage

1. Launch `Vitarg.exe` — a tray icon appears in the Windows system tray.
2. Drag any file in Windows Explorer or Desktop:
   - Hold **Shift** while dragging → **Conversion Wheel**
   - Hold **Alt + Shift** while dragging → **Tools Wheel**
3. Drop the file onto your desired action petal.
4. Output is generated cleanly in seconds without modifying the source file.

---

## 🔧 Building from Source

### Prerequisites
- Windows 10/11 (x64)
- Python 3.10+ (3.12 recommended)

### Quick Build
```powershell
git clone https://github.com/nercessery/Vitarg.git
cd Vitarg
build.bat
```

The automated build script will:
1. Initialize virtual environment and install dependencies.
2. Fetch FFmpeg, FFprobe, and Pandoc tools with UPX compression.
3. Run the complete automated test suite.
4. Bundle with PyInstaller using optimized module exclusions.
5. Compile `dist\Vitarg-Setup.exe` using Inno Setup ultra solid LZMA2 compression.

---

## 📄 License
MIT License. Free and open source.
