# -*- coding: utf-8 -*-
u"""Auto RevCloud - the element comparison.

No Revit and no .NET in this module, so every rule in it is a plain function
the bench can drive. arc_diff.py does the Revit side and hands the results in
here as dictionaries.

An "item" is one element reduced to what the comparison needs:

    {u"key": unique id, u"category": u"Pipes", u"type": u"100 dia",
     u"centre": (x, y, z), u"size": (dx, dy, dz), u"ends": ((x,y,z),(x,y,z))}

all in feet, in HOST coordinates - arc_diff transforms the link's elements by
the link transform before they get here, so everything below is one space.
"""
import math

# What each kind of change is called in the cloud's comment.
ADDED = u"added"
REMOVED = u"removed"
MOVED = u"moved"
RESIZED = u"resized"
RETYPED = u"retyped"
ROTATED = u"rotated"
ALTERED = u"altered"
FLIPPED = u"flipped"
EDITED = u"edited"       # the VersionGuid differs and nothing else can say why

# Order matters: the most significant thing that happened to an element is
# what gets reported for it.
KIND_ORDER = [REMOVED, ADDED, MOVED, RESIZED, ROTATED, FLIPPED, RETYPED,
              ALTERED, EDITED]


def distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def max_side_change(a, b):
    return max(abs(a[i] - b[i]) for i in range(3))


# ==========================================================================
# the spatial method
# ==========================================================================

def cell_of(point, size):
    u"""Which bucket of a regular grid a point falls in."""
    if size <= 0:
        return (0, 0, 0)
    return (int(math.floor(point[0] / size)),
            int(math.floor(point[1] / size)),
            int(math.floor(point[2] / size)))


def build_index(items, size):
    u"""Items bucketed by position, so a match can be looked for near a point
    instead of against every element on the sheet.

    Without this the spatial method is every host element against every link
    element - fifteen hundred against fifteen hundred is over two million
    comparisons for one view, which is slow enough to look like the tool has
    hung. Bucketed, only the neighbours are ever tested.
    """
    index = {}
    for item in items:
        key = cell_of(item[u"centre"], size)
        index.setdefault(key, []).append(item)
    return index


def nearby(index, point, size, reach=1):
    u"""Everything in the buckets around a point.

    `reach` of 1 covers the 27 buckets touching this one, which is what makes
    the bucket size the search radius: anything within `size` of the point is
    guaranteed to be in one of them.
    """
    base = cell_of(point, size)
    out = []
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            for dz in range(-reach, reach + 1):
                key = (base[0] + dx, base[1] + dy, base[2] + dz)
                if key in index:
                    out.extend(index[key])
    return out


def same_thing(a, b, tol, size_tol, check_type):
    u"""Is this the same element in the same place, to within the tolerances?

    Category always has to agree - a pipe standing where a duct used to be is
    a change, however well the boxes line up. Type only where asked.
    """
    if a.get(u"category") != b.get(u"category"):
        return False
    if check_type and a.get(u"type") != b.get(u"type"):
        return False
    if distance(a[u"centre"], b[u"centre"]) > tol:
        return False
    if max_side_change(a[u"size"], b[u"size"]) > size_tol:
        return False
    ends_a, ends_b = a.get(u"ends"), b.get(u"ends")
    if ends_a and ends_b and ends_moved(ends_a, ends_b) > tol:
        return False
    return True


