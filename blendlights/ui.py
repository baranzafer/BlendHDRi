"""Sidebar panels (3D View > N > Light Studio), menus and the light list."""

import bpy

from . import lightpaint, presets, sync

CATEGORY = "Light Studio"

TYPE_ICON = {'AREA': 'LIGHT_AREA', 'SPOT': 'LIGHT_SPOT', 'POINT': 'LIGHT_POINT', 'SUN': 'LIGHT_SUN'}


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

class LIGHTSTUDIO_MT_add(bpy.types.Menu):
    bl_idname = "LIGHTSTUDIO_MT_add"
    bl_label = "Add Studio Light"

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        groups = {}
        for key, (label, _d, icon, params) in presets.LIGHT_PRESETS.items():
            groups.setdefault(params.get("light_type", 'AREA'), []).append((key, label, icon))
        for ltype, title in (('AREA', "Area / Softbox"), ('SPOT', "Spot"),
                             ('POINT', "Point / Sun")):
            col = row.column()
            col.label(text=title, icon=TYPE_ICON[ltype])
            items = groups.get(ltype, [])
            if ltype == 'POINT':
                items = items + groups.get('SUN', [])
            for key, label, icon in items:
                col.operator("light_studio.add_light", text=label, icon=icon).preset = key
        user = presets.load_user_presets()["lights"]
        if user:
            col = row.column()
            col.label(text="My Lights", icon='USER')
            for name in sorted(user):
                op = col.operator("light_studio.load_user_preset", text=name, icon='LIGHT')
                op.kind, op.name = 'LIGHT', name


class LIGHTSTUDIO_MT_setups(bpy.types.Menu):
    bl_idname = "LIGHTSTUDIO_MT_setups"
    bl_label = "Studio Setups"

    def draw(self, context):
        layout = self.layout
        for key, (label, desc, _l) in presets.STUDIO_PRESETS.items():
            layout.operator("light_studio.load_setup", text=label, icon='LIGHT').setup = key
        user = presets.load_user_presets()["studios"]
        if user:
            layout.separator()
            layout.label(text="My Setups", icon='USER')
            for name in sorted(user):
                op = layout.operator("light_studio.load_user_preset", text=name, icon='SCENE')
                op.kind, op.name = 'STUDIO', name


class LIGHTSTUDIO_MT_manage_presets(bpy.types.Menu):
    bl_idname = "LIGHTSTUDIO_MT_manage_presets"
    bl_label = "Delete User Presets"

    def draw(self, context):
        layout = self.layout
        data = presets.load_user_presets()
        if not data["lights"] and not data["studios"]:
            layout.label(text="No user presets yet")
        for name in sorted(data["lights"]):
            op = layout.operator("light_studio.delete_user_preset", text=f"Light: {name}", icon='X')
            op.kind, op.name = 'LIGHT', name
        for name in sorted(data["studios"]):
            op = layout.operator("light_studio.delete_user_preset", text=f"Setup: {name}", icon='X')
            op.kind, op.name = 'STUDIO', name


class LIGHTSTUDIO_MT_light_specials(bpy.types.Menu):
    bl_idname = "LIGHTSTUDIO_MT_light_specials"
    bl_label = "Light Studio"

    def draw(self, context):
        layout = self.layout
        layout.operator("light_studio.duplicate_light", icon='DUPLICATE')
        layout.operator("light_studio.solo", icon='SOLO_ON')
        layout.operator("light_studio.rotate_all", icon='DRIVER_ROTATIONAL_DIFFERENCE')
        layout.separator()
        layout.operator("light_studio.adopt", icon='IMPORT')
        layout.operator("light_studio.release", icon='UNLINKED')
        layout.separator()
        layout.operator("light_studio.save_light_preset", icon='PRESET_NEW')
        layout.operator("light_studio.save_setup", icon='PRESET_NEW')
        layout.menu("LIGHTSTUDIO_MT_manage_presets", icon='TRASH')


# ---------------------------------------------------------------------------
# Light list (scene objects filtered to managed lights)
# ---------------------------------------------------------------------------

