import bpy

from . import canvas, lightpaint, studio


class HDRISTUDIO_UL_lights(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        icons = {'RECT': 'MESH_PLANE', 'ELLIPSE': 'MESH_CIRCLE',
                 'OCTAGON': 'SEQ_CHROMA_SCOPE', 'RING': 'MESH_TORUS'}
        row = layout.row(align=True)
        if item.blend != 'ADD':
            ic = 'SNAP_FACE'
        else:
            ic = icons.get(item.shape, 'LIGHT')
        if item.output == 'AREA':
            ic = 'LIGHT_AREA'
        row.prop(item, "name", text="", emboss=False, icon=ic)
        sub = row.row(align=True)
        sub.prop(item, "intensity", text="", emboss=False)
        row.prop(item, "enabled", text="", emboss=False,
                 icon='HIDE_OFF' if item.enabled else 'HIDE_ON')


def _studio_toggles(layout, context):
    s = context.scene.hdri_studio
    col = layout.column(align=True)
    row = col.row(align=True)
    row.scale_y = 1.3
    row.operator("hdri_studio.canvas_edit", text="Edit on Canvas",
                 icon='RESTRICT_SELECT_OFF', depress=canvas.is_editing())
    row.operator("hdri_studio.lightpaint", text="LightPaint",
                 icon='BRUSH_DATA', depress=lightpaint.is_running())
    row = col.row(align=True)
    row.prop(s, "paint_mode", expand=True)
    row.operator("hdri_studio.reset_tools", text="", icon='CANCEL')


class HDRIStudioPanel:
    bl_region_type = 'UI'
    bl_category = "HDRI Studio"


class _Main(HDRIStudioPanel):
    bl_label = "HDRI Studio"

    def draw(self, context):
        layout = self.layout
        s = context.scene.hdri_studio

        row = layout.row(align=True)
        if context.area.type == 'IMAGE_EDITOR' and canvas.is_canvas_space(context.space_data):
            pass
        else:
            row.scale_y = 1.3
            op = row.operator("hdri_studio.open_editor", text="Open Studio Editor", icon='WORKSPACE')
            op.mode = 'SPLIT'
            row.operator("hdri_studio.open_editor", text="", icon='WINDOW').mode = 'WINDOW'

        _studio_toggles(layout, context)

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(s, "auto_update", toggle=True, icon='FILE_REFRESH')
        row.operator("hdri_studio.update", text="Update", icon='RENDER_STILL')
        col.prop(s, "preview_res", text="")

        box = layout.box()
        world = studio.get_studio_world()
        active = world is not None and context.scene.world == world
        row = box.row(align=True)
        if active:
            row.label(text="Studio world active", icon='CHECKMARK')
        else:
            row.operator("hdri_studio.assign_world", icon='WORLD')
        row.operator("hdri_studio.restore_world", text="", icon='LOOP_BACK')
        box.prop(s, "world_strength")
        box.operator("hdri_studio.viewport_preview", icon='SHADING_TEXTURE')

        row = layout.row(align=True)
        row.menu("HDRISTUDIO_MT_studio", icon='PRESET')
        row.operator("hdri_studio.rotate_all", text="", icon='FILE_REFRESH')


class _Lights(HDRIStudioPanel):
    bl_label = "Lights"

    def draw(self, context):
        layout = self.layout
        s = context.scene.hdri_studio
        row = layout.row()
        row.template_list("HDRISTUDIO_UL_lights", "", s, "lights", s, "active_index", rows=5)
        col = row.column(align=True)
        col.menu("HDRISTUDIO_MT_add_light", text="", icon='ADD')
        col.operator("hdri_studio.remove_light", text="", icon='REMOVE')
        col.operator("hdri_studio.duplicate_light", text="", icon='DUPLICATE')
        col.separator()
        col.operator("hdri_studio.move_light", text="", icon='TRIA_UP').direction = 'UP'
        col.operator("hdri_studio.move_light", text="", icon='TRIA_DOWN').direction = 'DOWN'
        col.separator()
        col.operator("hdri_studio.clear_lights", text="", icon='TRASH')
        layout.prop(s, "canvas_add_preset", text="Ctrl+Click")


class _LightProps(HDRIStudioPanel):
    bl_label = "Light Properties"

    @classmethod
    def poll(cls, context):
        s = context.scene.hdri_studio
        return 0 <= s.active_index < len(s.lights)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.hdri_studio
        l = s.lights[s.active_index]

        layout.row().prop(l, "shape", expand=True, icon_only=True)
        layout.prop(l, "blend")
        layout.prop(l, "output")

        col = layout.column(align=True)
        col.prop(l, "lon")
        col.prop(l, "lat")
        col.prop(l, "roll")

        col = layout.column(align=True)
        col.prop(l, "width")
        col.prop(l, "height")

        col = layout.column(align=True)
        col.prop(l, "softness")
        if l.shape == 'RECT':
            col.prop(l, "roundness")
        if l.shape == 'RING':
            col.prop(l, "ring_inner")
        col.prop(l, "falloff")
        col.prop(l, "gradient")

        col = layout.column(align=True)
        col.prop(l, "color")
        col.prop(l, "use_temperature")
        sub = col.column()
        sub.active = l.use_temperature
        sub.prop(l, "temperature")
        if l.blend != 'MULTIPLY':
            layout.prop(l, "intensity")
        layout.prop(l, "opacity")

        col = layout.column()
        col.prop(l, "use_texture")
        if l.use_texture:
            col.template_ID(l, "texture", open="image.open")
            if l.output != 'HDRI':
                col.label(text="Textures only affect the HDRI", icon='INFO')


class _AreaLights(HDRIStudioPanel):
    bl_label = "Area Lights"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.hdri_studio
        layout.label(text="Turn HDRI lights into real Area lights")
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "area_target")
        col.prop(s, "area_distance")
        col.prop(s, "area_power_scale")
        layout.label(text="Active light:")
        row = layout.row(align=True)
        for key, text in (('HDRI', "HDRI"), ('AREA', "Area"), ('BOTH', "Both")):
            op = row.operator("hdri_studio.set_output", text=text)
            op.output, op.all_lights = key, False
        layout.label(text="All lights:")
        row = layout.row(align=True)
        for key, text in (('HDRI', "HDRI"), ('AREA', "Area"), ('BOTH', "Both")):
            op = row.operator("hdri_studio.set_output", text=text)
            op.output, op.all_lights = key, True
        layout.operator("hdri_studio.bake_area_lights", icon='UNLINKED')


