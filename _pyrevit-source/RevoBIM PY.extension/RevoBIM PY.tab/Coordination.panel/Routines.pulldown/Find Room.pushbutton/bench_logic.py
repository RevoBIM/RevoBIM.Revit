# -*- coding: utf-8 -*-
"""Find Room logic bench - plain CPython against the stub API and a fake model.

    python bench_logic.py            run every check
    python bench_logic.py --selftest break the real source on purpose, one
                                     breakage at a time, and prove the check
                                     meant to catch it fails

A check nobody has seen fail is a check that may not work.
"""
import os
import sys
import types
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402,F401 - installs System / Autodesk stubs
from bench_stubs import (  # noqa: E402
    ElementId, XYZ, Color, OverrideGraphicSettings, Transaction, _Raise,
    UIThemeManager, UITheme_Dark,
)


# =============================================================================
# Fake model
# =============================================================================
class P(object):
    def __init__(self, v):
        self.v = v

    def AsString(self):
        return self.v

    def AsValueString(self):
        return self.v


class Box(object):
    def __init__(self, lo, hi):
        self.Min = XYZ(*lo)
        self.Max = XYZ(*hi)


class Elem(object):
    _next = [100]

    def __init__(self, name=u"", cat=None, kind=None, params=None):
        Elem._next[0] += 1
        self.Id = ElementId(Elem._next[0])
        self.Name = name
        self.cat = cat
        self.kind = kind
        self.params = params or {}
        self.Category = None

    def get_Parameter(self, bip):
        if bip in self.params:
            return P(self.params[bip])
        return None


class Lvl(Elem):
    def __init__(self, name, elev):
        Elem.__init__(self, name, kind="Level")
        self.ProjectElevation = elev


class Room(Elem):
    def __init__(self, number, name, level, area=100.0, box=((0, 0, 0), (10, 10, 3)),
                 placed=True, cat="OST_Rooms"):
        Elem.__init__(self, u"{0} {1}".format(name, number), cat=cat,
                      params={"ROOM_NUMBER": number, "ROOM_NAME": name})
        self.LevelId = level.Id
        self.Area = area
        self.Location = object() if placed else None
        self.box = Box(*box) if box else None

    def get_BoundingBox(self, view):
        return self.box


class Ident(object):
    def __init__(self, dx=0.0, dy=0.0, dz=0.0):
        self.d = (dx, dy, dz)

    def OfPoint(self, p):
        return XYZ(p.X + self.d[0], p.Y + self.d[1], p.Z + self.d[2])

    @property
    def Inverse(self):
        return Ident(-self.d[0], -self.d[1], -self.d[2])


class Crop(object):
    def __init__(self, lo, hi):
        self.Transform = Ident()
        self.Min = XYZ(*lo)
        self.Max = XYZ(*hi)


class View(Elem):
    def __init__(self, name, level, template=False, vtype="FloorPlan", crop=None,
                 locked=False, can_tvp=True):
        Elem.__init__(self, name, kind="ViewPlan", params={"VIEWPORT_SHEET_NUMBER": u""})
        self.IsTemplate = template
        self.ViewType = vtype
        self.GenLevel = level
        self.ViewTemplateId = ElementId(-1)
        self.Scale = 100
        self.CropBoxActive = crop is not None
        self.CropBox = Crop(*crop) if crop else None
        self.hidden = {}
        self.tvp = False
        self.locked = locked              # template-controlled V/G
        self.can_tvp = can_tvp
        self.overrides = {}
        self.filters = {}
        self.disable_calls = 0

    def GetTypeId(self):
        return ElementId(-1)

    def GetPrimaryViewId(self):
        return ElementId(-1)

    # visibility
    def GetCategoryHidden(self, cid):
        return self.hidden.get(cid.Value, True)

    def CanCategoryBeHidden(self, cid):
        return True

    def SetCategoryHidden(self, cid, value):
        if self.locked and not self.tvp:
            raise Exception("controlled by template")
        self.hidden[cid.Value] = value

    # temporary view properties
    def IsTemporaryViewPropertiesModeEnabled(self):
        return self.tvp

    def CanEnableTemporaryViewPropertiesMode(self):
        return self.can_tvp and not self.tvp

    def EnableTemporaryViewPropertiesMode(self, tid):
        if not self.can_tvp:
            raise Exception("no")
        self.tvp = True
        self.saved_hidden = dict(self.hidden)
        return True

    def DisableTemporaryViewMode(self, mode):
        self.disable_calls += 1
        if str(mode) == "TemporaryViewProperties" and self.tvp:
            self.tvp = False
            self.hidden = dict(self.saved_hidden)

    # overrides
    def GetElementOverrides(self, eid):
        return self.overrides.get(eid.Value, OverrideGraphicSettings())

    def SetElementOverrides(self, eid, ogs):
        self.overrides[eid.Value] = ogs

    def IsFilterApplied(self, fid):
        return fid.Value in self.filters

    def AddFilter(self, fid):
        if self.locked and not self.tvp:
            raise Exception("filters controlled by template")
        self.filters[fid.Value] = None

    def RemoveFilter(self, fid):
        self.filters.pop(fid.Value, None)

    def SetFilterVisibility(self, fid, v):
        pass

    def SetFilterOverrides(self, fid, ogs):
        self.filters[fid.Value] = ogs

    def GetFilterOverrides(self, fid):
        return self.filters.get(fid.Value)