class LIGHTSTUDIO_UL_lights(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        ls = item.light_studio
        row = layout.row(align=True)
        row.prop(ls, "enabled", text="", emboss=False,
                 icon='HIDE_OFF' if ls.enabled else 'HIDE_ON')
        row.prop(item, "name", text="", emboss=False, icon=TYPE_ICON.get(ls.light_type, 'LIGHT'))
        if ls.pivot_mode == 'POINT':
            row.label(text="", icon='BRUSH_DATA')

    def filter_items(self, context, data, propname):
        objs = getattr(data, propname)
        flags = [self.bitflag_filter_item if sync.is_managed(o) else 0 for o in objs]
        if self.filter_name:
            f = self.filter_name.lower()
            flags = [fl if f in o.name.lower() else 0 for fl, o in zip(flags, objs)]
        return flags, []


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

class _Sidebar:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY


class LIGHTSTUDIO_PT_main(_Sidebar, bpy.types.Panel):
    bl_label = "Light Studio"
    bl_idname = "LIGHTSTUDIO_PT_main"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        s = scene.light_studio

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(s, "target_mode", text="")
        if s.target_mode == 'OBJECT':
            row.prop(s, "target", text="")
            row.operator("light_studio.target_selected", text="", icon='EYEDROPPER')
        row = layout.row(align=True)
        row.prop(s, "default_distance", text="Distance")
        row.prop(s, "power_scale", text="Power")

        # LightPaint
        box = layout.box()
        running = lightpaint.is_running()
        row = box.row(align=True)
        row.scale_y = 1.4
        row.operator("light_studio.lightpaint", text="Stop LightPaint" if running else "LightPaint",
                     icon='BRUSH_DATA', depress=running)
        row.operator("light_studio.reset_tools", text="", icon='X')
        box.row(align=True).prop(s, "paint_mode", expand=True)
        row = box.row(align=True)
        row.label(text="Aim")
        row.prop(s, "paint_pivot", text="")
        box.prop(s, "paint_add_preset", text="Shift+Click")

        row = layout.row(align=True)
        row.menu("LIGHTSTUDIO_MT_add", text="Add Light", icon='ADD')
        row.menu("LIGHTSTUDIO_MT_setups", text="Setups", icon='LIGHT')

        row = layout.row()
        row.template_list("LIGHTSTUDIO_UL_lights", "", scene, "objects", s, "active_index", rows=5)
        col = row.column(align=True)
        col.menu("LIGHTSTUDIO_MT_add", text="", icon='ADD')
        col.operator("light_studio.remove_light", text="", icon='REMOVE')
        col.separator()
        col.operator("light_studio.duplicate_light", text="", icon='DUPLICATE')
        col.operator("light_studio.solo", text="", icon='SOLO_ON')
        col.separator()
        col.menu("LIGHTSTUDIO_MT_light_specials", text="", icon='DOWNARROW_HLT')

        if any(o.type == 'LIGHT' and not sync.is_managed(o) for o in context.selected_objects):
            layout.operator("light_studio.adopt", icon='IMPORT')


def draw_light(layout, context, obj):
    """The main light settings (shared by the sidebar and the Properties editor)."""
    ls = obj.light_studio
    t = ls.light_type

    row = layout.row(align=True)
    row.prop(ls, "light_type", expand=True)

    col = layout.column(align=True)
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(ls, "lon")
    col.prop(ls, "lat")
    col.prop(ls, "roll")

    col = layout.column(align=True)
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(ls, "distance")
    row = col.row(align=True)
    row.prop(ls, "pivot_mode", text="Aim At")
    if ls.pivot_mode == 'POINT':
        row.operator("light_studio.reset_pivot", text="", icon='PIVOT_CURSOR')

    col = layout.column(align=True)
    col.use_property_split = True
    col.use_property_decorate = False
    if t in {'AREA', 'SPOT'}:
        col.prop(ls, "width", text="Width" if t == 'AREA' else "Beam Width")
        col.prop(ls, "height", text="Height" if t == 'AREA' else "Beam Height")
    else:
        col.prop(ls, "width", text="Size" if t == 'POINT' else "Angle")
    if t == 'SPOT':
        col.prop(ls, "source_size")

    if t in {'AREA', 'SPOT'}:
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(ls, "shape")
        col.prop(ls, "softness", slider=True)
        if ls.shape in {'RECT'}:
            col.prop(ls, "roundness", slider=True)
        if ls.shape == 'RING':
            col.prop(ls, "ring_inner", slider=True)
        col.prop(ls, "falloff", slider=True)
        col.prop(ls, "gradient_type", text="Gradient")

    col = layout.column(align=True)
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(ls, "color")
    col.prop(ls, "use_temperature")
    sub = col.row()
    sub.active = ls.use_temperature
    sub.prop(ls, "temperature")

    col = layout.column(align=True)
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(ls, "intensity")
    col.prop(ls, "opacity", slider=True)
    if t == 'AREA':
        col.prop(ls, "spread")
        col.prop(ls, "visible_camera")

    if t in {'AREA', 'SPOT'} and context.scene.render.engine != 'CYCLES':
        info = layout.box().column(align=True)
        info.scale_y = 0.8
        info.label(text="Shape, softness, gradient and", icon='INFO')
        info.label(text="textures are rendered by Cycles.")


class LIGHTSTUDIO_PT_light(_Sidebar, bpy.types.Panel):
    bl_label = "Light"
    bl_idname = "LIGHTSTUDIO_PT_light"
    bl_parent_id = "LIGHTSTUDIO_PT_main"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return sync.active_light(context) is not None

    def draw_header(self, context):
        obj = sync.active_light(context)
        self.layout.prop(obj.light_studio, "enabled", text="")

    def draw(self, context):
        obj = sync.active_light(context)
        self.layout.prop(obj, "name", text="", icon=TYPE_ICON.get(obj.light_studio.light_type))
        draw_light(self.layout, context, obj)


class LIGHTSTUDIO_PT_gradient(_Sidebar, bpy.types.Panel):
    bl_label = "Gradient"
    bl_idname = "LIGHTSTUDIO_PT_gradient"
    bl_parent_id = "LIGHTSTUDIO_PT_light"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = sync.active_light(context)
        return obj is not None and obj.light_studio.light_type in {'AREA', 'SPOT'}

    def draw(self, context):
        draw_gradient(self.layout, sync.active_light(context).light_studio)


def draw_gradient(layout, ls):
    layout.prop(ls, "gradient_type", expand=True)
    if ls.gradient_type == 'NONE':
        return
    col = layout.column(align=True)
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(ls, "gradient_angle")
    col.prop(ls, "gradient_offset", slider=True)
    col.prop(ls, "gradient_scale")
    col.prop(ls, "gradient_midpoint", slider=True)
    col.prop(ls, "gradient_interp")
    for c, v, label in (("gradient_color_a", "gradient_value_a", "A"),
                        ("gradient_color_b", "gradient_value_b", "B")):
        row = layout.row(align=True)
        row.label(text=label)
        row.prop(ls, c, text="")
        row.prop(ls, v, text="Strength")
    row = layout.row(align=True)
    row.operator("light_studio.gradient_swap", text="Swap", icon='ARROW_LEFTRIGHT')
    row.operator("light_studio.gradient_reset", text="Reset", icon='LOOP_BACK')


class LIGHTSTUDIO_PT_texture(_Sidebar, bpy.types.Panel):
    bl_label = "Texture"
    bl_idname = "LIGHTSTUDIO_PT_texture"
    bl_parent_id = "LIGHTSTUDIO_PT_light"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = sync.active_light(context)
        return obj is not None and obj.light_studio.light_type in {'AREA', 'SPOT'}

    def draw_header(self, context):
        self.layout.prop(sync.active_light(context).light_studio, "use_texture", text="")

    def draw(self, context):
        draw_texture(self.layout, sync.active_light(context))


def draw_texture(layout, obj):
    ls = obj.light_studio
    col = layout.column()
    col.active = ls.use_texture
    col.template_ID(ls, "texture", open="image.open")
    if ls.light_type == 'SPOT':
        col.label(text="Projected like a gobo", icon='INFO')
    col.prop(ls, "texture_res", text="Resolution")
    nt = obj.data.node_tree if obj.type == 'LIGHT' else None
    node = nt.nodes.get(sync.IMG_NODE) if nt else None
    img = node.image if node is not None else None
    linked = img is not None and sync.is_textured(obj)
    if img is not None and linked:
        box = layout.box()
        box.label(text="Generated light texture:")
        try:
            img.preview_ensure()
            box.template_icon(icon_value=img.preview.icon_id, scale=6.0)
        except Exception:
            box.label(text=img.name)


class LIGHTSTUDIO_PT_settings(_Sidebar, bpy.types.Panel):
    bl_label = "Settings"
    bl_idname = "LIGHTSTUDIO_PT_settings"
    bl_parent_id = "LIGHTSTUDIO_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.light_studio
        col = self.layout.column()
        col.prop(s, "follow_transform")
        col.prop(s, "show_overlay")
        col.separator()
        col.operator("light_studio.rotate_all", icon='DRIVER_ROTATIONAL_DIFFERENCE')
        row = col.row(align=True)
        row.operator("light_studio.save_light_preset", text="Save Light", icon='PRESET_NEW')
        row.operator("light_studio.save_setup", text="Save Setup", icon='PRESET_NEW')
        col.menu("LIGHTSTUDIO_MT_manage_presets", icon='TRASH')


# Properties editor > Light data ------------------------------------------------

class LIGHTSTUDIO_PT_data(bpy.types.Panel):
    bl_label = "Light Studio"
    bl_idname = "LIGHTSTUDIO_PT_data"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'LIGHT'

    def draw(self, context):
        obj = context.object
        if not sync.is_managed(obj):
            self.layout.operator("light_studio.adopt", icon='IMPORT')
            return
        self.layout.label(text="Managed by Light Studio (other light settings are overridden)",
                          icon='INFO')
        draw_light(self.layout, context, obj)


def _add_menu(self, context):
    self.layout.menu("LIGHTSTUDIO_MT_add", text="Studio Light", icon='LIGHT_AREA')


classes = (
    LIGHTSTUDIO_MT_add,
    LIGHTSTUDIO_MT_setups,
    LIGHTSTUDIO_MT_manage_presets,
    LIGHTSTUDIO_MT_light_specials,
    LIGHTSTUDIO_UL_lights,
    LIGHTSTUDIO_PT_main,
    LIGHTSTUDIO_PT_light,
    LIGHTSTUDIO_PT_gradient,
    LIGHTSTUDIO_PT_texture,
    LIGHTSTUDIO_PT_settings,
    LIGHTSTUDIO_PT_data,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_light_add.append(_add_menu)


def unregister():
    bpy.types.VIEW3D_MT_light_add.remove(_add_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
