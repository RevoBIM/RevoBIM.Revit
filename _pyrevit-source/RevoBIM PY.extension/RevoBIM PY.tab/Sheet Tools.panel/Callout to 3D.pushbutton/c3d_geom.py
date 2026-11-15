# -*- coding: utf-8 -*-
"""Callout to 3D - the geometry.

The maths sits in plain functions over tuples so the bench can run it under
CPython; only the thin wrappers at the bottom touch the Revit API.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import math

import c3d_core as core

# ---------------------------------------------------------------------------
# pure maths - all distances in millimetres unless the name says feet
# ---------------------------------------------------------------------------


def section_stations(count, low, high):
    """Evenly spaced cut positions across a span, none of them on an edge.

    One section sits on the middle; two sit at a third and two thirds, and so
    on - stations at (i + 1) / (count + 1) of the span.
    """
    try:
        count = int(count)
    except Exception:
        count = 0
    if count <= 0:
        return []
    span = float(high) - float(low)
    return [float(low) + span * (float(index + 1) / float(count + 1))
            for index in range(count)]


CUT_LIMIT = 0.02          # a dragged cut stays this fraction clear of the crop edge


def clamp_cut(fraction):
    try:
        value = float(fraction)
    except Exception:
        return None
    if value != value:
        return None
    return max(CUT_LIMIT, min(1.0 - CUT_LIMIT, value))


def stations_for(count, low, high, prefix, cuts=None):
    """The cut positions, with any that were dragged in the preview where they
    were left.  A dragged cut is kept as a fraction of the span rather than in
    millimetres, so it stays in the same place on the callout if the crop is
    nudged; one with no drag sits on the even spacing."""
    even = section_stations(count, low, high)
    cuts = cuts or {}
    span = float(high) - float(low)
    out = []
    for index, station in enumerate(even):
        moved = clamp_cut(cuts.get(u"{0}{1}".format(prefix, index + 1)))
        out.append(float(low) + span * moved if moved is not None else station)
    return out


def cut_fraction(value, low, high):
    """Where a point along a span sits, as the fraction a dragged cut keeps."""
    span = float(high) - float(low)
    if abs(span) < 1e-9:
        return 0.5
    return clamp_cut((float(value) - float(low)) / span)


def grid_ends(start, end, z_low, z_high):
    """A grid's line in a section, cut down to the top and bottom of the
    view's crop - each end keeps its own side, so the bubble stays where it
    was and only the length changes."""
    low, high = float(z_low), float(z_high)
    if float(start[2]) >= float(end[2]):
        return (start[0], start[1], high), (end[0], end[1], low)
    return (start[0], start[1], low), (end[0], end[1], high)


def label_shift(box, label, gap):
    """How far to move a viewport title so it sits `gap` under the view's box,
    level with its left edge: (dx, dy) in the same units as the outlines.

    Worked out from where the title actually is rather than from what
    LabelOffset is measured against, which Revit does not say - so a single
    move lands it whatever that reference point turns out to be."""
    (box_low_x, box_low_y), _box_high = box
    (label_low_x, _label_low_y), (_label_high_x, label_high_y) = label
    return box_low_x - label_low_x, (box_low_y - float(gap)) - label_high_y


def top_z_mm(rule, base_mm, next_level_mm, fixed_mm, offset_mm=0.0):
    """Where the top of the 3D box and the sections goes.

    The offset is measured from the level above and is normally negative, so
    the box stops short of the slab over it rather than cutting through it.
    It is deliberately NOT applied to the fixed height, which is already the
    answer to the same question and would otherwise be moved twice.
    """
    rule = (rule or "next_level").strip().lower()
    base = float(base_mm)
    offset = float(offset_mm or 0.0)
    fixed = base + float(fixed_mm)
    if rule == "fixed":
        return fixed
    # 'next_level', and 'callout' where the crop depth is handed in as
    # next_level_mm - both take the offset, both fall back to the fixed height
    if next_level_mm is not None and float(next_level_mm) > base + 1.0:
        top = float(next_level_mm) + offset
        return top if top > base + 1.0 else fixed
    return fixed






# ---------------------------------------------------------------------------
# sheet layouts - the presets the window cycles through
#
# Every preset takes the same things and gives back the same shape, so the
# preview, the run and the bench all go through one function:
#     {"callout": cell, "3d": cell, "x": [cells], "y": [cells],
#      "overflow": bool, "too_wide": bool}
# with each cell (x, y, width, height) in sheet mm from the bottom left.
# ---------------------------------------------------------------------------

LAYOUT_PRESETS = [
    ("columns", "Plan top left, 3D top right",
     "X sections down the left, Y sections down the right"),
    ("mirror", "3D top left, plan top right",
     "Y sections down the left, X sections down the right"),
    ("rows", "Plan top left, 3D top right",
     "every section in rows underneath, left to right"),
    ("plan_left", "Plan and 3D down the left",
     "every section stacked down the right"),
]


def preset_keys():
    return [key for key, _title, _detail in LAYOUT_PRESETS]


def preset_label(key):
    for candidate, title, detail in LAYOUT_PRESETS:
        if candidate == key:
            return title, detail
    return LAYOUT_PRESETS[0][1], LAYOUT_PRESETS[0][2]


def next_preset(key, step=1):
    """The preset after (or before) this one, going round."""
    keys = preset_keys()
    index = keys.index(key) if key in keys else 0
    return keys[(index + int(step)) % len(keys)]


def _rows_layout(usable, callout, three_d, x_cells, y_cells, gap, section_gap):
    """Plan and 3D across the top, then every section packed left to right
    underneath, wrapping when the width runs out."""
    left, bottom, width, height = [float(value) for value in usable]
    top_y = bottom + height
    callout_w, callout_h = (float(callout[0]), float(callout[1])) if callout else (0.0, 0.0)
    three_w, three_h = (float(three_d[0]), float(three_d[1])) if three_d else (0.0, 0.0)
    three_x = left + callout_w + gap if callout else left
    out = {
        "callout": (left, top_y - callout_h, callout_w, callout_h) if callout else None,
        "3d": (three_x, top_y - three_h, three_w, three_h) if three_d else None,
        "x": [], "y": [], "overflow": False,
        "too_wide": three_x + three_w > left + width + 0.001,
    }
    row_height = max(callout_h, three_h)
    y = top_y - row_height - gap if row_height else top_y
    x = left
    tallest = 0.0
    every = [("x", cell) for cell in x_cells] + [("y", cell) for cell in y_cells]
    for key, (cell_w, cell_h) in every:
        cell_w, cell_h = float(cell_w), float(cell_h)
        if x > left + 0.001 and x + cell_w > left + width + 0.001:
            y -= tallest + section_gap
            x = left
            tallest = 0.0
        out[key].append((x, y - cell_h, cell_w, cell_h))
        x += cell_w + section_gap
        tallest = max(tallest, cell_h)
    lowest = [cell[1] for cell in out["x"] + out["y"]]
    out["overflow"] = bool(lowest) and min(lowest) < bottom - 0.001
    return out


def _plan_left_layout(usable, callout, three_d, x_cells, y_cells, gap,
                      section_gap, min_gap):
    """Plan at the top of the left column with the 3D under it; every section
    stacked down a right hand column."""
    left, bottom, width, height = [float(value) for value in usable]
    top_y = bottom + height
    callout_w, callout_h = (float(callout[0]), float(callout[1])) if callout else (0.0, 0.0)
    three_w, three_h = (float(three_d[0]), float(three_d[1])) if three_d else (0.0, 0.0)
    three_top = top_y - callout_h - (gap if callout else 0.0)
    column_x = left + max(callout_w, three_w) + gap
    every = list(x_cells) + list(y_cells)
    places, _gap_used, over = column_stack(every, top_y, bottom, section_gap, min_gap)
    cells = [(column_x, place[1], place[2], place[3]) for place in places]
    widest = max([cell[0] for cell in every]) if every else 0.0
    return {
        "callout": (left, top_y - callout_h, callout_w, callout_h) if callout else None,
        "3d": (left, three_top - three_h, three_w, three_h) if three_d else None,
        "x": cells[:len(x_cells)], "y": cells[len(x_cells):],
        "overflow": over or (three_d is not None and three_top - three_h < bottom - 0.001),
        "too_wide": column_x + widest > left + width + 0.001,
    }


def layout_for(preset, usable, callout, three_d, x_cells, y_cells,
               gap_mm, section_gap_mm, min_gap_mm=2.0):
    """The cells for a preset.  An unknown preset falls back to the columns,
    which is what every sheet before 2.1.0 used."""
    preset = preset if preset in preset_keys() else "columns"
    if preset == "rows":
        return _rows_layout(usable, callout, three_d, x_cells, y_cells,
                            float(gap_mm), float(section_gap_mm))
    if preset == "plan_left":
        return _plan_left_layout(usable, callout, three_d, x_cells, y_cells,
                                 float(gap_mm), float(section_gap_mm), min_gap_mm)
    if preset == "mirror":
        out = two_column_layout(usable, three_d, callout, y_cells, x_cells,
                                gap_mm, section_gap_mm, min_gap_mm)
        out["callout"], out["3d"] = out["3d"], out["callout"]
        out["x"], out["y"] = out["y"], out["x"]
        return out
    return two_column_layout(usable, callout, three_d, x_cells, y_cells,
                             gap_mm, section_gap_mm, min_gap_mm)


def layout_roles(layout):
    """Every placed cell by the name it is known by in the preview and in a
    moved position: callout, 3d, X1.., Y1.."""
    out = []
    if layout.get("callout"):
        out.append(("callout", layout["callout"]))
    if layout.get("3d"):
        out.append(("3d", layout["3d"]))
    for axis in ("x", "y"):
        for index, cell in enumerate(layout.get(axis) or []):
            out.append((u"{0}{1}".format(axis.upper(), index + 1), cell))
    return out


def recheck_fit(layout, usable):
    """Whether anything sits off the usable area once boxes have been moved -
    a setout dragged clear of the bottom is no longer an overflow, and one
    dragged off it is."""
    left, bottom, width, height = [float(value) for value in usable]
    out = dict(layout)
    cells = [cell for _role, cell in layout_roles(layout)]
    out["overflow"] = any([cell[1] < bottom - 0.5 for cell in cells])
    out["too_wide"] = any([cell[0] + cell[2] > left + width + 0.5 for cell in cells])
    return out


def shift_moves(moves, origin):
    """A custom setout is kept from the paper's own bottom left corner, so it
    is the same on any sheet - moved onto the sheet where the title block's
    corner actually is before it is used."""
    ox, oy = float(origin[0]), float(origin[1])
    return dict([(role, (float(point[0]) + ox, float(point[1]) + oy))
                 for role, point in (moves or {}).items()])


def apply_moves(layout, moves):
    """Put any viewport the user dragged in the preview where they left it.

    `moves` maps a role to the sheet position of its centre.  The cell keeps
    its own width and height - the real viewport is measured at the run and
    may not be the size the preview guessed - and is centred where it was put.
    """
    if not moves:
        return layout
    out = dict(layout)

    def moved(role, cell):
        if cell is None or role not in moves:
            return cell
        centre_x, centre_y = moves[role]
        return (float(centre_x) - cell[2] / 2.0, float(centre_y) - cell[3] / 2.0,
                cell[2], cell[3])

    out["callout"] = moved("callout", layout.get("callout"))
    out["3d"] = moved("3d", layout.get("3d"))
    for axis in ("x", "y"):
        out[axis] = [moved(u"{0}{1}".format(axis.upper(), index + 1), cell)
                     for index, cell in enumerate(layout.get(axis) or [])]
    return out


def estimate_sizes(half_x, half_y, band_mm, scale, side_margin_mm, x_count, y_count,
                   title_mm=14.0, crop_margin_mm=150.0, section_scale=None,
                   three_d_scale=None):
    """Roughly how big each view will print, for the preview, in sheet mm.

    Only Revit knows for certain - the run measures the real viewports - but
    the preview needs boxes of about the right shape to be any use.  The 3D is
    the isometric outline of the box: (W + D) cos 30 across and
    (W + D) sin 30 + H high.
    """
    try:
        scale = max(1.0, float(scale or 50))
    except Exception:
        scale = 50.0
    width_x = 2.0 * float(half_x)
    width_y = 2.0 * float(half_y)
    band = max(1.0, float(band_mm))
    margin = float(side_margin_mm)
    plan = (width_x / scale, width_y / scale + title_mm)
    iso_w = (width_x + width_y) * 0.8660 + 2.0 * crop_margin_mm
    iso_h = (width_x + width_y) * 0.5 + band + 2.0 * crop_margin_mm
    try:
        iso = max(1.0, float(three_d_scale)) if three_d_scale else scale
    except Exception:
        iso = scale
    three = (iso_w / iso, iso_h / iso + title_mm)
    try:
        cut = max(1.0, float(section_scale)) if section_scale else scale
    except Exception:
        cut = scale
    x_cell = ((width_x + 2.0 * margin) / cut, band / cut + title_mm)
    y_cell = ((width_y + 2.0 * margin) / cut, band / cut + title_mm)
    return {
        "callout": plan,
        "3d": three,
        "x": [x_cell] * max(0, int(x_count)),
        "y": [y_cell] * max(0, int(y_count)),
    }


def sheet_fit(sheet_w, sheet_h, canvas_w, canvas_h, pad=14.0):
    """How a sheet sits in a preview canvas: (pixels per mm, left, top).

    The sheet is fitted whole and centred, so a box dragged to an edge in the
    preview is at the same edge on the paper.
    """
    sheet_w, sheet_h = max(1.0, float(sheet_w)), max(1.0, float(sheet_h))
    room_w = max(1.0, float(canvas_w) - 2.0 * pad)
    room_h = max(1.0, float(canvas_h) - 2.0 * pad)
    k = min(room_w / sheet_w, room_h / sheet_h)
    left = (float(canvas_w) - sheet_w * k) / 2.0
    top = (float(canvas_h) - sheet_h * k) / 2.0
    return k, left, top


def to_canvas(fit, sheet_h, x_mm, y_mm):
    """Sheet mm (from the bottom left) to canvas pixels (from the top left)."""
    k, left, top = fit
    return left + float(x_mm) * k, top + (float(sheet_h) - float(y_mm)) * k


def from_canvas(fit, sheet_h, x_px, y_px):
    """The other way: canvas pixels back to sheet mm."""
    k, left, top = fit
    k = k or 1.0
    return (float(x_px) - left) / k, float(sheet_h) - (float(y_px) - top) / k


def clamp_centre(cell, centre, sheet_w, sheet_h, snap_mm=1.0):
    """Where a dragged box is allowed to end up: wholly on the paper, its
    centre on a whole millimetre, so a nudge in the preview reads as a tidy
    number on the sheet."""
    half_w = min(float(cell[2]), float(sheet_w)) / 2.0
    half_h = min(float(cell[3]), float(sheet_h)) / 2.0
    x = min(max(float(centre[0]), half_w), float(sheet_w) - half_w)
    y = min(max(float(centre[1]), half_h), float(sheet_h) - half_h)
    step = float(snap_mm or 0.0)
    if step > 0:
        x = round(x / step) * step
        y = round(y / step) * step
        x = min(max(x, half_w), float(sheet_w) - half_w)
        y = min(max(y, half_h), float(sheet_h) - half_h)
    return (x, y)


def overlaps(layout):
    """Every pair of placed cells that overlap, by role - what the preview
    paints red, and what the bench proves every preset avoids."""
    roles = layout_roles(layout)
    out = []
    for index, (role_a, a) in enumerate(roles):
        for role_b, b in roles[index + 1:]:
            if a[0] < b[0] + b[2] - 0.001 and b[0] < a[0] + a[2] - 0.001 and \
                    a[1] < b[1] + b[3] - 0.001 and b[1] < a[1] + a[3] - 0.001:
                out.append((role_a, role_b))
    return out


# a stand-in for the preset thumbnails: the plan, the 3D and a section, in
# about the proportions a typical callout prints at
THUMB_SIZES = {"callout": (240.0, 170.0), "3d": (230.0, 170.0), "section": (240.0, 60.0)}


def thumbnail_layout(preset, x_count=2, y_count=2, sheet=(841.0, 594.0)):
    """A preset drawn with stand-in sizes, for its card in the cycler, so each
    card shows the arrangement rather than one callout's particular shape."""
    width, height = float(sheet[0]), float(sheet[1])
    usable = (20.0, 20.0, width - 40.0, height - 40.0)
    section = THUMB_SIZES["section"]
    return layout_for(preset, usable, THUMB_SIZES["callout"], THUMB_SIZES["3d"],
                      [section] * int(x_count), [section] * int(y_count),
                      12.0, 6.0, 2.0)


