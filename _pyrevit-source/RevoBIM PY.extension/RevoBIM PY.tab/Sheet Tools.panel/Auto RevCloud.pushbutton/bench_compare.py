# -*- coding: utf-8 -*-
"""Auto RevCloud - bench tests for the element comparison, plain CPython.

arc_compare touches neither Revit nor .NET, so every rule in it is the real
code here. Run from the pushbutton folder:

    python bench_compare.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import arc_compare as A

PASS = [0]
FAIL = []


def check(label, got, want):
    if got == want:
        PASS[0] += 1
    else:
        FAIL.append(u"{0}\n     got  {1}\n     want {2}".format(label, got, want))


def check_true(label, got):
    check(label, bool(got), True)


def check_false(label, got):
    check(label, bool(got), False)


def item(key, category=u"Pipes", centre=(0.0, 0.0, 0.0),
         size=(1.0, 1.0, 1.0), type_name=u"100 dia", eid=None,
         ends=None, rot=None, params=None, basis=None, flips=None,
         version=u""):
    return {u"key": key, u"category": category, u"type": type_name,
            u"centre": centre, u"size": size,
            u"ends": ends, u"rot": rot, u"params": params or {},
            u"basis": basis, u"flips": flips, u"version": version,
            u"eid": eid if eid is not None else hash(key) % 100000}


def kinds(changes):
    return sorted((c[u"kind"], c[u"key"]) for c in changes)


# ==========================================================================
# the diff
# ==========================================================================

def test_no_change():
    host = [item(u"a"), item(u"b", centre=(10.0, 0.0, 0.0))]
    link = [item(u"a"), item(u"b", centre=(10.0, 0.0, 0.0))]
    check(u"diff: an untouched model has no changes",
          A.diff_items(host, link, 0.02, 0.02), [])


def test_added_and_removed():
    host = [item(u"a"), item(u"new")]
    link = [item(u"a"), item(u"gone")]
    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"diff: one added and one removed", kinds(changes),
          [(u"added", u"new"), (u"removed", u"gone")])

    # a removal is clouded where it USED to be - the only place it exists
    removed = [c for c in changes if c[u"kind"] == u"removed"][0]
    check(u"diff: a removal carries the old position", removed[u"centre"],
          (0.0, 0.0, 0.0))


def test_moved():
    host = [item(u"a", centre=(0.0, 0.0, 1.0))]
    link = [item(u"a", centre=(0.0, 0.0, 0.0))]

    check(u"diff: a move under the tolerance is not a change",
          A.diff_items(host, link, 2.0, 0.02), [])

    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"diff: a move over the tolerance is", kinds(changes), [(u"moved", u"a")])
    check(u"diff: the distance is reported", round(changes[0][u"moved_by"], 6), 1.0)
    # the cloud goes where it is NOW, which is where somebody has to look
    check(u"diff: a move is clouded at the new position",
          changes[0][u"centre"], (0.0, 0.0, 1.0))


def test_resized_and_retyped():
    host = [item(u"a", size=(2.0, 1.0, 1.0))]
    link = [item(u"a", size=(1.0, 1.0, 1.0))]
    check(u"diff: a size change is a change",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"resized", u"a")])
    check(u"diff: under the size tolerance it is not",
          A.diff_items(host, link, 0.02, 5.0), [])

    host = [item(u"a", type_name=u"150 dia")]
    link = [item(u"a", type_name=u"100 dia")]
    check(u"diff: a type change is a change",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"retyped", u"a")])
    check(u"diff: type checking can be turned off",
          A.diff_items(host, link, 0.02, 0.02, check_type=False), [])


def test_move_beats_resize():
    """One element reports one thing: the most significant."""
    host = [item(u"a", centre=(5.0, 0.0, 0.0), size=(9.0, 1.0, 1.0),
                 type_name=u"200 dia")]
    link = [item(u"a")]
    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"diff: one element gives one change", len(changes), 1)
    check(u"diff: a move outranks a resize and a retype",
          changes[0][u"kind"], u"moved")


def test_redrawn_element():
    """Deleted and redrawn gets a new UniqueId, so it is one removal and one
    addition. That is honest - it is what happened."""
    host = [item(u"new-id", centre=(1.0, 0.0, 0.0))]
    link = [item(u"old-id", centre=(1.0, 0.0, 0.0))]
    check(u"diff: a redrawn element is a removal and an addition",
          kinds(A.diff_items(host, link, 0.02, 0.02)),
          [(u"added", u"new-id"), (u"removed", u"old-id")])


def test_empty_sides():
    check(u"diff: everything added when the link is empty",
          kinds(A.diff_items([item(u"a")], [], 0.02, 0.02)), [(u"added", u"a")])
    check(u"diff: everything removed when the host is empty",
          kinds(A.diff_items([], [item(u"a")], 0.02, 0.02)), [(u"removed", u"a")])
    check(u"diff: two empty sides give nothing",
          A.diff_items([], [], 0.02, 0.02), [])


# ==========================================================================
# projection into the view
# ==========================================================================

def test_match_by_element_id():
    """UniqueId first, ElementId for the leftovers.

    A UniqueId is regenerated by some routes to a copy of a model; the
    ElementId carries over instead. Matching the leftovers on it rescues those
    cases and cannot disturb anything already matched by UniqueId.
    """
    # same element, different UniqueId, same ElementId, and it has not moved
    host = [item(u"uid-new", eid=4242)]
    link = [item(u"uid-old", eid=4242)]
    check(u"eid: matched on ElementId and unchanged, so nothing is clouded",
          A.diff_items(host, link, 0.02, 0.02), [])

    # ...and with ElementId matching off it is an add plus a remove
    check(u"eid: without it the same pair is a redraw",
          kinds(A.diff_items(host, link, 0.02, 0.02, use_eid=False)),
          [(u"added", u"uid-new"), (u"removed", u"uid-old")])

    # matched on ElementId and moved: one move, not an add plus a remove
    host = [item(u"uid-new", centre=(0.0, 0.0, 3.0), eid=99)]
    link = [item(u"uid-old", eid=99)]
    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"eid: a matched element that moved is a move",
          kinds(changes), [(u"moved", u"uid-new")])

    # UniqueId wins where both could match, and an ElementId already used
    # cannot be claimed twice
    host = [item(u"same", eid=1), item(u"other", eid=1)]
    link = [item(u"same", eid=1)]
    pairs, host_only, link_only, stats = A.pair_up(host, link)
    check(u"eid: UniqueId takes precedence", pairs[0][0][u"key"], u"same")
    check(u"eid: a link element is claimed once", len(pairs), 1)
    check(u"eid: the loser is an addition", [h[u"key"] for h in host_only],
          [u"other"])
    check(u"eid: and nothing is left over on the link side", link_only, [])
    check(u"eid: the match is counted as a UniqueId one", stats[u"by_uid"], 1)


def test_box_covers_both_positions():
    """A cloud round a moved element has to cover where it left as well as
    where it went, or it sits on empty paper beside the thing still drawn in
    the old position."""
    origin, right, up = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    host = [item(u"a", centre=(10.0, 0.0, 0.0), size=(2.0, 2.0, 2.0))]
    link = [item(u"a", centre=(0.0, 0.0, 0.0), size=(2.0, 2.0, 2.0))]
    change = A.diff_items(host, link, 0.02, 0.02)[0]

    check(u"box: the old position is carried", change[u"was"], (0.0, 0.0, 0.0))
    box = A.item_box(change, origin, right, up)
    check(u"box: it spans both positions", box, (-1.0, -1.0, 11.0, 1.0))

    # an addition has no old position, so the box is just the element
    added = A.diff_items([item(u"b", centre=(5.0, 5.0, 0.0))], [], 0.02, 0.02)[0]
    check(u"box: an addition has no old position", added[u"was"], None)
    check(u"box: and is clouded where it is",
          A.item_box(added, origin, right, up), (4.5, 4.5, 5.5, 5.5))

    # a removal is clouded where it used to be
    removed = A.diff_items([], [item(u"c", centre=(7.0, 0.0, 0.0))], 0.02, 0.02)[0]
    check(u"box: a removal is clouded at the old position",
          A.item_box(removed, origin, right, up), (6.5, -0.5, 7.5, 0.5))

    # a retype has not moved, so both boxes coincide and nothing grows
    host = [item(u"d", type_name=u"150 dia")]
    link = [item(u"d", type_name=u"100 dia")]
    retyped = A.diff_items(host, link, 0.02, 0.02)[0]
    check(u"box: a retype does not widen the cloud",
          A.item_box(retyped, origin, right, up), (-0.5, -0.5, 0.5, 0.5))


def test_toggle_ticks():
    """The rule behind the category picker's tick list."""
    chosen = set()
    A.toggle_ticks(chosen, [u"Pipes", u"Ducts"])
    check(u"ticks: an unticked run ticks", sorted(chosen), [u"ducts", u"pipes"])

    A.toggle_ticks(chosen, [u"Pipes", u"Ducts"])
    check(u"ticks: a fully ticked run unticks", sorted(chosen), [])

    # the case every tick list gets wrong: a mixed run must not scramble
    chosen = set([u"pipes"])
    A.toggle_ticks(chosen, [u"Pipes", u"Ducts"])
    check(u"ticks: a mixed run ticks everything rather than flipping each",
          sorted(chosen), [u"ducts", u"pipes"])

    # names are matched case-insensitively, and stay lower case in the set
    chosen = set()
    A.toggle_ticks(chosen, [u"CABLE TRAYS"])
    check(u"ticks: stored lower case", sorted(chosen), [u"cable trays"])
    A.toggle_ticks(chosen, [u"cable trays"])
    check(u"ticks: and matched whatever the case", sorted(chosen), [])

    check(u"ticks: nothing picked changes nothing",
          sorted(A.toggle_ticks(set([u"pipes"]), [])), [u"pipes"])


