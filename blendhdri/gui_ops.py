"""Event handling for the studio interface.

All canvas interaction goes through keymap operators that run once per
event and return PASS_THROUGH when the event is not for us. The only modal
operator (``ui_drag``) lives just while a mouse button is held, and ends on
release, on a missed release (next press), on focus loss or when its
region disappears. Nothing can stay "stuck".
"""

import math
import traceback

import bpy
from bpy.props import EnumProperty

from . import canvas, gui, render, session, studio
from . import gui_kit as K
from .ops import active_light, new_light

_keymaps = []
_pending = {}


def _poll(context):
    space = context.space_data
    if not canvas.is_canvas_space(space):
        return False
    if context.region is None or context.region.type != 'WINDOW':
        return False
    try:
        return context.scene.hdri_studio.canvas_interaction or \
            context.scene.hdri_studio.use_custom_ui
    except Exception:
        return False


def _xy(event):
    return event.mouse_region_x, event.mouse_region_y


def _build(context):
    return gui.build_studio(context, context.region, None)


def _undo(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except Exception:
        pass


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


def _light_under(context, event):
    st = context.scene.hdri_studio
    if not st.canvas_interaction:
        return -1
    return canvas.pick_light(context.scene, context.region, event)


# ---------------------------------------------------------------------------
# Click
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_ui_press(bpy.types.Operator):
    bl_idname = "hdri_studio.ui_press"
    bl_label = "HDRI Studio Click"
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
        x, y = _xy(event)
        b = _build(context)
        t = b.hit(x, y)
        st = context.scene.hdri_studio
        if t is not None:
            if t.kind == 'button' and t.action is not None:
                t.action(context, event)
                studio.tag_redraw()
                _undo("HDRI Studio")
                return {'FINISHED'}
            if t.kind == 'slider':
                _start_drag(context, 'SLIDER', id=t.id, x=x, value=t.data["value"])
                # jump to the clicked position right away
                _apply_slider(context, t, x, event)
                return {'FINISHED'}
            if t.kind == 'title':
                pid = t.id.split(":")[0]
                pos = _panel_origin(b, pid)
                if pos is not None:
                    _start_drag(context, 'PANEL', id=pid, x=x, y=y, pos=pos)
                return {'FINISHED'}
            if t.kind == 'fold':
                pid = t.id.split(":")[0]
                gui.STATE["fold"][pid] = not gui.STATE["fold"].get(pid, False)
                _redraw(context)
                return {'FINISHED'}
            # panel background, strip, header: swallow the click
            return {'FINISHED'}

        if not st.canvas_interaction:
            return {'PASS_THROUGH'}
        u, v = canvas.mouse_uv(context.region, event)
        index = -1 if st.canvas_tool == 'ADD' else _light_under(context, event)
        if index >= 0:
            st.active_index = index
            light = st.lights[index]
            cu, cv = render.lonlat_to_uv(light.lon, light.lat)
            _start_drag(context, 'LIGHT', index=index, x=x, y=y,
                        du=(cu - u + 0.5) % 1.0 - 0.5, dv=cv - v,
                        orig=(light.lon, light.lat, light.width, light.height, light.roll))
            return {'FINISHED'}
        if (event.ctrl or st.canvas_tool == 'ADD') and 0.0 <= v <= 1.0:
            lon, lat = render.uv_to_lonlat(u % 1.0, v)
            new_light(context.scene, st.canvas_add_preset, lon=lon, lat=lat)
            studio.schedule_update(context.scene, force=True)
            _undo("Add HDRI Light")
            return {'FINISHED'}
        return {'PASS_THROUGH'}


def _panel_origin(b, pid):
    for t in b.targets:
        if t.id == pid + ":bg":
            x0, y0, x1, y1 = t.rect
            return (x0, y1)
    return None


# ---------------------------------------------------------------------------
# Drag (short-lived modal)
# ---------------------------------------------------------------------------

def _start_drag(context, mode, **data):
    _pending.clear()
    _pending.update(data)
    _pending["mode"] = mode
    bpy.ops.hdri_studio.ui_drag('INVOKE_DEFAULT')


def _apply_slider(context, t, x, event, start=None):
    d = t.data
    span = max(1.0, d["x1"] - d["x0"])
    vmin, vmax = d["vmin"], d["vmax"]
    if event.shift and start is not None:
        value = start[1] + (x - start[0]) / span * (vmax - vmin) * 0.1
    else:
        value = vmin + (x - d["x0"]) / span * (vmax - vmin)
    if event.ctrl:
        step = d["step"] * 10
        value = round(value / step) * step
    value = max(vmin, min(vmax, value))
    d["setter"](value)


class HDRISTUDIO_OT_ui_drag(bpy.types.Operator):
    bl_idname = "hdri_studio.ui_drag"
    bl_label = "HDRI Studio Drag"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not _pending:
            return {'CANCELLED'}
        self.data = dict(_pending)
        _pending.clear()
        self.region = context.region
        self.area = context.area
        gui.STATE["active"] = self.data.get("id")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context, commit=True, passthrough=False):
        gui.STATE["active"] = None
        if commit:
            _undo("HDRI Studio Edit")
        try:
            self.area.tag_redraw()
        except Exception:
            pass
        if passthrough:
            return {'FINISHED', 'PASS_THROUGH'}
        return {'FINISHED'}

    def _restore(self, context):
        d = self.data
        if d["mode"] == 'LIGHT':
            st = context.scene.hdri_studio
            if d["index"] < len(st.lights):
                l = st.lights[d["index"]]
                l.lon, l.lat, l.width, l.height, l.roll = d["orig"]
        elif d["mode"] == 'SLIDER':
            t = self._target(context)
            if t is not None:
                t.data["setter"](d["value"])
        elif d["mode"] == 'PANEL':
            gui.STATE["pos"][d["id"]] = d["pos"]

    def _target(self, context):
        b = gui.build_studio(context, self.region, None)
        for t in b.targets:
            if t.id == self.data.get("id"):
                return t
        return None

    def cancel(self, context):
        gui.STATE["active"] = None

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:
            traceback.print_exc()
            return self._end(context, commit=False)

    def _modal(self, context, event):
        if not session.region_alive(self.region):
            return self._end(context, commit=False)
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            x = event.mouse_x - self.region.x
            y = event.mouse_y - self.region.y
            self._update(context, event, x, y)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return self._end(context)
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._restore(context)
            return self._end(context, commit=False)
        if event.type == 'WINDOW_DEACTIVATE':
            return self._end(context, passthrough=True)
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # release happened outside Blender
            return self._end(context, passthrough=True)
        return {'RUNNING_MODAL'} if event.type in {'TIMER', 'NONE'} else {'PASS_THROUGH'}

    def _update(self, context, event, x, y):
        d = self.data
        mode = d["mode"]
        if mode == 'SLIDER':
            t = self._target(context)
            if t is not None:
                _apply_slider(context, t, x, event, start=(d["x"], d["value"]))
        elif mode == 'PANEL':
            px, py = d["pos"]
            gui.STATE["pos"][d["id"]] = (px + x - d["x"], py + y - d["y"])
            self.area.tag_redraw()
        elif mode == 'LIGHT':
            st = context.scene.hdri_studio
            if d["index"] >= len(st.lights):
                return
            l = st.lights[d["index"]]
            lon0, lat0, w0, h0, roll0 = d["orig"]
            dx = x - d["x"]
            tool = st.canvas_tool
            if tool == 'SCALE':
                f = math.exp(dx / (150.0 * K.ui_scale()))
                if not event.alt:
                    l.width = w0 * f
                if not event.shift:
                    l.height = h0 * f
            elif tool == 'ROTATE':
                l.roll = render.wrap_lon(roll0 + dx * 0.01)
            else:
                ev_x = event.mouse_x
                ev_y = event.mouse_y
                u, v = self.region.view2d.region_to_view(ev_x - self.region.x, ev_y - self.region.y)
                lon, lat = render.uv_to_lonlat((u + d["du"]) % 1.0,
                                               min(max(v + d["dv"], 0.0), 1.0))
                if st.snap_angle:
                    step = math.radians(5)
                    lon = round(lon / step) * step
                    lat = round(lat / step) * step
                l.lon = render.wrap_lon(lon)
                l.lat = max(-math.pi / 2, min(math.pi / 2, lat))