def room_tag_spot(corners, crop_min, crop_max, lift, inset=0.0):
    """Where a room tag goes in a section, in the crop box's own frame - or
    None when the section does not cut the room at all.

    `corners` are the room's bounding box corners already taken into that
    frame (x across the section, y up it, z into it).  The room is cut when
    its box overlaps the crop box on all three; the tag sits at the middle of
    the overlap across, `lift` above the bottom of it (half way up if the
    room is shorter than that), and on the view plane itself.
    """
    xs = [float(c[0]) for c in corners]
    ys = [float(c[1]) for c in corners]
    zs = [float(c[2]) for c in corners]
    low_x, high_x = max(min(xs), float(crop_min[0])), min(max(xs), float(crop_max[0]))
    low_y, high_y = max(min(ys), float(crop_min[1])), min(max(ys), float(crop_max[1]))
    low_z, high_z = max(min(zs), float(crop_min[2])), min(max(zs), float(crop_max[2]))
    if high_x <= low_x or high_y <= low_y or high_z < low_z:
        return None
    inset = float(inset or 0.0)
    x = (low_x + high_x) / 2.0
    y = low_y + min(float(lift), (high_y - low_y) / 2.0)
    y = min(max(y, float(crop_min[1]) + inset), float(crop_max[1]) - inset)
    return (x, y)


