# -*- coding: utf-8 -*-
"""Bench test of the rules themselves, under plain CPython with no stubs.

    python bench_logic.py

shtm_core, shtm_plan and shtm_rows carry no .NET at all, so the naming rules,
the duplication plan and the table's filtering, sorting and grouping can be run
exactly as shipped rather than in an approximation of them.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import shtm_core          # noqa: E402
import shtm_plan          # noqa: E402
import shtm_rows          # noqa: E402
import shtm_edit          # noqa: E402
import shtm_fill          # noqa: E402
import shtm_batch         # noqa: E402
import theme              # noqa: E402

PASSED = []
FAILED = []


def check(label, got, wanted):
    if got == wanted:
        PASSED.append(label)
    else:
        FAILED.append(u"{0}\n      got:    {1}\n      wanted: {2}".format(
            label, got, wanted))


def truthy(label, value):
    check(label, bool(value), True)


# ====================== naming ======================

def test_find_replace():
    check("find and replace ignores case by default",
          shtm_core.apply_find_replace(u"L01-Level 01", u"l01", u"L02"),
          u"L02-Level 01")
    check("match case leaves the wrong case alone",
          shtm_core.apply_find_replace(u"L01-Level 01", u"l01", u"L02", True),
          u"L01-Level 01")
    check("an empty find changes nothing",
          shtm_core.apply_find_replace(u"M-2100", u"", u"X"), u"M-2100")
    check("a dot in the find is not a wildcard",
          shtm_core.apply_find_replace(u"M-2100", u".", u"_"), u"M-2100")
    check("every occurrence is replaced",
          shtm_core.apply_find_replace(u"AA-AA", u"A", u"B"), u"BB-BB")
    check("replace then prefix, in that order",
          shtm_core.apply_rule(u"M-2100", u"2100", u"2200", u"WIP-"),
          u"WIP-M-2200")
    check("a prefix with no find and replace still lands",
          shtm_core.apply_rule(u"M-2100", u"", u"", u"C-"), u"C-M-2100")


def test_name_push_plan():
    grouping = [u"BGL_Sheet Stage", u"BGL_Sheet Discipline"]
    params = [u"BGL_Sheet Stage", u"BGL_Sheet Discipline", u"BGL_Sheet Series"]
    writes, skipped = shtm_core.name_push_plan(
        u"S4_Level 01_Right", params, grouping)
    check("a parameter the grouping is writing is left alone",
          skipped, [u"BGL_Sheet Stage", u"BGL_Sheet Discipline"])
    check("and only the rest is written from the name",
          writes, [(u"BGL_Sheet Series", u"Right")])

    writes, skipped = shtm_core.name_push_plan(
        u"S4_Level 01_Right", params, [])
    check("with no overlap every segment goes to its own parameter",
          writes, [(u"BGL_Sheet Stage", u"S4"),
                   (u"BGL_Sheet Discipline", u"Level 01"),
                   (u"BGL_Sheet Series", u"Right")])

    writes, skipped = shtm_core.name_push_plan(
        u"S4_Level 01_Right", params, [u"BGL_Sheet Discipline"])
    check("skipping one does not shift the segments after it",
          writes, [(u"BGL_Sheet Stage", u"S4"),
                   (u"BGL_Sheet Series", u"Right")])

    writes, skipped = shtm_core.name_push_plan(u"S4_A_B_C_D", params, [])
    check("extra segments still join onto the last parameter",
          writes[-1], (u"BGL_Sheet Series", u"B_C_D"))

    check("no parameters mapped means nothing is written",
          shtm_core.name_push_plan(u"S4_A", [], [])[0], [])
    check("a blank slot keeps its place rather than shuffling the rest up",
          shtm_core.name_push_plan(u"S4_A", [u"", u"BGL_X"], [])[0],
          [(u"BGL_X", u"A")])
    check("trailing blank slots are not slots at all",
          shtm_core.name_push_plan(u"S4_A", [u"BGL_X", u"", u""], [])[0],
          [(u"BGL_X", u"S4_A")])
    check("slots round trip through the settings text",
          shtm_core.split_slots(shtm_core.join_slots([u"", u"BGL_X", u""])),
          [u"", u"BGL_X"])


class _Extent(object):
    """Stands in for DatumExtentType, which compares by identity."""

    def __init__(self, label):
        self.label = label


MODEL = _Extent("Model")
VIEW_SPECIFIC = _Extent("ViewSpecific")


def test_datum_extents():
    check("both ends 3D: the line is the model's, so leave it alone",
          shtm_core.datum_needs_curve([MODEL, MODEL], VIEW_SPECIFIC), False)
    check("both ends view specific: copy the line",
          shtm_core.datum_needs_curve([VIEW_SPECIFIC, VIEW_SPECIFIC],
                                      VIEW_SPECIFIC), True)
    check("one end stretched is enough",
          shtm_core.datum_needs_curve([MODEL, VIEW_SPECIFIC], VIEW_SPECIFIC),
          True)
    check("an end Revit would not report does not decide it",
          shtm_core.datum_needs_curve([None, None], VIEW_SPECIFIC), False)
    check("nothing read means nothing written",
          shtm_core.datum_needs_curve([], VIEW_SPECIFIC), False)


def test_fit_line():
    # the new view's own line, at its cut plane of z=5, and the old view's
    # stretched line at z=3 - same grid, different cut plane
    current = ((0.0, 0.0, 5.0), (100.0, 0.0, 5.0))
    wanted = ((20.0, 0.0, 3.0), (60.0, 0.0, 3.0))
    check("the head and tail land on the target's own line, at its own z",
          shtm_core.fit_line(current, wanted),
          ((20.0, 0.0, 5.0), (60.0, 0.0, 5.0)))
    check("a hair off the line is projected onto it",
          shtm_core.fit_line(current, ((20.0, 0.2, 3.0), (60.0, -0.1, 3.0))),
          ((20.0, 0.0, 5.0), (60.0, 0.0, 5.0)))
    check("ends the other way round come back in the target's order",
          shtm_core.fit_line(current, ((60.0, 0.0, 3.0), (20.0, 0.0, 3.0))),
          ((20.0, 0.0, 5.0), (60.0, 0.0, 5.0)))
    check("a line stretched past the target's ends is still just projected",
          shtm_core.fit_line(current, ((-10.0, 0.0, 3.0), (150.0, 0.0, 3.0))),
          ((-10.0, 0.0, 5.0), (150.0, 0.0, 5.0)))
    diagonal = ((0.0, 0.0, 0.0), (10.0, 10.0, 0.0))
    got = shtm_core.fit_line(diagonal, ((2.0, 2.0, 9.0), (7.0, 7.0, 9.0)))
    truthy("a diagonal grid projects along itself",
           shtm_core.same_line(got, ((2.0, 2.0, 0.0), (7.0, 7.0, 0.0))))
    check("a wanted line square to the grid collapses and is refused",
          shtm_core.fit_line(current, ((30.0, -5.0, 3.0), (30.0, 5.0, 3.0))),
          None)
    check("no current line means nothing to fit to",
          shtm_core.fit_line(None, wanted), None)
    check("no wanted line means nothing to fit",
          shtm_core.fit_line(current, None), None)


def test_same_line():
    a = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    check("the same line is the same line", shtm_core.same_line(a, a), True)
    check("ends reported the other way round is still the same line",
          shtm_core.same_line(a, (a[1], a[0])), True)
    check("a shorter line is not",
          shtm_core.same_line(a, ((0.0, 0.0, 0.0), (9.0, 0.0, 0.0))), False)
    check("a difference under a millimetre does not count",
          shtm_core.same_line(a, ((0.0, 0.0, 0.0), (10.002, 0.0, 0.0))), True)
    check("a difference over it does",
          shtm_core.same_line(a, ((0.0, 0.0, 0.0), (10.02, 0.0, 0.0))), False)
    check("no line either side is agreement",
          shtm_core.same_line(None, None), True)
    check("a line where there should be none is not",
          shtm_core.same_line(a, None), False)
    check("nothing where there should be a line is not",
          shtm_core.same_line(None, a), False)


def test_titleblock_copy():
    sheet = [u"Sheet Number", u"Sheet Name", u"BGL_Sheet Stage", u"Drawn By"]
    titleblock = [u"Sheet Number", u"Sheet Name", u"Drawn By",
                  u"BGL_Titleblock Variant", u"Scale Bar"]
    wanted = shtm_core.titleblock_copy_names(
        titleblock, sheet, [u"Current Revision"])
    check("a title block keeps only what is really its own",
          wanted, [u"BGL_Titleblock Variant", u"Scale Bar"])
    truthy("the sheet number is never copied through a title block",
           u"Sheet Number" not in wanted)
    check("the skip list still applies on top",
          shtm_core.titleblock_copy_names(
              [u"Current Revision", u"Scale Bar"], [], [u"Current Revision"]),
          [u"Scale Bar"])
    check("nothing in and nothing out",
          shtm_core.titleblock_copy_names([], [], []), [])


def test_example_line():
    check("the example shows the change",
          shtm_core.example_line(u"e.g.", u"M-2100", u"M-2200"),
          u"e.g.  M-2100   \u2192   M-2200")
    check("a rule that changes nothing says so",
          shtm_core.example_line(u"e.g.", u"M-2100", u"M-2100"),
          u"e.g.  M-2100  -  unchanged")
    check("an empty pair does not throw",
          shtm_core.example_line(u"e.g.", None, None),
          u"e.g.    -  unchanged")


def test_unique_name():
    taken = set([u"floor plan"])
    check("a free name is taken as it is",
          shtm_core.unique_name(u"Ceiling Plan", taken), u"Ceiling Plan")
    check("a taken name steps to 2",
          shtm_core.unique_name(u"Floor Plan", taken), u"Floor Plan 2")
    check("and then to 3",
          shtm_core.unique_name(u"Floor Plan", taken), u"Floor Plan 3")
    check("an empty name does not come back empty",
          shtm_core.unique_name(u"", set()), u"Unnamed")


def test_natural_sort():
    numbers = [u"M-A10", u"M-A9", u"M-A100", u"M-A1"]
    numbers.sort(key=shtm_core.natural_key)
    check("drawing numbers sort the way people read them",
          numbers, [u"M-A1", u"M-A9", u"M-A10", u"M-A100"])
    check("a blank sorts without throwing",
          shtm_core.natural_key(u"") == shtm_core.natural_key(None), True)


def test_name_segments():
    check("exactly as many segments as parameters",
          shtm_core.split_name_segments(u"S3_M_VENT_WIP", 4),
          [u"S3", u"M", u"VENT", u"WIP"])
    check("fewer segments pad out",
          shtm_core.split_name_segments(u"S3_M", 4), [u"S3", u"M", u"", u""])
    check("extra segments join onto the last parameter",
          shtm_core.split_name_segments(u"S3_M_VENT_WIP_REV_B", 4),
          [u"S3", u"M", u"VENT", u"WIP_REV_B"])
    check("no parameters means nothing is written",
          shtm_core.split_name_segments(u"S3_M", 0), [])


def test_flags_and_lists():
    check("as_bool takes the spellings a settings file carries",
          [shtm_core.as_bool(v) for v in ("1", "true", "YES", "on", "0", "", "no")],
          [True, True, True, True, False, False, False])
    check("split_list drops blanks and duplicates but keeps order",
          shtm_core.split_list(u"B| A |B|  |C"), [u"B", u"A", u"C"])
    check("join_list round trips",
          shtm_core.join_list([u"B", u"A"]), u"B|A")


class _Value(object):
    Value = 1234


class _Old(object):
    @property
    def Value(self):
        raise AttributeError("Value went in 2024")

    IntegerValue = 5678


def test_eid_value():
    check("eid_value prefers .Value", shtm_core.eid_value(_Value()), 1234)
    check("eid_value falls back to .IntegerValue",
          shtm_core.eid_value(_Old()), 5678)
    check("eid_value of nothing is 0", shtm_core.eid_value(None), 0)


# ====================== settings ======================

def test_every_setting_survives_a_reload():
    folder = tempfile.mkdtemp(prefix="shtm_roundtrip_")
    try:
        path = os.path.join(folder, "s.txt")
        values = shtm_core.load_settings(path)
        for key in shtm_core.DEFAULTS:
            if key == "settings_version":
                continue
            values[key] = u"sentinel {0} = a|b".format(key)
        shtm_core.save_settings(values, path)
        back = shtm_core.load_settings(path)
        lost = [k for k in shtm_core.DEFAULTS
                if k != "settings_version" and back[k] != values[k]]
        check("every setting survives a save and a reload", lost, [])
        top = max([int(k) for k in list(shtm_core.MIGRATIONS) +
                   list(shtm_core.FILL_IF_BLANK)] or [0])
        check("the settings version is at least the highest migration",
              int(shtm_core.SETTINGS_VERSION) >= top, True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_name_push_defaults():
    check("the sheet name push defaults to the three BGL parameters",
          shtm_core.split_slots(shtm_core.DEFAULTS["name_parameters"]),
          [u"BGL_Sheet Name 1", u"BGL_Sheet Name 2", u"BGL_Sheet Name 3"])
    check("and never shares a parameter with the grouping defaults",
          set(shtm_core.split_slots(shtm_core.DEFAULTS["name_parameters"])) &
          set(shtm_core.DEFAULT_GROUPING), set())
    folder = tempfile.mkdtemp(prefix="shtm_fill_")
    try:
        path = os.path.join(folder, "s.txt")

        def older(name_parameters):
            handle = open(path, "wb")
            handle.write((u"settings_version=2\nname_parameters={0}\ntheme=light\n"
                          .format(name_parameters)).encode("utf-8"))
            handle.close()
            return shtm_core.load_settings(path)

        check("an older file with no mapping takes the new default",
              older(u"")["name_parameters"], shtm_core.DEFAULTS["name_parameters"])
        check("nor does a mapping of empty slots",
              older(u"||")["name_parameters"], shtm_core.DEFAULTS["name_parameters"])
        check("an older file with a mapping of its own keeps it",
              older(u"ABC_Part 1|ABC_Part 2")["name_parameters"],
              u"ABC_Part 1|ABC_Part 2")
        check("and everything else in it is kept", older(u"")["theme"], u"light")
        values = shtm_core.load_settings(path)
        values["name_parameters"] = u""
        shtm_core.save_settings(values, path)
        check("a mapping cleared on purpose since stays cleared",
              shtm_core.load_settings(path)["name_parameters"], u"")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_settings():
    folder = tempfile.mkdtemp(prefix="shtm_settings_")
    try:
        path = os.path.join(folder, "sheet_manager.txt")
        check("a missing file is the defaults",
              shtm_core.load_settings(path)["name_parameters"],
              shtm_core.DEFAULTS["name_parameters"])
        check("the name parameters do not default to the grouping ones",
              set(shtm_core.split_slots(shtm_core.DEFAULTS["name_parameters"])) &
              set(shtm_core.DEFAULT_GROUPING), set())

        values = shtm_core.load_settings(path)
        values["dup_name_prefix"] = u"WIP-"
        values["columns"] = u"BGL_Sheet Stage|BGL_Sheet Series"
        shtm_core.save_settings(values, path)
        back = shtm_core.load_settings(path)
        check("settings round trip", back["dup_name_prefix"], u"WIP-")
        check("a value holding a bar round trips",
              back["columns"], u"BGL_Sheet Stage|BGL_Sheet Series")

        handle = open(path, "ab")
        handle.write(b"something_nobody_ships=1\n")
        handle.close()
        check("a key from another version is ignored rather than breaking the load",
              "something_nobody_ships" in shtm_core.load_settings(path), False)

        handle = open(path, "wb")
        handle.write(b"this file is not key=value at all\n\x00\x01")
        handle.close()
        check("a damaged file falls back to the defaults",
              shtm_core.load_settings(path)["theme"], "auto")

        held = dict(shtm_core.MIGRATIONS)
        shtm_core.MIGRATIONS["2"] = ["dup_name_prefix"]
        try:
            values = dict(shtm_core.DEFAULTS)
            values["settings_version"] = "1"
            values["dup_name_prefix"] = u"OLD-"
            shtm_core.save_settings(values, path)
            check("a migration resets the key whose meaning changed",
                  shtm_core.load_settings(path)["dup_name_prefix"], u"")
        finally:
            shtm_core.MIGRATIONS.clear()
            shtm_core.MIGRATIONS.update(held)

        values = dict(shtm_core.DEFAULTS)
        values["dup_legends"] = "duplicate"
        values["theme"] = "light"
        shtm_core.reset_duplicate_options(values)
        check("resetting the duplicate options puts dup_legends back",
              values["dup_legends"], "reuse")
        check("resetting the duplicate options leaves the theme alone",
              values["theme"], "light")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ====================== the sheet preview ======================

SOURCES = [
    {"id": 1, "number": u"M-2100", "name": u"S3_M_VENT_L00"},
    {"id": 2, "number": u"M-2101", "name": u"S3_M_VENT_L01"},
]


def rules(**kwargs):
    base = {"number_find": u"", "number_replace": u"", "number_prefix": u"",
            "name_find": u"", "name_replace": u"", "name_prefix": u"",
            "match_case": False}
    base.update(kwargs)
    return base


def test_preview_sheets():
    rows = shtm_core.preview_sheets(
        SOURCES, rules(number_find=u"M-21", number_replace=u"M-22",
                       name_find=u"VENT", name_replace=u"HEAT"),
        [u"M-2100", u"M-2101"])
    check("the new number comes from find and replace",
          [r["new_number"] for r in rows], [u"M-2200", u"M-2201"])
    check("the new name comes from its own find and replace",
          [r["new_name"] for r in rows], [u"S3_M_HEAT_L00", u"S3_M_HEAT_L01"])
    check("nothing is flagged when the numbers are free",
          set([r["status"] for r in rows]), set(["ok"]))

    rows = shtm_core.preview_sheets(SOURCES, rules(), [u"M-2100", u"M-2101"])
    check("a number that is already in the project is blocked",
          [r["status"] for r in rows], ["bad", "bad"])
    truthy("and the row says why", u"already exists" in rows[0]["note"])

    rows = shtm_core.preview_sheets(
        SOURCES, rules(number_prefix=u"X-"), [u"M-2100", u"M-2101"])
    check("a prefix is enough to clear the clash",
          [r["new_number"] for r in rows], [u"X-M-2100", u"X-M-2101"])
    check("and the rows go green", set([r["status"] for r in rows]), set(["ok"]))

    clashing = [{"id": 1, "number": u"M-2100", "name": u"A"},
                {"id": 2, "number": u"M-2100", "name": u"B"}]
    rows = shtm_core.preview_sheets(
        clashing, rules(number_prefix=u"X-"), [])
    check("two sources landing on one number: the second is blocked",
          [r["status"] for r in rows], ["ok", "bad"])

    rows = shtm_core.preview_sheets(
        [{"id": 1, "number": u"M-2100", "name": u"A"}],
        rules(number_find=u"M-2100", number_replace=u""), [])
    check("an empty new number is blocked", rows[0]["status"], "bad")

    rows = shtm_core.preview_sheets(
        [{"id": 1, "number": u"M-2100", "name": u"A"}], rules(), [])
    check("a number identical to the source is a warning, not a block",
          rows[0]["status"], "warn")

    rows = shtm_core.preview_sheets(
        [{"id": 1, "number": u"M-2100", "name": u"Same Name"},
         {"id": 2, "number": u"M-2101", "name": u"Same Name"}],
        rules(number_prefix=u"X-"), [])
    check("sheet names are not stepped - Revit allows two the same",
          [r["new_name"] for r in rows], [u"Same Name", u"Same Name"])


# ====================== the plan ======================

VIEWS = {
    10: {"id": 10, "name": u"L00 Parent", "kind": "model", "type": u"FloorPlan",
         "primary": 0},
    11: {"id": 11, "name": u"L00 Dep A", "kind": "model", "type": u"FloorPlan",
         "primary": 10},
    12: {"id": 12, "name": u"L00 Dep B", "kind": "model", "type": u"FloorPlan",
         "primary": 10},
    20: {"id": 20, "name": u"Section 1", "kind": "model", "type": u"Section",
         "primary": 0},
    30: {"id": 30, "name": u"Legend - Vent", "kind": "legend", "type": u"Legend",
         "primary": 0},
    40: {"id": 40, "name": u"Detail 1", "kind": "drafting", "type": u"DraftingView",
         "primary": 0},
    50: {"id": 50, "name": u"Sheet List", "kind": "schedule", "type": u"Schedule",
         "primary": 0},
}


def options(**kwargs):
    base = {"legends": "reuse", "schedules": "reuse", "drafting": "duplicate",
            "parents": True, "all_dependents": True, "place_new_parent": True}
    base.update(kwargs)
    return base


def test_classify():
    check("a legend is placed again by default",
          shtm_plan.classify(VIEWS[30], options()), shtm_plan.REUSE)
    check("a legend is duplicated when that is asked for",
          shtm_plan.classify(VIEWS[30], options(legends="duplicate")),
          shtm_plan.DUPLICATE)
    check("a schedule is placed again by default",
          shtm_plan.classify(VIEWS[50], options()), shtm_plan.REUSE)
    check("a drafting view is duplicated by default",
          shtm_plan.classify(VIEWS[40], options()), shtm_plan.DUPLICATE)
    check("a dependent goes down the dependent route",
          shtm_plan.classify(VIEWS[11], options()), shtm_plan.DEPENDENT)
    check("a dependent always keeps its parent, whatever an old setting says",
          shtm_plan.classify(VIEWS[11], options(parents=False)),
          shtm_plan.DEPENDENT)
    check("a plain model view is duplicated",
          shtm_plan.classify(VIEWS[20], options()), shtm_plan.DUPLICATE)


def placements(*pairs):
    rows = []
    for index, pair in enumerate(pairs):
        sheet, view = pair[0], pair[1]
        kind = pair[2] if len(pair) > 2 else "viewport"
        rows.append({"sheet": sheet, "view": view, "kind": kind, "id": 900 + index})
    return rows


def actions(plan):
    return dict([(j["old_id"], j["action"]) for j in plan["jobs"]])


def test_plan_dependents():
    # sheet 1 carries dependent A, sheet 2 carries dependent B, both selected
    plan = shtm_plan.build_plan([1, 2], placements((1, 11), (2, 12)),
                                VIEWS, options())
    check("the parent is duplicated once", actions(plan).get(10), shtm_plan.PARENT)
    check("dependent A comes across", actions(plan).get(11), shtm_plan.DEPENDENT)
    check("dependent B comes across", actions(plan).get(12), shtm_plan.DEPENDENT)
    check("three view jobs in total", len(plan["jobs"]), 3)
    order = [j["action"] for j in plan["jobs"]]
    check("the parent is made before its dependents",
          order.index(shtm_plan.PARENT) < order.index(shtm_plan.DEPENDENT), True)
    check("both dependents land on a sheet", len(plan["placements"]), 2)
    check("only the parent is left unplaced",
          [j["old_id"] for j in plan["unplaced"]], [10])


def test_plan_unselected_sibling():
    # only sheet 1 is selected; dependent B lives on sheet 2, which is not
    plan = shtm_plan.build_plan([1], placements((1, 11), (2, 12)),
                                VIEWS, options())
    check("the sibling dependent is made anyway",
          actions(plan).get(12), shtm_plan.DEPENDENT)
    check("but it lands on no sheet",
          sorted([j["old_id"] for j in plan["unplaced"]]), [10, 12])

    plan = shtm_plan.build_plan([1], placements((1, 11), (2, 12)),
                                VIEWS, options(all_dependents=False))
    check("with that switched off the sibling is not made at all",
          12 in actions(plan), False)


def test_plan_parent_on_a_sheet():
    # the parent itself is on a selected sheet, and so is one of its dependents
    plan = shtm_plan.build_plan([1, 2], placements((1, 10), (2, 11)),
                                VIEWS, options())
    check("the parent is placed on its own new sheet",
          sorted([p["view"] for p in plan["placements"]]), [10, 11])
    check("only the sibling dependent with no sheet is left unplaced",
          [j["old_id"] for j in plan["unplaced"]], [12])

    plan = shtm_plan.build_plan([1, 2], placements((1, 10), (2, 11)),
                                VIEWS, options(place_new_parent=False))
    check("switching that off leaves the new parent off its sheet",
          [p["view"] for p in plan["placements"]], [11])
    check("and the parent turns up in the unplaced list",
          sorted([j["old_id"] for j in plan["unplaced"]]), [10, 12])
    check("the parent is still made", actions(plan).get(10), shtm_plan.DUPLICATE)
    check("and it is marked as the primary",
          [j["is_primary"] for j in plan["jobs"] if j["old_id"] == 10], [True])


def test_plan_reuse_and_placements():
    plan = shtm_plan.build_plan(
        [1, 2], placements((1, 30), (2, 30), (1, 40), (1, 50, "schedule")),
        VIEWS, options())
    check("a legend on two sheets is one job", actions(plan).get(30),
          shtm_plan.REUSE)
    check("and two placements",
          len([p for p in plan["placements"] if p["view"] == 30]), 2)
    check("a drafting view is duplicated", actions(plan).get(40),
          shtm_plan.DUPLICATE)
    check("a schedule is placed again", actions(plan).get(50), shtm_plan.REUSE)
    check("the schedule placement keeps its kind",
          [p["kind"] for p in plan["placements"] if p["view"] == 50], ["schedule"])
    check("the source element id is carried through for the placement",
          all([p.get("src") for p in plan["placements"]]), True)


def test_plan_names():
    plan = shtm_plan.build_plan([1], placements((1, 20), (1, 30)),
                                VIEWS, options())
    shtm_plan.name_the_plan(plan, {"find": u"Section", "replace": u"Sec",
                                   "prefix": u"WIP ", "match_case": False},
                            [u"Section 1", u"Legend - Vent"])
    names = dict([(j["old_id"], j["new_name"]) for j in plan["jobs"]])
    check("a duplicated view is renamed by the rule", names[20], u"WIP Sec 1")
    check("a reused view keeps its own name", names[30], u"Legend - Vent")

    plan = shtm_plan.build_plan([1], placements((1, 20)), VIEWS, options())
    shtm_plan.name_the_plan(plan, {"find": u"", "replace": u"", "prefix": u"",
                                   "match_case": False}, [u"Section 1"])
    check("a name Revit already has is stepped rather than refused",
          plan["jobs"][0]["new_name"], u"Section 1 2")
    truthy("and the row says it was stepped", plan["jobs"][0]["renamed"])


def test_plan_summary():
    plan = shtm_plan.build_plan([1, 2], placements((1, 11), (2, 12), (1, 30)),
                                VIEWS, options())
    rows = shtm_core.preview_sheets(SOURCES, rules(number_prefix=u"X-"), [])
    lines = shtm_plan.plan_summary(plan, rows)
    truthy("the summary counts the sheets", u"2 new sheet(s)" in lines)
    truthy("the summary counts the dependents",
           u"2 dependent view(s) created" in lines)
    check("blockers picks out only the bad rows",
          len(shtm_plan.blockers(shtm_core.preview_sheets(
              SOURCES, rules(), [u"M-2100"]))), 1)


# ====================== the table ======================

SHEETS = [
    {"id": 1, "values": {u"Sheet Number": u"M-2100", u"Sheet Name": u"Vent L00",
                         u"BGL_Sheet Stage": u"S3", u"BGL_Sheet Series": u"21"}},
    {"id": 2, "values": {u"Sheet Number": u"M-2101", u"Sheet Name": u"Vent L01",
                         u"BGL_Sheet Stage": u"S3", u"BGL_Sheet Series": u"21"}},
    {"id": 3, "values": {u"Sheet Number": u"E-3100", u"Sheet Name": u"Power L00",
                         u"BGL_Sheet Stage": u"S4", u"BGL_Sheet Series": u"31"}},
    {"id": 4, "values": {u"Sheet Number": u"E-3101", u"Sheet Name": u"Power L01",
                         u"BGL_Sheet Stage": u"S4", u"BGL_Sheet Series": u""}},
]


def state(**kwargs):
    value = shtm_rows.GridState()
    value.columns = [u"Sheet Number", u"Sheet Name", u"BGL_Sheet Stage",
                     u"BGL_Sheet Series"]
    # most of these tests are about filtering and sorting, not grouping, so the
    # default that makes the table group by what it is sorted by is turned off
    # unless a test asks for it
    value.group_by_sort = False
    for key in kwargs:
        setattr(value, key, kwargs[key])
    return value


def test_filtering():
    rows, shown = shtm_rows.compute_rows(SHEETS, state())
    check("with nothing set every sheet shows", shown, 4)
    check("and they sort by number", [r.values[u"Sheet Number"] for r in rows],
          [u"E-3100", u"E-3101", u"M-2100", u"M-2101"])

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(sorts=[(u"Sheet Number", False)]))
    check("descending reverses them", rows[0].values[u"Sheet Number"], u"M-2101")

    rows, shown = shtm_rows.compute_rows(SHEETS, state(search_all=u"power"))
    check("the search box searches every column", shown, 2)

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(search_all=u"power l01"))
    check("two words both have to be found", shown, 1)

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(searches={u"BGL_Sheet Stage": u"S4"}))
    check("a column search narrows to that column", shown, 2)

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(filters={u"BGL_Sheet Stage": set([u"S3"])}))
    check("a tick filter narrows to what is ticked", shown, 2)

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(filters={u"BGL_Sheet Stage": set()}))
    check("nothing ticked shows nothing", shown, 0)

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(filters={u"BGL_Sheet Series": set([u""])}))
    check("a blank is a value a tick filter can hold", shown, 1)


def test_sort_levels():
    value = state()
    check("it opens sorted on the drawing number",
          value.sorts, [(u"Sheet Number", True)])

    value.toggle_sort(u"Sheet Number")
    check("clicking the same heading again flips it",
          value.sorts, [(u"Sheet Number", False)])

    value.toggle_sort(u"BGL_Sheet Stage")
    check("clicking a different heading replaces the sort",
          value.sorts, [(u"BGL_Sheet Stage", True)])

    value.toggle_sort(u"Sheet Name", True)
    check("shift adds a second level rather than replacing",
          value.sorts, [(u"BGL_Sheet Stage", True), (u"Sheet Name", True)])
    check("the primary is outlined first", value.sort_index(u"BGL_Sheet Stage"), 0)
    check("the second level knows it is second",
          value.sort_index(u"Sheet Name"), 1)
    check("a column not sorted on has no outline",
          value.sort_index(u"Sheet Number"), -1)

    value.toggle_sort(u"Sheet Name", True)
    check("shift on a level already there flips that level",
          value.sorts, [(u"BGL_Sheet Stage", True), (u"Sheet Name", False)])

    value.toggle_sort(u"Sheet Number", True)
    check("three levels are allowed", len(value.sorts), 3)
    value.toggle_sort(u"BGL_Sheet Series", True)
    check("and up to six", len(value.sorts), 4)
    value.columns = value.columns + [u"A", u"B", u"C"]
    value.toggle_sort(u"A", True)
    value.toggle_sort(u"B", True)
    check("six is the ceiling", len(value.sorts), 6)
    check("a seventh is refused", value.toggle_sort(u"C", True), False)
    value.columns = value.columns[:4]

    value.toggle_sort(u"Sheet Number")
    check("a plain click clears the levels back to one",
          value.sorts, [(u"Sheet Number", True)])

    # two levels doing real work: stage descending, then number ascending
    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(sorts=[(u"BGL_Sheet Stage", False),
                             (u"Sheet Number", True)]))
    check("the second level orders within the first",
          [r.values[u"Sheet Number"] for r in rows],
          [u"E-3100", u"E-3101", u"M-2100", u"M-2101"])
    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(sorts=[(u"BGL_Sheet Stage", True),
                             (u"Sheet Number", False)]))
    check("a descending second level does not disturb the first",
          [r.values[u"Sheet Number"] for r in rows],
          [u"M-2101", u"M-2100", u"E-3101", u"E-3100"])
    check("and the groups follow the same order",
          [r.values[u"BGL_Sheet Stage"] for r in rows],
          [u"S3", u"S3", u"S4", u"S4"])

    value = state(columns=[u"Sheet Number", u"Sheet Name"],
                  sorts=[(u"BGL_Sheet Stage", True), (u"Sheet Number", True)])
    value.drop_missing_sorts()
    check("a column taken out of the table stops being sorted on",
          value.sorts, [(u"Sheet Number", True)])


def test_group_by_sort():
    fresh = shtm_rows.GridState()
    check("a new table groups by what it is sorted by", fresh.group_by_sort, True)

    value = state(sorts=[(u"BGL_Sheet Stage", True)], group_by_sort=True)
    check("group by sort follows the sort columns",
          value.grouping(), [u"BGL_Sheet Stage"])
    rows, shown = shtm_rows.compute_rows(SHEETS, value)
    check("so the table groups by them",
          [g.label for g in rows if g.kind == "group"], [u"S3", u"S4"])

    value.toggle_sort(u"BGL_Sheet Series", True)
    rows, shown = shtm_rows.compute_rows(SHEETS, value)
    check("and a shift-added level becomes a second level of groups",
          [(g.level, g.label) for g in rows if g.kind == "group"],
          [(0, u"S3"), (1, u"21"), (0, u"S4"), (1, u"(blank)"), (1, u"31")])

    value.collapsed = set([(u"S3",)])
    rows, shown = shtm_rows.compute_rows(SHEETS, value)
    check("which collapses like any other group",
          len([r for r in rows if r.kind == "sheet"]), 2)

    value.group_by_sort = False
    value.group_by = [u"BGL_Sheet Series"]
    check("switching it off hands grouping back to the dropdowns",
          value.grouping(), [u"BGL_Sheet Series"])


def test_values_allowed():
    value = state(filters={u"BGL_Sheet Stage": set([u"S3"])})
    check("a column's list shows what the other filters allow",
          shtm_rows.values_allowed(SHEETS, value, u"BGL_Sheet Series"), {u"21": 2})
    check("but its own filter is left out, so it can be widened again",
          shtm_rows.values_allowed(SHEETS, value, u"BGL_Sheet Stage"),
          {u"S3": 2, u"S4": 2})


def test_stale_count():
    store = shtm_edit.EditStore()
    value = state(sorts=[(u"Sheet Name", True)])
    check("no edits, nothing stale", shtm_rows.stale_count(SHEETS, value, store), 0)
    # rename a sheet so it would sort elsewhere
    store.set(1, u"Sheet Name", u"Vent L00", u"Zed")
    check("an edit that would move its row counts as stale",
          shtm_rows.stale_count(SHEETS, value, store), 1)
    value = state(filters={u"BGL_Sheet Stage": set([u"S3"])})
    store.clear()
    store.set(1, u"BGL_Sheet Stage", u"S3", u"S4")
    check("an edit that would drop its row out of the filter counts",
          shtm_rows.stale_count(SHEETS, value, store), 1)
    rows, shown = shtm_rows.compute_rows(SHEETS, value)
    check("but the row itself stays put until F5", shown, 2)
    store.clear()
    store.set(1, u"Sheet Name", u"Vent L00", u"Vent L00 x")
    check("an edit that changes nothing about its place is not stale",
          shtm_rows.stale_count(SHEETS, value, store), 0)


def test_snapshot():
    store = shtm_edit.EditStore()
    value = state(sorts=[(u"Sheet Name", True)])
    store.set(1, u"Sheet Name", u"Vent L00", u"Aaa")
    rows, shown = shtm_rows.compute_rows(SHEETS, value)
    check("a staged edit does not move its row",
          rows[0].values[u"Sheet Number"], u"E-3100")
    check("and the status line says it is out of place",
          shtm_rows.stale_count(SHEETS, value, store), 1)
    shtm_rows.take_snapshot(SHEETS, value, store)
    rows, shown = shtm_rows.compute_rows(SHEETS, value)
    check("F5 re-takes the decision and the row moves",
          rows[0].values[u"Sheet Number"], u"M-2100")
    check("and nothing is stale any more",
          shtm_rows.stale_count(SHEETS, value, store), 0)
    check("the model's own value is untouched",
          SHEETS[0]["values"][u"Sheet Name"], u"Vent L00")


def test_bands():
    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(group_by=[u"BGL_Sheet Stage", u"BGL_Sheet Series"],
                      sorts=[(u"BGL_Sheet Stage", True)]))
    check("each top-level group gets its own band, in table order",
          [(r.kind, r.band) for r in rows],
          [("group", 0), ("group", 0), ("sheet", 0), ("sheet", 0),
           ("group", 1), ("group", 1), ("sheet", 1), ("group", 1), ("sheet", 1)])
    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(group_by=[u"BGL_Sheet Stage"], collapsed=set([(u"S3",)]),
                      sorts=[(u"BGL_Sheet Stage", True)]))
    check("a collapsed group keeps its band so the colours do not shift",
          [r.band for r in rows if r.kind == "group"], [0, 1])
    rows, shown = shtm_rows.compute_rows(SHEETS, state())
    check("an ungrouped table has no bands", set([r.band for r in rows]), set([None]))


def test_grouping():
    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(group_by=[u"BGL_Sheet Stage"]))
    groups = [r for r in rows if r.kind == "group"]
    check("one group per value", [g.label for g in groups], [u"S4", u"S3"])
    check("and each carries its count", [g.count for g in groups], [2, 2])
    check("the sheets are still all there",
          len([r for r in rows if r.kind == "sheet"]), 4)

    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(group_by=[u"BGL_Sheet Stage", u"BGL_Sheet Series"]))
    levels = [(g.level, g.label) for g in rows if g.kind == "group"]
    check("two levels of grouping cascade",
          levels, [(0, u"S4"), (1, u"31"), (1, u"(blank)"),
                   (0, u"S3"), (1, u"21")])

    collapsed = set([(u"S4",)])
    rows, shown = shtm_rows.compute_rows(
        SHEETS, state(group_by=[u"BGL_Sheet Stage", u"BGL_Sheet Series"],
                      collapsed=collapsed))
    labels = [(g.level, g.label) for g in rows if g.kind == "group"]
    check("a collapsed group hides its child groups too",
          labels, [(0, u"S4"), (0, u"S3"), (1, u"21")])
    check("and its sheets", len([r for r in rows if r.kind == "sheet"]), 2)
    check("the collapsed group still reports its real count",
          [g.count for g in rows if g.kind == "group"][0], 2)
    check("the collapsed row draws its arrow closed",
          [g.expanded for g in rows if g.kind == "group"][0], False)


def test_export():
    folder = tempfile.mkdtemp(prefix="shtm_csv_")
    try:
        path = os.path.join(folder, "out.csv")
        rows = [shtm_rows.Row("group", label=u"S3", count=1),
                shtm_rows.Row("sheet", {u"Sheet Number": u"M-2100",
                                        u"Sheet Name": u'Vent, "L00"'})]
        shtm_rows.export_csv(rows, [u"Sheet Number", u"Sheet Name"], path)
        handle = open(path, "rb")
        text = handle.read().decode("utf-8-sig")
        handle.close()
        lines = text.strip().splitlines()
        check("the group row is not exported as a sheet", len(lines), 2)
        check("commas and quotes are escaped",
              lines[1], u'M-2100,"Vent, ""L00"""')
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ====================== editing ======================

