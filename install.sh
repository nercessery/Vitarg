#!/bin/bash
# Vitarg Linux Setup Wizard Launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Hata: python3 bulunamadı. Lütfen Python 3.10+ kurun (örn: sudo apt install python3 python3-venv python3-tk)."
    exit 1
fi

exec python3 "$SCRIPT_DIR/installer/setup_wizard.py" "$@"
