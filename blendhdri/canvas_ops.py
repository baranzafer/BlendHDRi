"""Direct editing of lights on the HDRI canvas (Image Editor).

Editing happens through the "HDRI Lights" tool in the Image Editor's toolbar.
A tool's keymap is evaluated before the editor's own keymaps, so its clicks
are not swallowed by the default Sample tool. Each operator runs once per
event and returns PASS_THROUGH when the event is not for a light, so panning
and zooming keep working. The only modal operator (``canvas_drag``) lives just
while the mouse button is held and ends on release, on a missed release
(next press), on focus loss or when its region disappears.
"""

import math
import traceback

import bpy
from bpy.props import EnumProperty

from . import canvas, render, session, studio
from .ops import active_light, new_light

TOOL_ID = "hdri_studio.light_tool"
DEFAULT_TOOL = "builtin.sample"

_pending = {}


def _poll(context):
    if not canvas.is_canvas_space(context.space_data):
        return False
    return context.region is not None and context.region.type == 'WINDOW'


def tool_active(context):
    """True if the HDRI Lights tool is the active Image Editor (View) tool."""
    try:
        tool = context.workspace.tools.from_space_image_mode('VIEW', create=False)
        return tool is not None and tool.idname == TOOL_ID
    except Exception:
        return False


def set_tool(area, enable=True):
    """Activate (or leave) the HDRI Lights tool in an Image Editor area."""
    if area is None or area.type != 'IMAGE_EDITOR':
        return False
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    try:
        if area.spaces.active.ui_mode != 'VIEW':
            area.spaces.active.ui_mode = 'VIEW'
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name=TOOL_ID if enable else DEFAULT_TOOL,
                                      space_type='IMAGE_EDITOR')
        return True
    except Exception:
        traceback.print_exc()
        return False


