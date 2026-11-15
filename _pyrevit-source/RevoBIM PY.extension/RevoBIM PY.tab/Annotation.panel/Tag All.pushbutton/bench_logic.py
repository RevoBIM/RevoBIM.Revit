# -*- coding: utf-8 -*-
"""Tag All - logic bench.

    python bench_logic.py
    python bench_logic.py --selftest

Every decision the tool takes lives in tagall_core as a plain function with
no Revit and no WPF in it, so it can be run here against a table of cases.
That is the single most valuable thing about the way this tool is laid out:
nearly every bug found late was found by one of these, and the ones that
survived to a live Revit session were all in the part that could not be
tested this way.

`--selftest` breaks a handful of those functions on purpose and confirms the
bench notices - a check nobody has tested does not work.
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import tagall_core as core   # noqa: E402


# A scratch copy must never carry __pycache__ across: a .pyc whose timestamp
# still matches the unmodified source is used in preference to the file the
# selftest just broke, and the breakage silently does not happen. That cost
# two "the bench passed with it broken" failures that were not real.
IGNORE_CACHE = shutil.ignore_patterns("__pycache__", "*.pyc")


FAILURES = []
COUNT = [0]


def check(label, got, wanted):
    COUNT[0] += 1
    if got != wanted:
        FAILURES.append(u"{0}: got {1!r}, wanted {2!r}".format(label, got, wanted))


def close(label, got, wanted, tolerance=1e-9):
    COUNT[0] += 1
    if abs(float(got) - float(wanted)) > tolerance:
        FAILURES.append(u"{0}: got {1}, wanted {2}".format(label, got, wanted))


# ============================================================
# element ids and keys
# ============================================================

class FakeId(object):
    def __init__(self, value, style="value"):
        if style == "value":
            self.Value = value
        elif style == "integer":
            self.IntegerValue = value


def bench_ids():
    check("eid_value None", core.eid_value(None), 0)
    check("eid_value .Value", core.eid_value(FakeId(1234)), 1234)
    check("eid_value .IntegerValue fallback", core.eid_value(FakeId(99, "integer")), 99)
    check("eid_value nothing useful", core.eid_value(object()), 0)

    check("host key", core.element_key(0, 5), (0, 5))
    check("link key", core.element_key(77, 5), (77, 5))
    check("invalid link id is host", core.element_key(-1, 5), (0, 5))
    check("None link id is host", core.element_key(None, 5), (0, 5))
    check("a link element and a host element of the same id are different things",
          core.element_key(77, 5) == core.element_key(0, 5), False)
    check("keys are hashable", len(set([core.element_key(0, 5), core.element_key(0, 5)])), 1)


# ============================================================
# units and geometry
# ============================================================

def bench_units():
    close("1 foot is 304.8mm", core.ft_to_mm(1.0), 304.8)
    close("304.8mm is 1 foot", core.mm_to_ft(304.8), 1.0)
    close("round trip", core.ft_to_mm(core.mm_to_ft(1500.0)), 1500.0, 1e-9)


def bench_head_point():
    right = (1.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    base = (10.0, 20.0, 3.0)

    head = core.head_point(base, right, up, 0, 0)
    check("no offset leaves the point alone", head, base)

    head = core.head_point(base, right, up, 304.8, 609.6)
    close("X offset is a real millimetre distance", head[0], 11.0)
    close("Y offset is a real millimetre distance", head[1], 22.0)
    close("Z is untouched", head[2], 3.0)

    # a section view: right is along the section, up is world Z
    head = core.head_point(base, (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 304.8, 304.8)
    close("the same numbers work in a section - X", head[1], 21.0)
    close("the same numbers work in a section - Z", head[2], 4.0)
    close("the section's X is untouched", head[0], 10.0)

    head = core.head_point(base, right, up, -304.8, -304.8)
    close("negative X goes the other way", head[0], 9.0)
    close("negative Y goes the other way", head[1], 19.0)


def tag_box(origin, right, up, width_mm, height_mm, down_mm=0.0, left_mm=0.0):
    """The four corners of a tag box, placed relative to the family origin.
    `left_mm` and `down_mm` say how far the box extends the other side of the
    origin - which is how a family whose origin is not its centre behaves."""
    def point(along_right, along_up):
        return core.add3(core.add3(origin, core.scale3(right, core.mm_to_ft(along_right))),
                         core.scale3(up, core.mm_to_ft(along_up)))
    return [point(-left_mm, -down_mm), point(width_mm - left_mm, -down_mm),
            point(-left_mm, height_mm - down_mm), point(width_mm - left_mm, height_mm - down_mm)]


def bench_elbow():
    right = (1.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    head = (5.0, 7.0, 0.0)

    check("a tag right of the element elbows to its left", core.elbow_side(600), 1.0)
    check("a tag left of the element elbows to its right", core.elbow_side(-600), -1.0)
    check("no sideways offset, no side", core.elbow_side(0), 0.0)

    check("no box falls back to the head", core.leader_anchor(head, right, up, None, 600), head)
    check("no elbow distance means no elbow", core.elbow_point(head, right, 600, 0), head)
    check("a zero X offset has no side to come back from",
          core.elbow_point(head, right, 0, 300), head)

    # a family whose origin IS its centre: the anchor is its left edge, same height
    box = tag_box(head, right, up, 1800, 400, down_mm=200, left_mm=900)
    anchor = core.leader_anchor(head, right, up, box, 600)
    close("the anchor sits on the outer edge", core.ft_to_mm(head[0] - anchor[0]), 900)
    close("at the head's height when the origin is central", anchor[1], 7.0)

    # a family whose origin is its bottom left - the case that tilted the leader
    box = tag_box(head, right, up, 1800, 400)
    anchor = core.leader_anchor(head, right, up, box, 600)
    close("the anchor is on the edge, not the origin", core.ft_to_mm(anchor[0] - head[0]), 0)
    close("and on the tag's centre line, half its height above the origin",
          core.ft_to_mm(anchor[1] - head[1]), 200)
    elbow = core.elbow_point(anchor, right, 600, 304.8)
    check("the elbow is level with the anchor",
          core.elbow_is_horizontal(anchor, elbow, up), True)
    close("and set back by the elbow distance from the edge",
          core.ft_to_mm(anchor[0] - elbow[0]), 304.8)
    check("levelling with the family origin instead would have been out",
          core.elbow_is_horizontal(head, elbow, up), False)
    close("by half the tag's height", core.off_level_mm(head, elbow, up), 200.0)

    # a tag on the left of the element elbows off its right edge
    box = tag_box(head, right, up, 1800, 400, down_mm=200, left_mm=900)
    anchor = core.leader_anchor(head, right, up, box, -600)
    close("the right edge this time", core.ft_to_mm(anchor[0] - head[0]), 900)
    elbow = core.elbow_point(anchor, right, -600, 304.8)
    close("and the elbow goes out to the right", core.ft_to_mm(elbow[0] - anchor[0]), 304.8)
    check("still level", core.elbow_is_horizontal(anchor, elbow, up), True)

    # a section view: right along the section, up world Z
    s_right, s_up = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    s_head = (2.0, 3.0, 4.0)
    s_box = tag_box(s_head, s_right, s_up, 1800, 400)
    s_anchor = core.leader_anchor(s_head, s_right, s_up, s_box, 600)
    s_elbow = core.elbow_point(s_anchor, s_right, 600, 304.8)
    check("horizontal in a section too",
          core.elbow_is_horizontal(s_anchor, s_elbow, s_up), True)
    close("the view's normal is untouched", s_elbow[0], 2.0)
    close("the centre line is found in the view's own up direction",
          core.ft_to_mm(s_anchor[2] - s_head[2]), 200)

    # a box that still carries the leader would put the edge out by the element
    contaminated = tag_box(head, right, up, 1800, 400, down_mm=200, left_mm=900) + \
        [core.add3(head, core.scale3(right, -core.mm_to_ft(6000)))]
    anchor = core.leader_anchor(head, right, up, contaminated, 600)
    close("a box measured with the leader on puts the anchor way out",
          core.ft_to_mm(head[0] - anchor[0]), 6000)

    elbow = core.elbow_point(head, right, 600, 1000000.0)
    check("a silly elbow distance still resolves to a point", len(elbow), 3)

    off = (5.0, 7.0 + core.mm_to_ft(50), 0.0)
    check("an elbow 50mm off level is reported as not horizontal",
          core.elbow_is_horizontal(head, off, up), False)
    check("half a millimetre off is within tolerance",
          core.elbow_is_horizontal(head, (5.0, 7.0 + core.mm_to_ft(0.5), 0.0), up), True)
    close("and the miss is reported in millimetres",
          core.off_level_mm(head, off, up), 50.0)


def bench_box_geometry():
    right, up = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    points = [(0.0, 0.0, 0.0), (2.0, 4.0, 0.0), (1.0, 1.0, 0.0)]
    check("centre of a box", core.centre_of(points), (1.0, 2.0, 0.0))
    check("no points, no centre", core.centre_of([]), None)
    check("furthest one way", core.extreme_along(points, right, True), (2.0, 4.0, 0.0))
    check("furthest the other", core.extreme_along(points, right, False), (0.0, 0.0, 0.0))
    check("furthest up", core.extreme_along(points, up, True), (2.0, 4.0, 0.0))
    check("nothing to be furthest", core.extreme_along([], right, True), None)


def bench_vectors():
    check("subtract", core.sub3((5.0, 5.0, 5.0), (1.0, 2.0, 3.0)), (4.0, 3.0, 2.0))
    close("dot", core.dot3((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), 32.0)
    close("a unit direction picks out its own component",
          core.dot3((3.0, 9.0, 0.0), (1.0, 0.0, 0.0)), 3.0)
    close("and square to it picks out nothing",
          core.dot3((3.0, 0.0, 0.0), (0.0, 1.0, 0.0)), 0.0)


def bench_bounds():
    lo_a, hi_a = (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)
    check("overlapping boxes", core.bounds_overlap(lo_a, hi_a, (5.0, 5.0, 5.0), (15.0, 15.0, 15.0)), True)
    check("touching boxes overlap", core.bounds_overlap(lo_a, hi_a, (10.0, 0.0, 0.0), (20.0, 10.0, 10.0)), True)
    check("apart in X", core.bounds_overlap(lo_a, hi_a, (11.0, 0.0, 0.0), (20.0, 10.0, 10.0)), False)
    check("apart in Z only is still apart", core.bounds_overlap(lo_a, hi_a, (0.0, 0.0, 11.0), (10.0, 10.0, 20.0)), False)
    check("an unbounded box overlaps everything", core.bounds_overlap(None, None, lo_a, hi_a), True)

    lo, hi = core.corners_bounds([(1.0, 2.0, 3.0), (-1.0, 5.0, 0.0)])
    check("corners min", lo, (-1.0, 2.0, 0.0))
    check("corners max", hi, (1.0, 5.0, 3.0))
    check("no corners", core.corners_bounds([]), (None, None))

    check("point inside", core.point_in_xy((5.0, 5.0, 99.0), (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)), True)
    check("point outside", core.point_in_xy((11.0, 5.0, 0.0), (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)), False)
    check("no crop means everything is inside", core.point_in_xy((999.0, 0.0, 0.0), None, None), True)


def bench_room_in_view():
    # a room from 0 to 3m, a cut plane at 1.2m
    min_z, max_z = 0.0, core.mm_to_ft(3000)
    cut = core.mm_to_ft(1200)
    check("the cut plane passes through the room",
          core.room_in_view(min_z, max_z, cut, (0.0, 0.0, 0.0), None, None), True)
    check("a cut plane above the room misses it",
          core.room_in_view(min_z, max_z, core.mm_to_ft(4000), (0.0, 0.0, 0.0), None, None), False)
    check("a cut plane below the room misses it",
          core.room_in_view(min_z, max_z, core.mm_to_ft(-500), (0.0, 0.0, 0.0), None, None), False)
    check("a cut plane a few mm above the top is still in, by the slack",
          core.room_in_view(min_z, max_z, max_z + core.mm_to_ft(5), (0.0, 0.0, 0.0), None, None), True)
    check("a cropped view leaves out a room outside the crop",
          core.room_in_view(min_z, max_z, cut, (50.0, 50.0, 0.0), (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)), False)
    check("a cropped view keeps a room inside the crop",
          core.room_in_view(min_z, max_z, cut, (5.0, 5.0, 0.0), (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)), True)
    check("no cut plane falls back to the crop alone",
          core.room_in_view(min_z, max_z, None, (50.0, 0.0, 0.0), (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)), False)


# ============================================================
# the planner - what gets tagged and what gets deleted
# ============================================================

def bench_plan_targets():
    a, b, c = (0, 1), (0, 2), (0, 3)
    candidates = [(a, "A"), (b, "B"), (c, "C")]
    tagged = {b: [101], c: [102, 103]}

    # plain: tag everything, delete nothing
    to_tag, to_delete = core.plan_targets(candidates, tagged, False, False)
    check("plain run tags everything", [key for key, _p in to_tag], [a, b, c])
    check("plain run deletes nothing", to_delete, [])

    # only untagged
    to_tag, to_delete = core.plan_targets(candidates, tagged, True, False)
    check("only untagged skips the tagged ones", [key for key, _p in to_tag], [a])
    check("only untagged deletes nothing", to_delete, [])

    # remove previous
    to_tag, to_delete = core.plan_targets(candidates, tagged, False, True)
    check("remove previous still tags everything", [key for key, _p in to_tag], [a, b, c])
    check("remove previous deletes every existing tag", sorted(to_delete), [101, 102, 103])

    # both together: nothing is deleted that will not be replaced
    to_tag, to_delete = core.plan_targets(candidates, tagged, True, True)
    check("both boxes: only the untagged are tagged", [key for key, _p in to_tag], [a])
    check("both boxes: nothing is deleted", to_delete, [])

    # an element carrying two tags
    to_tag, to_delete = core.plan_targets([(c, "C")], tagged, False, True)
    check("both of an element's tags are removed", sorted(to_delete), [102, 103])

    # nothing to do
    to_tag, to_delete = core.plan_targets([], tagged, False, True)
    check("no candidates, no work", (to_tag, to_delete), ([], []))

    # the payload survives
    to_tag, _delete = core.plan_targets(candidates, {}, False, False)
    check("the payload comes back with the key", to_tag[1][1], "B")


def bench_chunks():
    check("chunks of three", core.chunks([1, 2, 3, 4, 5, 6, 7], 3), [[1, 2, 3], [4, 5, 6], [7]])
    check("an empty list chunks to nothing", core.chunks([], 10), [])
    check("a chunk bigger than the list", core.chunks([1, 2], 40), [[1, 2]])
    check("a zero chunk size does not divide by zero", core.chunks([1, 2], 0), [[1], [2]])
    check("every element appears exactly once",
          sum([len(chunk) for chunk in core.chunks(list(range(97)), 40)]), 97)


def bench_progress():
    check("nothing to do is complete", core.percent(0, 0), 100)
    check("half way", core.percent(50, 100), 50)
    check("rounded down", core.percent(1, 3), 33)
    check("never over 100", core.percent(120, 100), 100)
    check("never under 0", core.percent(-5, 100), 0)
    check("the whole percent moved", core.should_repaint(1, 100, 0), True)
    check("the whole percent did not move", core.should_repaint(1, 1000, 0), False)
    check("the first call always paints", core.should_repaint(0, 100, -1), True)


# ============================================================
# tag families and categories
# ============================================================

def bench_singular():
    check("Pipes", core.singular(u"Pipes"), u"Pipe")
    check("Ducts", core.singular(u"Ducts"), u"Duct")
    check("Duct Accessories", core.singular(u"Duct Accessories"), u"Duct Accessory")
    check("Cable Trays", core.singular(u"Cable Trays"), u"Cable Tray")
    check("Mechanical Equipment stays put", core.singular(u"Mechanical Equipment"), u"Mechanical Equipment")
    check("Mass stays put", core.singular(u"Mass"), u"Mass")
    check("Walls", core.singular(u"Walls"), u"Wall")


def bench_tag_matching():
    check("Pipe Tags tag Pipes", core.tag_category_matches(u"Pipes", u"Pipe Tags"), True)
    check("Duct Tags tag Ducts", core.tag_category_matches(u"Ducts", u"Duct Tags"), True)
    check("Duct Accessory Tags tag Duct Accessories",
          core.tag_category_matches(u"Duct Accessories", u"Duct Accessory Tags"), True)
    check("Mechanical Equipment Tags tag Mechanical Equipment",
          core.tag_category_matches(u"Mechanical Equipment", u"Mechanical Equipment Tags"), True)
    check("Cable Tray Tags tag Cable Trays",
          core.tag_category_matches(u"Cable Trays", u"Cable Tray Tags"), True)
    check("Pipe Tags do not tag Ducts", core.tag_category_matches(u"Ducts", u"Pipe Tags"), False)
    check("Pipe Accessory Tags do not tag Pipes",
          core.tag_category_matches(u"Pipes", u"Pipe Accessory Tags"), False)
    check("Multi-Category Tags tag anything",
          core.tag_category_matches(u"Anything At All", u"Multi-Category Tags"), True)
    check("Keynote Tags never match by category",
          core.tag_category_matches(u"Pipes", u"Keynote Tags"), False)
    check("Material Tags never match by category",
          core.tag_category_matches(u"Walls", u"Material Tags"), False)
    check("Room Tags are the room tab's business, not this one",
          core.tag_category_matches(u"Rooms", u"Room Tags"), False)
    check("the singular form of the tag category also works",
          core.tag_category_matches(u"Pipes", u"Pipe Tag"), True)
    check("an empty tag category matches nothing",
          core.tag_category_matches(u"Pipes", u""), False)

    check("Pipe Tags -> Pipe", core.tag_base_name(u"Pipe Tags"), u"Pipe")
    check("Structural Column Tags -> Structural Column",
          core.tag_base_name(u"Structural Column Tags"), u"Structural Column")


def bench_default_tag():
    offered = [u"BGL_Pipe Tag : Size", u"Multi : Mark"]
    check("a category's default starts the row on it",
          core.default_tag_for(u"BGL_Pipe Tag : Size", offered), u"BGL_Pipe Tag : Size")
    check("a multi-category default is a default like any other",
          core.default_tag_for(u"Multi : Mark", offered), u"Multi : Mark")
    check("no default starts the row on <None>", core.default_tag_for(u"", offered), core.NONE_TAG)
    check("a default whose family has gone starts the row on <None>, not a guess",
          core.default_tag_for(u"BGL_Gone : Nope", offered), core.NONE_TAG)
    check("a category with no tags loaded starts on <None>",
          core.default_tag_for(u"BGL_Pipe Tag : Size", []), core.NONE_TAG)
    check("never the first tag on offer just because it is first",
          core.default_tag_for(u"", offered) != offered[0], True)

    settings = {}
    core.remember_tag(settings, u"Pipes", u"BGL_Pipe Tag : Size")
    check("a default is remembered against its category",
          core.remembered_tag(settings, u"Pipes"), u"BGL_Pipe Tag : Size")
    core.remember_tag(settings, u"Pipes", core.NONE_TAG)
    check("setting it back to <None> forgets it", core.remembered_tag(settings, u"Pipes"), u"")
    check("and leaves no empty line behind", len(settings), 0)
    core.remember_tag(settings, u"Ducts", u"  ")
    check("a blank default is not stored", len(settings), 0)


def bench_opening_scope():
    listed = [1, 2, 3, 4]

    current, narrowed, reason = core.opening_scope(listed, 9, True, [2, 3, 7], [])
    check("on a sheet, the list starts on the views placed on it", narrowed, set([2, 3]))
    check("ticked views, not current view", current, False)
    check("and says it was the sheet", reason, core.OPEN_SHEET)
    check("a view on the sheet this list cannot tag is left out",
          7 in narrowed, False)

    current, narrowed, reason = core.opening_scope(listed, 9, True, [2, 3], [3])
    check("viewports picked on the sheet narrow it further", narrowed, set([3]))
    check("and say so", reason, core.OPEN_SHEET_SELECTION)

    current, narrowed, reason = core.opening_scope(listed, 9, True, [2, 3], [7])
    check("a pick this list cannot tag falls back to the whole sheet", narrowed, set([2, 3]))
    check("reported as the sheet", reason, core.OPEN_SHEET)

    current, narrowed, reason = core.opening_scope(listed, 9, True, [7, 8], [])
    check("a sheet with nothing this list can tag starts on nothing", narrowed, set())
    check("and not on current view, which would be the sheet itself", current, False)
    check("reported as an empty sheet", reason, core.OPEN_SHEET_EMPTY)

    current, narrowed, reason = core.opening_scope(listed, 2, False, [], [])
    check("in a view this list can tag, Current view only", current, True)
    check("with nothing narrowed", narrowed, set())
    check("reported as the view", reason, core.OPEN_VIEW)

    current, narrowed, reason = core.opening_scope(listed, 2, False, [], [3, 4])
    check("views picked in the Project Browser win over the open view", narrowed, set([3, 4]))
    check("and turn Current view only off", current, False)
    check("reported as a selection", reason, core.OPEN_SELECTION)

    current, narrowed, reason = core.opening_scope(listed, 99, False, [], [])
    check("in a schedule or legend, the whole list and Ticked views", (current, narrowed), (False, set()))
    check("reported as unlisted", reason, core.OPEN_UNLISTED)

    # the same opening gives each tab its own answer
    plans_only = [2]
    _c, narrowed, _r = core.opening_scope(plans_only, 9, True, [2, 3], [])
    check("Room Tags on the same sheet starts on its plans alone", narrowed, set([2]))
    current, _n, reason = core.opening_scope(plans_only, 3, False, [], [])
    check("Room Tags open in a section has no current view to tag",
          (current, reason), (False, core.OPEN_UNLISTED))

    check("pressed once, Show All Views goes back to the sheet's views",
          core.opening_back_label(core.OPEN_SHEET), u"Show Sheet Views")
    check("or to the views picked", core.opening_back_label(core.OPEN_SELECTION), u"Show Selected Views")


def bench_type_display():
    check("family and type", core.type_display(u"BGL_Pipe Tag", u"Size"), u"BGL_Pipe Tag : Size")
    check("the same name twice is not repeated", core.type_display(u"Tag", u"Tag"), u"Tag")
    check("no type name", core.type_display(u"Tag", u""), u"Tag")
    check("no family name", core.type_display(u"", u"Size"), u"Size")
    check("neither", core.type_display(u"", u""), u"")


def bench_unique_names():
    check("the same link placed twice is numbered",
          core.unique_names([u"ARCH", u"STRUCT", u"ARCH"]),
          [u"ARCH", u"STRUCT", u"ARCH (2)"])
    check("three of them", core.unique_names([u"A", u"A", u"A"]), [u"A", u"A (2)", u"A (3)"])
    check("nothing to number", core.unique_names([]), [])


# ============================================================
# searching and sorting
# ============================================================

def bench_search():
    check("an empty query matches everything", core.matches_keywords(u"anything", u""), True)
    check("one word", core.matches_keywords(u"BGL_Pipe Tag", u"pipe"), True)
    check("case does not matter", core.matches_keywords(u"BGL_Pipe Tag", u"PIPE"), True)
    check("every word has to appear", core.matches_keywords(u"BGL_Pipe Tag", u"pipe tag"), True)
    check("order does not matter", core.matches_keywords(u"BGL_Pipe Tag", u"tag pipe"), True)
    check("a word that is not there", core.matches_keywords(u"BGL_Pipe Tag", u"pipe duct"), False)
    check("a number in the text", core.matches_keywords(u"Level 02 Plan", u"02"), True)


def bench_natural_order():
    names = [u"P-10", u"P-9", u"P-100", u"P-2"]
    check("natural order, not alphabetical",
          sorted(names, key=core.natural_key), [u"P-2", u"P-9", u"P-10", u"P-100"])
    check("levels come out in order",
          sorted([u"Level 10", u"Level 2", u"Level 1"], key=core.natural_key),
          [u"Level 1", u"Level 2", u"Level 10"])
    check("case is ignored", sorted([u"b", u"A"], key=core.natural_key), [u"A", u"b"])


def bench_pick_rows():
    """The highlight. Windows list conventions, and nothing to do with ticks."""
    rows = [10, 20, 30, 40, 50]

    selected, anchor = core.pick_rows(set(), None, 30, rows, False, False)
    check("a plain click highlights that row alone", selected, set([30]))
    check("and becomes the anchor", anchor, 30)

    selected, anchor = core.pick_rows(set([10, 20]), 10, 30, rows, False, False)
    check("a plain click replaces the highlight", selected, set([30]))

    selected, anchor = core.pick_rows(set([20]), 20, 40, rows, False, True)
    check("shift+click highlights the run", selected, set([20, 30, 40]))
    check("a run does not move the anchor", anchor, 20)

    selected, _a = core.pick_rows(set([40]), 40, 20, rows, False, True)
    check("a run picked upwards is the same run", selected, set([20, 30, 40]))

    selected, _a = core.pick_rows(set([20, 30, 40]), 20, 50, rows, False, True)
    check("shift again from the same anchor widens the run", selected, set([20, 30, 40, 50]))
    selected, _a = core.pick_rows(set([20, 30, 40, 50]), 20, 30, rows, False, True)
    check("and narrows it again", selected, set([20, 30]))

    selected, anchor = core.pick_rows(set([10]), 10, 30, rows, True, False)
    check("ctrl+click adds one row", selected, set([10, 30]))
    check("and moves the anchor to it", anchor, 30)
    selected, _a = core.pick_rows(set([10, 30]), 30, 30, rows, True, False)
    check("ctrl+click again takes it off", selected, set([10]))

    selected, _a = core.pick_rows(set([10]), 30, 50, rows, True, True)
    check("ctrl+shift adds a run to what is there", selected, set([10, 30, 40, 50]))

    selected, anchor = core.pick_rows(set(), None, 30, rows, False, True)
    check("shift with no anchor is a plain click", selected, set([30]))
    check("and sets the anchor", anchor, 30)
    selected, _a = core.pick_rows(set(), 99, 30, rows, False, True)
    check("shift with an anchor the search has hidden falls back too", selected, set([30]))

    on_screen = [10, 40, 50]
    selected, _a = core.pick_rows(set(), 10, 50, on_screen, False, True)
    check("a run means what it looks like on screen", selected, set([10, 40, 50]))

    before = set([10])
    core.pick_rows(before, 10, 30, rows, False, False)
    check("the set handed in is left alone", before, set([10]))


def bench_apply_tick():
    """The tick. Ticking one of a highlighted run ticks the run."""
    run = set([20, 30, 40])

    check("ticking a row inside the highlight ticks the whole highlight",
          core.apply_tick(set(), run, 30, True), set([20, 30, 40]))
    check("unticking one unticks the whole highlight",
          core.apply_tick(set([10, 20, 30, 40]), run, 30, False), set([10]))
    check("a tick outside the highlight is just that row",
          core.apply_tick(set(), run, 50, True), set([50]))
    check("and leaves the highlighted rows alone",
          core.apply_tick(set([20]), run, 50, True), set([20, 50]))
    check("a highlight of one is just that row",
          core.apply_tick(set(), set([30]), 30, True), set([30]))
    check("no highlight at all is just that row",
          core.apply_tick(set(), set(), 30, True), set([30]))
    check("ticking what is already ticked changes nothing",
          core.apply_tick(set([20, 30, 40]), run, 30, True), set([20, 30, 40]))
    check("ticks on rows outside the highlight survive",
          core.apply_tick(set([99]), run, 30, True), set([20, 30, 40, 99]))

    before = set([10])
    core.apply_tick(before, run, 30, True)
    check("the set handed in is left alone", before, set([10]))


def bench_views_from_sheets():
    sheets = [(1, [10, 20]), (2, [20, 30]), (3, []), (4, [40])]

    views, empty = core.views_from_sheets(sheets, set([1]))
    check("one sheet gives its views", views, [10, 20])
    check("and nothing is empty", empty, [])

    views, empty = core.views_from_sheets(sheets, set([1, 2]))
    check("a view on two ticked sheets is tagged once", views, [10, 20, 30])

    views, empty = core.views_from_sheets(sheets, set([1, 3]))
    check("a sheet with no views is named", empty, [3])
    check("and the rest still come through", views, [10, 20])

    views, _empty = core.views_from_sheets(sheets, set([4, 1]))
    check("views come out in sheet order, not tick order", views, [10, 20, 40])

    check("nothing ticked, nothing to do", core.views_from_sheets(sheets, set()), ([], []))
    check("no sheets at all", core.views_from_sheets([], set([1])), ([], []))
    check("a tick on a sheet that is no longer listed is ignored",
          core.views_from_sheets(sheets, set([99])), ([], []))


def _view_rows():
    return [
        (1, {"name": u"L01 Drainage", "type": u"Floor Plan : MEP", "g1": u"Mechanical", "g2": u"Level 01"}),
        (2, {"name": u"L02 Drainage", "type": u"Floor Plan : MEP", "g1": u"Mechanical", "g2": u"Level 02"}),
        (3, {"name": u"L10 Drainage", "type": u"Floor Plan : MEP", "g1": u"Mechanical", "g2": u"Level 10"}),
        (4, {"name": u"L01 Power", "type": u"Floor Plan : Elec", "g1": u"Electrical", "g2": u"Level 01"}),
        (5, {"name": u"Section A", "type": u"Section : Building", "g1": u"", "g2": u""}),
    ]


def bench_view_filters():
    rows = _view_rows()
    keys = lambda found: [row[0] for row in found]

    check("no filters, every row", keys(core.filter_rows(rows, {}, {})), [1, 2, 3, 4, 5])
    check("a keyword filter on the name",
          keys(core.filter_rows(rows, {"name": u"drainage"}, {})), [1, 2, 3])
    check("two words, any order",
          keys(core.filter_rows(rows, {"name": u"drainage l01"}, {})), [1])
    check("a tick filter keeps only the ticked values",
          keys(core.filter_rows(rows, {}, {"g1": set([u"Electrical"])})), [4])
    check("a tick filter of None is no filter",
          keys(core.filter_rows(rows, {}, {"g1": None})), [1, 2, 3, 4, 5])
    check("an empty tick filter shows nothing",
          keys(core.filter_rows(rows, {}, {"g1": set()})), [])
    check("blank is a value that can be ticked",
          keys(core.filter_rows(rows, {}, {"g1": set([u""])})), [5])
    check("filters on two columns compose",
          keys(core.filter_rows(rows, {"type": u"MEP"}, {"g2": set([u"Level 01"])})), [1])

    # a column's list ignores its own filter and honours the others
    choices = core.column_choices(rows, "g1", {}, {"g1": set([u"Electrical"])})
    check("a column's own filter is left out of its own list",
          [value for value, _n in choices], [u"Electrical", u"Mechanical", u""])
    choices = core.column_choices(rows, "g2", {}, {"g1": set([u"Mechanical"])})
    check("and the other columns' filters narrow it",
          [value for value, _n in choices], [u"Level 01", u"Level 02", u"Level 10"])
    check("with counts", dict(core.column_choices(rows, "g2", {}, {}))[u"Level 01"], 2)
    check("levels in natural order, not Level 01, Level 10, Level 02",
          [v for v, _n in core.column_choices(rows, "g2", {}, {}) if v][:3],
          [u"Level 01", u"Level 02", u"Level 10"])
    check("blank sorts last", core.column_choices(rows, "g1", {}, {})[-1][0], u"")

    listed = [u"A", u"B", u"C"]
    check("unticking one from no filter leaves the rest",
          core.tick_filter_after(None, listed, u"B", False), set([u"A", u"C"]))
    check("ticking the last one back removes the filter",
          core.tick_filter_after(set([u"A", u"C"]), listed, u"B", True), None)
    check("unticking everything leaves an empty filter, which shows nothing",
          core.tick_filter_after(set([u"A"]), listed, u"A", False), set())
    check("a column with a keyword is filtered", core.is_filtered("name", {"name": u"x"}, {}), True)
    check("a column with a tick filter is filtered",
          core.is_filtered("g1", {}, {"g1": set()}), True)
    check("a column with neither is not", core.is_filtered("g1", {"g1": u""}, {"g1": None}), False)


def bench_view_grouping():
    rows = _view_rows()
    groups = core.group_rows(rows, True, True)
    check("first-level groups in natural order, blank last",
          [first for first, _inner in groups], [u"Electrical", u"Mechanical", u""])
    mech = dict(groups)[u"Mechanical"]
    check("second-level groups in natural order",
          [second for second, _m in mech], [u"Level 01", u"Level 02", u"Level 10"])

    flat = core.group_rows(rows, False, False)
    check("no grouping is one group of everything", len(flat), 1)
    check("in natural order of name",
          [row[0] for row in flat[0][1][0][1]], [1, 4, 2, 3, 5])

    order = core.flatten_visible(groups, set(), True, True)
    check("everything open: every row, in drawing order", order, [4, 1, 2, 3, 5])
    order = core.flatten_visible(groups, set([core.group_id(u"Mechanical")]), True, True)
    check("a collapsed group drops out of the run order", order, [4, 5])
    order = core.flatten_visible(groups, set([core.group_id(u"Mechanical", u"Level 02")]), True, True)
    check("a collapsed second level drops only its own rows", order, [4, 1, 3, 5])
    order = core.flatten_visible(groups, set([core.group_id(u"Mechanical")]), False, False)
    check("a collapse means nothing when that level is not grouped",
          len(core.flatten_visible(core.group_rows(rows, False, False),
                                   set([core.group_id(u"")]), False, False)), 5)

    ids = core.all_group_ids(groups, True, True)
    check("collapse all reaches both levels",
          core.group_id(u"Mechanical") in ids and core.group_id(u"Mechanical", u"Level 01") in ids, True)
    check("and collapsing all of them hides every row",
          core.flatten_visible(groups, ids, True, True), [])

    check("a group tick ticks every view under it",
          core.toggle_group(set([9]), [1, 2]), set([1, 2, 9]))
    check("a group already all ticked unticks them",
          core.toggle_group(set([1, 2, 9]), [1, 2]), set([9]))
    check("a part-ticked group ticks the rest",
          core.toggle_group(set([1]), [1, 2]), set([1, 2]))
    check("an empty group changes nothing", core.toggle_group(set([1]), []), set([1]))


def bench_preselection():
    rows = _view_rows()
    keys = lambda found: [row[0] for row in found]
    check("views selected before opening narrow the list",
          keys(core.restrict_to_preselection(rows, set([2, 4]), False)), [2, 4])
    check("Show All Views shows them all", len(core.restrict_to_preselection(rows, set([2, 4]), True)), 5)
    check("nothing preselected, nothing narrowed", len(core.restrict_to_preselection(rows, set(), False)), 5)


def bench_tag_table():
    choices = {
        "pipe1": [u"Pipe : Size", u"Multi : Mark"],
        "pipe2": [u"Pipe : Size", u"Multi : Mark"],
        "duct1": [u"Duct : Size", u"Multi : Mark"],
    }
    applied, refused = core.apply_tag_to_rows(choices, set(["pipe1", "pipe2"]), "pipe1", u"Pipe : Size")
    check("a tag picked on a highlighted row lands on the whole highlight",
          sorted(applied), ["pipe1", "pipe2"])
    check("and nothing is refused", refused, [])

    applied, refused = core.apply_tag_to_rows(choices, set(["pipe1", "duct1"]), "pipe1", u"Pipe : Size")
    check("a row that cannot take the tag is refused", refused, ["duct1"])
    check("the others still get it", applied, ["pipe1"])

    applied, _r = core.apply_tag_to_rows(choices, set(["pipe1", "duct1"]), "pipe2", u"Pipe : Size")
    check("a row outside the highlight changes alone", applied, ["pipe2"])

    applied, _r = core.apply_tag_to_rows(choices, set(["pipe1"]), "pipe1", u"Multi : Mark")
    check("a highlight of one is just that row", applied, ["pipe1"])

    applied, refused = core.apply_tag_to_rows(choices, set(["pipe1", "duct1"]), None, core.NONE_TAG)
    check("<None> can go on anything", (sorted(applied), refused), (["duct1", "pipe1"], []))

    applied, refused = core.apply_tag_to_rows(choices, set(["pipe1", "duct1"]), None, u"Multi : Mark")
    check("the toolbar dropdown applies to the whole highlight",
          sorted(applied), ["duct1", "pipe1"])

    check("the tags every highlighted row can take",
          core.common_tags(choices, ["pipe1", "duct1"]), [u"Multi : Mark"])
    check("one category highlighted offers its own tags",
          core.common_tags(choices, ["pipe1", "pipe2"]), [u"Pipe : Size", u"Multi : Mark"])
    check("nothing highlighted offers nothing", core.common_tags(choices, []), [])
    check("every tag any highlighted row can take",
          core.any_tag_choices(choices, ["pipe1", "duct1"]),
          [u"Pipe : Size", u"Multi : Mark", u"Duct : Size"])


def bench_sorting():
    rows = [
        (1, {"number": u"M-10", "name": u"Level 01", "g1": u"Mechanical"}),
        (2, {"number": u"M-9", "name": u"Level 02", "g1": u""}),
        (3, {"number": u"E-1", "name": u"Level 01", "g1": u"Electrical"}),
        (4, {"number": u"M-100", "name": u"Roof", "g1": u"Mechanical"}),
    ]
    keys = lambda found: [row[0] for row in found]

    check("sheet numbers in natural order, not M-10 before M-9",
          keys(core.sort_rows(rows, [("number", False)])), [3, 2, 1, 4])
    check("and descending", keys(core.sort_rows(rows, [("number", True)])), [4, 1, 2, 3])
    check("blanks last ascending", keys(core.sort_rows(rows, [("g1", False)]))[-1], 2)
    check("and still last descending", keys(core.sort_rows(rows, [("g1", True)]))[-1], 2)
    check("a second level breaks the first level's ties",
          keys(core.sort_rows(rows, [("name", False), ("number", False)])), [3, 1, 2, 4])
    check("each level keeps its own direction",
          keys(core.sort_rows(rows, [("name", False), ("number", True)])), [1, 3, 2, 4])
    check("no sort leaves the order alone", keys(core.sort_rows(rows, [])), [1, 2, 3, 4])

    stack = [("number", False)]
    check("clicking the only sorted column flips it",
          core.next_sort_stack(stack, "number", False), [("number", True)])
    check("clicking another column starts again on it",
          core.next_sort_stack([("number", False), ("g1", True)], "name", False), [("name", False)])
    check("clicking a column that is one of several starts again on it alone",
          core.next_sort_stack([("number", False), ("g1", True)], "g1", False), [("g1", False)])
    check("shift adds a level beneath",
          core.next_sort_stack(stack, "g1", True), [("number", False), ("g1", False)])
    check("shift on a column already in the sort flips that level alone",
          core.next_sort_stack([("number", False), ("g1", False)], "g1", True),
          [("number", False), ("g1", True)])
    full = [(u"c{0}".format(i), False) for i in range(core.MAX_SORT_LEVELS)]
    check("no more than six levels", len(core.next_sort_stack(full, "extra", True)), core.MAX_SORT_LEVELS)
    check("nothing sorted yet, a click sorts", core.next_sort_stack([], "name", False), [("name", False)])

    check("one level shows its arrow alone", core.sort_badge([("number", False)], "number"), u"\u25b2")
    check("several levels show their place",
          core.sort_badge([("number", False), ("g1", True)], "g1"), u"2\u25bc")
    check("a column out of the sort shows nothing", core.sort_badge([("number", False)], "g1"), u"")


def bench_column_widths():
    widths = [70, 175, 88, 88, 52]
    floors = [56, 90, 60, 60, 44]

    out = core.resize_columns(widths, 1, 20, floors)
    check("dragging an edge right widens the column", out[1], 195.0)
    check("and narrows the one to its right by the same", out[2], 68.0)
    check("the others are untouched", (out[0], out[3], out[4]), (70.0, 88.0, 52.0))
    check("the total never changes", sum(out), float(sum(widths)))

    out = core.resize_columns(widths, 1, -20, floors)
    check("dragging left gives the width to the right-hand column", (out[1], out[2]), (155.0, 108.0))

    out = core.resize_columns(widths, 1, 500, floors)
    check("a column cannot squeeze its neighbour below its floor", out[2], 60.0)
    check("and grows only as far as that allows", out[1], 203.0)
    out = core.resize_columns(widths, 1, -500, floors)
    check("nor shrink itself below its own floor", out[1], 90.0)
    check("and the total still holds", sum(out), float(sum(widths)))

    check("the last column has no right-hand edge to drag",
          core.resize_columns(widths, 4, 30, floors), [float(w) for w in widths])
    check("nor does a column that does not exist",
          core.resize_columns(widths, -1, 30, floors), [float(w) for w in widths])

    check("widths are remembered as whole pixels", core.widths_text([70.4, 175.6]), u"70,176")
    check("and read back", core.parse_widths(u"80,160,90,90,52", widths, floors), [80.0, 160.0, 90.0, 90.0, 52.0])
    check("nothing remembered is the defaults", core.parse_widths(u"", widths, floors), [float(w) for w in widths])
    check("a different column count is the defaults",
          core.parse_widths(u"80,160,90", widths, floors), [float(w) for w in widths])
    check("rubbish is the defaults", core.parse_widths(u"80,wide,90,90,52", widths, floors),
          [float(w) for w in widths])
    check("a zero is the defaults", core.parse_widths(u"80,0,90,90,52", widths, floors),
          [float(w) for w in widths])
    check("a remembered width below its floor is lifted to it",
          core.parse_widths(u"10,160,90,90,52", widths, floors)[0], 56.0)


# ====================== the shrink drawer, on a stand-in window ======================

NAN = float("nan")


class _Root(object):
    def __init__(self):
        self.Height = NAN
        self.VerticalAlignment = "Stretch"


class _Part(object):
    def __init__(self, visibility="Visible"):
        self.Visibility = visibility


class _Header(object):
    def __init__(self, height=40.0):
        self.ActualHeight = height
        self.CornerRadius = "6,6,0,0"


class _Window(object):
    def __init__(self, left=100.0, top=120.0, width=1200.0, height=800.0,
                 size_to_content="Manual", min_height=620.0):
        self.Left = left
        self.Top = top
        self.Width = width
        self.Height = height
        self.ActualHeight = height if height == height else 300.0
        self.MinHeight = min_height
        self.SizeToContent = size_to_content
        self.Content = _Root()
        self.Owner = None
        self.owned = []
        self.activated = 0


class _Timer(object):
    def __init__(self):
        self.stopped = False

    def Stop(self):
        self.stopped = True


class _Platform(object):
    """Stands in for WpfPlatform. Its timer either runs every tick at once,
    on a clock that moves 20 ms a read, or holds them for the test to step."""

    def __init__(self, area=(0.0, 1040.0), run_now=True):
        self.area = area
        self.run_now = run_now
        self.clock = 0.0
        self.ticks = []
        self.frames = []
        self.pins = []
        self.fail_after = None
        self.looks = []
        self.parts = {}

    def on_click(self, button, handler):
        pass

    def on_closed(self, window, handler):
        window.closed_handler = handler

    def height(self, window):
        return window.Height if window.Height == window.Height else window.ActualHeight

    def owner(self, window):
        return window.Owner

    def owned(self, window):
        return list(window.owned)

    def manual_size(self):
        return "Manual"

    def bar_height(self, header, window):
        return header.ActualHeight + 2.0

    def work_area(self, window):
        return self.area

    def pin(self, window, height):
        window.Content.Height = height
        window.Content.VerticalAlignment = "Top"
        self.pins.append(height)

    def unpin(self, window):
        window.Content.Height = NAN
        window.Content.VerticalAlignment = "Stretch"

    def parts_beside(self, header, window):
        return self.parts.get(id(window), [])

    def visibility(self, part):
        return part.Visibility

    def collapse(self, part):
        part.Visibility = "Collapsed"

    def restore_visibility(self, part, visibility):
        part.Visibility = visibility

    def round_header(self, header):
        previous = header.CornerRadius
        header.CornerRadius = "6"
        return previous

    def restore_header(self, header, previous):
        if previous is not None:
            header.CornerRadius = previous

    def shrunk_look(self, button, shrunk):
        self.looks.append(shrunk)

    def activate(self, window):
        window.activated += 1

    def now(self):
        self.clock += 20.0
        if self.fail_after is not None and self.clock > self.fail_after:
            raise RuntimeError("a frame threw")
        return self.clock

    def timer(self, milliseconds, tick):
        timer = _Timer()
        if not self.run_now:
            self.ticks.append((timer, tick))
            return timer
        for _step in range(1000):
            if timer.stopped:
                break
            tick(timer)
            self.frames.append(None)
        self.ticks_run = _step
        return timer


def _drawer_for(window, platform, parts=None):
    import tagall_drawer
    platform.parts[id(window)] = parts if parts is not None else [_Part(), _Part(), _Part("Collapsed")]
    return tagall_drawer.WindowDrawer(window, _Header(), object(), platform)


def _fresh_drawers():
    import tagall_drawer
    del tagall_drawer.DRAWERS[:]
    return tagall_drawer


def _contrast(a, b):
    def channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(hex_text):
        r, g, b = [int(hex_text[i:i + 2], 16) for i in (1, 3, 5)]
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    high, low = sorted([luminance(a), luminance(b)], reverse=True)
    return (high + 0.05) / (low + 0.05)


# every pairing in the tool that carries text or a glyph someone has to read:
# (foreground, background, where it is)
TEXT_PAIRS = [
    ("TextBrush", surface, "body text") for surface in
    ("WindowBrush", "CardBrush", "FieldBrush", "BarBrush", "HeaderRowBrush", "SelectBrush", "HoverBrush")
] + [
    ("MutedBrush", surface, "muted text") for surface in
    ("WindowBrush", "CardBrush", "FieldBrush", "BarBrush", "HeaderRowBrush")
] + [
    (accent, surface, "accent text") for accent in ("BlueBrush", "OrangeBrush", "RedBrush", "LinkBrush")
    for surface in ("CardBrush", "FieldBrush", "BarBrush")
] + [
    ("OrangeBrush", "HeaderRowBrush", "a sort badge on a heading"),
    ("MutedBrush", "HeaderRowBrush", "a column heading"),
    ("OnAccentBrush", "BlueBrush", "the tick in a ticked box"),
    ("OnAccentBrush", "LinkBrush", "the linked models badge"),
]


def bench_revit_dark_palette():
    if "clr" not in sys.modules:
        import types
        stub = types.ModuleType("clr")
        stub.AddReference = lambda name: None
        sys.modules["clr"] = stub
    import theme as theme_module
    dark = theme_module.DARK
    # sampled from Revit's own dark Project Browser
    # and the same values the rest of the suite uses for dark
    for key, revit in (("WindowBrush", "#3C4454"), ("CardBrush", "#353D4B"), ("FieldBrush", "#2D3441"),
                       ("BarBrush", "#222933"), ("HeaderRowBrush", "#323C48"), ("HoverBrush", "#444E5E"),
                       ("SelectBrush", "#3A7392"), ("EdgeBrush", "#4A5464"), ("ChromeEdgeBrush", "#515C6B"),
                       ("TextBrush", "#EEF0F4"), ("BlueBrush", "#5AAEEB")):
        check(u"dark {0} is Revit's own {1}".format(key, revit), dark[key].upper(), revit)
    # held to the dark palette, the one matched to Revit. The light palette is
    # the house standard's, and its orange sits at 4.1:1 on white - a gap in
    # the standard, not something this tool should quietly diverge on
    for palette_name, palette in (("dark", dark),):
        for foreground, background, where in TEXT_PAIRS:
            COUNT[0] += 1
            ratio = _contrast(palette[foreground], palette[background])
            if ratio < 4.5:
                FAILURES.append(u"{0}: {1} on {2} ({3}) is {4:.2f}:1, under 4.5:1".format(
                    palette_name, foreground, background, where, ratio))
    COUNT[0] += 1
    if _contrast("#FFFFFF", dark["CloseHoverBrush"]) < 4.5:
        FAILURES.append(u"dark: the white close cross is unreadable on CloseHoverBrush")


def bench_family_groups():
    start = dict(core.GROUP_START)
    check("the tab opens with Categories open and the other two shut",
          (start["views"], start["categories"], start["families"]), (False, True, False))
    check("the groups stack Views / Sheets, Categories, Families to tag",
          core.GROUP_ORDER, ("views", "categories", "families"))
    views_open = {"views": True, "categories": False, "families": False}
    opened, done = core.toggle_family_group(views_open, "categories", False)
    check("opening Categories the first time shuts Views / Sheets",
          (opened["views"], opened["categories"], done), (False, True, True))
    opened, done = core.toggle_family_group(opened, "views", done)
    opened, done = core.toggle_family_group(opened, "categories", done)
    check("shutting Categories leaves Views / Sheets alone", (opened["views"], opened["categories"]), (True, False))
    opened, done = core.toggle_family_group(opened, "categories", done)
    check("opening Categories again does not shut Views / Sheets", (opened["views"], opened["categories"]), (True, True))
    shut = {"views": False, "categories": False, "families": False}
    shut, done2 = core.toggle_family_group(shut, "categories", False)
    check("Views / Sheets already shut: Categories opens and the first round is spent",
          (shut["views"], shut["categories"], done2), (False, True, True))
    fam, done3 = core.toggle_family_group(views_open, "families", False)
    check("Families to tag opens without touching the others or the first round",
          (fam["views"], fam["families"], done3), (True, True, False))
    fam, done3 = core.toggle_family_group(fam, "families", done3)
    check("and shuts again", fam["families"], False)
    shut_cats, _done = core.toggle_family_group(start, "categories", False)
    check("shutting Categories is not its first opening", (shut_cats["categories"], _done), (False, False))
    check("the caller's dict is left alone", start, dict(core.GROUP_START))
    opening, closing, steady = core.group_changes(views_open, opened_once(views_open))
    check("the first Categories open slides Categories open and Views / Sheets shut together",
          (opening, closing, steady), (["categories"], ["views"], []))
    opening, closing, steady = core.group_changes({"views": True, "categories": True, "families": False},
                                                  {"views": True, "categories": True, "families": True})
    check("a group open throughout is steady and takes up the slack",
          (opening, closing, steady), (["families"], [], ["views", "categories"]))
    close("a slide starts where it starts", core.slide_height(0, 300, 0), 0.0)
    close("eases out like the drawer: most of the way at half time", core.slide_height(0, 300, 0.5), 262.5)
    close("and lands exactly", core.slide_height(300, 0, 1.0), 0.0)
    close("never below nothing, however late the tick", core.slide_height(300, 0, 3.0), 0.0)
    heights, filler = core.group_heights(start)
    check("an open group shares the height, a shut one is its header", heights, [u"auto", u"star", u"auto"])
    check("with a group open the filler takes nothing", filler, u"auto")
    heights, filler = core.group_heights({"views": False, "categories": False, "families": False})
    check("every group shut: the filler takes the slack so the options stay at the bottom",
          (heights, filler), ([u"auto", u"auto", u"auto"], u"star"))
    shut = {"views": False, "categories": False, "families": False}
    check("every group shut on Family Tags: the window fits its bars", core.fit_window(shut, True, False), True)
    check("any group open: the window keeps its height", core.fit_window(start, True, False), False)
    check("never on Room Tags", core.fit_window(shut, False, False), False)
    check("never full screen or parked on the taskbar", core.fit_window(shut, True, True), False)
    # the source buttons on the Views / Sheets header
    check("the Sheets tab lights Sheets", core.view_source(1, True), core.SOURCE_SHEETS)
    check("the Views tab on Current view only lights Current view", core.view_source(0, True), core.SOURCE_CURRENT)
    check("the Views tab on ticked views lights Ticked views", core.view_source(0, False), core.SOURCE_TICKED)
    index, current, groups = core.pick_view_source(start, core.SOURCE_TICKED)
    check("Ticked views: the Views tab, off Current view only, Views / Sheets open, Categories shut",
          (index, current, groups["views"], groups["categories"], groups["families"]), (0, False, True, False, False))
    families_open = {"views": False, "categories": True, "families": True}
    index, current, groups = core.pick_view_source(families_open, core.SOURCE_SHEETS)
    check("Sheets: the Sheets tab, the radios left alone, Views / Sheets open, the other two shut",
          (index, current, groups["views"], groups["categories"], groups["families"]), (1, None, True, False, False))
    index, current, groups = core.pick_view_source(families_open, core.SOURCE_TICKED)
    check("Ticked views shuts Families to tag as well", groups["families"], False)
    picking = {"views": True, "categories": False, "families": True}
    index, current, groups = core.pick_view_source(picking, core.SOURCE_CURRENT)
    check("Current view: the Views tab on Current view only, Views / Sheets shut, Categories open",
          (index, current, groups["views"], groups["categories"], groups["families"]),
          (0, True, False, True, True))
    check("a family shows its types by default", core.family_open((u"Doors", u"Single"), set(), u""), True)
    check("one shut by hand stays shut", core.family_open((u"Doors", u"Single"), set([(u"Doors", u"Single")]), u""), False)
    check("a search opens it again", core.family_open((u"Doors", u"Single"), set([(u"Doors", u"Single")]), u"dbl"), True)


def opened_once(state):
    return core.toggle_family_group(state, "categories", False)[0]


def bench_edges_and_links():
    check("a double-click on the top edge fills the screen", core.edge_fills_screen("GripN"), True)
    check("and on the bottom edge", core.edge_fills_screen("GripS"), True)
    check("the side edges and the corners only resize",
          [core.edge_fills_screen(name) for name in ("GripE", "GripW", "GripNE", "GripNW", "GripSE", "GripSW")],
          [False] * 6)
    close("the linked models list drags taller", core.links_height(240), 240.0)
    close("but never shorter than a couple of rows", core.links_height(-50), core.LINKS_MIN_H)
    close("or taller than most of a screen", core.links_height(5000), core.LINKS_MAX_H)
    check("a blank saved height is the list as built", core.saved_links_height(u""), None)
    check("so is a damaged one", core.saved_links_height(u"tall"), None)
    close("a saved height comes back", core.saved_links_height(u"260"), 260.0)
    close("held to the limits on the way in", core.saved_links_height(u"9000"), core.LINKS_MAX_H)
    after = core.show_families_group({"views": True, "categories": True, "families": False})
    check("Add ticked shuts Categories and opens Families to tag, leaving Views / Sheets",
          (after["views"], after["categories"], after["families"]), (True, False, True))


def bench_after_placing():
    check("Untangle alone stays on", core.after_placing(True, False), (True, False))
    check("Tag Tidy alone stays on", core.after_placing(False, True), (False, True))
    check("neither is fine", core.after_placing(False, False), (False, False))
    check("both from an older settings file: Tag Tidy wins, as it did in the run",
          core.after_placing(True, True), (False, True))
    check("with Untangle ticked, Tag Tidy cannot be", core.after_placing_enabled(True, False), (True, False))
    check("with Tag Tidy ticked, Untangle cannot be", core.after_placing_enabled(False, True), (False, True))
    check("with neither ticked, either can be", core.after_placing_enabled(False, False), (True, True))


def bench_untangle():
    gap = 0.1
    # two tags on top of each other: the upper stays, the lower drops clear
    offsets = core.untangle_offsets([("a", (0.0, 4.0, 10.0, 11.0)), ("b", (1.0, 5.0, 9.5, 10.5))], gap)
    close("the topmost tag never moves", offsets["a"], 0.0)
    close("the one under it drops to just below it, the gap apart", offsets["b"], -(10.5 - (10.0 - gap)))
    # side by side, not touching: left alone
    offsets = core.untangle_offsets([("a", (0.0, 2.0, 10.0, 11.0)), ("b", (3.0, 5.0, 10.0, 11.0))], gap)
    check("tags side by side that do not touch are left alone", (offsets["a"], offsets["b"]), (0.0, 0.0))
    offsets = core.untangle_offsets([("a", (0.0, 2.0, 10.0, 11.0)), ("b", (2.05, 5.0, 10.0, 11.0))], gap)
    check("but closer than the gap across counts as touching", offsets["b"] < 0, True)
    # a pile of three becomes a stack
    pile = [("a", (0.0, 4.0, 10.0, 11.0)), ("b", (0.0, 4.0, 10.0, 11.0)), ("c", (0.0, 4.0, 9.9, 10.9))]
    offsets = core.untangle_offsets(pile, gap)
    tops = sorted([box[3] + offsets[key] for key, box in pile], reverse=True)
    close("a pile of three stacks: first top", tops[0], 11.0)
    close("second sits one tag and a gap lower", tops[1], 11.0 - 1.0 - gap)
    close("third one more", tops[2], 11.0 - 2.0 - 2 * gap)
    # whatever the mess, nothing touches afterwards and nothing moves up
    import random
    rng = random.Random(7)
    mess = []
    for index in range(60):
        x = rng.uniform(0, 20)
        y = rng.uniform(0, 10)
        mess.append((index, (x, x + rng.uniform(1, 4), y, y + rng.uniform(0.3, 0.8))))
    offsets = core.untangle_offsets(mess, gap)
    after = [(box[0], box[1], box[2] + offsets[key], box[3] + offsets[key]) for key, box in mess]
    touching = 0
    for i in range(len(after)):
        for j in range(i + 1, len(after)):
            shrunk_a = (after[i][0] + 1e-9, after[i][1] - 1e-9, after[i][2] + 1e-9, after[i][3] - 1e-9)
            if core.boxes_touch(shrunk_a, after[j], gap - 1e-6):
                touching += 1
    check("sixty tags dropped anywhere: none touch once untangled", touching, 0)
    check("and none was moved up", max(offsets.values()) <= 0.0, True)
    check("a tag Revit could not measure is left out rather than guessed",
          core.untangle_offsets([("a", None), ("b", (0.0, 1.0, 0.0, 1.0))], gap), {"b": 0.0})
    # the gap is paper mm through the view scale
    close("1 mm on paper at 1:100 is 100 mm in the model", core.untangle_gap_ft(100) * 304.8, 100.0)
    close("a view with no scale counts as 1:1", core.untangle_gap_ft(0) * 304.8, 1.0)
    # boxes in the view's own axes, so sections untangle as well as plans
    box = core.view_box([(1.0, 5.0, 2.0), (3.0, 5.0, 4.0)], (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    check("a section's box reads across along right and up along Z", box, (1.0, 3.0, 2.0, 4.0))
    check("no corners, no box", core.view_box(None, (1, 0, 0), (0, 1, 0)), None)
    check("the measured corners travel down with the tag",
          core.shift_corners([(0.0, 5.0, 0.0)], (0.0, 1.0, 0.0), -2.0), [(0.0, 3.0, 0.0)])
    check("untangling is off until ticked", core.DEFAULTS["untangle"], u"0")


def bench_tidy_hook():
    tab = os.path.join(u"C:", u"ext", u"RevoBIM PY.tab")
    button = os.path.join(tab, u"Annotation.panel", u"Tag All.pushbutton")
    listing = lambda folder: [u"Coordination.panel", u"Annotation.panel", u"Tags.panel",
                              u"notes.txt"]
    dirs = core.tidy_search_dirs(button, listing)
    check("Tag Tidy is looked for beside Tag All first",
          dirs[0], os.path.join(tab, u"Annotation.panel", u"Tag Tidy.pulldown"))
    check("then on every other panel of the tab, once each, never in a file",
          dirs[1:], [os.path.join(tab, u"Coordination.panel", u"Tag Tidy.pulldown"),
                     os.path.join(tab, u"Tags.panel", u"Tag Tidy.pulldown")])

    def broken(folder):
        raise OSError("no tab")
    check("a tab that cannot be listed still tries beside Tag All",
          core.tidy_search_dirs(button, broken),
          [os.path.join(tab, u"Annotation.panel", u"Tag Tidy.pulldown")])
    check("a run with leaders tells Tag Tidy to switch on any missing leader",
          core.tidy_overrides({"leader": True}), {"no_leader": u"switch_on"})
    check("a run without leaders tells Tag Tidy to leave leaderless tags alone",
          core.tidy_overrides({"leader": False}), {"no_leader": u"skip"})
    answer = {"ok": True, "summary": u"3 tags stacked in 1 column, all clear", "moved": 3,
              "kept": 0, "rows": [(u"done", u"Pipe Tags 1", u"fine"),
                                  (u"clash", u"Pipe Tags 2", u"its text crosses a duct"),
                                  (u"skip", u"Pipe Tags 3", u"pinned, left where it was"),
                                  (u"fail", u"Pipe Tags 4", u"Revit would not move the tag")]}
    problems, notes = core.tidy_outcome(u"L00 Plan", answer)
    check("a clash and a refusal need a look, so they are problems",
          problems, [u"L00 Plan: Tag Tidy - Pipe Tags 2: its text crosses a duct",
                     u"L00 Plan: Tag Tidy - Pipe Tags 4: Revit would not move the tag"])
    check("the summary and a tag left alone are notes",
          notes, [u"L00 Plan: Tag Tidy - 3 tags stacked in 1 column, all clear",
                  u"L00 Plan: Tag Tidy - Pipe Tags 3: pinned, left where it was"])
    check("a tidy that failed outright is one problem naming the view",
          core.tidy_outcome(u"L01", {"ok": False, "error": u"boom", "rows": []}),
          ([u"L01: Tag Tidy could not tidy the new tags - boom"], []))
    check("no answer, nothing to report", core.tidy_outcome(u"L01", None), ([], []))
    check("nothing moved, no summary note", core.tidy_outcome(u"L01", {"ok": True, "moved": 0,
                                                                       "kept": 0, "rows": []}),
          ([], []))
    check("tidying is on until unticked", core.DEFAULTS["tidy"], u"1")
    check("the hook contract this Tag All speaks", core.TIDY_HOOK_VERSION, 1)


def bench_family_default_tags():
    s = {}
    check("a family with nothing set follows its category's nothing",
          core.remembered_family_tag(s, u"Doors", u"Single Flush"), u"")
    core.remember_tag(s, u"Doors", u"Door Tag : Standard")
    check("setting the category fills every family with it",
          (core.remembered_family_tag(s, u"Doors", u"Single Flush"),
           core.remembered_family_tag(s, u"Doors", u"Double Glazed")),
          (u"Door Tag : Standard", u"Door Tag : Standard"))
    core.remember_family_tag(s, u"Doors", u"Double Glazed", u"Door Tag : Large")
    check("a family can then be given its own", core.remembered_family_tag(s, u"Doors", u"Double Glazed"),
          u"Door Tag : Large")
    check("and the others keep following the category",
          core.remembered_family_tag(s, u"Doors", u"Single Flush"), u"Door Tag : Standard")
    check("a family set by hand no longer follows", core.family_follows_category(s, u"Doors", u"Double Glazed"), False)
    loaded = core.parse_settings_text(u"\n".join([u"{0}={1}".format(k, v) for k, v in s.items()]))
    check("its own default is written to the file and read back",
          core.remembered_family_tag(loaded, u"Doors", u"Double Glazed"), u"Door Tag : Large")
    check("and survives the load's whitelist", core.family_tag_key(u"Doors", u"Double Glazed").startswith(core.TAG_PREFIX), True)
    core.remember_family_tag(s, u"Doors", u"Single Flush", core.NONE_TAG)
    check("a family can be told to start on <None> while its category has a tag",
          core.remembered_family_tag(s, u"Doors", u"Single Flush"), core.NONE_TAG)
    check("which the table reads as <None>",
          core.default_tag_for(core.remembered_family_tag(s, u"Doors", u"Single Flush"), [u"Door Tag : Standard"]),
          core.NONE_TAG)
    core.remember_family_tag(s, u"Doors", u"Single Flush", u"Door Tag : Standard")
    check("picking the category's own tag puts a family back to following it",
          core.family_follows_category(s, u"Doors", u"Single Flush"), True)
    core.remember_tag(s, u"Windows", u"Window Tag")
    core.remember_family_tag(s, u"Windows", u"Casement", u"Window Tag : Small")
    core.remember_tag(s, u"Doors", u"Door Tag : Wide")
    check("setting the category again fills its families again, overriding what was set by hand",
          core.remembered_family_tag(s, u"Doors", u"Double Glazed"), u"Door Tag : Wide")
    check("without touching another category's families",
          core.remembered_family_tag(s, u"Windows", u"Casement"), u"Window Tag : Small")
    core.remember_tag(s, u"Doors", core.NONE_TAG)
    check("setting the category to <None> empties its families too",
          core.remembered_family_tag(s, u"Doors", u"Double Glazed"), u"")
    check("a category whose name starts another's is not caught by it",
          core.remembered_family_tag(core.remember_tag({core.family_tag_key(u"Doors Extra", u"X"): u"T"}, u"Doors", u"A"),
                                     u"Doors Extra", u"X"), u"T")


def bench_drawer_arithmetic():
    close("the bar floats 8 px above the bottom of the working area",
          core.shrunk_top(0, 1040, 42), 990.0)
    close("a second bar stacks above the first, 4 px apart", core.shrunk_top(0, 1040, 42, 1), 944.0)
    close("a monitor above the primary parks on that monitor, not on the primary",
          core.shrunk_top(-1080, -40, 42), -90.0)
    close("however many stack, never above the top of the screen",
          core.shrunk_top(0, 1040, 42, 500), 0.0)
    check("slots fill from the bottom", core.free_slot([]), 0)
    check("a slot given back is reused rather than leaving a gap", core.free_slot([0, 2]), 1)
    close("the slide eases out: three quarters of the way at half time", core.ease_out(0.5), 0.875)
    close("and lands exactly", core.ease_out(1.0), 1.0)
    close("progress past the end is the end", core.ease_out(1.7), 1.0)
    close("a tween starts where it starts", core.tween(120, 990, 0), 120.0)

    left, top, height = core.expand_geometry(100, 120, 800, 100, 990, 990, 42, 0, 1040)
    check("a bar left where it landed opens back where the window was", (left, top, height), (100.0, 120.0, 800.0))
    left, top, height = core.expand_geometry(100, 120, 800, 400, 700, 990, 42, 0, 1040)
    check("a bar carried elsewhere opens upward from where it now sits",
          (left, top, height), (400.0, -58.0 if False else 0.0, 800.0))
    left, top, height = core.expand_geometry(100, 120, 400, 400, 700, 990, 42, 0, 1040)
    check("its bottom edge stays put", (left, top + height), (400.0, 742.0))
    left, top, height = core.expand_geometry(100, -900, 800, 100, -90, -90, 42, -1080, -40)
    check("on a monitor above the primary it opens back on that monitor", top, -900.0)
    left, top, height = core.expand_geometry(100, 0, 2000, 100, 990, 990, 42, 0, 1040)
    check("a window taller than its screen opens no taller than the screen", height, 1040.0)


def bench_drawer_slide():
    drawer_module = _fresh_drawers()
    platform = _Platform()
    window = _Window()
    already_hidden = _Part("Collapsed")
    parts = [_Part(), _Part(), already_hidden]
    drawer = _drawer_for(window, platform, parts)

    check("shrink starts", drawer.shrink(), True)
    check("it is parked once it has landed", (drawer.shrunk, drawer.sliding), (True, False))
    close("on the bar's top, 8 px above the working area's bottom", window.Top, 990.0)
    close("only the header shows: the window is the bar's height", window.Height, 42.0)
    check("it slid rather than jumped", len(platform.frames) > 5, True)
    check("the body was pinned at its height for the slide", platform.pins[0], 800.0)
    check("and unpinned once it landed", window.Content.Height != window.Content.Height, True)
    check("MinHeight is relaxed, or it vetoes the shrink", window.MinHeight, 0)
    check("SizeToContent is relaxed too", window.SizeToContent, "Manual")
    check("everything beside the header is parked",
          [part.Visibility for part in parts], ["Collapsed", "Collapsed", "Collapsed"])
    check("the header gets its four rounded corners", drawer.header.CornerRadius, u"6")
    check("the button turns into the green up arrow", platform.looks[-1], True)
    check("the true size is the window's, not the bar's", drawer.true_size(), (1200.0, 800.0))

    check("the slide stops its own timer rather than ticking on", platform.ticks_run < 30, True)
    check("a second shrink while parked does nothing", drawer.shrink(), False)
    platform.frames = []
    check("expand starts", drawer.expand(), True)
    check("it opens back where it was",
          (window.Left, window.Top, window.Height), (100.0, 120.0, 800.0))
    check("it slid open too", len(platform.frames) > 5, True)
    check("MinHeight is put back", window.MinHeight, 620.0)
    check("the parts come back as they were",
          [part.Visibility for part in parts], ["Visible", "Visible", "Collapsed"])
    check("so a panel that was already hidden stays hidden", already_hidden.Visibility, "Collapsed")
    check("the header's corners are put back", drawer.header.CornerRadius, "6,6,0,0")
    check("the body is unpinned", window.Content.VerticalAlignment, "Stretch")
    check("the button is the shrink glyph again", platform.looks[-1], False)
    check("its slot is given back", drawer.slot, None)
    check("and the window is brought to the front", window.activated, 1)
    check("not parked any more", drawer.busy(), False)
    del drawer_module.DRAWERS[:]


def bench_drawer_gestures():
    drawer_module = _fresh_drawers()
    platform = _Platform()
    window = _Window()
    drawer = _drawer_for(window, platform)

    check("Ctrl+Shift+H shrinks", drawer.key("H", True, True), True)
    check("and parks it", drawer.shrunk, True)
    check("Escape on a parked window reopens it rather than closing it",
          drawer.key("Escape", False, False), True)
    check("so it is open again", drawer.shrunk, False)
    check("Escape on an open window is left to the window", drawer.key("Escape", False, False), False)
    drawer.shrink()
    check("Enter reopens a parked prompt rather than answering it", drawer.key("Return", False, False), True)
    drawer.shrink()
    check("F11 reopens it rather than filling the screen with it", drawer.key("F11", False, False), True)
    check("plain H is just a letter", drawer.key("H", False, False), False)

    drawer.shrink()
    check("a single press on the bar is left to drag it", drawer.header_down(1), False)
    check("a double-click on the bar reopens it", drawer.header_down(2), True)
    check("open again", drawer.shrunk, False)
    check("a double-click on an open window is left to full screen", drawer.header_down(2), False)
    check("the button toggles", (drawer.toggle(), drawer.shrunk, drawer.toggle(), drawer.shrunk),
          (True, True, True, False))

    drawer.shrink()
    window.Left, window.Top = 400.0, 900.0
    drawer.expand()
    check("a bar carried elsewhere opens upward from it, its bottom edge staying put",
          (window.Left, window.Top + window.Height), (400.0, 942.0))
    drawer.shrink()
    window.Left, window.Top = 400.0, 300.0
    drawer.expand()
    check("and one carried too high to open upward stays on the screen",
          (window.Top, window.Height), (0.0, 800.0))

    # while sliding, nothing on the header acts and a second shrink is refused
    slow = _Platform(run_now=False)
    other = _Window()
    sliding = _drawer_for(other, slow)
    sliding.shrink()
    check("mid-slide it is sliding, not yet parked", (sliding.sliding, sliding.shrunk), (True, False))
    check("a second shrink mid-slide is refused", sliding.shrink(), False)
    check("an expand mid-slide is refused", sliding.expand(), False)
    check("the header ignores presses mid-slide", sliding.header_down(2), True)
    check("Escape mid-slide is swallowed, not passed to the window", sliding.key("Escape", False, False), True)
    check("the true size mid-slide is still the window's", sliding.true_size(), (1200.0, 800.0))
    timer, tick = slow.ticks[0]
    for _step in range(100):
        if timer.stopped:
            break
        tick(timer)
    check("the slide finishes on its own timer", sliding.shrunk, True)
    hidden_before = list(sliding.hidden)
    tick(timer)
    check("a tick arriving after the finish does nothing", sliding.hidden, hidden_before)

    # a frame that throws lands the window at the end state
    broken = _Platform()
    broken.fail_after = 60.0
    hurt = _Window()
    hurt_drawer = _drawer_for(hurt, broken)
    hurt_drawer.shrink()
    check("a frame that throws still lands the window", (hurt_drawer.shrunk, hurt.Height), (True, 42.0))
    del drawer_module.DRAWERS[:]


def bench_drawer_windows():
    drawer_module = _fresh_drawers()
    platform = _Platform()
    first = _Window()
    second = _Window(left=300.0, top=200.0)
    one = _drawer_for(first, platform)
    two = _drawer_for(second, platform)
    one.shrink()
    two.shrink()
    close("the first bar takes the bottom slot", first.Top, 990.0)
    close("the second stacks above it", second.Top, 944.0)
    one.expand()
    third_window = _Window()
    three = _drawer_for(third_window, platform)
    three.shrink()
    close("a slot given back is reused", third_window.Top, 990.0)
    del drawer_module.DRAWERS[:]

    # a dialog parks the window it belongs to first, and brings it back
    main = _Window()
    dialog = _Window(height=NAN, size_to_content="Height", min_height=0.0)
    dialog.ActualHeight = 300.0
    dialog.Owner = main
    main_drawer = _drawer_for(main, platform)
    dialog_drawer = _drawer_for(dialog, platform)
    dialog_drawer.shrink()
    check("shrinking a dialog parks the window it belongs to", main_drawer.shrunk, True)
    close("the window's bar takes the bottom slot", main.Top, 990.0)
    close("the dialog's stacks above it", dialog.Top, 944.0)
    check("a SizeToContent dialog remembers its laid-out height", dialog_drawer.true_size()[1], 300.0)
    dialog_drawer.expand()
    check("reopening the dialog brings the window back", main_drawer.shrunk, False)
    check("and the dialog sizes itself to its content again", dialog.SizeToContent, "Height")
    dialog_drawer.shrink()
    dialog.closed_handler(None, None)
    check("closing a parked dialog brings its window back", main_drawer.shrunk, False)
    check("and gives up its drawer", dialog_drawer in drawer_module.DRAWERS, False)
    del drawer_module.DRAWERS[:]

    # a window parks its open dialogs with it
    main = _Window()
    report = _Window(left=500.0, top=300.0, width=720.0, height=480.0, min_height=300.0)
    report.Owner = main
    main.owned = [report]
    main_drawer = _drawer_for(main, platform)
    report_drawer = _drawer_for(report, platform)
    main_drawer.shrink()
    check("shrinking a window parks its open dialogs with it", report_drawer.shrunk, True)
    main_drawer.expand()
    check("and reopening it brings them back", report_drawer.shrunk, False)
    check("each back where it was", (report.Left, report.Top, report.Height), (500.0, 300.0, 480.0))
    del drawer_module.DRAWERS[:]


def bench_open_prompt():
    text = core.open_sheets_prompt(u"42 tags placed", 1)
    check("one sheet is asked about as the sheet", u"open the sheet?" in text, True)
    check("and starts with Done", text.startswith(u"Done - 42 tags placed"), True)
    check("several are counted", u"open the 3 sheets?" in core.open_sheets_prompt(u"x", 3), True)
    check("a lot of sheets come with a warning",
          u"its own view" in core.open_sheets_prompt(u"x", core.MANY_SHEETS + 1), True)
    check("a few do not", u"its own view" in core.open_sheets_prompt(u"x", 2), False)


def bench_filter_views():
    views = [(u"Level 01 - Plumbing", 1), (u"Level 02 - Plumbing", 2), (u"Section A", 3)]
    check("filter by one word", core.filter_views(views, u"plumbing"), views[:2])
    check("filter by two", core.filter_views(views, u"02 plumbing"), [views[1]])
    check("no filter", core.filter_views(views, u""), views)
    check("no match", core.filter_views(views, u"elevation"), [])


# ============================================================
# settings
# ============================================================

def bench_settings_parsing():
    parsed = core.parse_settings_text(u"a=1\n\n# a comment\nb = two \nbroken\nc=x=y\n")
    check("a plain key", parsed.get("a"), u"1")
    check("spaces are stripped", parsed.get("b"), u"two")
    check("a line with no = is ignored", "broken" in parsed, False)
    check("comments are ignored", "# a comment" in parsed, False)
    check("split on the first = only", parsed.get("c"), u"x=y")

    check("true", core.parse_bool(u"1"), True)
    check("on", core.parse_bool(u"on"), True)
    check("false", core.parse_bool(u"0"), False)
    check("rubbish falls back to the default", core.parse_bool(u"maybe", True), True)
    check("blank falls back", core.parse_bool(u"", False), False)

    close("a float", core.parse_float(u"600.5"), 600.5)
    close("a comma decimal", core.parse_float(u"600,5"), 600.5)
    close("rubbish falls back", core.parse_float(u"six hundred", 600), 600)
    check("an int rounds", core.parse_int(u"299.6"), 300)
    check("a negative offset is allowed", core.parse_float(u"-600"), -600.0)


def bench_settings_round_trip():
    scratch = tempfile.mkdtemp()
    try:
        path = os.path.join(scratch, "settings.txt")
        settings = core.load_settings(path)
        check("a missing file is the defaults", settings["offset_x"], core.DEFAULTS["offset_x"])
        check("the defaults carry a version", "settings_version" in settings, True)

        settings["offset_x"] = u"1200"
        core.remember_tag(settings, u"Pipes", u"BGL_Pipe Tag : Size")
        core.save_settings(settings, path)

        reloaded = core.load_settings(path)
        check("a saved value comes back", reloaded["offset_x"], u"1200")
        check("a remembered tag comes back",
              core.remembered_tag(reloaded, u"Pipes"), u"BGL_Pipe Tag : Size")
        check("a category never seen has no remembered tag",
              core.remembered_tag(reloaded, u"Ducts"), u"")

        with open(path, "a") as handle:
            handle.write("tagtype:Ducts=BGL_Duct Tag : Size\n")
            handle.write("family_active_only=1\n")
        reloaded = core.load_settings(path)
        check("a 1.0 last-pick line does not come back as a default",
              core.remembered_tag(reloaded, u"Ducts"), u"")
        check("nor does the view mode the opening now decides",
              "family_active_only" in reloaded, False)
        core.save_settings(reloaded, path)
        check("and neither is written back out",
              "tagtype:" in open(path).read() or "family_active_only" in open(path).read(), False)

        settings = core.load_settings(path)
        settings["family_sheet_group_1"] = u"BGL_Sheet Discipline"
        settings["room_view_group_2"] = u"Sub-Discipline"
        core.save_settings(settings, path)
        reloaded = core.load_settings(path)
        check("a sheet group parameter survives a save and a load",
              reloaded["family_sheet_group_1"], u"BGL_Sheet Discipline")
        check("so does a view group parameter", reloaded["room_view_group_2"], u"Sub-Discipline")

        with open(path, "a") as handle:
            handle.write("some_key_from_1998=nonsense\n")
        reloaded = core.load_settings(path)
        check("a key from an older version is ignored rather than breaking the load",
              "some_key_from_1998" in reloaded, False)
        check("and the rest still loads", reloaded["offset_x"], u"1200")

        with open(path, "w") as handle:
            handle.write("\x00\x01 not a settings file at all")
        reloaded = core.load_settings(path)
        check("a damaged file falls back to the defaults key by key",
              reloaded["offset_x"], core.DEFAULTS["offset_x"])

        # a value carrying an = sign round-trips
        settings = core.load_settings(path)
        core.remember_tag(settings, u"Pipes", u"Tag : Size = DN")
        core.save_settings(settings, path)
        check("a value with an = in it survives",
              core.remembered_tag(core.load_settings(path), u"Pipes"), u"Tag : Size = DN")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def bench_pipe_lists():
    check("join", core.join_pipe([u"A", u"B"]), u"A|B")
    check("split", core.split_pipe(u"A|B"), [u"A", u"B"])
    check("empty round trip", core.split_pipe(core.join_pipe([])), [])
    check("blanks are dropped", core.join_pipe([u"A", u"", u"B"]), u"A|B")
    check("round trip", core.split_pipe(core.join_pipe([u"ARCH", u"ARCH (2)"])), [u"ARCH", u"ARCH (2)"])


# ============================================================
# theme
# ============================================================

def bench_theme():
    check("Dark", core.theme_from_text(u"Dark"), core.THEME_DARK)
    check("UITheme.Dark", core.theme_from_text(u"UITheme.Dark"), core.THEME_DARK)
    check("CanvasTheme.Light", core.theme_from_text(u"CanvasTheme.Light"), core.THEME_LIGHT)
    check("lower case", core.theme_from_text(u"light"), core.THEME_LIGHT)
    check("something unknown", core.theme_from_text(u"Chartreuse"), None)
    check("nothing at all", core.theme_from_text(None), None)

    check("auto follows Revit", core.resolve_theme(core.THEME_AUTO, core.THEME_LIGHT), core.THEME_LIGHT)
    check("auto with nothing reported is dark", core.resolve_theme(core.THEME_AUTO, None), core.THEME_DARK)
    check("pinned dark ignores Revit", core.resolve_theme(core.THEME_DARK, core.THEME_LIGHT), core.THEME_DARK)
    check("pinned light ignores Revit", core.resolve_theme(core.THEME_LIGHT, core.THEME_DARK), core.THEME_LIGHT)
    check("rubbish behaves like auto", core.resolve_theme(u"chartreuse", core.THEME_LIGHT), core.THEME_LIGHT)

    check("auto -> dark", core.next_theme_mode(core.THEME_AUTO), core.THEME_DARK)
    check("dark -> light", core.next_theme_mode(core.THEME_DARK), core.THEME_LIGHT)
    check("light -> auto", core.next_theme_mode(core.THEME_LIGHT), core.THEME_AUTO)
    check("three clicks return to auto",
          core.next_theme_mode(core.next_theme_mode(core.next_theme_mode(core.THEME_AUTO))),
          core.THEME_AUTO)
    check("rubbish resets to auto", core.next_theme_mode(u"chartreuse"), core.THEME_AUTO)
    check("the chip reads Auto", core.theme_label(core.THEME_AUTO), u"Auto")


def bench_palettes():
    """theme.py holds the two palettes, and its only module-level dependency
    is the assembly-reference module - so a two-line clr stub is enough to
    read the real palettes here rather than a copy of them."""
    if "clr" not in sys.modules:
        import types
        stub = types.ModuleType("clr")
        stub.AddReference = lambda name: None
        sys.modules["clr"] = stub
    import theme as theme_module
    check("both palettes carry the same keys",
          sorted(theme_module.DARK.keys()) == sorted(theme_module.LIGHT.keys()), True)
    check("the light accents are not the dark ones",
          theme_module.LIGHT["BlueBrush"] != theme_module.DARK["BlueBrush"], True)
    check("the light background is light",
          theme_module.LIGHT["WindowBrush"].upper() > u"#AAAAAA", True)
    check("an unknown palette name falls back to dark",
          theme_module.palette(u"chartreuse"), theme_module.DARK)
    for key, value in theme_module.DARK.items():
        COUNT[0] += 1
        if not (value.startswith("#") and len(value) == 7):
            FAILURES.append(u"dark palette {0} is not a #rrggbb colour: {1}".format(key, value))


# ============================================================
# reporting
# ============================================================

def bench_reporting():
    check("one tag", core.summarise(1, 0, 0, []), u"1 tag placed")
    check("many tags", core.summarise(40, 0, 0, []), u"40 tags placed")
    check("with removals", core.summarise(40, 5, 0, []), u"40 tags placed, 5 removed")
    check("with skips and problems", core.summarise(40, 0, 2, [u"a", u"b"]),
          u"40 tags placed, 2 skipped, 2 problems")
    check("nothing placed still says so", core.summarise(0, 0, 0, []), u"0 tags placed")

    check("problems open the window", core.should_show_results(core.SHOW_PROBLEMS, [u"a"]), True)
    check("a clean run does not interrupt", core.should_show_results(core.SHOW_PROBLEMS, []), False)
    check("always means always", core.should_show_results(core.SHOW_ALWAYS, []), True)
    check("never means never", core.should_show_results(core.SHOW_NEVER, [u"a"]), False)
    check("a blank setting behaves like the default",
          core.should_show_results(u"", [u"a"]), True)


def bench_text():
    check("None is an empty string", core.to_text(None), u"")
    check("a number", core.to_text(12), u"12")
    check("unicode survives", core.to_text(u"\u00e9"), u"\u00e9")
    check("an object that will not format still comes back as text",
          isinstance(core.to_text(object()), type(u"")), True)


def bench_paths():
    check("the settings file is named after the tool",
          core.settings_path().endswith("tag_all.txt"), True)
    check("the log sits beside it", core.log_path().endswith("tag_all.log"), True)
    check("the breadcrumb has its own name",
          core.breadcrumb_path().endswith("tag_all_last_error.txt"), True)
    check("all three sit in the same folder",
          os.path.dirname(core.settings_path()) == os.path.dirname(core.log_path()), True)


BENCHES = [
    bench_ids, bench_units, bench_head_point, bench_elbow, bench_box_geometry,
    bench_vectors,
    bench_bounds,
    bench_room_in_view, bench_plan_targets, bench_chunks, bench_progress,
    bench_singular, bench_tag_matching, bench_default_tag, bench_opening_scope, bench_type_display,
    bench_unique_names, bench_search, bench_natural_order, bench_filter_views,
    bench_pick_rows, bench_apply_tick, bench_views_from_sheets, bench_sorting, bench_open_prompt, bench_column_widths,
    bench_revit_dark_palette, bench_family_groups, bench_edges_and_links, bench_after_placing, bench_untangle, bench_tidy_hook, bench_family_default_tags, bench_drawer_arithmetic, bench_drawer_slide, bench_drawer_gestures, bench_drawer_windows,
    bench_view_filters, bench_view_grouping, bench_preselection, bench_tag_table,
    bench_settings_parsing, bench_settings_round_trip, bench_pipe_lists,
    bench_theme, bench_palettes, bench_reporting, bench_text, bench_paths,
]


def run():
    del FAILURES[:]
    COUNT[0] = 0
    for bench in BENCHES:
        bench()
    return COUNT[0], list(FAILURES)


# ============================================================
# selftest
# ============================================================

REGRESSIONS = [
    ("tag-all-not-tagged stops skipping the tagged ones", "tagall_core.py",
     "        if only_untagged and has_tag:\n            continue",
     "        if False:\n            continue"),
    ("remove-previous deletes tags on elements it is not re-tagging", "tagall_core.py",
     "        if remove_previous and has_tag:\n            to_delete.extend(tagged.get(key) or [])",
     "        if remove_previous:\n            to_delete.extend(tagged.get(key) or [])\n        for extra in tagged.values():\n            to_delete.extend(extra)"),
    ("the offset is applied in feet rather than millimetres", "tagall_core.py",
     "    return add3(add3(base, scale3(right, mm_to_ft(x_mm))),\n                scale3(up, mm_to_ft(y_mm)))",
     "    return add3(add3(base, scale3(right, x_mm)), scale3(up, y_mm))"),
    ("the elbow goes the wrong side of the tag", "tagall_core.py",
     "    if x_mm > 0:\n        return 1.0\n    if x_mm < 0:\n        return -1.0",
     "    if x_mm > 0:\n        return -1.0\n    if x_mm < 0:\n        return 1.0"),
    ("the elbow is levelled with the family origin rather than the tag's centre", "tagall_core.py",
     "    along_up = dot3(sub3(centre, head), up)",
     "    along_up = 0.0"),
    ("the elbow is measured from the tag's centre rather than its edge", "tagall_core.py",
     "    along_right = dot3(sub3(edge, head), right)",
     "    along_right = 0.0"),
    ("the elbow stops being a pure sideways move from the anchor", "tagall_core.py",
     "    return add3(anchor, scale3(right, -sign * mm_to_ft(elbow_mm)))",
     "    return add3(anchor, scale3((right[0], right[1] + 0.2, right[2]), -sign * mm_to_ft(elbow_mm)))"),
    ("the anchor takes the wrong edge of the tag", "tagall_core.py",
     "    edge = extreme_along(corners, right, sign < 0)",
     "    edge = extreme_along(corners, right, sign > 0)"),
    ("a link element and a host element of the same id collide", "tagall_core.py",
     "    if link_value > 0:\n        return (link_value, int(element_value))",
     "    if False:\n        return (link_value, int(element_value))"),
    ("Duct Accessory Tags stop matching Duct Accessories", "tagall_core.py",
     '    candidates = set([_norm(element_category), _norm(singular(element_category))])',
     '    candidates = set([_norm(element_category)])'),
    ("auto stops following Revit", "tagall_core.py",
     "    if mode in (THEME_DARK, THEME_LIGHT):\n        return mode\n    return revit_theme or THEME_DARK",
     "    return THEME_DARK"),
    ("the theme cycle skips a state", "tagall_core.py",
     "    return THEME_ORDER[(THEME_ORDER.index(mode) + 1) % len(THEME_ORDER)]",
     "    return THEME_ORDER[(THEME_ORDER.index(mode) + 2) % len(THEME_ORDER)]"),
    ("settings split on every = rather than the first", "tagall_core.py",
     '        key, value = line.split("=", 1)',
     '        key, value = line.split("=")[0], line.split("=")[1]'),
    ("a clean run starts interrupting people", "tagall_core.py",
     "    if mode == SHOW_ALWAYS:\n        return True\n    return bool(problems)",
     "    return True"),
    ("natural order falls back to alphabetical", "tagall_core.py",
     "            out.append((1, int(part), u\"\"))",
     "            out.append((0, 0, part))"),
    ("the anchor moves on a shift-click, so a run cannot be widened", "tagall_core.py",
     "            selected = set(run)\n        return selected, anchor",
     "            selected = set(run)\n        return selected, key"),
    ("a plain click adds to the highlight instead of replacing it", "tagall_core.py",
     "    return set([key]), key",
     "    selected.add(key)\n    return selected, key"),
    ("ticking one of a highlighted run stops ticking the run", "tagall_core.py",
     "    if key in selected and len(selected) > 1:\n        targets = set(selected)",
     "    if False:\n        targets = set(selected)"),
    ("ticking a row outside the highlight sweeps the highlight too", "tagall_core.py",
     "    if key in selected and len(selected) > 1:",
     "    if len(selected) > 1:"),
    ("a view on two ticked sheets is tagged twice", "tagall_core.py",
     "            if view_key in seen:\n                continue\n            seen.add(view_key)",
     "            seen.add(view_key)"),
    ("a ticked sheet with no views is passed over in silence", "tagall_core.py",
     "            empty.append(sheet_key)\n            continue",
     "            continue"),
    ("a column's own filter hides values from its own tick list", "tagall_core.py",
     "    for _key, cells in filter_rows(rows, keywords, ticks, exclude=column):",
     "    for _key, cells in filter_rows(rows, keywords, ticks):"),
    ("a fully ticked-back column stays filtered", "tagall_core.py",
     "    if listed and listed.issubset(current):\n        return None",
     "    if False:\n        return None"),
    ("a collapsed group still takes part in a Shift run", "tagall_core.py",
     "        if use_g1 and group_id(first) in collapsed:\n            continue",
     "        if False:\n            continue"),
    ("a group tick only ever ticks", "tagall_core.py",
     "    if keys and keys.issubset(ticked):\n        ticked.difference_update(keys)",
     "    if False:\n        ticked.difference_update(keys)"),
    ("a tag lands on rows whose category cannot take it", "tagall_core.py",
     "        if tag == NONE_TAG or tag in choices.get(key, ()):",
     "        if True:"),
    ("a pick outside the highlight sweeps the highlight", "tagall_core.py",
     "    if row_key is not None and (row_key not in selected or len(selected) < 2):",
     "    if row_key is not None and len(selected) < 2:"),
    ("preselected views stop narrowing the list", "tagall_core.py",
     "    if not preselected or show_all:\n        return list(rows)",
     "    if True:\n        return list(rows)"),
    ("the keyword search stops requiring every word", "tagall_core.py",
     "        if word not in haystack:\n            return False\n    return True",
     "        if word in haystack:\n            return True\n    return not words"),
    ("a room whose cut plane misses it is tagged anyway", "tagall_core.py",
     "    if cut_z is not None:\n        if not z_contains(room_min_z, room_max_z, cut_z):\n            return False",
     "    if False:\n        return False"),
    ("chunking loses the last part chunk", "tagall_core.py",
     "    return [items[i:i + size] for i in range(0, len(items), size)]",
     "    return [items[i:i + size] for i in range(0, len(items) - size + 1, size)]"),
    ("the progress bar repaints on every element", "tagall_core.py",
     "    return percent(done, total) != last_percent",
     "    return True"),
    ("a second sort level overrides the first instead of breaking its ties", "tagall_core.py",
     "    for column, descending in reversed(list(stack or [])):",
     "    for column, descending in list(stack or []):"),
    ("blanks sort first when a level runs descending", "tagall_core.py",
     "        ordered.sort(key=lambda row, c=column: to_text(row[1].get(c, u\"\")).strip() == u\"\")",
     "        pass"),
    ("sheet numbers sort as text, M-10 before M-9", "tagall_core.py",
     "        ordered.sort(key=lambda row, c=column: natural_key(row[1].get(c, u\"\")), reverse=descending)",
     "        ordered.sort(key=lambda row, c=column: to_text(row[1].get(c, u\"\")), reverse=descending)"),
    ("shift-clicking a sorted column starts the sort again", "tagall_core.py",
     "    if column in columns:\n        index = columns.index(column)",
     "    if False:\n        index = columns.index(column)"),
    ("a column resize changes the table's total width", "tagall_core.py",
     "    widths[left] += delta\n    widths[right] -= delta",
     "    widths[left] += delta"),
    ("a column resize ignores the floors", "tagall_core.py",
     "    delta = max(lowest, min(highest, float(delta)))",
     "    delta = float(delta)"),
    ("remembered widths that do not fit the table are used anyway", "tagall_core.py",
     "    if len(parts) != len(defaults):\n        return [float(width) for width in defaults]",
     "    if not parts:\n        return [float(width) for width in defaults]"),
    ("a window is not busy until after it parks its dialogs, and they recurse", "tagall_drawer.py",
     "        self.sliding = True\n        self.saved = {",
     "        self.saved = {"),
    ("a slide can finish more than once", "tagall_drawer.py",
     "            if state[\"finished\"]:\n                return\n            state[\"finished\"] = True",
     "            pass"),
    ("MinHeight is not relaxed, so it vetoes the shrink", "tagall_drawer.py",
     "        window.MinHeight = 0\n",
     "\n"),
    ("MinHeight is not put back, so the window can be dragged shut", "tagall_drawer.py",
     "        window.MinHeight = self.saved[\"min_height\"]",
     "        pass"),
    ("a panel that was hidden comes back shown", "tagall_drawer.py",
     "            platform.restore_visibility(part, visibility)",
     "            platform.restore_visibility(part, \"Visible\")"),
    ("the body and grips are left showing on the parked bar", "tagall_drawer.py",
     "            platform.collapse(part)",
     "            pass"),
    ("the body is left pinned after landing", "tagall_drawer.py",
     "            platform.collapse(part)\n        platform.unpin(window)",
     "            platform.collapse(part)"),
    ("a dialog leaves its window covering the model", "tagall_drawer.py",
     "        if owner is not None and not owner.busy():",
     "        if False:"),
    ("a window leaves its dialogs open when it parks", "tagall_drawer.py",
     "            if follower is not None and not follower.busy():",
     "            if False:"),
    ("Escape on a parked window is passed on and closes it", "tagall_drawer.py",
     "        if self.busy() and name in (\"Escape\", \"Enter\", \"Return\", \"F11\"):",
     "        if False:"),
    ("a window closed while parked saves the bar's size", "tagall_drawer.py",
     "        if self.saved is not None and self.busy():",
     "        if False:"),
    ("closing a parked dialog leaves its window parked", "tagall_drawer.py",
     "        for drawer in lifted:\n            if drawer.shrunk:\n                drawer.expand(animate=False)\n        self.shrunk = False",
     "        self.shrunk = False"),
    ("parked bars all land on top of each other", "tagall_core.py",
     "    top = float(area_bottom) - margin - float(bar_height) - slot * (float(bar_height) + gap)",
     "    top = float(area_bottom) - margin - float(bar_height)"),
    ("a bar parks on the primary screen's top, not its own", "tagall_core.py",
     "    return max(float(area_top), top)",
     "    return max(0.0, top)"),
    ("a bar carried elsewhere jumps back when opened", "tagall_core.py",
     "    if abs(float(bar_top) - float(landed_top)) <= DRAWER_MOVED:",
     "    if True:"),
    ("the dark palette drifts off Revit's panel grey", "theme.py",
     '    "CardBrush": "#353D4B",', '    "CardBrush": "#2B2B2E",'),
    ("the selection drifts off Revit's active-row blue", "theme.py",
     '    "SelectBrush": "#3A7392",', '    "SelectBrush": "#2B5473",'),
    ("a glyph on an accent fill goes back to white and can't be read", "theme.py",
     '    "OnAccentBrush": "#1B1F24",', '    "OnAccentBrush": "#FFFFFF",'),
    ("muted text drops under 4.5:1 on Revit's panel", "theme.py",
     '    "MutedBrush": "#ACB2B9",', '    "MutedBrush": "#A4AAB1",'),
    ("opening Categories shuts Views / Sheets every time", "tagall_core.py",
     "        if not categories_opened_before:\n            result[\"views\"] = False",
     "        result[\"views\"] = False"),
    ("a double-click on a side edge fills the screen too", "tagall_core.py",
     '    return grip_name in ("GripN", "GripS")', '    return grip_name.startswith("Grip")'),
    ("Add ticked leaves Categories open", "tagall_core.py",
     '    result["categories"] = False\n    result["families"] = True',
     '    result["families"] = True'),
    ("the linked models list drags to nothing", "tagall_core.py",
     "    return max(LINKS_MIN_H, min(LINKS_MAX_H, float(value)))",
     "    return min(LINKS_MAX_H, float(value))"),
    ("a group shutting is counted as opening", "tagall_core.py",
     "    closing = [g for g in GROUP_ORDER if before.get(g) and not after.get(g)]",
     "    closing = []"),
    ("the tab opens with every group shut", "tagall_core.py",
     'GROUP_START = {"views": False, "categories": True,', 'GROUP_START = {"views": False, "categories": False,'),
    ("Ticked views leaves Categories open", "tagall_core.py",
     '    result["views"] = True\n    result["categories"] = False\n    result["families"] = False',
     '    result["views"] = True\n    result["families"] = False'),
    ("Current view leaves Views / Sheets open", "tagall_core.py",
     '        result["views"] = False\n        result["categories"] = True\n        return 0, True, result',
     '        return 0, True, result'),
    ("families start shut on their types", "tagall_core.py",
     "    return bool(query) or family_key not in collapsed_families",
     "    return bool(query) or family_key in collapsed_families"),
    ("the window shrinks on Room Tags too", "tagall_core.py",
     "    if blocked or not on_family_tab:\n        return False\n    return not any(",
     "    if blocked:\n        return False\n    return not any("),
    ("Ticked views and Sheets leave Families to tag open", "tagall_core.py",
     '    result["categories"] = False\n    result["families"] = False\n    if source == SOURCE_SHEETS:',
     '    result["categories"] = False\n    if source == SOURCE_SHEETS:'),
    ("Untangle and Tag Tidy can both be left on", "tagall_core.py",
     "    if untangle and tidy:\n        return False, True", "    if False:\n        return False, True"),
    ("ticking one leaves the other tickable", "tagall_core.py",
     "    return not tidy, not untangle", "    return True, True"),
    ("an untangled tag drops only to touch the one above", "tagall_core.py",
     "            offset = lowest - gap - box[3]", "            offset = lowest - box[3]"),
    ("untangling looks at only the first tag it hits", "tagall_core.py",
     "        for _attempt in range(len(settled) + 1):", "        for _attempt in range(1):"),
    ("the untangle gap ignores the view scale", "tagall_core.py",
     "    return mm_to_ft(UNTANGLE_GAP_MM * scale)", "    return mm_to_ft(UNTANGLE_GAP_MM)"),
    ("setting a category leaves its families as they were", "tagall_core.py",
     "    for other in [k for k in settings.keys() if to_text(k).startswith(family_prefix)]:\n        settings.pop(other, None)",
     "    for other in []:\n        settings.pop(other, None)"),
    ("a family's own default is ignored", "tagall_core.py",
     "    if key in settings:\n        return to_text(settings.get(key))\n    return remembered_tag(settings, category)",
     "    return remembered_tag(settings, category)"),
    ("a family can never follow its category again", "tagall_core.py",
     "    if display == (remembered_tag(settings, category).strip() or NONE_TAG):\n        settings.pop(key, None)\n    else:\n        settings[key] = display",
     "    settings[key] = display"),
    ("Sheets lands on the Views tab", "tagall_core.py",
     "        return 1, None, result", "        return 0, None, result"),
    ("the options ride up under the headers when every group is shut", "tagall_core.py",
     'filler = u"auto" if any(', 'filler = u"auto" if True or any('),
    ("the slide stops easing and runs at a constant speed", "tagall_core.py",
     "    return 1.0 - (1.0 - progress) ** 3",
     "    return progress"),
    ("a default whose family has gone is used anyway", "tagall_core.py",
     "    if category_default and category_default in offered:",
     "    if category_default:"),
    ("setting a default back to <None> stores <None>", "tagall_core.py",
     "    if not display or display == NONE_TAG:\n        settings.pop(key, None)",
     "    if not display:\n        settings.pop(key, None)"),
    ("on a sheet, the list starts on the whole project", "tagall_core.py",
     "        if on_sheet:\n            return False, on_sheet, OPEN_SHEET",
     "        if False:\n            return False, on_sheet, OPEN_SHEET"),
    ("viewports picked on a sheet are ignored", "tagall_core.py",
     "    if chosen:\n        return False, chosen,",
     "    if chosen and not active_is_sheet:\n        return False, chosen,"),
    ("in a view, the list does not start on Current view only", "tagall_core.py",
     "    if active_key in listed:\n        return True, set(), OPEN_VIEW",
     "    if active_key in listed:\n        return False, set(), OPEN_VIEW"),
    ("a selection this list cannot tag empties the list", "tagall_core.py",
     "    chosen = set([key for key in selected_views if key in listed])",
     "    chosen = set(selected_views)"),
    ("Tag Tidy looked for only beside Tag All", "tagall_core.py",
     "    for name in names:\n        if not name.endswith(u\".panel\"):",
     "    for name in []:\n        if not name.endswith(u\".panel\"):"),
    ("Tag Tidy told to add leaders a run left off on purpose", "tagall_core.py",
     'return {"no_leader": u"switch_on" if options.get("leader") else u"skip"}',
     'return {"no_leader": u"switch_on"}'),
    ("a Tag Tidy clash reported only as a note", "tagall_core.py",
     "        if kind in (u\"clash\", u\"fail\"):", "        if kind in (u\"fail\",):"),
]


def selftest():
    caught = 0
    missed = []
    for label, file_name, find_text, replace_text in REGRESSIONS:
        scratch = tempfile.mkdtemp()
        try:
            work = os.path.join(scratch, "tool")
            shutil.copytree(HERE, work, ignore=IGNORE_CACHE)
            path = os.path.join(work, file_name)
            with open(path) as handle:
                text = handle.read()
            if find_text not in text:
                missed.append(u"{0}: could not apply the breakage".format(label))
                continue
            with open(path, "w") as handle:
                handle.write(text.replace(find_text, replace_text, 1))
            code = _run_in(work)
            if code == 0:
                missed.append(u"{0}: the bench passed with it broken".format(label))
            else:
                caught += 1
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    return caught, missed


def _run_in(folder):
    """Run the bench against a scratch copy, in its own process so the
    modules are loaded fresh."""
    import subprocess
    result = subprocess.call([sys.executable, os.path.join(folder, "bench_logic.py")],
                             cwd=folder, stdout=open(os.devnull, "w"),
                             stderr=open(os.devnull, "w"))
    return result


def main():
    if "--selftest" in sys.argv:
        caught, missed = selftest()
        for line in missed:
            sys.stdout.write(u"FAIL  {0}\n".format(line))
        sys.stdout.write(u"\nselftest: {0} of {1} deliberate breakages were caught\n".format(
            caught, len(REGRESSIONS)))
        return 0 if caught == len(REGRESSIONS) else 1

    total, failures = run()
    for line in failures:
        sys.stdout.write(u"FAIL  {0}\n".format(line))
    if failures:
        sys.stdout.write(u"\nbench_logic: {0} of {1} checks failed\n".format(len(failures), total))
        return 1
    sys.stdout.write(u"bench_logic: {0} checks, all pass\n".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
