# -*- coding: utf-8 -*-
"""Number Sequencer - logic bench. Plain CPython 3:

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the logic on purpose, prove checks fail

Covers numbering, formatting, the walk order (branches first, then on up the
main), the family tree, settings, theme, and a fake Revit document for the
connector graph and the parameter list.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402

bench_stubs.install()

import nsq_core as core  # noqa: E402
import nsq_revit as rv  # noqa: E402
import nsq_ui as ui  # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


class Fail(Exception):
    pass


def eq(got, want, what=""):
    if got != want:
        raise Fail("{0}: got {1!r}, want {2!r}".format(what, got, want))


def ok(cond, what):
    if not cond:
        raise Fail(what)


# ============================================================
# Graph helpers
# ============================================================

def link(nodes, a, ca, b, cb):
    nodes[a].conn(ca).links.append((b, cb))
    nodes[b].conn(cb).links.append((a, ca))


def straight_chain(keys, areas=None, x0=0.0):
    """Ducts along +X; each node: conn 0 at its start (facing -X), conn 1 at its end (+X)."""
    nodes = {}
    for i, k in enumerate(keys):
        a = areas[i] if areas else 1.0
        nodes[k] = core.Node(k, [core.Conn(0, a, (x0 + i, 0, 0), (-1, 0, 0)),
                                 core.Conn(1, a, (x0 + i + 1, 0, 0), (1, 0, 0))])
    for i in range(len(keys) - 1):
        link(nodes, keys[i], 1, keys[i + 1], 0)
    return nodes


def tee_network(branch_area=0.5, main_area=1.0):
    """A(1) - T(2) - B(3) - C(4) on the main, D(5) - E(6) off the tee."""
    nodes = {}
    nodes[1] = core.Node(1, [core.Conn(0, main_area, (0, 0, 0), (-1, 0, 0)),
                             core.Conn(1, main_area, (1, 0, 0), (1, 0, 0))])
    nodes[2] = core.Node(2, [core.Conn(0, main_area, (1, 0, 0), (-1, 0, 0)),
                             core.Conn(1, main_area, (2, 0, 0), (1, 0, 0)),
                             core.Conn(2, branch_area, (1.5, 0.5, 0), (0, 1, 0))])
    nodes[3] = core.Node(3, [core.Conn(0, main_area, (2, 0, 0), (-1, 0, 0)),
                             core.Conn(1, main_area, (3, 0, 0), (1, 0, 0))])
    nodes[4] = core.Node(4, [core.Conn(0, main_area, (3, 0, 0), (-1, 0, 0)),
                             core.Conn(1, main_area, (4, 0, 0), (1, 0, 0))])
    nodes[5] = core.Node(5, [core.Conn(0, branch_area, (1.5, 0.5, 0), (0, -1, 0)),
                             core.Conn(1, branch_area, (1.5, 1.5, 0), (0, 1, 0))])
    nodes[6] = core.Node(6, [core.Conn(0, branch_area, (1.5, 1.5, 0), (0, -1, 0)),
                             core.Conn(1, branch_area, (1.5, 2.5, 0), (0, 1, 0))])
    link(nodes, 1, 1, 2, 0)
    link(nodes, 2, 1, 3, 0)
    link(nodes, 3, 1, 4, 0)
    link(nodes, 2, 2, 5, 0)
    link(nodes, 5, 1, 6, 0)
    return nodes


# ============================================================
# Formatting and the plan
# ============================================================

@check
def formats():
    eq(core.format_number(5, 3), u"005", "001 format")
    eq(core.format_number(45, 3), u"045", "045")
    eq(core.format_number(1234, 3), u"1234", "longer than the pad keeps every digit")
    eq(core.format_number(7, 2), u"07", "01 format")
    eq(core.format_number(7, 0), u"7", "1 format")
    eq(core.format_number(0, 3), u"000", "zero")


@check
def start_parsing():
    eq(core.parse_start(u"045"), 45, "leading zeros")
    eq(core.parse_start(u" 7 "), 7, "spaces")
    eq(core.parse_start(u"-1"), None, "negative refused")
    eq(core.parse_start(u"4a"), None, "letters refused")
    eq(core.parse_start(u""), None, "blank refused")


@check
def plan_upwards():
    plan, errs = core.plan_numbers([10, 11, 12], lambda k: True, 45, u"up", 3)
    eq([p[2] for p in plan], [u"045", u"046", u"047"], "upwards from 045")
    eq(errs, [], "no errors")


@check
def plan_downwards_stops_at_zero():
    plan, errs = core.plan_numbers([1, 2, 3, 4], lambda k: True, 2, u"down", 2)
    eq([p[2] for p in plan], [u"02", u"01", u"00"], "down to 00")
    eq([e[0] for e in errs], [4], "the fourth would be below 0")


@check
def plan_skips_without_using_numbers():
    plan, errs = core.plan_numbers([1, 2, 3, 4], lambda k: k != 2, 1, u"up", 0)
    eq([(p[0], p[2]) for p in plan], [(1, u"1"), (3, u"2"), (4, u"3")], "skipped key takes no number")


@check
def preview():
    plan, errs = core.plan_numbers([1, 2], lambda k: True, 45, u"up", 3)
    eq(core.preview_text(plan, errs, 3, 3), u"2 numbered  045 to 046  |  3 skipped", "preview")
    eq(core.preview_text([], [], 0, 3), u"Nothing to number", "empty")


@check
def writes_prepared():
    infos = {
        1: {u"exists": True, u"readonly": False, u"storage": u"text", u"value": u"001"},
        2: {u"exists": True, u"readonly": False, u"storage": u"text", u"value": u"9"},
        3: {u"exists": False},
        4: {u"exists": True, u"readonly": True, u"storage": u"text", u"value": u""},
        5: {u"exists": True, u"readonly": False, u"storage": u"integer", u"value": 5},
        6: {u"exists": True, u"readonly": False, u"storage": u"integer", u"value": 0},
        7: {u"exists": True, u"readonly": False, u"storage": None, u"value": None},
    }
    plan = [(1, 1, u"001"), (2, 2, u"002"), (3, 3, u"003"), (4, 4, u"004"),
            (5, 5, u"005"), (6, 6, u"006"), (7, 7, u"007")]
    writes, same, errors = core.prepare_writes(plan, lambda k: infos.get(k))
    eq(writes, [(2, u"002"), (6, 6)], "only changed values are written, integers as numbers")
    eq(same, [1, 5], "already right is left alone")
    eq([e[0] for e in errors], [3, 4, 7], "missing, read-only and wrong storage reported")


@check
def read_back_matching():
    ok(core.value_matches(5, 5), "integer match")
    ok(not core.value_matches(5, 6), "integer mismatch")
    ok(core.value_matches(u"005", u"005"), "text match")
    ok(not core.value_matches(u"005", u"5"), "padding is part of the value")
    ok(not core.value_matches(u"005", None), "nothing read back")


# ============================================================
# The walk
# ============================================================

@check
def straight_run_from_equipment():
    nodes = straight_chain([1, 2, 3, 4])
    nodes[4].conn(1).equipment = True
    nodes[4].conn(1).external = True
    order, pieces = core.sequence_order(nodes)
    eq(order, [4, 3, 2, 1], "starts at the end joined to the AHU")
    eq(pieces, 1, "one piece")


@check
def straight_run_from_biggest_end():
    nodes = straight_chain([1, 2, 3, 4], areas=[0.3, 0.5, 0.8, 1.0])
    order, pieces = core.sequence_order(nodes)
    eq(order, [4, 3, 2, 1], "the biggest open end is the main's start")


@check
def branch_numbered_before_main_continues():
    order, pieces = core.sequence_order(tee_network())
    eq(order, [1, 2, 5, 6, 3, 4], "leg off the tee numbered in full, then on up the main")


@check
def straightest_is_main_when_sizes_match():
    order, pieces = core.sequence_order(tee_network(branch_area=1.0), start_key=1)
    eq(order, [1, 2, 5, 6, 3, 4], "same size: the straight-through outlet is the main")


@check
def nested_branches():
    nodes = tee_network()
    # a second tee on the branch: 5 grows a sub-branch 7
    nodes[5].conns.append(core.Conn(2, 0.2, (1.5, 1.0, 0), (1, 0, 0)))
    nodes[7] = core.Node(7, [core.Conn(0, 0.2, (1.5, 1.0, 0), (-1, 0, 0)),
                             core.Conn(1, 0.2, (2.5, 1.0, 0), (1, 0, 0))])
    link(nodes, 5, 2, 7, 0)
    order, pieces = core.sequence_order(nodes, start_key=1)
    eq(order, [1, 2, 5, 7, 6, 3, 4], "a branch's own branch is finished before the branch carries on")


@check
def taps_in_order_along_the_duct():
    nodes = {}
    nodes[1] = core.Node(1, [core.Conn(0, 1.0, (0, 0, 0), (-1, 0, 0)),
                             core.Conn(1, 1.0, (10, 0, 0), (1, 0, 0)),
                             core.Conn(2, 0.2, (7, 0, 0), (0, 1, 0)),
                             core.Conn(3, 0.2, (3, 0, 0), (0, 1, 0))])
    nodes[2] = core.Node(2, [core.Conn(0, 1.0, (10, 0, 0), (-1, 0, 0)),
                             core.Conn(1, 1.0, (20, 0, 0), (1, 0, 0))])
    nodes[3] = core.Node(3, [core.Conn(0, 0.2, (7, 0, 0), (0, -1, 0))])
    nodes[4] = core.Node(4, [core.Conn(0, 0.2, (3, 0, 0), (0, -1, 0))])
    link(nodes, 1, 1, 2, 0)
    link(nodes, 1, 2, 3, 0)
    link(nodes, 1, 3, 4, 0)
    order, pieces = core.sequence_order(nodes, start_key=1)
    eq(order, [1, 4, 3, 2], "taps nearest the inlet first, then the main")


@check
def picked_start_mid_run():
    nodes = straight_chain([1, 2, 3, 4, 5], areas=[1.0, 0.9, 0.8, 0.7, 0.6])
    order, pieces = core.sequence_order(nodes, start_key=3)
    eq(order, [3, 4, 5, 2, 1], "forward first, then the run behind the start")


@check
def separate_pieces_follow_on():
    nodes = straight_chain([1, 2, 3])
    nodes.update(straight_chain([10, 11], x0=50))
    order, pieces = core.sequence_order(nodes)
    eq(sorted(order), [1, 2, 3, 10, 11], "everything numbered once")
    eq(pieces, 2, "two pieces")


@check
def loop_terminates():
    nodes = {}
    for k in (1, 2, 3):
        nodes[k] = core.Node(k, [core.Conn(0, 1.0, (0, 0, 0), None),
                                 core.Conn(1, 1.0, (1, 0, 0), None)])
    link(nodes, 1, 1, 2, 0)
    link(nodes, 2, 1, 3, 0)
    link(nodes, 3, 1, 1, 0)
    order, pieces = core.sequence_order(nodes)
    eq(sorted(order), [1, 2, 3], "a closed loop numbers each element once")


@check
def long_run_no_recursion_limit():
    keys = list(range(1, 6001))
    nodes = straight_chain(keys)
    order, pieces = core.sequence_order(nodes, start_key=1)
    eq(len(order), 6000, "6000 elements walked")
    eq(order[:3], [1, 2, 3], "in order")


@check
def equipment_in_set_starts():
    nodes = straight_chain([1, 2, 3])
    nodes[9] = core.Node(9, [core.Conn(0, 2.0, (3, 0, 0), (1, 0, 0))], is_equipment=True)
    link(nodes, 9, 0, 3, 1)
    order, pieces = core.sequence_order(nodes)
    eq(order, [9, 3, 2, 1], "selected equipment is the source")


# ============================================================
# Several systems in one sequence
# ============================================================

def two_systems():
    """System A: 1-2-3 along X from 0. System B: 10-11 along X from 50.
    System C: 20-21 along X from 20 (between them)."""
    nodes = straight_chain([1, 2, 3], areas=[1.0, 0.9, 0.8])
    nodes.update(straight_chain([10, 11], areas=[1.0, 0.9], x0=50))
    nodes.update(straight_chain([20, 21], areas=[1.0, 0.9], x0=20))
    return nodes


@check
def systems_split():
    nodes = two_systems()
    eq(core.components(nodes), [[1, 2, 3], [10, 11], [20, 21]], "three separate systems")


@check
def equipment_never_joins_systems():
    nodes = straight_chain([1, 2], areas=[1.0, 1.0])
    nodes.update(straight_chain([5, 6], areas=[0.5, 0.5], x0=10))
    nodes[9] = core.Node(9, [core.Conn(0, 1.0, (2, 0, 0), (-1, 0, 0)),
                             core.Conn(1, 0.5, (10, 0, 0), (1, 0, 0))], is_equipment=True)
    link(nodes, 9, 0, 2, 1)
    link(nodes, 9, 1, 5, 0)
    eq(core.components(nodes), [[1, 2, 9], [5, 6]],
       "the AHU joins the system on its biggest connection, the other stays separate")


@check
def systems_ordered_from_picked_then_nearest():
    nodes = two_systems()
    comps = core.components(nodes)
    got = core.order_systems(nodes, comps, starts={10: True})
    eq([c for c, st in got], [[10, 11], [20, 21], [1, 2, 3]],
       "picked system first, then the nearest to where it finished, then the next")
    eq([st for c, st in got], [10, None, None], "only the picked system has a picked start")


@check
def systems_ordered_from_end_of_list():
    nodes = two_systems()
    comps = core.components(nodes)
    got = core.order_systems(nodes, comps, from_point=(70, 0, 0))
    eq([c[0] for c, st in got], [10, 20, 1], "added systems start nearest the end of the list")


@check
def numbers_run_on_across_systems():
    nodes = two_systems()
    systems = [{u"keys": [1, 2, 3], u"start": None}, {u"keys": [20, 21], u"start": 21},
               {u"keys": [10, 11], u"start": None}]
    order, spans = core.full_order(nodes, systems)
    eq(order, [1, 2, 3, 21, 20, 10, 11], "each system from its start, in list order")
    eq(spans, [(0, 3), (3, 5), (5, 7)], "spans")
    plan, errs = core.plan_numbers(order, lambda k: k != 2, 45, u"up", 3)
    ranges = core.system_ranges(plan, [order[a:b] for a, b in spans])
    eq(ranges, [(u"045", u"046"), (u"047", u"048"), (u"049", u"050")], "numbers continue into the next system")


@check
def system_names():
    eq(core.system_name([1, 2, 3], {1: u"SA-01", 2: u"", 3: u"SA-01"}, u"System 1"), u"SA-01", "common name")
    eq(core.system_name([1], {}, u"System 4"), u"System 4", "fallback")


@check
def parameter_filter_contains():
    params = [(u"BGL_Item Number", u"text", 1), (u"Comments", u"text", 1),
              (u"Item Number", u"text", 1), (u"Mark", u"text", 1)]
    eq([p[0] for p in core.filter_params(params, u"item")], [u"Item Number", u"BGL_Item Number"],
       "contains the text, starts-with first")
    eq([p[0] for p in core.filter_params(params, u"MAR")], [u"Mark"], "case-insensitive")
    eq(len(core.filter_params(params, u"  ")), 4, "blank keeps all")
    eq(core.filter_params(params, u"zzz"), [], "nothing contains it")
    eq(core.exact_param(params, u"mark"), u"Mark", "exact name typed")
    eq(core.exact_param(params, u"mar"), None, "partial is not a choice")


# ============================================================
# System selector
# ============================================================

def through_run():
    """Duct 1 - damper 2 (accessory) - duct 3 - tee 4 - duct 5 ; tee branch -> duct 6.
    All along X from 0, branch up +Y."""
    nodes = straight_chain([1, 2, 3, 4, 5])
    nodes[4].conns.append(core.Conn(2, 0.5, (3.5, 0.5, 0), (0, 1, 0)))
    nodes[6] = core.Node(6, [core.Conn(0, 0.5, (3.5, 0.5, 0), (0, -1, 0)),
                             core.Conn(1, 0.5, (3.5, 1.5, 0), (0, 1, 0))])
    link(nodes, 4, 2, 6, 0)
    return nodes


@check
def fab_joins_its_system():
    nodes = straight_chain([1, 2, 3, 4])
    nodes.update(straight_chain([20, 21], x0=40))
    got = core.assign_systems(nodes, {1: u"id:SA", 2: None, 3: None, 4: u"id:SA", 20: None, 21: None})
    eq([got[k] for k in (1, 2, 3, 4)], [u"id:SA"] * 4, "unlabelled fab parts join the system they connect to")
    eq([got[20], got[21]], [u"piece:20", u"piece:20"], "a loose run is its own piece")


@check
def flood_takes_nearest_system():
    nodes = straight_chain([1, 2, 3, 4, 5])
    got = core.assign_systems(nodes, {1: u"id:A", 5: u"id:B"})
    eq([got[k] for k in (1, 2, 3, 4, 5)], [u"id:A", u"id:A", u"id:A", u"id:B", u"id:B"],
       "each unlabelled part takes the nearest system (ties to the lower key)")


@check
def nearest_open_end():
    nodes = straight_chain([1, 2, 3, 4])
    eq(core.nearest_end(nodes, list(nodes), (10, 0, 0)), 4, "far end")
    eq(core.nearest_end(nodes, list(nodes), (-3, 0, 0)), 1, "near end")
    eq(core.nearest_end(nodes, list(nodes), (2, 0, 0)), 1, "only open ends count, not mid-run")
    eq(core.nearest_end(nodes, list(nodes), None), None, "no point, no pick")


@check
def chained_pieces_start_nearest():
    nodes = straight_chain([1, 2, 3])
    nodes.update(straight_chain([10, 11, 12], x0=4))
    order, pieces = core.sequence_order(nodes, start_key=1, chain=True)
    eq(order, [1, 2, 3, 10, 11, 12], "second piece starts at its end nearest the first's finish")


@check
def accessory_walked_not_numbered():
    nodes = through_run()
    passthrough = set([2])
    inc = lambda k: core.sel_include(k, passthrough, set(), {}, set())
    order, spans, starts = core.selector_order(nodes, [{u"keys": sorted(nodes), u"start": 1}], inc)
    eq(order, [1, 2, 3, 4, 6, 5], "one run straight through the damper, branch before main")
    plan, errs = core.plan_numbers(order, inc, 1, u"up", 3)
    eq([(k, t) for k, n, t in plan], [(1, u"001"), (3, u"002"), (4, u"003"), (6, u"004"), (5, u"005")],
       "the damper takes no number and the run is not split")


@check
def selector_include_rules():
    eq(core.sel_include(2, set([2]), set(), {}, set()), False, "accessory")
    eq(core.sel_include(3, set(), set([3]), {}, set()), False, "left out by hand")
    eq(core.sel_include(4, set(), set(), {4: u"a|b|c"}, set([u"a|b|c"])), False, "type unticked")
    eq(core.sel_include(5, set(), set(), {5: u"a|b|c"}, set()), True, "numbered")


@check
def next_system_starts_nearest_previous_end():
    nodes = straight_chain([1, 2, 3])                              # x 0..3, finishes near 3
    nodes.update(straight_chain([20, 21, 22], x0=10))             # points 10.5 .. 12.5
    nodes.update(straight_chain([30, 31, 32, 33, 34, 35], x0=8.5))  # ends at 9.0 and 14.0
    systems = [{u"keys": [1, 2, 3], u"start": 1}, {u"keys": [20, 21, 22], u"start": None},
               {u"keys": [30, 31, 32, 33, 34, 35], u"start": None}]
    order, spans, starts = core.selector_order(nodes, systems)
    eq(order, [1, 2, 3, 20, 21, 22, 35, 34, 33, 32, 31, 30], "list order kept, each from its nearest end")
    eq(starts, [(1, u"picked"), (20, u"nearest"), (35, u"nearest")],
       "system 2 from its end nearest 3, system 3 from its end nearest 22")
    systems[1][u"start"] = 22
    order, spans, starts = core.selector_order(nodes, systems)
    eq(order[3:6], [22, 21, 20], "a picked start wins")
    eq(starts[2], (30, u"nearest"), "and the next system chains from where that one finished")


@check
def auto_order_nearest_next():
    nodes = straight_chain([1, 2, 3])
    nodes.update(straight_chain([20, 21], x0=30))
    nodes.update(straight_chain([10, 11], x0=5))
    systems = [{u"keys": [20, 21], u"start": None, u"n": u"far"},
               {u"keys": [1, 2, 3], u"start": 1, u"n": u"picked"},
               {u"keys": [10, 11], u"start": None, u"n": u"near"}]
    eq([sd[u"n"] for sd in core.auto_order(nodes, systems)], [u"picked", u"near", u"far"],
       "picked start first, then nearest next")


@check
def unique_colours():
    cols = core.distinct_colours(300)
    eq(len(set(cols)), 300, "every colour different")
    ok(all([len(c) == 7 and c.startswith(u"#") for c in cols]), "valid hex")
    eq(core.hex_rgb(u"#FF8000"), (255, 128, 0), "hex to rgb")
    ok(cols[0] != cols[1] and cols[1] != cols[2], "neighbours differ")


@check
def move_rows():
    eq(core.move_item([u"a", u"b", u"c", u"d"], 3, 0), ([u"d", u"a", u"b", u"c"], 0), "to top")
    eq(core.move_item([u"a", u"b", u"c", u"d"], 0, 2), ([u"b", u"c", u"a", u"d"], 2), "drag down")
    eq(core.move_item([u"a", u"b"], 1, 9), ([u"a", u"b"], 1), "past the end clamps")
    items = [u"a", u"b", u"c", u"d"]
    eq(core.move_item(items, 0, core.drop_index(0, 2))[0], [u"b", u"a", u"c", u"d"],
       "a dropped on c lands above c when dragged down")
    eq(core.move_item(items, 3, core.drop_index(3, 1))[0], [u"a", u"d", u"b", u"c"],
       "and above b when dragged up")


@check
def natural_sort():
    names = [u"SA 10", u"SA 9", u"EA 1", u"SA 1"]
    eq(sorted(names, key=core.natural_key), [u"EA 1", u"SA 1", u"SA 9", u"SA 10"], "numbers in names")


@check
def plan_views_only():
    eq(core.tag_view_ok(u"FloorPlan", plans_only=True)[0], True, "plan")
    eq(core.tag_view_ok(u"CeilingPlan", plans_only=True)[0], True, "ceiling plan")
    eq(core.tag_view_ok(u"Section", plans_only=True)[0], False, "section refused on the selector")
    eq(core.tag_view_ok(u"ThreeD", locked_3d=True, plans_only=True)[0], False, "locked 3D refused")
    eq(core.tag_view_ok(u"Section")[0], True, "the Sequencer still tags sections")


@check
def tag_lists_per_kind():
    tags = [{u"tag_cat": u"OST_DuctTags"}, {u"tag_cat": u"OST_PipeTags"},
            {u"tag_cat": u"OST_MultiCategoryTags"}]
    eq([t[u"tag_cat"] for t in core.tags_for_kind(tags, u"pipe")], [u"OST_PipeTags", u"OST_MultiCategoryTags"],
       "pipe tab")
    ok(core.tag_can_host(u"OST_PipeTags", u"OST_PipeCurves"), "pipe tag takes pipes")
    ok(core.tag_can_host(u"OST_FabricationPipeworkTags", u"OST_FabricationPipework"), "fab pipe tag")


@check
def refresh_keeps_order():
    def sd(key, keys):
        return {u"key": key, u"keys": keys, u"on": True, u"start": None, u"colour": None}
    old = [sd(u"id:B", [3, 4]), sd(u"id:A", [1, 2]), sd(u"id:GONE", [9])]
    old[0][u"on"] = False
    old[0][u"colour"] = u"#111111"
    old[1][u"start"] = 2
    new = [sd(u"id:A", [1, 2]), sd(u"id:B", [3, 4]), sd(u"id:C", [5])]
    got = core.merge_systems(old, new)
    eq([g[u"key"] for g in got], [u"id:B", u"id:A", u"id:C"], "user order kept, new on the end, gone dropped")
    eq((got[0][u"on"], got[0][u"colour"], got[1][u"start"]), (False, u"#111111", 2), "ticks, colours, starts kept")


# ============================================================
# Tree, tags, parameters, search
# ============================================================

@check
def tree_sorted_and_counted():
    rows = [(1, u"Ducts", u"Rectangular Duct", u"Supply"),
            (2, u"Duct Fittings", u"Elbow", u"Radius"),
            (3, u"ducts", u"rectangular duct", u"a type"),
            (4, u"Duct Fittings", u"Elbow", u"Radius"),
            (5, u"Duct Accessories", u"Fire Damper", u"600x400")]
    tree = core.build_tree(rows)
    eq([c[u"name"] for c in tree], [u"Duct Accessories", u"Duct Fittings", u"Ducts", u"ducts"],
       "categories alphabetical, case-insensitive")
    elbow = tree[1][u"families"][0]
    eq(core.tree_count(elbow), 2, "family count")
    eq(elbow[u"types"][0][u"ids"], [2, 4], "ids under the type")


@check
def tri_state():
    keys = [u"a", u"b"]
    eq(core.group_state(keys, set()), True, "all in")
    eq(core.group_state(keys, set([u"a", u"b"])), False, "none in")
    eq(core.group_state(keys, set([u"a"])), None, "mixed")


@check
def tags_cover():
    ok(core.tag_can_host(u"OST_MultiCategoryTags", u"OST_DuctFitting"), "multi-category takes anything")
    ok(core.tag_can_host(u"OST_DuctTags", u"OST_DuctCurves"), "duct tag takes ducts")
    ok(not core.tag_can_host(u"OST_DuctTags", u"OST_DuctFitting"), "duct tag refuses fittings")
    ok(core.tag_can_host(u"OST_FabricationDuctworkTags", u"OST_FabricationDuctwork"), "fab tag")
    eq(core.tag_coverage(u"OST_DuctTags", [u"OST_DuctCurves", u"OST_DuctFitting", u"OST_DuctCurves"]),
       (2, 1), "coverage")


@check
def parameter_default():
    eq(core.default_parameter([u"Comments", u"Mark"], u""), u"Mark", "Mark before Comments")
    eq(core.default_parameter([u"Comments", u"Item Number"], u""), u"Item Number", "Item Number first")
    eq(core.default_parameter([u"Comments", u"X"], u"X"), u"X", "saved wins")
    eq(core.default_parameter([u"Comments"], u"Gone"), u"Comments", "saved but missing")


@check
def search_words():
    ok(core.matches(u"Duct Fittings Elbow Radius", u"elb rad"), "all words")
    ok(not core.matches(u"Duct Fittings Elbow", u"tee"), "missing word")
    ok(core.matches(u"x", u""), "blank matches")


# ============================================================
# Settings, theme, egg
# ============================================================

@check
def settings_round_trip():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, u"s.txt")
    vals = core.parse_settings(u"")
    vals[u"parameter"] = u"BGL_Item = Number"
    vals[u"skip"] = core.skip_text_from(set([u"Ducts|A|B", u"Duct Fittings|E|R"]))
    ok(core.save_settings(vals, path), "saved")
    back = core.load_settings(path)
    eq(back[u"parameter"], u"BGL_Item = Number", "split on the first = only")
    eq(core.skip_keys_from(back[u"skip"]), set([u"Ducts|A|B", u"Duct Fittings|E|R"]), "skip list")


@check
def settings_damaged():
    vals = core.parse_settings(u"garbage\nunknown=1\npad=2\n=\n")
    eq(vals[u"pad"], u"2", "good key kept")
    eq(vals[u"theme"], u"auto", "missing key defaults")
    ok(u"unknown" not in vals, "unknown keys ignored")


@check
def settings_migrate():
    old = dict(core.MIGRATIONS)
    try:
        core.MIGRATIONS[99] = {u"theme": u"light"}
        vals = core.parse_settings(u"settings_version=1\ntheme=dark\n")
        eq(vals[u"theme"], u"light", "migration applied to an older file")
    finally:
        core.MIGRATIONS.clear()
        core.MIGRATIONS.update(old)


@check
def theme_follow():
    eq(core.resolve_theme(u"auto", True), u"dark", "auto dark canvas")
    eq(core.resolve_theme(u"auto", False), u"light", "auto light canvas")
    eq(core.resolve_theme(u"auto", None), u"dark", "unreadable falls back dark")
    eq(core.resolve_theme(u"light", True), u"light", "explicit light")
    eq([core.next_theme(t) for t in core.THEME_CYCLE], [u"dark", u"light", u"auto"], "cycle")
    eq(core.luminance_is_dark(30, 30, 30), True, "dark canvas")
    eq(core.luminance_is_dark(255, 255, 255), False, "white canvas")


@check
def slow_clicks():
    c = core.SlowClicks()
    eq([c.click(t) for t in (0.0, 0.5, 1.0)], [False, False, True], "three slow clicks")
    c = core.SlowClicks()
    eq([c.click(t) for t in (0.0, 0.1, 0.2)], [False, False, False], "fast clicks ignored")
    c = core.SlowClicks()
    eq([c.click(t) for t in (0.0, 0.5, 5.0, 5.5)], [False, False, False, False], "long gap resets")


# ============================================================
# Fake Revit document - connector graph and parameters
# ============================================================

DB = sys.modules["Autodesk.Revit.DB"]
CATS = {u"OST_DuctCurves": -2008000, u"OST_DuctFitting": -2008010,
        u"OST_DuctAccessory": -2008016, u"OST_FlexDuctCurves": -2008020,
        u"OST_DuctTerminal": -2008013, u"OST_FabricationDuctwork": -2008193,
        u"OST_PlaceHolderDucts": -2008160, u"OST_MechanicalEquipment": -2001140,
        u"OST_ElectricalEquipment": -2001040, u"OST_DuctTags": -2008017,
        u"OST_MultiCategoryTags": -2005020}
for _n, _v in CATS.items():
    setattr(DB.BuiltInCategory, _n, _v)


class FId(object):
    def __init__(self, v):
        self.Value = v


class FCat(object):
    def __init__(self, name):
        self.Id = FId(CATS[name])
        self.Name = name


class FConn(object):
    def __init__(self, owner, cid, origin, direction, w=1.0, h=1.0, kind=u"End", domain=u"DomainHvac"):
        self.Owner = owner
        self.Id = cid
        self.Origin = FXYZ(*origin)
        self.CoordinateSystem = type("CS", (), {"BasisZ": FXYZ(*direction)})()
        self.Shape = u"ConnectorProfileType.Rectangular"
        self.Width = w
        self.Height = h
        self.ConnectorType = u"ConnectorType." + kind
        self.Domain = u"Domain." + domain
        self.AllRefs = []


class FXYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class FParam(object):
    def __init__(self, name, storage, value=None, readonly=False, builtin=False, yesno=False):
        self.Definition = type("Def", (), {
            "Name": name,
            "BuiltInParameter": u"MARK" if builtin else u"INVALID",
            "GetDataType": (lambda s: type("DT", (), {"TypeId": u"yesno" if yesno else u"other"})()),
        })()
        self.StorageType = u"StorageType." + storage
        self.IsReadOnly = readonly
        self.value = value
        self.HasValue = value is not None

    def AsString(self):
        return self.value

    def AsInteger(self):
        return self.value or 0


class FElem(object):
    def __init__(self, eid, cat, params=None):
        self.Id = FId(eid)
        self.Category = FCat(cat)
        self.conns = []
        self.Parameters = params or []
        self.ConnectorManager = type("CM", (), {"Connectors": self.conns})()

    def add(self, cid, origin, direction, **kw):
        c = FConn(self, cid, origin, direction, **kw)
        self.conns.append(c)
        return c

    def get_Parameter(self, bip):
        return None

    def GetTypeId(self):
        return FId(0)

    def LookupParameter(self, name):
        for p in self.Parameters:
            if p.Definition.Name == name:
                return p
        return None


def join(a, b):
    a.AllRefs.append(b)
    b.AllRefs.append(a)


class FDoc(object):
    def __init__(self, elems):
        self.map = dict((e.Id.Value, e) for e in elems)

    def GetElement(self, eid):
        return self.map.get(eid.Value)


def _setup_stubs():
    DB.StorageType.String = u"StorageType.String"
    DB.StorageType.Integer = u"StorageType.Integer"
    DB.SpecTypeId.Boolean = type("B", (), {"YesNo": type("Y", (), {"TypeId": u"yesno"})()})


def fake_run():
    """AHU(99, outside) -> duct 1 -> tee 2 -> duct 3 ; branch off the tee -> duct 4.
    Duct 3 also carries an electrical connector wired to duct 1 (must be ignored)
    and a logical ref to the system (must be ignored)."""
    ahu = FElem(99, u"OST_MechanicalEquipment")
    d1 = FElem(1, u"OST_DuctCurves")
    t2 = FElem(2, u"OST_DuctFitting")
    d3 = FElem(3, u"OST_DuctCurves")
    d4 = FElem(4, u"OST_DuctCurves")
    system = FElem(500, u"OST_DuctCurves")
    a = ahu.add(0, (0, 0, 0), (1, 0, 0))
    d1a = d1.add(0, (0, 0, 0), (-1, 0, 0))
    d1b = d1.add(1, (1, 0, 0), (1, 0, 0))
    t2a = t2.add(0, (1, 0, 0), (-1, 0, 0))
    t2b = t2.add(1, (2, 0, 0), (1, 0, 0))
    t2c = t2.add(2, (1.5, 0.5, 0), (0, 1, 0), w=0.5, h=0.5)
    d3a = d3.add(0, (2, 0, 0), (-1, 0, 0))
    d3.add(1, (3, 0, 0), (1, 0, 0))
    d4a = d4.add(0, (1.5, 0.5, 0), (0, -1, 0), w=0.5, h=0.5)
    d4.add(1, (1.5, 1.5, 0), (0, 1, 0), w=0.5, h=0.5)
    join(a, d1a)
    join(d1b, t2a)
    join(t2b, d3a)
    join(t2c, d4a)
    elec = d3.add(7, (2.5, 0, 0), (0, 0, 1), domain=u"DomainElectrical")
    join(elec, d1.add(8, (0.5, 0, 0), (0, 0, 1), domain=u"DomainElectrical"))
    d3a.AllRefs.append(FConn(system, 0, (0, 0, 0), (1, 0, 0), kind=u"Logical"))
    return [d1, t2, d3, d4], ahu


@check
def fake_graph_and_walk():
    elems, ahu = fake_run()
    data = rv.read_network(FDoc(elems + [ahu]), elems, core.DebugLog(False))
    nodes = data[u"nodes"]
    eq(sorted(nodes), [1, 2, 3, 4], "only the set becomes nodes")
    ok(nodes[1].conn(0).equipment, "AHU connection flagged as the source")
    eq([c.cid for c in nodes[3].conns], [0, 1], "electrical connector dropped")
    eq(nodes[3].conn(0).links, [(2, 1)], "logical ref to the system dropped")
    order, pieces = core.sequence_order(nodes)
    eq(order, [1, 2, 4, 3], "from the AHU, branch first, then on up the main")


@check
def fake_network_collect():
    elems, ahu = fake_run()
    net = rv.collect_network(FDoc(elems + [ahu]), elems[2])
    eq(sorted([e.Id.Value for e in net]), [1, 2, 3, 4], "connected run collected, AHU is a boundary")


@check
def fake_parameters():
    _setup_stubs()
    params = [FParam(u"Mark", u"String", builtin=True),
              FParam(u"Comments", u"String", builtin=True),
              FParam(u"Workset", u"Integer", value=1, builtin=True),
              FParam(u"BGL_Seq", u"Integer"),
              FParam(u"Yes", u"Integer", yesno=True),
              FParam(u"Area", u"Double"),
              FParam(u"Locked", u"String", readonly=True)]
    e1 = FElem(1, u"OST_DuctCurves", params)
    e2 = FElem(2, u"OST_DuctCurves", params[:2])
    storages, per_elem = rv.param_map([e1, e2])
    got = core.param_list(storages, per_elem, [1, 2])
    eq(got, [(u"BGL_Seq", u"integer", 1), (u"Comments", u"text", 2), (u"Mark", u"text", 2)],
       "text and shared integer parameters; never workset, yes/no, double or read-only")
    eq(core.param_list(storages, per_elem, [2]), [(u"Comments", u"text", 1), (u"Mark", u"text", 1)],
       "counts follow the elements still in the sequence")
    eq(rv.read_param_info(e1, u"Nope"), {u"exists": False}, "missing parameter")
    eq(rv.read_param_info(e1, u"Locked")[u"readonly"], True, "read-only seen")


@check
def row_selection_clicks():
    eq(core.click_selection(set([1]), 1, 3), (set([3]), 3), "plain click: just that row")
    eq(core.click_selection(set([1]), 1, 3, ctrl=True), (set([1, 3]), 3), "ctrl adds")
    eq(core.click_selection(set([1, 3]), 3, 3, ctrl=True), (set([1]), 3), "ctrl again removes")
    eq(core.click_selection(set([3]), 3, 3, ctrl=True), (set([3]), 3), "never empty by ctrl")
    eq(core.click_selection(set([1]), 1, 4, shift=True), (set([1, 2, 3, 4]), 1), "shift: a range, anchor kept")
    eq(core.click_selection(set([6]), 1, 3, ctrl=True, shift=True)[0], set([1, 2, 3, 6]), "ctrl+shift adds the range")


@check
def arrow_steps_wrap():
    eq(core.step_index(5, 2, 1), 3, "down")
    eq(core.step_index(5, 4, 1), 0, "down wraps to the top")
    eq(core.step_index(5, 0, -1), 4, "up wraps to the bottom")
    eq(core.step_index(5, None, 1), 0, "nothing selected: first")
    eq(core.step_index(0, None, 1), None, "empty table")


@check
def block_moves():
    eq(core.move_block(list(u"abcde"), set([1, 3]), -1), (list(u"badce"), set([0, 2])), "two rows up together")
    eq(core.move_block(list(u"abcde"), set([0, 1]), -1), (list(u"abcde"), set([0, 1])), "already at the top stays")
    eq(core.move_block(list(u"abcde"), set([3, 4]), 1), (list(u"abcde"), set([3, 4])), "already at the bottom stays")
    eq(core.move_block(list(u"abcde"), set([0, 2]), 1), (list(u"badce"), set([1, 3])), "two rows down together")


@check
def multi_row_drops():
    eq(core.move_many(list(u"abcde"), set([0, 1]), 4), (list(u"cdabe"), set([2, 3])), "drag two down")
    eq(core.move_many(list(u"abcde"), set([3, 4]), 0), (list(u"deabc"), set([0, 1])), "drag two to the top")
    eq(core.move_many(list(u"abcde"), set([1, 3]), 5), (list(u"acebd"), set([3, 4])), "scattered rows to the end, in order")
    eq(core.move_many(list(u"abcde"), set([2]), core.drop_before(0, True)), (list(u"acbde"), set([1])),
       "lower half of a row: lands after it")
    eq(core.move_many(list(u"abcde"), set([2]), core.drop_before(0, False)), (list(u"cabde"), set([0])),
       "upper half: lands before it")


@check
def own_selection_ignored():
    eq(core.user_selection([1, 2], [1, 2], [1, 2, 3]), [], "the tool's own selection")
    eq(core.user_selection([2, 9], [1, 2], [1, 2, 3]), [2], "the user's, only what is in the sequence")
    eq(core.user_selection([], None, [1]), [], "nothing selected")


@check
def start_stands_out():
    cols = core.distinct_colours(300)
    ok(core.START_COLOUR not in cols, "no system gets the start colour")
    ok(min([core.colour_distance(c, core.START_COLOUR) for c in cols]) >= core.START_GAP,
       "and none is near it")
    eq(core.start_keys([5, 6], [{u"start": None}, {u"start": 9}], []), set([5, 9]),
       "the first numbered and every picked start")


@check
def butted_parts_joined():
    """Fab parts end to end, never connected: joined where open ends touch and face."""
    nodes = {}
    for i, k in enumerate([1, 2, 3]):
        nodes[k] = core.Node(k, [core.Conn(0, 1.0, (i * 1.0, 0, 0), (-1, 0, 0)),
                                 core.Conn(1, 1.0, (i * 1.0 + 1.0, 0, 0), (1, 0, 0))])
    nodes[2].conns[0].origin = (1.004, 0, 0)          # 4mm-ish gap at the given tolerance
    nodes[9] = core.Node(9, [core.Conn(0, 1.0, (3.0, 0.002, 0), (1, 0, 0))])  # touches 3 but faces the same way
    eq(core.link_open_ends(nodes, 0.016), 2, "1-2 and 2-3 joined")
    eq(nodes[1].conn(1).links, [(2, 0)], "1 to 2")
    eq(nodes[9].conn(0).links, [], "a connector facing the same way is never joined")
    order, pieces = core.sequence_order(dict((k, nodes[k]) for k in (1, 2, 3)), start_key=1)
    eq(order, [1, 2, 3], "and the walk runs straight along them")
    eq(core.link_open_ends(nodes, 0.016), 0, "joined connectors are not open any more")
    grouped = core.assign_systems(nodes, {1: u"name:SA"})
    eq([grouped[k] for k in (1, 2, 3)], [u"name:SA"] * 3, "so the loose parts join the named run")


@check
def connected_ends_left_alone():
    nodes = straight_chain([1, 2])
    nodes[3] = core.Node(3, [core.Conn(0, 1.0, (2.0, 0, 0), (-1, 0, 0))])
    nodes[2].conn(1).external = True                   # joined to something outside the view
    eq(core.link_open_ends(nodes, 0.05), 0, "an end joined outside the view is not open")


@check
def crop_overlap():
    corners = [(x, y, z) for x in (5, 6) for y in (5, 6) for z in (0, 1)]
    ok(core.box_in_crop(corners, (0, 0, -1), (10, 10, 1)), "inside")
    ok(not core.box_in_crop(corners, (0, 0, -1), (4, 10, 1)), "beyond the crop in X")
    ok(core.box_in_crop(corners, (0, 0, 50), (10, 10, 60)), "plan crop ignores Z")
    ok(not core.box_in_crop(corners, (0, 0, 50), (10, 10, 60), use_z=True), "a section box does not")
    ok(core.box_in_crop(corners, (6.005, 0, 0), (10, 10, 1), tol=0.01), "touching within tolerance")
    ok(core.box_in_crop([], (0, 0, 0), (1, 1, 1)), "no box: kept")


@check
def view_pick_finds_row():
    systems = [{u"keys": [1, 2]}, {u"keys": [3, 4]}, {u"keys": [5]}]
    eq(core.systems_holding(systems, [4]), [1], "the system holding the pick")
    eq(core.systems_holding(systems, [2, 5]), [0, 2], "a pick across two systems")
    eq(core.systems_holding(systems, [99]), [], "not in any listed system")


@check
def summary_counts():
    systems = [{u"key": u"id:1", u"keys": [1, 2]}, {u"key": u"name:SA", u"keys": [3]},
               {u"key": u"piece:7", u"keys": [7]}, {u"key": u"piece:8", u"keys": [8, 9]}]
    eq(core.group_summary(systems), (1, 1, 2, 1), "systems by source, and one-part pieces")


@check
def removed_systems_leave_the_list():
    systems = [{u"key": u"a", u"num": [1, 2]}, {u"key": u"b", u"num": [3]}, {u"key": u"c", u"num": [4, 5]}]
    kept, batch = core.split_gone(systems, set([3, 4]))
    eq([sd[u"key"] for sd in kept], [u"a", u"c"], "b had every element removed")
    eq([(after, sd[u"key"]) for after, sd in batch], [(u"a", u"b")], "and remembers the row it followed")
    eq([sd[u"key"] for sd in core.bring_back(kept, [batch])], [u"a", u"b", u"c"], "Restore puts it back")
    kept, batch = core.split_gone([{u"key": u"z", u"num": []}], set())
    eq(len(kept), 1, "a system with nothing numberable is not dropped for it")


@check
def restore_after_several_removals():
    """Remove B, then C: restore must give A, B, C again (the review case)."""
    a, b, c = {u"key": u"A", u"num": [1]}, {u"key": u"B", u"num": [2]}, {u"key": u"C", u"num": [3]}
    kept, first = core.split_gone([a, b, c], set([2]))
    kept, second = core.split_gone(kept, set([2, 3]))
    eq([sd[u"key"] for sd in kept], [u"A"], "both gone")
    eq([sd[u"key"] for sd in core.bring_back(kept, [first, second])], [u"A", u"B", u"C"], "order restored")
    kept, batch = core.split_gone([a, b, c], set([1, 2]))
    eq([sd[u"key"] for sd in core.bring_back(kept, [batch])], [u"A", u"B", u"C"], "first two in one go")
    eq([sd[u"key"] for sd in core.bring_back([c], [[(u"GONE", a)]])], [u"C", u"A"], "lost neighbour: to the end")


@check
def move_to_a_position():
    on = lambda sd: sd[1]
    rows = [(u"a", 1), (u"b", 1), (u"x", 0), (u"c", 1), (u"d", 1)]
    out, new, last = core.move_to_position(rows, set([4]), 2, on)
    eq([r[0] for r in out], [u"a", u"d", u"b", u"x", u"c"], "d becomes #2")
    eq((new, last), (set([1]), 2), "and Move to next would go to #3")
    out, new, last = core.move_to_position(out, set([4]), last + 1, on)
    eq([r[0] for r in out], [u"a", u"d", u"c", u"b", u"x"], "Move to next: c lands at #3")
    eq(last, 3, "next would be #4")
    out, new, last = core.move_to_position(rows, set([0]), 99, on)
    eq((out[-1][0], last), (u"a", 4), "past the end: last")
    out, new, last = core.move_to_position(rows, set([3, 4]), 1, on)
    eq(([r[0] for r in out], last), ([u"c", u"d", u"a", u"b", u"x"], 2), "two selected to the top")
    out, new, last = core.move_to_position(rows, set([1]), 3, on)
    eq([r[0] for r in out], [u"a", u"x", u"c", u"b", u"d"], "unticked rows are not counted")
    eq(last, 3, "so b is #3")


@check
def typed_positions():
    eq(core.parse_position(u" 4 ", 1, 10), 4, "spaces")
    eq(core.parse_position(u"#7", 1, 10), 7, "a leading #")
    eq(core.parse_position(u"0", 1, 10), None, "below the range")
    eq(core.parse_position(u"11", 1, 10), None, "above it")
    eq(core.parse_position(u"two", 1, 10), None, "not a number")


@check
def auto_next_takes_the_nearest():
    """Three systems after the start: the next is the one whose nearest open
    end is closest to where the last placed one finishes."""
    nodes = straight_chain([1, 2, 3])                     # finishes near x 3
    nodes.update(straight_chain([10, 11], x0=40))          # far
    nodes.update(straight_chain([20, 21], x0=5))           # near: ends at 5.5 and 6.5
    nodes.update(straight_chain([30, 31], x0=9))           # nearer to 20-21's far end
    systems = [{u"key": u"S", u"keys": [1, 2, 3], u"start": 1},
               {u"key": u"F", u"keys": [10, 11], u"start": None},
               {u"key": u"N", u"keys": [20, 21], u"start": None},
               {u"key": u"M", u"keys": [30, 31], u"start": None}]
    found = core.next_nearest(nodes, systems, 0, set([u"S"]))
    eq(systems[found[0]][u"key"], u"N", "the nearest start to where S finishes")
    ok(abs(found[1] - 3.0) < 1e-6, "measured from S's last element (2.5) to N's nearest open end (5.5)")
    order = [systems[0], systems[2], systems[1], systems[3]]
    found = core.next_nearest(nodes, order, 1, set([u"S", u"N"]))
    eq(order[found[0]][u"key"], u"M", "then the nearest to where N finishes")
    eq(core.next_nearest(nodes, systems, 3, set([u"S", u"F", u"N", u"M"])), None, "nothing left")


@check
def exit_follows_the_order():
    nodes = straight_chain([1, 2, 3])
    nodes.update(straight_chain([20, 21], x0=5))
    p = core.exit_after(nodes, [{u"keys": [1, 2, 3], u"start": 1}, {u"keys": [20, 21], u"start": None}], 1)
    eq(round(p[0], 3), 6.5, "finishes at the far end of the second system")


@check
def view_table_filter_and_sort():
    views = [{u"id": 1, u"name": u"L10 Mech", u"g1": u"Mech", u"g2": u"Level 10"},
             {u"id": 2, u"name": u"L2 Mech", u"g1": u"Mech", u"g2": u""},
             {u"id": 3, u"name": u"L1 Elec", u"g1": u"Elec", u"g2": u"Level 1"}]
    eq([v[u"id"] for v in core.view_rows(views, {}, u"name", False)], [3, 2, 1], "natural sort by name")
    eq([v[u"id"] for v in core.view_rows(views, {u"g1": u"mech"}, u"name", False)], [2, 1], "filter a column")
    eq([v[u"id"] for v in core.view_rows(views, {}, u"g2", False)], [3, 1, 2], "blanks last")
    eq([v[u"id"] for v in core.view_rows(views, {}, u"g2", True)], [1, 3, 2], "reversed, blanks still last")
    eq([v[u"id"] for v in core.view_rows(views, {}, u"name", False, only=set([1, 3]))], [3, 1],
       "only the views that show the system")
    eq(core.default_group_param([u"Title", u"View Group", u"Sub-Discipline"], u"", 0), u"View Group", "group 1")
    eq(core.default_group_param([u"Title", u"View Group", u"Sub-Discipline"], u"", 1), u"Sub-Discipline", "group 2")
    eq(core.default_group_param([u"Title", u"BGL_X"], u"BGL_X", 0), u"BGL_X", "saved wins")
    eq(core.default_group_param([u"View Group"], core.NONE_MARK, 0), u"", "(none) chosen stays none")


@check
def column_value_lists():
    views = [{u"id": 1, u"name": u"L1 Mech", u"g1": u"Mech", u"g2": u"L1"},
             {u"id": 2, u"name": u"L1 Elec", u"g1": u"Elec", u"g2": u"L1"},
             {u"id": 3, u"name": u"L2 Mech", u"g1": u"Mech", u"g2": u"L2"},
             {u"id": 4, u"name": u"Roof", u"g1": u"", u"g2": u"L2"}]
    eq(core.column_values(views, u"g1", {}, {}), [(u"Elec", 1), (u"Mech", 2), (u"", 1)],
       "every value with a count, blank last")
    eq(core.column_values(views, u"g1", {}, {u"g2": set([u"L2"])}), [(u"Elec", 1), (u"Mech", 1)],
       "only what the other columns let through")
    eq(core.column_values(views, u"g1", {}, {u"g1": set([u"Mech"])}), [(u"Elec", 1), (u"Mech", 2), (u"", 1)],
       "its own unticked values still listed, so they can be ticked again")
    eq([v[u"id"] for v in core.view_rows(views, {}, u"name", False, excluded={u"g1": set([u"Mech", u""])})],
       [2], "unticked values hidden")
    eq([v[u"id"] for v in core.view_rows(views, {}, u"name", False,
                                         excluded={u"g1": set([u"Mech", u"Elec", u""])})], [], "nothing ticked: nothing")
    eq(core.tick_values(set(), [u"Mech", u"Elec"], False), set([u"Mech", u"Elec"]), "Clear all")
    eq(core.tick_values(set([u"Mech", u"Elec"]), [u"Mech"], True), set([u"Elec"]), "Select all over a search")


@check
def view_types():
    eq(sorted(core.TAG_VIEW_KINDS), [u"FloorPlan", u"Section", u"ThreeD"], "plans, sections and 3D")
    eq(core.kind_text(u"3D", False), u"3D (unlocked)", "an unlocked 3D view says so")
    eq(core.kind_text(u"3D", True), u"3D", "locked")
    eq(core.kind_text(u"Section", False), u"Section", "only 3D can be unlocked")
    views = [{u"id": 1, u"name": u"L1", u"kind": u"Floor plan"}, {u"id": 2, u"name": u"S1", u"kind": u"Section"},
             {u"id": 3, u"name": u"3D A", u"kind": u"3D"}]
    eq([v[u"id"] for v in core.view_rows(views, {}, u"name", False, excluded={u"kind": set([u"Section", u"3D"])})],
       [1], "one type on its own")
    eq(len(core.view_rows(views, {}, u"name", False, excluded={u"kind": set()})), 3, "all on")
    ok(core.tag_view_ok(u"Section")[0], "a ticked section takes tags")
    ok(not core.tag_view_ok(u"ThreeD", locked_3d=False)[0], "an unlocked 3D view does not")
    ok(core.tag_view_ok(u"ThreeD", locked_3d=True)[0], "a locked one does")


@check
def fake_selector_groups():
    """Two duct systems and a fab run joined to the first; a damper in the
    first; a terminal on the second."""
    DB.FabricationPart.__init__ = lambda self, *a, **k: None
    sa = type("Sys", (), {"Id": FId(700), "Name": u"Supply Air 2", "GetTypeId": lambda s: FId(0)})()
    ea = type("Sys", (), {"Id": FId(701), "Name": u"Extract Air 1", "GetTypeId": lambda s: FId(0)})()
    d1 = FElem(1, u"OST_DuctCurves")
    dmp = FElem(2, u"OST_DuctAccessory")
    d3 = FElem(3, u"OST_DuctCurves")

    class FFab(FElem, DB.FabricationPart):
        ServiceName = u"Supply 400"
    fab = FFab(4, u"OST_FabricationDuctwork")
    e1 = FElem(10, u"OST_DuctCurves")
    term = FElem(90, u"OST_DuctTerminal")
    for e, s_ in ((d1, sa), (dmp, sa), (d3, sa), (e1, ea)):
        e.MEPSystem = s_
    a = d1.add(1, (1, 0, 0), (1, 0, 0))
    b0, b1 = dmp.add(0, (1, 0, 0), (-1, 0, 0)), dmp.add(1, (2, 0, 0), (1, 0, 0))
    c0, c1 = d3.add(0, (2, 0, 0), (-1, 0, 0)), d3.add(1, (3, 0, 0), (1, 0, 0))
    f0 = fab.add(0, (3, 0, 0), (-1, 0, 0))
    fab.add(1, (4, 0, 0), (1, 0, 0))
    d1.add(0, (0, 0, 0), (-1, 0, 0))
    g0 = e1.add(0, (10, 0, 0), (-1, 0, 0))
    e1.add(1, (11, 0, 0), (1, 0, 0))
    t0 = term.add(0, (10, 0, 0), (1, 0, 0))
    join(a, b0)
    join(b1, c0)
    join(c1, f0)
    join(g0, t0)
    elems = [d1, dmp, d3, fab, e1]
    data = rv.selector_from_elems(FDoc(elems + [term]), elems, u"duct", core.DebugLog(False))
    names = [sd[u"name"] for sd in data[u"systems"]]
    eq(names, [u"Extract Air 1", u"Supply Air 2"], "two systems, natural order")
    sup = data[u"systems"][1]
    eq(sup[u"keys"], [1, 2, 3, 4], "the fab part joins Supply Air 2 through the duct")
    eq(sup[u"num"], [1, 3, 4], "the damper is walked, never numbered or selected")
    eq(data[u"passthrough"], set([2]), "accessory is pass-through")
    eq([i.Value for i in data[u"systems"][0][u"extras"]], [90], "terminal kept for isolating only")
    ok(90 not in data[u"nodes"], "terminal is never a node")
    eq(sorted([r[0] for r in data[u"rows"]]), [1, 3, 4, 10], "the tree never lists the damper")


# ============================================================
# Runner
# ============================================================

@check
def check_default_3d():
    eq(core.default_3d_names(u"drew"), [u"{3D - drew}", u"{3D}"], "user first")
    eq(core.default_3d_names(u""), [u"{3D}"], "no user")
    names = [u"Level 1 3D", u"{3D - amy}", u"{3D}", u"{3D - zed}"]
    eq(core.pick_default_3d(names, core.default_3d_names(u"zed")), u"{3D - zed}", "own view")
    eq(core.pick_default_3d([u"{3D - amy}", u"{3D}"], core.default_3d_names(u"")), u"{3D}", "not workshared")
    eq(core.pick_default_3d([u"{3D - sam}", u"Coord"], core.default_3d_names(u"drew")), u"{3D - sam}",
       "another user's default when there is no own one")
    eq(core.pick_default_3d([u"Coord"], core.default_3d_names(u"drew")), None, "none - make one")


@check
def check_combo_3d():
    views = [(u"a", u"Coord"), (u"b", u"{3D}")]
    items, idx = core.combo_3d_items(views, u"b")
    eq(items[0], (u"", u"Default 3D view"), "default first")
    eq(idx, 2, "chosen view selected")
    eq(core.combo_3d_items(views, u"gone")[1], 0, "missing view falls back to default")
    eq(core.combo_3d_items(views, u"")[1], 0, "nothing chosen")


# ---------------------------------------------------- groups (v1.9.0)

def _sys(*names):
    return [{u"key": n, u"keys": [], u"on": True, u"start": None, u"colour": u"#3FA75A"} for n in names]


def _names(systems):
    return u"".join([sd[u"key"] for sd in systems])


@check
def groups_made_together():
    systems = _sys(u"A", u"B", u"C", u"D", u"E")
    out, g = core.make_group(systems, {}, [u"B", u"D"], u"G1")
    eq(_names(out), u"ABDCE", "members gathered where the first one is, in list order")
    eq(g, {u"B": u"G1", u"D": u"G1"}, "both in G1")
    out, g = core.make_group(out, g, [u"A", u"D"], u"G2")
    eq(g, {u"A": u"G2", u"D": u"G2"}, "D leaves G1, which is left with one and is no group")
    eq(_names(out), u"ADBCE", "G2 gathered at A")
    eq(core.ungroup({u"A": u"G2", u"D": u"G2", u"B": u"G3", u"C": u"G3"}, [u"A"], u"ABCD"),
       {u"B": u"G3", u"C": u"G3"}, "ungroup breaks up the whole group of a selected member")
    eq(core.clean_groups({u"A": u"G1", u"B": u"G1", u"C": u"G2"}, u"AB"), {u"A": u"G1", u"B": u"G1"},
       "a lone member is no group")
    eq(core.group_label({u"B": u"G1", u"C": u"G1"}, u"C", _sys(u"A", u"B", u"C")), u"G1  2/2", "label")
    eq(core.next_group_id({u"A": u"G2"}, 1), (u"G3", 3), "ids never reused while in use")


def _move(systems, picked, before):
    out, new = core.move_many(systems, picked, before)
    return out, [out[i][u"key"] for i in new]


@check
def moves_keep_groups_whole():
    g = {u"B": u"G1", u"C": u"G1", u"D": u"G1"}
    systems = _sys(u"A", u"B", u"C", u"D", u"E")
    out, moved = _move(systems, set([3]), 5)
    eq(_names(out), u"ABCED", "D dragged to the end")
    eq(core.tidy_groups(out, g, moved)[1], {u"B": u"G1", u"C": u"G1"}, "moved away from its group: it leaves")
    out, moved = _move(systems, set([4]), 2)
    eq(_names(out), u"ABECD", "E dropped between B and C")
    eq(core.tidy_groups(out, g, moved)[1].get(u"E"), u"G1", "dropped inside a group: it joins")
    out, moved = _move(systems, set([1, 2, 3]), 0)
    eq(core.tidy_groups(out, g, moved)[1], g, "the whole group moved: still a group")
    out, moved = _move(systems, set([2]), 1)
    eq(_names(out), u"ACBDE", "C moved up inside its group")
    eq(core.tidy_groups(out, g, moved)[1], g, "moving inside the group changes nothing")
    two = {u"A": u"G1", u"B": u"G1", u"D": u"G2", u"E": u"G2"}
    out, moved = _move(_sys(u"A", u"B", u"C", u"D", u"E"), set([3, 4]), 1)
    eq(_names(out), u"ADEBC", "G2 dragged between A and B")
    out2, g2 = core.tidy_groups(out, two, moved)
    eq((_names(out2), g2), (u"ABDEC", two), "a whole group is never merged: it goes on after G1")
    gone = core.tidy_groups(_sys(u"A", u"B", u"E"), {u"A": u"G1", u"B": u"G1", u"C": u"G1"}, [u"E"], keep=[u"C"])[1]
    eq(gone.get(u"C"), u"G1", "a removed member keeps its group")


@check
def shift_steps_with_groups():
    g = {u"B": u"G1", u"C": u"G1", u"D": u"G1"}
    systems = _sys(u"A", u"B", u"C", u"D", u"E")
    out, g2, new = core.step_units(systems, g, set([2]), -1)
    eq((_names(out), g2, new), (u"ACBDE", g, set([1])), "a member steps inside its group")
    out, g2, new = core.step_units(systems, g, set([1]), -1)
    eq((_names(out), g2, new), (u"ABCDE", {u"C": u"G1", u"D": u"G1"}, set([1])),
       "past its top it leaves the group, just above it")
    out, g2, new = core.step_units(out, g2, new, -1)
    eq(_names(out), u"BACDE", "and the next step moves it on")
    out, g2, new = core.step_units(systems, g, set([3]), 1)
    eq((_names(out), g2), (u"ABCDE", {u"B": u"G1", u"C": u"G1"}), "past its end it leaves, just below")
    out, g2, new = core.step_units(systems, g, set([0]), 1)
    eq((_names(out), g2, new), (u"BCDAE", g, set([3])), "a lone system hops the whole group, never joins")
    out, g2, new = core.step_units(systems, g, set([1, 2, 3]), 1)
    eq((_names(out), new), (u"AEBCD", set([2, 3, 4])), "a whole group steps over the next part")
    two = {u"A": u"G1", u"B": u"G1", u"C": u"G2", u"D": u"G2"}
    out, g2, new = core.step_units(_sys(u"A", u"B", u"C", u"D"), two, set([2, 3]), -1)
    eq((_names(out), g2), (u"CDAB", two), "a group passes a group: both stay whole")


@check
def tidy_always_leaves_groups_together():
    import random
    rnd = random.Random(7)
    for trial in range(300):
        names = [u"S{0}".format(i) for i in range(9)]
        systems = _sys(*names)
        g = {}
        for k in names:
            if rnd.random() < 0.7:
                g[k] = u"G{0}".format(rnd.randint(1, 3))
        g = core.clean_groups(g, names)
        systems = core.gather_groups(systems, g)
        picked = set(rnd.sample(range(9), rnd.randint(1, 3)))
        out, moved = _move(systems, picked, rnd.randint(0, 9))
        if rnd.random() < 0.5:
            out, g2 = core.tidy_groups(out, g, moved)
        else:
            out, g2, new = core.step_units(systems, g, picked, rnd.choice([-1, 1]))
        for gid in set(g2.values()):
            idx = [i for i, sd in enumerate(out) if g2.get(sd[u"key"]) == gid]
            ok(idx == list(range(idx[0], idx[-1] + 1)), "trial {0}: {1} split up".format(trial, gid))
            ok(len(idx) >= 2, "trial {0}: {1} has one member".format(trial, gid))


def _lum(hex_text):
    r, g, b = core.hex_rgb(hex_text)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@check
def group_shades_dark_to_light():
    shades = core.group_shades(u"#2080FF", 5)
    ok(all([_lum(shades[i]) < _lum(shades[i + 1]) for i in range(4)]), "darkest first, lightest last")
    hues = [core.hex_hue(c) for c in shades]
    ok(all([core.hue_gap(h, hues[0]) < 0.02 for h in hues]), "one hue")
    systems = _sys(u"A", u"B", u"C", u"D")
    g = {u"B": u"G1", u"C": u"G1"}
    cols = core.system_colours(systems, g, {u"G1": u"#2080FF"})
    eq(cols[u"A"], u"#3FA75A", "a lone system keeps its own colour")
    ok(_lum(cols[u"B"]) < _lum(cols[u"C"]), "B before C is darker")
    swapped = core.system_colours([systems[0], systems[2], systems[1], systems[3]], g, {u"G1": u"#2080FF"})
    eq((swapped[u"C"], swapped[u"B"]), (cols[u"B"], cols[u"C"]), "re-ordered: the shades follow the order")


@check
def groups_stand_apart_in_colour():
    systems = _sys(u"A", u"B", u"C", u"D", u"E")
    systems[0][u"colour"] = u"#E03030"
    systems[1][u"colour"] = u"#E04040"
    systems[2][u"colour"] = u"#D83838"     # a lone system the group's red
    systems[3][u"colour"] = u"#30C0E0"
    systems[4][u"colour"] = u"#20B0D0"
    g = {u"A": u"G1", u"B": u"G1", u"D": u"G2", u"E": u"G2"}
    hues, changed = core.colour_groups(systems, g, {})
    ok(core.hue_gap(core.hex_hue(hues[u"G1"]), core.hex_hue(u"#E03030")) < 0.01, "G1 keeps its first member's hue")
    ok(core.hue_gap(core.hex_hue(hues[u"G1"]), core.hex_hue(hues[u"G2"])) >= 2 * core.GROUP_BAND, "groups apart")
    ok(u"C" in changed, "the lone red system takes another colour")
    for gid, c in hues.items():
        ok(core.hue_gap(core.hex_hue(changed[u"C"]), core.hex_hue(c)) >= core.GROUP_BAND,
           "its new colour is clear of {0}".format(gid))
    hues2, changed2 = core.colour_groups(systems, {u"A": u"G1", u"B": u"G1", u"C": u"G3", u"E": u"G3"},
                                         {u"G1": hues[u"G1"]})
    ok(core.hue_gap(core.hex_hue(hues2[u"G3"]), core.hex_hue(hues2[u"G1"])) >= 2 * core.GROUP_BAND,
       "a group whose first member is near another group's hue takes a far one")
    for gid, c in hues2.items():
        ok(core.hue_gap(core.hex_hue(c), core.MAGENTA_HUE) >= core.MAGENTA_GAP, "never the start's magenta")


def _group_fixture():
    nodes = straight_chain([1, 2, 3])                      # S finishes near x 3
    nodes.update(straight_chain([10, 11], x0=40))          # F far
    nodes.update(straight_chain([20, 21], x0=5))           # N near
    nodes.update(straight_chain([30, 31], x0=9))           # M a little further
    systems = [{u"key": u"S", u"keys": [1, 2, 3], u"start": 1, u"on": True},
               {u"key": u"F", u"keys": [10, 11], u"start": None, u"on": True},
               {u"key": u"N", u"keys": [20, 21], u"start": None, u"on": True},
               {u"key": u"M", u"keys": [30, 31], u"start": None, u"on": True}]
    return nodes, systems


@check
def auto_order_moves_groups_as_one():
    nodes, systems = _group_fixture()
    eq(_names(core.auto_order_units(nodes, systems, {})), _names(core.auto_order(nodes, systems)),
       "no groups: the same as before")
    g = {u"F": u"G1", u"N": u"G1"}
    eq(_names(core.auto_order_units(nodes, systems, g)), u"SMFN",
       "the group F,N is entered at F (far), so M comes first; the group keeps its order")
    systems[3][u"on"] = False
    eq(_names(core.auto_order_units(nodes, systems, {}))[-1], u"M", "unticked go last")


@check
def reorder_inside_a_group():
    nodes, systems = _group_fixture()
    g = {u"F": u"G1", u"N": u"G1", u"M": u"G1"}
    eq(_names(core.reorder_group(nodes, systems, g, u"G1")), u"SNMF",
       "first the member nearest where S finishes, then each nearest the last")
    systems[3][u"on"] = False
    eq(_names(core.reorder_group(nodes, systems, g, u"G1")), u"SNFM", "unticked members to the group's end")
    systems[3][u"on"] = True
    systems[1][u"start"] = 10
    eq(_names(core.reorder_group(nodes, systems, g, u"G1"))[1], u"F", "a picked start leads its group")


@check
def sheets_find_their_views():
    sheets = [{u"uid": u"a", u"number": u"M-10", u"name": u"Level 1", u"views": [1, 2], u"placed": 3},
              {u"uid": u"b", u"number": u"M-9", u"name": u"Level 2", u"views": [3], u"placed": 1},
              {u"uid": u"c", u"number": u"E-1", u"name": u"Lighting", u"views": [], u"placed": 1}]
    eq([sh[u"uid"] for sh in core.sheet_rows(sheets, u"")], [u"c", u"b", u"a"], "number order, naturally")
    eq([sh[u"uid"] for sh in core.sheet_rows(sheets, u"m level")], [u"b", u"a"], "every word typed")
    eq(core.sheet_views(sheets, set([u"a", u"b"])), set([1, 2, 3]), "views of the selected sheets")
    eq(core.sheet_views(sheets, set([u"b"])), set([3]), "only the selected sheet's views")
    eq(core.sheet_state(sheets[0], set([1, 2])), True, "all ticked")
    eq(core.sheet_state(sheets[0], set([2])), None, "some")
    eq(core.sheet_state(sheets[0], set()), False, "none")
    eq(core.sheet_state(sheets[2], set([1])), False, "no taggable views")


# ---------------------------------------------------- colours left behind (v1.9.1)

class _Col(object):
    def __init__(self, rgb):
        self.IsValid = rgb is not None
        self.Red, self.Green, self.Blue = rgb or (0, 0, 0)


class _Ogs(object):
    def __init__(self, rgbs, transparency=0):
        names = (u"ProjectionLineColor", u"CutLineColor", u"SurfaceForegroundPatternColor",
                 u"CutForegroundPatternColor")
        for n, c in zip(names, rgbs):
            setattr(self, n, _Col(c))
        self.SurfaceTransparency = transparency


@check
def tool_colouring_recognised():
    pal = core.hex_rgb(core.distinct_colours(5)[3])
    odd = (12, 34, 56)
    ok(core.rgb_hex(*odd) not in core.tool_palette(), "fixture: an odd colour the tool never gives")
    eq(core.is_tool_colouring([odd] * 4, core.COLOUR_MARK), True, "marked: the tool's, whatever the colour")
    eq(core.is_tool_colouring([pal] * 4, 0), True, "unmarked, a palette colour on all four: left by 1.9.0")
    eq(core.is_tool_colouring([core.hex_rgb(core.START_COLOUR)] * 4, 0), True, "the start colour")
    eq(core.is_tool_colouring([odd] * 4, 0), False, "someone's own colour override is left alone")
    eq(core.is_tool_colouring([pal, pal, odd, pal], core.COLOUR_MARK), False, "colours that differ: not the tool's")
    eq(core.is_tool_colouring([None] * 4, core.COLOUR_MARK), False, "no override")
    eq(rv.is_tool_colour(_Ogs([pal] * 4)), True, "read from Revit overrides")
    eq(rv.is_tool_colour(_Ogs([None] * 4)), False, "an element with no override")


@check
def open_after_run():
    sheets = [{u"uid": u"a", u"number": u"M-2", u"name": u"L1", u"views": [1, 2], u"placed": 2},
              {u"uid": u"b", u"number": u"M-1", u"name": u"L2", u"views": [3, 4], u"placed": 2}]
    full, views = core.open_list(sheets, set([1, 2, 3, 9]))
    eq([sh[u"uid"] for sh in full], [u"a"], "a sheet with every view ticked opens as the sheet")
    eq(views, [3, 9], "the other ticked views open on their own")
    full, views = core.open_list(sheets, set([1, 2, 3, 4]))
    eq(([sh[u"uid"] for sh in full], views), ([u"b", u"a"], []), "both sheets, in number order, no loose views")


@check
def smootherstep_eases():
    eq((ui.smootherstep(0.0), ui.smootherstep(1.0), ui.smootherstep(0.5)), (0.0, 1.0, 0.5), "ends and middle")
    eq((ui.smootherstep(-1.0), ui.smootherstep(2.0)), (0.0, 1.0), "clamped")
    ok(ui.smootherstep(0.02) < 0.001 and ui.smootherstep(0.98) > 0.999, "starts and stops with no speed")
    vals = [ui.smootherstep(i / 50.0) for i in range(51)]
    ok(all([vals[i] <= vals[i + 1] for i in range(50)]), "never goes back")


@check
def a_tag_for_every_category():
    air = {u"label": u"Air Terminal Tags : A", u"tag_cat": u"OST_DuctTerminalTags", u"id": 1}
    fab = {u"label": u"Fabrication Ductwork Tags : F", u"tag_cat": u"OST_FabricationDuctworkTags", u"id": 2}
    multi = {u"label": u"Multi-Category Tags : M", u"tag_cat": u"OST_MultiCategoryTags", u"id": 3}
    hosts = [u"OST_FabricationDuctwork"] * 3 + [u"OST_DuctTerminal", u"OST_DuctCurves"]
    by = core.tag_for_hosts([air, fab, multi], air, hosts)
    eq(by[u"OST_DuctTerminal"], air, "the chosen tag where it can go")
    eq(by[u"OST_FabricationDuctwork"], fab, "fabrication parts get the fabrication tag, not the air terminal one")
    eq(by[u"OST_DuctCurves"], multi, "no duct tag loaded: the multi-category tag")
    eq(core.tag_for_hosts([air], air, [u"OST_DuctCurves"])[u"OST_DuctCurves"], None, "nothing loaded can tag it")
    yes, no, others = core.tag_plan_note(by, air, hosts)
    eq((yes, no), (5, 0), "all five get a tag")
    eq(others, [(fab[u"label"], 3), (multi[u"label"], 1)], "the note names the other tags used")


@check
def untagged_only():
    eq(core.skip_tagging(set([7]), 9, True), True, "already tagged with anything: left alone")
    eq(core.skip_tagging(set(), 9, True), False, "untagged: tagged")
    eq(core.skip_tagging(set([7]), 9, False), False, "off: another tag goes on")
    eq(core.skip_tagging(set([9]), 9, False), True, "off: never the same tag twice")


def run_checks():
    failed = []
    for fn in CHECKS:
        try:
            fn()
        except Fail as ex:
            failed.append((fn.__name__, str(ex)))
        except Exception as ex:
            failed.append((fn.__name__, "{0}: {1}".format(type(ex).__name__, ex)))
    return failed


def _recursive_order(nodes, start_key=None):
    order = []
    seen = set()

    def visit(k, cid):
        seen.add(k)
        order.append(k)
        for nb, ncid in core.order_children(nodes[k], cid, nodes, seen):
            if nb not in seen:
                visit(nb, ncid)
    start = start_key if start_key is not None else core.choose_start(nodes, list(nodes))
    visit(start, core.start_inlet(nodes[start], nodes, set()))
    return order, 1


def _main_first(node, inlet_cid, nodes, visited):
    seq = ORIGINAL[u"order_children"](node, inlet_cid, nodes, visited)
    return list(reversed(seq))


ORIGINAL = {u"order_children": core.order_children}

SELFTEST = [
    (u"branches visited after the main", u"order_children", _main_first),
    (u"skip ignored", u"plan_numbers",
     lambda order, include, start, direction, pad:
     ORIGINAL_PLAN(order, lambda k: True, start, direction, pad)),
    (u"no zero padding", u"format_number", lambda n, pad: u"{0}".format(n)),
    (u"start at the smallest end", u"choose_start",
     lambda nodes, cands: sorted(cands, key=lambda k: (nodes[k].area(), k))[0]),
    (u"recursive walk", u"sequence_order", _recursive_order),
    (u"rewrite values already right", u"prepare_writes",
     lambda plan, read: ([(k, t) for k, n, t in plan], [], [])),
    (u"theme ignores the canvas", u"resolve_theme", lambda s, d: u"dark"),
    (u"typing does not narrow the list", u"filter_params", lambda params, typed: list(params)),
    (u"systems in found order, not nearest next", u"order_systems",
     lambda nodes, comps, starts=None, from_point=None: [(c, None) for c in comps]),
    (u"selector ignores the previous system's end", u"selector_order",
     lambda nodes, systems, include=None: (
         [k for sd in systems for k in core.sequence_order(
             dict((k, nodes[k]) for k in sd[u"keys"]), sd.get(u"start"))[0]], [], [(None, u"auto")] * len(systems))),
    (u"accessories numbered", u"sel_include", lambda key, p, l, t, s: key not in l),
    (u"fab parts left without a system", u"assign_systems",
     lambda nodes, labels: dict((k, labels.get(k) or u"piece:{0}".format(k)) for k in nodes)),
    (u"drop lands one row low", u"drop_index", lambda src, target: target),
    (u"shift-click ignored", u"click_selection",
     lambda selected, anchor, index, ctrl=False, shift=False: (set([index]), index)),
    (u"arrows stop at the ends", u"step_index",
     lambda n, current, delta: None if n <= 0 else (0 if current is None else max(0, min(n - 1, current + delta)))),
    (u"moving drops the other selected rows", u"move_many",
     lambda items, selected, before: (list(items), set(selected))),
    (u"the tool's own selection lights Remove", u"user_selection",
     lambda event_ids, own_ids, keys: sorted(set(event_ids or ()) & set(keys))),
    (u"start drawn like any system", u"start_keys", lambda order, systems, starts: set()),
    (u"butted parts left unjoined", u"link_open_ends", lambda nodes, tol: 0),
    (u"crop ignored", u"box_in_crop", lambda corners, mn, mx, use_z=False, tol=0.0: True),
    (u"view pick finds nothing", u"systems_holding", lambda systems, ids: []),
    (u"removed systems stay listed", u"split_gone", lambda systems, left_out: (list(systems), [])),
    (u"restore oldest first", u"bring_back",
     lambda systems, batches: [x for b in batches for a, x in b][::-1] + list(systems)),
    (u"move to ignores the position", u"move_to_position",
     lambda items, selected, position, counted: (list(items), set(selected), position)),
    (u"any text taken as a position", u"parse_position", lambda text, lo, hi: lo),
    (u"auto next takes the first left, not the nearest", u"next_nearest",
     lambda nodes, systems, last, placed, include=None: next(
         ((i, 0.0) for i, sd in enumerate(systems) if sd[u"key"] not in placed), None)),
    (u"value list ignores the other columns", u"column_values",
     lambda views, col, filters, excluded, only=None: sorted(
         dict(((v.get(col) or u""), 1) for v in views).items())),
    (u"select all does nothing", u"tick_values", lambda excluded, values, on: set(excluded or ())),
    (u"view filters ignored", u"view_rows",
     lambda views, filters, col, desc, only=None: list(views)),
    (u"colours repeat", u"distinct_colours", lambda n: [u"#FF0000"] * n),
    (u"tags allowed in sections on the selector", u"tag_view_ok",
     lambda vt, is_template=False, locked_3d=False, plans_only=False: (True, u"")),
    (u"pieces not chained", u"nearest_end", lambda nodes, candidates, point, visited=None: None),
    (u"numbers restart per system", u"full_order",
     lambda nodes, systems: (core.system_order(nodes, systems[-1][u"keys"], None), [(0, 0)] * len(systems))),
    (u"default 3D ignores the user's own view", u"pick_default_3d",
     lambda names, wanted: sorted([n for n in names if n.startswith(u"{3D")])[0] if any(
         n.startswith(u"{3D") for n in names) else None),
    (u"3D picker forgets the chosen view", u"combo_3d_items",
     lambda views, chosen: ([(u"", u"Default 3D view")] + list(views), 0)),
    (u"a member moved away stays in its group", u"tidy_groups",
     lambda systems, groups, moved, keep=(): (list(systems), dict(groups))),
    (u"Shift+Up drags a system into a group", u"step_units",
     lambda systems, groups, selected, delta, keep=(): core.move_block(systems, selected, delta)[:1] + (
         dict(groups), core.move_block(systems, selected, delta)[1])),
    (u"group shades lightest first", u"group_shades",
     lambda base, n: [core.shade(base, 1.0 - i / float(max(1, n - 1))) for i in range(n)]),
    (u"auto order ignores groups", u"auto_order_units",
     lambda nodes, systems, groups, include=None: core.auto_order(
         nodes, [sd for sd in systems if sd.get(u"on", True)]) + [sd for sd in systems if not sd.get(u"on", True)]),
    (u"reorder in group does nothing", u"reorder_group",
     lambda nodes, systems, groups, gid, include=None: core.gather_groups(systems, groups)),
    (u"lone systems keep a group's colour", u"colour_groups",
     lambda systems, groups, hues: (dict((g, u"#E03030") for g in set(groups.values())), {})),
    (u"grouping leaves members apart", u"make_group",
     lambda systems, groups, keys, gid: (list(systems), dict(list(groups.items()) + [(k, gid) for k in keys]))),
    (u"sheet selection ignored", u"sheet_views",
     lambda sheets, uids: set([v for sh in sheets for v in sh[u"views"]])),
    (u"left-over colours never found", u"is_tool_colouring", lambda colours, transparency: False),
    (u"ticked views open twice, on and off their sheet", u"open_list",
     lambda sheets, ticked: ([sh for sh in sheets if core.sheet_state(sh, ticked) is True], sorted(ticked))),
    (u"other categories left untagged", u"tag_for_hosts",
     lambda tags, chosen, hosts: dict((h, chosen if chosen is not None and core.tag_can_host(chosen[u"tag_cat"], h)
                                       else None) for h in set(hosts))),
    (u"untagged only ignored", u"skip_tagging", lambda have, tag_type, untagged_only: tag_type in have),
    (u"any one-colour override taken for the tool's", u"is_tool_colouring",
     lambda colours, transparency: bool(colours) and colours[0] is not None and all(
         [c == colours[0] for c in colours])),
]
ORIGINAL_PLAN = core.plan_numbers


def selftest():
    failures = 0
    rv_physical = rv.is_physical
    breaks = list(SELFTEST) + [(u"electrical / logical connectors kept", None, None)]
    for label, name, repl in breaks:
        if name is None:
            rv.is_physical = lambda c: True
        else:
            saved = getattr(core, name)
            setattr(core, name, repl)
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(1000)
        try:
            failed = run_checks()
        finally:
            sys.setrecursionlimit(old_limit)
            if name is None:
                rv.is_physical = rv_physical
            else:
                setattr(core, name, saved)
        if failed:
            print("  caught  {0}: {1} check(s) fail, e.g. {2}".format(label, len(failed), failed[0][0]))
        else:
            print("  MISSED  {0}: every check still passes".format(label))
            failures += 1
    print("selftest: {0} breakages, {1} failures".format(len(breaks), failures))
    return failures


def main():
    failed = run_checks()
    for name, msg in failed:
        print("FAIL  {0}: {1}".format(name, msg))
    print("bench_logic: {0} checks, {1} failed".format(len(CHECKS), len(failed)))
    rc = 1 if failed else 0
    if "--selftest" in sys.argv and selftest():
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
