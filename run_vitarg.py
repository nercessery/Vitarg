"""PyInstaller entry point for Vitarg."""
import os
import sys
import tempfile
import traceback
from pathlib import Path

if __name__ == "__main__":
    try:
        from vitarg.app import main
        sys.exit(main())
    except Exception as e:
        if "--selftest" in sys.argv:
            rep = Path(tempfile.gettempdir()) / "vitarg-selftest.txt"
            rep.write_text(f"STARTUP CRASH:\n{traceback.format_exc()}")
            sys.exit(5)
        raise