def test_edit_store():
    store = shtm_edit.EditStore()
    check("a real change is kept", store.set(1, u"Sheet Name", u"A", u"B"), True)
    check("and counted", store.count(), 1)
    check("setting it back to the original drops it - and that is a change",
          store.set(1, u"Sheet Name", u"A", u"A"), True)
    check("setting an untouched cell to its own value is not",
          store.set(5, u"Sheet Name", u"A", u"A"), False)
    check("so nothing is pending", store.count(), 0)
    store.set(1, u"Sheet Name", u"A", u"B")
    store.set(1, u"BGL_Sheet Stage", u"S3", u"S4")
    store.set(2, u"Sheet Name", u"C", u"D")
    check("sheets touched counts sheets, not cells", store.sheets_touched(), 2)
    check("the shown value is the pending one",
          store.value_of({"id": 1, "values": {u"Sheet Name": u"A"}}, u"Sheet Name"),
          u"B")
    check("and the original where nothing is pending",
          store.value_of({"id": 3, "values": {u"Sheet Name": u"Z"}}, u"Sheet Name"),
          u"Z")
    jobs = store.jobs()
    check("jobs are one per cell, ordered", [(j["id"], j["column"]) for j in jobs],
          [(1, u"BGL_Sheet Stage"), (1, u"Sheet Name"), (2, u"Sheet Name")])
    check("a job remembers what it is replacing", jobs[1]["was"], u"A")
    store.clear()
    check("clear clears", store.count(), 0)


