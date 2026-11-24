"""Tiny immediate-mode GPU widget kit used by the studio interface.

The same *builder* code runs in two modes:

* drawing (``Builder(painter=Painter(region))``): widgets emit draw commands
* hit testing (``Builder(painter=None)``): only the clickable targets are kept

so the clickable areas always match what is on screen.
"""

import math

import blf
import bpy

# Colours (Mini CAD palette) ------------------------------------------------
COL_BG = (0.11, 0.11, 0.12, 0.94)
COL_HEADER = (0.14, 0.14, 0.15, 0.97)
COL_TITLE = (0.17, 0.17, 0.19, 0.98)
COL_BTN = (0.22, 0.22, 0.24, 1.0)
COL_HOVER = (0.31, 0.31, 0.35, 1.0)
COL_ON = (0.24, 0.44, 0.75, 1.0)
COL_ORANGE = (0.94, 0.54, 0.14, 1.0)
COL_ORANGE_BG = (0.23, 0.17, 0.11, 1.0)
COL_GREEN = (0.37, 0.88, 0.54, 1.0)
COL_TEXT = (0.92, 0.92, 0.93, 1.0)
COL_DIM = (0.62, 0.62, 0.66, 1.0)
COL_SECTION = (0.62, 0.74, 0.94, 1.0)
COL_EDGE = (0.05, 0.05, 0.06, 1.0)
COL_TRACK = (0.20, 0.20, 0.22, 1.0)
COL_DARK = (0.06, 0.06, 0.07, 1.0)

FONT = 0


def ui_scale():
    try:
        return max(0.5, bpy.context.preferences.system.ui_scale)
    except Exception:
        return 1.0


def set_size(size):
    try:
        blf.size(FONT, size)
    except TypeError:
        blf.size(FONT, size, 72)


def text_width(text, size):
    set_size(size)
    return blf.dimensions(FONT, text)[0]


def fit_text(text, size, max_w):
    if max_w <= 0:
        return ""
    if text_width(text, size) <= max_w:
        return text
    while text and text_width(text + "…", size) > max_w:
        text = text[:-1]
    return text + "…" if text else ""


def inside(rect, x, y):
    x0, y0, x1, y1 = rect
    return x0 <= x <= x1 and y0 <= y <= y1


# ---------------------------------------------------------------------------
# Painter: batches primitives into a few GPU draw calls
# ---------------------------------------------------------------------------

class Painter:
    def __init__(self, region):
        self.region = region
        self.reset()

    def reset(self):
        self.tri_pos, self.tri_col = [], []
        self.lines = {}
        self.texts = []
        self.images = []

    def rect(self, x0, y0, x1, y1, col):
        p = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y0, 0), (x1, y1, 0), (x0, y1, 0)]
        self.tri_pos += p
        self.tri_col += [col] * 6

    def poly(self, pts, col):
        if len(pts) < 3:
            return
        a = pts[0]
        for b, c in zip(pts[1:-1], pts[2:]):
            self.tri_pos += [(a[0], a[1], 0), (b[0], b[1], 0), (c[0], c[1], 0)]
            self.tri_col += [col] * 3

    def gradient_rect(self, x0, y0, x1, y1, cols):
        """Horizontal multi-stop gradient."""
        n = len(cols) - 1
        for i in range(n):
            a = x0 + (x1 - x0) * i / n
            b = x0 + (x1 - x0) * (i + 1) / n
            ca, cb = cols[i], cols[i + 1]
            self.tri_pos += [(a, y0, 0), (b, y0, 0), (b, y1, 0), (a, y0, 0), (b, y1, 0), (a, y1, 0)]
            self.tri_col += [ca, cb, cb, ca, cb, ca]

    def line(self, pts, col, width=1.0, closed=False):
        seg = self.lines.setdefault(round(width, 2), ([], []))
        pts = list(pts)
        if closed and pts:
            pts.append(pts[0])
        for a, b in zip(pts[:-1], pts[1:]):
            seg[0].extend([(a[0], a[1], 0), (b[0], b[1], 0)])
            seg[1].extend([col, col])

    def text(self, x, y, text, col=COL_TEXT, size=11, align='L'):
        self.texts.append((x, y, text, col, size, align))

    def image(self, texture, x0, y0, x1, y1):
        self.images.append((texture, x0, y0, x1, y1))

    def flush(self):
        import gpu
        from gpu_extras.batch import batch_for_shader
        gpu.state.blend_set('ALPHA')
        if self.tri_pos:
            sh = gpu.shader.from_builtin('SMOOTH_COLOR')
            batch = batch_for_shader(sh, 'TRIS', {"pos": self.tri_pos, "color": self.tri_col})
            batch.draw(sh)
        for tex, x0, y0, x1, y1 in self.images:
            sh = gpu.shader.from_builtin('IMAGE')
            batch = batch_for_shader(
                sh, 'TRIS',
                {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                 "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]},
                indices=[(0, 1, 2), (0, 2, 3)])
            sh.bind()
            sh.uniform_sampler("image", tex)
            batch.draw(sh)
        if self.lines:
            sh = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
            for width, (pos, col) in self.lines.items():
                batch = batch_for_shader(sh, 'LINES', {"pos": pos, "color": col})
                sh.bind()
                sh.uniform_float("viewportSize", (self.region.width, self.region.height))
                sh.uniform_float("lineWidth", width)
                batch.draw(sh)
        for x, y, text, col, size, align in self.texts:
            set_size(size)
            if align != 'L':
                w = blf.dimensions(FONT, text)[0]
                x -= w if align == 'R' else w / 2
            blf.color(FONT, *col)
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, text)
        gpu.state.blend_set('NONE')
        self.reset()


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class Target:
    __slots__ = ("rect", "id", "kind", "action", "tip", "data")

    def __init__(self, rect, id, kind, action=None, tip="", data=None):
        self.rect = rect
        self.id = id
        self.kind = kind
        self.action = action
        self.tip = tip
        self.data = data or {}


