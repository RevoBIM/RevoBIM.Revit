# -*- coding: utf-8 -*-
"""Schematic Builder - the LV schematic layout and circuit routing.

Pure Python, in paper millimetres, so ``bench_logic.py`` can hold it to
account. Builds on the same room clusters and level stacking as the
ventilation schematic and adds the feeders:

- every panel gets a **slot** wide enough for its circuits to leave it
  side by side, ``gap`` apart (18mm by default);
- a feeder goes **up from the top of the supplying panel** in its own lane,
  runs **across under the fed panel** in a jog band beneath that level's
  panels, and **up into the bottom of the fed panel** - an orthogonal dog leg;
- a panel is **never placed on a lane** that passes through its level: the
  bands are laid out bottom-up, each level shifting its panels clear of the
  feeders rising through it, and the drawing is allowed to grow wider
  rather than wrap;
- jogs that would overlap under one level are **staggered**, and that
  level's clearance above its line grows to fit them.

Feeders that go down or sideways (a panel supplying one on its own level or
below) use a corridor above the fed panel instead; they are routed but not
kept clear of, and any crossing is counted so it can be reported.
"""
from sb_logic import (as_text, to_float, block_for_group, level_pitch, stack_levels,
                      natural_key)


def feed_depth(edges, level_of, main_id=None):
    """How many same-level feeds deep each panel is.

    A panel fed by another panel on its own level sits one row higher, so the
    supplying board is always below the boards it feeds - the main LV at the
    bottom of its level, its sub-boards above it, exactly as a real LV
    schematic reads. The main panel is pinned to the bottom row.
    """
    feeders = {}
    for src, dst, label in edges:
        if level_of.get(src) == level_of.get(dst) and src != dst:
            feeders.setdefault(dst, []).append(src)
    depth = {}

    def of(item_id, seen):
        if item_id in depth:
            return depth[item_id]
        if item_id in seen:
            return 0            # a ring: stop rather than recurse for ever
        seen = seen | set([item_id])
        best = 0
        for src in feeders.get(item_id, []):
            best = max(best, of(src, seen) + 1)
        depth[item_id] = best
        return best

    for item_id in level_of:
        of(item_id, set())
    if main_id in depth:
        depth[main_id] = 0
    return depth


def group_rows(groups, depth):
    """The row each room cluster belongs on: the shallowest item in it, so a
    room stays one box rather than being split across rows."""
    rows = []
    for group in groups:
        best = None
        for item in group["items"]:
            d = depth.get(item["id"], 0)
            best = d if best is None else min(best, d)
        rows.append(best or 0)
    return rows


def lv_params(settings, base):
    """The LV additions on top of the shared layout params."""
    p = dict(base)
    p["gap"] = to_float(settings.get("lv_line_gap_mm"), 18.0)
    p["jog_base"] = to_float(settings.get("lv_jog_mm"), 6.0)
    p["jog_step"] = to_float(settings.get("lv_jog_step_mm"), 4.0)
    p["lane_clear"] = to_float(settings.get("lv_lane_clear_mm"), 4.0)
    p["level_clear"] = max(p["level_clear"], to_float(settings.get("lv_level_clear_mm"), 30.0))
    p["row_gap"] = to_float(settings.get("lv_row_gap_mm"), 28.0)
    return p


def outlet_xs(centre, count, gap):
    """count positions centred on centre, gap apart."""
    if count <= 0:
        return []
    start = centre - (count - 1) * gap / 2.0
    return [start + i * gap for i in range(count)]


def item_levels(levels, groups_by_level):
    """{item id: index of its level, lowest = 0}."""
    order = dict([(levels[i][0], i) for i in range(len(levels))])
    level_of = {}
    for level_key in groups_by_level:
        for group in groups_by_level[level_key]:
            for item in group["items"]:
                level_of[item["id"]] = order.get(level_key, 0)
    return level_of


def widen_for_circuits(groups_by_level, edges, level_of, gap):
    """Give every panel a slot wide enough for its feeders. Records the
    symbol's real width as sym_w and how far to shift it to sit centred."""
    top_out = {}
    bottom_out = {}
    top_in = {}
    bottom_in = {}
    for src, dst, label in edges:
        if src not in level_of or dst not in level_of:
            continue
        if level_of[src] <= level_of[dst]:
            # up a level, or up a row on the same level: out of the top, into
            # the bottom, because the supplying board is always the lower one
            top_out[src] = top_out.get(src, 0) + 1
            bottom_in[dst] = bottom_in.get(dst, 0) + 1
        else:
            bottom_out[src] = bottom_out.get(src, 0) + 1  # down and out of the bottom
            top_in[dst] = top_in.get(dst, 0) + 1
    for level_key in groups_by_level:
        for group in groups_by_level[level_key]:
            for item in group["items"]:
                need = max(top_out.get(item["id"], 0), bottom_out.get(item["id"], 0),
                           top_in.get(item["id"], 0), bottom_in.get(item["id"], 0))
                if "sym_w" not in item:
                    item["sym_w"] = item["w"]
                slot = max(item["sym_w"], need * gap + gap) if need else item["sym_w"]
                item["w"] = slot
                item["slot_pad"] = (slot - item["sym_w"]) / 2.0


