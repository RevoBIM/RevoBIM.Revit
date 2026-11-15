# -*- coding: utf-8 -*-
"""Find in View - version, settings and small helpers.

Pure Python: no .NET names are touched here, so this module is safe to import
from the bench as well as from Revit.
"""

import os
import re

__version__ = "1.14.0"

TOOL_NAME = "Find in View"
RIBBON_TITLE = "Find in View"

# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

SETTINGS_DIR = os.path.join(os.environ.get('APPDATA', ''), 'RevoBIM')
SETTINGS_PATH = os.path.join(SETTINGS_DIR, 'find_in_view.txt')
ERROR_PATH = os.path.join(SETTINGS_DIR, 'find_in_view_last_error.txt')

SETTINGS_VERSION = '1'

DEFAULTS = {
    'settings_version': SETTINGS_VERSION,
    'theme': 'dark',
    # remembered choices
    'view_types': '',              # blank = all view types ticked
    'remember_search': '0',
    'search': '',
    'last_view': '',               # view name, re-selected on open when present
    'last_view_id': '',            # and its id, which is the better match of the two
    # window
    'window_width': '1040',
    'window_height': '700',
    'panel_width': '300',
    # zoom
    'zoom_padding_pct': '15',      # % of the element extent added all round
    'zoom_min_padding_mm': '300',
    'reselect_after_zoom': '1',
    # already in the view you are in
    'zoom_here': '1',              # zoom where it is, instead of opening the window
    'zoom_here_needs_all': '1',    # every selected element has to be drawn there
    # turning the category back on
    'unhide_categories': '1',      # switch the category on where the view has it off
    'unhide_mode': 'auto',         # auto | temporary | permanent
    # tiling
    'open_tiled': '0',             # open beside the view you started in
    'reuse_tile': '1',             # take over the first other tile rather than adding one
    'tile_zoom_extra_pct': '35',   # allowance for the window shrinking as it tiles
    'warn_tile_failure': '1',      # say so when Revit refuses to tile
    'zoom_attempts': '3',          # times to re-zoom when Revit reframes the window
}

# v1.2.0 removed the three content filters and the per view scan behind them.
# Nothing the window does now reads the document, so there is no slow setting
# left to remember or to leave switched on by accident.
REMOVED_SETTINGS = ['only_categories', 'only_elements', 'sheeted_only',
                    'scan_limit']

# keys each settings version reset, so a key whose meaning changed is not read
# with its old value.  Nothing has changed meaning yet; the plumbing is here so
# that when it does, a migration is a one line edit.
MIGRATIONS = {
    # '2': ['zoom_padding_pct'],
}


def _to_text(value):
    try:
        if isinstance(value, bool):
            return '1' if value else '0'
    except Exception:
        pass
    try:
        return '{0}'.format(value)
    except Exception:
        return ''


def load_settings():
    """Read settings, falling back to the defaults key by key.

    A missing or damaged file is not an error, and keys from an older version
    are ignored rather than breaking the load.
    """
    data = {}
    for key in DEFAULTS:
        data[key] = DEFAULTS[key]
    raw = {}
    try:
        if os.path.isfile(SETTINGS_PATH):
            handle = open(SETTINGS_PATH, 'r')
            try:
                for line in handle.read().splitlines():
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    # split on the FIRST '=' only: values may contain '='
                    key, value = line.split('=', 1)
                    raw[key.strip()] = value.strip()
            finally:
                handle.close()
    except Exception:
        raw = {}

    stored_version = raw.get('settings_version', '0')
    reset = set()
    if stored_version != SETTINGS_VERSION:
        for version in MIGRATIONS:
            if version > stored_version:
                for key in MIGRATIONS[version]:
                    reset.add(key)

    for key in raw:
        if key in DEFAULTS and key not in reset:
            data[key] = raw[key]
    data['settings_version'] = SETTINGS_VERSION
    return data