def test_endpoints_catch_what_the_box_cannot():
    """The gap that was letting real moves through: anything whose bounding
    box is unchanged even though the element moved."""
    # a run swung about its own middle: same centre, same box, both ends moved
    host = [item(u"a", ends=((0.0, 5.0, 0.0), (0.0, -5.0, 0.0)),
                 size=(10.0, 10.0, 1.0))]
    link = [item(u"a", ends=((5.0, 0.0, 0.0), (-5.0, 0.0, 0.0)),
                 size=(10.0, 10.0, 1.0))]
    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"ends: a run swung about its centre is a move",
          kinds(changes), [(u"moved", u"a")])

    # a pipe re-routed inside the same envelope
    host = [item(u"b", ends=((0.0, 0.0, 0.0), (10.0, 3.0, 0.0)))]
    link = [item(u"b", ends=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))]
    check(u"ends: a re-routed pipe is a move",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"moved", u"b")])

    # ...but a pipe simply redrawn from its far end is NOT a change
    host = [item(u"c", ends=((10.0, 0.0, 0.0), (0.0, 0.0, 0.0)))]
    link = [item(u"c", ends=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))]
    check(u"ends: a reversed element is not a move",
          A.diff_items(host, link, 0.02, 0.02), [])

    # a tiny end shift under the tolerance is not a move
    host = [item(u"d", ends=((0.0, 0.0, 0.0), (10.0, 0.001, 0.0)))]
    link = [item(u"d", ends=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))]
    check(u"ends: under the tolerance is not a move",
          A.diff_items(host, link, 0.02, 0.02), [])

    check(u"ends: nothing to compare gives nothing",
          A.ends_moved(None, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))), 0.0)


