# -*- coding: utf-8 -*-
"""Bench test of the rules in msm_core, run under plain CPython:

    python bench_logic.py            every check
    python bench_logic.py --selftest put a known bug back into each rule and
                                     confirm the checks catch it

Nothing here is shipped to Revit's engine - pyRevit never imports it.
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402

bench_stubs.build()
import msm_core as core  # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def rec(eid, system, stype, ptype, size, length=10.0, cls=u"Domestic Cold Water"):
    return {u"id": eid, u"system": system, u"system_type": stype,
            u"classification": cls, u"group_param": u"", u"ptype": ptype,
            u"size_mm": size, u"length_ft": length}


RECORDS = [
    rec(1, u"CWS 1", u"Cold Water", u"Copper", 22.0),
    rec(2, u"CWS 1", u"Cold Water", u"Copper", 22.0),
    rec(3, u"CWS 1", u"Cold Water", u"Copper", 15.0),
    rec(4, u"CWS 10", u"Cold Water", u"MLCP", 28.0),
    rec(5, u"CWS 2", u"Cold Water", u"Copper", 22.0),
    rec(6, u"HWS 1", u"Hot Water", u"Copper", 22.0, cls=u"Domestic Hot Water"),
    rec(7, u"", u"", u"Copper", 54.0, cls=u""),
]


# ============================================================
# text helpers
# ============================================================

@check
def natural_order():
    names = [u"P-10", u"P-9", u"P-100", u"p-2"]
    got = sorted(names, key=core.natural_key)
    assert got == [u"p-2", u"P-9", u"P-10", u"P-100"], got


@check
def natural_key_mixed_never_compares_str_with_int():
    sorted([u"10", u"A", u"", u"2B", None], key=core.natural_key)


@check
def size_text():
    assert core.format_size(15.0) == u"15"
    assert core.format_size(12.5) == u"12.5"
    assert core.format_size(21.9999) == u"22"
    assert core.format_size(None) == u""


@check
def feet_and_mm_round_trip():
    assert abs(core.feet_to_mm(core.mm_to_feet(54.0)) - 54.0) < 1e-9
    assert abs(core.feet_to_m(1.0) - 0.3048) < 1e-9


# ============================================================
# grouping
# ============================================================

@check
def grouped_by_service_type_with_unassigned_last():
    groups = core.build_groups(RECORDS)
    assert set(groups) == {u"Cold Water", u"Hot Water", core.UNASSIGNED}, groups.keys()
    assert core.group_order(list(groups))[-1] == core.UNASSIGNED


@check
def grouped_by_classification():
    groups = core.build_groups(RECORDS, group_by=u"classification")
    assert u"Domestic Hot Water" in groups and u"Domestic Cold Water" in groups


@check
def full_split_counts():
    rows = core.build_groups(RECORDS)[u"Cold Water"]
    by = dict(((r[u"system"], r[u"ptype"], r[u"size"]), r[u"count"]) for r in rows)
    assert by[(u"CWS 1", u"Copper", u"22")] == 2, by
    assert by[(u"CWS 1", u"Copper", u"15")] == 1, by
    assert len(rows) == 4, rows


@check
def unticking_size_merges_and_recounts():
    rows = core.build_groups(RECORDS, split_size=False)[u"Cold Water"]
    by = dict((r[u"system"], r) for r in rows)
    assert by[u"CWS 1"][u"count"] == 3
    assert by[u"CWS 1"][u"size"] == u"15-22", by[u"CWS 1"][u"size"]


@check
def unticking_everything_leaves_one_row_per_group():
    rows = core.build_groups(RECORDS, split_system=False, split_type=False,
                             split_size=False)[u"Cold Water"]
    assert len(rows) == 1
    assert rows[0][u"count"] == 5
    assert rows[0][u"system"] == u"3 systems", rows[0][u"system"]
    assert rows[0][u"ptype"] == u"2 types"
    assert sorted(rows[0][u"ids"]) == [1, 2, 3, 4, 5]


@check
def length_summed_in_metres():
    rows = core.build_groups(RECORDS, split_system=False, split_type=False,
                             split_size=False)[u"Hot Water"]
    assert rows[0][u"length"] == u"3.0", rows[0][u"length"]


@check
def rows_open_in_natural_system_order():
    rows = core.build_groups(RECORDS, split_type=False, split_size=False)[u"Cold Water"]
    assert [r[u"system"] for r in rows] == [u"CWS 1", u"CWS 2", u"CWS 10"]


# ============================================================
# sorting
# ============================================================

def _rows():
    return core.build_groups(RECORDS)[u"Cold Water"]


@check
def size_sorts_as_a_number():
    rows = core.sort_rows(_rows(), [(u"size", False)])
    assert [r[u"size"] for r in rows] == [u"15", u"22", u"22", u"28"]


@check
def count_descending():
    rows = core.sort_rows(_rows(), [(u"count", True)])
    assert rows[0][u"count"] == 2


@check
def multi_level_each_with_its_own_direction():
    rows = core.sort_rows(_rows(), [(u"ptype", False), (u"size", True)])
    got = [(r[u"ptype"], r[u"size"]) for r in rows]
    assert got == [(u"Copper", u"22"), (u"Copper", u"22"), (u"Copper", u"15"),
                   (u"MLCP", u"28")], got


@check
def click_starts_again_shift_click_adds():
    stack = core.toggle_sort([], u"size", False)
    assert stack == [(u"size", False)]
    stack = core.toggle_sort(stack, u"size", False)
    assert stack == [(u"size", True)]
    stack = core.toggle_sort(stack, u"ptype", True)
    assert stack == [(u"size", True), (u"ptype", False)]
    stack = core.toggle_sort(stack, u"ptype", True)
    assert stack == [(u"size", True), (u"ptype", True)], stack
    stack = core.toggle_sort(stack, u"count", False)
    assert stack == [(u"count", False)]


@check
def sort_levels_capped():
    stack = []
    for field in (u"a", u"b", u"c", u"d", u"e", u"f", u"g"):
        stack = core.toggle_sort(stack, field, True)
    assert len(stack) == 6


# ============================================================
# filtering
# ============================================================

@check
def every_keyword_must_match():
    assert core.keyword_match(u"CWS 1 Copper", u"cws copper")
    assert not core.keyword_match(u"CWS 1 Copper", u"cws mlcp")
    assert core.keyword_match(u"anything", u"   ")


@check
def column_keyword_filters():
    rows = core.filter_rows(_rows(), col_keywords={u"ptype": u"mlcp"})
    assert [r[u"system"] for r in rows] == [u"CWS 10"]


@check
def ticks_everything_means_no_filter_nothing_means_nothing():
    values = [u"Copper", u"MLCP"]
    assert core.ticks_to_filter(values, values) is None
    assert core.ticks_to_filter(values, []) == set()
    assert core.filter_rows(_rows(), col_ticks={u"ptype": set()}) == []
    assert len(core.filter_rows(_rows(), col_ticks={u"ptype": None})) == 4


@check
def tick_list_shows_what_the_other_filters_allow():
    ticks = {u"ptype": {u"Copper"}}
    # the Pipe Type list still offers MLCP so it can be ticked back on
    assert core.tick_values(_rows(), u"ptype", col_ticks=ticks) == [u"Copper", u"MLCP"]
    # the System list only offers the Copper systems
    assert core.tick_values(_rows(), u"system", col_ticks=ticks) == [u"CWS 1", u"CWS 2"]


@check
def search_box_reaches_the_group_name():
    rows = core.build_groups(RECORDS)[u"Hot Water"]
    assert core.filter_rows(rows, global_text=u"hot") == rows


@check
def selected_ids_deduplicate_in_order():
    rows = [{u"ids": [3, 1]}, {u"ids": [1, 2]}]
    assert core.selected_ids(rows) == [3, 1, 2]


# ============================================================
# checks and pipe type standards
# ============================================================

ALL_CHECKS = set([n for n, _l in core.CHECKS])


def _health_records():
    base = [dict(r) for r in RECORDS[:5]]
    for r in base:
        r.update({u"system_id": 100, u"open_ends": 0, u"mismatch": 0, u"size_ok": True,
                  u"fittings": [900 + r[u"id"]]})
    base[1][u"fittings"] = [901]            # shares pipe 1's fitting
    base[2][u"open_ends"] = 2
    base[4][u"ptype"] = u"PVC"               # CWS 2 on a type not allowed
    base[0][u"size_ok"] = False
    return base


@check
def standards_round_trip():
    std = {u"Cold Water": [u"MLCP", u"Copper"], u"Hot Water": [u"Copper"], u"Gas": []}
    text = core.encode_standards(std)
    assert text == u"Cold Water>>Copper|MLCP;;Hot Water>>Copper", text
    assert core.decode_standards(text) == {u"Cold Water": [u"Copper", u"MLCP"],
                                           u"Hot Water": [u"Copper"]}
    # separators inside a name cannot break the line
    odd = core.decode_standards(core.encode_standards({u"A>>B": [u"x|y"]}))
    assert odd == {u"A B": [u"x y"]}, odd
    assert core.decode_standards(u"garbage;;>>x;;Svc>>") == {}
    # it survives the settings file, = signs and all
    values = core.DomainView(dict(core.DEFAULTS), u"pipe")
    values[u"standards"] = u"A=B>>T=1"
    back = core.DomainView(core.parse_settings(core.format_settings(values)), u"pipe")
    assert back[u"standards"] == u"A=B>>T=1"


@check
def each_check_flags_only_when_switched_on():
    record = {u"ptype": u"PVC", u"size_ok": False, u"open_ends": 1, u"mismatch": 2,
              u"system_id": 0}
    std = {u"Cold Water": [u"Copper"]}
    got = core.record_issues(record, u"Cold Water", std, ALL_CHECKS)
    assert got == {u"standards": 1, u"sizes": 1, u"open_ends": 1, u"mismatch": 2,
                   u"no_system": 1}, got
    assert core.record_issues(record, u"Cold Water", std, set()) == {}
    assert core.record_issues(record, u"Cold Water", std, {u"sizes"}) == {u"sizes": 1}
    # no standard for the service: never 'not allowed'
    assert u"standards" not in core.record_issues(record, u"Gas", std, ALL_CHECKS)
    # a size that could not be read is not a failure
    record[u"size_ok"] = None
    assert u"sizes" not in core.record_issues(record, u"Cold Water", std, ALL_CHECKS)


@check
def rows_add_up_their_pipes_issues():
    std = {u"Cold Water": [u"Copper", u"MLCP"]}
    rows = core.build_groups(_health_records(), split_size=False, standards=std,
                             checks=ALL_CHECKS)[u"Cold Water"]
    by = dict((r[u"system"] + u"/" + r[u"ptype"], r) for r in rows)
    cws1 = by[u"CWS 1/Copper"]
    assert cws1[u"issues"] == {u"sizes": 1, u"open_ends": 2}, cws1[u"issues"]
    assert cws1[u"flag"] and cws1[u"issue_count"] == 3
    assert cws1[u"check"] == u"Size not in routing \u00b7 Open end \u00d72", cws1[u"check"]
    assert cws1[u"fittings"] == 2                 # 901 shared, 903 - counted once
    assert by[u"CWS 2/PVC"][u"check"] == u"Type not allowed"
    assert not by[u"CWS 10/MLCP"][u"flag"] and by[u"CWS 10/MLCP"][u"check"] == u""


@check
def the_switch_turns_every_check_off_and_keeps_the_ticks():
    settings = core.DomainView(dict(core.DEFAULTS), u"pipe")
    settings[u"check_sizes"] = u"0"
    assert core.enabled_checks(settings) == ALL_CHECKS - {u"sizes"}
    settings[u"checks_on"] = u"0"
    assert core.enabled_checks(settings) == set()
    assert settings[u"check_standards"] == u"1"          # the ticks are untouched
    settings[u"checks_on"] = u"1"
    assert core.enabled_checks(settings) == ALL_CHECKS - {u"sizes"}
    settings[u"checks_on"] = u"0"
    rows = core.build_groups(_health_records(), standards={u"Cold Water": [u"Copper"]},
                             checks=core.enabled_checks(settings))[u"Cold Water"]
    assert not [r for r in rows if r[u"flag"] or r[u"check"]]


@check
def no_checks_means_nothing_flagged():
    rows = core.build_groups(_health_records())[u"Cold Water"]
    assert not [r for r in rows if r[u"flag"]]


@check
def issues_only_and_sorting_by_checks():
    rows = core.build_groups(_health_records(),
                             standards={u"Cold Water": [u"Copper", u"MLCP"]},
                             checks=ALL_CHECKS)[u"Cold Water"]
    clean = [r for r in rows if not r[u"flag"]]
    assert clean, u"the case needs a row that passes, or hiding it proves nothing"
    flagged = core.only_flagged(rows, True)
    assert flagged and all([r[u"flag"] for r in flagged])
    assert len(flagged) == len(rows) - len(clean)
    assert core.only_flagged(rows, False) == rows
    worst = core.sort_rows(rows, [(u"check", True)])[0]
    assert worst[u"issue_count"] == max([r[u"issue_count"] for r in rows])


@check
def change_type_offers_the_services_first_allowed_type():
    std = {u"Cold Water": [u"MLCP", u"Copper"]}
    rows = [{u"group": u"Cold Water"}, {u"group": u"Cold Water"}]
    assert core.suggest_type(rows, std, [u"Copper", u"MLCP"]) == u"MLCP"
    assert core.suggest_type(rows, std, [u"Copper"]) == u"Copper"
    assert core.suggest_type(rows + [{u"group": u"Hot Water"}], std, [u"MLCP"]) is None
    assert core.suggest_type([{u"group": u"Gas"}], std, [u"MLCP"]) is None


@check
def export_file_name_is_legal():
    assert core.export_filename(u"Job: A/B.rvt") == u"Job A B - Pipe systems.xlsx"
    assert core.export_filename(u"") == u"Project - Pipe systems.xlsx"
    assert core.size_number(u"22") == 22.0 and core.size_number(u"15-54") is None


# ------------ the per-pipe health read, against a fake Revit ------------

class _Conn(object):
    def __init__(self, kind, connected, system=None):
        self.ConnectorType = kind
        self.IsConnected = connected
        self.MEPSystem = system


class _Sys(object):
    def __init__(self, number):
        self.Id = _Id(number)


class _Size(object):
    def __init__(self, feet):
        self.NominalDiameter = feet


class _Segment(object):
    def __init__(self, sizes_mm):
        self.sizes = [_Size(core.mm_to_feet(m)) for m in sizes_mm]

    def GetSizes(self):
        return self.sizes


class _Rule(object):
    def __init__(self, part):
        self.MEPPartId = _Id(part)


class _Manager(object):
    def __init__(self, parts):
        self.parts = parts

    def GetNumberOfRules(self, group):
        return len(self.parts)

    def GetRule(self, group, index):
        return _Rule(self.parts[index])


_MODEL_PATCH = None


def _load_model():
    for name in (u"msm_model", u"msm_clr"):
        sys.modules.pop(name, None)
    bench_stubs.build()
    sys.modules[u"msm_core"] = core
    if _MODEL_PATCH:
        import types
        source = open(os.path.join(HERE, u"msm_model.py")).read()
        before, after = _MODEL_PATCH
        if before not in source:
            raise AssertionError(u"selftest anchor missing in msm_model.py: " + before)
        m = types.ModuleType(u"msm_model")
        m.__file__ = os.path.join(HERE, u"msm_model.py")
        sys.modules[u"msm_model"] = m
        exec(compile(source.replace(before, after, 1), m.__file__, u"exec"), m.__dict__)
    else:
        import msm_model as m
    m.eid_value = lambda i: i.Value if i is not None else 0
    return m


@check
def health_read_of_a_pipe():
    m = _load_model()
    ptype = _Element(50, {})
    ptype.RoutingPreferenceManager = _Manager([60])
    doc = _Doc()
    doc.add(ptype)
    segment = _Element(60, {})
    segment.GetSizes = _Segment([15, 22, 28]).GetSizes
    doc.add(segment)
    pipe = _Element(1, {})
    pipe.Diameter = core.mm_to_feet(22.0)
    pipe.GetTypeId = lambda: _Id(50)
    same = _Element(5, {}, None, u"fitting")
    other = _Element(6, {}, None, u"fitting")
    equipment = _Element(7, {}, None, u"equipment")
    conns = {1: [_Conn(u"End", True), _Conn(u"End", False), _Conn(u"Curve", False)],
             5: [_Conn(u"End", True, _Sys(100))],
             6: [_Conn(u"End", True, _Sys(200))],
             7: [_Conn(u"End", True, _Sys(200))]}
    m.connectors_of = lambda e: conns.get(e.Id.Value, [])
    m.neighbours = lambda e: [same, other, equipment] if e is pipe else []
    m.is_fitting_or_accessory = lambda e: e.kind in (u"fitting", u"accessory")
    health = m.Health(doc)
    record = {u"system_id": 100}
    health.read(pipe, record)
    assert record[u"open_ends"] == 1, record          # the curve tap is not an end
    assert record[u"mismatch"] == 1, record           # fitting 6 on system 200
    assert sorted(record[u"fittings"]) == [5, 6]      # equipment is not a fitting
    assert record[u"size_ok"] is True
    pipe.Diameter = core.mm_to_feet(22.3)             # inside the 0.5mm tolerance
    assert health.size_ok(pipe) is True
    pipe.Diameter = core.mm_to_feet(35.0)
    assert health.size_ok(pipe) is False
    ptype.RoutingPreferenceManager = None             # unreadable: cached as unknown
    health2 = m.Health(doc)
    assert health2.size_ok(pipe) is None


# ============================================================
# three disciplines: pipe, duct, containment
# ============================================================

@check
def a_tab_reads_and_writes_its_own_settings():
    base = dict(core.DEFAULTS)
    pipe = core.DomainView(base, u"pipe")
    duct = core.DomainView(base, u"duct")
    pipe[u"retain"] = u"Comments"
    duct[u"retain"] = u"Mark"
    assert base[u"pipe.retain"] == u"Comments" and base[u"duct.retain"] == u"Mark"
    assert pipe.get(u"retain") == u"Comments" and duct.get(u"retain") == u"Mark"
    pipe[u"theme"] = u"light"                            # shared: one value for all tabs
    assert duct.get(u"theme") == u"light" and u"pipe.theme" not in base
    copy = pipe.copy()
    copy[u"retain"] = u"X"
    assert pipe.get(u"retain") == u"Comments"            # a dialog's copy is its own
    flat = duct.resolved()
    assert flat[u"retain"] == u"Mark" and flat[u"theme"] == u"light"
    assert flat[u"domain"] == u"duct"
    back = core.parse_settings(core.format_settings(duct))
    assert back[u"duct.retain"] == u"Mark" and back[u"pipe.retain"] == u"Comments"


@check
def pipe_system_manager_settings_carry_over():
    folder = tempfile.mkdtemp()
    legacy = os.path.join(folder, core.LEGACY_SETTINGS_NAME)
    with open(legacy, u"w") as handle:
        handle.write(u"theme=light\nretain=A|B\nstandards=CWS>>Copper\ncheck_sizes=0\n")
    got = core.load_settings(os.path.join(folder, u"missing.txt"), legacy)
    assert got[u"theme"] == u"light"
    assert got[u"pipe.retain"] == u"A|B" and got[u"pipe.standards"] == u"CWS>>Copper"
    assert got[u"pipe.check_sizes"] == u"0"
    assert got[u"duct.retain"] == core.DEFAULTS[u"duct.retain"]
    # an existing new file wins over the old one
    fresh = os.path.join(folder, u"new.txt")
    core.save_settings(dict(core.DEFAULTS), fresh)
    assert core.load_settings(fresh, legacy)[u"pipe.retain"] == core.DEFAULTS[u"pipe.retain"]


@check
def containment_has_its_own_words_and_checks():
    view = core.DomainView(dict(core.DEFAULTS), u"cont")
    assert u"sizes" not in core.enabled_checks(view, u"cont")          # ticked, but meaningless
    assert u"sizes" in core.enabled_checks(core.DomainView(view.base, u"pipe"), u"pipe")
    titles = core.field_titles(u"cont")
    assert titles[u"system"] == u"Run" and titles[u"ptype"] == u"Type"
    assert core.field_titles(u"duct")[u"ptype"] == u"Duct Type"
    assert core.check_text({u"no_system": 2, u"mismatch": 1}, core.check_labels(u"cont")) == \
        u"Fitting on another service \u00b7 No service type \u00d72"
    assert [k for k, _l in core.domain_info(u"cont")[u"group_options"]] == \
        [u"system_type", u"param"]
    assert core.noun(u"cont", 1) == u"tray or conduit" and core.noun(u"duct", 3) == u"ducts"
    assert core.export_filename(u"Job", u"Containment") == u"Job - Containment.xlsx"
    text = core.change_summary(4, [u"Run 7"], [u"Cable Tray: A"], u"Cable Tray: B", [],
                               True, True, 2, u"cont")
    assert u"Change 4 trays and conduits" in text and u"Runs: Run 7" in text
    assert u"fitting slot" in text and u"Keep each tray or conduit's size" in text


@check
def containment_no_service_type_is_flagged():
    record = {u"ptype": u"T", u"system_id": 0, u"has_system": True}
    assert u"no_system" not in core.record_issues(record, u"LV", {}, {u"no_system"})
    record[u"has_system"] = False
    assert core.record_issues(record, u"LV", {}, {u"no_system"}) == {u"no_system": 1}
    # pipes and ducts still go by their system id
    assert core.record_issues({u"system_id": 5}, u"X", {}, {u"no_system"}) == {}


def _duct(eid, system, size_text, size_num, ptype=u"Galv"):
    return {u"id": eid, u"system": system, u"system_type": u"Supply Air", u"ptype": ptype,
            u"size_text": size_text, u"size_num": size_num, u"length_ft": 3.28084}


@check
def rectangular_and_round_sizes_group_and_sort_by_area():
    records = [_duct(1, u"SA 1", u"600x300", 180000.0), _duct(2, u"SA 1", u"300x100", 30000.0),
               _duct(3, u"SA 1", u"\u00d8250", 49087.0), _duct(4, u"SA 1", u"600x300", 180000.0)]
    rows = core.build_groups(records)[u"Supply Air"]
    by = dict((r[u"size"], r) for r in rows)
    assert by[u"600x300"][u"count"] == 2
    ordered = [r[u"size"] for r in core.sort_rows(rows, [(u"size", False)])]
    assert ordered == [u"300x100", u"\u00d8250", u"600x300"], ordered
    merged = core.build_groups(records, split_size=False)[u"Supply Air"][0]
    assert merged[u"size"] == u"300x100-600x300", merged[u"size"]
    assert core.rect_size_text(600.0, 300.0) == u"600x300"
    assert core.round_size_text(250.0) == u"\u00d8250"


@check
def a_size_is_the_same_only_with_the_same_parameters():
    feet = core.mm_to_feet
    assert core.sizes_equal({u"W": feet(600)}, {u"W": feet(600) + 1e-9})
    assert not core.sizes_equal({u"W": feet(600)}, {u"W": feet(500)})
    assert not core.sizes_equal({u"D": feet(250)}, {u"W": feet(250), u"H": feet(250)})
    assert core.sizes_equal({}, {})


# ------------ model and ops for ducts and containment, against a fake Revit ------------

class _Bag(object):
    pass


def _eid_param(name, value, storage):
    p = _Bag()
    p.Definition = _Bag()
    p.Definition.Name = name
    p.StorageType = storage
    p.AsElementId = lambda: _Id(value)
    return p


@check
def containment_fittings_follow_their_slot():
    m = _load_model()
    fitting_cat = int(m.bic(u"OST_CableTrayFitting"))
    other_cat = int(m.bic(u"OST_Doors"))

    class _Symbol(m.FamilySymbol):
        pass

    doc = _Doc()

    def symbol(number, category):
        sym = _Symbol()
        sym.Id = _Id(number)
        sym.Category = _Bag()
        sym.Category.Id = _Id(category)
        doc.add(sym)
        return sym

    for number in (11, 12, 21, 22):
        symbol(number, fitting_cat)
    symbol(99, other_cat)
    ElementIdStorage = m.StorageType.ElementId
    old_type = _Element(1, {})
    old_type.Document = doc
    old_type.Parameters = [_eid_param(u"Horizontal Bend", 11, ElementIdStorage),
                           _eid_param(u"Tee", 12, ElementIdStorage),
                           _eid_param(u"Material", 99, ElementIdStorage),
                           _eid_param(u"Width", 0, m.StorageType.Double)]
    new_type = _Element(2, {})
    new_type.Document = doc
    new_type.Parameters = [_eid_param(u"Horizontal Bend", 21, ElementIdStorage),
                           _eid_param(u"Tee", 0, ElementIdStorage)]
    doc.add(old_type)
    doc.add(new_type)
    m.eid_value = lambda i: i.Value if i is not None else 0
    slots = m.fitting_slots(old_type)
    assert slots == {u"Horizontal Bend": 11, u"Tee": 12}, slots        # the door is not a slot

    ops = _load_ops()
    ops.model.fitting_slots = m.fitting_slots
    curve = _Element(100, {}, None, u"pipe")
    curve.GetTypeId = lambda: _Id(1)
    doc.add(curve)
    bend = _Element(200, {}, None, u"fitting")
    bend.GetTypeId = lambda: _Id(11)
    tee = _Element(201, {}, None, u"fitting")
    tee.GetTypeId = lambda: _Id(12)
    stray = _Element(202, {}, None, u"fitting")
    stray.GetTypeId = lambda: _Id(55)
    for f in (bend, tee, stray):
        doc.add(f)
        _link(curve, f)
    ops.model.is_curve = lambda e: e.kind == u"pipe"
    plan = ops.slot_parts_for(doc, [200, 201, 202], new_type)
    assert plan[200][0].Value == 21, plan
    assert plan[201][0] is None and u"Tee" in plan[201][1]
    assert plan[202][0] is None and u"old type" in plan[202][1]


def _run_model(pairs):
    """A fake model: trays and fittings with a service each, joined in pairs."""
    m = _load_model()
    m.eid_value = lambda i: i.Value
    made = {}

    def element(number, kind, service):
        e = _Element(number, {}, None, kind)
        e.service = service
        made[number] = e
        return e
    m.neighbours = lambda e: [x for x in e.links]
    m.is_fitting_or_accessory = lambda e: e.kind == u"fitting"
    m.is_curve = lambda e: e.kind in (u"tray", u"conduit")
    m.element_kind = lambda e: e.kind if e.kind in (u"tray", u"conduit") else u""
    m.service_of = lambda e, settings: e.service
    return m, element


@check
def a_containment_run_is_everything_joined_through_fittings():
    m, element = _run_model(None)
    a = element(30, u"tray", u"VRF")
    b = element(10, u"tray", u"VRF")
    c = element(50, u"tray", u"VRF")
    f = element(40, u"fitting", u"VRF")
    _link(a, f)
    _link(f, b)
    labels = m.run_labels(None, [a, b, c], {})
    assert labels == {30: u"Run 10", 10: u"Run 10", 50: u"Run 50"}, labels


@check
def a_run_stops_at_another_service_or_kind():
    m, element = _run_model(None)
    vrf1 = element(1, u"tray", u"VRF")
    vrf2 = element(2, u"tray", u"VRF")
    ict = element(3, u"tray", u"ICT TRAY")
    ict2 = element(4, u"tray", u"ICT TRAY")
    conduit = element(5, u"conduit", u"VRF")
    tee = element(10, u"fitting", u"VRF")          # joins VRF, VRF, ICT and a conduit
    bend = element(11, u"fitting", u"ICT TRAY")     # an ICT fitting on a VRF tray
    for other in (vrf2, ict, conduit):
        _link(tee, other)
    _link(vrf1, tee)
    _link(vrf1, bend)
    _link(bend, ict2)
    curves, fittings = m.walk_run(vrf1, {})
    assert sorted(curves) == [1, 2], curves               # not the ICT trays, not the conduit
    assert sorted(fittings) == [10, 11], fittings         # the boundary fittings are kept
    labels = m.run_labels(None, [vrf1, vrf2, ict, ict2, conduit], {})
    assert labels[1] == labels[2] == u"Run 1"
    assert labels[3] == u"Run 3" and labels[4] == u"Run 4" and labels[5] == u"Run 5", labels
    # a VRF tray reached only through an ICT fitting is not walked into: the
    # wrong-service fitting is the boundary (and the fitting check flags it)
    vrf3 = element(6, u"tray", u"VRF")
    _link(bend, vrf3)
    curves, fittings = m.walk_run(vrf1, {})
    assert 6 not in curves, curves


@check
def duct_and_containment_sizes_are_read_by_kind():
    m = _load_model()
    feet = core.mm_to_feet

    class _P(object):
        def __init__(self, value):
            self.HasValue = value is not None
            self.value = value

        def AsDouble(self):
            return self.value

    def element(kind, values):
        e = _Element(1, {}, None, kind)
        e.get_Parameter = lambda member: _P(values.get(u"{0}".format(member)))
        return e

    m.element_kind = lambda e: e.kind
    rect = element(u"duct", {u"RBS_CURVE_WIDTH_PARAM": feet(600), u"RBS_CURVE_HEIGHT_PARAM": feet(300)})
    text, area = m.size_of(rect)
    assert text == u"600x300" and abs(area - 180000.0) < 1e-6, (text, area)
    round_duct = element(u"duct", {u"RBS_CURVE_DIAMETER_PARAM": feet(250)})
    assert m.size_params(round_duct) == [u"RBS_CURVE_DIAMETER_PARAM"]
    assert m.size_of(round_duct)[0] == u"\u00d8250"
    tray = element(u"tray", {u"RBS_CABLETRAY_WIDTH_PARAM": feet(300),
                             u"RBS_CABLETRAY_HEIGHT_PARAM": feet(100)})
    assert m.size_of(tray)[0] == u"300x100"
    conduit = element(u"conduit", {u"RBS_CONDUIT_DIAMETER_PARAM": feet(25)})
    assert m.size_of(conduit)[0] == u"\u00d825"
    pipe = element(u"pipe", {u"RBS_PIPE_DIAMETER_PARAM": feet(22)})
    assert m.size_of(pipe) == (u"22", 22.0)
    assert m.size_label({u"A": feet(600), u"B": feet(300)}) == u"600x300"


# ============================================================
# isolate: reset the earlier isolate, then isolate the new selection
# ============================================================

class _View(object):
    """A 3D view that remembers what was done to it, in order."""

    def __init__(self, isolated, sticky=False):
        self.Id = _Id(77)
        self.Name = u"{3D - drew}"
        self.isolated = isolated
        self.sticky = sticky            # an isolate that will not come off
        self.calls = []
        self.IsSectionBoxActive = False

    def IsInTemporaryViewMode(self, mode):
        return self.isolated

    def DisableTemporaryViewMode(self, mode):
        if u"{0}".format(mode) == u"RevealHiddenElements":
            self.calls.append(u"reveal off")
            return
        self.calls.append(u"reset")
        if not self.sticky:
            self.isolated = False

    def IsolateElementsTemporary(self, ids):
        self.calls.append(u"isolate")
        self.isolated = True


def _run_isolate(view, view_id=77, previous=0, other=None, visible=None, settings_extra=None):
    ops = _load_ops()
    doc = _Doc()
    doc.add(view)
    if other is not None:
        doc.add(other)
    shown = list(visible or [])
    ops._visible_services = lambda d, v: shown.pop(0) if shown else []
    committed = []
    real_commit = doc.commit

    def commit():
        committed.append(list(view.calls))
        real_commit()
    doc.commit = commit
    ops.model.isolate_ids = lambda d, ids, what, domain, settings: (list(ids), {})
    ops.model.elem_name = lambda e: e.Name
    ops.find_or_make_default_3d = lambda d, app: (view, False)
    ops.elements_bounds = lambda d, ids, margin: None
    ops.make_id = lambda n: _Id(n)
    ops.committed = lambda status: True

    class _UIDoc(object):
        Document = doc
        ActiveView = None
    app = _Bag()
    app.ActiveUIDocument = _UIDoc()
    settings = core.DomainView(dict(core.DEFAULTS), u"pipe").resolved()
    settings[u"isolate_zoom"] = u"0"
    settings[u"isolated_view"] = u"{0}".format(previous) if previous else u""
    settings.update(settings_extra or {})
    result = ops.Result()
    ops.isolate_job([1, 2], view_id, settings)(app, result)
    return result, committed, _Group.last


@check
def a_second_isolate_resets_the_first():
    view = _View(isolated=True)
    result, committed, group = _run_isolate(view)
    assert result.error == u"", result.error
    assert view.calls == [u"reset", u"reveal off", u"isolate"], view.calls
    # the reset was committed on its own before the new isolate was made
    assert committed[0] == [u"reset", u"reveal off"], committed
    assert result.get(u"was_isolated") is True
    assert group.state == u"assimilated"             # one undo step


@check
def the_reset_is_done_even_when_the_view_says_nothing_is_isolated():
    view = _View(isolated=False)
    result, committed, group = _run_isolate(view, view_id=0)      # the default 3D view
    assert view.calls == [u"reset", u"reveal off", u"isolate"], view.calls
    assert result.get(u"was_isolated") is False and result.error == u""


@check
def an_isolate_that_will_not_come_off_is_not_stacked_on():
    view = _View(isolated=True, sticky=True)
    result, committed, group = _run_isolate(view)
    assert u"would not come off" in result.error, result.error
    assert u"isolate" not in view.calls, view.calls
    assert group.state == u"rolled back"


# ============================================================
# containment resize, the red highlight, the debug table
# ============================================================

@check
def size_boxes_read_as_millimetres():
    assert core.parse_mm(u"") == (None, u"")
    assert core.parse_mm(u" 300 ") == (300.0, u"")
    assert core.parse_mm(u"150mm") == (150.0, u"")
    assert core.parse_mm(u"abc")[1] and core.parse_mm(u"abc")[0] is None
    assert core.parse_mm(u"0")[1] and core.parse_mm(u"-5")[1]
    assert u"5m" in core.parse_mm(u"6000")[1]


@check
def a_resize_writes_only_what_changes_for_each_kind():
    T, H, D = core.TRAY_WIDTH, core.TRAY_HEIGHT, core.CONDUIT_DIAMETER
    elements = [{u"id": 1, u"kind": u"tray", u"size": {T: 150.0, H: 50.0}},
                {u"id": 2, u"kind": u"tray", u"size": {T: 300.0, H: 50.0}},
                {u"id": 3, u"kind": u"conduit", u"size": {D: 20.0}},
                {u"id": 4, u"kind": u"conduit", u"size": {D: 25.0}}]
    plan, counts = core.resize_plan(elements, width=300.0, diameter=25.0)
    assert plan == {1: {T: 300.0}, 3: {D: 25.0}}, plan
    assert counts == {u"unchanged": 2, u"no_input": 0}, counts
    plan, counts = core.resize_plan(elements, height=100.0)
    assert sorted(plan) == [1, 2] and counts[u"no_input"] == 2      # conduits: nothing asked


@check
def the_dialog_counts_the_whole_runs_before_anything_is_resized():
    def rec(eid, kind, service, run):
        return {u"id": eid, u"kind": kind, u"system_type": service, u"system": run}
    records = [rec(1, u"tray", u"VRF", u"Run 1"), rec(2, u"tray", u"VRF", u"Run 1"),
               rec(3, u"tray", u"VRF", u"Run 1"), rec(4, u"tray", u"ICT TRAY", u"Run 1"),
               rec(5, u"conduit", u"VRF", u"Run 1"), rec(6, u"tray", u"VRF", u"Run 6")]
    # picking tray 1 takes the rest of its run - not the ICT tray or the conduit
    # that happen to share a label, and not the other run
    assert core.run_members(records, [1]) == [1, 2, 3]
    assert core.run_members(records, [1, 6]) == [1, 2, 3, 6]
    assert core.run_members(records, [1], system_from=u"Mark") is None


@check
def the_resize_confirm_says_what_happens():
    text = core.resize_summary(2, 3, 1, 300.0, None, 25.0, True)
    assert u"Resize 2 runs (whole runs)" in text and u"3 cable trays to 300 x (height as is)" in text
    assert u"1 conduit to \u00d825" in text and u"put back as it was" in text
    assert u"no diameter given" in core.resize_summary(1, 0, 2, 300.0, None, None, False)


@check
def the_highlight_is_remembered_by_view():
    text = core.encode_highlight(77, [5, 6])
    assert text == u"77:5|6"
    assert core.decode_highlight(text) == (77, [5, 6])
    assert core.decode_highlight(u"") == (0, [])
    assert core.decode_highlight(u"x:1|2") == (0, [])
    assert core.decode_highlight(u"9:1|junk|3") == (9, [1, 3])
    assert core.encode_highlight(0, [1]) == u"" and core.encode_highlight(5, []) == u""


@check
def the_debug_table_pastes_as_markdown():
    assert core.md_cell(u"a|b\nc") == u"a\\|b<br>c"
    assert core.md_cell(None) == u""
    assert core.md_cell(u"x" * 1000).endswith(u"(cut)")
    rows = []
    for i in range(core.DEBUG_ROW_LIMIT + 5):
        core.add_debug_row(rows, {u"step": i})
    assert len(rows) == core.DEBUG_ROW_LIMIT and rows[0][u"step"] == 5    # newest kept
    table = core.debug_table([(u"Tool", u"v")], [{u"action": u"resize", u"detail": u"a|b"}])
    lines = table.strip().split(u"\n")
    body = [l for l in lines if l.startswith(u"| 1 |")]
    assert body and body[0].count(u"|") - body[0].count(u"\\|") == 8, body
    assert u"| Tool | v |" in table
    assert u"| - |" in core.debug_table([], [])                     # an empty table still reads


@check
def debug_starts_off_even_where_it_was_saved_on():
    assert core.DEFAULTS[u"debug"] == u"0"
    assert core.parse_settings(u"settings_version=2\ndebug=1\n")[u"debug"] == u"0"
    assert core.parse_settings(u"settings_version=3\ndebug=1\n")[u"debug"] == u"1"
    legacy = core.parse_settings(u"debug=1\nretain=A\n", legacy=True)
    assert legacy[u"debug"] == u"0" and legacy[u"pipe.retain"] == u"A"


class _SizeParam(object):
    def __init__(self, element, name):
        self.element = element
        self.name = name
        self.IsReadOnly = False

    def Set(self, value):
        self.element.sizes[self.name] = value
        return True


class _Failure(object):
    def __init__(self, severity, text, ids):
        self.severity = severity
        self.text = text
        self.ids = ids

    def GetSeverity(self):
        return self.severity

    def GetDescriptionText(self):
        return self.text

    def GetFailingElementIds(self):
        return [_Id(i) for i in self.ids]


class _Accessor(object):
    def __init__(self, failures):
        self.failures = failures
        self.deleted = []

    def GetFailureMessages(self):
        return list(self.failures)

    def DeleteWarning(self, failure):
        self.deleted.append(failure.text)


@check
def revit_errors_roll_a_run_back_and_name_the_elements():
    ops = _load_ops()
    ops.eid_value = lambda i: i.Value
    warn = _Failure(ops.FailureSeverity.Warning, u"slightly off axis", [9])
    error = _Failure(ops.FailureSeverity.Error, u"fitting cannot be sized", [5, 6])
    recorder = ops.FailureRecorder()
    accessor = _Accessor([warn, error])
    answer = recorder.PreprocessFailures(accessor)
    assert answer == ops.FailureProcessingResult.ProceedWithRollBack
    assert accessor.deleted == [u"slightly off axis"]
    assert recorder.errors == [(u"fitting cannot be sized", [5, 6])]
    only_warning = ops.FailureRecorder()
    assert only_warning.PreprocessFailures(_Accessor([warn])) == \
        ops.FailureProcessingResult.Continue


def _run_scene(tight=(), names=True, reverts=()):
    """Trays 1-8 at 100 high, to go to 50. A tray in tight cannot take the new
    size: any attempt holding it is refused, naming it if names is True.
    A tray in reverts takes the new size but is found back at 100 at the end
    (Revit putting it back)."""
    ops = _load_ops()
    heights = dict((n, 100.0) for n in range(1, 9))
    attempts = []

    def fake_try(doc, plan, name, with_fittings=True, stats=None):
        attempts.append(sorted(plan))
        bad = [n for n in plan if n in tight]
        if bad:
            return False, [(u"insufficient space to create the required fittings",
                            bad if names else [99])], [], u""
        for n in plan:
            heights[n] = 50.0
        return True, [], [], u""

    def fake_at_target(doc, number, changes):
        now = {core.TRAY_HEIGHT: 100.0 if number in reverts else heights[number]}
        return abs(now[core.TRAY_HEIGHT] - 50.0) < 0.01, now
    ops._try_resize = fake_try
    ops._at_target = fake_at_target
    ops._fittings_joined = lambda doc, ids: {}
    data = {u"runs_done": 0, u"resized": 0, u"failed_runs": [], u"warnings": [],
            u"not_taken": [], u"_done_all": [], u"partial_runs": [], u"_outcomes": [],
            u"run_detail": [], u"fittings_resized": 0, u"fittings_left": [],
            u"fitting_params": []}
    return ops, data, attempts, heights


def _plan():
    return dict((n, {core.TRAY_HEIGHT: 50.0}) for n in range(1, 9))


@check
def a_run_that_resizes_is_counted_and_proved():
    ops, data, attempts, heights = _run_scene()
    ops._resize_run(None, 1, {u"all": list(range(1, 9)) + [40]}, _plan(), data)
    ops._finish_resize(None, data)
    assert attempts == [list(range(1, 9))], attempts          # one go
    assert data[u"resized"] == 8 and data[u"runs_done"] == 1, data
    assert data[u"failed_runs"] == [] and 40 in data[u"_done_all"]


@check
def one_tight_tray_is_set_aside_and_the_rest_resize_together():
    """The reported case: a run of 8 where Revit refuses one tray. The rest
    are resized together - neighbours stay matched - not one at a time."""
    ops, data, attempts, heights = _run_scene(tight=(5,))
    ops._resize_run(None, 1, {u"all": list(range(1, 9))}, _plan(), data)
    ops._finish_resize(None, data)
    assert attempts == [list(range(1, 9)), [1, 2, 3, 4, 6, 7, 8]], attempts
    assert data[u"resized"] == 7, data
    failed = data[u"failed_runs"]
    assert len(failed) == 1 and failed[0][u"left"] == [5] and failed[0][u"resized"] == 7
    assert 5 in failed[0][u"broken"]
    assert u"2 tries, 7 of 8" in data[u"run_detail"][0], data[u"run_detail"]


@check
def when_revit_names_nothing_the_run_is_halved():
    ops, data, attempts, heights = _run_scene(tight=(5,), names=False)
    ops._resize_run(None, 1, {u"all": list(range(1, 9))}, _plan(), data)
    ops._finish_resize(None, data)
    assert [1, 2, 3, 4] in attempts, attempts                 # a block of neighbours
    assert data[u"resized"] == 7 and data[u"failed_runs"][0][u"left"] == [5], data


@check
def a_tray_revit_puts_back_is_not_counted_as_resized():
    ops, data, attempts, heights = _run_scene(reverts=(3,))
    ops._resize_run(None, 1, {u"all": list(range(1, 9))}, _plan(), data)
    ops._finish_resize(None, data)
    assert data[u"resized"] == 7, data
    assert [x for x in data[u"not_taken"] if x.startswith(u"3 - ") and u"put back" in x]
    assert data[u"failed_runs"][0][u"left"] == [3]


@check
def put_the_whole_run_back_means_nothing_changes():
    ops, data, attempts, heights = _run_scene(tight=(5,))
    ops._resize_run(None, 1, {u"all": list(range(1, 9))}, _plan(), data, u"run")
    ops._finish_resize(None, data)
    assert attempts == [list(range(1, 9))] and data[u"resized"] == 0, attempts
    assert data[u"failed_runs"][0][u"left"] == list(range(1, 9))


def _fitting_scene(tray_sizes, params):
    """A fitting joined to trays of the given sizes ({"width", "height"} in mm),
    with its own parameters [(name, mm)]. Its connector is a trap: setting any
    size on it fails the test - sizing must go through parameters."""
    ops = _load_ops()

    class _P(object):
        def __init__(self, name, mm, read_only=False):
            self.Definition = _Bag()
            self.Definition.Name = name
            self.StorageType = u"Double"
            self.IsReadOnly = read_only
            self.value = core.mm_to_feet(mm)

        def AsDouble(self):
            return self.value

        def Set(self, value):
            self.value = value
            return True

    fitting = _Element(50, {}, None, u"fitting")
    fitting.Parameters = [_P(n, mm) for n, mm in params]
    fitting.LookupParameter = lambda name: [p for p in fitting.Parameters
                                            if p.Definition.Name == name][0]
    trays = []
    for i, size in enumerate(tray_sizes):
        tray = _Element(i + 1, {}, None, u"tray")
        tray.size = size
        trays.append(tray)
        _link(tray, fitting)
    ops.model.neighbours = lambda e: list(e.links)
    ops.model.is_curve = lambda e: e.kind == u"tray"
    ops.model.is_fitting = lambda e: e.kind == u"fitting"
    ops.model.size_state = lambda e: dict(
        [(core.TRAY_WIDTH, core.mm_to_feet(e.size[u"width"])),
         (core.TRAY_HEIGHT, core.mm_to_feet(e.size[u"height"]))])

    def value(name):
        return core.feet_to_mm([p for p in fitting.Parameters
                                if p.Definition.Name == name][0].value)
    return ops, fitting, trays, value


@check
def a_new_height_goes_on_the_fittings_height_parameter():
    """The reported case: trays go from 25 to 50 high; the bend has to end
    up 200 wide and 50 high - not 50 wide."""
    ops, fitting, trays, value = _fitting_scene(
        [{u"width": 200.0, u"height": 50.0}, {u"width": 200.0, u"height": 50.0}],
        [(u"Tray Width", 200.0), (u"Tray Height", 25.0), (u"Bend Radius", 25.0),
         (u"Height Offset", 25.0)])
    stats = {}
    ops._size_fitting(fitting, stats)
    assert value(u"Tray Height") == 50.0 and value(u"Tray Width") == 200.0
    assert value(u"Bend Radius") == 25.0 and value(u"Height Offset") == 25.0
    assert stats == {u"Tray Height": 1}, stats
    targets, todo, missing = ops._fitting_plan(fitting)
    assert not todo and not missing                        # proved at the end


@check
def a_fitting_pinched_by_2_7_0_is_put_back_to_its_trays_width():
    ops, fitting, trays, value = _fitting_scene(
        [{u"width": 200.0, u"height": 50.0}, {u"width": 200.0, u"height": 50.0}],
        [(u"Tray Width", 50.0), (u"Tray Height", 25.0)])
    ops._size_fitting(fitting, {})
    assert value(u"Tray Width") == 200.0 and value(u"Tray Height") == 50.0


@check
def a_reducer_keeps_its_widths():
    ops, fitting, trays, value = _fitting_scene(
        [{u"width": 300.0, u"height": 50.0}, {u"width": 150.0, u"height": 50.0}],
        [(u"Width 1", 300.0), (u"Width 2", 150.0), (u"Height", 25.0)])
    ops._size_fitting(fitting, {})
    assert value(u"Width 1") == 300.0 and value(u"Width 2") == 150.0
    assert value(u"Height") == 50.0


@check
def a_fitting_with_no_height_parameter_is_reported_not_guessed():
    ops, fitting, trays, value = _fitting_scene(
        [{u"width": 200.0, u"height": 50.0}], [(u"Tray Width", 200.0)])
    stats = {}
    ops._size_fitting(fitting, stats)
    assert stats == {u"(no parameter for height)": 1}, stats
    targets, todo, missing = ops._fitting_plan(fitting)
    assert missing == [u"height"]


@check
def size_parameters_are_found_by_name_and_never_offsets():
    params = [(u"Tray Height", 25.0, True), (u"Height Offset", 25.0, True),
              (u"Bend Radius", 25.0, True), (u"Height 2", 25.0, True),
              (u"Tray Width", 200.0, True), (u"Length", 300.0, True),
              (u"Height (read only)", 25.0, False), (u"Depth", 25.0, True)]
    assert core.size_param_names(params, u"height") == [u"Tray Height", u"Height 2", u"Depth"]
    assert core.size_param_names(params, u"width") == [u"Tray Width"]
    assert core.fitting_size_targets([{u"width": 200.0, u"height": 50.0},
                                      {u"width": 100.0, u"height": 50.0}]) == {u"height": 50.0}
    todo, missing = core.fitting_param_plan(params, {u"height": 50.0, u"diameter": 20.0})
    assert todo == [(u"Tray Height", 50.0), (u"Height 2", 50.0), (u"Depth", 50.0)], todo
    assert missing == [u"diameter"]


def _real_resize_scene():
    ops, fitting, trays, value = _fitting_scene(
        [{u"width": 200.0, u"height": 25.0}, {u"width": 200.0, u"height": 25.0}],
        [(u"Tray Width", 200.0), (u"Tray Height", 25.0)])
    doc = _Doc()
    for tray in trays:
        doc.add(tray)

        class _H(object):
            IsReadOnly = False

            def __init__(self, tray):
                self.tray = tray

            def Set(self, v):
                self.tray.size[u"height"] = core.feet_to_mm(v)
                return True
        tray.get_Parameter = lambda member, t=tray: _H(t)
    doc.add(fitting)
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    return ops, doc, value


@check
def the_real_resize_sizes_the_fittings_with_the_trays():
    ops, doc, value = _real_resize_scene()
    plan = {1: {core.TRAY_HEIGHT: 50.0}, 2: {core.TRAY_HEIGHT: 50.0}}
    stats = {}
    ok, errors, warnings, error = ops._try_resize(doc, plan, u"x", True, stats)
    assert ok and not error, (ok, error)
    assert value(u"Tray Height") == 50.0 and value(u"Tray Width") == 200.0
    assert stats == {u"Tray Height": 1}, stats


@check
def with_fittings_off_only_the_trays_change():
    ops, doc, value = _real_resize_scene()
    ops._try_resize(doc, {1: {core.TRAY_HEIGHT: 50.0}, 2: {core.TRAY_HEIGHT: 50.0}},
                    u"x", False, {})
    assert value(u"Tray Height") == 25.0


@check
def a_fitting_left_at_the_old_size_is_reported_and_shown():
    ops, data, attempts, heights = _run_scene()
    fitting = _Element(77, {}, None, u"fitting")
    ops._fittings_joined = lambda doc, ids: {77: fitting}
    ops._fitting_plan = lambda f: ({u"height": 50.0}, [(u"Tray Height", 50.0)], [])
    ops._resize_run(None, 1, {u"all": list(range(1, 9)) + [77]}, _plan(), data)
    ops._finish_resize(None, data)
    assert data[u"resized"] == 8 and data[u"fittings_left"], data
    assert u"Tray Height is not 50" in data[u"fittings_left"][0]
    failed = data[u"failed_runs"]
    assert failed and failed[0][u"broken"] == [77] and failed[0][u"left"] == [], failed


@check
def revit_failures_are_explained():
    hint = core.explain_failure(u"The cable tray has been modified to be in the opposite "
                                u"direction or insufficient space to create the required fittings.")
    assert u"straight too short" in hint
    assert core.explain_failure(u"Something new") == u""
    assert core.explain_failure(None) == u""


@check
def the_attempts_are_capped():
    ops, data, attempts, heights = _run_scene(tight=tuple(range(1, 9)), names=False)
    ops._resize_run(None, 1, {u"all": list(range(1, 9))}, _plan(), data)
    ops._finish_resize(None, data)
    assert len(attempts) <= 24 and data[u"resized"] == 0, len(attempts)


# ============================================================
# the Workset Assigner, and containment service changes
# ============================================================

def _systems():
    return [
        {u"key": u"pipe:1", u"discipline": u"pipe", u"type": u"Domestic Cold Water",
         u"name": u"CWS 1", u"ids": [11, 12, 13], u"worksets": {100: 3}},
        {u"key": u"pipe:2", u"discipline": u"pipe", u"type": u"Domestic Cold Water",
         u"name": u"CWS 2", u"ids": [21, 22], u"worksets": {100: 1, 200: 1}},
        {u"key": u"duct:3", u"discipline": u"duct", u"type": u"Supply Air",
         u"name": u"SA 1", u"ids": [31], u"worksets": {200: 1}},
        {u"key": u"cont:4", u"discipline": u"cont", u"type": u"VRF",
         u"name": u"Run 4", u"ids": [41, 42], u"worksets": {300: 2}},
    ]


WS_NAMES = {100: u"MEP-Plumbing", 200: u"MEP-Mechanical", 300: u"MEP-Electrical"}


@check
def worksets_group_by_discipline_then_type():
    groups, notes = core.workset_rows(_systems(), {}, WS_NAMES)
    order = core.ws_group_order(list(groups.keys()))
    assert order == [u"Containment \u00b7 VRF", u"Pipework \u00b7 Domestic Cold Water",
                     u"Ductwork \u00b7 Supply Air"], order
    rows = dict((r[u"system"], r) for r in groups[order[1]])
    assert rows[u"CWS 1"][u"workset"] == u"MEP-Plumbing" and not rows[u"CWS 1"][u"mixed"]
    assert rows[u"CWS 2"][u"mixed"]
    assert rows[u"CWS 2"][u"workset"].startswith(u"Mixed: ")
    assert rows[u"CWS 1"][u"elements"] == 3 and rows[u"CWS 1"][u"ids"] == [11, 12, 13]
    assert notes[order[1]] == u"Mixed: MEP-Plumbing (4), MEP-Mechanical (1)", notes
    assert notes[order[2]] == u"MEP-Mechanical"
    # sorting by workset puts the mixed one where it belongs
    ordered = core.sort_rows(groups[order[1]], [(u"workset", False)])
    assert [r[u"system"] for r in ordered] == [u"CWS 1", u"CWS 2"]


@check
def the_tree_is_discipline_then_system_type():
    tree = core.workset_tree(_systems(), {}, WS_NAMES)
    assert [t[0] for t in tree] == [u"Containment", u"Pipework", u"Ductwork"], tree
    pipework = tree[1][1]
    assert [s[0] for s in pipework] == [u"Pipework \u00b7 Domestic Cold Water"]
    assert len(pipework[0][1]) == 2 and pipework[0][2].startswith(u"Mixed")


@check
def grouped_by_discipline_the_type_is_a_column():
    systems = _systems() + [
        {u"key": u"pipe:9", u"discipline": u"pipe", u"type": u"Chilled Water",
         u"name": u"CHW 1", u"ids": [91], u"worksets": {100: 1}}]
    tree = core.workset_tree(systems, {}, WS_NAMES, u"discipline")
    pipework = dict(tree)[u"Pipework"]
    assert len(pipework) == 1 and pipework[0][0] == u"Pipework"
    rows = pipework[0][1]
    assert [(r[u"system_type"], r[u"system"]) for r in rows] == [
        (u"Chilled Water", u"CHW 1"), (u"Domestic Cold Water", u"CWS 1"),
        (u"Domestic Cold Water", u"CWS 2")], rows


@check
def mixed_only_isolates_the_systems_to_fix():
    tree = core.workset_tree(_systems(), {}, WS_NAMES, u"type", True)
    assert [t[0] for t in tree] == [u"Pipework"], tree           # others emptied, dropped
    rows = tree[0][1][0][1]
    assert [r[u"system"] for r in rows] == [u"CWS 2"] and rows[0][u"mixed"]
    assert core.mixed_count(_systems()) == 1
    flat = core.workset_tree(_systems(), {}, WS_NAMES, u"discipline", True)
    assert [r[u"system"] for r in flat[0][1][0][1]] == [u"CWS 2"]


@check
def the_workset_list_narrows_to_every_word_typed():
    choices = [(u"MEP-Plumbing", 1), (u"MEP-Mechanical", 2), (u"ELEC-Containment", 3),
               (u"Shared Levels and Grids", 4)]
    assert core.filter_choices(choices, u"") == (choices, True)
    assert core.filter_choices(choices, u"mep") == (choices[:2], True)
    assert core.filter_choices(choices, u"mep mech") == ([choices[1]], True)
    assert core.filter_choices(choices, u"  CONTAIN ") == ([choices[2]], True)
    # nothing matches: the whole list stays, and it says so
    assert core.filter_choices(choices, u"drainage") == (choices, False)


@check
def apply_takes_every_staged_system_not_just_the_ones_shown():
    pending = {u"pipe:1": 200, u"duct:3": 300}
    rows = core.staged_rows(_systems(), pending, WS_NAMES)
    assert sorted(r[u"key"] for r in rows) == [u"duct:3", u"pipe:1"]
    # pipe:1 is on one workset, so "mixed only" hides it - Apply must not
    shown = core.workset_tree(_systems(), pending, WS_NAMES, u"type", True)
    visible = [r[u"key"] for _t, sections in shown for _n, rs, _no in sections for r in rs]
    assert u"pipe:1" not in visible
    total, _text = core.workset_plan_text(rows, pending, WS_NAMES)
    assert total == 4, total                              # 3 in CWS 1 + 1 in SA 1
    assert core.staged_rows(_systems(), {u"gone:9": 200}, WS_NAMES) == []


@check
def nothing_is_written_until_apply_staging_only_records():
    pending = core.stage_worksets({}, [u"pipe:1", u"cont:4"], 200)
    assert pending == {u"pipe:1": 200, u"cont:4": 200}
    pending = core.stage_worksets(pending, [u"cont:4"], 300)
    groups, notes = core.workset_rows(_systems(), pending, WS_NAMES)
    rows = dict((r[u"key"], r) for g in groups.values() for r in g)
    assert rows[u"pipe:1"][u"new_workset"] == u"MEP-Mechanical" and rows[u"pipe:1"][u"pend"]
    assert rows[u"cont:4"][u"new_workset"] == u"MEP-Electrical"
    assert rows[u"duct:3"][u"new_workset"] == u"" and not rows[u"duct:3"][u"pend"]
    total, text = core.workset_plan_text(list(rows.values()), pending, WS_NAMES)
    assert total == 5, total
    assert u"To MEP-Mechanical: 1 system, 3 elements" in text, text
    assert u"To MEP-Electrical: 1 system, 2 elements" in text
    assert core.workset_summary({}) == u"-"


@check
def a_service_change_reaches_rows_runs_or_whole_services():
    def rec(eid, kind, service, run):
        return {u"id": eid, u"kind": kind, u"system_type": service, u"system": run}
    records = [rec(1, u"tray", u"VRF", u"Run 1"), rec(2, u"tray", u"VRF", u"Run 1"),
               rec(3, u"tray", u"VRF", u"Run 3"), rec(4, u"tray", u"ICT", u"Run 4"),
               rec(5, u"conduit", u"VRF", u"Run 5")]
    assert core.service_scope_ids(records, [1], u"rows") == [1]
    assert core.service_scope_ids(records, [1], u"runs") == [1, 2]
    assert core.service_scope_ids(records, [1], u"services") == [1, 2, 3, 5]
    # System No from a parameter: runs are not in the table, so the rows stand
    assert core.service_scope_ids(records, [1], u"runs", system_from=u"Mark") == [1]


class _Workset(object):
    def __init__(self, number):
        self.IntegerValue = number


def _ws_scene(read_only=()):
    ops = _load_ops()
    doc = _Doc()

    class _WsParam(object):
        def __init__(self, element):
            self.element = element
            self.IsReadOnly = element.Id.Value in read_only

        def Set(self, number):
            self.element.WorksetId = _Workset(number)
            return True
    for number in (11, 12, 13, 31):
        e = _Element(number, {})
        e.WorksetId = _Workset(100)
        e.get_Parameter = lambda member, e=e: _WsParam(e)
        doc.add(e)
    ops.make_id = lambda n: _Id(n)
    ops.borrow = lambda d, ids: {}
    ops.committed = lambda status: True
    app = _Bag()
    app.ActiveUIDocument = _Bag()
    app.ActiveUIDocument.Document = doc
    return ops, doc, app


@check
def apply_moves_every_element_and_proves_it():
    ops, doc, app = _ws_scene(read_only=(13,))
    result = ops.Result()
    ops.workset_job([(u"CWS 1", [11, 12, 13], 200), (u"SA 1", [31], 200)])(app, result)
    d = result.data
    assert d[u"systems"] == 2 and d[u"systems_done"] == 1, d
    assert d[u"changed"] == 3 and d[u"already"] == 0      # 11, 12 and 31
    assert [x for x in d[u"failed"] if x.startswith(u"13 ")], d[u"failed"]
    assert d[u"not_taken"] == [u"CWS 1 - 2 of 3 elements on the new workset"], d[u"not_taken"]
    assert _Group.last.state == u"assimilated"
    assert u"wrote 4" in d[u"timing"], d[u"timing"]


@check
def elements_already_right_are_not_borrowed_or_written():
    ops, doc, app = _ws_scene()
    doc.elements[12].WorksetId = _Workset(200)            # already there
    borrowed = []
    ops.borrow = lambda d, ids: borrowed.extend(ids) or {}
    commits = []
    real_commit = doc.commit
    doc.commit = lambda: commits.append(1) or real_commit()
    result = ops.Result()
    ops.workset_job([(u"CWS 1", [11, 12, 13], 200)])(app, result)
    d = result.data
    assert sorted(borrowed) == [11, 13], borrowed
    assert d[u"changed"] == 2 and d[u"already"] == 1 and d[u"systems_done"] == 1, d
    assert len(commits) == 1, commits                    # one transaction, not one per batch


@check
def a_refused_lot_is_done_again_in_batches():
    ops, doc, app = _ws_scene()
    calls = []
    real = ops._set_worksets

    def refuse_the_lot(doc_, work, member, data):
        calls.append(len(work))
        if len(calls) == 1:
            return False, u"RolledBack", []
        return real(doc_, work, member, data)
    ops._set_worksets = refuse_the_lot
    result = ops.Result()
    ops.workset_job([(u"CWS 1", [11, 12, 13], 200)])(app, result)
    d = result.data
    assert calls == [3, 3], calls                        # the lot, then one batch of 3
    assert u"batches" in d[u"batched"] and d[u"changed"] == 3, d


@check
def borrowing_asks_only_about_what_it_could_not_borrow():
    ops = _load_ops()
    asked = []

    class _WSU(object):
        @staticmethod
        def CheckoutElements(doc, ids):
            return [_Id(n) for n in ids if n != 7]

        @staticmethod
        def GetWorksharingTooltipInfo(doc, eid):
            asked.append(eid.Value)
            info = _Bag()
            info.Owner = u"jsmith"
            return info

        @staticmethod
        def GetCheckoutStatus(doc, eid):
            raise AssertionError(u"asked about every element")
    ops.WorksharingUtils = _WSU
    ops.id_list = lambda numbers: list(numbers)
    ops.make_id = lambda n: _Id(n)
    doc = _Bag()
    doc.IsWorkshared = True
    locked = ops.borrow(doc, [5, 6, 7, 8])
    assert locked == {7: u"jsmith"} and asked == [7], (locked, asked)
    doc.IsWorkshared = False
    assert ops.borrow(doc, [5]) == {}


def _service_scene():
    ops = _load_ops()
    doc = _Doc()

    class _SvcParam(object):
        def __init__(self, element):
            self.element = element
            self.IsReadOnly = False

        def Set(self, value):
            self.element.service = value
            return True
    made = {}
    for number, kind, service in ((1, u"tray", u"VRF"), (2, u"tray", u"VRF"),
                                  (7, u"fitting", u"VRF"), (8, u"fitting", u"ICT"),
                                  (9, u"fitting", u"")):
        e = _Element(number, {}, None, kind)
        e.service = service
        e.get_Parameter = lambda member, e=e: _SvcParam(e)
        doc.add(e)
        made[number] = e
    ops.make_id = lambda n: _Id(n)
    ops.borrow = lambda d, ids: {}
    ops.committed = lambda status: True
    ops.model.service_of = lambda e, settings: e.service
    ops.model.walk_run = lambda e, settings: ([1, 2], [7, 8, 9])
    app = _Bag()
    app.ActiveUIDocument = _Bag()
    app.ActiveUIDocument.Document = doc
    return ops, made, app


@check
def a_new_service_type_goes_on_the_run_and_its_own_fittings():
    ops, made, app = _service_scene()
    result = ops.Result()
    settings = core.DomainView(dict(core.DEFAULTS), u"cont").resolved()
    ops.service_job([1, 2], u"LV", True, settings)(app, result)
    d = result.data
    assert made[1].service == made[2].service == u"LV"
    assert made[7].service == u"LV" and made[9].service == u"LV"     # its own, and a blank one
    assert made[8].service == u"ICT"                                # another service's: the edge
    assert d[u"changed"] == 4 and d[u"fittings"] == 2, d
    assert d[u"parameter"] == u"Service Type"


@check
def without_fittings_only_the_trays_change():
    ops, made, app = _service_scene()
    result = ops.Result()
    settings = core.DomainView(dict(core.DEFAULTS), u"cont").resolved()
    ops.service_job([1], u"LV", False, settings)(app, result)
    assert made[1].service == u"LV" and made[2].service == u"VRF" and made[7].service == u"VRF"


# ============================================================
# containment: the types each service type uses
# ============================================================

@check
def each_service_heading_lists_its_types():
    def rec(eid, service, ptype):
        return {u"id": eid, u"system_type": service, u"ptype": ptype}
    records = [rec(1, u"ICT", u"Cable Tray: BHE_CableTray (25mm High)"),
               rec(2, u"ICT", u"Cable Tray: BHE_CableTray (25mm High)"),
               rec(3, u"ICT", u"Cable Tray: BHE_Ladder"),
               rec(4, u"ICT", u"Conduit: 25mm PVC"),
               rec(5, u"VRF", u"Cable Tray: VRF_Refrigeration"),
               rec(6, u"", u"Cable Tray: BHE_Ladder")]
    by = core.types_by_group(records)
    assert by[u"ICT"] == {u"Cable Tray: BHE_CableTray (25mm High)": 2,
                          u"Cable Tray: BHE_Ladder": 1, u"Conduit: 25mm PVC": 1}, by
    text, several = core.type_summary(by[u"ICT"])
    assert several and text == (u"3 types: BHE_CableTray (25mm High) \u00d72 \u00b7 "
                                u"BHE_Ladder \u00d71 \u00b7 Conduit: 25mm PVC \u00d71"), text
    assert core.type_summary(by[u"VRF"]) == (u"Type: VRF_Refrigeration \u00d71", False)
    assert core.multi_type_groups(by) == {u"ICT"}
    assert core.UNASSIGNED in by                          # no service type still counted
    assert core.type_summary({}) == (u"", False)


@check
def the_type_count_ignores_how_the_rows_are_split():
    records = [{u"id": i, u"system_type": u"LV", u"system": u"Run 1", u"size_mm": 100.0,
                u"ptype": u"Cable Tray: A" if i < 3 else u"Cable Tray: B"} for i in range(5)]
    merged = core.build_groups(records, split_type=False)[u"LV"]
    assert len(merged) == 1                              # one row says "2 types"
    assert len(core.types_by_group(records)[u"LV"]) == 2  # the heading still lists both


# ============================================================
# the frozen system type heading
# ============================================================

@check
def the_heading_of_the_type_being_scrolled_is_pinned():
    h = 36.0
    # nothing scrolled: every heading is on screen, nothing pinned
    assert core.sticky_pick([(0.0, 300.0, True), (300.0, 600.0, True)], h) == (None, 0.0)
    # scrolled into the first type: it is pinned, not pushed
    assert core.sticky_pick([(-100.0, 200.0, True), (200.0, 500.0, True)], h) == (0, 0.0)
    # the next heading has come up under it: pushed up by the overlap
    assert core.sticky_pick([(-280.0, 20.0, True), (20.0, 320.0, True)], h) == (0, -16.0)
    # the next heading reaches the top: it takes over
    assert core.sticky_pick([(-300.0, 0.0, True), (0.0, 300.0, True)], h) == (None, 0.0)
    assert core.sticky_pick([(-310.0, -10.0, True), (-10.0, 290.0, True)], h) == (1, 0.0)
    # a folded type has no rows to pin a heading over
    assert core.sticky_pick([(-40.0, -4.0, False), (-4.0, 290.0, True)], h) == (1, 0.0)
    assert core.sticky_pick([(-40.0, 10.0, False), (10.0, 290.0, True)], h) == (None, 0.0)
    # the last type's own end pushes it out
    assert core.sticky_pick([(-300.0, 20.0, True)], h) == (0, -16.0)
    assert core.sticky_pick([], h) == (None, 0.0)


@check
def the_view_isolated_last_time_is_reset_too():
    """Checking system after system: if the last isolate went into another
    view, that view is reset as well, so no old isolate is left standing."""
    view = _View(isolated=False)
    old = _View(isolated=True)
    old.Id = _Id(88)
    old.Name = u"Coordination 3D"
    result, committed, group = _run_isolate(view, previous=88, other=old)
    assert old.calls == [u"reset", u"reveal off"], old.calls
    assert not old.isolated
    assert result.get(u"reset_views") == [u"{3D - drew}", u"Coordination 3D"], result.data
    assert result.get(u"view_id") == 77


@check
def anything_still_showing_is_reset_and_isolated_again():
    view = _View(isolated=True)
    # first look: element 9 from an old isolate still shows; second look: clean
    result, committed, group = _run_isolate(view, visible=[[1, 2, 9], [1, 2]])
    assert view.calls.count(u"isolate") == 2, view.calls
    assert result.get(u"retried") == 1 and not result.get(u"leftovers"), result.data
    assert group.state == u"assimilated"


@check
def what_will_not_clear_is_reported_not_hidden():
    view = _View(isolated=True)
    result, committed, group = _run_isolate(view, visible=[[1, 2, 9], [1, 2, 9]])
    assert result.get(u"leftovers") == [9], result.data
    assert view.calls.count(u"isolate") == 2                # one retry, not a loop


@check
def the_views_to_reset_and_the_leftovers():
    assert core.views_to_reset(77, 88) == [77, 88]
    assert core.views_to_reset(77, 77) == [77]
    assert core.views_to_reset(77, u"") == [77]
    assert core.views_to_reset(0, u"88") == [88]
    assert core.leftovers([1, 2, 9, 7], [1, 2]) == [7, 9]
    assert core.leftovers([], [1]) == []


# ============================================================
# sorting: containment by type, and the sorted heading
# ============================================================

@check
def containment_sorts_by_type_within_each_service_type():
    assert core.default_sort(u"cont") == [(u"ptype", False), (u"system", False)]
    assert core.default_sort(u"pipe") == [(u"system", False)]
    assert core.default_sort(None) == [(u"system", False)]
    rows = [{u"key": u"a", u"ptype": u"Cable Tray: Ladder", u"system": u"Run 9"},
            {u"key": u"b", u"ptype": u"Cable Tray: Basket", u"system": u"Run 2"},
            {u"key": u"c", u"ptype": u"Cable Tray: Basket", u"system": u"Run 10"}]
    ordered = core.sort_rows(rows, core.default_sort(u"cont"))
    assert [r[u"key"] for r in ordered] == [u"b", u"c", u"a"], ordered


@check
def the_sorted_heading_is_found_with_its_level():
    stack = [(u"ptype", False), (u"size", True)]
    assert core.sort_place(stack, u"ptype") == (0, False)
    assert core.sort_place(stack, u"size") == (1, True)
    assert core.sort_place(stack, u"count") is None
    assert core.sort_place([], u"size") is None


# ============================================================
# a colour per type
# ============================================================

@check
def every_type_keeps_its_own_colour():
    names = [u"Cable Tray: Ladder", u"Cable Tray: Basket", u"Conduit: 25mm"]
    colours = core.type_colours(names)
    assert colours == core.type_colours(list(reversed(names)) + names)   # order, repeats
    assert len(set(colours.values())) == 3                              # all different
    assert colours[u"Cable Tray: Basket"] == 0                          # natural order
    many = core.type_colours([u"T{0}".format(i) for i in range(12)])
    assert many[u"T0"] == many[u"T10"] and len(set(many.values())) == core.TYPE_COLOURS
    assert core.type_colours([None, u""]) == {}


@check
def the_heading_lists_each_type_in_its_colour():
    colours = {u"Cable Tray: Ladder": 3, u"Cable Tray: Basket": 5}
    parts = core.summary_parts({u"Cable Tray: Ladder": 12, u"Cable Tray: Basket": 3}, colours)
    assert parts == [(u"2 types: ", None), (u"Ladder", 3), (u" \u00d712", None),
                     (u" \u00b7 ", None), (u"Basket", 5), (u" \u00d73", None)], parts
    assert core.summary_parts({u"A": 1}, {})[0] == (u"Type: ", None)
    assert core.summary_parts({}, {}) == []


@check
def a_request_revit_has_not_run_frees_the_window_in_time():
    assert not core.busy_expired(None, 100.0)
    assert not core.busy_expired(100.0, 110.0)
    assert core.busy_expired(100.0, 100.0 + core.BUSY_TIMEOUT_S)


@check
def a_second_request_never_drops_the_first():
    """The bug behind "isolate stops after a few goes": a request made while
    Revit had not yet run the last one emptied the queue, the first job's
    callback never came, and the window stayed busy for ever."""
    ops = _load_ops()

    class _Event(object):
        answers = []

        def Raise(self):
            return self.answers.pop(0)
    runner = ops.ModelessRunner.__new__(ops.ModelessRunner)
    runner.handler = ops.JobHandler()
    runner.event = _Event()
    begun = []
    runner.started = lambda: begun.append(1)
    done = []
    accepted = ops.ExternalEventRequest.Accepted
    _Event.answers = [accepted, u"ExternalEventRequest.Pending"]
    first = runner.run(lambda app, r: None, lambda r: done.append((u"first", r.error)))
    second = runner.run(lambda app, r: None, lambda r: done.append((u"second", r.error)))
    assert len(runner.handler.queue) == 2, runner.handler.queue       # both still queued
    assert done == [] and second.endswith(u"Pending"), (done, second)
    runner.handler.Execute(None)                                        # Revit gets to it
    assert [d[0] for d in done] == [u"first", u"second"], done
    assert begun == [1], begun          # the window is told Revit has begun
    # a refusal takes back only the refused job
    _Event.answers = [accepted, u"ExternalEventRequest.Denied"]
    done[:] = []
    runner.run(lambda app, r: None, lambda r: done.append((u"kept", r.error)))
    runner.run(lambda app, r: None, lambda r: done.append((u"refused", r.error)))
    assert len(runner.handler.queue) == 1 and done[0][0] == u"refused" and done[0][1], done


# ============================================================
# System No folds
# ============================================================

@check
def a_service_type_folds_into_its_system_numbers():
    rows = [{u"key": u"a", u"system": u"SA 10"}, {u"key": u"b", u"system": u"SA 2"},
            {u"key": u"c", u"system": u"SA 2"}, {u"key": u"d", u"system": u""}]
    nested = core.nest_by_system(rows)
    assert [n for n, _r in nested] == [u"", u"SA 2", u"SA 10"], nested
    assert [r[u"key"] for r in dict(nested)[u"SA 2"]] == [u"b", u"c"]
    assert core.nested_name(u"Supply Air", u"SA 2") == u"Supply Air \u00b7 SA 2"
    assert core.nested_name(u"Supply Air", u"") == u"Supply Air \u00b7 " + core.UNASSIGNED


@check
def ducts_fold_by_system_number_by_default_the_rest_can():
    base = dict(core.DEFAULTS)
    assert core.DomainView(base, u"duct").get(u"nest_systems") == u"1"
    assert core.DomainView(base, u"pipe").get(u"nest_systems") == u"1"     # 3.0.0
    assert core.DomainView(base, u"cont").get(u"nest_systems") == u"0"
    assert core.DomainView(base, u"duct").resolved()[u"nest_systems"] == u"1"
    assert core.DomainView({}, u"duct").resolved()[u"nest_systems"] == u"1"   # a bare file


# ============================================================
# linked models
# ============================================================

@check
def nothing_is_picked_from_a_linked_model_unless_asked():
    allowed = core.pick_allowed
    # off (the default)
    assert core.DEFAULTS[u"lookup_linked"] == u"0"
    assert not allowed(True, False, False, False)          # the linked model itself
    assert not allowed(False, True, True, False)           # a pipe inside it
    assert allowed(False, False, True, False)              # this model's pipe
    assert not allowed(False, False, False, False)         # this model's wall
    # on
    assert allowed(True, False, False, True)
    assert allowed(False, True, True, True)
    assert not allowed(False, True, False, True)           # a linked wall


def _pick_scene(picks, lookup):
    """Revit's Selection answering the queued picks in turn."""
    ops = _load_ops()
    doc = _Doc()

    class _Link(object):
        pass
    ops.RevitLinkInstance = _Link
    link = _Link()
    link.Id = _Id(900)
    link.Name = u"Architect.rvt"
    inner = _Element(7, {}, None, u"pipe")
    inner.Category = _Bag()
    inner.Category.Name = u"Pipes"
    inner.MEPSystem = None
    inner.GetTypeId = lambda: _Id(55)
    link_doc = _Doc()
    link_doc.add(inner)
    link.GetLinkDocument = lambda: link_doc
    doc.elements[900] = link
    own = doc.add(_Element(1, {}, None, u"pipe"))
    own.Category = _Bag()
    own.Category.Name = u"Pipes"

    def ref(element_id, linked=None):
        r = _Bag()
        r.ElementId = _Id(element_id)
        r.LinkedElementId = _Id(linked) if linked is not None else None
        return r
    queue = [ref(*p) for p in picks]

    class _Selection(object):
        def PickObject(self, kind, pick_filter, prompt):
            return queue.pop(0)
    uidoc = _Bag()
    uidoc.Document = doc
    uidoc.Selection = _Selection()
    app = _Bag()
    app.ActiveUIDocument = uidoc
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value if i is not None else 0
    ops.model.domain_of = lambda e: u"pipe" if getattr(e, u"kind", u"") == u"pipe" else u""
    ops.model.is_curve = lambda e: getattr(e, u"kind", u"") == u"pipe"
    ops.model.neighbours = lambda e: []
    ops.model.elem_name = lambda e: getattr(e, u"Name", u"")
    ops.model.builtin_text = lambda e, name: u"CWS 1" if name == u"RBS_SYSTEM_NAME_PARAM" else u""
    ops.model.size_of = lambda e: (u"22", 22.0)
    result = ops.Result()
    ops.pick_job(lookup)(app, result)
    return result


