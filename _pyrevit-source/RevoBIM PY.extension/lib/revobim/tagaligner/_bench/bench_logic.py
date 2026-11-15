# -*- coding: utf-8 -*-
"""Tag Aligner bench_logic: the rules and whole runs against a simulated model.

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the code on purpose (monkeypatch
                                      or source edit) and prove a check fails

The stub model is deliberately awkward: a tag's text box is offset from its
head (as a family origin usually is), a leader's end and elbow make the view
box bigger (as Revit's do), boxes only update on Regenerate, and
transactions really roll back.
"""
from __future__ import print_function

import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import stubs  # noqa: E402

stubs.install()
from stubs import (XYZ, Document, IndependentTag, SpatialElementTag, View,  # noqa: E402
                   UIDocument, Family, FamilySymbol, FamilyDoc, TextElement,
                   TextElementType, ElementId)

MM = 1.0 / 304.8
CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def load():
    """Fresh copies of the tool modules (from LIB, or a patched folder)."""
    stubs.uninstall_tool_modules()
    folder = getattr(load, "folder", LIB)
    if folder in sys.path:
        sys.path.remove(folder)
    sys.path.insert(0, folder)
    import ta_core, ta_model, ta_ops, ta_theme  # noqa: E401
    return ta_core, ta_model, ta_ops, ta_theme


class Log(object):
    def __init__(self):
        self.lines = []

    def add(self, t):
        self.lines.append(t)


def settings(core, **over):
    s = core.default_settings()
    s.update(over)
    return s


def world(scale=50, right=None, up=None, workshared=False):
    doc = Document(workshared=workshared)
    view = View(doc, 1, right or XYZ(1, 0, 0), up or XYZ(0, 1, 0), scale)
    uidoc = UIDocument(doc, view)
    return doc, view, uidoc


def text_box(view, tag):
    """The text box exactly as Revit would draw it now (leader ignored)."""
    pts = tag._text_box(view, tag._head)
    us = [p.DotProduct(view.RightDirection) for p in pts]
    vs = [p.DotProduct(view.UpDirection) for p in pts]
    return min(us), max(us), min(vs), max(vs)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ==========================================================================
# Pure rules
# ==========================================================================

@check
def align_rules():
    core = load()[0]
    B = core.Box
    boxes = [B(1, 0.0, 2.0, 0, 1), B(2, 3.0, 4.0, 2, 3), B(3, 6.0, 9.0, 4, 5)]
    d = dict(core.align_deltas(boxes, u"left", u"first"))
    assert d == {1: 0.0, 2: -3.0, 3: -6.0}, d
    d = dict(core.align_deltas(boxes, u"right", u"average"))
    assert near(d[1], 5.0 - 2.0) and near(d[3], 5.0 - 9.0), d
    d = dict(core.align_deltas(boxes, u"centre", u"pick", B(9, 10.0, 12.0, 0, 1)))
    assert near(d[1], 10.0) and near(d[2], 7.5), d


@check
def untangle_gap_rule():
    core = load()[0]
    B = core.Box
    th = 1.0
    # three single line tags (height 1) piled on top of each other
    boxes = [B(1, 0, 4, 0.0, 1.0), B(2, 0, 4, 0.3, 1.3), B(3, 0, 4, 0.6, 1.6)]
    d, order = core.untangle_deltas(boxes, u"vertical", th, u"gap", 0.5, 1.5, u"centre")
    d = dict(d)
    new = dict((b.key, b.vc + d[b.key]) for b in boxes)
    assert order == [3, 2, 1], order                     # top to bottom
    assert near(new[3] - new[2], 1.5) and near(new[2] - new[1], 1.5), new  # TH + TH/2
    old_mean = sum(b.vc for b in boxes) / 3.0
    assert near(sum(new.values()) / 3.0, old_mean)       # centred on the group
    d2 = dict(core.untangle_deltas(boxes, u"vertical", th, u"gap", 0.5, 1.5, u"first")[0])
    assert near(d2[3], 0.0)                              # top tag stays


