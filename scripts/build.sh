#!/bin/bash
# One-step Linux build script for Vitarg:
# venv -> dependencies -> fetch Linux ELF tools (FFmpeg, FFprobe, Pandoc) -> PyInstaller -> self-test -> tar.gz package
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== [1/5] Preparing Python Virtual Environment ==="
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
python3 -m pip install --upgrade pip --quiet
python3 -m pip install PySide6 pillow pillow_heif py7zr python-docx pymupdf pypdf requests pyinstaller --quiet

echo "=== [2/5] Fetching Standalone Linux ELF Conversion Tools (FFmpeg, FFprobe, Pandoc) ==="
python3 "$SCRIPT_DIR/fetch_tools.py" --dest "$REPO_ROOT/tools"
chmod +x "$REPO_ROOT/tools/ffmpeg" "$REPO_ROOT/tools/ffprobe" "$REPO_ROOT/tools/pandoc"

echo "=== [3/5] Building Standalone Linux ELF Binary with PyInstaller ==="
rm -rf build dist
pyinstaller --noconfirm --clean --windowed --name Vitarg \
    --add-data "assets:assets" --add-data "tools:tools" \
    --collect-all pillow_heif --collect-all py7zr --collect-all fitz --collect-all pymupdf \
    run_vitarg.py

mkdir -p dist/Vitarg/tools
cp -r tools/* dist/Vitarg/tools/ || true
chmod -R +x dist/Vitarg/tools/ || true
chmod +x dist/Vitarg/Vitarg

echo "=== [4/5] Running Offscreen Self-Test ==="
QT_QPA_PLATFORM=offscreen ./dist/Vitarg/Vitarg --selftest
cat /tmp/vitarg-selftest.txt
echo ""

echo "=== [5/5] Packaging dist/Vitarg-linux-x86_64.tar.gz ==="
tar -czvf dist/Vitarg-linux-x86_64.tar.gz -C dist Vitarg
echo "=== Build Completed Successfully: dist/Vitarg-linux-x86_64.tar.gz ==="