class Cat(object):
    def __init__(self, name, value):
        self.Name = name
        self.Id = ElementId(value)
        self.SubCategories = []


class Fill(Elem):
    def __init__(self):
        Elem.__init__(self, u"<Solid fill>", kind="FillPatternElement")

    def GetFillPattern(self):
        f = types.SimpleNamespace()
        f.IsSolidFill = True
        return f


class Filt(Elem):
    def __init__(self, name, cats, ef):
        Elem.__init__(self, name, kind="ParameterFilterElement")
        self.cats, self.ef = cats, ef

    def SetCategories(self, cats):
        self.cats = list(cats)

    def SetElementFilter(self, ef):
        self.ef = ef


class LinkInst(Elem):
    def __init__(self, name, ldoc, tf):
        Elem.__init__(self, name, kind="RevitLinkInstance")
        self.ldoc, self.tf = ldoc, tf

    def GetLinkDocument(self):
        return self.ldoc

    def GetTotalTransform(self):
        return self.tf

    def GetTypeId(self):
        return ElementId(-1)


CAT_IDS = {"OST_Rooms": -2000160, "OST_RoomColorFill": -2000161,
           "OST_RoomInteriorFill": -2000162, "OST_RoomReference": -2000163,
           "OST_MEPSpaces": -2003600, "OST_MEPSpaceColorFill": -2003601,
           "OST_MEPSpaceInteriorFill": -2003602, "OST_MEPSpaceReference": -2003603}


class Doc(object):
    def __init__(self, title=u"Host"):
        self.Title = title
        self.PathName = u"C:\\{0}.rvt".format(title)
        self.IsWorkshared = False
        self.elems = []
        self.cats = dict((k, Cat(k, v)) for k, v in CAT_IDS.items())
        self.held_by_other = set()
        self.add(Fill())

    def add(self, e):
        self.elems.append(e)
        return e

    def GetElement(self, eid):
        for e in self.elems:
            if e.Id.Value == getattr(eid, "Value", eid):
                return e
        return None

    def _by_cat(self, cat):
        return [e for e in self.elems if e.cat == str(cat)]

    def _by_class(self, cls):
        return [e for e in self.elems if e.kind == cls.__name__]

    def _category(self, bic):
        return self.cats.get(str(bic))

    def _new_filter(self, name, cats, ef):
        return self.add(Filt(name, cats, ef))

    def _can_borrow(self, eid):
        return eid.Value not in self.held_by_other


class UIView(object):
    def __init__(self, vid):
        self.ViewId = vid
        self.zooms = []

    def ZoomAndCenterRectangle(self, a, b):
        self.zooms.append(((a.X, a.Y), (b.X, b.Y)))


