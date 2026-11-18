#!/bin/bash
# Fetch conversion tools for Linux (FFmpeg, FFprobe, Pandoc)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 "$SCRIPT_DIR/fetch_tools.py" --dest "$REPO_ROOT/tools"
