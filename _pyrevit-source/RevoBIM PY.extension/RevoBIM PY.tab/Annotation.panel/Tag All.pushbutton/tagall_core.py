# -*- coding: utf-8 -*-
"""Tag All - version, settings, log, and the rules.

Nothing in here imports Revit or WPF. Every decision the tool takes - which
tag family suits a category, where a tag head lands, whether a room is cut by
a view, what is tagged and what is deleted - is a plain function in this
module, so bench_logic.py can run it under CPython against a table of cases.
"""
import os
import re
import io
import time

__version__ = "1.10.1"

TOOL_NAME = u"Tag All"
RIBBON_NAME = u"RevoBIM Tag All"
FOLDER_NAME = u"Tag All.pushbutton"

SETTINGS_NAME = "tag_all.txt"
LOG_NAME = "tag_all.log"
BREADCRUMB_NAME = "tag_all_last_error.txt"
MODELESS_NOTE_NAME = "tag_all_modeless.txt"

MM_PER_FT = 304.8
CHUNK_SIZE = 40          # elements per transaction inside the TransactionGroup
LINK_SETTLE_MS = 400     # ticking a link re-reads the tree after this quiet spell
MAX_TAGS_PER_RUN = 20000

HOST_KEY = "host"        # the source key for the model the tool runs in
MULTI_CATEGORY = u"Multi-Category Tags"

THEME_AUTO = "auto"
THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_ORDER = (THEME_AUTO, THEME_DARK, THEME_LIGHT)

SHOW_PROBLEMS = "problems"
SHOW_ALWAYS = "always"
SHOW_NEVER = "never"


# ====================== paths and log ======================

def appdata_dir():
    """%APPDATA%\\RevoBIM, created on demand. TAGALL_SETTINGS_DIR overrides it
    so the bench can round-trip settings without touching a real profile."""
    override = os.environ.get("TAGALL_SETTINGS_DIR")
    if override:
        root = override
    else:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        root = os.path.join(base, "RevoBIM")
    try:
        if not os.path.isdir(root):
            os.makedirs(root)
    except Exception:
        pass
    return root


def settings_path():
    return os.path.join(appdata_dir(), SETTINGS_NAME)


def log_path():
    return os.path.join(appdata_dir(), LOG_NAME)


def breadcrumb_path():
    return os.path.join(appdata_dir(), BREADCRUMB_NAME)


def modeless_note_path():
    return os.path.join(appdata_dir(), MODELESS_NOTE_NAME)


def to_text(value):
    """Anything to unicode without raising."""
    if value is None:
        return u""
    try:
        if isinstance(value, unicode):
            return value
    except NameError:
        if isinstance(value, str):
            return value
    try:
        return u"{0}".format(value)
    except Exception:
        try:
            return str(value).decode("utf-8", "replace")
        except Exception:
            return u"?"


def log(message):
    """Append one line to the run log. Never raises."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with io.open(log_path(), "a", encoding="utf-8") as handle:
            handle.write(u"{0}  {1}\n".format(stamp, to_text(message)))
    except Exception:
        pass


def write_text_file(path, text):
    try:
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(to_text(text))
        return True
    except Exception:
        return False


def remove_file(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


# ====================== element ids ======================

def eid_value(element_id):
    """ElementId as a plain int. `.Value` first (2024+), `.IntegerValue` as a
    guarded fallback - it was removed in Revit 2026. Never touch either
    directly anywhere else."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        pass
    try:
        return int(element_id)
    except Exception:
        return 0


def element_key(link_value, element_value):
    """The identity of a tagged thing: a host element, or an element inside a
    particular link instance. Hashable, so it works as a set member."""
    try:
        link_value = int(link_value or 0)
    except Exception:
        link_value = 0
    if link_value > 0:
        return (link_value, int(element_value))
    return (0, int(element_value))


# ====================== units ======================

def mm_to_ft(mm):
    return float(mm) / MM_PER_FT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FT


# ====================== settings ======================

SETTINGS_VERSION = 1

DEFAULTS = {
    "settings_version": u"1",
    "theme_mode": THEME_AUTO,
    "tab": u"family",
    "leader": u"1",
    "offset_x": u"600",
    "offset_y": u"600",
    "elbow": u"1",
    "elbow_mm": u"300",
    "remove_previous": u"0",
    "only_untagged": u"1",
    "untangle": u"0",                 # move placed tags apart vertically until none touch
    "tidy": u"1",                     # run Tag Tidy on each view's new tags (replaces untangle)
    "room_list": u"views",            # views | sheets
    "room_remove_unassigned": u"1",
    "room_only_untagged": u"1",
    "room_tag_type": u"",
    "room_source": HOST_KEY,
    "links": u"",                     # pipe separated link names ticked last time
    "show_results": SHOW_PROBLEMS,
    "window_w": u"1560",
    "window_h": u"880",
    "family_view_group_1": u"",       # view parameter names; blank = first suitable
    "family_view_group_2": u"",
    "room_view_group_1": u"",
    "room_view_group_2": u"",
    "family_sheet_group_1": u"",      # sheet parameter names; blank = first suitable
    "family_sheet_group_2": u"",
    "room_sheet_group_1": u"",
    "room_sheet_group_2": u"",
    "links_height": u"",              # the linked models list, dragged taller; blank = as built
    "family_sheet_widths": u"",       # the sheet table's column widths; blank = default
    "room_sheet_widths": u"",
}

# keys reset when a saved file is older than a given version: version -> keys
MIGRATIONS = {}

# keys from older versions that are read and thrown away rather than kept
REMOVED_SETTINGS = ("scope", "family_active_only", "room_active_only")

# defaulttag:<category name>=<Family : Type> - the tag a category's rows
# start on when they go into the table. Renamed from 1.0's "tagtype:", which
# remembered the last pick rather than a chosen default: those lines are not
# carried forward, so an old pick never turns up as a default nobody set.
TAG_PREFIX = "defaulttag:"


