# -*- coding: utf-8 -*-
"""Duct Accessory Resize - version, settings, palettes and every rule.

Nothing in here touches .NET or Revit, so every function runs under plain
CPython on the bench. The Revit side hands in plain dicts and gets decisions
back.
"""

import io
import os
import re
import datetime

__version__ = "1.3.0"

TOOL_NAME = u"Duct Accessory Resize"
SETTINGS_FILE = u"duct_accessory_resize.txt"
DEBUG_FILE = u"duct_accessory_resize_debug.txt"
ERROR_FILE = u"duct_accessory_resize_last_error.txt"
SETTINGS_VERSION = 1

MM_PER_FOOT = 304.8
TOLERANCE_MM = 0.5
MIN_SIZE_MM = 1.0
MAX_SIZE_MM = 10000.0
MAX_ROWS_DRAWN = 1500

SHAPE_RECT = u"rect"
SHAPE_ROUND = u"round"

# the dimensions each shape resizes, in the order they are shown
DIMS = {
    SHAPE_RECT: (u"w", u"h"),
    SHAPE_ROUND: (u"d",),
}
DIM_NAMES = {u"w": u"Width", u"h": u"Height", u"d": u"Diameter"}
# the family kinds whose size comes from parameters the user names, each
# with its own setting per dimension - an air terminal rarely carries the
# same parameter names as a damper
KIND_ACC = u"accessory"
KIND_TERM = u"terminal"
FAMILY_KINDS = (KIND_ACC, KIND_TERM)
KIND_LABEL = {KIND_ACC: u"Duct Accessory", KIND_TERM: u"Air Terminal"}
KIND_WORD = {KIND_ACC: u"duct accessory", KIND_TERM: u"air terminal"}
KIND_INCLUDE = {KIND_ACC: u"include_accessories",
                KIND_TERM: u"include_terminals"}

DIM_SETTING = {u"w": u"acc_width", u"h": u"acc_height", u"d": u"acc_diameter"}
TERM_SETTING = {u"w": u"term_width", u"h": u"term_height",
                u"d": u"term_diameter"}
KIND_SETTING = {KIND_ACC: DIM_SETTING, KIND_TERM: TERM_SETTING}

DEFAULTS = {
    u"settings_version": u"1",
    u"shape": SHAPE_RECT,
    u"acc_width": u"",
    u"acc_height": u"",
    u"acc_diameter": u"",
    u"term_width": u"",
    u"term_height": u"",
    u"term_diameter": u"",
    u"include_ducts": u"1",
    u"include_accessories": u"1",
    u"include_terminals": u"1",
    u"type_mode": u"switch",
    u"theme": u"auto",
    u"debug": u"1",
    u"new_w": u"",
    u"new_h": u"",
    u"new_d": u"",
}

# version -> keys whose meaning changed and must go back to the default
MIGRATIONS = {}

PARAM_CANDIDATES = {
    KIND_ACC: {
        u"w": (u"Duct Width", u"Width", u"BGL_Duct Width", u"BGL_Width", u"W"),
        u"h": (u"Duct Height", u"Height", u"BGL_Duct Height", u"BGL_Height",
               u"H"),
        u"d": (u"Duct Diameter", u"Diameter", u"BGL_Duct Diameter",
               u"BGL_Diameter", u"D"),
    },
    # an air terminal is sized at its neck, so the neck names come first
    KIND_TERM: {
        u"w": (u"Neck Width", u"Duct Width", u"BGL_Neck Width",
               u"BGL_Duct Width", u"Width", u"BGL_Width"),
        u"h": (u"Neck Height", u"Duct Height", u"BGL_Neck Height",
               u"BGL_Duct Height", u"Height", u"BGL_Height"),
        u"d": (u"Neck Diameter", u"Duct Diameter", u"BGL_Neck Diameter",
               u"BGL_Duct Diameter", u"Diameter", u"BGL_Diameter"),
    },
}
PARAM_KEYWORD = {u"w": u"width", u"h": u"height", u"d": u"diameter"}
# names containing these are never a size, even if they contain "width"
PARAM_NOT_SIZE = (u"offset", u"elevation", u"length", u"insulation",
                  u"lining", u"radius", u"clearance", u"access")