def box_corners(low, high):
    """The eight corners of a box given its two opposite ones."""
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1])
            for z in (low[2], high[2])]


def footprint_mm(box, label, centre, pad_mm=0.0):
    """A viewport's whole footprint on the sheet, and where it sits relative
    to the point that moves it.

    `box` and `label` are ((min x, min y), (max x, max y)) in sheet mm; the
    label may be None.  Two lessons are built in:

    - THE LABEL IS NOT IN THE BOX OUTLINE, and it is usually wider than the
      view - measuring only the box packed each neighbour on top of a title;
    - THE BOX CENTRE IS NOT THE MIDDLE OF THE FOOTPRINT, since the title hangs
      below and to the left - positioning by the centre put every viewport out
      by the size of its own title.
    """
    (low_x, low_y), (high_x, high_y) = box
    if label is not None:
        low_x = min(low_x, label[0][0])
        low_y = min(low_y, label[0][1])
        high_x = max(high_x, label[1][0])
        high_y = max(high_y, label[1][1])
    pad = float(pad_mm or 0.0)
    low_x, low_y, high_x, high_y = low_x - pad, low_y - pad, high_x + pad, high_y + pad
    return {
        "width": high_x - low_x,
        "height": high_y - low_y,
        "offset_x": (low_x + high_x) / 2.0 - float(centre[0]),
        "offset_y": (low_y + high_y) / 2.0 - float(centre[1]),
    }