def test_undo_redo():
    store = shtm_edit.EditStore()
    store.take([(1, u"Sheet Name", u"A", u"B"), (2, u"Sheet Name", u"C", u"D")])
    store.take([(1, u"Sheet Name", u"A", u"E")])
    check("two batches are two steps", len(store.undo_stack), 2)
    check("undo takes back the whole last batch", store.undo(), True)
    check("and the cell is back to the batch before", store.get(1, u"Sheet Name"), u"B")
    check("undo again clears the first batch", store.undo() and store.count(), 0)
    check("nothing more to undo", store.undo(), False)
    check("redo puts the first batch back", store.redo() and store.count(), 2)
    store.take([(3, u"Sheet Name", u"X", u"Y")])
    check("a new edit throws the redo stack away", store.can_redo(), False)
    check("a batch that changes nothing is not a step",
          store.take([(3, u"Sheet Name", u"X", u"Y")]), 0)
    check("and does not grow the stack", len(store.undo_stack), 2)

    store.mark_refused(1, u"Sheet Name", u"no")
    check("a refusal paints over a pending edit",
          store.state_of(1, u"Sheet Name"), shtm_edit.REFUSED)
    store.set(1, u"Sheet Name", u"A", u"Z")
    check("editing the cell again clears the refusal",
          store.state_of(1, u"Sheet Name"), shtm_edit.EDITED)
    store.take([(2, u"Sheet Name", u"C", u"Q")], shtm_edit.IMPORTED)
    check("an import paints as an import", store.state_of(2, u"Sheet Name"),
          shtm_edit.IMPORTED)
    store.mark_copied([(2, u"Sheet Name"), (9, u"Sheet Name")])
    check("a copy mark never covers a pending edit",
          store.state_of(2, u"Sheet Name"), shtm_edit.IMPORTED)
    check("but shows on a cell with nothing pending",
          store.state_of(9, u"Sheet Name"), "copied")