class UIDoc(object):
    def __init__(self, doc, view):
        self.Document = doc
        self._active = view
        self.uiviews = [UIView(view.Id)]
        self.Selection = types.SimpleNamespace(GetElementIds=lambda: [])

    @property
    def ActiveView(self):
        return self._active

    @ActiveView.setter
    def ActiveView(self, view):
        self._active = view
        if not any(u.ViewId == view.Id for u in self.uiviews):
            self.uiviews.append(UIView(view.Id))

    def GetOpenUIViews(self):
        return list(self.uiviews)

    def RefreshActiveView(self):
        pass

    def RequestViewChange(self, view):
        self._active = view


class App(object):
    def __init__(self, bg=(255, 255, 255)):
        self.VersionNumber = u"2026"
        self.BackgroundColor = Color(*bg)


class UIApp(object):
    def __init__(self, uidoc, bg=(255, 255, 255)):
        self.ActiveUIDocument = uidoc
        self.Application = App(bg)


def model():
    """Host with three levels, two plans on L01 (one cropped away from R2),
    a template, a ceiling plan, rooms, a space; a link shifted 1000 ft east
    and 0.5 ft up with its own levels and rooms."""
    doc = Doc()
    b1 = doc.add(Lvl(u"B1", -10.0))
    l1 = doc.add(Lvl(u"L01", 0.0))
    l2 = doc.add(Lvl(u"L02", 12.0))
    other = doc.add(View(u"Start view", l2))
    v1 = doc.add(View(u"M - L01 Plan", l1))
    v2 = doc.add(View(u"M - L01 Dependent", l1, crop=((0, 0, 0), (5, 5, 5))))
    doc.add(View(u"L01 Template", l1, template=True))
    doc.add(View(u"L01 RCP", l1, vtype="CeilingPlan"))
    doc.add(View(u"M - L02 Plan", l2))
    r1 = doc.add(Room(u"101", u"Office", l1))
    r2 = doc.add(Room(u"102", u"Store", l1, box=((20, 20, 0), (30, 30, 3))))
    doc.add(Room(u"001", u"Plant", b1))
    doc.add(Room(u"9", u"Unplaced", l1, area=0, box=None, placed=False))
    doc.add(Room(u"S1", u"Space one", l1, cat="OST_MEPSpaces"))
    ldoc = Doc(u"Arch")
    ll1 = ldoc.add(Lvl(u"Level 01 (arch)", 0.0))
    ldoc.add(Lvl(u"Level 02 (arch)", 12.0))
    ldoc.add(Room(u"A1", u"Lobby", ll1))
    link = doc.add(LinkInst(u"Arch.rvt", ldoc, Ident(1000.0, 0.0, 0.5)))
    uidoc = UIDoc(doc, other)
    return types.SimpleNamespace(doc=doc, uidoc=uidoc, uiapp=UIApp(uidoc), v1=v1, v2=v2,
                                 r1=r1, r2=r2, l1=l1, link=link, other=other)


# =============================================================================
# Checks - each takes ctx (core, rv, runner modules) and raises on failure
# =============================================================================
def eq(a, b, what):
    if a != b:
        raise AssertionError(u"{0}: expected {1!r}, got {2!r}".format(what, b, a))


def ok(cond, what):
    if not cond:
        raise AssertionError(what)


def check_settings(c):
    s = c.core.parse_settings(u"theme=light\nmodel=A=B.rvt\nbogus=1\n# x\nnoequals\n")
    eq(s[u"theme"], u"light", "theme read")
    eq(s[u"model"], u"A=B.rvt", "split on the first = only")
    ok(u"bogus" not in s, "unknown keys ignored")
    eq(c.core.parse_settings(u"theme=purple")[u"theme"], u"follow", "bad theme falls back")
    eq(c.core.parse_settings(u"")[u"highlight"], u"#E8912D", "defaults")
    old = dict(c.core.MIGRATIONS)
    try:
        c.core.MIGRATIONS.clear()
        c.core.MIGRATIONS[0] = {u"zoom_margin_mm": u"999"}
        eq(c.core.parse_settings(u"settings_version=0\nzoom_margin_mm=5")[u"zoom_margin_mm"],
           u"999", "migration moves old files onto the new default")
        eq(c.core.parse_settings(u"settings_version=1\nzoom_margin_mm=5")[u"zoom_margin_mm"],
           u"5", "current files keep their value")
    finally:
        c.core.MIGRATIONS.clear()
        c.core.MIGRATIONS.update(old)
    text = c.core.format_settings(s)
    eq(c.core.parse_settings(text)[u"model"], u"A=B.rvt", "round trip")