def cell_centre(cell):
    x, y, w, h = cell
    return (x + w / 2.0, y + h / 2.0)






def section_frames(extents_mm, x_count, y_count, base_mm, top_mm,
                   side_margin_mm=250.0, flip_x=False, flip_y=False, per=None,
                   cuts=None):
    """Every section the run will cut, in the callout's own frame.

    An 'X axis' section is a cut line running along the callout's X axis - you
    look along Y at it - and they are arrayed up the Y span.  A 'Y axis'
    section is the other way round.

    `flip_x` and `flip_y` turn a whole axis round.  `per` is a dictionary keyed
    by label - X1, X2, Y1 - and turns **one** section round on top of that, so
    a single section that wants to look the other way does not mean flipping
    its neighbours with it.  Each section carries its own `label` and `flipped`
    so the name, the preview and the run all say the same thing.
    """
    x0, y0, x1, y1 = [float(v) for v in extents_mm]
    height = float(top_mm) - float(base_mm)
    mid_z = (float(top_mm) + float(base_mm)) / 2.0
    margin = float(side_margin_mm)
    per = per or {}
    frames = []

    def flipped_for(label, axis_flip):
        one = per.get(label)
        if one is None:
            return bool(axis_flip)
        return bool(axis_flip) != bool(one)      # the override turns it round

    for index, station in enumerate(stations_for(x_count, y0, y1, "X", cuts)):
        label = u"X{0}".format(index + 1)
        flipped = flipped_for(label, flip_x)
        frames.append({
            "axis": "X",
            "index": index + 1,
            "label": label,
            "flipped": flipped,
            "origin": ((x0 + x1) / 2.0, station, mid_z),
            "look": (0.0, -1.0, 0.0) if flipped else (0.0, 1.0, 0.0),
            "width": (x1 - x0) + 2.0 * margin,
            "height": height,
            "station": station,
        })

    for index, station in enumerate(stations_for(y_count, x0, x1, "Y", cuts)):
        label = u"Y{0}".format(index + 1)
        flipped = flipped_for(label, flip_y)
        frames.append({
            "axis": "Y",
            "index": index + 1,
            "label": label,
            "flipped": flipped,
            "origin": (station, (y0 + y1) / 2.0, mid_z),
            "look": (1.0, 0.0, 0.0) if flipped else (-1.0, 0.0, 0.0),
            "width": (y1 - y0) + 2.0 * margin,
            "height": height,
            "station": station,
        })

    return frames


# ---------------------------------------------------------------------------
# Revit wrappers
# ---------------------------------------------------------------------------

from Autodesk.Revit.DB import (                      # noqa: E402
    BoundingBoxXYZ, Transform, XYZ, BuiltInParameter,
)


def level_model_z(level, source="Elevation"):
    """The level's elevation in Revit's internal (model) coordinates, in feet.

    WHICH PROPERTY IS THE INTERNAL ONE DEPENDS ON THE PROJECT, so it is not
    assumed - `source` says which, and `c3d_model.elevation_source` works it
    out from the model itself.  On a job whose elevation base is the survey
    point, `Elevation` comes back as the **shared** elevation and
    `ProjectElevation` is the internal one; set up the usual way it is the
    other way round.  Guessing cost 88 metres on a real model: every section
    and every 3D box was built that far above the building, so the views came
    out empty and the 3D would not even go on a sheet.

    Both are tried in turn, so a release that renames one does not take the
    tool down.
    """
    if level is None:
        return None
    order = ("ProjectElevation", "Elevation") if source == "ProjectElevation" \
        else ("Elevation", "ProjectElevation")
    for attribute in order:
        try:
            value = getattr(level, attribute)
            if value is not None:
                return float(value)
        except Exception:
            continue
    return None


