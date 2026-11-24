"""Interactive HDRI canvas inside the Image Editor.

* A POST_PIXEL draw handler outlines every light on top of the canvas image.
* ``hdri_studio.canvas_edit`` is a modal operator that lets the user select,
  drag, resize, rotate and add lights directly on the canvas.
"""

import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import render, studio
from .ops import active_light, new_light

state = {
    "editing": False,
    "stop": False,
    "hover": -1,
}

_draw_handle = None

COL_ACTIVE = (1.0, 0.55, 0.1, 1.0)
COL_NORMAL = (1.0, 1.0, 1.0, 0.75)
COL_HOVER = (0.5, 0.85, 1.0, 0.95)
COL_DISABLED = (0.5, 0.5, 0.5, 0.5)

HELP = ("HDRI Studio  |  LMB: select / drag   Ctrl+LMB: add light   "
        "Ctrl+Wheel: size   Shift+Wheel: rotate   Alt+Wheel: intensity   "
        "H: hide   X/Del: delete   Esc / RMB: finish")


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
                blf.draw(font, light.name if light.enabled else light.name + " (off)")

    if state["editing"]:
        blf.color(font, 1.0, 0.8, 0.4, 1.0)
        blf.position(font, 12, 12, 0)
        blf.draw(font, HELP)

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


# ---------------------------------------------------------------------------
# Modal editing operator
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_canvas_edit(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_edit"
    bl_label = "Edit Lights on Canvas"
    bl_description = ("Interactively place lights by dragging them on the HDRI canvas. "
                      "Run again to stop")

    def invoke(self, context, event):
        if state["editing"]:
            state["stop"] = True
            return {'CANCELLED'}
        if studio.get_canvas(context.scene, create=False) is None:
            studio.update_preview(context.scene)
        self.drag = None
        state["editing"] = True
        state["stop"] = False
        context.window_manager.modal_handler_add(self)
        try:
            context.workspace.status_text_set(HELP)
        except Exception:
            pass
        studio.tag_redraw()
        return {'RUNNING_MODAL'}

    def finish(self, context):
        state["editing"] = False
        state["stop"] = False
        state["hover"] = -1
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass
        studio.tag_redraw()
        return {'FINISHED'}

    def _push_undo(self, msg):
        try:
            bpy.ops.ed.undo_push(message=msg)
        except Exception:
            pass

    def modal(self, context, event):
        if state["stop"]:
            return self.finish(context)
        scene = context.scene
        s = scene.hdri_studio

        # Ongoing drag ------------------------------------------------------
        if self.drag is not None:
            region, index, du, dv = self.drag
            if event.type == 'MOUSEMOVE':
                if index < len(s.lights):
                    u, v = mouse_uv(region, event)
                    lon, lat = render.uv_to_lonlat((u + du) % 1.0, min(max(v + dv, 0.0), 1.0))
                    light = s.lights[index]
                    light.lon = lon
                    light.lat = lat
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.drag = None
                self._push_undo("Move HDRI Light")
                return {'RUNNING_MODAL'}
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                self.drag = None
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        area, region = canvas_under_mouse(context, event)
        if region is None:
            if state["hover"] != -1:
                state["hover"] = -1
                studio.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            h = pick_light(scene, region, event)
            if h != state["hover"]:
                state["hover"] = h
                area.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type in {'ESC'} and event.value == 'PRESS':
            return self.finish(context)
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            return self.finish(context)

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if event.ctrl:
                u, v = mouse_uv(region, event)
                if 0.0 <= v <= 1.0:
                    lon, lat = render.uv_to_lonlat(u % 1.0, v)
                    new_light(scene, s.canvas_add_preset, lon=lon, lat=lat)
                    studio.schedule_update(scene, force=True)
                    self._push_undo("Add HDRI Light")
                return {'RUNNING_MODAL'}
            index = pick_light(scene, region, event)
            if index < 0:
                return {'PASS_THROUGH'}
            s.active_index = index
            light = s.lights[index]
            u, v = mouse_uv(region, event)
            cu, cv = render.lonlat_to_uv(light.lon, light.lat)
            du = (cu - u + 0.5) % 1.0 - 0.5
            self.drag = (region, index, du, cv - v)
            return {'RUNNING_MODAL'}

        light = active_light(scene)
        if light is None:
            return {'PASS_THROUGH'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and (event.ctrl or event.shift or event.alt):
            up = event.type == 'WHEELUPMOUSE'
            if event.ctrl:
                f = 1.08 if up else 1.0 / 1.08
                light.width = light.width * f
                light.height = light.height * f
                self._push_undo("Resize HDRI Light")
            elif event.shift:
                light.roll = render.wrap_lon(light.roll + math.radians(5 if up else -5))
                self._push_undo("Rotate HDRI Light")
            elif event.alt:
                light.intensity = light.intensity * (1.1 if up else 1.0 / 1.1)
                self._push_undo("HDRI Light Intensity")
            return {'RUNNING_MODAL'}

        if event.value == 'PRESS' and event.type in {'X', 'DEL'}:
            s.lights.remove(s.active_index)
            s.active_index = min(s.active_index, len(s.lights) - 1)
            studio.schedule_update(scene, force=True)
            self._push_undo("Delete HDRI Light")
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.type == 'H':
            light.enabled = not light.enabled
            self._push_undo("Toggle HDRI Light")
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}


classes = (HDRISTUDIO_OT_canvas_edit,)


def register():
    global _draw_handle
    for c in classes:
        bpy.utils.register_class(c)
    _draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
        draw_overlay, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _draw_handle
    state["stop"] = True
    if _draw_handle is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
