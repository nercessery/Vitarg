"""Persistent settings + trigger (hotkey) configuration and conflict detection."""
from __future__ import annotations
import json, os, sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

MODIFIERS = ["CTRL", "ALT", "SHIFT", "WIN"]
LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
FKEYS = [f"F{i}" for i in range(1, 13)]
EXTRA_KEYS = LETTERS + FKEYS + ["SPACE", "CAPSLOCK"]
ORDER = MODIFIERS + EXTRA_KEYS

# Virtual-key codes (a name may map to several codes, e.g. left/right Win)
VK = {"CTRL": [0x11], "ALT": [0x12], "SHIFT": [0x10], "WIN": [0x5B, 0x5C],
      "SPACE": [0x20], "CAPSLOCK": [0x14]}
VK.update({c: [ord(c)] for c in LETTERS})
VK.update({f"F{i}": [0x6F + i] for i in range(1, 13)})

DEFAULT_CONV = ["SHIFT"]
DEFAULT_TOOLS = ["ALT", "SHIFT"]


def normalize(keys) -> list[str]:
    ks = {k.upper() for k in keys if k and k.upper() in VK}
    return sorted(ks, key=ORDER.index)


def label(keys) -> str:
    return " + ".join(k.capitalize() if len(k) > 1 and k not in FKEYS else k for k in normalize(keys)) or "(none)"


# Combos that Windows or nearly every app already uses; these are rejected.
RESERVED = [
    ({"ALT"}, "F4"), ({"CTRL"}, "C"), ({"CTRL"}, "V"), ({"CTRL"}, "X"), ({"CTRL"}, "Z"),
    ({"CTRL"}, "A"), ({"CTRL"}, "S"), ({"CTRL"}, "W"), ({"ALT"}, "SPACE"), ({"CTRL"}, "SPACE"),
]
DRAG_NOTES = {
    "CTRL": "Ctrl during a drag makes Explorer copy files.",
    "ALT": "Alt during a drag makes Explorer create shortcuts.",
    "SHIFT": "Shift during a drag makes Explorer move files (Vitarg always copies).",
}


def validate(conv, tools) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block saving; warnings are informational."""
    errors, warnings = [], []
    c, t = set(normalize(conv)), set(normalize(tools))
    for name, s in (("Conversion wheel", c), ("Tools wheel", t)):
        if not s:
            errors.append(f"{name}: choose at least one key.")
            continue
        extras = [k for k in s if k in EXTRA_KEYS]
        if len(extras) > 1:
            errors.append(f"{name}: use at most one non-modifier key.")
        if s == {"WIN"}:
            errors.append(f"{name}: the Windows key alone opens the Start menu.")
        if not (s & set(MODIFIERS)) and extras:
            errors.append(f"{name}: add a modifier (Ctrl/Alt/Shift/Win) to the key.")
        for mods, key in RESERVED:
            if s == mods | {key}:
                errors.append(f"{name}: {label(s)} is reserved by Windows or most applications.")
        if "WIN" in s and extras:
            errors.append(f"{name}: Win+{extras[0]} is a Windows system shortcut.")
    if c and t:
        if c == t:
            errors.append("Both wheels use the same trigger. Choose different combinations.")
        elif c < t or t < c:
            warnings.append("One trigger is contained in the other, so the smaller wheel may "
                            "flash briefly while you press the larger combination.")
    for s in (c, t):
        for k, note in DRAG_NOTES.items():
            if s == {k} and note not in warnings:
                warnings.append(note)
    return errors, warnings


@dataclass
class Settings:
    conv_trigger: list = field(default_factory=lambda: list(DEFAULT_CONV))
    tools_trigger: list = field(default_factory=lambda: list(DEFAULT_TOOLS))
    output_mode: str = "source"          # "source" = beside the original, "folder" = custom folder
    output_folder: str = ""
    overwrite: str = "never"             # "never" -> "name 2.ext"; "overwrite" replaces
    jpg_quality: int = 92
    webp_quality: int = 90
    video_crf: int = 20
    audio_bitrate_k: int = 192
    compress_preset: str = "Balanced"    # Balanced | Strong
    sound: bool = True
    opacity: int = 75                    # glass opacity in percent (soft see-through)
    tint: str = "#12111A"                # soft obsidian black glass tint
    highlight: str = "#7C3AED"           # colour of the hovered wheel petal (royal deep purple)
    text_color: str = "#F5F5F7"          # label / text colour
    radius: int = 28                     # panel corner radius
    appearance_slots: list = field(default_factory=lambda: [{}, {}, {}])   # saved looks; {} = empty slot
    active_slot: int = -1                # last slot loaded/saved (-1 = none)
    launch_at_login: bool = False
    enabled: bool = True
    auto_update: bool = True             # automatically check for updates on startup
    prompt_rename: bool = True           # prompt to review/edit file name before running

    # ---- persistence -------------------------------------------------
    @staticmethod
    def path() -> Path:
        base = os.environ.get("APPDATA") or str(Path.home() / ".config")
        return Path(base) / "Vitarg" / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        p = cls.path()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k) and type(getattr(s, k)) is type(v):
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        slots = [x if isinstance(x, dict) else {} for x in s.appearance_slots][:3]
        s.appearance_slots = slots + [{}] * (3 - len(slots))
        s.conv_trigger = normalize(s.conv_trigger) or list(DEFAULT_CONV)
        s.tools_trigger = normalize(s.tools_trigger) or list(DEFAULT_TOOLS)
        if validate(s.conv_trigger, s.tools_trigger)[0]:      # corrupted/conflicting file
            s.conv_trigger, s.tools_trigger = list(DEFAULT_CONV), list(DEFAULT_TOOLS)
        return s

    def save(self) -> None:
        base = os.environ.get("APPDATA") or str(Path.home() / ".config")
        p = Path(base) / "Vitarg" / "settings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, p)

    # ---- appearance (applied live, saved without closing anything) ------
    APPEARANCE_KEYS = ("opacity", "tint", "highlight", "text_color", "radius")

    def appearance(self) -> dict:
        return {k: getattr(self, k) for k in self.APPEARANCE_KEYS}

    def set_appearance(self, d: dict) -> None:
        for k in self.APPEARANCE_KEYS:
            if k in d and type(d[k]) is type(getattr(self, k)):
                setattr(self, k, d[k])

    def reset_appearance(self) -> None:
        d = Settings()
        self.set_appearance(d.appearance())

    def reset_triggers(self) -> None:
        self.conv_trigger, self.tools_trigger = list(DEFAULT_CONV), list(DEFAULT_TOOLS)

    def reset_all(self) -> None:
        self.__dict__.update(Settings().__dict__)


def set_launch_at_login(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            exe = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" -m vitarg'
            winreg.SetValueEx(key, "Vitarg", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, "Vitarg")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def create_desktop_shortcut() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = shell.SpecialFolders("Desktop")
        shortcut_path = os.path.join(desktop, "Vitarg.lnk")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.TargetPath = sys.executable
        if not getattr(sys, "frozen", False):
            shortcut.Arguments = "-m vitarg"
        shortcut.WorkingDirectory = os.path.dirname(sys.executable)
        shortcut.IconLocation = sys.executable
        shortcut.Description = "Vitarg File Converter & Toolkit"
        shortcut.Save()
        return True
    except Exception:
        return False
