"""Properties: per light (on the light Object) and per scene."""

import math

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _owner(self):
    return self.id_data if isinstance(self.id_data, bpy.types.Object) else None


def _changed(self, context):
    from . import sync
    obj = _owner(self)
    if obj is not None:
        sync.request(obj, texture=False)


def _tex_changed(self, context):
    from . import sync
    obj = _owner(self)
    if obj is not None:
        sync.request(obj, texture=True)


def _scene_changed(self, context):
    from . import sync
    sync.request_all(context.scene if context else None)


def _active_index_changed(self, context):
    from . import sync
    sync.select_from_index(context)


def _redraw(self, context):
    from . import overlay
    overlay.tag_redraw()


LIGHT_TYPES = [
    ('AREA', "Area", "Softbox / panel: shape, softness and textures are visible in "
     "reflections and shape the light (Cycles)", 'LIGHT_AREA', 0),
    ('SPOT', "Spot", "Spot / projector: the shape and texture are projected like a gobo (Cycles)",
     'LIGHT_SPOT', 1),
    ('POINT', "Point", "Bulb: Width sets the size of the bulb (shadow softness)", 'LIGHT_POINT', 2),
    ('SUN', "Sun", "Sun: Width sets the angular diameter (shadow softness)", 'LIGHT_SUN', 3),
]

SHAPES = [
    ('RECT', "Rectangle", "Rectangle (Roundness rounds the corners)", 'MESH_PLANE', 0),
    ('ELLIPSE', "Round", "Round / elliptical", 'MESH_CIRCLE', 1),
    ('OCTAGON', "Octabox", "Eight-sided octabox", 'SEQ_CHROMA_SCOPE', 2),
    ('RING', "Ring", "Ring light", 'MESH_TORUS', 3),
]

TEX_RES = [
    ('128', "128", "Fastest"),
    ('256', "256", "Good balance"),
    ('512', "512", "Sharp"),
    ('1024', "1024", "Very sharp (slower updates)"),
]


