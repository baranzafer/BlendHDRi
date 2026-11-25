"""Keeps real Blender lights in sync with their Light Studio settings.

Fast settings (position, size, colour, power) are written immediately from
the property update callbacks. The generated light texture (shape, softness,
roundness, falloff, gradient, user image) is rebuilt from a short timer and
only when something that affects it actually changed.
"""

import math
import traceback

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from . import core

COLLECTION = "Light Studio"
IMG_NODE = "LS_Image"
UV_NODE = "LS_TexCoord"
OWNER_KEY = "ls_owner"
POINT_CAL = 1.1  # Cycles point/spot vs. sun calibration (measured)

_tex_pending = set()
_tex_keys = {}       # object name -> texture key last written
_user_tex = {}       # image name -> (signature, array)
_timer_running = False


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def settings(scene):
    return scene.light_studio


def is_managed(obj):
    return (obj is not None and obj.type == 'LIGHT'
            and getattr(obj, "light_studio", None) is not None and obj.light_studio.managed)


def managed_lights(scene):
    return [o for o in scene.objects if is_managed(o)]


def active_light(context):
    obj = getattr(context, "active_object", None)
    if is_managed(obj):
        return obj
    scene = context.scene
    i = settings(scene).active_index
    if 0 <= i < len(scene.objects) and is_managed(scene.objects[i]):
        return scene.objects[i]
    return None


def _scene_of(obj):
    scene = bpy.context.scene
    if scene is not None and obj.name in scene.objects:
        return scene
    for sc in bpy.data.scenes:
        if obj.name in sc.objects:
            return sc
    return scene


def target_point(scene):
    s = settings(scene)
    if s.target_mode == 'CURSOR':
        return scene.cursor.location.copy()
    if s.target_mode == 'OBJECT' and s.target is not None:
        return s.target.matrix_world.translation.copy()
    return Vector((0.0, 0.0, 0.0))


def pivot(scene, ls):
    if ls.pivot_mode == 'POINT':
        return Vector(ls.pivot_point)
    return target_point(scene)


def front_lon(scene):
    """Longitude that points from the target towards the camera."""
    cam = scene.camera
    if cam is not None:
        d = cam.matrix_world.translation - target_point(scene)
        if d.x * d.x + d.y * d.y > 1e-8:
            return math.atan2(d.y, d.x)
    return -math.pi / 2  # Blender's front view looks from -Y


def light_matrix(scene, ls):
    L, T, B = core.light_basis(ls.lon, ls.lat, ls.roll)
    pos = pivot(scene, ls) + Vector(L) * ls.distance
    rot = Matrix((T, B, L)).transposed().to_4x4()
    return Matrix.Translation(pos) @ rot


def shape_data(ls):
    tex = None
    if ls.use_texture and ls.texture is not None:
        tex = image_array(ls.texture)
    grad = {}
    if ls.gradient_type != 'NONE':
        grad = dict(
            grad_type=ls.gradient_type, grad_angle=ls.gradient_angle,
            grad_offset=ls.gradient_offset, grad_scale=ls.gradient_scale,
            grad_mid=ls.gradient_midpoint, grad_interp=ls.gradient_interp,
            grad_a=tuple(c * ls.gradient_value_a for c in ls.gradient_color_a),
            grad_b=tuple(c * ls.gradient_value_b for c in ls.gradient_color_b))
    softness = ls.softness
    if ls.light_type == 'SPOT' and ls.shape == 'ELLIPSE' and tex is None and not grad \
            and ls.falloff == 0.0 and abs(ls.width - ls.height) < 1e-6:
        softness = 0.0  # handled by the native spot blend
    return core.ShapeData(
        shape=ls.shape, softness=softness, roundness=ls.roundness,
        ring_inner=ls.ring_inner, falloff=ls.falloff, tex=tex, **grad)


def image_array(img, max_size=1024):
    """User image as a float (h, w, 4) array, cached and downsampled."""
    try:
        w, h = img.size
    except ReferenceError:
        return None
    if w == 0 or h == 0:
        return None
    sig = (w, h, img.filepath, img.is_dirty, getattr(img, "generated_type", None))
    hit = _user_tex.get(img.name)
    if hit is not None and hit[0] == sig:
        return hit[1]
    try:
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
    except Exception:
        traceback.print_exc()
        return None
    arr = buf.reshape(h, w, 4).astype(np.float64)
    step = max(1, int(math.ceil(max(w, h) / max_size)))
    if step > 1:
        arr = arr[::step, ::step]
    _user_tex[img.name] = (sig, arr)
    return arr


def clear_caches():
    _tex_keys.clear()
    _user_tex.clear()