def parse_settings_text(text):
    """key=value lines, split on the first `=` only, so a value carrying `=`
    survives. Blank lines and # comments are ignored."""
    out = {}
    for raw in to_text(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        out[key] = value.strip()
    return out


def apply_migrations(loaded):
    """Drop keys whose meaning changed since the file was written, and keys
    that no longer exist. Everything else is kept."""
    try:
        version = int(loaded.get("settings_version", "0"))
    except Exception:
        version = 0
    for target in sorted(MIGRATIONS.keys()):
        if version < target:
            for key in MIGRATIONS[target]:
                loaded.pop(key, None)
    for key in REMOVED_SETTINGS:
        loaded.pop(key, None)
    loaded["settings_version"] = u"{0}".format(SETTINGS_VERSION)
    return loaded


def load_settings(path=None):
    """Defaults, overlaid key by key with whatever the file holds. A missing
    or damaged file is the defaults."""
    settings = dict(DEFAULTS)
    path = path or settings_path()
    try:
        if os.path.isfile(path):
            with io.open(path, "r", encoding="utf-8") as handle:
                loaded = parse_settings_text(handle.read())
            loaded = apply_migrations(loaded)
            for key, value in loaded.items():
                if key in DEFAULTS or key.startswith(TAG_PREFIX):
                    settings[key] = value
    except Exception:
        pass
    return settings


def save_settings(settings, path=None):
    path = path or settings_path()
    settings = dict(settings)
    settings["settings_version"] = u"{0}".format(SETTINGS_VERSION)
    lines = [u"# RevoBIM Tag All settings - key=value, one per line"]
    for key in sorted(settings.keys()):
        value = to_text(settings[key]).replace(u"\n", u" ").replace(u"\r", u"")
        lines.append(u"{0}={1}".format(key, value))
    try:
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(u"\n".join(lines) + u"\n")
        return True
    except Exception:
        return False


def parse_bool(value, default=False):
    text = to_text(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def parse_float(value, default=0.0):
    try:
        return float(to_text(value).strip().replace(u",", u"."))
    except Exception:
        return float(default)


def parse_int(value, default=0):
    try:
        return int(round(parse_float(value, default)))
    except Exception:
        return int(default)


def bool_text(value):
    return u"1" if value else u"0"


def remembered_tag(settings, category):
    return to_text(settings.get(TAG_PREFIX + to_text(category), u""))


def remember_tag(settings, category, display):
    """Set a category's default tag. Blank or <None> forgets it, so a
    category set back to <None> does not keep an empty line in the file.

    Setting a category fills every one of its families with that tag: any
    family set by hand goes back to following the category, and can then be
    changed again one by one."""
    key = TAG_PREFIX + to_text(category)
    display = to_text(display).strip()
    if not display or display == NONE_TAG:
        settings.pop(key, None)
    else:
        settings[key] = display
    family_prefix = key + u"|"
    for other in [k for k in settings.keys() if to_text(k).startswith(family_prefix)]:
        settings.pop(other, None)
    return settings


# defaulttag:<category>|<family>=<Family : Type> - a family's own default,
# set by hand. Absent, the family follows its category. "<None>" is kept when
# it differs from the category, so a family can be told to start on nothing.
def family_tag_key(category, family):
    return TAG_PREFIX + to_text(category) + u"|" + to_text(family)


def remembered_family_tag(settings, category, family):
    """The tag a family's rows start on: its own default when set by hand,
    else its category's."""
    key = family_tag_key(category, family)
    if key in settings:
        return to_text(settings.get(key))
    return remembered_tag(settings, category)


def family_follows_category(settings, category, family):
    return family_tag_key(category, family) not in settings


def remember_family_tag(settings, category, family, display):
    """Set one family's default. Picking what the category already gives
    forgets the family's own line, so it follows the category again."""
    key = family_tag_key(category, family)
    display = to_text(display).strip() or NONE_TAG
    if display == (remembered_tag(settings, category).strip() or NONE_TAG):
        settings.pop(key, None)
    else:
        settings[key] = display
    return settings


def split_pipe(text):
    return [part for part in to_text(text).split(u"|") if part]


def join_pipe(items):
    return u"|".join([to_text(item) for item in items if to_text(item)])


# ====================== text rules ======================

_NUMBER = re.compile(r"(\d+)")


def natural_key(text):
    """P-9 before P-10 before P-100."""
    parts = _NUMBER.split(to_text(text).lower())
    out = []
    for part in parts:
        if part.isdigit():
            out.append((1, int(part), u""))
        elif part:
            out.append((0, 0, part))
    return out


def matches_keywords(text, query):
    """Every word typed has to appear somewhere in the text, in any order.
    An empty query matches everything."""
    words = to_text(query).lower().split()
    if not words:
        return True
    haystack = to_text(text).lower()
    for word in words:
        if word not in haystack:
            return False
    return True


def singular(name):
    """A category name in the singular, the way Revit names its tag
    categories: Pipes -> Pipe, Duct Accessories -> Duct Accessory,
    Mechanical Equipment -> Mechanical Equipment, Mass -> Mass."""
    text = to_text(name).strip()
    low = text.lower()
    if low.endswith("ies"):
        # Accessories -> Accessory, Assemblies -> Assembly
        return text[:-3] + (u"Y" if text[-3].isupper() else u"y")
    if low.endswith("sses") or low.endswith("xes") or low.endswith("ches"):
        return text[:-2]
    if low.endswith("ss") or low.endswith("us"):
        return text
    if low.endswith("s"):
        return text[:-1]
    return text


def _norm(text):
    return re.sub(r"[^a-z0-9]+", u" ", to_text(text).lower()).strip()


# tag categories that tag by something other than the element's category
UNIVERSAL_TAG_CATEGORIES = (MULTI_CATEGORY,)
IGNORED_TAG_CATEGORIES = (u"Material Tags", u"Keynote Tags", u"Room Tags",
                          u"Space Tags", u"Area Tags")


def tag_base_name(tag_category_name):
    """'Pipe Tags' -> 'Pipe'."""
    text = to_text(tag_category_name).strip()
    for suffix in (u" Tags", u" Tag"):
        if text.lower().endswith(suffix.lower()):
            return text[:-len(suffix)].strip()
    return text


def tag_category_matches(element_category, tag_category):
    """Does a tag category tag elements of a model category?

    Revit names most tag categories as the singular of the model category
    plus ' Tags' - Pipe Tags for Pipes, Duct Accessory Tags for Duct
    Accessories, Mechanical Equipment Tags for Mechanical Equipment. Two
    forms of the element category name are tried against the tag base.
    Multi-Category Tags match everything; keynote and material tags never
    match by category and are left out.
    """
    tag_category = to_text(tag_category).strip()
    if tag_category in UNIVERSAL_TAG_CATEGORIES:
        return True
    if tag_category in IGNORED_TAG_CATEGORIES:
        return False
    base = _norm(tag_base_name(tag_category))
    if not base:
        return False
    element_category = to_text(element_category).strip()
    candidates = set([_norm(element_category), _norm(singular(element_category))])
    return base in candidates


def type_display(family, type_name):
    family = to_text(family).strip()
    type_name = to_text(type_name).strip()
    if family and type_name and family != type_name:
        return u"{0} : {1}".format(family, type_name)
    return family or type_name


def default_tag_for(category_default, offered):
    """The tag a row starts on when it goes into the table: its category's
    default when that tag is still loaded and suits the row, else <None>.

    Never a guess. A default whose family has since been purged, or one that
    only suits some of a category's rows, leaves the row on <None> rather than
    landing a tag nobody picked for it.
    """
    category_default = to_text(category_default).strip()
    if category_default and category_default in offered:
        return category_default
    return NONE_TAG


def unique_names(names):
    """The same link placed twice gets numbered: 'ARCH', 'ARCH (2)'."""
    seen = {}
    out = []
    for name in names:
        name = to_text(name)
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else u"{0} ({1})".format(name, count))
    return out


# ====================== geometry rules ======================

def add3(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale3(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def head_point(base, right, up, x_mm, y_mm):
    """Where the tag head goes: the element's point moved X along the view's
    right direction and Y along its up direction, in model millimetres, so
    the same numbers place the tag the same way in a plan and in a section."""
    return add3(add3(base, scale3(right, mm_to_ft(x_mm))),
                scale3(up, mm_to_ft(y_mm)))


def elbow_side(x_mm):
    """Which side of the tag the elbow goes: the side facing the element.
    A tag offset to the right elbows to its left. With no sideways offset
    there is no side, and a horizontal elbow would only put a kink in a
    leader that is already straight."""
    if x_mm > 0:
        return 1.0
    if x_mm < 0:
        return -1.0
    return 0.0


def extreme_along(points, direction, furthest_positive):
    """The point furthest along a direction, either way."""
    if not points:
        return None
    if furthest_positive:
        return max(points, key=lambda point: dot3(point, direction))
    return min(points, key=lambda point: dot3(point, direction))


def centre_of(points):
    """The middle of a set of corners."""
    lo, hi = corners_bounds(points)
    if lo is None:
        return None
    return ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0)


def leader_anchor(head, right, up, corners=None, x_mm=0.0):
    """Where the leader meets the tag.

    Revit attaches a horizontal tag's leader to the **middle of the outer
    edge on the side the leader comes from** - the family's own horizontal
    centre line, not its origin. `TagHeadPosition` is the family origin,
    which sits wherever that family happens to put it, so an elbow levelled
    with the head is level with nothing in particular.

    So the anchor is built from the tag's measured box: its extent along the
    view's right gives the edge, its centre gives the height. With no box it
    falls back to the head, which is only right for a family whose origin is
    already its centre.
    """
    if not corners:
        return head
    sign = elbow_side(x_mm)
    edge = extreme_along(corners, right, sign < 0)
    centre = centre_of(corners)
    if edge is None or centre is None:
        return head
    along_right = dot3(sub3(edge, head), right)
    along_up = dot3(sub3(centre, head), up)
    return add3(add3(head, scale3(right, along_right)), scale3(up, along_up))


def elbow_point(anchor, right, x_mm, elbow_mm):
    """The elbow: straight back from the anchor along the view's right, and
    nothing else. Level with where the leader meets the tag by construction,
    whatever the view is and wherever the family's origin sits."""
    if not elbow_mm or elbow_mm <= 0:
        return anchor
    sign = elbow_side(x_mm)
    if sign == 0.0:
        return anchor
    return add3(anchor, scale3(right, -sign * mm_to_ft(elbow_mm)))


# ====================== untangling tags vertically ======================

UNTANGLE_GAP_MM = 1.0      # paper mm left between tags stacked clear of each other


def view_box(corners, right, up):
    """A tag's box in the view's own axes: (left, right, bottom, top) along
    the view's right and up, from the corners Revit measured."""
    if not corners:
        return None
    xs = [dot3(point, right) for point in corners]
    ys = [dot3(point, up) for point in corners]
    return min(xs), max(xs), min(ys), max(ys)


def after_placing(untangle, tidy):
    """Untangle and Tag Tidy both lay out the new tags, so at most one is
    on. A settings file from before they excluded each other can hold both;
    Tag Tidy wins, as it did in the run."""
    if untangle and tidy:
        return False, True
    return bool(untangle), bool(tidy)


def after_placing_enabled(untangle, tidy):
    """(untangle can be ticked, Tag Tidy can be ticked): each only while the
    other is not."""
    return not tidy, not untangle


def untangle_gap_ft(view_scale):
    """The gap between stacked tags in model feet: paper mm through the view
    scale, so it looks the same at 1:50 and 1:200."""
    try:
        scale = max(1.0, float(view_scale))
    except Exception:
        scale = 1.0
    return mm_to_ft(UNTANGLE_GAP_MM * scale)


def boxes_touch(a, b, gap):
    """Two view boxes (left, right, bottom, top) touch when they come within
    `gap` of each other both across and up."""
    return (a[0] < b[1] + gap and b[0] < a[1] + gap and
            a[2] < b[3] + gap and b[2] < a[3] + gap)


def untangle_offsets(boxes, gap):
    """How far to move each tag along the view's up so no two touch.

    `boxes` is [(key, (left, right, bottom, top))]. The tags are taken from
    the top of the view down, left to right where level. Each keeps its own
    height unless it would touch one already settled; then it drops to just
    below the lowest one it touches, and is tried again, until it touches
    none. Only ever down, so the topmost tag never moves and the stack reads
    in the order the tags were placed. Tags side by side that do not touch
    are left alone. Returns {key: offset} - zero or negative, in the same
    units as the boxes.
    """
    order = sorted([item for item in boxes if item[1] is not None],
                   key=lambda item: (-(item[1][2] + item[1][3]) / 2.0, item[1][0]))
    settled = []
    out = {}
    for key, box in order:
        offset = 0.0
        for _attempt in range(len(settled) + 1):
            moved = (box[0], box[1], box[2] + offset, box[3] + offset)
            hits = [other for other in settled if boxes_touch(moved, other, gap)]
            if not hits:
                break
            lowest = min([other[2] for other in hits])
            offset = lowest - gap - box[3]
        settled.append((box[0], box[1], box[2] + offset, box[3] + offset))
        out[key] = offset
    return out


def shift_corners(corners, up, offset):
    """The measured corners carried along the view's up with the tag."""
    if not corners:
        return corners
    return [add3(point, scale3(up, offset)) for point in corners]


def elbow_is_horizontal(anchor, elbow, up, tolerance_mm=1.0):
    """Is the elbow level with where the leader meets the tag? Measured
    rather than assumed - this is what the run reads back after Revit has
    had its say."""
    return abs(ft_to_mm(dot3(sub3(elbow, anchor), up))) <= float(tolerance_mm)


def off_level_mm(anchor, elbow, up):
    return ft_to_mm(dot3(sub3(elbow, anchor), up))


def bounds_overlap(a_min, a_max, b_min, b_max):
    """Axis-aligned boxes overlap when they overlap on every axis. A None box
    means unbounded and overlaps everything."""
    if a_min is None or b_min is None:
        return True
    for axis in range(3):
        if a_max[axis] < b_min[axis] or b_max[axis] < a_min[axis]:
            return False
    return True


def z_contains(min_z, max_z, z, slack_mm=10.0):
    slack = mm_to_ft(slack_mm)
    return (min_z - slack) <= z <= (max_z + slack)


def point_in_xy(point, box_min, box_max):
    if box_min is None or box_max is None:
        return True
    return (box_min[0] <= point[0] <= box_max[0] and
            box_min[1] <= point[1] <= box_max[1])


def corners_bounds(points):
    """The world-aligned box around a set of points."""
    if not points:
        return None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def room_in_view(room_min_z, room_max_z, cut_z, room_point, crop_min, crop_max):
    """A room belongs in a plan view when the view's cut plane passes through
    it and, where the view is cropped, its point sits inside the crop."""
    if cut_z is not None:
        if not z_contains(room_min_z, room_max_z, cut_z):
            return False
    return point_in_xy(room_point, crop_min, crop_max)


# ====================== planning ======================

def plan_targets(candidates, tagged, only_untagged, remove_previous):
    """Decide what a run does in one view.

    candidates: list of (key, payload) for everything that could be tagged
    tagged: dict key -> [tag ids] for the tags already in the view

    Returns (to_tag, tags_to_delete). With only_untagged the elements that
    already carry a tag are left out; with remove_previous the tags on the
    elements being tagged are deleted first. Both together: nothing is
    deleted and only the untagged are done, because a run that removes tags
    it will not replace is not what either box means.
    """
    to_tag = []
    to_delete = []
    for key, payload in candidates:
        has_tag = bool(tagged.get(key))
        if only_untagged and has_tag:
            continue
        to_tag.append((key, payload))
        # only the tags on elements this run is about to re-tag are deleted -
        # a run that removes a tag it will not replace is not what either box
        # means. With only_untagged on, those elements never reach here.
        if remove_previous and has_tag:
            to_delete.extend(tagged.get(key) or [])
    return to_tag, to_delete


def chunks(items, size):
    size = max(1, int(size))
    return [items[i:i + size] for i in range(0, len(items), size)]


def percent(done, total):
    if not total:
        return 100
    return int(min(100, max(0, (100.0 * done) / total)))


def should_repaint(done, total, last_percent):
    """Repaint only when the whole percent moves - pumping the dispatcher on
    every element costs more than the work being measured."""
    return percent(done, total) != last_percent


def pick_rows(selected, anchor, key, keys, control, shift):
    """What a click on a row does to the **highlight**. Returns
    (selected, anchor).

    Windows list conventions, because that is what the hands already know:
    a plain click highlights that row alone and becomes the anchor,
    Shift+click highlights the run from the anchor, Ctrl+click adds or
    removes one row, and Ctrl+Shift+click adds a run to what is already
    highlighted. A run does not move the anchor, so the same Shift+click can
    be repeated to widen or narrow one run.

    The highlight is not the tick. Highlighting rows changes nothing about
    what a run will do - it only says which rows a tick will land on.

    `keys` is the visible list in the order it is drawn, so a run means what
    it looks like on screen. With no usable anchor - the first click, or one
    whose anchor the search has hidden - Shift falls back to a plain click
    rather than doing nothing.
    """
    selected = set(selected)
    if shift and anchor in keys and key in keys:
        first = keys.index(anchor)
        last = keys.index(key)
        if first > last:
            first, last = last, first
        run = keys[first:last + 1]
        if control:
            selected.update(run)
        else:
            selected = set(run)
        return selected, anchor
    if control:
        if key in selected:
            selected.discard(key)
        else:
            selected.add(key)
        return selected, key
    return set([key]), key


def apply_tick(ticked, selected, key, on):
    """Ticking a row's box applies that tick to **every highlighted row**,
    when the row ticked is one of them. Tick one of a blue run and the whole
    run follows; tick a row outside the run and only that row changes, so a
    stray tick can never sweep a highlight that had been forgotten about.
    """
    ticked = set(ticked)
    if key in selected and len(selected) > 1:
        targets = set(selected)
    else:
        targets = set([key])
    if on:
        ticked.update(targets)
    else:
        ticked.difference_update(targets)
    return ticked


# ====================== the linked models list ======================

LINKS_MIN_H = 40.0         # the list dragged as short as it goes
LINKS_MAX_H = 600.0        # and as tall


def links_height(value):
    """The linked models list's height after a drag, kept between a couple of
    rows and most of a screen."""
    return max(LINKS_MIN_H, min(LINKS_MAX_H, float(value)))


def saved_links_height(text):
    """The saved height, or None for the list as built (blank or damaged)."""
    try:
        value = float(to_text(text).strip())
    except Exception:
        return None
    if value != value or value <= 0:
        return None
    return links_height(value)


def show_families_group(open_groups):
    """After Add ticked: Categories shuts and Families to tag opens, so the
    rows just added are in front of you with their tag dropdowns."""
    result = dict(open_groups)
    result["categories"] = False
    result["families"] = True
    return result


def family_open(family_key, collapsed_families, query):
    """A category or family in the Categories tree is open, down to its
    types, unless it was shut by hand; a search opens everything it
    matches."""
    return bool(query) or family_key not in collapsed_families


# ====================== the Family Tags groups ======================

# top to bottom, as they stack in the tab
GROUP_ORDER = ("views", "categories", "families")
# how the tab opens: Categories open, reading the current view by default;
# Views / Sheets and Families to tag shut
GROUP_START = {"views": False, "categories": True, "families": False}


# what a Family Tags run works through, picked from the Views / Sheets header
SOURCE_CURRENT = u"current"
SOURCE_TICKED = u"ticked"
SOURCE_SHEETS = u"sheets"
SOURCES = (SOURCE_CURRENT, SOURCE_TICKED, SOURCE_SHEETS)


def view_source(list_index, current_only):
    """Which header button is lit: the Sheets tab means sheets; on the Views
    tab, Current view only or the ticked views."""
    if list_index == 1:
        return SOURCE_SHEETS
    return SOURCE_CURRENT if current_only else SOURCE_TICKED


def pick_view_source(open_groups, source):
    """A header button pressed. Returns (list tab index, current only or None
    to leave it, open groups).

    Ticked views and Sheets both mean picking from the list, so Views /
    Sheets opens - on the matching tab - and the other two shut to give it
    all the room. Current view needs no list, so Views / Sheets collapses and
    Categories expands again."""
    result = dict(open_groups)
    if source == SOURCE_CURRENT:
        # no list to pick from: put it away and go back to the categories
        result["views"] = False
        result["categories"] = True
        return 0, True, result
    result["views"] = True
    result["categories"] = False
    result["families"] = False
    if source == SOURCE_SHEETS:
        return 1, None, result
    return 0, False, result


def toggle_family_group(open_groups, group, categories_opened_before):
    """Open or shut one group. Returns (open_groups, categories_opened_before).

    The first time Categories is opened, Views / Sheets shuts to make room -
    by then the views are usually picked and the categories need the space.
    That happens once per window: open Categories again later and Views /
    Sheets is left as it is, since putting it back open was deliberate.
    """
    result = dict(open_groups)
    now_open = not bool(result.get(group, False))
    result[group] = now_open
    if group == "categories" and now_open:
        if not categories_opened_before:
            result["views"] = False
        categories_opened_before = True
    return result, categories_opened_before


GROUP_SLIDE_MS = 220       # a group opening or shutting, like a drawer


def group_changes(before, after):
    """(opening, closing, steady) - the groups that slide open, the ones that
    slide shut, and the ones open throughout, top to bottom."""
    opening = [g for g in GROUP_ORDER if after.get(g) and not before.get(g)]
    closing = [g for g in GROUP_ORDER if before.get(g) and not after.get(g)]
    steady = [g for g in GROUP_ORDER if before.get(g) and after.get(g)]
    return opening, closing, steady


def slide_height(start, end, progress):
    """A sliding group's height part way through, eased like the drawer and
    never below nothing."""
    return max(0.0, tween(start, end, progress))


def fit_window(open_groups, on_family_tab, blocked):
    """Whether the window shrinks to fit its group bars. With every Family
    Tags group shut there is nothing to give the height to, so the footer
    rides up under the last bar; open any group and the window goes back
    to the height it had, never further. Not on Room Tags, and not while
    the window is full screen or parked on the taskbar."""
    if blocked or not on_family_tab:
        return False
    return not any([open_groups.get(group) for group in GROUP_ORDER])


def group_heights(open_groups):
    """Row heights for the stacked groups, top to bottom, then the filler
    row beneath them. An open group shares the height with the other open
    ones ("star"); a shut one is only as tall as its header ("auto"). With
    every group shut the filler takes the slack, so the options stay at the
    bottom of the tab rather than riding up under the headers."""
    heights = [u"star" if open_groups.get(group) else u"auto" for group in GROUP_ORDER]
    filler = u"auto" if any([open_groups.get(group) for group in GROUP_ORDER]) else u"star"
    return heights, filler


def views_from_sheets(sheet_views, ticked_keys):
    """The views to tag, from the sheets ticked.

    `sheet_views` is [(sheet key, [view key, ...])] in the order the sheets
    are listed. Returns (view keys in sheet order, keys of ticked sheets
    carrying no view): a view placed on two ticked sheets is tagged once, and
    a ticked sheet with nothing taggable on it is named rather than passed
    over in silence.
    """
    out = []
    seen = set()
    empty = []
    for sheet_key, view_keys in sheet_views:
        if sheet_key not in ticked_keys:
            continue
        if not view_keys:
            empty.append(sheet_key)
            continue
        for view_key in view_keys:
            if view_key in seen:
                continue
            seen.add(view_key)
            out.append(view_key)
    return out, empty


# ====================== the view table ======================
# Rows are (key, cells) where cells maps a column id to its text. The view
# table, the tick-list filters and the grouping all work on that shape, so
# none of it needs WPF or Revit to test.

VIEW_COLUMNS = ("name", "type", "g1", "g2")
NO_GROUP = u""
BLANK_LABEL = u"(blank)"


def row_matches(cells, keywords, ticks, exclude=None):
    """Every keyword filter and every tick filter, except the one excluded.
    A tick filter of None means that column is not filtered."""
    for column, text in keywords.items():
        if column == exclude or not text:
            continue
        if not matches_keywords(cells.get(column, u""), text):
            return False
    for column, allowed in ticks.items():
        if column == exclude or allowed is None:
            continue
        if cells.get(column, u"") not in allowed:
            return False
    return True


def filter_rows(rows, keywords, ticks, exclude=None):
    return [row for row in rows if row_matches(row[1], keywords, ticks, exclude)]


def column_choices(rows, column, keywords, ticks):
    """The values a column's tick list offers, with how many rows carry each.

    A column's own filter is left out of its own list, the way Excel does
    it: otherwise the values it is hiding would not be there to tick back
    on, and a filter could only ever narrow. Every other column's filter
    still applies, so the list offers what the rest of the table allows.
    Blanks sort last.
    """
    counts = {}
    for _key, cells in filter_rows(rows, keywords, ticks, exclude=column):
        value = cells.get(column, u"")
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (item[0] == u"", natural_key(item[0])))


def tick_filter_after(allowed, listed, value, on):
    """A column's tick filter after one value is ticked or unticked.

    None means no filter. Ticking every listed value returns None again, so
    a filter that has been fully ticked back is a filter that is gone rather
    than one that silently hides values the list no longer shows.
    """
    listed = set(listed)
    current = set(listed) if allowed is None else set(allowed)
    if on:
        current.add(value)
    else:
        current.discard(value)
    if listed and listed.issubset(current):
        return None
    return current


def is_filtered(column, keywords, ticks):
    return bool(keywords.get(column)) or ticks.get(column) is not None


def group_rows(rows, use_g1, use_g2):
    """[(label1, [(label2, [row, ...]), ...]), ...] in display order.

    Labels in natural order with blanks last; rows in natural order of view
    name. A level that is not in use carries the single label NO_GROUP.
    """
    tree = {}
    for row in rows:
        cells = row[1]
        first = cells.get("g1", u"") if use_g1 else NO_GROUP
        second = cells.get("g2", u"") if use_g2 else NO_GROUP
        tree.setdefault(first, {}).setdefault(second, []).append(row)

    def label_key(label):
        return (label == u"", natural_key(label))

    out = []
    for first in sorted(tree.keys(), key=label_key):
        inner = []
        for second in sorted(tree[first].keys(), key=label_key):
            members = sorted(tree[first][second],
                             key=lambda row: natural_key(row[1].get("name", u"")))
            inner.append((second, members))
        out.append((first, inner))
    return out


def group_id(first, second=None):
    if second is None:
        return (u"1", first)
    return (u"2", first, second)


def all_group_ids(groups, use_g1, use_g2):
    out = set()
    for first, inner in groups:
        if use_g1:
            out.add(group_id(first))
        for second, _members in inner:
            if use_g2:
                out.add(group_id(first, second))
    return out


def flatten_visible(groups, collapsed, use_g1, use_g2):
    """The row keys a reader can see, in the order they are drawn - which is
    what a Shift+click run has to mean."""
    out = []
    for first, inner in groups:
        if use_g1 and group_id(first) in collapsed:
            continue
        for second, members in inner:
            if use_g2 and group_id(first, second) in collapsed:
                continue
            out.extend([row[0] for row in members])
    return out


def toggle_group(ticked, keys):
    """A group heading's tick: ticks every view under it unless every one is
    already ticked, in which case it unticks them."""
    ticked = set(ticked)
    keys = set(keys)
    if keys and keys.issubset(ticked):
        ticked.difference_update(keys)
    else:
        ticked.update(keys)
    return ticked


# what the tool opened on, and the views it starts on
OPEN_SELECTION = "selection"        # views picked in the Project Browser
OPEN_SHEET_SELECTION = "sheet_selection"   # viewports picked on the open sheet
OPEN_SHEET = "sheet"                # the open sheet, nothing picked on it
OPEN_SHEET_EMPTY = "sheet_empty"    # the open sheet carries nothing this list can tag
OPEN_VIEW = "view"                  # a view this list can tag
OPEN_UNLISTED = "unlisted"          # a schedule, legend or the like


def opening_scope(listed, active_key, active_is_sheet, sheet_views, selected_views):
    """Where a view list starts. Returns (current_only, narrowed keys, reason).

    In order:
      - views picked before opening - in the Project Browser, or viewports
        picked on the open sheet - narrow the list to themselves, ticked;
      - on a sheet, the views placed on it narrow the list, ticked;
      - in a view the list can tag, Current view only;
      - anywhere else, the whole list with nothing ticked.

    `listed` is what this particular list can tag, so the same opening gives
    each tab its own answer: a sheet carrying a plan and two sections starts
    Family Tags on all three and Room Tags on the plan alone. A selection
    whose views this list cannot tag falls through to the next rule rather
    than leaving an empty list.
    """
    listed = set(listed)
    chosen = set([key for key in selected_views if key in listed])
    if chosen:
        return False, chosen, (OPEN_SHEET_SELECTION if active_is_sheet else OPEN_SELECTION)
    if active_is_sheet:
        on_sheet = set([key for key in sheet_views if key in listed])
        if on_sheet:
            return False, on_sheet, OPEN_SHEET
        return False, set(), OPEN_SHEET_EMPTY
    if active_key in listed:
        return True, set(), OPEN_VIEW
    return False, set(), OPEN_UNLISTED


def opening_back_label(reason):
    """What Show All Views turns into once pressed - the way back to where
    the list started."""
    if reason == OPEN_SHEET:
        return u"Show Sheet Views"
    return u"Show Selected Views"


def restrict_to_preselection(rows, preselected, show_all):
    """Views selected in Revit before the tool opened narrow the list to
    themselves until Show All Views is pressed. Their ticks never depend on
    which of the two is showing."""
    if not preselected or show_all:
        return list(rows)
    return [row for row in rows if row[0] in preselected]


# ====================== sorting ======================
# A sort is a stack of (column, descending) levels, most significant first.
# The sheet table takes it from the table reference used across RevoBIM:
# click a heading to sort by it, click it again to flip it, Shift+click to
# add a level beneath.

MAX_SORT_LEVELS = 6
SHEET_COLUMNS = ("number", "name", "g1", "g2", "views")


def next_sort_stack(stack, column, shift):
    """The sort after a click on a heading.

    Without Shift: a column that is already the whole sort flips; anything
    else starts again on that column alone, ascending. With Shift: a column
    already in the sort flips that level and leaves the rest alone; a new
    one is added beneath, up to six levels.
    """
    stack = list(stack or [])
    columns = [level[0] for level in stack]
    if not shift:
        if len(stack) == 1 and columns[0] == column:
            return [(column, not stack[0][1])]
        return [(column, False)]
    if column in columns:
        index = columns.index(column)
        stack[index] = (column, not stack[index][1])
        return stack
    if len(stack) < MAX_SORT_LEVELS:
        stack.append((column, False))
    return stack


def sort_rows(rows, stack):
    """Rows sorted by the stack, in natural order, blanks last whichever way
    a level runs. Layered least significant first on a stable sort, because
    one composite key can only reverse everything at once."""
    ordered = list(rows)
    for column, descending in reversed(list(stack or [])):
        ordered.sort(key=lambda row, c=column: natural_key(row[1].get(c, u"")), reverse=descending)
        ordered.sort(key=lambda row, c=column: to_text(row[1].get(c, u"")).strip() == u"")
    return ordered


def sort_badge(stack, column):
    """'1\u25b2' for the first level ascending, '2\u25bc' for the second
    descending; blank for a column not in the sort. The number is left off
    while there is only one level."""
    for index, level in enumerate(stack or []):
        if level[0] == column:
            arrow = u"\u25bc" if level[1] else u"\u25b2"
            return arrow if len(stack) == 1 else u"{0}{1}".format(index + 1, arrow)
    return u""


# ====================== column widths ======================
# A column edge dragged in the sheet table moves width between the two
# columns either side of it, the way a GridSplitter does - so the table
# always fits its panel and never needs a sideways scroll bar. Widths are
# kept as star weights in pixels, which is also what gets remembered.

def resize_columns(widths, index, delta, minimums):
    """Widths after the edge to the right of column `index` is dragged by
    `delta` pixels. The column grows, its right-hand neighbour shrinks by the
    same, neither below its minimum; the total never changes. Dragging the
    last column's right edge, or past a minimum, moves only as far as it can.
    """
    widths = [float(width) for width in widths]
    if index < 0 or index + 1 >= len(widths):
        return widths
    left, right = index, index + 1
    lowest = float(minimums[left]) - widths[left]       # most it can shrink by (negative)
    highest = widths[right] - float(minimums[right])    # most it can grow by
    delta = max(lowest, min(highest, float(delta)))
    widths[left] += delta
    widths[right] -= delta
    return widths


def widths_text(widths):
    return u",".join([u"{0}".format(int(round(width))) for width in widths])


def parse_widths(text, defaults, minimums):
    """Remembered widths, or the defaults when what was saved does not fit
    this table - a different column count, a blank, or anything that is not
    a positive number. Each width is held to its column's minimum."""
    parts = [part.strip() for part in to_text(text).split(u",") if part.strip()]
    if len(parts) != len(defaults):
        return [float(width) for width in defaults]
    out = []
    for part, minimum in zip(parts, minimums):
        try:
            value = float(part)
        except Exception:
            return [float(width) for width in defaults]
        if value <= 0:
            return [float(width) for width in defaults]
        out.append(max(float(minimum), value))
    return out


# ====================== the shrink drawer ======================
# Pressing shrink slides a window down to the bottom of its own screen like a
# drawer closing, leaving only its header floating clear of the taskbar. The
# arithmetic is here so the bench can prove it, including a second monitor
# *above* the primary one, where a negative work-area top is what sends a bar
# to the wrong screen when the primary's numbers are used by mistake.

DRAWER_MS = 280            # the slide, both ways
DRAWER_TICK_MS = 15
DRAWER_MARGIN = 8          # how far the bar floats above the working area's bottom
DRAWER_GAP = 4             # between bars stacked by several windows
DRAWER_MOVED = 2.0         # a bar carried further than this opens from where it is


def edge_fills_screen(grip_name):
    """Which resize grips fill the screen on a double-click: the top and
    bottom edges, not the sides or the corners."""
    return grip_name in ("GripN", "GripS")


def ease_out(progress):
    """1-(1-p)^3 - quick away, gentle landing, like a drawer running home."""
    progress = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - progress) ** 3


