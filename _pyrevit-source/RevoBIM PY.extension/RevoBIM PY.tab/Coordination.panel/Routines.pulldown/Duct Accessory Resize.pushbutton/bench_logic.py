# -*- coding: utf-8 -*-
"""Logic bench for Duct Accessory Resize. Run from this folder:

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the code on purpose and confirm
                                      the checks notice

The rules in dar_core are tested directly. The resize itself runs end to
end against a fake Revit document that can roll back, refuse an element,
refuse one until its neighbour is done, or silently not take a value.
"""

from __future__ import print_function

import copy
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_stubs  # noqa: E402

FT = 304.8
DUCT_CAT = -2008000
ACC_CAT = -2008016
TERM_CAT = -2008013


# ============================================================
# a fake Revit
# ============================================================

class Enum(object):
    pass


class StorageType(Enum):
    Double = "Double"
    String = "String"


class TransactionStatus(Enum):
    Committed = "Committed"
    RolledBack = "RolledBack"


class FailureSeverity(Enum):
    Warning = "Warning"
    Error = "Error"


class FailureProcessingResult(Enum):
    Continue = "Continue"
    ProceedWithRollBack = "ProceedWithRollBack"


class BuiltInParameter(Enum):
    RBS_CURVE_WIDTH_PARAM = "RBS_CURVE_WIDTH_PARAM"
    RBS_CURVE_HEIGHT_PARAM = "RBS_CURVE_HEIGHT_PARAM"
    RBS_CURVE_DIAMETER_PARAM = "RBS_CURVE_DIAMETER_PARAM"
    SYMBOL_NAME_PARAM = "SYMBOL_NAME_PARAM"
    ALL_MODEL_TYPE_NAME = "ALL_MODEL_TYPE_NAME"


class BuiltInCategory(Enum):
    OST_DuctCurves = DUCT_CAT
    OST_DuctAccessory = ACC_CAT
    OST_DuctTerminal = TERM_CAT


class Id(object):
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return getattr(other, "Value", None) == self.Value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.Value)


class Category(object):
    def __init__(self, bic):
        self.BuiltInCategory = bic
        self.Id = Id(bic)


class Definition(object):
    def __init__(self, name):
        self.Name = name


class Param(object):
    def __init__(self, doc, owner_id, name, mm, readonly=False, sticky=False):
        self.doc = doc
        self.owner_id = owner_id
        self.Definition = Definition(name)
        self.value = None if mm is None else mm / FT
        self.IsReadOnly = readonly
        self.sticky = sticky
        self.StorageType = StorageType.Double

    @property
    def HasValue(self):
        return self.value is not None

    def AsDouble(self):
        return self.value

    def Set(self, value):
        self.doc.written.add(self.owner_id)
        if self.doc.in_network_with_accessory(self.owner_id):
            self.doc.network_broken = True
        if not self.sticky:
            self.value = value
        return True


