"""Operators: adding / removing lights, studio setups, adopting lights, presets."""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from mathutils import Vector

from . import core, presets, sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def light_collection(scene):
    coll = bpy.data.collections.get(sync.COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(sync.COLLECTION)
    if coll.name not in scene.collection.children and coll not in scene.collection.children_recursive:
        try:
            scene.collection.children.link(coll)
        except RuntimeError:
            pass
    return coll


def _unique_name(name):
    if name not in bpy.data.objects:
        return name
    i = 2
    while f"{name} {i}" in bpy.data.objects:
        i += 1
    return f"{name} {i}"


def new_light(context, preset='SOFTBOX_LARGE', az=30.0, el=25.0, lon=None, lat=None,
              name=None, select=True, **overrides):
    scene = context.scene
    s = scene.light_studio
    ptype = presets.LIGHT_PRESETS[preset][3].get("light_type", 'AREA')
    label = name or presets.LIGHT_PRESETS[preset][0]
    data = bpy.data.lights.new(_unique_name(label), type=ptype)
    obj = bpy.data.objects.new(_unique_name(label), data)
    light_collection(scene).objects.link(obj)
    ls = obj.light_studio
    ls.managed = True
    presets.apply_light_preset(ls, preset)
    ls.distance = s.default_distance
    ls.lon = core.wrap_lon(sync.front_lon(scene) + math.radians(az)) if lon is None else lon
    ls.lat = math.radians(el) if lat is None else lat
    for k, v in overrides.items():
        setattr(ls, k, v)
    sync.request(obj, texture=True)
    if select:
        _select_only(context, obj)
    return obj


def _select_only(context, obj):
    try:
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except (RuntimeError, AttributeError):
        pass
    sync.set_active(context, obj)


def remove_light(obj):
    data = obj.data
    imgs = []
    nt = getattr(data, "node_tree", None)
    if nt is not None:
        node = nt.nodes.get(sync.IMG_NODE)
        if node is not None and node.image is not None:
            imgs.append(node.image)
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.lights.remove(data)
    for img in imgs:
        if img.users == 0:
            bpy.data.images.remove(img)


def _active(context):
    return sync.active_light(context)


class _ActiveLightOp:
    @classmethod
    def poll(cls, context):
        return _active(context) is not None


# ---------------------------------------------------------------------------
# Add / remove
# ---------------------------------------------------------------------------

class LIGHTSTUDIO_OT_add_light(bpy.types.Operator):
    bl_idname = "light_studio.add_light"
    bl_label = "Add Light"
    bl_description = "Add a managed light from a preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Preset", items=presets.light_enum_items())

    def execute(self, context):
        new_light(context, self.preset)
        return {'FINISHED'}