def test_rotation():
    """A fitting turned in place: same centre, and for a symmetric family the
    same bounding box too."""
    host = [item(u"a", rot=1.5708)]
    link = [item(u"a", rot=0.0)]
    check(u"rotation: a fitting turned in place is caught",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"rotated", u"a")])

    host = [item(u"b", rot=0.001)]
    link = [item(u"b", rot=0.0)]
    check(u"rotation: under the tolerance is not a change",
          A.diff_items(host, link, 0.02, 0.02), [])

    # a full turn is the same orientation, not a change
    import math as _m
    check_false(u"rotation: a full turn is not a change",
                A.angle_changed(2.0 * _m.pi, 0.0, 0.02))
    check_true(u"rotation: a quarter turn is",
               A.angle_changed(_m.pi / 2.0, 0.0, 0.02))
    check_false(u"rotation: nothing to compare is not a change",
                A.angle_changed(None, 0.0, 0.02))

    # a move outranks a rotation
    host = [item(u"c", centre=(9.0, 0.0, 0.0), rot=1.5)]
    link = [item(u"c", rot=0.0)]
    check(u"rotation: a move outranks it",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"moved", u"c")])


def test_parameters():
    """A change that moves nothing and resizes nothing."""
    host = [item(u"a", params={u"Reference Level": u"L01", u"Size": u"100"})]
    link = [item(u"a", params={u"Reference Level": u"L00", u"Size": u"100"})]
    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"params: a changed level is a change", kinds(changes),
          [(u"altered", u"a")])
    check(u"params: the field is named", changes[0][u"params_changed"],
          [u"Reference Level"])
    check(u"params: and reaches the comment",
          A.describe(changes), u"Pipe altered (Reference Level)")

    same = [item(u"b", params={u"Size": u"100"})]
    check(u"params: identical parameters are not a change",
          A.diff_items(same, same, 0.02, 0.02), [])

    # a parameter only one side carries is not a change - it may have been
    # added to the model since the link was saved
    host = [item(u"c", params={u"Size": u"100", u"New Field": u"x"})]
    link = [item(u"c", params={u"Size": u"100"})]
    check(u"params: a parameter the link does not have is not a change",
          A.diff_items(host, link, 0.02, 0.02), [])

    check(u"params: nothing to compare", A.params_changed({}, {}), [])


