"""Glue between the scene settings, the canvas image and the world."""

import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import render

CANVAS_NAME = "HDRI Studio Canvas"
EXPORT_NAME = "HDRI Studio Export"
WORLD_NAME = "HDRI Studio World"
NODE_ENV = "HDRI Studio Environment"
NODE_BG = "HDRI Studio Background"
# The world alternates between two images so that every update assigns a
# *different* image to the Environment node. Rewriting pixels of the same
# image is picked up by EEVEE (Material Preview) but Cycles (Rendered view)
# keeps its own copy and only reloads when the shader changes.
WORLD_IMAGES = ("HDRI Studio World A", "HDRI Studio World B")
AREA_COLLECTION = "HDRI Studio Lights"
INTERNAL_IMAGES = (CANVAS_NAME, EXPORT_NAME) + WORLD_IMAGES

_pending = set()
_bg_cache = {}


def settings(scene=None):
    scene = scene or bpy.context.scene
    return scene.hdri_studio


# ---------------------------------------------------------------------------
# Redraw / scheduling
# ---------------------------------------------------------------------------

def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in {'IMAGE_EDITOR', 'VIEW_3D', 'PROPERTIES'}:
                area.tag_redraw()


def _flush():
    names = list(_pending)
    _pending.clear()
    for name in names:
        scene = bpy.data.scenes.get(name)
        if scene is not None:
            update_preview(scene)
    return None


def schedule_update(scene=None, force=False):
    scene = scene or bpy.context.scene
    if scene is None:
        return
    if not force and not scene.hdri_studio.auto_update:
        tag_redraw()
        return
    _pending.add(scene.name)
    if not bpy.app.timers.is_registered(_flush):
        bpy.app.timers.register(_flush, first_interval=0.0)


# ---------------------------------------------------------------------------
# Rendering into images
# ---------------------------------------------------------------------------

