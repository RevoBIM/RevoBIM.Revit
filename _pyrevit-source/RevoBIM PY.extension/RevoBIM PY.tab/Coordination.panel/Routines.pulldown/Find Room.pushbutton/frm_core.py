# -*- coding: utf-8 -*-
"""Find Room - pure logic. No .NET, no Revit: runs under plain CPython on the
bench (bench_logic.py) as well as IronPython 2.7 / 3 inside Revit.

Holds settings, palettes, the theme decision, room sorting / grouping /
search, the level match used for linked rooms, and the small geometry helpers.
"""
import os
import re

from frm_version import __version__

MM_PER_FT = 304.8


def mm_to_ft(mm):
    return float(mm) / MM_PER_FT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FT


# =============================================================================
# Text helpers
# =============================================================================
def to_text(value):
    if value is None:
        return u""
    try:
        return u"{0}".format(value)
    except Exception:
        try:
            return unicode(value)  # noqa: F821 - IronPython 2.7
        except Exception:
            return u""


_NUM_SPLIT = re.compile(r"(\d+)")


def natural_key(text):
    """'L2' sorts before 'L10'; case-insensitive; numbers as numbers."""
    parts = _NUM_SPLIT.split(to_text(text).lower())
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part), u""))
        elif part:
            key.append((1, 0, part))
    return key


def words(query):
    return [w for w in to_text(query).lower().split() if w]


def matches(query_words, *fields):
    """Every word of the search must appear somewhere in the fields."""
    if not query_words:
        return True
    hay = u" ".join(to_text(f).lower() for f in fields)
    for w in query_words:
        if w not in hay:
            return False
    return True


def format_area(m2):
    try:
        value = float(m2)
    except Exception:
        return u""
    if value <= 0:
        return u""
    return u"{0:.1f} m\u00b2".format(value)


def format_elev(ft):
    try:
        return u"{0:+.0f} mm".format(ft_to_mm(ft))
    except Exception:
        return u""


# =============================================================================
# Settings - key=value text under %APPDATA%\RevoBIM\
# =============================================================================
SETTINGS_VERSION = 1

# old_version -> {key: new_default}. Empty until the first default changes.
MIGRATIONS = {}

DEFAULTS = {
    u"settings_version": u"1",
    u"theme": u"follow",            # follow | dark | light
    u"mode": u"rooms",              # rooms | spaces
    u"model": u"",                  # last model chosen (host or link name)
    u"highlight": u"#E8912D",       # temporary colour fill
    u"transparency": u"20",         # 0-90 %
    u"zoom_margin_mm": u"1500",
    u"level_tol_mm": u"50",         # linked level -> host level match
    u"show_unplaced": u"0",
    u"restore_on_close": u"1",
    u"debug": u"0",
    u"width": u"1040",
    u"height": u"680",
    u"split": u"0.55",
}


def settings_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), "find_room.txt")


def debug_path():
    return os.path.join(settings_dir(), "find_room_debug.txt")


def error_path():
    return os.path.join(settings_dir(), "find_room_error.txt")


def parse_settings(text):
    """Defaults first, then each key=value line (split on the FIRST = only).
    Unknown keys from older versions are ignored, damaged lines skipped, and
    MIGRATIONS move anyone with an old settings file onto changed defaults."""
    out = dict(DEFAULTS)
    found = {}
    for line in to_text(text).splitlines():
        line = line.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        key = key.strip()
        if key in DEFAULTS:
            found[key] = value.strip()
    out.update(found)
    try:
        old = int(found.get(u"settings_version", u"0") or 0)
    except Exception:
        old = 0
    if found and old < SETTINGS_VERSION:
        for ver in sorted(MIGRATIONS):
            if ver >= old:
                for k, v in MIGRATIONS[ver].items():
                    out[k] = v
    out[u"settings_version"] = to_text(SETTINGS_VERSION)
    if out.get(u"theme") not in (u"follow", u"dark", u"light"):
        out[u"theme"] = u"follow"
    if out.get(u"mode") not in (u"rooms", u"spaces"):
        out[u"mode"] = u"rooms"
    return out


