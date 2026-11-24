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

def _background_pixels(s):
    img = s.bg_image
    if s.bg_mode != 'IMAGE' or img is None or img.name in (CANVAS_NAME, EXPORT_NAME):
        return None
    w, h = img.size
    if w == 0 or h == 0:
        return None
    key = (img.name, w, h, img.channels)
    cached = _bg_cache.get(key)
    if cached is not None:
        return cached
    buf = np.empty(w * h * img.channels, dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(h, w, img.channels)
    if img.channels < 3:
        arr = np.repeat(arr[..., :1], 3, axis=2)
    # Do not keep stale images around
    _bg_cache.clear()
    _bg_cache[key] = arr
    return arr


def clear_background_cache():
    _bg_cache.clear()


def collect_lights(s):
    return [render.LightData.from_prop(l) for l in s.lights if l.enabled]


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


def update_preview(scene=None):
    scene = scene or bpy.context.scene
    s = settings(scene)
    img = get_canvas(scene)
    arr = render_array(scene, int(s.preview_res))
    _write_image(img, arr)
    ensure_world(scene)
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


def ensure_world(scene, activate=None):
    """Make sure the studio world exists and holds the canvas.

    The world is only assigned to the scene the first time (or when
    ``activate`` is True) so the user can still switch worlds freely.
    """
    s = settings(scene)
    img = get_canvas(scene)
    world = get_studio_world()
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
    if bpy.app.timers.is_registered(_flush):
        bpy.app.timers.unregister(_flush)
