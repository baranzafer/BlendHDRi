"""Pure math for Light Studio (no bpy), so it can be tested on its own.

Placement
---------
Every managed light orbits a *pivot* (the studio target, the 3D cursor, the
world origin or a point picked with LightPaint). Its position is stored as
longitude / latitude / distance around that pivot, plus a roll around the
light's own axis. Longitude = atan2(y, x), latitude = asin(z).

Light textures
--------------
Blender lights cannot do edge softness, roundness, centre falloff or
gradients by themselves, so each light gets a small generated float texture
that is fed into the light's emission through a light node tree (Cycles).
The texture covers the light's "carrier": the whole area light, or the full
cone of a spot light. ``light_texture`` rasterises the shape into it.

Texture coordinates were measured in Cycles: for area lights the UV output of
the Texture Coordinate node runs 0..1 along the light's local X / Y; for spot
lights it is ``0.5 + 0.5 * tan(angle) / tan(spot_size / 2)`` along local X / Y.
"""

import math

import numpy as np

TAU = math.tau
MAX_ANGLE = math.radians(170.0)


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------

def lonlat_to_dir(lon, lat):
    cl = math.cos(lat)
    return (cl * math.cos(lon), cl * math.sin(lon), math.sin(lat))


def dir_to_lonlat(d):
    x, y, z = d
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    z = max(-1.0, min(1.0, z / length))
    return math.atan2(y, x), math.asin(z)


def wrap_lon(lon):
    return (lon + math.pi) % TAU - math.pi


def light_basis(lon, lat, roll):
    """Return (L, T, B): direction from the pivot to the light + rolled frame.

    The light object's local axes are X = T, Y = B, Z = L, so the light
    (which shines along its local -Z) points at the pivot.
    """
    cl, sl = math.cos(lat), math.sin(lat)
    co, so = math.cos(lon), math.sin(lon)
    L = (cl * co, cl * so, sl)
    east = (-so, co, 0.0)
    north = (-sl * co, -sl * so, cl)
    cr, sr = math.cos(roll), math.sin(roll)
    T = tuple(cr * e + sr * n for e, n in zip(east, north))
    B = tuple(-sr * e + cr * n for e, n in zip(east, north))
    return L, T, B


def roll_from_axes(lon, lat, x_axis):
    """Inverse of light_basis for the roll: angle of ``x_axis`` in the east/north frame."""
    cl, sl = math.cos(lat), math.sin(lat)
    co, so = math.cos(lon), math.sin(lon)
    east = (-so, co, 0.0)
    north = (-sl * co, -sl * so, cl)
    e = sum(a * b for a, b in zip(x_axis, east))
    n = sum(a * b for a, b in zip(x_axis, north))
    return math.atan2(n, e)


def reflect(d, n):
    k = 2.0 * sum(a * b for a, b in zip(d, n))
    return tuple(a - k * b for a, b in zip(d, n))


def _norm(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / length for c in v)


def paint_direction(mode, view_dir, normal):
    """Direction from the clicked surface point towards where the light goes.

    REFLECTION: the light is seen mirrored exactly at the clicked point.
    ILLUMINATION: the light faces the surface head on (brightest diffuse).
    RIM: the light sits behind the surface, grazing it for an edge highlight.
    """
    d = _norm(view_dir)
    n = _norm(normal)
    if sum(a * b for a, b in zip(n, d)) > 0.0:
        n = tuple(-c for c in n)  # back face: flip towards the viewer
    if mode == 'ILLUMINATION':
        return n
    if mode == 'RIM':
        dn = sum(a * b for a, b in zip(n, d))
        t = tuple(a - b * dn for a, b in zip(n, d))
        if math.sqrt(sum(c * c for c in t)) < 1e-4:
            t = n
        t = _norm(t)
        return _norm(tuple(a + b * 1.2 for a, b in zip(t, d)))
    return _norm(reflect(d, n))


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

def kelvin_to_rgb(kelvin):
    """Approximate black body colour (linear), normalised so max channel == 1."""
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
    rgb = [c ** 2.2 for c in rgb]
    m = max(rgb) or 1.0
    return tuple(c / m for c in rgb)


# ---------------------------------------------------------------------------
# Shape description
# ---------------------------------------------------------------------------