@check
def a_linked_pick_is_thrown_away_by_default():
    result = _pick_scene([(900,)], False)
    assert result.get(u"linked_refused") and not result.get(u"id"), result.data
    result = _pick_scene([(900, 7)], False)                 # a reference into a link
    assert result.get(u"linked_refused"), result.data
    result = _pick_scene([(1,)], False)                     # this model's pipe
    assert result.get(u"id") == 1 and result.get(u"domain") == u"pipe", result.data


@check
def with_linked_lookup_the_element_inside_is_reported_read_only():
    result = _pick_scene([(900,), (900, 7)], True)
    linked = result.get(u"linked")
    assert linked and linked[u"link"] == u"Architect.rvt" and linked[u"id"] == 7, result.data
    assert linked[u"system"] == u"CWS 1" and not result.get(u"id")


# ============================================================
# Change Pipe Type: the size mapping, groups, the log
# ============================================================

def _mapping_records():
    def rec(eid, ptype, size):
        return {u"id": eid, u"ptype": ptype, u"size_mm": size}
    return [rec(1, u"Copper", 22.0), rec(2, u"Copper", 22.0), rec(3, u"Copper", 15.0),
            rec(4, u"MLCP", 22.0), rec(5, u"Copper", 54.0), {u"id": 6, u"ptype": u"X"}]


