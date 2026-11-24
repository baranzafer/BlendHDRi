"""LightPaint: click on the model in the 3D viewport to position a light.

Reflection mode puts the light where it will be *seen reflected* at the
clicked point, Illumination mode makes it light the surface head on and Rim
mode places it behind the surface for an edge highlight.
"""

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import render, session, studio
from .ops import active_light, new_light

SESSION = "lightpaint"

HELP = ("HDRI LightPaint  |  LMB (drag): move active light to the clicked spot   "
        "Shift+LMB: new light   1/2/3: Reflection/Illumination/Rim   Esc / RMB: finish")


def view3d_under_mouse(context, event):
    win = context.window
    if win is None:
        return None, None, None
    for area in win.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type != 'WINDOW':
                continue
            if (region.x <= event.mouse_x < region.x + region.width
                    and region.y <= event.mouse_y < region.y + region.height):
                rv3d = getattr(region, "data", None) or area.spaces.active.region_3d
                return area, region, rv3d
    return None, None, None


def light_direction(mode, view_dir, normal):
    d = view_dir.normalized()
    n = normal.normalized()
    if n.dot(d) > 0.0:
        n = -n  # facing away from the viewer (back face)
    if mode == 'ILLUMINATION':
        return n
    if mode == 'RIM':
        t = n - d * n.dot(d)
        if t.length < 1e-4:
            t = n
        return (t.normalized() + d * 1.2).normalized()
    # REFLECTION
    return (d - 2.0 * d.dot(n) * n).normalized()


def raycast(context, region, rv3d, event):
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _loc, normal, _idx, _obj, _mat = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit:
        return None
    return direction, Vector(normal)


# ---------------------------------------------------------------------------
# Viewport palette (GPU drawn, handled inside the LightPaint modal)
# ---------------------------------------------------------------------------

LP = {"hover": None, "create_next": False, "fold": False}
_draw_handle = None


def _lp_text(key):
    from . import gui
    tr = {
        "title": ("LightPaint", "LightPaint"),
        "mode": ("MOD", "MODE"),
        "active": ("AKTİF IŞIK", "ACTIVE LIGHT"),
        "new": ("+ Yeni ışık", "+ New light"),
        "new_on": ("Tıkla: yeni ışık", "Click: new light"),
        "studio": ("Studio", "Studio"),
        "finish": ("Bitir", "Finish"),
        "tip": ("Modele tıkla / sürükle · Shift+tık: yeni ışık · Sağ tık: bitir",
                "Click / drag on the model · Shift+click: new light · Right click: finish"),
        "map": ("HDRI haritası", "HDRI map"),
        "r": ("1 Yansıma", "1 Reflect"), "i": ("2 Aydınlat", "2 Light"), "k": ("3 Kenar", "3 Rim"),
        "none": ("Henüz ışık yok", "No lights yet"),
    }[key]
    return tr[0] if gui.language() == 'TR' else tr[1]


