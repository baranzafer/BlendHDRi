"""Built-in light and studio presets.

Positions in studio setups use ``az`` (azimuth, degrees) relative to the
*front* of the subject: 0 = in front (towards the camera), +90 = camera
right, 180 = behind. ``el`` is the elevation in degrees.
"""

import json
import math
import os

D = math.radians

# name -> (label, description, icon, params)
LIGHT_PRESETS = {
    'SOFTBOX_LARGE': ("Large Softbox", "Big rectangular softbox", 'MESH_PLANE', dict(
        shape='RECT', width=D(45), height=D(32), softness=0.12, roundness=0.05,
        falloff=0.15, intensity=6.0)),
    'SOFTBOX_SQUARE': ("Square Softbox", "Medium square softbox", 'MESH_PLANE', dict(
        shape='RECT', width=D(28), height=D(28), softness=0.1, roundness=0.05,
        falloff=0.2, intensity=8.0)),
    'SOFTBOX_SMALL': ("Small Softbox", "Small, crisp softbox", 'MESH_PLANE', dict(
        shape='RECT', width=D(14), height=D(10), softness=0.06, roundness=0.05,
        falloff=0.1, intensity=20.0)),
    'STRIP': ("Strip Softbox", "Tall narrow strip light", 'IPO_LINEAR', dict(
        shape='RECT', width=D(9), height=D(70), softness=0.12, roundness=0.1,
        falloff=0.05, intensity=10.0)),
    'STRIP_WIDE': ("Horizontal Strip", "Wide horizontal strip", 'IPO_LINEAR', dict(
        shape='RECT', width=D(90), height=D(8), softness=0.12, roundness=0.1,
        falloff=0.05, intensity=8.0)),
    'OCTABOX': ("Octabox", "Large eight-sided octabox", 'SEQ_CHROMA_SCOPE', dict(
        shape='OCTAGON', width=D(45), height=D(45), softness=0.08,
        falloff=0.35, intensity=7.0)),
    'ROUND': ("Round Softbox", "Round softbox / beauty dish", 'MESH_CIRCLE', dict(
        shape='ELLIPSE', width=D(26), height=D(26), softness=0.1,
        falloff=0.3, intensity=9.0)),
    'RING': ("Ring Light", "Ring light", 'MESH_TORUS', dict(
        shape='RING', width=D(30), height=D(30), softness=0.15, ring_inner=0.72,
        intensity=8.0)),
    'PANEL': ("Overhead Panel", "Huge diffuse panel", 'MESH_GRID', dict(
        shape='RECT', width=D(110), height=D(70), softness=0.25, roundness=0.02,
        falloff=0.1, intensity=2.5)),
    'SPOT': ("Hard Spot", "Small hard light, crisp highlights", 'LIGHT_SPOT', dict(
        shape='ELLIPSE', width=D(5), height=D(5), softness=0.05,
        intensity=80.0)),
    'SUN': ("Sun", "Sun disc", 'LIGHT_SUN', dict(
        shape='ELLIPSE', width=D(2), height=D(2), softness=0.3,
        intensity=1500.0, use_temperature=True, temperature=5500.0)),
    'WINDOW': ("Window", "Window light with soft vertical gradient", 'MOD_LATTICE', dict(
        shape='RECT', width=D(35), height=D(50), softness=0.08, roundness=0.0,
        gradient=0.35, intensity=5.0, use_temperature=True, temperature=6500.0)),
    'FLAG': ("Black Flag", "Blocks light behind it", 'SNAP_FACE', dict(
        shape='RECT', blend='OVER', width=D(30), height=D(45), softness=0.05,
        intensity=0.0, color=(0.0, 0.0, 0.0))),
    'REFLECTOR': ("Reflector Card", "Dim white bounce card", 'SNAP_FACE', dict(
        shape='RECT', blend='OVER', width=D(40), height=D(40), softness=0.2,
        intensity=0.6)),
}


def _l(preset, name, az, el, **over):
    return dict(preset=preset, name=name, az=az, el=el, **over)


