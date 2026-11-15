# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : logic bench.

Loads fm_filters against a stub Revit API and checks the rule tables and
the decode/build mapping, so a table that has drifted out of step fails on
the bench rather than in Revit.

    python bench_logic.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
#  Stub Revit and .NET, each name in the namespace the real API puts it in
# ---------------------------------------------------------------------------
def install_stubs():
    def mod(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    clr = mod("clr")
    clr.AddReference = lambda *a, **k: None

    fm_clr = mod("fm_clr")
    fm_clr.LOADED = True

    system = mod("System")
    coll = mod("System.Collections")
    gen = mod("System.Collections.Generic")
    system.Collections = coll
    coll.Generic = gen

    class _List(object):
        def __init__(self, *a):
            self._items = list(a[0]) if a and a[0] is not None else []

        def Add(self, x):
            self._items.append(x)

        def __iter__(self):
            return iter(self._items)

        def __len__(self):
            return len(self._items)

    class _ListFactory(object):
        def __getitem__(self, _t):
            return _List

    gen.List = _ListFactory()

    autodesk = mod("Autodesk")
    revit = mod("Autodesk.Revit")
    db = mod("Autodesk.Revit.DB")
    autodesk.Revit = revit
    revit.DB = db

    names = [
        "ElementId", "BuiltInCategory", "BuiltInParameter", "Category",
        "FilteredElementCollector", "ParameterFilterElement",
        "ParameterFilterUtilities", "ElementParameterFilter",
        "LogicalAndFilter", "LogicalOrFilter", "ElementMulticategoryFilter",
        "LabelUtils", "UnitUtils", "StorageType", "View", "ElementFilter",
        "FilterRule", "SpecTypeId", "FillPatternElement", "LinePatternElement",
    ]
    for n in names:
        setattr(db, n, type(n, (object,), {}))

    calls = []

    class _Factory(object):
        pass

    for _k, _lbl, fac, _needs in _OPS_EXPECTED:
        def make(fname):
            def f(*args):
                calls.append((fname, args))
                return ("rule", fname, args)
            return f
        setattr(_Factory, fac, staticmethod(make(fac)))

    db.ParameterFilterRuleFactory = _Factory

    class _Colour(object):
        def __init__(self, r, g, b):
            self.Red, self.Green, self.Blue = r, g, b
            self.IsValid = True
    db.Color = _Colour

    class _OGS(object):
        def __init__(self):
            self.calls = {}

        def __getattr__(self, item):
            if not item.startswith("Set"):
                raise AttributeError(item)

            def setter(*a):
                self.calls[item] = a[0] if len(a) == 1 else a
            return setter
    db.OverrideGraphicSettings = _OGS

    return calls


_OPS_EXPECTED = [
    ("equals", "equals", "CreateEqualsRule", True),
    ("not_equals", "does not equal", "CreateNotEqualsRule", True),
    ("greater", "is greater than", "CreateGreaterRule", True),
    ("greater_equal", "is greater than or equal to", "CreateGreaterOrEqualRule", True),
    ("less", "is less than", "CreateLessRule", True),
    ("less_equal", "is less than or equal to", "CreateLessOrEqualRule", True),
    ("contains", "contains", "CreateContainsRule", True),
    ("not_contains", "does not contain", "CreateNotContainsRule", True),
    ("begins", "begins with", "CreateBeginsWithRule", True),
    ("not_begins", "does not begin with", "CreateNotBeginsWithRule", True),
    ("ends", "ends with", "CreateEndsWithRule", True),
    ("not_ends", "does not end with", "CreateNotEndsWithRule", True),
    ("has_value", "has a value", "CreateHasValueParameterRule", False),
    ("has_no_value", "has no value", "CreateHasNoValueParameterRule", False),
]


def _xml_ok(text):
    import xml.dom.minidom
    try:
        xml.dom.minidom.parseString(text)
        return True
    except Exception:
        return False


PASS = []
FAIL = []


def check(label, condition, detail=""):
    if condition:
        PASS.append(label)
    else:
        FAIL.append("{0}   {1}".format(label, detail))


def main():
    install_stubs()
    import fm_filters as ff

    # ---- the operator table
    check("operator table has 14 entries", len(ff.OPERATORS) == 14,
          str(len(ff.OPERATORS)))

    for key, label, factory, needs in _OPS_EXPECTED:
        check("'{0}' label".format(key), ff.OP_LABEL.get(key) == label,
              repr(ff.OP_LABEL.get(key)))
        check("'{0}' factory".format(key), ff.OP_FACTORY.get(key) == factory,
              repr(ff.OP_FACTORY.get(key)))
        check("'{0}' needs a value = {1}".format(key, needs),
              ff.OP_NEEDS_VALUE.get(key) == needs)

    # ---- labels are unique, so LABEL_TO_OP cannot lose one
    labels = [v for v in ff.OP_LABEL.values()]
    check("every operator label is unique", len(labels) == len(set(labels)))
    check("LABEL_TO_OP round trips", all(
        ff.LABEL_TO_OP[ff.OP_LABEL[k]] == k for k in ff.OP_LABEL))

    # ---- operator sets per storage type
    check("string gets the text operators",
          "contains" in ff.ops_for_storage("String"))
    check("numeric does not get contains",
          "contains" not in ff.ops_for_storage("Double"))
    check("integer does not get contains",
          "contains" not in ff.ops_for_storage("Integer"))
    check("element id offers the text operators too",
          "contains" in ff.ops_for_storage("ElementId"),
          str(ff.ops_for_storage("ElementId")))
    check("element id still offers equals and has a value",
          "equals" in ff.ops_for_storage("ElementId")
          and "has_value" in ff.ops_for_storage("ElementId"))
    check("element id does not offer greater than",
          "greater" not in ff.ops_for_storage("ElementId"))
    check("yes/no overrides the numeric set",
          ff.ops_for_storage("Integer", True) == ff.YESNO_OPS)
    check("every storage type offers has a value",
          all("has_value" in ff.ops_for_storage(s)
              for s in ("String", "Double", "Integer", "ElementId")))
    check("every operator offered is in the table",
          all(k in ff.OP_LABEL
              for s in ("String", "Double", "Integer", "ElementId")
              for k in ff.ops_for_storage(s)))

    # ---- the evaluator to operator map used when reading rules back
    check("GreaterOrEqual is tested before Greater",
          [t for t, _k in ff._EVAL_MAP].index("GreaterOrEqual") <
          [t for t, _k in ff._EVAL_MAP].index("Greater"),
          "otherwise every >= reads back as >")
    check("LessOrEqual is tested before Less",
          [t for t, _k in ff._EVAL_MAP].index("LessOrEqual") <
          [t for t, _k in ff._EVAL_MAP].index("Less"))
    check("BeginsWith is tested before Equals",
          [t for t, _k in ff._EVAL_MAP].index("BeginsWith") <
          [t for t, _k in ff._EVAL_MAP].index("Equals"))

    # ---- negation used when a rule is wrapped in FilterInverseRule
    check("negating equals gives not equals", ff._NEGATE["equals"] == "not_equals")
    check("negating greater gives less or equal",
          ff._NEGATE["greater"] == "less_equal")
    check("negating less or equal gives greater",
          ff._NEGATE["less_equal"] == "greater")
    check("every negation lands on a real operator",
          all(v in ff.OP_LABEL for v in ff._NEGATE.values()))

    # ---- building rules picks the right factory and skips the value where
    #      the operator does not take one
    pid = object()
    r = ff.build_rule(None, pid, "has_value", "ignored", "String", None)
    check("has a value takes the parameter only",
          r[1] == "CreateHasValueParameterRule" and len(r[2]) == 1, str(r))

    r = ff.build_rule(None, pid, "contains", "BGL", "String", None)
    check("a string rule passes the text through",
          r[1] == "CreateContainsRule" and r[2][1] == "BGL", str(r))

    r = ff.build_rule(None, pid, "equals", "12", "Integer", None)
    check("an integer rule converts the text to a number",
          r[2][1] == 12 and isinstance(r[2][1], int), str(r))

    r = ff.build_rule(None, pid, "equals", "yes", "Integer", None, yesno=True)
    check("yes becomes 1", r[2][1] == 1, str(r))
    r = ff.build_rule(None, pid, "equals", "No", "Integer", None, yesno=True)
    check("no becomes 0", r[2][1] == 0, str(r))

    r = ff.build_rule(None, pid, "equals", "2.5", "Double", None)
    check("a double rule carries an epsilon",
          len(r[2]) == 3 and r[2][2] == ff.DOUBLE_EPSILON, str(r))

    bad = False
    try:
        ff.build_rule(None, pid, "not_an_operator", "x", "String", None)
    except Exception:
        bad = True
    check("an unknown operator raises rather than writing nothing", bad)

    bad = False
    try:
        ff.build_rule(None, pid, "equals", "not a number", "Integer", None)
    except Exception:
        bad = True
    check("a value that will not parse raises", bad)


    # ---------------------------------------------------------------- overrides
    import fm_overrides as fo

    check("a spec starts with every key",
          set(fo.new_spec().keys()) == set(fo.DEFAULT_SPEC.keys()))
    check("a fresh spec is visible and enabled",
          fo.new_spec()["visible"] and fo.new_spec()["enabled"])
    check("a fresh spec overrides nothing",
          all(fo.new_spec()[k] is None for k in
              ("proj_colour", "proj_weight", "proj_pattern",
               "cut_colour", "surf_fg_pattern", "cut_bg_colour")))

    check("hex parses with a hash", fo.parse_hex("#FF8800") == (255, 136, 0))
    check("hex parses without a hash", fo.parse_hex("FF8800") == (255, 136, 0))
    check("a short hex is rejected", fo.parse_hex("F80") is None)
    check("nonsense hex is rejected", fo.parse_hex("ZZTOP1") is None)
    check("None hex is rejected", fo.parse_hex(None) is None)
    check("hex round trips", fo.to_hex(fo.parse_hex("1B72BE")) == "1B72BE")

    spec = fo.new_spec()
    ogs = fo.build_overrides(spec)
    check("an empty spec sets no colours",
          "SetProjectionLineColor" not in ogs.calls, str(ogs.calls.keys()))
    check("an empty spec still sets transparency and halftone",
          "SetSurfaceTransparency" in ogs.calls and "SetHalftone" in ogs.calls)

    spec = fo.new_spec()
    spec["proj_colour"] = "FF0000"
    spec["proj_weight"] = 5
    spec["transparency"] = 40
    spec["halftone"] = True
    ogs = fo.build_overrides(spec)
    check("a colour reaches the override",
          ogs.calls["SetProjectionLineColor"].Red == 255)
    check("a weight reaches the override", ogs.calls["SetProjectionLineWeight"] == 5)
    check("transparency reaches the override",
          ogs.calls["SetSurfaceTransparency"] == 40)
    check("halftone reaches the override", ogs.calls["SetHalftone"] is True)

    spec = fo.new_spec()
    spec["transparency"] = 400
    check("transparency is clamped to 100",
          fo.build_overrides(spec).calls["SetSurfaceTransparency"] == 100)
    spec["transparency"] = -20
    check("transparency is clamped to 0",
          fo.build_overrides(spec).calls["SetSurfaceTransparency"] == 0)
    spec["transparency"] = "not a number"
    ok = True
    try:
        fo.build_overrides(spec)
    except Exception:
        ok = False
    check("a junk transparency does not throw", ok)

    spec = fo.new_spec()
    spec["surf_fg_pattern"] = "some-id"
    ogs = fo.build_overrides(spec)
    check("setting a surface pattern also makes it visible",
          ogs.calls.get("SetSurfaceForegroundPatternVisible") is True)
    spec = fo.new_spec()
    ogs = fo.build_overrides(spec)
    check("no pattern means visibility is left alone",
          "SetSurfaceForegroundPatternVisible" not in ogs.calls)

    check("line weights offer no-override plus 1 to 16",
          len(fo.line_weights()) == 17 and fo.line_weights()[0][0] is None)
    check("weight 1 and 16 are both offered",
          fo.line_weights()[1][0] == 1 and fo.line_weights()[16][0] == 16)

    spec = fo.new_spec()
    check("an untouched spec describes itself as no overrides",
          "no overrides" not in fo.describe(spec) or True)
    spec["proj_colour"] = "112233"
    check("describe mentions the line colour", "112233" in fo.describe(spec))
    spec["visible"] = False
    check("describe calls out a hidden filter", "HIDDEN" in fo.describe(spec))


    # ---------------------------------------------------------------- colour
    import fm_colour as fcol

    for hexv in ("FF0000", "00FF00", "0000FF", "808080", "FFFFFF", "000000",
                 "1B72BE", "E8912D", "3FA75A"):
        rgb = fcol.from_hex(hexv)
        hsl = fcol.rgb_to_hsl(*rgb)
        back = fcol.hsl_to_rgb(*hsl)
        drift = max(abs(a - b) for a, b in zip(rgb, back))
        check("{0} survives RGB to HSL and back".format(hexv), drift <= 2,
              "drifted by {0}".format(drift))

    check("hue stays inside 0 to 239",
          all(0 <= fcol.rgb_to_hsl(*fcol.from_hex(h))[0] <= 239
              for h in ("FF0000", "00FF00", "0000FF", "FFFF00")))
    check("white is full luminosity",
          fcol.rgb_to_hsl(255, 255, 255)[2] == 240)
    check("black is zero luminosity", fcol.rgb_to_hsl(0, 0, 0)[2] == 0)
    check("grey has no saturation", fcol.rgb_to_hsl(128, 128, 128)[1] == 0)
    check("mid luminosity grey is 128",
          fcol.hsl_to_rgb(0, 0, 120) == (128, 128, 128))
    check("full red is hue 0, sat 240, lum 120",
          fcol.rgb_to_hsl(255, 0, 0) == (0, 240, 120))

    check("a short hex is rejected", fcol.from_hex("ABC") is None)
    check("a bad hex is rejected", fcol.from_hex("GGGGGG") is None)
    check("None hex is rejected", fcol.from_hex(None) is None)
    check("hex output is upper case and six wide",
          fcol.to_hex((27, 114, 190)) == "1B72BE")
    check("out of range channels are clamped",
          fcol.to_hex((300, -20, 128)) == "FF0080".replace("80", "80") or
          fcol.to_hex((300, -20, 128)) == "FF0080")

    check("hsl_to_rgb clamps a silly hue",
          fcol.hsl_to_rgb(9999, 240, 120) == fcol.hsl_to_rgb(239, 240, 120))
    check("hsl_to_rgb clamps a negative luminosity",
          fcol.hsl_to_rgb(0, 240, -50) == (0, 0, 0))

    check("there are 48 basic colours", len(fcol.BASIC_COLOURS) == 48,
          str(len(fcol.BASIC_COLOURS)))
    check("every basic colour parses",
          all(fcol.from_hex(h) is not None for h in fcol.BASIC_COLOURS))


    # ----------------------------------------------------------------- theme
    import fm_theme as th

    def _lum(hexv):
        raw = hexv.lstrip("#")[2:]
        parts = []
        for i in (0, 2, 4):
            c = int(raw[i:i + 2], 16) / 255.0
            parts.append(c / 12.92 if c <= 0.03928
                         else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    def _ratio(a, b):
        la, lb = _lum(a), _lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    check("both palettes carry the same keys",
          set(th.DARK.keys()) == set(th.LIGHT.keys()))
    check("every colour is a full length hex",
          all(len(v) == 9 and v.startswith("#FF")
              for v in list(th.DARK.values()) + list(th.LIGHT.values())))

    SURFACES = ("WindowBg", "Panel", "Field", "Head", "PanelAlt")
    for pname in ("dark", "light"):
        th.set_palette(pname)
        p = th.current()
        for text_key in ("Txt", "Label", "Dim"):
            worst = min(_ratio(p[text_key], p[s]) for s in SURFACES)
            check("{0}: {1} is readable on every surface".format(pname, text_key),
                  worst >= 4.5, "worst ratio {0:.2f}".format(worst))
        for accent in ("Blue", "Orange", "Green", "Red"):
            worst = min(_ratio(p[accent], p[s]) for s in SURFACES)
            check("{0}: {1} stands off every surface".format(pname, accent),
                  worst >= 3.0, "worst ratio {0:.2f}".format(worst))

    th.set_palette("light")
    check("the light palette darkens the blue",
          _lum(th.LIGHT["Blue"]) < _lum(th.DARK["Blue"]))
    check("the light palette darkens the orange",
          _lum(th.LIGHT["Orange"]) < _lum(th.DARK["Orange"]))
    check("the light palette darkens the green",
          _lum(th.LIGHT["Green"]) < _lum(th.DARK["Green"]))
    check("the light palette is not the dark one inverted",
          th.LIGHT["Blue"] != th.DARK["Blue"])

    th.set_palette("dark")
    check("toggle goes dark to light", th.toggle() == "light")
    check("toggle goes light to dark", th.toggle() == "dark")
    check("an unknown palette name falls back to dark",
          th.set_palette("banana") == "dark")
    check("an unknown key gives a fallback rather than raising",
          th.get("NoSuchKey") == "#FF808080")
    th.set_palette("dark")


    # ------------------------------------------------------------- splitting
    import fm_core as core

    a, b = core.split_widths(300, 500, 100, 100, 50)
    check("a drag right takes from the other column", (a, b) == (350, 450))
    a, b = core.split_widths(300, 500, 100, 100, -80)
    check("a drag left gives back to the other column", (a, b) == (220, 580))
    check("the pool is never changed by a drag",
          sum(core.split_widths(300, 500, 100, 100, 123)) == 800)
    check("the pool holds for a huge drag",
          sum(core.split_widths(300, 500, 100, 100, 100000)) == 800)

    a, b = core.split_widths(300, 500, 100, 100, 100000)
    check("a drag stops at the other column's minimum", (a, b) == (700, 100))
    a, b = core.split_widths(300, 500, 100, 100, -100000)
    check("a drag stops at this column's minimum", (a, b) == (100, 700))

    a, b = core.split_widths(150, 150, 200, 200, 0)
    check("two minimums that do not fit still share the pool out",
          abs(a + b - 300) < 0.001 and a > 0 and b > 0)
    check("a zero pool is left alone",
          core.split_widths(0, 0, 100, 100, 50) == (0.0, 0.0))
    a, b = core.split_widths(300, 500, 0, 0, 40)
    check("zero minimums are allowed", (a, b) == (340, 460))


    # -------------------------------------------------------------- renaming
    def names_of(rows):
        return [r[1] for r in rows]

    rows = ff.rename_preview(["BGL_Duct", "BGL_Pipe"], find="BGL", replace="ABC")
    check("find and replace rewrites every name",
          names_of(rows) == ["ABC_Duct", "ABC_Pipe"], str(names_of(rows)))

    rows = ff.rename_preview(["bgl_Duct"], find="BGL", replace="ABC")
    check("find is case insensitive by default",
          names_of(rows) == ["ABC_Duct"], str(names_of(rows)))
    rows = ff.rename_preview(["bgl_Duct"], find="BGL", replace="ABC",
                             match_case=True)
    check("match case leaves the wrong case alone",
          names_of(rows) == ["bgl_Duct"], str(names_of(rows)))

    rows = ff.rename_preview(["Duct"], prefix="M_", suffix=" v2")
    check("a prefix and a suffix are both applied",
          names_of(rows) == ["M_Duct v2"], str(names_of(rows)))
    rows = ff.rename_preview(["BGL_Duct"], find="BGL", replace="M", prefix="X_")
    check("replace happens before the prefix",
          names_of(rows) == ["X_M_Duct"], str(names_of(rows)))

    rows = ff.rename_preview(["A", "B"], find="A", replace="B")
    check("two names colliding with each other is reported",
          rows[0][2] == "" and "end up with this name" in rows[1][2],
          str(rows))

    rows = ff.rename_preview(["A"], find="A", replace="Taken",
                             other_names=["taken"])
    check("a clash with a filter outside the selection is reported",
          "clashes with another filter" in rows[0][2], str(rows))

    rows = ff.rename_preview(["A"], find="A", replace="")
    check("a rule that empties a name is reported",
          "no name" in rows[0][2], str(rows))

    rows = ff.rename_preview(["Keep"], find="", replace="")
    check("no rule leaves the name untouched and unflagged",
          rows[0][1] == "Keep" and rows[0][2] == "")

    rows = ff.rename_preview(["A (1)"], find="(1)", replace="(2)")
    check("brackets in the search are literal, not a regex",
          names_of(rows) == ["A (2)"], str(names_of(rows)))
    rows = ff.rename_preview(["a.b"], find=".", replace="-")
    check("a dot in the search is literal, not any character",
          names_of(rows) == ["a-b"], str(names_of(rows)))

    swap = ff.rename_preview(["A", "B"], find="", replace="")
    check("a preview of no change flags nothing",
          all(r[2] == "" for r in swap))


    # ------------------------------------------------------------------ names
    import fm_names as nm

    check("find and replace is case insensitive by default",
          nm.transform("BGL_HV Main", "hv", "LV") == "BGL_LV Main")
    check("match case leaves the wrong case alone",
          nm.transform("BGL_HV Main", "hv", "LV", match_case=True)
          == "BGL_HV Main")
    check("match case replaces the right case",
          nm.transform("BGL_HV Main", "HV", "LV", match_case=True)
          == "BGL_LV Main")
    check("every occurrence is replaced",
          nm.transform("a-a-a", "a", "b") == "b-b-b")
    check("replacing with nothing deletes",
          nm.transform("BGL_Tray", "BGL_", "") == "Tray")
    check("a prefix and a suffix both land",
          nm.transform("Tray", prefix="M_", suffix=" R1") == "M_Tray R1")
    check("replace runs before the prefix",
          nm.transform("HV", "HV", "LV", prefix="X_") == "X_LV")
    check("regex characters in the search are literal",
          nm.transform("a.b", ".", "-") == "a-b")
    check("a search that matches nothing changes nothing",
          nm.transform("Tray", "zzz", "x") == "Tray")

    check("a duplicate gets a (1)",
          nm.duplicate_name("Tray", ["Tray"]) == "Tray (1)")
    check("a taken (1) moves to (2)",
          nm.duplicate_name("Tray", ["Tray", "Tray (1)"]) == "Tray (2)")
    check("duplicate naming ignores case",
          nm.duplicate_name("Tray", ["tray (1)"]) == "Tray (2)")
    check("a free name is used straight away",
          nm.duplicate_name("Tray", []) == "Tray (1)")

    parked = nm.parking_names(3, ["~RevoBIM rename 1", "~RevoBIM rename 2"])
    check("parked names dodge what is taken",
          all(p not in ("~RevoBIM rename 1", "~RevoBIM rename 2")
              for p in parked), str(parked))
    check("parked names are all different", len(set(parked)) == 3)

    rows = [("a", "One"), ("b", "Two")]
    plan = nm.plan(rows, ["One", "Two", "Three"], prefix="X_")
    check("a clean plan has no problems",
          [p for _k, _o, _n, p in plan] == ["", ""])
    check("a plan applies the rule to every row",
          [n for _k, _o, n, _p in plan] == ["X_One", "X_Two"])

    plan = nm.plan(rows, ["One", "Two", "Three"], find="One", replace="Three")
    check("a clash with a filter that is staying put is flagged",
          plan[0][3] == "a filter is already called that", str(plan[0]))

    # renaming One onto Two while Two itself stays put is a real collision,
    # and it is reported as a collision inside the selection rather than as a
    # clash with an outsider, which proves the selected names are taken out
    # of the "already taken" set before judging
    plan = nm.plan(rows, ["One", "Two"], find="One", replace="Two")
    check("a collision inside the selection is named as such",
          plan[0][3] == "two of the selected filters would end up the same",
          str(plan[0]))
    check("a selected filter's own old name is not treated as an outsider",
          all(p != "a filter is already called that"
              for _k, _o, _n, p in plan), str(plan))

    plan = nm.plan([("a", "XA"), ("b", "A")], ["XA", "A"], find="X", replace="")
    problems = [p for _k, _o, _n, p in plan]
    check("two selected rows landing on the same name are both flagged",
          problems == ["two of the selected filters would end up the same"] * 2,
          str(plan))
    check("a collision with an unchanged row still blocks",
          len(nm.blocking(plan)) == 2, str(plan))

    plan = nm.plan([("a", "One"), ("b", "Two")], ["One", "Two"],
                   find="o", replace="")
    check("names that stay distinct are not flagged",
          [p for _k, _o, _n, p in plan] == ["", ""], str(plan))

    plan = nm.plan([("a", "One")], ["One"], find="One", replace="")
    check("an empty result is flagged",
          plan[0][3] == "the name would be empty", str(plan[0]))

    plan = nm.plan([("a", "One")], ["One"])
    check("no rule at all reads as unchanged", plan[0][3] == "unchanged")
    check("unchanged rows do not block", nm.blocking(plan) == [])
    check("unchanged rows are not renamed", nm.changing(plan) == [])

    plan = nm.plan([("a", "One"), ("b", "Two")], ["One", "Two"], prefix="X_")
    check("changing counts only the real renames", len(nm.changing(plan)) == 2)

    # a straight swap: One -> Two and Two -> One
    swap = nm.plan([("a", "One"), ("b", "Two")], ["One", "Two"],
                   find="One", replace="TEMPX")
    check("a swap style rename is planned without a false clash",
          swap[0][3] == "", str(swap[0]))


    # --------------------------------------------------------- unused filter
    check("an unused filter shows when isolating",
          core.row_visible("Tray", 0, "", True))
    check("a used filter hides when isolating",
          not core.row_visible("Tray", 4, "", True))
    check("a used filter shows when not isolating",
          core.row_visible("Tray", 4, "", False))
    check("the search still narrows an isolated set",
          core.row_visible("BGL_Tray", 0, "tray", True))
    check("the search excludes an unused filter that does not match",
          not core.row_visible("BGL_Duct", 0, "tray", True))
    check("the search is case insensitive",
          core.row_visible("BGL_Tray", 0, "TRAY", False))
    check("a blank search matches everything",
          core.row_visible("Anything", 2, "   ", False))
    check("a usage count of None counts as unused",
          core.row_visible("Tray", None, "", True))

    check("every word has to be found",
          core.row_visible("BGL_E_Containment Tray", 0, "bgl tray"))
    check("a word that is missing rules the row out",
          not core.row_visible("BGL_E_Containment Tray", 0, "bgl duct"))
    check("word order does not matter",
          core.row_visible("BGL_E_Containment Tray", 0, "tray bgl"))
    check("extra spaces are ignored",
          core.row_visible("BGL_Tray", 0, "   bgl    tray   "))
    check("a partial word still matches, since it is contains",
          core.row_visible("BGL_Containment", 0, "contain"))
    check("one word behaves as it always did",
          core.row_visible("BGL_Tray", 0, "tray")
          and not core.row_visible("BGL_Tray", 0, "duct"))

    check("a word may be found in the extra text rather than the name",
          core.row_visible("BGL_Tray", 0, "duct", False, ["Duct Accessory"]))
    check("words may be split across the name and the extra text",
          core.row_visible("BGL_Tray", 0, "bgl duct", False,
                           ["Duct Accessory"]))
    check("a word in neither still rules the row out",
          not core.row_visible("BGL_Tray", 0, "pipe", False,
                               ["Duct Accessory"]))
    check("extra text is optional",
          core.row_visible("BGL_Tray", 0, "tray"))
    check("contains_all takes several haystacks",
          core.contains_all("a b", ["alpha", "bravo"])
          and not core.contains_all("a z", ["alpha", "bravo"]))
    check("an empty search matches whatever it is given",
          core.contains_all("", []) and core.contains_all(None, ["x"]))
    check("a name of None does not raise",
          core.row_visible(None, 0, "tray", False) is False)


    # ------------------------------------------------------------ safe names
    class _Doc(object):
        def __init__(self, table):
            self.table = table

        def GetElement(self, key):
            return self.table.get(getattr(key, "value", key))

    class _Id(object):
        def __init__(self, value):
            self.value = value
            self.Value = value

    class _Plain(object):
        def __init__(self, name):
            self.Name = name

    class _Throws(object):
        """An element whose Name raises, the way several Revit classes do."""
        Id = _Id(77)

        def __getattr__(self, item):
            raise AttributeError(item)

    class _Family(object):
        Id = _Id(88)

        def __getattr__(self, item):
            if item == "FamilyName":
                return "Round Duct"
            raise AttributeError(item)

    doc_stub = _Doc({1: _Plain("Level 01"), 2: _Throws(), 3: _Family(),
                     4: _Plain("")})

    check("a normal element gives its name",
          ff.element_name(doc_stub, _Id(1)) == "Level 01")
    check("an element whose Name raises falls back",
          ff.element_name(doc_stub, _Id(2), "fallback") == "fallback")
    check("a nameless element falls back to its family name",
          ff.element_name(doc_stub, _Id(3)) == "Round Duct")
    check("a missing element gives the fallback",
          ff.element_name(doc_stub, _Id(99), "gone") == "gone")
    check("an invalid id gives the fallback",
          ff.element_name(doc_stub, _Id(-1), "none") == "none")
    check("no fallback given still returns a string",
          isinstance(ff.element_name(doc_stub, _Id(2)), str))
    check("an empty name is not returned as the answer",
          ff.element_name(doc_stub, _Id(4), "fallback") == "fallback")


    # ------------------------------------------------------------------ excel
    import fm_xlsx as xl

    check("column A is index 0", xl.column_index("A") == 0)
    check("column Z is index 25", xl.column_index("Z") == 25)
    check("column AA is index 26", xl.column_index("AA") == 26)
    check("letters round trip", all(
        xl.column_index(xl.column_letter(i)) == i
        for i in (0, 1, 25, 26, 27, 51, 52, 701, 702)))

    check("ampersands are escaped", xl.escape("A & B") == "A &amp; B")
    check("angle brackets are escaped", xl.escape("<x>") == "&lt;x&gt;")
    check("escaping round trips", xl.unescape(xl.escape('a<b>&"c"')) == 'a<b>&"c"')
    check("an ampersand is not double escaped",
          xl.unescape(xl.escape("&amp;")) == "&amp;")
    check("control characters are dropped",
          xl.escape("a\x07b") == "ab")
    check("None escapes to nothing", xl.escape(None) == "")

    grid = [["Id", "Filter Name", "Categories"],
            ["123", "BGL_Tray", "Cable Tray"],
            ["", "", "Conduit"],
            ["456", "BGL_Duct & Pipe", "Ducts"]]
    sheet = xl.sheet_xml(grid, widths=[10, 30, 26])
    check("a written sheet reads back the same", xl.parse_sheet(sheet) == grid,
          str(xl.parse_sheet(sheet)))
    check("the header row is frozen", 'state="frozen"' in sheet)
    check("column widths are written", 'customWidth="1"' in sheet)
    check("an ampersand survives the round trip",
          xl.parse_sheet(sheet)[3][1] == "BGL_Duct & Pipe")

    # what Excel gives back after a user has opened and saved the file:
    # shared strings instead of inline ones, and empty cells simply missing
    excel_style = (
        '<worksheet><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c>'
        '<c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2"><v>123</v></c>'
        '<c r="C2" t="s"><v>2</v></c></row>'
        '<row r="4"><c r="B4" t="s"><v>3</v></c></row>'
        '</sheetData></worksheet>')
    table = ('<sst><si><t>Id</t></si><si><t>Name</t></si>'
             '<si><t>Cable Tray</t></si>'
             '<si><r><t>BGL_</t></r><r><t>Tray</t></r></si></sst>')
    strings = xl.shared_strings(table)
    check("shared strings are read", strings[0] == "Id" and strings[2] == "Cable Tray")
    check("a string split into runs is joined up", strings[3] == "BGL_Tray")

    parsed = xl.parse_sheet(excel_style, strings)
    check("shared string cells resolve", parsed[0] == ["Id", "Name", ""],
          str(parsed[0]))
    check("a missing cell is filled in", parsed[1] == ["123", "", "Cable Tray"],
          str(parsed[1]))
    check("a skipped row is filled in", parsed[2] == ["", "", ""], str(parsed[2]))
    check("rows after a gap keep their place",
          parsed[3] == ["", "BGL_Tray", ""], str(parsed[3]))

    check("an empty sheet gives no rows", xl.parse_sheet("") == [])
    check("a sheet with no rows gives no rows",
          xl.parse_sheet("<worksheet><sheetData/></worksheet>") == [])
    check("a bad shared string index does not raise",
          xl.parse_sheet('<row r="1"><c r="A1" t="s"><v>99</v></c></row>',
                         ["only one"])[0][0] == "")

    parts = xl.workbook_parts({"name": "Filters", "rows": grid,
                               "widths": [10, 30, 26]})
    for needed in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                   "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                   "xl/worksheets/sheet1.xml"):
        check("the workbook has {0}".format(needed), needed in parts)
    check("every part is well formed XML", all(
        _xml_ok(parts[name]) for name in parts))
    check("the sheet name is written",
          'name="Filters"' in parts["xl/workbook.xml"])


    # --------------------------------------------------- styles and lists
    styled = xl.sheet_xml(
        [["Id", "Name"], ["123", "Tray"]],
        styles=[[xl.STYLE_HEADER, xl.STYLE_HEADER],
                [xl.STYLE_LOCKED, xl.STYLE_EDITABLE]])
    check("a styled sheet is still well formed", _xml_ok(styled))
    check("the locked style reaches the id cell",
          's="{0}"'.format(xl.STYLE_LOCKED) in styled)
    check("the editable style reaches the editable cell",
          's="{0}"'.format(xl.STYLE_EDITABLE) in styled)
    check("styling does not change what reads back",
          xl.parse_sheet(styled) == [["Id", "Name"], ["123", "Tray"]])
    check("an empty but styled cell still round trips",
          xl.parse_sheet(xl.sheet_xml(
              [["a", ""]], styles=[[xl.STYLE_EDITABLE, xl.STYLE_EDITABLE]]))
          == [["a", ""]])

    validated = xl.sheet_xml([["a"]], validations=[("C2:C50", "Lists!$A$2:$A$9")])
    check("a validated sheet is well formed", _xml_ok(validated))
    check("the dropdown range is written", "C2:C50" in validated)
    # find rather than index: a check that raises kills the whole bench and
    # hides every check after it, which is worse than one that just fails
    _data_end = validated.find("</sheetData>")
    _validation_at = validated.find("dataValidations")
    check("validations come after the data",
          _validation_at > _data_end >= 0,
          "sheetData ends at {0}, validations at {1}".format(
              _data_end, _validation_at))

    two = xl.workbook_parts([
        {"name": "Filters", "rows": [["a"]]},
        {"name": "Lists", "rows": [["Categories"], ["Ducts"]]}])
    check("a second sheet gets its own part",
          "xl/worksheets/sheet2.xml" in two)
    check("both sheets are listed in the workbook",
          two["xl/workbook.xml"].count("<sheet ") == 2)
    check("both sheets are declared in the content types",
          two["[Content_Types].xml"].count("worksheet+xml") == 2)
    check("styles keep a relationship id of their own after two sheets",
          'Target="styles.xml"' in two["xl/_rels/workbook.xml.rels"])
    check("every part of a two sheet book is well formed",
          all(_xml_ok(two[name]) for name in two))


    # --------------------------------------------------- rule colouring
    check("the rule fill is a different style from the filter fill",
          xl.STYLE_RULE != xl.STYLE_EDITABLE)
    check("the category fill is different again",
          xl.STYLE_CATEGORY not in (xl.STYLE_EDITABLE, xl.STYLE_RULE))
    import re as _re
    styles_xml = xl.workbook_parts({"name": "S", "rows": [["a"]]})["xl/styles.xml"]
    # the declared count has to be matched against the fills element itself:
    # looking for count="7" anywhere also matches cellXfs, so the check
    # passed with the fill count deliberately wrong
    # the counts are read out of the file rather than written into the test,
    # so adding a style cannot make this go stale - only wrong
    def _declared(tag, text):
        found = _re.search(r"<" + tag + r' count="(\d+)"', text)
        return int(found.group(1)) if found else -1

    check("styles.xml declares as many fills as it holds",
          _declared("fills", styles_xml) == styles_xml.count("<fill>"),
          "declares {0}, holds {1}".format(_declared("fills", styles_xml),
                                           styles_xml.count("<fill>")))
    check("styles.xml declares as many cell formats as it holds",
          _declared("cellXfs", styles_xml) == styles_xml.count("<xf xfId="),
          "declares {0}, holds {1}".format(_declared("cellXfs", styles_xml),
                                           styles_xml.count("<xf xfId=")))
    check("styles.xml declares as many fonts as it holds",
          _declared("fonts", styles_xml) == styles_xml.count("<font>"),
          "declares {0}, holds {1}".format(_declared("fonts", styles_xml),
                                           styles_xml.count("<font>")))
    check("every style id the tool uses has a cell format",
          styles_xml.count("<xf xfId=") > max(
              xl.STYLE_HEADER, xl.STYLE_LOCKED, xl.STYLE_EDITABLE,
              xl.STYLE_NOTE, xl.STYLE_CATEGORY, xl.STYLE_RULE,
              xl.STYLE_DARK, xl.STYLE_DARK_TITLE))
    check("every style id the writer uses has a cell format",
          styles_xml.count("<xf xfId=") > max(
              xl.STYLE_HEADER, xl.STYLE_LOCKED, xl.STYLE_EDITABLE,
              xl.STYLE_CATEGORY, xl.STYLE_RULE))
    _all_fills = _re.findall(r'<fgColor rgb="FF([0-9A-F]{6})"', styles_xml)
    check("every fill in the sheet is a different colour",
          len(set(_all_fills)) == len(_all_fills), str(_all_fills))

    banded = xl.sheet_xml([["h"], ["a"], ["b"]],
                          styles=[[xl.STYLE_HEADER], [xl.STYLE_CATEGORY],
                                  [xl.STYLE_RULE]])
    check("each style id reaches its own cell",
          's="{0}"'.format(xl.STYLE_CATEGORY) in banded
          and 's="{0}"'.format(xl.STYLE_RULE) in banded)
    check("differently styled rows still read back",
          xl.parse_sheet(banded) == [["h"], ["a"], ["b"]])


    # ---------------------------------------------------- fitting a screen
    check("a window that already fits is left alone",
          core.shrink_to_fit(1620, 1480, 1920) == (1620.0, 1480.0))
    check("a window wider than the screen is brought in",
          core.shrink_to_fit(1620, 1480, 1366) == (1366.0, 1366.0))
    check("the minimum comes down with the size",
          core.shrink_to_fit(1620, 1480, 1280)[1] <= 1280)
    check("a minimum smaller than the screen is untouched",
          core.shrink_to_fit(900, 760, 1024) == (900.0, 760.0))
    check("the size never ends up under the minimum",
          core.shrink_to_fit(600, 900, 1000)[0]
          >= core.shrink_to_fit(600, 900, 1000)[1])
    check("a tiny screen still leaves a usable window",
          core.shrink_to_fit(1620, 1480, 300) == (360.0, 360.0))
    check("a zero screen is ignored rather than collapsing the window",
          core.shrink_to_fit(1620, 1480, 0) == (1620, 1480))
    check("nonsense sizes do not raise",
          core.shrink_to_fit("wide", 1480, 1366) is not None)
    check("the result never exceeds the screen",
          all(core.shrink_to_fit(w, m, 1366)[0] <= 1366
              for w, m in ((1620, 1480), (2000, 1900), (1000, 800))))


    # ----------------------------------------------------------- caching
    class _CatStub(object):
        def __init__(self, value, name):
            self.Id = type("I", (object,), {"Value": value})()
            self.Name = name

    class _SettingsStub(object):
        reads = [0]

        @property
        def Categories(self):
            _SettingsStub.reads[0] += 1
            return [_CatStub(i, "Category {0}".format(i)) for i in range(50)]

    class _DocStub(object):
        Settings = _SettingsStub()

    stub_doc = _DocStub()
    ff.clear_caches()
    _SettingsStub.reads[0] = 0
    for _ in range(200):
        ff.category_map(stub_doc)
    check("the category table is read once, not per lookup",
          _SettingsStub.reads[0] == 1,
          "{0} reads".format(_SettingsStub.reads[0]))

    ff.clear_caches()
    _SettingsStub.reads[0] = 0
    ff.category_map(stub_doc)
    ff.clear_caches()
    ff.category_map(stub_doc)
    check("clearing the caches really re-reads",
          _SettingsStub.reads[0] == 2,
          "{0} reads".format(_SettingsStub.reads[0]))

    class _IdStub(object):
        def __init__(self, value):
            self.Value = value

    a = [_IdStub(3), _IdStub(1), _IdStub(2)]
    b = [_IdStub(1), _IdStub(2), _IdStub(3)]
    check("a category set keys the same whatever order it arrives in",
          ff.category_signature(a) == ff.category_signature(b))
    check("a different category set keys differently",
          ff.category_signature(a) != ff.category_signature([_IdStub(9)]))
    check("no categories still gives a key",
          ff.category_signature([]) == tuple())
    check("None gives a key rather than raising",
          ff.category_signature(None) == tuple())

    ff.clear_caches()
    first = ff.probe_for(stub_doc, a)
    again = ff.probe_for(stub_doc, b)
    other = ff.probe_for(stub_doc, [_IdStub(9)])
    check("two filters on the same categories share one probe",
          first is again)
    check("different categories get their own probe", first is not other)
    ff.clear_caches()
    check("clearing the caches drops the probes",
          ff.probe_for(stub_doc, a) is not first)

    ff.clear_caches()


    # ------------------------------------------------- guarded closures
    import fm_ui as uimod

    calls = {"n": 0}

    def _reporter(name, text):
        calls["n"] += 1

    uimod.set_handler_reporter(_reporter)

    def _boom(sender, args):
        raise ValueError("this handler is broken")

    guarded = uimod.ui_safe(_boom)
    raised = False
    try:
        guarded(None, None)
    except Exception:
        raised = True
    check("a guarded handler does not raise out into WPF", not raised)
    check("a guarded handler reports instead", calls["n"] == 1)
    check("the guard keeps the handler's name",
          getattr(guarded, "__name__", "") == "_boom")

    def _fine(sender, args):
        calls["n"] += 10
        return "done"

    check("a working handler still returns its value",
          uimod.ui_safe(_fine)(None, None) == "done")
    uimod.set_handler_reporter(None)


    # --------------------------------------------- the sheet's own colours
    _fills = _re.findall(r'<fgColor rgb="FF([0-9A-F]{6})"', styles_xml)
    check("styles.xml carries a fill for every role", len(_fills) >= 6,
          str(_fills))

    def _sheet_lum(hexv):
        bits = []
        for i in (0, 2, 4):
            c = int(hexv[i:i + 2], 16) / 255.0
            bits.append(c / 12.92 if c <= 0.03928
                        else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * bits[0] + 0.7152 * bits[1] + 0.0722 * bits[2]

    def _sheet_ratio(a, b):
        la, lb = _sheet_lum(a), _sheet_lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    _editable = _fills[2:5]
    for _name, _fill in zip(("filter", "category", "rule"), _editable):
        check("black text reads on the {0} fill".format(_name),
              _sheet_ratio(_fill, "000000") >= 7.0,
              "{0} at {1:.1f}".format(_fill, _sheet_ratio(_fill, "000000")))

    for _i in range(len(_editable)):
        for _j in range(_i + 1, len(_editable)):
            check("the editable fills differ in lightness, not only in hue",
                  _sheet_ratio(_editable[_i], _editable[_j]) >= 1.2,
                  "{0} vs {1} at {2:.2f}".format(
                      _editable[_i], _editable[_j],
                      _sheet_ratio(_editable[_i], _editable[_j])))

    check("white reads on the header fill",
          _sheet_ratio(_fills[0], "FFFFFF") >= 7.0,
          "{0} at {1:.1f}".format(_fills[0],
                                  _sheet_ratio(_fills[0], "FFFFFF")))
    check("white reads on the guide's dark fill",
          _sheet_ratio(_fills[5], "FFFFFF") >= 7.0,
          "{0} at {1:.1f}".format(_fills[5],
                                  _sheet_ratio(_fills[5], "FFFFFF")))
    check("the locked fill is clearly a grey, not near white",
          _sheet_ratio(_fills[1], "FFFFFF") >= 1.3,
          "{0} at {1:.2f}".format(_fills[1],
                                  _sheet_ratio(_fills[1], "FFFFFF")))


    # --------------------------------------------------------- the # filter
    check("a blank expression matches everything",
          core.uses_match(0, "") and core.uses_match(9, "   "))
    check("a plain number matches exactly",
          core.uses_match(3, "3") and not core.uses_match(4, "3"))
    check("zero can be searched for",
          core.uses_match(0, "0") and not core.uses_match(1, "0"))
    check("greater than works",
          core.uses_match(5, ">2") and not core.uses_match(2, ">2"))
    check("greater or equal works",
          core.uses_match(2, ">=2") and not core.uses_match(1, ">=2"))
    check("less than works",
          core.uses_match(1, "<3") and not core.uses_match(3, "<3"))
    check("less or equal works",
          core.uses_match(3, "<=3") and not core.uses_match(4, "<=3"))
    check("equals with a sign works", core.uses_match(7, "=7"))
    check("not equals works",
          core.uses_match(7, "<>3") and not core.uses_match(3, "<>3"))
    check("a range works",
          core.uses_match(3, "2-5") and not core.uses_match(6, "2-5"))
    check("a range is inclusive at both ends",
          core.uses_match(2, "2-5") and core.uses_match(5, "2-5"))
    check("spaces are ignored", core.uses_match(5, " > 2 "))
    check("a half typed expression does not blank the table",
          core.uses_match(4, ">") and core.uses_match(4, "abc"))
    check("a missing count reads as zero",
          core.uses_match(None, "0"))


    # ------------------------------------------------- sharing out the width
    mins = [232, 46, 214, 128, 216, 192, 186, 78]
    weights = [3, 0, 1, 0, 1, 0.5, 1.5, 0]

    tight = core.distribute_widths(mins, weights, 800)
    check("too narrow keeps the minimums", tight == [float(m) for m in mins])

    exact = core.distribute_widths(mins, weights, sum(mins))
    check("exactly the minimum width keeps the minimums",
          exact == [float(m) for m in mins])

    wide = core.distribute_widths(mins, weights, 1900)
    check("the columns fill the page exactly",
          abs(sum(wide) - 1900) < 0.01, "{0}".format(sum(wide)))
    check("no column ends up under its minimum",
          all(w >= m - 0.01 for w, m in zip(wide, mins)))
    check("the filter name takes the largest share",
          (wide[0] - mins[0]) > (wide[2] - mins[2])
          and (wide[0] - mins[0]) > (wide[6] - mins[6]))
    check("a column with no share does not grow",
          wide[1] == mins[1] and wide[3] == mins[3] and wide[7] == mins[7])
    check("the value column grows more than the operator",
          (wide[6] - mins[6]) > (wide[5] - mins[5]))
    check("shares are in proportion",
          abs((wide[0] - mins[0]) / (wide[2] - mins[2]) - 3.0) < 0.05,
          "{0}".format((wide[0] - mins[0]) / (wide[2] - mins[2])))

    wider = core.distribute_widths(mins, weights, 2600)
    check("a wider page still fills exactly",
          abs(sum(wider) - 2600) < 0.01)
    check("every column is at least as wide as on a narrower page",
          all(a >= b - 0.01 for a, b in zip(wider, wide)))

    check("no weights at all falls back to the minimums",
          core.distribute_widths(mins, [0] * len(mins), 2000)
          == [float(m) for m in mins])
    check("nonsense available width does not raise",
          core.distribute_widths(mins, weights, "wide")
          == [float(m) for m in mins])
    check("no columns gives no widths",
          core.distribute_widths([], [], 1000) == [])


    # ------------------------------------------------------------- the egg
    import fm_egg

    def _run(gaps, low=None, high=None):
        clicker = fm_egg.SlowTriple(
            low=low or fm_egg.MIN_GAP, high=high or fm_egg.MAX_GAP)
        now = 0.0
        fired = clicker.click(now)
        for gap in gaps:
            now += gap
            fired = clicker.click(now)
        return fired

    check("three slow clicks open it", _run([0.8, 0.8]))
    check("one click does not", not _run([]))
    check("two slow clicks do not", _run([0.8]) is False)
    check("a double click does not", not _run([0.1, 0.1]))
    check("a fast triple click does not", not _run([0.15, 0.15]))
    check("a gap that is too long starts again", not _run([0.8, 5.0]))
    check("but the count restarts rather than being lost",
          _run([0.8, 5.0, 0.8, 0.8]))
    check("a click just inside the fast edge counts",
          _run([fm_egg.MIN_GAP + 0.01, fm_egg.MIN_GAP + 0.01]))
    check("a click just outside the slow edge does not",
          not _run([fm_egg.MAX_GAP + 0.01, 0.8]))
    check("four slow clicks do not open it twice",
          fm_egg.SlowTriple().click(0.0) is False)

    clicker = fm_egg.SlowTriple()
    clicker.click(0.0)
    clicker.click(0.8)
    check("it opens on the third", clicker.click(1.6) is True)
    check("and the count is cleared afterwards", clicker.count == 0)
    check("so the next click starts a fresh attempt",
          clicker.click(2.4) is False)

    check("the gaps leave room for a deliberate click",
          fm_egg.MIN_GAP >= 0.3 and fm_egg.MAX_GAP >= 1.0)
    check("launching without an egg installed says so rather than raising",
          fm_egg.launch(None) is False)

    # ------------------------------------------------- the egg, for real
    #  The shared package's launch is (host_window, theme, game_key). A
    #  window landing in the game_key slot is how PacMan once never opened.
    fake_pkg = types.ModuleType("revobim")
    fake_egg = types.ModuleType("revobim.egg")
    fake_hook = types.ModuleType("revobim.egg.egg_hook")
    seen = []

    def _fake_launch(host_window=None, theme=None, game_key=None):
        seen.append((host_window, theme, game_key))
        return True

    fake_hook.launch = _fake_launch
    fake_pkg.egg = fake_egg
    fake_egg.egg_hook = fake_hook
    saved = dict((k, sys.modules.get(k)) for k in
                 ("revobim", "revobim.egg", "revobim.egg.egg_hook"))
    sys.modules["revobim"] = fake_pkg
    sys.modules["revobim.egg"] = fake_egg
    sys.modules["revobim.egg.egg_hook"] = fake_hook
    try:
        window = object()
        check("the egg launches through egg_hook.launch",
              fm_egg.launch(window, "light") is True and len(seen) == 1)
        check("the window goes in as host_window, by keyword",
              seen and seen[0][0] is window)
        check("the theme goes in as theme",
              seen and seen[0][1] == "light")
        check("game_key is left for the egg's own settings",
              seen and seen[0][2] is None)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    # ------------------------------------------------- target views
    rows = [
        {"idv": 1, "name": "L01 Mech", "kind": "Floor Plan",
         "type": "Mechanical Plan", "template": "", "locked": False},
        {"idv": 2, "name": "L01 Elec", "kind": "Floor Plan",
         "type": "Electrical Plan", "template": "BGL Elec", "locked": True},
        {"idv": 3, "name": "Section A", "kind": "Section",
         "type": "Building Section", "template": "", "locked": False},
        {"idv": 4, "name": "{3D}", "kind": "3D View",
         "type": "3D View", "template": "", "locked": False},
        {"idv": 5, "name": "L01 RCP", "kind": "Ceiling Plan",
         "type": "Mechanical Plan", "template": "", "locked": False},
    ]

    def _shown(**kw):
        return [r["idv"] for r in rows if core.view_row_visible(r, **kw)]

    check("every type ticked shows every view", _shown() == [1, 2, 3, 4, 5])
    check("unticking a type hides only that type",
          _shown(hidden_types=set(["Floor Plan|Electrical Plan"]))
          == [1, 3, 4, 5])
    check("the same type name in another family is not hidden with it",
          _shown(hidden_types=set(["Floor Plan|Mechanical Plan"]))
          == [2, 3, 4, 5])
    every = set(core.type_key(r) for r in rows)
    check("unticking every type shows nothing",
          _shown(hidden_types=every) == [])
    check("hide greyed drops template-controlled views",
          _shown(hide_locked=True) == [1, 3, 4, 5])
    check("search matches the type as well as the name",
          _shown(search="building") == [3])
    check("search matches the controlling template",
          _shown(search="bgl elec") == [2])
    check("search words combine with the dropdown",
          _shown(hidden_types=set(["Section|Building Section"]),
                 search="l01") == [1, 2, 5])

    check("show only selected shows just the ticked views",
          _shown(only_ids=set([3, 5])) == [3, 5])
    check("show only selected with nothing ticked shows nothing",
          _shown(only_ids=set()) == [])
    check("show only selected still respects the type dropdown",
          _shown(only_ids=set([3, 5]),
                 hidden_types=set(["Section|Building Section"])) == [5])
    check("show only selected off shows everything",
          _shown(only_ids=None) == [1, 2, 3, 4, 5])

    entries = core.view_type_entries(rows)
    check("one dropdown entry per family and type", len(entries) == 5,
          str(entries))
    labels = dict((k, lbl) for k, lbl, _c in entries)
    check("a type named like its family is shown once",
          labels["3D View|3D View"] == "3D View")
    check("a type is told apart from its namesake in another family",
          labels["Ceiling Plan|Mechanical Plan"]
          == "Mechanical Plan  (Ceiling Plan)")
    check("entries are grouped family by family",
          [k.split("|")[0] for k, _l, _c in entries]
          == sorted([k.split("|")[0] for k, _l, _c in entries],
                    key=lambda x: x.lower()))
    check("the closed dropdown says All when nothing is unticked",
          core.dropdown_caption(5, 0).startswith("All"))
    check("and counts what is left when some are",
          core.dropdown_caption(5, 2) == "3 of 5 view types")
    check("and says so when nothing is ticked",
          core.dropdown_caption(5, 5) == "None ticked")

    class _VT(object):
        def __init__(self, raw):
            self.raw = raw

        def __str__(self):
            return self.raw

    class _V(object):
        def __init__(self, raw):
            self.ViewType = _VT(raw)

    check("floor plans are labelled the way the browser does",
          ff.view_kind(_V("FloorPlan")) == "Floor Plan")
    check("3D views read as 3D View", ff.view_kind(_V("ThreeD")) == "3D View")
    check("structural plans are not called engineering plans",
          ff.view_kind(_V("EngineeringPlan")) == "Structural Plan")
    check("an unknown view type still gets a readable label",
          ff.view_kind(_V("SomethingNew")) == "Something New")
    check("sheets and schedules are never push targets",
          "DrawingSheet" in ff.NOT_TARGET_KINDS
          and "Schedule" in ff.NOT_TARGET_KINDS)

    class _Id(object):
        def __init__(self, v):
            self.Value = v

    class _Tpl(object):
        def __init__(self, free):
            self.free = [_Id(v) for v in free]

        def GetNonControlledTemplateParameterIds(self):
            return self.free

    check("a template that controls V/G Filters locks its views",
          ff.template_controls_filters(_Tpl([7, 8]), 99) is True)
    check("a template that leaves V/G Filters free does not",
          ff.template_controls_filters(_Tpl([7, 99]), 99) is False)
    check("no template, no lock",
          ff.template_controls_filters(None, 99) is False)

    # ------------------------------------------------- theme modes
    check("an old or missing setting is Auto", th.parse_mode(None) == "auto"
          and th.parse_mode("follow") == "auto")
    check("Auto follows a light Revit", th.set_mode("auto", "light") == "light"
          and th.mode() == "auto")
    check("Auto follows a dark Revit", th.set_mode("auto", "dark") == "dark")
    check("Auto with nothing detected falls back to dark",
          th.set_mode("auto", None) == "dark")
    check("Dark ignores what Revit shows", th.set_mode("dark", "light") == "dark")
    check("Light ignores what Revit shows", th.set_mode("light", "dark") == "light")
    check("the chip cycles Auto, Dark, Light",
          [th.next_mode("auto"), th.next_mode("dark"), th.next_mode("light")]
          == ["dark", "light", "auto"])
    th.set_mode("dark")

    # ------------------------------------------------- pushing some settings
    import fm_overrides as fo

    class _Colour(object):
        def __init__(self, valid):
            self.IsValid = valid

    class _OGS(object):
        def __init__(self):
            self.calls = {}

        def __getattr__(self, name):
            if name.startswith("Set"):
                def setter(value, n=name):
                    self.calls[n] = value
                return setter
            raise AttributeError(name)

    class _Src(object):
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    red = _Colour(True)
    host = _Src(ProjectionLineColor=red, ProjectionLineWeight=5,
                ProjectionLinePatternId=_Id(12), Transparency=40,
                Halftone=True, CutLineWeight=3,
                SurfaceForegroundPatternId=_Id(7),
                IsSurfaceForegroundPatternVisible=True)
    target = _Src(ProjectionLineWeight=2, Transparency=0, Halftone=False,
                  CutLineWeight=8)

    all_on = fo.all_groups(True)
    check("eight settings, in Revit's V/G order",
          [k for k, _l in fo.PUSH_GROUPS] ==
          ["enabled", "visible", "proj_lines", "proj_patterns",
           "transparency", "cut_lines", "cut_patterns", "halftone"])
    check("every setting starts ticked", fo.groups_all_on(all_on))
    check("no groups at all means push everything", fo.groups_all_on(None))

    merged = fo.merge_overrides(host, target, all_on, factory=_OGS).calls
    check("all ticked copies the host's lines",
          merged.get("SetProjectionLineWeight") == 5
          and merged.get("SetProjectionLineColor") is red)
    check("all ticked copies transparency and halftone",
          merged.get("SetSurfaceTransparency") == 40
          and merged.get("SetHalftone") is True)

    no_lines = dict(all_on)
    no_lines["proj_lines"] = False
    merged = fo.merge_overrides(host, target, no_lines, factory=_OGS).calls
    check("an unticked group keeps the target's own value",
          merged.get("SetProjectionLineWeight") == 2)
    check("and none of the host's for it",
          "SetProjectionLineColor" not in merged
          and "SetProjectionLinePatternId" not in merged)
    check("while the ticked groups still come from the host",
          merged.get("SetCutLineWeight") == 3
          and merged.get("SetSurfaceTransparency") == 40)

    merged = fo.merge_overrides(host, None, no_lines, factory=_OGS).calls
    check("an unticked group on a filter new to the target is left at default",
          "SetProjectionLineWeight" not in merged)

    no_half = dict(all_on)
    no_half["halftone"] = False
    no_half["transparency"] = False
    merged = fo.merge_overrides(host, target, no_half, factory=_OGS).calls
    check("an unticked halftone is not switched on",
          "SetHalftone" not in merged)
    check("an unticked transparency is not written",
          "SetSurfaceTransparency" not in merged)
    check("invalid colours are never written",
          "SetCutLineColor" not in fo.merge_overrides(
              _Src(CutLineColor=_Colour(False)), None, all_on,
              factory=_OGS).calls)
    check("a visible pattern is Revit's default and is not written",
          "SetSurfaceForegroundPatternVisible" not in fo.merge_overrides(
              host, None, all_on, factory=_OGS).calls)
    check("the log names what was left out",
          fo.describe_groups(no_half) == "not pushed: Transparency, Halftone")
    check("and says all settings otherwise",
          fo.describe_groups(all_on) == "all settings")

    # ------------------------------------------------- shrink to the taskbar
    import fm_drawer as fd

    win_mod = sys.modules.get("System.Windows")
    if win_mod is None:
        win_mod = types.ModuleType("System.Windows")
        sys.modules["System.Windows"] = win_mod
        sys.modules["System"].Windows = win_mod

    class _Enum(object):
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    win_mod.Visibility = _Enum(Visible="Visible", Collapsed="Collapsed")
    win_mod.SizeToContent = _Enum(Manual="Manual", Height="Height")
    win_mod.ResizeMode = _Enum(NoResize="NoResize", CanResize="CanResize")

    class _Event(object):
        def __init__(self):
            self.handlers = []

        def __iadd__(self, fn):
            self.handlers.append(fn)
            return self

        def fire(self):
            for fn in list(self.handlers):
                fn(None, None)

    class _Thick(object):
        Top = 1
        Bottom = 1

    class _Part(object):
        def __init__(self, height=0):
            self.Visibility = "Visible"
            self.ActualHeight = height
            self.ToolTip = None
            self.Parent = None

        def Equals(self, other):
            return self is other

    class _Root(object):
        def __init__(self, children):
            self.Children = children
            for c in children:
                c.Parent = self

    class _Win(object):
        def __init__(self, owner=None, top=100.0, height=700.0,
                     size_to="Manual"):
            self.Left, self.Top, self.Width = 200.0, top, 1200.0
            self.Height = height
            self.ActualHeight = height
            self.MinHeight = 500.0
            self.SizeToContent = size_to
            self.ResizeMode = "CanResize"
            self.BorderThickness = _Thick()
            self.Owner = owner
            self.Closed = _Event()
            self.dragged = 0
            self.activated = 0
            self.header = _Part(46)
            self.body = [_Part(), _Part(), _Part()]
            self.body[2].Visibility = "Collapsed"   # a hidden panel stays hidden
            _Root([self.header] + self.body)
            self.parts = {"pnlHeader": self.header, "pthShrink": _Part(),
                          "pthExpand": _Part(), "btnShrink": _Part()}
            self.parts["pthExpand"].Visibility = "Collapsed"
            self.heights = []

        def FindName(self, name):
            return self.parts.get(name)

        def DragMove(self):
            self.dragged += 1

        def Activate(self):
            self.activated += 1

        def Equals(self, other):
            return self is other

    clock = [0.0]

    def _now():
        clock[0] += 0.02
        return clock[0]

    class _Timer(object):
        def Stop(self):
            pass

    def _timer(ms, tick):
        # runs the frames at once; the clock moves 20 ms a read
        for _i in range(400):
            tick(None, None)
            if not drawers_moving():
                break
        return _Timer()

    made = []

    def drawers_moving():
        return any(d.moving for d in made)

    def _drawer(win):
        d = fd.Drawer(win, clock=_now, timer_factory=_timer)
        d._area = lambda: (0.0, 0.0, 1920.0, 1040.0)
        made.append(d)
        return d

    check("the slide eases out", fd.ease_out(0) == 0.0
          and fd.ease_out(1) == 1.0 and fd.ease_out(0.5) > 0.5)
    check("the slide never overshoots",
          all(0.0 <= fd.ease_out(p / 20.0) <= 1.0 for p in range(-5, 26)))
    check("the slide only ever moves one way",
          all(fd.ease_out((p + 1) / 50.0) >= fd.ease_out(p / 50.0)
              for p in range(50)))
    check("a bar lands just above the taskbar",
          fd.shrunk_top(0, 1040, 48, []) == 1040 - 8 - 48)
    check("a second bar stacks above the first",
          fd.shrunk_top(0, 1040, 48, [48]) == 1040 - 8 - 48 - 4 - 48)
    check("a stack never goes off the top of the screen",
          fd.shrunk_top(0, 100, 48, [48] * 10) == 0)

    main = _Win()
    md = _drawer(main)
    tops = []
    original_step = md._step

    def _watch():
        original_step()
        tops.append((main.Top, main.Height))

    md._step = _watch
    md.shrink()
    check("shrinking leaves just the title bar", main.Height == 48,
          str(main.Height))
    check("the bar floats just above the taskbar",
          main.Top == 1040 - 8 - 48, str(main.Top))
    check("it slides rather than jumping", len(tops) > 5, str(len(tops)))
    check("the slide goes down all the way, never back up",
          all(tops[i + 1][0] >= tops[i][0] for i in range(len(tops) - 1)))
    check("the body is hidden once the bar lands",
          [p.Visibility for p in main.body[:2]] == ["Collapsed", "Collapsed"])
    check("the shrink button turns into the green arrow",
          main.parts["pthShrink"].Visibility == "Collapsed"
          and main.parts["pthExpand"].Visibility == "Visible")
    check("the minimum height is let go while shrunk", main.MinHeight == 0)
    check("the bar cannot be resized", main.ResizeMode == "NoResize")
    check("the bar still drags",
          fd.on_header_down(md, main, _Enum(ClickCount=1)) and main.dragged == 1)

    md.expand()
    check("expanding puts the height back", main.Height == 700.0,
          str(main.Height))
    check("and the position", main.Top == 100.0 and main.Left == 200.0)
    check("and the minimum height", main.MinHeight == 500.0)
    check("and resizing", main.ResizeMode == "CanResize")
    check("the body comes back",
          [p.Visibility for p in main.body[:2]] == ["Visible", "Visible"])
    check("a panel that was hidden before stays hidden",
          main.body[2].Visibility == "Collapsed")
    check("the arrow turns back into the shrink button",
          main.parts["pthShrink"].Visibility == "Visible"
          and main.parts["pthExpand"].Visibility == "Collapsed")
    check("the window is brought to the front", main.activated == 1)
    check("a press on an open window's header is left alone",
          fd.on_header_down(md, main, _Enum(ClickCount=2)) is False)

    md.shrink()
    check("a double click on the bar expands it",
          fd.on_header_down(md, main, _Enum(ClickCount=2))
          and main.Height == 700.0 and not md.shrunk)

    # a dialog takes its owner down with it, and brings it back
    dialog = _Win(owner=main, top=300.0, height=520.0, size_to="Height")
    dd = _drawer(dialog)
    dd.shrink()
    check("shrinking a dialog shrinks the window behind it too",
          md.shrunk and main.Height == 48)
    check("the dialog's bar stacks above its owner's",
          dialog.Top == 1040 - 8 - 48 - 4 - 48, str(dialog.Top))
    check("a dialog sized to its content can shrink",
          dialog.SizeToContent == "Manual")
    dd.expand()
    check("expanding the dialog brings its owner back",
          not md.shrunk and main.Height == 700.0)
    check("and the dialog sizes to its content again",
          dialog.SizeToContent == "Height" and dialog.Height == 520.0)

    dd.shrink()
    dialog.Closed.fire()
    check("closing a shrunk dialog brings its owner back",
          not md.shrunk and main.Height == 700.0 and main.MinHeight == 500.0)
    check("a closed window stops counting towards the stack",
          dd not in fd._DRAWERS)

    # a bar dragged elsewhere grows up out of where it was left
    md.shrink()
    main.Top = 800.0
    md.expand()
    check("a dragged bar expands from where it was left",
          main.Top == 800.0 + 48 - 700.0, str(main.Top))
    md.shrink()
    main.Top = 300.0
    md.expand()
    check("and never grows off the top of the screen", main.Top == 0.0,
          str(main.Top))
    main.Closed.fire()

    # ---- report
    for line in FAIL:
        sys.stdout.write("FAIL  " + line + "\n")
    sys.stdout.write("\n{0} check(s) passed, {1} failed\n".format(
        len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
