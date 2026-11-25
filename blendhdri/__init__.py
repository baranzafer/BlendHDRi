"""BlendHDRi - HDRI Studio for Blender.

Create studio HDRIs procedurally: place softboxes, strip lights, octaboxes
and more on an equirectangular canvas, see the result live in the viewport,
paint light positions directly onto your model and export the result as
OpenEXR / Radiance HDR.
"""

bl_info = {
    "name": "BlendHDRi - HDRI Studio",
    "author": "BlendHDRi contributors",
    "version": (0, 5, 0),
    "blender": (4, 2, 0),
    "location": "Image Editor > Sidebar (N) > HDRI Studio, Window > HDRI Studio Editor",
    "description": "Build studio lighting HDRIs with softboxes, LightPaint and EXR export",
    "category": "Lighting",
}

if "bpy" in locals():
    import importlib
    for _m in (render, presets, session, props, studio, ops, canvas, canvas_ops, lightpaint, ui):  # noqa: F821
        importlib.reload(_m)
else:
    from . import render, presets, session, props, studio, ops, canvas, canvas_ops, lightpaint, ui

import bpy  # noqa: E402,F401

_modules = (session, props, studio, ops, canvas, canvas_ops, lightpaint, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
