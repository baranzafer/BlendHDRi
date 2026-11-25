# HDRLS Shot Manager
#
# Keeps a separate HDR Light Studio lighting project for every shot (frame
# range) of a Blender scene, stores all of them inside the .blend file and
# swaps the live HDR Light Studio session when the current frame enters
# another shot.  For final renders every shot can point to its own HDRI and
# a "Shots" world switches the image per frame.
#
# The HDR Light Studio connection add-on keeps its whole project as XML in
# scene["HDRLS Project Data"].  This add-on only copies that string in and
# out of per-shot slots and uses the connection's own Start / Stop operators;
# it never talks to HDR Light Studio directly.

bl_info = {
    "name": "HDRLS Shot Manager",
    "author": "BlendHDRi",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Properties > World > HDRLS Shots  |  3D View > N panel > HDRLS",
    "description": "Separate HDR Light Studio lighting for each shot / frame, saved in the .blend",
    "category": "Lighting",
}

import os
import re
import shutil
import time
import uuid
from xml.sax.saxutils import escape as _xml_escape

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

PROJECT_KEY = "HDRLS Project Data"
LIVE_WORLD = "HDRLS World"
LIVE_IMAGE = "HDRLS Dome Light"
RENDER_WORLD = "HDRLS Shots World"
RENDER_TAG = "hdrls_shots_world"
ENV_NODE = "HDRLS Shot Environment"

# Blender 4.5+ warns about "//" paths unless the property opts in.
_PATH_OPTS = {"PATH_SUPPORTS_BLEND_RELATIVE"} if bpy.app.version >= (4, 5, 0) else set()
HDRLS_SAVE_MODULES = {"Connection"}


# --------------------------------------------------------------------------
# Runtime state (not saved)
# --------------------------------------------------------------------------

_state = {
    "pending": None,   # scene name waiting for a frame check
    "due": 0.0,        # monotonic time of that check
    "job": None,       # running switch generator
    "status": "",      # text shown in the panel
}


def _set_status(text):
    _state["status"] = text
    _redraw()


def _redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in {"PROPERTIES", "VIEW_3D", "TIMELINE", "DOPESHEET_EDITOR"}:
                area.tag_redraw()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _settings(scene):
    return scene.hdrls_shots


def find_shot(st, uid):
    if not uid:
        return None
    for shot in st.shots:
        if shot.uid == uid:
            return shot
    return None


def shot_for_frame(st, frame):
    """The shot that owns `frame`: the last shot starting at or before it.
    Frames before the first shot belong to the first shot."""
    best = None
    first = None
    for shot in st.shots:
        if first is None or shot.frame < first.frame:
            first = shot
        if shot.frame <= frame and (best is None or shot.frame > best.frame):
            best = shot
    return best or first


def _is_playing():
    wm = bpy.context.window_manager
    if wm is None:
        return False
    return any(w.screen and w.screen.is_animation_playing for w in wm.windows)


def _is_rendering():
    try:
        return bpy.app.is_job_running("RENDER")
    except Exception:
        return False


def _abs(path):
    return os.path.normpath(bpy.path.abspath(path)) if path else ""


def _output_dir(st):
    """Absolute output folder, or "" when it cannot be resolved yet
    (relative path in a file that was never saved)."""
    d = st.output_dir or "//hdrls_shots/"
    if d.startswith("//") and not bpy.data.filepath:
        return ""
    d = _abs(d)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as exc:
        print("HDRLS Shots: cannot create", d, exc)
        return ""
    return d


def _safe_name(shot):
    name = bpy.path.clean_name(shot.name or "shot")
    return name or "shot"


def _live_image():
    world = bpy.data.worlds.get(LIVE_WORLD)
    if world and world.node_tree:
        for node in world.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexEnvironment" and node.image:
                return node.image
    return bpy.data.images.get(LIVE_IMAGE)


def _export_ext(xml):
    m = re.search(r"<export>.*?<file>(.*?)</file>", xml or "", re.S)
    if m:
        ext = os.path.splitext(m.group(1).strip())[1].lower()
        if ext in {".hdr", ".exr"}:
            return ext
    return ".hdr"


def patch_export_path(xml, path):
    """Point HDR Light Studio's Render output (<export><file>) to `path`."""
    pat = re.compile(r"(<export>.*?<file>)(.*?)(</file>)", re.S)
    if not pat.search(xml):
        return xml
    p = _xml_escape(path.replace("\\", "/"))
    return pat.sub(lambda m: m.group(1) + p + m.group(3), xml, count=1)


