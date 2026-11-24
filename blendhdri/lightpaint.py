"""LightPaint: click on the model in the 3D viewport to position a light.

Reflection mode puts the light where it will be *seen reflected* at the
clicked point, Illumination mode makes it light the surface head on and Rim
mode places it behind the surface for an edge highlight.
"""

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import render, studio
from .ops import active_light, new_light

state = {"running": False, "stop": False}

HELP = ("HDRI LightPaint  |  LMB (drag): move active light to the clicked spot   "
        "Shift+LMB: new light   1/2/3: Reflection/Illumination/Rim   Esc / RMB: finish")


def view3d_under_mouse(context, event):
    win = context.window
    if win is None:
        return None, None, None
    for area in win.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type != 'WINDOW':
                continue
            if (region.x <= event.mouse_x < region.x + region.width
                    and region.y <= event.mouse_y < region.y + region.height):
                rv3d = getattr(region, "data", None) or area.spaces.active.region_3d
                return area, region, rv3d
    return None, None, None


def light_direction(mode, view_dir, normal):
    d = view_dir.normalized()
    n = normal.normalized()
    if n.dot(d) > 0.0:
        n = -n  # facing away from the viewer (back face)
    if mode == 'ILLUMINATION':
        return n
    if mode == 'RIM':
        t = n - d * n.dot(d)
        if t.length < 1e-4:
            t = n
        return (t.normalized() + d * 1.2).normalized()
    # REFLECTION
    return (d - 2.0 * d.dot(n) * n).normalized()


def raycast(context, region, rv3d, event):
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _loc, normal, _idx, _obj, _mat = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit:
        return None
    return direction, Vector(normal)


class HDRISTUDIO_OT_lightpaint(bpy.types.Operator):
    bl_idname = "hdri_studio.lightpaint"
    bl_label = "LightPaint"
    bl_description = ("Click on your model in the 3D viewport to place the active light "
                      "(reflection / illumination / rim). Run again to stop")

    def invoke(self, context, event):
        if state["running"]:
            state["stop"] = True
            return {'CANCELLED'}
        state["running"] = True
        state["stop"] = False
        self.painting = False
        context.window_manager.modal_handler_add(self)
        try:
            context.workspace.status_text_set(HELP)
        except Exception:
            pass
        studio.tag_redraw()
        return {'RUNNING_MODAL'}

    def finish(self, context):
        state["running"] = False
        state["stop"] = False
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass
        studio.tag_redraw()
        return {'FINISHED'}

    def _apply(self, context, region, rv3d, event, create=False):
        res = raycast(context, region, rv3d, event)
        if res is None:
            return False
        view_dir, normal = res
        s = context.scene.hdri_studio
        lon, lat = render.dir_to_lonlat(light_direction(s.paint_mode, view_dir, normal))
        light = active_light(context.scene)
        if create or light is None:
            new_light(context.scene, s.canvas_add_preset, lon=lon, lat=lat)
            studio.schedule_update(context.scene, force=True)
        else:
            light.lon = lon
            light.lat = lat
        return True

    def modal(self, context, event):
        if state["stop"]:
            return self.finish(context)
        s = context.scene.hdri_studio

        if self.painting:
            if event.type == 'MOUSEMOVE':
                area, region, rv3d = view3d_under_mouse(context, event)
                if region is not None:
                    self._apply(context, region, rv3d, event)
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.painting = False
                try:
                    bpy.ops.ed.undo_push(message="LightPaint")
                except Exception:
                    pass
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        area, region, rv3d = view3d_under_mouse(context, event)
        if region is None:
            return {'PASS_THROUGH'}

        if event.value == 'PRESS':
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                return self.finish(context)
            if event.type in {'ONE', 'TWO', 'THREE'} and not (event.ctrl or event.alt or event.shift):
                s.paint_mode = {'ONE': 'REFLECTION', 'TWO': 'ILLUMINATION',
                                'THREE': 'RIM'}[event.type]
                studio.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE':
                if self._apply(context, region, rv3d, event, create=event.shift):
                    self.painting = not event.shift
                    if event.shift:
                        try:
                            bpy.ops.ed.undo_push(message="LightPaint Add")
                        except Exception:
                            pass
                    return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}
        return {'PASS_THROUGH'}


classes = (HDRISTUDIO_OT_lightpaint,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    state["stop"] = True
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
