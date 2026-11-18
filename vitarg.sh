#!/bin/bash
# Direct Linux launcher for Vitarg (creates .venv automatically on first run if needed)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/run_vitarg.py" "$@"
fi

if command -v python3 >/dev/null 2>&1 && python3 -c "import PySide6, PIL" 2>/dev/null; then
    exec python3 "$SCRIPT_DIR/run_vitarg.py" "$@"
fi

echo "İlk çalıştırma için Python sanal ortamı (.venv) hazırlanıyor..."
python3 -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/python3" -m pip install --upgrade pip --quiet
"$SCRIPT_DIR/.venv/bin/python3" -m pip install --quiet PySide6 pillow pillow_heif py7zr python-docx pymupdf pypdf requests
exec "$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/run_vitarg.py" "$@"