class Builder:
    def __init__(self, region, painter=None, hover_id=None, active_id=None):
        self.region = region
        self.p = painter
        self.s = ui_scale()
        self.targets = []
        self.hover_id = hover_id
        self.active_id = active_id
        self.blocks = []   # panel rectangles (block clicks to the canvas)

    # -- registration ------------------------------------------------------------
    def target(self, rect, id, kind, action=None, tip="", **data):
        t = Target(rect, id, kind, action, tip, data)
        self.targets.append(t)
        return t

    def hit(self, x, y):
        for t in reversed(self.targets):
            if inside(t.rect, x, y):
                return t
        return None

    def over_ui(self, x, y):
        return any(inside(r, x, y) for r in self.blocks)

    def hovered(self, id):
        return id is not None and (self.hover_id == id or self.active_id == id)

    # -- drawing primitives (no-ops without a painter) -----------------------------
    def rect(self, *a):
        if self.p:
            self.p.rect(*a)

    def frame(self, x0, y0, x1, y1, col, w=1.0):
        if self.p:
            self.p.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], col, w, closed=True)

    def text(self, *a, **k):
        if self.p:
            self.p.text(*a, **k)

    def flush(self):
        if self.p:
            self.p.flush()

    # -- widgets -----------------------------------------------------------------
    def button(self, rect, id, label="", action=None, on=False, tip="", style='normal',
               icon=None, size=None, align='C', enabled=True, trail=None):
        x0, y0, x1, y1 = rect
        s = self.s
        size = size or int(11 * s)
        if style == 'accent':
            col = COL_ON
        elif style == 'orange':
            col = COL_ORANGE
        elif style == 'card':
            col = COL_ORANGE_BG if on else (COL_HOVER if self.hovered(id) else (0.15, 0.15, 0.17, 1.0))
        else:
            col = COL_ON if on else (COL_HOVER if self.hovered(id) else COL_BTN)
        if style == 'orange' and self.hovered(id):
            col = (1.0, 0.64, 0.3, 1.0)
        self.rect(x0, y0, x1, y1, col)
        if style == 'card':
            self.frame(x0, y0, x1, y1, COL_ORANGE if on else (0.19, 0.19, 0.21, 1.0), 1.0)
        tcol = (0.1, 0.07, 0.02, 1.0) if style == 'orange' else (COL_TEXT if enabled else COL_DIM)
        if icon is not None and self.p:
            icon(self.p, (x0 + x1) / 2 if not label else x0 + (y1 - y0) / 2 + 2 * s,
                 (y0 + y1) / 2, min(x1 - x0, y1 - y0) * 0.6, tcol)
        if trail is not None and self.p:
            trail(self.p, x1 - (y1 - y0) / 2, (y0 + y1) / 2, (y1 - y0) * 0.7, tcol)
            x1 -= (y1 - y0) * 0.6
        if label:
            ty = (y0 + y1) / 2 - size * 0.36
            if align == 'C' and icon is None:
                self.text((x0 + x1) / 2, ty, fit_text(label, size, x1 - x0 - 6 * s), tcol, size, 'C')
            else:
                lx = x0 + (y1 - y0 + 2 * s if icon is not None else 7 * s)
                self.text(lx, ty, fit_text(label, size, x1 - lx - 4 * s), tcol, size)
        return self.target(rect, id, 'button', action, tip)

    def segmented(self, rect, id, items, current, setter, tips=None, icons=None):
        x0, y0, x1, y1 = rect
        n = len(items)
        w = (x1 - x0) / n
        gap = 2 * self.s
        for i, (key, label) in enumerate(items):
            bx0 = x0 + i * w + (gap / 2 if i else 0)
            bx1 = x0 + (i + 1) * w - (gap / 2 if i < n - 1 else 0)
            self.button((bx0, y0, bx1, y1), f"{id}:{key}", label,
                        action=(lambda k: (lambda ctx, ev: setter(k)))(key),
                        on=current == key, tip=(tips or {}).get(key, ""),
                        icon=(icons or {}).get(key))

    def slider(self, rect, id, label, value, vmin, vmax, setter, fmt="{:.2f}",
               tip="", track=None, step=None, soft=True):
        """Horizontal value slider. Drag to change, wheel to nudge."""
        x0, y0, x1, y1 = rect
        s = self.s
        size = int(10.5 * s)
        hov = self.hovered(id)
        self.text(x0, y1 - size, label, COL_TEXT if hov else (0.78, 0.78, 0.8, 1.0), size)
        self.text(x1, y1 - size, fmt.format(value), COL_TEXT, size, 'R')
        ty0, ty1 = y0, y0 + 7 * s
        if track is not None:
            if self.p:
                self.p.gradient_rect(x0, ty0, x1, ty1, track)
        else:
            self.rect(x0, ty0, x1, ty1, COL_TRACK if not hov else (0.27, 0.27, 0.3, 1.0))
        t = 0.0 if vmax == vmin else (value - vmin) / (vmax - vmin)
        t = max(0.0, min(1.0, t))
        if track is None:
            self.rect(x0, ty0, x0 + (x1 - x0) * t, ty1, COL_ON)
        kx = x0 + (x1 - x0) * t
        self.rect(kx - 2 * s, ty0 - 2 * s, kx + 2 * s, ty1 + 2 * s, COL_TEXT)
        step = step if step is not None else (vmax - vmin) / 100.0
        return self.target(rect, id, 'slider', None, tip, x0=x0, x1=x1, vmin=vmin,
                           vmax=vmax, setter=setter, value=value, step=step)

    def section(self, x, y, w, label, id=None, open_=True, toggle=None):
        s = self.s
        size = int(9.5 * s)
        h = 19 * s
        tx = x
        if toggle:
            if self.p:
                icon_tri('down' if open_ else 'right')(self.p, x + 4 * s, y - h + 8 * s, 12 * s,
                                                       COL_SECTION)
            tx = x + 12 * s
        self.text(tx, y - h + 5 * s, label, COL_SECTION, size)
        if toggle:
            self.target((x, y - h, x + w, y), id, 'button', toggle)
        return y - h - 3 * s

    # -- panels ----------------------------------------------------------------
    def panel_bg(self, rect, title=None, title_id=None, collapsed=False, extra=None):
        """Draw a floating panel frame; returns the content top y."""
        x0, y0, x1, y1 = rect
        s = self.s
        self.blocks.append(rect)
        self.rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1, COL_EDGE)
        self.rect(x0, y0, x1, y1, COL_BG)
        self.target(rect, (title_id or "panel") + ":bg", 'panel')
        if title is None:
            return y1
        th = 22 * s
        self.rect(x0, y1 - th, x1, y1, COL_TITLE)
        size = int(10.5 * s)
        self.text(x0 + 8 * s, y1 - th + 7 * s, fit_text(title, size, x1 - x0 - 50 * s),
                  COL_TEXT, size)
        # chevron = collapse
        if self.p:
            icon_tri('right' if collapsed else 'down')(
                self.p, x1 - 13 * s, y1 - th / 2, 16 * s,
                COL_TEXT if self.hovered(title_id + ":fold") else COL_DIM)
        self.target((x0, y1 - th, x1 - 26 * s, y1), title_id + ":title", 'title')
        self.target((x1 - 26 * s, y1 - th, x1, y1), title_id + ":fold", 'fold')
        return y1 - th


