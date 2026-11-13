"""Real frosted-glass: asks Windows DWM to blur whatever is behind the window (clipped to a rounded/round shape)."""
import sys


def apply(widget, shape: str = "round", radius: float = 26.0, inset: float = 0.0) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class DWM_BLURBEHIND(ctypes.Structure):
            _fields_ = [("dwFlags", wintypes.DWORD), ("fEnable", wintypes.BOOL),
                        ("hRgnBlur", wintypes.HRGN), ("fTransitionOnMaximized", wintypes.BOOL)]

        dpr = widget.devicePixelRatioF()
        w, h = int(widget.width() * dpr), int(widget.height() * dpr)
        i = int(inset * dpr)
        gdi = ctypes.windll.gdi32
        if shape == "ellipse":
            rgn = gdi.CreateEllipticRgn(i, i, w - i, h - i)
        else:
            r = int(radius * dpr * 2)
            rgn = gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        bb = DWM_BLURBEHIND(0x1 | 0x2, True, rgn, False)          # DWM_BB_ENABLE | DWM_BB_BLURREGION
        ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(wintypes.HWND(int(widget.winId())), ctypes.byref(bb))
        gdi.DeleteObject(rgn)
    except Exception:
        pass            # no blur available: the translucent painting still works