THEME_CYCLE = (u"auto", u"dark", u"light")

PALETTES = {
    # Revit's own dark UI: a blue-grey slate, not a near-black. Sampled
    # from Revit 2024's project browser and shared with the rest of the
    # RevoBIM suite - see the house theme reference.
    u"dark": {
        u"Bg": u"#3B4453", u"Card": u"#333B49", u"Field": u"#2C3440",
        u"Bar": u"#222933", u"Edge": u"#515C6B", u"WindowEdge": u"#5C6878",
        u"Text": u"#F5F5F5", u"Muted": u"#9DA5B0", u"Blue": u"#4FA3E3",
        u"Orange": u"#E8912D", u"Green": u"#3FA75A",
        u"GreenHover": u"#4EC06D", u"Red": u"#D9534F", u"Select": u"#2D5B80",
        u"Hover": u"#414B5A", u"OrangeWash": u"#665341",
        u"GreenWash": u"#365942", u"RedWash": u"#61424B",
        u"OnAccent": u"#FFFFFF",
    },
    u"light": {
        u"Bg": u"#F3F3F5", u"Card": u"#FFFFFF", u"Field": u"#FAFAFB",
        u"Bar": u"#E6E6EA", u"Edge": u"#C9C9CF", u"WindowEdge": u"#B5B5BC",
        u"Text": u"#1E1E22", u"Muted": u"#6A6A72", u"Blue": u"#1B72BE",
        u"Orange": u"#B96A12", u"Green": u"#2E8546",
        u"GreenHover": u"#379B53", u"Red": u"#C0392B", u"Select": u"#CFE3F5",
        u"Hover": u"#ECECF0", u"OrangeWash": u"#FBEBD6",
        u"GreenWash": u"#DDF1E2", u"RedWash": u"#F8DCDA",
        u"OnAccent": u"#FFFFFF",
    },
}

# row states, and the palette key each one paints with
STATE_WASH = {
    u"orange": u"OrangeWash", u"green": u"GreenWash", u"red": u"RedWash",
    u"idle": u"Card",
}
STATE_TEXT = {
    u"orange": u"Orange", u"green": u"Green", u"red": u"Red",
    u"idle": u"Muted",
}

CLICK_GAP_MIN_MS = 250
CLICK_GAP_MAX_MS = 2000


# ============================================================
# small helpers
# ============================================================

def to_text(value):
    if value is None:
        return u""
    try:
        return u"{0}".format(value)
    except Exception:
        try:
            return unicode(value)  # noqa - IronPython 2.7
        except Exception:
            return u""


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026; .Value is the
    Int64 that replaced it. Always go through here."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def mm_to_ft(mm):
    return float(mm) / MM_PER_FOOT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FOOT


def same_mm(a, b):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= TOLERANCE_MM


def fmt_mm(value):
    if value is None:
        return u"-"
    value = float(value)
    rounded = round(value)
    if abs(value - rounded) < 0.05:
        return u"{0}".format(int(rounded))
    return u"{0:.1f}".format(value)


def fmt_size(shape, sizes):
    """600 x 400 for a rectangle, \u00d8300 for a circle; a dimension that
    could not be read shows as a dash."""
    sizes = sizes or {}
    if shape == SHAPE_ROUND:
        return u"\u00d8" + fmt_mm(sizes.get(u"d"))
    return u"{0} x {1}".format(fmt_mm(sizes.get(u"w")), fmt_mm(sizes.get(u"h")))


