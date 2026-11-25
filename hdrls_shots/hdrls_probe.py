import bpy, addon_utils, traceback, os

out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

def short(v, n=400):
    try:
        if hasattr(v, "to_dict"):
            v = v.to_dict()
        elif hasattr(v, "to_list"):
            v = v.to_list()
    except Exception:
        pass
    s = repr(v)
    return s if len(s) <= n else s[:n] + " ... (toplam %d karakter)" % len(s)

KEYS = ("hdr", "hls", "lightmap", "lightstudio")
def match(s):
    s = str(s).lower()
    return any(k in s for k in KEYS)

def dump_rna(obj, prefix, depth=0):
    if obj is None or depth > 3:
        return
    for p in obj.bl_rna.properties:
        if p.identifier == "rna_type":
            continue
        try:
            v = getattr(obj, p.identifier)
        except Exception as e:
            log(prefix + p.identifier, "<okunamadi>", e)
            continue
        if p.type == "POINTER" and v is not None and not isinstance(v, bpy.types.ID):
            log(prefix + p.identifier, "(grup)")
            dump_rna(v, prefix + "    ", depth + 1)
        elif p.type == "COLLECTION":
            log(prefix + p.identifier, "(koleksiyon, %d oge)" % len(v))
            for i, item in enumerate(list(v)[:5]):
                log(prefix + "  [%d]" % i)
                dump_rna(item, prefix + "      ", depth + 1)
        else:
            log(prefix + p.identifier, "=", p.type, short(v))

def runtime_props(idblock, label):
    for p in idblock.bl_rna.properties:
        if getattr(p, "is_runtime", False):
            try:
                v = getattr(idblock, p.identifier)
            except Exception as e:
                log("  %s.%s <okunamadi> %s" % (label, p.identifier, e))
                continue
            log("  %s.%s  [%s]" % (label, p.identifier, p.type))
            if p.type == "POINTER" and v is not None and not isinstance(v, bpy.types.ID):
                dump_rna(v, "      ")
            elif p.type == "COLLECTION":
                log("      (koleksiyon, %d oge)" % len(v))
            else:
                log("      =", short(v))

def id_props(idblock, label):
    try:
        for k in idblock.keys():
            log("  %s[%r] (%s) = %s" % (label, k, type(idblock[k]).__name__, short(idblock[k])))
    except Exception as e:
        log("  %s id props okunamadi: %s" % (label, e))

def section(title, fn):
    log("")
    log("=" * 8, title, "=" * 8)
    try:
        fn()
    except Exception:
        log(traceback.format_exc())

def s_info():
    log("Blender:", bpy.app.version_string)
    log("Dosya:", os.path.basename(bpy.data.filepath) or "(kaydedilmemis)")
    log("Sahneler:", [s.name for s in bpy.data.scenes], " aktif:", bpy.context.scene.name)
    log("Aktif world:", bpy.context.scene.world.name if bpy.context.scene.world else None)

def s_addons():
    for m in addon_utils.modules():
        name = m.__name__
        info = getattr(m, "bl_info", {}) or {}
        if match(name) or match(info.get("name", "")):
            log(name, "| etkin:", addon_utils.check(name)[1], "| surum:", info.get("version"),
                "| ad:", info.get("name"))
            log("   dosya:", m.__file__)
            try:
                folder = os.path.dirname(m.__file__)
                log("   klasor icerigi:", sorted(os.listdir(folder)))
            except Exception as e:
                log("   klasor okunamadi:", e)

def s_scene():
    for sc in bpy.data.scenes:
        log("Scene:", sc.name)
        id_props(sc, "scene")
        runtime_props(sc, "scene")

def s_worlds():
    for w in bpy.data.worlds:
        log("World:", w.name, "| kullanici:", w.users, "| fake user:", w.use_fake_user)
        id_props(w, "world")
        runtime_props(w, "world")
        if w.node_tree:
            for n in w.node_tree.nodes:
                extra = ""
                if getattr(n, "node_tree", None):
                    extra = " group=" + n.node_tree.name
                if getattr(n, "image", None):
                    extra += " image=" + n.image.name
                log("   node:", n.name, "|", n.bl_idname, "| label:", n.label, extra)
            for l in w.node_tree.links:
                log("   link:", l.from_node.name, ".", l.from_socket.name, "->", l.to_node.name, ".", l.to_socket.name)
    for g in bpy.data.node_groups:
        if match(g.name):
            log("NodeGroup:", g.name, [n.bl_idname for n in g.nodes])

def s_images():
    for im in bpy.data.images:
        if match(im.name) or match(im.filepath):
            log("Image:", im.name, "| source:", im.source, "| packed:", bool(im.packed_file),
                "| boyut:", tuple(im.size), "| yol:", im.filepath)
            id_props(im, "image")

def s_texts():
    for t in bpy.data.texts:
        log("Text:", t.name, "| uzunluk:", len(t.as_string()))

def s_wm():
    wm = bpy.context.window_manager
    id_props(wm, "wm")
    runtime_props(wm, "wm")
    for ob in bpy.data.objects:
        for p in ob.bl_rna.properties:
            if getattr(p, "is_runtime", False) and match(p.identifier):
                log("Object prop:", ob.name, p.identifier)
        for k in ob.keys():
            if match(k):
                log("Object id prop:", ob.name, k, short(ob[k]))

def s_ops():
    for cat in dir(bpy.ops):
        try:
            mod = getattr(bpy.ops, cat)
            names = dir(mod)
        except Exception:
            continue
        for op in names:
            if match(cat) or match(op):
                desc = ""
                try:
                    desc = getattr(mod, op).get_rna_type().description
                except Exception:
                    pass
                log("bpy.ops.%s.%s  -  %s" % (cat, op, desc))

def s_types():
    for name in dir(bpy.types):
        if match(name):
            cls = getattr(bpy.types, name)
            log(name, "| bl_idname:", getattr(cls, "bl_idname", ""), "| modul:", getattr(cls, "__module__", ""))

def s_handlers():
    for hname in dir(bpy.app.handlers):
        if hname.startswith("_"):
            continue
        lst = getattr(bpy.app.handlers, hname)
        if isinstance(lst, list) and lst:
            for f in lst:
                log(hname, "->", getattr(f, "__module__", "?"), getattr(f, "__name__", repr(f)))

section("GENEL", s_info)
section("EKLENTILER", s_addons)
section("SAHNE OZELLIKLERI", s_scene)
section("WORLD / NODE", s_worlds)
section("GORUNTULER", s_images)
section("TEXT BLOKLARI", s_texts)
section("DIGER OZELLIKLER", s_wm)
section("OPERATORLER", s_ops)
section("SINIFLAR (panel/operator)", s_types)
section("HANDLER'LAR", s_handlers)

report = "\n".join(out)
txt = bpy.data.texts.get("HDRLS_Rapor") or bpy.data.texts.new("HDRLS_Rapor")
txt.clear()
txt.write(report)
print(report)

# Raporu acik olan Text Editor'de goster
for area in bpy.context.screen.areas:
    if area.type == "TEXT_EDITOR":
        area.spaces.active.text = txt
        break