class Point(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class Connector(object):
    """Connections live in doc.links as frozensets of connector keys, so a
    rolled-back transaction puts them back with everything else."""

    def __init__(self, owner, index, origin):
        self.Owner = owner
        self.key = (owner.Id.Value, index)
        self.Origin = Point(*origin)
        self.ConnectorType = "End"

    def _others(self):
        doc = self.Owner.doc
        out = []
        for link in doc.links:
            if self.key in link:
                other = [k for k in link if k != self.key][0]
                out.append(doc.connector(other))
        return out

    @property
    def IsConnected(self):
        return bool(self._others())

    @property
    def AllRefs(self):
        return self._others()

    def IsConnectedTo(self, other):
        return frozenset([self.key, other.key]) in self.Owner.doc.links

    def ConnectTo(self, other):
        self.Owner.doc.links.add(frozenset([self.key, other.key]))

    def DisconnectFrom(self, other):
        self.Owner.doc.links.discard(frozenset([self.key, other.key]))


class Manager(object):
    def __init__(self, connectors):
        self.Connectors = connectors


class MEPModel(object):
    def __init__(self, manager):
        self.ConnectorManager = manager


class Element(object):
    def __init__(self, doc, eid, name, cat=None, type_id=None):
        self.doc = doc
        self.Id = Id(eid)
        self.Name = name
        self.Category = Category(cat) if cat is not None else None
        self.type_id = type_id
        self.params = {}
        self.bips = {}
        doc.elements[eid] = self

    def add(self, name, mm, **kw):
        self.params[name] = Param(self.doc, self.Id.Value, name, mm, **kw)
        return self.params[name]

    def add_connectors(self, *origins_mm):
        found = [Connector(self, i, tuple(v / FT for v in o))
                 for i, o in enumerate(origins_mm)]
        if self.Category is not None and self.Category.BuiltInCategory \
                in (ACC_CAT, TERM_CAT):
            self.MEPModel = MEPModel(Manager(found))
        else:
            self.ConnectorManager = Manager(found)
        self.conns = found
        return found

    def add_bip(self, bip, mm):
        self.bips[bip] = Param(self.doc, self.Id.Value, bip, mm)

    def LookupParameter(self, name):
        return self.params.get(name)

    def GetParameters(self, name):
        return [self.params[name]] if name in self.params else []

    def get_Parameter(self, bip):
        return self.bips.get(bip)

    def GetTypeId(self):
        return Id(self.type_id if self.type_id is not None else -1)

    def ChangeTypeId(self, type_id):
        self.doc.written.add(self.Id.Value)
        self.type_id = type_id.Value

    @property
    def Parameters(self):
        return list(self.params.values())


class Family(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name

    def GetFamilySymbolIds(self):
        return [Id(e.Id.Value) for e in self.doc.elements.values()
                if getattr(e, "Family", None) is self]


class ElementTypeFake(Element):
    def __init__(self, doc, eid, name, family=None, shape=None):
        Element.__init__(self, doc, eid, name)
        self.Family = family
        self.FamilyName = family.name if family else u"Rectangular Duct"
        self.Shape = shape

    def Duplicate(self, name):
        new = ElementTypeFake(self.doc, self.doc.next_id(), name,
                              self.Family, self.Shape)
        for pname, p in self.params.items():
            new.add(pname, None if p.value is None else p.value * FT)
        return new


class Doc(object):
    def __init__(self):
        self.elements = {}
        self.written = set()
        self.refuse = lambda written: False
        self.IsWorkshared = False
        self.Title = u"bench"
        self.commits = 0
        self.links = set()
        self.network_broken = False
        self.regenerated = 0

    def connector(self, key):
        return self.elements[key[0]].conns[key[1]]

    def connect(self, a, b):
        self.links.add(frozenset([a.key, b.key]))

    def in_network_with_accessory(self, eid):
        """Revit's rule as the live log showed it: a size written to an
        element still connected to a duct accessory (either end) cannot
        keep the connectivity."""
        element = self.elements[eid]
        is_acc = element.Category is not None and \
            element.Category.BuiltInCategory in (ACC_CAT, TERM_CAT)
        for link in self.links:
            ids = [k[0] for k in link]
            if eid not in ids:
                continue
            other = [i for i in ids if i != eid]
            if not other:
                continue
            other_el = self.elements[other[0]]
            if is_acc or (other_el.Category is not None and
                          other_el.Category.BuiltInCategory
                          in (ACC_CAT, TERM_CAT)):
                return True
        return False

    def Regenerate(self):
        self.regenerated += 1

    def next_id(self):
        return max(self.elements.keys()) + 1

    def GetElement(self, eid):
        return self.elements.get(getattr(eid, "Value", eid))

    def snapshot(self):
        return copy.copy(self.elements), set(self.links), dict(
            (k, (e.type_id, dict((n, p.value) for n, p in e.params.items()),
                 dict((n, p.value) for n, p in e.bips.items())))
            for k, e in self.elements.items())

    def restore(self, snap):
        elements, links, state = snap
        self.elements = elements
        self.links = set(links)
        for k, (type_id, params, bips) in state.items():
            e = self.elements[k]
            e.type_id = type_id
            for n, v in params.items():
                e.params[n].value = v
            for n, v in bips.items():
                e.bips[n].value = v


class Options(object):
    def SetFailuresPreprocessor(self, p):
        pass

    def SetClearAfterRollback(self, v):
        pass

    def SetForcedModalHandling(self, v):
        pass


class Transaction(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.snap = None
        self.ended = False

    def Start(self):
        self.snap = self.doc.snapshot()
        self.doc.written = set()
        self.doc.network_broken = False

    def GetFailureHandlingOptions(self):
        return Options()

    def SetFailureHandlingOptions(self, o):
        pass

    def HasStarted(self):
        return self.snap is not None

    def HasEnded(self):
        return self.ended

    def Commit(self):
        self.ended = True
        if self.doc.network_broken or self.doc.refuse(set(self.doc.written)):
            self.doc.restore(self.snap)
            return TransactionStatus.RolledBack
        self.doc.commits += 1
        return TransactionStatus.Committed

    def RollBack(self):
        self.ended = True
        self.doc.restore(self.snap)


class TransactionGroup(Transaction):
    def Start(self):
        self.snap = self.doc.snapshot()

    def Assimilate(self):
        self.ended = True


class UIDoc(object):
    def __init__(self, doc):
        self.Document = doc


class UIApp(object):
    def __init__(self, doc):
        self.ActiveUIDocument = UIDoc(doc)


# ============================================================
# a fake WPF, enough to drive the drawer
# ============================================================

class EventSlot(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)
        return self


class DoubleStub(object):
    NaN = float("nan")


class TimeSpanStub(object):
    @staticmethod
    def FromMilliseconds(ms):
        return ms


class Vis(object):
    Visible = "Visible"
    Collapsed = "Collapsed"


class VAlign(object):
    Top = "Top"
    Stretch = "Stretch"


class SizeTo(object):
    Manual = "Manual"
    Height = "Height"


class FakeTimer(object):
    """A DispatcherTimer that runs its ticks only when the bench asks.

    It deliberately does NOT tick inside Start(). Writing it the obvious
    way - ticks run at once - hides the one breakage that matters: an
    exception escaping a tick would land in the try around Start(), the
    very fallback the slide uses when no timer can start, and the window
    would land anyway. A real DispatcherTimer sends it to the dispatcher
    instead and leaves the drawer sliding for ever. So escapes are caught
    here the way the dispatcher would catch them, recorded, and the bench
    fails on anything recorded."""

    live = []
    escaped = []

    def __init__(self):
        self.Tick = EventSlot()
        self.Interval = None
        self.running = False
        FakeTimer.live.append(self)

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    @classmethod
    def reset(cls):
        cls.live = []
        cls.escaped = []

    @classmethod
    def pump(cls, limit=400):
        turns = 0
        while turns < limit:
            running = [t for t in cls.live if t.running]
            if not running:
                return turns
            turns += 1
            for timer in running:
                for handler in list(timer.Tick.handlers):
                    try:
                        handler(timer, None)
                    except Exception as error:
                        cls.escaped.append(error)
        raise AssertionError("the slide never finished")


class FakeElement(object):
    def __init__(self, height=0.0):
        self.ActualHeight = height
        self.Height = height
        self.VerticalAlignment = VAlign.Stretch
        self.Visibility = Vis.Visible
        self.Tag = None
        self.ToolTip = None


class FakeWindow(object):
    def __init__(self, top=100.0, height=700.0, min_height=620.0):
        self.Top = top
        self.Height = height
        self.ActualHeight = height
        self.MinHeight = min_height
        self.SizeToContent = SizeTo.Manual
        self.ResizeMode = "NoResize"


def make_drawer(dr_mod, top=100.0, height=700.0, header=52.0,
                screen=(0.0, 0.0, 1920.0, 1040.0)):
    FakeTimer.reset()
    window = FakeWindow(top, height)
    head = FakeElement(header)
    body = FakeElement(height)
    button = FakeElement()
    grips = FakeElement()
    dr_mod._TAKEN.clear()
    drawer = dr_mod.Drawer(window, head, body, button, grips)
    drawer._screen = lambda: screen
    return drawer, window, head, body, button, grips


def load_modules():
    bench_stubs.install({
        "Autodesk.Revit.DB.StorageType": StorageType,
        "Autodesk.Revit.DB.TransactionStatus": TransactionStatus,
        "Autodesk.Revit.DB.FailureSeverity": FailureSeverity,
        "Autodesk.Revit.DB.FailureProcessingResult": FailureProcessingResult,
        "Autodesk.Revit.DB.BuiltInParameter": BuiltInParameter,
        "Autodesk.Revit.DB.BuiltInCategory": BuiltInCategory,
        "Autodesk.Revit.DB.Transaction": Transaction,
        "Autodesk.Revit.DB.TransactionGroup": TransactionGroup,
        "System.Windows.Threading.DispatcherTimer": FakeTimer,
        "System.Double": DoubleStub,
        "System.TimeSpan": TimeSpanStub,
        "System.Windows.Visibility": Vis,
        "System.Windows.VerticalAlignment": VAlign,
        "System.Windows.SizeToContent": SizeTo,
    })
    bench_stubs.forget()
    import dar_core
    import dar_revit
    import dar_drawer
    # a bench-only handle, so the checks can reach the drawer through the
    # same (core, rv) pair every check already takes
    dar_revit.DRAWER = dar_drawer
    return dar_core, dar_revit


# ============================================================
# model builders
# ============================================================

def rect_duct(doc, eid, w, h, duct_type):
    e = Element(doc, eid, u"Duct", DUCT_CAT, duct_type)
    e.add_bip("RBS_CURVE_WIDTH_PARAM", w)
    e.add_bip("RBS_CURVE_HEIGHT_PARAM", h)
    return e


def round_duct(doc, eid, d, duct_type):
    e = Element(doc, eid, u"Duct", DUCT_CAT, duct_type)
    e.add_bip("RBS_CURVE_DIAMETER_PARAM", d)
    return e


def base_doc():
    doc = Doc()
    ElementTypeFake(doc, 1, u"Rect", shape="Rectangular")
    ElementTypeFake(doc, 2, u"Round", shape="Round")
    return doc


SETTINGS = {
    u"acc_width": u"Duct Width", u"acc_height": u"Duct Height",
    u"acc_diameter": u"Duct Diameter",
    u"term_width": u"Neck Width", u"term_height": u"Neck Height",
    u"term_diameter": u"Neck Diameter",
    u"include_ducts": u"1", u"include_accessories": u"1",
    u"include_terminals": u"1", u"type_mode": u"switch",
}


class Log(object):
    def __init__(self):
        self.lines = []

    def add(self, text, *args):
        self.lines.append(text)

    def section(self, title):
        pass


def run_resize(core, rv, doc, shape, new, settings=None):
    settings = dict(SETTINGS, **(settings or {}))
    ids = [Id(k) for k, e in sorted(doc.elements.items())
           if e.Category is not None]
    rows, skipped = rv.read_rows(doc, ids, settings, Log())
    result = rv.apply_resize(UIApp(doc), rows, shape, new, settings, Log())
    return rows, result


def size_of(doc, eid, name):
    e = doc.elements[eid]
    p = e.params.get(name) or e.bips.get(name)
    if p is None:
        t = doc.elements[e.type_id]
        p = t.params.get(name)
    return round(p.value * FT, 1)


# ============================================================
# checks
# ============================================================

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def parse_sizes(core, rv):
    assert core.parse_mm(u"300") == (300.0, None)
    assert core.parse_mm(u" 300mm ") == (300.0, None)
    assert core.parse_mm(u"300,5") == (300.5, None)
    assert core.parse_mm(u"") == (None, None)
    assert core.parse_mm(u"abc")[1]
    assert core.parse_mm(u"-5")[1]
    assert core.parse_mm(u"0")[1]
    new, errors = core.parse_new_sizes(core.SHAPE_RECT,
                                       {u"w": u"800", u"h": u""})
    assert new == {u"w": 800.0} and not errors


@check
def formats(core, rv):
    assert core.fmt_size(core.SHAPE_RECT, {u"w": 600, u"h": 400.0}) == \
        u"600 x 400"
    assert core.fmt_size(core.SHAPE_ROUND, {u"d": 250.04}) == u"\u00d8250"
    assert core.fmt_mm(399.96) == u"400"
    assert core.fmt_mm(None) == u"-"


@check
def blank_box_keeps_dimension(core, rv):
    t = core.target_sizes(core.SHAPE_RECT, {u"w": 600, u"h": 400},
                          {u"w": 800})
    assert t == {u"w": 800, u"h": 400}, t


@check
def row_states(core, rv):
    R = core.SHAPE_RECT
    duct = {u"kind": u"duct", u"el_shape": R, u"current": {u"w": 600,
                                                           u"h": 400}}
    assert core.row_status(duct, R, {})[0] == u"idle"
    assert core.row_status(duct, R, {u"w": 600})[0] == u"green"
    assert core.row_status(duct, R, {u"w": 600.3})[0] == u"green"
    assert core.row_status(duct, R, {u"w": 800})[0] == u"orange"
    assert core.row_status(duct, R, {u"w": 800}, include_ducts=False)[0] \
        == u"idle"
    rnd = dict(duct, el_shape=core.SHAPE_ROUND)
    assert core.row_status(rnd, R, {u"w": 800})[0] == u"red"
    oval = dict(duct, el_shape=u"oval")
    assert core.row_status(oval, R, {u"w": 800})[0] == u"red"
    acc = {u"kind": u"accessory", u"current": {u"w": 600, u"h": 400},
           u"sources": {u"w": (u"type", True)},
           u"param_names": {u"w": u"Duct Width", u"h": u"Duct Height"}}
    state, note = core.row_status(acc, R, {u"w": 800})
    assert state == u"red" and u"Height" in note, note
    acc[u"sources"][u"h"] = (u"instance", False)
    state, note = core.row_status(acc, R, {u"w": 800})
    assert state == u"red" and u"read-only" in note, note
    acc[u"sources"][u"h"] = (u"instance", True)
    assert core.row_status(acc, R, {u"w": 800})[0] == u"orange"
    acc[u"param_names"][u"h"] = u""
    assert u"choose" in core.row_status(acc, R, {u"w": 800})[1]
    acc[u"result"] = (u"green", u"resized")
    assert core.row_status(acc, R, {u"w": 1})[0] == u"green"
    term = {u"kind": core.KIND_TERM, u"current": {u"w": 600, u"h": 400},
            u"sources": {u"w": (u"instance", True),
                         u"h": (u"instance", True)},
            u"param_names": {u"w": u"Neck Width", u"h": u"Neck Height"}}
    assert core.row_status(term, R, {u"w": 800})[0] == u"orange"
    assert core.row_status(term, R, {u"w": 800},
                           include_terminals=False)[0] == u"idle"
    assert core.row_status(term, R, {u"w": 800},
                           include_accessories=False)[0] == u"orange"


@check
def summary(core, rv):
    R = core.SHAPE_RECT
    rows = [{u"current": {u"w": 500, u"h": 300}},
            {u"current": {u"w": 600, u"h": 400}},
            {u"current": {u"w": 600, u"h": 400}}]
    assert core.summarise(R, rows) == u"600 x 400 (2), 500 x 300 (1)"
    assert core.counts_in_summary(u"orange", u"")
    assert not core.counts_in_summary(u"red", u"x")
    assert not core.counts_in_summary(u"idle", u"ducts switched off")


@check
def type_names(core, rv):
    R, O = core.SHAPE_RECT, core.SHAPE_ROUND
    assert core.type_name_for(R, u"FD 600x400", {u"w": 800, u"h": 400}) \
        == u"FD 800x400"
    assert core.type_name_for(R, u"FD 600 x 400 (R2)",
                              {u"w": 800, u"h": 400}) == u"FD 800x400 (R2)"
    assert core.type_name_for(R, u"Fire Damper", {u"w": 800, u"h": 400}) \
        == u"Fire Damper 800x400"
    assert core.type_name_for(O, u"SD \u00d8250", {u"d": 300}) == \
        u"SD \u00d8300"
    assert core.type_name_for(O, u"SD 250mm dia", {u"d": 300}) == \
        u"SD \u00d8300"
    assert core.strip_size(R, u"FD 800x400") == u"FD"
    assert core.unique_name(u"FD 800x400", [u"fd 800x400"]) == \
        u"FD 800x400 (2)"


@check
def default_params(core, rv):
    names = [u"Offset Width", u"Width", u"Duct Width", u"Height"]
    assert core.pick_default(names, u"w") == u"Duct Width"
    assert core.pick_default([u"Blade Width Offset", u"Nominal Width"],
                             u"w") == u"Nominal Width"
    assert core.pick_default([u"Length"], u"d") == u""
    terminal = [u"Duct Width", u"Neck Width", u"Neck Diameter"]
    assert core.pick_default(terminal, u"w", core.KIND_TERM) == u"Neck Width"
    assert core.pick_default(terminal, u"w", core.KIND_ACC) == u"Duct Width"
    assert core.pick_default(terminal, u"d", core.KIND_TERM) == \
        u"Neck Diameter"
    shown, matched = core.filter_names([u"Duct Width", u"Height"], u"zzz")
    assert not matched and len(shown) == 2
    shown, matched = core.filter_names([u"Duct Width", u"Height"], u"duct w")
    assert matched and shown == [u"Duct Width"]
    assert core.is_size_spec(u"autodesk.spec.aec:length-2.0.0")
    assert core.is_size_spec(u"autodesk.spec.aec.hvac:ductSize-2.0.0")
    assert not core.is_size_spec(u"autodesk.spec.aec:angle-2.0.0")


@check
def batches_isolate_the_bad_one(core, rv):
    def attempt(chunk):
        return (5 not in chunk), u"bad"
    ok, bad = core.run_batches(list(range(10)), attempt)
    assert sorted(ok) == [i for i in range(10) if i != 5], ok
    assert list(bad.keys()) == [5]


@check
def batches_retry_unblocks(core, rv):
    done = set()

    def attempt(chunk):
        if 3 in chunk and 4 not in done and 4 not in chunk:
            return False, u"needs 4"
        if 3 in chunk and 4 in chunk:
            return False, u"together fails"
        done.update(chunk)
        return True, u""
    ok, bad = core.run_batches([3, 4], attempt)
    assert sorted(ok) == [3, 4] and not bad, (ok, bad)


@check
def settings_round_trip(core, rv):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "s.txt")
    values = core.load_settings(path)
    assert values[u"shape"] == u"rect"
    values[u"acc_width"] = u"A=B"
    values[u"shape"] = u"round"
    assert core.save_settings(values, path)
    again = core.load_settings(path)
    assert again[u"acc_width"] == u"A=B" and again[u"shape"] == u"round"
    with open(path, "a") as h:
        h.write("nonsense line\nunknown_key=1\nshape=triangle\n")
    again = core.load_settings(path)
    assert again[u"shape"] == u"rect" and u"unknown_key" not in again


@check
def theme(core, rv):
    assert core.next_theme(u"auto") == u"dark"
    assert core.next_theme(u"light") == u"auto"
    assert core.resolve_theme(u"auto", None) == u"dark"
    assert core.resolve_theme(u"auto", False) == u"light"
    assert core.resolve_theme(u"dark", False) == u"dark"
    assert core.colour_is_dark(40, 40, 40)
    assert not core.colour_is_dark(255, 255, 255)
    assert core.theme_chip_text(u"auto", u"light") == u"Auto \u00b7 Light"


@check
def slow_clicks(core, rv):
    c = core.SlowClicks()
    assert not c.click(1000) and not c.click(1600) and c.click(2300)
    c = core.SlowClicks()
    assert not c.click(1000) and not c.click(1100) and not c.click(1200)
    c = core.SlowClicks()
    assert not c.click(1000) and not c.click(1000) and not c.click(1500)
    assert c.click(2000)


@check
def resize_ducts_and_instance_accessory(core, rv):
    doc = base_doc()
    rect_duct(doc, 10, 600, 400, 1)
    rect_duct(doc, 11, 600, 400, 1)
    fam = Family(doc, u"FD")
    t = ElementTypeFake(doc, 20, u"FD", fam)
    acc = Element(doc, 21, u"FD", ACC_CAT, 20)
    acc.add(u"Duct Width", 600)
    acc.add(u"Duct Height", 400)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 800})
    assert sorted(result[u"changed"]) == [10, 11, 21], result
    for eid in (10, 11):
        assert size_of(doc, eid, "RBS_CURVE_WIDTH_PARAM") == 800
        assert size_of(doc, eid, "RBS_CURVE_HEIGHT_PARAM") == 400
    assert size_of(doc, 21, u"Duct Width") == 800
    assert size_of(doc, 21, u"Duct Height") == 400
    assert doc.commits == 1, doc.commits