def format_settings(values):
    lines = [u"# RevoBIM Find Room settings v{0}".format(__version__)]
    for key in sorted(DEFAULTS):
        lines.append(u"{0}={1}".format(key, to_text(values.get(key, DEFAULTS[key]))))
    return u"\n".join(lines) + u"\n"


def load_settings(path=None):
    path = path or settings_path()
    text = u""
    try:
        if os.path.exists(path):
            with open(path, "r") as handle:
                text = handle.read()
            try:
                text = text.decode("utf-8")
            except Exception:
                pass
    except Exception:
        text = u""
    return parse_settings(text)


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        data = format_settings(values)
        try:
            data = data.encode("utf-8")
            mode = "wb"
        except Exception:
            mode = "w"
        with open(path, mode) as handle:
            handle.write(data)
        return True
    except Exception:
        return False


def get_int(values, key, lo=None, hi=None):
    try:
        number = int(float(to_text(values.get(key, DEFAULTS.get(key, u"0")))))
    except Exception:
        number = int(float(DEFAULTS.get(key, u"0")))
    if lo is not None and number < lo:
        number = lo
    if hi is not None and number > hi:
        number = hi
    return number


def get_float(values, key, lo=None, hi=None):
    try:
        number = float(to_text(values.get(key, DEFAULTS.get(key, u"0"))))
    except Exception:
        number = float(DEFAULTS.get(key, u"0"))
    if lo is not None and number < lo:
        number = lo
    if hi is not None and number > hi:
        number = hi
    return number


def get_bool(values, key):
    return to_text(values.get(key, DEFAULTS.get(key, u"0"))).strip().lower() in (
        u"1", u"true", u"yes", u"on")


_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_hex(text, fallback=(232, 145, 45)):
    """'#E8912D' -> (232, 145, 45). Anything unreadable -> fallback."""
    m = _HEX.match(to_text(text).strip())
    if not m:
        return fallback
    h = m.group(1)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def to_hex(rgb):
    return u"#{0:02X}{1:02X}{2:02X}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


# =============================================================================
# Palettes and theme
# =============================================================================
DARK = {
    u"Bg": u"#232326", u"Card": u"#2B2B2E", u"Field": u"#1C1C1F",
    u"Bar": u"#1C1C1F", u"Edge": u"#3E3E42", u"WinEdge": u"#4A4A50",
    u"Text": u"#E4E4E4", u"Muted": u"#9A9A9E", u"Faint": u"#6A6A70",
    u"Blue": u"#4FA3E3", u"Orange": u"#E8912D", u"Green": u"#3FA75A",
    u"GreenHover": u"#4EC06D", u"Red": u"#D9534F", u"Select": u"#2B5473",
    u"Hover": u"#333338", u"OnAccent": u"#FFFFFF", u"Tick": u"#10263A",
    u"LevelBg": u"#29292D", u"OrangeWash": u"#3A2C1C", u"RedWash": u"#3A2222",
    u"Overlay": u"#CC101012",
}

LIGHT = {
    u"Bg": u"#F3F3F5", u"Card": u"#FFFFFF", u"Field": u"#FFFFFF",
    u"Bar": u"#E6E6EA", u"Edge": u"#C9C9CF", u"WinEdge": u"#B0B0B8",
    u"Text": u"#1E1E22", u"Muted": u"#5E5E66", u"Faint": u"#9A9AA2",
    u"Blue": u"#1B72BE", u"Orange": u"#B96A12", u"Green": u"#2E8546",
    u"GreenHover": u"#379A53", u"Red": u"#C0392B", u"Select": u"#CFE3F6",
    u"Hover": u"#ECECF0", u"OnAccent": u"#FFFFFF", u"Tick": u"#FFFFFF",
    u"LevelBg": u"#EDEDF1", u"OrangeWash": u"#FBEBD6", u"RedWash": u"#F8DCDA",
    u"Overlay": u"#CCF3F3F5",
}

THEME_MODES = (u"follow", u"dark", u"light")


def next_theme_mode(mode):
    """The chip cycles Auto -> Dark -> Light -> Auto."""
    try:
        i = THEME_MODES.index(mode)
    except ValueError:
        return u"follow"
    return THEME_MODES[(i + 1) % len(THEME_MODES)]