def check_theme(c):
    k = c.core
    eq([k.next_theme_mode(m) for m in (u"follow", u"dark", u"light")],
       [u"dark", u"light", u"follow"], "chip cycles Auto, Dark, Light")
    eq(k.resolve_theme(u"follow", u"light"), u"light", "Auto follows a light canvas")
    eq(k.resolve_theme(u"follow", u"dark"), u"dark", "Auto follows a dark canvas")
    eq(k.resolve_theme(u"follow", None), u"dark", "unreadable canvas -> dark")
    eq(k.resolve_theme(u"light", u"dark"), u"light", "explicit light wins")
    eq(k.theme_from_text(u"Dark"), u"dark", "enum text")
    eq(k.theme_from_rgb(30, 30, 30), u"dark", "dark background")
    eq(k.theme_from_rgb(250, 250, 250), u"light", "light background")
    eq(sorted(k.DARK), sorted(k.LIGHT), "both palettes carry the same keys")


def check_natural(c):
    names = [u"10", u"2", u"1A", u"1"]
    eq(sorted(names, key=c.core.natural_key), [u"1", u"1A", u"2", u"10"], "natural order")


def _rooms(c):
    R = c.core.RoomInfo
    box = ((0, 0, 0), (1, 1, 1))
    return [
        R(u"a", u"10", u"Office", u"L00", u"L00", 0.0, 10, u"ok", box),
        R(u"b", u"2", u"Store", u"L00", u"L00", 0.0, 5, u"ok", box),
        R(u"c", u"R1", u"Plant", u"AR", u"A-Roof", 30.0, 5, u"ok", box),
        R(u"d", u"B01", u"Tank", u"B1", u"B1", -10.0, 5, u"ok", box),
        R(u"e", u"X", u"Ghost", u"L00", u"L00", 0.0, 0, u"unplaced", None),
    ]


def check_rows(c):
    rows, shown, levels = c.core.build_rows(_rooms(c))
    eq([r.level_name for r in rows if r.kind == u"level"], [u"B1", u"L00", u"A-Roof"],
       "levels in elevation order, not by name")
    eq([r.room.number for r in rows if r.kind == u"room" and r.level_key == u"L00"],
       [u"2", u"10"], "rooms in natural number order")
    eq(shown, 4, "unplaced hidden by default")
    rows, shown, _ = c.core.build_rows(_rooms(c), show_unplaced=True)
    eq(shown, 5, "unplaced shown when ticked")
    rows, shown, _ = c.core.build_rows(_rooms(c), collapsed={u"L00"})
    lv = [r for r in rows if r.kind == u"level" and r.level_key == u"L00"][0]
    ok(not lv.expanded, "collapsed level reported shut")
    eq(len([r for r in rows if r.kind == u"room" and r.level_key == u"L00"]), 0,
       "collapsed level hides its rooms")
    eq(lv.count, 2, "collapsed level still counts its rooms")
    rows, shown, levels = c.core.build_rows(_rooms(c), u"office", collapsed={u"L00"})
    eq([r.room.name for r in rows if r.kind == u"room"], [u"Office"],
       "search opens the collapsed level holding a match")
    eq(levels, 1, "levels without a match drop out")
    rows, _, _ = c.core.build_rows(_rooms(c), u"l00 store")
    eq([r.room.name for r in rows if r.kind == u"room"], [u"Store"], "every word must match")


def check_match(c):
    lv = [(1, u"Ground", 0.0), (2, u"First", 10.0), (3, u"Second", 20.0)]
    tol = c.core.mm_to_ft(50)
    keys, how, off = c.core.match_levels(10.0 + c.core.mm_to_ft(30), u"x", lv, tol)
    eq((keys, how), ([2], u"elevation"), "within tolerance matches by height")
    keys, how, off = c.core.match_levels(13.0, u"second", lv, tol)
    eq((keys, how), ([3], u"name"), "name match when no level at that height")
    keys, how, off = c.core.match_levels(13.0, u"zzz", lv, tol)
    eq((keys, how), ([2], u"nearest"), "nearest as a last resort")