@check
def the_selection_is_grouped_by_type_and_size():
    rows = core.size_rows(_mapping_records())
    assert [(r[u"type"], r[u"size"], r[u"count"]) for r in rows] == [
        (u"Copper", 15.0, 1), (u"Copper", 22.0, 2), (u"MLCP", 22.0, 1), (u"Copper", 54.0, 1)], rows
    by_type = core.sort_size_rows(rows, u"type")
    assert [r[u"type"] for r in by_type] == [u"Copper", u"Copper", u"Copper", u"MLCP"]
    by_count = core.sort_size_rows(rows, u"count")
    assert by_count[0][u"count"] == 2
    colours = core.size_colours(rows)
    assert colours == {15.0: 0, 22.0: 1, 54.0: 2}, colours       # one per size


@check
def each_size_defaults_to_the_same_or_the_next_up():
    offered = [15.0, 22.0, 28.0, 35.0]
    assert core.default_target(22.0, offered) == 22.0
    assert core.default_target(20.0, offered) == 22.0
    assert core.default_target(54.0, offered) == 35.0             # bigger than any: the largest
    assert core.default_target(22.0, []) is None                 # unknown: keep


@check
def the_mapping_becomes_a_size_per_pipe():
    rows = core.size_rows(_mapping_records())
    choices = {(u"Copper", 22.0): 25.0, (u"Copper", 15.0): None}
    size_map = core.size_map_from(rows, choices)
    assert size_map[1] == 25.0 and size_map[2] == 25.0
    assert size_map[3] == 15.0                                   # no choice: keeps its size
    assert size_map[4] == 22.0 and 6 not in size_map
    lines = core.mapping_summary(rows, choices, u"PEX")
    assert u"Copper 22 \u00d72  \u2192  PEX 25" in lines, lines