def test_basis_and_flips():
    """What Location.Rotation cannot see: a turn about any axis, and a mirror."""
    X = (1.0, 0.0, 0.0)
    Y = (0.0, 1.0, 0.0)
    Z = (0.0, 0.0, 1.0)

    check_false(u"basis: identical axes are no change",
                A.basis_changed((X, Z), (X, Z), 0.02))
    check_true(u"basis: a quarter turn about Z is a change",
               A.basis_changed((Y, Z), (X, Z), 0.02))
    # rolled about its own run - invisible to Location.Rotation
    check_true(u"basis: rolled about its own axis is a change",
               A.basis_changed((X, Y), (X, Z), 0.02))
    check_false(u"basis: nothing to compare is no change",
                A.basis_changed(None, (X, Z), 0.02))

    host = [item(u"a", basis=(Y, Z))]
    link = [item(u"a", basis=(X, Z))]
    check(u"basis: a fitting turned in place is caught",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"rotated", u"a")])

    # mirrored: same box, same angle, different drawing
    host = [item(u"b", basis=(X, Z), flips=1)]
    link = [item(u"b", basis=(X, Z), flips=0)]
    check(u"flips: a mirrored family is caught",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"flipped", u"b")])

    same = [item(u"c", basis=(X, Z), flips=3)]
    check(u"flips: an unchanged flip state is not a change",
          A.diff_items(same, same, 0.02, 0.02), [])

    # an element with no flip information must not read as flipped
    host = [item(u"d", basis=(X, Z))]
    link = [item(u"d", basis=(X, Z))]
    check(u"flips: no flip information is not a change",
          A.diff_items(host, link, 0.02, 0.02), [])

    # a move still outranks both
    host = [item(u"e", centre=(9.0, 0.0, 0.0), basis=(Y, Z), flips=1)]
    link = [item(u"e", basis=(X, Z), flips=0)]
    check(u"flips: a move outranks a turn and a mirror",
          kinds(A.diff_items(host, link, 0.02, 0.02)), [(u"moved", u"e")])


# ==========================================================================
# the spatial method
# ==========================================================================

def test_new_ids_are_always_clouded():
    """An element whose id is nowhere in the link is new to this view."""
    host = [item(u"h1", eid=9001, centre=(3.0, 0.0, 0.0)),
            item(u"h2", eid=1, centre=(0.0, 0.0, 0.0))]
    link = [item(u"h2", eid=1, centre=(0.0, 0.0, 0.0))]
    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"new id: the new element is clouded",
          kinds(changes), [(u"added", u"h1")])
    check(u"new id: and is marked as a new id", changes[0][u"new_id"], True)

    # an addition whose id DOES exist in the link is not marked - it is a
    # redraw of something that was there, not a new element
    host = [item(u"fresh-uid", eid=1, centre=(50.0, 0.0, 0.0))]
    link = [item(u"old-uid", eid=1, centre=(0.0, 0.0, 0.0), category=u"Ducts")]
    changes = A.diff_items(host, link, 0.02, 0.02)
    added = [c for c in changes if c[u"kind"] == u"added"][0]
    check(u"new id: an id that exists in the link is not a new id",
          added[u"new_id"], False)


def test_id_match_needs_the_same_category():
    """An ElementId only means the same thing when the link is a copy of this
    model. Where it is not, an id can be shared with something unrelated."""
    host = [item(u"new-uid", eid=500, category=u"Pipes", centre=(0.0, 0.0, 0.0))]
    link = [item(u"other-uid", eid=500, category=u"Ducts", centre=(0.0, 0.0, 0.0))]

    changes = A.diff_items(host, link, 0.02, 0.02)
    check(u"id match: a different category is not the same element",
          sorted(c[u"kind"] for c in changes), [u"added", u"removed"])

    # ...and the same category still pairs, which is the point of the fallback
    host = [item(u"new-uid", eid=500, category=u"Pipes", centre=(0.0, 0.0, 0.0))]
    link = [item(u"other-uid", eid=500, category=u"Pipes", centre=(0.0, 0.0, 0.0))]
    check(u"id match: the same category still pairs on the id",
          A.diff_items(host, link, 0.02, 0.02), [])

    # with type checking on, a different type does not pair on the id either
    host = [item(u"a", eid=7, type_name=u"150 dia")]
    link = [item(u"b", eid=7, type_name=u"100 dia")]
    check(u"id match: type checking applies to the id fallback too",
          sorted(c[u"kind"] for c in A.diff_items(host, link, 0.02, 0.02,
                                                  check_type=True)),
          [u"added", u"removed"])


def test_spatial_ignores_ids():
    """The case it exists for: the two models share no ids at all."""
    host = [item(u"h1", centre=(0.0, 0.0, 0.0), eid=1),
            item(u"h2", centre=(10.0, 0.0, 0.0), eid=2)]
    link = [item(u"L9", centre=(0.0, 0.0, 0.0), eid=77),
            item(u"L8", centre=(10.0, 0.0, 0.0), eid=88)]

    check(u"spatial: nothing moved, so nothing is clouded",
          A.diff_spatially(host, link, 0.05, 0.05), [])

    # ...and the id method calls the same pair a wholesale replacement
    check(u"spatial: the id method would report every one of them",
          len(A.diff_items(host, link, 0.05, 0.05)), 4)