def test_bulk_edits():
    store = shtm_edit.EditStore()
    edits = shtm_edit.find_replace(SHEETS, [u"Sheet Name"], u"vent", u"Heat")
    check("find and replace ignores case by default", len(edits), 2)
    check("and rewrites the value", edits[0][3], u"Heat L00")
    store.take(edits)
    edits = shtm_edit.find_replace(SHEETS, [u"Sheet Name"], u"Heat", u"Cool",
                                   store=store)
    check("a second pass works on the pending value, like Excel",
          [e[3] for e in edits], [u"Cool L00", u"Cool L01"])
    check("and the original is what the store already held",
          edits[0][2], u"Heat L00")
    check("an empty find changes nothing",
          shtm_edit.find_replace(SHEETS, [u"Sheet Name"], u"", u"x"), [])
    check("match case leaves the wrong case alone",
          shtm_edit.find_replace(SHEETS, [u"Sheet Name"], u"vent", u"x", True), [])

    edits = shtm_edit.affix(SHEETS[:1], [u"Sheet Number"], u"X-", u"-R1")
    check("a prefix and a suffix land either side",
          edits[0][3], u"X-M-2100-R1")
    check("no affix is no edit", shtm_edit.affix(SHEETS, [u"Sheet Name"]), [])

    edits = shtm_edit.fill_down(SHEETS, u"BGL_Sheet Stage", u"S5")
    check("fill down puts one value into every chosen sheet", len(edits), 4)
    edits = shtm_edit.fill_down(SHEETS[:2], u"BGL_Sheet Stage", u"S3")
    check("a fill that changes nothing makes no edits", edits, [])


def test_read_only_cells():
    locked = {"id": 9, "values": {u"Sheet Number": u"M-9000",
                                  u"Sheet Name": u"Locked",
                                  u"Views on sheet": u"3"},
              "readonly": set([u"Views on sheet"])}
    check("a read-only column is left out of find and replace",
          shtm_edit.find_replace([locked], [u"Views on sheet"], u"3", u"4"), [])
    check("and out of a prefix",
          shtm_edit.affix([locked], [u"Views on sheet"], u"x"), [])
    check("and out of a fill",
          shtm_edit.fill_down([locked], u"Views on sheet", u"9"), [])
    check("a writable column on the same sheet still works",
          len(shtm_edit.affix([locked], [u"Sheet Name"], u"X-")), 1)
    edits, unknown, ignored = shtm_edit.import_diff(
        [locked], [u"Sheet Number", u"Views on sheet"],
        [[u"Sheet Number", u"Views on sheet"], [u"M-9000", u"77"]])
    check("and an import cannot write it either", edits, [])


def test_import_diff():
    rows = [
        [u"Sheet Number", u"Sheet Name", u"BGL_Sheet Stage", u"Not A Column"],
        [u"M-2101", u"Vent L01 REV", u"S3", u"ignored"],
        [u"M-2100", u"Vent L00", u"S9", u"ignored"],
        [u"Z-0000", u"Nobody", u"S1", u""],
    ]
    edits, unknown, ignored = shtm_edit.import_diff(
        SHEETS, [u"Sheet Number", u"Sheet Name", u"BGL_Sheet Stage"], rows)
    check("rows match on the sheet number, in any order",
          sorted([(e[0], e[1], e[3]) for e in edits]),
          [(1, u"BGL_Sheet Stage", u"S9"), (2, u"Sheet Name", u"Vent L01 REV")])
    check("a number that matches nothing is reported", unknown, [u"Z-0000"])
    check("a column the table does not carry is ignored, not refused",
          ignored, [u"Not A Column"])
    check("the key column is never written from the file",
          [e for e in edits if e[1] == u"Sheet Number"], [])
    edits, unknown, ignored = shtm_edit.import_diff(
        SHEETS, [u"Sheet Number"], [[u"Sheet Name"], [u"x"]])
    check("a file with no number column is refused with a reason",
          ignored, [u"no 'Sheet Number' column in the file"])
    check("an empty file is nothing",
          shtm_edit.import_diff(SHEETS, [u"Sheet Number"], []), ([], [], []))


def test_csv_round_trip():
    rows = [[u"Sheet Number", u"Sheet Name"],
            [u"M-2100", u'Vent, "L00"'],
            [u"M-2101", u"Two\nlines"]]
    text = shtm_edit.to_csv(rows)
    check("commas, quotes and newlines survive the round trip",
          shtm_edit.from_csv(text), rows)
    check("a blank line is not a row",
          shtm_edit.from_csv(u"a,b\r\n\r\nc,d\r\n"), [[u"a", u"b"], [u"c", u"d"]])
    check("a plain unquoted file reads",
          shtm_edit.from_csv(u"a,b\nc,d"), [[u"a", u"b"], [u"c", u"d"]])


def test_apply_blockers():
    store = shtm_edit.EditStore()
    store.set(1, u"Sheet Number", u"M-2100", u"E-3100")
    problems = shtm_edit.blockers(store, SHEETS)
    check("a number another sheet already has is blocked",
          problems, [u"'E-3100' would be used by two sheets"])
    store.clear()
    store.set(1, u"Sheet Number", u"M-2100", u"M-9000")
    store.set(2, u"Sheet Number", u"M-2101", u"m-9000")
    check("two pending numbers that collide are blocked, whatever the case",
          shtm_edit.blockers(store, SHEETS), [u"'m-9000' would be used by two sheets"])
    store.clear()
    store.set(1, u"Sheet Number", u"M-2100", u"")
    truthy("a blank number is blocked",
           u"cannot be blank" in shtm_edit.blockers(store, SHEETS)[0])
    store.clear()
    store.set(1, u"Sheet Name", u"Vent L00", u"Power L00")
    check("a name another sheet has is not blocked - Revit allows it",
          shtm_edit.blockers(store, SHEETS), [])
    truthy("the summary counts cells and sheets",
           u"1 cell(s) on 1 sheet(s)" in shtm_edit.apply_summary(store))