def save_settings(data):
    """Write settings as plain key=value text.  Failure is never fatal."""
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        lines = []
        for key in sorted(DEFAULTS.keys()):
            lines.append('{0}={1}'.format(key, _to_text(data.get(key, DEFAULTS[key]))))
        handle = open(SETTINGS_PATH, 'w')
        try:
            handle.write('\n'.join(lines))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def as_bool(value, fallback=False):
    text = _to_text(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return fallback


def as_int(value, fallback=0):
    try:
        return int(float(_to_text(value).strip()))
    except Exception:
        return fallback


def pack_list(values):
    """Store a list of strings in one key=value line."""
    cleaned = []
    for value in values or []:
        text = _to_text(value).replace('|', ' ').strip()
        if text:
            cleaned.append(text)
    return '|'.join(cleaned)


def unpack_list(text):
    out = []
    for part in _to_text(text).split('|'):
        part = part.strip()
        if part:
            out.append(part)
    return out


# ---------------------------------------------------------------------------
# window tiling arithmetic
# ---------------------------------------------------------------------------
#
# A rect is (view_id_value, left, top, right, bottom), read from
# UIView.GetWindowRectangle.  The rules live here as plain arithmetic so the
# bench can test them without a Revit.

OVERLAP_TOLERANCE = 0.20

# What has to happen to the window layout after the view is opened.
TILE_NEVER = 'never'    # leave the windows exactly as they are
TILE_ALWAYS = 'always'  # the view you came from is the only one open: tile them


def rect_area(rect):
    width = max(0, rect[3] - rect[1])
    height = max(0, rect[4] - rect[2])
    return width * height


def overlap_ratio(first, second):
    """Shared area as a share of the smaller of the two rectangles."""
    left = max(first[1], second[1])
    top = max(first[2], second[2])
    right = min(first[3], second[3])
    bottom = min(first[4], second[4])
    if right <= left or bottom <= top:
        return 0.0
    shared = (right - left) * (bottom - top)
    smallest = min(rect_area(first), rect_area(second))
    if smallest <= 0:
        return 0.0
    return float(shared) / float(smallest)


def looks_tiled(rects):
    """Is Revit already showing these windows side by side?

    Tiled windows do not overlap.  Maximised or tabbed windows sit on top of
    each other and come back with the same rectangle, which reads as an
    overlap of 1.0 - so the test is about overlap rather than about counting
    windows.
    """
    if not rects or len(rects) < 2:
        return False
    for index, first in enumerate(rects):
        for second in rects[index + 1:]:
            if overlap_ratio(first, second) > OVERLAP_TOLERANCE:
                return False
    return True


def pick_tile_to_reuse(rects, host_id, target_id):
    """The first tile that is neither the one started in nor the one wanted.

    "First" is the top left one on screen, read in the order the eye does:
    down the page, then across.
    """
    candidates = []
    for rect in rects or []:
        if rect[0] == host_id or rect[0] == target_id:
            continue
        candidates.append(rect)
    if not candidates:
        return None
    candidates.sort(key=lambda rect: (rect[2], rect[1]))
    return candidates[0][0]


# ---------------------------------------------------------------------------
# the shrink drawer
# ---------------------------------------------------------------------------
#
# All of the arithmetic, kept pure so the bench can prove it without a screen.
# A Storyboard on a borderless window's Top and Height fights the layout pass,
# so the slide is eased by hand on a timer - which means these are the numbers
# every frame is built from.

DRAWER_MS = 280.0        # the whole slide
DRAWER_TICK_MS = 15.0    # one frame
DRAWER_GAP = 8.0         # the parked bar sits this far above the taskbar
DRAWER_STACK = 4.0       # and this far above a bar already parked there


def ease_out(progress):
    """1-(1-p)^3: quick away, gentle in, the same curve as the other tools."""
    step = min(1.0, max(0.0, float(progress)))
    return 1.0 - (1.0 - step) ** 3


def drawer_frame(start, end, progress):
    """Where a value sits part way through the slide."""
    return float(start) + (float(end) - float(start)) * ease_out(progress)


def bar_height(header_height, header_offset):
    """The parked bar: the header, plus the window border above AND below it.

    The offset is how far down the window the header starts - the drop shadow
    margin plus the border - and the same amount is needed underneath, or the
    bar is parked with its bottom edge cut off.
    """
    return max(1.0, float(header_height) + 2.0 * float(header_offset))


def shrunk_top(area_top, area_height, bar, slot=0):
    """Where a parked bar lands, measured from the top of the screen it is on.

    area_top is signed and often negative - a second monitor ABOVE the primary
    one has a negative work area top, and reading it as zero is what sends the
    bar to the wrong screen.
    """
    bottom = float(area_top) + float(area_height)
    step = float(bar) + DRAWER_STACK
    return bottom - float(bar) - DRAWER_GAP - (max(0, int(slot)) * step)


def expand_top(parked_top, height, bar, area_top, area_height):
    """Where the window goes when it opens from a bar that has been dragged.

    It grows UPWARD out of the bar: the bar itself stays put and the body
    appears above it, so the window opens where the user left it rather than
    jumping back to a position they have already moved on from.  The bottom of
    the parked bar is therefore the bottom of the opened window, which is why
    the bar height is part of the sum and not a detail.
    """
    top = float(parked_top) + float(bar) - float(height)
    bottom = float(area_top) + float(area_height)
    if top + float(height) > bottom:
        top = bottom - float(height)
    if top < float(area_top):
        top = float(area_top)
    return top


def free_slot(taken):
    """The lowest parking slot nobody is in, so a freed one is reused."""
    used = set()
    for entry in taken or []:
        try:
            used.add(int(entry))
        except Exception:
            pass
    slot = 0
    while slot in used:
        slot += 1
    return slot


# ---------------------------------------------------------------------------
# is it already in the view you are in?
# ---------------------------------------------------------------------------

HERE_ZOOM = 'zoom'
HERE_WINDOW = 'window'


def zoom_here_decision(enabled, view_can_zoom, selected, drawn, needs_all):
    """Zoom where you are, or open the window and pick a view.

    Part of a selection being drawn is the interesting case: four pipes on this
    level and one on the next is exactly when the view list is wanted, so the
    default is that every selected element has to be here before the window is
    skipped.
    """
    if not enabled or not view_can_zoom:
        return HERE_WINDOW
    if not selected or drawn <= 0:
        return HERE_WINDOW
    if needs_all and drawn < selected:
        return HERE_WINDOW
    return HERE_ZOOM


# ---------------------------------------------------------------------------
# which box takes the caret
# ---------------------------------------------------------------------------

FIELD_ID = 'id'
FIELD_SEARCH = 'search'


def first_field(has_selection):
    """Where the caret goes when the window opens.

    Nothing selected - usually because Find by ID was skipped - means the next
    thing typed is an element id.  A selection means it is a view name.
    """
    return FIELD_SEARCH if has_selection else FIELD_ID


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------

LEVEL_TOLERANCE_FT = 0.01


def nearest_level(levels, elevation):
    """The level a point belongs to.  levels is [(name, elevation), ...].

    The level BELOW wins, because that is how a storey is read - something at
    2.4m above L01 is on L01, not "nearly L02".  Only where there is nothing
    below at all does the lowest level above stand in.
    """
    if not levels:
        return None
    below = [entry for entry in levels if entry[1] <= elevation + LEVEL_TOLERANCE_FT]
    if below:
        below.sort(key=lambda entry: entry[1])
        return below[-1][0]
    above = sorted(levels, key=lambda entry: entry[1])
    return above[0][0]


def summarise_levels(names):
    """"L01 (3), L02 (1)" - the most used first, then alphabetically."""
    counts = {}
    for name in names or []:
        key = name or 'no level'
        counts[key] = counts.get(key, 0) + 1
    entries = list(counts.items())
    entries.sort(key=lambda entry: (-entry[1], natural_key(entry[0])))
    parts = []
    for name, count in entries:
        parts.append(name if count == 1 else '{0} ({1})'.format(name, count))
    return ', '.join(parts)


# ---------------------------------------------------------------------------
# turning a category back on
# ---------------------------------------------------------------------------

UNHIDE_NONE = 'none'
UNHIDE_TEMPORARY = 'temporary'
UNHIDE_PERMANENT = 'permanent'


def plan_unhide(enabled, mode, hidden_categories, hidden_elements, has_template):
    """How to make the selection visible in the view it is about to open in.

    Temporary view properties are only available to a view that HAS a view
    template - Revit's own mode is "apply this template temporarily", so there
    is nothing to enter the mode with otherwise.  Asking for temporary on a
    view with no template therefore lands on permanent, and the caller says so
    rather than quietly doing something else.
    """
    if not enabled:
        return UNHIDE_NONE
    if not hidden_categories and not hidden_elements:
        return UNHIDE_NONE
    if mode == UNHIDE_PERMANENT:
        return UNHIDE_PERMANENT
    if has_template:
        return UNHIDE_TEMPORARY
    return UNHIDE_PERMANENT


# ---------------------------------------------------------------------------
# did the zoom land?
# ---------------------------------------------------------------------------
#
# A void API call is not evidence.  ZoomAndCenterRectangle raises nothing when
# it does not take, and Revit does its own framing when it opens a window - so
# the only way to know is to read the visible rectangle back and compare.
# Everything here is in the view's own (u, v) frame.

ZOOM_SPAN_LIMIT = 4.0    # showing more than this much of what was asked for is
                         # not a zoom to the selection, it is a zoom to fit
ZOOM_SPAN_FLOOR = 0.80   # showing less than this cuts the selection off


def rect_centre(low, high):
    return ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)