@check
def untangle_multiline_never_overlaps():
    core = load()[0]
    B = core.Box
    boxes = [B(1, 0, 4, 0, 3.0), B(2, 0, 4, 0.5, 1.5), B(3, 0, 4, 1, 2)]
    for mode in (u"gap", u"pitch"):
        d = dict(core.untangle_deltas(boxes, u"vertical", 1.0, mode, 0.5, 1.5, u"centre")[0])
        moved = sorted((b.shifted(dv=d[b.key]) for b in boxes), key=lambda b: -b.vc)
        for a, b in zip(moved, moved[1:]):
            assert a.vmin >= b.vmax - 1e-9, (mode, a, b)


@check
def untangle_horizontal_uses_width():
    core = load()[0]
    B = core.Box
    boxes = [B(1, 0, 6, 0, 1), B(2, 1, 3, 0, 1), B(3, 2, 5, 0, 1)]
    d = dict(core.untangle_deltas(boxes, u"horizontal", 1.0, u"gap", 0.5, 1.5, u"first")[0])
    moved = sorted((b.shifted(du=d[b.key]) for b in boxes), key=lambda b: b.uc)
    gaps = [b.umin - a.umax for a, b in zip(moved, moved[1:])]
    assert all(near(g, 0.5) for g in gaps), gaps
    assert all(near(b.vc, 0.5) for b in moved)


@check
def settings_round_trip():
    core = load()[0]
    folder = tempfile.mkdtemp(prefix="ta_set_")
    path = os.path.join(folder, "s.txt")
    s = core.default_settings()
    s[u"v_gap"] = 0.75
    s[u"align_reference"] = u"average"
    core.save_settings(s, path)
    back = core.load_settings(path)
    assert back[u"v_gap"] == 0.75 and back[u"align_reference"] == u"average"
    with io.open(path, "a", encoding="utf-8") as h:
        h.write(u"v_pitch=banana\nunknown_key=1\nh_mode=sideways\n")
    back = core.load_settings(path)
    assert back[u"v_pitch"] == 1.5 and back[u"h_mode"] == u"gap"   # key by key
    assert core.parse_settings_text(u"a=b=c")[u"a"] == u"b=c"       # first '=' only
    core.MIGRATIONS[2] = [u"v_gap"]
    old = core.SETTINGS_VERSION
    core.SETTINGS_VERSION = 2
    try:
        assert core.load_settings(path)[u"v_gap"] == 0.5             # reset by migration
    finally:
        core.SETTINGS_VERSION = old
        del core.MIGRATIONS[2]


@check
def theme_follows_canvas():
    _, _, _, theme = load()
    ui = sys.modules["Autodesk.Revit.UI"]
    mgr = ui.UIThemeManager
    keep = (mgr.CurrentCanvasTheme, mgr.CurrentTheme)
    try:
        mgr.CurrentCanvasTheme = ui.UITheme.Dark
        assert theme.canvas_is_dark() is True
        assert theme.resolve(u"follow") == u"dark"
        mgr.CurrentCanvasTheme = ui.UITheme.Light
        assert theme.resolve(u"follow") == u"light"
        mgr.CurrentCanvasTheme = None
        mgr.CurrentTheme = ui.UITheme.Light
        assert theme.resolve(u"follow") == u"light"           # falls back to UI theme
        assert theme.resolve(u"dark") == u"dark" and theme.resolve(u"light") == u"light"
        assert theme.next_mode(u"follow") == u"dark" and theme.next_mode(u"light") == u"follow"
    finally:
        mgr.CurrentCanvasTheme, mgr.CurrentTheme = keep


@check
def report_visibility():
    core = load()[0]
    r = core.Report(u"x")
    r.ok(u"fine")
    assert not r.should_show(u"needed") and r.should_show(u"always")
    r.warn(u"look")
    assert r.should_show(u"needed") and not r.should_show(u"never")
    r.cancelled = True
    assert not r.should_show(u"always")


# ==========================================================================
# Whole runs against the simulated model
# ==========================================================================

def three_tags(doc, view, leader_on_second=True):
    a = IndependentTag(doc, 101, view, XYZ(0.0, 0.0, 0), 1.2, 0.25)
    b = IndependentTag(doc, 102, view, XYZ(2.0, 1.0, 0), 0.8, 0.25,
                       leader_end=XYZ(-6.0, -4.0, 0) if leader_on_second else None,
                       elbow=XYZ(1.0, 1.1, 0) if leader_on_second else None)
    c = IndependentTag(doc, 103, view, XYZ(-1.5, 2.0, 0), 1.6, 0.25)
    return a, b, c


