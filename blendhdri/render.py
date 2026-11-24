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
        "rgb", "opacity",
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

    @classmethod
    def from_prop(cls, p):
        rgb = tuple(p.color)
        if p.use_temperature:
            k = kelvin_to_rgb(p.temperature)
            rgb = tuple(a * b for a, b in zip(rgb, k))
        if p.blend != 'MULTIPLY':
            rgb = tuple(c * p.intensity for c in rgb)
        return cls(
            shape=p.shape, blend=p.blend, lon=p.lon, lat=p.lat, roll=p.roll,
            width=p.width, height=p.height, softness=p.softness,
            roundness=p.roundness, ring_inner=p.ring_inner,
            falloff=p.falloff, gradient=p.gradient, rgb=rgb,
            opacity=p.opacity,
        )

    # Shape helpers --------------------------------------------------------
    def tan_half(self):
        w = min(max(self.width, 1e-4), MAX_LIGHT_ANGLE)
        h = min(max(self.height, 1e-4), MAX_LIGHT_ANGLE)
        return math.tan(w * 0.5), math.tan(h * 0.5)

    def angular_radius(self):
        tw, th = self.tan_half()
        return math.atan(math.sqrt(tw * tw + th * th))

    def rect_exponent(self):
        # roundness 0 -> almost square corners, 1 -> ellipse
        return 2.0 + (1.0 - max(0.0, min(1.0, self.roundness))) * 38.0


OCT_ANGLES = [k * math.pi / 4.0 + math.pi / 8.0 for k in range(8)]
OCT_NORM = 1.0 / math.cos(math.pi / 8.0)


def shape_distance(shape, nx, ny, exponent):
    """Normalised distance: 1.0 on the shape boundary."""
    if shape == 'RECT':
        ax = np.minimum(np.abs(nx), 4.0)
        ay = np.minimum(np.abs(ny), 4.0)
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


def light_mask(light, dx, dy, dz):
    """Return (mask, profile) arrays for the given direction arrays."""
    L, T, B = light_basis(light.lon, light.lat, light.roll)
    dl = dx * L[0] + dy * L[1] + dz * L[2]
    front = dl > 1e-3
    inv = np.where(front, 1.0 / np.where(front, dl, 1.0), 0.0)
    tw, th = light.tan_half()
    nx = (dx * T[0] + dy * T[1] + dz * T[2]) * inv / tw
    ny = (dx * B[0] + dy * B[1] + dz * B[2]) * inv / th

    r = shape_distance(light.shape, nx, ny, light.rect_exponent())
    s = max(light.softness, 1e-3)
    mask = _smooth(1.0, 1.0 - s, r)
    if light.shape == 'RING':
        inner = max(0.0, min(0.98, light.ring_inner))
        mask = mask * _smooth(inner - s * 0.5, inner + s * 0.5, r)
    mask = np.where(front, mask, 0.0)

    profile = None
    if light.falloff > 0.0:
        rr = np.clip(np.sqrt(nx * nx + ny * ny), 0.0, 1.0)
        profile = 1.0 - light.falloff * rr * rr
    if light.gradient != 0.0:
        g = np.clip(1.0 + light.gradient * np.clip(ny, -1.0, 1.0), 0.0, 2.0)
        profile = g if profile is None else profile * g
    return mask, profile


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
            mask, profile = light_mask(lt, dx, dy, dz)
            if lt.opacity != 1.0:
                mask = mask * lt.opacity
            col = np.array(lt.rgb, dtype=np.float64)
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

def outline_local(light, segments=72):
    """Boundary points in normalised light space (nx, ny)."""
    pts = []
    if light.shape == 'OCTAGON':
        for k in range(8):
            a = k * math.pi / 4.0
            pts.append((math.cos(a), math.sin(a)))
        pts.append(pts[0])
        # subdivide edges so they curve correctly on the sphere
        dense = []
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            for i in range(8):
                t = i / 8.0
                dense.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        dense.append(dense[0])
        return dense
    p = light.rect_exponent() if light.shape == 'RECT' else 2.0
    e = 2.0 / p
    for i in range(segments + 1):
        a = TAU * i / segments
        c, s = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** e, c)
        y = math.copysign(abs(s) ** e, s)
        pts.append((x, y))
    return pts


def local_to_lonlat(light, nx, ny):
    L, T, B = light_basis(light.lon, light.lat, light.roll)
    tw, th = light.tan_half()
    x, y = nx * tw, ny * th
    d = tuple(l + x * t + y * b for l, t, b in zip(L, T, B))
    return dir_to_lonlat(d)


def outline_uv(light, segments=72):
    return [lonlat_to_uv(*local_to_lonlat(light, x, y))
            for x, y in outline_local(light, segments)]


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