class LIGHTSTUDIO_OT_remove_light(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.remove_light"
    bl_label = "Remove Light"
    bl_description = "Delete the active managed light"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        remove_light(_active(context))
        rest = sync.managed_lights(context.scene)
        if rest:
            _select_only(context, rest[-1])
        return {'FINISHED'}


class LIGHTSTUDIO_OT_duplicate_light(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.duplicate_light"
    bl_label = "Duplicate Light"
    bl_description = "Duplicate the active light and rotate the copy a little"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        src = _active(context)
        obj = src.copy()
        obj.data = src.data.copy()
        obj.name = _unique_name(src.name)
        nt = obj.data.node_tree
        if nt is not None and nt.nodes.get(sync.IMG_NODE) is not None:
            nt.nodes[sync.IMG_NODE].image = None
        for coll in src.users_collection:
            coll.objects.link(obj)
        obj.light_studio.lon = core.wrap_lon(src.light_studio.lon + math.radians(20))
        sync.request(obj, texture=True)
        _select_only(context, obj)
        return {'FINISHED'}


class LIGHTSTUDIO_OT_select_light(bpy.types.Operator):
    bl_idname = "light_studio.select_light"
    bl_label = "Select Light"
    bl_options = {'INTERNAL'}

    name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is not None:
            _select_only(context, obj)
        return {'FINISHED'}


class LIGHTSTUDIO_OT_solo(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.solo"
    bl_label = "Solo Light"
    bl_description = "Disable every other managed light (run again to enable all)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        act = _active(context)
        lights = sync.managed_lights(context.scene)
        others = [o for o in lights if o != act]
        solo = any(o.light_studio.enabled for o in others) or not act.light_studio.enabled
        for o in others:
            o.light_studio.enabled = not solo
        act.light_studio.enabled = True
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Studio setups
# ---------------------------------------------------------------------------

def clear_lights(scene):
    for obj in sync.managed_lights(scene):
        remove_light(obj)


class LIGHTSTUDIO_OT_load_setup(bpy.types.Operator):
    bl_idname = "light_studio.load_setup"
    bl_label = "Load Studio Setup"
    bl_description = "Create a complete lighting setup around the target"
    bl_options = {'REGISTER', 'UNDO'}

    setup: EnumProperty(name="Setup", items=presets.studio_enum_items())
    replace: BoolProperty(name="Replace Existing", default=True,
                          description="Delete the current managed lights first")

    def execute(self, context):
        if self.replace:
            clear_lights(context.scene)
        _label, _desc, lights = presets.STUDIO_PRESETS[self.setup]
        last = None
        for spec in lights:
            spec = dict(spec)
            preset = spec.pop("preset")
            name = spec.pop("name")
            az = spec.pop("az")
            el = spec.pop("el")
            last = new_light(context, preset, az=az, el=el, name=name, select=False, **spec)
        if last is not None:
            _select_only(context, last)
        return {'FINISHED'}


class LIGHTSTUDIO_OT_rotate_all(bpy.types.Operator):
    bl_idname = "light_studio.rotate_all"
    bl_label = "Rotate All Lights"
    bl_description = "Rotate every managed light around its pivot"
    bl_options = {'REGISTER', 'UNDO'}

    angle: FloatProperty(name="Angle", subtype='ANGLE', default=math.radians(45))

    def execute(self, context):
        for obj in sync.managed_lights(context.scene):
            ls = obj.light_studio
            ls.lon = core.wrap_lon(ls.lon + self.angle)
        return {'FINISHED'}


class LIGHTSTUDIO_OT_target_selected(bpy.types.Operator):
    bl_idname = "light_studio.target_selected"
    bl_label = "Use Selected as Target"
    bl_description = "Arrange the lights around the selected object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type != 'LIGHT'

    def execute(self, context):
        s = context.scene.light_studio
        s.target_mode = 'OBJECT'
        s.target = context.active_object
        return {'FINISHED'}


class LIGHTSTUDIO_OT_reset_pivot(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.reset_pivot"
    bl_label = "Aim at Studio Target"
    bl_description = "Stop aiming at the painted point and orbit the studio target again"
    bl_options = {'REGISTER', 'UNDO'}

    keep_position: BoolProperty(name="Keep Position", default=True,
                                description="Keep the light where it is and re-aim it")

    def execute(self, context):
        obj = _active(context)
        ls = obj.light_studio
        pos = obj.matrix_world.translation.copy()
        ls.pivot_mode = 'TARGET'
        if self.keep_position:
            d = pos - sync.target_point(context.scene)
            if d.length > 1e-6:
                ls.lon, ls.lat = core.dir_to_lonlat(tuple(d))
                ls.distance = d.length
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Adopt / release existing lights
# ---------------------------------------------------------------------------

def adopt(scene, obj):
    """Turn an ordinary light into a managed one, keeping its look."""
    s = scene.light_studio
    data = obj.data
    # Snapshot everything first: enabling management rewrites the light.
    mw = obj.matrix_world.copy()
    scale = mw.to_scale()
    src = dict(
        type=data.type, color=tuple(data.color), energy=data.energy,
        use_temperature=getattr(data, "use_temperature", False),
        temperature=getattr(data, "temperature", 6500.0),
        visible_camera=obj.visible_camera,
    )
    if data.type == 'AREA':
        src.update(size_x=data.size * scale.x,
                   size_y=(data.size_y if data.shape in {'RECTANGLE', 'ELLIPSE'} else data.size) * scale.y,
                   shape=data.shape, spread=getattr(data, "spread", math.pi))
    elif data.type == 'SPOT':
        src.update(spot_size=data.spot_size, spot_blend=data.spot_blend,
                   radius=data.shadow_soft_size)
    elif data.type == 'POINT':
        src.update(radius=data.shadow_soft_size)
    elif data.type == 'SUN':
        src.update(angle=data.angle)

    pos = mw.translation.copy()
    d = pos - sync.target_point(scene)
    dist = d.length
    if dist < 1e-4:
        dist = s.default_distance
        d = mw.to_3x3() @ Vector((0.0, 0.0, 1.0))  # lights shine along -Z
    lon, lat = core.dir_to_lonlat(tuple(d))
    x_axis = mw.to_3x3().normalized().col[0]

    ls = obj.light_studio
    ls.managed = False  # no syncing while the settings are filled in
    presets._reset(ls)
    t = src["type"] if src["type"] in {'AREA', 'SPOT', 'POINT', 'SUN'} else 'POINT'
    ls.light_type = t
    ls.pivot_mode = 'TARGET'
    ls.lon, ls.lat, ls.distance = lon, lat, dist
    ls.roll = core.roll_from_axes(lon, lat, tuple(x_axis))
    ls.color = src["color"]
    ls.use_temperature = src["use_temperature"]
    ls.temperature = src["temperature"]
    ls.softness = ls.falloff = ls.roundness = 0.0
    if t == 'AREA':
        sx, sy = src["size_x"], src["size_y"]
        ls.width = max(2.0 * math.atan(sx / (2.0 * dist)), math.radians(0.1))
        ls.height = max(2.0 * math.atan(sy / (2.0 * dist)), math.radians(0.1))
        ls.shape = 'ELLIPSE' if src["shape"] in {'DISK', 'ELLIPSE'} else 'RECT'
        ls.intensity = src["energy"] / max(core.area_power(1.0, sx, sy, ls.shape == 'ELLIPSE'), 1e-9)
        ls.spread = max(src["spread"], math.radians(1))
    elif t == 'SPOT':
        ls.shape = 'ELLIPSE'
        ls.width = ls.height = min(src["spot_size"], math.radians(170))
        ls.softness = src["spot_blend"]
        ls.source_size = min(2.0 * math.atan(src["radius"] / dist), math.radians(60))
        ls.intensity = src["energy"] / (core.point_power(1.0, dist) * sync.POINT_CAL)
    elif t == 'POINT':
        ls.width = max(2.0 * math.atan(src["radius"] / dist), math.radians(0.1))
        ls.intensity = src["energy"] / (core.point_power(1.0, dist) * sync.POINT_CAL)
    else:
        ls.width = max(src["angle"], math.radians(0.1))
        ls.intensity = src["energy"]
    ls.intensity = ls.intensity / max(s.power_scale, 1e-9)
    ls.visible_camera = src["visible_camera"]
    ls.managed = True
    sync.request(obj, texture=True)


class LIGHTSTUDIO_OT_adopt(bpy.types.Operator):
    bl_idname = "light_studio.adopt"
    bl_label = "Manage Selected Lights"
    bl_description = ("Let Light Studio control the selected lights. Their current "
                      "position, size, colour and power are kept")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'LIGHT' and not sync.is_managed(o) for o in context.selected_objects)

    def execute(self, context):
        n = 0
        for obj in context.selected_objects:
            if obj.type == 'LIGHT' and not sync.is_managed(obj):
                adopt(context.scene, obj)
                n += 1
        self.report({'INFO'}, f"{n} light(s) now managed by Light Studio")
        return {'FINISHED'}


class LIGHTSTUDIO_OT_release(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.release"
    bl_label = "Release Light"
    bl_description = ("Stop managing the active light. It stays in the scene exactly as it "
                      "is (its texture is packed into the .blend)")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active(context)
        sync.flush_now()
        nt = obj.data.node_tree
        node = nt.nodes.get(sync.IMG_NODE) if nt else None
        if node is not None and node.image is not None:
            node.image.name = f"Light Texture {obj.name}"
            if sync.OWNER_KEY in node.image:
                del node.image[sync.OWNER_KEY]
            try:
                node.image.pack()
            except Exception:
                pass
        obj.light_studio.managed = False
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

class LIGHTSTUDIO_OT_gradient_swap(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.gradient_swap"
    bl_label = "Swap Gradient Colors"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ls = _active(context).light_studio
        ca, va = tuple(ls.gradient_color_a), ls.gradient_value_a
        ls.gradient_color_a, ls.gradient_value_a = tuple(ls.gradient_color_b), ls.gradient_value_b
        ls.gradient_color_b, ls.gradient_value_b = ca, va
        return {'FINISHED'}


class LIGHTSTUDIO_OT_gradient_reset(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.gradient_reset"
    bl_label = "Reset Gradient"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ls = _active(context).light_studio
        for key in ("gradient_angle", "gradient_offset", "gradient_scale", "gradient_midpoint",
                    "gradient_interp", "gradient_color_a", "gradient_value_a",
                    "gradient_color_b", "gradient_value_b"):
            ls.property_unset(key)
        sync.request(_active(context), texture=True)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# User presets
# ---------------------------------------------------------------------------

class LIGHTSTUDIO_OT_save_light_preset(_ActiveLightOp, bpy.types.Operator):
    bl_idname = "light_studio.save_light_preset"
    bl_label = "Save Light Preset"
    bl_description = "Save the active light's settings as a preset (available in every file)"

    name: StringProperty(name="Name", default="My Light")

    def invoke(self, context, event):
        self.name = _active(context).name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        data = presets.load_user_presets()
        data["lights"][self.name] = presets.light_to_dict(_active(context).light_studio)
        presets.save_user_presets(data)
        self.report({'INFO'}, f"Saved light preset '{self.name}'")
        return {'FINISHED'}


class LIGHTSTUDIO_OT_save_setup(bpy.types.Operator):
    bl_idname = "light_studio.save_setup"
    bl_label = "Save Studio Setup"
    bl_description = "Save all managed lights as a setup (available in every file)"

    name: StringProperty(name="Name", default="My Setup")

    @classmethod
    def poll(cls, context):
        return bool(sync.managed_lights(context.scene))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        data = presets.load_user_presets()
        front = sync.front_lon(context.scene)
        lights = []
        for obj in sync.managed_lights(context.scene):
            d = presets.light_to_dict(obj.light_studio, placement=True)
            d["lon"] = core.wrap_lon(d["lon"] - front)  # store relative to the camera
            d["name"] = obj.name
            lights.append(d)
        data["studios"][self.name] = {"lights": lights}
        presets.save_user_presets(data)
        self.report({'INFO'}, f"Saved setup '{self.name}'")
        return {'FINISHED'}


class LIGHTSTUDIO_OT_load_user_preset(bpy.types.Operator):
    bl_idname = "light_studio.load_user_preset"
    bl_label = "Load User Preset"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    kind: EnumProperty(items=[('LIGHT', "Light", ""), ('STUDIO', "Studio", "")])
    name: StringProperty()

    def execute(self, context):
        data = presets.load_user_presets()
        scene = context.scene
        if self.kind == 'LIGHT':
            d = data["lights"].get(self.name)
            if d is None:
                return {'CANCELLED'}
            obj = new_light(context, 'SOFTBOX_LARGE', name=self.name)
            presets.dict_to_light(obj.light_studio, d)
            sync.request(obj, texture=True)
            return {'FINISHED'}
        st = data["studios"].get(self.name)
        if st is None:
            return {'CANCELLED'}
        clear_lights(scene)
        front = sync.front_lon(scene)
        last = None
        for d in st.get("lights", []):
            obj = new_light(context, 'SOFTBOX_LARGE', name=d.get("name", "Light"), select=False)
            presets.dict_to_light(obj.light_studio, d)
            obj.light_studio.lon = core.wrap_lon(d.get("lon", 0.0) + front)
            sync.request(obj, texture=True)
            last = obj
        if last is not None:
            _select_only(context, last)
        return {'FINISHED'}


class LIGHTSTUDIO_OT_delete_user_preset(bpy.types.Operator):
    bl_idname = "light_studio.delete_user_preset"
    bl_label = "Delete User Preset"
    bl_options = {'INTERNAL'}

    kind: EnumProperty(items=[('LIGHT', "Light", ""), ('STUDIO', "Studio", "")])
    name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        data = presets.load_user_presets()
        group = data["lights"] if self.kind == 'LIGHT' else data["studios"]
        group.pop(self.name, None)
        presets.save_user_presets(data)
        return {'FINISHED'}


classes = (
    LIGHTSTUDIO_OT_add_light,
    LIGHTSTUDIO_OT_remove_light,
    LIGHTSTUDIO_OT_duplicate_light,
    LIGHTSTUDIO_OT_select_light,
    LIGHTSTUDIO_OT_solo,
    LIGHTSTUDIO_OT_load_setup,
    LIGHTSTUDIO_OT_rotate_all,
    LIGHTSTUDIO_OT_target_selected,
    LIGHTSTUDIO_OT_reset_pivot,
    LIGHTSTUDIO_OT_adopt,
    LIGHTSTUDIO_OT_release,
    LIGHTSTUDIO_OT_gradient_swap,
    LIGHTSTUDIO_OT_gradient_reset,
    LIGHTSTUDIO_OT_save_light_preset,
    LIGHTSTUDIO_OT_save_setup,
    LIGHTSTUDIO_OT_load_user_preset,
    LIGHTSTUDIO_OT_delete_user_preset,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