@check
def align_left_measures_without_leader():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a, b, c = three_tags(doc, view)
    elbow_before = b.GetLeaderElbow(b._ref)
    uidoc.Selection.ids = [a.Id, b.Id, c.Id]
    v_before = [text_box(view, t)[2] for t in (a, b, c)]
    r = ops.run(uidoc, u"align_left", settings(core), Log())
    assert r.moved == 2 and not r.needs_look, r.lines
    lefts = [text_box(view, t)[0] for t in (a, b, c)]
    assert near(lefts[0], lefts[1]) and near(lefts[0], lefts[2]), lefts
    assert [text_box(view, t)[2] for t in (a, b, c)] == v_before   # no vertical move
    assert b.HasLeader, "leader not restored after measuring"
    moved = text_box(view, b)[0] - (2.0 + 0.3 * 0.8)
    expected_elbow = elbow_before.Add(XYZ(lefts[1] - (2.0 + 0.3 * 0.8) + 0, 0, 0))
    assert near(b.GetLeaderElbow(b._ref).X, elbow_before.X + (lefts[1] - (2.0 + 0.24))), moved
    assert near(b.GetLeaderElbow(b._ref).Y, expected_elbow.Y)
    assert [e.Value for e in uidoc.Selection.ids] == [101, 102, 103]  # selection kept


@check
def align_right_average_and_centre():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a, b, c = three_tags(doc, view, leader_on_second=False)
    rights = [text_box(view, t)[1] for t in (a, b, c)]
    uidoc.Selection.ids = [a.Id, b.Id, c.Id]
    ops.run(uidoc, u"align_right", settings(core, align_reference=u"average"), Log())
    now = [text_box(view, t)[1] for t in (a, b, c)]
    assert all(near(x, sum(rights) / 3.0) for x in now), now
    ops.run(uidoc, u"align_centre", settings(core), Log())
    cs = [(lambda bx: (bx[0] + bx[1]) / 2.0)(text_box(view, t)) for t in (a, b, c)]
    assert near(cs[0], cs[1]) and near(cs[1], cs[2]), cs


@check
def rotated_view_uses_view_axes():
    core, model, ops, _ = load()
    right = XYZ(0.8, 0.6, 0)
    up = XYZ(-0.6, 0.8, 0)
    doc, view, uidoc = world(right=right, up=up)
    a, b, c = three_tags(doc, view, leader_on_second=False)
    uidoc.Selection.ids = [a.Id, b.Id, c.Id]
    vs = [text_box(view, t)[2] for t in (a, b, c)]
    ops.run(uidoc, u"align_left", settings(core), Log())
    lefts = [text_box(view, t)[0] for t in (a, b, c)]
    assert near(lefts[0], lefts[1]) and near(lefts[1], lefts[2]), lefts
    assert all(near(x, y) for x, y in zip(vs, [text_box(view, t)[2] for t in (a, b, c)]))


@check
def pick_reference_outside_selection():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a, b, c = three_tags(doc, view, leader_on_second=False)
    ref = IndependentTag(doc, 120, view, XYZ(5.0, 5.0, 0), 1.0, 0.25)
    uidoc.Selection.ids = [a.Id, b.Id]
    uidoc.Selection.pick_one = ref
    ops.run(uidoc, u"align_left", settings(core, align_reference=u"pick"), Log())
    target = text_box(view, ref)[0]
    assert near(text_box(view, a)[0], target) and near(text_box(view, b)[0], target)
    assert near(ref._head.X, 5.0)                        # reference untouched
    uidoc.Selection.pick_one = "cancel"
    r = ops.run(uidoc, u"align_left", settings(core, align_reference=u"pick"), Log())
    assert r.cancelled and not r.should_show(u"always")


