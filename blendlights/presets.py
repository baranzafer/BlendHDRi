"""Built-in light presets, studio setups and user presets (JSON)."""

import json
import math
import os

D = math.radians

# key -> (label, description, icon, params)
LIGHT_PRESETS = {
    'SOFTBOX_LARGE': ("Large Softbox", "Big rectangular softbox", 'MESH_PLANE', dict(
        light_type='AREA', shape='RECT', width=D(45), height=D(32), softness=0.12,
        roundness=0.05, falloff=1.0, intensity=10.0)),
    'SOFTBOX_SQUARE': ("Square Softbox", "Medium square softbox", 'MESH_PLANE', dict(
        light_type='AREA', shape='RECT', width=D(28), height=D(28), softness=0.1,
        roundness=0.05, falloff=1.2, intensity=14.0)),
    'SOFTBOX_SMALL': ("Small Softbox", "Small, crisp softbox", 'MESH_PLANE', dict(
        light_type='AREA', shape='RECT', width=D(14), height=D(10), softness=0.06,
        roundness=0.05, falloff=0.8, intensity=40.0)),
    'STRIP': ("Strip Softbox", "Tall narrow strip light", 'IPO_LINEAR', dict(
        light_type='AREA', shape='RECT', width=D(9), height=D(70), softness=0.12,
        roundness=0.1, falloff=0.4, intensity=20.0)),
    'STRIP_WIDE': ("Horizontal Strip", "Wide horizontal strip", 'IPO_LINEAR', dict(
        light_type='AREA', shape='RECT', width=D(90), height=D(8), softness=0.12,
        roundness=0.1, falloff=0.4, intensity=16.0)),
    'OCTABOX': ("Octabox", "Large eight-sided octabox", 'SEQ_CHROMA_SCOPE', dict(
        light_type='AREA', shape='OCTAGON', width=D(45), height=D(45), softness=0.08,
        falloff=1.8, intensity=10.0)),
    'ROUND': ("Round Softbox", "Round softbox", 'MESH_CIRCLE', dict(
        light_type='AREA', shape='ELLIPSE', width=D(26), height=D(26), softness=0.1,
        falloff=1.5, intensity=16.0)),
    'BEAUTY_DISH': ("Beauty Dish", "Round light, bright rim and darker centre", 'MESH_CIRCLE', dict(
        light_type='AREA', shape='ELLIPSE', width=D(30), height=D(30), softness=0.12,
        gradient_type='RADIAL', gradient_offset=0.2, gradient_scale=0.8,
        gradient_value_a=0.55, gradient_value_b=1.25, intensity=16.0)),
    'RING': ("Ring Light", "Ring light", 'MESH_TORUS', dict(
        light_type='AREA', shape='RING', width=D(30), height=D(30), softness=0.15,
        ring_inner=0.72, intensity=16.0)),
    'PANEL': ("Overhead Panel", "Huge diffuse panel", 'MESH_GRID', dict(
        light_type='AREA', shape='RECT', width=D(110), height=D(70), softness=0.25,
        roundness=0.02, falloff=0.8, intensity=3.0)),
    'WINDOW': ("Window", "Window light with a soft vertical gradient", 'MOD_LATTICE', dict(
        light_type='AREA', shape='RECT', width=D(35), height=D(50), softness=0.08,
        roundness=0.0, gradient_type='LINEAR', gradient_angle=D(90),
        gradient_value_a=0.65, gradient_value_b=1.35, intensity=10.0,
        use_temperature=True, temperature=6500.0)),
    'STRIP_FADE': ("Fade Strip", "Strip fading out towards the bottom", 'IPO_EASE_OUT', dict(
        light_type='AREA', shape='RECT', width=D(9), height=D(80), softness=0.15,
        roundness=0.1, gradient_type='LINEAR', gradient_angle=D(90), gradient_interp='SMOOTH',
        gradient_value_a=0.05, gradient_value_b=1.0, intensity=28.0)),
    'REFLECTOR': ("Reflector Card", "Dim white bounce card", 'SNAP_FACE', dict(
        light_type='AREA', shape='RECT', width=D(40), height=D(40), softness=0.2,
        intensity=0.8, spread=D(180))),
    'GRID_SOFTBOX': ("Softbox + Grid", "Softbox with a honeycomb grid (narrow spread)", 'MESH_GRID', dict(
        light_type='AREA', shape='RECT', width=D(30), height=D(30), softness=0.1,
        roundness=0.05, falloff=1.2, intensity=20.0, spread=D(40))),
    'SPOT_HARD': ("Hard Spot", "Crisp fresnel spot", 'LIGHT_SPOT', dict(
        light_type='SPOT', shape='ELLIPSE', width=D(30), height=D(30), softness=0.15,
        source_size=D(1.0), intensity=4.0)),
    'SPOT_BARNDOOR': ("Barn Door Spot", "Rectangular beam with soft barn doors", 'LIGHT_SPOT', dict(
        light_type='SPOT', shape='RECT', width=D(30), height=D(16), softness=0.25,
        roundness=0.0, source_size=D(2.0), intensity=4.0)),
    'SPOT_GOBO': ("Gobo Projector", "Spot projecting an image (set one in Texture)", 'IMAGE_DATA', dict(
        light_type='SPOT', shape='RECT', width=D(35), height=D(35), softness=0.0,
        roundness=0.0, source_size=D(0.2), intensity=4.0, use_texture=True)),
    'BULB': ("Bulb", "Point light", 'LIGHT_POINT', dict(
        light_type='POINT', width=D(4), intensity=3.0, use_temperature=True,
        temperature=3200.0)),
    'SUN': ("Sun", "Directional sun light", 'LIGHT_SUN', dict(
        light_type='SUN', width=D(1.0), intensity=4.0, use_temperature=True,
        temperature=5500.0)),
}