# --------------------------------------------------------------------------
# Talking to the HDR Light Studio connection add-on
# --------------------------------------------------------------------------

def hdrls_installed():
    return hasattr(bpy.types, "WM_OT_launch_hdrls")


def _override_kwargs():
    ctx = bpy.context
    win = ctx.window
    if win is None and ctx.window_manager and ctx.window_manager.windows:
        win = ctx.window_manager.windows[0]
    if win is None:
        return {}
    kw = {"window": win, "screen": win.screen}
    for area in win.screen.areas:
        if area.type == "PROPERTIES":
            kw["area"] = area
            for region in area.regions:
                if region.type == "WINDOW":
                    kw["region"] = region
            break
    return kw


def _hdrls_op(name):
    if not hasattr(bpy.types, "WM_OT_" + name):
        return None
    return getattr(bpy.ops.wm, name)


def hdrls_call(name):
    op = _hdrls_op(name)
    if op is None:
        return False
    try:
        with bpy.context.temp_override(**_override_kwargs()):
            op()
        return True
    except Exception as exc:
        print("HDRLS Shots: wm.%s failed: %s" % (name, exc))
        return False


def hdrls_running():
    """Best guess whether a live HDR Light Studio session is connected:
    the connection's Stop operator is only available while it runs."""
    op = _hdrls_op("stop_hdrls")
    if op is None:
        return False
    try:
        with bpy.context.temp_override(**_override_kwargs()):
            return bool(op.poll())
    except Exception:
        return False


def _hdrls_save_handlers():
    found = []
    for fn in bpy.app.handlers.save_pre:
        if getattr(fn, "__module__", "") in HDRLS_SAVE_MODULES:
            if all(fn is not f for f in found):
                found.append(fn)
    return found


def sync_from_hdrls():
    """Ask the connection to write the live project into the scene, the same
    way it does right before the .blend is saved."""
    handlers = _hdrls_save_handlers()
    if not handlers:
        return False
    fn = handlers[0]
    for args in ((bpy.data.filepath,), (), (None,)):
        try:
            fn(*args)
            return True
        except TypeError:
            continue
        except Exception as exc:
            print("HDRLS Shots: sync from HDR Light Studio failed:", exc)
            return False
    return False


# --------------------------------------------------------------------------
# Shot data <-> scene
# --------------------------------------------------------------------------

def capture_preview(scene, shot):
    """Copy the low resolution live HDRI of HDR Light Studio next to the
    .blend so the shot can be previewed / rendered even without a final
    HDRI."""
    st = _settings(scene)
    img = _live_image()
    if img is None:
        return False
    src = _abs(img.filepath)
    if not src or not os.path.isfile(src):
        return False
    out = _output_dir(st)
    if not out:
        return False
    dst = os.path.join(out, _safe_name(shot) + "_preview" + os.path.splitext(src)[1])
    try:
        shutil.copy2(src, dst)
    except OSError as exc:
        print("HDRLS Shots: preview copy failed:", exc)
        return False
    shot.preview_path = bpy.path.relpath(dst) if bpy.data.filepath else dst
    return True


def store_live(scene, sync=True):
    """Save the lighting currently loaded in HDR Light Studio into the shot
    that owns it."""
    st = _settings(scene)
    shot = find_shot(st, st.current_uid)
    if shot is None:
        return None
    if sync and st.sync_before_store:
        sync_from_hdrls()
    data = scene.get(PROJECT_KEY)
    if isinstance(data, str) and data:
        shot.data = data
    capture_preview(scene, shot)
    return shot


def load_shot(scene, shot):
    """Put the shot's project into scene["HDRLS Project Data"] and mark it
    as the live one."""
    st = _settings(scene)
    data = shot.data or scene.get(PROJECT_KEY, "")
    if not isinstance(data, str):
        data = ""
    if data and st.set_render_path:
        out = _output_dir(st)
        if out:
            path = os.path.join(out, _safe_name(shot) + _export_ext(data))
            data = patch_export_path(data, path)
            if not shot.image_path:
                shot.image_path = bpy.path.relpath(path) if bpy.data.filepath else path
    if data:
        shot.data = data
        scene[PROJECT_KEY] = data
    st.current_uid = shot.uid