@check
def untangle_vertical_scaled_text_height():
    core, model, ops, _ = load()
    doc, view, uidoc = world(scale=100)
    th_paper = 2.5 * MM
    h = th_paper * 100 * 1.0                              # single line box = TH
    tags = [IndependentTag(doc, 200 + i, view, XYZ(0.1 * i, 0.02 * i, 0), 1.0, h)
            for i in range(4)]
    uidoc.Selection.ids = [t.Id for t in tags]
    r = ops.run(uidoc, u"untangle_v",
                settings(core, text_height_source=u"fixed", text_height_mm=2.5), Log())
    assert r.moved >= 3 and not r.needs_look, r.lines
    boxes = sorted((text_box(view, t) for t in tags), key=lambda b: -b[2])
    centres = [(b[2] + b[3]) / 2.0 for b in boxes]
    steps = [x - y for x, y in zip(centres, centres[1:])]
    want = h + 0.5 * th_paper * 100                       # TH + TH/2 at 1:100
    assert all(near(s, want, 1e-9) for s in steps), (steps, want)
    xs = [t._head.X for t in tags]
    assert xs == [0.1 * i for i in range(4)]              # sideways untouched


@check
def untangle_horizontal_reads_family_text():
    core, model, ops, _ = load()
    doc, view, uidoc = world(scale=50)
    fam = Family(doc, 300)
    sym = FamilySymbol(doc, 301, fam)
    fdoc = FamilyDoc(doc)
    ttype = TextElementType(fdoc, 1)
    ttype._params["TEXT_SIZE"] = 3.5 * MM
    label = TextElement(fdoc, 2)
    label._type_id = ttype.Id
    doc.families[300] = fdoc
    tags = []
    for i, w in enumerate((1.0, 2.0, 1.5)):
        t = IndependentTag(doc, 310 + i, view, XYZ(0.2 * i, 0, 0), w, 0.2)
        t._type_id = sym.Id
        tags.append(t)
    uidoc.Selection.ids = [t.Id for t in tags]
    log = Log()
    ops.run(uidoc, u"untangle_h", settings(core), log)
    assert doc.edit_family_inside_tx == 0
    assert doc.closed_family_docs == 1, "family document left open"
    boxes = sorted((text_box(view, t) for t in tags), key=lambda b: b[0])
    gaps = [b2[0] - b1[1] for b1, b2 in zip(boxes, boxes[1:])]
    want = 0.5 * 3.5 * MM * 50
    assert all(near(g, want, 1e-9) for g in gaps), (gaps, want)


@check
def open_family_editor_left_open():
    """A tag family the user has open in the editor is read, never closed."""
    core, model, ops, _ = load()
    doc, view, uidoc = world(scale=50)
    fam = Family(doc, 600)
    fam.Name = "BGL_Pipe Tag"
    sym = FamilySymbol(doc, 601, fam)
    fdoc = FamilyDoc(doc)
    fdoc.IsFamilyDocument = True
    fdoc.OwnerFamily = fam
    fdoc.Title = "BGL_Pipe Tag.rfa"
    ttype = TextElementType(fdoc, 1)
    ttype._params["TEXT_SIZE"] = 2.0 * MM
    doc.families[600] = fdoc

    class App(object):
        Documents = [doc, fdoc]
    doc.Application = App()
    doc.IsFamilyDocument = False
    tags = []
    for i in range(2):
        t = IndependentTag(doc, 610 + i, view, XYZ(0, 0.01 * i, 0), 1.0, 0.1)
        t._type_id = sym.Id
        tags.append(t)
    uidoc.Selection.ids = [t.Id for t in tags]
    log = Log()
    ops.run(uidoc, u"untangle_v", settings(core), log)
    assert doc.closed_family_docs == 0, "closed the user's open family editor"
    assert any(u"2.00 mm" in line for line in log.lines), log.lines


@check
def pinned_and_owned_tags():
    core, model, ops, _ = load()
    doc, view, uidoc = world(workshared=True)
    a, b, c = three_tags(doc, view, leader_on_second=False)
    b.Pinned = True
    doc.owned_by_others.add(103)
    uidoc.Selection.ids = [a.Id, b.Id, c.Id]
    heads = [t._head.X for t in (b, c)]
    r = ops.run(uidoc, u"align_left", settings(core), Log())
    assert [t._head.X for t in (b, c)] == heads, "pinned / owned tag moved"
    text = u" ".join(t for _, t in r.lines)
    assert u"pinned" in text and u"another user" in text and r.needs_look
    doc.owned_by_others.clear()
    r = ops.run(uidoc, u"align_left", settings(core, pinned=u"unpin"), Log())
    assert near(text_box(view, b)[0], text_box(view, a)[0]) and b.Pinned