def crop_frame(view, cache=None):
    """The callout's crop rectangle, flattened into model space.

    The crop box is handed back in its own coordinates with a transform onto
    the model, and the two are easy to mix up: local minimums are not model
    minimums, and a crop transform's origin is not the model origin.  Every
    later step wants the same three things - where the middle of the callout
    is in the model, how big it is, and which way its X axis points - so they
    are worked out once, here, and nothing downstream touches CropBox again.

        centre      the middle of the crop, in model millimetres
        half_x      half its width along its own X axis, in millimetres
        half_y      half its height along its own Y axis
        axis_x      that X axis as a model direction, flattened into plan
        axis_y      the Y axis, square to it
        rotated     False when the callout is square to the project

    Getting this wrong put the 3D box and every section near the project
    origin rather than on the callout, which is what v1.4.0 did.
    """
    # THE CROP REGION FIRST, because it is unambiguous.
    #
    # GetCropShape() hands back the crop as CurveLoops **in model
    # coordinates** - there is no transform to apply and so no way to apply it
    # twice.  CropBox is the opposite: Min and Max are in the view's own
    # coordinates and Transform maps them out, and if the two are combined
    # wrongly the result is a point roughly twice as far from the origin as it
    # should be, which is exactly what "the coordinates are way off" looks
    # like.  So the curves are asked first and CropBox is only the fallback.
    key = None
    try:
        key = core.eid_value(view.Id)
    except Exception:
        key = None
    if cache is not None and key is not None and key in cache:
        return cache[key]

    from_curves = _frame_from_crop_shape(view)
    from_box = _frame_from_crop_box(view)

    # said once per view per session: the same six lines were going into the
    # log on every read and every refresh, burying everything around them
    if from_curves and from_box and key not in _DISAGREEMENT_SAID:
        gap = max(abs(from_curves["centre"][0] - from_box["centre"][0]),
                  abs(from_curves["centre"][1] - from_box["centre"][1]))
        if gap > 1.0:
            _DISAGREEMENT_SAID.add(key)
            core.log(
                u"crop region and crop box disagree by {0:.0f}mm: curves say "
                u"{1:.0f}, {2:.0f} and the box says {3:.0f}, {4:.0f} - the "
                u"curves are used".format(
                    gap, from_curves["centre"][0], from_curves["centre"][1],
                    from_box["centre"][0], from_box["centre"][1]))
    frame = from_curves or from_box
    if cache is not None and key is not None:
        cache[key] = frame
    return frame


_DISAGREEMENT_SAID = set()


def _frame_from_crop_shape(view):
    """The crop region as model-space curves, which is the answer with no
    transform question attached to it."""
    try:
        manager = view.GetCropRegionShapeManager()
        loops = manager.GetCropShape()
    except Exception:
        return None
    points = []
    try:
        for loop in (loops or []):
            for curve in loop:
                try:
                    points.append(curve.GetEndPoint(0))
                    points.append(curve.GetEndPoint(1))
                except Exception:
                    continue
    except Exception:
        return None
    if len(points) < 3:
        return None

    # the axis is the direction of the longest edge, so a rotated crop is read
    # from its own geometry rather than assumed square to the project
    axis_x = (1.0, 0.0)
    longest = 0.0
    try:
        for loop in (loops or []):
            for curve in loop:
                try:
                    start, end = curve.GetEndPoint(0), curve.GetEndPoint(1)
                except Exception:
                    continue
                length = math.sqrt((end.X - start.X) ** 2 + (end.Y - start.Y) ** 2)
                if length > longest:
                    longest = length
                    axis_x = _flat_unit(end.X - start.X, end.Y - start.Y)
    except Exception:
        pass
    axis_y = (-axis_x[1], axis_x[0])

    us, vs, zs = [], [], []
    for point in points:
        try:
            x = core.ft_to_mm(point.X)
            y = core.ft_to_mm(point.Y)
            zs.append(core.ft_to_mm(point.Z))
        except Exception:
            continue
        us.append(x * axis_x[0] + y * axis_x[1])
        vs.append(x * axis_y[0] + y * axis_y[1])
    if not us:
        return None

    mid_u = (min(us) + max(us)) / 2.0
    mid_v = (min(vs) + max(vs)) / 2.0
    centre = (mid_u * axis_x[0] + mid_v * axis_y[0],
              mid_u * axis_x[1] + mid_v * axis_y[1])

    return {
        "transform": None,
        "source": "crop region",
        "centre": centre,
        "z": (sum(zs) / len(zs)) if zs else 0.0,
        "half_x": (max(us) - min(us)) / 2.0,
        "half_y": (max(vs) - min(vs)) / 2.0,
        "axis_x": axis_x,
        "axis_y": axis_y,
        "rotated": abs(axis_x[1]) > 1.0e-6,
    }


def _frame_from_crop_box(view):
    try:
        box = view.CropBox
    except Exception:
        return None
    if box is None:
        return None
    try:
        transform = box.Transform
        low, high = box.Min, box.Max

        def to_model(x, y):
            point = XYZ(x, y, 0.0)
            try:
                out = transform.OfPoint(point)
            except Exception:
                out = point
            return (core.ft_to_mm(out.X), core.ft_to_mm(out.Y))

        centre_local = ((low.X + high.X) / 2.0, (low.Y + high.Y) / 2.0)
        centre = to_model(centre_local[0], centre_local[1])

        try:
            basis_x = transform.OfVector(XYZ(1.0, 0.0, 0.0))
        except Exception:
            basis_x = XYZ(1.0, 0.0, 0.0)
        axis_x = _flat_unit(basis_x.X, basis_x.Y)
        axis_y = (-axis_x[1], axis_x[0])

        half_x = abs(core.ft_to_mm(high.X - low.X)) / 2.0
        half_y = abs(core.ft_to_mm(high.Y - low.Y)) / 2.0

        # the crop's own elevation, which is what a callout with no GenLevel
        # of its own is matched to a level by
        try:
            elevation = core.ft_to_mm(transform.Origin.Z)
        except Exception:
            elevation = 0.0

        return {
            "transform": transform,
            "source": "crop box",
            "centre": centre,
            "z": elevation,
            "half_x": half_x,
            "half_y": half_y,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "rotated": abs(axis_x[1]) > 1.0e-6,
        }
    except Exception:
        return None