def test_spatial_finds_changes():
    host = [item(u"a", centre=(0.0, 0.0, 0.0)),
            item(u"b", centre=(10.0, 0.0, 0.0))]
    link = [item(u"x", centre=(0.0, 0.0, 0.0))]
    changes = A.diff_spatially(host, link, 0.05, 0.05)
    check(u"spatial: an element with nothing under it is added",
          [(c[u"kind"], c[u"key"]) for c in changes], [(u"added", u"b")])

    link = [item(u"x", centre=(0.0, 0.0, 0.0)),
            item(u"y", centre=(50.0, 0.0, 0.0))]
    host = [item(u"a", centre=(0.0, 0.0, 0.0))]
    changes = A.diff_spatially(host, link, 0.05, 0.05)
    check(u"spatial: a link element nothing claimed is removed",
          [(c[u"kind"], c[u"key"]) for c in changes], [(u"removed", u"y")])

    # a category swap in the same place is a change, however well it lines up
    host = [item(u"a", category=u"Ducts")]
    link = [item(u"x", category=u"Pipes")]
    check(u"spatial: a duct where a pipe was is a change",
          len(A.diff_spatially(host, link, 0.05, 0.05)), 2)

    # a different type in the same place, when type checking is on
    host = [item(u"a", type_name=u"150 dia")]
    link = [item(u"x", type_name=u"100 dia")]
    check(u"spatial: a retype in place is a change with checking on",
          len(A.diff_spatially(host, link, 0.05, 0.05, check_type=True)), 2)
    check(u"spatial: and is not with it off",
          A.diff_spatially(host, link, 0.05, 0.05, check_type=False), [])

    # size matters even where the centre agrees
    host = [item(u"a", size=(9.0, 1.0, 1.0))]
    link = [item(u"x", size=(1.0, 1.0, 1.0))]
    check(u"spatial: a resize in place is a change",
          len(A.diff_spatially(host, link, 0.05, 0.05)), 2)


def test_spatial_move_pass():
    """Without ids a move is only a move if something like it is found
    nearby - otherwise it is honestly a removal plus an addition."""
    host = [item(u"a", centre=(5.0, 0.0, 0.0))]
    link = [item(u"x", centre=(0.0, 0.0, 0.0))]

    pair = A.diff_spatially(host, link, 0.05, 0.05, search=20.0)
    check(u"spatial: a like element nearby reads as a move",
          [c[u"kind"] for c in pair], [u"moved"])
    check(u"spatial: and carries the old position for the cloud",
          pair[0][u"was"], (0.0, 0.0, 0.0))

    apart = A.diff_spatially(host, link, 0.05, 0.05, search=1.0)
    check(u"spatial: too far apart is a removal and an addition",
          sorted(c[u"kind"] for c in apart), [u"added", u"removed"])

    check(u"spatial: no search at all is the same",
          sorted(c[u"kind"] for c in A.diff_spatially(host, link, 0.05, 0.05)),
          [u"added", u"removed"])

    # the move pass must not pair things of different categories
    host = [item(u"a", centre=(5.0, 0.0, 0.0), category=u"Ducts")]
    check(u"spatial: it will not pair a duct with a pipe",
          sorted(c[u"kind"] for c in A.diff_spatially(host, link, 0.05, 0.05,
                                                      search=20.0)),
          [u"added", u"removed"])


def test_spatial_buckets():
    """The index is what keeps it from being every element against every
    element - fifteen hundred each way is over two million comparisons."""
    check(u"buckets: a point lands in its cell", A.cell_of((5.0, 5.0, 5.0), 10.0),
          (0, 0, 0))
    check(u"buckets: and the next one along", A.cell_of((11.0, 5.0, 5.0), 10.0),
          (1, 0, 0))
    check(u"buckets: negatives round down", A.cell_of((-1.0, 0.0, 0.0), 10.0),
          (-1, 0, 0))

    items = [item(u"a", centre=(0.0, 0.0, 0.0)),
             item(u"b", centre=(100.0, 0.0, 0.0))]
    index = A.build_index(items, 10.0)
    found = A.nearby(index, (0.0, 0.0, 0.0), 10.0)
    check(u"buckets: only the neighbour comes back", len(found), 1)
    check(u"buckets: and it is the right one", found[0][u"key"], u"a")
    check(u"buckets: nothing nearby is nothing",
          A.nearby(index, (500.0, 0.0, 0.0), 10.0), [])

    # anything within one bucket width is guaranteed to be found, which is
    # what makes the bucket size the search radius
    close_pair = [item(u"a", centre=(9.5, 0.0, 0.0))]
    index = A.build_index(close_pair, 10.0)
    check(u"buckets: a neighbour just over a boundary is still found",
          len(A.nearby(index, (10.5, 0.0, 0.0), 10.0)), 1)