def theme_label(mode):
    return {u"follow": u"Auto", u"dark": u"Dark", u"light": u"Light"}.get(mode, u"Auto")


def resolve_theme(mode, canvas):
    """mode follow|dark|light; canvas is 'dark' / 'light' / None (unread)."""
    if mode == u"dark":
        return u"dark"
    if mode == u"light":
        return u"light"
    if canvas in (u"dark", u"light"):
        return canvas
    return u"dark"


def theme_from_text(text):
    """Enum names compared by text, never by importing the enum (it moves)."""
    t = to_text(text).lower()
    if u"dark" in t:
        return u"dark"
    if u"light" in t:
        return u"light"
    return None


def theme_from_rgb(r, g, b):
    """Canvas background colour -> dark/light by luminance."""
    try:
        lum = 0.2126 * float(r) + 0.7152 * float(g) + 0.0722 * float(b)
    except Exception:
        return None
    return u"dark" if lum < 128 else u"light"


def palette_for(theme):
    return LIGHT if theme == u"light" else DARK


# =============================================================================
# Rooms and spaces
# =============================================================================
class RoomInfo(object):
    """One room or space as the list needs it. `ref` holds whatever the Revit
    layer needs to find it again (ElementIds kept as Revit handed them)."""

    def __init__(self, key, number, name, level_key, level_name, level_elev,
                 area_m2=0.0, state=u"ok", box=None, ref=None):
        self.key = key
        self.number = to_text(number)
        self.name = to_text(name)
        self.level_key = level_key
        self.level_name = to_text(level_name) or u"(no level)"
        self.level_elev = float(level_elev or 0.0)
        self.area_m2 = area_m2 or 0.0
        self.state = state            # ok | unplaced | not_enclosed | redundant
        self.box = box                # ((x,y,z),(x,y,z)) host model coords, feet
        self.ref = ref

    @property
    def findable(self):
        return self.state == u"ok" and self.box is not None

    @property
    def label(self):
        if self.number and self.name:
            return u"{0}  {1}".format(self.number, self.name)
        return self.number or self.name or u"(unnamed)"

    @property
    def state_text(self):
        return {u"unplaced": u"Not placed", u"not_enclosed": u"Not enclosed",
                u"redundant": u"Redundant"}.get(self.state, u"")


def classify(area_ft2, has_location):
    """Revit's own room states: no location = not placed, location but no
    area = not enclosed (or redundant - the Revit layer tells them apart)."""
    if not has_location:
        return u"unplaced"
    try:
        if float(area_ft2) <= 1e-6:
            return u"not_enclosed"
    except Exception:
        return u"not_enclosed"
    return u"ok"


def room_sort_key(room):
    return (room.level_elev, natural_key(room.level_name),
            natural_key(room.number), natural_key(room.name))


def sort_rooms(rooms):
    return sorted(rooms, key=room_sort_key)


class Row(object):
    """A flat list row: a level header or a room under it."""

    def __init__(self, kind, level_key, level_name, room=None, count=0,
                 shown=0, expanded=True, elev=0.0):
        self.kind = kind              # "level" | "room"
        self.level_key = level_key
        self.level_name = level_name
        self.room = room
        self.count = count
        self.shown = shown
        self.expanded = expanded
        self.elev = elev


def build_rows(rooms, query=u"", collapsed=None, show_unplaced=False):
    """Rooms grouped under their level, levels in elevation order.

    A level whose rooms all fail the search is left out; while a search is
    typed every level with a match is shown open, whatever it was before.
    Returns (rows, rooms_shown, levels_shown)."""
    collapsed = collapsed or set()
    q = words(query)
    groups = []
    index = {}
    for room in sort_rooms(rooms):
        if not show_unplaced and room.state != u"ok":
            continue
        if not matches(q, room.number, room.name, room.level_name):
            continue
        gk = room.level_key
        if gk not in index:
            index[gk] = len(groups)
            groups.append((gk, room.level_name, room.level_elev, []))
        groups[index[gk]][3].append(room)
    rows = []
    shown = 0
    for gk, gname, gelev, members in groups:
        open_ = True if q else (gk not in collapsed)
        rows.append(Row(u"level", gk, gname, count=len(members),
                        shown=len(members), expanded=open_, elev=gelev))
        shown += len(members)
        if open_:
            for room in members:
                rows.append(Row(u"room", gk, gname, room=room, elev=gelev))
    return rows, shown, len(groups)