class ShapeData:
    """Everything that ends up in a light's generated texture."""

    __slots__ = (
        "shape", "softness", "roundness", "ring_inner", "falloff",
        "grad_type", "grad_angle", "grad_offset", "grad_scale", "grad_mid",
        "grad_interp", "grad_a", "grad_b", "tex",
    )

    def __init__(self, **kw):
        self.shape = kw.get("shape", "RECT")
        self.softness = kw.get("softness", 0.1)
        self.roundness = kw.get("roundness", 0.0)
        self.ring_inner = kw.get("ring_inner", 0.7)
        self.falloff = kw.get("falloff", 0.0)
        self.grad_type = kw.get("grad_type", 'NONE')
        self.grad_angle = kw.get("grad_angle", math.pi / 2)
        self.grad_offset = kw.get("grad_offset", 0.0)
        self.grad_scale = kw.get("grad_scale", 1.0)
        self.grad_mid = kw.get("grad_mid", 0.5)
        self.grad_interp = kw.get("grad_interp", 'LINEAR')
        self.grad_a = kw.get("grad_a", (1.0, 1.0, 1.0))
        self.grad_b = kw.get("grad_b", (0.0, 0.0, 0.0))
        self.tex = kw.get("tex", None)  # (h, w, 4) float array or None

    def key(self):
        """Hashable summary used to skip regenerating an unchanged texture."""
        vals = []
        for k in self.__slots__:
            v = getattr(self, k)
            if k == "tex":
                v = None if v is None else (v.shape, float(v[..., :3].sum()), float(v[..., 3].sum()))
            elif isinstance(v, float):
                v = round(v, 6)
            elif isinstance(v, (tuple, list)):
                v = tuple(round(float(c), 6) for c in v)
            vals.append(v)
        return tuple(vals)

    def edge_extent(self):
        """How far (in normalised units) the soft edge reaches outwards (bloom)."""
        return 1.0 + max(0.0, self.softness - 1.0) * BLOOM_PER_UNIT

    def is_plain(self):
        """True if the light looks exactly like a hard-edged native light."""
        return (self.softness <= 1e-4 and self.falloff == 0.0 and self.grad_type == 'NONE'
                and self.tex is None and self.shape in {'RECT', 'ELLIPSE'}
                and (self.shape != 'RECT' or self.roundness <= 1e-4))


# Edge softness above 1 grows the light outwards by this much per unit.
BLOOM_PER_UNIT = 0.75
# Soft edges and centre falloff are shaped in photographic stops, so they stay
# visible on bright lights (a linear fade is mostly clipped to white on screen).
SOFT_STOPS = 5.0

OCT_ANGLES = [k * math.pi / 4.0 + math.pi / 8.0 for k in range(8)]
OCT_NORM = 1.0 / math.cos(math.pi / 8.0)


def shape_distance(shape, nx, ny, roundness=0.0):
    """Normalised distance: 0 in the centre, 1.0 on the shape outline.

    Rectangles use ``roundness`` as a corner radius: 0 = square,
    0.5 = half rounded corners, 1 = ellipse (evenly in between). Above 1 the
    sides curve inwards (superellipse) up to a four-pointed star at 3.
    """
    if shape == 'RECT':
        ax = np.minimum(np.abs(nx), 8.0)
        ay = np.minimum(np.abs(ny), 8.0)
        r = max(0.0, min(3.0, roundness))
        if r <= 1.0:
            c = r
            qx = ax - (1.0 - c)
            qy = ay - (1.0 - c)
            outside = np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2)
            inside = np.minimum(np.maximum(qx, qy), 0.0)
            return 1.0 + outside + inside - c
        e = 2.0 / (1.0 + (r - 1.0) * 1.5)
        return (ax ** e + ay ** e) ** (1.0 / e)
    if shape == 'OCTAGON':
        d = None
        for a in OCT_ANGLES:
            t = nx * math.cos(a) + ny * math.sin(a)
            d = t if d is None else np.maximum(d, t)
        return d * OCT_NORM
    return np.sqrt(nx * nx + ny * ny)


def stops_curve(f, stops=SOFT_STOPS):
    """Map a 0..1 fade to 0..1 evenly in stops (exposure), not linearly."""
    return (np.exp2(stops * f) - 1.0) / (2.0 ** stops - 1.0)


def falloff_profile(falloff, nx, ny, shape='ELLIPSE', roundness=1.0):
    """Centre falloff in stops: +f = edge f stops darker, -f = centre f stops darker.

    The radial profile is normalised to the shape's farthest point, so the
    corners of a rectangle keep fading instead of flattening out.
    """
    reach2 = 1.0
    if shape == 'RECT' and roundness < 1.0:
        c = max(0.0, roundness)
        reach2 = 2.0 * ((1.0 - c) + c / math.sqrt(2.0)) ** 2
    rr2 = np.clip((nx * nx + ny * ny) / reach2, 0.0, 1.0)
    if falloff > 0.0:
        return np.exp2(-falloff * rr2)
    return np.exp2(falloff * (1.0 - rr2))