def parse_mm(text):
    """A typed size. Returns (value, error). Blank is (None, None): keep the
    dimension as it is. Accepts 300, 300mm, 300.5 and 300,5."""
    text = to_text(text).strip().lower()
    if not text:
        return None, None
    if text.endswith(u"mm"):
        text = text[:-2].strip()
    text = text.replace(u",", u".")
    try:
        value = float(text)
    except Exception:
        return None, u"not a number"
    if value < MIN_SIZE_MM:
        return None, u"must be more than 0"
    if value > MAX_SIZE_MM:
        return None, u"over {0}mm".format(int(MAX_SIZE_MM))
    return value, None


def parse_new_sizes(shape, texts):
    """texts is {dim: typed text}. Returns (new, errors) where new only holds
    the dimensions the user typed, and errors is {dim: message}."""
    new, errors = {}, {}
    for dim in DIMS[shape]:
        value, error = parse_mm(texts.get(dim, u""))
        if error:
            errors[dim] = error
        elif value is not None:
            new[dim] = value
    return new, errors


def target_sizes(shape, current, new):
    """What the element should end up as: the typed value where there is
    one, the current one where the box was left blank."""
    out = {}
    for dim in DIMS[shape]:
        if dim in new:
            out[dim] = new[dim]
        else:
            out[dim] = (current or {}).get(dim)
    return out


def sizes_match(shape, a, b):
    for dim in DIMS[shape]:
        if not same_mm((a or {}).get(dim), (b or {}).get(dim)):
            return False
    return True


def summarise(shape, rows):
    """'600 x 400 (9), 500 x 300 (2)' - the current sizes of the rows given,
    most common first."""
    counts, order = {}, []
    for row in rows:
        label = fmt_size(shape, row.get(u"current"))
        if label not in counts:
            counts[label] = 0
            order.append(label)
        counts[label] += 1
    # the key reads a copy: a list being sorted is empty while it sorts
    first_seen = list(order)
    ranked = sorted(order, key=lambda k: (-counts[k], first_seen.index(k)))
    return u", ".join(u"{0} ({1})".format(k, counts[k]) for k in ranked)


def counts_in_summary(state, note):
    """The current-size line describes what can actually be resized: rows
    that will change, are already right, or are waiting for a size - not
    red rows and not a category switched off."""
    if state in (u"orange", u"green"):
        return True
    return state == u"idle" and note == u"enter a new size"


def shape_word(shape):
    return u"Circular" if shape == SHAPE_ROUND else u"Rectangular"


# ============================================================
# the rule for one row
# ============================================================

def row_problems(row, shape):
    """Why a row cannot be resized in this shape, or an empty list.
    row['kind'] is duct or accessory; row['el_shape'] is rect, round, oval
    or None; row['sources'] is {dim: (where, writable)} for accessories."""
    problems = list(row.get(u"read_problems") or [])
    kind = row.get(u"kind")
    if kind == u"duct":
        el_shape = row.get(u"el_shape")
        if el_shape == u"oval":
            problems.append(u"oval duct - not resized by this tool")
        elif el_shape and el_shape != shape:
            problems.append(u"{0} duct - switch the tool to {1}".format(
                u"round" if el_shape == SHAPE_ROUND else u"rectangular",
                shape_word(el_shape)))
    elif kind in FAMILY_KINDS:
        clash = param_clash(row.get(u"param_names") or {}, shape)
        if clash:
            problems.append(clash)
            return problems
        sources = row.get(u"sources") or {}
        for dim in DIMS[shape]:
            src = sources.get(dim)
            name = (row.get(u"param_names") or {}).get(dim, u"")
            if not name:
                problems.append(u"choose the {0} parameter".format(
                    DIM_NAMES[dim]))
            elif src is None:
                problems.append(u"no {0} parameter '{1}'".format(
                    DIM_NAMES[dim], name))
            elif not src[1]:
                problems.append(u"{0} is read-only (formula or connector "
                                u"driven)".format(DIM_NAMES[dim]))
    return problems