# ---------------------------------------------------------------------------
# Hover
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_ui_hover(bpy.types.Operator):
    bl_idname = "hdri_studio.ui_hover"
    bl_label = "HDRI Studio Hover"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        try:
            x, y = _xy(event)
            b = _build(context)
            t = b.hit(x, y)
            hid = t.id if t is not None and t.kind != 'panel' else None
            light = -1
            if t is None:
                light = _light_under(context, event)
            if hid != gui.STATE["hover"] or light != canvas.state["hover"]:
                gui.STATE["hover"] = hid
                canvas.state["hover"] = light
                _redraw(context)
        except Exception:
            traceback.print_exc()
        return {'PASS_THROUGH'}


# ---------------------------------------------------------------------------
# Wheel
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_ui_wheel(bpy.types.Operator):
    bl_idname = "hdri_studio.ui_wheel"
    bl_label = "HDRI Studio Wheel"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

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
        up = self.direction == 'UP'
        x, y = _xy(event)
        b = _build(context)
        t = b.hit(x, y)
        st = context.scene.hdri_studio
        if t is not None:
            if t.kind == 'slider':
                step = t.data["step"] * (0.2 if event.shift else (10 if event.ctrl else 1))
                v = t.data["value"] + (step if up else -step)
                t.data["setter"](max(t.data["vmin"], min(t.data["vmax"], v)))
                _undo("HDRI Studio Edit")
                return {'FINISHED'}
            if t.kind == 'strip' or t.id.startswith(("card:", "eye:")):
                gui.STATE["scroll"] += (-60 if up else 60) * K.ui_scale()
                _redraw(context)
                return {'FINISHED'}
            return {'FINISHED'}   # over a panel: never zoom the image
        if not (event.ctrl or event.shift or event.alt) or not st.canvas_interaction:
            return {'PASS_THROUGH'}
        index = _light_under(context, event)
        light = st.lights[index] if index >= 0 else active_light(context.scene)
        if light is None:
            return {'PASS_THROUGH'}
        if event.ctrl:
            f = 1.08 if up else 1.0 / 1.08
            light.width = light.width * f
            light.height = light.height * f
        elif event.shift:
            light.roll = render.wrap_lon(light.roll + math.radians(5 if up else -5))
        else:
            light.intensity = light.intensity * (1.1 if up else 1.0 / 1.1)
        _undo("HDRI Light")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Keys and context menu
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_ui_key(bpy.types.Operator):
    bl_idname = "hdri_studio.ui_key"
    bl_label = "HDRI Studio Key"
    bl_options = {'INTERNAL'}

    action: EnumProperty(items=[('DELETE', "Delete", ""), ('HIDE', "Hide", "")])

    @classmethod
    def poll(cls, context):
        return _poll(context) and context.scene.hdri_studio.canvas_interaction

    def invoke(self, context, event):
        st = context.scene.hdri_studio
        x, y = _xy(event)
        if _build(context).hit(x, y) is not None:
            return {'PASS_THROUGH'}
        index = _light_under(context, event)
        if index < 0:
            return {'PASS_THROUGH'}
        if self.action == 'DELETE':
            from .studio import remove_area_light
            remove_area_light(st.lights[index])
            st.lights.remove(index)
            st.active_index = min(st.active_index, len(st.lights) - 1)
            canvas.state["hover"] = -1
            studio.schedule_update(context.scene, force=True)
            _undo("Delete HDRI Light")
        else:
            st.lights[index].enabled = not st.lights[index].enabled
            _undo("Toggle HDRI Light")
        return {'FINISHED'}


