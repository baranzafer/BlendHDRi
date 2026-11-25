"""Procedural HDRI rasterizer.

Everything here is pure numpy so it can run (and be tested) without the UI.
Coordinates follow Blender/Cycles' equirectangular convention:

    u = 0.5 - atan2(y, x) / (2*pi)
    v = 0.5 + asin(z) / pi

with pixel row 0 at the *bottom* of the image (Blender's pixel order).
Light positions are stored as longitude/latitude in radians where
longitude = atan2(y, x) and latitude = asin(z).
"""

import math

import numpy as np

TAU = math.tau
MAX_LIGHT_ANGLE = math.radians(170.0)


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def lonlat_to_dir(lon, lat):
    cl = math.cos(lat)
    return (cl * math.cos(lon), cl * math.sin(lon), math.sin(lat))


def dir_to_lonlat(d):
    x, y, z = d
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    z = max(-1.0, min(1.0, z / length))
    return math.atan2(y, x), math.asin(z)


def lonlat_to_uv(lon, lat):
    u = (0.5 - lon / TAU) % 1.0
    v = 0.5 + lat / math.pi
    return u, v


def uv_to_lonlat(u, v):
    lon = (0.5 - u) * TAU
    lon = (lon + math.pi) % TAU - math.pi
    lat = (min(max(v, 0.0), 1.0) - 0.5) * math.pi
    return lon, lat


def wrap_lon(lon):
    return (lon + math.pi) % TAU - math.pi


def light_basis(lon, lat, roll):
    """Return (L, T, B): light direction plus tangent frame (rolled)."""
    cl, sl = math.cos(lat), math.sin(lat)
    co, so = math.cos(lon), math.sin(lon)
    L = (cl * co, cl * so, sl)
    east = (-so, co, 0.0)
    north = (-sl * co, -sl * so, cl)
    cr, sr = math.cos(roll), math.sin(roll)
    T = tuple(cr * e + sr * n for e, n in zip(east, north))
    B = tuple(-sr * e + cr * n for e, n in zip(east, north))
    return L, T, B