def _quarter_turn(axis_x, tolerance=1.0e-4):
    """0, 90, 180 or 270 when the callout is square to the project to within
    a whisker, and None when it really is at an angle."""
    try:
        x, y = float(axis_x[0]), float(axis_x[1])
    except Exception:
        return 0
    for degrees, (want_x, want_y) in ((0, (1.0, 0.0)), (90, (0.0, 1.0)),
                                      (180, (-1.0, 0.0)), (270, (0.0, -1.0))):
        if abs(x - want_x) <= tolerance and abs(y - want_y) <= tolerance:
            return degrees
    return None


def _flat_unit(x, y):
    length = math.sqrt(x * x + y * y)
    if length < 1.0e-9:
        return (1.0, 0.0)
    return (x / length, y / length)


def extents_mm(frame, margin_mm=0.0):
    """The callout rectangle as offsets from its own centre, in millimetres.

    Centred rather than absolute, so the same four numbers describe a callout
    anywhere in the model and a rotated one needs no special case.
    """
    if not frame:
        return None
    margin = float(margin_mm or 0.0)
    half_x = float(frame["half_x"]) + margin
    half_y = float(frame["half_y"]) + margin
    return (-half_x, -half_y, half_x, half_y)


def section_box(frame, extents, base_mm, top_mm):
    """A BoundingBoxXYZ for View3D.SetSectionBox.

    Two shapes, and which one is used matters.  A callout square to the
    project gets an **identity transform and model coordinates**, which is the
    form `SetSectionBox` is most reliable with.  A rotated callout gets a
    transform whose origin is the callout's centre at Z zero and whose basis
    carries the rotation, with Min and Max as offsets - so the local Z is the
    model Z either way and the elevations go straight in.

    Reusing the crop box's own transform, which is what v1.4.0 did, mixes the
    view's Z origin into the box and puts it in the wrong place.
    """
    x0, y0, x1, y1 = extents
    centre = frame.get("centre", (0.0, 0.0))
    axis_x = frame.get("axis_x", (1.0, 0.0))
    box = BoundingBoxXYZ()

    # A QUARTER TURN IS NOT A ROTATION WORTH KEEPING.
    #
    # A callout turned 90 degrees describes exactly the same rectangle as an
    # axis-aligned one with its two half sizes swapped, and an axis-aligned box
    # with an identity transform is the form SetSectionBox is most reliable
    # with.  Handing Revit a rotated transform and having it ignored gives a
    # box the right size and the right centre but turned 90 degrees off the
    # callout - correct arithmetic, wrong box.  So a quarter turn is taken out
    # here rather than trusted to survive the API.
    turn = _quarter_turn(axis_x)
    if turn is not None:
        if turn in (90, 270):
            x0, y0, x1, y1 = y0, x0, y1, x1
        box.Transform = Transform.Identity
        box.Min = XYZ(core.mm_to_ft(centre[0] + min(x0, x1)),
                      core.mm_to_ft(centre[1] + min(y0, y1)),
                      core.mm_to_ft(base_mm))
        box.Max = XYZ(core.mm_to_ft(centre[0] + max(x0, x1)),
                      core.mm_to_ft(centre[1] + max(y0, y1)),
                      core.mm_to_ft(top_mm))
        return box

    axis_y = frame.get("axis_y", (0.0, 1.0))
    transform = Transform.Identity
    transform.Origin = XYZ(core.mm_to_ft(centre[0]), core.mm_to_ft(centre[1]), 0.0)
    transform.BasisX = XYZ(axis_x[0], axis_x[1], 0.0)
    transform.BasisY = XYZ(axis_y[0], axis_y[1], 0.0)
    transform.BasisZ = XYZ(0.0, 0.0, 1.0)
    box.Transform = transform
    box.Min = XYZ(core.mm_to_ft(x0), core.mm_to_ft(y0), core.mm_to_ft(base_mm))
    box.Max = XYZ(core.mm_to_ft(x1), core.mm_to_ft(y1), core.mm_to_ft(top_mm))
    return box


def _to_model(frame, point_mm):
    """A point measured from the callout's centre, in millimetres, out to a
    model point in feet.  Z goes straight through as an absolute elevation."""
    u, v, z = point_mm[0], point_mm[1], point_mm[2]
    centre = frame.get("centre", (0.0, 0.0))
    axis_x = frame.get("axis_x", (1.0, 0.0))
    axis_y = frame.get("axis_y", (0.0, 1.0))
    x = centre[0] + u * axis_x[0] + v * axis_y[0]
    y = centre[1] + u * axis_x[1] + v * axis_y[1]
    return XYZ(core.mm_to_ft(x), core.mm_to_ft(y), core.mm_to_ft(z))


def _direction(frame, vector):
    """A direction in the callout's own axes, out to a model direction."""
    axis_x = frame.get("axis_x", (1.0, 0.0))
    axis_y = frame.get("axis_y", (0.0, 1.0))
    x = vector[0] * axis_x[0] + vector[1] * axis_y[0]
    y = vector[0] * axis_x[1] + vector[1] * axis_y[1]
    unit = _flat_unit(x, y)
    return XYZ(unit[0], unit[1], 0.0)


def section_creation_box(frame, spec, depth_mm, sign=-1.0):
    """The BoundingBoxXYZ handed to ViewSection.CreateSection.

    BasisZ points towards the viewer, so the intended looking direction goes
    in negated; ``sign`` lets a run flip that once if a release turns out to
    disagree, which is checked by reading ViewDirection back off the first
    section made.
    """
    look = _direction(frame, spec["look"])
    up = XYZ(0, 0, 1)
    basis_z = XYZ(look.X * sign, look.Y * sign, look.Z * sign).Normalize()
    basis_x = up.CrossProduct(basis_z).Normalize()

    transform = Transform.Identity
    transform.Origin = _to_model(frame, spec["origin"])
    transform.BasisX = basis_x
    transform.BasisY = up
    transform.BasisZ = basis_z

    half_w = core.mm_to_ft(spec["width"]) / 2.0
    half_h = core.mm_to_ft(spec["height"]) / 2.0
    depth = core.mm_to_ft(depth_mm)

    box = BoundingBoxXYZ()
    box.Transform = transform
    box.Min = XYZ(-half_w, -half_h, -depth)
    box.Max = XYZ(half_w, half_h, 0.0)
    return box, look