def tween(start, end, progress):
    return float(start) + (float(end) - float(start)) * ease_out(progress)


def free_slot(taken):
    """The lowest stacking slot no parked bar is using, so a bar released by
    a window reopening is reused rather than leaving a gap."""
    taken = set(taken)
    slot = 0
    while slot in taken:
        slot += 1
    return slot


def shrunk_top(area_top, area_bottom, bar_height, slot=0,
               margin=DRAWER_MARGIN, gap=DRAWER_GAP):
    """Where a parked bar's top sits: `margin` above the bottom of the
    working area of the window's own screen, stacked above any bars in lower
    slots. Never above the top of that screen, however many are stacked."""
    top = float(area_bottom) - margin - float(bar_height) - slot * (float(bar_height) + gap)
    return max(float(area_top), top)


def expand_geometry(saved_left, saved_top, saved_height, bar_left, bar_top, landed_top,
                    bar_height, area_top, area_bottom):
    """Where a window opens to from its bar. Returns (left, top, height).

    A bar left where it landed opens back to where the window was. A bar the
    user has carried somewhere else opens upward from where it now sits - its
    bottom edge stays put - rather than jumping back to a place they have
    moved on from. Either way the window is held on its own screen.
    """
    height = min(float(saved_height), float(area_bottom) - float(area_top))
    if abs(float(bar_top) - float(landed_top)) <= DRAWER_MOVED:
        left, top = float(saved_left), float(saved_top)
    else:
        left = float(bar_left)
        top = float(bar_top) + float(bar_height) - height
    top = max(float(area_top), min(top, float(area_bottom) - height))
    return left, top, height