def test_spatial_claims_once():
    """Two host elements must not both match the same link element."""
    host = [item(u"a", centre=(0.0, 0.0, 0.0)),
            item(u"b", centre=(0.0, 0.0, 0.0))]
    link = [item(u"x", centre=(0.0, 0.0, 0.0))]
    changes = A.diff_spatially(host, link, 0.05, 0.05)
    check(u"spatial: the second one is not matched to the same element",
          [c[u"kind"] for c in changes], [u"added"])


def test_still_in_host():
    """A removal means gone from the model, not undrawn in this view."""
    import arc_diff_stub as D

    changes = [{u"kind": u"removed", u"key": u"gone"},
               {u"kind": u"removed", u"key": u"hidden-here"},
               {u"kind": u"added", u"key": u"new"}]

    class Doc(object):
        def __init__(self, present):
            self.present = present

        def GetElement(self, key):
            return object() if key in self.present else None

    kept, dropped = D.still_in_host(Doc([u"hidden-here"]), changes)
    check(u"removals: the one still in the model is dropped", dropped, 1)
    check(u"removals: the real deletion survives",
          [c[u"key"] for c in kept], [u"gone", u"new"])

    kept, dropped = D.still_in_host(Doc([]), changes)
    check(u"removals: nothing dropped when both are really gone", dropped, 0)
    check(u"removals: additions are never touched", len(kept), 3)

    # a document that throws on lookup must not swallow real removals
    class Angry(object):
        def GetElement(self, key):
            raise RuntimeError(u"no")

    kept, dropped = D.still_in_host(Angry(), changes)
    check(u"removals: a failed lookup keeps the removal", dropped, 0)


# ==========================================================================
# option 1 - the VersionGuid
# ==========================================================================

def test_guid_off_is_ignored():
    """With the option off the guid is never read, so a difference in it
    changes nothing."""
    host = [item(u"a", version=u"g2")]
    link = [item(u"a", version=u"g1")]
    check(u"guid off: a different guid alone is not a change",
          A.diff_items(host, link, 0.02, 0.02, guid_mode=u"off"), [])


def test_guid_same_skips_everything():
    """An identical guid is Revit itself saying the element was not touched,
    which outranks every other test."""
    # a move that every other test would catch - but the guid says untouched
    host = [item(u"a", centre=(9.0, 0.0, 0.0), version=u"same")]
    link = [item(u"a", centre=(0.0, 0.0, 0.0), version=u"same")]
    for mode in (u"flag", u"trust"):
        check(u"guid same: skips even a visible move ({0})".format(mode),
              A.diff_items(host, link, 0.02, 0.02, guid_mode=mode), [])

    stats = {}
    A.diff_items(host, link, 0.02, 0.02, guid_mode=u"flag", stats=stats)
    check(u"guid same: counted", stats[u"guid_same"], 1)
    check(u"guid same: nothing counted as differing", stats[u"guid_differs"], 0)


def test_guid_differs_flag_versus_trust():
    """The two modes disagree exactly when the guid differs and nothing else
    can say why."""
    host = [item(u"a", version=u"after")]
    link = [item(u"a", version=u"before")]

    check(u"guid flag: a difference nothing explains is not clouded",
          A.diff_items(host, link, 0.02, 0.02, guid_mode=u"flag"), [])
    changes = A.diff_items(host, link, 0.02, 0.02, guid_mode=u"trust")
    check(u"guid trust: it is clouded as edited",
          kinds(changes), [(u"edited", u"a")])
    check(u"guid trust: and the comment says so",
          A.describe(changes), u"Pipe edited")

    # where a test CAN say why, both modes report that rather than 'edited'
    host = [item(u"b", centre=(9.0, 0.0, 0.0), version=u"after")]
    link = [item(u"b", version=u"before")]
    for mode in (u"flag", u"trust"):
        check(u"guid differs: a visible move is still a move ({0})".format(mode),
              kinds(A.diff_items(host, link, 0.02, 0.02, guid_mode=mode)),
              [(u"moved", u"b")])


def test_guid_unreadable():
    """No guid on one side is unknown, not a match and not a difference."""
    host = [item(u"a", version=u"")]
    link = [item(u"a", version=u"x")]
    stats = {}
    check(u"guid unknown: falls through to the normal tests",
          A.diff_items(host, link, 0.02, 0.02, guid_mode=u"trust", stats=stats), [])
    check(u"guid unknown: counted as unreadable", stats[u"guid_unknown"], 1)
    check(u"guid unknown: not counted as differing", stats[u"guid_differs"], 0)