@check
def a_group_is_edited_unless_nested_or_a_copy_is_held():
    assert core.group_decision(False) == (True, u"")
    ok, why = core.group_decision(True)
    assert not ok and u"nested" in why
    ok, why = core.group_decision(False, u"jsmith")
    assert not ok and u"jsmith" in why and u"every copy" in why


@check
def every_copy_lands_exactly_where_it_was_on_the_changed_group():
    """The heart of editing a group with copies: the rebuilt group puts the
    members somewhere else entirely; each copy is put back from where its
    members were and where they are now - no group origin involved."""
    members = [(0.0, 0.0, 0.0), (10.0, 0.0, 3.0), (10.0, 6.0, 3.0), (-2.5, 4.0, 1.0)]

    def placed(origin, angle):
        return [core.add3(origin, core.rot_z(m, angle)) for m in members]
    for origin in ((0.0, 0.0, 0.0), (100.0, 50.0, 0.0), (-40.0, 7.0, 12.0)):
        for angle in (0.0, 0.7, math.pi / 2, -2.4):
            was = placed(origin, angle)
            for new_origin in ((0.0, 0.0, 0.0), (13.0, -4.0, 9.0)):
                for new_angle in (0.0, 1.1, -2.2):
                    now = placed(new_origin, new_angle)
                    turn, about, move = core.align_transform(was, now)
                    for old_point, new_point in zip(was, now):
                        back = core.apply_alignment(new_point, turn, about, move)
                        assert core.dist3(old_point, back) < 1e-9, (origin, angle, back)
    assert core.align_transform([], []) is None