def check_views_sort(c):
    V = c.core.ViewInfo
    vs = [V(1, u"B plan"), V(2, u"A plan", in_crop=False), V(3, u"C plan"), V(4, u"D plan")]
    eq([v.key for v in c.core.sort_views(vs, active_key=3, preferred_key=4)], [4, 3, 1, 2],
       "last used, then open now, then by name, cropped-out last")
    eq([v.key for v in c.core.filter_views(vs, u"c plan")], [3], "view search")


def check_geometry(c):
    eq(c.core.pad_box(((0, 0, 0), (1, 1, 1)), 2), ((-2, -2, 0), (3, 3, 1)), "pad on XY")
    ok(c.core.in_crop((1, 1, 0), (0, 0, 0), (2, 2, 0)), "inside crop")
    ok(not c.core.in_crop((3, 1, 0), (0, 0, 0), (2, 2, 0)), "outside crop")
    eq(c.core.classify(0, False), u"unplaced", "no location")
    eq(c.core.classify(0, True), u"not_enclosed", "no area")
    eq(c.core.classify(5, True), u"ok", "placed")


def check_canvas(c):
    m = model()
    m.uiapp.Application.BackgroundColor = Color(255, 255, 255)
    UIThemeManager.CurrentCanvasTheme = UITheme_Dark
    eq(c.rv.canvas_theme(m.uiapp), u"dark",
       "UITheme.Dark is 0 - must be read with `is not None`, not truthiness")


def check_host_read(c):
    m = model()
    host = c.rv.list_models(m.doc)[0]
    rooms, problems = c.rv.read_rooms(m.doc, host, u"rooms")
    eq(len(rooms), 4, "four rooms (the space is not a room)")
    r = [x for x in rooms if x.number == u"101"][0]
    eq(r.key, u"{0}".format(m.r1.Id.Value), "host key is the element id")
    eq(r.level_name, u"L01", "level name")
    ok(abs(r.area_m2 - 9.290304) < 1e-6, "area in m2")
    eq(r.box, ((0, 0, 0), (10, 10, 3)), "box")
    eq([x.state for x in rooms if x.number == u"9"], [u"unplaced"], "unplaced state")
    spaces, _ = c.rv.read_rooms(m.doc, host, u"spaces")
    eq([s.number for s in spaces], [u"S1"], "spaces read from the host")


def check_link_read(c):
    m = model()
    models = c.rv.list_models(m.doc)
    link = [x for x in models if x.is_link][0]
    eq(link.count, 1, "room count on the dropdown")
    rooms, _ = c.rv.read_rooms(m.doc, link, u"rooms")
    eq(len(rooms), 1, "linked rooms")
    r = rooms[0]
    ok(r.key.startswith(u"L"), "linked keys are prefixed")
    eq(r.box, ((1000.0, 0.0, 0.5), (1010.0, 10.0, 3.5)), "box moved into host coordinates")
    ok(abs(r.level_elev - 0.5) < 1e-9, "level elevation moved into host coordinates")


def check_plans(c):
    m = model()
    host = c.rv.list_models(m.doc)[0]
    rooms, _ = c.rv.read_rooms(m.doc, host, u"rooms")
    r2 = [x for x in rooms if x.number == u"102"][0]
    views, how, off, names = c.rv.plans_for_room(m.doc, r2, 0.2)
    eq(sorted(v.name for v in views), [u"M - L01 Dependent", u"M - L01 Plan"],
       "floor plans on the level only - no template, no ceiling plan, no other level")
    eq([v.in_crop for v in views if v.name == u"M - L01 Dependent"], [False],
       "room outside the crop flagged")
    link = [x for x in c.rv.list_models(m.doc) if x.is_link][0]
    lr = c.rv.read_rooms(m.doc, link, u"rooms")[0][0]
    views, how, off, names = c.rv.plans_for_room(m.doc, lr, c.core.mm_to_ft(50) * 4)
    eq(how, u"elevation", "linked room matched by height (0.5 ft = 152 mm, tol 200 mm)")
    eq(names, [u"L01"], "to L01")
    views, how, off, names = c.rv.plans_for_room(m.doc, lr, c.core.mm_to_ft(50))
    eq(how, u"nearest", "outside tolerance: nearest level")