# name -> (label, description, background, lights)
STUDIO_PRESETS = {
    'THREE_POINT': ("Three Point", "Classic key / fill / rim setup",
        dict(bg_mode='GRADIENT', bg_top=(0.02,) * 3, bg_horizon=(0.01,) * 3, bg_bottom=(0.003,) * 3),
        [
            _l('SOFTBOX_LARGE', "Key", 40, 25, intensity=10.0),
            _l('OCTABOX', "Fill", -55, 10, intensity=2.5),
            _l('STRIP', "Rim", 160, 15, intensity=14.0),
        ]),
    'PRODUCT_WHITE': ("Product White", "Bright, clean product shot",
        dict(bg_mode='GRADIENT', bg_top=(0.9,) * 3, bg_horizon=(0.6,) * 3, bg_bottom=(0.25,) * 3, bg_blend=0.4),
        [
            _l('PANEL', "Top Panel", 0, 80, intensity=4.0),
            _l('STRIP', "Strip Left", -70, 10, intensity=8.0),
            _l('STRIP', "Strip Right", 70, 10, intensity=8.0),
            _l('SOFTBOX_LARGE', "Front Fill", 0, 15, intensity=2.0),
        ]),
    'PRODUCT_DARK': ("Product Dark", "Dark background, sculpted highlights",
        dict(bg_mode='SOLID', bg_color=(0.0, 0.0, 0.0)),
        [
            _l('STRIP', "Strip Left", -110, 10, intensity=15.0),
            _l('STRIP', "Strip Right", 110, 10, intensity=15.0),
            _l('SOFTBOX_SQUARE', "Top", 0, 70, intensity=6.0),
        ]),
    'CAR_STUDIO': ("Car Studio", "Long overhead panel and side strips",
        dict(bg_mode='GRADIENT', bg_top=(0.03,) * 3, bg_horizon=(0.05,) * 3, bg_bottom=(0.01,) * 3, bg_blend=0.1),
        [
            _l('PANEL', "Overhead", 0, 88, width=D(150), height=D(45), intensity=3.0),
            _l('STRIP_WIDE', "Horizon Left", -90, 4, width=D(120), intensity=4.0),
            _l('STRIP_WIDE', "Horizon Right", 90, 4, width=D(120), intensity=4.0),
            _l('SOFTBOX_LARGE', "Front Kick", 20, 20, intensity=3.0),
        ]),
    'PORTRAIT': ("Portrait", "Octabox key with ring fill",
        dict(bg_mode='SOLID', bg_color=(0.01, 0.01, 0.012)),
        [
            _l('OCTABOX', "Key", 30, 30, intensity=9.0),
            _l('RING', "Ring Fill", 0, 0, intensity=1.5),
            _l('STRIP', "Hair", -150, 40, intensity=10.0),
        ]),
    'DRAMATIC_RIM': ("Dramatic Rim", "Two rim strips behind the subject",
        dict(bg_mode='SOLID', bg_color=(0.0, 0.0, 0.0)),
        [
            _l('STRIP', "Rim Left", -140, 15, intensity=20.0),
            _l('STRIP', "Rim Right", 140, 15, intensity=20.0, use_temperature=True, temperature=4200.0),
            _l('SOFTBOX_SMALL', "Accent", 25, 35, intensity=6.0),
        ]),
    'OUTDOOR': ("Outdoor Sky", "Gradient sky with a sun",
        dict(bg_mode='GRADIENT', bg_top=(0.12, 0.25, 0.6), bg_horizon=(0.6, 0.65, 0.7),
             bg_bottom=(0.08, 0.07, 0.06), bg_blend=0.35),
        [
            _l('SUN', "Sun", 60, 35),
        ]),
}


def light_enum_items():
    return [(k, v[0], v[1], v[2], i) for i, (k, v) in enumerate(LIGHT_PRESETS.items())]


def studio_enum_items():
    return [(k, v[0], v[1], 'LIGHT', i) for i, (k, v) in enumerate(STUDIO_PRESETS.items())]


def apply_light_preset(light, key):
    label, _desc, _icon, params = LIGHT_PRESETS[key]
    light.name = label
    for k, v in params.items():
        setattr(light, k, v)


# ---------------------------------------------------------------------------
# User presets (stored as JSON in Blender's user config directory so they are
# available in every .blend file)
# ---------------------------------------------------------------------------

LIGHT_SKIP = {"rna_type", "area_object", "texture", "name"}
SETTINGS_KEYS = ("bg_mode", "bg_color", "bg_top", "bg_horizon", "bg_bottom",
                 "bg_blend", "bg_strength", "bg_rotation", "world_strength")


def user_preset_path():
    import bpy
    folder = bpy.utils.user_resource('CONFIG', path="blendhdri", create=True)
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


def light_to_dict(light):
    d = {}
    for prop in light.bl_rna.properties:
        key = prop.identifier
        if key in LIGHT_SKIP or prop.is_readonly or prop.type in {'POINTER', 'COLLECTION'}:
            continue
        d[key] = _plain(getattr(light, key))
    if light.texture is not None:
        import bpy
        d["texture"] = {"name": light.texture.name,
                        "filepath": bpy.path.abspath(light.texture.filepath)}
    return d


def dict_to_light(light, d):
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
            light.texture = img
            continue
        if key in LIGHT_SKIP or not hasattr(light, key):
            continue
        try:
            setattr(light, key, value)
        except (TypeError, ValueError, AttributeError):
            pass


def studio_to_dict(settings):
    data = {k: _plain(getattr(settings, k)) for k in SETTINGS_KEYS}
    data["lights"] = []
    for l in settings.lights:
        d = light_to_dict(l)
        d["name"] = l.name
        data["lights"].append(d)
    return data


def dict_to_studio(settings, data):
    for k in SETTINGS_KEYS:
        if k in data:
            try:
                setattr(settings, k, data[k])
            except (TypeError, ValueError):
                pass
    settings.lights.clear()
    for d in data.get("lights", []):
        light = settings.lights.add()
        dict_to_light(light, d)
        light.name = d.get("name", "Light")
    settings.active_index = 0 if settings.lights else -1