def _switch_job(scene_name, uid):
    """Generator driven by a timer; yields the seconds to wait."""
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        return
    st = _settings(scene)
    target = find_shot(st, uid)
    if target is None or uid == st.current_uid:
        return
    restart = st.restart_live and hdrls_running()
    _set_status("Switching to %s..." % target.name)

    store_live(scene, sync=restart)
    if restart:
        hdrls_call("stop_hdrls")
        yield st.restart_wait
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return
        st = _settings(scene)
        target = find_shot(st, uid)
        if target is None:
            return
        # Stopping may have written the latest project once more.
        old = find_shot(st, st.current_uid)
        data = scene.get(PROJECT_KEY)
        if old is not None and isinstance(data, str) and data:
            old.data = data

    load_shot(scene, target)
    if restart:
        hdrls_call("launch_hdrls")
    _set_status("")
    update_render_world(scene)


def _tick():
    job = _state["job"]
    if job is not None:
        try:
            return max(0.01, float(next(job)))
        except StopIteration:
            _state["job"] = None
        except Exception as exc:
            _state["job"] = None
            _set_status("")
            print("HDRLS Shots: switch failed:", exc)
            import traceback
            traceback.print_exc()

    name = _state["pending"]
    if name is None:
        return None
    if time.monotonic() < _state["due"] or _is_playing() or _is_rendering():
        return 0.1
    _state["pending"] = None
    scene = bpy.data.scenes.get(name)
    if scene is None:
        return None
    st = _settings(scene)
    shot = shot_for_frame(st, scene.frame_current)
    if shot is not None and shot.uid != st.current_uid:
        _state["job"] = _switch_job(name, shot.uid)
    return 0.01


def request_check(scene, delay=None):
    st = _settings(scene)
    _state["pending"] = scene.name
    _state["due"] = time.monotonic() + (st.switch_delay if delay is None else delay)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.05)


def switch_now(scene, shot):
    if _state["job"] is not None:
        return False
    _state["pending"] = None
    _state["job"] = _switch_job(scene.name, shot.uid)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.01)
    return True


# --------------------------------------------------------------------------
# Render world: one Environment Texture whose image follows the shots
# --------------------------------------------------------------------------

def shot_render_file(shot):
    for p in (shot.image_path, shot.preview_path):
        ap = _abs(p)
        if ap and os.path.isfile(ap):
            return ap
    return ""


def ensure_render_world(scene):
    world = bpy.data.worlds.get(RENDER_WORLD)
    if world is None:
        world = bpy.data.worlds.new(RENDER_WORLD)
    world[RENDER_TAG] = True
    if world.node_tree is None:
        world.use_nodes = True  # Blender < 5.0
    nt = world.node_tree
    env = nt.nodes.get(ENV_NODE)
    if env is None:
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        out.location = (300, 0)
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.location = (100, 0)
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.name = ENV_NODE
        env.label = "Shot HDRI (set by HDRLS Shots)"
        env.location = (-250, 0)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return world


def refresh_render_images(scene, reload=True):
    st = _settings(scene)
    missing = []
    for shot in st.shots:
        path = shot_render_file(shot)
        if not path:
            shot.render_image = None
            missing.append(shot.name)
            continue
        img = bpy.data.images.load(path, check_existing=True)
        if reload:
            img.reload()
        shot.render_image = img
    return missing


def update_render_world(scene):
    world = scene.world
    if world is None or not world.get(RENDER_TAG) or world.node_tree is None:
        return
    node = world.node_tree.nodes.get(ENV_NODE)
    shot = shot_for_frame(_settings(scene), scene.frame_current)
    if node is not None and shot is not None and shot.render_image is not None:
        if node.image != shot.render_image:
            node.image = shot.render_image


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------

def _on_shot_frame(self, context):
    if context.scene is not None:
        request_check(context.scene)