def row_status(row, shape, new, include_ducts=True, include_accessories=True,
               include_terminals=True):
    """(state, note) for one row: red cannot be done, idle nothing to do
    yet, green already that size, orange will change."""
    result = row.get(u"result")
    if result:
        return result
    kind = row.get(u"kind")
    if kind == u"duct" and not include_ducts:
        return u"idle", u"ducts switched off"
    if kind == KIND_ACC and not include_accessories:
        return u"idle", u"duct accessories switched off"
    if kind == KIND_TERM and not include_terminals:
        return u"idle", u"air terminals switched off"
    problems = row_problems(row, shape)
    if problems:
        return u"red", u"; ".join(problems)
    if not new:
        return u"idle", u"enter a new size"
    current = row.get(u"current") or {}
    target = target_sizes(shape, current, new)
    if sizes_match(shape, current, target):
        return u"green", u"already this size"
    return u"orange", u"{0} -> {1}".format(fmt_size(shape, current),
                                           fmt_size(shape, target))


# ============================================================
# parameters
# ============================================================

def pick_default(available, dim, kind=KIND_ACC):
    """The parameter to offer first for a dimension: an exact name from the
    candidate list, then anything carrying the keyword that is not an
    offset, length or similar."""
    lowered = dict((to_text(n).lower(), n) for n in available)
    for cand in PARAM_CANDIDATES[kind][dim]:
        hit = lowered.get(cand.lower())
        if hit is not None:
            return hit
    word = PARAM_KEYWORD[dim]
    for name in sorted(available, key=lambda n: (len(n), n.lower())):
        low = to_text(name).lower()
        if word in low and not any(bad in low for bad in PARAM_NOT_SIZE):
            return name
    return u""


def is_size_spec(type_id):
    """Offer only parameters that can hold a size: lengths and duct sizes.
    An unreadable spec is let through rather than hiding a parameter."""
    text = to_text(type_id).lower()
    if not text:
        return True
    return u":length" in text or u"ductsize" in text


def param_clash(names, shape):
    """Two dimensions pointed at one parameter write both sizes into it -
    v1.0.0 put 625 then 450 into BGL_Duct Width and the damper could never
    match its ducts. names is {dim: parameter name}."""
    seen = {}
    for dim in DIMS[shape]:
        name = to_text(names.get(dim, u"")).strip()
        if not name:
            continue
        if name.lower() in seen:
            return u"{0} and {1} both use '{2}' - pick a different " \
                   u"parameter for {1}".format(DIM_NAMES[seen[name.lower()]],
                                               DIM_NAMES[dim], name)
        seen[name.lower()] = dim
    return u""


def settings_names(settings, kind=KIND_ACC):
    return dict((dim, to_text(settings.get(key, u"")))
                for dim, key in KIND_SETTING[kind].items())


def all_clashes(settings, shape):
    """The clash message for each family kind that is switched on."""
    out = {}
    for kind in FAMILY_KINDS:
        if not flag(settings, KIND_INCLUDE[kind]):
            continue
        message = param_clash(settings_names(settings, kind), shape)
        if message:
            out[kind] = u"{0}: {1}".format(KIND_LABEL[kind], message)
    return out


def search_list(names, current, text):
    """What a parameter dropdown shows while its search box has text in it.
    Searching only filters - it never changes the chosen parameter, so the
    current one stays at the top even when it does not match. v1.0.0
    selected the first match as you typed, which is how Height ended up on
    BGL_Duct Width. Returns (shown, matched)."""
    shown, matched = filter_names(names, text)
    if current and current not in shown:
        shown = [current] + shown
    return shown, matched


def filter_names(names, text):
    """Keyword search: every word typed must appear. Returns (list, matched)
    - with no match the full list comes back rather than an empty one."""
    words = [w for w in to_text(text).lower().split() if w]
    if not words:
        return list(names), True
    hits = [n for n in names if all(w in to_text(n).lower() for w in words)]
    if not hits:
        return list(names), False
    return hits, True