# ---------------------------------------------------------------------------
# Applying settings
# ---------------------------------------------------------------------------

def _layout(ls, shape):
    """Return (use_texture, kx, ky, extent) for the light's carrier."""
    t = ls.light_type
    if t == 'AREA':
        if shape.is_plain():
            return False, 1.0, 1.0, 1.0
        e = shape.edge_extent()
        return True, e, e, e
    if t == 'SPOT':
        if shape.is_plain() and shape.shape == 'ELLIPSE' and abs(ls.width - ls.height) < 1e-6:
            return False, 1.0, 1.0, 1.0
        e = shape.edge_extent()
        _spot, kx, ky = core.spot_cone(ls.width, ls.height, e, shape.shape in {'RECT', 'OCTAGON'})
        return True, kx, ky, e
    return False, 1.0, 1.0, 1.0


def is_textured(obj):
    ls = obj.light_studio
    return _layout(ls, shape_data(ls))[0]


def _ensure_data(obj, ltype):
    data = obj.data
    if data.users > 1:
        # Linked duplicate (Alt+D): every managed light needs its own data.
        obj.data = data = data.copy()
    if data.type != ltype:
        data.type = ltype
        data = obj.data
    return data


def apply(obj, scene=None):
    """Write position, size, colour and power. Returns True if a texture is needed."""
    if not is_managed(obj):
        return False
    scene = scene or _scene_of(obj)
    ls = obj.light_studio
    s = settings(scene)
    data = _ensure_data(obj, ls.light_type)
    shape = shape_data(ls)
    textured, _kx, _ky, extent = _layout(ls, shape)

    m = light_matrix(scene, ls)
    if not _matrix_close(obj.matrix_world, m):
        obj.matrix_world = m

    hidden = not ls.enabled
    if obj.hide_render != hidden:
        obj.hide_render = hidden
    if obj.hide_viewport != hidden:
        obj.hide_viewport = hidden

    gain = ls.opacity * s.power_scale
    d = ls.distance
    t = ls.light_type
    if t == 'AREA':
        sx, sy = core.area_size(ls.width, ls.height, d)
        if textured:
            data.shape = 'RECTANGLE'
            sx, sy = sx * extent, sy * extent
            energy = core.area_power(ls.intensity, sx, sy)
        else:
            data.shape = 'ELLIPSE' if ls.shape in {'ELLIPSE', 'RING', 'OCTAGON'} else 'RECTANGLE'
            energy = core.area_power(ls.intensity, sx, sy, ellipse=data.shape == 'ELLIPSE')
        data.size, data.size_y = sx, sy
        if hasattr(data, "spread"):
            data.spread = ls.spread
    elif t == 'SPOT':
        if textured:
            spot, _a, _b = core.spot_cone(ls.width, ls.height, extent,
                                          shape.shape in {'RECT', 'OCTAGON'})
            data.spot_size = min(spot, math.pi)
            data.spot_blend = 0.0
        else:
            data.spot_size = min(ls.width, math.pi)
            data.spot_blend = min(max(ls.softness, 0.0), 1.0)
        data.shadow_soft_size = d * math.tan(ls.source_size * 0.5)
        energy = core.point_power(ls.intensity, d) * POINT_CAL
    elif t == 'POINT':
        data.shadow_soft_size = d * core.tan_half(ls.width)
        energy = core.point_power(ls.intensity, d) * POINT_CAL
    else:  # SUN
        data.angle = min(ls.width, math.radians(179))
        energy = ls.intensity
    data.energy = energy * gain

    # colour
    color = tuple(ls.color)
    if hasattr(data, "use_temperature"):
        data.use_temperature = ls.use_temperature
        data.temperature = ls.temperature
    elif ls.use_temperature:
        k = core.kelvin_to_rgb(ls.temperature)
        color = tuple(a * b for a, b in zip(color, k))
    data.color = color

    if obj.visible_camera != ls.visible_camera:
        obj.visible_camera = ls.visible_camera

    _set_nodes(data, textured)
    return textured


def _matrix_close(a, b, eps=1e-6):
    n = len(a)
    for i in range(n):
        for j in range(n):
            if abs(a[i][j] - b[i][j]) > eps:
                return False
    return True


def _node_tree(data):
    nt = data.node_tree
    if nt is None:
        try:
            data.use_nodes = True
        except Exception:
            pass
        nt = data.node_tree
    return nt