# ====================== fill, series, duplicates ======================

def test_split_number():
    check("the rightmost number is the counter",
          shtm_fill.split_number(u"L01-P-1"), (u"L01-P-", u"1", u""))
    check("a hyphen in a tag is not a minus sign",
          shtm_fill.split_number(u"AHU-1"), (u"AHU-", u"1", u""))
    check("a minus at the start is a sign",
          shtm_fill.split_number(u"-5"), (u"", u"-5", u""))
    check("a minus after a space is a sign",
          shtm_fill.split_number(u"Level -1"), (u"Level ", u"-1", u""))
    check("text after the number is kept",
          shtm_fill.split_number(u"P-10 rev"), (u"P-", u"10", u" rev"))
    check("no number is None", shtm_fill.split_number(u"Plant"), None)


def test_series():
    check("AHU-1 steps to AHU-2, not AHU0",
          shtm_fill.series_value(u"AHU-1", 1, 1), u"AHU-2")
    check("no invented padding: AHU-10 steps down to AHU-9",
          shtm_fill.series_value(u"AHU-10", -1, 1), u"AHU-9")
    check("real padding is kept: SD-005 to SD-004",
          shtm_fill.series_value(u"SD-005", -1, 1), u"SD-004")
    check("L01-P-1 steps to L01-P-3, not L02-P-1",
          shtm_fill.series_value(u"L01-P-1", 2, 1), u"L01-P-3")
    check("a real negative steps through zero",
          shtm_fill.series_value(u"Level -1", 1, 2), u"Level 1")
    check("an even gap is inferred", shtm_fill.infer_step([u"P-2", u"P-4", u"P-6"]), 2)
    check("an uneven gap is not", shtm_fill.infer_step([u"P-2", u"P-3", u"P-6"]), None)
    check("different text is not a series", shtm_fill.infer_step([u"P-2", u"Q-4"]), None)


def test_fill_plan():
    check("no number: copied", shtm_fill.fill_plan([u"Plant"], 3), [u"Plant"] * 3)
    check("a number: stepped downwards",
          shtm_fill.fill_plan([u"AHU-1"], 3), [u"AHU-2", u"AHU-3", u"AHU-4"])
    check("stepped upwards when filling up",
          shtm_fill.fill_plan([u"AHU-5"], 2, False), [u"AHU-4", u"AHU-3"])
    check("several seeds with an even gap keep it",
          shtm_fill.fill_plan([u"P-2", u"P-4"], 2), [u"P-6", u"P-8"])
    check("several seeds with no series repeat as a block",
          shtm_fill.fill_plan([u"A", u"B"], 5), [u"A", u"B", u"A", u"B", u"A"])
    check("nothing to fill is nothing", shtm_fill.fill_plan([], 3), [])
    check("fill series gives a bare word a number",
          shtm_fill.fill_series([u"Plant"], 3), [u"Plant 1", u"Plant 2", u"Plant 3"])
    check("fill series on a number is a plain fill",
          shtm_fill.fill_series([u"AHU-1"], 2), [u"AHU-2", u"AHU-3"])


def test_unique_sequence():
    out = shtm_fill.unique_sequence([u"P-1", u"P-1", u"P-1"], [u"P-2"])
    check("clashes are renumbered past what is taken",
          out, [(u"P-1", u"P-1"), (u"P-1", u"P-3"), (u"P-1", u"P-4")])
    check("a value already unique is left alone",
          shtm_fill.unique_sequence([u"Q-9"], [u"P-1"]), [(u"Q-9", u"Q-9")])
    check("padding is kept when renumbering",
          shtm_fill.unique_sequence([u"SD-005", u"SD-005"], []),
          [(u"SD-005", u"SD-005"), (u"SD-005", u"SD-006")])
    check("a value with no number gets one appended rather than left clashing",
          shtm_fill.unique_sequence([u"Plant", u"Plant"], []),
          [(u"Plant", u"Plant"), (u"Plant", u"Plant 1")])
    check("case does not make two values different",
          shtm_fill.unique_sequence([u"p-1"], [u"P-1"]), [(u"p-1", u"p-2")])


def test_duplicates():
    groups = shtm_fill.duplicate_groups([u"A", u"b", u"", u"B", u"", u"a", u"c"])
    check("duplicates are grouped, case-insensitively, with their positions",
          groups, [(u"a", [0, 5]), (u"b", [1, 3])])
    check("blanks are never duplicates",
          [g for g in groups if g[0] == u""], [])


def test_clipboard_block():
    rows = [[u"a", u"b"], [u"c", u"d"]]
    text = shtm_fill.to_block(rows)
    check("a block round trips as tab-separated lines",
          shtm_fill.parse_block(text), rows)
    check("a trailing newline is not an extra row",
          shtm_fill.parse_block(u"x\ty\r\n"), [[u"x", u"y"]])
    check("empty is empty", shtm_fill.parse_block(u""), [])

    s1, s2, s3 = SHEETS[0], SHEETS[1], SHEETS[2]
    columns = [u"Sheet Number", u"Sheet Name", u"BGL_Sheet Stage"]
    targets = [(s1, u"Sheet Name"), (s2, u"Sheet Name"), (s3, u"Sheet Name")]
    check("one value goes into every selected cell",
          shtm_fill.paste_plan([[u"X"]], targets, columns),
          [(s1, u"Sheet Name", u"X"), (s2, u"Sheet Name", u"X"),
           (s3, u"Sheet Name", u"X")])
    block = [[u"n1", u"s1"], [u"n2", u"s2"]]
    check("a block lands from the top-left selected cell across and down",
          shtm_fill.paste_plan(block, [(s1, u"Sheet Name"), (s2, u"Sheet Name")],
                               columns),
          [(s1, u"Sheet Name", u"n1"), (s1, u"BGL_Sheet Stage", u"s1"),
           (s2, u"Sheet Name", u"n2"), (s2, u"BGL_Sheet Stage", u"s2")])
    check("a block wider than the table is cut at the edge",
          shtm_fill.paste_plan([[u"a", u"b", u"c"]], [(s1, u"BGL_Sheet Stage")],
                               columns),
          [(s1, u"BGL_Sheet Stage", u"a")])
    data = [s1, s2, s3]
    check("a block taller than the selection runs on down the data rows",
          shtm_fill.paste_plan([[u"a"], [u"b"], [u"c"]], [(s1, u"Sheet Name")],
                               columns, data),
          [(s1, u"Sheet Name", u"a"), (s2, u"Sheet Name", u"b"),
           (s3, u"Sheet Name", u"c")])
    check("and stops at the end of the table",
          len(shtm_fill.paste_plan([[u"a"], [u"b"]], [(s3, u"Sheet Name")],
                                   columns, data)), 1)


# ====================== template-driven batches ======================

B_SOURCES = [
    {"id": 1, "number": u"WRX-BW-001202", "name": u"BW Level 00 Part A",
     "values": {u"BGL_Sheet Stage": u"Stage 4", u"BGL_Sheet Series": u"BW-100",
                u"BGL_WIP_Tag": u"WIP"}},
    {"id": 2, "number": u"WRX-BW-001203", "name": u"BW Level 00 Part B",
     "values": {u"BGL_Sheet Stage": u"Stage 4", u"BGL_Sheet Series": u"BW-200",
                u"BGL_WIP_Tag": u""}},
]
B_PARAMS = [u"BGL_Sheet Stage", u"BGL_Sheet Series", u"BGL_WIP_Tag"]
B_VIEWS = {
    10: {"id": 10, "name": u"BW_L00", "kind": "model", "type": u"FloorPlan", "primary": 0},
    11: {"id": 11, "name": u"DEP_BW_L00 - 1", "kind": "model", "type": u"FloorPlan", "primary": 10},
    12: {"id": 12, "name": u"DEP_BW_L00 - 2", "kind": "model", "type": u"FloorPlan", "primary": 10},
    20: {"id": 20, "name": u"BW Section", "kind": "model", "type": u"Section", "primary": 0},
    30: {"id": 30, "name": u"Legend", "kind": "legend", "type": u"Legend", "primary": 0},
}
B_PLACED = [
    {"sheet": 1, "view": 11, "kind": "viewport", "id": 901},
    {"sheet": 2, "view": 12, "kind": "viewport", "id": 902},
    {"sheet": 2, "view": 20, "kind": "viewport", "id": 903},
    {"sheet": 1, "view": 30, "kind": "viewport", "id": 904},
]
B_OPTIONS = {"legends": "reuse", "schedules": "reuse", "drafting": "duplicate",
             "parents": True, "all_dependents": True, "place_new_parent": True}
B_FINDS = {"number": u"0012", "name": u"BW", "view": u"BW", "match_case": False}
B_TEMPLATES = shtm_batch.template_records({
    u"FloorPlan": [{"id": 500, "name": u"BW - Slab"}, {"id": 501, "name": u"BW - Wall"}],
    u"Section": [{"id": 600, "name": u"BW - Section"}],
    u"CeilingPlan": [{"id": 700, "name": u"RCP"}],
})


def b_row(template_id, number, name=u"", view=u"", params=None):
    template = [t for t in B_TEMPLATES if t["id"] == template_id][0]
    row = shtm_batch.new_row(template, B_SOURCES, B_PARAMS)
    row["number"] = number
    row["name"] = name
    row["view"] = view
    if params:
        row["params"].update(params)
    return row


def test_template_table():
    check("templates carry their family and readable type, sorted by name",
          [(t["name"], t["family"], t["type"]) for t in B_TEMPLATES],
          [(u"BW - Section", u"Sections", u"Section"), (u"BW - Slab", u"Plans", u"Floor Plan"),
           (u"BW - Wall", u"Plans", u"Floor Plan"), (u"RCP", u"Plans", u"Ceiling Plan")])
    check("the list opens on Plans", shtm_batch.default_family(B_TEMPLATES), u"Plans")
    check("or on everything when a project has no plan templates",
          shtm_batch.default_family(B_TEMPLATES[:1]), shtm_batch.ALL)
    check("the family filter offers every family once",
          shtm_batch.families(B_TEMPLATES), [u"(all)", u"Plans", u"Sections"])
    check("the type filter narrows to the family picked",
          shtm_batch.types_in(B_TEMPLATES, u"Plans"),
          [u"(all)", u"Ceiling Plan", u"Floor Plan"])
    check("filter by type",
          [t["name"] for t in shtm_batch.filter_templates(
              B_TEMPLATES, u"Plans", u"Floor Plan")], [u"BW - Slab", u"BW - Wall"])
    check("keyword search needs every word",
          [t["name"] for t in shtm_batch.filter_templates(
              B_TEMPLATES, needle=u"bw sec")], [u"BW - Section"])
    check("an unknown view type still has a family",
          shtm_batch.family_of(u"Something"), u"Other")
    slab = B_TEMPLATES[1]
    check("a floor plan template applies to the one parent, not each dependent",
          shtm_batch.applies_to(slab, B_SOURCES, B_PLACED, B_VIEWS), 1)
    check("a ceiling plan template applies to nothing on these sheets",
          shtm_batch.applies_to([t for t in B_TEMPLATES if t["name"] == u"RCP"][0],
                                B_SOURCES, B_PLACED, B_VIEWS), 0)
    counts = shtm_batch.applies_counts(B_TEMPLATES, B_SOURCES, B_PLACED, B_VIEWS)
    check("the one-pass count agrees with the per-template count for every template",
          counts, dict([(t["id"], shtm_batch.applies_to(t, B_SOURCES, B_PLACED, B_VIEWS))
                        for t in B_TEMPLATES]))
    check("and follows the ticked sources",
          shtm_batch.applies_counts(B_TEMPLATES, B_SOURCES[:1], B_PLACED, B_VIEWS)[600], 0)
    check("no sources, nothing applies",
          set(shtm_batch.applies_counts(B_TEMPLATES, [], B_PLACED, B_VIEWS).values()),
          set([0]))


