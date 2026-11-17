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
    context_menu: bool = True            # Windows Explorer / Linux context menu integration
    cpu_mode: str = "eco"                # "eco" (max 40-50% CPU for smooth PC & gaming) | "full" (100% CPU)

    # ---- persistence -------------------------------------------------
    @staticmethod
    def path() -> Path:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.environ.get("APPDATA") or str(Path.home() / ".config")
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
        p = self.path()
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
    if sys.platform == "win32":
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
    elif sys.platform.startswith("linux"):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        autostart_dir = config_home / "autostart"
        desktop_file = autostart_dir / "vitarg.desktop"
        if enabled:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            exe = sys.executable if getattr(sys, "frozen", False) else f"{sys.executable} -m vitarg"
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Vitarg\n"
                "Comment=Vitarg File Converter & Toolkit\n"
                f"Exec={exe}\n"
                "Icon=vitarg\n"
                "Terminal=false\n"
                "Categories=Utility;\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            desktop_file.write_text(content, encoding="utf-8")
            try:
                desktop_file.chmod(0o755)
            except OSError:
                pass
        else:
            if desktop_file.exists():
                try:
                    desktop_file.unlink()
                except OSError:
                    pass


def create_desktop_shortcut() -> bool:
    if sys.platform == "win32":
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
    elif sys.platform.startswith("linux"):
        try:
            exe = sys.executable if getattr(sys, "frozen", False) else f"{sys.executable} -m vitarg"
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Vitarg\n"
                "Comment=Vitarg File Converter & Toolkit\n"
                f"Exec={exe}\n"
                "Icon=vitarg\n"
                "Terminal=false\n"
                "Categories=Utility;\n"
            )
            created = False
            desktop_dir = Path.home() / "Desktop"
            if desktop_dir.exists():
                desk_file = desktop_dir / "vitarg.desktop"
                desk_file.write_text(content, encoding="utf-8")
                try:
                    desk_file.chmod(0o755)
                except OSError:
                    pass
                created = True
            data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
            apps_dir = data_home / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            app_file = apps_dir / "vitarg.desktop"
            app_file.write_text(content, encoding="utf-8")
            try:
                app_file.chmod(0o755)
            except OSError:
                pass
            created = True
            return created
        except Exception:
            return False
    return False


def set_context_menu(enabled: bool) -> bool:
    """Register or unregister 'Convert with Vitarg' in the Windows Explorer or Linux file manager context menu."""
    if sys.platform == "win32":
        import winreg
        exe = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" -m vitarg'
        ico = str(Path(__file__).resolve().parent.parent / "assets" / "vitarg.ico")
        icon_arg = sys.executable if getattr(sys, "frozen", False) else (ico if os.path.exists(ico) else sys.executable)

        targets = [
            (winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell\Vitarg", f'{exe} "%1"'),
            (winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell\Vitarg", f'{exe} "%1"'),
            (winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\Background\shell\Vitarg", f'{exe} --select "%V"'),
            (winreg.HKEY_CURRENT_USER, r"Software\Classes\DesktopBackground\shell\Vitarg", f'{exe} --select "%V"'),
        ]

        try:
            if enabled:
                for root, key_path, cmd in targets:
                    with winreg.CreateKey(root, key_path) as k:
                        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Convert with Vitarg")
                        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon_arg)
                    with winreg.CreateKey(root, key_path + r"\command") as k:
                        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
                return True
            else:
                for root, key_path, _ in targets:
                    try:
                        winreg.DeleteKey(root, key_path + r"\command")
                    except (FileNotFoundError, OSError):
                        pass
                    try:
                        winreg.DeleteKey(root, key_path)
                    except (FileNotFoundError, OSError):
                        pass
                return True
        except Exception:
            return False
    elif sys.platform.startswith("linux"):
        try:
            exe = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" -m vitarg'
            nautilus_dir = Path.home() / ".local" / "share" / "nautilus" / "scripts"
            kde_dir = Path.home() / ".local" / "share" / "kio" / "servicemenus"
            script_path = nautilus_dir / "Convert with Vitarg"
            kde_path = kde_dir / "vitarg.desktop"
            if enabled:
                nautilus_dir.mkdir(parents=True, exist_ok=True)
                script_path.write_text(f'#!/bin/bash\n{exe} "$@"\n', encoding="utf-8")
                try:
                    script_path.chmod(0o755)
                except OSError:
                    pass
                kde_dir.mkdir(parents=True, exist_ok=True)
                kde_content = (
                    "[Desktop Entry]\n"
                    "Type=Service\n"
                    "ServiceTypes=KonqPopupMenu/Plugin\n"
                    "MimeType=all/allfiles;\n"
                    "Actions=VitargConvert;\n"
                    "\n"
                    "[Desktop Action VitargConvert]\n"
                    "Name=Convert with Vitarg\n"
                    "Icon=vitarg\n"
                    f"Exec={exe} %F\n"
                )
                kde_path.write_text(kde_content, encoding="utf-8")
                return True
            else:
                if script_path.exists():
                    script_path.unlink()
                if kde_path.exists():
                    kde_path.unlink()
                return True
        except Exception:
            return False
    return False