@check
def a_copys_frame_comes_from_its_own_members():
    members = [(0.0, 0.0, 0.0), (10.0, 0.0, 3.0), (10.0, 6.0, 3.0)]
    first = core.local_frame(members)
    moved = [core.add3((20.0, -5.0, 2.0), core.rot_z(m, 1.3)) for m in members]
    second = core.local_frame(moved)
    # the same members give the same local places wherever the copy sits
    for member, point in zip(members, moved):
        assert core.dist3(core.to_local(member, first[0], first[1]),
                          core.to_local(point, second[0], second[1])) < 1e-9
    assert core.local_frame([]) == (None, 0.0)
    assert core.local_frame([(1.0, 2.0, 3.0)]) == ((1.0, 2.0, 3.0), 0.0)


@check
def a_pipe_in_any_copy_finds_its_counterpart_in_the_edited_one():
    members = [(0.0, 0.0, 0.0), (10.0, 0.0, 3.0), (10.0, 6.0, 3.0)]
    centre, angle = core.local_frame(members)
    edited = dict((n, core.to_local(m, centre, angle)) for n, m in zip((1, 2, 3), members))
    # the same pipe in a copy 40 ft away and turned
    moved = [core.add3((-40.0, 7.0, 12.0), core.rot_z(m, 1.1)) for m in members]
    copy_centre, copy_angle = core.local_frame(moved)
    local = core.to_local(moved[2], copy_centre, copy_angle)
    assert core.counterpart(local, edited, 0.03) == 3
    assert core.counterpart((50.0, 50.0, 0.0), edited, 0.03) is None
    before = ((0.0, 0.0, 0.0), (10.0, 6.0, 3.0))
    assert not core.bbox_moved(before, ((0.05, 0.0, 0.0), (10.05, 6.0, 3.0)), 0.82)
    assert core.bbox_moved(before, ((4.0, 0.0, 0.0), (14.0, 6.0, 3.0)), 0.82)


def _close_scene(copy_moves):
    """A group edited and closed: copy 21 lands, copies in copy_moves shift
    by the given distance when swapped."""
    ops = _load_ops()
    doc = _Doc()
    renamed = []
    deleted = []

    class _Type(object):
        def __init__(self, number, name):
            self.Id = _Id(number)
            self._name = name

        def _get(self):
            return self._name

        def _set(self, value):
            self._name = value
            renamed.append((self.Id.Value, value))
        Name = property(_get, _set)
    old_type = _Type(800, u"WC Pod")
    new_type = _Type(801, u"Group 12")
    doc.elements[800] = old_type

    class _Copy(object):
        def __init__(self, number, shift):
            self.Id = _Id(number)
            self.shift = shift
            self.GroupType = old_type
    copies = {21: _Copy(21, 0.0), 22: _Copy(22, copy_moves.get(22, 0.0))}
    for number, copy in copies.items():
        doc.elements[number] = copy
    new_group = _Bag()
    new_group.GroupType = new_type

    class _Create(object):
        def NewGroup(self, ids):
            return new_group
    doc.Create = _Create()
    doc.Delete = lambda i: deleted.append(i.Value)
    for n in (1, 2):
        doc.add(_Element(n, {}))
    class _UndoTransaction(_Transaction):
        """Rolls back what a real one would: each copy's group type."""
        def Start(self):
            self.saved = dict((n, c.GroupType) for n, c in copies.items())
            return _Transaction.Start(self)

        def RollBack(self):
            for n, t in self.saved.items():
                copies[n].GroupType = t
            return _Transaction.RollBack(self)
    ops.Transaction = _UndoTransaction
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    ops.id_list = lambda n: list(n)
    ops.XYZ = lambda *a: _Bag()
    ops._rebuild_group = lambda d, item, data: new_group
    ops.model.extents = lambda e: ((e.shift, 0.0, 0.0), (1.0 + e.shift, 1.0, 1.0))
    ops._member_points = lambda d, g: [(1, (getattr(g, u"shift", 0.0), 0.0, 0.0)),
                                       (2, (getattr(g, u"shift", 0.0) + 1.0, 1.0, 0.0))]
    data = {u"failed": [], u"groups_reclosed": [], u"group_skipped": [], u"log_ok": []}
    item = {u"name": u"WC Pod", u"type_id": old_type.Id, u"members": [1, 2],
            u"via": {22: [555]},
            u"others": [{u"id": n, u"points": [(1, (0.0, 0.0, 0.0)), (2, (1.0, 1.0, 0.0))],
                         u"extents": ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))} for n in (21, 22)]}
    ops._close_groups(doc, [item], data)
    before = len(data[u"groups_reclosed"])
    ops._close_groups(doc, [item], data)        # a second pass must do nothing
    assert len(data[u"groups_reclosed"]) == before, data[u"groups_reclosed"]
    return data, copies, renamed, deleted, new_type


@check
def every_copy_that_lands_is_updated_and_the_group_keeps_its_name():
    data, copies, renamed, deleted, new_type = _close_scene({})
    assert copies[21].GroupType is new_type and copies[22].GroupType is new_type
    assert deleted == [800] and new_type.Name == u"WC Pod", (deleted, renamed)
    assert data[u"groups_reclosed"] == [u"WC Pod - edited, and 2 of 2 other copies updated"]
    assert data[u"log_ok"] == [u"555 - changed through its group 'WC Pod'"], data[u"log_ok"]


@check
def a_copy_that_would_move_is_left_as_it_was_and_named():
    data, copies, renamed, deleted, new_type = _close_scene({22: 3.0})
    assert copies[21].GroupType is new_type
    assert copies[22].GroupType is not new_type                 # rolled back
    assert not deleted and (800, u"WC Pod (copies not changed)") in renamed, renamed
    assert new_type.Name == u"WC Pod"
    assert [f for f in data[u"failed"] if f.startswith(u"22 - ")], data[u"failed"]
    assert data[u"group_skipped"] == [u"555 - its copy of group 'WC Pod' was left as it was"]


@check
def the_change_log_names_every_success_and_error_by_id():
    ops = _load_ops()
    doc = _Doc()

    def pipe(number, type_id, diameter):
        e = _Element(number, {}, None, u"pipe")
        e.GetTypeId = lambda: _Id(type_id)
        e.Diameter = core.mm_to_feet(diameter)
        return doc.add(e)
    pipe(1, 500, 25.0)            # changed to the new type at its mapped size
    pipe(2, 400, 22.0)            # Revit refused it
    pipe(3, 500, 28.0)            # on the type, wrong size
    doc.add(_Element(400, {}))
    doc.elements[400].Name = u"Copper"
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    ops.model.elem_name = lambda e: getattr(e, u"Name", u"")
    ops.model.whole_system_ids = lambda d, ids, domain: [1, 2, 3, 90]
    data = {u"failed": [u"2 - Revit refused the type"], u"locked": [], u"fitting_failed": [],
            u"group_skipped": [u"4 - its group has 2 other copies"], u"not_restored": [],
            u"wrong_kind": [], u"size_changed": [], u"swapped_ids": [60],
            u"log_ok": [], u"log_err": []}
    before = {1: (u"Copper", 22.0), 2: (u"Copper", 22.0), 3: (u"Copper", 22.0)}
    ops._change_log(doc, [1, 2, 3], before, 500, u"PEX", {1: 25.0, 2: 25.0, 3: 25.0}, True, data)
    assert data[u"log_ok"][0] == u"1 - Copper 22 \u2192 PEX 25", data[u"log_ok"]
    assert u"60 - fitting swapped" in data[u"log_ok"][1]
    joined = u" | ".join(data[u"log_err"])
    assert u"2 - Revit refused the type" in joined and u"3 - size is 28, wanted 25" in joined
    assert u"4 - its group has 2 other copies" in joined, joined
    assert data[u"_success_ids"] == [1, 60] and data[u"_error_ids"] == [2, 3, 4]
    assert data[u"_system_ids"] == [1, 2, 3, 90]


@check
def errors_are_magenta_lines_and_successes_see_through():
    ops = _load_ops()
    calls = []

    class _OGS(object):
        def SetSurfaceTransparency(self, value):
            calls.append((u"transparency", value))

        def SetProjectionLinePatternId(self, value):
            calls.append((u"pattern", u"solid"))

        def SetProjectionLineColor(self, value):
            calls.append((u"colour", value))
    ops.OverrideGraphicSettings = _OGS
    ops.Color = lambda r, g, b: (r, g, b)
    ops._transparent(60)
    ops._magenta_lines(None)
    assert calls == [(u"transparency", 60), (u"pattern", u"solid"),
                     (u"colour", (255, 0, 255))], calls


# ============================================================
# accessories on a resized system
# ============================================================

@check
def an_accessorys_instance_diameter_follows_its_pipe():
    params = [(u"Nominal Diameter", 22.0, True, True),
              (u"Size", 22.0, True, True),
              (u"Body Length", 22.0, True, True),          # not a size word
              (u"Offset Diameter", 22.0, True, True),      # an offset, never
              (u"Diameter", 28.0, True, True),             # not the old size
              (u"DN", 22.0, True, False),                  # driven by the type
              (u"Bore", 22.0, False, True)]                # read-only
    todo, left = core.accessory_size_plan(params, 22.0, 25.0)
    assert todo == [(u"Nominal Diameter", 25.0), (u"Size", 25.0)], todo
    assert left == [u"DN is driven by the type", u"Bore cannot be written"], left
    assert core.accessory_size_plan([], 22.0, 25.0) == ([], [])


@check
def accessories_are_resized_with_their_pipes_and_the_rest_reported():
    ops = _load_ops()
    doc = _Doc()
    pipe = doc.add(_Element(1, {}, None, u"pipe"))

    class _P(object):
        def __init__(self, name, mm, writable=True):
            self.Definition = _Bag()
            self.Definition.Name = name
            self.StorageType = u"Double"
            self.IsReadOnly = not writable
            self.value = core.mm_to_feet(mm)

        def AsDouble(self):
            return self.value

        def Set(self, value):
            self.value = value
            return True

    def accessory(number, params, type_params=()):
        e = _Element(number, {}, None, u"accessory")
        e.Parameters = [_P(n, mm) for n, mm in params]
        type_element = _Bag()
        type_element.Parameters = [_P(n, mm) for n, mm in type_params]
        e.Document = _Bag()
        e.Document.GetElement = lambda i: type_element
        e.GetTypeId = lambda: _Id(900)
        e.LookupParameter = lambda name: [p for p in e.Parameters
                                          if p.Definition.Name == name][0]
        doc.add(e)
        _link(pipe, e)
        return e
    valve = accessory(50, [(u"Nominal Diameter", 22.0), (u"Body Length", 22.0)])
    typed = accessory(51, [], [(u"Nominal Diameter", 22.0)])
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    ops.borrow = lambda d, ids: {}
    ops.committed = lambda status: True
    ops.model.neighbours = lambda e: list(e.links)
    ops.model.is_fitting_or_accessory = lambda e: e.kind == u"accessory"
    ops.model.is_fitting = lambda e: e.kind == u"fitting"
    data = {u"locked": [], u"accessories_resized": 0, u"accessories_left": [],
            u"_accessory_ids": []}
    ops._resize_accessories(doc, {1: (22.0, 25.0)}, data)
    assert abs(core.feet_to_mm(valve.Parameters[0].value) - 25.0) < 1e-6
    assert abs(core.feet_to_mm(valve.Parameters[1].value) - 22.0) < 1e-6   # length untouched
    assert data[u"accessories_resized"] == 1 and data[u"_accessory_ids"] == [50]
    assert [x for x in data[u"accessories_left"] if x.startswith(u"51 - ") and
            u"driven by the type" in x], data[u"accessories_left"]
    # a pipe whose size did not change leaves its accessories alone
    data = {u"locked": [], u"accessories_resized": 0, u"accessories_left": [],
            u"_accessory_ids": []}
    ops._resize_accessories(doc, {1: (25.0, 25.0)}, data)
    assert data[u"accessories_resized"] == 0 and not data[u"accessories_left"]


@check
def the_named_accessory_parameters_come_first():
    params = [(u"BGL_Diameter", 22.0, True, True),
              (u"Nominal Diameter", 22.0, True, False),     # type driven
              (u"Size", 22.0, True, True)]
    todo, left = core.accessory_named_plan(params, [u"BGL_Diameter", u"Nominal Diameter"], 25.0)
    assert todo == [(u"BGL_Diameter", 25.0)], todo
    assert left == [u"Nominal Diameter is driven by the type"], left
    # named outright, so it is set whatever it holds now
    odd = [(u"BGL_Diameter", 9.0, True, True)]
    assert core.accessory_named_plan(odd, [u"bgl_diameter"], 25.0)[0] == [(u"BGL_Diameter", 25.0)]
    assert core.accessory_named_plan(params, [], 25.0) == ([], [])
    assert core.DEFAULTS[u"accessory_params"] == u"BGL_Diameter"


@check
def a_chunk_changes_its_pipes_and_their_fittings_in_one_step():
    by_pipe = {1: [50, 51], 2: [51, 52], 9: [60]}
    ops = _load_ops()
    assert ops._fittings_for(by_pipe, [1, 2]) == [50, 51, 52]      # each fitting once
    assert ops._fittings_for(by_pipe, [9]) == [60]
    assert ops._fittings_for(by_pipe, [7]) == []
    modes = dict(core.FITTING_MODES)
    assert core.DEFAULTS[u"fitting_mode"] == u"size_second"      # 3.7.0
    assert u"together" in modes and u"size_second" in modes


@check
def one_bad_batch_never_stops_the_rest():
    """3.6.0: adding up a batch's tallies hit a counter the job had not set
    up, threw, and took every later batch with it - 1 pipe of 27 changed."""
    ops = _load_ops()
    calls = []

    def fake_chunk(doc, numbers, target, keep_size, data, batch, size_map=None,
                   fittings=None, pipe_type=None, slot_parts=None, change_type=True,
                   allow_disconnect=False):
        calls.append(list(numbers))
        if batch:
            raise KeyError(u"fittings_already")     # what 3.6.0 threw, after committing
        if numbers[0] == 2:
            raise Exception(u"Revit refused this one")
        data[u"changed"] = data.get(u"changed", 0) + len(numbers)
        return True
    ops._pipe_chunk = fake_chunk
    data = {u"changed": 0, u"failed": []}
    ops._change_batches(None, [1, 2, 3], None, True, data, None, u"together", {}, None, None)
    assert calls == [[1, 2, 3], [1], [2], [3]], calls      # the batch, then one at a time
    assert data[u"changed"] == 2, data                     # 1 and 3 changed; only 2 was lost
    joined = u" | ".join(data[u"failed"])
    assert u"fittings_already" in joined and u"2 - Revit refused this one" in joined, joined


@check
def only_the_pipes_whose_size_moves_go_through_the_second_pass():
    before = {1: (u"Copper", 22.0), 2: (u"Copper", 15.0), 3: (u"Copper", 28.0), 4: (u"X", None)}
    size_map = {1: 25.0, 2: 15.0, 3: 28.4, 4: 25.0}
    # 2 keeps its size; 3 moves by less than a tolerance; 4's size is unknown
    assert core.pipes_to_resize(before, size_map) == [1, 4], core.pipes_to_resize(before, size_map)
    assert core.pipes_to_resize({}, {}) == []


@check
def the_type_goes_on_first_and_the_size_after():
    """The sequence the model showed was steadiest: a routing preference picks
    a fitting by size, so the type and its fittings go on at the size each
    pipe already has, and the sizes follow."""
    ops = _load_ops()
    passes = []

    def fake_chunk(doc, numbers, target, keep_size, data, batch, size_map=None,
                   fittings=None, pipe_type=None, slot_parts=None, change_type=True,
                   allow_disconnect=False):
        passes.append((u"type" if change_type else u"size", list(numbers), keep_size,
                       sorted(size_map) if size_map else None, list(fittings or [])))
        data[u"changed" if change_type else u"resized"] = \
            data.get(u"changed" if change_type else u"resized", 0) + len(numbers)
        return True
    ops._pipe_chunk = fake_chunk
    data = {}
    by_pipe = {1: [50], 2: [51]}
    ops._change_batches(None, [1, 2], None, True, data, None, u"size_second", by_pipe,
                        None, None)
    ops._change_batches(None, [1], None, False, data, {1: 25.0}, u"size_second", by_pipe,
                        None, None, False)
    assert passes[0][0] == u"type" and passes[0][2] is True and passes[0][3] is None
    assert passes[0][4] == [50, 51]                 # the fittings go with the type pass
    assert passes[1][0] == u"size" and passes[1][1] == [1] and passes[1][3] == [1]
    assert passes[1][4] == [50]                     # and again with the size pass
    assert data[u"changed"] == 2 and data[u"resized"] == 1, data


@check
def a_refusal_says_what_revit_said():
    text = core.failure_text([(u"The pipes are not connected", [11766874])], [], u"RolledBack")
    assert u"The pipes are not connected" in text and text.startswith(u"Revit refused")
    # a warning, when that is all there is
    assert u"Slightly off axis" in core.failure_text([], [(u"Slightly off axis", [])], u"x")
    # nothing said at all is itself worth saying
    assert u"without saying why" in core.failure_text([], [], u"RolledBack")
    # the known messages keep their plain-English hint
    hint = core.failure_text([(u"insufficient space to create the required fittings", [])],
                             [], u"RolledBack")
    assert u"straight too short" in hint


@check
def settings_files_move_to_the_two_pass_order():
    assert core.SETTINGS_VERSION >= 4 and u"fitting_mode" in core.MIGRATIONS[4]
    # a settings file the last version wrote: the saved order kept the old
    # sequence, so 3.7.0's two passes never ran for anyone who had one
    older = core.parse_settings(u"settings_version=3\nfitting_mode=together\ntheme=light\n")
    assert older[u"fitting_mode"] == u"size_second", older[u"fitting_mode"]
    assert older[u"theme"] == u"light"          # everything else is left alone
    current = core.parse_settings(u"settings_version=4\nfitting_mode=together\n")
    assert current[u"fitting_mode"] == u"together"      # a deliberate choice stands


@check
def a_pipe_refused_while_its_neighbours_moved_gets_one_more_go():
    size_map = {1: 25.0, 2: 25.0, 3: 20.0}
    sizes = {1: 25.0, 2: 22.0, 3: 20.4}          # 2 did not take; 3 is within tolerance
    assert core.still_wrong_size(sizes, size_map) == [2]
    assert core.still_wrong_size({}, size_map) == []
    assert core.still_wrong_size(sizes, {}) == []


@check
def revits_disconnect_question_is_answered_no_unless_asked():
    ops = _load_ops()

    class _Failure(object):
        def __init__(self, text, severity, resolution=True):
            self.text = text
            self.severity = severity
            self.resolution = resolution
            self.resolved = False

        def GetDescriptionText(self):
            return self.text

        def GetSeverity(self):
            return self.severity

        def GetFailingElementIds(self):
            return [_Id(11766874)]

        def HasResolutionOfType(self, kind):
            return self.resolution

        def SetCurrentResolutionType(self, kind):
            pass

    class _Accessor(object):
        def __init__(self, failures):
            self.failures = failures

        def GetFailureMessages(self):
            return self.failures

        def DeleteWarning(self, failure):
            pass

        def ResolveFailure(self, failure):
            failure.resolved = True
    ops.FailureSeverity.Warning = u"Warning"
    text = u"The family is connected in a network and can no longer keep the connectivity."
    # off: the question is not answered, so the change rolls back
    failure = _Failure(text, u"Error")
    recorder = ops.FailureRecorder(False)
    result = recorder.PreprocessFailures(_Accessor([failure]))
    assert not failure.resolved and recorder.errors and not recorder.disconnected
    assert u"RollBack" in u"{0}".format(result)
    # on: Revit disconnects, and what it disconnected is written down
    failure = _Failure(text, u"Error")
    recorder = ops.FailureRecorder(True)
    result = recorder.PreprocessFailures(_Accessor([failure]))
    assert failure.resolved and not recorder.errors
    assert recorder.disconnected[0][1] == [11766874], recorder.disconnected
    assert u"RollBack" not in u"{0}".format(result)
    # a failure Revit offers no disconnect for still rolls back
    failure = _Failure(u"Line is too short.", u"Error", resolution=False)
    recorder = ops.FailureRecorder(True)
    assert u"RollBack" in u"{0}".format(recorder.PreprocessFailures(_Accessor([failure])))
    assert recorder.errors and not recorder.disconnected


@check
def the_same_refusal_is_reported_once():
    """A pipe tried again at the end fails the same way; every attempt was
    being written down, so the log read as two identical paragraphs."""
    said = [u"Revit refused: Line is too short.", u"Revit refused: Line is too short.",
            u"Revit refused: something else"]
    assert core.unique_reasons(said) == [u"Revit refused: Line is too short.",
                                         u"Revit refused: something else"]
    assert core.unique_reasons([]) == [] and core.unique_reasons(None) == []


@check
def a_pipe_revit_called_too_short_is_not_tried_again():
    failed = [u"11826746 - Revit refused: Line is too short.",
              u"11766878 - Revit refused: The duct/pipe has been modified to be in the "
              u"opposite direction causing the connections to be invalid.",
              u"a batch of 27 stopped: something"]
    assert core.retry_candidates([11826746, 11766878, 11766929], failed) == [11766878, 11766929]
    assert core.retry_candidates([], failed) == []