def test_confirm_row_defaults():
    row = b_row(500, u"0013")
    check("a shared value is prefilled", row["params"][u"BGL_Sheet Stage"], u"Stage 4")
    check("a value the sources disagree on is left to each sheet",
          row["params"][u"BGL_Sheet Series"], u"")
    check("the series parameter is found by name",
          shtm_batch.series_parameter(B_PARAMS), u"BGL_Sheet Series")
    check("with no series parameter the first one leads",
          shtm_batch.series_parameter([u"A", u"B"]), u"A")


def test_build_batches():
    rows = [b_row(500, u"0013", u"BW SLAB", u"BW_SLAB", {u"BGL_Sheet Stage": u"Stage 5"}),
            b_row(501, u"0014", u"BW WALL", u"BW_WALL")]
    batches, records = shtm_batch.build(
        B_SOURCES, rows, B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS,
        [u"WRX-BW-001202", u"WRX-BW-001203"], [v["name"] for v in B_VIEWS.values()])
    check("one set per template row", len(batches), 2)
    check("every source sheet in every set", len(records), 4)
    check("the numbers come from each row's replacement",
          [r["values"][u"Sheet Number"] for r in records],
          [u"WRX-BW-001302", u"WRX-BW-001303", u"WRX-BW-001402", u"WRX-BW-001403"])
    check("the names too",
          records[0]["values"][u"Sheet Name"], u"BW SLAB Level 00 Part A")
    check("every new sheet is ready", set([r["status"] for r in records]), set(["ok"]))
    check("each set carries its own template for its view type",
          [b["options"]["templates"] for b in batches],
          [{u"FloorPlan": 500}, {u"FloorPlan": 501}])
    check("the row's grouping value is written", batches[0]["grouping"],
          {u"BGL_Sheet Stage": u"Stage 5"})
    check("a blank grouping cell leaves each sheet its own",
          [r["values"][u"BGL_Sheet Series"] for r in records[:2]],
          [u"BW-100", u"BW-200"])
    check("the preview names the views on each sheet",
          records[0]["values"][u"Views on sheet"],
          u"DEP_BW_SLAB_L00 - 1, Legend")
    names = [j["new_name"] for b in batches for j in b["plan"]["jobs"]
             if j["action"] != shtm_plan.REUSE]
    check("view names are unique across every set", len(names), len(set(names)))
    check("the parent is made again in each set, so each keeps its organisation",
          [len([j for j in b["plan"]["jobs"] if j["action"] == shtm_plan.PARENT])
           for b in batches], [1, 1])
    check("sheet rows carry a key the window can paint them by",
          batches[1]["sheet_rows"][0]["key"], u"1:1")


def test_build_clashes():
    rows = [b_row(500, u"0013"), b_row(501, u"0013")]
    batches, records = shtm_batch.build(
        B_SOURCES, rows, B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [])
    check("two rows with the same replacement clash in the second set",
          [r["status"] for r in records], ["ok", "ok", "bad", "bad"])
    finds = dict(B_FINDS, number=u"9999")
    batches, records = shtm_batch.build(
        B_SOURCES, [b_row(500, u"0013")], finds, B_PLACED, B_VIEWS, B_OPTIONS,
        B_PARAMS, [u"WRX-BW-001202", u"WRX-BW-001203"], [])
    check("find text that is not in the number blocks that sheet",
          set([r["status"] for r in records]), set(["bad"]))
    truthy("and says why", u"not in" in records[0]["values"][u"Status"])
    batches, records = shtm_batch.build(
        B_SOURCES, [b_row(500, u"")], B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS,
        B_PARAMS, [], [])
    check("a row with no replacement number blocks its sheets",
          set([r["status"] for r in records]), set(["bad"]))


def test_name_push_preview():
    names = [u"BGL_Sheet Name 1", u"BGL_Sheet Name 2", u"BGL_Sheet Name 3"]
    check("the preview adds a column per mapped parameter, after the grouping",
          shtm_batch.preview_columns(B_PARAMS, names)[4:],
          B_PARAMS + names + [u"From sheet", u"Status"])
    check("no push, no extra columns",
          shtm_batch.preview_columns(B_PARAMS), shtm_batch.preview_columns(B_PARAMS, None))
    check("a mapped parameter that is also a grouping column is not shown twice",
          shtm_batch.push_columns(B_PARAMS, [u"BGL_Sheet Stage", u"X"]), [u"X"])
    check("the example from the request splits in order",
          shtm_batch.name_push_values(u"MECHANICAL SERVICES_VENTILATION_LAYOUT",
                                      names, []),
          {u"BGL_Sheet Name 1": u"MECHANICAL SERVICES",
           u"BGL_Sheet Name 2": u"VENTILATION",
           u"BGL_Sheet Name 3": u"LAYOUT"})
    check("a name with fewer parts leaves the rest blank",
          shtm_batch.name_push_values(u"MECHANICAL SERVICES_VENTILATION", names, []),
          {u"BGL_Sheet Name 1": u"MECHANICAL SERVICES",
           u"BGL_Sheet Name 2": u"VENTILATION", u"BGL_Sheet Name 3": u""})
    check("extra parts join onto the last parameter",
          shtm_batch.name_push_values(u"A_B_C_D", names, [])[u"BGL_Sheet Name 3"],
          u"C_D")
    rows = [b_row(500, u"0013", u"MECH_VENT_LAYOUT")]
    finds = dict(B_FINDS, name=u"BW Level 00 Part A")
    batches, records = shtm_batch.build(
        B_SOURCES, rows, finds, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [],
        names)
    check("the build shows each new sheet's name parts in the preview",
          [records[0]["values"][n] for n in names], [u"MECH", u"VENT", u"LAYOUT"])
    batches, records = shtm_batch.build(
        B_SOURCES, rows, finds, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [])
    check("and not when the push is off", u"BGL_Sheet Name 1" in records[0]["values"],
          False)
    overlap = [u"BGL_WIP_Tag", u"BGL_Sheet Name 2", u""]
    batches, records = shtm_batch.build(
        B_SOURCES, rows, finds, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [],
        overlap)
    check("a push into a grouping column left blank shows the pushed part there",
          records[0]["values"][u"BGL_WIP_Tag"], u"MECH")
    rows_set = [b_row(500, u"0013", u"MECH_VENT_LAYOUT",
                      params={u"BGL_WIP_Tag": u"WIP"})]
    batches, records = shtm_batch.build(
        B_SOURCES, rows_set, finds, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [],
        overlap)
    check("a grouping value set for the set wins; the push still fills the rest "
          "(a blank last slot is dropped, so the remainder joins onto part 2)",
          [records[0]["values"][u"BGL_WIP_Tag"], records[0]["values"][u"BGL_Sheet Name 2"]],
          [u"WIP", u"VENT_LAYOUT"])


def test_readiness():
    rows = [b_row(500, u"0013")]
    batches, records = shtm_batch.build(
        B_SOURCES, rows, B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [])
    check("sources, a find, a template and a number: ready",
          shtm_batch.readiness(B_SOURCES, rows, B_FINDS, records), [])
    truthy("no sources is not ready",
           shtm_batch.readiness([], rows, B_FINDS, records))
    truthy("no find is not ready",
           shtm_batch.readiness(B_SOURCES, rows, dict(B_FINDS, number=u""), records))
    truthy("no templates is not ready",
           shtm_batch.readiness(B_SOURCES, [], B_FINDS, []))
    reasons = shtm_batch.readiness(B_SOURCES, [b_row(500, u"")], B_FINDS, [])
    truthy("a row with no number names the template",
           u"BW - Slab" in reasons[0])
    check("the worked example uses the first sheet and the first row",
          shtm_batch.example(B_SOURCES, rows, B_FINDS).split(u"\n")[0],
          u"e.g.  WRX-BW-001202  \u2192  WRX-BW-001302")


def test_plural_and_sorts():
    check("one sheet", shtm_core.plural(1, u"sheet"), u"1 sheet")
    check("many sheets", shtm_core.plural(3, u"sheet"), u"3 sheets")
    check("none is plural", shtm_core.plural(0, u"set"), u"0 sets")
    check("an irregular plural", shtm_core.plural(2, u"copy", u"copies"), u"2 copies")
    sorts = [(u"BGL_Sheet Series", True), (u"Sheet Number", False)]
    text = shtm_core.sorts_to_text(sorts)
    check("sorts round trip, primary first",
          shtm_core.sorts_from_text(text), sorts)
    check("a column the table no longer has is dropped",
          shtm_core.sorts_from_text(text, [u"Sheet Number"]), [(u"Sheet Number", False)])
    check("a colon in a parameter name survives",
          shtm_core.sorts_from_text(shtm_core.sorts_to_text([(u"Ref: A", True)])),
          [(u"Ref: A", True)])
    check("junk is forgotten rather than half restored",
          shtm_core.sorts_from_text(u"nonsense|Sheet Number:sideways||:asc"), [])
    check("a column named twice keeps its first place",
          shtm_core.sorts_from_text(u"A:asc|A:desc"), [(u"A", True)])
    check("nothing saved is nothing", shtm_core.sorts_from_text(u""), [])


def c_rows():
    rows = []
    for number in (u"0013", u"", u""):
        row = b_row(500, number)
        rows.append(row)
    return rows


def test_cells():
    keys = shtm_batch.cell_keys(B_PARAMS)
    check("the keys run in table order",
          keys, [u"number", u"name", u"view"] + B_PARAMS)
    check("shift-click picks the rectangle, row by row",
          shtm_batch.cell_range((0, u"name"), (1, u"number"), keys),
          [(0, u"number"), (0, u"name"), (1, u"number"), (1, u"name")])
    check("a range across the grouping columns",
          shtm_batch.cell_range((2, u"BGL_Sheet Series"), (2, u"BGL_Sheet Stage"), keys),
          [(2, u"BGL_Sheet Stage"), (2, u"BGL_Sheet Series")])
    cells = shtm_batch.toggle_cell([(0, u"number")], (1, u"number"))
    check("ctrl-click adds a cell", cells, [(0, u"number"), (1, u"number")])
    check("and takes it out again",
          shtm_batch.toggle_cell(cells, (0, u"number")), [(1, u"number")])
    check("a heading picks the whole column",
          shtm_batch.column_cells(3, u"BGL_WIP_Tag"),
          [(0, u"BGL_WIP_Tag"), (1, u"BGL_WIP_Tag"), (2, u"BGL_WIP_Tag")])

    rows = c_rows()
    picked = shtm_batch.column_cells(3, u"BGL_Sheet Series")
    undo = shtm_batch.apply_value(rows, picked, u"BW-300")
    check("one value goes into every picked cell",
          [shtm_batch.cell_value(r, u"BGL_Sheet Series") for r in rows], [u"BW-300"] * 3)
    check("and the undo list holds what each one had", len(undo), 3)
    check("a cell that already holds it is not counted",
          len(shtm_batch.apply_value(rows, picked, u"BW-300")), 0)
    shtm_batch.undo_cells(rows, undo)
    check("undo puts them back",
          [shtm_batch.cell_value(r, u"BGL_Sheet Series") for r in rows], [u""] * 3)
    undo = shtm_batch.apply_value(rows, [(0, u"name"), (5, u"name")], u"SLAB")
    check("a cell past the last row is ignored, not an error", len(undo), 1)

    rows = c_rows()
    undo = shtm_batch.fill_series_cells(rows, shtm_batch.column_cells(3, u"number"))
    check("fill series steps the number down the column, keeping its zeros",
          [r["number"] for r in rows], [u"0013", u"0014", u"0015"])
    rows = c_rows()
    rows[0]["params"][u"BGL_WIP_Tag"] = u"WIP"
    shtm_batch.fill_series_cells(rows, shtm_batch.column_cells(3, u"BGL_WIP_Tag"))
    check("a top cell with no number gets one",
          [r["params"][u"BGL_WIP_Tag"] for r in rows], [u"WIP", u"WIP 1", u"WIP 2"])
    check("one cell is not a series",
          shtm_batch.fill_series_cells(c_rows(), [(0, u"number")]), [])

    check("the fill bar names one column",
          shtm_batch.selection_label([(0, u"number"), (1, u"number")]),
          u"2 cells in Sheet number")
    check("or says how many",
          shtm_batch.selection_label([(0, u"number"), (0, u"BGL_WIP_Tag")]),
          u"2 cells across 2 columns")
    check("nothing picked says nothing", shtm_batch.selection_label([]), u"")