def diff_spatially(host_items, link_items, tol, size_tol, check_type=True,
                   search=0.0):
    u"""Compare by geometry alone, with no element ids involved.

    Every host element looks for something of the same category sitting in the
    same place in the link. Anything that cannot find one is clouded, and any
    link element nothing claimed is clouded as a removal.

    What this method is FOR: it does not care how an element came to be there.
    An element deleted and redrawn in the same position is not a change under
    it, where id matching reports one removal and one addition. A model
    rebuilt, copied in from elsewhere, or round-tripped through a format that
    regenerates ids compares cleanly.

    What it costs: two identical elements in the same place are
    indistinguishable, so swapping them is invisible; and an element that
    genuinely moved is reported as a removal plus an addition unless `search`
    is wide enough to pair them up, since without ids there is nothing to say
    the two are the same element.
    """
    bucket = max(tol, 1e-6)
    index = build_index(link_items, bucket)
    claimed = set()
    changes = []
    unmatched_host = []

    for item in host_items:
        found = None
        for other in nearby(index, item[u"centre"], bucket):
            if id(other) in claimed:
                continue
            if same_thing(item, other, tol, size_tol, check_type):
                found = other
                break
        if found is None:
            unmatched_host.append(item)
        else:
            claimed.add(id(found))

    leftovers = [i for i in link_items if id(i) not in claimed]

    # Second pass: pair a leftover on each side that looks like the same
    # element further away, so a move reads as a move and gets one cloud
    # round both positions rather than two clouds at opposite ends.
    if search > tol and unmatched_host and leftovers:
        wide = build_index(leftovers, search)
        taken = set()
        still = []
        for item in unmatched_host:
            best = None
            best_gap = None
            for other in nearby(wide, item[u"centre"], search):
                if id(other) in taken:
                    continue
                if item.get(u"category") != other.get(u"category"):
                    continue
                if max_side_change(item[u"size"], other[u"size"]) > size_tol:
                    continue
                gap = distance(item[u"centre"], other[u"centre"])
                if gap > search:
                    continue
                if best_gap is None or gap < best_gap:
                    best, best_gap = other, gap
            if best is None:
                still.append(item)
            else:
                taken.add(id(best))
                changes.append(_change(MOVED, item, best_gap, best))
        unmatched_host = still
        leftovers = [i for i in leftovers if id(i) not in taken]

    for item in unmatched_host:
        changes.append(_change(ADDED, item, 0.0))
    for item in leftovers:
        changes.append(_change(REMOVED, item, 0.0))

    changes.sort(key=lambda c: (c[u"category"], c[u"kind"], c[u"key"]))
    return changes


# ==========================================================================
# the element id method
# ==========================================================================

def pair_up(host_items, link_items, use_eid=True, check_type=False):
    u"""Match each host element to its counterpart in the link.

    Two keys, tried in order, because neither is reliable on its own:

      **UniqueId** first. It survives a Save As, so a link that is a copy of
      this model carries the same one for the same element. It is the stronger
      key and it is tried first.

      **ElementId** for whatever is left. A UniqueId is regenerated when a
      model is created by other routes - eDetach, a transmitted model, some
      exports - and in those the ElementId is what carries over instead.
      Matching the leftovers on it rescues exactly those cases and cannot
      disturb anything already matched by UniqueId.

    Returns (pairs, host_only, link_only) where pairs is [(host, link), ...].
    """
    link_by_uid = {}
    link_by_eid = {}
    for item in link_items:
        link_by_uid[item[u"key"]] = item
        eid = item.get(u"eid")
        if eid:
            link_by_eid[eid] = item

    pairs = []
    host_only = []
    taken = set()
    unmatched = []
    # Counted so a run can say HOW the two models correspond. "Nothing is
    # being picked up" has a different cause depending on whether the ids
    # matched wholesale, partly, or not at all, and without this it is a
    # guess every time.
    stats = {u"by_uid": 0, u"by_eid": 0, u"unmatched": 0, u"link_only": 0}

    for item in host_items:
        other = link_by_uid.get(item[u"key"])
        if other is not None:
            pairs.append((item, other))
            taken.add(other[u"key"])
            stats[u"by_uid"] += 1
        else:
            unmatched.append(item)

    for item in (unmatched if use_eid else []):
        eid = item.get(u"eid")
        other = link_by_eid.get(eid) if eid else None
        # The CATEGORY has to agree before an id match is believed. An
        # ElementId only means the same thing when the link is a copy of this
        # model; where it is not, a brand new element can share an id with
        # something unrelated in the link, and pairing them reports a new
        # element as moved - or as unchanged, if the two happen to sit near
        # each other - instead of clouding it as new.
        if other is not None and other[u"key"] not in taken:
            if other.get(u"category") != item.get(u"category"):
                other = None
            elif check_type and other.get(u"type") != item.get(u"type"):
                other = None
        if other is not None and other[u"key"] not in taken:
            pairs.append((item, other))
            taken.add(other[u"key"])
            stats[u"by_eid"] += 1
        else:
            host_only.append(item)
    if not use_eid:
        host_only.extend(unmatched)

    link_only = [i for i in link_items if i[u"key"] not in taken]
    return pairs, host_only, link_only, stats