# ============================================================
# type names, for type-sized families
# ============================================================

RECT_RX = re.compile(u"(\\d+(?:\\.\\d+)?)\\s*[xX\u00d7]\\s*(\\d+(?:\\.\\d+)?)")
ROUND_RX = re.compile(u"(\u00d8\\s*\\d+(?:\\.\\d+)?)"
                      u"|(\\b\\d+(?:\\.\\d+)?\\s*(?:mm\\s*)?dia\\b\\.?)",
                      re.IGNORECASE)


def size_label(shape, target):
    if shape == SHAPE_ROUND:
        return u"\u00d8" + fmt_mm(target.get(u"d"))
    return u"{0}x{1}".format(fmt_mm(target.get(u"w")), fmt_mm(target.get(u"h")))


def _last_span(rx, text):
    span = None
    for m in rx.finditer(text):
        span = m.span()
    return span


def strip_size(shape, name):
    """The type name with its size token taken out - used to recognise two
    types as the same thing in different sizes."""
    name = to_text(name)
    rx = ROUND_RX if shape == SHAPE_ROUND else RECT_RX
    out = rx.sub(u"", name)
    return re.sub(u"\\s+", u" ", out).strip(u" -_")


def type_name_for(shape, base_name, target):
    """The name a new size of a type gets: its size token swapped for the
    new one, or the new size appended where it carried none."""
    base_name = to_text(base_name)
    label = size_label(shape, target)
    rx = ROUND_RX if shape == SHAPE_ROUND else RECT_RX
    span = _last_span(rx, base_name)
    if span is not None:
        return base_name[:span[0]] + label + base_name[span[1]:]
    return (base_name + u" " + label).strip()


def unique_name(name, taken):
    taken_low = set(to_text(t).lower() for t in taken)
    if name.lower() not in taken_low:
        return name
    n = 2
    while True:
        cand = u"{0} ({1})".format(name, n)
        if cand.lower() not in taken_low:
            return cand
        n += 1


# ============================================================
# batching - try everything together, halve what Revit refuses
# ============================================================

# ============================================================
# connections - detached round the resize, then put back
# ============================================================

RECONNECT_TOL_MM = 10.0


def point_key(point):
    return tuple(round(float(v) * MM_PER_FOOT, 0) for v in point)


def pair_key(id_a, point_a, id_b, point_b):
    """One key for a connection whichever end it was found from."""
    ends = sorted([(id_a, point_key(point_a)), (id_b, point_key(point_b))])
    return tuple(ends)


def distance_mm(a, b):
    return (sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5
            * MM_PER_FOOT)


def nearest(points, target, tolerance_mm=RECONNECT_TOL_MM):
    """Index of the point nearest target within tolerance, or None."""
    best, best_d = None, None
    for index, point in enumerate(points):
        d = distance_mm(point, target)
        if best_d is None or d < best_d:
            best, best_d = index, d
    if best_d is None or best_d > tolerance_mm:
        return None
    return best


def unique_messages(messages):
    out = []
    for message in messages:
        if message not in out:
            out.append(message)
    return out


def run_batches(items, attempt, log=None):
    """attempt(chunk) -> (ok, message) commits the chunk or rolls it back.
    Everything is tried together first, because neighbours resized one at a
    time leave fittings half old and half new between steps. A refused chunk
    is halved until the element at fault is on its own; refused elements
    get one more go at the end, since resized neighbours can unblock them.
    Returns (accepted, refused) - refused is {item: message}."""
    accepted, refused = [], {}

    def go(chunk):
        if not chunk:
            return
        ok, message = attempt(list(chunk))
        if log is not None:
            log.add(u"batch of {0}: {1}{2}", len(chunk),
                    u"committed" if ok else u"refused",
                    u"" if ok else u" - " + to_text(message))
        if ok:
            accepted.extend(chunk)
            return
        if len(chunk) == 1:
            refused[chunk[0]] = to_text(message) or u"refused by Revit"
            return
        mid = len(chunk) // 2
        go(chunk[:mid])
        go(chunk[mid:])

    go(list(items))
    for item in list(refused.keys()):
        ok, message = attempt([item])
        if log is not None:
            log.add(u"retry {0}: {1}", item, u"committed" if ok else u"refused")
        if ok:
            accepted.append(item)
            del refused[item]
    return accepted, refused