def type_sized(doc):
    fam = Family(doc, u"FD")
    t = ElementTypeFake(doc, 20, u"FD 600x400", fam)
    t.add(u"Duct Width", 600)
    t.add(u"Duct Height", 400)
    for eid in (21, 22):
        Element(doc, eid, u"FD", ACC_CAT, 20)
    return fam


@check
def type_sized_switches_to_existing(core, rv):
    doc = base_doc()
    fam = type_sized(doc)
    other = ElementTypeFake(doc, 30, u"FD 800x400", fam)
    other.add(u"Duct Width", 800)
    other.add(u"Duct Height", 400)
    before = len(doc.elements)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 800})
    assert sorted(result[u"changed"]) == [21, 22], result
    assert doc.elements[21].type_id == 30 and doc.elements[22].type_id == 30
    assert len(doc.elements) == before, u"a type was duplicated needlessly"
    assert size_of(doc, 20, u"Duct Width") == 600, u"old type was edited"


@check
def type_sized_duplicates_once(core, rv):
    doc = base_doc()
    type_sized(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT,
                              {u"w": 1000, u"h": 500})
    assert sorted(result[u"changed"]) == [21, 22], result
    new_type = doc.elements[doc.elements[21].type_id]
    assert new_type.Name == u"FD 1000x500", new_type.Name
    assert doc.elements[22].type_id == new_type.Id.Value, u"two duplicates"
    assert size_of(doc, 20, u"Duct Width") == 600


