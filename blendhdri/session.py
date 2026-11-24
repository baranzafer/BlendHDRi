"""Robust bookkeeping for the add-on's modal tools.

Blender can kill a modal operator without calling any of our code: loading a
file, closing a window, reloading the add-on or an exception inside
``modal()``. A plain "running" flag then stays True forever, the toolbar
button looks pressed and pressing it only asks a dead operator to stop.

Each tool therefore owns a :class:`ModalSession`:

* ``start()`` hands out a unique token; only the operator holding the
  current token may act, so a stale instance quietly exits.
* the operator calls ``beat(token)`` on every event (a window timer makes
  sure events arrive even when the user is idle). ``running`` is only True
  while the heartbeat is fresh, so the UI recovers by itself.
* ``reset()`` clears everything (file load, add-on unregister, the
  "Reset Tools" button).
"""

import time
import traceback

import bpy
from bpy.app.handlers import persistent

STALE_AFTER = 2.5   # seconds without heartbeat => considered dead
TIMER_STEP = 0.25   # timer interval that drives the heartbeat


class ModalSession:
    def __init__(self, name):
        self.name = name
        self.reset()

    def reset(self):
        self.token = None
        self.last_beat = 0.0
        self.stop_requested = False

    # -- state -------------------------------------------------------------
    @property
    def running(self):
        return (self.token is not None
                and time.monotonic() - self.last_beat < STALE_AFTER)

    def start(self):
        self.token = object()
        self.last_beat = time.monotonic()
        self.stop_requested = False
        return self.token

    def owns(self, token):
        return token is not None and token is self.token

    def beat(self, token):
        if self.owns(token):
            self.last_beat = time.monotonic()

    def request_stop(self):
        self.stop_requested = True

    def end(self, token):
        if self.owns(token):
            self.reset()


SESSIONS = {}


def get(name):
    s = SESSIONS.get(name)
    if s is None:
        s = SESSIONS[name] = ModalSession(name)
    return s


def reset_all():
    for s in SESSIONS.values():
        s.reset()


class ModalToolMixin:
    """Shared modal plumbing: toggling, heartbeat timer, error safety.

    Subclasses set ``session_name`` and implement ``tool_start``,
    ``tool_modal`` and ``tool_cleanup``.
    """

    session_name = ""
    status_text = ""

    # -- toggle ----------------------------------------------------------------
    def invoke(self, context, event):
        sess = get(self.session_name)
        if sess.running:
            # Second click on the button: ask the live operator to finish.
            sess.request_stop()
            _tag_all()
            return {'CANCELLED'}
        sess.reset()  # drop any stale state left behind by a dead operator
        self._token = sess.start()
        self._timer = None
        try:
            if self.tool_start(context, event) is False:
                sess.end(self._token)
                return {'CANCELLED'}
            self._timer = context.window_manager.event_timer_add(TIMER_STEP, window=context.window)
            context.window_manager.modal_handler_add(self)
        except Exception:
            traceback.print_exc()
            self._shutdown(context)
            return {'CANCELLED'}
        self._set_status(context, self.status_text)
        _tag_all()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        sess = get(self.session_name)
        if not sess.owns(self._token):
            # Superseded or reset (file load, Reset button): leave quietly.
            self._shutdown(context, own=False)
            return {'CANCELLED'}
        sess.beat(self._token)
        if sess.stop_requested:
            return self._finish(context)
        try:
            result = self.tool_modal(context, event)
        except Exception as ex:
            traceback.print_exc()
            try:
                self.report({'WARNING'}, f"{self.bl_label} stopped: {ex}")
            except Exception:
                pass
            return self._finish(context, cancelled=True)
        if result == 'FINISH':
            return self._finish(context)
        return result

    def cancel(self, context):
        # Called by Blender when it removes the handler itself.
        self._shutdown(context)

    # -- helpers -----------------------------------------------------------
    def _finish(self, context, cancelled=False):
        self._shutdown(context)
        return {'CANCELLED'} if cancelled else {'FINISHED'}

    def _shutdown(self, context, own=True):
        try:
            self.tool_cleanup(context)
        except Exception:
            traceback.print_exc()
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                context.window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None
        if own:
            get(self.session_name).end(getattr(self, "_token", None))
            self._set_status(context, None)
        _tag_all()

    @staticmethod
    def _set_status(context, text):
        try:
            context.workspace.status_text_set(text)
        except Exception:
            pass

    # -- to override ---------------------------------------------------------
    def tool_start(self, context, event):
        return True

    def tool_modal(self, context, event):
        return {'PASS_THROUGH'}

    def tool_cleanup(self, context):
        pass


def region_alive(region):
    """True if a stored region reference is still valid."""
    if region is None:
        return False
    try:
        region.width  # noqa: B018 - raises ReferenceError when freed
        return True
    except (ReferenceError, AttributeError):
        return False


def _tag_all():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class HDRISTUDIO_OT_reset_tools(bpy.types.Operator):
    bl_idname = "hdri_studio.reset_tools"
    bl_label = "Reset Interactive Tools"
    bl_description = ("Stop Edit on Canvas / LightPaint and clear their state "
                      "(use if a button looks stuck)")

    def execute(self, context):
        reset_all()
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass
        _tag_all()
        return {'FINISHED'}


@persistent
def _on_load_pre(_dummy=None):
    # Loading a file removes every modal handler; forget their state.
    reset_all()


def register():
    bpy.utils.register_class(HDRISTUDIO_OT_reset_tools)
    bpy.app.handlers.load_pre.append(_on_load_pre)


def unregister():
    reset_all()
    if _on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load_pre)
    bpy.utils.unregister_class(HDRISTUDIO_OT_reset_tools)