def _set_nodes(data, textured):
    nt = data.node_tree if not textured else _node_tree(data)
    if nt is None:
        return
    nodes = nt.nodes
    emission = next((n for n in nodes if n.type == 'EMISSION'), None)
    img_node = nodes.get(IMG_NODE)
    if emission is None:
        return
    if not textured:
        if img_node is not None:
            for link in list(emission.inputs['Color'].links):
                if link.from_node == img_node:
                    nt.links.remove(link)
            emission.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
            if img_node.image is not None:
                img_node.image = None  # unused texture: do not keep / pack it
        return
    uv = nodes.get(UV_NODE)
    if uv is None:
        uv = nodes.new('ShaderNodeTexCoord')
        uv.name = UV_NODE
        uv.location = (emission.location.x - 520, emission.location.y)
    if img_node is None:
        img_node = nodes.new('ShaderNodeTexImage')
        img_node.name = IMG_NODE
        img_node.label = "Light Studio Texture"
        img_node.location = (emission.location.x - 300, emission.location.y)
        img_node.extension = 'CLIP'
        img_node.interpolation = 'Linear'
    if not uv.outputs['UV'].links:
        nt.links.new(uv.outputs['UV'], img_node.inputs['Vector'])
    if not any(l.from_node == img_node for l in emission.inputs['Color'].links):
        nt.links.new(img_node.outputs['Color'], emission.inputs['Color'])
    if 'Strength' in emission.inputs:
        emission.inputs['Strength'].default_value = 1.0


SLOTS = ("A", "B")
SYNC_TEXTURE_PIXELS = 512 * 512  # textures up to this size update instantly


def _slot_name(obj, slot):
    return f".LS {obj.name} {slot}"


def _owned(img, obj):
    return img is not None and img.get(OWNER_KEY) == obj.name


def texture_image(obj, res, create=True):
    """Return (node, image to write next).

    Every light has two texture images and they take turns. Cycles' Rendered
    view does not notice an image whose pixels changed in place, so the old
    texture stayed on screen while the light's size was already new (an
    exaggerated, "stuck" look). Swapping the image in the node is a real
    update that every engine picks up.
    """
    data = obj.data
    nt = data.node_tree
    node = nt.nodes.get(IMG_NODE) if nt else None
    if node is None:
        return None, None
    current = node.image
    slot = "B" if (_owned(current, obj) and current.name == _slot_name(obj, "A")) else "A"
    name = _slot_name(obj, slot)
    img = bpy.data.images.get(name)
    if img is not None and not _owned(img, obj):
        img = None
        name = None
    if img is None and create:
        img = bpy.data.images.new(name or _slot_name(obj, slot), res, res,
                                  alpha=False, float_buffer=True)
        img[OWNER_KEY] = obj.name
        try:
            img.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
    if img is not None and tuple(img.size) != (res, res):
        img.scale(res, res)
    return node, img


def update_texture(obj, force=False):
    if not is_managed(obj):
        return
    ls = obj.light_studio
    shape = shape_data(ls)
    textured, kx, ky, extent = _layout(ls, shape)
    if not textured:
        _tex_keys.pop(obj.name, None)
        return
    res = texture_resolution(ls, extent)
    key = (shape.key(), round(kx, 6), round(ky, 6), res)
    nt = obj.data.node_tree
    node = nt.nodes.get(IMG_NODE) if nt else None
    if (not force and _tex_keys.get(obj.name) == key and node is not None
            and _owned(node.image, obj)):
        return
    node, img = texture_image(obj, res)
    if img is None:
        return
    arr = core.light_texture(shape, res, kx, ky)
    img.pixels.foreach_set(arr.ravel())
    img.update()
    if img.packed_file is not None:
        img.pack()  # keep the packed copy in step, it is what a reload uses
    node.image = img
    for idb in (img, nt, obj.data):
        try:
            idb.update_tag()
        except Exception:
            pass
    _tex_keys[obj.name] = key