class HDRISTUDIO_OT_ui_context(bpy.types.Operator):
    bl_idname = "hdri_studio.ui_context"
    bl_label = "HDRI Studio Context Menu"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        st = context.scene.hdri_studio
        x, y = _xy(event)
        t = _build(context).hit(x, y)
        index = -1
        if t is not None and t.id.startswith("card:"):
            index = int(t.id.split(":")[1])
        elif t is None:
            index = _light_under(context, event)
        if index < 0:
            return {'FINISHED'} if t is not None else {'PASS_THROUGH'}
        st.active_index = index
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
        layout.label(text=l.name, icon='LIGHT_AREA')
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


# ---------------------------------------------------------------------------
# Popups and view
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_light_popup(bpy.types.Operator):
    bl_idname = "hdri_studio.light_popup"
    bl_label = "Light Settings"
    bl_options = {'INTERNAL'}

    section: EnumProperty(items=[('COLOR', "Color", ""), ('TEXTURE', "Texture", ""),
                                 ('NAME', "Name", "")])

    @classmethod
    def poll(cls, context):
        return active_light(context.scene) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=int(280 * K.ui_scale()))

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
        elif self.section == 'TEXTURE':
            layout.label(text=l.name, icon='TEXTURE')
            layout.prop(l, "use_texture")
            layout.template_ID(l, "texture", open="image.open")
        else:
            layout.prop(l, "name")