def _room(c, m, number, mode=u"rooms"):
    host = c.rv.list_models(m.doc)[0]
    return [x for x in c.rv.read_rooms(m.doc, host, mode)[0] if x.number == number][0]


S = {u"highlight": u"#112233", u"transparency": u"20", u"zoom_margin_mm": u"1000"}


def check_host_highlight(c):
    m = model()
    r1 = _room(c, m, u"101")
    before = OverrideGraphicSettings()
    m.v1.overrides[m.r1.Id.Value] = before
    res = c.rv.go_to_room(m.uiapp, r1, m.v1.Id, S, None)
    rec = res[u"record"]
    ok(rec is not None, "record kept")
    ok(m.v1.tvp, "Temporary View Properties on")
    for name in (u"OST_Rooms", u"OST_RoomColorFill", u"OST_RoomInteriorFill", u"OST_RoomReference"):
        eq(m.v1.hidden.get(CAT_IDS[name]), False, u"{0} switched on".format(name))
    got = m.v1.overrides[m.r1.Id.Value]
    eq(got.SurfaceForegroundPatternColor.Red, 0x11, "room coloured with the setting")
    ok(m.uidoc.ActiveView is m.v1, "view opened")
    ok(res[u"zoomed"], "zoomed")
    zoom = [u for u in m.uidoc.uiviews if u.ViewId == m.v1.Id][0].zooms[-1]
    eq(zoom, ((-1000 / 304.8, -1000 / 304.8), (10 + 1000 / 304.8, 10 + 1000 / 304.8)),
       "zoom = room box plus margin")
    ok(c.rv.clear(m.uiapp, rec), "clear ran")
    ok(not m.v1.tvp, "Temporary View Properties off again")
    ok(m.v1.overrides[m.r1.Id.Value] is before, "the room's own override put back")
    eq(m.v1.hidden.get(CAT_IDS[u"OST_Rooms"], True), True, "rooms hidden again")


def check_no_tvp(c):
    m = model()
    m.v1.can_tvp = False
    r1 = _room(c, m, u"101")
    res = c.rv.go_to_room(m.uiapp, r1, m.v1.Id, S, None)
    eq(m.v1.hidden.get(CAT_IDS[u"OST_Rooms"]), False, "rooms on without TVP")
    ok(res[u"msgs"], "says Temporary View Properties could not be used")
    c.rv.clear(m.uiapp, res[u"record"])
    eq(m.v1.hidden.get(CAT_IDS[u"OST_Rooms"]), True,
       "without TVP the categories are recorded and hidden again on clear")


def check_link_highlight(c):
    m = model()
    link = [x for x in c.rv.list_models(m.doc) if x.is_link][0]
    lr = c.rv.read_rooms(m.doc, link, u"rooms")[0][0]
    res = c.rv.go_to_room(m.uiapp, lr, m.v1.Id, S, None)
    rec = res[u"record"]
    ok(rec[u"filter_id"] is not None, "rule filter used for a linked room")
    ok(rec[u"filter_id"].Value in m.v1.filters, "filter on the view")
    filt = m.doc.GetElement(rec[u"filter_id"])
    eq(sorted(r[2] for r in filt.ef.rules), [u"A1", u"Lobby"], "filter aimed at number and name")
    c.rv.clear(m.uiapp, rec)
    ok(rec[u"filter_id"].Value not in m.v1.filters, "filter taken off the view on clear")