@check
def room_tag_single_elbow():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a = IndependentTag(doc, 401, view, XYZ(0, 0, 0), 1.0, 0.25)
    rt = SpatialElementTag(doc, 402, view, XYZ(3, 1, 0), 1.0, 0.25,
                           leader_end=XYZ(8, -3, 0), elbow=XYZ(2.5, 1.1, 0))
    uidoc.Selection.ids = [a.Id, rt.Id]
    ops.run(uidoc, u"align_left", settings(core), Log())
    shift = text_box(view, rt)[0] - (3 + 0.3)
    assert near(text_box(view, rt)[0], text_box(view, a)[0])
    assert near(rt.LeaderElbow.X, 2.5 + shift) and rt.HasLeader


@check
def no_leader_moves_whole_tag():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a, b, c = three_tags(doc, view, leader_on_second=False)
    uidoc.Selection.ids = [a.Id, b.Id, c.Id]
    ops.run(uidoc, u"align_left", settings(core), Log())
    assert b.move_calls == 1 and c.move_calls == 1 and a.move_calls == 0


@check
def refused_commit_moves_nothing():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a, b, c = three_tags(doc, view)
    doc.refuse_commit = True
    heads = [t._head.X for t in (a, b, c)]
    uidoc.Selection.ids = [a.Id, b.Id, c.Id]
    r = ops.run(uidoc, u"align_left", settings(core), Log())
    assert [t._head.X for t in (a, b, c)] == heads and r.moved == 0
    assert any(level == u"error" for level, _ in r.lines)


@check
def nothing_selected_asks_then_cancels():
    core, model, ops, _ = load()
    doc, view, uidoc = world()
    a, b, c = three_tags(doc, view, leader_on_second=False)
    uidoc.Selection.pick_many = [a, b, c]
    r = ops.run(uidoc, u"align_right", settings(core), Log())
    assert r.moved == 2
    assert sorted(e.Value for e in uidoc.Selection.ids) == [101, 102, 103], \
        "picked tags not left selected for the next command"
    uidoc.Selection.ids = []
    uidoc.Selection.pick_many = "cancel"
    r = ops.run(uidoc, u"align_right", settings(core), Log())
    assert r.cancelled


@check
def stubborn_tag_is_reported():
    """A tag Revit silently refuses to move must be reported, not counted."""
    core, model, ops, _ = load()
    doc, view, uidoc = world()

    class Stubborn(IndependentTag):
        @property
        def TagHeadPosition(self):
            return XYZ(self._head.X, self._head.Y, self._head.Z)

        @TagHeadPosition.setter
        def TagHeadPosition(self, p):
            pass

    a = IndependentTag(doc, 501, view, XYZ(0, 0, 0), 1.0, 0.25)
    s = Stubborn(doc, 502, view, XYZ(3, 1, 0), 1.0, 0.25, leader_end=XYZ(5, -2, 0))
    uidoc.Selection.ids = [a.Id, s.Id]
    r = ops.run(uidoc, u"align_left", settings(core), Log())
    assert r.moved == 0 and r.needs_look, r.lines


# ==========================================================================
# Deliberate breakages
# ==========================================================================

def patch(module_name, attr, value):
    def apply():
        mods = load()
        target = dict((m.__name__, m) for m in mods)[module_name]
        setattr(target, attr, value)
    return apply


def source_edit(module_name, old, new):
    """Copy the lib to a temp folder with one edit, and load from there."""
    def apply():
        folder = tempfile.mkdtemp(prefix="ta_break_")
        for n in os.listdir(LIB):
            if n.endswith(".py"):
                with io.open(os.path.join(LIB, n), encoding="utf-8") as h:
                    text = h.read()
                if n == module_name + ".py":
                    assert old in text, "anchor missing: " + old
                    text = text.replace(old, new, 1)
                with io.open(os.path.join(folder, n), "w", encoding="utf-8") as h:
                    h.write(text)
        load.folder = folder
    return apply