def set_far_clip(view, depth_mm):
    """Set the far clip explicitly rather than trusting the creation box's Z
    convention, and read it back."""
    ok = True
    try:
        active = view.get_Parameter(BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING)
        if active is not None and not active.IsReadOnly:
            active.Set(1)
    except Exception:
        ok = False
    try:
        offset = view.get_Parameter(BuiltInParameter.VIEWER_BOUND_OFFSET_FAR)
        if offset is not None and not offset.IsReadOnly:
            offset.Set(core.mm_to_ft(depth_mm))
            read = core.ft_to_mm(offset.AsDouble())
            if abs(read - float(depth_mm)) > 1.0:
                ok = False
    except Exception:
        ok = False
    return ok


def view_looks_the_wrong_way(view, intended_look):
    """ViewDirection points towards the viewer, so it should be the negative
    of where the section is meant to look."""
    try:
        actual = view.ViewDirection
    except Exception:
        return False
    try:
        dot = (actual.X * intended_look.X + actual.Y * intended_look.Y +
               actual.Z * intended_look.Z)
    except Exception:
        return False
    return dot > 0.2


# WHERE THE CAMERA STANDS, as a direction out from the middle of the box.
#
# The Z is what says whether the view looks down on the callout or up at it
# from underneath, and it has to be POSITIVE: the camera stands above the box
# and looks down.  It was negative, which put the eye 30 metres below the slab
# looking up through it.
ORIENTATIONS = {
    "se_iso": (1.0, -1.0, 1.0),
    "sw_iso": (-1.0, -1.0, 1.0),
    "ne_iso": (1.0, 1.0, 1.0),
    "nw_iso": (-1.0, 1.0, 1.0),
}

# 35.264 degrees above the horizontal is the true isometric - the angle at
# which a cube's three visible faces come out equal - and is what (1, 1, 1)
# gives on its own.
ISOMETRIC_PITCH = 35.264


def orientation_vector(key, pitch_degrees=ISOMETRIC_PITCH):
    """The stand-off direction for a compass corner, at a given angle above
    the horizontal.  A steeper pitch looks more from overhead, a shallower one
    more from the side; either way it is from above."""
    base = ORIENTATIONS.get((key or "se_iso").strip().lower())
    if base is None:
        return None
    try:
        pitch = float(pitch_degrees)
    except Exception:
        pitch = ISOMETRIC_PITCH
    pitch = max(5.0, min(85.0, pitch))
    flat = math.sqrt(base[0] ** 2 + base[1] ** 2) or 1.0
    return (base[0], base[1], flat * math.tan(math.radians(pitch)))


def eye_point_mm(centre_mm, forward, back_mm=30000.0):
    """Where the camera stands so that it looks at `centre_mm`.

    The camera looks along -forward, so it stands off along +forward.  Pure
    arithmetic, kept out of orient_3d so it can be proved without a Revit view.
    """
    back = float(back_mm)
    return (centre_mm[0] + forward[0] * back,
            centre_mm[1] + forward[1] * back,
            centre_mm[2] + forward[2] * back)


def orient_3d(view3d, key, target=None, back_mm=30000.0,
              pitch_degrees=ISOMETRIC_PITCH):
    """Point a new 3D view at the callout from one of the four isometric
    corners.

    `target` is the middle of the section box, in model feet.  It matters:
    `SetOrientation` moves the view's target as well as its direction, so an
    eye left at the project origin aims the camera at the base point and the
    view comes up **empty** with the callout tens of metres off screen.  That
    is what "the 3D shows nothing" was.
    """
    key = (key or "se_iso").strip().lower()
    if key == "keep" or key not in ORIENTATIONS:
        return False
    try:
        from Autodesk.Revit.DB import ViewOrientation3D
        forward = orientation_vector(key, pitch_degrees)
        if forward is None:
            return False
        centre = target if target is not None else XYZ(0, 0, 0)
        stand = eye_point_mm(
            (core.ft_to_mm(centre.X), core.ft_to_mm(centre.Y), core.ft_to_mm(centre.Z)),
            forward, back_mm)
        eye = XYZ(core.mm_to_ft(stand[0]), core.mm_to_ft(stand[1]),
                  core.mm_to_ft(stand[2]))
        direction = XYZ(forward[0], forward[1], forward[2]).Normalize()
        up_rough = XYZ(0, 0, 1)
        right = direction.CrossProduct(up_rough)
        if right.GetLength() < 1e-6:
            return False
        up = right.CrossProduct(direction).Normalize()
        view3d.SetOrientation(ViewOrientation3D(eye, up, XYZ(-direction.X, -direction.Y, -direction.Z)))
        return True
    except Exception:
        return False


def box_centre(box):
    """The middle of a BoundingBoxXYZ, in model feet, transform included."""
    try:
        middle = XYZ((box.Min.X + box.Max.X) / 2.0,
                     (box.Min.Y + box.Max.Y) / 2.0,
                     (box.Min.Z + box.Max.Z) / 2.0)
        transform = box.Transform
        if transform is None:
            return middle
        return transform.OfPoint(middle)
    except Exception:
        return None


def cut_plane_offset_mm(view):
    """The view range's cut plane offset above its level, in millimetres.

    This is what says where the level really is: a plan's crop plane sits at
    its cut plane, and the crop region's Z is a model coordinate with nothing
    between it and the truth.  Subtract one from the other and the answer is
    the level's internal elevation, whatever the project's elevation base has
    done to `Level.Elevation`.
    """
    try:
        from Autodesk.Revit.DB import PlanViewPlane
        enum = getattr(PlanViewPlane, "CutPlane", None)
        if enum is None:
            return None
        return core.ft_to_mm(view.GetViewRange().GetOffset(enum))
    except Exception:
        return None