class HDRISTUDIO_OT_fit_view(bpy.types.Operator):
    bl_idname = "hdri_studio.fit_view"
    bl_label = "Fit Canvas"
    bl_description = "Fit the HDRI between the studio panels"

    @classmethod
    def poll(cls, context):
        return canvas.is_canvas_space(context.space_data)

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        fit_area(context.area)
        return {'FINISHED'}


def fit_area(area):
    """Zoom the canvas so it fits between the panels of the studio UI."""
    if area is None:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    space = area.spaces.active
    if region is None or space.image is None:
        return
    s = K.ui_scale()
    use_ui = bpy.context.scene.hdri_studio.use_custom_ui
    side = (214 + 272 + 60) * s if use_ui else 40 * s
    vert = (gui.header_height() + gui.strip_height() + 70 * s) if use_ui else 40 * s
    w, h = space.image.size
    if w == 0:
        return
    ratio = min((region.width - side) / w, (region.height - vert) / h)
    ratio = max(0.05, ratio)
    try:
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.image.view_all(fit_view=False)
            bpy.ops.image.view_zoom_ratio(ratio=ratio)
    except Exception:
        traceback.print_exc()


classes = (
    HDRISTUDIO_OT_ui_press,
    HDRISTUDIO_OT_ui_drag,
    HDRISTUDIO_OT_ui_hover,
    HDRISTUDIO_OT_ui_wheel,
    HDRISTUDIO_OT_ui_key,
    HDRISTUDIO_OT_ui_context,
    HDRISTUDIO_MT_light_context,
    HDRISTUDIO_OT_light_popup,
    HDRISTUDIO_OT_fit_view,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:   # background mode
        return
    km = kc.keymaps.new(name='Image', space_type='IMAGE_EDITOR')
    items = [
        ("hdri_studio.ui_press", 'LEFTMOUSE', 'PRESS', {"any": True}, {}),
        ("hdri_studio.ui_hover", 'MOUSEMOVE', 'ANY', {"any": True}, {}),
        ("hdri_studio.ui_wheel", 'WHEELUPMOUSE', 'PRESS', {"any": True}, {"direction": 'UP'}),
        ("hdri_studio.ui_wheel", 'WHEELDOWNMOUSE', 'PRESS', {"any": True}, {"direction": 'DOWN'}),
        ("hdri_studio.ui_key", 'X', 'PRESS', {}, {"action": 'DELETE'}),
        ("hdri_studio.ui_key", 'DEL', 'PRESS', {}, {"action": 'DELETE'}),
        ("hdri_studio.ui_key", 'H', 'PRESS', {}, {"action": 'HIDE'}),
        ("hdri_studio.ui_context", 'RIGHTMOUSE', 'PRESS', {}, {}),
    ]
    for idname, key, value, mods, props in items:
        kmi = km.keymap_items.new(idname, key, value, **mods)
        for k, v in props.items():
            setattr(kmi.properties, k, v)
        _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymaps.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