def zoom_landed(wanted_low, wanted_high, visible_low, visible_high):
    """Is the view actually framed on what was asked for?  (ok, reason)."""
    visible = [(min(visible_low[axis], visible_high[axis]),
                max(visible_low[axis], visible_high[axis])) for axis in (0, 1)]
    wanted = [(min(wanted_low[axis], wanted_high[axis]),
               max(wanted_low[axis], wanted_high[axis])) for axis in (0, 1)]

    centre = rect_centre(wanted_low, wanted_high)
    for axis in (0, 1):
        if not (visible[axis][0] <= centre[axis] <= visible[axis][1]):
            return False, 'the selection is not in the middle of the view'

    for axis in (0, 1):
        wanted_span = wanted[axis][1] - wanted[axis][0]
        visible_span = visible[axis][1] - visible[axis][0]
        if wanted_span <= 0:
            continue
        ratio = visible_span / wanted_span
        if ratio > ZOOM_SPAN_LIMIT:
            return False, ('the view is showing about {0} times the selection '
                           'rather than framing it'.format(int(round(ratio))))
        if ratio < ZOOM_SPAN_FLOOR:
            return False, 'the view is cutting the selection off'
    return True, ''


# ---------------------------------------------------------------------------
# the easter egg
# ---------------------------------------------------------------------------
#
# Three SLOW clicks on the RevoBIM logo.  Slow is the point: a double click, or
# an impatient triple, must not open it by accident, so a gap shorter than the
# minimum starts the count again rather than counting.