def kelvin_to_rgb(kelvin):
    """Approximate black body colour, normalised so max channel == 1."""
    t = max(1000.0, min(40000.0, kelvin)) / 100.0
    if t <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19.0 else 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
        b = 255.0
    rgb = [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    # sRGB-ish -> linear
    rgb = [c ** 2.2 for c in rgb]
    m = max(rgb) or 1.0
    return tuple(c / m for c in rgb)


# ---------------------------------------------------------------------------
# Light description (decoupled from bpy so the renderer is testable)
# ---------------------------------------------------------------------------

class LightData:
    __slots__ = (
        "shape", "blend", "lon", "lat", "roll", "width", "height",
        "softness", "roundness", "ring_inner", "falloff", "gradient",
        "rgb", "opacity", "tex",
        "grad_type", "grad_angle", "grad_offset", "grad_scale", "grad_mid",
        "grad_interp", "grad_a", "grad_b",
    )

    def __init__(self, **kw):
        self.shape = kw.get("shape", "RECT")
        self.blend = kw.get("blend", "ADD")
        self.lon = kw.get("lon", 0.0)
        self.lat = kw.get("lat", 0.0)
        self.roll = kw.get("roll", 0.0)
        self.width = kw.get("width", math.radians(30))
        self.height = kw.get("height", math.radians(30))
        self.softness = kw.get("softness", 0.1)
        self.roundness = kw.get("roundness", 0.0)
        self.ring_inner = kw.get("ring_inner", 0.7)
        self.falloff = kw.get("falloff", 0.0)
        self.gradient = kw.get("gradient", 0.0)
        self.rgb = kw.get("rgb", (1.0, 1.0, 1.0))
        self.opacity = kw.get("opacity", 1.0)
        self.tex = kw.get("tex", None)  # (h, w, 4) float array or None
        self.grad_type = kw.get("grad_type", 'NONE')
        self.grad_angle = kw.get("grad_angle", math.pi / 2)
        self.grad_offset = kw.get("grad_offset", 0.0)
        self.grad_scale = kw.get("grad_scale", 1.0)
        self.grad_mid = kw.get("grad_mid", 0.5)
        self.grad_interp = kw.get("grad_interp", 'LINEAR')
        self.grad_a = kw.get("grad_a", (1.0, 1.0, 1.0))
        self.grad_b = kw.get("grad_b", (0.0, 0.0, 0.0))
        if self.grad_type == 'NONE' and self.gradient != 0.0:
            # legacy single value: brightness 1-g at the bottom, 1+g at the top
            g = self.gradient
            self.grad_type = 'LINEAR'
            self.grad_angle = math.pi / 2
            self.grad_a = (1.0 - g,) * 3
            self.grad_b = (1.0 + g,) * 3

    @classmethod
    def from_prop(cls, p):
        rgb = tuple(p.color)
        if p.use_temperature:
            k = kelvin_to_rgb(p.temperature)
            rgb = tuple(a * b for a, b in zip(rgb, k))
        if p.blend != 'MULTIPLY':
            rgb = tuple(c * p.intensity for c in rgb)
        grad = {}
        gtype = getattr(p, "gradient_type", 'NONE')
        if gtype != 'NONE':
            grad = dict(
                grad_type=gtype, grad_angle=p.gradient_angle,
                grad_offset=p.gradient_offset, grad_scale=p.gradient_scale,
                grad_mid=p.gradient_midpoint, grad_interp=p.gradient_interp,
                grad_a=tuple(c * p.gradient_value_a for c in p.gradient_color_a),
                grad_b=tuple(c * p.gradient_value_b for c in p.gradient_color_b))
        return cls(
            shape=p.shape, blend=p.blend, lon=p.lon, lat=p.lat, roll=p.roll,
            width=p.width, height=p.height, softness=p.softness,
            roundness=p.roundness, ring_inner=p.ring_inner,
            falloff=p.falloff, gradient=p.gradient if gtype == 'NONE' else 0.0,
            rgb=rgb, opacity=p.opacity, **grad,
        )

    # Shape helpers --------------------------------------------------------
    def tan_half(self):
        w = min(max(self.width, 1e-4), MAX_LIGHT_ANGLE)
        h = min(max(self.height, 1e-4), MAX_LIGHT_ANGLE)
        return math.tan(w * 0.5), math.tan(h * 0.5)

    def edge_extent(self):
        """How far (in normalised light units) the soft edge reaches outwards."""
        return 1.0 + max(0.0, self.softness - 1.0) * 0.5

    def angular_radius(self):
        tw, th = self.tan_half()
        e = self.edge_extent()
        # include the bloom of very soft edges; the light is a cap < 90°
        return min(math.atan(math.sqrt(tw * tw + th * th) * e), math.pi / 2)

    def rect_exponent(self):
        # roundness 0 -> almost square corners, 1 -> ellipse,
        # 2 -> sides curved inwards (astroid-like)
        r = max(0.0, min(2.0, self.roundness))
        if r <= 1.0:
            return 2.0 + (1.0 - r) * 38.0
        return 2.0 - (r - 1.0) * 1.5


OCT_ANGLES = [k * math.pi / 4.0 + math.pi / 8.0 for k in range(8)]
OCT_NORM = 1.0 / math.cos(math.pi / 8.0)


def shape_distance(shape, nx, ny, exponent):
    """Normalised distance: 1.0 on the shape boundary."""
    if shape == 'RECT':
        ax = np.minimum(np.abs(nx), 8.0)
        ay = np.minimum(np.abs(ny), 8.0)
        return (ax ** exponent + ay ** exponent) ** (1.0 / exponent)
    if shape == 'OCTAGON':
        d = None
        for a in OCT_ANGLES:
            t = nx * math.cos(a) + ny * math.sin(a)
            d = t if d is None else np.maximum(d, t)
        # scale so vertices sit on the unit circle
        return d * OCT_NORM
    # ELLIPSE, RING
    return np.sqrt(nx * nx + ny * ny)


def _smooth(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sample_texture(tex, nx, ny):
    """Bilinear sample of ``tex`` at light-local coordinates.

    The texture covers the light's bounding box; u runs from the light's
    left to right as seen from inside the sphere (i.e. on the canvas).
    """
    th, tw = tex.shape[:2]
    u = np.clip(0.5 - nx * 0.5, 0.0, 1.0)
    v = np.clip(0.5 + ny * 0.5, 0.0, 1.0)
    fx = u * (tw - 1)
    fy = v * (th - 1)
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    x1 = np.minimum(x0 + 1, tw - 1)
    y1 = np.minimum(y0 + 1, th - 1)
    wx = (fx - x0)[..., None]
    wy = (fy - y0)[..., None]
    a = tex[y0, x0] * (1 - wx) + tex[y0, x1] * wx
    b = tex[y1, x0] * (1 - wx) + tex[y1, x1] * wx
    return a * (1 - wy) + b * wy


def light_mask(light, dx, dy, dz):
    """Return (mask, profile, tex_rgb) arrays for the given direction arrays."""
    L, T, B = light_basis(light.lon, light.lat, light.roll)
    dl = dx * L[0] + dy * L[1] + dz * L[2]
    front = dl > 1e-3
    inv = np.where(front, 1.0 / np.where(front, dl, 1.0), 0.0)
    tw, th = light.tan_half()
    nx = (dx * T[0] + dy * T[1] + dz * T[2]) * inv / tw
    ny = (dx * B[0] + dy * B[1] + dz * B[2]) * inv / th

    r = shape_distance(light.shape, nx, ny, light.rect_exponent())
    s = max(light.softness, 1e-3)
    # Up to 1 the fade happens inside the outline (as before); above 1 it
    # also extends outside, so the light blooms.
    outer = light.edge_extent()
    inner_edge = 1.0 - min(s, 1.0)
    mask = _smooth(outer, inner_edge, r)
    if light.shape == 'RECT':
        # Very soft rectangles: fade each axis separately (like a real
        # softbox) instead of along the square distance, which shows an "X"
        # along the diagonals. Blended in above softness 0.5 so harder
        # lights look exactly as before.
        w = min(max((s - 0.5) / 0.5, 0.0), 1.0) * (1.0 - min(light.roundness, 1.0))
        if w > 0.0:
            axis = _smooth(outer, inner_edge, np.abs(nx)) * _smooth(outer, inner_edge, np.abs(ny))
            mask = mask * (1.0 - w) + axis * w
    if light.shape == 'RING':
        inner = max(0.0, min(0.98, light.ring_inner))
        rs = min(s, 1.0)
        mask = mask * _smooth(inner - rs * 0.5, inner + rs * 0.5, r)
    mask = np.where(front, mask, 0.0)

    tex_rgb = None
    if light.tex is not None:
        t = sample_texture(light.tex, nx, ny)
        tex_rgb = t[..., :3]
        mask = mask * t[..., 3]

    profile = None
    f = light.falloff
    if f != 0.0:
        rr2 = np.clip(nx * nx + ny * ny, 0.0, 1.0)
        if f <= 1.0:
            profile = 1.0 - f * rr2           # f < 0: brighter towards the edge
        else:
            profile = (1.0 - rr2) ** f        # tighter hot spot

    grad_rgb = gradient_rgb(light, nx, ny)
    if grad_rgb is not None:
        tex_rgb = grad_rgb if tex_rgb is None else tex_rgb * grad_rgb
    return mask, profile, tex_rgb


def gradient_t(kind, angle, offset, scale, mid, interp, nx, ny):
    """Gradient parameter 0..1 in light space.

    ``nx`` runs to the light's left as seen on the canvas, so canvas X is -nx.
    """
    X, Y = -nx, ny
    scale = max(scale, 1e-3)
    ca, sa = math.cos(angle), math.sin(angle)
    if kind == 'LINEAR':
        t = 0.5 + 0.5 * ((X * ca + Y * sa) - offset) / scale
    elif kind == 'REFLECTED':
        t = np.abs((X * ca + Y * sa) - offset) / scale
    elif kind == 'RADIAL':
        t = (np.sqrt(X * X + Y * Y) - offset) / scale
    else:  # ANGULAR
        t = ((np.arctan2(Y, X) - angle) / TAU + offset) % 1.0 / scale
    t = np.clip(t, 0.0, 1.0)
    if abs(mid - 0.5) > 1e-4:
        t = t ** (math.log(0.5) / math.log(min(max(mid, 0.01), 0.99)))
    if interp == 'SMOOTH':
        t = t * t * (3.0 - 2.0 * t)
    elif interp == 'CONSTANT':
        t = (t >= 0.5).astype(np.float64)
    return t


def gradient_rgb(light, nx, ny):
    if light.grad_type == 'NONE':
        return None
    t = gradient_t(light.grad_type, light.grad_angle, light.grad_offset, light.grad_scale,
                   light.grad_mid, light.grad_interp, nx, ny)[..., None]
    a = np.array(light.grad_a, dtype=np.float64)
    b = np.array(light.grad_b, dtype=np.float64)
    return a * (1.0 - t) + b * t


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------

class BackgroundData:
    def __init__(self, mode='GRADIENT', color=(0.0, 0.0, 0.0),
                 top=(0.05, 0.05, 0.05), horizon=(0.02, 0.02, 0.02),
                 bottom=(0.005, 0.005, 0.005), blend=0.15, strength=1.0,
                 image_pixels=None, rotation=0.0):
        self.mode = mode
        self.color = color
        self.top = top
        self.horizon = horizon
        self.bottom = bottom
        self.blend = blend
        self.strength = strength
        self.image_pixels = image_pixels  # (h, w, >=3) float array or None
        self.rotation = rotation

    @classmethod
    def from_settings(cls, s, image_pixels=None):
        return cls(
            mode=s.bg_mode, color=tuple(s.bg_color), top=tuple(s.bg_top),
            horizon=tuple(s.bg_horizon), bottom=tuple(s.bg_bottom),
            blend=s.bg_blend, strength=s.bg_strength,
            image_pixels=image_pixels, rotation=s.bg_rotation,
        )

    def fill(self, out, lat_rows, u_cols):
        """Fill ``out`` (rows, cols, 3) with the background."""
        k = self.strength
        if self.mode == 'SOLID':
            out[:] = np.array(self.color, dtype=np.float32) * k
            return
        if self.mode == 'IMAGE' and self.image_pixels is not None:
            img = self.image_pixels
            ih, iw = img.shape[:2]
            v = 0.5 + lat_rows / math.pi
            u = (u_cols - self.rotation / TAU) % 1.0
            fy = np.clip(v * ih - 0.5, 0.0, ih - 1.0)
            fx = u * iw - 0.5
            y0 = np.floor(fy).astype(np.int64)
            y1 = np.minimum(y0 + 1, ih - 1)
            wy = (fy - y0)[:, None, None]
            x0f = np.floor(fx)
            wx = (fx - x0f)[None, :, None]
            x0 = x0f.astype(np.int64) % iw
            x1 = (x0 + 1) % iw
            top = img[y1][:, x0, :3] * (1 - wx) + img[y1][:, x1, :3] * wx
            bot = img[y0][:, x0, :3] * (1 - wx) + img[y0][:, x1, :3] * wx
            out[:] = (bot * (1 - wy) + top * wy) * k
            return
        # GRADIENT (also fallback for IMAGE without pixels)
        t = np.sin(lat_rows)  # -1 .. 1
        b = max(self.blend, 1e-3)
        top = np.array(self.top, dtype=np.float32)
        hor = np.array(self.horizon, dtype=np.float32)
        bot = np.array(self.bottom, dtype=np.float32)
        up = np.clip(t / b, 0.0, 1.0)[:, None]
        down = np.clip(-t / b, 0.0, 1.0)[:, None]
        up = up * up * (3 - 2 * up)
        down = down * down * (3 - 2 * down)
        row = hor[None, :] * (1 - up - down) + top[None, :] * up + bot[None, :] * down
        out[:] = row[:, None, :] * k


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _row_lats(height, y0, y1):
    v = (np.arange(y0, y1, dtype=np.float64) + 0.5) / height
    return (v - 0.5) * math.pi


def render(width, height, background, lights, chunk_rows=256):
    """Rasterise the HDRI. Returns float32 array of shape (h, w, 4)."""
    out = np.empty((height, width, 4), dtype=np.float32)
    out[..., 3] = 1.0

    u = (np.arange(width, dtype=np.float64) + 0.5) / width
    lon = (0.5 - u) * TAU
    cos_lon = np.cos(lon)
    sin_lon = np.sin(lon)
    row_step = math.pi / height

    # Per-light latitude bounds for row culling
    bounds = []
    for lt in lights:
        a = lt.angular_radius() + 2.0 * row_step
        bounds.append((lt.lat - a, lt.lat + a))

    for y0 in range(0, height, chunk_rows):
        y1 = min(height, y0 + chunk_rows)
        lats = _row_lats(height, y0, y1)
        rgb = np.empty((y1 - y0, width, 3), dtype=np.float64)
        background.fill(rgb, lats, u)

        for lt, (lo, hi) in zip(lights, bounds):
            sel = np.nonzero((lats >= lo) & (lats <= hi))[0]
            if sel.size == 0:
                continue
            a, b = sel[0], sel[-1] + 1
            sub_lat = lats[a:b]
            cl = np.cos(sub_lat)[:, None]
            dz = np.broadcast_to(np.sin(sub_lat)[:, None], (b - a, width))
            dx = cl * cos_lon[None, :]
            dy = cl * sin_lon[None, :]
            mask, profile, tex_rgb = light_mask(lt, dx, dy, dz)
            if lt.opacity != 1.0:
                mask = mask * lt.opacity
            col = np.array(lt.rgb, dtype=np.float64)
            if tex_rgb is not None:
                col = tex_rgb * col
            region = rgb[a:b]
            if lt.blend == 'ADD':
                m = mask if profile is None else mask * profile
                region += m[..., None] * col
            elif lt.blend == 'MULTIPLY':
                m = mask[..., None]
                region *= (1.0 - m) + m * col
            else:  # OVER
                emit = col if profile is None else profile[..., None] * col
                m = mask[..., None]
                region *= (1.0 - m)
                region += m * emit

        out[y0:y1, :, :3] = rgb
    return out


# ---------------------------------------------------------------------------
# Outline / picking helpers used by the canvas overlay
# ---------------------------------------------------------------------------

def outline_local(light, segments=256):
    """Boundary points (nx, ny) of the light in its own tangent plane.

    The boundary is found radially (``point = dir / distance(dir)``) so the
    points are spread along the whole perimeter, not bunched up in the
    corners of near-square superellipses.
    """
    exp = light.rect_exponent()
    pts = []
    for i in range(segments + 1):
        a = TAU * i / segments
        c, s_ = math.cos(a), math.sin(a)
        d = float(shape_distance(light.shape, np.array(c), np.array(s_), exp))
        d = d if d > 1e-6 else 1.0
        pts.append((c / d, s_ / d))
    return pts


def local_to_lonlat(light, nx, ny):
    L, T, B = light_basis(light.lon, light.lat, light.roll)
    tw, th = light.tan_half()
    x, y = nx * tw, ny * th
    d = tuple(l + x * t + y * b for l, t, b in zip(L, T, B))
    return dir_to_lonlat(d)


def outline_lonlat(light, segments=256, max_step=math.radians(0.75)):
    """Outline as (lon, lat) points, densified so every segment is short.

    Straight lines in the light's tangent plane are great circles on the
    sphere, so subdividing in the plane follows the true (curved) edge of the
    light in the equirectangular image.
    """
    local = outline_local(light, segments)
    tw, th = light.tan_half()
    out = []
    prev = None
    for p in local:
        if prev is not None:
            # angular length of this piece (approx.)
            a = local_to_lonlat(light, *prev)
            b = local_to_lonlat(light, *p)
            da = math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(lonlat_to_dir(*a), lonlat_to_dir(*b))))))
            n = max(1, int(math.ceil(da / max_step)))
            for k in range(1, n):
                t = k / n
                out.append(local_to_lonlat(light, prev[0] + (p[0] - prev[0]) * t,
                                           prev[1] + (p[1] - prev[1]) * t))
        out.append(local_to_lonlat(light, *p))
        prev = p
    return out