class HDRLSShot(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Shot")
    uid: StringProperty(options={"HIDDEN"})
    frame: IntProperty(
        name="Start Frame",
        description="The shot lasts from this frame until the next shot starts",
        default=1, update=_on_shot_frame)
    data: StringProperty(
        name="Project Data", options={"HIDDEN"},
        description="HDR Light Studio project (XML) of this shot")
    image_path: StringProperty(
        name="Final HDRI", subtype="FILE_PATH", options=_PATH_OPTS,
        description="Full resolution HDRI used for rendering this shot. "
                    "HDR Light Studio's Render button writes here when "
                    "'Set HDRLS Render Path' is on")
    preview_path: StringProperty(
        name="Preview HDRI", subtype="FILE_PATH", options=_PATH_OPTS,
        description="Copy of the low resolution live HDRI, used when there is no final HDRI")
    render_image: PointerProperty(type=bpy.types.Image, options={"HIDDEN"})


def _on_auto_switch(self, context):
    if self.auto_switch and context.scene is not None:
        request_check(context.scene)


class HDRLSShotSettings(bpy.types.PropertyGroup):
    shots: CollectionProperty(type=HDRLSShot)
    active_index: IntProperty(default=0)
    current_uid: StringProperty(options={"HIDDEN"})
    auto_switch: BoolProperty(
        name="Auto Switch on Frame Change", default=True, update=_on_auto_switch,
        description="Load the shot's lighting into HDR Light Studio when the "
                    "current frame moves into another shot")
    restart_live: BoolProperty(
        name="Restart Live Session", default=True,
        description="Stop and start HDR Light Studio so it loads the new shot. "
                    "When off only the data stored in the .blend is swapped")
    sync_before_store: BoolProperty(
        name="Sync Before Storing", default=True,
        description="Ask the HDR Light Studio connection for the latest "
                    "project before saving it into a shot")
    switch_delay: FloatProperty(
        name="Switch Delay", default=0.6, min=0.0, max=10.0, unit="TIME_ABSOLUTE",
        description="Wait this long after the last frame change before switching (scrubbing)")
    restart_wait: FloatProperty(
        name="Restart Wait", default=2.0, min=0.0, max=30.0, unit="TIME_ABSOLUTE",
        description="Pause between Stop and Start of HDR Light Studio")
    set_render_path: BoolProperty(
        name="Set HDRLS Render Path", default=True,
        description="Point HDR Light Studio's Render output of every shot to "
                    "<output folder>/<shot name>.hdr so final HDRIs land in the right place")
    output_dir: StringProperty(
        name="Output Folder", subtype="DIR_PATH", default="//hdrls_shots/", options=_PATH_OPTS,
        description="Where shot HDRIs (final and preview) are written")


# --------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------

class HDRLSSHOTS_OT_add(bpy.types.Operator):
    bl_idname = "hdrls_shots.add"
    bl_label = "Add Shot"
    bl_description = ("Create a shot starting at the current frame with a copy "
                      "of the lighting that is live in HDR Light Studio now")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        st = _settings(scene)
        frame = scene.frame_current
        if any(s.frame == frame for s in st.shots):
            self.report({"WARNING"}, "A shot already starts on frame %d" % frame)
            return {"CANCELLED"}
        if _state["job"] is not None:
            self.report({"WARNING"}, "A shot switch is still running")
            return {"CANCELLED"}
        _state["pending"] = None

        store_live(scene)
        if st.sync_before_store and not st.shots:
            sync_from_hdrls()
        data = scene.get(PROJECT_KEY, "")
        if not isinstance(data, str) or not data:
            self.report({"WARNING"},
                        "No HDR Light Studio project in this scene yet. "
                        "Start HDR Light Studio once, then add the shot")
            return {"CANCELLED"}

        shot = st.shots.add()
        shot.uid = uuid.uuid4().hex[:12]
        shot.name = "F%03d" % frame
        shot["frame"] = frame
        shot.data = data
        st.active_index = len(st.shots) - 1
        # HDR Light Studio already shows this lighting: no restart needed.
        load_shot(scene, shot)
        capture_preview(scene, shot)
        update_render_world(scene)
        return {"FINISHED"}


class HDRLSSHOTS_OT_remove(bpy.types.Operator):
    bl_idname = "hdrls_shots.remove"
    bl_label = "Remove Shot"
    bl_description = "Delete the selected shot (its files on disk are kept)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        st = _settings(context.scene)
        return 0 <= st.active_index < len(st.shots)

    def execute(self, context):
        scene = context.scene
        st = _settings(scene)
        shot = st.shots[st.active_index]
        if shot.uid == st.current_uid:
            st.current_uid = ""
        st.shots.remove(st.active_index)
        st.active_index = min(st.active_index, len(st.shots) - 1)
        if st.shots and not st.current_uid:
            # HDR Light Studio keeps showing the removed shot's lighting;
            # hand it to the shot of the current frame on the next change.
            request_check(scene)
        return {"FINISHED"}


class HDRLSSHOTS_OT_store(bpy.types.Operator):
    bl_idname = "hdrls_shots.store"
    bl_label = "Save Lighting to Shot"
    bl_description = "Store the lighting that is live in HDR Light Studio into the current shot now"

    @classmethod
    def poll(cls, context):
        st = _settings(context.scene)
        return find_shot(st, st.current_uid) is not None

    def execute(self, context):
        shot = store_live(context.scene)
        self.report({"INFO"}, "Lighting saved to %s" % shot.name)
        return {"FINISHED"}


class HDRLSSHOTS_OT_goto(bpy.types.Operator):
    bl_idname = "hdrls_shots.goto"
    bl_label = "Go to Shot"
    bl_description = "Jump to the selected shot's start frame and load its lighting"

    index: IntProperty(default=-1)

    def execute(self, context):
        scene = context.scene
        st = _settings(scene)
        i = self.index if self.index >= 0 else st.active_index
        if not (0 <= i < len(st.shots)):
            return {"CANCELLED"}
        shot = st.shots[i]
        st.active_index = i
        scene.frame_set(shot.frame)
        if shot.uid != st.current_uid:
            if not switch_now(scene, shot):
                self.report({"WARNING"}, "A shot switch is still running")
        return {"FINISHED"}


class HDRLSSHOTS_OT_sync_frame(bpy.types.Operator):
    bl_idname = "hdrls_shots.sync_frame"
    bl_label = "Load Shot of Current Frame"
    bl_description = "Load the lighting of the shot that owns the current frame"

    def execute(self, context):
        scene = context.scene
        shot = shot_for_frame(_settings(scene), scene.frame_current)
        if shot is None:
            return {"CANCELLED"}
        if shot.uid == _settings(scene).current_uid:
            self.report({"INFO"}, "%s is already live" % shot.name)
            return {"FINISHED"}
        switch_now(scene, shot)
        return {"FINISHED"}


class HDRLSSHOTS_OT_reload_live(bpy.types.Operator):
    bl_idname = "hdrls_shots.reload_live"
    bl_label = "Reload into HDR Light Studio"
    bl_description = ("Stop HDR Light Studio and start it again with the "
                      "current shot's stored lighting (if it got out of sync)")

    @classmethod
    def poll(cls, context):
        st = _settings(context.scene)
        return hdrls_installed() and find_shot(st, st.current_uid) is not None

    def execute(self, context):
        scene = context.scene
        st = _settings(scene)
        shot = find_shot(st, st.current_uid)
        scene_name = scene.name
        uid = shot.uid

        def job():
            _set_status("Reloading %s..." % shot.name)
            hdrls_call("stop_hdrls")
            yield st.restart_wait
            sc = bpy.data.scenes.get(scene_name)
            if sc is None:
                return
            s = find_shot(_settings(sc), uid)
            if s is not None and s.data:
                sc[PROJECT_KEY] = s.data
            hdrls_call("launch_hdrls")
            _set_status("")

        if _state["job"] is not None:
            return {"CANCELLED"}
        _state["job"] = job()
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.01)
        return {"FINISHED"}


