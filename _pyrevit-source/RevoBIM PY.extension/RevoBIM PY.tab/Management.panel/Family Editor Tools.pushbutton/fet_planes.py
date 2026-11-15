# =========================================================================
# Family Editor Tools - standard reference plane layouts
#
# Pure data and pure geometry.  No Revit API and no WPF, so the positions,
# the dimension list and the preview drawing are all plain functions that
# can be run against a table of cases on the bench.  fet_ops turns the
# positions into reference planes; fet_window draws the same positions as
# the preview, so the picture and the model cannot disagree.
# =========================================================================

# ELEM_REFERENCE_PLANE_IS_REFERENCE is an integer parameter, not an enum
# the API hands you.  These are its values.
NOT_A_REFERENCE = 0
STRONG = 1
WEAK = 2
LEFT = 3
CENTRE_LR = 4
RIGHT = 5
FRONT = 6
CENTRE_FB = 7
BACK = 8
BOTTOM = 9
CENTRE_ELEV = 10
TOP = 11

REF_NAMES = {
    NOT_A_REFERENCE: u"Not a Reference",
    STRONG: u"Strong Reference",
    WEAK: u"Weak Reference",
    LEFT: u"Left",
    CENTRE_LR: u"Center (Left/Right)",
    RIGHT: u"Right",
    FRONT: u"Front",
    CENTRE_FB: u"Center (Front/Back)",
    BACK: u"Back",
    BOTTOM: u"Bottom",
    CENTRE_ELEV: u"Center (Elevation)",
    TOP: u"Top",
}

# Size keys the offsets are written against.
#   w  width     (along X)
#   d  depth     (along Y)
#   h  height    (along Z)
#   c  clearance (along Y, in front)


def resolve_offset(terms, sizes):
    u"""terms is a list of (factor, size key or None).  Returns millimetres."""
    total = 0.0
    for factor, key in terms:
        if key is None:
            total += float(factor)
        else:
            total += float(factor) * float(sizes.get(key, 0.0))
    return total