@check
def a_refused_pipe_says_how_long_it_is():
    assert core.length_note(core.mm_to_feet(132.0)) == u" (this pipe is 132 long)"
    assert core.length_note(None) == u""


@check
def revits_disconnect_question_names_the_setting_that_answers_it():
    hint = core.explain_failure(u"The family is connected in a network and can no longer keep "
                                u"the connectivity. Disconnect the family from the network?")
    assert u"Let Revit disconnect a family it cannot keep" in hint, hint
    short = core.explain_failure(u"Line is too short.")
    assert u"shorter than the fittings the new size needs" in short, short


# ============================================================
# Re-apply Type
# ============================================================

@check
def only_fittings_wholly_on_the_selection_and_one_type_are_reapplied():
    fittings = {
        10: [(1, 500), (2, 500)],          # both selected, one type: re-applied
        11: [(2, 500), (9, 500)],          # joins a pipe not selected
        12: [(1, 500), (3, 600)],          # joins two types
        13: [(3, 600), (3, 600)],          # a single pipe's end fitting
        14: [],                            # joins nothing readable
    }
    plan, left = core.reapply_plan(fittings, [1, 2, 3])
    assert plan == {10: 500, 13: 600}, plan
    assert left == {u"not_selected": 1, u"mixed_types": 1}, left


@check
def reapply_swaps_what_the_routing_preferences_call_for():
    ops = _load_ops()
    doc = _Doc()

    def pipe(number):
        e = _Element(number, {}, None, u"pipe")
        e.GetTypeId = lambda: _Id(500)
        return doc.add(e)
    p1, p2, p9 = pipe(1), pipe(2), pipe(9)
    swapped = []

    def fitting(number, symbol):
        e = _Element(number, {}, None, u"fitting")
        e.symbol = symbol
        e.GetTypeId = lambda: _Id(e.symbol)

        def change(new_id):
            e.symbol = new_id.Value
            swapped.append(number)
        e.ChangeTypeId = change
        return doc.add(e)
    wrong = fitting(10, 700)            # between 1 and 2, the wrong family
    right = fitting(11, 800)            # between 1 and 2, already right
    edge = fitting(12, 700)             # between 2 and 9 - 9 is not selected
    for f in (wrong, right):
        _link(p1, f)
        _link(f, p2)
    _link(p2, edge)
    _link(edge, p9)
    doc.add(_Element(500, {}))           # the pipe type
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    ops.committed = lambda status: True
    ops.borrow = lambda d, ids: {}
    ops.snapshot_attached = lambda d, ids, retain: {}
    ops.restore_pass = lambda d, a, b, data: None
    ops.routing_part_for = lambda pipe_type, f: (_Id(800), u"")
    ops.model.neighbours = lambda e: list(e.links)
    ops.model.is_curve = lambda e: e.kind == u"pipe"
    ops.model.is_fitting = lambda e: e.kind == u"fitting"
    ops.model.connected_count = lambda e: len(e.links)
    app = _Bag()
    app.ActiveUIDocument = _Bag()
    app.ActiveUIDocument.Document = doc
    result = ops.Result()
    ops.reapply_job([1, 2], core.DomainView(dict(core.DEFAULTS), u"pipe").resolved())(app, result)
    d = result.data
    assert swapped == [10] and wrong.symbol == 800, swapped
    assert edge.symbol == 700                               # joins an unselected pipe
    assert d[u"fittings_swapped"] == 1 and d[u"fittings_already"] == 1, d
    assert d[u"not_selected"] == 1 and d[u"pipes"] == 2, d
    assert _Group.last.state == u"assimilated"


# ============================================================
# selecting across groups
# ============================================================

@check
def a_plain_click_keeps_only_the_group_clicked_in():
    assert core.groups_to_clear([3, 0, 2, 5], 2, False) == [0, 3]
    assert core.groups_to_clear([3, 0, 2, 5], 2, True) == []          # Ctrl adds
    assert core.groups_to_clear([0, 4], 1, False) == []
    assert core.groups_to_clear([], 0, False) == []


@check
def a_traceback_becomes_rows_you_can_read():
    text = (u'Traceback (most recent call last):\n'
            u'  File "C:\\x\\msm_ops.py", line 187, in run_job\n'
            u'    job(uiapp, result)\n'
            u'  File "C:\\x\\msm_ops.py", line 1204, in job\n'
            u'    _close_groups(doc, opened, data)\n'
            u"TypeError: 'NoneType' object is not subscriptable")
    rows = core.error_rows(text)
    assert rows[0] == (u"message", u"TypeError: 'NoneType' object is not subscriptable"), rows
    assert rows[-1] == (u"at", u"msm_ops.py line 1204, in job - _close_groups(doc, opened, data)")
    assert len(rows) <= 5
    assert core.error_rows(u"") == [] and core.error_rows(None) == []


@check
def a_group_closes_with_what_revit_left_behind():
    """Changing a pipe's type makes Revit delete and recreate fittings: the
    ids the group was opened with are not the ids it closes with."""
    members = [1, 2, 3, 4]
    alive = [1, 2, 4]                       # Revit deleted 3
    assert core.group_members_now(members, alive, [99]) == [1, 2, 4, 99]
    assert core.group_members_now(members, alive, []) == [1, 2, 4]
    assert core.group_members_now(members, alive, [2, 99]) == [1, 2, 4, 99]
    assert core.group_members_now([], [], []) == []


def _rebuild_scene(refuse=()):
    ops = _load_ops()
    doc = _Doc()
    attempts = []

    class _Create(object):
        def NewGroup(self, ids):
            attempts.append(list(ids))
            bad = [n for n in ids if n in refuse]
            if bad:
                raise Exception(u"The element {0} is not valid".format(bad[0]))
            group = _Bag()
            group.GroupType = _Bag()
            return group
    doc.Create = _Create()
    for number in (1, 2, 4, 99):
        doc.add(_Element(number, {}, None, u"pipe"))
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    ops.id_list = lambda n: list(n)
    ops.committed = lambda status: True
    ops._group_replacements = lambda d, alive, known: [99]
    data = {u"failed": [], u"groups_reclosed": []}
    item = {u"name": u"WC Pod", u"members": [1, 2, 3, 4]}
    group = ops._rebuild_group(doc, item, data)
    return group, attempts, data


@check
def a_group_is_always_put_back_together():
    group, attempts, data = _rebuild_scene()
    assert group is not None
    assert attempts == [[1, 2, 4, 99]], attempts        # 3 is gone, 99 is Revit's replacement
    assert [x for x in data[u"groups_reclosed"] if u"Revit replaced" in x]
    # an element Revit will not take is dropped and the rest still group
    group, attempts, data = _rebuild_scene(refuse=(99,))
    assert group is not None and attempts == [[1, 2, 4, 99], [1, 2, 4]], attempts
    assert [x for x in data[u"failed"] if u"would not take back" in x], data[u"failed"]
    # nothing groupable at all: the elements are named, never left silently loose
    group, attempts, data = _rebuild_scene(refuse=(1, 2, 4, 99))
    assert group is None
    assert [x for x in data[u"failed"] if u"left ungrouped" in x], data[u"failed"]


@check
def an_accessory_past_a_fitting_is_still_found():
    """A valve usually sits past an elbow or a tee, not against the pipe:
    looking only at what touches the pipe found none at all."""
    ops = _load_ops()
    doc = _Doc()
    pipe = doc.add(_Element(1, {}, None, u"pipe"))
    elbow = doc.add(_Element(2, {}, None, u"fitting"))
    valve = doc.add(_Element(3, {}, None, u"accessory"))
    far = doc.add(_Element(4, {}, None, u"accessory"))
    other = doc.add(_Element(5, {}, None, u"fitting"))
    _link(pipe, elbow)
    _link(elbow, valve)
    _link(valve, other)
    _link(other, far)                      # two fittings away: out of reach
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    ops.model.neighbours = lambda e: list(e.links)
    ops.model.is_fitting = lambda e: e.kind == u"fitting"
    ops.model.is_fitting_or_accessory = lambda e: e.kind in (u"fitting", u"accessory")
    found = [e.Id.Value for e in ops._accessories_near(doc, 1)]
    assert found == [3], found


# ============================================================
# Pick System
# ============================================================

@check
def a_picked_element_selects_its_whole_system():
    def rec(eid, service, run, size):
        return {u"id": eid, u"system_type": service, u"system": run, u"size_mm": size}
    records = [rec(1, u"VRF", u"Run 1", 100.0), rec(2, u"VRF", u"Run 1", 200.0),
               rec(3, u"VRF", u"Run 3", 100.0), rec(4, u"ICT", u"Run 1", 100.0)]
    # the whole of Run 1 in VRF, whichever size row it is on - not ICT's Run 1
    assert core.picked_system_ids(records, [2]) == [1, 2]
    # a fitting: found through the trays it joins
    assert core.picked_system_ids(records, [99, 3]) == [3]
    assert core.picked_system_ids(records, [99]) == []
    assert core.KIND_DOMAIN[u"conduit"] == u"cont" and core.KIND_DOMAIN[u"duct"] == u"duct"


# ============================================================
# keeping the selection through a refresh
# ============================================================

@check
def selection_found_again_after_a_type_change():
    before = core.build_groups(RECORDS)[u"Cold Water"]
    picked = [r for r in before if r[u"system"] == u"CWS 1" and r[u"size"] == u"22"]
    keys = [r[u"key"] for r in picked]
    ids = core.selected_ids(picked)
    changed = [dict(r) for r in RECORDS]
    for r in changed:
        if r[u"id"] in (1, 2):
            r[u"ptype"] = u"MLCP"
    after = core.build_groups(changed)[u"Cold Water"]
    again = core.rows_to_reselect(after, keys, ids)
    assert len(again) == 1, again
    assert again[0][u"ptype"] == u"MLCP" and sorted(again[0][u"ids"]) == [1, 2]
    assert again[0][u"key"] not in keys          # found by pipe id, not by key


@check
def selection_found_by_key_when_nothing_changed():
    rows = core.build_groups(RECORDS)[u"Cold Water"]
    again = core.rows_to_reselect(rows, [rows[0][u"key"]], [])
    assert again == [rows[0]]
    assert core.rows_to_reselect(rows, [], []) == []


@check
def filters_loosened_only_as_far_as_the_selection_needs():
    rows = core.build_groups(RECORDS)[u"Cold Water"]
    mlcp = [r for r in rows if r[u"ptype"] == u"MLCP"]
    kw, ticks, fields, hides = core.loosen_for(
        mlcp, {u"ptype": u"copper", u"system": u"cws"},
        {u"ptype": {u"Copper"}, u"size": None}, u"")
    assert kw[u"ptype"] == u"" and kw[u"system"] == u"cws"
    assert ticks[u"ptype"] == {u"Copper", u"MLCP"} and ticks[u"size"] is None
    assert fields == [u"ptype"], fields
    assert not hides
    assert core.filter_rows(mlcp, kw, ticks) == mlcp


@check
def loosening_does_not_touch_the_saved_filters():
    rows = core.build_groups(RECORDS)[u"Cold Water"]
    saved = {u"ptype": {u"Copper"}}
    core.loosen_for(rows, {}, saved, u"")
    assert saved == {u"ptype": {u"Copper"}}


@check
def search_box_hiding_the_selection_is_reported():
    rows = core.build_groups(RECORDS)[u"Cold Water"]
    assert core.loosen_for(rows[:1], {}, {}, u"hot water")[3]
    assert not core.loosen_for(rows[:1], {}, {}, u"cold")[3]


@check
def filters_carry_over_only_when_the_row_layout_is_the_same():
    a = dict(core.DEFAULTS)
    b = dict(core.DEFAULTS)
    assert core.layout_signature(a) == core.layout_signature(b)
    b[u"split_size"] = u"0"
    assert core.layout_signature(a) != core.layout_signature(b)
    b = dict(core.DEFAULTS)
    b[u"theme"] = u"light"
    assert core.layout_signature(a) == core.layout_signature(b)


# ============================================================
# the dead-engine prompt
# ============================================================

@check
def modal_offered_only_for_a_live_note_from_this_version():
    v = core.__version__
    note = core.flag_text(v)
    assert core.should_offer_modal(note, v, u"modeless")
    assert core.should_offer_modal(note + u"\n", v, u"modeless")
    assert not core.should_offer_modal(None, v, u"modeless")
    assert not core.should_offer_modal(u"opened", v, u"modeless")          # pre-1.3.0 note
    assert not core.should_offer_modal(core.flag_text(u"0.0.1"), v, u"modeless")
    assert not core.should_offer_modal(note, v, u"modal")


# ============================================================
# 3D view
# ============================================================

@check
def default_3d_prefers_the_users_own():
    names = [u"{3D}", u"{3D - drew}"]
    assert core.pick_default_3d(names, u"drew", True) == u"{3D - drew}"
    assert core.pick_default_3d(names, u"drew", False) == u"{3D}"
    assert core.pick_default_3d([u"{3D}"], u"drew", True) == u"{3D}"
    assert core.pick_default_3d([u"Coord 3D"], u"drew", True) is None


@check
def default_view_always_gets_its_section_box_fitted():
    off = {u"isolate_section_box": u"0"}
    on = {u"isolate_section_box": u"1"}
    assert core.fit_section_box(True, off)
    assert core.fit_section_box(True, on)
    assert core.fit_section_box(True, None)
    assert not core.fit_section_box(False, off)
    assert core.fit_section_box(False, on)


@check
def isolate_keeps_only_the_picked_systems():
    keep = core.keep_for_isolate
    # a picked pipe always stays
    assert keep(True, False, [], [], False)
    # a fitting on a picked system
    assert keep(False, True, [10], [10, 11], True)
    # a valve at the boundary, on the next system along, touching a picked pipe
    assert not keep(False, True, [12], [10], True)
    # a fitting that sits between a picked system and another one
    assert keep(False, True, [10, 12], [10], True)
    # equipment on the picked system is not pipework
    assert not keep(False, False, [10], [10], True)
    # a fitting that reports no system comes in only by touching a picked pipe
    assert keep(False, True, [], [10], True)
    assert not keep(False, True, [], [10], False)
    assert not keep(False, True, [0, None], [10], False)


@check
def replaced_fitting_found_by_position():
    tol = core.mm_to_feet(5.0)
    here = (1.0, 2.0, 3.0)
    near = (1.0 + core.mm_to_feet(2.0), 2.0, 3.0)
    far = (1.0 + core.mm_to_feet(50.0), 2.0, 3.0)
    assert core.nearest_within(here, [(7, far), (8, near)], tol) == 8
    assert core.nearest_within(here, [(7, far)], tol) is None
    assert core.nearest_within(None, [(8, near)], tol) is None
    assert core.nearest_within(here, [(9, None), (8, near)], tol) == 8
    closer = (1.0 + core.mm_to_feet(1.0), 2.0, 3.0)
    assert core.nearest_within(here, [(8, near), (6, closer)], tol) == 6


# ============================================================
# changing pipe type
# ============================================================

@check
def restore_plans_only_what_moved():
    snap = {u"Comments": (u"String", u"riser A"), u"Mark": (u"String", u"P1"),
            u"Offset": (u"Double", 1.0)}
    back = {u"Comments": (u"String", u""), u"Mark": (u"String", u"P1"),
            u"Offset": (u"Double", 1.0 + 1e-9)}
    assert core.plan_restore(snap, back) == [u"Comments"]


@check
def restore_includes_a_parameter_that_vanished():
    snap = {u"BGL_Service": (u"String", u"CWS")}
    assert core.plan_restore(snap, {}) == [u"BGL_Service"]


@check
def blank_and_none_strings_are_equal():
    assert core.values_equal(None, u"", u"String")
    assert not core.values_equal(u"a", u"b", u"String")


@check
def fitting_swapped_only_when_every_neighbour_changes():
    assert core.fitting_swap_allowed([1, 2], [1, 2, 3])
    assert not core.fitting_swap_allowed([1, 9], [1, 2, 3])
    assert not core.fitting_swap_allowed([], [1, 2])
    assert not core.fitting_swap_allowed([None], [1])


@check
def routing_groups():
    assert core.routing_group_for(u"Elbow") == u"Elbows"
    assert core.routing_group_for(u"Tee") == u"Junctions"
    assert core.routing_group_for(u"Transition") == u"Transitions"
    assert core.routing_group_for(u"MultiPort") is None


@check
def chunks_cover_everything_once():
    got = core.chunks(range(53), 25)
    assert [len(c) for c in got] == [25, 25, 3]
    assert sum(got, []) == list(range(53))


@check
def summary_names_the_retained_parameters():
    text = core.change_summary(12, [u"CWS 1"], [u"Copper"], u"MLCP",
                               [u"Comments", u"Mark"], True, True, 4)
    assert u"12 pipes" in text and u"Comments, Mark" in text and u"MLCP" in text
    text = core.change_summary(1, [], [], u"MLCP", [], False, False, 0)
    assert u"1 pipe " in text and u"none ticked" in text


@check
def results_window_only_when_something_needs_a_look():
    assert not core.results_need_a_look({u"changed": 10})
    assert core.results_need_a_look({u"changed": 9, u"locked": [u"x"]})
    assert core.results_need_a_look({u"not_restored": [u"Comments"]})


# ============================================================
# the final restore pass, against a fake Revit
# ============================================================

class _Id(object):
    def __init__(self, value):
        self.Value = value


class _List(list):
    @property
    def Count(self):
        return len(self)


class _Storage(object):
    String = u"String"
    Integer = u"Integer"
    Double = u"Double"
    ElementId = u"ElementId"


class _Param(object):
    StorageType = u"String"

    def __init__(self, element, name):
        self.element = element
        self.name = name

    @property
    def IsReadOnly(self):
        return self.name in self.element.readonly

    def AsString(self):
        return self.element.values.get(self.name)

    def Set(self, value):
        if self.IsReadOnly:
            raise Exception(u"read only")
        self.element.values[self.name] = value
        return True


class _Element(object):
    def __init__(self, number, values, point=None, kind=u"pipe"):
        self.Id = _Id(number)
        self.values = dict(values)
        self.readonly = set()
        self.point = point
        self.kind = kind
        self.links = []
        self.IsValidObject = True

    def GetParameters(self, name):
        return _List([_Param(self, name)] if name in self.values else [])

    def LookupParameter(self, name):
        return _Param(self, name) if name in self.values else None


class _Doc(object):
    def __init__(self):
        self.elements = {}
        self.commit_hooks = []

    def add(self, element):
        self.elements[element.Id.Value] = element
        return element

    def delete(self, number):
        element = self.elements.pop(number)
        element.IsValidObject = False

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)

    def Regenerate(self):
        pass

    def commit(self):
        hooks, self.commit_hooks = self.commit_hooks, []
        for hook in hooks:
            hook()