def view_range_mm(doc, view, source="Elevation"):
    """The callout's own view range, bottom and top, in model millimetres.

    This is what a plan actually shows, so it is the honest answer to "make
    the section box the same as the callout".  Each plane is a level plus an
    offset; a plane with no level (unlimited) gives nothing back and the
    caller falls back to the level rule.
    """
    try:
        from Autodesk.Revit.DB import PlanViewPlane
    except Exception:
        return None
    try:
        view_range = view.GetViewRange()
    except Exception:
        return None

    def plane(name):
        try:
            enum = getattr(PlanViewPlane, name, None)
            if enum is None:
                return None
            level_id = view_range.GetLevelId(enum)
            if level_id is None or core.eid_value(level_id) <= 0:
                return None            # unlimited, so it says nothing useful
            level = doc.GetElement(level_id)
            if level is None:
                return None
            base = level_model_z(level, source)
            if base is None:
                return None
            offset = view_range.GetOffset(enum)
            return core.ft_to_mm(base + offset)
        except Exception:
            return None

    top = plane("TopClipPlane")
    bottom = plane("ViewDepthPlane")
    if bottom is None:
        bottom = plane("BottomClipPlane")
    if top is None or bottom is None:
        return None
    if top <= bottom + 1.0:
        return None
    return (bottom, top)


def tighten_3d_crop(view3d, box, margin_mm=0.0):
    """Pull a 3D view's crop region in around its section box.

    The crop of a 3D view is measured in the view's own frame, and Revit hands
    that frame over on the crop box itself.  So the eight corners of the
    section box are pushed back through it and the crop is set to what comes
    out - which is the tight rectangle round the box, whatever direction the
    view is looking from.

    Returns the printed width and height in model millimetres, or None.
    """
    try:
        crop = view3d.CropBox
        frame = crop.Transform
        inverse = frame.Inverse
    except Exception:
        return None

    try:
        low, high = box.Min, box.Max
        box_frame = box.Transform
    except Exception:
        return None

    corners = []
    for x in (low.X, high.X):
        for y in (low.Y, high.Y):
            for z in (low.Z, high.Z):
                point = XYZ(x, y, z)
                try:
                    if box_frame is not None:
                        point = box_frame.OfPoint(point)
                except Exception:
                    pass
                try:
                    corners.append(inverse.OfPoint(point))
                except Exception:
                    continue
    if len(corners) < 8:
        return None

    margin = core.mm_to_ft(float(margin_mm or 0.0))
    xs = [point.X for point in corners]
    ys = [point.Y for point in corners]
    try:
        crop.Min = XYZ(min(xs) - margin, min(ys) - margin, crop.Min.Z)
        crop.Max = XYZ(max(xs) + margin, max(ys) + margin, crop.Max.Z)
        view3d.CropBox = crop
    except Exception:
        return None
    return (core.ft_to_mm(max(xs) - min(xs)) + 2.0 * float(margin_mm or 0.0),
            core.ft_to_mm(max(ys) - min(ys)) + 2.0 * float(margin_mm or 0.0))




def column_stack(cells, top_y, bottom, gap_mm, min_gap_mm=2.0):
    """Stack (width, height) boxes down a column from `top_y`.

    The gap is squeezed - down to `min_gap_mm` and no further - to get as many
    in above `bottom` as will go.  Views are never scaled to fit: a viewport
    shrunk to fit is a scale nobody asked for, so once the gap is at its
    minimum the rest simply carry on below the sheet and that is reported.

    Returns (places, the gap actually used, whether it overflowed).
    """
    cells = [(float(w), float(h)) for w, h in cells]
    if not cells:
        return [], float(gap_mm), False

    gap = float(gap_mm)
    floor = float(min_gap_mm)
    available = float(top_y) - float(bottom)
    total = sum([height for _w, height in cells])
    joints = len(cells) - 1

    if joints and total + joints * gap > available:
        gap = max(floor, (available - total) / float(joints))

    places = []
    y = float(top_y)
    for width, height in cells:
        places.append((None, y - height, width, height))   # x filled in by the caller
        y -= (height + gap)

    lowest = min([place[1] for place in places])
    return places, gap, lowest < float(bottom) - 0.001


def two_column_layout(usable, callout, three_d, x_cells, y_cells,
                      gap_mm, section_gap_mm, min_gap_mm=2.0):
    """The whole sheet: the plan and the 3D across the top, then the X sections
    down the left and the Y sections down the right.

    The two columns are as wide as whatever has to go in them, and the 3D sits
    at the head of the right hand one, so a Y section lines up under it.  Each
    is (x, y, width, height) in sheet millimetres from the bottom left; `None`
    where there is nothing to place.
    """
    left, bottom, width, height = [float(value) for value in usable]
    gap = float(gap_mm)
    top_y = bottom + height

    callout_w, callout_h = (float(callout[0]), float(callout[1])) if callout else (0.0, 0.0)
    three_w, three_h = (float(three_d[0]), float(three_d[1])) if three_d else (0.0, 0.0)

    widest_x = max([cell[0] for cell in x_cells]) if x_cells else 0.0
    widest_y = max([cell[0] for cell in y_cells]) if y_cells else 0.0

    left_column = max(callout_w, widest_x)
    right_x = left + left_column + gap if (three_d or y_cells) else left

    out = {
        "callout": (left, top_y - callout_h, callout_w, callout_h) if callout else None,
        "3d": (right_x, top_y - three_h, three_w, three_h) if three_d else None,
        "x": [],
        "y": [],
        "overflow": False,
        "too_wide": (right_x + max(three_w, widest_y)) > left + width + 0.001,
    }

    row_height = max(callout_h, three_h)
    column_top = top_y - row_height - gap if row_height else top_y

    for key, cells, column_x in (("x", x_cells, left), ("y", y_cells, right_x)):
        places, _gap_used, over = column_stack(cells, column_top, bottom,
                                               section_gap_mm, min_gap_mm)
        out[key] = [(column_x, place[1], place[2], place[3]) for place in places]
        out["overflow"] = out["overflow"] or over

    return out