LAYOUTS = [
    {
        u"key": u"centred_box",
        u"name": u"Centred box - Width and Depth",
        u"view": u"plan",
        u"note": u"The everyday equipment setting out. Four faces, both "
                 u"centres, both runs equalised about the origin.",
        u"planes": [
            {u"name": u"Center (Left/Right)", u"axis": u"x", u"off": [(0.0, None)], u"ref": CENTRE_LR},
            {u"name": u"Left", u"axis": u"x", u"off": [(-0.5, u"w")], u"ref": LEFT},
            {u"name": u"Right", u"axis": u"x", u"off": [(0.5, u"w")], u"ref": RIGHT},
            {u"name": u"Center (Front/Back)", u"axis": u"y", u"off": [(0.0, None)], u"ref": CENTRE_FB},
            {u"name": u"Front", u"axis": u"y", u"off": [(-0.5, u"d")], u"ref": FRONT},
            {u"name": u"Back", u"axis": u"y", u"off": [(0.5, u"d")], u"ref": BACK},
        ],
        u"dims": [
            {u"kind": u"eq", u"axis": u"x", u"planes": [u"Left", u"Center (Left/Right)", u"Right"], u"slot": 0},
            {u"kind": u"label", u"axis": u"x", u"planes": [u"Left", u"Right"], u"param": u"w", u"slot": 1},
            {u"kind": u"eq", u"axis": u"y", u"planes": [u"Front", u"Center (Front/Back)", u"Back"], u"slot": 0},
            {u"kind": u"label", u"axis": u"y", u"planes": [u"Front", u"Back"], u"param": u"d", u"slot": 1},
        ],
    },
    {
        u"key": u"centred_front_origin",
        u"name": u"Centred width, front on the origin",
        u"view": u"plan",
        u"note": u"For anything that sits against a wall. Width equalised "
                 u"about the centre, depth measured back from the origin.",
        u"planes": [
            {u"name": u"Center (Left/Right)", u"axis": u"x", u"off": [(0.0, None)], u"ref": CENTRE_LR},
            {u"name": u"Left", u"axis": u"x", u"off": [(-0.5, u"w")], u"ref": LEFT},
            {u"name": u"Right", u"axis": u"x", u"off": [(0.5, u"w")], u"ref": RIGHT},
            {u"name": u"Front", u"axis": u"y", u"off": [(0.0, None)], u"ref": FRONT},
            {u"name": u"Back", u"axis": u"y", u"off": [(1.0, u"d")], u"ref": BACK},
        ],
        u"dims": [
            {u"kind": u"eq", u"axis": u"x", u"planes": [u"Left", u"Center (Left/Right)", u"Right"], u"slot": 0},
            {u"kind": u"label", u"axis": u"x", u"planes": [u"Left", u"Right"], u"param": u"w", u"slot": 1},
            {u"kind": u"label", u"axis": u"y", u"planes": [u"Front", u"Back"], u"param": u"d", u"slot": 0},
        ],
    },
    {
        u"key": u"corner_origin",
        u"name": u"Corner on the origin",
        u"view": u"plan",
        u"note": u"Insertion point at the front left corner. No equality, "
                 u"so the family grows away from its origin.",
        u"planes": [
            {u"name": u"Left", u"axis": u"x", u"off": [(0.0, None)], u"ref": LEFT},
            {u"name": u"Right", u"axis": u"x", u"off": [(1.0, u"w")], u"ref": RIGHT},
            {u"name": u"Front", u"axis": u"y", u"off": [(0.0, None)], u"ref": FRONT},
            {u"name": u"Back", u"axis": u"y", u"off": [(1.0, u"d")], u"ref": BACK},
        ],
        u"dims": [
            {u"kind": u"label", u"axis": u"x", u"planes": [u"Left", u"Right"], u"param": u"w", u"slot": 0},
            {u"kind": u"label", u"axis": u"y", u"planes": [u"Front", u"Back"], u"param": u"d", u"slot": 0},
        ],
    },
    {
        u"key": u"width_only",
        u"name": u"Width only, centred",
        u"view": u"plan",
        u"note": u"A single run equalised about the centre - trays, "
                 u"trunking, anything with no depth worth driving.",
        u"planes": [
            {u"name": u"Center (Left/Right)", u"axis": u"x", u"off": [(0.0, None)], u"ref": CENTRE_LR},
            {u"name": u"Left", u"axis": u"x", u"off": [(-0.5, u"w")], u"ref": LEFT},
            {u"name": u"Right", u"axis": u"x", u"off": [(0.5, u"w")], u"ref": RIGHT},
        ],
        u"dims": [
            {u"kind": u"eq", u"axis": u"x", u"planes": [u"Left", u"Center (Left/Right)", u"Right"], u"slot": 0},
            {u"kind": u"label", u"axis": u"x", u"planes": [u"Left", u"Right"], u"param": u"w", u"slot": 1},
        ],
    },
    {
        u"key": u"crosshair",
        u"name": u"Centre crosshair only",
        u"view": u"plan",
        u"note": u"The two centres and nothing else, named and set as "
                 u"references so a nested family has something to host to.",
        u"planes": [
            {u"name": u"Center (Left/Right)", u"axis": u"x", u"off": [(0.0, None)], u"ref": CENTRE_LR},
            {u"name": u"Center (Front/Back)", u"axis": u"y", u"off": [(0.0, None)], u"ref": CENTRE_FB},
        ],
        u"dims": [],
    },
    {
        u"key": u"height_elevation",
        u"name": u"Height - front elevation",
        u"view": u"elevation",
        u"note": u"Run this from a front or back elevation. Bottom on the "
                 u"reference level, top driven by Height.",
        u"planes": [
            {u"name": u"Bottom", u"axis": u"z", u"off": [(0.0, None)], u"ref": BOTTOM},
            {u"name": u"Center (Elevation)", u"axis": u"z", u"off": [(0.5, u"h")], u"ref": CENTRE_ELEV},
            {u"name": u"Top", u"axis": u"z", u"off": [(1.0, u"h")], u"ref": TOP},
        ],
        u"dims": [
            {u"kind": u"eq", u"axis": u"z", u"planes": [u"Bottom", u"Center (Elevation)", u"Top"], u"slot": 0},
            {u"kind": u"label", u"axis": u"z", u"planes": [u"Bottom", u"Top"], u"param": u"h", u"slot": 1},
        ],
    },
    {
        u"key": u"revolve_elevation",
        u"name": u"Revolve - front elevation",
        u"view": u"elevation",
        u"note": u"The setting out a revolve needs: the axis on the centre, "
                 u"a radius plane to sketch the profile against, and the "
                 u"bottom and top it runs between.",
        u"planes": [
            {u"name": u"Center (Left/Right)", u"axis": u"x", u"off": [(0.0, None)], u"ref": CENTRE_LR},
            {u"name": u"Radius", u"axis": u"x", u"off": [(1.0, u"r")], u"ref": RIGHT},
            {u"name": u"Bottom", u"axis": u"z", u"off": [(0.0, None)], u"ref": BOTTOM},
            {u"name": u"Top", u"axis": u"z", u"off": [(1.0, u"h")], u"ref": TOP},
        ],
        u"dims": [
            {u"kind": u"label", u"axis": u"x", u"planes": [u"Center (Left/Right)", u"Radius"], u"param": u"r", u"slot": 0},
            {u"kind": u"label", u"axis": u"z", u"planes": [u"Bottom", u"Top"], u"param": u"h", u"slot": 0},
        ],
    },
    {
        u"key": u"box_with_clearance",
        u"name": u"Centred box with a clearance zone",
        u"view": u"plan",
        u"note": u"The centred box plus a weak reference in front of it, "
                 u"driven by Clearance, for maintenance access.",
        u"planes": [
            {u"name": u"Center (Left/Right)", u"axis": u"x", u"off": [(0.0, None)], u"ref": CENTRE_LR},
            {u"name": u"Left", u"axis": u"x", u"off": [(-0.5, u"w")], u"ref": LEFT},
            {u"name": u"Right", u"axis": u"x", u"off": [(0.5, u"w")], u"ref": RIGHT},
            {u"name": u"Center (Front/Back)", u"axis": u"y", u"off": [(0.0, None)], u"ref": CENTRE_FB},
            {u"name": u"Front", u"axis": u"y", u"off": [(-0.5, u"d")], u"ref": FRONT},
            {u"name": u"Back", u"axis": u"y", u"off": [(0.5, u"d")], u"ref": BACK},
            {u"name": u"Clearance", u"axis": u"y", u"off": [(-0.5, u"d"), (-1.0, u"c")], u"ref": WEAK},
        ],
        u"dims": [
            {u"kind": u"eq", u"axis": u"x", u"planes": [u"Left", u"Center (Left/Right)", u"Right"], u"slot": 0},
            {u"kind": u"label", u"axis": u"x", u"planes": [u"Left", u"Right"], u"param": u"w", u"slot": 1},
            {u"kind": u"eq", u"axis": u"y", u"planes": [u"Front", u"Center (Front/Back)", u"Back"], u"slot": 0},
            {u"kind": u"label", u"axis": u"y", u"planes": [u"Front", u"Back"], u"param": u"d", u"slot": 1},
            {u"kind": u"label", u"axis": u"y", u"planes": [u"Clearance", u"Front"], u"param": u"c", u"slot": 2},
        ],
    },
]

