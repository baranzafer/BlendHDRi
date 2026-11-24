"""HDRI canvas in the Image Editor: light outlines, grid and picking.

The outlines follow the exact edge of every light on the sphere (see
``render.outline_lonlat``) and wrap across the left/right seam. Clicks are
handled by the keymap operators in ``canvas_ops``.
"""

import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import render, studio

state = {
    "hover": -1,
}

COL_ACTIVE = (1.0, 0.55, 0.1, 1.0)
COL_NORMAL = (1.0, 1.0, 1.0, 0.8)
COL_HOVER = (0.45, 0.8, 1.0, 1.0)
COL_DISABLED = (0.55, 0.55, 0.58, 0.6)
COL_AREA = (0.4, 1.0, 0.5, 0.95)
COL_SHADOW = (0.0, 0.0, 0.0, 0.65)

_draw_handle = None
_outline_cache = {}


def is_canvas_space(space):
    return (space is not None and space.type == 'IMAGE_EDITOR'
            and space.image is not None and space.image.name == studio.CANVAS_NAME)


# ---------------------------------------------------------------------------
# Outline geometry (cached in image UV space)
# ---------------------------------------------------------------------------

def light_outline_segments(light):
    """List of ((u0, v0), (u1, v1)) segments tracing the light's edge."""
    d = render.LightData.from_prop(light)
    key = (d.shape, round(d.lon, 5), round(d.lat, 5), round(d.roll, 5),
           round(d.width, 5), round(d.height, 5), round(d.roundness, 4))
    segs = _outline_cache.get(key)
    if segs is None:
        if len(_outline_cache) > 256:
            _outline_cache.clear()
        segs = render.uv_segments(render.outline_uv(d))
        _outline_cache[key] = segs
    return segs


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_lines(region, coords, color, width):
    if not coords:
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _to_region(v2d, segs):
    coords = []
    for (u0, v0), (u1, v1) in segs:
        a = v2d.view_to_region(u0, v0, clip=False)
        b = v2d.view_to_region(u1, v1, clip=False)
        coords.append((a[0], a[1], 0.0))
        coords.append((b[0], b[1], 0.0))
    return coords


def _circle(cx, cy, r, n=20):
    pts = [(cx + r * math.cos(math.tau * i / n), cy + r * math.sin(math.tau * i / n), 0.0)
           for i in range(n + 1)]
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        out += [a, b]
    return out


def _font_size(size):
    try:
        blf.size(0, size)
    except TypeError:
        blf.size(0, size, 72)


def _scale():
    try:
        return bpy.context.preferences.system.ui_scale
    except Exception:
        return 1.0


def _draw_grid(context, region):
    v2d = region.view2d
    k = _scale()
    lines = []
    for i in range(1, 12):
        u = i / 12
        a = v2d.view_to_region(u, 0.0, clip=False)
        b = v2d.view_to_region(u, 1.0, clip=False)
        lines += [(a[0], a[1], 0.0), (b[0], b[1], 0.0)]
    for j in (1, 2, 4, 5):
        v = j / 6
        a = v2d.view_to_region(0.0, v, clip=False)
        b = v2d.view_to_region(1.0, v, clip=False)
        lines += [(a[0], a[1], 0.0), (b[0], b[1], 0.0)]
    _draw_lines(region, lines, (1.0, 1.0, 1.0, 0.08), 1.0)
    a = v2d.view_to_region(0.0, 0.5, clip=False)
    b = v2d.view_to_region(1.0, 0.5, clip=False)
    _draw_lines(region, [(a[0], a[1], 0.0), (b[0], b[1], 0.0)], (1.0, 1.0, 1.0, 0.2), 1.0)

    # direction labels along the top edge, relative to the camera
    front = studio.front_lon(context.scene)
    _font_size(int(11 * k))
    for label, off in (("Front", 0.0), ("Right", math.pi / 2), ("Back", math.pi),
                       ("Left", -math.pi / 2)):
        u, _v = render.lonlat_to_uv(render.wrap_lon(front + off), 0.0)
        x, y = v2d.view_to_region(u, 1.0, clip=False)
        w = blf.dimensions(0, label)[0]
        col = (1.0, 0.7, 0.35, 1.0) if off == 0.0 else (0.8, 0.8, 0.82, 0.9)
        blf.color(0, *col)
        blf.position(0, x - w / 2, y + 6 * k, 0)
        blf.draw(0, label)