EGG_CLICKS = 3
EGG_MIN_GAP = 0.25   # seconds - faster than this is a double click, not a knock
EGG_MAX_GAP = 2.0    # seconds - slower than this is a new attempt


def egg_click(times, now):
    """Record a click on the logo.  Returns (open it, the clicks to keep)."""
    kept = list(times or [])
    if kept:
        gap = now - kept[-1]
        if gap < EGG_MIN_GAP or gap > EGG_MAX_GAP:
            kept = []
    kept.append(now)
    if len(kept) >= EGG_CLICKS:
        return True, []
    return False, kept


# ---------------------------------------------------------------------------
# element ids typed by hand
# ---------------------------------------------------------------------------

def parse_ids(text):
    """Split what was typed into id tokens.

    Revit's own dialog says semicolons, so semicolons have to work - but commas,
    spaces and new lines are what people actually paste, so they all separate
    too.  Duplicates are dropped, keeping the order they were typed in.
    """
    out = []
    seen = set()
    buffer = []
    for character in _to_text(text):
        if character.isdigit() or character == '-' or character.isalpha():
            buffer.append(character)
            continue
        token = ''.join(buffer).strip()
        buffer = []
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    token = ''.join(buffer).strip()
    if token and token not in seen:
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

_NUM = re.compile(r'(\d+)')


def natural_key(text):
    """Sort key that reads numbers as numbers, so L10 follows L9."""
    parts = _NUM.split(_to_text(text))
    key = []
    for index, part in enumerate(parts):
        if index % 2:
            try:
                key.append((1, int(part), ''))
            except Exception:
                key.append((0, 0, part.lower()))
        elif part:
            key.append((0, 0, part.lower()))
    return key


def matches_keywords(haystack, query):
    """Every whitespace separated word in query must appear in haystack.

    Case insensitive, order independent - the same rule the other RevoBIM
    search boxes use.
    """
    text = _to_text(haystack).lower()
    words = _to_text(query).lower().split()
    if not words:
        return True
    for word in words:
        if word not in text:
            return False
    return True