# ============================================================
# theme
# ============================================================

def next_theme(mode):
    mode = to_text(mode).lower()
    if mode not in THEME_CYCLE:
        return THEME_CYCLE[0]
    return THEME_CYCLE[(THEME_CYCLE.index(mode) + 1) % len(THEME_CYCLE)]


def colour_is_dark(red, green, blue):
    """Relative luminance of Revit's canvas colour."""
    lum = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return lum < 128


def resolve_theme(mode, canvas_dark):
    """auto follows the canvas; a canvas that could not be read is dark,
    which is the house default."""
    mode = to_text(mode).lower()
    if mode == u"dark" or mode == u"light":
        return mode
    if canvas_dark is None:
        return u"dark"
    return u"dark" if canvas_dark else u"light"


def theme_chip_text(mode, resolved):
    if mode == u"auto":
        return u"Auto \u00b7 " + resolved.capitalize()
    return resolved.capitalize()


# ============================================================
# shrink to taskbar - the drawer arithmetic
# ============================================================

DRAWER_MS = 280.0
DRAWER_TICK_MS = 15.0
DRAWER_GAP = 4.0
DRAWER_BAR_FLOOR = 28.0
DRAWER_CHROME = 2.0


def ease(p):
    """1-(1-p)^3 - away fast, settling in. The slide is eased by hand on a
    timer rather than by a Storyboard: an animation holds its end value and
    outranks every later assignment, so a window whose Top and Height were
    animated can never be moved or resized again unless the animation is
    released. Easing by hand leaves nothing to release."""
    p = float(p)
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return 1.0 - (1.0 - p) ** 3


def slide_steps(total_ms=DRAWER_MS, tick_ms=DRAWER_TICK_MS):
    steps = int(round(float(total_ms) / float(tick_ms)))
    return steps if steps >= 1 else 1


def tween(start, end, p):
    start, end = float(start), float(end)
    return start + (end - start) * ease(p)


def bar_height(header_height, chrome=DRAWER_CHROME, floor=DRAWER_BAR_FLOOR):
    """What is left floating: the header bar plus the window's own border."""
    height = float(header_height) + float(chrome)
    return height if height >= float(floor) else float(floor)


def bar_top(work_top, work_height, height, slot=0, gap=DRAWER_GAP):
    """Where a parked bar's top goes - resting on the bottom of the work
    area of the screen it is on, stacking upward a slot at a time.

    The work area's own top is read, never assumed to be zero: a second
    monitor ABOVE the primary one has a negative top, and treating it as
    zero parks the bar on the wrong screen."""
    bottom = float(work_top) + float(work_height)
    height = float(height)
    return bottom - height - (height + float(gap)) * int(slot)


def restore_top(parked_top, height, full_height, work_top, work_height):
    """Opening upward from where the bar now sits: the bottom of the bar
    becomes the bottom of the window, so a bar carried somewhere else opens
    where the user left it rather than jumping back. Clamped into the work
    area, measured from that area's own top."""
    top = float(parked_top) + float(height) - float(full_height)
    lowest = float(work_top) + float(work_height) - float(full_height)
    if top > lowest:
        top = lowest
    if top < float(work_top):
        top = float(work_top)
    return top


def take_slot(taken):
    """The lowest free stacking slot - a freed one is reused rather than
    the stack climbing for ever."""
    taken = set(taken or [])
    slot = 0
    while slot in taken:
        slot += 1
    return slot