def level_keys(rooms):
    seen = []
    for room in sort_rooms(rooms):
        if room.level_key not in seen:
            seen.append(room.level_key)
    return seen


# =============================================================================
# Linked rooms -> host levels
# =============================================================================
def match_levels(target_elev, target_name, host_levels, tol_ft):
    """host_levels: [(key, name, elev_ft)] in host internal coordinates.

    1. every host level within tol of the linked level's elevation;
    2. else the host level of the same name;
    3. else the nearest host level by elevation.
    Returns (keys, how, offset_ft) - how is 'elevation' / 'name' / 'nearest' /
    'none'."""
    if not host_levels:
        return [], u"none", 0.0
    near = [(abs(e - target_elev), k) for k, n, e in host_levels
            if abs(e - target_elev) <= tol_ft + 1e-9]
    if near:
        near.sort(key=lambda p: p[0])
        return [k for d, k in near], u"elevation", near[0][0]
    tname = to_text(target_name).strip().lower()
    if tname:
        named = [(k, e) for k, n, e in host_levels if to_text(n).strip().lower() == tname]
        if named:
            return [named[0][0]], u"name", abs(named[0][1] - target_elev)
    best = min(host_levels, key=lambda lv: abs(lv[2] - target_elev))
    return [best[0]], u"nearest", abs(best[2] - target_elev)


# =============================================================================
# Views list
# =============================================================================
class ViewInfo(object):
    def __init__(self, key, name, type_name=u"", scale=0, sheet=u"",
                 template=u"", dependent=False, in_crop=True, ref=None):
        self.key = key
        self.name = to_text(name)
        self.type_name = to_text(type_name)
        self.scale = scale
        self.sheet = to_text(sheet)
        self.template = to_text(template)
        self.dependent = dependent
        self.in_crop = in_crop
        self.ref = ref

    @property
    def scale_text(self):
        try:
            s = int(self.scale)
        except Exception:
            return u""
        return u"1:{0}".format(s) if s > 0 else u""

    @property
    def note(self):
        bits = []
        if not self.in_crop:
            bits.append(u"Room outside crop")
        if self.dependent:
            bits.append(u"Dependent")
        return u" \u00b7 ".join(bits)


def sort_views(views, active_key=None, preferred_key=None):
    """Views holding the room first; the last one used on this level, then the
    active view, lead; the rest by natural name."""
    def key(v):
        lead = 2
        if preferred_key is not None and v.key == preferred_key:
            lead = 0
        elif active_key is not None and v.key == active_key:
            lead = 1
        return (0 if v.in_crop else 1, lead, natural_key(v.name))
    return sorted(views, key=key)


def filter_views(views, query):
    q = words(query)
    return [v for v in views if matches(q, v.name, v.type_name, v.sheet, v.template)]


# =============================================================================
# Geometry
# =============================================================================
def box_corners(lo, hi):
    out = []
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                out.append((x, y, z))
    return out


def box_of_points(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def pad_box(box, margin_ft):
    """Grow a box by a margin on X and Y (plans zoom on XY)."""
    if box is None:
        return None
    lo, hi = box
    m = max(0.0, float(margin_ft))
    return ((lo[0] - m, lo[1] - m, lo[2]), (hi[0] + m, hi[1] + m, hi[2]))


def box_centre(box):
    lo, hi = box
    return ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0)


def in_crop(local_point, crop_lo, crop_hi):
    """A point already in the crop box's own coordinates, tested on X and Y."""
    x, y = local_point[0], local_point[1]
    return crop_lo[0] - 1e-6 <= x <= crop_hi[0] + 1e-6 and \
        crop_lo[1] - 1e-6 <= y <= crop_hi[1] + 1e-6


def highlight_key(doc_key, view_key, target_key):
    return u"{0}|{1}|{2}".format(to_text(doc_key), to_text(view_key), to_text(target_key))