# ====================== after a run from sheets ======================

MANY_SHEETS = 8


def open_sheets_prompt(summary, count):
    """The question asked when a run from ticked sheets finishes."""
    if count == 1:
        question = u"Would you like to open the sheet?"
    else:
        question = u"Would you like to open the {0} sheets?".format(count)
        if count > MANY_SHEETS:
            question += u" Each one opens as its own view in Revit."
    return u"Done - {0}.\n\n{1}".format(to_text(summary), question)


# ====================== the tag table ======================

NONE_TAG = u"<None>"


def apply_tag_to_rows(choices, selected, row_key, tag):
    """Choosing a tag on a highlighted row applies it to every highlighted
    row that can take it. Returns (applied keys, refused keys).

    A row can take a tag its own category offers, so a Pipe tag lands on the
    highlighted pipe rows and is refused - and named - on the duct rows
    highlighted alongside them. <None> can go anywhere. A row outside the
    highlight changes alone, so a stray pick never sweeps a forgotten
    highlight.
    """
    if row_key is not None and (row_key not in selected or len(selected) < 2):
        targets = [row_key]
    else:
        targets = [key for key in choices if key in selected]
    applied = []
    refused = []
    for key in targets:
        if tag == NONE_TAG or tag in choices.get(key, ()):
            applied.append(key)
        else:
            refused.append(key)
    return applied, refused


