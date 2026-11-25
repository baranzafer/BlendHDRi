"""3D viewport overlay: aim lines from managed lights to their pivots."""

import bpy

from . import sync

_handle = None
_shader = None

ACTIVE = (1.0, 0.55, 0.1, 0.9)
NORMAL = (0.9, 0.9, 0.9, 0.35)
PAINTED = (0.3, 0.8, 1.0, 0.6)


def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in {'VIEW_3D', 'PROPERTIES'}:
                area.tag_redraw()


def _get_shader():
    global _shader
    if _shader is None:
        import gpu
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _cross(p, size):
    x, y, z = p
    return [(x - size, y, z), (x + size, y, z), (x, y - size, z), (x, y + size, z),
            (x, y, z - size), (x, y, z + size)]


def _draw():
    context = bpy.context
    scene = context.scene
    if scene is None or not scene.light_studio.show_overlay:
        return
    space = context.space_data
    if space is not None and getattr(space, "overlay", None) is not None \
            and not space.overlay.show_overlays:
        return
    lights = sync.managed_lights(scene)
    if not lights:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader

    active = sync.active_light(context)
    shader = _get_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(1.5)
    groups = {}
    for obj in lights:
        ls = obj.light_studio
        if not ls.enabled or obj.hide_get():
            continue
        p0 = obj.matrix_world.translation
        p1 = sync.pivot(scene, ls)
        col = ACTIVE if obj == active else (PAINTED if ls.pivot_mode == 'POINT' else NORMAL)
        pts = groups.setdefault(col, [])
        pts += [tuple(p0), tuple(p1)]
        size = max(0.02, ls.distance * 0.015)
        pts += _cross(tuple(p1), size)
    for col, pts in groups.items():
        batch = batch_for_shader(shader, 'LINES', {"pos": pts})
        shader.bind()
        shader.uniform_float("color", col)
        batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def register():
    global _handle
    if bpy.app.background:
        return
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _handle, _shader
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _shader = None
