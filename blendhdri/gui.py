"""BlendHDRi studio interface drawn on top of the canvas (Image Editor).

``build_studio`` lays out every widget. It is called by the draw handler
(with a painter) and by the event operators in ``gui_ops`` (without one) so
clicks always hit what is drawn.
"""

import math

import bpy

from . import canvas, presets, render, studio
from . import gui_kit as K

# Session-only interface state (like Mini CAD's palette position)
STATE = {
    "hover": None,          # id of the hovered widget
    "hover_light": -1,      # index of the light under the cursor
    "active": None,         # id of the widget being dragged
    "pos": {},              # panel id -> (x, top)
    "fold": {},             # panel/section id -> folded?
    "scroll": 0.0,          # layer strip scroll offset (px)
}

_textures = {"version": -1, "chrome": None, "diffuse": None}
_draw_handle = None


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

TEXT = {
    "title": ("BlendHDRi Studio", "BlendHDRi Studio"),
    "setups": ("Kurulumlar", "Setups"),
    "save": ("Kaydet…", "Save…"),
    "live": ("Canlı", "Live"),
    "preview": ("Önizleme", "Preview"),
    "world_on": ("Dünya", "World"),
    "world_use": ("Dünyayı kullan", "Use world"),
    "viewport": ("Viewport", "Viewport"),
    "fit": ("Sığdır", "Fit"),
    "classic": ("Klasik", "Classic"),
    "export": ("Dışa aktar", "Export"),
    "tools": ("BlendHDRi · Araçlar", "BlendHDRi · Tools"),
    "sec_tool": ("ARAÇ", "TOOL"),
    "sec_add": ("IŞIK EKLE", "ADD LIGHT"),
    "sec_mode": ("YERLEŞİM MODU", "PLACEMENT"),
    "sec_canvas": ("TUVAL", "CANVAS"),
    "reflection": ("Yansıma", "Reflect"),
    "illumination": ("Aydınlat", "Light"),
    "rim": ("Kenar", "Rim"),
    "grid": ("Izgara", "Grid"),
    "labels": ("Etiket", "Labels"),
    "snap": ("Yakala", "Snap"),
    "light": ("Işık", "Light"),
    "no_light": ("Işık yok: soldan bir ışık ekleyin", "No lights: add one on the left"),
    "sec_pos": ("KONUM", "POSITION"),
    "sec_shape": ("BİÇİM", "SHAPE"),
    "sec_emit": ("IŞIK", "EMISSION"),
    "sec_out": ("ÇIKTI", "OUTPUT"),
    "lon": ("Boylam", "Longitude"),
    "lat": ("Enlem", "Latitude"),
    "roll": ("Dönüş", "Rotation"),
    "width": ("Genişlik", "Width"),
    "height": ("Yükseklik", "Height"),
    "soft": ("Kenar yumuşaklığı", "Edge softness"),
    "round": ("Köşe yuvarlaklığı", "Roundness"),
    "ring": ("Halka iç boyutu", "Ring inner size"),
    "falloff": ("Merkez kararması", "Center falloff"),
    "gradient": ("Gradyan", "Gradient"),
    "intensity": ("Parlaklık", "Intensity"),
    "opacity": ("Opaklık", "Opacity"),
    "temp": ("Renk sıcaklığı", "Temperature"),
    "color": ("Renk", "Color"),
    "texture": ("Doku", "Texture"),
    "no_texture": ("Doku yok · seçmek için tıkla", "No texture · click to choose"),
    "duplicate": ("Çoğalt", "Duplicate"),
    "delete": ("Sil", "Delete"),
    "save_preset": ("Preset", "Preset"),
    "layers": ("KATMANLAR · alttan üste çizilir", "LAYERS · drawn bottom to top"),
    "layers_tip": ("H: gizle · X: sil · sağ tık: menü", "H: hide · X: delete · right click: menu"),
    "chrome": ("Krom", "Chrome"),
    "matte": ("Mat", "Matte"),
    "front": ("Ön (kamera)", "Front (camera)"),
    "back": ("Arka", "Back"),
    "left": ("Sol", "Left"),
    "right": ("Sağ", "Right"),
    "out_hdri": ("HDRI", "HDRI"),
    "out_area": ("Area", "Area"),
    "out_both": ("İkisi", "Both"),
    "b_add": ("Ekle", "Add"),
    "b_over": ("Üstüne", "Over"),
    "b_mul": ("Çarp", "Multiply"),
    "shape_rect": ("Dikdörtgen", "Rectangle"),
    "shape_round": ("Yuvarlak", "Round"),
    "shape_oct": ("Octabox", "Octabox"),
    "shape_ring": ("Halka", "Ring"),
    "tool_MOVE": ("Seç / taşı: ışığa tıkla ve sürükle. Ctrl+tık: yeni ışık.",
                  "Select / move: click a light and drag. Ctrl+click: new light."),
    "tool_SCALE": ("Ölçekle: sürükle. Shift: yalnız genişlik, Alt: yalnız yükseklik.",
                   "Scale: drag. Shift: width only, Alt: height only."),
    "tool_ROTATE": ("Döndür: ışığı sürükleyerek kendi ekseninde çevir.",
                    "Rotate: drag to spin the light around its axis."),
    "tool_ADD": ("Ekle: tuvale tıkla, seçili preset oraya eklenir.",
                 "Add: click on the canvas to place the chosen preset."),
    "tool_PAINT": ("LightPaint: 3B görünümde modele tıkla, ışık oraya yerleşir.",
                   "LightPaint: click your model in the 3D view to place the light."),
    "t_move": ("Seç / taşı", "Select / move"),
    "t_scale": ("Ölçekle", "Scale"),
    "t_rotate": ("Döndür", "Rotate"),
    "t_add": ("Tıkla ekle", "Click to add"),
    "t_paint": ("LightPaint (3B görünüm)", "LightPaint (3D view)"),
}