def draw_overlay():
    context = bpy.context
    space = context.space_data
    if not is_canvas_space(space):
        return
    scene = context.scene
    s = scene.hdri_studio
    region = context.region
    v2d = region.view2d
    k = _scale()

    gpu.state.blend_set('ALPHA')
    blf.enable(0, blf.SHADOW)
    blf.shadow(0, 3, 0.0, 0.0, 0.0, 0.9)
    try:
        if s.show_grid:
            _draw_grid(context, region)
        if not s.show_outlines:
            return
        order = [i for i in range(len(s.lights)) if i != s.active_index]
        if 0 <= s.active_index < len(s.lights):
            order.append(s.active_index)     # active light on top
        for i in order:
            light = s.lights[i]
            active = i == s.active_index
            if active:
                col, width = COL_ACTIVE, 2.5
            elif i == state["hover"]:
                col, width = COL_HOVER, 2.0
            elif not light.enabled:
                col, width = COL_DISABLED, 1.2
            elif light.output == 'AREA':
                col, width = COL_AREA, 1.5
            else:
                col, width = COL_NORMAL, 1.5
            width *= k
            coords = _to_region(v2d, light_outline_segments(light))
            cu, cv = render.lonlat_to_uv(light.lon, light.lat)
            cx, cy = v2d.view_to_region(cu, cv, clip=False)
            marker = _circle(cx, cy, (5.0 if active else 3.5) * k)
            # dark under-stroke keeps the outline readable on bright lights
            _draw_lines(region, coords + marker, COL_SHADOW, width + 2.0 * k)
            _draw_lines(region, coords + marker, col, width)
            if s.show_labels:
                label = light.name
                if not light.enabled:
                    label += " (off)"
                elif light.output == 'AREA':
                    label += " (area)"
                elif light.output == 'BOTH':
                    label += " (+area)"
                _font_size(int((12 if active else 11) * k))
                blf.color(0, *col)
                blf.position(0, cx + 9 * k, cy + 7 * k, 0)
                blf.draw(0, label)
    finally:
        blf.disable(0, blf.SHADOW)
        gpu.state.blend_set('NONE')


def _draw_handler():
    try:
        draw_overlay()
    except Exception:
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Picking helpers
# ---------------------------------------------------------------------------

def mouse_uv(region, event):
    x = event.mouse_x - region.x
    y = event.mouse_y - region.y
    return region.view2d.region_to_view(x, y)


def pick_light(scene, region, event):
    s = scene.hdri_studio
    u, v = mouse_uv(region, event)
    if not (0.0 <= v <= 1.0):
        return -1
    lon, lat = render.uv_to_lonlat(u % 1.0, v)
    # Active light first, then topmost (last drawn); inside the shape wins.
    order = list(reversed(range(len(s.lights))))
    if 0 <= s.active_index < len(s.lights):
        order.remove(s.active_index)
        order.insert(0, s.active_index)
    for i in order:
        if render.hit_test(render.LightData.from_prop(s.lights[i]), lon, lat) <= 1.0:
            return i
    # Otherwise: nearest centre within a few pixels
    mx, my = event.mouse_x - region.x, event.mouse_y - region.y
    best, best_d = -1, 14.0 * _scale()
    for i, l in enumerate(s.lights):
        cu, cv = render.lonlat_to_uv(l.lon, l.lat)
        cx, cy = region.view2d.view_to_region(cu, cv, clip=False)
        d = math.hypot(cx - mx, cy - my)
        if d < best_d:
            best, best_d = i, d
    return best


def register():
    global _draw_handle
    _draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
        _draw_handler, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _outline_cache.clear()