@check
def type_edit_mode(core, rv):
    doc = base_doc()
    type_sized(doc)
    before = len(doc.elements)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 900},
                              {u"type_mode": u"edit"})
    assert sorted(result[u"changed"]) == [21, 22], result
    assert len(doc.elements) == before
    assert size_of(doc, 20, u"Duct Width") == 900


@check
def refused_element_is_isolated(core, rv):
    doc = base_doc()
    for eid in range(10, 18):
        rect_duct(doc, eid, 600, 400, 1)
    doc.refuse = lambda written: 13 in written
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 800})
    assert sorted(result[u"changed"]) == [10, 11, 12, 14, 15, 16, 17], result
    assert list(result[u"refused"].keys()) == [13]
    assert size_of(doc, 13, "RBS_CURVE_WIDTH_PARAM") == 600, u"not rolled back"


@check
def silent_write_is_reported(core, rv):
    doc = base_doc()
    fam = Family(doc, u"FD")
    ElementTypeFake(doc, 20, u"FD", fam)
    acc = Element(doc, 21, u"FD", ACC_CAT, 20)
    acc.add(u"Duct Width", 600, sticky=True)
    acc.add(u"Duct Height", 400)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 800})
    assert 21 in result[u"refused"], result
    assert u"reads back" in result[u"refused"][21]