def build_palette(context, region, painter=None):
    from . import gui_kit as K
    b = K.Builder(region, painter, LP["hover"])
    s = b.s
    st = context.scene.hdri_studio
    w = 236 * s
    x0 = 14 * s
    top = region.height - 44 * s
    lights = list(enumerate(st.lights))[:7]
    rows = max(1, len(lights))
    h = 22 * s + 8 * s + 22 * s + 26 * s + 8 * s + 22 * s + rows * 28 * s + 6 * s + 26 * s + 8 * s + 38 * s
    if LP["fold"]:
        h = 22 * s
    rect = (x0, top - h, x0 + w, top)
    y = b.panel_bg(rect, _lp_text("title"), "lp", LP["fold"])
    if LP["fold"]:
        b.flush()
        return _minimap(b, context, region, painter)
    pad = 8 * s
    x, iw = x0 + pad, w - 2 * pad
    y -= 8 * s
    y = b.section(x, y, iw, _lp_text("mode"))

    def set_mode(m):
        st.paint_mode = m
    b.segmented((x, y - 26 * s, x + iw, y), "lpmode",
                [('REFLECTION', _lp_text("r")), ('ILLUMINATION', _lp_text("i")), ('RIM', _lp_text("k"))],
                st.paint_mode, set_mode)
    y -= 26 * s + 8 * s
    y = b.section(x, y, iw, _lp_text("active"))
    if not lights:
        b.text(x, y - 18 * s, _lp_text("none"), K.COL_DIM, int(10 * s))
        y -= 28 * s
    for i, l in lights:
        def pick(ctx, ev, i=i):
            ctx.scene.hdri_studio.active_index = i
            LP["create_next"] = False
        r = (x, y - 26 * s, x + iw, y)
        b.button(r, f"lp:light:{i}", l.name, pick, on=i == st.active_index and not LP["create_next"],
                 style='card', align='L')
        b.text(x + iw - 8 * s, y - 17 * s, f"{l.intensity:.1f}", K.COL_DIM, int(9.5 * s), 'R')
        y -= 28 * s
    y -= 6 * s
    bw = iw / 3

    def toggle_new(ctx, ev):
        LP["create_next"] = not LP["create_next"]

    def open_studio(ctx, ev):
        try:
            bpy.ops.hdri_studio.open_editor(mode='WINDOW')
        except Exception as ex:
            print("BlendHDRi:", ex)

    def finish(ctx, ev):
        session.get(SESSION).request_stop()
    b.button((x, y - 26 * s, x + bw - 1, y), "lp:new",
             _lp_text("new_on") if LP["create_next"] else _lp_text("new"), toggle_new,
             on=LP["create_next"])
    b.button((x + bw + 1, y - 26 * s, x + 2 * bw - 1, y), "lp:studio", _lp_text("studio"), open_studio)
    b.button((x + 2 * bw + 1, y - 26 * s, x + iw, y), "lp:finish", _lp_text("finish"), finish)
    y -= 26 * s + 8 * s
    b.rect(x0, y, x0 + w, y + 1, K.COL_EDGE)
    size = int(9 * s)
    from .gui import _wrap
    for i, line in enumerate(_wrap(_lp_text("tip"), size, w - 16 * s)[:2]):
        b.text(x0 + 8 * s, y - 13 * s - i * 11 * s, line, K.COL_DIM, size)
    b.flush()
    return _minimap(b, context, region, painter)


def _minimap(b, context, region, painter):
    from . import gui_kit as K
    s = b.s
    st = context.scene.hdri_studio
    # mini HDRI map (top right)
    mw, mh = 200 * s, 100 * s
    mx1 = region.width - 80 * s
    my1 = region.height - 44 * s
    mx0, my0 = mx1 - mw, my1 - mh
    b.blocks.append((mx0, my0 - 18 * s, mx1, my1))
    b.target((mx0, my0 - 18 * s, mx1, my1), "lp:map", 'panel')
    if painter is not None:
        img = studio.get_canvas(context.scene, create=False)
        b.rect(mx0 - 1, my0 - 1, mx1 + 1, my1 + 1, K.COL_EDGE)
        if img is not None and not bpy.app.background:
            try:
                import gpu
                painter.image(gpu.texture.from_image(img), mx0, my0, mx1, my1)
            except Exception:
                b.rect(mx0, my0, mx1, my1, K.COL_DARK)
        b.flush()
        for i, l in enumerate(st.lights):
            u, v = render.lonlat_to_uv(l.lon, l.lat)
            cx, cy = mx0 + u * mw, my0 + v * mh
            col = K.COL_ORANGE if i == st.active_index else (0.8, 0.8, 0.85, 0.9)
            painter.line(K._circle(cx, cy, (4 if i == st.active_index else 2.5) * s, 12), col, 1.6)
        b.text(mx1, my0 - 14 * s, _lp_text("map"), K.COL_DIM, int(9 * s), 'R')
        # status line
        l = active_light(context.scene)
        if l is not None:
            import math
            mode = {'REFLECTION': _lp_text("r"), 'ILLUMINATION': _lp_text("i"), 'RIM': _lp_text("k")}[st.paint_mode]
            msg = f"{l.name} · {math.degrees(l.lon):.0f}° / {math.degrees(l.lat):.0f}° · {mode[2:]}"
            b.rect(0, 0, region.width, 24 * s, (0.08, 0.08, 0.09, 0.85))
            b.text(14 * s, 7 * s, msg, (0.82, 0.82, 0.85, 1.0), int(10 * s))
        b.flush()
    return b


