import math

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from . import presets


def _changed(self, context):
    from . import studio
    studio.schedule_update(context.scene if context else None)


def _world_strength_changed(self, context):
    from . import studio
    studio.sync_world_strength(context.scene)


def _active_changed(self, context):
    from . import studio
    studio.tag_redraw()


SHAPES = [
    ('RECT', "Rectangle", "Rectangular softbox (use Roundness for rounded corners)", 'MESH_PLANE', 0),
    ('ELLIPSE', "Round", "Round / elliptical softbox", 'MESH_CIRCLE', 1),
    ('OCTAGON', "Octabox", "Eight-sided octabox", 'SEQ_CHROMA_SCOPE', 2),
    ('RING', "Ring", "Ring light", 'MESH_TORUS', 3),
]

BLENDS = [
    ('ADD', "Add", "Add light on top of everything below (standard light)"),
    ('OVER', "Over", "Replace what is below (cards, flags with intensity 0)"),
    ('MULTIPLY', "Multiply", "Multiply below by the colour (gels, dimmers, black flags)"),
]


class HDRIStudioLight(PropertyGroup):
    name: StringProperty(name="Name", default="Light")
    enabled: BoolProperty(name="Enabled", default=True, update=_changed)
    shape: EnumProperty(name="Shape", items=SHAPES, default='RECT', update=_changed)
    blend: EnumProperty(name="Blend", items=BLENDS, default='ADD', update=_changed)

    lon: FloatProperty(
        name="Longitude", description="Horizontal position on the HDRI",
        subtype='ANGLE', default=0.0, min=-math.pi, max=math.pi,
        update=_changed)
    lat: FloatProperty(
        name="Latitude", description="Vertical position on the HDRI (elevation)",
        subtype='ANGLE', default=math.radians(20), min=-math.pi / 2, max=math.pi / 2,
        update=_changed)
    roll: FloatProperty(
        name="Rotation", description="Rotation of the light around its own axis",
        subtype='ANGLE', default=0.0, min=-math.pi, max=math.pi, update=_changed)

    width: FloatProperty(
        name="Width", description="Angular width of the light",
        subtype='ANGLE', default=math.radians(30), min=math.radians(0.2),
        max=math.radians(170), update=_changed)
    height: FloatProperty(
        name="Height", description="Angular height of the light",
        subtype='ANGLE', default=math.radians(30), min=math.radians(0.2),
        max=math.radians(170), update=_changed)

    softness: FloatProperty(
        name="Edge Softness", description="Width of the soft edge (0 = hard edge)",
        default=0.1, min=0.0, max=1.0, subtype='FACTOR', update=_changed)
    roundness: FloatProperty(
        name="Roundness", description="Corner roundness of rectangular lights",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=_changed)
    ring_inner: FloatProperty(
        name="Ring Inner Size", default=0.7, min=0.0, max=0.98,
        subtype='FACTOR', update=_changed)
    falloff: FloatProperty(
        name="Center Falloff", description="Darken towards the edge (hot spot in the middle)",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_changed)
    gradient: FloatProperty(
        name="Gradient", description="Linear brightness gradient across the light (top/bottom)",
        default=0.0, min=-1.0, max=1.0, update=_changed)

    intensity: FloatProperty(
        name="Intensity", default=5.0, min=0.0, soft_max=100.0, update=_changed)
    color: FloatVectorProperty(
        name="Color", subtype='COLOR', size=3, default=(1.0, 1.0, 1.0),
        min=0.0, soft_max=1.0, update=_changed)
    use_temperature: BoolProperty(
        name="Use Temperature", description="Tint the light with a black body temperature",
        default=False, update=_changed)
    temperature: FloatProperty(
        name="Temperature", description="Colour temperature in Kelvin",
        default=5600.0, min=1000.0, max=20000.0, update=_changed)
    opacity: FloatProperty(
        name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=_changed)

    use_texture: BoolProperty(
        name="Use Texture", default=False, update=_changed,
        description="Fill the light with an image (photo of a softbox, window, gobo...)")
    texture: PointerProperty(
        name="Texture", type=bpy.types.Image, update=_changed,
        description="Image stretched over the light. Alpha is used as a mask")

    output: EnumProperty(
        name="Output", update=_changed, default='HDRI',
        description="Where this light exists",
        items=[
            ('HDRI', "HDRI", "Only in the HDRI (environment)"),
            ('AREA', "Area Light", "Only as a real Area light object in the scene"),
            ('BOTH', "Both", "In the HDRI (reflections) and as an Area light"),
        ])
    area_object: PointerProperty(
        name="Area Light", type=bpy.types.Object,
        description="Area light object driven by this HDRI light")


PREVIEW_RES = [
    ('512', "512 x 256", "Fastest"),
    ('1024', "1K (1024 x 512)", "Good balance"),
    ('2048', "2K (2048 x 1024)", "Sharper, slower updates"),
]

EXPORT_RES = [
    ('1024', "1K", ""),
    ('2048', "2K", ""),
    ('4096', "4K", ""),
    ('8192', "8K", ""),
]