def _l(preset, name, az, el, **over):
    return dict(preset=preset, name=name, az=az, el=el, **over)


# key -> (label, description, lights). Azimuth is relative to the camera:
# 0 = in front of the subject (camera side), +90 = camera right, 180 = behind.
STUDIO_PRESETS = {
    'THREE_POINT': ("Three Point", "Classic key / fill / rim", [
        _l('SOFTBOX_LARGE', "Key", 40, 25, intensity=12.0),
        _l('OCTABOX', "Fill", -55, 10, intensity=3.0),
        _l('STRIP', "Rim", 160, 15, intensity=25.0),
    ]),
    'PRODUCT_WHITE': ("Product White", "Bright, clean product shot", [
        _l('PANEL', "Top Panel", 0, 80, intensity=4.0),
        _l('STRIP', "Strip Left", -70, 10, intensity=14.0),
        _l('STRIP', "Strip Right", 70, 10, intensity=14.0),
        _l('SOFTBOX_LARGE', "Front Fill", 0, 15, intensity=3.0),
    ]),
    'PRODUCT_DARK': ("Product Dark", "Sculpted highlights on a dark set", [
        _l('STRIP', "Strip Left", -110, 10, intensity=25.0),
        _l('STRIP', "Strip Right", 110, 10, intensity=25.0),
        _l('SOFTBOX_SQUARE', "Top", 0, 70, intensity=10.0),
    ]),
    'CAR_STUDIO': ("Car Studio", "Long overhead panel and side strips", [
        _l('PANEL', "Overhead", 0, 88, width=D(150), height=D(45), intensity=3.0),
        _l('STRIP_WIDE', "Horizon Left", -90, 4, width=D(120), intensity=6.0),
        _l('STRIP_WIDE', "Horizon Right", 90, 4, width=D(120), intensity=6.0),
        _l('SOFTBOX_LARGE', "Front Kick", 20, 20, intensity=4.0),
    ]),
    'PORTRAIT': ("Portrait", "Octabox key, ring fill, hair light", [
        _l('OCTABOX', "Key", 30, 30, intensity=14.0),
        _l('RING', "Ring Fill", 0, 0, intensity=3.0),
        _l('STRIP', "Hair", -150, 40, intensity=18.0),
    ]),
    'DRAMATIC_RIM': ("Dramatic Rim", "Two rim strips behind the subject", [
        _l('STRIP', "Rim Left", -140, 15, intensity=35.0),
        _l('STRIP', "Rim Right", 140, 15, intensity=35.0, use_temperature=True, temperature=4200.0),
        _l('SPOT_BARNDOOR', "Accent", 25, 35, intensity=3.0),
    ]),
    'THEATRE': ("Spot Stage", "Hard key spot, gobo background, warm fill", [
        _l('SPOT_HARD', "Key Spot", 35, 40, intensity=6.0),
        _l('ROUND', "Fill", -50, 10, intensity=3.0, use_temperature=True, temperature=3400.0),
        _l('STRIP', "Back", 180, 25, intensity=20.0),
    ]),
    'OUTDOOR': ("Outdoor Sun", "Sun with a cool sky fill panel", [
        _l('SUN', "Sun", 60, 35),
        _l('PANEL', "Sky Fill", -30, 70, intensity=1.0, color=(0.6, 0.75, 1.0)),
    ]),
}


