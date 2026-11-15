# -*- coding: utf-8 -*-
"""Number Sequencer - the System Selector tab.

Lists every duct or pipe system in the active view in a table you put in
order. That order is the numbering order: each system after the first starts
at its open end nearest where the last one finished. Accessories are walked
through but never numbered or selected; equipment and terminals never are
either.

The table: click / Ctrl+click / Shift+click to select systems (they are
selected in Revit too), Up / Down (arrow keys or the buttons) to step
through them, Shift+Up / Shift+Down or a drag to move them.

The view: Isolate (only the families ticked in the tree, with their tags,
and coloured), Colour (each system its swatch colour, the start heavy in
magenta), Isolate in 3D (opens the chosen 3D view - the default 3D view
unless another is picked - isolated and coloured the same way, and kept in
step with the table), Remove from sequence (elements selected in the view
are hidden and left out). Colours come off on Clear, on Run and on closing;
every isolate is reset on closing. Changing view lights Refresh.

Groups: systems grouped (from elements selected in the view, or rows
selected in the table) are numbered as one block and drawn in one hue, dark
to light in their order. Reorder in group puts a group in nearest-next order;
Auto order moves groups as one. Dragging a member out of its group takes it
out; dropping a system between two members puts it in.

The sequencing options on the right of the window (parameter, format, start
number, direction, tags) are shared with the Sequencer tab.
"""

import nsq_clr  # noqa: F401  (must stay the first import)

import traceback

from System import Action, AppDomain
from System.Windows import (Thickness, CornerRadius, FontWeights, GridLength, GridUnitType,
                            VerticalAlignment, HorizontalAlignment, TextTrimming,
                            FrameworkElement, DragDrop, DragDropEffects, DataObject)
from System.Windows.Controls import (Grid, Border, TextBlock, CheckBox, ColumnDefinition,
                                     TextBox, ComboBox, ComboBoxItem, ContextMenu, MenuItem)
from System.Windows.Input import Cursors, MouseButtonState, Keyboard, ModifierKeys, Key
from System.Windows.Shapes import Path, Shape
from System.Windows.Media import Geometry, VisualTreeHelper

import nsq_core as core
import nsq_revit as rv
import nsq_tree
import nsq_ui as ui

DRAG_FORMAT = u"RevoBIM.NumberSequencer.SystemRow"
DRAG_MIN = 6
AUTOSCROLL = 26
GRIP = u"M0,0 L8,0 M0,4 L8,4 M0,8 L8,8"
CLEAR = u"#00000000"

# the window that Revit's selection / view events talk to, and the once-only hook flag
TARGET_KEY = u"RevoBIM.NumberSequencer.selector." + core.__version__
HOOK_KEY = u"RevoBIM.NumberSequencer.hooks." + core.__version__

# windows closing: held until their tidy-up job has run - a window nobody
# references can be collected, and its ExternalEvent with it, before Revit runs it
_CLOSING = []


def run_when_idle(uiapp, fn, log):
    """Run fn(uiapp) once in Revit's Idling event - when the ExternalEvent
    is refused. Idling is an API context, so it may change the model."""
    def handler(sender, e):
        try:
            uiapp.Idling -= handler
        except Exception:
            pass
        try:
            fn(uiapp)
        except Exception:
            log.add(u"idle job failed: " + traceback.format_exc())
    try:
        uiapp.Idling += handler
        return True
    except Exception:
        log.add(u"could not wait for idle: " + traceback.format_exc())
        return False


# the sub-steps of step 2 (Systems), shown in small red squares on their buttons
STEP_ISO3D = u"2.1"
STEP_GROUP = u"2.2"
STEP_PICK = u"2.3"
STEP_AUTO = u"2.4"

# key, heading, width, star, min width - header and rows share this list
COLUMNS = [
    (u"grip", u"", 18, False, 0),
    (u"num", u"#", 30, False, 0),
    (u"on", u"", 24, False, 0),
    (u"swatch", u"", 24, False, 0),
    (u"grp", u"Group", 64, False, 0),
    (u"name", u"System name", 3, True, 110),
    (u"type", u"System type", 2, True, 80),
    (u"abbr", u"Abbrev.", 1, True, 46),
    (u"cls", u"Classification", 2, True, 80),
    (u"count", u"Elements", 70, False, 0),
    (u"range", u"Numbers", 100, False, 0),
]


# ============================================================
# Revit events - hooked once per Revit session
# ============================================================

def _target():
    try:
        return AppDomain.CurrentDomain.GetData(TARGET_KEY)
    except Exception:
        return None


def _on_selection_changed(sender, e):
    try:
        t = _target()
        if t is None:
            return
        ids = [rv.eid_value(i) for i in e.GetSelectedElements()]
        t.revit_selection_changed(ids, rv.doc_key(e.GetDocument()))
    except Exception:
        pass


def _on_view_activated(sender, e):
    try:
        t = _target()
        if t is None:
            return
        view = e.CurrentActiveView
        t.view_changed(rv.doc_key(e.Document), rv.eid_value(view.Id) if view is not None else None)
    except Exception:
        pass


def install_hooks(uiapp, log):
    """Hook Revit's SelectionChanged (2023+) and ViewActivated, pointing at
    whichever window is the target. The handlers hooked are kept in the
    AppDomain: anything an earlier engine (a pyRevit reload, a window that
    could not unhook) left behind is unhooked first, so handlers never pile up.
    These are module functions - the same object every time - so -= finds them."""
    try:
        old = AppDomain.CurrentDomain.GetData(HOOK_KEY)
    except Exception:
        old = None
    if old is not None:
        remove_hooks(uiapp, old, log)
    done = []
    try:
        uiapp.SelectionChanged += _on_selection_changed
        done.append((u"SelectionChanged", _on_selection_changed))
    except Exception:
        log.add(u"SelectionChanged not available - Remove from sequence reads the selection when pressed")
    try:
        uiapp.ViewActivated += _on_view_activated
        done.append((u"ViewActivated", _on_view_activated))
    except Exception:
        log.add(u"ViewActivated not available - the view is checked when the window is activated")
    try:
        AppDomain.CurrentDomain.SetData(HOOK_KEY, done)
    except Exception:
        pass
    log.add(u"hooked: " + (u", ".join([n for n, f in done]) or u"nothing"))
    return done


def remove_hooks(uiapp, hooks, log):
    for name, fn in list(hooks or []):
        try:
            if name == u"SelectionChanged":
                uiapp.SelectionChanged -= fn
            elif name == u"ViewActivated":
                uiapp.ViewActivated -= fn
        except Exception:
            log.add(u"could not unhook " + name)
    try:
        if AppDomain.CurrentDomain.GetData(HOOK_KEY) is hooks:
            AppDomain.CurrentDomain.SetData(HOOK_KEY, None)
    except Exception:
        pass


def selection_hooked(hooks):
    return any([n == u"SelectionChanged" for n, f in (hooks or [])])


def _new_state():
    return {u"loaded": False, u"data": None, u"systems": [], u"cur": None, u"picked": set(),
            u"anchor": None, u"left_out": set(), u"order": [], u"spans": [], u"starts": [],
            u"type_of": {}, u"colour_n": 0, u"tree": None, u"gone": [], u"chain": [],
            u"groups": {}, u"hues": {}, u"gid_n": 0, u"shade": {}, u"reorder_due": False}