BREAKAGES = [
    ("leaders not switched off before measuring",
     source_edit("ta_model", "                    t.HasLeader = False", "                    pass"),
     "align_left_measures_without_leader"),
    ("measuring SubTransaction committed instead of rolled back",
     source_edit("ta_model", "            sub.RollBack()\n", "            pass\n"),
     "align_left_measures_without_leader"),
    ("elbow not carried with the head",
     source_edit("ta_model", "        write_elbow(tag, ref, target)\n", ""),
     "align_left_measures_without_leader"),
    ("world X used instead of RightDirection",
     source_edit("ta_model", "us.append(p.DotProduct(right))", "us.append(p.X)"),
     "rotated_view_uses_view_axes"),
    ("untangle ignores tag size",
     source_edit("ta_core", "    return half_sum + text_height * gap_factor",
                 "    return text_height * gap_factor"),
     "untangle_vertical_scaled_text_height"),
    ("text height not scaled by the view",
     source_edit("ta_core", "    return paper_feet * max(int(scale or 1), 1)", "    return paper_feet"),
     "untangle_vertical_scaled_text_height"),
    ("centre anchor not applied",
     source_edit("ta_core", '    if anchor == u"centre":', '    if anchor == u"never":'),
     "untangle_gap_rule"),
    ("family document left open",
     source_edit("ta_model", "                fdoc.Close(False)", "                pass"),
     "untangle_horizontal_reads_family_text"),
    ("open family editor closed",
     source_edit("ta_model", "        if fdoc is not None and already_open is None:", "        if fdoc is not None:"),
     "open_family_editor_left_open"),
    ("checkout ignored",
     source_edit("ta_model", "        return set(eid_value(i) for i in got)", "        return keys"),
     "pinned_and_owned_tags"),
    ("pinned tags moved anyway",
     source_edit("ta_ops", '        if pinned and settings[u"pinned"] == u"skip":', "        if False:"),
     "pinned_and_owned_tags"),
    ("verification switched off",
     source_edit("ta_core", "    along = abs(", "    along = 0 * abs("),
     "stubborn_tag_is_reported"),
    ("commit status not checked",
     source_edit("ta_ops", "        if status != TransactionStatus.Committed:", "        if False:"),
     "refused_commit_moves_nothing"),
    ("settings split on every '='",
     source_edit("ta_core", 'key, value = line.split(u"=", 1)', 'key, value = line.split(u"=")[:2]'),
     "settings_round_trip"),
    ("canvas theme read by truthiness (UITheme.Dark is 0)",
     source_edit("ta_theme", "        if theme is not None:", "        if theme:"),
     "theme_follows_canvas"),
    ("room tag elbow ignored",
     source_edit("ta_model", '            out.append((None, tag.LeaderElbow))', '            pass'),
     "room_tag_single_elbow"),
    ("selection not restored",
     source_edit("ta_ops", "    model.set_selection(uidoc, tags)\n", ""),
     "nothing_selected_asks_then_cancels"),
    ("align moves tags up and down",
     source_edit("ta_ops", "            vector_of = right\n", "            vector_of = right.Add(up)\n"),
     "align_left_measures_without_leader"),
]


def run_checks():
    failed = {}
    for fn in CHECKS:
        try:
            fn()
        except Exception as ex:
            failed[fn.__name__] = repr(ex)[:300]
    return failed


# Dark must be falsy in the stub, as UITheme.Dark == 0 is in Revit.
type(sys.modules["Autodesk.Revit.UI"].UITheme.Dark).__bool__ = \
    lambda self: self.name != "Dark"


def main(argv):
    load.folder = LIB
    failed = run_checks()
    for name, why in sorted(failed.items()):
        print("FAIL {0}: {1}".format(name, why))
    print("bench_logic: {0} checks, {1} failing".format(len(CHECKS), len(failed)))
    ok = not failed
    if "--selftest" in argv:
        inert = []
        for label, breakage, expected in BREAKAGES:
            load.folder = LIB
            try:
                breakage()
            except AssertionError as ex:
                inert.append("{0}: {1}".format(label, ex))
                continue
            caught = run_checks()
            load.folder = LIB
            if expected not in caught:
                inert.append("{0}: {1} still passes (failing: {2})".format(
                    label, expected, sorted(caught)))
        for line in inert:
            print("INERT " + line)
        print("selftest: {0} breakages, {1} inert".format(len(BREAKAGES), len(inert)))
        ok = ok and not inert
    stubs.uninstall_tool_modules()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
