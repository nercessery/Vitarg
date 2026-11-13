"""Pure crop-rectangle maths (no Qt). Rects are (left, top, right, bottom) in image pixels."""
RATIOS = {"Free": None, "1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4}
MIN = 8.0


def fit_ratio(rect, ratio, bounds):
    """Shrink rect around its centre to the given ratio (w/h), staying inside bounds."""
    if not ratio:
        return rect
    l, t, r, b = rect
    cx, cy, w, h = (l + r) / 2, (t + b) / 2, r - l, b - t
    if w / h > ratio:
        w = h * ratio
    else:
        h = w / ratio
    return _centered(cx, cy, w, h, ratio, bounds)


def _centered(cx, cy, w, h, ratio, bounds):
    bl, bt, br, bb = bounds
    maxw = 2 * min(cx - bl, br - cx)
    maxh = 2 * min(cy - bt, bb - cy)
    if ratio:
        s = min(1.0, maxw / w if w else 1, maxh / h if h else 1)
        w, h = w * s, h * s
    else:
        w, h = min(w, maxw), min(h, maxh)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def move(rect, dx, dy, bounds):
    l, t, r, b = rect
    w, h = r - l, b - t
    l = min(max(l + dx, bounds[0]), bounds[2] - w)
    t = min(max(t + dy, bounds[1]), bounds[3] - h)
    return (l, t, l + w, t + h)


def resize(rect, handle, pos, ratio, bounds):
    l, t, r, b = rect
    bl, bt, br, bb = bounds
    x = min(max(pos[0], bl), br)
    y = min(max(pos[1], bt), bb)
    if not ratio:
        if "l" in handle: l = min(x, r - MIN)
        if "r" in handle: r = max(x, l + MIN)
        if "t" in handle: t = min(y, b - MIN)
        if "b" in handle: b = max(y, t + MIN)
        return (l, t, r, b)
    if len(handle) == 2:                                   # corner with locked ratio
        ax = r if "l" in handle else l
        ay = b if "t" in handle else t
        sx = -1 if "l" in handle else 1
        sy = -1 if "t" in handle else 1
        w = max(abs(x - ax), abs(y - ay) * ratio, MIN)
        max_w = (ax - bl) if sx < 0 else (br - ax)
        max_h = (ay - bt) if sy < 0 else (bb - ay)
        w = min(w, max_w, max_h * ratio)
        h = w / ratio
        x2, y2 = ax + sx * w, ay + sy * h
        return (min(ax, x2), min(ay, y2), max(ax, x2), max(ay, y2))
    cx, cy = (l + r) / 2, (t + b) / 2                      # edge with locked ratio
    if handle in ("l", "r"):
        w = max((x - l) if handle == "r" else (r - x), MIN)
        h = w / ratio
        s = min(1.0, 2 * min(cy - bt, bb - cy) / h)
        w, h = w * s, h * s
        return (l, cy - h / 2, l + w, cy + h / 2) if handle == "r" else (r - w, cy - h / 2, r, cy + h / 2)
    h = max((y - t) if handle == "b" else (b - y), MIN)
    w = h * ratio
    s = min(1.0, 2 * min(cx - bl, br - cx) / w)
    w, h = w * s, h * s
    return (cx - w / 2, t, cx + w / 2, t + h) if handle == "b" else (cx - w / 2, b - h, cx + w / 2, b)


def set_size(rect, w, h, ratio, bounds, changed):
    """Apply typed W/H (px). changed = 'w' or 'h'. Keeps the top-left corner when possible."""
    l, t, _, _ = rect
    bl, bt, br, bb = bounds
    if changed == "w":
        w = min(max(w, MIN), br - bl)
        h = w / ratio if ratio else (rect[3] - rect[1])
    else:
        h = min(max(h, MIN), bb - bt)
        w = h * ratio if ratio else (rect[2] - rect[0])
    w, h = min(w, br - bl), min(h, bb - bt)
    if ratio:
        s = min(1.0, (br - bl) / w, (bb - bt) / h)
        w, h = w * s, h * s
    l = min(max(l, bl), br - w)
    t = min(max(t, bt), bb - h)
    return (l, t, l + w, t + h)


def hit_handle(rect, pos, tol):
    """Return 'tl','t',...,'move' or None for a pointer position (all in the same units)."""
    l, t, r, b = rect
    cx, cy = (l + r) / 2, (t + b) / 2
    pts = {"tl": (l, t), "tr": (r, t), "bl": (l, b), "br": (r, b),
           "t": (cx, t), "b": (cx, b), "l": (l, cy), "r": (r, cy)}
    for name in ("tl", "tr", "bl", "br", "t", "b", "l", "r"):
        px, py = pts[name]
        if abs(pos[0] - px) <= tol and abs(pos[1] - py) <= tol:
            return name
    if l <= pos[0] <= r and t <= pos[1] <= b:
        return "move"
    return None