def T(key):
    pair = TEXT.get(key)
    if pair is None:
        return key
    return pair[0] if language() == 'TR' else pair[1]


def language():
    try:
        lang = bpy.context.scene.hdri_studio.ui_language
    except Exception:
        lang = 'AUTO'
    if lang == 'AUTO':
        try:
            loc = bpy.app.translations.locale or ""
            use = bpy.context.preferences.view.use_translate_interface
            return 'TR' if (use and loc.startswith("tr")) else 'EN'
        except Exception:
            return 'EN'
    return lang


PRESET_NAMES_TR = {
    'SOFTBOX_LARGE': "Büyük softbox", 'SOFTBOX_SQUARE': "Kare softbox",
    'SOFTBOX_SMALL': "Küçük softbox", 'STRIP': "Strip", 'STRIP_WIDE': "Yatay strip",
    'OCTABOX': "Octabox", 'ROUND': "Yuvarlak softbox", 'RING': "Halka ışık",
    'PANEL': "Üst panel", 'SPOT': "Sert spot", 'SUN': "Güneş", 'WINDOW': "Pencere",
    'FLAG': "Siyah bayrak", 'REFLECTOR': "Reflektör",
}

PALETTE_PRESETS = ['SOFTBOX_LARGE', 'SOFTBOX_SQUARE', 'STRIP', 'STRIP_WIDE', 'ROUND', 'OCTABOX',
                   'RING', 'PANEL', 'SPOT', 'SUN', 'WINDOW', 'FLAG']


