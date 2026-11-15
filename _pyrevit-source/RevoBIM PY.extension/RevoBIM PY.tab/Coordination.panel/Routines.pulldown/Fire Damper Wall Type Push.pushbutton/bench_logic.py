# -*- coding: utf-8 -*-
"""Bench test for the decisions Fire Damper Wall Type Push makes.

`import_check.py` proves the modules load and the XAML parses. This one proves
the rules: which rows come out orange, green or red, what Apply writes, and
what it leaves alone. It stubs the Revit API and replaces only the geometry
call, so everything from "which wall won" onwards is the real code.

    python bench_logic.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# a Revit API just real enough for the rules
# ---------------------------------------------------------------------------

def _module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def _install_stubs():
    clr = _module("clr")
    clr.AddReference = lambda name: None

    for name in (
        "System", "System.Collections", "System.Collections.Generic",
        "Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB",
    ):
        _module(name)

    class StorageType(object):
        String = "String"
        Integer = "Integer"
        Double = "Double"
        ElementId = "ElementId"

    db = sys.modules["Autodesk.Revit.DB"]
    db.StorageType = StorageType
    for name in (
        "BooleanOperationsType", "BooleanOperationsUtils",
        "BoundingBoxIntersectsFilter", "BuiltInCategory", "BuiltInParameter",
        "CurveLoop", "ElementId", "ElementIntersectsSolidFilter",
        "ElementMulticategoryFilter", "FilteredElementCollector",
        "GeometryCreationUtilities", "GeometryInstance", "Line", "Options",
        "Outline", "RevitLinkInstance", "Solid", "SolidUtils", "Transform",
        "ViewDetailLevel", "WorksharingUtils", "XYZ",
    ):
        setattr(db, name, type(str(name), (object,), {}))

    class _Generic(object):
        def __getitem__(self, item):
            return list

    sys.modules["System.Collections.Generic"].List = _Generic()


_install_stubs()
sys.path.insert(0, HERE)

import fdwt_core as core  # noqa: E402


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeParam(object):
    def __init__(self, name, value=None, storage="String", read_only=False):
        self.name = name
        self.value = value
        self.StorageType = storage
        self.IsReadOnly = read_only

    @property
    def HasValue(self):
        return self.value not in (None, "")

    def AsString(self):
        return self.value

    def AsValueString(self):
        return self.value

    def AsInteger(self):
        return int(self.value or 0)

    def AsDouble(self):
        return float(self.value or 0)

    def Set(self, value):
        self.value = value
        return True

    def SetValueString(self, value):
        self.value = value
        return True


class FakeId(object):
    def __init__(self, value):
        self.Value = value


class FakeElement(object):
    def __init__(self, eid, params=None, name="", type_element=None, level="L00"):
        self.Id = FakeId(eid)
        self._params = params or {}
        self.Name = name
        self._type = type_element
        self.LevelId = FakeId(1)
        self.level_name = level

    # the API surface fdwt_core actually touches
    def GetParameters(self, name):
        raise Exception("GetParameters is not available on this stub")

    def LookupParameter(self, name):
        return self._params.get(name)

    def GetTypeId(self):
        return FakeId(999)

    @property
    def Parameters(self):
        return list(self._params.values())


class FakeDoc(object):
    def __init__(self, type_element=None, level_name="L00"):
        self.type_element = type_element
        self.level_name = level_name

    def GetElement(self, element_id):
        if getattr(element_id, "Value", 0) == 1:
            return FakeElement(1, name=self.level_name)
        return self.type_element


def accessory(eid, type_value=None, fire_value=None, missing=None):
    params = {
        "Mark": FakeParam("Mark", "FD-{0}".format(eid)),
    }
    missing = missing or []
    if "BGL_Wall Type" not in missing:
        params["BGL_Wall Type"] = FakeParam("BGL_Wall Type", type_value)
    if "BGL_Wall Fire Rating" not in missing:
        params["BGL_Wall Fire Rating"] = FakeParam(
            "BGL_Wall Fire Rating", fire_value
        )
    symbol = FakeElement(500, name="FD - Rectangular")
    symbol.Family = FakeElement(400, name="BGL_Fire Damper")
    return FakeElement(eid, params, name="FD", type_element=symbol), symbol


def host(type_name, rating, kind="Walls", eid=800):
    host_type = FakeElement(
        900,
        {"POP_PERF_FireRatingTarget": FakeParam("POP_PERF_FireRatingTarget", rating)},
        name=type_name,
    )
    element = FakeElement(eid, {}, name=kind, type_element=host_type)
    element.Category = FakeElement(0, name=kind)
    return element, host_type


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

RESULTS = []


def check(label, got, expected):
    ok = got == expected
    RESULTS.append((ok, label, got, expected))
    print("  {0} {1}{2}".format(
        "ok  " if ok else "FAIL",
        label,
        "" if ok else "   got {0!r}, expected {1!r}".format(got, expected),
    ))


def run(hits_by_id, accessories, doc, host_doc, only_rated=False,
        tgt_type="BGL_Wall Type", tgt_fire="BGL_Wall Fire Rating"):
    """build_rows with the geometry replaced, everything else real."""
    original = core.find_hosts_for

    def fake(accessory_element, _host_doc, _transform, _options,
             _cache=None, _keys=None):
        return hits_by_id.get(core.eid_value(accessory_element.Id), [])

    core.find_hosts_for = fake
    try:
        return core.build_rows(
            doc, accessories, host_doc,
            None,
            core.TYPE_NAME_KEY,
            "POP_PERF_FireRatingTarget",
            tgt_type,
            tgt_fire,
            only_rated=only_rated,
        )
    finally:
        core.find_hosts_for = original


def main():
    print("Bench test - the rules the tool applies\n")

    host_element, host_type = host("BLK 140 FR60", "60 minutes")
    host_doc = FakeDoc(type_element=host_type)

    # 1 - nothing intersecting
    element, symbol = accessory(11)
    doc = FakeDoc(type_element=symbol)
    rows = run({}, [element], doc, host_doc)
    check("nothing intersecting is red", rows[0].status, core.STATUS_REVIEW)
    check("and says so", rows[0].note, "nothing intersecting")

    # 2 - empty targets, wall found
    element, symbol = accessory(12)
    doc = FakeDoc(type_element=symbol)
    rows = run({12: [(host_element, 0.5)]}, [element], doc, host_doc)
    check("empty targets are orange", rows[0].status, core.STATUS_CHANGE)
    check("1st value is the wall type name", rows[0].new_type_value, "BLK 140 FR60")
    check("2nd value is the fire rating", rows[0].new_fire_value, "60 minutes")

    # 3 - already correct
    element, symbol = accessory(13, "BLK 140 FR60", "60 minutes")
    doc = FakeDoc(type_element=symbol)
    rows = run({13: [(host_element, 0.5)]}, [element], doc, host_doc)
    check("matching values are green", rows[0].status, core.STATUS_SAME)

    # 4 - target parameter not on the family
    element, symbol = accessory(14, missing=["BGL_Wall Fire Rating"])
    doc = FakeDoc(type_element=symbol)
    rows = run({14: [(host_element, 0.5)]}, [element], doc, host_doc)
    check("a missing target parameter is red", rows[0].status, core.STATUS_REVIEW)
    check("naming the parameter", rows[0].note, "no parameter: BGL_Wall Fire Rating")

    # 5 - unrated wall, with and without the filter
    plain_wall, plain_type = host("BLK 100", None)
    plain_doc = FakeDoc(type_element=plain_type)
    element, symbol = accessory(15)
    doc = FakeDoc(type_element=symbol)
    rows = run({15: [(plain_wall, 0.5)]}, [element], doc, plain_doc, only_rated=True)
    check("only fire rated walls skips an unrated one", rows[0].status,
          core.STATUS_REVIEW)

    element, symbol = accessory(16)
    doc = FakeDoc(type_element=symbol)
    rows = run({16: [(plain_wall, 0.5)]}, [element], doc, plain_doc)
    check("without the filter it still pushes the type", rows[0].status,
          core.STATUS_CHANGE)
    check("and says the rating is missing", rows[0].note,
          "no fire rating on the walls")

    # 6 - two walls, deepest overlap wins
    other_wall, other_type = host("STUD 70", "30 minutes")
    element, symbol = accessory(17)
    doc = FakeDoc(type_element=symbol)
    rows = run(
        {17: [(host_element, 0.9), (other_wall, 0.2)]}, [element], doc, host_doc
    )
    check("two hosts hit is flagged", rows[0].note, "2 hosts hit, deepest used")
    check("deepest overlap wins", rows[0].new_type_value, "BLK 140 FR60")

    # 7 - apply writes, and respects overwrite
    element, symbol = accessory(18)
    doc = FakeDoc(type_element=symbol)
    rows = run({18: [(host_element, 0.5)]}, [element], doc, host_doc)
    core.apply_row(rows[0], "BGL_Wall Type", "BGL_Wall Fire Rating", overwrite=True)
    check("apply writes the wall type",
          element.LookupParameter("BGL_Wall Type").value, "BLK 140 FR60")
    check("apply writes the fire rating",
          element.LookupParameter("BGL_Wall Fire Rating").value, "60 minutes")
    check("and the row goes green", rows[0].status, core.STATUS_DONE)

    element, symbol = accessory(19, "SOMETHING ELSE", "OLD")
    doc = FakeDoc(type_element=symbol)
    rows = run({19: [(host_element, 0.5)]}, [element], doc, host_doc)
    core.apply_row(rows[0], "BGL_Wall Type", "BGL_Wall Fire Rating", overwrite=False)
    check("overwrite off leaves an existing value alone",
          element.LookupParameter("BGL_Wall Type").value, "SOMETHING ELSE")

    element, symbol = accessory(20, "SOMETHING ELSE", "OLD")
    doc = FakeDoc(type_element=symbol)
    rows = run({20: [(host_element, 0.5)]}, [element], doc, host_doc)
    core.apply_row(rows[0], "BGL_Wall Type", "BGL_Wall Fire Rating", overwrite=True)
    check("overwrite on replaces it",
          element.LookupParameter("BGL_Wall Type").value, "BLK 140 FR60")

    # 8 - a read only target is refused, not silently skipped
    element, symbol = accessory(21)
    element.LookupParameter("BGL_Wall Type").IsReadOnly = True
    doc = FakeDoc(type_element=symbol)
    rows = run({21: [(host_element, 0.5)]}, [element], doc, host_doc)
    core.apply_row(rows[0], "BGL_Wall Type", "BGL_Wall Fire Rating", overwrite=True)
    check("a read only target is reported", rows[0].status, core.STATUS_FAILED)
    check("with the reason on the row",
          "read only" in rows[0].note, True)

    # 9 - a write that silently does not take is caught by the read back
    class DeafParam(FakeParam):
        def Set(self, value):
            return True  # says yes, changes nothing - exactly what Revit does

    element, symbol = accessory(22)
    element._params["BGL_Wall Type"] = DeafParam("BGL_Wall Type", None)
    doc = FakeDoc(type_element=symbol)
    rows = run({22: [(host_element, 0.5)]}, [element], doc, host_doc)
    core.apply_row(rows[0], "BGL_Wall Type", "BGL_Wall Fire Rating", overwrite=True)
    check("a write that does not take is caught", rows[0].status, core.STATUS_FAILED)
    check("and the row says what it read back",
          "reads back" in rows[0].note, True)

    # 10 - a read only duplicate does not stop the writable one
    class TwoRoutes(FakeElement):
        def GetParameters(self, name):
            if name == "BGL_Wall Type":
                return [FakeParam("BGL_Wall Type", None, read_only=True),
                        self._params["BGL_Wall Type"]]
            return []

    element, symbol = accessory(23)
    twin = TwoRoutes(23, element._params, type_element=symbol)
    ok, message = core.write_value(twin, "BGL_Wall Type", "BLK 140 FR60")
    check("a read only duplicate is stepped over", ok, True)
    check("and the writable one took it",
          element._params["BGL_Wall Type"].value, "BLK 140 FR60")

    # 11 - values_match tolerates Revit's own number formatting
    check("60 matches 60.0", core.values_match("60", "60.0"), True)
    check("60 does not match 90", core.values_match("60", "90"), False)

    # 12 - settings round trip, unknown keys ignored
    values = core.load_settings()
    check("fire rating target defaults to BGL_Wall Fire Rating",
          values["tgt_fire_param"], "BGL_Wall Fire Rating")
    check("fire rating source defaults to POP_PERF_FireRatingTarget",
          values["src_fire_param"], "POP_PERF_FireRatingTarget")
    check("wall type source defaults to Family type name",
          values["src_type_param"], core.TYPE_NAME_KEY)

    # 10 - a floor is a host too, and hands over the same two values
    floor_element, floor_type = host("SLAB 200 FR120", "120 minutes",
                                     kind="Floors", eid=850)
    floor_doc = FakeDoc(type_element=floor_type)
    element, symbol = accessory(23)
    doc = FakeDoc(type_element=symbol)
    rows = run({23: [(floor_element, 0.5)]}, [element], doc, floor_doc)
    check("a floor is picked up as a host", rows[0].status, core.STATUS_CHANGE)
    check("the floor type name comes across", rows[0].new_type_value,
          "SLAB 200 FR120")
    check("the floor fire rating comes across", rows[0].new_fire_value,
          "120 minutes")
    check("the row says which kind of host it was", rows[0].host_kind, "Floors")

    # 11 - a wall and a floor both hit: the deeper one still wins
    element, symbol = accessory(24)
    doc = FakeDoc(type_element=symbol)
    rows = run(
        {24: [(floor_element, 0.8), (host_element, 0.3)]},
        [element], doc, floor_doc,
    )
    check("wall and floor both hit is flagged", rows[0].note,
          "2 hosts hit, deepest used")
    check("and the deeper host wins", rows[0].new_type_value, "SLAB 200 FR120")

    # 12 - host categories are cleaned up rather than left empty
    check("no categories falls back to walls", core.host_categories([]),
          ["walls"])
    check("a category that is not a host is dropped",
          core.host_categories(["walls", "roofs"]), ["walls"])
    check("both are kept, in the order given",
          core.host_categories(["floors", "walls"]), ["floors", "walls"])

    failed = len([1 for ok, _l, _g, _e in RESULTS if not ok])
    print("")
    if failed:
        print("{0} of {1} checks failed.".format(failed, len(RESULTS)))
        return 1
    print("All {0} checks passed.".format(len(RESULTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