class HDRLSSHOTS_OT_capture_preview(bpy.types.Operator):
    bl_idname = "hdrls_shots.capture_preview"
    bl_label = "Capture Preview HDRI"
    bl_description = "Copy HDR Light Studio's current live HDRI as the preview of the current shot"

    @classmethod
    def poll(cls, context):
        st = _settings(context.scene)
        return find_shot(st, st.current_uid) is not None

    def execute(self, context):
        scene = context.scene
        st = _settings(scene)
        if not _output_dir(st):
            self.report({"ERROR"}, "Save the .blend first (the output folder is relative to it)")
            return {"CANCELLED"}
        if not capture_preview(scene, find_shot(st, st.current_uid)):
            self.report({"WARNING"}, "No live HDR Light Studio image found")
            return {"CANCELLED"}
        refresh_render_images(scene)
        update_render_world(scene)
        return {"FINISHED"}


class HDRLSSHOTS_OT_use_render_world(bpy.types.Operator):
    bl_idname = "hdrls_shots.use_render_world"
    bl_label = "Use Shots World"
    bl_description = ("Switch the scene to the 'HDRLS Shots World', whose HDRI "
                      "follows the shots frame by frame (for final renders)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        world = ensure_render_world(scene)
        missing = refresh_render_images(scene)
        scene.world = world
        update_render_world(scene)
        if missing:
            self.report({"WARNING"}, "No HDRI yet for: " + ", ".join(missing))
        return {"FINISHED"}


class HDRLSSHOTS_OT_use_live_world(bpy.types.Operator):
    bl_idname = "hdrls_shots.use_live_world"
    bl_label = "Use Live World"
    bl_description = "Switch the scene back to HDR Light Studio's live 'HDRLS World'"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy.data.worlds.get(LIVE_WORLD) is not None

    def execute(self, context):
        context.scene.world = bpy.data.worlds[LIVE_WORLD]
        request_check(context.scene, 0.0)
        return {"FINISHED"}


class HDRLSSHOTS_OT_refresh_images(bpy.types.Operator):
    bl_idname = "hdrls_shots.refresh_images"
    bl_label = "Reload Shot HDRIs"
    bl_description = "Reload every shot's HDRI from disk (after rendering new ones in HDR Light Studio)"

    def execute(self, context):
        missing = refresh_render_images(context.scene)
        update_render_world(context.scene)
        if missing:
            self.report({"WARNING"}, "No HDRI yet for: " + ", ".join(missing))
        return {"FINISHED"}


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

class HDRLSSHOTS_UL_shots(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        live = item.uid == data.current_uid
        row = layout.row(align=True)
        row.label(text="", icon="LIGHT_SUN" if live else "BLANK1")
        row.prop(item, "name", text="", emboss=False)
        sub = row.row(align=True)
        sub.alignment = "RIGHT"
        sub.label(text="F %d" % item.frame)
        has_final = bool(item.image_path) and os.path.isfile(_abs(item.image_path))
        has_prev = bool(item.preview_path) and os.path.isfile(_abs(item.preview_path))
        sub.label(text="", icon="IMAGE_RGB" if has_final else ("IMAGE_ALPHA" if has_prev else "IMAGE"))
        op = sub.operator("hdrls_shots.goto", text="", icon="PLAY", emboss=False)
        op.index = index


def draw_shots(layout, context):
    scene = context.scene
    st = _settings(scene)

    if not hdrls_installed():
        layout.label(text="HDR Light Studio connection not found", icon="ERROR")

    live = find_shot(st, st.current_uid)
    row = layout.row()
    if _state["status"]:
        row.label(text=_state["status"], icon="SORTTIME")
    elif live is not None:
        row.label(text="Live: %s" % live.name, icon="LIGHT_SUN")
    else:
        row.label(text="No shot live", icon="INFO")
    world = scene.world
    if world is not None and world.get(RENDER_TAG):
        row.label(text="Shots World", icon="WORLD")

    row = layout.row()
    row.template_list("HDRLSSHOTS_UL_shots", "", st, "shots", st, "active_index", rows=4)
    col = row.column(align=True)
    col.operator("hdrls_shots.add", text="", icon="ADD")
    col.operator("hdrls_shots.remove", text="", icon="REMOVE")
    col.separator()
    col.operator("hdrls_shots.store", text="", icon="FILE_TICK")
    col.operator("hdrls_shots.sync_frame", text="", icon="FILE_REFRESH")

    if 0 <= st.active_index < len(st.shots):
        shot = st.shots[st.active_index]
        box = layout.box()
        box.prop(shot, "name")
        box.prop(shot, "frame")
        box.prop(shot, "image_path")
        r = box.row()
        r.enabled = False
        r.prop(shot, "preview_path")

    row = layout.row(align=True)
    row.operator("hdrls_shots.store", icon="FILE_TICK")
    row.operator("hdrls_shots.capture_preview", text="Capture Preview", icon="IMAGE_DATA")

    col = layout.column(heading="Render", align=True)
    row = col.row(align=True)
    row.operator("hdrls_shots.use_render_world", icon="WORLD")
    row.operator("hdrls_shots.use_live_world", icon="LIGHT_SUN")
    col.operator("hdrls_shots.refresh_images", icon="FILE_REFRESH")


def draw_settings(layout, context):
    st = _settings(context.scene)
    layout.use_property_split = True
    layout.use_property_decorate = False
    col = layout.column()
    col.prop(st, "auto_switch")
    col.prop(st, "restart_live")
    col.prop(st, "sync_before_store")
    col.prop(st, "switch_delay")
    col.prop(st, "restart_wait")
    col.separator()
    col.prop(st, "set_render_path")
    col.prop(st, "output_dir")
    col.separator()
    col.operator("hdrls_shots.reload_live", icon="RECOVER_LAST")


class HDRLSSHOTS_PT_world(bpy.types.Panel):
    bl_label = "HDRLS Shots"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"

    def draw(self, context):
        draw_shots(self.layout, context)


class HDRLSSHOTS_PT_world_settings(bpy.types.Panel):
    bl_label = "Settings"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"
    bl_parent_id = "HDRLSSHOTS_PT_world"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_settings(self.layout, context)


class HDRLSSHOTS_PT_view3d(bpy.types.Panel):
    bl_label = "HDRLS Shots"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HDRLS"

    def draw(self, context):
        draw_shots(self.layout, context)


class HDRLSSHOTS_PT_view3d_settings(bpy.types.Panel):
    bl_label = "Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HDRLS"
    bl_parent_id = "HDRLSSHOTS_PT_view3d"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_settings(self.layout, context)


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

@persistent
def _on_frame_change_pre(scene, depsgraph=None):
    # Render world: pick the shot's HDRI before the frame is evaluated, so
    # animation renders get the right image on every frame.
    try:
        update_render_world(scene)
    except Exception as exc:
        print("HDRLS Shots:", exc)


@persistent
def _on_frame_change_post(scene, depsgraph=None):
    st = _settings(scene)
    if not st.auto_switch or not st.shots or _is_rendering():
        return
    world = scene.world
    if world is not None and world.get(RENDER_TAG):
        return  # render world in use: do not touch the live session
    shot = shot_for_frame(st, scene.frame_current)
    if shot is None:
        return
    if shot.uid != st.current_uid:
        request_check(scene)
    elif _state["pending"] == scene.name and _state["job"] is None:
        _state["pending"] = None  # scrubbed back into the live shot


@persistent
def _on_save_pre(*_args):
    # Runs after the HDR Light Studio save handler (see _order_handlers), so
    # scene["HDRLS Project Data"] already holds the latest live project.
    if _state["job"] is not None:
        return
    for scene in bpy.data.scenes:
        st = _settings(scene)
        shot = find_shot(st, st.current_uid)
        data = scene.get(PROJECT_KEY)
        if shot is not None and isinstance(data, str) and data:
            shot.data = data


@persistent
def _on_load_pre(*_args):
    _state["job"] = None
    _state["pending"] = None
    _state["status"] = ""


@persistent
def _on_load_post(*_args):
    _order_handlers()


def _order_handlers():
    """Keep our save handler after the HDR Light Studio one."""
    lst = bpy.app.handlers.save_pre
    while _on_save_pre in lst:
        lst.remove(_on_save_pre)
    lst.append(_on_save_pre)


_HANDLERS = (
    ("frame_change_pre", _on_frame_change_pre),
    ("frame_change_post", _on_frame_change_post),
    ("save_pre", _on_save_pre),
    ("load_pre", _on_load_pre),
    ("load_post", _on_load_post),
)


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

_CLASSES = (
    HDRLSShot,
    HDRLSShotSettings,
    HDRLSSHOTS_OT_add,
    HDRLSSHOTS_OT_remove,
    HDRLSSHOTS_OT_store,
    HDRLSSHOTS_OT_goto,
    HDRLSSHOTS_OT_sync_frame,
    HDRLSSHOTS_OT_reload_live,
    HDRLSSHOTS_OT_capture_preview,
    HDRLSSHOTS_OT_use_render_world,
    HDRLSSHOTS_OT_use_live_world,
    HDRLSSHOTS_OT_refresh_images,
    HDRLSSHOTS_UL_shots,
    HDRLSSHOTS_PT_world,
    HDRLSSHOTS_PT_world_settings,
    HDRLSSHOTS_PT_view3d,
    HDRLSSHOTS_PT_view3d_settings,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hdrls_shots = PointerProperty(type=HDRLSShotSettings)
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn not in lst:
            lst.append(fn)
    # The HDR Light Studio add-on may register after us.
    bpy.app.timers.register(_order_handlers, first_interval=1.0)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _state["job"] = None
    _state["pending"] = None
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        while fn in lst:
            lst.remove(fn)
    del bpy.types.Scene.hdrls_shots
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
