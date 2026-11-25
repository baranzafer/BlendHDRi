"""LightPaint: click on the model to decide where the light falls.

* Reflection: the highlight (the light's mirror image) lands on the clicked point.
* Illumination: the light faces the clicked surface head on.
* Rim: the light sits behind the surface and grazes its edge.

With "Aim: Clicked Point" the light orbits the clicked point itself, so the
placement is exact on any surface. With "Aim: Studio Target" the light keeps
orbiting the studio target; for reflections its position is solved so the
highlight still lands exactly on the clicked point.
"""

import math

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import core, overlay, session, sync
from .ops import new_light

SESSION = "lightpaint"

HELP = ("LightPaint  |  LMB (drag): place active light   Shift+LMB: new light   "
        "1/2/3: Reflection/Illumination/Rim   Ctrl+Wheel: size   Shift+Wheel: rotate   "
        "Alt+Wheel: intensity   Ctrl+Shift+Wheel: distance   Esc / RMB: finish")


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


def raycast(context, region, rv3d, event):
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, loc, normal, _idx, _obj, _mat = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit:
        return None
    return Vector(loc), Vector(direction), Vector(normal)


def solve_on_sphere(hit, direction, center, radius):
    """Point where the ray hit + t*direction (t > 0) leaves the sphere, or None."""
    o = hit - center
    b = o.dot(direction)
    c = o.dot(o) - radius * radius
    disc = b * b - c
    if disc < 0.0:
        return None
    t = -b + math.sqrt(disc)
    if t <= 1e-6:
        return None
    return hit + direction * t


def place(scene, obj, hit, view_dir, normal, mode, aim):
    ls = obj.light_studio
    direction = Vector(core.paint_direction(mode, tuple(view_dir), tuple(normal)))
    if aim == 'SURFACE':
        ls.pivot_mode = 'POINT'
        ls.pivot_point = hit
        ls.lon, ls.lat = core.dir_to_lonlat(tuple(direction))
        return True
    ls.pivot_mode = 'TARGET'
    center = sync.target_point(scene)
    p = solve_on_sphere(hit, direction, center, ls.distance)
    d = (p - center) if p is not None else direction
    if d.length < 1e-6:
        return False
    ls.lon, ls.lat = core.dir_to_lonlat(tuple(d))
    return True


class LIGHTSTUDIO_OT_lightpaint(session.ModalToolMixin, bpy.types.Operator):
    bl_idname = "light_studio.lightpaint"
    bl_label = "LightPaint"
    bl_description = ("Click on your model to place the active light so its highlight / "
                      "illumination / rim lands there. Run again to stop")

    session_name = SESSION
    status_text = HELP

    def tool_start(self, context, event):
        self.painting = False
        return True

    def tool_cleanup(self, context):
        if getattr(self, "painting", False):
            self.painting = False
            _undo("LightPaint")

    def _apply(self, context, region, rv3d, event, create=False):
        res = raycast(context, region, rv3d, event)
        if res is None:
            return False
        hit, view_dir, normal = res
        scene = context.scene
        s = scene.light_studio
        obj = sync.active_light(context)
        if create or obj is None:
            obj = new_light(context, s.paint_add_preset)
        return place(scene, obj, hit, view_dir, normal, s.paint_mode, s.paint_pivot)

    def _wheel(self, context, event):
        obj = sync.active_light(context)
        if obj is None:
            return False
        ls = obj.light_studio
        up = event.type == 'WHEELUPMOUSE'
        f = 1.1 if up else 1.0 / 1.1
        if event.ctrl and event.shift:
            ls.distance = max(0.01, ls.distance * f)
        elif event.ctrl:
            ls.width = min(max(ls.width * f, math.radians(0.1)), math.radians(170))
            ls.height = min(max(ls.height * f, math.radians(0.1)), math.radians(170))
        elif event.shift:
            ls.roll = core.wrap_lon(ls.roll + math.radians(5 if up else -5))
        elif event.alt:
            ls.intensity = ls.intensity * f
        else:
            return False
        return True

    def tool_modal(self, context, event):
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}
        s = context.scene.light_studio

        if self.painting:
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                _area, region, rv3d = view3d_under_mouse(context, event)
                if region is not None:
                    self._apply(context, region, rv3d, event)
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.painting = False
                _undo("LightPaint")
                return {'RUNNING_MODAL'}
            if event.type in {'WINDOW_DEACTIVATE', 'ESC', 'RIGHTMOUSE'} or \
                    (event.type == 'LEFTMOUSE' and event.value == 'PRESS'):
                self.painting = False  # missed release
                _undo("LightPaint")
                if event.type != 'LEFTMOUSE':
                    return {'PASS_THROUGH'}
            else:
                return {'PASS_THROUGH'}

        _area, region, rv3d = view3d_under_mouse(context, event)
        if region is None or rv3d is None:
            return {'PASS_THROUGH'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and \
                (event.ctrl or event.shift or event.alt):
            if self._wheel(context, event):
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.value == 'PRESS':
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                return 'FINISH'
            if event.type in {'ONE', 'TWO', 'THREE'} and not (event.ctrl or event.alt or event.shift):
                s.paint_mode = {'ONE': 'REFLECTION', 'TWO': 'ILLUMINATION',
                                'THREE': 'RIM'}[event.type]
                overlay.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and not (event.ctrl or event.alt):
                create = event.shift
                if self._apply(context, region, rv3d, event, create=create):
                    if create:
                        _undo("LightPaint Add")
                    else:
                        self.painting = True
                    return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}
        return {'PASS_THROUGH'}


def _undo(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except Exception:
        pass


def is_running():
    return session.get(SESSION).running


classes = (LIGHTSTUDIO_OT_lightpaint,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    session.get(SESSION).reset()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