# ============================================================
# easter egg fallback click counter
# ============================================================

class SlowClicks(object):
    """Three slow clicks: each gap between 250ms and 2s. WPF ClickCount only
    reports 1 or 2, so gaps are measured from the event Timestamp, and a
    repeated Timestamp (the same click seen twice) is ignored."""

    def __init__(self, needed=3):
        self.needed = needed
        self.stamps = []

    def click(self, stamp_ms):
        if self.stamps and stamp_ms == self.stamps[-1]:
            return False
        if self.stamps:
            gap = stamp_ms - self.stamps[-1]
            if gap < CLICK_GAP_MIN_MS or gap > CLICK_GAP_MAX_MS:
                self.stamps = []
        self.stamps.append(stamp_ms)
        if len(self.stamps) >= self.needed:
            self.stamps = []
            return True
        return False


# ============================================================
# settings
# ============================================================

def settings_dir():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(root, "RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), SETTINGS_FILE)


def load_settings(path=None):
    """Missing or damaged falls back key by key; keys nobody knows are
    ignored; keys a newer version reset go back to their default."""
    path = path or settings_path()
    values = dict(DEFAULTS)
    raw = {}
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip(u"\r\n")
                if not line or line.startswith(u"#") or u"=" not in line:
                    continue
                key, value = line.split(u"=", 1)
                raw[key.strip()] = value
    except Exception:
        return values
    try:
        saved_version = int(raw.get(u"settings_version", u"0"))
    except Exception:
        saved_version = 0
    reset = set()
    for version, keys in MIGRATIONS.items():
        if saved_version < version:
            reset.update(keys)
    for key, value in raw.items():
        if key in DEFAULTS and key not in reset and key != u"settings_version":
            values[key] = value
    values[u"settings_version"] = to_text(SETTINGS_VERSION)
    if values[u"shape"] not in (SHAPE_RECT, SHAPE_ROUND):
        values[u"shape"] = DEFAULTS[u"shape"]
    if values[u"theme"] not in THEME_CYCLE:
        values[u"theme"] = DEFAULTS[u"theme"]
    if values[u"type_mode"] not in (u"switch", u"edit"):
        values[u"type_mode"] = DEFAULTS[u"type_mode"]
    return values


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        lines = [u"# RevoBIM {0} v{1}".format(TOOL_NAME, __version__)]
        for key in sorted(DEFAULTS.keys()):
            value = to_text(values.get(key, DEFAULTS[key]))
            value = value.replace(u"\r", u" ").replace(u"\n", u" ")
            lines.append(u"{0}={1}".format(key, value))
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(u"\n".join(lines) + u"\n")
        return True
    except Exception:
        return False


def flag(values, key):
    return to_text(values.get(key, u"")).strip() in (u"1", u"true", u"True")


# ============================================================
# debug log
# ============================================================

class DebugLog(object):
    """Everything worth sending back when something goes wrong. Kept in
    memory for Copy debug and written to %APPDATA%\\RevoBIM when on."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.lines = []

    def clear(self):
        self.lines = []

    def add(self, text, *args):
        try:
            if args:
                text = to_text(text).format(*args)
        except Exception:
            text = to_text(text) + u" " + u" ".join(to_text(a) for a in args)
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.lines.append(u"{0}  {1}".format(stamp, to_text(text)))

    def section(self, title):
        self.lines.append(u"")
        self.lines.append(u"==== {0} ====".format(to_text(title)))

    def text(self):
        return u"\n".join(self.lines)

    def path(self):
        return os.path.join(settings_dir(), DEBUG_FILE)

    def write(self):
        if not self.enabled:
            return None
        try:
            folder = settings_dir()
            if not os.path.isdir(folder):
                os.makedirs(folder)
            with io.open(self.path(), "w", encoding="utf-8") as handle:
                handle.write(self.text() + u"\n")
            return self.path()
        except Exception:
            return None
