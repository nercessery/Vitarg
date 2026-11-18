#!/bin/bash
# Vitarg Linux Uninstaller
set -euo pipefail

INSTALL_DIR="${1:-$HOME/.local/share/vitarg}"

echo "Vitarg Linux kaldırılıyor..."
rm -rf "$INSTALL_DIR"
rm -f "$HOME/.local/bin/vitarg"
rm -f "$HOME/.local/share/applications/vitarg.desktop"
rm -f "$HOME/.config/autostart/vitarg.desktop"
rm -f "$HOME/Desktop/vitarg.desktop" "$HOME/Masaüstü/vitarg.desktop"
rm -f "$HOME/.local/share/nautilus/scripts/Convert with Vitarg"
rm -f "$HOME/.local/share/nemo/scripts/Convert with Vitarg"
rm -f "$HOME/.config/caja/scripts/Convert with Vitarg"
rm -f "$HOME/.local/share/kio/servicemenus/vitarg.desktop"
rm -f "$HOME/.local/share/kservices5/ServiceMenus/vitarg.desktop"

echo "Vitarg Linux sistemden temizlendi."