class HDRIStudioSettings(PropertyGroup):
    lights: CollectionProperty(type=HDRIStudioLight)
    active_index: IntProperty(name="Active Light", default=0, update=_active_changed)

    auto_update: BoolProperty(
        name="Live Update", description="Re-render the HDRI whenever a setting changes",
        default=True)
    preview_res: EnumProperty(
        name="Preview Resolution", items=PREVIEW_RES, default='1024', update=_changed)
    world_strength: FloatProperty(
        name="World Strength", default=1.0, min=0.0, soft_max=10.0,
        update=_world_strength_changed)
    previous_world: PointerProperty(
        name="Previous World", type=bpy.types.World,
        description="World that was active before HDRI Studio took over")

    # Background ---------------------------------------------------------
    bg_mode: EnumProperty(
        name="Background", update=_changed, default='GRADIENT',
        items=[
            ('SOLID', "Solid", "Single colour background"),
            ('GRADIENT', "Gradient", "Sky / horizon / ground gradient"),
            ('IMAGE', "HDRI Image", "Use an existing equirectangular image as base"),
        ])
    bg_color: FloatVectorProperty(
        name="Color", subtype='COLOR', size=3, default=(0.0, 0.0, 0.0),
        min=0.0, soft_max=1.0, update=_changed)
    bg_top: FloatVectorProperty(
        name="Top", subtype='COLOR', size=3, default=(0.03, 0.03, 0.03),
        min=0.0, soft_max=1.0, update=_changed)
    bg_horizon: FloatVectorProperty(
        name="Horizon", subtype='COLOR', size=3, default=(0.015, 0.015, 0.015),
        min=0.0, soft_max=1.0, update=_changed)
    bg_bottom: FloatVectorProperty(
        name="Ground", subtype='COLOR', size=3, default=(0.004, 0.004, 0.004),
        min=0.0, soft_max=1.0, update=_changed)
    bg_blend: FloatProperty(
        name="Horizon Blend", default=0.25, min=0.001, max=1.0,
        subtype='FACTOR', update=_changed)
    bg_strength: FloatProperty(
        name="Background Strength", default=1.0, min=0.0, soft_max=10.0,
        update=_changed)
    bg_image: PointerProperty(
        name="Image", type=bpy.types.Image, update=_changed,
        description="Equirectangular image used as the base of the HDRI")
    bg_rotation: FloatProperty(
        name="Image Rotation", subtype='ANGLE', default=0.0, update=_changed)

    # Area lights -------------------------------------------------------
    area_target: PointerProperty(
        name="Target", type=bpy.types.Object, update=_changed,
        description="Area lights are placed around this object (world origin if empty)")
    area_distance: FloatProperty(
        name="Distance", default=5.0, min=0.01, soft_max=50.0, unit='LENGTH',
        update=_changed, description="Distance of the area lights from the target")
    area_power_scale: FloatProperty(
        name="Power Scale", default=1.0, min=0.0, soft_max=10.0, update=_changed,
        description="Multiplier for the power of generated area lights")

    # Canvas editing -----------------------------------------------------------
    canvas_tool: EnumProperty(
        name="Canvas Tool", default='MOVE', update=_active_changed,
        items=[
            ('MOVE', "Move", "Click to select, drag to move"),
            ('SCALE', "Scale", "Drag to change the size (Shift: keep proportions off)"),
            ('ROTATE', "Rotate", "Drag to rotate the light"),
            ('ADD', "Add", "Click on the canvas to add the chosen preset"),
        ])
    show_grid: BoolProperty(name="Show Grid", default=True, update=_active_changed)
    snap_angle: BoolProperty(
        name="Snap", default=False, update=_active_changed,
        description="Snap light positions to 5 degree steps while dragging")

    # Canvas overlay -------------------------------------------------------
    show_outlines: BoolProperty(
        name="Show Outlines", default=True, update=_active_changed)
    show_labels: BoolProperty(
        name="Show Labels", default=True, update=_active_changed)

    canvas_add_preset: EnumProperty(
        name="Ctrl+Click Adds", description="Light preset added with Ctrl+Click on the canvas",
        items=presets.light_enum_items(), default="SOFTBOX_SQUARE")

    # LightPaint -----------------------------------------------------------
    paint_mode: EnumProperty(
        name="Placement",
        items=[
            ('REFLECTION', "Reflection", "Place the light so its reflection appears where you click"),
            ('ILLUMINATION', "Illumination", "Place the light so it lights the clicked surface head on"),
            ('RIM', "Rim", "Place the light behind the surface to create a rim highlight"),
        ],
        default='REFLECTION')

    # Export -----------------------------------------------------------------
    export_res: EnumProperty(name="Export Resolution", items=EXPORT_RES, default='4096')
    export_format: EnumProperty(
        name="Format",
        items=[
            ('OPEN_EXR', "OpenEXR (.exr)", "32-bit float OpenEXR"),
            ('HDR', "Radiance HDR (.hdr)", "Radiance RGBE"),
        ],
        default='OPEN_EXR')


classes = (HDRIStudioLight, HDRIStudioSettings)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.hdri_studio = PointerProperty(type=HDRIStudioSettings)


def unregister():
    del bpy.types.Scene.hdri_studio
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