class LightStudioLight(PropertyGroup):
    managed: BoolProperty(
        name="Managed", default=False, options={'HIDDEN'},
        description="This light is controlled by Light Studio")
    enabled: BoolProperty(name="Enabled", default=True, update=_changed)
    light_type: EnumProperty(name="Type", items=LIGHT_TYPES, default='AREA', update=_tex_changed)
    preset: StringProperty(name="Preset", default="", options={'HIDDEN'})

    # Placement --------------------------------------------------------------
    pivot_mode: EnumProperty(
        name="Aim At", default='TARGET', update=_changed,
        items=[
            ('TARGET', "Studio Target", "Orbit the studio target (object, 3D cursor or origin)"),
            ('POINT', "Painted Point", "Orbit the surface point picked with LightPaint"),
        ])
    pivot_point: FloatVectorProperty(
        name="Point", subtype='TRANSLATION', size=3, default=(0.0, 0.0, 0.0),
        update=_changed, description="Surface point the light aims at (set by LightPaint)")
    lon: FloatProperty(
        name="Longitude", description="Horizontal angle around the pivot",
        subtype='ANGLE', default=0.0, min=-math.pi, max=math.pi, update=_changed)
    lat: FloatProperty(
        name="Latitude", description="Elevation above the pivot",
        subtype='ANGLE', default=math.radians(20), min=-math.pi / 2, max=math.pi / 2,
        update=_changed)
    roll: FloatProperty(
        name="Rotation", description="Rotation of the light around its own axis",
        subtype='ANGLE', default=0.0, min=-math.pi, max=math.pi, update=_changed)
    distance: FloatProperty(
        name="Distance", description="Distance from the pivot",
        default=4.0, min=0.01, soft_max=50.0, unit='LENGTH', update=_changed)

    # Size -------------------------------------------------------------------
    width: FloatProperty(
        name="Width", subtype='ANGLE', default=math.radians(30),
        min=math.radians(0.1), max=math.radians(170), update=_changed,
        description=("Angular width as seen from the pivot. Area: size of the panel, "
                     "Spot: beam angle, Point: bulb size, Sun: disc size"))
    height: FloatProperty(
        name="Height", subtype='ANGLE', default=math.radians(30),
        min=math.radians(0.1), max=math.radians(170), update=_changed,
        description="Angular height as seen from the pivot (Area and Spot)")
    source_size: FloatProperty(
        name="Source Size", subtype='ANGLE', default=math.radians(2.0),
        min=0.0, max=math.radians(60), update=_changed,
        description="Spot only: angular size of the bulb (soft shadows)")

    # Shape ------------------------------------------------------------------
    shape: EnumProperty(name="Shape", items=SHAPES, default='RECT', update=_tex_changed)
    softness: FloatProperty(
        name="Edge Softness",
        description=("Soft edge width. 0 = hard edge, 1 = fades from the centre, "
                     "above 1 the light also blooms beyond its outline"),
        default=0.1, min=0.0, max=4.0, soft_max=2.0, update=_tex_changed)
    roundness: FloatProperty(
        name="Roundness",
        description="Rectangle corners: 0 = square, 1 = ellipse, above 1 sides curve inwards",
        default=0.05, min=0.0, max=2.0, update=_tex_changed)
    ring_inner: FloatProperty(
        name="Ring Inner Size", default=0.7, min=0.0, max=0.98,
        subtype='FACTOR', update=_tex_changed)
    falloff: FloatProperty(
        name="Center Falloff",
        description=("Brightness from the centre to the edge. Positive = hot spot "
                     "(above 1 it gets tighter), negative = brighter edges"),
        default=0.0, min=-1.0, max=8.0, soft_max=4.0, update=_tex_changed)

    # Gradient ---------------------------------------------------------------
    gradient_type: EnumProperty(
        name="Gradient", default='NONE', update=_tex_changed,
        items=[
            ('NONE', "None", "No gradient"),
            ('LINEAR', "Linear", "Colour A to colour B along a direction"),
            ('REFLECTED', "Reflected", "Colour A in the middle, colour B towards both sides"),
            ('RADIAL', "Radial", "Colour A in the centre, colour B at the edge"),
            ('ANGULAR', "Angular", "Colour A to colour B around the centre"),
        ])
    gradient_angle: FloatProperty(
        name="Angle", subtype='ANGLE', default=math.radians(90), update=_tex_changed,
        description="Direction of the gradient as seen from the subject (90° = bottom to top)")
    gradient_offset: FloatProperty(
        name="Offset", default=0.0, min=-2.0, max=2.0, soft_min=-1.0, soft_max=1.0,
        update=_tex_changed)
    gradient_scale: FloatProperty(
        name="Spread", default=1.0, min=0.02, max=8.0, soft_max=3.0, update=_tex_changed,
        description="Length of the transition (smaller = sharper)")
    gradient_midpoint: FloatProperty(
        name="Midpoint", default=0.5, min=0.01, max=0.99, subtype='FACTOR',
        update=_tex_changed)
    gradient_interp: EnumProperty(
        name="Interpolation", default='LINEAR', update=_tex_changed,
        items=[('LINEAR', "Linear", "Even blend"),
               ('SMOOTH', "Smooth", "Eased blend"),
               ('CONSTANT', "Constant", "Hard split at the midpoint")])
    gradient_color_a: FloatVectorProperty(
        name="Color A", subtype='COLOR', size=3, default=(1.0, 1.0, 1.0),
        min=0.0, soft_max=1.0, update=_tex_changed)
    gradient_value_a: FloatProperty(
        name="Strength A", default=1.0, min=0.0, soft_max=4.0, update=_tex_changed)
    gradient_color_b: FloatVectorProperty(
        name="Color B", subtype='COLOR', size=3, default=(1.0, 1.0, 1.0),
        min=0.0, soft_max=1.0, update=_tex_changed)
    gradient_value_b: FloatProperty(
        name="Strength B", default=0.0, min=0.0, soft_max=4.0, update=_tex_changed)

    # Colour / power -----------------------------------------------------------
    color: FloatVectorProperty(
        name="Color", subtype='COLOR', size=3, default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0, update=_changed)
    use_temperature: BoolProperty(
        name="Use Temperature", default=False, update=_changed,
        description="Tint the light with a black body colour temperature")
    temperature: FloatProperty(
        name="Temperature", description="Colour temperature in Kelvin",
        default=5600.0, min=1000.0, max=20000.0, update=_changed)
    intensity: FloatProperty(
        name="Intensity", default=10.0, min=0.0, soft_max=100.0, update=_changed,
        description=("Area: surface brightness (like an HDRI light, independent of distance). "
                     "Spot / Point / Sun: illumination at the pivot (sun strength units)"))
    opacity: FloatProperty(
        name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_changed,
        description="Fade the light in / out without touching its intensity")

    # Texture ------------------------------------------------------------------
    use_texture: BoolProperty(
        name="Use Texture", default=False, update=_tex_changed,
        description="Fill the light with an image (softbox photo, window, gobo...)")
    texture: PointerProperty(
        name="Image", type=bpy.types.Image, update=_tex_changed,
        description="Image stretched over the light. Alpha is used as a mask")
    texture_res: EnumProperty(
        name="Texture Resolution", items=TEX_RES, default='256', update=_tex_changed,
        description="Resolution of the generated light texture")

    # Render options -----------------------------------------------------------
    visible_camera: BoolProperty(
        name="Visible to Camera", default=False, update=_changed,
        description="Show the light surface in renders (Cycles, area lights)")
    spread: FloatProperty(
        name="Spread", subtype='ANGLE', default=math.radians(180), min=math.radians(1),
        max=math.radians(180), update=_changed,
        description="Area only: beam angle (a honeycomb / grid on a softbox)")