class _Transaction(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.started = False
        self.ended = False

    def GetFailureHandlingOptions(self):
        raise Exception(u"not in the fake")

    def Start(self):
        self.started = True

    def Commit(self):
        self.ended = True
        self.doc.commit()
        return u"TransactionStatus.Committed"

    def RollBack(self):
        self.ended = True

    def HasStarted(self):
        return self.started

    def HasEnded(self):
        return self.ended


_OPS_PATCH = None


class _Group(object):
    """A TransactionGroup that records whether it was kept or thrown away."""
    last = None

    def __init__(self, doc, name):
        self.doc = doc
        self.state = u"new"
        _Group.last = self

    def Start(self):
        self.state = u"started"

    def Assimilate(self):
        self.state = u"assimilated"

    def RollBack(self):
        self.state = u"rolled back"

    def HasStarted(self):
        return self.state != u"new"

    def HasEnded(self):
        return self.state in (u"assimilated", u"rolled back")


def _load_ops():
    """msm_ops against the fake, sharing this file's msm_core so a regression
    put into core reaches it too."""
    for name in (u"msm_ops", u"msm_model", u"msm_clr"):
        sys.modules.pop(name, None)
    bench_stubs.build({u"Autodesk.Revit.DB": {u"Transaction": _Transaction,
                                             u"TransactionGroup": _Group,
                                             u"StorageType": _Storage}})
    sys.modules[u"msm_core"] = core
    if _OPS_PATCH:
        import types
        source = open(os.path.join(HERE, u"msm_ops.py")).read()
        before, after = _OPS_PATCH
        if before not in source:
            raise AssertionError(u"selftest anchor missing in msm_ops.py: " + before)
        ops = types.ModuleType(u"msm_ops")
        ops.__file__ = os.path.join(HERE, u"msm_ops.py")
        sys.modules[u"msm_ops"] = ops
        exec(compile(source.replace(before, after, 1), ops.__file__, u"exec"), ops.__dict__)
    else:
        import msm_ops as ops
    ops.make_id = lambda n: _Id(n)
    ops.eid_value = lambda i: i.Value
    m = ops.model
    m.make_id = lambda n: _Id(n)
    m.eid_value = lambda i: i.Value
    m.is_live = lambda e: e is not None and e.IsValidObject
    m.neighbours = lambda e: [x for x in e.links if x.IsValidObject]
    m.is_pipe = lambda e: e.kind == u"pipe"
    m.is_fitting_or_accessory = lambda e: e.kind in (u"fitting", u"accessory")
    m.point_of = lambda e: e.point
    return ops


def _link(a, b):
    a.links.append(b)
    b.links.append(a)


def _scenario():
    ops = _load_ops()
    doc = _Doc()
    pipe = doc.add(_Element(1, {u"Comments": u"riser A", u"Mark": u"P1"}))
    other = doc.add(_Element(2, {u"Comments": u"riser A"}))
    fitting = doc.add(_Element(5, {u"Comments": u"F5"}, (0.0, 0.0, 0.0), u"fitting"))
    valve = doc.add(_Element(7, {u"Mark": u"V1"}, (3.0, 0.0, 0.0), u"accessory"))
    _link(pipe, fitting)
    _link(other, fitting)
    _link(pipe, valve)
    retain = [u"Comments", u"Mark"]
    pipe_snaps = {1: ops.snapshot_params(pipe, retain)}
    attached = ops.snapshot_attached(doc, [1], retain)
    data = {u"not_restored": [], u"values_restored": 0, u"replaced_fittings": 0,
            u"failed": []}
    return ops, doc, pipe, other, fitting, valve, pipe_snaps, attached, data


@check
def retained_values_go_back_after_the_type_change():
    ops, doc, pipe, other, fitting, valve, snaps, attached, data = _scenario()
    assert sorted(attached) == [5, 7], attached
    # the type change: values reset, and Revit replaces the fitting
    pipe.values[u"Comments"] = u""
    valve.values[u"Mark"] = u""
    doc.delete(5)
    new_fitting = doc.add(_Element(6, {u"Comments": u""},
                                   (core.mm_to_feet(1.0), 0.0, 0.0), u"fitting"))
    _link(pipe, new_fitting)
    _link(other, new_fitting)
    ops.restore_pass(doc, snaps, attached, data)
    assert pipe.values[u"Comments"] == u"riser A"
    assert pipe.values[u"Mark"] == u"P1"
    assert valve.values[u"Mark"] == u"V1"
    assert new_fitting.values[u"Comments"] == u"F5"
    assert data[u"replaced_fittings"] == 1
    assert data[u"not_restored"] == [], data[u"not_restored"]
    assert data[u"values_restored"] == 3, data[u"values_restored"]


@check
def a_value_reset_by_the_commit_is_written_again():
    ops, doc, pipe, other, fitting, valve, snaps, attached, data = _scenario()
    pipe.values[u"Comments"] = u""

    def regenerate_resets_it():
        pipe.values[u"Comments"] = u""
    doc.commit_hooks.append(regenerate_resets_it)
    ops.restore_pass(doc, snaps, attached, data)
    assert pipe.values[u"Comments"] == u"riser A"
    assert data[u"not_restored"] == [], data[u"not_restored"]


@check
def a_value_that_will_not_go_back_is_named():
    ops, doc, pipe, other, fitting, valve, snaps, attached, data = _scenario()
    pipe.values[u"Mark"] = u"X"
    pipe.readonly.add(u"Mark")
    doc.delete(5)                       # replaced, and the new one is nowhere near
    ops.restore_pass(doc, snaps, attached, data)
    joined = u" | ".join(data[u"not_restored"])
    assert u"1 - Mark (Revit refused the write)" in joined, joined
    assert u"5 - fitting was replaced" in joined, joined


@check
def untouched_values_are_not_rewritten():
    ops, doc, pipe, other, fitting, valve, snaps, attached, data = _scenario()
    ops.restore_pass(doc, snaps, attached, data)
    assert data[u"values_restored"] == 0
    assert data[u"not_restored"] == []


# ============================================================
# settings
# ============================================================

@check
def settings_round_trip():
    values = core.DomainView(dict(core.DEFAULTS), u"pipe")
    values[u"retain"] = core.join_list([u"Comments", u"BGL_Service|Code"])
    values[u"theme"] = u"light"
    back = core.DomainView(core.parse_settings(core.format_settings(values)), u"pipe")
    assert back[u"theme"] == u"light"
    assert core.split_list(back[u"retain"]) == [u"Comments", u"BGL_Service/Code"]


@check
def damaged_settings_fall_back_key_by_key():
    back = core.parse_settings(u"theme=dark\ngarbage line\nunknown=1\nsection_margin_mm=a=b\n")
    assert back[u"theme"] == u"dark"
    assert u"unknown" not in back
    assert back[u"section_margin_mm"] == u"a=b"
    assert core.to_float(back[u"section_margin_mm"], 300.0) == 300.0
    assert back[u"pipe.scope"] == core.DEFAULTS[u"pipe.scope"]


@check
def migrations_reset_listed_keys():
    saved = dict(core.MIGRATIONS)
    try:
        core.MIGRATIONS.clear()
        core.MIGRATIONS[3] = [u"pipe.retain"]
        back = core.parse_settings(u"settings_version=2\npipe.retain=Old\n")
        assert back[u"pipe.retain"] == core.DEFAULTS[u"pipe.retain"]
        back = core.parse_settings(u"settings_version=3\npipe.retain=New\n")
        assert back[u"pipe.retain"] == u"New"
    finally:
        core.MIGRATIONS.clear()
        core.MIGRATIONS.update(saved)


@check
def settings_save_and_load_from_disk():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, u"sub", core.SETTINGS_NAME)
    values = core.DomainView(dict(core.DEFAULTS), u"duct")
    values[u"keep_size"] = u"0"
    assert core.save_settings(values, path)
    assert core.load_settings(path)[u"duct.keep_size"] == u"0"
    assert core.load_settings(path)[u"pipe.keep_size"] == u"1"
    assert core.load_settings(os.path.join(folder, u"missing.txt")) == core.DEFAULTS


# ============================================================
# runner and selftest
# ============================================================

# ============================================================
# shrink to the taskbar: the drawer's arithmetic, and whole slides
# driven against a stand-in window
# ============================================================

@check
def drawer_easing_is_cubic_out_and_clamped():
    assert core.ease_out(0) == 0.0 and core.ease_out(1) == 1.0
    assert abs(core.ease_out(0.5) - 0.875) < 1e-9, core.ease_out(0.5)
    assert core.ease_out(-1) == 0.0 and core.ease_out(2) == 1.0
    steps = [core.ease_out(i / 10.0) for i in range(11)]
    assert steps == sorted(steps)
    assert core.slide_value(100, 900, 1.0) == 900
    assert core.slide_progress(1000, 1140) == 0.5
    assert core.slide_progress(1000, 5000) == 1.0


@check
def drawer_bar_keeps_its_frame():
    assert core.bar_height(1, 48) == 50
    assert core.bar_height(None, 48) == 48
    assert core.bar_height(-3, 48) == 48


@check
def drawer_parks_above_the_taskbar_on_its_own_screen():
    # primary 1080p with a 40px taskbar
    assert core.parked_top(0, 1040, 50) == 1040 - 8 - 50
    # a monitor ABOVE the primary: negative working-area top
    assert core.parked_top(0 - 1080, 1040, 50) == 0 - 1080 + 1040 - 8 - 50
    # stacked bars sit above the ones parked first, a gap apart
    below = core.stacked_below([50])
    assert below == 54
    assert core.parked_top(0, 1040, 40, below) == 1040 - 8 - 40 - 54
    # never parks above the top of the screen
    assert core.parked_top(100, 60, 50, 500) == 100


@check
def drawer_reopens_where_it_was_or_up_from_a_moved_bar():
    saved = (200, 150, 1180, 780)
    area = (0, 0, 1920, 1040)
    parked = (200, 982)
    # not moved (or within the tolerance): exactly where it was
    assert core.reopen_bounds(saved, parked, (200, 982), 50, area) == (200, 150)
    assert core.reopen_bounds(saved, parked, (201, 983), 50, area) == (200, 150)
    assert not core.bar_moved(parked, (202, 980))
    assert core.bar_moved(parked, (260, 982))
    # dragged to the right: opens upward from the bar, bottom on the bar's
    assert core.reopen_bounds(saved, parked, (600, 900), 50, area) == (600, 900 + 50 - 780)
    # dragged near the top: kept on the screen rather than opening off it
    assert core.reopen_bounds(saved, parked, (600, 20), 50, area) == (600, 0)
    # dragged to the far right: kept on the screen
    assert core.reopen_bounds(saved, parked, (1500, 900), 50, area)[0] == 1920 - 1180
    # dragged onto a monitor above the primary
    upper = (0, -1080, 1920, 1040)
    left, top = core.reopen_bounds(saved, parked, (300, -200), 50, upper)
    assert (left, top) == (300, -200 + 50 - 780)


_UI_PATCH = None


def _load_ui():
    for name in (u"msm_ui", u"msm_theme", u"msm_clr"):
        sys.modules.pop(name, None)
    bench_stubs.build()
    sys.modules[u"msm_core"] = core
    if _UI_PATCH:
        import types
        source = open(os.path.join(HERE, u"msm_ui.py")).read()
        before, after = _UI_PATCH
        if before not in source:
            raise AssertionError(u"selftest anchor missing in msm_ui.py: " + before)
        m = types.ModuleType(u"msm_ui")
        m.__file__ = os.path.join(HERE, u"msm_ui.py")
        sys.modules[u"msm_ui"] = m
        exec(compile(source.replace(before, after, 1), m.__file__, u"exec"), m.__dict__)
        return m
    import msm_ui
    return msm_ui


class _Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in list(self.handlers):
            handler(None, None)


class _El(object):
    def __init__(self, ui, name, height=0.0, children=None):
        self.name = name
        self.Visibility = ui.Visibility.Visible
        self.ActualHeight = height
        self.Height = float(u"nan")
        self.VerticalAlignment = ui.VerticalAlignment.Stretch
        self.Parent = None
        if children is not None:
            self.Children = children
            for child in children:
                child.Parent = self

    def __repr__(self):
        return self.name


class _Win(object):
    def __init__(self, ui, top=150, height=780, min_height=560, size=None):
        self.ui = ui
        self.Left, self.Top = 200.0, float(top)
        self.ActualWidth = 1180.0
        self._height = float(height)
        self.MinHeight = min_height
        self.SizeToContent = size if size is not None else ui.SizeToContent.Manual
        self.Owner = None
        self.Closed = _Event()
        self.released = []
        self.names = {}
        self.header = _El(ui, u"header", 48)
        self.body = _El(ui, u"body", 600)
        self.footer = _El(ui, u"footer", 40)
        self.overlay = _El(ui, u"overlay", 0)
        self.overlay.Visibility = ui.Visibility.Collapsed   # a closed prompt
        inner = _El(ui, u"inner", height - 2,
                    [self.header, self.body, self.footer, self.overlay])
        border = _El(ui, u"border", height - 2)
        border.Child = inner
        inner.Parent = border
        self.grips = _El(ui, u"grips", height)
        self.Content = _El(ui, u"outer", height, [border, self.grips])
        self.Content.Parent = self
        self.button = _El(ui, u"button")
        self.button.Click = _Event()
        self.button.ToolTip = u""
        self.names = {u"ShrinkGlyph": _El(ui, u"shrink"), u"ExpandGlyph": _El(ui, u"expand"),
                      u"GripLayer": self.grips}
        self.names[u"ExpandGlyph"].Visibility = ui.Visibility.Collapsed

    @property
    def Height(self):
        return self._height

    @Height.setter
    def Height(self, value):
        self._height = float(value)

    @property
    def ActualHeight(self):
        return self._height

    def FindName(self, name):
        return self.names.get(name)

    def BeginAnimation(self, prop, animation):
        if animation is None:
            self.released.append(prop)


class _Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Timer(object):
    def __init__(self, window, tick):
        self.tick = tick
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    def run(self, clock, ms):
        """Tick until the slide lands or the time runs out."""
        end = clock.now + ms
        while self.running and clock.now < end:
            clock.now += 15
            self.tick(None, None)


def _drawer(ui, window, clock, area=(0.0, 0.0, 1920.0, 1040.0)):
    timers = []

    def make_timer(w, tick):
        timer = _Timer(w, tick)
        timers.append(timer)
        return timer
    drawer = ui.WindowDrawer(window, window.header, window.button,
                             timer_factory=make_timer, clock=clock,
                             area_of=lambda w: area, frame_of=lambda w, h: 1.0)
    return drawer, timers


@check
def drawer_slides_down_to_a_bar_and_back_exactly():
    ui = _load_ui()
    del ui._DRAWERS[:]
    vis = ui.Visibility
    w = _Win(ui)
    clock = _Clock()
    drawer, timers = _drawer(ui, w, clock)
    assert w.button.Click.handlers, u"the shrink button was never wired"
    w.button.Click.fire()
    # the slide has started: the traps are set before the first frame
    assert drawer.parked
    assert w.MinHeight == 0, u"MinHeight left in place vetoes the slide"
    assert w.Content.Height == 780 and w.Content.VerticalAlignment == ui.VerticalAlignment.Top, \
        u"the body is not pinned for the slide"
    assert w.grips.Visibility == vis.Collapsed, u"the resize grips were not parked"
    assert w.names[u"ExpandGlyph"].Visibility == vis.Visible, u"no green up arrow"
    assert w.names[u"ShrinkGlyph"].Visibility == vis.Collapsed
    clock.now += 140
    drawer.frame()
    assert 150 < w.Top < 982 and 50 < w.Height < 780, (w.Top, w.Height)
    timers[0].run(clock, 400)
    # landed: only the header, floating 8 above the taskbar
    assert w.Height == 50, w.Height
    assert w.Top == 1040 - 8 - 50, w.Top
    assert not timers[0].running, u"the timer was left running"
    assert ui.Window.TopProperty in w.released and ui.Window.HeightProperty in w.released, \
        u"Top / Height were never released"
    assert w.body.Visibility == vis.Collapsed and w.footer.Visibility == vis.Collapsed
    assert w.header.Visibility == vis.Visible
    assert w.Content.VerticalAlignment == ui.VerticalAlignment.Stretch, \
        u"the parked body was left pinned"
    # back up
    w.button.Click.fire()
    assert not drawer.parked
    timers[0].run(clock, 400)
    assert (w.Left, w.Top, w.Height) == (200, 150, 780), (w.Left, w.Top, w.Height)
    assert w.MinHeight == 560, u"MinHeight was not put back"
    assert w.body.Visibility == vis.Visible and w.footer.Visibility == vis.Visible
    assert w.overlay.Visibility == vis.Collapsed, u"a closed prompt was reopened"
    assert w.grips.Visibility == vis.Visible, u"the grips stayed parked"
    assert w.names[u"ShrinkGlyph"].Visibility == vis.Visible
    assert w.names[u"ExpandGlyph"].Visibility == vis.Collapsed
    assert w.Content.VerticalAlignment == ui.VerticalAlignment.Stretch


@check
def drawer_relaxes_size_to_content_and_puts_it_back():
    ui = _load_ui()
    del ui._DRAWERS[:]
    w = _Win(ui, top=300, height=420, min_height=0, size=ui.SizeToContent.Height)
    clock = _Clock()
    drawer, timers = _drawer(ui, w, clock)
    drawer.shrink()
    assert w.SizeToContent == ui.SizeToContent.Manual, u"SizeToContent vetoes the slide"
    timers[0].run(clock, 400)
    assert w.Height == 50
    drawer.reopen()
    timers[0].run(clock, 400)
    assert w.SizeToContent == ui.SizeToContent.Height
    assert w.Height == 420 and w.Top == 300


@check
def drawer_opens_up_from_a_bar_that_was_carried_away():
    ui = _load_ui()
    del ui._DRAWERS[:]
    w = _Win(ui)
    clock = _Clock()
    drawer, timers = _drawer(ui, w, clock)
    drawer.shrink()
    timers[0].run(clock, 400)
    w.Left, w.Top = 600.0, 900.0          # dragged by its bar
    drawer.reopen()
    timers[0].run(clock, 400)
    assert (w.Left, w.Top, w.Height) == (600, 900 + 50 - 780, 780), (w.Left, w.Top)


@check
def drawer_turns_back_mid_slide():
    ui = _load_ui()
    del ui._DRAWERS[:]
    w = _Win(ui)
    clock = _Clock()
    drawer, timers = _drawer(ui, w, clock)
    drawer.shrink()
    clock.now += 100
    drawer.frame()
    drawer.reopen()                       # changed their mind halfway down
    timers[0].run(clock, 400)
    assert (w.Left, w.Top, w.Height, w.MinHeight) == (200, 150, 780, 560)
    assert w.body.Visibility == ui.Visibility.Visible


@check
def drawer_lands_if_the_timer_cannot_start():
    ui = _load_ui()
    del ui._DRAWERS[:]
    w = _Win(ui)

    def no_timer(window, tick):
        raise RuntimeError(u"no dispatcher")
    drawer = ui.WindowDrawer(w, w.header, w.button, timer_factory=no_timer,
                             clock=_Clock(), area_of=lambda x: (0.0, 0.0, 1920.0, 1040.0),
                             frame_of=lambda x, h: 1.0)
    drawer.shrink()
    assert w.Height == 50 and w.Top == 982, (w.Height, w.Top)
    assert ui.Window.HeightProperty in w.released
    drawer.reopen()
    assert w.Height == 780 and w.Top == 150 and w.MinHeight == 560


@check
def drawer_takes_the_owner_down_and_stacks_above_it():
    ui = _load_ui()
    del ui._DRAWERS[:]
    main = _Win(ui)
    clock = _Clock()
    main_drawer, main_timers = _drawer(ui, main, clock)
    dialog = _Win(ui, top=200, height=500, min_height=0, size=ui.SizeToContent.Height)
    dialog.Owner = main
    dialog_drawer, dialog_timers = _drawer(ui, dialog, clock)
    assert dialog_drawer.owner is main_drawer
    dialog_drawer.shrink()
    assert main_drawer.parked, u"the dialog left its owner standing over Revit"
    main_timers[0].run(clock, 400)
    dialog_timers[0].run(clock, 400)
    assert main.Top == 982
    assert dialog.Top == 982 - 54, dialog.Top
    dialog_drawer.reopen()
    assert not main_drawer.parked, u"bringing the dialog back left its owner parked"
    main_timers[0].run(clock, 400)
    dialog_timers[0].run(clock, 400)
    assert main.Top == 150 and dialog.Top == 200
    # closing a parked dialog brings the owner back
    dialog_drawer.shrink()
    main_timers[0].run(clock, 400)
    dialog_timers[0].run(clock, 400)
    dialog.Closed.fire()
    main_timers[0].run(clock, 400)
    assert not main_drawer.parked and main.Top == 150
    assert dialog_drawer not in ui._DRAWERS


def _bad_parked_top(area_top, area_height, bar, below=0.0):
    return max(0.0, area_height - core.DRAWER_CLEAR - bar - below)


def _bad_reopen_bounds(saved, parked_at, bar_at, bar, area):
    return saved[0], saved[1]


def _bad_stacked_below(bars):
    return 0.0


def _bad_ease_out(progress):
    return min(1.0, max(0.0, float(progress)))


def _bad_bar_height(frame_top, header_height):
    return float(header_height or 0.0)


UI_REGRESSIONS = [
    (u"MinHeight not relaxed for the slide",
     (u"        w.MinHeight = 0\n        w.Height = height", u"        w.Height = height")),
    (u"animation never released",
     (u"                w.BeginAnimation(prop, None)", u"                pass")),
    (u"body never pinned",
     (u"            root.VerticalAlignment = VerticalAlignment.Top\n", u"")),
    (u"grips left over the bar",
     (u"            self.grips.Visibility = Visibility.Collapsed\n", u"")),
    (u"hidden panels all made visible",
     (u"                element.Visibility = visibility\n",
      u"                element.Visibility = Visibility.Visible\n")),
    (u"dialog does not take its owner down",
     (u"        if self.owner is not None and not self.owner.parked:\n            self.owner.shrink()",
      u"        pass")),
    (u"button glyph never swapped",
     (u"                expand.Visibility = Visibility.Visible if self.parked else Visibility.Collapsed",
      u"                pass")),
    (u"MinHeight never put back",
     (u"                w.MinHeight = min_height\n", u"")),
]


def run(quiet=False):
    failed = []
    for fn in CHECKS:
        try:
            fn()
        except Exception as error:
            failed.append((fn.__name__, error))
            if not quiet:
                sys.stdout.write(u"FAIL {0}: {1!r}\n".format(fn.__name__, error))
    if not quiet:
        sys.stdout.write(u"{0} checks, {1} failed\n".format(len(CHECKS), len(failed)))
    return failed


def _bad_natural_key(value):
    return u"{0}".format(value or u"").lower()


def _bad_sort_rows(rows, stack):
    ordered = list(rows)
    for field, descending in stack:           # most significant first: wrong
        ordered.sort(key=lambda r, f=field: core.sort_value(r, f), reverse=descending)
    return ordered


