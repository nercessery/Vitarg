"""Undo / Rollback manager for Vitarg: tracks recent file operations and safely reverts them."""
from __future__ import annotations
import os, shutil, sys, tempfile, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def notify_explorer(paths):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        for d in {str(Path(p).parent) for p in paths if p}:
            ctypes.windll.shell32.SHChangeNotify(0x00001000, 0x0005, ctypes.c_wchar_p(d), None)
    except Exception:
        pass


@dataclass
class UndoAction:
    description: str
    created_files: list[str] = field(default_factory=list)
    backups: list[tuple[str, str]] = field(default_factory=list)  # (backup_temp_file, original_target_file)
    timestamp: float = field(default_factory=time.time)


class UndoManager:
    """Singleton undo manager keeping track of operations."""
    _instance: Optional[UndoManager] = None

    def __init__(self, max_history: int = 15):
        self.history: list[UndoAction] = []
        self.max_history = max_history
        self._backup_dir = Path(tempfile.gettempdir()) / "vitarg-backups"
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.prune_stale_backups()

    def prune_stale_backups(self, max_age_days: int = 7) -> int:
        """Remove any backup file or folder older than max_age_days (default 7 days)."""
        if not self._backup_dir.exists():
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        try:
            for item in self._backup_dir.iterdir():
                try:
                    if item.stat().st_mtime < cutoff:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
                        removed += 1
                except Exception:
                    pass
        except Exception:
            pass
        return removed

    @classmethod
    def get(cls) -> UndoManager:
        if cls._instance is None:
            cls._instance = UndoManager()
        return cls._instance

    def record(self, description: str, created_files: list[str],
               overwritten_targets: Optional[list[str]] = None) -> UndoAction:
        backups = []
        if overwritten_targets:
            try:
                self._backup_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            for tgt in overwritten_targets:
                tp = Path(tgt)
                if tp.exists():
                    try:
                        bname = f"backup_{int(time.time()*1000)}_{tp.name}"
                        bpath = self._backup_dir / bname
                        shutil.copy2(tp, bpath)
                        backups.append((str(bpath), str(tp)))
                    except Exception:
                        pass
        action = UndoAction(
            description=description,
            created_files=[str(Path(f).resolve()) for f in created_files if f],
            backups=backups
        )
        self.history.append(action)
        if len(self.history) > self.max_history:
            oldest = self.history.pop(0)
            self._cleanup_action_backups(oldest)
        return action

    def _cleanup_action_backups(self, action: UndoAction):
        for bpath, _ in action.backups:
            try:
                Path(bpath).unlink(missing_ok=True)
            except Exception:
                pass

    def can_undo(self) -> bool:
        return len(self.history) > 0

    def last_description(self) -> str:
        if not self.history:
            return ""
        return self.history[-1].description

    def undo(self) -> tuple[bool, str, list[str]]:
        """Undo the last recorded action. Returns (success, message, affected_paths)."""
        if not self.history:
            return False, "No actions to undo", []
        action = self.history.pop()
        affected = []
        errors = []

        # 1. Delete created output files
        for fpath in action.created_files:
            p = Path(fpath)
            if p.exists():
                try:
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    affected.append(fpath)
                except Exception as e:
                    errors.append(f"Failed to delete {p.name}: {e}")

        # 2. Restore overwritten files
        for bpath, orig in action.backups:
            bp, op = Path(bpath), Path(orig)
            if bp.exists():
                try:
                    shutil.copy2(bp, op)
                    bp.unlink(missing_ok=True)
                    affected.append(orig)
                except Exception as e:
                    errors.append(f"Failed to restore {op.name}: {e}")

        # 3. Notify Windows Explorer of folder changes
        notify_explorer(affected + [f for f in action.created_files])

        if errors:
            msg = f"Partial undo for '{action.description}': {'; '.join(errors)}"
            return False, msg, affected
        return True, f"Successfully undone: {action.description}", affected


undo_manager = UndoManager.get()