def diff_items(host_items, link_items, move_tol, size_tol, check_type=True,
               use_eid=True, angle_tol=0.02, stats=None,
               guid_mode=u"off"):
    u"""Compare two sets of elements and say what changed.

    An element matched to a counterpart within the move tolerance and the size
    tolerance is not a change and is not clouded, which is the whole point:
    the two models are mostly identical and the tolerance is what stops the
    noise.

    An element that has been deleted and redrawn matches on neither key and
    shows up as one removal plus one addition, which is honest: that is what
    happened.

    Returns a list of changes:

        {u"kind": ..., u"key": ..., u"category": ..., u"type": ...,
         u"centre": (x, y, z), u"size": (dx, dy, dz),
         u"was": (x, y, z) or None, u"was_size": (dx, dy, dz) or None,
         u"moved_by": feet}

    `centre` is where the element is NOW. `was` is where it was in the link,
    carried so the cloud can be drawn round both positions - a pipe that moved
    needs the cloud to cover where it left as well as where it went, or the
    drawing shows a cloud round empty paper.
    """
    pairs, host_only, link_only, counted = pair_up(host_items, link_items,
                                                   use_eid, check_type)
    counted[u"unmatched"] = len(host_only)
    counted[u"link_only"] = len(link_only)
    # Filled in place rather than returned through a module level global: a
    # global would be shared by every view in a run and by every window in
    # the session, and the caller has to opt in by handing a dict over.
    if stats is not None:
        stats.clear()
        stats.update(counted)
    changes = []

    # An element whose id appears nowhere in the link is new to this view,
    # and is always clouded - no tolerance applies to something that was not
    # there before. Marked so the report can count them separately.
    link_eids = set()
    for other in link_items:
        if other.get(u"eid"):
            link_eids.add(other[u"eid"])
    for item in host_only:
        entry = _change(ADDED, item, 0.0)
        entry[u"new_id"] = bool(item.get(u"eid")) and item[u"eid"] not in link_eids
        changes.append(entry)

    guid_same = 0
    guid_differs = 0
    guid_unknown = 0
    for item, old in pairs:
        # Option 1: the VersionGuid. Identical means Revit itself says the
        # element has not been touched, which outranks every test below and
        # skips them. Different means SOMETHING changed; the tests below say
        # what, and in "trust" mode a difference none of them can explain is
        # still clouded, as "edited".
        same_guid = None
        if guid_mode != u"off":
            mine, theirs = item.get(u"version"), old.get(u"version")
            if mine and theirs:
                same_guid = (mine == theirs)
                if same_guid:
                    guid_same += 1
                else:
                    guid_differs += 1
            else:
                guid_unknown += 1
        if same_guid:
            continue

        shift = distance(item[u"centre"], old[u"centre"])
        grew = max_side_change(item[u"size"], old[u"size"])
        # The endpoints catch what the box cannot: a pipe re-routed inside the
        # same envelope, an element flipped end for end, a run swung about its
        # middle. All of those leave the bounding box identical.
        end_shift = ends_moved(item.get(u"ends"), old.get(u"ends"))
        if max(shift, end_shift) > move_tol:
            changes.append(_change(MOVED, item, max(shift, end_shift), old))
        elif grew > size_tol:
            changes.append(_change(RESIZED, item, grew, old))
        elif (angle_changed(item.get(u"rot"), old.get(u"rot"), angle_tol)
              or basis_changed(item.get(u"basis"), old.get(u"basis"), angle_tol)):
            changes.append(_change(ROTATED, item, 0.0, old))
        elif (item.get(u"flips") is not None
              and item.get(u"flips") != old.get(u"flips")):
            # Mirrored in place: same box, same angle, different drawing.
            changes.append(_change(FLIPPED, item, 0.0, old))
        elif check_type and item.get(u"type") != old.get(u"type"):
            changes.append(_change(RETYPED, item, 0.0, old))
        else:
            differing = params_changed(item.get(u"params"), old.get(u"params"))
            if differing:
                entry = _change(ALTERED, item, 0.0, old)
                entry[u"params_changed"] = differing
                changes.append(entry)
            elif same_guid is False and guid_mode == u"trust":
                changes.append(_change(EDITED, item, 0.0, old))

    if stats is not None:
        stats[u"guid_same"] = guid_same
        stats[u"guid_differs"] = guid_differs
        stats[u"guid_unknown"] = guid_unknown

    for item in link_only:
        changes.append(_change(REMOVED, item, 0.0))

    changes.sort(key=lambda c: (c[u"category"], c[u"kind"], c[u"key"]))
    return changes