class _Background(HDRIStudioPanel):
    bl_label = "Background"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.hdri_studio
        layout.prop(s, "bg_mode")
        if s.bg_mode == 'SOLID':
            layout.prop(s, "bg_color")
        elif s.bg_mode == 'GRADIENT':
            col = layout.column(align=True)
            col.prop(s, "bg_top")
            col.prop(s, "bg_horizon")
            col.prop(s, "bg_bottom")
            layout.prop(s, "bg_blend")
        else:
            layout.template_ID(s, "bg_image", open="image.open")
            layout.prop(s, "bg_rotation")
        layout.prop(s, "bg_strength")


class _Display(HDRIStudioPanel):
    bl_label = "Canvas Display"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.hdri_studio
        row = self.layout.row(align=True)
        row.prop(s, "show_outlines", toggle=True)
        row.prop(s, "show_labels", toggle=True)


class _Export(HDRIStudioPanel):
    bl_label = "Export"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.hdri_studio
        row = layout.row(align=True)
        row.prop(s, "export_res", expand=True)
        layout.prop(s, "export_format", text="")
        layout.operator("hdri_studio.export", icon='EXPORT')


_BASES = (_Main, _Lights, _LightProps, _AreaLights, _Background, _Display, _Export)


def _make_panels():
    panels = []
    for space, tag in (('IMAGE_EDITOR', "IMAGE"), ('VIEW_3D', "VIEW3D")):
        parent = None
        for base in _BASES:
            name = f"HDRISTUDIO_PT_{tag}_{base.__name__.strip('_').lower()}"
            attrs = {"bl_space_type": space, "bl_idname": name}
            if base is not _Main:
                attrs["bl_parent_id"] = parent
            cls = type(name, (base, bpy.types.Panel), attrs)
            if base is _Main:
                parent = name
            panels.append(cls)
    return panels


PANELS = _make_panels()


def draw_image_header(self, context):
    if not canvas.is_canvas_space(context.space_data):
        return
    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    row.label(text="HDRI Studio", icon='LIGHT_AREA')
    row.operator("hdri_studio.canvas_edit", text="Edit", icon='RESTRICT_SELECT_OFF',
                 depress=canvas.is_editing())
    row.menu("HDRISTUDIO_MT_add_light", text="", icon='ADD')
    row.menu("HDRISTUDIO_MT_studio", text="", icon='PRESET')
    row.operator("hdri_studio.update", text="", icon='FILE_REFRESH')


def draw_open_menu(self, context):
    self.layout.separator()
    self.layout.operator("hdri_studio.open_editor", text="HDRI Studio Editor",
                         icon='LIGHT_AREA').mode = 'SPLIT'


classes = (HDRISTUDIO_UL_lights, *PANELS)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.IMAGE_HT_header.append(draw_image_header)
    bpy.types.VIEW3D_MT_view.append(draw_open_menu)
    bpy.types.TOPBAR_MT_window.append(draw_open_menu)


def unregister():
    bpy.types.TOPBAR_MT_window.remove(draw_open_menu)
    bpy.types.VIEW3D_MT_view.remove(draw_open_menu)
    bpy.types.IMAGE_HT_header.remove(draw_image_header)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