def test_copy_row():
    row = b_row(500, u"0013", params={u"BGL_Sheet Stage": u"Stage 5"})
    copy = shtm_batch.copy_row(row)
    check("a copied set keeps every value", copy["number"], u"0013")
    check("but has an id of its own", copy["uid"] != row["uid"], True)
    copy["params"][u"BGL_Sheet Stage"] = u"Stage 6"
    check("and its own grouping values", row["params"][u"BGL_Sheet Stage"], u"Stage 5")


def test_presets():
    preset = {"number": u"0013", "view": u"SLAB",
              "params": {u"BGL_Sheet Series": u"BW-100", u"Not here": u"x"}}
    template = [t for t in B_TEMPLATES if t["id"] == 500][0]
    row = shtm_batch.new_row(template, B_SOURCES, B_PARAMS, preset)
    check("a preset fills the row it is added as", row["number"], u"0013")
    check("and its view replacement", row["view"], u"SLAB")
    check("and its grouping value", row["params"][u"BGL_Sheet Series"], u"BW-100")
    check("a value the preset does not hold keeps the shared one",
          row["params"][u"BGL_Sheet Stage"], u"Stage 4")
    check("a parameter the table does not have is not invented",
          u"Not here" in row["params"], False)
    check("the row says it came from a preset", row["from_preset"], True)
    check("without a preset it did not",
          shtm_batch.new_row(template, B_SOURCES, B_PARAMS)["from_preset"], False)

    taken = shtm_batch.preset_from_row(row, B_PARAMS)
    check("a row becomes a preset with its blanks left out",
          sorted(taken.keys()), [u"number", u"params", u"view"])
    check("and its grouping values",
          taken["params"], {u"BGL_Sheet Stage": u"Stage 4", u"BGL_Sheet Series": u"BW-100"})

    awkward = {u"BW - Slab = A|B": {"number": u"00\u00e913", "params": {
        u"BGL_Sheet Series": u'say "hi"'}},
               u"Empty": {"params": {}}}
    text = shtm_batch.presets_to_text(awkward)
    check("presets are one line of plain ASCII, safe in a key=value file",
          (u"\n" in text, all(ord(c) < 128 for c in text)), (False, True))
    back = shtm_batch.presets_from_text(text)
    check("and come back exactly, = | quotes and accents included",
          back, {u"BW - Slab = A|B": awkward[u"BW - Slab = A|B"]})
    check("an empty preset is not kept", u"Empty" in back, False)
    check("a damaged value is no presets, not an error",
          shtm_batch.presets_from_text(u"{not json"), {})
    check("nothing saved is no presets", shtm_batch.presets_from_text(u""), {})
    folder = tempfile.mkdtemp(prefix="shtm_presets_")
    try:
        path = os.path.join(folder, "s.txt")
        values = shtm_core.load_settings(path)
        values["template_presets"] = text
        shtm_core.save_settings(values, path)
        check("presets survive the settings file",
              shtm_batch.presets_from_text(
                  shtm_core.load_settings(path)["template_presets"]),
              back)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    other_project = {"number": u"0013", "params": {u"XYZ_Zone": u"Z1",
                                                   u"BGL_Sheet Series": u"BW-100"}}
    merged = shtm_batch.merge_preset(
        other_project, {"number": u"0014", "params": {u"BGL_Sheet Stage": u"S5"}},
        B_PARAMS)
    check("updating a preset keeps the values for parameters this project lacks",
          merged["params"].get(u"XYZ_Zone"), u"Z1")
    check("and takes this project's values from the screen",
          merged["params"].get(u"BGL_Sheet Stage"), u"S5")
    check("a parameter this project has, left blank on screen, is cleared",
          u"BGL_Sheet Series" in merged["params"], False)
    check("the replacements come from the screen", merged["number"], u"0014")
    check("merging what is already there changes nothing",
          shtm_batch.merge_preset(other_project, other_project, B_PARAMS), other_project)
    check("a summary names what the preset fills in",
          shtm_batch.preset_summary({"number": u"0013",
                                     "params": {u"BGL_Sheet Series": u"BW-100"}}, B_PARAMS),
          u"Sheet number \u2192 0013   \u00b7   Sheet Series: BW-100")


def test_row_states():
    rows = [b_row(500, u"0013"), b_row(501, u""), b_row(501, u"0013")]
    batches, records = shtm_batch.build(
        B_SOURCES, rows, B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [])
    states = shtm_batch.row_states(rows, records, B_FINDS)
    check("each row has its own state",
          [s[0] for s in states], ["ok", "todo", "bad"])
    check("a ready row shows its first sheet before and after",
          states[0][1].startswith(u"WRX-BW-001202  \u2192  WRX-BW-001302"), True)
    truthy("a row whose sheets clash says how many", states[2][1].startswith(u"2 sheets"))
    states = shtm_batch.row_states(rows[:1], records, dict(B_FINDS, number=u""))
    check("with no find text the row says where to set it", states[0][0], "todo")


# ====================== 1.8.0 ======================

def test_highlight_spans():
    check("every place the find appears is marked, the rest left plain",
          shtm_core.highlight_spans(u"WRX-BW-001202", u"0012"),
          [(u"WRX-BW-", False), (u"0012", True), (u"02", False)])
    check("case is ignored unless asked, and the sheet's own case is kept",
          shtm_core.highlight_spans(u"Level 01 Part A", u"level 01"),
          [(u"Level 01", True), (u" Part A", False)])
    check("match case leaves the wrong case unmarked",
          shtm_core.highlight_spans(u"Level 01", u"level", True),
          [(u"Level 01", False)])
    check("every occurrence, never overlapping",
          shtm_core.highlight_spans(u"AAA", u"AA"), [(u"AA", True), (u"A", False)])
    check("no find, nothing marked", shtm_core.highlight_spans(u"M-2100", u""),
          [(u"M-2100", False)])
    check("the pieces always put the text back together",
          u"".join(p for p, _f in shtm_core.highlight_spans(u"a-0012-0012-b", u"0012")),
          u"a-0012-0012-b")
    check("it finds exactly what find and replace replaces",
          [f for _p, f in shtm_core.highlight_spans(u"M.2100", u".")],
          [False, True, False])
    hits, more = shtm_core.views_found(
        [u"BW_L00", u"BW Section", u"Legend", u"BW_L01", u"BW_L02"], u"bw", most=3)
    check("the views a view find catches, the first three", hits,
          [u"BW_L00", u"BW Section", u"BW_L01"])
    check("and how many more", more, 1)


def test_picked_sheets():
    check("only the sheets among the selection, in the tool's order",
          shtm_core.picked_sheet_ids([30, 999, 10], [10, 20, 30]), [10, 30])
    check("nothing selected, no filter", shtm_core.picked_sheet_ids([], [10, 20]), [])
    sheets = [{"id": 1, "values": {u"Sheet Number": u"A1", u"Sheet Name": u"One"}},
              {"id": 2, "values": {u"Sheet Number": u"A2", u"Sheet Name": u"Two"}},
              {"id": 3, "values": {u"Sheet Number": u"A3", u"Sheet Name": u"Three"}}]
    state = shtm_rows.GridState()
    state.only_ids = set([1, 3])
    check("the table shows only the sheets selected in Revit",
          [s["id"] for s in sheets if shtm_rows.matches(s, state)], [1, 3])
    state.clear_filters()
    check("Clear filters leaves the selection filter to its own tick box",
          state.only_ids, set([1, 3]))
    state.only_ids = None
    check("unticked, every sheet", len([s for s in sheets if shtm_rows.matches(s, state)]), 3)


def test_drawer_maths():
    check("the slide starts at 0 and lands at 1",
          [shtm_core.ease_out(0), shtm_core.ease_out(1)], [0.0, 1.0])
    truthy("it is quick off the mark", shtm_core.ease_out(0.5) > 0.8)
    check("past the end it holds the end", shtm_core.ease_out(1.7), 1.0)
    check("the first bar takes slot 0", shtm_core.free_slot([]), 0)
    check("a freed slot is reused", shtm_core.free_slot([0, 2]), 1)
    check("a bar parks 8px above the taskbar",
          shtm_core.parked_top(0, 1040, 50), 1040 - 8 - 50)
    check("a second bar stacks 4px above the first",
          shtm_core.parked_top(0, 1040, 40, [50]), 1040 - 8 - 50 - 4 - 40)
    check("a monitor above the primary (negative top) parks on that monitor",
          shtm_core.parked_top(-1080, 1040, 50), -1080 + 1040 - 8 - 50)
    check("not moved while parked: back exactly where it was",
          shtm_core.opened_top(120, 800, 982, 983, 0, 1040), 120)
    check("carried up the screen: opens from where the bar now sits",
          shtm_core.opened_top(120, 600, 982, 300, 0, 1040), 300)
    check("carried low: kept on the screen",
          shtm_core.opened_top(120, 800, 982, 700, 0, 1040), 240)
    check("never above the top of the screen",
          shtm_core.opened_top(120, 1400, 982, 700, 0, 1040), 0)