def common_tags(choices, keys):
    """The tags every one of `keys` can take, in the first row's order -
    what the table's own dropdown offers for the highlight."""
    keys = [key for key in keys if key in choices]
    if not keys:
        return []
    shared = set(choices[keys[0]])
    for key in keys[1:]:
        shared &= set(choices[key])
    return [tag for tag in choices[keys[0]] if tag in shared]


def any_tag_choices(choices, keys):
    """Every tag at least one of `keys` can take, in first-seen order."""
    out = []
    for key in keys:
        for tag in choices.get(key, ()):
            if tag not in out:
                out.append(tag)
    return out


def filter_views(views, query):
    """views: list of (name, payload). Keyword search over the name."""
    return [item for item in views if matches_keywords(item[0], query)]


# ====================== the Tag Tidy hook ======================
#
# Tag Tidy is a separate RevoBIM tool.  Tag All finds it on disk, never
# imports it at load, and carries on without it when it is not installed.

TIDY_FOLDER = u"Tag Tidy.pulldown"
TIDY_HOOK_FILE = u"tidy_hook.py"
TIDY_HOOK_VERSION = 1           # the tidy_hook contract this Tag All was written against


def tidy_search_dirs(button_dir, listdir=None):
    """Where to look for Tag Tidy, best first: beside Tag All in its own
    panel, then a Tag Tidy.pulldown on any other panel of the same tab (it
    may have been moved).  Pure apart from listdir, which the bench fakes."""
    listdir = listdir or os.listdir
    panel = os.path.dirname(os.path.normpath(button_dir))
    tab = os.path.dirname(panel)
    found = [os.path.join(panel, TIDY_FOLDER)]
    try:
        names = sorted(listdir(tab))
    except Exception:
        names = []
    for name in names:
        if not name.endswith(u".panel"):
            continue
        candidate = os.path.join(tab, name, TIDY_FOLDER)
        if candidate not in found:
            found.append(candidate)
    return found