def layout_band_lv(groups, x_start, right, blocked, p, clear, rows=None, wanted=None):
    """One level's clusters, in rows: row 0 sits just above the level line and
    each row above it holds the boards fed from the row below. Clusters are
    shifted clear of the lanes rising through this level, and the drawing
    grows to the right rather than wrapping.

    ``wanted`` gives the x a group would like to be centred on - the outlet of
    the board feeding it - so a board sits as straight above its supply as the
    boards to its left allow."""
    max_inner_w = max(right - x_start - 2.0 * p["offset"], 10.0)
    rows = rows or [0] * len(groups)
    wanted = wanted or {}
    out = {"items": {}, "boxes": [], "labels": [], "height": 0.0, "right": x_start,
           "rows": 1 if groups else 0}
    y = clear
    for row_index in sorted(set(rows)):
        cursor_x = x_start
        row_h = 0.0
        ordered = [(index, group) for index, group in enumerate(groups) if rows[index] == row_index]
        # left to right by where each group wants to be, so the ones with a
        # supply above them keep their order and the rest fill in around them
        ordered.sort(key=lambda pair: (wanted.get(pair[0]) is None, wanted.get(pair[0], 0.0), pair[0]))
        for group_index, group in ordered:
            group_row = row_index
            block = block_for_group(group, max_inner_w * 4.0, p)   # never wrap inside a room
            like = wanted.get(group_index)
            if like is not None:
                cursor_x = max(cursor_x, like - block["w"] / 2.0)
            cursor_x = clear_of_lanes(cursor_x, block["w"], blocked, p["lane_clear"])
            for item_id in block["rel"]:
                rx, ry = block["rel"][item_id]
                out["items"][item_id] = (cursor_x + rx, y + ry)
            if block["boxed"]:
                out["boxes"].append((cursor_x, y, cursor_x + block["w"], y + block["h"]))
                lx, ly = block["label_top"]
                out["labels"].append((cursor_x + lx, y + ly, group.get("label", u"")))
            out["right"] = max(out["right"], cursor_x + block["w"])
            out["height"] = max(out["height"], y + block["h"])
            row_h = max(row_h, block["h"])
            cursor_x += block["w"] + p["room_gap"]
        y += row_h + p["row_gap"]
    out["rows"] = len(set(rows)) if groups else 0
    return out


def wanted_x(groups, rows, fed_by, lane_x):
    """Where each cluster would like to sit: the average of the outlets that
    feed the boards in it, so a board lands straight above its supply."""
    wanted = {}
    for index, group in enumerate(groups):
        xs = []
        for item in group["items"]:
            for edge in lane_x:
                if edge[1] == item["id"]:
                    xs.append(lane_x[edge])
        if xs:
            wanted[index] = sum(xs) / float(len(xs))
    return wanted


def clear_of_lanes(x, width, blocked, lane_clear):
    """Slide a block to the right until no lane runs through it."""
    moved = True
    while moved:
        moved = False
        for lane in sorted(blocked):
            if lane - lane_clear < x + width and lane + lane_clear > x:
                x = lane + lane_clear
                moved = True
    return x


def assign_lanes(edge_rows):
    """Greedy interval colouring: rows with overlapping x ranges get
    different lane numbers. edge_rows: [(x0, x1, edge)] -> {edge: lane}."""
    lanes = {}
    taken = []      # per lane, list of (x0, x1)
    for x0, x1, edge in sorted(edge_rows, key=lambda r: (min(r[0], r[1]), max(r[0], r[1]))):
        lo, hi = min(x0, x1), max(x0, x1)
        lane = 0
        while lane < len(taken) and [1 for a, b in taken[lane] if a < hi and b > lo]:
            lane += 1
        if lane == len(taken):
            taken.append([])
        taken[lane].append((lo, hi))
        lanes[edge] = lane
    return lanes