@check
def wrong_shape_left_alone(core, rv):
    doc = base_doc()
    round_duct(doc, 10, 250, 2)
    rect_duct(doc, 11, 600, 400, 1)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 800})
    assert result[u"changed"] == [11], result
    assert size_of(doc, 10, "RBS_CURVE_DIAMETER_PARAM") == 250


@check
def circular(core, rv):
    doc = base_doc()
    round_duct(doc, 10, 250, 2)
    fam = Family(doc, u"SD")
    ElementTypeFake(doc, 20, u"SD", fam)
    acc = Element(doc, 21, u"SD", ACC_CAT, 20)
    acc.add(u"Duct Diameter", 250)
    rows, result = run_resize(core, rv, doc, core.SHAPE_ROUND, {u"d": 315})
    assert sorted(result[u"changed"]) == [10, 21], result
    assert size_of(doc, 10, "RBS_CURVE_DIAMETER_PARAM") == 315
    assert size_of(doc, 21, u"Duct Diameter") == 315


@check
def read_only_never_written(core, rv):
    doc = base_doc()
    fam = Family(doc, u"FD")
    ElementTypeFake(doc, 20, u"FD", fam)
    acc = Element(doc, 21, u"FD", ACC_CAT, 20)
    acc.add(u"Duct Width", 600, readonly=True)
    acc.add(u"Duct Height", 400)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 800})
    assert result[u"asked"] == 0 and doc.commits == 0, result


def damper_run(doc, acc_height_param=u"Duct Height"):
    """duct 10 = damper 21 = duct 11, all 500 x 500, as in the live log."""
    d1 = rect_duct(doc, 10, 500, 500, 1)
    d2 = rect_duct(doc, 11, 500, 500, 1)
    fam = Family(doc, u"FD")
    ElementTypeFake(doc, 20, u"FD", fam)
    acc = Element(doc, 21, u"FD", ACC_CAT, 20)
    acc.add(u"Duct Width", 500)
    acc.add(u"Duct Height", 500)
    c1 = d1.add_connectors((0, 0, 0), (1000, 0, 0))
    ca = acc.add_connectors((1000, 0, 0), (1300, 0, 0))
    c2 = d2.add_connectors((1300, 0, 0), (2300, 0, 0))
    doc.connect(c1[1], ca[0])
    doc.connect(ca[1], c2[0])
    return c1, ca, c2


@check
def inline_damper_resizes_and_stays_connected(core, rv):
    doc = base_doc()
    c1, ca, c2 = damper_run(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT,
                              {u"w": 625, u"h": 450})
    assert sorted(result[u"changed"]) == [10, 11, 21], result
    assert size_of(doc, 21, u"Duct Width") == 625
    assert size_of(doc, 21, u"Duct Height") == 450
    assert size_of(doc, 10, "RBS_CURVE_HEIGHT_PARAM") == 450
    assert c1[1].IsConnectedTo(ca[0]) and ca[1].IsConnectedTo(c2[0]), \
        u"the run was left disconnected"
    assert doc.regenerated >= 1


@check
def ducts_beside_an_unselected_damper(core, rv):
    doc = base_doc()
    c1, ca, c2 = damper_run(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 625},
                              {u"include_accessories": u"0"})
    assert sorted(result[u"changed"]) == [10, 11], result
    assert c1[1].IsConnectedTo(ca[0]) and ca[1].IsConnectedTo(c2[0])


@check
def reconnect_failure_rolls_back(core, rv):
    doc = base_doc()
    c1, ca, c2 = damper_run(doc)
    original = rv.connector_near
    rv.connector_near = lambda element, point: None
    try:
        rows, result = run_resize(core, rv, doc, core.SHAPE_RECT,
                                  {u"w": 625})
    finally:
        rv.connector_near = original
    assert not result[u"changed"], result
    assert size_of(doc, 10, "RBS_CURVE_WIDTH_PARAM") == 500
    assert c1[1].IsConnectedTo(ca[0]), u"rollback lost the connection"