def tidy_overrides(options):
    """What Tag All tells Tag Tidy for its own run.  A Tag All run with
    leaders off placed tags with no leader on purpose, so Tag Tidy is told to
    leave those alone rather than switch a leader on."""
    return {"no_leader": u"switch_on" if options.get("leader") else u"skip"}


def tidy_outcome(view_name, answer):
    """Turn a tidy_hook answer for one view into (problems, notes) for the
    run's report.  A clash or a refusal needs a look and is a problem, so
    the results window opens; a tag Tag Tidy left alone is only a note."""
    problems = []
    notes = []
    if not answer:
        return problems, notes
    if not answer.get("ok", True):
        problems.append(u"{0}: Tag Tidy could not tidy the new tags - {1}".format(
            view_name, to_text(answer.get("error")) or u"it gave no reason"))
        return problems, notes
    if answer.get("moved") or answer.get("kept"):
        notes.append(u"{0}: Tag Tidy - {1}".format(view_name, to_text(answer.get("summary"))))
    for kind, label, note in answer.get("rows") or []:
        line = u"{0}: Tag Tidy - {1}: {2}".format(view_name, to_text(label), to_text(note))
        if kind in (u"clash", u"fail"):
            problems.append(line)
        elif kind == u"skip":
            notes.append(line)
    return problems, notes