def _draw_palette():
    if not is_running():
        return
    context = bpy.context
    try:
        from . import gui_kit as K
        build_palette(context, context.region, K.Painter(context.region))
    except Exception:
        import traceback
        traceback.print_exc()


class HDRISTUDIO_OT_lightpaint(session.ModalToolMixin, bpy.types.Operator):
    bl_idname = "hdri_studio.lightpaint"
    bl_label = "LightPaint"
    bl_description = ("Click on your model in the 3D viewport to place the active light "
                      "(reflection / illumination / rim). Run again to stop")

    session_name = SESSION
    status_text = HELP

    def tool_start(self, context, event):
        self.painting = False
        LP["create_next"] = False
        LP["hover"] = None
        return True

    def tool_cleanup(self, context):
        if getattr(self, "painting", False):
            self.painting = False
            self._push_undo("LightPaint")

    @staticmethod
    def _push_undo(msg):
        try:
            bpy.ops.ed.undo_push(message=msg)
        except Exception:
            pass

    def _apply(self, context, region, rv3d, event, create=False):
        res = raycast(context, region, rv3d, event)
        if res is None:
            return False
        view_dir, normal = res
        s = context.scene.hdri_studio
        lon, lat = render.dir_to_lonlat(light_direction(s.paint_mode, view_dir, normal))
        light = active_light(context.scene)
        if create or light is None:
            new_light(context.scene, s.canvas_add_preset, lon=lon, lat=lat)
            studio.schedule_update(context.scene, force=True)
        else:
            light.lon = lon
            light.lat = lat
        return True

    def tool_modal(self, context, event):
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}
        s = context.scene.hdri_studio

        if self.painting:
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                area, region, rv3d = view3d_under_mouse(context, event)
                if region is not None:
                    self._apply(context, region, rv3d, event)
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.painting = False
                self._push_undo("LightPaint")
                return {'RUNNING_MODAL'}
            if event.type in {'WINDOW_DEACTIVATE', 'ESC', 'RIGHTMOUSE'} or \
                    (event.type == 'LEFTMOUSE' and event.value == 'PRESS'):
                # Missed release (button let go outside Blender): stop painting.
                self.painting = False
                self._push_undo("LightPaint")
                if event.type != 'LEFTMOUSE':
                    return {'PASS_THROUGH'}
            else:
                return {'PASS_THROUGH'}

        area, region, rv3d = view3d_under_mouse(context, event)
        if region is None or rv3d is None:
            return {'PASS_THROUGH'}

        # Palette / HUD ----------------------------------------------------------
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        pal = build_palette(context, region)
        t = pal.hit(x, y)
        hid = t.id if t is not None and t.kind != 'panel' else None
        if hid != LP["hover"]:
            LP["hover"] = hid
            area.tag_redraw()
        if t is not None:
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                if t.kind == 'fold':
                    LP["fold"] = not LP["fold"]
                    area.tag_redraw()
                elif t.action is not None:
                    t.action(context, event)
                    for a in context.screen.areas:
                        a.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type in {'LEFTMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.value == 'PRESS':
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                return 'FINISH'
            if event.type in {'ONE', 'TWO', 'THREE'} and not (event.ctrl or event.alt or event.shift):
                s.paint_mode = {'ONE': 'REFLECTION', 'TWO': 'ILLUMINATION',
                                'THREE': 'RIM'}[event.type]
                studio.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and not (event.ctrl or event.alt):
                create = event.shift or LP["create_next"]
                if self._apply(context, region, rv3d, event, create=create):
                    if create:
                        LP["create_next"] = False
                        self._push_undo("LightPaint Add")
                    else:
                        self.painting = True
                    return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}
        return {'PASS_THROUGH'}


def is_running():
    return session.get(SESSION).running


classes = (HDRISTUDIO_OT_lightpaint,)


def register():
    global _draw_handle
    for c in classes:
        bpy.utils.register_class(c)
    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_palette, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _draw_handle
    session.get(SESSION).reset()
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
