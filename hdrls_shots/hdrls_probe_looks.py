# HDRLS Light Looks probe
#
# Run in Blender's Text Editor (Run Script). It only reads; the result goes
# to a text block named "HDRLS_Rapor_Looks".
#
# It lists what the HDR Light Studio connection add-on can do from Python
# (modules, functions, command names) and how Light Looks are stored in
# scene["HDRLS Project Data"], to find out whether a Look can be activated
# without restarting HDR Light Studio.

import bpy, sys, os, re, inspect, traceback
import xml.etree.ElementTree as ET

out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

def section(title, fn):
    log("")
    log("=" * 8, title, "=" * 8)
    try:
        fn()
    except Exception:
        log(traceback.format_exc())

KEYWORDS = re.compile(r"look|command|cmd|send|queue|project|activ|select|socket|port|def |class ", re.I)
ADDON_MODULES = ("Connection", "CommandQueue", "HdrLightStudio", "HdrlsHelper", "HdrlsParams",
                 "HdrlsSceneDetails", "Operators", "HdrlsUI", "HdrlsErrorHandling", "config")

def _addon_dir():
    import addon_utils
    for m in addon_utils.modules():
        if m.__name__ == "HDRLightStudioConnection":
            return os.path.dirname(m.__file__)
    return ""

def s_files():
    d = _addon_dir()
    if not d:
        log("HDRLightStudioConnection eklentisi bulunamadi")
        return
    log("Klasor:", d)
    for root, dirs, files in os.walk(d):
        if "__pycache__" in root or "icons" in root:
            continue
        for f in files:
            p = os.path.join(root, f)
            log("  ", os.path.relpath(p, d), os.path.getsize(p), "bayt")

def s_modules():
    names = sorted(n for n in sys.modules
                   if not n.startswith(("bl_", "bpy", "_bpy")) and (n in ADDON_MODULES or "lightmap" in n.lower() or "hdrls" in n.lower()
                   or n.startswith("HDRLightStudioConnection")))
    for n in names:
        mod = sys.modules[n]
        log("")
        log("MODUL:", n, "|", getattr(mod, "__file__", ""))
        for attr in sorted(dir(mod)):
            if attr.startswith("__"):
                continue
            try:
                obj = getattr(mod, attr)
            except Exception:
                continue
            if inspect.ismodule(obj):
                continue
            if inspect.isclass(obj):
                if getattr(obj, "__module__", "") != n:
                    continue
                log("  class", attr)
                for ma in sorted(vars(obj)):
                    if ma.startswith("__") and ma != "__init__":
                        continue
                    mv = getattr(obj, ma, None)
                    if callable(mv):
                        try:
                            sig = str(inspect.signature(mv))
                        except Exception:
                            sig = "(?)"
                        log("      def", ma + sig)
                    else:
                        log("      attr", ma, "=", repr(mv)[:80])
            elif callable(obj):
                try:
                    sig = str(inspect.signature(obj))
                except Exception:
                    sig = "(?)"
                doc = (getattr(obj, "__doc__", "") or "").strip().splitlines()
                log("  def", attr + sig, ("  # " + doc[0][:80]) if doc else "")
            else:
                r = repr(obj)
                log("  var", attr, "=", r[:100])

def s_grep():
    d = _addon_dir()
    if not d:
        return
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py"):
            continue
        try:
            lines = open(os.path.join(d, f), encoding="utf-8", errors="replace").read().splitlines()
        except Exception as e:
            log(f, "okunamadi", e)
            continue
        hits = [(i + 1, l.rstrip()) for i, l in enumerate(lines) if KEYWORDS.search(l)]
        log("")
        log("DOSYA:", f, "(%d satir, %d eslesme)" % (len(lines), len(hits)))
        for no, l in hits[:250]:
            log("  %5d: %s" % (no, l[:160]))
        if len(hits) > 250:
            log("  ... (%d eslesme daha)" % (len(hits) - 250))

def _tree(el, depth, maxdepth, counts_line):
    children = list(el)
    counts = {}
    for c in children:
        counts[c.tag] = counts.get(c.tag, 0) + 1
    text = (el.text or "").strip()
    log("  " * depth + "<%s>" % el.tag
        + (" attrs=%s" % dict(el.attrib) if el.attrib else "")
        + (" = %r" % text[:60] if text and not children else "")
        + (" {%s}" % ", ".join("%s x%d" % kv for kv in counts.items()) if children else ""))
    if depth >= maxdepth:
        return
    seen = set()
    for c in children:
        # show each child tag once (first example) to keep it short
        if c.tag in seen:
            continue
        seen.add(c.tag)
        _tree(c, depth + 1, maxdepth, counts_line)

def s_xml():
    sc = None
    for s in bpy.data.scenes:
        if isinstance(s.get("HDRLS Project Data"), str):
            sc = s
            break
    if sc is None:
        log("HDRLS Project Data bulunamadi")
        return
    xml = sc["HDRLS Project Data"]
    log("Sahne:", sc.name, "| uzunluk:", len(xml))
    root = ET.fromstring(xml)
    log("--- Yapi (her etiketten bir ornek, 4 seviye) ---")
    _tree(root, 0, 4, None)
    log("--- 'look' gecen etiketler ---")
    for el in root.iter():
        if "look" in el.tag.lower():
            kids = [c.tag for c in el][:12]
            text = (el.text or "").strip()
            log("  <%s> attrs=%s text=%r cocuklar=%s" % (el.tag, dict(el.attrib), text[:60], kids))
    log("--- 'look' gecen satirlar (ilk 60) ---")
    n = 0
    for i, line in enumerate(xml.splitlines()):
        if "look" in line.lower():
            log("  %5d: %s" % (i + 1, line.strip()[:160]))
            n += 1
            if n >= 60:
                break

section("EKLENTI DOSYALARI", s_files)
section("MODULLER VE FONKSIYONLAR", s_modules)
section("KAYNAK KODDA ANAHTAR SATIRLAR", s_grep)
section("PROJE XML / LIGHT LOOKS", s_xml)

report = "\n".join(out)
txt = bpy.data.texts.get("HDRLS_Rapor_Looks") or bpy.data.texts.new("HDRLS_Rapor_Looks")
txt.clear()
txt.write(report)
print("HDRLS_Rapor_Looks:", len(out), "satir")
for area in bpy.context.screen.areas:
    if area.type == "TEXT_EDITOR":
        area.spaces.active.text = txt
        break