def summarise(created, deleted, skipped, problems):
    parts = []
    parts.append(u"{0} tag{1} placed".format(created, u"" if created == 1 else u"s"))
    if deleted:
        parts.append(u"{0} removed".format(deleted))
    if skipped:
        parts.append(u"{0} skipped".format(skipped))
    if problems:
        parts.append(u"{0} problem{1}".format(len(problems),
                                              u"" if len(problems) == 1 else u"s"))
    return u", ".join(parts)


def should_show_results(mode, problems):
    mode = to_text(mode).strip().lower() or SHOW_PROBLEMS
    if mode == SHOW_NEVER:
        return False
    if mode == SHOW_ALWAYS:
        return True
    return bool(problems)


# ====================== theme rules ======================

def theme_from_text(text):
    """Revit reports its theme as an enum whose member names have not been
    stable across releases, so it is compared as text."""
    low = to_text(text).lower()
    if "dark" in low:
        return THEME_DARK
    if "light" in low:
        return THEME_LIGHT
    return None


def resolve_theme(mode, revit_theme):
    """The palette to use for a saved mode. Auto follows Revit's canvas; if
    Revit reports nothing (before 2024) Auto is dark."""
    if mode in (THEME_DARK, THEME_LIGHT):
        return mode
    return revit_theme or THEME_DARK


def next_theme_mode(mode):
    """Auto -> Dark -> Light -> Auto."""
    if mode not in THEME_ORDER:
        return THEME_AUTO
    return THEME_ORDER[(THEME_ORDER.index(mode) + 1) % len(THEME_ORDER)]


def theme_label(mode):
    return {THEME_AUTO: u"Auto", THEME_DARK: u"Dark", THEME_LIGHT: u"Light"}.get(mode, u"Auto")