@check
def same_parameter_twice_is_stopped(core, rv):
    names = {u"w": u"BGL_Duct Width", u"h": u"BGL_Duct Width"}
    assert u"both use" in core.param_clash(names, core.SHAPE_RECT)
    assert core.param_clash(names, core.SHAPE_ROUND) == u""
    assert core.param_clash({u"w": u"A", u"h": u"a"}, core.SHAPE_RECT)
    doc = base_doc()
    damper_run(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT,
                              {u"w": 625, u"h": 450},
                              {u"acc_height": u"Duct Width"})
    assert result.get(u"stopped") and not result[u"changed"], result
    assert doc.commits == 0
    acc = [r for r in rows if r[u"kind"] == u"accessory"][0]
    assert core.row_status(acc, core.SHAPE_RECT, {u"w": 625})[0] == u"red"


@check
def search_never_changes_the_choice(core, rv):
    names = [u"BGL_Duct Diameter", u"BGL_Duct Height", u"BGL_Duct Width"]
    shown, matched = core.search_list(names, u"BGL_Duct Height", u"width")
    assert shown[0] == u"BGL_Duct Height" and u"BGL_Duct Width" in shown
    shown, matched = core.search_list(names, u"BGL_Duct Height", u"height")
    assert shown == [u"BGL_Duct Height"]
    shown, matched = core.search_list(names, u"", u"zzz")
    assert not matched and shown == names


@check
def connection_helpers(core, rv):
    assert core.pair_key(1, (0, 0, 0), 2, (1, 0, 0)) == \
        core.pair_key(2, (1, 0, 0), 1, (0, 0, 0))
    pts = [(0, 0, 0), (1, 0, 0)]
    assert core.nearest(pts, (1.00001, 0, 0)) == 1
    assert core.nearest(pts, (0.5, 0, 0)) is None
    assert core.unique_messages([u"a", u"b", u"a"]) == [u"a", u"b"]


def diffuser_on_a_branch(doc):
    """duct 10 = damper 21 = duct 11 = diffuser 31, all 500 x 500."""
    c1, ca, c2 = damper_run(doc)
    fam = Family(doc, u"VAV Diffuser")
    ElementTypeFake(doc, 30, u"Diffuser", fam)
    term = Element(doc, 31, u"Diffuser", TERM_CAT, 30)
    term.add(u"Neck Width", 500)
    term.add(u"Neck Height", 500)
    ct = term.add_connectors((2300, 0, 0),)
    doc.connect(c2[1], ct[0])
    return c1, ca, c2, ct


@check
def air_terminals_resize_with_the_run(core, rv):
    doc = base_doc()
    c1, ca, c2, ct = diffuser_on_a_branch(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT,
                              {u"w": 625, u"h": 450})
    assert sorted(result[u"changed"]) == [10, 11, 21, 31], result
    assert size_of(doc, 31, u"Neck Width") == 625
    assert size_of(doc, 31, u"Neck Height") == 450
    assert c2[1].IsConnectedTo(ct[0]), u"the diffuser was left disconnected"
    term = [r for r in rows if r[u"kind"] == core.KIND_TERM][0]
    assert term[u"category"] == u"Air Terminal"


@check
def terminal_uses_its_own_parameter_names(core, rv):
    """The damper is on Duct Width/Height and the diffuser on Neck
    Width/Height - one set of names for both would miss one of them."""
    doc = base_doc()
    diffuser_on_a_branch(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 625})
    assert sorted(result[u"changed"]) == [10, 11, 21, 31], result
    assert size_of(doc, 21, u"Duct Width") == 625
    assert size_of(doc, 31, u"Neck Width") == 625
    assert core.settings_names(SETTINGS, core.KIND_TERM)[u"w"] == \
        u"Neck Width"
    assert core.settings_names(SETTINGS, core.KIND_ACC)[u"w"] == u"Duct Width"


@check
def terminals_can_be_switched_off(core, rv):
    doc = base_doc()
    c1, ca, c2, ct = diffuser_on_a_branch(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 625},
                              {u"include_terminals": u"0"})
    assert sorted(result[u"changed"]) == [10, 11, 21], result
    assert size_of(doc, 31, u"Neck Width") == 500
    assert c2[1].IsConnectedTo(ct[0]), u"detach left the diffuser loose"


@check
def terminal_clash_is_its_own(core, rv):
    settings = dict(SETTINGS, term_height=u"Neck Width")
    clashes = core.all_clashes(settings, core.SHAPE_RECT)
    assert list(clashes.keys()) == [core.KIND_TERM], clashes
    assert u"Air Terminal" in clashes[core.KIND_TERM]
    off = dict(settings, include_terminals=u"0")
    assert not core.all_clashes(off, core.SHAPE_RECT)
    doc = base_doc()
    diffuser_on_a_branch(doc)
    rows, result = run_resize(core, rv, doc, core.SHAPE_RECT, {u"w": 625},
                              {u"term_height": u"Neck Width"})
    assert result.get(u"stopped") and doc.commits == 0, result


# ============================================================
# shrink to taskbar
# ============================================================

@check
def drawer_arithmetic(core, rv):
    assert core.ease(0) == 0.0 and core.ease(1) == 1.0
    assert core.ease(0.5) > 0.5, u"the slide should be away fast"
    last = -1.0
    for i in range(0, 21):
        value = core.ease(i / 20.0)
        assert value >= last, u"the easing curve goes backwards"
        last = value
    assert core.slide_steps() == 19, core.slide_steps()
    assert core.tween(100, 200, 0) == 100 and core.tween(100, 200, 1) == 200
    assert core.bar_height(52) == 54
    assert core.bar_height(4) == core.DRAWER_BAR_FLOOR, u"no floor on the bar"
    # resting on the bottom of the work area
    assert core.bar_top(0, 1040, 54) == 1040 - 54
    # stacking upward, a freed slot reused
    assert core.bar_top(0, 1040, 54, 1) == 1040 - 54 - 58
    assert core.take_slot([]) == 0 and core.take_slot([0, 2]) == 1
    assert core.take_slot([0, 1]) == 2


@check
def drawer_monitor_above_the_primary(core, rv):
    """A second monitor above the primary one has a negative work area
    top. Reading it as zero parks the bar on the wrong screen."""
    top = core.bar_top(-1080, 1040, 54)
    assert top == -1080 + 1040 - 54, top
    assert top < 0, u"the bar landed on the primary screen"
    back = core.restore_top(top, 54, 700, -1080, 1040)
    assert back == -1080 + 1040 - 700, back