def plural(count, singular, many=None):
    if many is None:
        many = singular + 's'
    return '{0} {1}'.format(count, singular if count == 1 else many)


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026: prefer .Value."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue  # noqa - guarded fallback
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# zoom arithmetic - kept out of the Revit modules so the bench can test it
# ---------------------------------------------------------------------------

MM_PER_FOOT = 304.8


def mm_to_feet(mm):
    try:
        return float(mm) / MM_PER_FOOT
    except Exception:
        return 0.0


def padded_box(minimum, maximum, padding_pct, min_padding_ft):
    """Grow a (min, max) box by a percentage of its own extent.

    Both arguments are 3-tuples of feet.  The padding is per axis, never less
    than min_padding_ft, so a single point still produces a box Revit will
    accept rather than a degenerate rectangle it refuses to zoom to.
    """
    lows = []
    highs = []
    try:
        pct = max(0.0, float(padding_pct)) / 100.0
    except Exception:
        pct = 0.0
    try:
        floor_pad = max(0.0, float(min_padding_ft))
    except Exception:
        floor_pad = 0.0
    for axis in range(3):
        low = min(minimum[axis], maximum[axis])
        high = max(minimum[axis], maximum[axis])
        pad = max((high - low) * pct, floor_pad)
        lows.append(low - pad)
        highs.append(high + pad)
    return (lows[0], lows[1], lows[2]), (highs[0], highs[1], highs[2])


def box_corners(low, high):
    """All eight corners of a box, not just the two opposite ones."""
    corners = []
    for x_value in (low[0], high[0]):
        for y_value in (low[1], high[1]):
            for z_value in (low[2], high[2]):
                corners.append((x_value, y_value, z_value))
    return corners


def to_frame(point, origin, right, up, normal):
    """A model point in the view's own right / up / depth coordinates."""
    offset = (point[0] - origin[0], point[1] - origin[1], point[2] - origin[2])
    return (offset[0] * right[0] + offset[1] * right[1] + offset[2] * right[2],
            offset[0] * up[0] + offset[1] * up[1] + offset[2] * up[2],
            offset[0] * normal[0] + offset[1] * normal[1] + offset[2] * normal[2])


def from_frame(point, origin, right, up, normal):
    """Back out of the view's coordinates into model coordinates."""
    return (origin[0] + right[0] * point[0] + up[0] * point[1] + normal[0] * point[2],
            origin[1] + right[1] * point[0] + up[1] * point[1] + normal[1] * point[2],
            origin[2] + right[2] * point[0] + up[2] * point[1] + normal[2] * point[2])


def zoom_rectangle(low, high, origin, right, up, normal, padding_pct, min_padding_ft):
    """The two model points to hand to ZoomAndCenterRectangle.

    Every one of the box's eight corners is projected into the view's own
    right/up frame and the extent taken there, because Revit fits the
    rectangle spanned by the two points AS SEEN IN THE VIEW.  Handing it two
    opposite corners of a model axis aligned box only spans the right
    rectangle when the view happens to look down a model axis; on a section
    cut at an angle, or a rotated 3D view, those two corners project to points
    well inside the real extent and the zoom cuts the selection off.

    The padding is applied in the view frame too, so it is a share of what is
    actually on screen rather than of the model box.
    """
    frame_points = [to_frame(corner, origin, right, up, normal)
                    for corner in box_corners(low, high)]
    lows = [min(point[axis] for point in frame_points) for axis in range(3)]
    highs = [max(point[axis] for point in frame_points) for axis in range(3)]
    padded_low, padded_high = padded_box(lows, highs, padding_pct, min_padding_ft)
    return (from_frame(padded_low, origin, right, up, normal),
            from_frame(padded_high, origin, right, up, normal))


def union_box(boxes):
    """Union a list of ((minx,miny,minz),(maxx,maxy,maxz)) tuples."""
    live = [box for box in boxes or [] if box]
    if not live:
        return None
    lows = [None, None, None]
    highs = [None, None, None]
    for minimum, maximum in live:
        for axis in range(3):
            low = min(minimum[axis], maximum[axis])
            high = max(minimum[axis], maximum[axis])
            if lows[axis] is None or low < lows[axis]:
                lows[axis] = low
            if highs[axis] is None or high > highs[axis]:
                highs[axis] = high
    return (lows[0], lows[1], lows[2]), (highs[0], highs[1], highs[2])