class LightStudioSettings(PropertyGroup):
    active_index: IntProperty(name="Active Light", default=-1, update=_active_index_changed)

    target_mode: EnumProperty(
        name="Target", default='OBJECT', update=_scene_changed,
        items=[
            ('OBJECT', "Object", "Lights orbit the target object (origin if none)"),
            ('CURSOR', "3D Cursor", "Lights orbit the 3D cursor"),
            ('ORIGIN', "World Origin", "Lights orbit the world origin"),
        ])
    target: PointerProperty(
        name="Target Object", type=bpy.types.Object, update=_scene_changed,
        description="Subject the lights are arranged around")
    default_distance: FloatProperty(
        name="Default Distance", default=4.0, min=0.01, soft_max=50.0, unit='LENGTH',
        description="Distance used for new lights")
    power_scale: FloatProperty(
        name="Power Scale", default=1.0, min=0.0, soft_max=10.0, update=_scene_changed,
        description="Global multiplier for the power of all managed lights")
    follow_transform: BoolProperty(
        name="Follow Viewport Edits", default=True,
        description=("Moving a managed light with G (or the gizmo) updates its "
                     "longitude / latitude / distance and keeps it aimed at the pivot"))
    show_overlay: BoolProperty(
        name="Show Aim Lines", default=True, update=_redraw,
        description="Draw a line from each light to the point it aims at")

    paint_mode: EnumProperty(
        name="Placement", default='REFLECTION', update=_redraw,
        items=[
            ('REFLECTION', "Reflection", "The highlight (reflection) appears where you click"),
            ('ILLUMINATION', "Illumination", "The light faces the clicked surface head on"),
            ('RIM', "Rim", "The light sits behind the surface for a rim highlight"),
        ])
    paint_pivot: EnumProperty(
        name="Aim", default='SURFACE',
        items=[
            ('SURFACE', "Clicked Point", "Aim the light at the clicked point (exact placement)"),
            ('TARGET', "Studio Target", "Keep orbiting the studio target, only change the angle"),
        ])
    paint_add_preset: EnumProperty(
        name="Shift+Click Adds", items=lambda self, ctx: _preset_items(),
        description="Light preset added with Shift+Click in LightPaint")


_PRESET_CACHE = []


def _preset_items():
    if not _PRESET_CACHE:
        from . import presets
        _PRESET_CACHE.extend(presets.light_enum_items())
    return _PRESET_CACHE


classes = (LightStudioLight, LightStudioSettings)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.light_studio = PointerProperty(type=LightStudioLight)
    bpy.types.Scene.light_studio = PointerProperty(type=LightStudioSettings)


def unregister():
    del bpy.types.Scene.light_studio
    del bpy.types.Object.light_studio
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