LAYOUT_BY_KEY = {}
for _layout in LAYOUTS:
    LAYOUT_BY_KEY[_layout[u"key"]] = _layout


# The view a layout has to be set out in, and the names Revit's own family
# templates give it.  Metric and imperial templates spell the plan
# differently, which is why it is a list rather than one name.
LAYOUT_VIEW_NAMES = {
    u"plan": (u"Ref. Level", u"Ref Level", u"Reference Level", u"Level 1",
              u"Lower Ref. Level"),
    u"elevation": (u"Front", u"Front Elevation", u"Back"),
}


def view_names_for(key):
    return LAYOUT_VIEW_NAMES.get(get_layout(key)[u"view"], ())


def layout_keys():
    return [item[u"key"] for item in LAYOUTS]


def get_layout(key):
    return LAYOUT_BY_KEY.get(key) or LAYOUTS[0]


def layout_index(key):
    for index, item in enumerate(LAYOUTS):
        if item[u"key"] == key:
            return index
    return 0


def step_layout(key, delta):
    u"""Cycle the layout list, wrapping at both ends."""
    index = (layout_index(key) + int(delta)) % len(LAYOUTS)
    return LAYOUTS[index][u"key"]


def plane_positions(key, sizes):
    u"""[(name, axis, offset in mm, reference type)] for the layout."""
    out = []
    for spec in get_layout(key)[u"planes"]:
        out.append((spec[u"name"], spec[u"axis"],
                    resolve_offset(spec[u"off"], sizes), spec[u"ref"]))
    return out


def plane_offset_map(key, sizes):
    out = {}
    for name, axis, offset, ref in plane_positions(key, sizes):
        out[name] = (axis, offset)
    return out


def dimension_specs(key, sizes):
    u"""[(kind, axis, [(plane name, offset)], param key, slot)] in order."""
    offsets = plane_offset_map(key, sizes)
    out = []
    for spec in get_layout(key)[u"dims"]:
        pairs = []
        ok = True
        for name in spec[u"planes"]:
            if name not in offsets:
                ok = False
                break
            pairs.append((name, offsets[name][1]))
        if not ok:
            continue
        # A dimension has to read left to right / bottom to top or Revit
        # takes the segments in the order handed to it.
        pairs.sort(key=lambda pair: pair[1])
        out.append((spec[u"kind"], spec[u"axis"], pairs,
                    spec.get(u"param"), spec.get(u"slot", 0)))
    return out


def params_used(key):
    u"""Which of w / d / h / c the layout actually drives."""
    out = []
    for spec in get_layout(key)[u"dims"]:
        name = spec.get(u"param")
        if name and name not in out:
            out.append(name)
    return out


# =========================================================================
# The preview
#
# Built from the same plane positions the model gets, in a 0..1 box with
# y running DOWN the way a canvas does, so the drawing and the model can
# never drift apart.
# =========================================================================