class SelectorTab(object):

    def __init__(self, w):
        self.w = w
        self.ctl = w.ctl
        self.kind = w.settings.get(u"sel_kind") if w.settings.get(u"sel_kind") in core.KINDS else u"duct"
        self.skipped = core.skip_keys_from(w.settings.get(u"sel_skip"))
        self.state = dict((k, _new_state()) for k in core.KINDS)
        for k in core.KINDS:
            self.state[k][u"tree"] = nsq_tree.FamilyTree(
                self.ctl(u"SelTreeHost"), self.ctl(u"SelCountText"), self.ctl(u"SelSearchBox"),
                w._guard, lambda: self.w.mode, self.skipped, self._tree_changed, self._select_keys)
        # (document, view id value) -> (view ElementId, {element id value: (ElementId, overrides before)})
        self.snapshots = {}
        # (document, view id value) -> view ElementId, every view this tool isolated
        self.iso_views = {}
        # (document, view id value) -> view ElementId, views where Remove hid elements
        self.hide_views = {}
        # (document, view id value) -> (view ElementId, [ElementId]) still carrying the
        # tool's colouring from a session that never put it back
        self.leftovers = {}
        # (document, view id value) -> (view ElementId, section box before Isolate 3D fitted it)
        self.boxes = {}
        # (document, view id value) of the view the systems were last read from, either kind
        self.view_key = None
        self.iso_on = False
        self.col_on = False
        self.col_auto = False
        self.stale = False
        self.user_sel = []
        self.view_sel = []      # every element the user picked in the view (accessories too), for Group
        self.own_sel = None
        self.sync_wanted = False
        self.sync_queued = False
        self.last_col = None
        self.last_iso = None
        self.last_key = None   # the last system moved, for Move to next
        # Isolate in 3D: (document, view id value) of the 3D view it is on, else None
        self.iso3d = None
        self.iso3d_id = None
        self.iso3d_name = u""
        self.iso3d_busy = False
        self.col3d = False
        self.last_iso3d = None
        self.last_col3d = None
        self.filling_3d = False
        self.drag = None
        self.drag_set = set()
        self.dragged = False
        self.skip_up = False
        self.rows = []
        self.range_cells = []
        self.ctl(u"SelDuctTab" if self.kind == u"duct" else u"SelPipeTab").IsChecked = True
        self._build_header()
        self._build_menu()
        self.fill_3d_combo([])
        self._wire()
        self._refresh_view_buttons()
        try:
            AppDomain.CurrentDomain.SetData(TARGET_KEY, self)
        except Exception:
            pass
        self.hooks = install_hooks(w.uiapp, w.log)

    # ---------------------------------------------------- wiring
    def _wire(self):
        g = self.w._guard
        c = self.ctl
        c(u"SelDuctTab").Checked += g(self._on_kind)
        c(u"SelPipeTab").Checked += g(self._on_kind)
        c(u"SelRefreshBtn").Click += g(self._on_refresh)
        c(u"SelIsolateBtn").Click += g(self._on_isolate)
        c(u"SelColourBtn").Click += g(self._on_colour)
        c(u"SelIso3DBtn").Click += g(self._on_iso3d)
        c(u"Sel3DCombo").SelectionChanged += g(self._on_3d_choice)
        c(u"SelRemoveBtn").Click += g(self._on_remove)
        c(u"SelRestoreBtn").Click += g(self._on_restore)
        c(u"SelUpBtn").Click += g(self._on_up)
        c(u"SelDownBtn").Click += g(self._on_down)
        c(u"SelTopBtn").Click += g(self._on_top)
        c(u"SelBottomBtn").Click += g(self._on_bottom)
        c(u"SelAutoOrderBtn").Click += g(self._on_auto_order)
        c(u"SelAllOnBtn").Click += g(self._on_all_on)
        c(u"SelAllOffBtn").Click += g(self._on_all_off)
        c(u"SelPickStartBtn").Click += g(self._on_pick_start_btn)
        c(u"SelAutoBtn").Click += g(self._on_auto_btn)
        c(u"SelGroupBtn").Click += g(self._on_group)
        c(u"SelUngroupBtn").Click += g(self._on_ungroup)
        c(u"SelGroupOrderBtn").Click += g(self._on_group_order)
        c(u"SelSearchBox").TextChanged += g(self._on_search)
        c(u"SelExpandAllBtn").Click += g(self._on_expand_all)
        c(u"SelCollapseAllBtn").Click += g(self._on_collapse_all)
        c(u"SelTickAllBtn").Click += g(self._on_tick_all)
        c(u"SelUntickAllBtn").Click += g(self._on_untick_all)
        c(u"SelScroll").PreviewDragOver += g(self._on_scroll_drag)
        c(u"SelScroll").Drop += g(self._on_scroll_drop)
        self.w.win.PreviewKeyDown += g(self._on_key)

    def st(self):
        return self.state[self.kind]

    def _systems(self):
        return self.st()[u"systems"]

    def _index(self, key):
        for i, sd in enumerate(self._systems()):
            if sd[u"key"] == key:
                return i
        return None

    def _picked_idx(self):
        st = self.st()
        idx = set([i for i, sd in enumerate(st[u"systems"]) if sd[u"key"] in st[u"picked"]])
        if not idx and self._index(st[u"cur"]) is not None:
            idx.add(self._index(st[u"cur"]))
        return idx

    def _cur_index(self):
        i = self._index(self.st()[u"cur"])
        return i

    # ---------------------------------------------------- the active tab's numbering source
    def include(self, key):
        st = self.st()
        d = st[u"data"]
        if d is None:
            return False
        return core.sel_include(key, d[u"passthrough"], st[u"left_out"], st[u"type_of"], self.skipped)

    def on_systems(self):
        return [sd for sd in self.st()[u"systems"] if sd[u"on"]]

    def source(self):
        st = self.st()
        d = st[u"data"] or {}
        keys = [k for sd in self.on_systems() for k in sd[u"num"]]
        return {u"order": st[u"order"], u"include": self.include, u"idmap": d.get(u"idmap", {}),
                u"labels": d.get(u"labels", {}), u"hostcat": d.get(u"hostcat", {}),
                u"storages": d.get(u"storages", {}), u"per_elem": d.get(u"per_elem", {}),
                u"keys": keys, u"total": len(keys), u"has": bool(keys),
                u"systems": len(self.on_systems()), u"kind": self.kind, u"plans_only": True,
                u"view_type": d.get(u"view_type", u""), u"verb": u"Run", u"after": self.after_run,
                u"needs_start": True, u"started": self._started(),
                u"empty_hint": u"Tick a system to list its parameters"}

    # ---------------------------------------------------- reading
    def activate(self):
        st = self.st()
        if not st[u"loaded"]:
            self.refresh()
        self._check_view()
        self.recompute()

    def _read_job(self, kind):
        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            view = doc.ActiveView
            key = (rv.doc_key(doc), rv.eid_value(view.Id))
            if key in self.iso_views:
                # the tool's isolate stops the view's collector seeing the
                # unticked systems: refreshing now would drop them. Elements
                # Remove hid are meant to go, so a refresh after Remove is fine.
                return {u"kind": kind, u"isolated": True}
            data = rv.read_selector(doc, view, kind, self.w.log)
            data[u"isolated"] = rv.is_isolated(view)
            data[u"tags"] = rv.tag_choices(doc)
            data[u"views3d"] = rv.views_3d(doc)
            snap = self.snapshots.get(key, (None, {}))[1]
            data[u"leftover"] = rv.tool_coloured(
                view, [i for i in data[u"idmap"].values() if rv.eid_value(i) not in snap])
            data[u"kind"] = kind
            data[u"doc_key"] = rv.doc_key(doc)
            return data
        return job

    def read_now(self, uiapp):
        """At launch we are inside the command, so read directly."""
        try:
            self._loaded(self._read_job(self.kind)(uiapp), None)
        except Exception:
            self.w.log.add(u"selector read failed: " + traceback.format_exc())

    def refresh(self):
        label = core.KINDS[self.kind][u"label"].lower()
        self.w._queue(u"read " + self.kind, self._read_job(self.kind), self._loaded,
                      u"Reading the {0} in the active view".format(label))

    def _on_refresh(self, sender, e):
        self.refresh()

    def _loaded(self, res, err):
        if err or res is None:
            self.w._status(u"Could not read the systems - see debug")
            return
        if u"systems" not in res:
            self.w._status(u"This view is isolated by the tool - reset its isolate, then Refresh "
                           u"(the isolate hides the unticked systems)")
            return
        st = self.state[res[u"kind"]]
        new_key = (res[u"doc_key"], rv.eid_value(res[u"view_id"]))
        same_view = self.view_key is None or self.view_key == new_key
        self.view_key = new_key
        if self.iso3d is not None and self.iso3d[0] != res[u"doc_key"]:
            # another project: its 3D view keeps the isolate until Reset or close
            self._iso3d_off()
        self.fill_3d_combo(res.get(u"views3d") or [])
        if res.get(u"leftover"):
            self.leftovers[new_key] = (res[u"view_id"], list(res[u"leftover"]))
        else:
            self.leftovers.pop(new_key, None)
        # the same systems in another view keep their order, ticks and colours
        old = st[u"systems"]
        systems = core.merge_systems(old, res[u"systems"]) if old else res[u"systems"]
        need = [sd for sd in systems if not sd.get(u"colour")]
        if need:
            # never a colour already in use (a lone system moved off a group's hue took one)
            used = set([sd.get(u"colour") for sd in systems if sd.get(u"colour")])
            pal = core.distinct_colours(st[u"colour_n"] + len(need) + len(used))
            for sd in need:
                while pal[st[u"colour_n"]] in used:
                    st[u"colour_n"] += 1
                sd[u"colour"] = pal[st[u"colour_n"]]
                used.add(sd[u"colour"])
                st[u"colour_n"] += 1
        st[u"data"] = res
        st[u"systems"] = systems
        st[u"loaded"] = True
        st[u"type_of"] = dict((r[0], core.type_key(r[1], r[2], r[3])) for r in res[u"rows"])
        st[u"left_out"] = set([k for k in st[u"left_out"] if k in res[u"nodes"]])
        st[u"gone"] = []   # hidden systems are simply not read; the rest drop out in recompute
        self.last_key = None
        keys = set([sd[u"key"] for sd in systems])
        st[u"picked"] = set([k for k in st[u"picked"] if k in keys])
        if st[u"cur"] not in keys:
            st[u"cur"] = systems[0][u"key"] if systems else None
        st[u"tree"].set_rows([], 0, reset=not old)
        if not same_view:
            # a new view starts plain: the old view keeps its isolate and colours
            # until the window closes or Clear is pressed
            self.iso_on = False
            self.col_on = False
            self.col_auto = False
            self.last_iso = None
            self.last_col = None
        self.stale = False
        self.w.tags = res[u"tags"]
        if res[u"kind"] == self.kind:
            self.recompute()
        self._refresh_view_buttons()
        self.w._status(u"{0} {1} in {2} ({3}){4}{5}".format(
            len(systems), core.KINDS[res[u"kind"]][u"label"].lower(), res[u"view_name"], res[u"view_type"],
            u" - read from an isolated view, only what it shows" if res.get(u"isolated") else u"",
            u" - {0} elements still coloured from before: Clear colours takes it off".format(
                len(res[u"leftover"])) if res.get(u"leftover") else u""))

    # ---------------------------------------------------- the view changing under the window
    def _kind_view_key(self):
        d = self.st()[u"data"]
        return None if d is None else (d.get(u"doc_key"), rv.eid_value(d[u"view_id"]))

    def view_changed(self, doc_key, view_value):
        if self.view_key is None or view_value is None:
            return
        here = (doc_key, view_value)
        # stale when Revit moved on, or this kind was read in another view -
        # never in the 3D view Isolate in 3D opened: it shows these systems
        stale = here != self.view_key or (self._kind_view_key() not in (None, here))
        if self.iso3d is not None and here == self.iso3d:
            stale = False
        if self.iso3d is not None and here == self.view_key and (self.iso_on or self.col_on):
            # back from the 3D view: catch up on changes made while it was active
            self._request_sync()
        if stale != self.stale:
            self.stale = stale
            self._refresh_view_buttons()
            if stale:
                self.w._status(u"The active view changed - Refresh from view to read its systems")

    def _check_view(self):
        """Fallback when ViewActivated is not hooked: compare on activation."""
        try:
            uidoc = self.w.uiapp.ActiveUIDocument
            self.view_changed(rv.doc_key(uidoc.Document), rv.eid_value(uidoc.ActiveView.Id))
        except Exception:
            pass

    def revit_selection_changed(self, id_values, doc_key):
        d = self.st()[u"data"]
        if d is None or doc_key != d.get(u"doc_key"):
            return
        own = self.own_sel is not None and set(id_values) == set(self.own_sel)
        keys = [k for sd in self.on_systems() for k in sd[u"num"] if self.include(k)]
        self.user_sel = core.user_selection(id_values, self.own_sel, keys)
        self.view_sel = [] if own else list(id_values)
        if id_values and not own:
            self._follow_selection(id_values)
        self._refresh_view_buttons()
        self._refresh_group_buttons()

    def _follow_selection(self, id_values):
        """An element picked in the view: select its system's row (several
        systems if the pick spans them), scroll to it, and leave the Revit
        selection exactly as the user made it. Switches Duct / Pipe when the
        pick belongs to the other, already read, kind."""
        hits = core.systems_holding(self._systems(), id_values)
        if not hits:
            other = u"pipe" if self.kind == u"duct" else u"duct"
            ost = self.state[other]
            if ost[u"data"] is None or not core.systems_holding(ost[u"systems"], id_values):
                return
            self.ctl(u"SelPipeTab" if other == u"pipe" else u"SelDuctTab").IsChecked = True  # runs _on_kind
            hits = core.systems_holding(self._systems(), id_values)
            if not hits:
                return
        st = self.st()
        systems = st[u"systems"]
        st[u"picked"] = set([systems[i][u"key"] for i in hits])
        st[u"cur"] = systems[hits[0]][u"key"]
        st[u"anchor"] = st[u"cur"]
        self._paint_rows()
        self._bring_into_view(hits[0])
        self._refresh_order_buttons()
        self.w._refresh_start()
        on = self.on_systems()
        sd = systems[hits[0]]
        where = u"system {0}".format(on.index(sd) + 1) if sd in on else u"unticked"
        self.w._status(u"Picked in the view: {0} ({1}){2}".format(
            sd[u"name"], where, u" and {0} more".format(len(hits) - 1) if len(hits) > 1 else u""))

    # ---------------------------------------------------- order
    def recompute(self):
        st = self.st()
        d = st[u"data"]
        # only systems still in the view: every element removed -> off the list
        st[u"systems"], gone = core.split_gone(st[u"systems"], st[u"left_out"])
        if gone:
            st[u"gone"].append(gone)
            self.w.log.add(u"{0} system(s) fully removed, off the list: {1}".format(
                len(gone), u", ".join([sd[u"name"] for i, sd in gone])))
            keys = set([sd[u"key"] for sd in st[u"systems"]])
            st[u"picked"] = set([k for k in st[u"picked"] if k in keys])
            if st[u"cur"] not in keys:
                st[u"cur"] = st[u"systems"][0][u"key"] if st[u"systems"] else None
        self._regroup()
        if d is None:
            st[u"order"], st[u"spans"], st[u"starts"] = [], [], []
        else:
            st[u"order"], st[u"spans"], st[u"starts"] = core.selector_order(
                d[u"nodes"], self.on_systems(), self.include)
            self.w.log.add(u"selector walk: {0} elements over {1} ticked system(s)".format(
                len(st[u"order"]), len(self.on_systems())))
        self.rebuild()
        self.w._sel_changed()
        if self.iso_on or self.col_on or self.iso3d is not None:
            self._request_sync()

    def rebuild(self):
        """Table, tree and labels for the active kind."""
        st = self.st()
        d = st[u"data"]
        self._build_rows()
        tree = st[u"tree"]
        if d is not None:
            keep = set([k for sd in self.on_systems() for k in sd[u"num"]])
            tree.set_rows([r for r in d[u"rows"] if r[0] in keep], len(keep))
        tree.build()
        if d is None:
            self.ctl(u"SelViewText").Text = u"Not read yet - Refresh from view"
        else:
            out = len(st[u"left_out"])
            self.ctl(u"SelViewText").Text = u"View: {0} ({1})  |  {2} systems, {3} ticked{4}  |  " \
                u"Ctrl / Shift + click to select several, Up / Down to step, Shift + Up / Down " \
                u"or drag to re-order".format(d[u"view_name"], d[u"view_type"], len(st[u"systems"]),
                                              len(self.on_systems()),
                                              u", {0} removed".format(out) if out else u"")
        self._refresh_order_buttons()
        self._refresh_view_buttons()

    def _on_kind(self, sender, e):
        kind = u"pipe" if self.ctl(u"SelPipeTab").IsChecked else u"duct"
        if kind == self.kind:
            return
        self.kind = kind
        self.w.settings[u"sel_kind"] = kind
        self.w._save()
        self.user_sel = []
        self.last_col = None
        self.last_iso = None
        self.last_col3d = None
        self.last_iso3d = None
        self.last_key = None
        if not self.st()[u"loaded"]:
            self.refresh()
        self._check_view()
        self.recompute()

    # ---------------------------------------------------- the table
    def _columns(self, grid):
        for key, head, width, star, minw in COLUMNS:
            cd = ColumnDefinition()
            if star:
                cd.Width = GridLength(width, getattr(GridUnitType, u"Star"))
                cd.MinWidth = minw
            else:
                cd.Width = GridLength(width)
            grid.ColumnDefinitions.Add(cd)

    def _cell(self, grid, col, text, muted=False, bold=False):
        tb = TextBlock()
        tb.Text = text or u""
        tb.Margin = Thickness(4, 0, 6, 0)
        tb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
        tb.TextTrimming = getattr(TextTrimming, u"CharacterEllipsis")
        tb.ToolTip = text or None
        tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted" if muted else u"Text")
        if bold:
            tb.FontWeight = FontWeights.SemiBold
        Grid.SetColumn(tb, col)
        grid.Children.Add(tb)
        return tb

    def _build_header(self):
        grid = Grid()
        self._columns(grid)
        for i, (key, head, width, star, minw) in enumerate(COLUMNS):
            if head:
                tb = self._cell(grid, i, head, muted=True, bold=True)
                tb.FontSize = 11
        self.ctl(u"SelHeaderHost").Child = grid

    def _line(self, top):
        """The insertion line shown while dragging: drawn over the row edge,
        never changing the row's size, so nothing jumps under the cursor."""
        ln = Border()
        ln.Height = 3
        ln.CornerRadius = CornerRadius(1.5)
        ln.Margin = Thickness(2, -2, 2, 0) if top else Thickness(2, 0, 2, -2)
        ln.VerticalAlignment = getattr(VerticalAlignment, u"Top" if top else u"Bottom")
        ln.IsHitTestVisible = False
        ln.SetResourceReference(Border.BackgroundProperty, u"Blue")
        ui.show(ln, False)
        return ln

    def _build_rows(self):
        host = self.ctl(u"SelRows")
        host.Children.Clear()
        self.rows = []
        self.range_cells = []
        st = self.st()
        if not st[u"systems"]:
            tb = TextBlock()
            tb.Margin = Thickness(8, 8, 8, 8)
            tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            tb.Text = u"No {0} in the active view".format(core.KINDS[self.kind][u"label"].lower()) \
                if st[u"loaded"] else u"Not read yet - Refresh from view"
            host.Children.Add(tb)
            return
        starts = core.start_keys(st[u"order"], self.on_systems(), st[u"starts"])
        groups = st[u"groups"]
        shade = st[u"shade"]
        on_index = 0
        prev_gid = None
        for i, sd in enumerate(st[u"systems"]):
            gid = groups.get(sd[u"key"])
            holder = Grid()
            holder.AllowDrop = True
            # a gap where a group starts or ends, so each group reads as a block
            gap = 5 if i > 0 and gid != prev_gid and (gid is not None or prev_gid is not None) else 0
            prev_gid = gid
            # the gap sits inside the holder, which paints (clear) to catch a drop anywhere on it
            holder.Background = ui.brush(CLEAR)
            holder.Margin = Thickness(0, 0, 0, 0)
            row = Border()
            row.Padding = Thickness(0, 3, 0, 3)
            row.CornerRadius = CornerRadius(3)
            row.Background = ui.brush(CLEAR)
            row.Cursor = Cursors.Hand
            grid = Grid()
            self._columns(grid)

            grip = Path()
            grip.Data = Geometry.Parse(GRIP)
            grip.StrokeThickness = 1.4
            grip.SetResourceReference(Shape.StrokeProperty, u"Muted")
            grip.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            grip.HorizontalAlignment = getattr(HorizontalAlignment, u"Center")
            grip.Cursor = Cursors.SizeNS
            grip.ToolTip = u"Drag to re-order (drags every selected system)"
            Grid.SetColumn(grip, 0)
            grid.Children.Add(grip)

            badge = Border()
            badge.Width = 22
            badge.Height = 20
            badge.CornerRadius = CornerRadius(10)
            num = TextBlock()
            num.FontSize = 11
            num.FontWeight = FontWeights.SemiBold
            num.HorizontalAlignment = getattr(HorizontalAlignment, u"Center")
            num.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            if sd[u"on"]:
                on_index += 1
                num.Text = u"{0}".format(on_index)
                badge.SetResourceReference(Border.BackgroundProperty, u"Orange")
                num.SetResourceReference(TextBlock.ForegroundProperty, u"OnAccent")
            else:
                num.Text = u"-"
                badge.SetResourceReference(Border.BackgroundProperty, u"Edge")
                num.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            badge.Child = num
            Grid.SetColumn(badge, 1)
            grid.Children.Add(badge)

            cb = CheckBox()
            cb.IsChecked = bool(sd[u"on"])
            cb.ToolTip = u"Include in the sequence (applies to every selected system)"
            cb.HorizontalAlignment = getattr(HorizontalAlignment, u"Center")
            cb.Click += self.w._guard(self._tick(i, cb))
            Grid.SetColumn(cb, 2)
            grid.Children.Add(cb)

            sw = Border()
            sw.Width = 16
            sw.Height = 16
            sw.CornerRadius = CornerRadius(3)
            colour = shade.get(sd[u"key"]) or sd[u"colour"]
            sw.Background = ui.brush(colour)
            sw.SetResourceReference(Border.BorderBrushProperty, u"Edge")
            sw.BorderThickness = Thickness(1)
            sw.ToolTip = u"Colour used by Colour systems: {0}{1}".format(
                colour, u" - its group's shade for its place, darkest first" if gid else u"")
            Grid.SetColumn(sw, 3)
            grid.Children.Add(sw)

            if gid is not None:
                # the group: a bar in its hue and a chip "G2  1/3"
                cell = Grid()
                bar = Border()
                bar.Width = 4
                bar.Margin = Thickness(0, 1, 0, 1)
                bar.HorizontalAlignment = getattr(HorizontalAlignment, u"Left")
                bar.Background = ui.brush(st[u"hues"].get(gid) or colour)
                bar.CornerRadius = CornerRadius(2)
                cell.Children.Add(bar)
                chip = Border()
                chip.CornerRadius = CornerRadius(3)
                chip.Padding = Thickness(5, 1, 5, 1)
                chip.Margin = Thickness(7, 0, 2, 0)
                chip.HorizontalAlignment = getattr(HorizontalAlignment, u"Left")
                chip.VerticalAlignment = getattr(VerticalAlignment, u"Center")
                chip.SetResourceReference(Border.BackgroundProperty, u"Edge")
                gt = TextBlock()
                gt.FontSize = 11
                gt.Text = core.group_label(groups, sd[u"key"], st[u"systems"])
                gt.SetResourceReference(TextBlock.ForegroundProperty, u"Text")
                chip.Child = gt
                cell.Children.Add(chip)
                cell.ToolTip = u"Group {0}: numbered as one block. Drag a system out to take it out of the group.".format(gid)
                Grid.SetColumn(cell, 4)
                grid.Children.Add(cell)

            name = sd[u"name"]
            if any([k in starts for k in sd[u"keys"]]) and sd[u"on"]:
                name += u"   (start)"
            self._cell(grid, 5, name, muted=not sd[u"on"], bold=bool(sd[u"on"]))
            self._cell(grid, 6, sd[u"type"], muted=True)
            self._cell(grid, 7, sd[u"abbr"], muted=True)
            self._cell(grid, 8, sd[u"cls"], muted=True)
            out = len([k for k in sd[u"num"] if k in st[u"left_out"]])
            self._cell(grid, 9, u"{0}{1}".format(len(sd[u"num"]), u" (-{0})".format(out) if out else u""),
                       muted=True)
            rng = self._cell(grid, 10, u"" if sd[u"on"] else u"off")
            rng.SetResourceReference(TextBlock.ForegroundProperty, u"Blue")

            row.Margin = Thickness(0, gap, 0, 1)
            row.Child = grid
            top = self._line(True)
            bottom = self._line(False)
            holder.Children.Add(row)
            holder.Children.Add(top)
            holder.Children.Add(bottom)
            holder.ToolTip = u"Click: select in Revit.  Ctrl / Shift + click: several.  " \
                             u"Double-click: zoom.  Drag: re-order."
            holder.PreviewMouseLeftButtonDown += self.w._guard(self._row_down(i))
            holder.PreviewMouseMove += self.w._guard(self._row_move(i))
            holder.MouseLeftButtonUp += self.w._guard(self._row_up(i))
            holder.DragOver += self.w._guard(self._row_drag_over(i))
            holder.DragLeave += self.w._guard(self._row_drag_leave(i))
            holder.Drop += self.w._guard(self._row_drop(i))
            holder.PreviewMouseRightButtonDown += self.w._guard(self._row_right(i))
            holder.ContextMenu = self.menu
            host.Children.Add(holder)
            self.rows.append((holder, row, top, bottom))
            self.range_cells.append((sd, rng))
        self._paint_rows()

    def _paint_rows(self):
        picked = self._picked_idx()
        cur = self._cur_index()
        for i, (holder, row, top, bottom) in enumerate(self.rows):
            if i in picked:
                row.SetResourceReference(Border.BackgroundProperty, u"Sel")
            else:
                row.Background = ui.brush(CLEAR)
            # the current row gets an accent edge; every row keeps the same
            # border width so nothing shifts as the selection moves
            row.BorderThickness = Thickness(3, 0, 0, 0)
            if i == cur:
                row.SetResourceReference(Border.BorderBrushProperty, u"Blue")
            else:
                row.BorderBrush = ui.brush(CLEAR)

    def refresh_ranges(self, plan):
        st = self.st()
        on = [sd for sd, cell in self.range_cells if sd[u"on"]]
        ranges = core.system_ranges(plan or [], [st[u"order"][a:b] for a, b in st[u"spans"]])
        by_sys = dict(zip([id(sd) for sd in on], ranges))
        for sd, cell in self.range_cells:
            if not sd[u"on"]:
                cell.Text = u"off"
                continue
            r = by_sys.get(id(sd))
            cell.Text = (r[0] if r[0] == r[1] else u"{0} - {1}".format(r[0], r[1])) if r else u"none"

    # ---------------------------------------------------- selecting rows
    def _mods(self):
        m = Keyboard.Modifiers
        ctrl = (m & getattr(ModifierKeys, u"Control")) == getattr(ModifierKeys, u"Control")
        shift = (m & getattr(ModifierKeys, u"Shift")) == getattr(ModifierKeys, u"Shift")
        return ctrl, shift

    def _shift(self):
        return self._mods()[1]

    def _click(self, index, ctrl=False, shift=False, zoom=False):
        st = self.st()
        systems = st[u"systems"]
        if not (0 <= index < len(systems)):
            return
        new, anchor = core.click_selection(self._picked_idx(), self._index(st[u"anchor"]), index, ctrl, shift)
        st[u"picked"] = set([systems[i][u"key"] for i in new])
        st[u"anchor"] = systems[anchor][u"key"] if anchor is not None else None
        st[u"cur"] = systems[index][u"key"]
        self._after_pick(zoom)

    def _after_pick(self, zoom=False):
        self._paint_rows()
        self._bring_into_view(self._cur_index())
        self._select_picked(zoom)
        self._refresh_order_buttons()
        self.w._refresh_start()

    def _select_picked(self, zoom):
        st = self.st()
        if st[u"data"] is None:
            return
        idmap = st[u"data"][u"idmap"]
        picked = [st[u"systems"][i] for i in sorted(self._picked_idx())]
        keys = [k for sd in picked for k in sd[u"num"] if k in idmap]
        self.own_sel = set(keys)
        self.user_sel = []
        self.view_sel = []
        self._refresh_view_buttons()
        self._refresh_group_buttons()
        self.w._select_ids([idmap[k] for k in keys], zoom)
        if len(picked) == 1:
            self.w._status(u"{0}: {1} elements selected in Revit".format(picked[0][u"name"], len(keys)))
        elif picked:
            self.w._status(u"{0} systems, {1} elements selected in Revit".format(len(picked), len(keys)))

    def _select_keys(self, keys):
        idmap = (self.st()[u"data"] or {}).get(u"idmap", {})
        self.own_sel = set([k for k in keys if k in idmap])
        self.w._select_ids([idmap[k] for k in keys if k in idmap], True)

    def _bring_into_view(self, index):
        if index is not None and 0 <= index < len(self.rows):
            try:
                self.rows[index][0].BringIntoView()
            except Exception:
                pass

    def _step(self, delta):
        st = self.st()
        n = len(st[u"systems"])
        i = core.step_index(n, self._cur_index(), delta)
        if i is None:
            return
        key = st[u"systems"][i][u"key"]
        st[u"cur"] = key
        st[u"anchor"] = key
        st[u"picked"] = set([key])
        self._after_pick()

    def _on_key(self, sender, e):
        if self.w.tab != u"sel" or e.Key not in (getattr(Key, u"Up"), getattr(Key, u"Down")):
            return
        focused = Keyboard.FocusedElement
        if isinstance(focused, (TextBox, ComboBox, ComboBoxItem)):
            return
        if self.ctl(u"ParamPopup").IsOpen or self.ctl(u"TagCombo").IsDropDownOpen:
            return
        if not self._systems():
            return
        delta = -1 if e.Key == getattr(Key, u"Up") else 1
        if self._shift():
            self._move_picked(delta)
        else:
            self._step(delta)
        e.Handled = True

    # ---------------------------------------------------- row mouse
    def _in_checkbox(self, source):
        node = source
        for _ in range(12):
            if node is None:
                return False
            if isinstance(node, CheckBox):
                return True
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return False
        return False

    def _row_down(self, index):
        def handler(sender, e):
            if self._in_checkbox(e.OriginalSource):
                self.drag = None
                return   # the tick box handles its own press
            try:
                self.ctl(u"SelScroll").Focus()   # arrow keys come to the table, not a text box
            except Exception:
                pass
            if e.ClickCount == 2:
                self._click(index, zoom=True)
                self.drag = None
                self.skip_up = True   # the button-up after a double-click must not undo the zoom
                e.Handled = True
                return
            p = e.GetPosition(self.ctl(u"SelRows"))
            self.drag = (index, p.X, p.Y)
            self.dragged = False
        return handler

    def _row_up(self, index):
        def handler(sender, e):
            if self.dragged or self.skip_up:
                self.dragged = False
                self.skip_up = False
                return
            self.drag = None
            ctrl, shift = self._mods()
            self._click(index, ctrl, shift)
        return handler

    def _row_move(self, index):
        def handler(sender, e):
            if self.drag is None or self.drag[0] != index:
                return
            if e.LeftButton != getattr(MouseButtonState, u"Pressed"):
                self.drag = None
                return
            p = e.GetPosition(self.ctl(u"SelRows"))
            if abs(p.Y - self.drag[2]) < DRAG_MIN and abs(p.X - self.drag[1]) < DRAG_MIN:
                return
            self.dragged = True
            self.drag = None
            picked = self._picked_idx()
            self.drag_set = picked if index in picked else set([index])
            for i in self.drag_set:
                if i < len(self.rows):
                    self.rows[i][1].Opacity = 0.45
            try:
                DragDrop.DoDragDrop(self.rows[index][0], DataObject(DRAG_FORMAT, u"rows"),
                                    getattr(DragDropEffects, u"Move"))
            finally:
                for holder, row, top, bottom in self.rows:
                    row.Opacity = 1.0
                    ui.show(top, False)
                    ui.show(bottom, False)
        return handler

    def _below(self, index, e):
        holder = self.rows[index][0]
        return e.GetPosition(holder).Y > holder.ActualHeight / 2.0

    def _row_drag_over(self, index):
        def handler(sender, e):
            if not e.Data.GetDataPresent(DRAG_FORMAT):
                e.Effects = getattr(DragDropEffects, u"None")
                e.Handled = True
                return
            below = self._below(index, e)
            for i, (holder, row, top, bottom) in enumerate(self.rows):
                ui.show(top, i == index and not below)
                ui.show(bottom, i == index and below)
            e.Effects = getattr(DragDropEffects, u"Move")
            e.Handled = True
        return handler

    def _row_drag_leave(self, index):
        def handler(sender, e):
            holder, row, top, bottom = self.rows[index]
            ui.show(top, False)
            ui.show(bottom, False)
        return handler

    def _row_drop(self, index):
        def handler(sender, e):
            e.Handled = True
            if not e.Data.GetDataPresent(DRAG_FORMAT):
                return
            before = core.drop_before(index, self._below(index, e))
            moving = set(self.drag_set)
            # rebuild after the drop event has finished with this row
            self._later(lambda: self._move_to(moving, before))
        return handler

    def _on_scroll_drag(self, sender, e):
        """Scroll the table while dragging near its top or bottom edge."""
        if not e.Data.GetDataPresent(DRAG_FORMAT):
            return
        sv = self.ctl(u"SelScroll")
        y = e.GetPosition(sv).Y
        if y < AUTOSCROLL:
            sv.LineUp()
        elif y > sv.ActualHeight - AUTOSCROLL:
            sv.LineDown()

    def _on_scroll_drop(self, sender, e):
        """Dropped below the last row: to the end."""
        if e.Handled or not e.Data.GetDataPresent(DRAG_FORMAT):
            return
        e.Handled = True
        moving = set(self.drag_set)
        self._later(lambda: self._move_to(moving, len(self._systems())))

    def _tick(self, index, cb):
        def handler(sender, e):
            on = cb.IsChecked == True  # noqa: E712
            picked = self._picked_idx()
            targets = picked if index in picked else set([index])
            for i in targets:
                self._systems()[i][u"on"] = on
            self._later(self.recompute)
        return handler

    def _later(self, fn):
        def run():
            try:
                fn()
            except Exception:
                self.w.log.add(u"deferred step failed: " + traceback.format_exc())
        self.ctl(u"SelRows").Dispatcher.BeginInvoke(Action(run))

    # ---------------------------------------------------- re-ordering
    def _note_place(self, new):
        """Remember the last system moved, for Move to next."""
        if new:
            self.last_key = self.st()[u"systems"][max(new)][u"key"]

    def _next_place(self):
        """(list index to insert at, the # it gives) straight after the last
        system moved, or None when there is none."""
        i = self._index(self.last_key)
        if i is None:
            return None
        # after the whole group when the last one moved is in one
        i = max([j for j in [self._index(k) for k in self._unit_keys(self.last_key)] if j is not None] + [i])
        sd = self._systems()[i]
        return i + 1, core.position_of(self._systems(), i, self._counted, [sd]) + 1

    def _counted(self, sd):
        return bool(sd[u"on"])

    def _gone_keys(self):
        """Systems off the list because every element was removed - they keep
        their group, so Restore puts them back in it."""
        return [sd[u"key"] for batch in self.st()[u"gone"] for after, sd in batch]

    def _moved(self, new):
        """After a drag or a move to a place: a member moved away from its
        group leaves it, a system dropped between two members joins theirs, a
        whole group dropped inside another goes on after it.
        Returns (left, joined, new indexes)."""
        st = self.st()
        before = dict(st[u"groups"])
        moved = [st[u"systems"][i][u"key"] for i in new if 0 <= i < len(st[u"systems"])]
        st[u"systems"], st[u"groups"] = core.tidy_groups(st[u"systems"], st[u"groups"], moved, self._gone_keys())
        new = set([i for i, sd in enumerate(st[u"systems"]) if sd[u"key"] in set(moved)])
        left = [k for k in before if k not in st[u"groups"]]
        joined = [k for k in st[u"groups"] if before.get(k) != st[u"groups"][k]]
        self._note_place(new)
        return left, joined, new

    def _group_note(self, left, joined, new=None):
        bits = []
        if joined:
            bits.append(u"joined {0}".format(self.st()[u"groups"][joined[0]]))
        if left:
            bits.append(u"{0} left a group".format(len(left)) if len(left) > 1 else u"left its group")
        return (u" - " + u", ".join(bits)) if bits else u""

    def _move_to(self, moving, before):
        st = self.st()
        st[u"systems"], new = core.move_many(st[u"systems"], moving, before)
        note = self._group_note(*self._moved(new))
        self.recompute()
        self._bring_into_view(self._cur_index())
        if note:
            self.w._status(u"Moved" + note)

    def _move_picked(self, delta):
        """Shift+Up / Down: inside a group a member steps within it (past its
        end, out of it); otherwise systems and groups step over whole parts."""
        st = self.st()
        before = dict(st[u"groups"])
        st[u"systems"], st[u"groups"], new = core.step_units(st[u"systems"], st[u"groups"], self._picked_idx(),
                                                             delta, self._gone_keys())
        self._note_place(new)
        note = self._group_note([k for k in before if k not in st[u"groups"]], [])
        self.recompute()
        self._bring_into_view(self._cur_index())
        if note:
            self.w._status(u"Moved" + note)

    def _move_position(self, position):
        """Move the selected systems so the first becomes number position."""
        st = self.st()
        picked = self._picked_idx()
        if not picked:
            return
        names = [st[u"systems"][i][u"name"] for i in sorted(picked)]
        st[u"systems"], new, last = core.move_to_position(st[u"systems"], picked, position, self._counted)
        new = self._moved(new)[2]
        self.recompute()
        self._moved_status(names, new)

    def _moved_status(self, names, new):
        self._bring_into_view(self._cur_index())
        st = self.st()
        if not new:
            return
        first = min(new)
        if first >= len(st[u"systems"]):
            return
        at = core.position_of(st[u"systems"], first, self._counted, [st[u"systems"][first]])
        nxt = self._next_place()
        self.w._status(u"Moved {0} to #{1}{2}".format(
            names[0] if len(names) == 1 else u"{0} systems".format(len(names)), at,
            u" - Move to next goes to #{0}".format(nxt[1]) if nxt else u""))

    # ---------------------------------------------------- right-click menu
    def _build_menu(self):
        """One shared, themed menu: its own copy of the theme, since a context
        menu opens outside the window's visual tree."""
        menu = ContextMenu()
        ui.merge_theme(menu)
        ui.apply_palette(menu, self.w.mode)
        self.menu_to = MenuItem()
        self.menu_top = MenuItem()
        self.menu_next = MenuItem()
        self.menu_clear = MenuItem()
        self.menu_group = MenuItem()
        for item, key, text, fn in ((self.menu_to, u"order", u"Move to...", self._on_menu_to),
                                    (self.menu_top, u"top", u"Move to top", self._on_menu_top),
                                    (self.menu_next, u"down", u"Move to next", self._on_menu_next),
                                    (self.menu_group, u"group", u"Select its group", self._on_menu_group),
                                    (self.menu_clear, u"remove", u"Clear picked start", self._on_menu_clear)):
            item.Header = text
            item.Icon = ui.icon(key)
            item.Click += self.w._guard(fn)
            menu.Items.Add(item)
        menu.Opened += self.w._guard(self._on_menu_opened)
        self.menu = menu

    def _row_right(self, index):
        def handler(sender, e):
            # right-click on a row that is not selected selects it, as Explorer does
            if index not in self._picked_idx():
                self._click(index)
        return handler

    def _on_menu_opened(self, sender, e):
        ui.apply_palette(self.menu, self.w.mode)
        n = len(self._picked_idx())
        what = u"" if n <= 1 else u" ({0} systems)".format(n)
        self.menu_to.Header = u"Move to..." + what
        self.menu_top.Header = u"Move to top" + what
        self.menu_clear.IsEnabled = any([self._systems()[i][u"start"] is not None for i in self._picked_idx()])
        self.menu_group.IsEnabled = bool(self._picked_gids())
        nxt = self._next_place()
        last = self._index(self.last_key)
        if nxt is None or last in self._picked_idx():
            self.menu_next.Header = u"Move to next (move a system first)" if nxt is None else \
                u"Move to next (this is the last one moved)"
            self.menu_next.IsEnabled = False
        else:
            self.menu_next.Header = u"Move to next (#{0}){1}".format(nxt[1], what)
            self.menu_next.IsEnabled = True

    def _on_menu_to(self, sender, e):
        st = self.st()
        picked = self._picked_idx()
        if not picked:
            return
        moving = [st[u"systems"][i] for i in picked]
        others = len([x for x in self.on_systems() if x not in moving])
        hi = others + 1   # the block can land anywhere from first to after the last ticked system
        sd = st[u"systems"][min(picked)]
        now = min(hi, core.position_of(st[u"systems"], min(picked), self._counted, [sd]))
        msg = u"Move {0} to position (1 to {1}):".format(
            sd[u"name"] if len(picked) == 1 else u"the {0} selected systems".format(len(picked)), hi)
        pos = ui.prompt_number(self.w.win, self.w.mode, u"Move to", msg, now, 1, hi)
        if pos is not None:
            self._move_position(pos)

    def _on_menu_group(self, sender, e):
        """Select every member of the selected systems' groups - to move a group as one."""
        st = self.st()
        gids = self._picked_gids()
        keys = [sd[u"key"] for sd in st[u"systems"] if st[u"groups"].get(sd[u"key"]) in gids]
        if keys:
            st[u"picked"] = set(keys)
            st[u"cur"] = keys[0]
            st[u"anchor"] = keys[0]
            self._after_pick()

    def _on_menu_clear(self, sender, e):
        self.auto_start()

    def _on_menu_top(self, sender, e):
        self._move_position(1)

    def _on_menu_next(self, sender, e):
        """Straight after the last system moved - ticked or not, no gaps."""
        nxt = self._next_place()
        picked = self._picked_idx()
        if nxt is None or not picked or self._index(self.last_key) in picked:
            return
        st = self.st()
        names = [st[u"systems"][i][u"name"] for i in sorted(picked)]
        st[u"systems"], new = core.move_many(st[u"systems"], picked, nxt[0])
        new = self._moved(new)[2]
        self.recompute()
        self._moved_status(names, new)

    def _refresh_order_buttons(self):
        st = self.st()
        n = len(st[u"systems"])
        has = n > 0
        picked = self._picked_idx()
        self.ctl(u"SelUpBtn").IsEnabled = has
        self.ctl(u"SelDownBtn").IsEnabled = has
        self.ctl(u"SelTopBtn").IsEnabled = bool(picked) and min(picked) > 0
        self.ctl(u"SelBottomBtn").IsEnabled = bool(picked) and max(picked) < n - 1
        self.ctl(u"SelAutoOrderBtn").IsEnabled = len(self.on_systems()) > 1
        self._refresh_group_buttons()

    def _on_up(self, sender, e):
        if self._shift():
            self._move_picked(-1)
        else:
            self._step(-1)

    def _on_down(self, sender, e):
        if self._shift():
            self._move_picked(1)
        else:
            self._step(1)

    def _on_top(self, sender, e):
        self._move_to(self._picked_idx(), 0)

    def _on_bottom(self, sender, e):
        self._move_to(self._picked_idx(), len(self._systems()))

    def _on_auto_order(self, sender, e):
        st = self.st()
        if st[u"data"] is None:
            return
        st[u"systems"] = core.auto_order_units(st[u"data"][u"nodes"], st[u"systems"], st[u"groups"], self.include)
        self.recompute()
        on = self.on_systems()
        n = len(set(st[u"groups"].values()))
        self.w._status(u"Ordered nearest-next from {0}{1}".format(
            on[0][u"name"] if on else u"the first system",
            u" - {0} group(s) moved as one, each next starting nearest where the last finished".format(n)
            if n else u""))

    def _on_all_on(self, sender, e):
        for sd in self._systems():
            sd[u"on"] = True
        self.recompute()

    def _on_all_off(self, sender, e):
        for sd in self._systems():
            sd[u"on"] = False
        self.recompute()

    # ---------------------------------------------------- groups
    def _regroup(self):
        """Groups kept whole and together; their hues and every system's
        shade worked out (a lone system too near a group's hue is moved off it)."""
        st = self.st()
        listed = [sd[u"key"] for sd in st[u"systems"]] + self._gone_keys()
        st[u"groups"] = core.clean_groups(st[u"groups"], listed)
        st[u"systems"] = core.gather_groups(st[u"systems"], st[u"groups"])
        st[u"hues"], changed = core.colour_groups(st[u"systems"], st[u"groups"], st[u"hues"])
        for sd in st[u"systems"]:
            if sd[u"key"] in changed:
                sd[u"colour"] = changed[sd[u"key"]]
        st[u"shade"] = core.system_colours(st[u"systems"], st[u"groups"], st[u"hues"])

    def _picked_gids(self):
        st = self.st()
        return set([st[u"groups"][st[u"systems"][i][u"key"]] for i in self._picked_idx()
                    if st[u"systems"][i][u"key"] in st[u"groups"]])

    def _unit_of(self, key):
        return self.st()[u"groups"].get(key) or key

    def _unit_keys(self, key, st=None):
        """The system and, when grouped, every other member of its group, in list order."""
        st = st or self.st()
        gid = st[u"groups"].get(key)
        if gid is None:
            return [key]
        return [sd[u"key"] for sd in st[u"systems"] if st[u"groups"].get(sd[u"key"]) == gid]

    def _ticked_keys(self, keys):
        on = set([sd[u"key"] for sd in self.on_systems()])
        return [k for k in keys if k in on]

    def _entry_skip(self):
        """Grouped systems that are not their group's first ticked one: Auto
        next only ever starts a group at its first."""
        st = self.st()
        out = set()
        seen = set()
        for sd in self.on_systems():
            gid = st[u"groups"].get(sd[u"key"])
            if gid is None:
                continue
            if gid in seen:
                out.add(sd[u"key"])
            else:
                seen.add(gid)
        return out

    def _view_hits(self):
        """Systems holding the elements the user selected in the view."""
        if not self.view_sel:
            return []
        return core.systems_holding(self._systems(), self.view_sel)

    def _group_candidates(self):
        """(systems to group, where from): the systems of the elements picked in
        the view when they span two or more, else the rows selected in the table."""
        st = self.st()
        hits = self._view_hits()
        if len(hits) >= 2:
            return [st[u"systems"][i] for i in hits], u"from the view"
        return [st[u"systems"][i] for i in sorted(self._picked_idx())], u"from the table"

    def _refresh_group_buttons(self):
        st = self.st()
        has = st[u"data"] is not None and bool(st[u"systems"])
        btn = self.ctl(u"SelGroupBtn")
        hits = self._view_hits()
        if len(hits) >= 2:
            # elements of two or more systems picked in the view: ready to group them
            ui.set_button(btn, u"group", u"Group systems ({0})".format(len(hits)), STEP_GROUP)
            btn.SetResourceReference(FrameworkElement.StyleProperty, u"GreenFillButton")
        else:
            ui.set_button(btn, u"group", u"Group systems", STEP_GROUP)
            btn.SetResourceReference(FrameworkElement.StyleProperty, u"GreenButton")
        hooked = selection_hooked(getattr(self, u"hooks", None))
        btn.IsEnabled = has and (len(hits) >= 2 or len(self._picked_idx()) >= 2 or not hooked)
        self.ctl(u"SelUngroupBtn").IsEnabled = bool(self._picked_gids())
        self.ctl(u"SelGroupOrderBtn").IsEnabled = has and bool(st[u"groups"])

    def _on_group(self, sender, e):
        st = self.st()
        if st[u"data"] is None:
            return
        sds, where = self._group_candidates()
        if len(sds) < 2:
            if not self.view_sel and not selection_hooked(self.hooks) and sender is not None:
                # no selection event (older Revit): read the selection now
                def read(uiapp):
                    return [rv.eid_value(i) for i in rv.selected_ids(uiapp.ActiveUIDocument)]

                def got(values, err):
                    values = values or []
                    own = self.own_sel is not None and set(values) == set(self.own_sel)
                    self.view_sel = [] if own else values
                    self._on_group(None, None)

                self._view_job(u"read selection", read, got, u"Reading the Revit selection")
                return
            self.w._status(u"Select elements of two or more systems in the view (or two or more rows), "
                           u"then Group systems")
            return
        gid, st[u"gid_n"] = core.next_group_id(st[u"groups"], st[u"gid_n"])
        keys = [sd[u"key"] for sd in sds]
        st[u"systems"], st[u"groups"] = core.make_group(st[u"systems"], st[u"groups"], keys, gid,
                                                        self._gone_keys())
        members = self._unit_keys(keys[0])
        st[u"picked"] = set(members)
        st[u"cur"] = members[0]
        st[u"anchor"] = members[0]
        self.last_key = members[-1]
        st[u"reorder_due"] = True
        self.view_sel = []   # used: the button stops offering the same group again
        if not self.col_on:
            # the group's shades are how it shows: colours on
            self.col_on = True
            self.col_auto = False
        self.recompute()
        self._bring_into_view(self._cur_index())
        self.w._status(u"Grouped {0} systems {1} as {2} - numbered as one block, dark to light in order. "
                       u"Reorder in group puts them nearest-next".format(len(members), where, gid))

    def _on_ungroup(self, sender, e):
        st = self.st()
        gids = self._picked_gids()
        if not gids:
            self.w._status(u"Select a grouped system first")
            return
        keys = [sd[u"key"] for sd in st[u"systems"] if st[u"groups"].get(sd[u"key"]) in gids]
        listed = [sd[u"key"] for sd in st[u"systems"]] + self._gone_keys()
        st[u"groups"] = core.ungroup(st[u"groups"], keys, listed)
        st[u"reorder_due"] = True
        self.recompute()
        self.w._status(u"Ungrouped {0} - {1} systems back on their own".format(
            u", ".join(sorted(gids, key=core.natural_key)), len(keys)))

    def _on_group_order(self, sender, e):
        """Nearest-next inside the selected systems' groups, or every group."""
        st = self.st()
        if st[u"data"] is None or not st[u"groups"]:
            return
        gids = self._picked_gids()
        if not gids:
            gids = set(st[u"groups"].values())
        ordered = []
        for sd in list(st[u"systems"]):
            gid = st[u"groups"].get(sd[u"key"])
            if gid in gids and gid not in ordered:
                ordered.append(gid)
        st[u"reorder_due"] = True
        for gid in ordered:
            st[u"systems"] = core.reorder_group(st[u"data"][u"nodes"], st[u"systems"], st[u"groups"],
                                                gid, self.include)
        self.recompute()
        self.w._status(u"Re-ordered {0} nearest-next - shades follow the new order".format(
            u"group " + ordered[0] if len(ordered) == 1 else u"{0} groups".format(len(ordered))))

    # ---------------------------------------------------- start point
    def _started(self):
        return bool(self._chain()) or any([sd[u"start"] is not None for sd in self.on_systems()])

    def _due(self):
        """Mark that the order may want working out again (a start picked,
        elements removed or restored, systems grouped)."""
        self.st()[u"reorder_due"] = True

    def _refresh_auto(self):
        """Pick start: green until a start is picked, then orange. Auto
        Re-order: off until there is a start, then green whenever a re-order
        can help (a new start, removals, groups), plain once done."""
        st = self.st()
        started = self._started()
        pick = self.ctl(u"SelPickStartBtn")
        if started:
            ui.set_button(pick, u"start", u"Start picked", STEP_PICK)
            pick.SetResourceReference(FrameworkElement.StyleProperty, u"ActiveButton")
            pick.ToolTip = u"The sequence starts at the picked element - press to pick another"
        else:
            ui.set_button(pick, u"start", u"Pick start", STEP_PICK)
            pick.SetResourceReference(FrameworkElement.StyleProperty, u"GreenFillButton")
            pick.ToolTip = u"Click the element the sequence starts from - its system (or group) goes to #1"
        pick.IsEnabled = self._has()
        btn = self.ctl(u"SelAutoBtn")
        units = len(set([self._unit_of(sd[u"key"]) for sd in self.on_systems()]))
        ui.set_button(btn, u"auto", u"Auto Re-order", STEP_AUTO)
        if started and units > 1 and st[u"reorder_due"]:
            btn.SetResourceReference(FrameworkElement.StyleProperty, u"GreenButton")
        else:
            btn.SetResourceReference(FrameworkElement.StyleProperty, u"ToolButton")
        btn.IsEnabled = started and units > 1
        btn.ToolTip = (u"Order every system (and group) from the picked start: each next is the one starting "
                       u"nearest where the last finished.  Shift: just the next one" if started else
                       u"Pick a start first")

    def refresh_start(self):
        self._refresh_auto()
        t = self.ctl(u"StartText")
        st = self.st()
        if st[u"data"] is None or not st[u"systems"]:
            t.Text = u"No systems read yet - Refresh from view"
            return
        i = self._cur_index()
        sd = st[u"systems"][i if i is not None else 0]
        on = self.on_systems()
        if sd not in on:
            t.Text = u"{0} is unticked - it is not numbered".format(sd[u"name"])
            return
        n = on.index(sd)
        key, how = st[u"starts"][n] if n < len(st[u"starts"]) else (None, u"auto")
        if key is None:
            t.Text = u"{0}: nothing to number".format(sd[u"name"])
            return
        why = {u"picked": u"picked", u"auto": u"auto - equipment end or biggest open end",
               u"nearest": u"open end nearest where system {0} finished".format(n)}.get(how, how)
        t.Text = u"System {0}, {1}: starts ({2}) at {3}  [{4}]".format(
            n + 1, sd[u"name"], why, st[u"data"][u"labels"].get(key, u""), key)

    def pick_start(self):
        kind = self.kind
        ints = rv.kind_ints(kind, u"walk")

        def job(uiapp):
            el = rv.pick_element(uiapp.ActiveUIDocument, ints,
                                 u"RevoBIM Number Sequencer: click the element to start the sequence from")
            return None if el is None else rv.eid_value(el.Id)

        def done(key, err):
            if err or key is None:
                self.w._status(u"Cancelled")
                return
            st = self.state[kind]
            for sd in st[u"systems"]:
                if key in sd[u"num"]:
                    sd[u"start"] = key
                    sd[u"on"] = True
                    # the picked start begins the sequence: its system goes to #1
                    # and starts the chain Auto next builds on
                    for other in st[u"systems"]:
                        if other is not sd and other[u"start"] is not None and other[u"key"] in st[u"chain"][:1]:
                            other[u"start"] = None
                    gid = st[u"groups"].get(sd[u"key"])
                    if gid is not None:
                        # a start inside a group: that system leads its group
                        rest = [x for x in st[u"systems"] if x is not sd]
                        hits = [j for j, x in enumerate(rest) if st[u"groups"].get(x[u"key"]) == gid]
                        if hits:
                            rest.insert(hits[0], sd)
                            st[u"systems"] = rest
                    unit = self._unit_keys(sd[u"key"], st)
                    idx = set([j for j, x in enumerate(st[u"systems"]) if x[u"key"] in unit])
                    st[u"systems"], new, last = core.move_to_position(st[u"systems"], idx, 1, self._counted)
                    # the whole group (or the system) begins the chain Auto next builds on
                    st[u"chain"] = [x[u"key"] for x in st[u"systems"] if x[u"key"] in unit and x[u"on"]]
                    st[u"reorder_due"] = True
                    self.last_key = st[u"chain"][-1] if st[u"chain"] else sd[u"key"]
                    st[u"cur"] = sd[u"key"]
                    st[u"anchor"] = sd[u"key"]
                    st[u"picked"] = set([sd[u"key"]])
                    # show the start: colours on, the start drawn heavy in its own colour
                    self.col_on = True
                    self.col_auto = False
                    self.recompute()
                    self.w._status(u"Start set on {0}, now #1 - press Auto next for the nearest "
                                   u"system after it (Shift: all the rest)".format(sd[u"name"]))
                    return
            self.w._status(u"That element is not in a listed system - Refresh from view first")

        self.w._queue(u"pick start", job, done, u"Click the element to start the sequence from (Esc cancels)")

    def auto_start(self):
        """Kept for the right-click menu: back on the automatic start."""
        changed = False
        for i in self._picked_idx():
            sd = self._systems()[i]
            if sd[u"start"] is not None:
                sd[u"start"] = None
                changed = True
                if self.st()[u"chain"][:1] == [sd[u"key"]]:
                    self.st()[u"chain"] = []
        if changed:
            self.recompute()

    def _chain(self):
        """The systems placed so far by Pick start / Auto next, still listed and ticked."""
        st = self.st()
        on_keys = set([sd[u"key"] for sd in self.on_systems()])
        return [k for k in st[u"chain"] if k in on_keys]

    def _on_pick_start_btn(self, sender, e):
        self.pick_start()

    def _on_auto_btn(self, sender, e):
        self.auto_reorder(step=self._shift())

    def auto_reorder(self, step=False):
        """Auto Re-order: from the picked start, every system and group in
        nearest-next order (the chain begins again, so removals and groups
        are taken into account). Shift: only the next one after the last placed."""
        st = self.st()
        if st[u"data"] is None or not self.on_systems():
            return
        if not step:
            st[u"chain"] = []
        self.auto_next(all_rest=not step)
        chain = set(self._chain())
        left = [sd for sd in self.on_systems() if sd[u"key"] not in chain]
        st[u"reorder_due"] = bool(left)
        self._refresh_auto()

    def auto_next(self, all_rest=False):
        """Best judgement of the next system: of those not yet placed, the one
        whose nearest open end is closest to where the last placed system
        finishes numbering goes straight after it. Shift: place all the rest."""
        st = self.st()
        if st[u"data"] is None or not self.on_systems():
            return
        nodes = st[u"data"][u"nodes"]
        chain = self._chain()
        if not chain:
            starts = [sd for sd in self.on_systems() if sd[u"start"] is not None]
            first = starts[0] if starts else self.on_systems()[0]
            unit = self._unit_keys(first[u"key"])
            idx = set([self._index(k) for k in unit])
            if min(idx) != 0:
                st[u"systems"], new, last = core.move_to_position(st[u"systems"], idx, 1, self._counted)
            chain = self._ticked_keys(self._unit_keys(first[u"key"]))
        placed = []
        dist = None
        while True:
            on = self.on_systems()
            keys = [sd[u"key"] for sd in on]
            last_i = keys.index(chain[-1])
            # a group is only ever entered at its first ticked system, and moves whole
            found = core.next_nearest(nodes, on, last_i, set(chain) | self._entry_skip(), self.include)
            if found is None:
                break
            sd = on[found[0]]
            dist = found[1]
            unit = self._unit_keys(sd[u"key"])
            end = max([self._index(k) for k in self._unit_keys(chain[-1])]) + 1
            st[u"systems"], new = core.move_many(st[u"systems"], set([self._index(k) for k in unit]), end)
            chain.extend(self._ticked_keys(self._unit_keys(sd[u"key"])))
            placed.append(sd)
            if not all_rest:
                break
        st[u"chain"] = chain
        self.last_key = chain[-1]
        st[u"cur"] = chain[-1]
        st[u"anchor"] = chain[-1]
        st[u"picked"] = set([chain[-1]])
        self.recompute()
        self._bring_into_view(self._cur_index())
        if not placed:
            self.w._status(u"Every ticked system is placed")
            return
        if len(placed) == 1:
            on = self.on_systems()
            pos = on.index(placed[0]) + 1 if placed[0] in on else 0
            gid = st[u"groups"].get(placed[0][u"key"])
            what = placed[0][u"name"] if gid is None else u"group {0} ({1} systems, from {2})".format(
                gid, len(self._unit_keys(placed[0][u"key"])), placed[0][u"name"])
            self.w._status(u"Auto next: {0} is #{1}, its start {2:.0f} mm from where the last one finishes".format(
                what, pos, (dist or 0) * 304.8 if dist is not None and dist < 1e20 else 0))
            self._select_picked(False)
        else:
            self.w._status(u"Auto next placed {0} systems / groups, each the nearest after the last".format(len(placed)))

    def picked_keys(self):
        """(element keys, label) of the selected systems, for Find views."""
        st = self.st()
        picked = [st[u"systems"][i] for i in sorted(self._picked_idx())]
        keys = [k for sd in picked for k in sd[u"num"]]
        label = picked[0][u"name"] if len(picked) == 1 else u"{0} systems".format(len(picked))
        return keys, label

    def show_start(self):
        st = self.st()
        on = self.on_systems()
        i = self._cur_index()
        if i is None:
            return
        sd = st[u"systems"][i]
        if sd in on and on.index(sd) < len(st[u"starts"]):
            key = st[u"starts"][on.index(sd)][0]
            if key is not None:
                self.own_sel = set([key])
                self.w._select_ids([st[u"data"][u"idmap"][key]], True)

    # ---------------------------------------------------- the view: isolate, colour, remove
    def _has(self):
        return self.st()[u"data"] is not None and bool(self._systems())

    def _same_view(self, uiapp):
        doc = uiapp.ActiveUIDocument.Document
        here = (rv.doc_key(doc), rv.eid_value(doc.ActiveView.Id))
        if self.st()[u"data"] is None or here != self.view_key or self._kind_view_key() != here:
            raise Exception(u"The active view is not the one the systems were read from - Refresh from view")

    def _isolate_ids(self):
        """Only the families ticked in the tree, in the ticked systems, not
        removed - never accessories. Their tags go with them."""
        st = self.st()
        idmap = st[u"data"][u"idmap"]
        return [idmap[k] for sd in self.on_systems() for k in sd[u"keys"]
                if k in idmap and self.include(k)]

    def _colour_groups(self):
        """Each system its swatch colour (a group's dark-to-light shade); the
        start last, heavy, in its own colour."""
        st = self.st()
        idmap = st[u"data"][u"idmap"]
        shade = st[u"shade"]
        groups = [(shade.get(sd[u"key"]) or sd[u"colour"], [idmap[k] for k in sd[u"keys"] if k in idmap], None)
                  for sd in st[u"systems"]]
        starts = core.start_keys(st[u"order"], self.on_systems(), st[u"starts"])
        groups.append((core.START_COLOUR, [idmap[k] for k in sorted(starts) if k in idmap], core.START_WEIGHT))
        return groups

    def _request_sync(self):
        """Bring the view in line with the table: colours and isolate. Many
        changes in a row send one job, which reads the state when it runs."""
        self.sync_wanted = True
        if self.sync_queued:
            return
        self.sync_queued = True

        def job(uiapp):
            self.sync_queued = False
            if not self.sync_wanted:
                return u""
            self.sync_wanted = False
            return self._sync(uiapp)

        def done(msg, err):
            self.sync_queued = False
            self._refresh_view_buttons()
            if err:
                self.w._status(self._why(err, u"Could not update the view"))
            elif msg:
                self.w._status(msg)

        self.w.runner.queue(u"view sync", job, done)

    def _col_sig(self, key, groups):
        # order-free: re-ordering the table never re-colours the view
        return (key, frozenset([(g[0], frozenset([rv.eid_value(i) for i in g[1]])) for g in groups]))

    def _iso_sig(self, key, ids):
        return (key, frozenset([rv.eid_value(i) for i in ids]))

    def _sync(self, uiapp):
        if not self._has() or not (self.col_on or self.iso_on or self.iso3d is not None):
            return u""
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        msgs = []
        here = (rv.doc_key(doc), rv.eid_value(doc.ActiveView.Id))
        if (self.col_on or self.iso_on) and not (self.iso3d is not None and here != self.view_key):
            # the read view; while Isolate in 3D is on, only when it is the active view
            self._sync_read_view(uiapp, msgs)
        if self.iso3d is not None and here[0] == self.iso3d[0]:
            self._sync_3d(uidoc, msgs)
        try:
            uidoc.RefreshActiveView()
        except Exception:
            pass
        return (u"View: " + u", ".join(msgs)) if msgs else u""

    def _sync_3d(self, uidoc, msgs):
        """Keep the Isolate in 3D view in step with the table."""
        doc = uidoc.Document
        view = doc.GetElement(self.iso3d_id)
        if view is None:
            self._iso3d_off()
            return
        key = self.iso3d
        if self.col3d:
            groups = self._colour_groups()
            sig = self._col_sig(key, groups)
            if sig != self.last_col3d:
                entry = self.snapshots.setdefault(key, (view.Id, {}))
                rv.colour_systems(doc, view, groups, entry[1], self.w.log)
                self._absorb(key)
                self.last_col3d = sig
                msgs.append(u"3D re-coloured")
        ids = self._isolate_ids()
        sig = self._iso_sig(key, ids)
        if sig != self.last_iso3d:
            # new systems: the section box follows them
            old_box = rv.fit_section_box(doc, view, ids, self.w.log)
            if old_box is not None and key not in self.boxes:
                self.boxes[key] = (view.Id, old_box)
            n = rv.isolate_systems(uidoc, ids, self.w.log, view)
            self.iso_views[key] = view.Id
            self.hide_views.pop(key, None)
            self.last_iso3d = sig
            msgs.append(u"3D isolated {0} elements and tags".format(n))

    def _sync_read_view(self, uiapp, msgs):
        self._same_view(uiapp)
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        view = doc.ActiveView
        key = (rv.doc_key(doc), rv.eid_value(view.Id))
        if self.col_on:
            groups = self._colour_groups()
            sig = self._col_sig(key, groups)
            if sig != self.last_col:
                entry = self.snapshots.setdefault(key, (view.Id, {}))
                n = rv.colour_systems(doc, view, groups, entry[1], self.w.log)
                self._absorb(key)
                self.last_col = sig
                msgs.append(u"coloured {0} elements".format(n))
        if self.iso_on:
            ids = self._isolate_ids()
            sig = self._iso_sig(key, ids)
            if sig != self.last_iso:
                n = rv.isolate_systems(uidoc, ids, self.w.log)
                self.iso_views[key] = view.Id
                self.hide_views.pop(key, None)   # the isolate reset any temporary hide
                self.last_iso = sig
                msgs.append(u"isolated {0} elements and tags".format(n))

    def _view_job(self, name, fn, done, status):
        """View changes go straight to the runner: a toggle must never show a
        state the view did not get because the window was busy."""
        self.w._status(status)
        self.w.runner.queue(name, fn, done)

    def _on_isolate(self, sender, e):
        if self.iso_on:
            self.iso_on = False
            self.last_iso = None
            clear = self.col_auto
            if clear:
                self.col_on = False
                self.col_auto = False
                self.last_col = None
            self._refresh_view_buttons()

            def job(uiapp):
                n = self._reset_isolates(uiapp, skip=self.iso3d)
                if clear:
                    self._restore_all(uiapp, skip=self.iso3d)
                return n

            def done(r, err):
                self._refresh_view_buttons()
                self.w._status(u"Could not reset the isolate - see debug" if err else u"Isolate reset")

            self._view_job(u"reset isolate", job, done, u"Resetting the isolate")
            return
        if not self._has():
            self.w._status(u"Nothing to isolate - Refresh from view")
            return
        self.iso_on = True
        if not self.col_on:
            self.col_on = True
            self.col_auto = True   # isolating turned the colours on, resetting turns them off
        self._refresh_view_buttons()
        self._request_sync()

    # ---------------------------------------------------- Isolate in 3D
    def fill_3d_combo(self, views):
        """The 3D view picker: Default 3D view, then the model's 3D views."""
        combo = self.ctl(u"Sel3DCombo")
        items, idx = core.combo_3d_items(views, self.w.settings.get(u"iso3d_view") or u"")
        self.filling_3d = True
        try:
            combo.Items.Clear()
            for uid, label in items:
                it = ComboBoxItem()
                it.Content = label
                it.Tag = uid
                combo.Items.Add(it)
            combo.SelectedIndex = idx
        finally:
            self.filling_3d = False

    def _on_3d_choice(self, sender, e):
        if self.filling_3d:
            return
        self.w.settings[u"iso3d_view"] = self._chosen_3d()
        self.w._save()

    def _chosen_3d(self):
        it = self.ctl(u"Sel3DCombo").SelectedItem
        return u"{0}".format(it.Tag or u"") if it is not None else u""

    def _iso3d_off(self):
        self.iso3d = None
        self.iso3d_id = None
        self.iso3d_name = u""
        self.col3d = False
        self.last_iso3d = None
        self.last_col3d = None

    def _on_iso3d(self, sender, e):
        if self.iso3d_busy:
            return
        if self.iso3d is not None:
            key = self.iso3d
            vid = self.iso3d_id
            name = self.iso3d_name
            self._iso3d_off()
            clear = self.col_auto and not self.iso_on
            if clear:
                self.col_on = False
                self.col_auto = False
                self.last_col = None
            self._refresh_view_buttons()

            def job(uiapp):
                n = 0
                for here, doc in rv.open_documents(uiapp):
                    if here != key[0]:
                        continue
                    rv.reset_isolate_view(doc, self.iso_views.pop(key, vid), self.w.log)
                    self.hide_views.pop(key, None)
                    if key in self.boxes:
                        rv.restore_section_box(doc, self.boxes[key][0], self.boxes.pop(key)[1], self.w.log)
                    if key in self.snapshots:
                        view_id, snap = self.snapshots[key]
                        n += rv.restore_overrides(doc, view_id, snap, self.w.log)
                        if not snap:
                            del self.snapshots[key]
                if clear:
                    n += self._restore_all(uiapp)
                try:
                    uiapp.ActiveUIDocument.RefreshActiveView()
                except Exception:
                    pass
                return n

            def done(n, err):
                self._refresh_view_buttons()
                self.w._status(u"Could not reset the 3D isolate - see debug" if err else
                               u"3D isolate reset in {0}".format(name))
                self._check_view()

            self._view_job(u"reset 3D isolate", job, done, u"Resetting the 3D isolate")
            return
        if not self._has():
            self.w._status(u"Nothing to isolate - Refresh from view")
            return
        uid = self._chosen_3d()
        self.iso3d_busy = True
        if not self.col_on:
            # isolating shows the colours: Colour systems on (off again with the reset)
            self.col_on = True
            self.col_auto = True
        self._refresh_view_buttons()

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            d = self.st()[u"data"]
            if d is None or rv.doc_key(doc) != d.get(u"doc_key"):
                raise Exception(u"The active project is not the one the systems were read from - Refresh from view")
            view = rv.view_by_uid(doc, uid) or rv.default_3d(doc)
            created = view is None
            if created:
                view = rv.create_default_3d(doc, self.w.log)
            key = (rv.doc_key(doc), rv.eid_value(view.Id))
            groups = self._colour_groups()
            entry = self.snapshots.setdefault(key, (view.Id, {}))
            rv.colour_systems(doc, view, groups, entry[1], self.w.log)
            self._absorb(key)
            ids = self._isolate_ids()
            old_box = rv.fit_section_box(doc, view, ids, self.w.log)
            boxed = old_box is not None
            if boxed and key not in self.boxes:
                self.boxes[key] = (view.Id, old_box)
            n = rv.isolate_systems(uidoc, ids, self.w.log, view)
            self.iso_views[key] = view.Id
            self.hide_views.pop(key, None)
            self.iso3d = key
            self.iso3d_id = view.Id
            self.iso3d_name = rv.elem_name(view)
            self.col3d = True
            self.last_col3d = self._col_sig(key, groups)
            self.last_iso3d = self._iso_sig(key, ids)
            if rv.eid_value(doc.ActiveView.Id) != key[1]:
                uidoc.RequestViewChange(view)   # opens once this event returns
            return {u"n": n, u"name": self.iso3d_name, u"created": created, u"id": view.Id,
                    u"views3d": rv.views_3d(doc) if created else None, u"boxed": boxed}

        def done(res, err):
            self.iso3d_busy = False
            if (err or res is None) and self.col_auto and not self.iso_on and self.iso3d is None:
                self.col_on = False   # nothing isolated: the colours it turned on go off again
                self.col_auto = False
            self._refresh_view_buttons()
            if err or res is None:
                self.w._status(self._why(err, u"Could not isolate in 3D"))
                return
            if res[u"views3d"] is not None:
                self.fill_3d_combo(res[u"views3d"])
            self.stale = False
            self._refresh_view_buttons()
            self.w._status(u"Isolated {0} elements and tags in {1}{2}, coloured by system{3}".format(
                res[u"n"], res[u"name"], u" (new 3D view)" if res[u"created"] else u"",
                u", section box fitted to them" if res.get(u"boxed") else u""))
            vid = res[u"id"]
            # the view opens after the isolate job returns: zoom in a job of its own
            self.w.runner.queue(u"zoom 3D", lambda uiapp: rv.zoom_view(uiapp.ActiveUIDocument, vid),
                                lambda r, e2: None)

        self._view_job(u"isolate in 3D", job, done, u"Isolating the systems in 3D")

    def _reset_isolates(self, uiapp, skip=None):
        """Reset every isolate this tool made, in every open document - all but
        skip, the Isolate in 3D view, which has its own button."""
        n = 0
        for here, doc in rv.open_documents(uiapp):
            for key in list(self.iso_views):
                if key[0] != here or key == skip:
                    continue
                if rv.reset_isolate_view(doc, self.iso_views.pop(key), self.w.log):
                    n += 1
                self.hide_views.pop(key, None)   # the reset also undid any temporary hide
        try:
            uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception:
            pass
        return n

    def _show_hidden(self, uiapp):
        """Undo the temporary hides Remove made, in the views it made them."""
        for here, doc in rv.open_documents(uiapp):
            for key in list(self.hide_views):
                if key[0] == here:
                    rv.reset_isolate_view(doc, self.hide_views.pop(key), self.w.log)
        try:
            uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception:
            pass

    def _on_colour(self, sender, e):
        if self.col_on or self.leftovers:
            # off: this session's colours put back, and any left from before taken off
            self.col_on = False
            self.col_auto = False
            self.last_col = None
            self._refresh_view_buttons()

            def job(uiapp):
                return self._restore_all(uiapp, skip=self.iso3d) + self._clear_leftovers(uiapp, skip=self.iso3d)

            def done(n, err):
                self._refresh_view_buttons()
                self.w._status(u"Could not clear the colours - see debug" if err else
                               u"Colours cleared from {0} elements".format(n))

            self._view_job(u"clear colours", job, done, u"Clearing the system colours")
            return
        if not self._has():
            return
        self.col_on = True
        self.col_auto = False
        self._refresh_view_buttons()
        self._request_sync()

    def _on_remove(self, sender, e):
        st = self.st()
        if st[u"data"] is None:
            return
        keys = list(self.user_sel)
        idmap = st[u"data"][u"idmap"]
        if not keys:
            if selection_hooked(self.hooks):
                # Revit reports every selection; nothing lit means nothing of the
                # user's own is selected (the tool's own row selections never count)
                self.w._status(u"Select elements of the sequence in the view first")
                return

            # no selection event (older Revit): read the selection now
            def read(uiapp):
                return [rv.eid_value(i) for i in rv.selected_ids(uiapp.ActiveUIDocument)]

            def got(values, err):
                seq = [k for sd in self.on_systems() for k in sd[u"num"] if self.include(k)]
                self.user_sel = core.user_selection(values or [], self.own_sel, seq)
                if self.user_sel:
                    self._on_remove(None, None)
                else:
                    self.w._status(u"Select elements of the sequence in the view first")

            self._view_job(u"read selection", read, got, u"Reading the Revit selection")
            return
        st[u"left_out"].update(keys)
        st[u"reorder_due"] = True   # the order may want working out again
        self.user_sel = []
        self.own_sel = set()
        ids = [idmap[k] for k in keys if k in idmap]
        isolated = self.iso_on

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            rv.select_and_show(uidoc, [], False)
            doc = uidoc.Document
            in_3d = self.iso3d is not None and (rv.doc_key(doc), rv.eid_value(doc.ActiveView.Id)) == self.iso3d
            # isolated views drop them in the re-isolate the sync makes
            if not isolated and not in_3d:
                self._same_view(uiapp)
                rv.hide_temporary(uidoc, ids, self.w.log)
                view = uidoc.Document.ActiveView
                self.hide_views[(rv.doc_key(uidoc.Document), rv.eid_value(view.Id))] = view.Id
            return len(ids)

        def done(n, err):
            self._refresh_view_buttons()
            self.w._status(self._why(err, u"Removed from the sequence, but could not hide them") if err else
                           u"{0} element(s) removed from the sequence and hidden".format(n))

        self._view_job(u"remove from sequence", job, done, u"Removing from the sequence")
        # when isolated, the isolate is rebuilt without them by the sync recompute asks for
        self.recompute()

    def _on_restore(self, sender, e):
        """Everything removed comes back, on both tabs - unhiding a view
        brings back what either tab hid in it."""
        n = 0
        for kind in core.KINDS:
            st = self.state[kind]
            n += len(st[u"left_out"])
            st[u"left_out"] = set()
            st[u"systems"] = core.bring_back(st[u"systems"], st[u"gone"])
            st[u"gone"] = []
            st[u"reorder_due"] = True
        if self.hide_views:
            hidden = set(self.hide_views)
            kind = self.kind

            # one job: unhide, then read again if the active view was a hidden one,
            # so the systems that left with their elements come back
            def job(uiapp):
                self._show_hidden(uiapp)
                doc = uiapp.ActiveUIDocument.Document
                here = (rv.doc_key(doc), rv.eid_value(doc.ActiveView.Id))
                if here in hidden and here not in self.iso_views:
                    return self._read_job(kind)(uiapp)
                return None

            def done(res, err):
                if res is not None and not err:
                    self._loaded(res, None)
                self._refresh_view_buttons()

            self._view_job(u"show removed", job, done, u"Showing the removed elements")
        self.recompute()
        self.w._status(u"{0} element(s) back in the sequence".format(n))

    def _absorb(self, key):
        """Left-over colours this session has now coloured over are in its
        record (as no override), so clearing takes them off."""
        left = self.leftovers.get(key)
        if not left:
            return
        snap = self.snapshots.get(key, (None, {}))[1]
        rest = [i for i in left[1] if rv.eid_value(i) not in snap]
        if rest:
            self.leftovers[key] = (left[0], rest)
        else:
            self.leftovers.pop(key, None)

    def _clear_leftovers(self, uiapp, skip=None):
        """Take off the colours an earlier session left, in every open document."""
        n = 0
        for here, doc in rv.open_documents(uiapp):
            for key in list(self.leftovers):
                if key[0] != here or key == skip:
                    continue
                view_id, ids = self.leftovers.pop(key)
                n += rv.clear_overrides(doc, view_id, ids, self.w.log)
        try:
            uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception:
            pass
        return n

    def _why(self, err, fallback):
        """Our own refusals carry a message worth showing; anything else is in the debug log."""
        text = u"{0}".format(err or u"")
        if u"Refresh from view" in text:
            return u"The active view changed - Refresh from view first"
        return fallback + u" - see debug"

    def _restore_all(self, uiapp, skip=None):
        """Put back the colours in every open document, each into the document
        it was taken from (never written into the wrong file). skip: a view
        left coloured (the Isolate in 3D view, while it is on)."""
        n = 0
        for here, doc in rv.open_documents(uiapp):
            for key in list(self.snapshots):
                if key[0] != here or key == skip:
                    continue
                view_id, snap = self.snapshots[key]
                n += rv.restore_overrides(doc, view_id, snap, self.w.log)
                if not snap:
                    del self.snapshots[key]
        try:
            uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception:
            pass
        return n

    def after_run(self, uiapp):
        """Run finished: turn the temporary colours off again - the 3D view's
        too. Isolates stay until reset."""
        self.col_on = False
        self.col_auto = False
        self.last_col = None
        self.col3d = False
        self.last_col3d = None
        n = self._restore_all(uiapp)
        return n + self._clear_leftovers(uiapp)

    def after_run_ui(self):
        self._refresh_view_buttons()

    def colours_on(self):
        return any([bool(snap) for vid, snap in self.snapshots.values()]) or bool(self.leftovers)

    def _refresh_view_buttons(self):
        has = self._has()
        iso = self.ctl(u"SelIsolateBtn")
        if self.iso_on:
            ui.set_button(iso, u"unisolate", u"Reset 2D isolate")
            iso.SetResourceReference(FrameworkElement.StyleProperty, u"ActiveButton")
        else:
            ui.set_button(iso, u"isolate", u"Isolate Systems 2D")
            iso.SetResourceReference(FrameworkElement.StyleProperty, u"ToolButton")
        iso.IsEnabled = has or self.iso_on or bool(self.iso_views)
        col = self.ctl(u"SelColourBtn")
        left = sum([len(v[1]) for k, v in self.leftovers.items() if k != self.iso3d])
        if self.col_on:
            # the row is kept compact: the colour toggle is its icon, orange while on
            ui.set_button(col, u"uncolour", u"")
            col.SetResourceReference(FrameworkElement.StyleProperty, u"ActiveButton")
            col.ToolTip = u"Colours on - press to take the system colours off the view"
        elif left:
            # colours left in the view by an earlier session: one press takes them off
            ui.set_button(col, u"uncolour", u"{0}".format(left))
            col.SetResourceReference(FrameworkElement.StyleProperty, u"ActiveButton")
            col.ToolTip = u"Clear colours: {0} elements still carry colours from an earlier session - press to take them off".format(left)
        else:
            ui.set_button(col, u"colour", u"")
            col.SetResourceReference(FrameworkElement.StyleProperty, u"ToolButton")
            col.ToolTip = (u"Colour systems: each system in the view in its swatch colour; the start is drawn "
                           u"heavy in magenta. Press again to clear.")
        col.IsEnabled = has or self.col_on or bool(left)
        b3 = self.ctl(u"SelIso3DBtn")
        if self.iso3d is not None:
            ui.set_button(b3, u"cube", u"Reset 3D isolate", STEP_ISO3D)
            b3.SetResourceReference(FrameworkElement.StyleProperty, u"ActiveButton")
            b3.ToolTip = u"Reset the isolate and colours in {0}".format(self.iso3d_name)
        else:
            ui.set_button(b3, u"cube", u"Isolate 3D", STEP_ISO3D)
            b3.SetResourceReference(FrameworkElement.StyleProperty, u"GreenFillButton")
            b3.ToolTip = (u"Open the 3D view chosen beside it, isolate the ticked systems there, fit its "
                          u"section box to them and colour them. Press again to reset that 3D view.")
        b3.IsEnabled = (has or self.iso3d is not None) and not self.iso3d_busy
        rem = self.ctl(u"SelRemoveBtn")
        if self.user_sel:
            ui.set_button(rem, u"hide", u"Remove from sequence ({0})".format(len(self.user_sel)))
            rem.SetResourceReference(FrameworkElement.StyleProperty, u"RedActiveButton")
        else:
            ui.set_button(rem, u"hide", u"Remove from sequence")
            rem.SetResourceReference(FrameworkElement.StyleProperty, u"RedButton")
        rem.IsEnabled = has
        res = self.ctl(u"SelRestoreBtn")
        out = len(self.st()[u"left_out"])
        ui.set_button(res, u"restore", u"{0}".format(out) if out else u"")
        res.IsEnabled = out > 0 or bool(self.hide_views) or bool(self.st()[u"gone"])
        ref = self.ctl(u"SelRefreshBtn")
        if self.stale:
            ui.set_button(ref, u"refresh", u"Refresh - view changed")
            ref.SetResourceReference(FrameworkElement.StyleProperty, u"HotButton")
        else:
            ui.set_button(ref, u"refresh", u"Refresh from view")
            ref.SetResourceReference(FrameworkElement.StyleProperty, u"AccentButton")

    def on_closed(self):
        """Closing the window resets the isolate and puts the view colours back."""
        try:
            if AppDomain.CurrentDomain.GetData(TARGET_KEY) is self:
                AppDomain.CurrentDomain.SetData(TARGET_KEY, None)
        except Exception:
            pass
        remove_hooks(self.w.uiapp, self.hooks, self.w.log)
        if not self.iso_views and not self.colours_on() and not self.hide_views and not self.boxes:
            return
        log = self.w.log

        def job(uiapp):
            n = 0
            # colours first, each step on its own: a view that will not reset
            # must never leave the colours on
            for name, step in ((u"colours", lambda: self._restore_all(uiapp)),
                               (u"left-over colours", lambda: self._clear_leftovers(uiapp))):
                try:
                    n += step() or 0
                except Exception:
                    log.add(u"close: {0} failed: {1}".format(name, traceback.format_exc()))
            for here, doc in rv.open_documents(uiapp):
                for key in list(self.iso_views):
                    if key[0] == here:
                        try:
                            rv.reset_isolate_view(doc, self.iso_views.pop(key), self.w.log)
                        except Exception:
                            log.add(u"close: isolate reset failed: " + traceback.format_exc())
                        self.hide_views.pop(key, None)
            try:
                self._show_hidden(uiapp)
            except Exception:
                log.add(u"close: unhide failed: " + traceback.format_exc())
            for here, doc in rv.open_documents(uiapp):
                for key in list(self.boxes):
                    if key[0] == here:
                        view_id, box = self.boxes.pop(key)
                        try:
                            rv.restore_section_box(doc, view_id, box, log)
                        except Exception:
                            log.add(u"close: section box failed: " + traceback.format_exc())
            log.add(u"close: tidied, {0} colours off".format(n))
            log.write()
            return n

        def done(r, err):
            if self.w in _CLOSING:
                _CLOSING.remove(self.w)

        # held until the job has run: nothing else references a closed window
        _CLOSING.append(self.w)
        queued = False
        try:
            queued = self.w.runner.queue(u"tidy the view on close", job, done)
        except Exception:
            log.add(u"close: queue failed: " + traceback.format_exc())
        if not queued:
            # Revit refused the event: do it the next time Revit is idle
            def idle(uiapp):
                try:
                    job(uiapp)
                finally:
                    done(None, None)
            run_when_idle(self.w.uiapp, idle, log)

    # ---------------------------------------------------- family tree
    def _tree_changed(self):
        self.w._save()
        self.recompute()

    def _on_search(self, sender, e):
        self.st()[u"tree"].build()

    def _on_expand_all(self, sender, e):
        self.st()[u"tree"].expand_all()

    def _on_collapse_all(self, sender, e):
        self.st()[u"tree"].collapse_all()

    def _on_tick_all(self, sender, e):
        self.st()[u"tree"].tick_all()

    def _on_untick_all(self, sender, e):
        self.st()[u"tree"].untick_all()