def _luminance(hex_value):
    value = hex_value.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(value[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(one, other):
    a, b = _luminance(one), _luminance(other)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_revit_dark_palette():
    dark = theme.DARK
    revit = {"WindowBg": "#3C4454", "FieldBg": "#2D3441", "BarBg": "#222933",
             "HeaderBg": "#323C48", "HoverBg": "#444E5E", "SelectionBrush": "#3A7392"}
    check("dark is Revit's own dark theme",
          dict((k, dark[k]) for k in revit), revit)
    low = [k for k in dark if k.endswith("Bg") and contrast(dark["TextBrush"], dark[k]) < 4.5]
    check("text reads at 4.5:1 on every dark background", low, [])
    low = [k for k in ("WindowBg", "CardBg", "FieldBg", "BarBg", "HeaderBg")
           if contrast(dark["MutedBrush"], dark[k]) < 4.0]
    check("muted text holds 4:1 on the panels", low, [])
    check("the light palette is untouched by it", theme.LIGHT["WindowBg"], "#F4F4F6")
    low = [k for k in ("CardBg", "FieldBg", "WindowBg")
           if contrast(dark["FoundGreen"], dark[k]) < 4.5
           or contrast(theme.LIGHT["FoundGreen"], theme.LIGHT[k]) < 4.5]
    check("the found view text holds 4.5:1 in both palettes", low, [])


class _Named(object):
    def __init__(self, text):
        self.text = text

    def ToString(self):
        return self.text


def test_canvas_theme():
    check("Revit's dark canvas reads as dark", theme.theme_name(_Named("Dark")), "dark")
    check("its light one as light", theme.theme_name(_Named("Light")), "light")
    check("nothing to read, no answer", theme.theme_name(None), None)


# ====================== 1.9.0 ======================

def test_legends_left_off():
    off = options(include_legends=False)
    check("a legend is left off when legends are not asked for",
          shtm_plan.classify(VIEWS[30], off), shtm_plan.SKIP)
    placements = [{"sheet": 1, "view": 30, "kind": "viewport", "id": 1},
                  {"sheet": 1, "view": 20, "kind": "viewport", "id": 2}]
    plan = shtm_plan.build_plan([1], placements, VIEWS, off)
    check("a left-off legend makes no job", [j["old_id"] for j in plan["jobs"]], [20])
    check("and is not placed on the new sheet",
          [p["view"] for p in plan["placements"]], [20])
    plan = shtm_plan.build_plan([1], placements, VIEWS, options(include_legends=True))
    check("ticked, it is placed again as before",
          sorted(p["view"] for p in plan["placements"]), [20, 30])
    check("the setting is off unless chosen",
          shtm_core.DEFAULTS["dup_include_legends"], "0")


def test_dependent_keeps_its_parent():
    """A sheet carrying only a dependent: the parent is copied, the dependent
    is made a dependent of that copy, and it - not the parent - lands on the
    new sheet."""
    placements = [{"sheet": 7, "view": 11, "kind": "viewport", "id": 70}]
    plan = shtm_plan.build_plan([7], placements, VIEWS,
                                options(all_dependents=False, parents=False))
    jobs = [(j["old_id"], j["action"], j.get("parent_old")) for j in plan["jobs"]]
    check("the parent is copied first, the dependent hangs off it",
          jobs, [(10, shtm_plan.PARENT, 0), (11, shtm_plan.DEPENDENT, 10)])
    check("the dependent is placed on the new sheet where the old one was",
          [(p["sheet"], p["view"], p["src"]) for p in plan["placements"]], [(7, 11, 70)])
    check("the parent is made but not placed - it was on no sheet",
          [j["old_id"] for j in plan["unplaced"]], [10])
    rows = [b_row(500, u"0013")]
    batches, _records = shtm_batch.build(
        B_SOURCES, rows, B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [])
    actions = dict((j["old_id"], j["action"]) for j in batches[0]["plan"]["jobs"])
    check("in a set: the parent of the dependents on the sheets is copied",
          actions.get(10), shtm_plan.PARENT)
    check("and both dependents on the sheets come as its dependents",
          [actions.get(11), actions.get(12)], [shtm_plan.DEPENDENT] * 2)
    placed = dict((p["view"], p["sheet"]) for p in batches[0]["plan"]["placements"])
    check("each dependent goes on its own new sheet", [placed.get(11), placed.get(12)],
          [1, 2])


def test_source_view_lines():
    placements = [{"sheet": 1, "view": 30, "kind": "viewport"},
                  {"sheet": 1, "view": 11, "kind": "viewport"},
                  {"sheet": 1, "view": 20, "kind": "viewport"}]
    lines, more = shtm_batch.source_view_lines(
        1, placements, VIEWS, options(include_legends=False), u"l00", False)
    check("every view on the sheet is listed, by name",
          [l["name"] for l in lines], [u"L00 Dep A", u"Legend - Vent", u"Section 1"])
    check("a dependent says its parent comes with it",
          lines[0]["note"], u"dependent - a copy of L00 Parent comes too")
    check("the view find is marked on a view that is copied",
          lines[0]["spans"], [(u"L00", True), (u" Dep A", False)])
    check("a left-off legend says so and is never marked",
          (lines[1]["note"], lines[1]["spans"]),
          (u"legend - left off", [(u"Legend - Vent", False)]))
    lines, more = shtm_batch.source_view_lines(
        1, placements, VIEWS, options(include_legends=True), u"", False, most=2)
    check("a legend brought along is placed again as it is",
          lines[1]["note"], u"legend - placed again as it is")
    check("past the most shown, a count", more, 1)


def test_view_examples():
    rows = [b_row(500, u"0013", view=u"BW1"), b_row(501, u"0014")]
    batches, _records = shtm_batch.build(
        B_SOURCES, rows, B_FINDS, B_PLACED, B_VIEWS, B_OPTIONS, B_PARAMS, [], [])
    lines = shtm_batch.view_examples(rows, batches)
    truthy("the first renamed view, before and after",
           lines[0].startswith(u"view  BW Section  \u2192  BW1 Section"))
    truthy("and how many more change", u"more" in lines[0])
    check("a set with a blank view cell keeps every view name, and says so",
          lines[1], u"views keep their names")
    check("and its sheet names keep the found text too (blank keeps it)",
          [r["values"][shtm_batch.COL_NAME] for r in _records if r["batch"] == 1],
          [u"BW Level 00 Part A", u"BW Level 00 Part B"])


def test_find_presets():
    finds = {"number": u"0012", "name": u"Level 00", "view": u"L00", "match_case": True}
    text = shtm_batch.find_presets_to_text({u"Level 00 set": shtm_batch.find_preset(finds)})
    check("saved finds come back exactly",
          shtm_batch.find_presets_from_text(text),
          {u"Level 00 set": {"number": u"0012", "name": u"Level 00", "view": u"L00",
                             "match_case": True}})
    check("one line, so it cannot break the settings file", "\n" in text, False)
    check("an empty preset is not kept",
          shtm_batch.find_presets_from_text(shtm_batch.find_presets_to_text(
              {u"blank": shtm_batch.find_preset({})})), {})
    check("rubbish reads as nothing", shtm_batch.find_presets_from_text(u"{oops"), {})
    settings = shtm_core.load_settings(os.path.join(tempfile.mkdtemp(), "none.txt"))
    check("no saved finds to start with", settings.get("find_presets"), u"")


def test_template_helpers():
    taken = set([u"bw - slab copy"])
    check("a copy is '<name> Copy'", shtm_core.copy_name(u"BW - Wall", set()), u"BW - Wall Copy")
    check("stepped when that is taken", shtm_core.copy_name(u"BW - Slab", taken),
          u"BW - Slab Copy 2")
    check("scales read however they are typed",
          [shtm_core.parse_scale(t) for t in (u"1 : 50", u"1:100", u"200", u" 1 : 20 ")],
          [50, 100, 200, 20])
    check("and nonsense is refused",
          [shtm_core.parse_scale(t) for t in (u"", u"2 : 50", u"fifty", u"0", u"12.5")],
          [None, None, None, None, None])
    check("a scale reads back the way Revit shows it", shtm_core.scale_text(50), u"1 : 50")
    rows = [{"id": 1, "value": u"Fine", "include": True, "editable": True},
            {"id": 2, "value": u"edit in Revit", "include": True, "editable": False},
            {"id": 3, "value": u"1 : 50", "include": False, "editable": True}]
    changes = shtm_core.template_changes(
        rows, {1: u"Fine", 2: u"changed?", 3: u"1 : 100"}, {1: True, 2: False, 3: False},
        u"BW - Slab", u"BW - Slab")
    check("only what differs is written, and never a value Revit owns",
          changes, {"name": None, "values": {3: u"1 : 100"}, "include": {2: False}})
    check("a new name is a change",
          shtm_core.template_changes(rows, {}, {}, u"A", u" B ")["name"], u"B")
    check("a room's point on the level is on it, a little above or below too",
          [shtm_core.near_level(z, 10.0) for z in (10.0, 10.5, 9.6, 12.0, 8.0)],
          [True, True, True, False, False])


def test_name_delimiter():
    names = [u"P1", u"P2", u"P3"]
    check("the default delimiter is _",
          shtm_batch.name_push_values(u"MECH_VENT_LAYOUT", names, []),
          {u"P1": u"MECH", u"P2": u"VENT", u"P3": u"LAYOUT"})
    check("a set delimiter splits on that instead",
          shtm_batch.name_push_values(u"MECH - VENT - LAYOUT - L01", names, [], u" - "),
          {u"P1": u"MECH", u"P2": u"VENT", u"P3": u"LAYOUT - L01"})
    check("and leaves underscores alone",
          shtm_batch.name_push_values(u"MECH_A-VENT", names[:2], [], u"-"),
          {u"P1": u"MECH_A", u"P2": u"VENT"})
    check("a blank delimiter means _", shtm_core.delimiter_of(u""), u"_")
    check("the setting starts as _", shtm_core.delimiter_of(
        shtm_core.DEFAULTS["name_delimiter"]), u"_")
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "s.txt")
    settings = shtm_core.load_settings(path)
    settings["name_delimiter"] = shtm_core.delimiter_stored(u" - ")
    shtm_core.save_settings(settings, path)
    check("a delimiter's spaces survive saving and reading back",
          shtm_core.delimiter_of(shtm_core.load_settings(path)["name_delimiter"]), u" - ")
    check("parts are trimmed, so a bare - does not leave spaces behind",
          shtm_batch.name_push_values(u"MECH - VENT", names[:2], [], u"-"),
          {u"P1": u"MECH", u"P2": u"VENT"})
    rows = [b_row(500, u"0013", u"MECH-VENT")]
    finds = dict(B_FINDS, name=u"BW Level 00 Part A")
    options = dict(B_OPTIONS, name_delimiter=u"-")
    _batches, records = shtm_batch.build(
        B_SOURCES, rows, finds, B_PLACED, B_VIEWS, options, B_PARAMS, [], [], names)
    check("the preview splits on the set delimiter",
          [records[0]["values"][n] for n in names], [u"MECH", u"VENT", u""])


def test_full_height_and_editor_changes():
    top, height, saved = shtm_core.full_height(0, 1040, 200, 600, None)
    check("a double click on the edge fills the screen's height",
          (top, height, saved), (0, 1040, (200, 600)))
    check("the next puts it back", shtm_core.full_height(0, 1040, 0, 1040, saved),
          (200, 600, None))
    check("a monitor above the primary keeps its negative top",
          shtm_core.full_height(-1080, 1040, -900, 500, None)[:2], (-1080, 1040))
    rows = [{"id": 1, "visible": True, "halftone": False},
            {"id": 2, "visible": False, "halftone": True}]
    check("only the ticks that differ are written",
          shtm_core.flag_changes(rows, {1: {"visible": True, "halftone": True},
                                        2: {"visible": False}}, ("visible", "halftone")),
          {1: {"halftone": True}})
    check("millimetres read however they are typed",
          [round(shtm_core.parse_mm(t) or 0, 4) for t in (u"1200", u"1200 mm", u"-304.8",
                                                           u"2,300")],
          [round(1200 / 304.8, 4), round(1200 / 304.8, 4), -1.0, round(2300 / 304.8, 4)])
    check("and words do not", shtm_core.parse_mm(u"high"), None)
    check("feet shown as whole millimetres", shtm_core.mm_text(1.0), u"304.8")
    ranges = [{"plane": "CutPlane", "level": "Current", "offset_text": u"1200"},
              {"plane": "TopClipPlane", "level": "Current", "offset_text": u"2300"}]
    changes, bad = shtm_core.range_changes(
        ranges, {"CutPlane": {"offset": u"1500"}, "TopClipPlane": {"level": "LevelAbove",
                                                                   "offset": u"2300"}})
    check("a changed cut offset and a changed top level, nothing else",
          (sorted(changes), round(changes["CutPlane"]["offset"] * 304.8, 3),
           changes["TopClipPlane"]), (["CutPlane", "TopClipPlane"], 1500.0,
                                      {"level": "LevelAbove"}))
    check("an offset that is not a number is held back, not written",
          shtm_core.range_changes(ranges, {"CutPlane": {"offset": u"high"}}),
          ({}, ["CutPlane"]))


def test_fit_widths():
    check("a column is as wide as its text needs, never narrower than it was",
          shtm_batch.fit_widths([10.0, 196.0, 118.0, 96.0], [None, 250.4, 90.0, None]),
          [10.0, 251.0, 118.0, 96.0])


TESTS = [
    test_find_replace, test_name_push_plan, test_datum_extents,
    test_fit_line, test_same_line,
    test_titleblock_copy, test_example_line, test_unique_name, test_natural_sort, test_name_segments,
    test_flags_and_lists, test_eid_value, test_every_setting_survives_a_reload,
    test_name_push_defaults,
    test_settings, test_preview_sheets,
    test_classify, test_plan_dependents, test_plan_unselected_sibling,
    test_plan_parent_on_a_sheet,
    test_plan_reuse_and_placements, test_plan_names, test_plan_summary,
    test_filtering, test_sort_levels, test_group_by_sort, test_values_allowed,
    test_stale_count, test_snapshot, test_bands, test_grouping,
    test_export, test_edit_store, test_undo_redo, test_bulk_edits, test_import_diff,
    test_read_only_cells, test_csv_round_trip, test_apply_blockers, test_split_number, test_series,
    test_fill_plan, test_unique_sequence, test_duplicates, test_clipboard_block,
    test_template_table, test_confirm_row_defaults, test_build_batches,
    test_build_clashes, test_name_push_preview, test_readiness,
    test_plural_and_sorts, test_cells,
    test_copy_row, test_presets, test_row_states,
    test_highlight_spans, test_picked_sheets, test_drawer_maths,
    test_revit_dark_palette, test_canvas_theme,
    test_legends_left_off, test_dependent_keeps_its_parent, test_source_view_lines,
    test_view_examples, test_find_presets, test_template_helpers,
    test_name_delimiter, test_full_height_and_editor_changes, test_fit_widths,
]


def main():
    for test in TESTS:
        try:
            test()
        except Exception:
            import traceback
            FAILED.append(u"{0} threw:\n{1}".format(
                test.__name__, traceback.format_exc()))
    for problem in FAILED:
        sys.stdout.write(u"FAILED  {0}\n".format(problem))
    sys.stdout.write("\n{0} check(s) passed, {1} failed\n".format(
        len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