def _undo(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except Exception:
        pass


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


def _light_under(context, event):
    return canvas.pick_light(context.scene, context.region, event)


# ---------------------------------------------------------------------------
# Click: select / start drag / add
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_canvas_press(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_press"
    bl_label = "HDRI Canvas Click"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        try:
            return self._invoke(context, event)
        except Exception:
            traceback.print_exc()
            return {'PASS_THROUGH'}

    def _invoke(self, context, event):
        st = context.scene.hdri_studio
        u, v = canvas.mouse_uv(context.region, event)
        index = -1 if st.canvas_tool == 'ADD' else _light_under(context, event)
        if index >= 0:
            st.active_index = index
            light = st.lights[index]
            cu, cv = render.lonlat_to_uv(light.lon, light.lat)
            _pending.clear()
            _pending.update(
                index=index, x=event.mouse_x, y=event.mouse_y,
                du=(cu - u + 0.5) % 1.0 - 0.5, dv=cv - v,
                orig=(light.lon, light.lat, light.width, light.height, light.roll))
            bpy.ops.hdri_studio.canvas_drag('INVOKE_DEFAULT')
            return {'FINISHED'}
        if (event.ctrl or st.canvas_tool == 'ADD') and 0.0 <= v <= 1.0:
            lon, lat = render.uv_to_lonlat(u % 1.0, v)
            new_light(context.scene, st.canvas_add_preset, lon=lon, lat=lat)
            studio.schedule_update(context.scene, force=True)
            _undo("Add HDRI Light")
            return {'FINISHED'}
        return {'PASS_THROUGH'}


class HDRISTUDIO_OT_canvas_drag(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_drag"
    bl_label = "Drag HDRI Light"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not _pending:
            return {'CANCELLED'}
        self.data = dict(_pending)
        _pending.clear()
        self.region = context.region
        self.area = context.area
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, commit=True, passthrough=False):
        if commit:
            _undo("Edit HDRI Light")
        try:
            self.area.tag_redraw()
        except Exception:
            pass
        return {'FINISHED', 'PASS_THROUGH'} if passthrough else {'FINISHED'}

    def _light(self, context):
        st = context.scene.hdri_studio
        i = self.data["index"]
        return st.lights[i] if i < len(st.lights) else None

    def _restore(self, context):
        l = self._light(context)
        if l is not None:
            l.lon, l.lat, l.width, l.height, l.roll = self.data["orig"]

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:
            traceback.print_exc()
            return self._end(commit=False)

    def _modal(self, context, event):
        if not session.region_alive(self.region) or self._light(context) is None:
            return self._end(commit=False)
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._update(context, event)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return self._end()
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._restore(context)
            return self._end(commit=False)
        if event.type == 'WINDOW_DEACTIVATE':
            return self._end(passthrough=True)
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            return self._end(passthrough=True)   # release happened outside Blender
        return {'PASS_THROUGH'}

    def _update(self, context, event):
        d = self.data
        st = context.scene.hdri_studio
        l = self._light(context)
        lon0, lat0, w0, h0, roll0 = d["orig"]
        dx = event.mouse_x - d["x"]
        tool = st.canvas_tool
        if tool == 'SCALE':
            f = math.exp(dx / 150.0)
            if not event.alt:
                l.width = w0 * f
            if not event.shift:
                l.height = h0 * f
        elif tool == 'ROTATE':
            l.roll = render.wrap_lon(roll0 + dx * 0.01)
        else:
            r = self.region
            u, v = r.view2d.region_to_view(event.mouse_x - r.x, event.mouse_y - r.y)
            lon, lat = render.uv_to_lonlat((u + d["du"]) % 1.0, min(max(v + d["dv"], 0.0), 1.0))
            if st.snap_angle:
                step = math.radians(5)
                lon = round(lon / step) * step
                lat = round(lat / step) * step
            l.lon = render.wrap_lon(lon)
            l.lat = max(-math.pi / 2, min(math.pi / 2, lat))


# ---------------------------------------------------------------------------
# Hover highlight
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_canvas_hover(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_hover"
    bl_label = "HDRI Canvas Hover"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        try:
            h = _light_under(context, event)
            if h != canvas.state["hover"]:
                canvas.state["hover"] = h
                _redraw(context)
        except Exception:
            traceback.print_exc()
        return {'PASS_THROUGH'}


# ---------------------------------------------------------------------------
# Wheel: Ctrl = size, Shift = rotation, Alt = intensity
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_canvas_wheel(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_wheel"
    bl_label = "HDRI Canvas Wheel"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        if not (event.ctrl or event.shift or event.alt):
            return {'PASS_THROUGH'}
        st = context.scene.hdri_studio
        index = _light_under(context, event)
        light = st.lights[index] if index >= 0 else None
        if light is None:
            return {'PASS_THROUGH'}
        up = self.direction == 'UP'
        if event.ctrl:
            f = 1.08 if up else 1.0 / 1.08
            light.width = light.width * f
            light.height = light.height * f
        elif event.shift:
            light.roll = render.wrap_lon(light.roll + math.radians(5 if up else -5))
        else:
            light.intensity = light.intensity * (1.1 if up else 1.0 / 1.1)
        st.active_index = index
        _undo("Edit HDRI Light")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Keys and context menu (only act on the light under the cursor)
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_canvas_key(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_key"
    bl_label = "HDRI Canvas Key"
    bl_options = {'INTERNAL'}

    action: EnumProperty(items=[('DELETE', "Delete", ""), ('HIDE', "Hide", "")])

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        st = context.scene.hdri_studio
        index = _light_under(context, event)
        if index < 0:
            return {'PASS_THROUGH'}
        if self.action == 'DELETE':
            studio.remove_area_light(st.lights[index])
            st.lights.remove(index)
            st.active_index = min(st.active_index, len(st.lights) - 1)
            canvas.state["hover"] = -1
            studio.schedule_update(context.scene, force=True)
            _undo("Delete HDRI Light")
        else:
            st.lights[index].enabled = not st.lights[index].enabled
            _undo("Toggle HDRI Light")
        return {'FINISHED'}


class HDRISTUDIO_OT_canvas_context(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_context"
    bl_label = "HDRI Canvas Context Menu"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        index = _light_under(context, event)
        if index < 0:
            return {'PASS_THROUGH'}
        context.scene.hdri_studio.active_index = index
        bpy.ops.wm.call_menu(name="HDRISTUDIO_MT_light_context")
        return {'FINISHED'}


class HDRISTUDIO_MT_light_context(bpy.types.Menu):
    bl_idname = "HDRISTUDIO_MT_light_context"
    bl_label = "HDRI Light"

    def draw(self, context):
        layout = self.layout
        l = active_light(context.scene)
        if l is None:
            return
        layout.prop(l, "name", text="")
        layout.prop(l, "enabled")
        layout.separator()
        layout.operator("hdri_studio.duplicate_light", icon='DUPLICATE')
        layout.operator("hdri_studio.remove_light", icon='TRASH')
        layout.separator()
        layout.props_enum(l, "output")
        layout.separator()
        layout.operator("hdri_studio.light_popup", text="Color…", icon='COLOR').section = 'COLOR'
        layout.operator("hdri_studio.light_popup", text="Texture…", icon='TEXTURE').section = 'TEXTURE'
        layout.operator("hdri_studio.save_light_preset", icon='FILE_TICK')


class HDRISTUDIO_OT_light_popup(bpy.types.Operator):
    bl_idname = "hdri_studio.light_popup"
    bl_label = "Light Settings"
    bl_options = {'INTERNAL'}

    section: EnumProperty(items=[('COLOR', "Color", ""), ('TEXTURE', "Texture", "")])

    @classmethod
    def poll(cls, context):
        return active_light(context.scene) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=280)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        l = active_light(context.scene)
        if l is None:
            return
        layout = self.layout
        if self.section == 'COLOR':
            layout.label(text=l.name, icon='COLOR')
            layout.template_color_picker(l, "color", value_slider=True)
            layout.prop(l, "color", text="")
            row = layout.row(align=True)
            row.prop(l, "use_temperature", text="")
            sub = row.row(align=True)
            sub.active = l.use_temperature
            sub.prop(l, "temperature")
        else:
            layout.label(text=l.name, icon='TEXTURE')
            layout.prop(l, "use_texture")
            layout.template_ID(l, "texture", open="image.open")


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_fit_view(bpy.types.Operator):
    bl_idname = "hdri_studio.fit_view"
    bl_label = "Fit Canvas"
    bl_description = "Fit the whole HDRI canvas into the editor"

    @classmethod
    def poll(cls, context):
        return canvas.is_canvas_space(context.space_data)

    def execute(self, context):
        fit_area(context.area)
        return {'FINISHED'}


def fit_area(area):
    if area is None:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return
    try:
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.image.view_all(fit_view=True)
    except Exception:
        traceback.print_exc()


class HDRISTUDIO_OT_canvas_edit_toggle(bpy.types.Operator):
    bl_idname = "hdri_studio.canvas_edit_toggle"
    bl_label = "Edit on Canvas"
    bl_description = ("Switch the Image Editor to the HDRI Lights tool to select and drag "
                      "lights on the canvas (click again to go back to Sample)")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'IMAGE_EDITOR'

    def execute(self, context):
        if not canvas.is_canvas_space(context.space_data):
            img = studio.get_canvas(context.scene, create=False) or studio.update_preview(context.scene)
            context.space_data.image = img
        set_tool(context.area, enable=not tool_active(context))
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


def _draw_tool_settings(context, layout, tool):
    st = context.scene.hdri_studio
    layout.prop(st, "canvas_tool", expand=True)
    layout.prop(st, "canvas_add_preset", text="Add")
    layout.prop(st, "snap_angle", text="Snap 5°")


class HDRIStudioLightTool(bpy.types.WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'
    bl_context_mode = 'VIEW'
    bl_idname = TOOL_ID
    bl_label = "HDRI Lights"
    bl_description = ("Select and drag HDRI Studio lights on the canvas.\n"
                      "Ctrl+Click: add light · Ctrl/Shift/Alt+Wheel: size/rotation/intensity\n"
                      "H / X over a light: hide / delete · Right click: light menu")
    bl_icon = "ops.transform.translate"
    bl_widget = None
    bl_keymap = (
        ("hdri_studio.canvas_press", {"type": 'LEFTMOUSE', "value": 'PRESS', "any": True}, None),
        ("hdri_studio.canvas_hover", {"type": 'MOUSEMOVE', "value": 'ANY', "any": True}, None),
        ("hdri_studio.canvas_wheel", {"type": 'WHEELUPMOUSE', "value": 'PRESS', "any": True},
         {"properties": [("direction", 'UP')]}),
        ("hdri_studio.canvas_wheel", {"type": 'WHEELDOWNMOUSE', "value": 'PRESS', "any": True},
         {"properties": [("direction", 'DOWN')]}),
        ("hdri_studio.canvas_key", {"type": 'X', "value": 'PRESS'}, {"properties": [("action", 'DELETE')]}),
        ("hdri_studio.canvas_key", {"type": 'DEL', "value": 'PRESS'}, {"properties": [("action", 'DELETE')]}),
        ("hdri_studio.canvas_key", {"type": 'H', "value": 'PRESS'}, {"properties": [("action", 'HIDE')]}),
        ("hdri_studio.canvas_context", {"type": 'RIGHTMOUSE', "value": 'PRESS'}, None),
    )

    def draw_settings(context, layout, tool):
        _draw_tool_settings(context, layout, tool)


classes = (
    HDRISTUDIO_OT_canvas_edit_toggle,
    HDRISTUDIO_OT_canvas_press,
    HDRISTUDIO_OT_canvas_drag,
    HDRISTUDIO_OT_canvas_hover,
    HDRISTUDIO_OT_canvas_wheel,
    HDRISTUDIO_OT_canvas_key,
    HDRISTUDIO_OT_canvas_context,
    HDRISTUDIO_MT_light_context,
    HDRISTUDIO_OT_light_popup,
    HDRISTUDIO_OT_fit_view,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.utils.register_tool(HDRIStudioLightTool, after={DEFAULT_TOOL}, separator=True)


def unregister():
    try:
        bpy.utils.unregister_tool(HDRIStudioLightTool)
    except Exception:
        traceback.print_exc()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