def ends_moved(now, before):
    u"""How far the furthest end of an element has moved.

    Compared both ways round, because an element drawn the other way about -
    a pipe redrawn from its far end - has its endpoints swapped and is not a
    change. Taking the smaller of the two pairings stops every reversed
    element being reported as a move.
    """
    if not now or not before:
        return 0.0
    straight = max(distance(now[0], before[0]), distance(now[1], before[1]))
    swapped = max(distance(now[0], before[1]), distance(now[1], before[0]))
    return min(straight, swapped)


def basis_changed(now, before, tol):
    u"""Have the element's own axes turned by more than `tol` radians?

    Compares the facing and the up axis with a dot product, which covers a
    turn about any axis rather than only about Z. A dot product of 1 is the
    same direction; the tolerance is converted once by the caller.
    """
    if not now or not before:
        return False
    limit = math.cos(max(tol, 0.0))
    for index in (0, 1):
        a, b = now[index], before[index]
        dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
        if dot < limit:
            return True
    return False


def angle_changed(now, before, tol):
    if now is None or before is None:
        return False
    difference = abs(now - before) % (2.0 * math.pi)
    if difference > math.pi:
        difference = 2.0 * math.pi - difference
    return difference > tol


def params_changed(now, before):
    u"""The names whose value differs. Only names BOTH sides carry are
    compared - a parameter added to the model since the link was saved is not
    a change to the element."""
    if not now or not before:
        return []
    out = []
    for name in sorted(now.keys()):
        if name in before and now[name] != before[name]:
            out.append(name)
    return out


def _change(kind, item, amount, was=None):
    return {u"kind": kind, u"key": item[u"key"],
            u"category": item.get(u"category", u""),
            u"type": item.get(u"type", u""),
            u"centre": item[u"centre"], u"size": item[u"size"],
            u"was": was[u"centre"] if was else None,
            u"was_size": was[u"size"] if was else None,
            u"moved_by": amount}


# ==========================================================================
# projecting into the view
# ==========================================================================

def _lower(value):
    try:
        return value.lower()
    except Exception:
        return value


def toggle_ticks(chosen, names):
    u"""Tick or untick a run of names, Explorer style.

    One rule, so a shift-click over a mixed run does something predictable:
    if any of the picked names is unticked the whole run is ticked, and only
    when every one is already ticked does the run untick. Toggling each name
    independently would scramble a mixed selection and is the thing people
    complain about in every tick list that gets it wrong.

    `chosen` is a set of lower-case names and is returned, modified.
    """
    keys = [_lower(n) for n in names]
    turning_on = not all(k in chosen for k in keys)
    for key in keys:
        if turning_on:
            chosen.add(key)
        else:
            chosen.discard(key)
    return chosen


def loop_signed_area(points2d):
    u"""Twice the signed area of a closed loop of (x, y) points; positive is
    counter-clockwise. Which side a revision cloud's arcs bulge is decided by
    the winding order of the outline, and nothing else."""
    total = 0.0
    count = len(points2d)
    if count < 3:
        return 0.0
    for i in range(count):
        ax, ay = points2d[i]
        bx, by = points2d[(i + 1) % count]
        total += ax * by - bx * ay
    return total