@check
def drawer_opens_from_where_the_bar_sits(core, rv):
    """The bottom of the bar becomes the bottom of the window, so a bar
    carried somewhere else opens where the user left it."""
    parked = core.bar_top(0, 1040, 54)
    assert core.restore_top(parked, 54, 700, 0, 1040) == parked + 54 - 700
    # dragged up the screen, it still opens upward from there
    assert core.restore_top(600, 54, 300, 0, 1040) == 600 + 54 - 300
    # never off the top of the work area
    assert core.restore_top(100, 54, 900, 0, 1040) == 0
    assert core.restore_top(-1000, 54, 900, -1080, 1040) == -1080


@check
def drawer_parks_and_opens(core, rv):
    dr = rv.DRAWER
    drawer, window, head, body, button, grips = make_drawer(dr)
    assert not drawer.parked
    drawer.shrink()
    FakeTimer.pump()
    assert not FakeTimer.escaped, FakeTimer.escaped
    assert drawer.parked
    bar = core.bar_height(52)
    assert window.Height == bar, window.Height
    assert window.Top == core.bar_top(0, 1040, bar), window.Top
    assert window.MinHeight == 0.0, u"MinHeight vetoes the Height change"
    assert body.Height == 700.0 and body.VerticalAlignment == VAlign.Top, \
        u"the body was not pinned - the table re-measures every frame"
    assert grips.Visibility == Vis.Collapsed, \
        u"the grips were left over the parked bar"
    assert button.Tag == dr.SHRUNK, u"the button still shows the down arrow"

    drawer.restore()
    FakeTimer.pump()
    assert not FakeTimer.escaped, FakeTimer.escaped
    assert not drawer.parked
    assert window.Height == 700.0, window.Height
    assert window.MinHeight == 620.0, u"MinHeight was never put back"
    assert body.Height != body.Height, u"the body is still pinned"
    assert body.VerticalAlignment == VAlign.Stretch
    assert grips.Visibility == Vis.Visible
    assert button.Tag is None


@check
def drawer_toggles_again_and_again(core, rv):
    dr = rv.DRAWER
    drawer, window, head, body, button, grips = make_drawer(dr)
    for _ in range(3):
        drawer.toggle()
        FakeTimer.pump()
        assert drawer.parked
        drawer.toggle()
        FakeTimer.pump()
        assert not drawer.parked
        assert window.Height == 700.0
    assert not FakeTimer.escaped, FakeTimer.escaped


@check
def drawer_survives_a_tick_that_throws(core, rv):
    """An exception inside a tick reaches the dispatcher, NOT the try
    around Start(). Without its own fallback the drawer is left sliding
    for ever and the button never works again."""
    dr = rv.DRAWER
    drawer, window, head, body, button, grips = make_drawer(dr)
    original = core.tween
    core.tween = lambda a, b, p: 1 / 0
    try:
        drawer.shrink()
        FakeTimer.pump()
    finally:
        core.tween = original
    assert not FakeTimer.escaped, \
        u"the tick let an exception reach the dispatcher"
    assert not drawer.sliding, u"the drawer is stuck sliding"
    assert drawer.parked and window.Height == core.bar_height(52), \
        u"the window did not land"
    drawer.restore()
    FakeTimer.pump()
    assert not drawer.parked and window.Height == 700.0


@check
def drawer_lands_with_no_timer(core, rv):
    """No timer at all - the window still has to land, unpinned."""
    dr = rv.DRAWER
    drawer, window, head, body, button, grips = make_drawer(dr)

    class DeadTimer(object):
        def __init__(self):
            raise Exception(u"no timer today")
    original = dr.DispatcherTimer
    dr.DispatcherTimer = DeadTimer
    try:
        drawer.shrink()
        assert drawer.parked and not drawer.sliding
        assert window.Height == core.bar_height(52)
        drawer.restore()
    finally:
        dr.DispatcherTimer = original
    assert not drawer.parked
    assert window.Height == 700.0
    assert window.MinHeight == 620.0, u"MinHeight clamped on the quiet path"
    assert body.Height != body.Height, u"the body is pinned on the quiet path"
    assert grips.Visibility == Vis.Visible


@check
def drawer_settles_for_a_close(core, rv):
    """Closing while parked restores first, so nothing is left pinned."""
    dr = rv.DRAWER
    drawer, window, head, body, button, grips = make_drawer(dr)
    drawer.shrink()
    FakeTimer.pump()
    assert drawer.settle()
    assert not drawer.parked
    assert window.Height == 700.0
    assert window.MinHeight == 620.0
    assert body.Height != body.Height
    assert grips.Visibility == Vis.Visible
    assert not drawer.settle(), u"settling an open window should do nothing"


@check
def drawer_stacks_two_windows(core, rv):
    dr = rv.DRAWER
    first = make_drawer(dr)[0]
    second_window = FakeWindow(100.0, 500.0)
    second = dr.Drawer(second_window, FakeElement(52.0), FakeElement(500.0),
                       FakeElement(), FakeElement())
    second._screen = lambda: (0.0, 0.0, 1920.0, 1040.0)
    first.shrink()
    second.shrink()
    FakeTimer.pump()
    bar = core.bar_height(52)
    assert first.slot == 0 and second.slot == 1, (first.slot, second.slot)
    assert second_window.Top == core.bar_top(0, 1040, bar, 1)
    first.restore()
    FakeTimer.pump()
    third = make_drawer(dr)[0]
    dr._TAKEN.add(1)
    third.shrink()
    FakeTimer.pump()
    assert third.slot == 0, u"a freed slot was not reused"


def run_checks(core, rv, quiet=False):
    failed = []
    for fn in CHECKS:
        try:
            fn(core, rv)
            if not quiet:
                print("  ok    " + fn.__name__)
        except Exception as error:
            failed.append(fn.__name__)
            if not quiet:
                print("  FAIL  {0}: {1!r}".format(fn.__name__, error))
    return failed


# ============================================================
# selftest - break the code, the checks must notice
# ============================================================

def _break_batches(core, rv):
    def all_or_nothing(items, attempt, log=None):
        ok, message = attempt(list(items))
        return (list(items), {}) if ok else ([], dict((i, message)
                                                     for i in items))
    core.run_batches = all_or_nothing


def _break_units(core, rv):
    rv.read_mm = lambda p: None if p is None or p.value is None else p.value