def image_pixels(img):
    """Return (h, w, 4) float32 pixels of ``img`` (cached)."""
    if img is None or img.name in INTERNAL_IMAGES:
        return None
    w, h = img.size
    if w == 0 or h == 0:
        return None
    key = img.name
    sig = (w, h, img.channels, img.filepath)
    cached = _bg_cache.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    ch = img.channels
    buf = np.empty(w * h * ch, dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(h, w, ch)
    if ch < 4:
        pad = np.ones((h, w, 4), dtype=np.float32)
        if ch == 1:
            pad[..., :3] = arr[..., :1]
        else:
            pad[..., :ch] = arr
        arr = pad
    if len(_bg_cache) > 16:
        _bg_cache.clear()
    _bg_cache[key] = (sig, arr)
    return arr


def _background_pixels(s):
    if s.bg_mode != 'IMAGE':
        return None
    return image_pixels(s.bg_image)


def clear_background_cache():
    _bg_cache.clear()


def collect_lights(s):
    out = []
    for l in s.lights:
        if not l.enabled or l.output == 'AREA':
            continue
        d = render.LightData.from_prop(l)
        if l.use_texture and l.texture is not None:
            d.tex = image_pixels(l.texture)
        out.append(d)
    return out


def render_array(scene, width):
    s = settings(scene)
    height = width // 2
    bg = render.BackgroundData.from_settings(s, _background_pixels(s))
    return render.render(width, height, bg, collect_lights(s))


def _write_image(img, arr):
    h, w = arr.shape[:2]
    if tuple(img.size) != (w, h):
        img.scale(w, h)
    img.pixels.foreach_set(arr.ravel())
    img.update()


def get_canvas(scene=None, create=True):
    img = bpy.data.images.get(CANVAS_NAME)
    if img is None and create:
        s = settings(scene)
        w = int(s.preview_res)
        img = bpy.data.images.new(CANVAS_NAME, w, w // 2, alpha=False,
                                  float_buffer=True)
    if img is not None:
        # Show the HDR through the scene view transform (AgX/Filmic) so
        # bright lights are not simply clipped on the canvas.
        try:
            img.use_view_as_render = True
        except Exception:
            pass
    return img


def _next_world_image(width):
    """Pick the world image that is *not* currently in use."""
    world = get_studio_world()
    current = None
    if world is not None and world.node_tree is not None:
        env = world.node_tree.nodes.get(NODE_ENV)
        current = env.image if env is not None else None
    name = WORLD_IMAGES[1] if (current is not None and current.name == WORLD_IMAGES[0]) \
        else WORLD_IMAGES[0]
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.new(name, width, width // 2, alpha=False, float_buffer=True)
    return img


def front_lon(scene):
    """Longitude that faces the camera (front of the subject)."""
    import math
    cam = scene.camera
    if cam is not None:
        from mathutils import Vector
        fwd = cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
        if fwd.xy.length > 1e-6:
            return math.atan2(-fwd.y, -fwd.x)
    return -math.pi / 2  # Blender front view looks along +Y, camera at -Y


def update_preview(scene=None):
    scene = scene or bpy.context.scene
    s = settings(scene)
    img = get_canvas(scene)
    width = int(s.preview_res)
    arr = render_array(scene, width)
    _write_image(img, arr)
    world_img = _next_world_image(width)
    _write_image(world_img, arr)
    world = ensure_world(scene, image=world_img)
    # Make sure every render engine re-syncs the world.
    for idb in (world_img, world.node_tree, world):
        try:
            idb.update_tag()
        except Exception:
            pass
    sync_area_lights(scene)
    tag_redraw()
    return img


def render_export(scene, width):
    arr = render_array(scene, width)
    img = bpy.data.images.get(EXPORT_NAME)
    if img is not None:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(EXPORT_NAME, width, width // 2, alpha=False,
                              float_buffer=True)
    _write_image(img, arr)
    return img


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------

def _build_world_nodes(world, image):
    try:
        world.use_nodes = True
    except Exception:  # deprecated / read-only in newer versions
        pass
    nt = world.node_tree
    env = nt.nodes.get(NODE_ENV)
    bg = nt.nodes.get(NODE_BG)
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None)
    if env is None or bg is None or out is None:
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputWorld')
        out.location = (300, 0)
        bg = nt.nodes.new('ShaderNodeBackground')
        bg.name = bg.label = NODE_BG
        bg.location = (100, 0)
        env = nt.nodes.new('ShaderNodeTexEnvironment')
        env.name = env.label = NODE_ENV
        env.location = (-250, 0)
        env.interpolation = 'Linear'
        nt.links.new(env.outputs['Color'], bg.inputs['Color'])
        nt.links.new(bg.outputs['Background'], out.inputs['Surface'])
    if env.image != image:
        env.image = image
    return bg


def get_studio_world():
    return bpy.data.worlds.get(WORLD_NAME)


def ensure_world(scene, activate=None, image=None):
    """Make sure the studio world exists and holds the canvas.

    The world is only assigned to the scene the first time (or when
    ``activate`` is True) so the user can still switch worlds freely.
    """
    s = settings(scene)
    world = get_studio_world()
    img = image
    if img is None:
        env = world.node_tree.nodes.get(NODE_ENV) if world is not None and world.node_tree else None
        img = env.image if env is not None and env.image is not None else get_canvas(scene)
    created = world is None
    if created:
        world = bpy.data.worlds.new(WORLD_NAME)
    bg = _build_world_nodes(world, img)
    bg.inputs['Strength'].default_value = s.world_strength
    if activate or (activate is None and created):
        if scene.world is not None and scene.world != world:
            s.previous_world = scene.world
        scene.world = world
    return world


def sync_world_strength(scene):
    world = get_studio_world()
    if world is None or world.node_tree is None:
        return
    bg = world.node_tree.nodes.get(NODE_BG)
    if bg is not None:
        bg.inputs['Strength'].default_value = settings(scene).world_strength


# ---------------------------------------------------------------------------
# Real area lights linked to HDRI lights
# ---------------------------------------------------------------------------

AREA_SHAPES = {'RECT': 'RECTANGLE', 'ELLIPSE': 'ELLIPSE', 'OCTAGON': 'ELLIPSE', 'RING': 'ELLIPSE'}


def _area_collection(scene):
    coll = bpy.data.collections.get(AREA_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(AREA_COLLECTION)
    if coll.name not in scene.collection.children:
        try:
            scene.collection.children.link(coll)
        except RuntimeError:
            pass
    return coll


def area_center(s):
    if s.area_target is not None:
        return s.area_target.matrix_world.translation.copy()
    from mathutils import Vector
    return Vector((0.0, 0.0, 0.0))


def area_light_matrix(s, light):
    from mathutils import Matrix, Vector
    L, T, B = render.light_basis(light.lon, light.lat, light.roll)
    pos = area_center(s) + Vector(L) * s.area_distance
    # Area lights shine along their local -Z, so +Z points away from the target.
    rot = Matrix((T, B, L)).transposed().to_4x4()
    return Matrix.Translation(pos) @ rot


def _sync_one(s, coll, light):
    obj = light.area_object
    if obj is None or obj.name not in bpy.data.objects or obj.type != 'LIGHT':
        data = bpy.data.lights.new(light.name, type='AREA')
        obj = bpy.data.objects.new(light.name, data)
        coll.objects.link(obj)
        light.area_object = obj
    elif obj.name not in coll.objects:
        try:
            coll.objects.link(obj)
        except RuntimeError:
            pass
    data = obj.data
    if data.type != 'AREA':
        data.type = 'AREA'
    data = obj.data
    d = render.LightData.from_prop(light)
    tw, th = d.tan_half()
    dist = s.area_distance
    sx, sy = 2.0 * dist * tw, 2.0 * dist * th
    data.shape = AREA_SHAPES.get(light.shape, 'RECTANGLE')
    data.size = sx
    data.size_y = sy
    rgb = d.rgb
    if d.grad_type != 'NONE':
        # an area light cannot show a gradient: use its average colour
        avg = [(a + b) * 0.5 for a, b in zip(d.grad_a, d.grad_b)]
        rgb = tuple(c * g for c, g in zip(rgb, avg))
    peak = max(rgb) if max(rgb) > 0 else 0.0
    data.color = tuple(c / peak for c in rgb) if peak > 0 else (1.0, 1.0, 1.0)
    # Radiance L of an area light with power P and area A is P / (pi * A)
    area = sx * sy * (1.0 if data.shape == 'RECTANGLE' else 3.14159265 / 4.0)
    soft = 1.0 - 0.5 * light.softness  # soft edges emit a little less
    data.energy = peak * 3.14159265 * area * soft * light.opacity * s.area_power_scale
    try:
        data.spread = 3.14159265
    except AttributeError:
        pass
    obj.hide_viewport = obj.hide_render = not light.enabled
    obj.matrix_world = area_light_matrix(s, light)
    if obj.name != light.name and not light.name in bpy.data.objects:
        obj.name = light.name


def remove_area_light(light):
    obj = light.area_object
    if obj is not None:
        data = obj.data if obj.type == 'LIGHT' else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.lights.remove(data)
    light.area_object = None


def sync_area_lights(scene):
    s = settings(scene)
    wanted = [l for l in s.lights if l.output in {'AREA', 'BOTH'}]
    linked = {l.area_object for l in s.lights if l.area_object is not None}
    if not wanted and not linked and AREA_COLLECTION not in bpy.data.collections:
        return
    for l in s.lights:
        if l.output == 'HDRI' and l.area_object is not None:
            remove_area_light(l)
    if wanted:
        coll = _area_collection(scene)
        for l in wanted:
            _sync_one(s, coll, l)
    # Remove orphans (lights deleted from the list)
    coll = bpy.data.collections.get(AREA_COLLECTION)
    if coll is not None:
        keep = {l.area_object for l in s.lights if l.area_object is not None}
        for obj in list(coll.objects):
            if obj not in keep and obj.type == 'LIGHT':
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.lights.remove(data)


# ---------------------------------------------------------------------------
# Handlers: generated images are not saved with the .blend, rebuild them.
# ---------------------------------------------------------------------------

@persistent
def _on_load(_dummy=None):
    clear_background_cache()
    for scene in bpy.data.scenes:
        if len(scene.hdri_studio.lights) or bpy.data.images.get(CANVAS_NAME):
            schedule_update(scene, force=True)


@persistent
def _on_undo(_dummy=None):
    scene = bpy.context.scene
    if scene is not None and bpy.data.images.get(CANVAS_NAME):
        schedule_update(scene, force=True)


def register():
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.undo_post.append(_on_undo)
    bpy.app.handlers.redo_post.append(_on_undo)


def unregister():
    for lst, fn in ((bpy.app.handlers.load_post, _on_load),
                    (bpy.app.handlers.undo_post, _on_undo),
                    (bpy.app.handlers.redo_post, _on_undo)):
        if fn in lst:
            lst.remove(fn)
    for fn in (_flush,):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