def _smooth(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sample_texture(tex, nx, ny):
    """Bilinear sample of a user image over the light outline.

    ``nx`` runs along the light's local X. Seen from the subject looking at
    the light that axis points to the *left*, so the image is flipped to
    appear upright and unmirrored from the subject's point of view.
    """
    th, tw = tex.shape[:2]
    inside = (np.abs(nx) <= 1.0) & (np.abs(ny) <= 1.0)
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
    out = a * (1 - wy) + b * wy
    return np.where(inside[..., None], out, 0.0)


def gradient_t(kind, angle, offset, scale, mid, interp, nx, ny):
    """Gradient parameter 0..1. Angle is measured as seen from the subject."""
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


def shape_rgba(s, nx, ny):
    """RGB emission multiplier for light-local coordinates (1.0 = outline)."""
    r = shape_distance(s.shape, nx, ny, s.roundness)
    soft = max(s.softness, 1e-3)
    outer = s.edge_extent()
    inner_edge = 1.0 - min(soft, 1.0)
    fade = _smooth(outer, inner_edge, r)
    if s.shape == 'RECT':
        # Very soft rectangles fade per axis like a real softbox (no "X").
        w = min(max((soft - 0.5) / 0.5, 0.0), 1.0) * (1.0 - min(s.roundness, 1.0))
        if w > 0.0:
            axis = _smooth(outer, inner_edge, np.abs(nx)) * _smooth(outer, inner_edge, np.abs(ny))
            fade = fade * (1.0 - w) + axis * w
    if s.shape == 'RING':
        inner = max(0.0, min(0.98, s.ring_inner))
        rs = min(soft, 1.0)
        fade = fade * _smooth(inner - rs * 0.5, inner + rs * 0.5, r)
    if s.softness > 1e-3:
        # Even in stops: the soft edge is visible however bright the light is.
        mask = stops_curve(fade, SOFT_STOPS * min(1.0, 0.3 + s.softness * 3.0))
    else:
        mask = fade

    if s.falloff != 0.0:
        mask = mask * falloff_profile(s.falloff, nx, ny, s.shape, s.roundness)

    rgb = np.repeat(mask[..., None], 3, axis=-1)
    if s.grad_type != 'NONE':
        t = gradient_t(s.grad_type, s.grad_angle, s.grad_offset, s.grad_scale,
                       s.grad_mid, s.grad_interp, nx, ny)[..., None]
        a = np.array(s.grad_a, dtype=np.float64)
        b = np.array(s.grad_b, dtype=np.float64)
        rgb = rgb * (a * (1.0 - t) + b * t)
    if s.tex is not None:
        t = sample_texture(s.tex, nx, ny)
        rgb = rgb * t[..., :3] * t[..., 3:4]
    return np.maximum(rgb, 0.0)


def light_texture(s, res, kx=1.0, ky=1.0):
    """Rasterise ``s`` into a (res, res, 4) float32 RGBA image.

    Pixel (u, v) of the image maps to light-local coordinates
    ``nx = (2u - 1) * kx``, ``ny = (2v - 1) * ky`` where 1.0 is the outline.
    Row 0 is the bottom of the image (Blender pixel order).
    """
    c = (np.arange(res, dtype=np.float64) + 0.5) / res * 2.0 - 1.0
    nx = c[None, :] * kx
    ny = c[:, None] * ky
    nx, ny = np.broadcast_arrays(nx, ny)
    rgb = shape_rgba(s, nx, ny)
    out = np.empty((res, res, 4), dtype=np.float32)
    out[..., :3] = rgb
    out[..., 3] = 1.0
    return out


# ---------------------------------------------------------------------------
# Light sizes and power
# ---------------------------------------------------------------------------

def tan_half(angle):
    return math.tan(min(max(angle, 1e-4), MAX_ANGLE) * 0.5)


def area_size(width, height, distance):
    """Physical size of an area light covering (width x height) degrees."""
    return 2.0 * distance * tan_half(width), 2.0 * distance * tan_half(height)


def area_power(intensity, size_x, size_y, ellipse=False):
    """Power for an area light whose surface brightness is ``intensity``.

    Matches the radiance a light of the same angular size would have in an
    HDRI (P = L * pi * A), so moving a light away keeps the subject's
    illumination constant as long as its angular size stays the same.
    """
    a = size_x * size_y * (math.pi / 4.0 if ellipse else 1.0)
    return intensity * math.pi * a


def point_power(intensity, distance):
    """Power of a point / spot light giving ``intensity`` (sun units) at ``distance``."""
    return intensity * 4.0 * math.pi * distance * distance


def spot_cone(width, height, extent, square):
    """Spot cone angle (full) that contains a (width x height) beam shape.

    Returns (spot_size, kx, ky) where kx / ky map texture UV to local
    coordinates (see ``light_texture``).
    """
    tw, th = tan_half(width) * extent, tan_half(height) * extent
    reach = math.sqrt(tw * tw + th * th) if square else max(tw, th)
    reach = min(reach, math.tan(math.radians(179.0) * 0.5))
    spot = 2.0 * math.atan(reach)
    # local nx = tan(angle_x) / tan_half(width); UV spans +-reach
    return spot, reach / tan_half(width), reach / tan_half(height)