PREVIEW_MARGIN = 0.13


def _extent(values, fallback):
    if not values:
        return (-fallback, fallback)
    low = min(values)
    high = max(values)
    if abs(high - low) < 1e-9:
        return (low - fallback, high + fallback)
    return (low, high)


def preview_items(key, sizes=None):
    u"""Return drawing items in a 0..1 box:
        (u'plane', x1, y1, x2, y2, style, label)
        (u'dim',   x1, y1, x2, y2, text, kind)
        (u'tick',  x, y)
        (u'origin', x, y)
    style is u'face', u'centre' or u'weak'; kind is u'eq' or u'label'.
    """
    if sizes is None:
        sizes = {u"w": 600.0, u"d": 400.0, u"h": 500.0, u"c": 300.0,
                 u"r": 300.0}
    layout = get_layout(key)
    elevation = layout[u"view"] == u"elevation"
    planes = plane_positions(key, sizes)

    across = [off for name, axis, off, ref in planes if axis == u"x"]
    if elevation:
        up = [off for name, axis, off, ref in planes if axis == u"z"]
        if not across:
            across = [-0.5 * sizes.get(u"w", 600.0), 0.5 * sizes.get(u"w", 600.0)]
    else:
        up = [off for name, axis, off, ref in planes if axis == u"y"]

    span = max(sizes.get(u"w", 600.0), sizes.get(u"d", 400.0),
               sizes.get(u"r", 0.0) * 2.0, 1.0)
    x_low, x_high = _extent(across, span * 0.5)
    y_low, y_high = _extent(up, span * 0.5)

    # Leave room for the dimension runs outside the planes.
    pad_x = max(x_high - x_low, 1.0) * 0.30
    pad_y = max(y_high - y_low, 1.0) * 0.30
    x_low -= pad_x
    x_high += pad_x
    y_low -= pad_y
    y_high += pad_y

    scale = (1.0 - 2.0 * PREVIEW_MARGIN) / max(x_high - x_low, y_high - y_low, 1e-6)
    off_x = PREVIEW_MARGIN + ((1.0 - 2.0 * PREVIEW_MARGIN)
                              - (x_high - x_low) * scale) * 0.5
    off_y = PREVIEW_MARGIN + ((1.0 - 2.0 * PREVIEW_MARGIN)
                              - (y_high - y_low) * scale) * 0.5

    def to_x(value):
        return off_x + (value - x_low) * scale

    def to_y(value):
        # Canvas y runs down, model y and z run up.
        return 1.0 - (off_y + (value - y_low) * scale)

    items = []
    style_of = {CENTRE_LR: u"centre", CENTRE_FB: u"centre",
                CENTRE_ELEV: u"centre", WEAK: u"weak",
                NOT_A_REFERENCE: u"weak"}

    for name, axis, offset, ref in planes:
        style = style_of.get(ref, u"face")
        if axis == u"x":
            x = to_x(offset)
            items.append((u"plane", x, to_y(y_low), x, to_y(y_high), style, name))
        else:
            y = to_y(offset)
            items.append((u"plane", to_x(x_low), y, to_x(x_high), y, style, name))

    step = max(x_high - x_low, y_high - y_low) * 0.085
    for kind, axis, pairs, param, slot in dimension_specs(key, sizes):
        text = u"EQ" if kind == u"eq" else {
            u"w": u"Width", u"d": u"Depth",
            u"h": u"Height", u"c": u"Clearance",
            u"r": u"Radius"}.get(param, u"")
        low = pairs[0][1]
        high = pairs[-1][1]
        if axis == u"x":
            line_y = y_low + step * (slot + 0.8)
            items.append((u"dim", to_x(low), to_y(line_y),
                          to_x(high), to_y(line_y), text, kind))
            if kind == u"eq":
                for name, value in pairs:
                    items.append((u"tick", to_x(value), to_y(line_y)))
        else:
            line_x = x_low + step * (slot + 0.8)
            items.append((u"dim", to_x(line_x), to_y(low),
                          to_x(line_x), to_y(high), text, kind))
            if kind == u"eq":
                for name, value in pairs:
                    items.append((u"tick", to_x(line_x), to_y(value)))

    items.append((u"origin", to_x(0.0), to_y(0.0)))
    return items


def preview_in_bounds(items, slack=0.001):
    u"""Every drawn point sits inside the 0..1 box.  The preview is scaled
    to fit, so anything outside means the fit is wrong."""
    for item in items:
        if item[0] == u"plane" or item[0] == u"dim":
            values = [item[1], item[2], item[3], item[4]]
        else:
            values = [item[1], item[2]]
        for value in values:
            if value < -slack or value > 1.0 + slack:
                return False
    return True