# ==========================================================================
# option 2 - only what this view shows
# ==========================================================================

def test_only_visible():
    origin, right, up = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)

    # a pipe that moved straight UP: invisible on a plan, clouded on a section
    host = [item(u"a", centre=(0.0, 0.0, 3.0))]
    link = [item(u"a", centre=(0.0, 0.0, 0.0))]
    moved = A.diff_items(host, link, 0.02, 0.02)
    check(u"visible: it is a move", kinds(moved), [(u"moved", u"a")])

    kept, dropped = A.only_visible(moved, origin, right, up, 0.1)
    check(u"visible: a vertical move does not show on a plan", dropped, 1)
    check(u"visible: and is not clouded there", kept, [])

    section_up = (0.0, 0.0, 1.0)
    kept, dropped = A.only_visible(moved, origin, right, section_up, 0.1)
    check(u"visible: the same move shows on a section", dropped, 0)

    # a sideways move shows on a plan
    host = [item(u"b", centre=(3.0, 0.0, 0.0))]
    link = [item(u"b", centre=(0.0, 0.0, 0.0))]
    kept, dropped = A.only_visible(A.diff_items(host, link, 0.02, 0.02),
                                   origin, right, up, 0.1)
    check(u"visible: a sideways move shows on a plan", dropped, 0)

    # under the tolerance is not visible
    host = [item(u"c", centre=(0.05, 0.0, 0.0))]
    link = [item(u"c", centre=(0.0, 0.0, 0.0))]
    kept, dropped = A.only_visible(A.diff_items(host, link, 0.02, 0.02),
                                   origin, right, up, 0.1)
    check(u"visible: a move under the tolerance is not shown", dropped, 1)

    # everything that is not a move or a resize is always kept
    always = [{u"kind": k, u"centre": (0.0, 0.0, 0.0), u"size": (1.0, 1.0, 1.0),
               u"was": (0.0, 0.0, 9.0), u"was_size": None}
              for k in (u"added", u"removed", u"rotated", u"flipped",
                        u"retyped", u"altered", u"edited")]
    kept, dropped = A.only_visible(always, origin, right, up, 100.0)
    check(u"visible: only moves and resizes are judged", dropped, 0)

    # a resize that only changes height does not show on a plan
    host = [item(u"d", size=(1.0, 1.0, 5.0))]
    link = [item(u"d", size=(1.0, 1.0, 1.0))]
    kept, dropped = A.only_visible(A.diff_items(host, link, 0.02, 0.02),
                                   origin, right, up, 0.1)
    check(u"visible: a height-only resize does not show on a plan", dropped, 1)

    check(u"visible: nothing in, nothing out",
          A.only_visible([], origin, right, up, 0.1), ([], 0))