def plan_lv(levels, groups_by_level, edges, frame, p, main_id=None):
    """levels: [(key, label, label_w, label_h)] lowest first.
    groups_by_level: as build_groups.
    edges: [(source_id, target_id, label)].

    Returns the layout dict of layout_schematic plus:
      routes  [(label, src, dst, [(x, y), ...])]
      clashes [(label, item_id)]  vertical runs crossing a panel they do not serve
      right   the right hand edge the drawing needs
      pads    {item_id: shift so the symbol sits centred in its slot}
    """
    left, bottom, right, top = frame
    gap = p["gap"]
    level_of = item_levels(levels, groups_by_level)
    seen = set()
    unique = []
    for edge in edges:
        if edge[0] in level_of and edge[1] in level_of and edge[0] != edge[1] and edge not in seen:
            seen.add(edge)
            unique.append(edge)
    edges = unique
    widen_for_circuits(groups_by_level, edges, level_of, gap)
    depth = feed_depth(edges, level_of, main_id)
    rows_for = {}
    group_of_item = {}
    for key in groups_by_level:
        rows_for[key] = group_rows(groups_by_level[key], depth)
        for index, group in enumerate(groups_by_level[key]):
            for item in group["items"]:
                group_of_item[item["id"]] = (key, index)
    fed_by = {}
    for src, dst, label in edges:
        fed_by.setdefault(dst, []).append(src)

    widest = 0.0
    for key, label, label_w, label_h in levels:
        widest = max(widest, label_w)
    x_start = left + max(widest + 10.0, 25.0)

    # ---- x positions, bottom up, keeping clear of the lanes rising through
    bands = {}
    lane_x = {}                     # edge -> x of its vertical run from the source
    for index, (key, label, label_w, label_h) in enumerate(levels):
        blocked = [lane_x[e] for e in lane_x
                   if level_of[e[0]] < index < level_of[e[1]]]
        band = layout_band_lv(groups_by_level.get(key, []), x_start, right, blocked, p,
                              p["level_clear"], rows_for.get(key),
                              wanted_x(groups_by_level.get(key, []), rows_for.get(key), fed_by, lane_x))
        bands[key] = band
        # outlets on the panels of this level, in target order left to right
        for group in groups_by_level.get(key, []):
            for item in group["items"]:
                out_edges = [e for e in edges if e[0] == item["id"]]
                if not out_edges:
                    continue
                out_edges.sort(key=lambda e: (level_of[e[1]], natural_key(as_text(e[1]))))
                cx = band["items"][item["id"]][0] + item["w"] / 2.0
                for x, edge in zip(outlet_xs(cx, len(out_edges), gap), out_edges):
                    lane_x[edge] = x

    # ---- inlets, jogs and the clearance each level needs for them
    item_of = {}
    for key in groups_by_level:
        for group in groups_by_level[key]:
            for item in group["items"]:
                item_of[item["id"]] = item
    inlet_x = {}
    for key, label, label_w, label_h in levels:
        for group in groups_by_level.get(key, []):
            for item in group["items"]:
                in_edges = [e for e in edges if e[1] == item["id"]]
                if not in_edges:
                    continue
                in_edges.sort(key=lambda e: lane_x.get(e, 0.0))
                cx = bands[key]["items"][item["id"]][0] + item["w"] / 2.0
                for x, edge in zip(outlet_xs(cx, len(in_edges), gap), in_edges):
                    inlet_x[edge] = x

    bottom_jogs = {}                # level index -> {edge: lane}  (arriving from below)
    row_jogs = {}                   # level index -> {edge: lane}  (same level, row to row)
    top_jogs = {}                   # level index -> {edge: lane}  (arriving from above)
    for index, (key, label, label_w, label_h) in enumerate(levels):
        arriving_below = [(lane_x[e], inlet_x[e], e) for e in edges
                          if level_of[e[1]] == index and level_of[e[0]] < index]
        same_level = [(lane_x[e], inlet_x[e], e) for e in edges
                      if level_of[e[1]] == index and level_of[e[0]] == index]
        arriving_above = [(lane_x[e], inlet_x[e], e) for e in edges
                          if level_of[e[1]] == index and level_of[e[0]] > index]
        bottom_jogs[index] = assign_lanes(arriving_below)
        row_jogs[index] = assign_lanes(same_level)
        top_jogs[index] = assign_lanes(arriving_above)

    clears = []
    corridors = []
    for index in range(len(levels)):
        count = (max(bottom_jogs[index].values()) + 1) if bottom_jogs[index] else 0
        clears.append(max(p["level_clear"], p["jog_base"] + count * p["jog_step"] + p["jog_base"]) if count
                      else p["level_clear"])
        count_top = (max(top_jogs[index].values()) + 1) if top_jogs[index] else 0
        corridors.append(p["jog_base"] + count_top * p["jog_step"] if count_top else 0.0)

    # ---- final bands with the right clearance, then stack the levels
    used_right = right
    pitches = []
    for index, (key, label, label_w, label_h) in enumerate(levels):
        blocked = [lane_x[e] for e in lane_x if level_of[e[0]] < index < level_of[e[1]]]
        band = layout_band_lv(groups_by_level.get(key, []), x_start, right, blocked, p, clears[index],
                              rows_for.get(key),
                              wanted_x(groups_by_level.get(key, []), rows_for.get(key), fed_by, lane_x))
        bands[key] = band
        used_right = max(used_right, band["right"] + p["room_gap"])
        pitches.append(level_pitch(band["height"] + corridors[index], label_h, p))
    ys, used_top, fits = stack_levels(pitches, frame)

    out = {"lines": [], "level_labels": [], "items": {}, "boxes": [], "labels": [],
           "ys": {}, "rows": {}, "height": used_top - bottom, "fits": fits, "overflow": [],
           "routes": [], "clashes": [], "right": used_right, "pads": {}, "widths": {},
           "depth": depth}
    abs_box = {}
    for index, (key, label, label_w, label_h) in enumerate(levels):
        y = ys[index]
        band = bands[key]
        out["ys"][key] = y
        out["rows"][key] = band.get("rows", 1 if band["items"] else 0)
        out["lines"].append((left, y, used_right))
        out["level_labels"].append((left, y + p["text_gap"] + label_h, label))
        for item_id in band["items"]:
            x, ry = band["items"][item_id]
            item = item_of[item_id]
            out["items"][item_id] = (x, y + ry)
            out["pads"][item_id] = item.get("slot_pad", 0.0)
            out["widths"][item_id] = item["w"]
            abs_box[item_id] = (x, y + ry, x + item["w"], y + ry + item["h"])
        for x0, y0, x1, y1 in band["boxes"]:
            out["boxes"].append((x0, y + y0, x1, y + y1))
        for x, y_top, text in band["labels"]:
            out["labels"].append((x, y + y_top, text))

    # ---- the routes
    for src, dst, label in edges:
        edge = (src, dst, label)
        sx0, sy0, sx1, sy1 = abs_box[src]
        tx0, ty0, tx1, ty1 = abs_box[dst]
        x_out = lane_x[edge]
        x_in = inlet_x[edge]
        src_level = level_of[src]
        dst_level = level_of[dst]
        if src_level < dst_level:
            lane = bottom_jogs[dst_level].get(edge, 0)
            y_jog = ys[dst_level] + p["jog_base"] + lane * p["jog_step"]
            points = [(x_out, sy1), (x_out, y_jog), (x_in, y_jog), (x_in, ty0)]
        elif src_level == dst_level:
            # the supplying board is on the row below: straight up out of its
            # top, across in the gap between the rows, up into the fed board
            lane = row_jogs[dst_level].get(edge, 0)
            y_jog = sy1 + p["jog_base"] + lane * p["jog_step"]
            if ty0 <= sy1:
                y_jog = max(y_jog, ty1 + p["jog_base"] + lane * p["jog_step"])
                points = [(x_out, sy1), (x_out, y_jog), (x_in, y_jog), (x_in, ty1)]
            else:
                y_jog = min(y_jog, ty0 - 1e-9) if y_jog >= ty0 else y_jog
                points = [(x_out, sy1), (x_out, y_jog), (x_in, y_jog), (x_in, ty0)]
        else:
            # downwards: out of the bottom, into the top of the fed panel
            lane = top_jogs[dst_level].get(edge, 0)
            corridor_base = ys[dst_level] + bands[levels[dst_level][0]]["height"]
            y_c = corridor_base + p["jog_base"] + lane * p["jog_step"]
            points = [(x_out, sy0), (x_out, y_c), (x_in, y_c), (x_in, ty1)]
        out["routes"].append((label, src, dst, points))
        # a vertical run through a panel it does not serve
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if abs(ax - bx) > 1e-9:
                continue
            lo, hi = min(ay, by), max(ay, by)
            for item_id in abs_box:
                if item_id in (src, dst):
                    continue
                bx0, by0, bx1, by1 = abs_box[item_id]
                if bx0 < ax < bx1 and by0 < hi and by1 > lo:
                    out["clashes"].append((label, item_id))
    return out
