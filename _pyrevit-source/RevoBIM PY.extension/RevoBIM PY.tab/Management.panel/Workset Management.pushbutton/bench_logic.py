# -*- coding: utf-8 -*-
"""Logic bench for Workset Management - plain CPython, no Revit.

    python bench_logic.py              every check
    python bench_logic.py --selftest   break the code on purpose, prove a check fails

Part one runs the rules in wsm_core against tables of cases.  Part two drives
wsm_revit's apply routines against a fake workshared model that enforces the
API's own rules - checkout outside a transaction, rename and delete inside
one, a workset must be checked out before it is renamed or deleted - so the
order of work is tested, not just the arithmetic.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402

bench_stubs.install()

import wsm_core as core    # noqa: E402
import wsm_revit as revit  # noqa: E402

CHECKS = []


def check(func):
    CHECKS.append(func)
    return func


def expect(failures, label, got, want):
    if got != want:
        failures.append(u"{0}: got {1!r}, want {2!r}".format(label, got, want))


def rows_of(*specs):
    """(name, count[, owner]) -> WsRow list keyed ws:1, ws:2 ..."""
    out = []
    for index, spec in enumerate(specs, 1):
        owner = spec[2] if len(spec) > 2 else u""
        out.append(core.WsRow(u"ws:{0}".format(index), spec[0], spec[1], owner=owner, iid=index))
    return out


# ================================================================ part one: rules

@check
def natural_sort():
    failures = []
    names = [u"Level 10", u"Level 2", u"level 1", u"P-100", u"P-9", u"P-10"]
    expect(failures, "natural order", sorted(names, key=core.natural_key),
           [u"level 1", u"Level 2", u"Level 10", u"P-9", u"P-10", u"P-100"])
    return failures


@check
def rename_operations():
    failures = []
    cases = [
        (u"MEP - Pipework", {"find": u"mep", "replace": u"BGL"}, u"BGL - Pipework"),
        (u"MEP - Pipework", {"find": u"mep", "replace": u"BGL", "match_case": True},
         u"MEP - Pipework"),
        (u"Pipework", {"prefix": u"M_", "suffix": u"_L1"}, u"M_Pipework_L1"),
        (u"XX_Ductwork", {"remove_first": 3}, u"Ductwork"),
        (u"Ductwork_OLD", {"remove_last": 4}, u"Ductwork"),
        (u"abc", {"remove_last": 9}, u""),
        (u"XX_Duct", {"remove_first": 3, "prefix": u"M_"}, u"M_Duct"),
        (u"duct", {"case": "upper", "prefix": u"m_"}, u"m_DUCT"),
        (u"MEP-HVAC services", {"case": "title"}, u"Mep-Hvac Services"),
        (u"  Pipe   work ", {"tidy": True}, u"Pipe work"),
        (u"a.b", {"find": u".", "replace": u"_"}, u"a_b"),
        (u"Cost $1", {"find": u"$1", "replace": u"\\1"}, u"Cost \\1"),
        (u"Same", {}, u"Same"),
    ]
    for name, ops, want in cases:
        expect(failures, u"rename {0!r} {1}".format(name, ops), core.rename_name(name, ops), want)
    expect(failures, "empty ops", core.ops_empty({"case": "keep"}), True)
    expect(failures, "non-empty ops", core.ops_empty({"suffix": u"x"}), False)
    return failures


@check
def name_rules():
    failures = []
    expect(failures, "blank", bool(core.name_problem(u"   ")), True)
    expect(failures, "bad char", bool(core.name_problem(u"A:B")), True)
    expect(failures, "too long", bool(core.name_problem(u"x" * 300)), True)
    expect(failures, "fine", core.name_problem(u"M&E - Level 01 (North)"), u"")
    return failures


@check
def filters():
    failures = []
    for number, expr, want in [(5, ">0", True), (0, ">0", False), (0, "=0", True),
                               (0, "0", True), (12, "10-20", True), (25, "10-20", False),
                               (25, "20..10", False), (7, "<=7", True), (7, "!=7", False),
                               (7, "", True), (1234, "1234", True),
                               (1234, "23", False), (5, "abc", False)]:
        expect(failures, u"numeric {0} {1}".format(number, expr), core.numeric_match(number, expr), want)
    expect(failures, "words", core.text_match(u"MEP - Pipework L1", u"pipe l1"), True)
    expect(failures, "exclude", core.text_match(u"MEP - Pipework", u"mep -pipe"), False)
    rows = rows_of((u"Pipework", 10, u"anna"), (u"Ductwork", 0), (u"Shared", 3, u"anna"))
    by_key = dict((r.key, r) for r in rows)
    shown = [r.name for r in rows if core.row_passes(r, {"count": ">0"}, {}, by_key)]
    expect(failures, "count filter", shown, [u"Pipework", u"Shared"])
    ticks = {"owner": set([u"(nobody)"])}
    shown = [r.name for r in rows if core.row_passes(r, {}, ticks, by_key)]
    expect(failures, "owner tick", shown, [u"Ductwork"])
    expect(failures, "own column excluded from its list",
           core.tick_choices(rows, "owner", {}, ticks, by_key), [u"(nobody)", u"anna"])
    rows[1].visible = False
    shown = [r.name for r in rows if core.row_passes(r, {}, {"visible": set([u"No"])}, by_key)]
    expect(failures, "off in all views by tick", shown, [u"Ductwork"])
    expect(failures, "visible choices", core.tick_choices(rows, "visible", {}, {}, by_key),
           [u"No", u"Yes"])
    rows[1].visible = True
    expect(failures, "other filters narrow the list",
           core.tick_choices(rows, "owner", {"count": "=0"}, {}, by_key), [u"(nobody)"])
    return failures


@check
def category_columns():
    failures = []
    breakdown = core.category_breakdown({u"Pipes": 120, u"Ducts": 80, u"Pipe Fittings": 80,
                                         u"Valves": 3, u"Gone": 0, u"": 2})
    expect(failures, "biggest first, ties natural, zero dropped, blank named",
           breakdown, [(u"Pipes", 120), (u"Ducts", 80), (u"Pipe Fittings", 80),
                       (u"Valves", 3), (core.NO_CATEGORY, 2)])
    expect(failures, "summary", core.category_summary(breakdown),
           u"Pipes 120  \u00B7  Ducts 80  \u00B7  Pipe Fittings 80  \u00B7  +2 more")
    expect(failures, "empty summary", core.category_summary([]), u"")
    rows = rows_of((u"Containment", 9), (u"Drainage", 5), (u"Empty", 0))
    rows[0].categories = [(u"Cable Tray", 6), (u"Cable Tray Fittings", 3)]
    rows[1].categories = [(u"Pipes", 3), (u"Cable", 1), (u"Tray Fittings", 1)]
    by_key = dict((r.key, r) for r in rows)
    shown = lambda expr: [r.name for r in rows
                          if core.row_passes(r, {"cats": expr}, {}, by_key)]
    expect(failures, "words must meet in one category", shown(u"cable tray"), [u"Containment"])
    expect(failures, "a single word", shown(u"fittings"), [u"Containment", u"Drainage"])
    expect(failures, "exclude a category", shown(u"-tray"), [u"Empty"])
    expect(failures, "sort by how many categories",
           [r.name for r in core.sort_rows(rows, [("cats", True)])],
           [u"Drainage", u"Containment", u"Empty"])
    return failures


@check
def scan_counts_categories():
    """The breakdown counts every element, view specific and uncategorised
    included, so it adds up to the Elements column."""
    failures = []

    class Cat(object):
        def __init__(self, name, value, kind="Model"):
            self.Name = name
            self.Id = FakeElementId(value)
            self.CategoryType = E(kind)

    class Element(object):
        def __init__(self, ws, category, view_specific=False):
            self.WorksetId = WsId(ws)
            self.Category = category
            self.ViewSpecific = view_specific
            self.Id = FakeElementId(id(self))

    pipes, tags = Cat(u"Pipes", 1), Cat(u"Pipe Tags", 2, "Annotation")
    elements = [Element(2, pipes), Element(2, pipes), Element(2, tags, True),
                Element(2, None), Element(3, pipes)]

    class Collector(object):
        def __init__(self, document):
            pass

        def WhereElementIsNotElementType(self):
            return elements

    original = revit.DB.FilteredElementCollector
    revit.DB.FilteredElementCollector = Collector
    try:
        scan = revit.scan_model(object(), True, False)
    finally:
        revit.DB.FilteredElementCollector = original
    breakdown = core.category_breakdown(scan.workset_categories.get(2, {}))
    expect(failures, "breakdown", breakdown,
           [(u"Pipes", 2), (core.NO_CATEGORY, 1), (u"Pipe Tags", 1)])
    expect(failures, "adds up to the workset's count",
           sum(c for _, c in breakdown), scan.workset_counts.get(2))
    expect(failures, "assigner still sees model categories only",
           [(e.label, e.count) for e in scan.entries], [(u"Pipes", 3)])
    return failures


@check
def sorting():
    failures = []
    rows = rows_of((u"B", 5), (u"a", 9), (u"C", 5), (u"d", 1))
    expect(failures, "by name", [r.name for r in core.sort_rows(rows, [("name", False)])],
           [u"a", u"B", u"C", u"d"])
    expect(failures, "count desc then name",
           [r.name for r in core.sort_rows(rows, [("count", True), ("name", False)])],
           [u"a", u"B", u"C", u"d"])
    expect(failures, "count asc then name desc",
           [r.name for r in core.sort_rows(rows, [("count", False), ("name", True)])],
           [u"d", u"C", u"B", u"a"])
    stack = core.push_sort([("name", False)], "name", False)
    expect(failures, "click flips the only level", stack, [("name", True)])
    stack = core.push_sort(stack, "count", True)
    expect(failures, "shift adds a level", stack, [("name", True), ("count", False)])
    stack = core.push_sort(stack, "count", True)
    expect(failures, "shift on a level flips it alone", stack, [("name", True), ("count", True)])
    expect(failures, "plain click starts again", core.push_sort(stack, "owner", False),
           [("owner", False)])
    return failures


@check
def validation():
    failures = []
    rows = rows_of((u"Pipework", 1), (u"Ductwork", 1))
    rows[1].name = u"pipework"
    expect(failures, "case-only clash caught", core.validate(rows), 1)
    expect(failures, "problem on the renamed row", bool(rows[1].problem), True)
    expect(failures, "unchanged row clean", rows[0].problem, u"")

    rows = rows_of((u"A", 1), (u"B", 1))
    rows.append(core.WsRow(u"new:1", u"", is_new=True))
    expect(failures, "blank new name", core.validate(rows), 1)

    rows = rows_of((u"A", 1), (u"B", 1))
    rows[0].delete_to, rows[1].delete_to = u"ws:2", u"ws:1"
    expect(failures, "everything deleted", core.validate(rows) > 0, True)

    rows = rows_of((u"A", 1), (u"B", 1), (u"C", 1))
    rows, _ = core.stage_deletes(rows, [u"ws:1"], u"ws:2")
    rows, _ = core.stage_deletes(rows, [u"ws:2"], u"ws:3")
    core.validate(rows)
    expect(failures, "target being deleted too", bool(rows[0].problem), True)

    rows = rows_of((u"Old", 1), (u"Keep", 1))
    rows, _ = core.stage_deletes(rows, [u"ws:1"], u"ws:2")
    rows.append(core.WsRow(u"new:1", u"Old", is_new=True))
    expect(failures, "new name clashes with one still being deleted", core.validate(rows), 1)
    return failures


@check
def deleting_and_reverting():
    failures = []
    rows = rows_of((u"A", 4), (u"B", 0), (u"C", 2))
    rows[0].name = u"A renamed"
    rows.append(core.WsRow(u"new:1", u"Fresh", is_new=True))
    rows, problem = core.stage_deletes(rows, [u"ws:1", u"new:1"], u"ws:3")
    expect(failures, "no problem", problem, u"")
    expect(failures, "new row simply dropped", [r.key for r in rows], [u"ws:1", u"ws:2", u"ws:3"])
    expect(failures, "rename undone by the delete", rows[0].name, u"A")
    expect(failures, "state", rows[0].state(), core.STATE_DELETE)
    _, problem = core.stage_deletes(rows, [u"ws:2"], u"ws:2")
    expect(failures, "target cannot be one being deleted", bool(problem), True)
    expect(failures, "targets exclude deleted and deleting",
           [r.key for r in core.delete_targets(rows, [u"ws:2"])], [u"ws:3"])
    by_key = dict((r.key, r) for r in rows)
    expect(failures, "change text", core.change_text(rows[0], by_key),
           u"Delete - move 4 elements to C")
    rows = core.revert(rows, set([u"ws:3"]))
    expect(failures, "reverting a row leaves others", rows[0].delete_to, u"ws:3")
    rows = core.revert(rows)
    expect(failures, "revert all", [r.staged() for r in rows], [False, False, False])
    return failures


@check
def plan_building():
    failures = []
    rows = rows_of((u"A", 4), (u"B", 0), (u"C", 2))
    rows[1].name = u"B2"
    rows.append(core.WsRow(u"new:1", u"D", is_new=True))
    rows, _ = core.stage_deletes(rows, [u"ws:1"], u"new:1")
    core.validate(rows)
    plan = core.build_plan(rows)
    expect(failures, "creates", plan["creates"], [u"D"])
    expect(failures, "renames", [(i["old"], i["new"]) for i in plan["renames"]], [(u"B", u"B2")])
    expect(failures, "delete to a new workset",
           [(d["name"], d["target_name"], d["target_new"], d["count"]) for d in plan["deletes"]],
           [(u"A", u"D", True, 4)])
    expect(failures, "count", core.plan_count(plan), 3)
    rows[1].name = u"C"
    core.validate(rows)
    expect(failures, "problem rows left out", core.plan_count(core.build_plan(rows)), 2)
    return failures


@check
def bulk_rename_scope():
    failures = []
    rows = rows_of((u"M_A", 1), (u"M_B", 1), (u"X", 1))
    rows, _ = core.stage_deletes(rows, [u"ws:2"], u"ws:3")
    plan = core.bulk_rename_plan(rows, [u"ws:1", u"ws:2", u"ws:3"], {"find": u"M_", "replace": u""})
    expect(failures, "deleted rows untouched, unchanged names omitted", plan,
           [(u"ws:1", u"M_A", u"A")])
    return failures


@check
def spreadsheet_import():
    failures = []
    rows = rows_of((u"Pipework", 3), (u"Ductwork", 2), (u"Shared", 0), (u"Spare", 0))
    sheet = [
        (2, u"1", u"Pipework - L1"),            # rename by id
        (3, u"2", u"Ductwork"),                  # unchanged
        (4, u"3", u""),                          # emptied
        (5, core.NEW_ROW_KEY, core.NEW_ROW_PLACEHOLDER),
        (6, core.NEW_ROW_KEY, u"Electrical"),    # new
        (7, u"", u"Fire"),                       # new, id wiped
        (8, u"1", u"Again"),                     # id twice
        (9, u"77", u"Ghost"),                    # id not in model
        (10, core.NEW_ROW_KEY, u"ductwork"),     # clashes
        (11, u"4.0", u"Spare 2"),                # Excel's float id
    ]
    renames, creates, skipped = core.import_changes(sheet, rows)
    expect(failures, "renames", renames, {u"ws:1": u"Pipework - L1", u"ws:4": u"Spare 2"})
    expect(failures, "creates", creates, [u"Electrical", u"Fire"])
    expect(failures, "skipped count", len(skipped), 4)
    return failures


@check
def assigner_claims():
    failures = []
    scan = core.ModelScan()
    tray = core.CategoryEntry(u"cat:1", u"Cable Tray", 6)
    tray.element_ids = [1, 2, 3, 4, 5, 6]
    scan.add(tray)
    for key, label, ids in ((u"svc:1:LV", u"LV", [1, 2, 3]), (u"svc:1:Data", u"Data", [4, 5, 6])):
        child = core.CategoryEntry(key, label, len(ids), u"cat:1")
        child.element_ids = ids
        scan.add(child)
    pipes = core.CategoryEntry(u"cat:2", u"Pipes", 2)
    pipes.element_ids = [7, 8]
    scan.add(pipes)
    scan.finish()

    picked = core.toggle(set(), u"cat:1", True, scan)
    expect(failures, "parent ticks children", picked, set([u"cat:1", u"svc:1:LV", u"svc:1:Data"]))
    picked = core.toggle(picked, u"svc:1:Data", False, scan)
    expect(failures, "child releases parent", picked, set([u"svc:1:LV"]))
    picked = core.toggle(picked, u"svc:1:Data", True, scan)
    expect(failures, "all children brings the parent back", u"cat:1" in picked, True)

    selections = {u"E-LV": set([u"svc:1:LV"]), u"M-Pipe": set([u"cat:2"])}
    claims = core.build_claims(selections, scan)
    lines = [(e.key, d, en) for e, d, en in core.picker_lines(u"E-Data", claims, scan)]
    expect(failures, "partly held parent greyed, held child and category hidden", lines,
           [(u"cat:1", 0, False), (u"svc:1:Data", 1, True)])
    lines = [e.key for e, _, _ in core.picker_lines(u"M-Pipe", claims, scan)]
    expect(failures, "a workset still sees its own", u"cat:2" in lines, True)
    expect(failures, "search", [e.key for e, _, _ in
                                core.picker_lines(u"X", {}, scan, u"data")],
           [u"cat:1", u"svc:1:Data"])
    full = core.toggle(set(), u"cat:1", True, scan)
    expect(failures, "no element twice", sorted(core.element_ids_for(full, scan)),
           [1, 2, 3, 4, 5, 6])
    expect(failures, "count without children", core.selection_count(full, scan), 1)
    return failures


@check
def routines_round_trip():
    failures = []
    routines = {u"Fit-out; v2": {u"E | LV=1": [u"svc:1:LV; HV", u"cat:2"], u"Empty": []}}
    back = core.parse_routines(core.routine_lines(routines))
    expect(failures, "awkward characters survive", back,
           {u"Fit-out; v2": {u"E | LV=1": [u"svc:1:LV; HV", u"cat:2"]}})
    expect(failures, "project key", core.project_key(u"C:\\Jobs\\BGL MEP v6.rvt"), u"BGL MEP v6")
    return failures


@check
def settings_files():
    failures = []
    values = core.parse_settings([u"settings_version=1", u"theme=dark", u"debug=false",
                                  u"last_export_dir=C:\\a=b", u"junk=1", u"broken line"])
    expect(failures, "migration resets theme", values["theme"], u"follow")
    expect(failures, "kept key", values["debug"], u"false")
    expect(failures, "split on the first = only", values["last_export_dir"], u"C:\\a=b")
    expect(failures, "unknown key ignored", "junk" in values, False)
    expect(failures, "version stamped", values["settings_version"], core.SETTINGS_VERSION)
    current = core.parse_settings([u"settings_version=2", u"theme=light"])
    expect(failures, "current file not migrated", current["theme"], u"light")
    folder = tempfile.mkdtemp()
    try:
        path = os.path.join(folder, "s.txt")
        values["tab"] = u"assign"
        core.save_settings(values, path)
        expect(failures, "round trip", core.load_settings(path)["tab"], u"assign")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return failures


@check
def theme_rules():
    failures = []
    expect(failures, "auto follows canvas", core.resolve_theme("follow", "light"), "light")
    expect(failures, "auto with no canvas", core.resolve_theme("follow", None), "dark")
    expect(failures, "explicit wins", core.resolve_theme("dark", "light"), "dark")
    expect(failures, "cycle", [core.next_theme("follow"), core.next_theme("dark"),
                               core.next_theme("light")], ["dark", "light", "follow"])
    expect(failures, "palettes carry the same keys",
           sorted(core.PALETTES["dark"].keys()), sorted(core.PALETTES["light"].keys()))
    return failures


# ================================================================ part two: fake Revit

class E(str):
    def ToString(self):
        return str(self)


class WsId(object):
    def __init__(self, value):
        self.IntegerValue = value

    def __eq__(self, other):
        return isinstance(other, WsId) and other.IntegerValue == self.IntegerValue

    def __hash__(self):
        return hash(self.IntegerValue)


class FakeWorkset(object):
    def __init__(self, iid, name, owner=u"", locked=False):
        self.Id = WsId(iid)
        self.Name = name
        self.Owner = owner
        self.IsEditable = False
        self.IsOpen = True
        self.locked = locked          # CanDeleteWorkset says no


class FakeTable(object):
    def __init__(self, doc):
        self.doc = doc

    def GetActiveWorksetId(self):
        return WsId(self.doc.active)

    def SetActiveWorksetId(self, ws_id):
        self.doc.active = ws_id.IntegerValue

    def GetWorkset(self, ws_id):
        return self.doc.find(ws_id.IntegerValue)


class FakeElementId(object):
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return isinstance(other, FakeElementId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class FakeParam(object):
    def __init__(self, element):
        self.element = element
        self.IsReadOnly = element.read_only

    def Set(self, value):
        if not self.element.doc.in_tx:
            raise Exception("modification outside a transaction")
        self.element.ws = value


class FakeElement(object):
    def __init__(self, doc, eid, ws, owner=u"", read_only=False):
        self.doc = doc
        self.Id = FakeElementId(eid)
        self.ws = ws
        self.owner = owner
        self.read_only = read_only

    @property
    def WorksetId(self):
        return WsId(self.ws)

    def get_Parameter(self, bip):
        return FakeParam(self)


class FakeApp(object):
    Username = u"drew"


class FakeDoc(object):
    def __init__(self, worksets, active=1):
        self.worksets = worksets
        self.active = active
        self.in_tx = False
        self.in_group = False
        self.events = []
        self.elements = {}
        self.IsWorkshared = True
        self.Application = FakeApp()
        self.next_id = 100

    def find(self, iid):
        for workset in self.worksets:
            if workset.Id.IntegerValue == iid:
                return workset
        return None

    def GetWorksetTable(self):
        return FakeTable(self)

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)

    def count(self, iid):
        return len([e for e in self.elements.values() if e.ws == iid])


def install_fake_db(doc):
    DB = revit.DB

    class Collector(object):
        def __init__(self, document):
            self.document = document

        def OfKind(self, kind):
            return list(self.document.worksets)

    class Transaction(object):
        def __init__(self, document, name):
            self.document = document

        def GetFailureHandlingOptions(self):
            return bench_stubs.NetStub()

        def SetFailureHandlingOptions(self, options):
            pass

        def Start(self):
            self.document.in_tx = True

        def Commit(self):
            self.document.in_tx = False
            return E("Committed")

        def RollBack(self):
            self.document.in_tx = False

    class Group(object):
        def __init__(self, document, name):
            self.document = document

        def Start(self):
            self.document.in_group = True

        def Assimilate(self):
            self.document.in_group = False

        def RollBack(self):
            self.document.in_group = False

    def checkout_worksets(document, collection):
        if document.in_tx or document.in_group:
            raise Exception("CheckoutWorksets cannot run inside a transaction")
        document.events.append("checkout")
        for ws_id in collection:
            workset = document.find(ws_id.IntegerValue)
            if workset is not None and (not workset.Owner or workset.Owner == u"drew"):
                workset.IsEditable = True
                workset.Owner = u"drew"
        return collection

    def checkout_elements(document, collection):
        if document.in_tx or document.in_group:
            raise Exception("CheckoutElements cannot run inside a transaction")
        document.events.append("borrow")
        return [e for e in collection if not document.elements[e.Value].owner]

    class Utils(object):
        CheckoutWorksets = staticmethod(checkout_worksets)
        CheckoutElements = staticmethod(checkout_elements)

        @staticmethod
        def GetCheckoutStatus(document, element_id):
            return E("OwnedByOtherUser" if document.elements[element_id.Value].owner
                     else "NotOwned")

        @staticmethod
        def GetWorksharingTooltipInfo(document, element_id):
            info = bench_stubs.NetStub()
            info.__dict__["Owner"] = document.elements[element_id.Value].owner
            return info

    def need(document, ws_id, verb):
        if not document.in_tx:
            raise Exception("{0} outside a transaction".format(verb))
        workset = document.find(ws_id.IntegerValue)
        if workset is None or not workset.IsEditable:
            raise Exception("{0}: the workset is not checked out".format(verb))
        return workset

    class Table(object):
        @staticmethod
        def RenameWorkset(document, ws_id, name):
            need(document, ws_id, "RenameWorkset").Name = name
            document.events.append("rename")

        @staticmethod
        def IsWorksetNameUnique(document, name):
            return all(w.Name.lower() != name.lower() for w in document.worksets)

        @staticmethod
        def CanDeleteWorkset(document, ws_id, settings):
            return not document.find(ws_id.IntegerValue).locked

        @staticmethod
        def DeleteWorkset(document, ws_id, settings):
            victim = need(document, ws_id, "DeleteWorkset")
            if settings.option != "MoveElementsToWorkset":
                raise Exception("this tool must never delete elements")
            if document.active == victim.Id.IntegerValue:
                raise Exception("cannot delete the active workset")
            for element in document.elements.values():
                if element.ws == victim.Id.IntegerValue:
                    element.ws = settings.target.IntegerValue
            document.worksets.remove(victim)
            document.events.append("delete")

    class Workset(object):
        @staticmethod
        def Create(document, name):
            if not document.in_tx:
                raise Exception("Workset.Create outside a transaction")
            document.next_id += 1
            made = FakeWorkset(document.next_id, name, u"drew")
            made.IsEditable = True
            document.worksets.append(made)
            document.events.append("create")
            return made

    class Settings(object):
        def __init__(self, option, target):
            self.option = option
            self.target = target

    class Options(object):
        MoveElementsToWorkset = "MoveElementsToWorkset"
        DeleteAllElements = "DeleteAllElements"

    class Bip(object):
        ELEM_PARTITION_PARAM = "ELEM_PARTITION_PARAM"

    DB.FilteredWorksetCollector = Collector
    DB.WorksetKind = bench_stubs.NetStub()
    DB.Transaction = Transaction
    DB.TransactionGroup = Group
    DB.WorksharingUtils = Utils
    DB.WorksetTable = Table
    DB.Workset = Workset
    DB.DeleteWorksetSettings = Settings
    DB.DeleteWorksetOption = Options
    DB.BuiltInParameter = Bip

    class Generic(object):
        def __getitem__(self, kind):
            class Typed(list):
                def Add(self, item):
                    self.append(item)

                @property
                def Count(self):
                    return len(self)
            return Typed
    revit.List = Generic()


def fake_model():
    doc = FakeDoc([FakeWorkset(1, u"Shared Levels and Grids"),
                   FakeWorkset(2, u"Pipework"),
                   FakeWorkset(3, u"Ductwork"),
                   FakeWorkset(4, u"Old Services"),
                   FakeWorkset(5, u"Theirs", owner=u"sam")], active=3)
    for eid, ws in ((10, 2), (11, 2), (12, 3), (13, 3), (14, 3), (15, 4)):
        doc.elements[eid] = FakeElement(doc, eid, ws)
    install_fake_db(doc)
    return doc


def plan_for(doc, edit):
    records = revit.read_worksets(doc)
    rows = [core.WsRow(u"ws:{0}".format(r.iid), r.name, doc.count(r.iid), r.editable,
                       r.owner, iid=r.iid) for r in records]
    rows = edit(rows) or rows
    core.validate(rows)
    return core.build_plan(rows)


@check
def apply_renames_and_checkout():
    failures = []
    doc = fake_model()

    def edit(rows):
        by_name = dict((r.orig, r) for r in rows)
        by_name[u"Pipework"].name = u"M - Pipework"
        by_name[u"Theirs"].name = u"Mine now"
        rows.append(core.WsRow(u"new:1", u"Electrical", is_new=True))
    log = core.Log(False)
    result = revit.apply_manage(doc, plan_for(doc, edit), True, log)
    expect(failures, "checked out before anything was written", doc.events[0], "checkout")
    expect(failures, "renamed", result["renamed"], [(u"Pipework", u"M - Pipework")])
    expect(failures, "created", result["created"], [u"Electrical"])
    expect(failures, "someone else's workset refused with their name",
           [(what, u"sam" in why) for what, why in result["refused"]], [(u"Rename Theirs", True)])
    expect(failures, "no error", result["error"], u"")
    return failures


@check
def apply_without_auto_editable():
    failures = []
    doc = fake_model()

    def edit(rows):
        rows[1].name = u"Pipes"
    result = revit.apply_manage(doc, plan_for(doc, edit), False, core.Log(False))
    expect(failures, "nothing checked out", "checkout" in doc.events, False)
    expect(failures, "refused with a hint", len(result["refused"]), 1)
    expect(failures, "nothing renamed", result["renamed"], [])
    return failures


@check
def apply_deletes():
    failures = []
    doc = fake_model()

    def edit(rows):
        by_name = dict((r.orig, r) for r in rows)
        rows.append(core.WsRow(u"new:1", u"Mechanical", is_new=True))
        keys = [by_name[u"Ductwork"].key, by_name[u"Old Services"].key]
        rows, problem = core.stage_deletes(rows, keys, u"new:1")
        return rows
    result = revit.apply_manage(doc, plan_for(doc, edit), True, core.Log(False))
    mechanical = [w for w in doc.worksets if w.Name == u"Mechanical"][0].Id.IntegerValue
    expect(failures, "both deleted", sorted(name for name, _, _ in result["deleted"]),
           [u"Ductwork", u"Old Services"])
    expect(failures, "every element kept and moved to the new workset",
           sorted(e.Id.Value for e in doc.elements.values() if e.ws == mechanical),
           [12, 13, 14, 15])
    expect(failures, "element count unchanged", len(doc.elements), 6)
    expect(failures, "active workset handed over", doc.active, mechanical)
    expect(failures, "create ran before the deletes", doc.events.index("create") <
           doc.events.index("delete"), True)
    expect(failures, "no refusals", result["refused"], [])
    return failures


@check
def apply_delete_refused_keeps_others():
    failures = []
    doc = fake_model()
    doc.find(2).locked = True

    def edit(rows):
        by_name = dict((r.orig, r) for r in rows)
        rows, _ = core.stage_deletes(rows, [by_name[u"Pipework"].key,
                                            by_name[u"Old Services"].key],
                                     by_name[u"Shared Levels and Grids"].key)
        return rows
    result = revit.apply_manage(doc, plan_for(doc, edit), True, core.Log(False))
    expect(failures, "the free one went", [n for n, _, _ in result["deleted"]], [u"Old Services"])
    expect(failures, "the locked one reported", [w for w, _ in result["refused"]],
           [u"Delete Pipework"])
    expect(failures, "locked one still there", doc.find(2) is not None, True)
    return failures


@check
def apply_assignments_reads_back():
    failures = []
    doc = fake_model()
    doc.elements[12].owner = u"sam"
    doc.elements[13].read_only = True
    ids = [doc.elements[e].Id for e in (10, 12, 13, 14)]
    result = revit.apply_assignments(doc, [(4, u"Old Services", ids)], True, core.Log(False))
    expect(failures, "borrowed outside the transaction", "borrow" in doc.events, True)
    expect(failures, "moved, counted from the model", result["moved"], 2)
    expect(failures, "owned by sam", (result["owned"], result["owners"]), (1, {u"sam": 1}))
    expect(failures, "read-only refused", result["refused"], 1)
    expect(failures, "really moved", sorted(e.Id.Value for e in doc.elements.values() if e.ws == 4),
           [10, 14, 15])
    again = revit.apply_assignments(doc, [(4, u"Old Services", ids[:1])], True, core.Log(False))
    expect(failures, "already in place is not moved again", (again["moved"], again["already"]), (0, 1))
    return failures


# ================================================================ part three: 2.2.0

@check
def colours_per_workset():
    failures = []
    first = core.workset_colours([12, 3, 7])
    expect(failures, "every workset gets one", sorted(first.keys()), [3, 7, 12])
    expect(failures, "all different", len(set(first.values())), 3)
    expect(failures, "hex", all(len(v) == 7 and v.startswith(u"#") for v in first.values()), True)
    later = core.workset_colours([40, 12, 3, 7])   # name order puts the new one first
    expect(failures, "adding a workset keeps the others' colours",
           [later[i] for i in (3, 7, 12)], [first[i] for i in (3, 7, 12)])
    many = [core.distinct_colour(i) for i in range(40)]
    expect(failures, "forty distinct colours", len(set(many)), 40)
    expect(failures, "hex to rgb", core.hex_rgb(u"#FF8000"), (255, 128, 0))
    expect(failures, "bad hex", core.hex_rgb(u"Transparent"), None)
    return failures


@check
def merge_staging():
    failures = []
    rows = rows_of((u"Pipes A", 4), (u"Pipes B", 2), (u"Pipes C", 1), (u"Other", 9))
    rows[0].name = u"Pipework"                      # rename staged on the master
    rows[2].name = u"Will be lost"                  # rename on a merged row
    rows.append(core.WsRow(u"new:1", u"Empty new", is_new=True))
    keys = [u"ws:1", u"ws:2", u"ws:3", u"new:1"]
    _, problem = core.stage_merge(list(rows), keys, u"ws:4")
    expect(failures, "master must be in the selection", bool(problem), True)
    _, problem = core.stage_merge(list(rows), [u"ws:1"], u"ws:1")
    expect(failures, "needs two", bool(problem), True)
    rows, problem = core.stage_merge(rows, keys, u"ws:1")
    expect(failures, "no problem", problem, u"")
    expect(failures, "new row dropped", [r.key for r in rows], [u"ws:1", u"ws:2", u"ws:3", u"ws:4"])
    expect(failures, "master keeps its rename", (rows[0].name, rows[0].state()),
           (u"Pipework", core.STATE_RENAME))
    expect(failures, "others merge", [r.state() for r in rows[1:3]],
           [core.STATE_MERGE, core.STATE_MERGE])
    expect(failures, "a merged row's rename is dropped", rows[2].name, u"Pipes C")
    by_key = dict((r.key, r) for r in rows)
    expect(failures, "change text", core.change_text(rows[1], by_key),
           u"Merge into Pipework - move 2 elements")
    expect(failures, "tick value", core.tick_value(rows[1], "change", by_key), u"Merge")
    core.validate(rows)
    plan = core.build_plan(rows)
    expect(failures, "plan", [(d["name"], d["target_name"], d["merge"]) for d in plan["deletes"]],
           [(u"Pipes B", u"Pipework", True), (u"Pipes C", u"Pipework", True)])
    expect(failures, "plan lines", core.plan_lines(plan)[-1],
           u"Merge    Pipes C  into  Pipework  (1 elements)")
    rows = core.revert(rows)
    expect(failures, "revert clears the merge", [r.merge for r in rows], [False] * 4)
    return failures


@check
def apply_merge():
    failures = []
    doc = fake_model()

    def edit(rows):
        by_name = dict((r.orig, r) for r in rows)
        keys = [by_name[n].key for n in (u"Pipework", u"Ductwork", u"Old Services")]
        rows, _ = core.stage_merge(rows, keys, by_name[u"Pipework"].key)
        return rows
    result = revit.apply_manage(doc, plan_for(doc, edit), True, core.Log(False))
    expect(failures, "reported as merged, not deleted",
           (sorted(n for n, _, _ in result["merged"]), result["deleted"]),
           ([u"Ductwork", u"Old Services"], []))
    expect(failures, "every element now on the master",
           sorted(e.Id.Value for e in doc.elements.values() if e.ws == 2), [10, 11, 12, 13, 14, 15])
    expect(failures, "nothing lost", len(doc.elements), 6)
    return failures


class FakeEvent(object):
    def __init__(self, answers):
        self.answers = list(answers)

    def Raise(self):
        return E(self.answers.pop(0) if self.answers else "Accepted")


def make_runner(answers):
    import wsm_runner
    runner = wsm_runner.Runner()
    runner.event = FakeEvent(answers)
    return runner


@check
def runner_queue():
    failures = []
    seen = []
    runner = make_runner(["Accepted", "Pending", "Denied"])
    done = lambda tag: (lambda result, error: seen.append((tag, result, error is None)))
    expect(failures, "accepted", runner.submit("a", lambda app: 1, done("a"))[0], True)
    expect(failures, "pending is still queued", runner.submit("b", lambda app: 2, done("b"))[0], True)
    ok, why = runner.submit("c", lambda app: 3, done("c"))
    expect(failures, "denied is refused with a reason", (ok, bool(why)), (False, True))
    expect(failures, "only the refused job left the queue", [j.label for j in runner.jobs], ["a", "b"])
    expect(failures, "busy while queued", runner.busy(), True)
    runner.Execute(object())
    expect(failures, "both ran, in order", seen, [("a", 1, True), ("b", 2, True)])
    expect(failures, "idle after", runner.busy(), False)

    seen[:] = []
    runner.submit("boom", lambda app: 1 / 0, done("boom"))
    runner.Execute(object())
    expect(failures, "a failure reaches its callback, nothing escapes", seen, [("boom", None, False)])

    runner.submit("stuck", lambda app: 1, done("stuck"))
    runner.jobs[0].raised_at -= 999
    expect(failures, "watchdog frees a request Revit never picked up",
           (runner.watchdog(), runner.busy()), (["stuck"], False))

    direct = make_runner([])
    direct.direct = True
    seen[:] = []
    direct.submit("now", lambda app: 7, done("now"))
    expect(failures, "direct mode runs at once", seen, [("now", 7, True)])
    return failures


class FakeView(object):
    """A 3D view that behaves like Revit's: a collector on an isolated view
    only sees the isolated elements."""

    def __init__(self, doc):
        self.doc = doc
        self.Id = FakeElementId(500)
        self.Name = u"Workset Management"
        self.IsTemplate = False
        self.isolated = None
        self.events = doc.events

    def IsTemporaryHideIsolateActive(self):
        return self.isolated is not None

    def DisableTemporaryViewMode(self, mode):
        if not self.doc.in_tx:
            raise Exception("view change outside a transaction")
        self.isolated = None
        self.events.append("reset")

    def IsolateElementsTemporary(self, ids):
        if not self.doc.in_tx:
            raise Exception("isolate outside a transaction")
        self.isolated = set(i.Value for i in ids)
        self.events.append("isolate")


def install_fake_views(doc):
    DB = revit.DB
    view = FakeView(doc)
    doc.view = view

    class Collector(object):
        def __init__(self, document, view_id=None):
            self.document = document
            self.view_id = view_id
            self.ws = None

        def OfClass(self, kind):
            return [view] if kind is DB.View3D else []

        def WherePasses(self, element_filter):
            self.ws = element_filter.ws.IntegerValue
            return self

        def WhereElementIsNotElementType(self):
            out = []
            for element in self.document.elements.values():
                if self.ws is not None and element.ws != self.ws:
                    continue
                if self.view_id is not None and view.isolated is not None and \
                        element.Id.Value not in view.isolated:
                    continue
                out.append(element)
            return out

    class WorksetFilter(object):
        def __init__(self, ws):
            self.ws = ws

    class Modes(object):
        TemporaryHideIsolate = "TemporaryHideIsolate"

    DB.FilteredElementCollector = Collector
    DB.ElementWorksetFilter = WorksetFilter
    DB.TemporaryViewMode = Modes
    DB.View3D = type("View3D", (object,), {})
    for element in doc.elements.values():
        element.Category = object()
    return view


class FakeUIDoc(object):
    def __init__(self, doc):
        self.Document = doc
        self.ActiveView = None
        self.requested = []

    def RequestViewChange(self, view):
        self.requested.append(view)

    def RefreshActiveView(self):
        pass


class FakeUIApp(object):
    def __init__(self, uidoc):
        self.ActiveUIDocument = uidoc


def fake_3d():
    doc = fake_model()
    doc.Title = u"Bench model"
    doc.Equals = lambda other: other is doc
    view = install_fake_views(doc)
    uidoc = FakeUIDoc(doc)
    return doc, view, uidoc, FakeUIApp(uidoc)


@check
def isolate_order():
    failures = []
    doc, view, uidoc, uiapp = fake_3d()
    first = revit.isolate_worksets(uiapp, doc, [2], False, core.Log(False))
    expect(failures, "first isolate", (first["count"], sorted(view.isolated)), (2, [10, 11]))
    second = revit.isolate_worksets(uiapp, doc, [3], False, core.Log(False))
    expect(failures, "a second isolate is not starved by the first", sorted(view.isolated),
           [12, 13, 14])
    expect(failures, "reset committed before each isolate",
           [e for e in doc.events if e in ("reset", "isolate")],
           ["reset", "isolate", "reset", "isolate"])
    expect(failures, "the view is asked for", len(uidoc.requested), 2)
    revit.unisolate(uiapp, doc, core.Log(False))
    expect(failures, "un-isolate", view.isolated, None)
    try:
        revit.isolate_worksets(uiapp, doc, [99], False, core.Log(False))
        expect(failures, "nothing to isolate refused", "no refusal", "ToolStop")
    except revit.ToolStop:
        pass
    other = FakeUIApp(FakeUIDoc(object()))
    try:
        revit.isolate_worksets(other, doc, [2], False, core.Log(False))
        expect(failures, "another model active refused", "no refusal", "ToolStop")
    except revit.ToolStop:
        pass
    return failures


# ================================================================ part four: scope boxes

def scope_rows():
    return [core.ScopeRow(1, u"SB-01", [u"L1 Mech", u"L2 Mech"], [u"Level 01"]),
            core.ScopeRow(2, u"SB-02"),
            core.ScopeRow(3, u"SB-10", [u"L3 Mech"]),
            core.ScopeRow(4, u"Old box")]


@check
def scope_rules():
    failures = []
    rows = scope_rows()
    expect(failures, "used", [core.scope_value(r, "used") for r in rows],
           [u"Yes", u"No", u"Yes", u"No"])
    expect(failures, "counts", [(core.scope_value(r, "views"), core.scope_value(r, "datums"))
                                for r in rows], [(2, 1), (0, 0), (1, 0), (0, 0)])
    expect(failures, "used by", core.scope_used_by(rows[0]), u"L1 Mech, L2 Mech  +1 more")
    expect(failures, "tooltip lists everyone", core.scope_used_full(rows[0]).count(u"\n"), 4)
    shown = lambda filters, ticks=None: [r.orig for r in rows
                                         if core.scope_passes(r, filters, ticks or {})]
    expect(failures, "unused by tick", shown({}, {"used": set([u"No"])}), [u"SB-02", u"Old box"])
    expect(failures, "views filter", shown({"views": u">1"}), [u"SB-01"])
    expect(failures, "used by filter", shown({"usedby": u"l3"}), [u"SB-10"])
    expect(failures, "natural sort", [r.orig for r in core.scope_sort(rows, [("name", False)])],
           [u"Old box", u"SB-01", u"SB-02", u"SB-10"])
    expect(failures, "sort by views", [r.orig for r in core.scope_sort(rows, [("views", True)])][:2],
           [u"SB-01", u"SB-10"])

    core.scope_stage_delete(rows, [u"sb:1", u"sb:4"])
    rows[1].name = u"SB-01"                       # takes the name the delete frees
    rows[2].name = u"sb-01"                       # clashes with row 2's new name
    expect(failures, "two rows wanting one name are both flagged",
           (core.scope_validate(rows), bool(rows[1].problem), bool(rows[2].problem)),
           (2, True, True))
    rows[2].name = u"SB-03"
    expect(failures, "a name freed by a delete can be taken",
           (core.scope_validate(rows), rows[1].problem), (0, u""))
    expect(failures, "change text", [core.scope_change_text(r) for r in rows],
           [u"Delete - 2 views and 1 level/grid lose it", u"Rename from SB-02",
            u"Rename from SB-10", u"Delete - not used"])
    plan = core.scope_plan(rows)
    expect(failures, "plan", (len(plan["deletes"]), [i["new"] for i in plan["renames"]]),
           (2, [u"SB-01", u"SB-03"]))
    expect(failures, "deletes listed before renames",
           [line.split()[0] for line in core.scope_plan_lines(plan)],
           [u"Delete", u"Delete", u"Rename", u"Rename"])
    expect(failures, "bulk rename skips rows being deleted",
           [k for k, _, _ in core.bulk_rename_plan(rows, [r.key for r in rows], {"prefix": u"Z-"})],
           [u"sb:2", u"sb:3"])
    rows = core.revert(rows)
    expect(failures, "revert", [r.staged() for r in rows], [False] * 4)
    return failures


class FakeParamValue(object):
    def __init__(self, element, key):
        self.element = element
        self.key = key
        self.IsReadOnly = False

    def AsElementId(self):
        return FakeElementId(self.element.scope)

    def AsString(self):
        return self.element.Name

    def Set(self, value):
        if not self.element.doc.in_tx:
            raise Exception("modification outside a transaction")
        if self.element.owner:
            raise Exception("the element is not borrowed")
        self.element.Name = value


class FakeNamed(object):
    def __init__(self, doc, eid, name, kind, scope=0, owner=u""):
        self.doc = doc
        self.Id = FakeElementId(eid)
        self.Name = name
        self.kind = kind
        self.scope = scope
        self.owner = owner
        self.IsTemplate = False
        self.WorksetId = WsId(1)

    def get_Parameter(self, bip):
        return FakeParamValue(self, bip)


def fake_scope_model():
    doc = fake_model()
    doc.elements = {}
    items = [FakeNamed(doc, 201, u"SB-01", "box"), FakeNamed(doc, 202, u"SB-02", "box"),
             FakeNamed(doc, 203, u"SB-03", "box"),
             FakeNamed(doc, 301, u"L1 Mech", "view", 201), FakeNamed(doc, 302, u"L2 Mech", "view", 203),
             FakeNamed(doc, 401, u"01", "level", 201)]
    for item in items:
        doc.elements[item.Id.Value] = item
    DB = revit.DB

    class Collector(object):
        def __init__(self, document, view_id=None):
            self.document = document
            self.kind = None

        def OfCategory(self, category):
            self.kind = {"OST_VolumeOfInterest": "box", "OST_Levels": "level"}.get(category, "none")
            return self

        def OfClass(self, cls):
            self.kind = "view"
            return self

        def WhereElementIsNotElementType(self):
            return self

        def __iter__(self):
            return iter([e for e in self.document.elements.values() if e.kind == self.kind])

    class Categories(object):
        OST_VolumeOfInterest = "OST_VolumeOfInterest"
        OST_Levels = "OST_Levels"
        OST_Grids = "OST_Grids"
        OST_CLines = "OST_CLines"

    class Params(object):
        VOLUME_OF_INTEREST_NAME = "VOLUME_OF_INTEREST_NAME"
        VIEWER_VOLUME_OF_INTEREST_CROP = "VIEWER_VOLUME_OF_INTEREST_CROP"
        DATUM_VOLUME_OF_INTEREST = "DATUM_VOLUME_OF_INTEREST"

    def delete(element_id):
        if not doc.in_tx:
            raise Exception("Delete outside a transaction")
        element = doc.elements[element_id.Value]
        if element.owner:
            raise Exception("not borrowed")
        for other in doc.elements.values():
            if other.scope == element_id.Value:
                if other.owner:
                    raise Exception("a user of it is not borrowed")
                other.scope = 0
        del doc.elements[element_id.Value]
        doc.events.append("delete")

    doc.Delete = delete
    doc.GetElement = lambda element_id: doc.elements.get(element_id.Value)
    doc.GetWorksetTable().__class__.GetWorkset = lambda self, ws: doc.find(1)
    DB.FilteredElementCollector = Collector
    DB.BuiltInCategory = Categories
    DB.BuiltInParameter = Params
    DB.View = type("View", (object,), {})

    def borrow(document, collection):
        if document.in_tx or document.in_group:
            raise Exception("CheckoutElements cannot run inside a transaction")
        document.events.append("borrow")
        return [e for e in collection if not document.elements[e.Value].owner]

    def status(document, element_id):
        return E("OwnedByOtherUser" if document.elements[element_id.Value].owner else "NotOwned")

    def tooltip(document, element_id):
        info = bench_stubs.NetStub()
        info.__dict__["Owner"] = document.elements[element_id.Value].owner
        return info
    DB.WorksharingUtils.CheckoutElements = staticmethod(borrow)
    DB.WorksharingUtils.GetCheckoutStatus = staticmethod(status)
    DB.WorksharingUtils.GetWorksharingTooltipInfo = staticmethod(tooltip)
    return doc


@check
def scope_read_and_apply():
    failures = []
    doc = fake_scope_model()
    records = revit.read_scope_boxes(doc)
    expect(failures, "read", [(r.name, r.views, r.datums) for r in records],
           [(u"SB-01", [u"L1 Mech"], [u"Level 01"]), (u"SB-02", [], []),
            (u"SB-03", [u"L2 Mech"], [])])
    doc.elements[302].owner = u"sam"           # a view using SB-03 is someone else's
    rows = [core.ScopeRow(r.eid, r.name, r.views, r.datums) for r in records]
    core.scope_stage_delete(rows, [u"sb:201", u"sb:203"])
    rows[1].name = u"SB-01"
    core.scope_validate(rows)
    result = revit.apply_scope(doc, core.scope_plan(rows), True, core.Log(False))
    expect(failures, "borrowed before anything was written", doc.events[0], "borrow")
    expect(failures, "deleted, read back", result["deleted"], [u"SB-01"])
    expect(failures, "refused because sam holds a view using it",
           [(w, u"sam" in why) for w, why in result["refused"]], [(u"Delete SB-03", True)])
    expect(failures, "the freed name taken in the same Apply", result["renamed"],
           [(u"SB-02", u"SB-01")])
    expect(failures, "the view that used the deleted box has none now", doc.elements[301].scope, 0)
    expect(failures, "the refused one is still there", 203 in doc.elements, True)
    return failures


# ================================================================ running

def run_all():
    failed = 0
    for func in CHECKS:
        try:
            problems = func()
        except Exception as err:
            problems = [u"raised {0}: {1}".format(type(err).__name__, err)]
        if problems:
            failed += 1
            print(u"  FAIL  {0}".format(func.__name__))
            for line in problems:
                print(u"          " + line)
        else:
            print(u"  ok    {0}".format(func.__name__))
    return failed


def _patch(target, name, value):
    def apply():
        original = getattr(target, name)
        setattr(target, name, value)
        return lambda: setattr(target, name, original)
    return apply


_REAL_SCOPE_PLAN = core.scope_plan
_REAL_TO_TEXT = core.to_text


def _pending_clears(value):
    """Breakage: the runner reads every answer as a refusal."""
    text = _REAL_TO_TEXT(value)
    return u"Denied" if text == u"Pending" else text


BREAKAGES = [
    ("natural sort -> plain text", natural_sort,
     _patch(core, "natural_key", lambda v: core.to_text(v).lower())),
    ("prefix applied before removing characters", rename_operations,
     _patch(core, "rename_name", lambda name, ops: (core.to_text(ops.get("prefix", u"")) +
                                                    core.to_text(name))[core.as_int(ops.get("remove_first", 0)):])),
    ("duplicates not checked", validation,
     _patch(core, "name_problem", lambda name: u"")),
    ("new rows kept on delete", deleting_and_reverting,
     _patch(core, "stage_deletes", lambda rows, keys, target: (rows, u""))),
    ("toggle never releases the parent", assigner_claims,
     _patch(core, "toggle", lambda selected, key, ticked, scan:
            (set(selected) | set([key])) if ticked else set(selected))),
    ("claims ignored by the picker", assigner_claims,
     _patch(core, "free_for", lambda claims, workset, key: True)),
    ("import matches nothing", spreadsheet_import,
     _patch(core, "import_changes", lambda sheet, rows: ({}, [], []))),
    ("settings split on every =", settings_files,
     _patch(core, "parse_settings", lambda lines: dict(core.DEFAULTS))),
    ("numeric filter as substring only", filters,
     _patch(core, "numeric_match", lambda number, expr: core.to_text(expr) in core.to_text(number))),
    ("auto theme ignores the canvas", theme_rules,
     _patch(core, "resolve_theme", lambda setting, canvas: "dark")),
    ("checkout never called", apply_renames_and_checkout,
     _patch(revit, "checkout_worksets", lambda doc, ids, log: set())),
    ("delete removes elements", apply_deletes,
     _patch(revit, "_delete_settings", lambda target: revit.DB.DeleteWorksetSettings(
         "DeleteAllElements", target))),
    ("assignment counts calls, not read back", apply_assignments_reads_back,
     _patch(revit, "wsid_value", lambda ws_id: 999)),
    ("breakdown unsorted", category_columns,
     _patch(core, "category_breakdown", lambda counts: list(counts.items()))),
    ("categories filter matches words across categories", category_columns,
     _patch(core, "any_word_matches", lambda cats, expr: core.text_match(
         u" ".join(n for n, _ in cats), expr))),
    ("breakdown skips view-specific elements", scan_counts_categories,
     _patch(revit, "scan_model", lambda doc, a, b: _scan_without_annotations(doc, a, b))),
    ("colours by position, not by id", colours_per_workset,
     _patch(core, "workset_colours", lambda iids: dict(
         (iid, core.distinct_colour(n)) for n, iid in enumerate(iids)))),
    ("merge keeps the merged rows' renames", merge_staging,
     _patch(core, "stage_merge", lambda rows, keys, master: (rows, u""))),
    ("isolate without the reset", isolate_order,
     _patch(revit, "reset_isolate", lambda view: None)),
    ("runner clears the queue on Pending", runner_queue,
     _patch(core, "to_text", _pending_clears)),
    ("scope names clash with rows being deleted", scope_rules,
     _patch(core, "scope_validate", lambda rows: 0)),
    ("scope users not borrowed", scope_read_and_apply,
     _patch(revit, "checkout_elements", lambda doc, ids, log: set(revit.eid_value(i) for i in ids))),
    ("renames before deletes", scope_read_and_apply,
     _patch(core, "scope_plan", lambda rows: dict(_REAL_SCOPE_PLAN(rows), deletes=[]))),
    ("active workset not handed over", apply_deletes,
     _patch(revit, "active_workset_iid", lambda doc: -1)),
]



_REAL_SCAN = revit.scan_model


def _scan_without_annotations(doc, hide_empty, subgroup):
    """The 2.0.0 shape: per-workset counts taken after the model filter."""
    scan = _REAL_SCAN(doc, hide_empty, subgroup)
    for ws, per in scan.workset_categories.items():
        per.pop(core.NO_CATEGORY, None)
        for name in [n for n in per if n.endswith(u"Tags")]:
            per.pop(name)
    return scan

def selftest():
    if run_all():
        print(u"\nThe clean run fails - fix that before the selftest means anything.")
        return 1
    print(u"")
    missed = 0
    for label, target_check, patch in BREAKAGES:
        restore = patch()
        try:
            try:
                problems = target_check()
            except Exception as err:
                problems = [u"raised {0}".format(err)]
        finally:
            restore()
        if problems:
            print(u"  ok    {0}: caught by {1}".format(label, target_check.__name__))
        else:
            print(u"  MISS  {0}: {1} did not notice".format(label, target_check.__name__))
            missed += 1
    print(u"\n{0} breakages, {1} missed.".format(len(BREAKAGES), missed))
    return missed


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        bad = selftest()
    else:
        bad = run_all()
        print(u"\n{0} checks, {1} failed.".format(len(CHECKS), bad))
    sys.exit(1 if bad else 0)