# ---------------------------------------------------------------------------
# Icons (drawn with lines / polys, sized to ``sz``)
# ---------------------------------------------------------------------------

def _circle(cx, cy, r, n=20, a0=0.0, a1=math.tau):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def icon_move(p, cx, cy, sz, col):
    h = sz / 2
    p.line([(cx - h, cy), (cx + h, cy)], col, 1.6)
    p.line([(cx, cy - h), (cx, cy + h)], col, 1.6)
    a = sz * 0.18
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        tx, ty = cx + dx * h, cy + dy * h
        p.line([(tx - dx * a - dy * a, ty - dy * a - dx * a), (tx, ty),
                (tx - dx * a + dy * a, ty - dy * a + dx * a)], col, 1.6)


def icon_scale(p, cx, cy, sz, col):
    h = sz / 2
    p.line([(cx - h, cy - h), (cx + h, cy + h)], col, 1.6)
    a = sz * 0.3
    p.line([(cx + h - a, cy + h), (cx + h, cy + h), (cx + h, cy + h - a)], col, 1.6)
    p.line([(cx - h + a, cy - h), (cx - h, cy - h), (cx - h, cy - h + a)], col, 1.6)


def icon_rotate(p, cx, cy, sz, col):
    r = sz * 0.42
    pts = _circle(cx, cy, r, 18, 0.3, math.tau - 0.6)
    p.line(pts, col, 1.6)
    ex, ey = pts[-1]
    a = sz * 0.2
    p.line([(ex - a, ey + a * 0.2), (ex, ey), (ex + a * 0.1, ey + a)], col, 1.6)