def _bad_ticks(all_values, ticked):
    return set(ticked) or None                # nothing ticked -> no filter


def _bad_swap(neighbours, changing):
    return any(n in set(changing) for n in neighbours)


def _bad_tick_values(rows, field, col_keywords=None, col_ticks=None, global_text=u""):
    passing = core.filter_rows(rows, col_keywords, col_ticks, global_text)
    return sorted(set([core.cell_text(r, field) for r in passing]))


def _bad_toggle(stack, field, add_level, max_levels=6):
    return [(field, False)]


def _bad_default_3d(names, user, workshared):
    return u"{3D}" if u"{3D}" in names else None


def _bad_plan_restore(snapshot, readback):
    return [n for n in sorted(snapshot) if n in readback and
            snapshot[n][1] != readback[n][1]]


def _bad_chunks(items, size):
    items = list(items)
    return [items[i:i + size] for i in range(0, len(items) - size + 1, size)]


def _bad_parse(text):
    values = dict(core.DEFAULTS)
    for line in (text or u"").splitlines():
        if u"=" in line:
            key, value = line.split(u"=")[:2]
            values[key.strip()] = value.strip()
    return values


def _bad_format_size(mm):
    try:
        return u"{0}".format(float(mm))
    except Exception:
        return u""


def _bad_fit_section_box(default_view, settings):
    return core.to_bool((settings or {}).get(u"isolate_section_box"))


def _bad_keep_for_isolate(is_selected, category_ok, element_systems,
                         selected_systems, touches_selected):
    return is_selected or (category_ok and touches_selected)


def _bad_nearest_within(point, candidates, tolerance):
    for cid, other in candidates:
        if other is not None:
            return cid
    return None


def _bad_plan_restore_nothing(snapshot, readback):
    return []


def _bad_should_offer_modal(flag_contents, version, window_mode):
    return flag_contents is not None and window_mode != u"modal"


def _bad_rows_to_reselect(rows, keys, ids):
    keys = set(keys or [])
    return [r for r in rows if r.get(u"key") in keys]


def _bad_loosen_for(rows, col_keywords, col_ticks, global_text=u""):
    return dict(col_keywords or {}), dict(col_ticks or {}), [], False


def _bad_loosen_in_place(rows, col_keywords, col_ticks, global_text=u""):
    for row in rows:
        for field, allowed in (col_ticks or {}).items():
            if allowed is not None:
                allowed.add(core.cell_text(row, field))
    return dict(col_keywords or {}), col_ticks, [], False


def _bad_layout_signature(settings):
    return u"same"


def _bad_record_issues(record, group, standards, checks):
    out = {}
    allowed = core.allowed_types(standards, group)
    if (record.get(u"ptype") or u"") not in allowed:      # flags services with no standard
        out[u"standards"] = 1
    if record.get(u"size_ok") is not True:               # flags an unreadable size
        out[u"sizes"] = 1
    return out


def _bad_encode_standards(standards):
    return u";;".join([k + u">>" + u"|".join(v) for k, v in (standards or {}).items()])


def _bad_suggest_type(rows, standards, available):
    for row in rows or []:
        allowed = core.allowed_types(standards, row.get(u"group"))
        if allowed:
            return allowed[0]
    return None


def _bad_only_flagged(rows, on):
    return list(rows)


def _bad_enabled_checks(settings):
    return set([name for name, _label in core.CHECKS
                if core.to_bool((settings or {}).get(u"check_" + name, u"1"))])


def _bad_enabled_checks_any_domain(settings, domain=None):
    if not core.checks_on(settings):
        return set()
    return set([n for n, _l in core.CHECKS
                if core.to_bool((settings or {}).get(u"check_" + n, u"1"))])


def _bad_sizes_equal(before, after, tolerance=1e-6):
    for key, value in (before or {}).items():
        if key in (after or {}) and abs(value - after[key]) > tolerance:
            return False
    return True


def _bad_field_titles(domain=None):
    return dict(core.FIELD_TITLES)


class _BadDomainView(object):
    """Every tab writes the same key - the bug that would make Duct's
    settings overwrite Pipe's."""
    def __init__(self, base, domain):
        self.base = base
        self.domain = domain

    def get(self, key, default=None):
        return self.base.get(core.full_key(u"pipe", key)
                             if key in core.DOMAIN_DEFAULTS else key, default)

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.base[core.full_key(u"pipe", key) if key in core.DOMAIN_DEFAULTS else key] = value

    def copy(self):
        return _BadDomainView(dict(self.base), self.domain)

    def resolved(self):
        return core.DomainView(self.base, u"pipe").resolved()


_real_parse = core.parse_settings


def _bad_parse_no_legacy(text, legacy=False):
    return _real_parse(text, False)


def _bad_parse_mm(text):
    try:
        return float(u"{0}".format(text).replace(u"mm", u"")), u""
    except Exception:
        return None, u""


def _bad_resize_plan(elements, width=None, height=None, diameter=None):
    plan = {}
    for e in elements:
        if e[u"kind"] == u"tray" and width is not None:
            plan[e[u"id"]] = {core.TRAY_WIDTH: width}
    return plan, {u"unchanged": 0, u"no_input": 0}


def _bad_md_cell(value):
    return u"{0}".format(u"" if value is None else value)


def _bad_decode_highlight(text):
    head, tail = u"{0}".format(text).split(u":", 1)
    return int(head), [int(p) for p in tail.split(u"|")]


def _bad_run_members(records, ids, group_by=u"system_type", system_from=u""):
    runs = set([r[u"system"] for r in records if r[u"id"] in set(ids)])
    return sorted([r[u"id"] for r in records if r[u"system"] in runs])


def _bad_ws_group_order(names):
    return sorted(names, key=core.natural_key)


def _bad_workset_rows(systems, pending, names):
    groups, notes = _real_workset_rows(systems, {}, names)
    return groups, notes


_real_workset_rows = core.workset_rows


def _bad_service_scope_ids(records, ids, scope, group_by=u"system_type", system_from=u""):
    return sorted([r[u"id"] for r in records if r.get(u"id") in set(ids)])


_real_workset_tree = core.workset_tree


def _bad_workset_tree(systems, pending, names, grouping=u"type", mixed_only=False):
    return _real_workset_tree(systems, pending, names, grouping, False)


def _bad_filter_choices(choices, text):
    return [c for c in choices if keyword_all(c[0], text)], True


def keyword_all(name, text):
    return (text or u"").strip().lower() in name.lower()


_real_staged_rows = core.staged_rows


def _bad_staged_rows(systems, pending, names):
    shown = core.workset_tree(systems, pending, names, u"type", True)
    return [r for _t, sections in shown for _n, rs, _no in sections for r in rs
            if r[u"key"] in pending]


def _bad_sticky_pick(sections, header_height):
    for index, (top, bottom, is_open) in enumerate(sections):
        if top < 0 and bottom > 0:
            return index, 0.0
    return None, 0.0


def _bad_multi_type_groups(by_group):
    return set(by_group or {})


def _bad_type_summary(counts):
    items = sorted((counts or {}).items())
    return (u", ".join([k for k, _v in items]), False) if items else (u"", False)


def _bad_size_param_names(params, dim):
    return [n for n, v, w in params or [] if w and dim in (n or u"").lower()]


def _bad_fitting_size_targets(trays, tolerance=0.5):
    return dict(trays[0]) if trays else {}

def _bad_views_to_reset(target_id, previous_id):
    return [int(target_id)] if target_id else []


def _bad_default_sort(domain):
    return [(u"system", False)]


def _bad_type_colours(names, count=10):
    return dict((n, hash(n) % count) for n in names or [] if n)


def _bad_picked_system_ids(records, picked, group_by=u"system_type"):
    return sorted(set(picked or []) & set([r[u"id"] for r in records or []]))


def _bad_nest_by_system(rows):
    by = {}
    for row in rows or []:
        by.setdefault(row.get(u"system") or u"", []).append(row)
    return sorted(by.items())


def _bad_reapply_plan(fittings, selected):
    plan = {}
    for fid, joined in (fittings or {}).items():
        if joined:
            plan[fid] = joined[0][1]
    return plan, {u"not_selected": 0, u"mixed_types": 0}


def _bad_pick_allowed(is_link, in_link, on_system, lookup_linked):
    return bool(on_system) or bool(is_link)


def _bad_default_target(size, available):
    available = sorted(available or [])
    return available[0] if available else None


def _bad_size_map_from(rows, choices):
    return dict((n, (choices or {}).get(r[u"key"])) for r in rows or [] for n in r[u"ids"])


def _bad_group_decision(nested, held_by=u""):
    return True, u""


def _bad_align_transform(old_points, new_points):
    old_centre = core.centroid(old_points)
    new_centre = core.centroid(new_points)
    if old_centre is None or new_centre is None:
        return None
    return 0.0, new_centre, core.sub3(old_centre, new_centre)      # never turns


def _bad_groups_to_clear(selected, active, ctrl):
    return []


def _bad_accessory_size_plan(params, old_mm, new_mm, tolerance=0.5):
    return ([(n, new_mm) for n, v, w, i in params or [] if w and v is not None
             and abs(v - old_mm) <= tolerance], [])


def _bad_group_members_now(members, alive, replacements):
    return list(members or [])


def _bad_accessory_named_plan(params, names, new_mm):
    wanted = [n.lower() for n in names or []]
    return ([(n, new_mm) for n, v, w, i in params or [] if (n or u"").lower() in wanted], [])


def _bad_pipes_to_resize(before, size_map, tolerance=0.5):
    return sorted(size_map or {})


def _bad_still_wrong_size(sizes, size_map, tolerance=0.5):
    return sorted(size_map or {})


def _bad_retry_candidates(numbers, failed_lines):
    return list(numbers or [])


REGRESSIONS = [
    (u"parked_top", _bad_parked_top),
    (u"reopen_bounds", _bad_reopen_bounds),
    (u"stacked_below", _bad_stacked_below),
    (u"ease_out", _bad_ease_out),
    (u"bar_height", _bad_bar_height),
    (u"retry_candidates", _bad_retry_candidates),
    (u"still_wrong_size", _bad_still_wrong_size),
    (u"pipes_to_resize", _bad_pipes_to_resize),
    (u"accessory_named_plan", _bad_accessory_named_plan),
    (u"group_members_now", _bad_group_members_now),
    (u"accessory_size_plan", _bad_accessory_size_plan),
    (u"groups_to_clear", _bad_groups_to_clear),
    (u"default_target", _bad_default_target),
    (u"size_map_from", _bad_size_map_from),
    (u"group_decision", _bad_group_decision),
    (u"align_transform", _bad_align_transform),
    (u"pick_allowed", _bad_pick_allowed),
    (u"reapply_plan", _bad_reapply_plan),
    (u"nest_by_system", _bad_nest_by_system),
    (u"picked_system_ids", _bad_picked_system_ids),
    (u"type_colours", _bad_type_colours),
    (u"default_sort", _bad_default_sort),
    (u"views_to_reset", _bad_views_to_reset),
    (u"size_param_names", _bad_size_param_names),
    (u"fitting_size_targets", _bad_fitting_size_targets),
    (u"multi_type_groups", _bad_multi_type_groups),
    (u"type_summary", _bad_type_summary),
    (u"sticky_pick", _bad_sticky_pick),
    (u"staged_rows", _bad_staged_rows),
    (u"filter_choices", _bad_filter_choices),
    (u"workset_tree", _bad_workset_tree),
    (u"ws_group_order", _bad_ws_group_order),
    (u"workset_rows", _bad_workset_rows),
    (u"service_scope_ids", _bad_service_scope_ids),
    (u"run_members", _bad_run_members),
    (u"parse_mm", _bad_parse_mm),
    (u"resize_plan", _bad_resize_plan),
    (u"md_cell", _bad_md_cell),
    (u"decode_highlight", _bad_decode_highlight),
    (u"DomainView", _BadDomainView),
    (u"parse_settings", _bad_parse_no_legacy),
    (u"enabled_checks", _bad_enabled_checks_any_domain),
    (u"sizes_equal", _bad_sizes_equal),
    (u"field_titles", _bad_field_titles),
    (u"enabled_checks", _bad_enabled_checks),
    (u"record_issues", _bad_record_issues),
    (u"encode_standards", _bad_encode_standards),
    (u"suggest_type", _bad_suggest_type),
    (u"only_flagged", _bad_only_flagged),
    (u"rows_to_reselect", _bad_rows_to_reselect),
    (u"loosen_for", _bad_loosen_for),
    (u"loosen_for", _bad_loosen_in_place),
    (u"layout_signature", _bad_layout_signature),
    (u"should_offer_modal", _bad_should_offer_modal),
    (u"plan_restore", _bad_plan_restore_nothing),
    (u"keep_for_isolate", _bad_keep_for_isolate),
    (u"nearest_within", _bad_nearest_within),
    (u"fit_section_box", _bad_fit_section_box),
    (u"natural_key", _bad_natural_key),
    (u"sort_rows", _bad_sort_rows),
    (u"ticks_to_filter", _bad_ticks),
    (u"fitting_swap_allowed", _bad_swap),
    (u"tick_values", _bad_tick_values),
    (u"toggle_sort", _bad_toggle),
    (u"pick_default_3d", _bad_default_3d),
    (u"plan_restore", _bad_plan_restore),
    (u"chunks", _bad_chunks),
    (u"parse_settings", _bad_parse),
    (u"format_size", _bad_format_size),
]


# the restore pass lives in msm_ops, so these break its source instead
OPS_REGRESSIONS = [
    (u"a refused element loses the whole group",
     (u"            refused.append(drop)\n            members = [n for n in members if n != drop]",
      u"            members = []")),
    (u"a group closed twice",
     (u"        if item.get(u\"closed\"):\n            continue", u"        if False:\n            continue")),
    (u"groups closed under a new name",
     (u"                new_type.Name = name", u"                pass")),
    (u"a copy that moved is kept",
     (u"        if core.bbox_moved(other[u\"extents\"], model.extents(copy), GROUP_MOVED_FT):",
      u"        if False:")),
    (u"errors not magenta",
     (u"        ogs.SetProjectionLineColor(Color(*MAGENTA))",
      u"        ogs.SetProjectionLineColor(Color(255, 0, 0))")),
    (u"a linked pick used anyway",
     (u"            if not lookup_linked:\n                result.data[u\"linked_refused\"] = True\n                return",
      u"            if False:\n                pass")),
    (u"a refused or pending request empties the queue",
     (u"        try:\n            self.handler.queue.remove(entry)\n        except ValueError:\n            pass",
      u"        del self.handler.queue[:]")),
    (u"pending treated as a failure",
     (u"        if status == ExternalEventRequest.Accepted or text.endswith(u\"Pending\"):",
      u"        if status == ExternalEventRequest.Accepted:")),
    (u"no second look after isolating",
     (u"    left = core.leftovers(_visible_services(doc, view) or [], ids)\n    if left:",
      u"    left = []\n    if left:")),
    (u"fittings never sized",
     (u"                _size_fitting(fitting, stats if stats is not None else {})",
      u"                pass")),
    (u"already-right elements borrowed and written",
     (u"                if model.workset_number(element.WorksetId) == target:\n"
      u"                    data[u\"already\"] += 1\n                else:\n"
      u"                    work.append((label, number, target))",
      u"                work.append((label, number, target))")),
    (u"every element asked about after borrowing",
     (u"    if held is not None:\n        for number in numbers:",
      u"    if False:\n        for number in numbers:")),
    (u"a refused run tried one tray at a time",
     (u"    if culprits and len(culprits) < len(plan):",
      u"    if False:")),
    (u"success counted before the end",
     (u"            if ok:\n                took.append(number)",
      u"            if True:\n                took.append(number)")),
    (u"a part-moved system counted as moved",
     (u"            if on == len(ids):\n                data[u\"systems_done\"] += 1",
      u"            if on:\n                data[u\"systems_done\"] += 1")),
    (u"another service's fitting renamed with the run",
     (u"                    if not service or service == old:\n                        seen.add(fid)",
      u"                    if True:\n                        seen.add(fid)")),
    (u"an error left to commit",
     (u"        if has_error:\n            return FailureProcessingResult.ProceedWithRollBack",
      u"        if False:\n            return FailureProcessingResult.ProceedWithRollBack")),
    (u"a rolled back run counted as resized",
     (u"    if committed(status):\n        data[u\"runs_done\"] += 1",
      u"    if True:\n        data[u\"runs_done\"] += 1")),
    (u"reset only when the view says it is isolated",
     (u"        try:\n            view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)\n"
      u"        except Exception:\n            pass\n        status = t.Commit()",
      u"        try:\n            if _isolate_mode_on(view):\n"
      u"                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)\n"
      u"        except Exception:\n            pass\n        status = t.Commit()")),
    (u"new isolate stacked on one that would not come off",
     (u"    if _isolate_mode_on(view):\n        result.error = (u\"The earlier isolate",
      u"    if False:\n        result.error = (u\"The earlier isolate")),
    (u"slot fittings matched to the wrong slot",
     (u"                if value == symbol:", u"                if value != symbol:")),
    (u"restore tried only once",
     (u"def restore_pass(doc, pipe_snaps, fit_snaps, data, attempts=2):",
      u"def restore_pass(doc, pipe_snaps, fit_snaps, data, attempts=1):")),
    (u"replaced fitting never looked for",
     (u"    found = core.nearest_within(info.get(u\"point\"), candidates, REPLACED_TOLERANCE_FT)",
      u"    found = None")),
    (u"accessories not snapshotted",
     (u"            if oid in out or not model.is_fitting_or_accessory(owner):\n                continue\n            params",
      u"            if oid in out or owner.kind != u\"fitting\":\n                continue\n            params")),
]


MODEL_REGRESSIONS = [
    (u"a run that crosses into another service",
     (u"                if run_key(owner, settings) != key:\n                    continue\n", u"")),
    (u"a run that walks on through another service's fitting",
     (u"                if service and service != key[1]:\n"
      u"                    continue                    # the boundary: kept, not crossed\n", u"")),
    (u"a door counted as a fitting slot",
     (u"            if category_number(target) not in wanted:\n                continue\n", u"")),
    (u"a run named after its first element, not its lowest",
     (u'        name = u"Run {0}".format(min(members))', u'        name = u"Run {0}".format(members[0])')),
    (u"round ducts read as rectangular",
     (u"        if _double(element, u\"RBS_CURVE_DIAMETER_PARAM\") is not None:\n"
      u"            return [u\"RBS_CURVE_DIAMETER_PARAM\"]\n", u"")),
    (u"branch taps counted as open ends",
     (u"                if u\"{0}\".format(connector.ConnectorType) != u\"End\":\n"
      u"                    continue\n",
      u"")),
    (u"equipment counted as a fitting",
     (u"            if not is_fitting_or_accessory(owner):\n                continue\n"
      u"            oid = eid_value(owner.Id)\n            fittings.append(oid)",
      u"            oid = eid_value(owner.Id)\n            fittings.append(oid)")),
    (u"no size tolerance",
     (u"                if abs(size - diameter) <= SIZE_TOLERANCE_FT:",
      u"                if size == diameter:")),
]


def selftest():
    if run(quiet=True):
        sys.stdout.write(u"selftest needs a clean run first\n")
        return 1
    missed = []
    for name, broken in REGRESSIONS:
        original = getattr(core, name)
        setattr(core, name, broken)
        try:
            caught = run(quiet=True)
        finally:
            setattr(core, name, original)
        if not caught:
            missed.append(name)
            sys.stdout.write(u"MISSED regression in {0}\n".format(name))
    global _OPS_PATCH
    for label, patch in OPS_REGRESSIONS:
        _OPS_PATCH = patch
        try:
            caught = run(quiet=True)
        finally:
            _OPS_PATCH = None
        if not caught:
            missed.append(label)
            sys.stdout.write(u"MISSED regression in msm_ops: {0}\n".format(label))
    global _MODEL_PATCH
    for label, patch in MODEL_REGRESSIONS:
        _MODEL_PATCH = patch
        try:
            caught = run(quiet=True)
        finally:
            _MODEL_PATCH = None
        if not caught:
            missed.append(label)
            sys.stdout.write(u"MISSED regression in msm_model: {0}\n".format(label))
    global _UI_PATCH
    for label, patch in UI_REGRESSIONS:
        _UI_PATCH = patch
        try:
            caught = run(quiet=True)
        finally:
            _UI_PATCH = None
        if not caught:
            missed.append(label)
            sys.stdout.write(u"MISSED regression in msm_ui: {0}\n".format(label))
    sys.stdout.write(u"selftest: {0} regressions, {1} missed\n".format(
        len(REGRESSIONS) + len(OPS_REGRESSIONS) + len(MODEL_REGRESSIONS) + len(UI_REGRESSIONS),
        len(missed)))
    return 1 if missed else 0


def main():
    try:
        if u"--selftest" in sys.argv:
            return selftest()
        return 1 if run() else 0
    finally:
        bench_stubs.remove()


if __name__ == u"__main__":
    sys.exit(main())