def should_reverse(points2d, want_ccw):
    u"""True when the loop has to be reversed to wind the way asked for."""
    area = loop_signed_area(points2d)
    if area == 0.0:
        return False
    return (area > 0.0) != bool(want_ccw)


def project(point, origin, right, up):
    u"""A model point in the view's own 2D frame, in feet."""
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    dz = point[2] - origin[2]
    return (dx * right[0] + dy * right[1] + dz * right[2],
            dx * up[0] + dy * up[1] + dz * up[2])


def _one_box(centre_xyz, size, origin, right, up):
    centre = project(centre_xyz, origin, right, up)
    half_u = (abs(size[0] * right[0]) + abs(size[1] * right[1]) +
              abs(size[2] * right[2])) / 2.0
    half_v = (abs(size[0] * up[0]) + abs(size[1] * up[1]) +
              abs(size[2] * up[2])) / 2.0
    return (centre[0] - half_u, centre[1] - half_v,
            centre[0] + half_u, centre[1] + half_v)


def item_box(change, origin, right, up):
    u"""The change's extent in view coordinates, as (u0, v0, u1, v1).

    Where the element also exists in the link, the box covers **both**
    positions - the cloud has to enclose where it went and where it left, or
    an element that moved gets a cloud round empty paper next to the thing
    that is still drawn where it used to be.

    The bounding half-sizes are projected onto the view axes rather than the
    box being taken as read: a section or a rotated plan sees the same element
    at a different width, and using the model-space size there would cloud the
    wrong shape.
    """
    box = _one_box(change[u"centre"], change[u"size"], origin, right, up)
    was = change.get(u"was")
    if was is not None:
        box = union_box(box, _one_box(was, change.get(u"was_size") or change[u"size"],
                                      origin, right, up))
    return box


def visible_in_view(change, origin, right, up, tol):
    u"""Would this change show on the drawing this view makes?

    A pipe that moved 300mm straight up looks identical on a plan, and a
    cloud round it says "look here" at nothing. Only the kinds with a before
    and an after position are judged - a move or a resize - and only by how
    far they moved AS PROJECTED onto the view's plane. Everything else is kept:
    an addition or a removal is visible by definition, and a retype, a
    rotation or a parameter change is a change to what is drawn regardless
    of where it sits.
    """
    kind = change.get(u"kind")
    if kind not in (MOVED, RESIZED):
        return True
    was = change.get(u"was")
    if was is None:
        return True
    now_box = _one_box(change[u"centre"], change[u"size"], origin, right, up)
    was_box = _one_box(was, change.get(u"was_size") or change[u"size"],
                       origin, right, up)
    shift = max(abs(now_box[i] - was_box[i]) for i in range(4))
    return shift > tol


def only_visible(changes, origin, right, up, tol):
    u"""The changes that show in this view, and how many did not."""
    kept = []
    dropped = 0
    for change in changes:
        if visible_in_view(change, origin, right, up, tol):
            kept.append(change)
        else:
            dropped += 1
    return kept, dropped


def grow_box(box, amount):
    return (box[0] - amount, box[1] - amount, box[2] + amount, box[3] + amount)


def boxes_touch(a, b, gap):
    u"""Do two boxes come within `gap` of each other?"""
    return not (a[2] + gap < b[0] or b[2] + gap < a[0] or
                a[3] + gap < b[1] or b[3] + gap < a[1])


