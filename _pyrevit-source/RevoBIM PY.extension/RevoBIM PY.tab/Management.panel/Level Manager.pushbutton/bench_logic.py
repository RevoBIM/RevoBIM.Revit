# -*- coding: utf-8 -*-
"""Level Manager - logic checks under plain CPython, against a fake model.

    python bench_logic.py              run every check
    python bench_logic.py --selftest   break the logic on purpose, prove the checks notice

The assign algorithm is driven through a fake Revit (FakeApi) that behaves
the ways real elements do: some hold their position when the level changes
(pipes), some drop with the level (walls) until their offset is put back,
some cannot be put back, some drag a connected element, some are owned by
someone else, and some Revit refuses outright.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402
bench_stubs.install()

import lvm_core as core  # noqa: E402
import lvm_revit as rv  # noqa: E402

FT = 1.0 / 304.8
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


# =========================================================================
# Fixtures
# =========================================================================

def levels():
    return [
        {"id": 30, "name": "Level 02", "proj": 6000 * FT, "disp": 6000 * FT},
        {"id": 10, "name": "Level 00", "proj": 0.0, "disp": 0.0},
        {"id": 20, "name": "Level 01", "proj": 3000 * FT, "disp": 3000 * FT},
    ]


def el(i, level, cat, name, z=None, assignable=True, route="RBS_START_LEVEL_PARAM", note=u"", **extra):
    info = {"id": i, "level": level, "category": cat, "name": name,
            "family": name.split(" : ")[0], "type": name.split(" : ")[-1],
            "workset": u"MEP", "z": z, "z_disp": z, "route": route if assignable else None,
            "assignable": assignable, "note": note, "params": {}}
    info.update(extra)
    return info


def elements():
    return [
        el(1, 10, u"Pipes", u"Pipe : P-10", z=2500 * FT),
        el(2, 10, u"Pipes", u"Pipe : P-9", z=2600 * FT),
        el(3, 10, u"Pipes", u"Pipe : P-100", z=2700 * FT),
        el(4, 10, u"Ducts", u"Duct : AHU-1", z=2800 * FT),
        el(5, 20, u"Walls", u"Basic Wall : 100 BLK", z=3000 * FT, route="WALL_BASE_CONSTRAINT"),
        el(6, 20, u"Rooms", u"Room 1", z=3000 * FT, assignable=False, note=u"Level is read-only"),
        el(7, 30, u"Pipes", u"Pipe : P-1", z=None),
        el(8, 99, u"Pipes", u"Pipe : orphan", z=0.0),      # level not in the list
    ]


def model():
    return core.Model(levels(), elements())


# =========================================================================
# Core checks
# =========================================================================

def test_text():
    names = [u"P-10", u"P-9", u"P-100", u"P-2"]
    check("natural order", sorted(names, key=core.natural_key) == [u"P-2", u"P-9", u"P-10", u"P-100"])
    check("fmt_mm rounds", core.fmt_mm(2500.4 * FT) == u"2500")
    check("fmt_mm no -0", core.fmt_mm(-0.3 * FT) == u"0")
    check("fmt_mm negative", core.fmt_mm(-450 * FT) == u"-450")
    check("fmt_mm None", core.fmt_mm(None) == u"")
    check("chunks", [len(c) for c in core.chunks(list(range(85)), 40)] == [40, 40, 5])
    check("count text", core.fmt_count(3, 10, True) == u"3 of 10" and core.fmt_count(10, 10, True) == u"10")


def test_settings():
    s = core.parse_settings(u"theme=light\ndebug=1\nparams=A|B=C|A\nbogus=1\nbroken line\nwidth=900")
    check("settings read", s["theme"] == "light" and s["debug"] == "1" and s["width"] == "900")
    check("split on first = only", core.split_params(s["params"]) == [u"A", u"B=C"])
    check("unknown key dropped", "bogus" not in s)
    d = core.parse_settings(u"")
    check("debug off by default", d["debug"] == "0" and core.DEFAULTS["debug"] == "0")
    check("theme follows canvas by default", d["theme"] == "auto")
    bad = core.parse_settings(u"theme=purple\ndebug=yes")
    check("damaged values fall back", bad["theme"] == "auto" and bad["debug"] == "0")
    again = core.parse_settings(core.dump_settings(s))
    check("settings round trip", again == s)
    check("join params", core.join_params([u"A", u"", u"B"]) == u"A|B")


def test_theme():
    check("auto follows dark canvas", core.resolve_theme("auto", True) == "dark")
    check("auto follows light canvas", core.resolve_theme("auto", False) == "light")
    check("auto unreadable -> dark", core.resolve_theme("auto", None) == "dark")
    check("forced light", core.resolve_theme("light", True) == "light")
    check("cycle", core.next_theme_mode("auto") == "dark" and core.next_theme_mode("dark") == "light"
          and core.next_theme_mode("light") == "auto")

    class FalsyDark(object):         # UITheme.Dark is 0: falsy, but it IS dark
        def __bool__(self):
            return False
        __nonzero__ = __bool__

        def __str__(self):
            return "Dark"

    check("UITheme.Dark falsy still dark", core.canvas_theme_is_dark(FalsyDark()) is True)
    check("Light canvas", core.canvas_theme_is_dark("Light") is False)
    check("unknown canvas", core.canvas_theme_is_dark(None) is None)
    check("palettes share keys", set(core.PALETTE_DARK) == set(core.PALETTE_LIGHT))
    check("light accents darker", core.PALETTE_LIGHT["Blue"] == "#1B72BE" and core.PALETTE_DARK["Blue"] == "#4FA3E3")
    check("background luminance", core.colour_is_dark(30, 30, 30) and not core.colour_is_dark(240, 240, 240))


def test_logo_clicks():
    c = core.LogoClicks()
    check("logo: 1st and 2nd click do nothing", not c.click(0) and not c.click(400))
    check("logo: 3rd slow click fires", c.click(900))
    check("logo: a 4th click does not fire again", not c.click(1300))
    c = core.LogoClicks()
    c.click(0); c.click(400)
    c.reset()
    check("logo: a click elsewhere starts over", not c.click(800))
    c = core.LogoClicks()
    c.click(0); c.click(100)
    check("logo: double-click speed does not count", not c.click(200))
    c = core.LogoClicks()
    c.click(0); c.click(400)
    check("logo: same event twice is one click", not c.click(400))
    c = core.LogoClicks()
    c.click(0); c.click(400)
    check("logo: a long pause starts over", not c.click(5000) and not c.click(5400) and c.click(5800))


def test_slow_clicks():
    check("three slow clicks", core.slow_clicks([0, 400, 900]))
    check("too fast", not core.slow_clicks([0, 100, 500]))
    check("too slow", not core.slow_clicks([0, 400, 3000]))
    check("two clicks", not core.slow_clicks([0, 400]))


def test_tree():
    m = model()
    check("orphan level skipped", 8 not in m.elements)
    check("levels by elevation", [lv["name"] for lv in m.levels] == [u"Level 00", u"Level 01", u"Level 02"])
    rows = m.rows()
    check("collapsed: levels only", [r["kind"] for r in rows] == ["L", "L", "L"])
    check("level count", rows[0]["count"] == u"4")
    check("level elevation shown", rows[1]["elev"] == u"3000")
    m.toggle_open(core.level_key(10))
    rows = m.rows()
    check("level opens to categories", [r["name"] for r in rows[:3]] == [u"Level 00", u"Ducts", u"Pipes"])
    m.toggle_open(core.cat_key(10, u"Pipes"))
    rows = m.rows()
    names = [r["name"] for r in rows if r["kind"] == "E"]
    check("elements natural order", names == [u"Pipe : P-9", u"Pipe : P-10", u"Pipe : P-100"])
    e = [r for r in rows if r["kind"] == "E"][0]
    check("element indent depth", e["depth"] == 2 and e["family"] == u"Pipe" and e["elev"] == u"2600")
    check("above level", e["above"] == u"2600")
    m.collapse_all()
    check("collapse all", [r["kind"] for r in m.rows()] == ["L", "L", "L"])
    m.expand_all()
    kinds = [r["kind"] for r in m.rows()]
    check("expand all", kinds.count("E") == 7 and kinds.count("C") == 5)
    locked = [r for r in m.rows() if r.get("eid") == 6][0]
    check("locked row state", locked["state"] == "locked")


def test_filters():
    m = model()
    m.search = u"p-10"
    check("filter active", m.filter_active())
    rows = m.rows()
    elems = [r["eid"] for r in rows if r["kind"] == "E"]
    check("search opens matches", sorted(elems) == [1, 3])
    check("search count", rows[0]["count"] == u"2 of 4")
    check("match count", m.last_match == 2)
    m.toggle_open(core.level_key(10))
    check("collapse while filtered", not [r for r in m.rows() if r["kind"] == "E"])
    m.clear_filters()
    m.col_filters["family"] = u"duct"
    m.expand_all()
    check("column keyword", [r["eid"] for r in m.rows() if r["kind"] == "E"] == [4])
    m.clear_filters()
    m.val_filters["category"] = None
    m.val_filters["family"] = set([u"Pipe"])
    vals = m.values_for("family")
    check("own filter left out of its list", u"Duct" in vals and u"Pipe" in vals)
    m.col_filters["type"] = u"P-1"
    vals = m.values_for("family")
    check("other filters narrow the list", vals == [u"Pipe"])
    m.clear_filters()
    m.val_filters["family"] = set()
    m.expand_all()
    check("nothing ticked shows nothing", not [r for r in m.rows() if r["kind"] == "E"])
    m.clear_filters()
    check("blank value shown as (blank)", core.BLANK in m.values_for("elev"))


def test_sort():
    m = model()
    m.expand_all()
    m.click_sort("elev", False)
    order = [r["eid"] for r in m.rows() if r["kind"] == "E" and r["level"] == 10 and r.get("family") == u"Pipe"]
    check("numeric sort", order == [1, 2, 3])
    m.click_sort("elev", False)
    order = [r["eid"] for r in m.rows() if r["kind"] == "E" and r["level"] == 10 and r.get("family") == u"Pipe"]
    check("flip direction", order == [3, 2, 1])
    check("sort badge", m.sort_badge("elev").startswith(u"1"))
    m2 = core.Model(levels(), [el(1, 10, u"Pipes", u"A", z=None), el(2, 10, u"Pipes", u"B", z=5 * FT),
                               el(3, 10, u"Pipes", u"C", z=1 * FT)])
    m2.expand_all()
    m2.click_sort("elev", False)
    m2.click_sort("elev", False)
    order = [r["eid"] for r in m2.rows() if r["kind"] == "E"]
    check("blanks last both ways", order == [2, 3, 1])
    m2.click_sort("name", True)
    check("shift adds a level", len(m2.sort_stack) == 2)


def test_ticks():
    m = model()
    n = m.toggle_tick(core.level_key(10))
    check("tick a level", n == 4 and m.tick_state(m.visible_ids(10)) == "1")
    m.toggle_tick(core.level_key(10))
    check("untick a level", not m.ticked)
    m.search = u"duct"
    m.toggle_tick(core.level_key(10))
    check("tick respects the filter", m.ticked == set([4]))
    m.clear_filters()
    check("partial state", m.tick_state(m.visible_ids(10)) == "p")
    m.untick_all()
    hi = set([core.elem_key(1), core.elem_key(2)])
    m.toggle_tick(core.elem_key(1), hi)
    check("ticking a highlighted row ticks the highlight", m.ticked == set([1, 2]))
    m.toggle_tick(core.elem_key(3), hi)
    check("a row outside the highlight changes alone", m.ticked == set([1, 2, 3]))
    sel = m.selection([core.cat_key(20, u"Walls")])
    check("selection = ticked + highlighted heading", sel == [1, 2, 3, 5])
    m.untick_all()
    m.tick_ids([5, 999])
    m.open_levels_of([5])
    check("tick from Revit selection", m.ticked == set([5]) and core.level_key(20) in m.expanded)


def test_params():
    m = model()
    m.param_cols = [u"System Name"]
    m.set_param_values(u"System Name", {1: u"CWS", 2: u"LTHW"})
    m.search = u"lthw"
    check("search reaches parameter columns", [i for i in m.elements if m.passes(m.elements[i])] == [2])
    m.set_param_values(u"System Name", {1: u"CWS", 2: u"CHW"})
    check("cache forgets on new values", not m.passes(m.elements[2]))
    check("param column order", m.visible_keys()[-2:] == [u"p:System Name", "note"])
    m.show_workset = False
    check("workset column hidden on non-workshared", "workset" not in m.visible_keys())


def test_plan():
    m = model()
    plan = core.plan_assign(m, [1, 4, 5, 6, 7], 30)
    check("plan do", sorted(plan["do"]) == [1, 4, 5])
    check("plan already", plan["already"] == [7])
    check("plan locked", [i for i, _ in plan["locked"]] == [6])
    text = core.plan_summary(m, plan, 30)
    check("plan summary", u"3 elements" in text and u"Level 02" in text and u"1 already" in text)


def test_routes():
    check("route offsets include generic", core.offsets_for("WALL_BASE_CONSTRAINT")[0] == "WALL_BASE_OFFSET"
          and "INSTANCE_ELEVATION_PARAM" in core.offsets_for("WALL_BASE_CONSTRAINT"))
    check("paired beam offsets", core.offset_members(core.offsets_for("INSTANCE_REFERENCE_LEVEL_PARAM")[0])
          == ["STRUCTURAL_BEAM_END0_ELEVATION", "STRUCTURAL_BEAM_END1_ELEVATION"])
    check("route labels", core.route_label("RBS_START_LEVEL_PARAM") == u"Reference Level"
          and core.route_label("name:Base Level") == u"Base Level")
    check("compensation sign", abs(core.compensated_offset(1.0, 0.25) - 0.75) < 1e-12)
    check("deviation", core.deviation((0, 0, 0), (0, 0, 2 * FT)) > core.MOVE_TOL_FT)
    check("no move", not core.has_moved((1, 2, 3), (1, 2, 3)))
    check("z shift", abs(core.z_shift((0, 0, 1), (0, 0, 3)) - 2) < 1e-12)


# =========================================================================
# The fake Revit for assign_levels
# =========================================================================

class FakeApi(object):
    """Elements: id -> dict(z, level, offset, kind, ...). kinds:
      hold     - level changes, element stays (pipes)
      drop     - element shifts by the level difference until its offset is reset (walls)
      stuck    - shifts, no offset, pinned: cannot be held
      refuse   - set_level returns False
      drag     - holds itself but shifts neighbour 'nb' by 50mm
      commit   - Revit rolls the transaction back at commit
      noread   - change reports success but reads back on the old level
    """

    def __init__(self, elems, levels_z, owned=None):
        self.e = elems
        self.levels_z = levels_z
        self.owned = owned or {}
        self.tx = None
        self.group = None
        self.group_saved = []
        self.errors = []
        self.calls = []
        self.late_drift = None

    def _state(self):
        import copy
        return copy.deepcopy(self.e)

    def checkout(self, ids):
        held = [i for i in ids if i not in self.owned]
        refused = [(i, u"Owned by " + self.owned[i]) for i in ids if i in self.owned]
        return held, refused

    def neighbours(self, i):
        nb = self.e[i].get("nb")
        return [nb] if nb is not None else []

    def snapshot(self, i):
        x = self.e[i]
        return (x.get("x", 0.0), 0.0, x["z"] + x.get("offset", 0.0))

    def set_level(self, i, route, target):
        x = self.e[i]
        if x["kind"] == "refuse":
            return False
        old = self.levels_z[x["level"]]
        new = self.levels_z[target]
        x["level"] = target
        if x["kind"] in ("drop", "stuck"):
            x["z"] += new - old            # moves with its level, offset unchanged
        if x["kind"] == "drag":
            self.e[x["nb"]]["z"] += 50 * FT
        if x["kind"] == "commit":
            self.errors = [u"Elements have duplicate Mark values"]
        return True

    def compensate(self, i, route, dz):
        x = self.e[i]
        if x["kind"] == "stuck":
            return []
        x["offset"] = core.compensated_offset(x.get("offset", 0.0), dz)
        return [u"Base Offset"]

    def move(self, i, dz):
        if self.e[i]["kind"] == "stuck":
            return False
        self.e[i]["z"] += dz
        return True

    def regenerate(self):
        self.calls.append("regen")

    def begin(self, name):
        self.tx = self._state()
        self.errors = []

    def commit(self):
        if self.errors:
            self.e = self.tx
            return False
        self.tx = None
        return True

    def rollback(self):
        self.e = self.tx
        self.tx = None

    def last_errors(self):
        return list(self.errors)

    def group_start(self, name):
        self.group_saved.append(self._state())

    def group_commit(self):
        self.group_saved.pop()
        self.group = "committed"

    def group_rollback(self):
        self.e = self.group_saved.pop()
        self.group = "rolled back"

    def delete_level(self, level, protect):
        gone = sorted([i for i, x in self.e.items() if x["level"] == level])
        hit = [i for i in gone if i in protect]
        if hit:
            return "blocked", hit, []
        for i in gone:
            del self.e[i]
        self.deleted_level = level
        return "ok", gone, []

    def level_of(self, i, route=None):
        x = self.e[i]
        if x["kind"] == "noread":
            return -1
        if self.late_drift is not None and i == self.late_drift:
            x["z"] += 3 * FT                   # something moves after the batches
            self.late_drift = None
        return x["level"]


LZ = {10: 0.0, 20: 3000 * FT, 30: 6000 * FT}


def fake_world():
    return {
        1: {"z": 2500 * FT, "level": 10, "kind": "hold"},
        2: {"z": 100 * FT, "level": 10, "kind": "drop"},
        3: {"z": 50 * FT, "level": 10, "kind": "stuck"},
        4: {"z": 10 * FT, "level": 10, "kind": "refuse"},
        5: {"z": 20 * FT, "level": 10, "kind": "drag", "nb": 50},
        50: {"z": 20 * FT, "level": 10, "kind": "hold"},
        6: {"z": 30 * FT, "level": 10, "kind": "commit"},
        7: {"z": 40 * FT, "level": 10, "kind": "hold"},
        8: {"z": 40 * FT, "level": 10, "kind": "noread"},
    }


def items(ids):
    return [{"id": i, "route": "RBS_START_LEVEL_PARAM"} for i in ids]


def test_assign():
    api = FakeApi(fake_world(), LZ, owned={7: u"Sam"})
    before = dict((i, api.snapshot(i)) for i in api.e)
    seen = []
    res = core.assign_levels(api, items([1, 2, 3, 4, 5, 6, 7, 8]), 20,
                             progress=lambda d, t: seen.append((d, t)))
    done = sorted(res["done"])
    refused = dict(res["refused"])
    check("held elements reassigned", 1 in done and api.e[1]["level"] == 20)
    check("dropping element compensated", 2 in done and 2 in res["compensated"])
    check("compensated element did not move", not core.has_moved(before[2], api.snapshot(2)))
    check("uncompensatable element refused", 3 in refused and u"would move" in refused[3])
    check("refused element left on its level", api.e[3]["level"] == 10)
    check("Revit refusal named", 4 in refused and u"Reference Level" in refused[4])
    check("dragged neighbour refused", 5 in refused and u"connected" in refused[5] and api.e[5]["level"] == 10)
    check("neighbour back where it was", not core.has_moved(before[50], api.snapshot(50)))
    check("commit refusal named", 6 in refused and u"Mark" in refused[6])
    check("owned element skipped", dict(res["skipped"]).get(7) == u"Owned by Sam")
    check("read-back mismatch refused", 8 in refused and u"read back" in refused[8])
    check("group kept", api.group == "committed" and not res["rolled_back"])
    check("nothing moved anywhere", all([not core.has_moved(before[i], api.snapshot(i)) for i in api.e]))
    check("progress reported", seen and seen[-1][0] == seen[-1][1])
    check("needs a look", core.needs_a_look(res))
    check("summary says nothing moved", u"Nothing moved" in core.result_summary(res))


def test_assign_clean():
    api = FakeApi({1: {"z": 0.0, "level": 10, "kind": "hold"},
                   2: {"z": 5 * FT, "level": 10, "kind": "drop"}}, LZ)
    res = core.assign_levels(api, items([1, 2]), 30)
    check("clean run", sorted(res["done"]) == [1, 2] and not core.needs_a_look(res))
    check("clean run one batch", res["refused"] == [])


def test_assign_proof():
    api = FakeApi({1: {"z": 0.0, "level": 10, "kind": "hold"},
                   2: {"z": 0.0, "level": 10, "kind": "hold"}}, LZ)
    api.late_drift = 2
    res = core.assign_levels(api, items([1, 2]), 20)
    check("final proof rolls everything back", res["rolled_back"] and res["done"] == [] and res["moved"])
    check("rolled back to the old level", api.e[1]["level"] == 10 and api.group == "rolled back")
    check("summary says nothing changed", core.result_summary(res).startswith(u"Nothing changed"))


def test_assign_batches():
    world = dict((i, {"z": float(i), "level": 10, "kind": "hold"}) for i in range(1, 101))
    world[57]["kind"] = "stuck"
    api = FakeApi(world, LZ)
    res = core.assign_levels(api, items(list(range(1, 101))), 30)
    check("one bad element does not lose its batch", len(res["done"]) == 99 and dict(res["refused"]).get(57))


# =========================================================================
# Revit-side helpers against fake elements
# =========================================================================

class FakeEnum(object):
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return str(other).split(".")[-1] == self.name

    def __ne__(self, other):
        return not self.__eq__(other)


class FakeId(object):
    def __init__(self, v):
        self.Value = v


class FakeParam(object):
    def __init__(self, level, ro=False):
        self.StorageType = FakeEnum("ElementId")
        self._lvl = level
        self.IsReadOnly = ro

    def AsElementId(self):
        return FakeId(self._lvl)


class FakeElem(object):
    def __init__(self, params, level_id=0):
        self.params = params
        self.LevelId = FakeId(level_id)

    def get_Parameter(self, member):
        return self.params.get(str(member).split(".")[-1])

    def LookupParameter(self, name):
        return self.params.get("name:" + name)


def test_revit_helpers():
    check("eid_value Value", rv.eid_value(FakeId(42)) == 42)
    check("eid_value None", rv.eid_value(None) == 0)
    hints = {}
    pipe = FakeElem({"RBS_START_LEVEL_PARAM": FakeParam(10)})
    route, lid, note = rv.find_route(pipe, 1, hints)
    check("pipe route", route == "RBS_START_LEVEL_PARAM" and lid == 10 and hints[1] == 0)
    col = FakeElem({"FAMILY_BASE_LEVEL_PARAM": FakeParam(20), "FAMILY_LEVEL_PARAM": FakeParam(20, ro=True)})
    route, lid, note = rv.find_route(col, 2, hints)
    check("column base level first", route == "FAMILY_BASE_LEVEL_PARAM")
    door = FakeElem({"FAMILY_LEVEL_PARAM": FakeParam(30, ro=True)})
    route, lid, note = rv.find_route(door, 3, hints)
    check("read-only level noted", route is None and lid == 30 and u"read-only" in note)
    hosted = FakeElem({"FAMILY_LEVEL_PARAM": FakeParam(10, ro=True),
                       "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM": FakeParam(20)})
    route, lid, note = rv.find_route(hosted, 4, hints)
    check("schedule level used when level is fixed", route == "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM" and lid == 20)
    named = FakeElem({"name:Reference Level": FakeParam(30)})
    route, lid, note = rv.find_route(named, 5, hints)
    check("name fallback route", route == "name:Reference Level" and lid == 30)
    bare = FakeElem({}, level_id=10)
    route, lid, note = rv.find_route(bare, 6, hints)
    check("LevelId fallback not editable", route is None and lid == 10)
    shift = rv.display_shift([{"disp": 10.0, "proj": 0.0}, {"disp": 13.0, "proj": 3.0}, {"disp": 3.0, "proj": 3.0}])
    check("display shift majority", abs(shift - 10.0) < 1e-9)


def test_delete_level():
    m = model()
    check("one level highlighted", core.single_level([core.level_key(10), core.elem_key(1)]) == 10)
    check("two levels: no delete", core.single_level([core.level_key(10), core.level_key(20)]) is None)
    check("no level: no delete", core.single_level([core.elem_key(1)]) is None)
    preview = {"items": [
        {"id": 5, "kind": "model", "name": u"Walls: 100 BLK"},
        {"id": 6, "kind": "model", "name": u"Rooms: Room 1"},
        {"id": 900, "kind": "view", "name": u"Level 01 - Floor Plan"},
        {"id": 901, "kind": "view", "name": u"Level 01 - Ceiling Plan"},
        {"id": 902, "kind": "viewport", "sheet": u"M-101 - Layout"},
        {"id": 903, "kind": "viewport", "sheet": u"M-101 - Layout"},
        {"id": 904, "kind": "viewport", "sheet": u"M-102 - Sections"},
        {"id": 905, "kind": "other", "name": u"Tag"},
    ], "active_blocked": False}
    imp = core.delete_impact(m, 20, preview)
    check("movable elements move", imp["moving"] == [5])
    check("locked element is lost", [i for i, n, w in imp["lost"]] == [6])
    check("views counted", len(imp["views"]) == 2)
    check("sheets: none deleted, two affected", imp["sheets_deleted"] == 0 and imp["sheets_affected"] == 2)
    lines = core.impact_lines(m, 20, 30, imp)
    text = u"\n".join(lines)
    check("impact names the target", u"Level 02" in lines[0])
    check("impact warns of deletion", u"DELETED" in text and u"Room 1" in text)
    check("impact says sheets deleted", u"Sheets deleted: 0." in text and u"2 sheets lose a view" in text)
    blocked = core.delete_impact(m, 20, dict(preview, active_blocked=True, active_name=u"Level 01"))
    check("active view blocks", blocked["blocked"] and blocked["active_name"] == u"Level 01")
    early = core.delete_impact(m, 20, {"items": [], "active_blocked": True, "active_name": u"Level 01"})
    check("active view blocks before any delete", early["blocked"] and not early["error"])
    api = FakeApi({1: {"z": 0.0, "level": 20, "kind": "hold"}}, LZ, owned={1: u"Sam"})
    res = core.delete_level(api, items([1]), 20, 30)
    check("owned elements stop the delete and say why", not res["ok"] and u"another user" in res["reason"]
          and 1 in api.e)

    world = {1: {"z": 0.0, "level": 20, "kind": "hold"},
             2: {"z": 9 * FT, "level": 20, "kind": "drop"},
             3: {"z": 5 * FT, "level": 20, "kind": "locked"},
             4: {"z": 1 * FT, "level": 10, "kind": "hold"}}
    api = FakeApi(world, LZ)
    res = core.delete_level(api, items([1, 2]), 20, 30)
    check("delete level ok", res["ok"] and api.group == "committed" and not api.group_saved)
    check("moved elements survive", 1 in api.e and 2 in api.e and api.e[2]["level"] == 30)
    check("locked element goes with the level", 3 not in api.e and res["deleted"] == [3])
    check("untouched level kept", api.e[4]["level"] == 10)

    world = {1: {"z": 0.0, "level": 20, "kind": "hold"},
             2: {"z": 0.0, "level": 20, "kind": "refuse"}}
    api = FakeApi(world, LZ)
    res = core.delete_level(api, items([1, 2]), 20, 30)
    check("refusal stops the delete", not res["ok"] and api.e[1]["level"] == 20 and 2 in api.e)
    check("refusal rolls back the move", api.group == "rolled back" and not api.group_saved)

    class Sticky(FakeApi):
        def delete_level(self, level, protect):
            return "blocked", sorted(protect), []
    api = Sticky({1: {"z": 0.0, "level": 20, "kind": "hold"}}, LZ)
    res = core.delete_level(api, items([1]), 20, 30)
    check("Revit still taking a moved element blocks", not res["ok"] and res["blocked"] == [1]
          and api.e[1]["level"] == 20)
    api = FakeApi({7: {"z": 0.0, "level": 10, "kind": "hold"}}, LZ)
    res = core.delete_level(api, [], 20, None)
    check("empty level deletes with no target", res["ok"])


def test_isolate_helpers():
    box = core.box_around([((0, 0, 0), (1, 1, 1)), None, ((-2, 0.5, 0), (0.5, 3, 2))], 0.5)
    check("box round everything plus margin", box == ((-2.5, -0.5, -0.5), (1.5, 3.5, 2.5)))
    check("no boxes", core.box_around([], 1) is None)
    check("default 3D names", core.default_3d_names(u"drew") == [u"{3D - drew}", u"{3D}"]
          and core.default_3d_names(u"") == [u"{3D}"])


# =========================================================================
# Shrink to taskbar - arithmetic, and the real Drawer on a stand-in window
# =========================================================================

import lvm_ui as ui  # noqa: E402

AREA = (0.0, 0.0, 1920.0, 1040.0)          # 40px taskbar at the bottom
AREA_ABOVE = (0.0, -1080.0, 1920.0, -40.0)  # a second monitor above the primary


def test_drawer_maths():
    check("ease starts at 0 and ends at 1", core.ease_out(0) == 0.0 and core.ease_out(1) == 1.0)
    check("ease is out (fast start)", core.ease_out(0.5) > 0.8)
    check("ease clamps", core.ease_out(-1) == 0.0 and core.ease_out(2) == 1.0)
    vals = [core.ease_out(i / 10.0) for i in range(11)]
    check("ease never goes back", all([b >= a for a, b in zip(vals, vals[1:])]))
    check("free slot reuses a gap", core.free_slot([0, 2]) == 1 and core.free_slot([]) == 0)
    check("bar lands above the taskbar", core.shrunk_top(1040, 52, []) == 1040 - 8 - 52)
    check("bars stack 4px apart", core.shrunk_top(1040, 44, [52]) == 1040 - 8 - 44 - 52 - 4)
    check("empty slot below counts as ours", core.slot_heights(2, {0: 52}, 44) == [52, 44])
    check("monitor above: bar stays on it", core.shrunk_top(AREA_ABOVE[3], 52, []) == -100.0)
    saved = (300.0, 120.0, 1240.0, 760.0)
    parked = (300.0, 980.0)
    check("unmoved bar opens where it was", core.expand_rect(saved, parked, parked, 52, AREA) == saved)
    r = core.expand_rect(saved, parked, (500.0, 900.0), 52, AREA)
    check("moved bar opens upward from where it sits", r == (500.0, 900.0 + 52 - 760.0, 1240.0, 760.0))
    r = core.expand_rect(saved, parked, (1500.0, 10.0), 52, AREA)
    check("moved bar opening is kept on screen", r[0] == 1920 - 1240 and r[1] == 0.0)
    r = core.expand_rect(saved, parked, (100.0, -300.0), 52, AREA_ABOVE)
    check("monitor above: opens on that monitor", AREA_ABOVE[1] <= r[1] and r[1] + r[3] <= AREA_ABOVE[3])
    r = core.expand_rect((0, 0, 3000, 2000), (0, 990), (0, 990), 52, AREA)
    check("larger than the screen is shrunk to fit", r[2] == 1920 and r[3] == 1040)
    check("a dragged bar is noticed", core.bar_moved((0, 0), (0, 5)) and not core.bar_moved((0, 0), (1, 1)))
    mid = core.frame_at((100, 760), (980, 52), 0.5)
    check("half way is past half way", mid[0] > 540 and mid[1] < 406)


class Ev(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self, *args):
        for fn in list(self.handlers):
            fn(*args)


class El(object):
    def __init__(self, vis="Visible", height=0.0):
        self.Visibility = vis
        self.ActualHeight = height
        self.Height = float("nan")
        self.VerticalAlignment = "Stretch"
        self.Children = []
        self.Parent = None
        self.CornerRadius = ("corner", "6,6,0,0")
        self.ToolTip = u""
        self.Click = Ev()
        self.MouseLeftButtonDown = Ev()

    def Equals(self, other):
        return self is other


class Win(El):
    """Height is watched: the smallest value it ever took is kept, so a
    window that blinks down to 1px mid-slide is caught."""

    def __init__(self, left=300.0, top=120.0, width=1240.0, height=760.0, sizing="Manual", laid_out=None):
        El.__init__(self)
        self.lowest = None
        self.Left, self.Top, self.Width, self.Height = left, top, width, height
        self.laid_out = laid_out
        self.MinHeight = 440.0
        self.MinWidth = 600.0
        self.SizeToContent = sizing
        self.Owner = None
        self.Content = El()
        self.Closed = Ev()
        self.PreviewKeyDown = Ev()
        self.names = {"ShrinkGlyph": El("Visible"), "ExpandGlyph": El("Collapsed")}
        self.activated = 0
        self.dragged = 0

    @property
    def Height(self):
        return self._h

    @Height.setter
    def Height(self, value):
        self._h = value
        if value == value and self.lowest is not None:
            self.lowest = min(self.lowest, value)
        elif value == value:
            self.lowest = value

    @property
    def ActualHeight(self):
        if self.laid_out is not None and self._h != self._h:
            return self.laid_out
        return self._h if self._h == self._h else 0.0

    @ActualHeight.setter
    def ActualHeight(self, value):
        pass

    @property
    def ActualWidth(self):
        return self.Width

    def FindName(self, name):
        return self.names.get(name)

    def Activate(self):
        self.activated += 1

    def DragMove(self):
        self.dragged += 1


class Enum(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


CLOCK = [0.0]
FRAMES = [0]


def fake_timer(drawer, step):
    while True:
        CLOCK[0] += 0.02
        FRAMES[0] += 1
        if not step():
            break


def ui_env():
    """Point lvm_ui at the stand-ins. Returns a restore function."""
    saved = {}
    patch = {
        "Visibility": Enum(Visible="Visible", Collapsed="Collapsed"),
        "SizeToContent": Enum(Manual="Manual", Height="Height"),
        "VerticalAlignment": Enum(Top="Top", Stretch="Stretch"),
        "CornerRadius": lambda r: ("corner", r),
        "_now": lambda: CLOCK[0],
        "_start_timer": fake_timer,
        "work_area": lambda w: AREA,
        "_header_offset": lambda h, w: 1.0,
        "Key": Enum(H="H", Escape="Escape", Enter="Enter", Return="Return", F11="F11", A="A"),
        "ModifierKeys": Enum(Control=2, Shift=4, NoModifier=0),
        "Keyboard": Enum(Modifiers=0),
        "XamlReader": Enum(Parse=lambda text: None),
    }
    for k, v in patch.items():
        saved[k] = getattr(ui, k)
        setattr(ui, k, v)
    del ui._DRAWERS[:]

    def restore():
        for k, v in saved.items():
            setattr(ui, k, v)
        del ui._DRAWERS[:]
    return restore


def build(win=None, header_h=50.0, extra_hidden=False, grips=True):
    win = win or Win()
    layout = El()
    header = El(height=header_h)
    header.Parent = layout
    body = El()
    progress = El("Collapsed" if extra_hidden else "Visible")
    layout.Children = [header, body, progress]
    btn = El()
    g = El() if grips else None
    d = ui.Drawer(win, header, btn, g, win.FindName("ShrinkGlyph"), win.FindName("ExpandGlyph"))
    return win, d, header, body, progress, btn, g


def test_drawer():
    restore = ui_env()
    try:
        win, d, header, body, progress, btn, grips = build(extra_hidden=True)
        FRAMES[0] = 0
        btn.Click.fire(btn, None)
        bar = 50.0 + 2.0
        check("drawer: parked as the header bar", d.state == "shrunk" and win.Height == bar)
        check("drawer: bar 8px above the taskbar", win.Top == AREA[3] - 8 - bar)
        check("drawer: it slides, it does not jump", FRAMES[0] >= 10)
        check("drawer: Left kept", win.Left == 300.0)
        check("drawer: body hidden once landed", body.Visibility == "Collapsed" and progress.Visibility == "Collapsed")
        check("drawer: header stays", header.Visibility == "Visible" and header.CornerRadius == ("corner", 6))
        check("drawer: grips parked with it", grips.Visibility == "Collapsed")
        check("drawer: green up arrow shown", win.names["ExpandGlyph"].Visibility == "Visible"
              and win.names["ShrinkGlyph"].Visibility == "Collapsed")
        check("drawer: MinHeight relaxed", win.MinHeight == 0)
        check("drawer: body unpinned after landing", win.Content.Height != win.Content.Height)   # NaN
        check("drawer: true size, not the bar", d.true_bounds() == (300.0, 120.0, 1240.0, 760.0))
        d.set_visibility(progress, "Visible")
        check("drawer: nothing appears inside the bar", progress.Visibility == "Collapsed")
        FRAMES[0] = 0
        btn.Click.fire(btn, None)
        check("drawer: opens back where it was", (win.Left, win.Top, win.Width, win.Height) == (300.0, 120.0, 1240.0, 760.0))
        check("drawer: opening slides too", FRAMES[0] >= 10)
        check("drawer: body back", body.Visibility == "Visible")
        check("drawer: change made while parked is kept", progress.Visibility == "Visible")
        check("drawer: MinHeight restored", win.MinHeight == 440.0)
        check("drawer: grips back", grips.Visibility == "Visible")
        check("drawer: shrink glyph back", win.names["ShrinkGlyph"].Visibility == "Visible"
              and win.names["ExpandGlyph"].Visibility == "Collapsed")
        check("drawer: corners back", header.CornerRadius == ("corner", "6,6,0,0"))
        check("drawer: activated on opening", win.activated == 1)
        check("drawer: slot freed", d.slot is None)

        d.shrink()
        win.Left, win.Top = 600.0, 900.0           # the bar is dragged
        d.expand()
        check("drawer: dragged bar opens upward from it", win.Left == 600.0 and win.Top == 900.0 + bar - 760.0)
        d.shrink()
        win.Left, win.Top = 600.0, 100.0           # dragged near the top
        d.expand()
        check("drawer: opening near the top stays on screen", win.Top == AREA[1])

        prompt = Win(width=460.0, height=float("nan"), sizing="Height", laid_out=180.0)
        _, dp, _, _, _, _, _ = build(prompt, header_h=42.0, grips=False)
        prompt.lowest = None
        dp.shrink()
        check("drawer: SizeToContent relaxed while parked", prompt.SizeToContent == "Manual")
        check("drawer: sized-to-text window keeps its real height", dp.saved[3] == 180.0
              and dp.true_bounds()[3] == 180.0)
        check("drawer: never smaller than its bar mid-slide", prompt.lowest >= 44.0)
        dp.expand()
        check("drawer: SizeToContent restored", prompt.SizeToContent == "Height")
        check("drawer: opens to its real height", prompt.Height == 180.0)
        win.lowest = None
        d.shrink()
        check("drawer: height held while it slides", FRAMES[0] > 0 and win.lowest == 52.0)
        d.expand()
    finally:
        restore()


def test_drawer_owners():
    restore = ui_env()
    try:
        main, dm, _, _, _, _, _ = build()
        dlg = Win(left=600.0, top=300.0, width=560.0, height=600.0)
        dlg.Owner = main
        _, dd, _, _, _, dbtn, _ = build(dlg, header_h=46.0, grips=False)
        dd.shrink()
        check("owners: a dialog takes the main window down", dm.state == "shrunk" and dd.state == "shrunk")
        check("owners: bars stack, not overlap", dm.slot == 0 and dd.slot == 1
              and dlg.Top == AREA[3] - 8 - 52 - 4 - 48)
        dd.expand()
        check("owners: opening the dialog brings the main window back", dm.state == "open"
              and (main.Top, main.Height) == (120.0, 760.0))
        dd.shrink()
        dlg.Closed.fire(dlg, None)
        check("owners: closing a parked dialog brings the main window back", dm.state == "open")
        check("owners: a closed window gives up its slot", dd not in ui._DRAWERS)

        res = Win(left=200.0, top=200.0, width=760.0, height=520.0)
        res.Owner = main
        _, dr, _, _, _, _, _ = build(res, header_h=46.0, grips=False)
        dm.shrink()
        check("owners: the main window takes an open Results window with it", dr.state == "shrunk")
        dm.expand()
        check("owners: and brings it back", dr.state == "open" and res.Height == 520.0)
        dm.toggle()
        check("owners: toggle shrinks", dm.state == "shrunk")
        dm.state = "closing"
        dm.toggle()
        check("owners: no double move while sliding", dm.state == "closing")
        dm.state = "shrunk"
    finally:
        restore()


def test_drawer_fault():
    restore = ui_env()
    real = core.frame_at
    try:
        def boom(*a):
            raise ValueError("frame")
        core.frame_at = boom
        win, d, _, body, _, _, _ = build()
        d.shrink()
        check("drawer: a frame that throws lands at the end state", d.state == "shrunk"
              and win.Height == 52.0 and body.Visibility == "Collapsed")
    finally:
        core.frame_at = real
        restore()


class Args(object):
    def __init__(self, key=None, clicks=1):
        self.Key = key
        self.ClickCount = clicks
        self.Handled = False
        self.HorizontalChange = 50.0
        self.VerticalChange = 50.0


def test_chrome_parked():
    restore = ui_env()
    try:
        win = Win()
        layout = El()
        header = El(height=50.0)
        header.Parent = layout
        layout.Children = [header, El()]
        shrink_btn = El()
        close_btn = El()
        full_btn = El()
        ch = ui.Chrome(win, header, close_btn, full_btn, None, None, shrink_btn)
        check("chrome: builds a drawer when given the button", ch.drawer is not None)
        ui.Keyboard.Modifiers = 6
        a = Args("H")
        ch._key(win, a)
        check("chrome: Ctrl+Shift+H shrinks", ch.drawer.state == "shrunk" and a.Handled)
        ui.Keyboard.Modifiers = 0
        ch._drag("R", 100.0, 100.0)
        check("chrome: no resizing while parked", win.Width == 1240.0 and win.Height == 52.0)
        ch.toggle_full()
        check("chrome: full screen opens it instead", ch.drawer.state == "open" and not ch.full)
        ch.drawer.shrink()
        a = Args("Escape")
        ch._key(win, a)
        check("chrome: Esc opens it rather than closing", ch.drawer.state == "open" and a.Handled)
        ch.drawer.shrink()
        a = Args("A")
        ch._key(win, a)
        check("chrome: other keys swallowed while parked", a.Handled and ch.drawer.state == "shrunk")
        ch._header_down(header, Args(clicks=1))
        check("chrome: the bar drags", win.dragged == 1 and ch.drawer.state == "shrunk")
        ch._header_down(header, Args(clicks=2))
        check("chrome: double-click on the bar opens it", ch.drawer.state == "open")
        ch.drawer.shrink()
        check("chrome: closing while parked saves the real size", ch.true_bounds() == (300.0, 120.0, 1240.0, 760.0))
        ui.open_parent(win)
        check("chrome: a dialog opening over a parked window opens it first", ch.drawer.state == "open")
        ch._enter_full()
        ch.drawer.shrink()
        check("chrome: full screen then parked saves the pre-full size", ch.true_bounds() == (300.0, 120.0, 1240.0, 760.0))
    finally:
        restore()


def test_debug_table():
    text = core.debug_table([[1, u"done", u"x"], [22, u"refused", u"why"]], [u"Element", u"Outcome", u"Detail"])
    lines = text.splitlines()
    check("debug table", len(lines) == 4 and lines[0].startswith(u"Element") and u"refused" in lines[3])


TESTS = [test_text, test_settings, test_theme, test_slow_clicks, test_logo_clicks, test_tree, test_filters,
         test_sort, test_ticks, test_params, test_plan, test_routes, test_assign,
         test_assign_clean, test_assign_proof, test_assign_batches, test_revit_helpers,
         test_delete_level, test_isolate_helpers, test_drawer_maths, test_drawer,
         test_drawer_owners, test_drawer_fault, test_chrome_parked, test_debug_table]


def run_all():
    del RESULTS[:]
    for t in TESTS:
        try:
            t()
        except Exception as ex:
            import traceback
            RESULTS.append((t.__name__ + " crashed", False, traceback.format_exc()))
    return [r for r in RESULTS if not r[1]]


# =========================================================================
# Self test: each breakage must make at least one check fail
# =========================================================================

def _swap(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    return lambda: setattr(obj, name, old)


BREAKAGES = [
    ("compensation sign flipped", lambda: _swap(core, "compensated_offset", lambda o, dz: o + dz)),
    ("moves never detected", lambda: _swap(core, "has_moved", lambda a, b, tol=0: False)),
    ("tick ignores the highlight", lambda: _swap(core.Model, "toggle_tick",
                                                 lambda self, key, highlighted=None: core.Model.__dict__["tick_ids"](self, self.ids_for_key(key)))),
    ("blanks sorted first", lambda: _swap(core.Model, "ordered",
                                          lambda self, ids: sorted([self.elements[i] for i in ids],
                                                                   key=lambda r: self.value(r, "elev")))),
    ("own filter in its own list", lambda: _swap(core.Model, "values_for",
                                                 lambda self, key, limit=3000: sorted(set(
                                                     [self.value(i, key) or core.BLANK for i in self.elements.values()
                                                      if self.passes(i)])))),
    ("Dark read by truthiness", lambda: _swap(core, "canvas_theme_is_dark",
                                              lambda v: True if v else (None if v is None else False))),
    ("slow click floor removed", lambda: _swap(core, "SLOW_FLOOR_MS", 0)),
    ("debug on by default", lambda: _swap(core, "DEFAULTS", dict(core.DEFAULTS, debug="1"))),
    ("movement tolerance swallowed", lambda: _swap(core, "MOVE_TOL_FT", 1.0e9)),
    ("read-only route accepted", lambda: _swap(rv, "find_route", lambda e, c, h: ("FAMILY_LEVEL_PARAM", 30, u""))),
    ("levels not sorted", lambda: _swap(core, "natural_key", lambda t: 0)),
    ("linear slide", lambda: _swap(core, "ease_out", lambda p: max(0.0, min(1.0, p)))),
    ("bars land on each other", lambda: _swap(core, "free_slot", lambda used: 0)),
    ("dragged bar ignored", lambda: _swap(core, "bar_moved", lambda a, b, tol=0: False)),
    ("opening not kept on screen", lambda: _swap(core, "expand_rect",
                                                 lambda s, p, n, b, a: (n[0], n[1] + b - s[3], s[2], s[3])
                                                 if core.bar_moved(p, n) else tuple(s))),
    ("visibility written into the bar", lambda: _swap(ui.Drawer, "set_visibility",
                                                      lambda self, el, v: setattr(el, "Visibility", v))),
    ("body left pinned", lambda: _swap(ui.Drawer, "_unpin", lambda self: None)),
    ("dialog does not lift its owner", lambda: _swap(ui, "drawer_of", lambda w: None)),
    ("NaN height saved", lambda: _swap(ui, "real_size", lambda a, d: d)),
    ("dialog centres on a parked bar", lambda: _swap(ui, "open_parent", lambda owner: None)),
    ("parked window still resizes", lambda: _swap(ui.Chrome, "parked", lambda self: False)),
    ("logo fires on one click", lambda: _swap(core.LogoClicks, "click", lambda self, ts: True)),
    ("logo reset ignored", lambda: _swap(core.LogoClicks, "reset", lambda self: None)),
    ("delete ignores refusals", lambda: _swap(core, "assign_levels",
                                              lambda api, it, t, p=None, l=None: core.new_result())),
    ("lost elements counted as moving", lambda: _swap(core, "delete_impact",
                                                      lambda m, s, p: dict(core.__dict__["_real_impact"](m, s, p), lost=[]))),
    ("section box margin dropped", lambda: _swap(core, "box_around",
                                                 lambda b, m: core.__dict__["_real_box"](b, 0))),
]

core._real_impact = core.delete_impact
core._real_box = core.box_around


def selftest():
    bad = 0
    base = run_all()
    if base:
        print("FAIL the checks do not pass before breaking anything:")
        for name, ok, detail in base:
            print("   " + name + (" - " + detail if detail else ""))
        return 1
    for label, breaker in BREAKAGES:
        restore = breaker()
        try:
            failures = run_all()
        finally:
            restore()
        if failures:
            print("ok   '{0}' caught by: {1}".format(label, failures[0][0]))
        else:
            print("FAIL '{0}' was NOT caught".format(label))
            bad += 1
    return bad


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        n = selftest()
        print("\nselftest: {0}".format("every breakage caught" if n == 0 else "{0} problem(s)".format(n)))
    else:
        fails = run_all()
        for name, ok, detail in RESULTS:
            print("{0} {1}".format("ok  " if ok else "FAIL", name))
            if not ok and detail:
                print("     " + detail.replace("\n", "\n     "))
        print("\nbench_logic: {0} checks, {1} failing".format(len(RESULTS), len(fails)))
        n = len(fails)
    sys.exit(1 if n else 0)