def preset_label(key):
    if language() == 'TR':
        return PRESET_NAMES_TR.get(key, key)
    return presets.LIGHT_PRESETS[key][0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_studio_space(space):
    if not canvas.is_canvas_space(space):
        return False
    try:
        return bpy.context.scene.hdri_studio.use_custom_ui
    except Exception:
        return False


def _call(op, *args, **kw):
    def run(ctx, ev):
        try:
            op(*args, **kw)
        except Exception as ex:
            print("BlendHDRi:", ex)
    return run


def _set(obj, attr, transform=None):
    def setter(value):
        setattr(obj, attr, transform(value) if transform else value)
    return setter


def _toggle(obj, attr):
    def run(ctx, ev):
        setattr(obj, attr, not getattr(obj, attr))
    return run


def _fold(key):
    def run(ctx, ev):
        STATE["fold"][key] = not STATE["fold"].get(key, False)
    return run


def _wrap(text, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if K.text_width(t, size) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _measure(region, fn, *args):
    b = K.Builder(region, None)
    return fn(b, *args)


def _panel_pos(pid, region, default):
    x, top = STATE["pos"].get(pid, default)
    s = K.ui_scale()
    x = min(max(x, 0), max(region.width - 60 * s, 0))
    top = min(max(top, 60 * s), region.height)
    return x, top


def header_height():
    return 34 * K.ui_scale()


def strip_height():
    return 118 * K.ui_scale()


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------

def _header(b, context, region):
    s = b.s
    sc = context.scene
    st = sc.hdri_studio
    y1 = region.height
    y0 = y1 - header_height()
    b.blocks.append((0, y0, region.width, y1))
    b.rect(0, y0, region.width, y1, K.COL_HEADER)
    b.rect(0, y0 - 1, region.width, y0, K.COL_EDGE)
    b.target((0, y0, region.width, y1), "header:bg", 'panel')
    by0, by1 = y0 + 5 * s, y1 - 5 * s
    size = int(11 * s)

    x = 10 * s
    if b.p:
        b.p.line(K._circle(x + 8 * s, (y0 + y1) / 2, 7 * s), K.COL_ORANGE, 1.6)
        b.p.line([(x + 1 * s, (y0 + y1) / 2), (x + 15 * s, (y0 + y1) / 2)], K.COL_ORANGE, 1.2)
    b.text(x + 22 * s, (y0 + y1) / 2 - 4 * s, T("title"), K.COL_TEXT, int(12 * s))
    x += 26 * s + K.text_width(T("title"), int(12 * s)) + 14 * s

    def btn(label, id, action, w=None, on=False, style='normal', tip="", icon=None, trail=None):
        nonlocal x
        b.button((x, by0, x + w, by1), id, label, action, on=on, style=style, tip=tip,
                 icon=icon, trail=trail, align='L' if icon is not None else 'C')
        x += w + 5 * s

    right = region.width - 10 * s
    exp_label = f"{T('export')} {'EXR' if st.export_format == 'OPEN_EXR' else 'HDR'} {int(st.export_res) // 1024}K"
    ew = K.text_width(exp_label, size) + 26 * s
    b.button((right - ew, by0, right, by1), "hdr:export", exp_label,
             _call(bpy.ops.hdri_studio.export, 'INVOKE_DEFAULT'), style='orange',
             tip="OpenEXR / Radiance HDR")
    right -= ew + 6 * s
    cw = K.text_width(T("classic"), size) + 20 * s
    b.button((right - cw, by0, right, by1), "hdr:classic", T("classic"),
             _toggle(st, "use_custom_ui"),
             tip="Sidebar (N) panels" if language() == 'EN' else "Kenar çubuğu (N) panellerine dön")
    right -= cw + 6 * s

    world = studio.get_studio_world()
    active = world is not None and sc.world == world
    live_dot = K.icon_dot((0.49, 1.0, 0.63, 1.0) if st.auto_update else (0.5, 0.5, 0.52, 1.0))
    res = {'512': "0.5K", '1024': "1K", '2048': "2K"}.get(st.preview_res, st.preview_res)
    items = [
        # label, id, action, on, icon, trail
        (T("setups"), "hdr:setups", _call(bpy.ops.wm.call_menu, name="HDRISTUDIO_MT_studio"), False, None, K.icon_tri('down')),
        (T("save"), "hdr:save", _call(bpy.ops.hdri_studio.save_studio_preset, 'INVOKE_DEFAULT'), False, None, None),
        (T("live"), "hdr:live", _toggle(st, "auto_update"), st.auto_update, live_dot, None),
        (f"{T('preview')} {res}", "hdr:res", _cycle_res(st), False, None, None),
        (T("world_on") if active else T("world_use"), "hdr:world",
         _call(bpy.ops.hdri_studio.assign_world), active, K.icon_check if active else None, None),
        (T("viewport"), "hdr:vp", _call(bpy.ops.hdri_studio.viewport_preview), False, None, None),
        (T("fit"), "hdr:fit", _call(bpy.ops.hdri_studio.fit_view, 'INVOKE_DEFAULT'), False, None, None),
    ]
    for label, id, action, on, icon, trail in items:
        w = K.text_width(label, size) + 22 * s + (16 * s if icon or trail else 0)
        if x + w > right - 8 * s:
            break
        btn(label, id, action, w, on, icon=icon, trail=trail)


def _cycle_res(st):
    def run(ctx, ev):
        order = ['512', '1024', '2048']
        st.preview_res = order[(order.index(st.preview_res) + 1) % len(order)]
    return run


# ---------------------------------------------------------------------------
# Tool palette (left)
# ---------------------------------------------------------------------------

TOOLS = [('MOVE', K.icon_move, "t_move"), ('SCALE', K.icon_scale, "t_scale"),
         ('ROTATE', K.icon_rotate, "t_rotate"), ('ADD', K.icon_add, "t_add"),
         ('PAINT', K.icon_paint, "t_paint")]


def _palette_content(b, context, x0, top, w):
    s = b.s
    st = context.scene.hdri_studio
    pad = 7 * s
    x = x0 + pad
    iw = w - 2 * pad
    y = top - 4 * s

    y = b.section(x, y, iw, T("sec_tool"))
    bw = iw / 5
    from . import lightpaint
    for i, (key, icon, tip) in enumerate(TOOLS):
        r = (x + i * bw + 1, y - 32 * s, x + (i + 1) * bw - 1, y)
        if key == 'PAINT':
            b.button(r, "tool:PAINT", "", _call(bpy.ops.hdri_studio.lightpaint, 'INVOKE_DEFAULT'),
                     on=lightpaint.is_running(), tip=T("tool_PAINT"), icon=icon)
        else:
            b.button(r, f"tool:{key}", "", _set_tool(st, key), on=st.canvas_tool == key,
                     tip=T(f"tool_{key}"), icon=icon)
    y -= 32 * s + 6 * s

    y = b.section(x, y, iw, T("sec_add"))
    cols, bh = 4, 36 * s
    cw = iw / cols
    for i, key in enumerate(PALETTE_PRESETS):
        r_, c_ = divmod(i, cols)
        p = presets.LIGHT_PRESETS[key][3]
        r = (x + c_ * cw + 1, y - (r_ + 1) * bh + 1, x + (c_ + 1) * cw - 1, y - r_ * bh - 1)
        icon = K.shape_icon(p.get('shape', 'RECT'), p.get('width', 1), p.get('height', 1),
                            p.get('blend', 'ADD'))
        b.button(r, f"preset:{key}", "", _add_preset(key), tip=preset_label(key), icon=icon,
                 on=st.canvas_tool == 'ADD' and st.canvas_add_preset == key)
    y -= math.ceil(len(PALETTE_PRESETS) / cols) * bh + 6 * s

    y = b.section(x, y, iw, T("sec_mode"))
    b.segmented((x, y - 26 * s, x + iw, y), "mode", [
        ('REFLECTION', T("reflection")), ('ILLUMINATION', T("illumination")), ('RIM', T("rim"))],
        st.paint_mode, _set(st, "paint_mode"))
    y -= 26 * s + 6 * s

    y = b.section(x, y, iw, T("sec_canvas"))
    tw = iw / 3
    for i, (attr, key) in enumerate((("show_grid", "grid"), ("show_labels", "labels"),
                                      ("snap_angle", "snap"))):
        b.button((x + i * tw + 1, y - 26 * s, x + (i + 1) * tw - 1, y), f"opt:{attr}", T(key),
                 _toggle(st, attr), on=getattr(st, attr))
    y -= 26 * s + 6 * s
    return y


def _set_tool(st, key):
    def run(ctx, ev):
        st.canvas_tool = key
    return run


def _add_preset(key):
    def run(ctx, ev):
        st = ctx.scene.hdri_studio
        if st.canvas_tool == 'ADD':
            st.canvas_add_preset = key   # next canvas click places it
        else:
            bpy.ops.hdri_studio.add_light(preset=key)
    return run


def _palette(b, context, region):
    s = b.s
    w = 214 * s
    default = (12 * s, region.height - header_height() - 10 * s)
    x0, top = _panel_pos("pal", region, default)
    folded = STATE["fold"].get("pal", False)
    th = 22 * s
    if folded:
        h = th
    else:
        bottom = _measure(region, _palette_content, context, x0, top - th, w)
        tip_h = 34 * s
        h = top - bottom + tip_h
    rect = (x0, top - h, x0 + w, top)
    ctop = b.panel_bg(rect, T("tools"), "pal", folded)
    if folded:
        return
    y = _palette_content(b, context, x0, ctop, w)
    # tooltip / hint line
    b.rect(x0, y - 1, x0 + w, y, K.COL_EDGE)
    tip = _current_tip(b, context)
    size = int(9.5 * s)
    for i, line in enumerate(_wrap(tip, size, w - 16 * s)[:2]):
        b.text(x0 + 8 * s, y - 13 * s - i * 12 * s, line, K.COL_DIM, size)


def _current_tip(b, context):
    hid = STATE.get("hover")
    if hid:
        for t in b.targets:
            if t.id == hid and t.tip:
                return t.tip
    st = context.scene.hdri_studio
    return T(f"tool_{st.canvas_tool}")


# ---------------------------------------------------------------------------
# Inspector (right)
# ---------------------------------------------------------------------------

D = math.degrees
R = math.radians


def _inspector_content(b, context, x0, top, w):
    s = b.s
    st = context.scene.hdri_studio
    pad = 9 * s
    x, iw = x0 + pad, w - 2 * pad
    y = top - 6 * s
    if not (0 <= st.active_index < len(st.lights)):
        b.text(x, y - 16 * s, T("no_light"), K.COL_DIM, int(10 * s))
        return y - 28 * s
    l = st.lights[st.active_index]
    sl = 30 * s

    shapes = [('RECT', T("shape_rect")), ('ELLIPSE', T("shape_round")),
              ('OCTAGON', T("shape_oct")), ('RING', T("shape_ring"))]
    icons = {k: K.shape_icon(k, 1.3 if k == 'RECT' else 1, 1) for k, _ in shapes}
    bw = iw / 4
    for i, (k, label) in enumerate(shapes):
        r = (x + i * bw + 1, y - 40 * s, x + (i + 1) * bw - 1, y)
        b.button(r, f"shape:{k}", "", (lambda kk: (lambda c, e: setattr(l, "shape", kk)))(k),
                 on=l.shape == k, tip=label, icon=icons[k])
    y -= 40 * s + 5 * s
    b.segmented((x, y - 22 * s, x + iw, y), "blend",
                [('ADD', T("b_add")), ('OVER', T("b_over")), ('MULTIPLY', T("b_mul"))],
                l.blend, _set(l, "blend"))
    y -= 22 * s + 6 * s

    def sec(key, label):
        nonlocal y
        open_ = not STATE["fold"].get("sec:" + key, False)
        y = b.section(x, y, iw, label, "sec:" + key, open_, _fold("sec:" + key))
        return open_

    def slider(id, label, value, vmin, vmax, setter, fmt, step=None, track=None):
        nonlocal y
        b.slider((x, y - sl + 4 * s, x + iw, y), id, label, value, vmin, vmax, setter, fmt,
                 step=step, track=track)
        y -= sl

    if sec("pos", T("sec_pos")):
        slider("s:lon", T("lon"), D(l.lon), -180, 180, _set(l, "lon", R), "{:.0f}°", 1)
        slider("s:lat", T("lat"), D(l.lat), -90, 90, _set(l, "lat", R), "{:.0f}°", 1)
        slider("s:roll", T("roll"), D(l.roll), -180, 180, _set(l, "roll", R), "{:.0f}°", 1)
    if sec("shape", T("sec_shape")):
        slider("s:w", T("width"), D(l.width), 0.2, 170, _set(l, "width", R), "{:.1f}°", 0.5)
        slider("s:h", T("height"), D(l.height), 0.2, 170, _set(l, "height", R), "{:.1f}°", 0.5)
        slider("s:soft", T("soft"), l.softness, 0, 1, _set(l, "softness"), "{:.2f}", 0.01)
        if l.shape == 'RECT':
            slider("s:round", T("round"), l.roundness, 0, 1, _set(l, "roundness"), "{:.2f}", 0.01)
        if l.shape == 'RING':
            slider("s:ring", T("ring"), l.ring_inner, 0, 0.98, _set(l, "ring_inner"), "{:.2f}", 0.01)
        slider("s:fall", T("falloff"), l.falloff, 0, 1, _set(l, "falloff"), "{:.2f}", 0.01)
        slider("s:grad", T("gradient"), l.gradient, -1, 1, _set(l, "gradient"), "{:+.2f}", 0.02)
    if sec("emit", T("sec_emit")):
        if l.blend != 'MULTIPLY':
            slider("s:int", T("intensity"), l.intensity, 0, max(50.0, l.intensity * 1.25),
                   _set(l, "intensity"), "{:.1f}", 0.1)
        slider("s:op", T("opacity"), l.opacity, 0, 1, _set(l, "opacity"), "{:.2f}", 0.01)
        # colour swatch + temperature
        sw = 26 * s
        b.rect(x, y - sw, x + sw, y, tuple(min(1.0, c) for c in l.color) + (1.0,))
        b.frame(x, y - sw, x + sw, y, (0.35, 0.35, 0.38, 1.0))
        b.target((x, y - sw, x + sw, y), "color", 'button',
                 _call(bpy.ops.hdri_studio.light_popup, 'INVOKE_DEFAULT', section='COLOR'), T("color"))
        tx = x + sw + 6 * s
        tg = 22 * s
        b.button((tx, y - sw, tx + tg, y), "temp:on", "K", _toggle(l, "use_temperature"),
                 on=l.use_temperature, tip=T("temp"))
        kx0 = tx + tg + 6 * s
        track = [(1.0, 0.45, 0.15, 1.0), (1.0, 0.8, 0.6, 1.0), (1.0, 1.0, 1.0, 1.0),
                 (0.8, 0.87, 1.0, 1.0), (0.6, 0.74, 1.0, 1.0)] if l.use_temperature else None
        b.slider((kx0, y - sw, x + iw, y), "s:temp", T("temp"), l.temperature, 1000, 12000,
                 _set(l, "temperature"), "{:.0f} K", 50, track=track)
        y -= sw + 8 * s
    if sec("out", T("sec_out")):
        b.segmented((x, y - 24 * s, x + iw, y), "out",
                    [('HDRI', T("out_hdri")), ('AREA', T("out_area")), ('BOTH', T("out_both"))],
                    l.output, _set(l, "output"))
        y -= 24 * s + 6 * s
        th = 30 * s
        has = l.use_texture and l.texture is not None
        label = l.texture.name if has else T("no_texture")
        b.button((x, y - th, x + iw, y), "texture", label,
                 _call(bpy.ops.hdri_studio.light_popup, 'INVOKE_DEFAULT', section='TEXTURE'),
                 on=has, align='L', tip=T("texture"))
        y -= th + 6 * s
    # footer
    fw = iw / 3
    acts = [("dup", T("duplicate"), _call(bpy.ops.hdri_studio.duplicate_light)),
            ("del", T("delete"), _call(bpy.ops.hdri_studio.remove_light)),
            ("pre", T("save_preset"), _call(bpy.ops.hdri_studio.save_light_preset, 'INVOKE_DEFAULT'))]
    for i, (k, label, act) in enumerate(acts):
        b.button((x + i * fw + 1, y - 24 * s, x + (i + 1) * fw - 1, y), f"foot:{k}", label, act)
    y -= 24 * s + 8 * s
    return y


def _inspector(b, context, region):
    s = b.s
    st = context.scene.hdri_studio
    w = 272 * s
    default = (region.width - w - 12 * s, region.height - header_height() - 10 * s)
    x0, top = _panel_pos("insp", region, default)
    title = T("light")
    if 0 <= st.active_index < len(st.lights):
        title += " · " + st.lights[st.active_index].name
    folded = STATE["fold"].get("insp", False)
    th = 22 * s
    if folded:
        h = th
    else:
        h = top - _measure(region, _inspector_content, context, x0, top - th, w) + 0
    rect = (x0, top - h, x0 + w, top)
    ctop = b.panel_bg(rect, title, "insp", folded)
    if not folded:
        _inspector_content(b, context, x0, ctop, w)


# ---------------------------------------------------------------------------
# Bottom: layers + preview spheres
# ---------------------------------------------------------------------------

def _layers(b, context, region):
    s = b.s
    st = context.scene.hdri_studio
    balls_w = 200 * s
    x0, x1 = 12 * s, region.width - 12 * s - balls_w - 8 * s
    y0, y1 = 10 * s, 10 * s + strip_height()
    if x1 - x0 < 160 * s:
        x1 = region.width - 12 * s
        balls_w = 0
    b.panel_bg((x0, y0, x1, y1), None, "layers")
    size = int(9.5 * s)
    b.text(x0 + 10 * s, y1 - 16 * s, T("layers"), K.COL_SECTION, size)
    # header buttons: move layer, add
    bx = x1 - 8 * s
    for key, icon, act, tip in (
            ("add", K.icon_add, _call(bpy.ops.wm.call_menu, name="HDRISTUDIO_MT_add_light"), "+"),
            ("down", K.icon_tri('right'), _call(bpy.ops.hdri_studio.move_light, direction='DOWN'), ""),
            ("up", K.icon_tri('left'), _call(bpy.ops.hdri_studio.move_light, direction='UP'), "")):
        b.button((bx - 22 * s, y1 - 22 * s, bx, y1 - 5 * s), f"layer:{key}", "", act, icon=icon)
        bx -= 25 * s
    tip = T("layers_tip")
    tw = K.text_width(tip, size)
    if bx - tw - 10 * s > x0 + K.text_width(T("layers"), size) + 30 * s:
        b.text(bx - 8 * s, y1 - 16 * s, tip, K.COL_DIM, size, 'R')

    cw, ch, gap = 190 * s, 66 * s, 6 * s
    total = len(st.lights) * (cw + gap)
    view_w = x1 - x0 - 20 * s
    STATE["scroll"] = max(0.0, min(STATE["scroll"], max(0.0, total - view_w)))
    b.target((x0, y0, x1, y1 - 24 * s), "layers:strip", 'strip')
    cx = x0 + 10 * s - STATE["scroll"]
    cy1 = y1 - 26 * s
    cy0 = cy1 - ch
    for i, l in enumerate(st.lights):
        if cx + cw < x0 or cx > x1:
            cx += cw + gap
            continue
        if cx < x0 + 4 * s or cx + cw > x1 - 4 * s:   # partially visible: skip drawing
            cx += cw + gap
            continue
        on = i == st.active_index
        b.button((cx, cy0, cx + cw, cy1), f"card:{i}", "", _select(i), on=on, style='card')
        # thumbnail
        tx0, ty0 = cx + 6 * s, cy0 + 10 * s
        b.rect(tx0, ty0, tx0 + 54 * s, ty0 + 44 * s, K.COL_DARK)
        if b.p:
            K.shape_icon(l.shape, l.width, l.height, l.blend, outline=l.output == 'AREA')(
                b.p, tx0 + 27 * s, ty0 + 22 * s, 34 * s, K.COL_TEXT)
        nx = tx0 + 62 * s
        size_n = int(10.5 * s)
        b.text(nx, cy1 - 18 * s, K.fit_text(l.name, size_n, cx + cw - nx - 26 * s),
               K.COL_TEXT if l.enabled else K.COL_DIM, size_n)
        meta = f"{l.intensity:.1f}" + (f" · {l.temperature:.0f} K" if l.use_temperature else "")
        b.text(nx, cy1 - 33 * s, meta, K.COL_DIM, int(9.5 * s))
        badge = {'HDRI': "HDRI", 'AREA': "Area", 'BOTH': "HDRI + Area"}[l.output]
        bcol = {'HDRI': (0.2, 0.2, 0.22, 1.0), 'AREA': (0.12, 0.23, 0.16, 1.0),
                'BOTH': (0.14, 0.2, 0.29, 1.0)}[l.output]
        tcol = {'HDRI': (0.8, 0.8, 0.83, 1.0), 'AREA': K.COL_GREEN, 'BOTH': K.COL_SECTION}[l.output]
        bw_ = K.text_width(badge, int(9 * s)) + 12 * s
        b.rect(nx, cy0 + 8 * s, nx + bw_, cy0 + 22 * s, bcol)
        b.text(nx + 6 * s, cy0 + 11 * s, badge, tcol, int(9 * s))
        # eye toggle
        ex0, ey1 = cx + cw - 24 * s, cy1 - 4 * s
        er = (ex0, ey1 - 18 * s, ex0 + 20 * s, ey1)
        if b.p:
            K.icon_eye(b.p, (er[0] + er[2]) / 2, (er[1] + er[3]) / 2, 18 * s,
                       K.COL_TEXT if b.hovered(f"eye:{i}") else K.COL_DIM, l.enabled)
        b.target(er, f"eye:{i}", 'button', _toggle(l, "enabled"),
                 "Gizle / göster (H)" if language() == 'TR' else "Hide / show (H)")
        cx += cw + gap

    if balls_w:
        _balls(b, context, region, region.width - 12 * s - balls_w, y0, region.width - 12 * s, y1)


def _select(i):
    def run(ctx, ev):
        ctx.scene.hdri_studio.active_index = i
    return run


def _sphere_textures():
    pv = studio.preview
    if pv.get("chrome") is None or bpy.app.background:
        return None, None
    if _textures["version"] != pv["version"]:
        try:
            import gpu
            out = []
            for key in ("chrome", "diffuse"):
                arr = pv[key]
                h, w = arr.shape[:2]
                buf = gpu.types.Buffer('FLOAT', w * h * 4, arr.ravel().tolist())
                out.append(gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf))
            _textures["chrome"], _textures["diffuse"] = out
            _textures["version"] = pv["version"]
        except Exception as ex:
            print("BlendHDRi: preview texture failed:", ex)
            return None, None
    return _textures["chrome"], _textures["diffuse"]


def _balls(b, context, region, x0, y0, x1, y1):
    s = b.s
    b.panel_bg((x0, y0, x1, y1), None, "balls")
    d = 76 * s
    cy0 = y0 + 22 * s
    x0 += (x1 - x0 - (2 * d + 16 * s)) / 2 - 14 * s
    chrome, diffuse = _sphere_textures() if b.p else (None, None)
    for i, (tex, key) in enumerate(((chrome, "chrome"), (diffuse, "matte"))):
        bx = x0 + 14 * s + i * (d + 16 * s)
        if tex is not None and b.p:
            b.p.image(tex, bx, cy0, bx + d, cy0 + d)
        else:
            b.rect(bx, cy0, bx + d, cy0 + d, K.COL_DARK)
        b.text(bx + d / 2, y0 + 8 * s, T(key), K.COL_DIM, int(9.5 * s), 'C')


# ---------------------------------------------------------------------------
# Canvas decorations: grid and direction labels (image space)
# ---------------------------------------------------------------------------

def _canvas_grid(b, context, region):
    st = context.scene.hdri_studio
    if not st.show_grid or not b.p:
        return
    v2d = region.view2d
    s = b.s
    col = (1.0, 1.0, 1.0, 0.07)
    for i in range(1, 12):
        u = i / 12
        a = v2d.view_to_region(u, 0.0, clip=False)
        c = v2d.view_to_region(u, 1.0, clip=False)
        b.p.line([a, c], col, 1.0)
    for j in (1, 2, 4, 5):
        v = j / 6
        a = v2d.view_to_region(0.0, v, clip=False)
        c = v2d.view_to_region(1.0, v, clip=False)
        b.p.line([a, c], col, 1.0)
    a = v2d.view_to_region(0.0, 0.5, clip=False)
    c = v2d.view_to_region(1.0, 0.5, clip=False)
    b.p.line([a, c], (1.0, 1.0, 1.0, 0.18), 1.0)
    # direction labels along the top edge
    front = studio.front_lon(context.scene)
    size = int(9.5 * s)
    for key, off in (("front", 0.0), ("right", math.pi / 2), ("back", math.pi), ("left", -math.pi / 2)):
        u, _v = render.lonlat_to_uv(render.wrap_lon(front + off), 0.0)
        x, y = v2d.view_to_region(u, 1.0, clip=False)
        col = (0.94, 0.66, 0.35, 0.95) if key == "front" else (0.75, 0.75, 0.78, 0.8)
        b.text(x, y + 6 * s, T(key), col, size, 'C')


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def build_studio(context, region, painter=None):
    b = K.Builder(region, painter, STATE.get("hover"), STATE.get("active"))
    if painter is not None:
        _canvas_grid(b, context, region)
        b.flush()
    if not is_studio_space(context.space_data):
        return b
    _layers(b, context, region)
    b.flush()
    _inspector(b, context, region)
    b.flush()
    _palette(b, context, region)
    b.flush()
    _header(b, context, region)
    b.flush()
    return b


def draw_handler():
    context = bpy.context
    space = context.space_data
    if not canvas.is_canvas_space(space):
        return
    region = context.region
    try:
        canvas.draw_overlay()
        build_studio(context, region, K.Painter(region))
    except Exception:
        import traceback
        traceback.print_exc()


def register():
    global _draw_handle
    _draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
        draw_handler, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _textures.update({"version": -1, "chrome": None, "diffuse": None})