def check_same_view(c):
    m = model()
    r1 = _room(c, m, u"101")
    r2 = _room(c, m, u"102")
    first = c.rv.go_to_room(m.uiapp, r1, m.v1.Id, S, None)[u"record"]
    second = c.rv.go_to_room(m.uiapp, r2, m.v1.Id, S, first)[u"record"]
    eq(m.v1.disable_calls, 0, "same plan: TVP not switched off and on again")
    ok(m.r1.Id.Value not in m.v1.overrides or
       m.v1.overrides[m.r1.Id.Value].SurfaceForegroundPatternColor.Red != 0x11,
       "previous room's colour taken off")
    eq(m.v1.overrides[m.r2.Id.Value].SurfaceForegroundPatternColor.Red, 0x11, "new room coloured")
    c.rv.clear(m.uiapp, second)
    ok(not m.v1.tvp, "after two finds on one plan, clear still ends TVP")
    third = c.rv.go_to_room(m.uiapp, r1, m.v2.Id, S, None)[u"record"]
    c.rv.go_to_room(m.uiapp, r2, m.v1.Id, S, third)
    ok(not m.v2.tvp, "moving to another plan restores the first one")


def check_borrow(c):
    m = model()
    m.doc.IsWorkshared = True
    m.doc.held_by_other.add(m.v1.Id.Value)
    r1 = _room(c, m, u"101")
    res = c.rv.go_to_room(m.uiapp, r1, m.v1.Id, S, None)
    ok(res[u"record"] is None, "nothing recorded on a view someone else holds")
    ok(not m.v1.tvp and m.r1.Id.Value not in m.v1.overrides, "nothing changed on it")
    ok(any(u"someone" in x for x in res[u"msgs"]), "says who holds it")
    ok(m.uidoc.ActiveView is m.v1, "still opens the view")


def check_runner(c):
    calls = []

    class Disp(object):
        def BeginInvoke(self, action):
            action()
    r = c.runner.Runner(Disp())
    try:
        _Raise.answer = "Pending"
        ok(r.submit("a", lambda app: 1, lambda res, err: calls.append(("a", res, err))),
           "Pending accepted")
        eq(len(r.queue), 1, "a Pending job stays queued")
        _Raise.answer = "Denied"
        ok(not r.submit("b", lambda app: 2, lambda res, err: calls.append(("b", res, err))),
           "Denied refused")
        eq(len(r.queue), 1, "only the refused job is dropped")
        ok(calls and calls[0][0] == "b" and calls[0][2], "refusal reported to the window")
        r._execute(None)
        eq(calls[-1], ("a", 1, None), "queued job ran later")
        eq(r.queue, [], "queue empty after running")
    finally:
        _Raise.answer = "Accepted"


CHECKS = [check_settings, check_theme, check_natural, check_rows, check_match,
          check_views_sort, check_geometry, check_canvas, check_host_read,
          check_link_read, check_plans, check_host_highlight, check_no_tvp,
          check_link_highlight, check_same_view, check_borrow, check_runner]


# =============================================================================
# Running
# =============================================================================
def _load(name, source=None):
    path = os.path.join(HERE, name + ".py")
    text = source if source is not None else open(path).read()
    mod = types.ModuleType(name)
    mod.__file__ = path
    saved = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        exec(compile(text, path, "exec"), mod.__dict__)
    finally:
        if saved is not None and source is not None:
            sys.modules[name] = saved
    return mod


def context(mutate=None):
    core = _load("frm_core")
    sys.modules["frm_core"] = core
    rv = _load("frm_revit")
    runner = _load("frm_runner")
    ctx = types.SimpleNamespace(core=core, rv=rv, runner=runner)
    if mutate:
        modname, old, new = mutate
        text = open(os.path.join(HERE, modname + ".py")).read()
        if old not in text:
            raise RuntimeError(u"breakage text not found in {0}: {1!r}".format(modname, old))
        broken = _load(modname, text.replace(old, new, 1))
        setattr(ctx, {"frm_core": "core", "frm_revit": "rv", "frm_runner": "runner"}[modname],
                broken)
    return ctx


def run(ctx, checks=None, quiet=False):
    failed = []
    for check in checks or CHECKS:
        try:
            check(ctx)
            if not quiet:
                print("  ok    " + check.__name__)
        except Exception as exc:
            failed.append(check.__name__)
            if not quiet:
                print("  FAIL  {0}: {1}".format(check.__name__, exc))
                traceback.print_exc()
    return failed