def texture_resolution(ls, extent):
    res = int(ls.texture_res)
    # Very soft lights bloom far outside their outline: keep the outline sharp.
    return min(2048, int(res * max(1.0, extent / 1.5)) // 8 * 8)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def request(obj, texture=True):
    """Called from property updates."""
    try:
        textured = apply(obj)
    except Exception:
        traceback.print_exc()
        return
    if textured:
        ls = obj.light_studio
        _textured, _kx, _ky, extent = _layout(ls, shape_data(ls))
        if texture_resolution(ls, extent) ** 2 <= SYNC_TEXTURE_PIXELS:
            # Update the texture together with the light's size and power so
            # the two never disagree on screen.
            try:
                update_texture(obj)
            except Exception:
                traceback.print_exc()
        else:
            _tex_pending.add(obj.name)
            _start_timer()
    from . import overlay
    overlay.tag_redraw()


def request_all(scene=None, texture=False):
    scene = scene or bpy.context.scene
    if scene is None:
        return
    for obj in managed_lights(scene):
        request(obj, texture=texture)


def _start_timer():
    global _timer_running
    if not _timer_running:
        _timer_running = True
        bpy.app.timers.register(_flush, first_interval=0.02)


def _flush():
    global _timer_running
    _timer_running = False
    names = list(_tex_pending)
    _tex_pending.clear()
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            update_texture(obj)
        except Exception:
            traceback.print_exc()
    return None


def flush_now():
    """Synchronous version (used by tests and before rendering)."""
    _flush()


def select_from_index(context):
    scene = context.scene
    i = settings(scene).active_index
    if not (0 <= i < len(scene.objects)):
        return
    obj = scene.objects[i]
    if not is_managed(obj):
        return
    vl = context.view_layer
    try:
        for o in context.selected_objects:
            if o != obj:
                o.select_set(False)
        obj.select_set(True)
        vl.objects.active = obj
    except RuntimeError:
        pass  # hidden / not in view layer


def set_active(context, obj):
    scene = context.scene
    try:
        idx = list(scene.objects).index(obj)
    except ValueError:
        return
    settings(scene).active_index = idx


# ---------------------------------------------------------------------------
# Viewport edits -> settings ("Follow Viewport Edits")
# ---------------------------------------------------------------------------

def read_transform(obj, scene=None, keep_roll=True):
    """Update lon / lat / distance (and roll) from the object's current transform."""
    scene = scene or _scene_of(obj)
    ls = obj.light_studio
    mw = obj.matrix_world
    pos = mw.translation
    expected = light_matrix(scene, ls)
    moved = (pos - expected.translation).length > 1e-5
    rotated = not _matrix_close(mw.to_3x3().normalized(), expected.to_3x3(), 1e-5)
    if not moved and not rotated:
        return False
    if moved:
        d = pos - pivot(scene, ls)
        dist = d.length
        if dist < 1e-6:
            return False
        lon, lat = core.dir_to_lonlat(tuple(d))
        roll = ls.roll
    else:
        lon, lat, dist = ls.lon, ls.lat, ls.distance
        x_axis = mw.to_3x3().normalized().col[0]
        roll = core.roll_from_axes(lon, lat, tuple(x_axis))
    # Assigning triggers the update callbacks, which re-aim the light.
    ls.lon, ls.lat = lon, lat
    ls.distance = dist
    if not keep_roll or not moved:
        ls.roll = roll
    return True


@persistent
def _on_depsgraph(scene, depsgraph):
    s = getattr(scene, "light_studio", None)
    if s is None:
        return
    target = s.target if s.target_mode == 'OBJECT' else None
    target_moved = False
    for upd in depsgraph.updates:
        if not upd.is_updated_transform:
            continue
        idv = upd.id
        if not isinstance(idv, bpy.types.Object):
            continue
        obj = idv.original
        if target is not None and obj == target:
            target_moved = True
            continue
        if s.follow_transform and is_managed(obj):
            try:
                read_transform(obj, scene)
            except Exception:
                traceback.print_exc()
    if target_moved:
        for obj in managed_lights(scene):
            if obj.light_studio.pivot_mode == 'TARGET':
                apply(obj, scene)


@persistent
def _on_frame(scene, _depsgraph=None):
    # Animated Light Studio settings do not fire update callbacks.
    for obj in managed_lights(scene):
        try:
            if apply(obj, scene):
                update_texture(obj)
        except Exception:
            traceback.print_exc()


@persistent
def _on_load(_dummy=None):
    clear_caches()
    for scene in bpy.data.scenes:
        for obj in managed_lights(scene):
            try:
                if apply(obj, scene):
                    update_texture(obj, force=True)
            except Exception:
                traceback.print_exc()


@persistent
def _on_undo(_dummy=None):
    clear_caches()
    scene = bpy.context.scene
    if scene is not None:
        for obj in managed_lights(scene):
            _tex_pending.add(obj.name)
        _start_timer()


@persistent
def _on_save_pre(_dummy=None):
    # Pack generated textures so renders work without the add-on
    # (command line, render farms).
    _flush()
    for img in bpy.data.images:
        if img.get(OWNER_KEY) and img.users:
            try:
                img.pack()
            except Exception:
                traceback.print_exc()


_HANDLERS = (
    ("depsgraph_update_post", _on_depsgraph),
    ("frame_change_post", _on_frame),
    ("load_post", _on_load),
    ("undo_post", _on_undo),
    ("redo_post", _on_undo),
    ("save_pre", _on_save_pre),
)


def register():
    for name, fn in _HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)


def unregister():
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(_flush):
        bpy.app.timers.unregister(_flush)
    global _timer_running
    _timer_running = False
    clear_caches()
