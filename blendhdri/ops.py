import math
import os

import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper

from . import presets, render, studio


front_lon = studio.front_lon


def new_light(scene, preset='SOFTBOX_LARGE', az=30.0, el=25.0, lon=None, lat=None):
    s = scene.hdri_studio
    light = s.lights.add()
    presets.apply_light_preset(light, preset)
    light.lon = render.wrap_lon(front_lon(scene) + math.radians(az)) if lon is None else lon
    light.lat = math.radians(el) if lat is None else lat
    names = {l.name for l in s.lights if l != light}
    base, i = light.name, 1
    while light.name in names:
        i += 1
        light.name = f"{base} {i}"
    s.active_index = len(s.lights) - 1
    return light


def active_light(scene):
    s = scene.hdri_studio
    if 0 <= s.active_index < len(s.lights):
        return s.lights[s.active_index]
    return None


class HDRISTUDIO_OT_add_light(bpy.types.Operator):
    bl_idname = "hdri_studio.add_light"
    bl_label = "Add Light"
    bl_description = "Add a preset light to the HDRI"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Preset", items=presets.light_enum_items())

    def execute(self, context):
        new_light(context.scene, self.preset)
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_remove_light(bpy.types.Operator):
    bl_idname = "hdri_studio.remove_light"
    bl_label = "Remove Light"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_light(context.scene) is not None

    def execute(self, context):
        s = context.scene.hdri_studio
        s.lights.remove(s.active_index)
        s.active_index = min(s.active_index, len(s.lights) - 1)
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_duplicate_light(bpy.types.Operator):
    bl_idname = "hdri_studio.duplicate_light"
    bl_label = "Duplicate Light"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_light(context.scene) is not None

    def execute(self, context):
        s = context.scene.hdri_studio
        src = active_light(context.scene)
        dst = s.lights.add()
        for prop in src.bl_rna.properties:
            if prop.identifier in {'rna_type', 'area_object'} or prop.is_readonly:
                continue
            setattr(dst, prop.identifier, getattr(src, prop.identifier))
        dst.name = src.name + " Copy"
        dst.lon = render.wrap_lon(src.lon - math.radians(15))
        s.active_index = len(s.lights) - 1
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_move_light(bpy.types.Operator):
    bl_idname = "hdri_studio.move_light"
    bl_label = "Move Light"
    bl_description = "Change the layer order (lower layers are drawn first)"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def execute(self, context):
        s = context.scene.hdri_studio
        i = s.active_index
        j = i - 1 if self.direction == 'UP' else i + 1
        if 0 <= j < len(s.lights):
            s.lights.move(i, j)
            s.active_index = j
            studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_clear_lights(bpy.types.Operator):
    bl_idname = "hdri_studio.clear_lights"
    bl_label = "Clear All Lights"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        context.scene.hdri_studio.lights.clear()
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_apply_studio(bpy.types.Operator):
    bl_idname = "hdri_studio.apply_studio"
    bl_label = "Load Studio Setup"
    bl_description = "Load a complete lighting setup (relative to the active camera)"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Setup", items=presets.studio_enum_items())
    replace: BoolProperty(name="Replace Existing Lights", default=True)

    def execute(self, context):
        scene = context.scene
        s = scene.hdri_studio
        _label, _desc, bg, lights = presets.STUDIO_PRESETS[self.preset]
        if self.replace:
            s.lights.clear()
            for k, v in bg.items():
                setattr(s, k, v)
        for spec in lights:
            spec = dict(spec)
            light = new_light(scene, spec.pop('preset'), spec.pop('az'), spec.pop('el'))
            light.name = spec.pop('name')
            for k, v in spec.items():
                setattr(light, k, v)
        s.active_index = 0 if s.lights else -1
        studio.schedule_update(scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_update(bpy.types.Operator):
    bl_idname = "hdri_studio.update"
    bl_label = "Update HDRI"
    bl_description = "Re-render the HDRI preview now"

    def execute(self, context):
        studio.clear_background_cache()
        studio.update_preview(context.scene)
        return {'FINISHED'}


class HDRISTUDIO_OT_assign_world(bpy.types.Operator):
    bl_idname = "hdri_studio.assign_world"
    bl_label = "Use Studio World"
    bl_description = "Use the HDRI Studio world for this scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        studio.update_preview(context.scene)
        studio.ensure_world(context.scene, activate=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_restore_world(bpy.types.Operator):
    bl_idname = "hdri_studio.restore_world"
    bl_label = "Restore Previous World"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.hdri_studio.previous_world is not None

    def execute(self, context):
        context.scene.world = context.scene.hdri_studio.previous_world
        return {'FINISHED'}


class HDRISTUDIO_OT_rotate_all(bpy.types.Operator):
    bl_idname = "hdri_studio.rotate_all"
    bl_label = "Rotate All Lights"
    bl_description = "Rotate every light horizontally around the scene"
    bl_options = {'REGISTER', 'UNDO'}

    angle: FloatProperty(name="Angle", subtype='ANGLE', default=math.radians(45))

    def execute(self, context):
        s = context.scene.hdri_studio
        for l in s.lights:
            l.lon = render.wrap_lon(l.lon + self.angle)
        s.bg_rotation += self.angle
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_open_editor(bpy.types.Operator):
    bl_idname = "hdri_studio.open_editor"
    bl_label = "Open HDRI Studio Editor"
    bl_description = ("Split the current area and open the HDRI Studio canvas "
                      "(an Image Editor showing the live HDRI)")

    mode: EnumProperty(
        name="Open In",
        items=[
            ('SPLIT', "Split Area", "Split the current area, like opening a Shader Editor"),
            ('REPLACE', "This Area", "Turn the current area into the studio canvas"),
            ('WINDOW', "New Window", "Open the studio canvas in a new window"),
        ],
        default='SPLIT')

    def execute(self, context):
        scene = context.scene
        img = studio.get_canvas(scene, create=False)
        if img is None or not scene.hdri_studio.lights:
            if not scene.hdri_studio.lights:
                bpy.ops.hdri_studio.apply_studio(preset='THREE_POINT')
            img = studio.update_preview(scene)

        area = context.area
        if area is None or area.type in {'TOPBAR', 'STATUSBAR', 'OUTLINER', 'PROPERTIES'}:
            # e.g. invoked from the Window menu: use the biggest 3D view instead
            areas = [a for a in context.screen.areas if a.type == 'VIEW_3D'] or \
                [a for a in context.screen.areas if a.type not in {'TOPBAR', 'STATUSBAR'}]
            area = max(areas, key=lambda a: a.width * a.height, default=None)
        if area is None:
            self.report({'ERROR'}, "Run this from an editor area")
            return {'CANCELLED'}
        if self.mode == 'REPLACE':
            target = area
        else:
            target = self._split(context, area)
            if self.mode == 'WINDOW' and target is not area:
                self._setup(target, img)
                if self._pop_out(context, target):
                    studio.tag_redraw()
                    return {'FINISHED'}

        if target is None:
            self.report({'ERROR'}, "No area to open the studio in")
            return {'CANCELLED'}
        self._setup(target, img)
        studio.tag_redraw()
        return {'FINISHED'}

    @staticmethod
    def _window_region(area):
        return next((r for r in area.regions if r.type == 'WINDOW'), None)

    def _split(self, context, area):
        before = set(context.screen.areas[:])
        try:
            with context.temp_override(area=area, region=self._window_region(area)):
                bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
        except Exception:
            return area
        new = [a for a in context.screen.areas if a not in before]
        return new[0] if new else area

    @staticmethod
    def _setup(target, img):
        target.type = 'IMAGE_EDITOR'
        space = target.spaces.active
        space.image = img
        try:
            space.ui_mode = 'VIEW'
        except Exception:
            pass
        space.show_region_ui = True
        try:
            space.show_region_toolbar = False
        except Exception:
            pass
        # Fit once the new area has its final size.
        def fit():
            try:
                from . import canvas_ops
                canvas_ops.fit_area(target)
                canvas_ops.set_tool(target, enable=True)
            except Exception:
                pass
            return None
        bpy.app.timers.register(fit, first_interval=0.15)

    def _pop_out(self, context, target):
        """Move the freshly split area into its own window."""
        try:
            with context.temp_override(area=target, region=self._window_region(target)):
                ret = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
            if 'FINISHED' not in ret:
                return False
            with context.temp_override(area=target, region=self._window_region(target)):
                bpy.ops.screen.area_close()
            return True
        except Exception:
            return False


class HDRISTUDIO_OT_viewport_preview(bpy.types.Operator):
    bl_idname = "hdri_studio.viewport_preview"
    bl_label = "Preview in Viewport"
    bl_description = ("Switch the 3D viewports to Material Preview using the scene world, "
                      "so the studio HDRI is visible while you edit")

    def execute(self, context):
        studio.ensure_world(context.scene, activate=True)
        for area in context.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            shading = area.spaces.active.shading
            if shading.type not in {'MATERIAL', 'RENDERED'}:
                shading.type = 'MATERIAL'
            shading.use_scene_world = True
            shading.use_scene_world_render = True
            area.tag_redraw()
        return {'FINISHED'}


class HDRISTUDIO_OT_export(bpy.types.Operator, ExportHelper):
    bl_idname = "hdri_studio.export"
    bl_label = "Export HDRI"
    bl_description = "Render the HDRI at full resolution and save it to disk"

    filename_ext = ".exr"
    filter_glob: StringProperty(default="*.exr;*.hdr", options={'HIDDEN'})
    use_in_world: BoolProperty(
        name="Use Exported File in a New World",
        description="Create a world that uses the saved file (independent of the studio)",
        default=False)

    def invoke(self, context, event):
        s = context.scene.hdri_studio
        self.filename_ext = ".exr" if s.export_format == 'OPEN_EXR' else ".hdr"
        if not self.filepath:
            self.filepath = "studio_hdri" + self.filename_ext
        return super().invoke(context, event)

    def draw(self, context):
        s = context.scene.hdri_studio
        col = self.layout.column()
        col.prop(s, "export_res")
        col.prop(s, "export_format")
        col.prop(self, "use_in_world")

    def execute(self, context):
        scene = context.scene
        s = scene.hdri_studio
        ext = ".exr" if s.export_format == 'OPEN_EXR' else ".hdr"
        path = bpy.path.ensure_ext(os.path.splitext(self.filepath)[0], ext)
        width = int(s.export_res)
        context.window_manager.progress_begin(0, 1)
        try:
            if s.export_format == 'HDR':
                render.write_radiance_hdr(path, studio.render_array(scene, width))
            else:
                img = studio.render_export(scene, width)
                img.filepath_raw = path
                img.file_format = 'OPEN_EXR'
                img.save()
        except Exception as ex:  # pragma: no cover - reported to the user
            self.report({'ERROR'}, f"Export failed: {ex}")
            return {'CANCELLED'}
        finally:
            context.window_manager.progress_end()
        tmp = bpy.data.images.get(studio.EXPORT_NAME)
        if tmp is not None:
            bpy.data.images.remove(tmp)

        if self.use_in_world:
            loaded = bpy.data.images.load(path, check_existing=False)
            world = bpy.data.worlds.new(os.path.basename(path))
            try:
                world.use_nodes = True
            except Exception:
                pass
            nt = world.node_tree
            nt.nodes.clear()
            out = nt.nodes.new('ShaderNodeOutputWorld')
            bg = nt.nodes.new('ShaderNodeBackground')
            env = nt.nodes.new('ShaderNodeTexEnvironment')
            env.image = loaded
            out.location, bg.location, env.location = (300, 0), (100, 0), (-250, 0)
            nt.links.new(env.outputs['Color'], bg.inputs['Color'])
            nt.links.new(bg.outputs['Background'], out.inputs['Surface'])
            bg.inputs['Strength'].default_value = s.world_strength
            scene.world = world

        self.report({'INFO'}, f"Saved {path} ({width}x{width // 2})")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# User presets
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_save_light_preset(bpy.types.Operator):
    bl_idname = "hdri_studio.save_light_preset"
    bl_label = "Save Light Preset"
    bl_description = "Save the active light as a reusable preset (available in every file)"

    preset_name: StringProperty(name="Name", default="My Light")

    @classmethod
    def poll(cls, context):
        return active_light(context.scene) is not None

    def invoke(self, context, event):
        self.preset_name = active_light(context.scene).name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.preset_name.strip()
        if not name:
            return {'CANCELLED'}
        data = presets.load_user_presets()
        data["lights"][name] = presets.light_to_dict(active_light(context.scene))
        presets.save_user_presets(data)
        self.report({'INFO'}, f"Saved light preset '{name}'")
        return {'FINISHED'}


class HDRISTUDIO_OT_save_studio_preset(bpy.types.Operator):
    bl_idname = "hdri_studio.save_studio_preset"
    bl_label = "Save Studio Setup"
    bl_description = "Save all lights and the background as a reusable studio setup"

    preset_name: StringProperty(name="Name", default="My Studio")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.preset_name.strip()
        if not name:
            return {'CANCELLED'}
        data = presets.load_user_presets()
        data["studios"][name] = presets.studio_to_dict(context.scene.hdri_studio)
        presets.save_user_presets(data)
        self.report({'INFO'}, f"Saved studio setup '{name}'")
        return {'FINISHED'}


class HDRISTUDIO_OT_add_user_light(bpy.types.Operator):
    bl_idname = "hdri_studio.add_user_light"
    bl_label = "Add User Light"
    bl_options = {'REGISTER', 'UNDO'}

    preset_name: StringProperty()

    def execute(self, context):
        d = presets.load_user_presets()["lights"].get(self.preset_name)
        if d is None:
            self.report({'ERROR'}, "Preset not found")
            return {'CANCELLED'}
        light = new_light(context.scene, 'SOFTBOX_SQUARE')
        presets.dict_to_light(light, d)
        light.name = self.preset_name
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_apply_user_studio(bpy.types.Operator):
    bl_idname = "hdri_studio.apply_user_studio"
    bl_label = "Load User Studio"
    bl_options = {'REGISTER', 'UNDO'}

    preset_name: StringProperty()

    def execute(self, context):
        d = presets.load_user_presets()["studios"].get(self.preset_name)
        if d is None:
            self.report({'ERROR'}, "Setup not found")
            return {'CANCELLED'}
        presets.dict_to_studio(context.scene.hdri_studio, d)
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_delete_user_preset(bpy.types.Operator):
    bl_idname = "hdri_studio.delete_user_preset"
    bl_label = "Delete User Preset"

    kind: EnumProperty(items=[('lights', "Light", ""), ('studios', "Studio", "")])
    preset_name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        data = presets.load_user_presets()
        data[self.kind].pop(self.preset_name, None)
        presets.save_user_presets(data)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Area lights
# ---------------------------------------------------------------------------

class HDRISTUDIO_OT_set_output(bpy.types.Operator):
    bl_idname = "hdri_studio.set_output"
    bl_label = "Set Light Output"
    bl_description = "Choose whether lights live in the HDRI, as real Area lights, or both"
    bl_options = {'REGISTER', 'UNDO'}

    output: EnumProperty(items=[
        ('HDRI', "HDRI", ""), ('AREA', "Area Light", ""), ('BOTH', "Both", "")])
    all_lights: BoolProperty(name="All Lights", default=False)

    def execute(self, context):
        s = context.scene.hdri_studio
        targets = s.lights if self.all_lights else [active_light(context.scene)]
        for l in targets:
            if l is not None:
                l.output = self.output
        studio.schedule_update(context.scene, force=True)
        return {'FINISHED'}


class HDRISTUDIO_OT_bake_area_lights(bpy.types.Operator):
    bl_idname = "hdri_studio.bake_area_lights"
    bl_label = "Detach Area Lights"
    bl_description = ("Keep the generated Area lights as ordinary scene lights and "
                      "stop driving them from the studio")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.hdri_studio
        coll = bpy.data.collections.get(studio.AREA_COLLECTION)
        n = 0
        for l in s.lights:
            obj = l.area_object
            if obj is None:
                continue
            if coll is not None and obj.name in coll.objects:
                coll.objects.unlink(obj)
                context.scene.collection.objects.link(obj)
            l.area_object = None
            if l.output == 'AREA':
                l.enabled = False
            l.output = 'HDRI'
            n += 1
        studio.schedule_update(context.scene, force=True)
        self.report({'INFO'}, f"Detached {n} area light(s)")
        return {'FINISHED'}


class HDRISTUDIO_MT_add_light(bpy.types.Menu):
    bl_idname = "HDRISTUDIO_MT_add_light"
    bl_label = "Add Light"

    def draw(self, context):
        layout = self.layout
        for key, (label, _d, icon, _p) in presets.LIGHT_PRESETS.items():
            layout.operator(HDRISTUDIO_OT_add_light.bl_idname, text=label, icon=icon).preset = key
        user = presets.load_user_presets()["lights"]
        if user:
            layout.separator()
            layout.label(text="My Lights", icon='USER')
            for name in sorted(user):
                layout.operator(HDRISTUDIO_OT_add_user_light.bl_idname, text=name,
                                icon='LIGHT_AREA').preset_name = name
        layout.separator()
        layout.operator(HDRISTUDIO_OT_save_light_preset.bl_idname, icon='FILE_TICK')
        if user:
            layout.menu("HDRISTUDIO_MT_delete_user_lights", icon='TRASH')


class HDRISTUDIO_MT_studio(bpy.types.Menu):
    bl_idname = "HDRISTUDIO_MT_studio"
    bl_label = "Studio Setups"

    def draw(self, context):
        layout = self.layout
        for key, (label, _d, _b, _l) in presets.STUDIO_PRESETS.items():
            layout.operator(HDRISTUDIO_OT_apply_studio.bl_idname, text=label).preset = key
        user = presets.load_user_presets()["studios"]
        if user:
            layout.separator()
            layout.label(text="My Setups", icon='USER')
            for name in sorted(user):
                layout.operator(HDRISTUDIO_OT_apply_user_studio.bl_idname, text=name,
                                icon='LIGHT').preset_name = name
        layout.separator()
        layout.operator(HDRISTUDIO_OT_save_studio_preset.bl_idname, icon='FILE_TICK')
        if user:
            layout.menu("HDRISTUDIO_MT_delete_user_studios", icon='TRASH')


class HDRISTUDIO_MT_delete_user_lights(bpy.types.Menu):
    bl_idname = "HDRISTUDIO_MT_delete_user_lights"
    bl_label = "Delete Light Preset"

    def draw(self, context):
        for name in sorted(presets.load_user_presets()["lights"]):
            op = self.layout.operator(HDRISTUDIO_OT_delete_user_preset.bl_idname, text=name)
            op.kind, op.preset_name = 'lights', name


class HDRISTUDIO_MT_delete_user_studios(bpy.types.Menu):
    bl_idname = "HDRISTUDIO_MT_delete_user_studios"
    bl_label = "Delete Studio Setup"

    def draw(self, context):
        for name in sorted(presets.load_user_presets()["studios"]):
            op = self.layout.operator(HDRISTUDIO_OT_delete_user_preset.bl_idname, text=name)
            op.kind, op.preset_name = 'studios', name


classes = (
    HDRISTUDIO_OT_add_light,
    HDRISTUDIO_OT_remove_light,
    HDRISTUDIO_OT_duplicate_light,
    HDRISTUDIO_OT_move_light,
    HDRISTUDIO_OT_clear_lights,
    HDRISTUDIO_OT_apply_studio,
    HDRISTUDIO_OT_update,
    HDRISTUDIO_OT_assign_world,
    HDRISTUDIO_OT_restore_world,
    HDRISTUDIO_OT_rotate_all,
    HDRISTUDIO_OT_open_editor,
    HDRISTUDIO_OT_viewport_preview,
    HDRISTUDIO_OT_export,
    HDRISTUDIO_OT_save_light_preset,
    HDRISTUDIO_OT_save_studio_preset,
    HDRISTUDIO_OT_add_user_light,
    HDRISTUDIO_OT_apply_user_studio,
    HDRISTUDIO_OT_delete_user_preset,
    HDRISTUDIO_OT_set_output,
    HDRISTUDIO_OT_bake_area_lights,
    HDRISTUDIO_MT_add_light,
    HDRISTUDIO_MT_studio,
    HDRISTUDIO_MT_delete_user_lights,
    HDRISTUDIO_MT_delete_user_studios,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