def _break_switch(core, rv):
    def always_duplicate(doc, element, shape, target, dims, names, cache, log):
        current = rv.type_of(doc, element)
        new_type = current.Duplicate(core.type_name_for(
            shape, rv.safe_name(current), target) + u" dup")
        for dim in dims:
            rv.set_mm(rv.lookup(new_type, names[dim]), target[dim])
        return new_type.Id
    rv.switch_type = always_duplicate


def _break_readback(core, rv):
    core.sizes_match = lambda shape, a, b: True
    original = rv.describe

    def describe(doc, element, settings):
        return original(doc, element, settings)
    rv.describe = describe


def _break_blank_keeps(core, rv):
    core.target_sizes = lambda shape, current, new: dict(new)


def _break_names(core, rv):
    core.type_name_for = lambda shape, base, target: base + u" " + \
        core.size_label(shape, target)


def _break_tolerance(core, rv):
    core.same_mm = lambda a, b: a is not None and b is not None and a == b


def _break_clicks(core, rv):
    core.CLICK_GAP_MIN_MS = 0


def _break_readonly(core, rv):
    original = core.row_problems

    def lenient(row, shape):
        return [p for p in original(row, shape) if u"read-only" not in p]
    core.row_problems = lenient


def _break_edit_mode(core, rv):
    original = rv.write_row

    def ignore_mode(doc, row, shape, target, names, type_mode, cache, log):
        return original(doc, row, shape, target, names, u"switch", cache, log)
    rv.write_row = ignore_mode


def _break_tick_fallback(core, rv):
    """The tick loses its own try/except - the trap. The try around Start()
    does not cover a tick, so the exception reaches the dispatcher and the
    drawer is left sliding for ever."""
    dr = rv.DRAWER

    def slide(self, top_to, height_to, done):
        top_from = float(self.window.Top)
        height_from = self._measured_height()
        steps = core.slide_steps()
        state = {u"step": 0}

        def land():
            self.window.Top = float(top_to)
            self.window.Height = float(height_to)
            self.sliding = False
            done()

        def on_tick(sender, args):
            state[u"step"] += 1
            progress = float(state[u"step"]) / steps
            if progress >= 1.0:
                self._stop_timer()
                land()
                return
            self.window.Top = core.tween(top_from, top_to, progress)
            self.window.Height = core.tween(height_from, height_to, progress)

        self.sliding = True
        try:
            self.timer = dr.DispatcherTimer()
            self.timer.Interval = dr.TimeSpan.FromMilliseconds(
                core.DRAWER_TICK_MS)
            self.timer.Tick += on_tick
            self.timer.Start()
        except Exception:
            self.timer = None
            land()
    dr.Drawer._slide = slide


def _break_unpin(core, rv):
    rv.DRAWER.Drawer._unpin_body = lambda self: None


def _break_min_height(core, rv):
    rv.DRAWER.Drawer._put_back = lambda self: None


def _break_grips(core, rv):
    rv.DRAWER.Drawer._show_grips = lambda self, visible: None


def _break_bar_from_zero(core, rv):
    """The parked bar measured from zero instead of its own screen - what
    sends it to the primary monitor when the window is on one above."""
    original = core.bar_top
    core.bar_top = lambda work_top, work_height, height, slot=0, \
        gap=core.DRAWER_GAP: original(0, work_height, height, slot, gap)


def _break_reopen_forgets_the_bar(core, rv):
    core.restore_top = lambda parked_top, height, full_height, work_top, \
        work_height: float(work_top)


def _break_easing(core, rv):
    core.ease = lambda p: float(p)


def _break_terminal_names(core, rv):
    core.settings_names = lambda settings, kind=core.KIND_ACC: dict(
        (dim, core.to_text(settings.get(key, u"")))
        for dim, key in core.DIM_SETTING.items())


def _break_terminal_detach(core, rv):
    original = rv.family_kind
    rv.family_kind = lambda element: (
        None if original(element) == core.KIND_TERM else original(element))


def _break_detach(core, rv):
    rv.detach_accessories = lambda doc, elements, log: []


def _break_reattach(core, rv):
    rv.reattach = lambda doc, pairs, log: None


def _break_clash(core, rv):
    core.param_clash = lambda names, shape: u""


def _break_search(core, rv):
    core.search_list = lambda names, current, text: core.filter_names(
        names, text)


BREAKS = [
    ("the tick loses its own fallback", _break_tick_fallback),
    ("the body is never unpinned", _break_unpin),
    ("MinHeight is left clamped", _break_min_height),
    ("the grips are left over the bar", _break_grips),
    ("the bar measured from zero, not its screen", _break_bar_from_zero),
    ("reopening forgets where the bar was", _break_reopen_forgets_the_bar),
    ("the slide is linear, not eased", _break_easing),
    ("terminals share the accessory names", _break_terminal_names),
    ("air terminals not treated as families", _break_terminal_detach),
    ("accessories not detached (v1.0.0)", _break_detach),
    ("connections not put back", _break_reattach),
    ("same parameter twice allowed", _break_clash),
    ("search drops the chosen parameter", _break_search),
    ("all-or-nothing batches", _break_batches),
    ("no unit conversion on read", _break_units),
    ("switch always duplicates", _break_switch),
    ("read-back never fails", _break_readback),
    ("blank box clears the dimension", _break_blank_keeps),
    ("type name appended, not swapped", _break_names),
    ("no size tolerance", _break_tolerance),
    ("fast clicks count for the egg", _break_clicks),
    ("read-only treated as writable", _break_readonly),
    ("edit mode ignored", _break_edit_mode),
]


def selftest():
    core, rv = load_modules()
    if run_checks(core, rv, quiet=True):
        print("the shipped code fails - fix it before the selftest")
        return 1
    missed = 0
    for label, breaker in BREAKS:
        core, rv = load_modules()
        breaker(core, rv)
        failed = run_checks(core, rv, quiet=True)
        print("  {0:<36} {1}".format(label, ("caught by " + ", ".join(failed))
                                     if failed else "MISSED"))
        if not failed:
            missed += 1
    print("")
    print("selftest: {0} breakages, {1} missed".format(len(BREAKS), missed))
    return 1 if missed else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    core, rv = load_modules()
    failed = run_checks(core, rv)
    print("")
    print("bench_logic: {0} checks, {1} failed".format(len(CHECKS),
                                                       len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
