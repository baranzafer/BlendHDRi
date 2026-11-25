"""BlendLights - Physical Light Studio for Blender.

Manage real Blender lights the way an HDRI studio manages its lights:
place them by longitude / latitude around the subject, paint where their
highlight falls with LightPaint, and give them edge softness, roundness,
centre falloff, gradients and image textures (Cycles light node textures).
"""

bl_info = {
    "name": "BlendLights - Physical Light Studio",
    "author": "BlendHDRi contributors",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar (N) > Light Studio",
    "description": "Studio control of physical lights: LightPaint, softness, gradients, textures",
    "category": "Lighting",
}

if "bpy" in locals():
    import importlib
    for _m in (core, presets, session, props, sync, overlay, ops, lightpaint, ui):  # noqa: F821
        importlib.reload(_m)
else:
    from . import core, presets, session, props, sync, overlay, ops, lightpaint, ui

import bpy  # noqa: E402,F401

_modules = (session, props, sync, overlay, ops, lightpaint, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