def outline_uv(light, segments=256):
    return [lonlat_to_uv(lon, lat) for lon, lat in outline_lonlat(light, segments)]


def uv_segments(uvs):
    """Split an outline into drawable (u, v) segments, wrapping across the seam.

    A segment that crosses the left/right edge of the image is drawn twice,
    once on each side, instead of being dropped.
    """
    segs = []
    for (u0, v0), (u1, v1) in zip(uvs[:-1], uvs[1:]):
        du = u1 - u0
        if abs(du) <= 0.5:
            segs.append(((u0, v0), (u1, v1)))
        else:
            shift = -1.0 if du > 0 else 1.0
            segs.append(((u0, v0), (u1 + shift, v1)))
            segs.append(((u0 - shift, v0), (u1, v1)))
    return segs


def hit_test(light, lon, lat):
    """Return normalised distance of direction to the light (<=1 inside)."""
    L, T, B = light_basis(light.lon, light.lat, light.roll)
    d = lonlat_to_dir(lon, lat)
    dl = sum(a * b for a, b in zip(d, L))
    if dl <= 1e-3:
        return float("inf")
    tw, th = light.tan_half()
    nx = sum(a * b for a, b in zip(d, T)) / dl / tw
    ny = sum(a * b for a, b in zip(d, B)) / dl / th
    r = shape_distance(light.shape, np.array(nx), np.array(ny),
                       light.rect_exponent())
    return float(r)


# ---------------------------------------------------------------------------
# Radiance .hdr writer (Blender's own HDR save path may apply display
# transforms / clamping to generated images, so write RGBE ourselves).
# ---------------------------------------------------------------------------

def write_radiance_hdr(path, arr):
    """Write ``arr`` (h, w, >=3 float, row 0 = bottom) as an RGBE .hdr."""
    rgb = np.ascontiguousarray(arr[::-1, :, :3], dtype=np.float32)
    h, w = rgb.shape[:2]
    m = np.max(rgb, axis=2)
    mant, expo = np.frexp(m)
    scale = np.where(m > 1e-32, mant * 256.0 / np.where(m > 1e-32, m, 1.0), 0.0)
    rgbe = np.zeros((h, w, 4), dtype=np.uint8)
    rgbe[..., :3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(m > 1e-32, expo + 128, 0).astype(np.uint8)
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {h} +X {w}\n".encode("ascii"))
        f.write(rgbe.tobytes())