def icon_add(p, cx, cy, sz, col):
    h = sz * 0.42
    p.line([(cx - h, cy), (cx + h, cy)], col, 2.0)
    p.line([(cx, cy - h), (cx, cy + h)], col, 2.0)


def icon_paint(p, cx, cy, sz, col):
    p.line(_circle(cx, cy, sz * 0.42), col, 1.6)
    p.line(_circle(cx, cy, sz * 0.16, 10), col, 1.6)
    h = sz * 0.55
    p.line([(cx - h, cy), (cx - sz * 0.3, cy)], col, 1.4)
    p.line([(cx + sz * 0.3, cy), (cx + h, cy)], col, 1.4)


def icon_eye(p, cx, cy, sz, col, on=True):
    w, h = sz * 0.5, sz * 0.28
    top = [(cx - w + 2 * w * i / 12, cy + h * math.sin(math.pi * i / 12)) for i in range(13)]
    bot = [(cx - w + 2 * w * i / 12, cy - h * math.sin(math.pi * i / 12)) for i in range(13)]
    p.line(top, col, 1.3)
    p.line(bot, col, 1.3)
    if on:
        p.poly(_circle(cx, cy, sz * 0.13, 10), col)
    else:
        p.line([(cx - w, cy - h * 1.3), (cx + w, cy + h * 1.3)], col, 1.3)


def icon_tri(direction):
    """Small filled triangle: 'down', 'right', 'left', 'up'."""
    def draw(p, cx, cy, sz, col):
        h = sz * 0.32
        pts = {'down': [(cx - h, cy + h * 0.5), (cx + h, cy + h * 0.5), (cx, cy - h * 0.6)],
               'up': [(cx - h, cy - h * 0.5), (cx + h, cy - h * 0.5), (cx, cy + h * 0.6)],
               'right': [(cx - h * 0.5, cy - h), (cx - h * 0.5, cy + h), (cx + h * 0.6, cy)],
               'left': [(cx + h * 0.5, cy - h), (cx + h * 0.5, cy + h), (cx - h * 0.6, cy)]}[direction]
        p.poly(pts, col)
    return draw


def icon_dot(col_override=None):
    def draw(p, cx, cy, sz, col):
        p.poly(_circle(cx, cy, sz * 0.2, 12), col_override or col)
    return draw


def icon_check(p, cx, cy, sz, col):
    h = sz * 0.3
    p.line([(cx - h, cy), (cx - h * 0.3, cy - h * 0.7), (cx + h, cy + h * 0.7)], col, 1.8)


def shape_icon(shape, w=1.0, h=1.0, blend='ADD', outline=False):
    """Return an icon drawer for a light shape with aspect ``w``:``h``."""
    def draw(p, cx, cy, sz, col):
        m = max(w, h) or 1.0
        hw, hh = sz * 0.5 * w / m, sz * 0.5 * h / m
        hw, hh = max(hw, sz * 0.07), max(hh, sz * 0.07)
        fill = (0.07, 0.07, 0.08, 1.0) if blend != 'ADD' and not outline else (0.93, 0.93, 0.95, 1.0)
        if shape in ('ELLIPSE', 'RING'):
            pts = [(cx + hw * math.cos(a), cy + hh * math.sin(a))
                   for a in (math.tau * i / 24 for i in range(25))]
        elif shape == 'OCTAGON':
            pts = [(cx + hw * math.cos(a), cy + hh * math.sin(a))
                   for a in (math.pi / 8 + math.pi / 4 * i for i in range(9))]
        else:
            pts = [(cx - hw, cy - hh), (cx + hw, cy - hh), (cx + hw, cy + hh), (cx - hw, cy + hh)]
        if outline:
            p.line(pts, COL_GREEN, 1.2, closed=True)
        elif shape == 'RING':
            p.line(pts, fill, max(2.0, sz * 0.12))
        else:
            p.poly(pts, fill)
            if blend != 'ADD':
                p.line(pts, (0.5, 0.5, 0.52, 1.0), 1.0, closed=True)
    return draw
