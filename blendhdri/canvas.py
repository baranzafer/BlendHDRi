"""HDRI canvas helpers: light outlines drawn over the image and picking.

Drawing is driven by ``gui.draw_handler``; clicks are handled by the
keymap operators in ``gui_ops`` (no long running modal operator).
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
COL_NORMAL = (1.0, 1.0, 1.0, 0.75)
COL_HOVER = (0.5, 0.85, 1.0, 0.95)
COL_DISABLED = (0.5, 0.5, 0.5, 0.5)
COL_AREA = (0.4, 1.0, 0.5, 0.9)

def is_canvas_space(space):
    return (space is not None and space.type == 'IMAGE_EDITOR'
            and space.image is not None and space.image.name == studio.CANVAS_NAME)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _polyline_shader():
    return gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')


def _draw_segments(region, segments, color, width):
    if not segments:
        return
    shader = _polyline_shader()
    coords = []
    for a, b in segments:
        coords.append((a[0], a[1], 0.0))
        coords.append((b[0], b[1], 0.0))
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _uv_segments(v2d, uvs):
    segs = []
    prev = None
    for u, v in uvs:
        if prev is not None and abs(u - prev[0]) < 0.5:
            a = v2d.view_to_region(prev[0], prev[1], clip=False)
            b = v2d.view_to_region(u, v, clip=False)
            segs.append((a, b))
        prev = (u, v)
    return segs


def _circle_segments(cx, cy, r, n=16):
    pts = [(cx + r * math.cos(math.tau * i / n), cy + r * math.sin(math.tau * i / n))
           for i in range(n + 1)]
    return list(zip(pts[:-1], pts[1:]))


def draw_overlay():
    context = bpy.context
    space = context.space_data
    if not is_canvas_space(space):
        return
    scene = context.scene
    s = scene.hdri_studio
    region = context.region
    v2d = region.view2d

    gpu.state.blend_set('ALPHA')
    font = 0
    try:
        blf.size(font, 12)
    except TypeError:  # very old signature
        blf.size(font, 12, 72)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.9)

    if s.show_outlines:
        for i, light in enumerate(s.lights):
            data = render.LightData.from_prop(light)
            if i == s.active_index:
                col, width = COL_ACTIVE, 2.5
            elif i == state["hover"]:
                col, width = COL_HOVER, 2.0
            elif not light.enabled:
                col, width = COL_DISABLED, 1.0
            elif light.output == 'AREA':
                col, width = COL_AREA, 1.2
            else:
                col, width = COL_NORMAL, 1.2
            segs = _uv_segments(v2d, render.outline_uv(data))
            cu, cv = render.lonlat_to_uv(light.lon, light.lat)
            cx, cy = v2d.view_to_region(cu, cv, clip=False)
            segs += _circle_segments(cx, cy, 4.0 if i == s.active_index else 3.0)
            _draw_segments(region, segs, col, width)
            if s.show_labels:
                blf.color(font, *col)
                blf.position(font, cx + 8, cy + 6, 0)
                label = light.name
                if not light.enabled:
                    label += " (off)"
                elif light.output == 'AREA':
                    label += " (area)"
                elif light.output == 'BOTH':
                    label += " (+area)"
                blf.draw(font, label)

    blf.disable(font, blf.SHADOW)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Picking helpers
# ---------------------------------------------------------------------------

def canvas_under_mouse(context, event):
    win = context.window
    if win is None:
        return None, None
    for area in win.screen.areas:
        if area.type != 'IMAGE_EDITOR' or not is_canvas_space(area.spaces.active):
            continue
        for region in area.regions:
            if region.type != 'WINDOW':
                continue
            if (region.x <= event.mouse_x < region.x + region.width
                    and region.y <= event.mouse_y < region.y + region.height):
                return area, region
    return None, None


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
    # Topmost (last drawn) first; inside the shape wins.
    for i in reversed(range(len(s.lights))):
        if render.hit_test(render.LightData.from_prop(s.lights[i]), lon, lat) <= 1.05:
            return i
    # Otherwise: nearest centre within a few pixels
    mx, my = event.mouse_x - region.x, event.mouse_y - region.y
    best, best_d = -1, 14.0
    for i, l in enumerate(s.lights):
        cu, cv = render.lonlat_to_uv(l.lon, l.lat)
        cx, cy = region.view2d.view_to_region(cu, cv, clip=False)
        d = math.hypot(cx - mx, cy - my)
        if d < best_d:
            best, best_d = i, d
    return best


def register():
    pass


def unregister():
    pass