def test_project():
    origin = (0.0, 0.0, 0.0)
    right = (1.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    check(u"project: a plan view drops Z", A.project((3.0, 4.0, 99.0), origin, right, up),
          (3.0, 4.0))
    check(u"project: the origin is the centre",
          A.project((0.0, 0.0, 0.0), origin, right, up), (0.0, 0.0))

    # a section: right is world X, up is world Z
    check(u"project: a section sees height as up",
          A.project((2.0, 50.0, 7.0), origin, (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
          (2.0, 7.0))

    # a rotated plan
    got = A.project((1.0, 0.0, 0.0), origin, (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
    check(u"project: a rotated plan turns the point with it", got, (0.0, -1.0))


def test_item_box():
    origin, right, up = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    change = {u"centre": (10.0, 20.0, 0.0), u"size": (4.0, 2.0, 6.0)}
    box = A.item_box(change, origin, right, up)
    check(u"box: a plan sees width and depth", box, (8.0, 19.0, 12.0, 21.0))

    # the same element in a section is a different shape on the page, which is
    # why the size is projected rather than taken as read
    box = A.item_box(change, origin, (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    check(u"box: a section sees width and height", box, (8.0, -3.0, 12.0, 3.0))

    grown = A.grow_box((0.0, 0.0, 1.0, 1.0), 0.5)
    check(u"box: growing adds to every side", grown, (-0.5, -0.5, 1.5, 1.5))


# ==========================================================================
# clustering
# ==========================================================================

def test_cluster():
    a = (0.0, 0.0, 1.0, 1.0)
    b = (1.5, 0.0, 2.5, 1.0)          # 0.5 away from a
    far = (50.0, 50.0, 51.0, 51.0)

    check_true(u"cluster: near boxes touch at a 1.0 gap", A.boxes_touch(a, b, 1.0))
    check_false(u"cluster: they do not at 0.1", A.boxes_touch(a, b, 0.1))

    groups = A.cluster_boxes([a, b, far], 1.0)
    check(u"cluster: the near pair joins, the far one stands alone",
          len(groups), 2)
    check(u"cluster: the biggest group comes first", groups[0][1], [0, 1])
    check(u"cluster: the merged box covers both", groups[0][0], (0.0, 0.0, 2.5, 1.0))

    groups = A.cluster_boxes([a, b, far], 0.1)
    check(u"cluster: a tight gap keeps all three apart", len(groups), 3)

    # merging is transitive: a chain along a run becomes one cloud
    chain = [(0.0, 0.0, 1.0, 1.0), (1.5, 0.0, 2.5, 1.0),
             (3.0, 0.0, 4.0, 1.0), (4.5, 0.0, 5.5, 1.0)]
    groups = A.cluster_boxes(chain, 1.0)
    check(u"cluster: a chain merges into one", len(groups), 1)
    check(u"cluster: and keeps every member", groups[0][1], [0, 1, 2, 3])

    check(u"cluster: nothing in, nothing out", A.cluster_boxes([], 1.0), [])
    check(u"cluster: one box is one group", len(A.cluster_boxes([a], 1.0)), 1)


# ==========================================================================
# the comment
# ==========================================================================

def test_singular():
    check(u"singular: pipes", A.singular(u"Pipes"), u"pipe")
    check(u"singular: ducts", A.singular(u"Ducts"), u"duct")
    check(u"singular: cable trays", A.singular(u"Cable Trays"), u"cable tray")
    check(u"singular: pipe accessories keeps the y",
          A.singular(u"Pipe Accessories"), u"pipe accessory")
    check(u"singular: equipment is already singular",
          A.singular(u"Mechanical Equipment"), u"mechanical equipment")
    check(u"singular: an unknown plural still works",
          A.singular(u"Widgets"), u"widget")
    check(u"singular: nothing is an element", A.singular(u""), u"element")


def test_describe():
    one = [{u"category": u"Pipes", u"kind": u"moved"}]
    check(u"describe: one pipe", A.describe(one), u"Pipe moved")

    three = [{u"category": u"Pipes", u"kind": u"moved"}] * 3
    check(u"describe: three pipes are counted and pluralised",
          A.describe(three), u"3 pipes moved")

    mixed = ([{u"category": u"Pipes", u"kind": u"moved"}] * 2 +
             [{u"category": u"Cable Trays", u"kind": u"added"}])
    check(u"describe: the most numerous comes first",
          A.describe(mixed), u"2 pipes moved, cable tray added")

    check(u"describe: nothing to say", A.describe([]), u"")

    # a long list is cut short rather than filling the schedule column
    many = []
    for name in (u"Pipes", u"Ducts", u"Cable Trays", u"Conduits",
                 u"Air Terminals", u"Sprinklers"):
        many.append({u"category": name, u"kind": u"moved"})
    text = A.describe(many, limit=3)
    check_true(u"describe: a long list is trimmed", text.endswith(u"and 3 more"))
    check_true(u"describe: and starts with a capital", text[0].isupper())

    # equipment must not become "equipments"
    equip = [{u"category": u"Mechanical Equipment", u"kind": u"moved"}] * 2
    check(u"describe: equipment does not take an s",
          A.describe(equip), u"2 mechanical equipment moved")

    # accessories pluralise back correctly
    acc = [{u"category": u"Pipe Accessories", u"kind": u"removed"}] * 2
    check(u"describe: accessory pluralises to accessories",
          A.describe(acc), u"2 pipe accessories removed")


TESTS = [
    test_no_change, test_added_and_removed, test_moved,
    test_resized_and_retyped, test_move_beats_resize, test_redrawn_element,
    test_empty_sides, test_match_by_element_id,
    test_box_covers_both_positions, test_toggle_ticks,
    test_endpoints_catch_what_the_box_cannot, test_rotation, test_parameters,
    test_basis_and_flips, test_still_in_host, test_guid_off_is_ignored,
    test_guid_same_skips_everything, test_guid_differs_flag_versus_trust,
    test_guid_unreadable, test_only_visible, test_new_ids_are_always_clouded,
    test_id_match_needs_the_same_category, test_spatial_ignores_ids, test_spatial_finds_changes,
    test_spatial_move_pass, test_spatial_buckets, test_spatial_claims_once,
    test_project, test_item_box, test_cluster,
    test_singular, test_describe,
]


def main():
    for test in TESTS:
        test()
    if FAIL:
        sys.stdout.write(u"bench_compare: {0} of {1} checks FAILED\n".format(
            len(FAIL), len(FAIL) + PASS[0]))
        for line in FAIL:
            sys.stdout.write(u"  - " + line + u"\n")
        return 1
    sys.stdout.write(u"bench_compare: all {0} checks pass\n".format(PASS[0]))
    return 0


if __name__ == u"__main__":
    sys.exit(main())