def light_enum_items():
    return [(k, v[0], v[1], v[2], i) for i, (k, v) in enumerate(LIGHT_PRESETS.items())]


def studio_enum_items():
    return [(k, v[0], v[1], 'LIGHT', i) for i, (k, v) in enumerate(STUDIO_PRESETS.items())]


def apply_light_preset(ls, key):
    """Reset ``ls`` (a LightStudioLight) to defaults and apply a preset."""
    _reset(ls)
    label, _desc, _icon, params = LIGHT_PRESETS[key]
    for k, v in params.items():
        setattr(ls, k, v)
    ls.preset = key
    return label


def _reset(ls):
    for prop in ls.bl_rna.properties:
        key = prop.identifier
        if key in SKIP or prop.is_readonly or prop.type in {'POINTER', 'COLLECTION'}:
            continue
        try:
            if getattr(prop, "is_array", False):
                setattr(ls, key, prop.default_array)
            else:
                setattr(ls, key, prop.default)
        except (TypeError, AttributeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# User presets: JSON in Blender's config folder, available in every file
# ---------------------------------------------------------------------------

SKIP = {"rna_type", "texture", "name", "managed", "pivot_point", "pivot_mode",
        "lon", "lat", "distance"}
PLACE_KEYS = ("lon", "lat", "distance")


def user_preset_path():
    import bpy
    folder = bpy.utils.user_resource('CONFIG', path="blendlights", create=True)
    return os.path.join(folder, "presets.json")


def load_user_presets():
    try:
        with open(user_preset_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("lights", {})
    data.setdefault("studios", {})
    return data


def save_user_presets(data):
    path = user_preset_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _plain(value):
    if hasattr(value, "__len__") and not isinstance(value, str):
        return [float(v) for v in value]
    return value


def light_to_dict(ls, placement=False):
    d = {}
    for prop in ls.bl_rna.properties:
        key = prop.identifier
        if key in SKIP or prop.is_readonly or prop.type in {'POINTER', 'COLLECTION'}:
            continue
        d[key] = _plain(getattr(ls, key))
    if placement:
        for k in PLACE_KEYS:
            d[k] = float(getattr(ls, k))
    if ls.texture is not None:
        import bpy
        d["texture"] = {"name": ls.texture.name,
                        "filepath": bpy.path.abspath(ls.texture.filepath)}
    return d


def dict_to_light(ls, d):
    import bpy
    for key, value in d.items():
        if key == "texture":
            img = bpy.data.images.get(value.get("name", ""))
            path = value.get("filepath", "")
            if img is None and path and os.path.exists(path):
                try:
                    img = bpy.data.images.load(path, check_existing=True)
                except RuntimeError:
                    img = None
            ls.texture = img
            continue
        if (key in SKIP and key not in PLACE_KEYS) or not hasattr(ls, key):
            continue
        try:
            setattr(ls, key, value)
        except (TypeError, ValueError, AttributeError):
            pass