def union_box(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def cluster_boxes(boxes, gap):
    u"""Group boxes that sit within `gap` of each other.

    Returns [[index, ...], ...]. Merging is transitive and repeated until
    nothing more merges, so a chain of changes along a run becomes one cloud
    rather than a string of overlapping ones.
    """
    groups = []
    for index, box in enumerate(boxes):
        groups.append({u"box": box, u"members": [index]})

    merged = True
    while merged:
        merged = False
        out = []
        while groups:
            current = groups.pop(0)
            rest = []
            for other in groups:
                if boxes_touch(current[u"box"], other[u"box"], gap):
                    current = {u"box": union_box(current[u"box"], other[u"box"]),
                               u"members": current[u"members"] + other[u"members"]}
                    merged = True
                else:
                    rest.append(other)
            groups = rest
            out.append(current)
        groups = out
    groups.sort(key=lambda g: -len(g[u"members"]))
    return [(g[u"box"], sorted(g[u"members"])) for g in groups]


# ==========================================================================
# describing a cloud
# ==========================================================================

def singular(category):
    u"""'Pipes' -> 'pipe'. Revit category names are plural; a comment reads
    better in the singular when there is one of them."""
    name = category.strip()
    if not name:
        return u"element"
    lowered = name.lower()
    specials = {
        u"pipes": u"pipe", u"ducts": u"duct", u"cable trays": u"cable tray",
        u"conduits": u"conduit", u"wires": u"wire", u"lines": u"line",
        u"air terminals": u"air terminal", u"sprinklers": u"sprinkler",
        u"pipe fittings": u"pipe fitting", u"duct fittings": u"duct fitting",
        u"pipe accessories": u"pipe accessory",
        u"duct accessories": u"duct accessory",
        u"cable tray fittings": u"cable tray fitting",
        u"conduit fittings": u"conduit fitting",
        u"mechanical equipment": u"mechanical equipment",
        u"electrical equipment": u"electrical equipment",
        u"electrical fixtures": u"electrical fixture",
        u"lighting fixtures": u"lighting fixture",
        u"lighting devices": u"lighting device",
        u"data devices": u"data device",
        u"fire alarm devices": u"fire alarm device",
        u"communication devices": u"communication device",
        u"security devices": u"security device",
        u"plumbing fixtures": u"plumbing fixture",
        u"generic models": u"generic model",
        u"detail items": u"detail item",
        u"specialty equipment": u"specialty equipment",
        u"flex pipes": u"flex pipe", u"flex ducts": u"flex duct",
    }
    if lowered in specials:
        return specials[lowered]
    if lowered.endswith(u"ies"):
        return lowered[:-3] + u"y"
    if lowered.endswith(u"ses") or lowered.endswith(u"xes"):
        return lowered[:-2]
    if lowered.endswith(u"s"):
        return lowered[:-1]
    return lowered


def describe(changes, limit=4):
    u"""A short comment for a cloud: 'Pipe moved, cable tray added'.

    Grouped by category and kind and counted, most numerous first, so a cloud
    over a reroute reads '3 pipes moved' rather than listing three pipes. The
    text is what goes in the cloud's Comments parameter, so it is kept to
    something that fits in a schedule column.
    """
    if not changes:
        return u""
    counts = {}
    order = []
    for change in changes:
        key = (change[u"category"], change[u"kind"])
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1

    def rank(key):
        kind = key[1]
        place = KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)
        return (-counts[key], place, key[0])

    order.sort(key=rank)

    parts = []
    for key in order[:limit]:
        category, kind = key
        count = counts[key]
        name = singular(category)
        if count > 1:
            name = _plural(name)
            parts.append(u"{0} {1} {2}".format(count, name, kind))
        else:
            parts.append(u"{0} {1}".format(name, kind))
        if kind == ALTERED:
            fields = []
            for change in changes:
                if (change[u"category"], change[u"kind"]) != key:
                    continue
                for field in change.get(u"params_changed", []):
                    if field not in fields:
                        fields.append(field)
            if fields:
                parts[-1] += u" ({0})".format(u", ".join(fields[:2]))
    if len(order) > limit:
        parts.append(u"and {0} more".format(len(order) - limit))
    text = u", ".join(parts)
    return text[:1].upper() + text[1:]


def _plural(name):
    if name.endswith(u"y") and not name.endswith((u"ay", u"ey", u"oy", u"uy")):
        return name[:-1] + u"ies"
    if name.endswith((u"s", u"x", u"ch", u"sh")):
        return name + u"es"
    if name.endswith(u"equipment"):
        return name
    return name + u"s"