BREAKAGES = [
    ("frm_core", u'key, value = line.split(u"=", 1)',
     u'parts = line.split(u"=")\n        key, value = parts[0], parts[-1]', check_settings),
    ("frm_core", u"(i + 1) % len(THEME_MODES)", u"(i + 2) % len(THEME_MODES)", check_theme),
    ("frm_core", u'if canvas in (u"dark", u"light"):\n        return canvas',
     u'if False:\n        return canvas', check_theme),
    ("frm_core", u"open_ = True if q else (gk not in collapsed)", u"open_ = True", check_rows),
    ("frm_core", u"open_ = True if q else (gk not in collapsed)",
     u"open_ = gk not in collapsed", check_rows),
    ("frm_core", u'if not show_unplaced and room.state != u"ok":', u"if False:", check_rows),
    ("frm_core", u"return (room.level_elev, natural_key(room.level_name),",
     u"return (0, natural_key(room.level_name),", check_rows),
    ("frm_core", u'key.append((0, int(part), u""))', u"key.append((1, 0, part))", check_natural),
    ("frm_core", u"if abs(e - target_elev) <= tol_ft + 1e-9]", u"if True]", check_match),
    ("frm_core", u"        if named:", u"        if False:", check_match),
    ("frm_core", u"return (0 if v.in_crop else 1, lead, natural_key(v.name))",
     u"return (lead, natural_key(v.name))", check_views_sort),
    ("frm_revit", u"if value is not None:\n                found = core.theme_from_text",
     u"if value:\n                found = core.theme_from_text", check_canvas),
    ("frm_revit", u'        if applied.get(u"tvp_by_us"):\n            disable_tvp(view)',
     u'        if False:\n            disable_tvp(view)', check_host_highlight),
    ("frm_revit", u'view.SetElementOverrides(applied[u"elem_id"], prev)', u"pass",
     check_host_highlight),
    ("frm_revit", u'record[u"cats"].append((cid, True))', u"pass", check_no_tvp),
    ("frm_revit", u"view.RemoveFilter(fid)", u"pass", check_link_highlight),
    ("frm_revit", u"                keep = previous\n", u"                keep = None\n",
     check_same_view),
    ("frm_revit", u"if view.IsTemplate:\n            return False",
     u"if False:\n            return False", check_plans),
    ("frm_revit", u"corners = [_tuple(tf.OfPoint(_xyz(c))) for c in corners]", u"pass",
     check_link_read),
    ("frm_revit", u"    if not ok:\n        return None, [why", u"    if False:\n        return None, [why",
     check_borrow),
    ("frm_revit", u"lo, hi = core.pad_box(box, margin_ft)", u"lo, hi = box", check_host_highlight),
    ("frm_runner", u'if answer in (u"Accepted", u"Pending"):', u'if answer in (u"Accepted",):',
     check_runner),
    ("frm_runner", u"            self.queue.remove(job)", u"            self.queue = []",
     check_runner),
]


def selftest():
    print("selftest: {0} deliberate breakages".format(len(BREAKAGES)))
    bad = 0
    for modname, old, new, check in BREAKAGES:
        try:
            ctx = context((modname, old, new))
        except Exception as exc:
            print("  ERROR  {0}: {1}".format(check.__name__, exc))
            bad += 1
            continue
        failed = run(ctx, [check], quiet=True)
        label = u"{0}: {1!r}".format(modname, old.strip()[:60])
        if failed:
            print("  caught  {0} <- {1}".format(check.__name__, label))
        else:
            print("  MISSED  {0} <- {1}".format(check.__name__, label))
            bad += 1
    # the clean source must still pass every check afterwards
    if run(context(), quiet=True):
        print("  clean source no longer passes")
        bad += 1
    return bad


def main():
    if "--selftest" in sys.argv:
        bad = selftest()
        print("selftest {0}".format("FAILED ({0})".format(bad) if bad else "passed"))
        return 1 if bad else 0
    print("bench_logic: {0} checks".format(len(CHECKS)))
    failed = run(context())
    print("{0} failed".format(len(failed)) if failed else "all passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
