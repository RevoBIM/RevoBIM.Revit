# -*- coding: utf-8 -*-
"""Level Manager - version, settings, palettes and every rule.

No .NET and no Revit in this module, so every decision the tool takes can be
tested under plain CPython by bench_logic.py.
"""
import os
import re

__version__ = "1.2.0"

TOOL_NAME = u"Level Manager"
APP_KEY = "RevoBIM.LevelManager"
SETTINGS_NAME = "level_manager.txt"
DEBUG_NAME = "level_manager_debug.txt"
ERROR_NAME = "level_manager_error.txt"
NOTE_NAME = "level_manager_open.txt"
SETTINGS_VERSION = 1

MM_PER_FT = 304.8
MOVE_TOL_FT = 0.5 / MM_PER_FT          # half a millimetre counts as moved
CHUNK = 40                              # elements per transaction
BIG_RUN = 2000                          # ask before a run this large

try:
    _TEXT = unicode                     # IronPython 2.7
except NameError:                       # IronPython 3 / CPython
    _TEXT = str


def to_text(value):
    if value is None:
        return u""
    if isinstance(value, _TEXT):
        return value
    try:
        return _TEXT(value)
    except Exception:
        try:
            return _TEXT(str(value), "utf-8", "replace")
        except Exception:
            return u""


# =========================================================================
# Settings
# =========================================================================

DEFAULTS = {
    "settings_version": str(SETTINGS_VERSION),
    "theme": "auto",          # auto / dark / light
    "debug": "0",             # off by default
    "params": "",             # extra parameter columns, | separated
    "left": "",
    "top": "",
    "width": "1240",
    "height": "760",
}

# version -> function(dict) bringing an older file up to that version
MIGRATIONS = {}


def settings_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RevoBIM")


def settings_path(name=SETTINGS_NAME):
    return os.path.join(settings_dir(), name)


def parse_settings(text):
    """key=value lines, split on the first = only. Unknown keys dropped,
    damaged lines ignored, every missing key falls back to its default."""
    out = dict(DEFAULTS)
    found = {}
    for line in to_text(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in DEFAULTS:
            found[key] = value.strip()
    out.update(found)
    try:
        ver = int(found.get("settings_version", "0"))
    except Exception:
        ver = 0
    for step in sorted(MIGRATIONS):
        if ver < step:
            MIGRATIONS[step](out)
    out["settings_version"] = str(SETTINGS_VERSION)
    if out.get("theme") not in ("auto", "dark", "light"):
        out["theme"] = "auto"
    if out.get("debug") not in ("0", "1"):
        out["debug"] = "0"
    return out


def dump_settings(settings):
    lines = [u"# RevoBIM Level Manager settings"]
    for key in sorted(DEFAULTS):
        value = to_text(settings.get(key, DEFAULTS[key]))
        value = value.replace(u"\r", u" ").replace(u"\n", u" ")
        lines.append(u"{0}={1}".format(key, value))
    return u"\n".join(lines) + u"\n"


def load_settings_file(path=None):
    path = path or settings_path()
    try:
        with open(path, "r") as handle:
            raw = handle.read()
        try:
            raw = raw.decode("utf-8")
        except Exception:
            pass
        return parse_settings(raw)
    except Exception:
        return dict(DEFAULTS)


def save_settings_file(settings, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        text = dump_settings(settings)
        data = text.encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(data)
        return True
    except Exception:
        return False


def split_params(text):
    out = []
    for part in to_text(text).split(u"|"):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def join_params(names):
    return u"|".join([to_text(n) for n in names if to_text(n).strip()])


# =========================================================================
# Theme
# =========================================================================

PALETTE_DARK = {
    "Bg": "#232326", "Card": "#2B2B2E", "Field": "#1C1C1F", "Bar": "#1C1C1F",
    "Edge": "#3E3E42", "Frame": "#4A4A50", "Text": "#E4E4E4",
    "Muted": "#9A9A9E", "Dim": "#6A6A70", "Blue": "#4FA3E3",
    "Orange": "#E8912D", "Green": "#3FA75A", "GreenHover": "#4EC06D",
    "Red": "#D9534F", "Select": "#2B5473", "Hover": "#34343A",
    "LevelRow": "#22313F", "CatRow": "#2A2A2E", "GridLine": "#303034",
    "OnAccent": "#FFFFFF", "Violet": "#9B7FE0",
}

PALETTE_LIGHT = {
    "Bg": "#F3F3F5", "Card": "#FFFFFF", "Field": "#FFFFFF", "Bar": "#E6E6EA",
    "Edge": "#C8C8CE", "Frame": "#B4B4BC", "Text": "#1E1E22",
    "Muted": "#5F5F68", "Dim": "#A0A0A8", "Blue": "#1B72BE",
    "Orange": "#B96A12", "Green": "#2E8546", "GreenHover": "#379C53",
    "Red": "#C0392B", "Select": "#CFE3F5", "Hover": "#E8EEF5",
    "LevelRow": "#DCE9F6", "CatRow": "#EFEFF3", "GridLine": "#E2E2E7",
    "OnAccent": "#FFFFFF", "Violet": "#6A4FC2",
}

THEME_CYCLE = {"auto": "dark", "dark": "light", "light": "auto"}


def next_theme_mode(mode):
    return THEME_CYCLE.get(mode, "auto")


def resolve_theme(mode, canvas_dark):
    """'auto' follows Revit's canvas. canvas_dark None means unreadable -> dark."""
    if mode == "dark":
        return "dark"
    if mode == "light":
        return "light"
    if canvas_dark is None:
        return "dark"
    return "dark" if canvas_dark else "light"


def palette_for(mode, canvas_dark):
    return PALETTE_DARK if resolve_theme(mode, canvas_dark) == "dark" else PALETTE_LIGHT


def theme_label(mode):
    return {"auto": u"Auto", "dark": u"Dark", "light": u"Light"}.get(mode, u"Auto")


def canvas_theme_is_dark(theme_value):
    """Read UIThemeManager.CurrentCanvasTheme. UITheme.Dark is 0, so the test
    is 'is not None' and on the member's name, never truthiness."""
    if theme_value is None:
        return None
    name = to_text(theme_value).strip().lower()
    if name.endswith("dark") or name == "0":
        return True
    if name.endswith("light") or name == "1":
        return False
    return None


def colour_is_dark(red, green, blue):
    lum = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return lum < 128


def hex_rgb(hex_text):
    text = hex_text.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


# Line icons: 16-unit paths on a 16x16 canvas, stroked with the button colour.
ICONS = {
    "theme": "M8,2 A6,6 0 1 0 8,14 A6,6 0 1 0 8,2 Z M8,2 L8,14",
    "search": "M7,2.5 A4.5,4.5 0 1 0 7,11.5 A4.5,4.5 0 1 0 7,2.5 Z M10.3,10.3 L14,14",
    "expand": "M3,5 L8,10 L13,5",
    "collapse": "M3,10 L8,5 L13,10",
    "levels": "M2,4 L14,4 M2,8 L14,8 M2,12 L14,12",
    "clear": "M3,3 L13,13 M13,3 L3,13",
    "plus": "M8,2.5 L8,13.5 M2.5,8 L13.5,8",
    "refresh": "M13,8 A5,5 0 1 1 11.5,4.5 M11.8,1.8 L11.8,4.8 L8.8,4.8",
    "select": "M3,2 L3,13 L6,10 L8.5,14.5 L10.2,13.6 L7.8,9.2 L12,9.2 Z",
    "assign": "M2,12 L14,12 M2,4 L14,4 M8,11 L8,5.5 M5.5,8 L8,5.5 L10.5,8",
    "copy": "M5,5 L13,5 L13,14 L5,14 Z M3,11 L3,2 L10,2",
    "untick": "M2.5,2.5 L13.5,2.5 L13.5,13.5 L2.5,13.5 Z",
    "fromrevit": "M2,8 L10,8 M7,5 L10,8 L7,11 M12,2.5 L14,2.5 L14,13.5 L12,13.5",
    "caret": "M4,6 L8,10 L12,6",
    "close": "M4,4 L12,12 M12,4 L4,12",
    "cube": "M8,1.5 L14,4.8 L14,11.2 L8,14.5 L2,11.2 L2,4.8 Z M2,4.8 L8,8 L14,4.8 M8,8 L8,14.5",
    "delete": "M3,4 L13,4 M6,4 L6,2.5 L10,2.5 L10,4 M4.5,4 L5.3,14 L10.7,14 L11.5,4 M7,6.5 L7,11.5 M9,6.5 L9,11.5",
}

ARROW_RIGHT = "M0,0 L5,4 L0,8 Z"
ARROW_DOWN = "M0,0 L8,0 L4,5 Z"
ARROW_NONE = "M0,0"


# =========================================================================
# Text helpers
# =========================================================================

_NUM = re.compile(r"(\d+)")


def natural_key(text):
    parts = _NUM.split(to_text(text).lower())
    out = []
    for part in parts:
        if part.isdigit():
            out.append((0, int(part), u""))
        else:
            out.append((1, 0, part))
    return out


def fmt_mm(feet):
    """Feet to a millimetre string, no '-0'."""
    if feet is None:
        return u""
    try:
        mm = float(feet) * MM_PER_FT
    except Exception:
        return u""
    value = int(round(mm))
    if value == 0:
        value = 0
    return to_text(value)


def fmt_count(shown, total, filtered):
    if filtered and shown != total:
        return u"{0} of {1}".format(shown, total)
    return to_text(total)


def thousands(n):
    try:
        return u"{0:,}".format(int(n))
    except Exception:
        return to_text(n)


def words(text):
    return [w for w in to_text(text).lower().split() if w]


def chunks(items, size):
    size = max(1, int(size))
    for start in range(0, len(items), size):
        yield items[start:start + size]


# =========================================================================
# How a level association is held, per kind of element
# =========================================================================
# Each route is the BuiltInParameter (looked up by name at call time) that
# holds the level, and the offsets that keep the element where it is when
# the level changes. Order matters: the first route that exists and is
# writable on an element is the one used.

ROUTES = [
    ("RBS_START_LEVEL_PARAM", ["RBS_OFFSET_PARAM"]),                       # pipes, ducts, trays, conduit
    ("WALL_BASE_CONSTRAINT", ["WALL_BASE_OFFSET"]),                        # walls
    ("FAMILY_BASE_LEVEL_PARAM", ["FAMILY_BASE_LEVEL_OFFSET_PARAM"]),       # columns
    ("INSTANCE_REFERENCE_LEVEL_PARAM", ["STRUCTURAL_BEAM_END0_ELEVATION+STRUCTURAL_BEAM_END1_ELEVATION",
                                        "Z_OFFSET_VALUE"]),                # framing
    ("STAIRS_BASE_LEVEL_PARAM", ["STAIRS_BASE_OFFSET"]),                   # stairs
    ("STAIRS_RAILING_BASE_LEVEL_PARAM", ["STAIRS_RAILING_HEIGHT_OFFSET"]),  # railings
    ("ROOF_BASE_LEVEL_PARAM", ["ROOF_LEVEL_OFFSET_PARAM"]),                # roofs
    ("GROUP_LEVEL_PARAM", ["GROUP_OFFSET_FROM_LEVEL"]),                    # model groups
    ("FABRICATION_LEVEL_PARAM", ["FABRICATION_OFFSET_PARAM"]),             # fabrication parts
    ("FAMILY_LEVEL_PARAM", ["INSTANCE_ELEVATION_PARAM",
                            "INSTANCE_FREE_HOST_OFFSET_PARAM"]),           # families
    ("LEVEL_PARAM", ["FLOOR_HEIGHTABOVELEVEL_PARAM",
                     "CEILING_HEIGHTABOVELEVEL_PARAM"]),                   # floors, ceilings
    ("INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", []),                            # face/work plane hosted
    ("name:Reference Level", ["name:Middle Elevation", "name:Offset"]),
    ("name:Base Level", ["name:Base Offset"]),
    ("name:Level", ["name:Elevation from Level", "name:Offset from Host",
                    "name:Height Offset From Level"]),
    ("name:Schedule Level", []),
]

GENERIC_OFFSETS = ["INSTANCE_ELEVATION_PARAM", "INSTANCE_FREE_HOST_OFFSET_PARAM"]

ROUTE_NAMES = [r[0] for r in ROUTES]

# An offset entry may name several parameters joined by '+', set together
# (a beam's two end offsets). Only the FIRST entry that is fully writable on
# an element is used - two entries can be two names for the same quantity,
# and setting both would put the element back twice.


def offset_members(entry):
    return [p for p in to_text(entry).split(u"+") if p]


def offsets_for(route):
    for name, offsets in ROUTES:
        if name == route:
            out = list(offsets)
            for extra in GENERIC_OFFSETS:
                if extra not in out:
                    out.append(extra)
            return out
    return list(GENERIC_OFFSETS)


def route_label(route):
    """Human name for the parameter a route writes."""
    labels = {
        "RBS_START_LEVEL_PARAM": u"Reference Level",
        "WALL_BASE_CONSTRAINT": u"Base Constraint",
        "FAMILY_BASE_LEVEL_PARAM": u"Base Level",
        "INSTANCE_REFERENCE_LEVEL_PARAM": u"Reference Level",
        "STAIRS_BASE_LEVEL_PARAM": u"Base Level",
        "STAIRS_RAILING_BASE_LEVEL_PARAM": u"Base Level",
        "ROOF_BASE_LEVEL_PARAM": u"Base Level",
        "GROUP_LEVEL_PARAM": u"Reference Level",
        "FABRICATION_LEVEL_PARAM": u"Reference Level",
        "FAMILY_LEVEL_PARAM": u"Level",
        "LEVEL_PARAM": u"Level",
        "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM": u"Schedule Level",
    }
    if route and route.startswith("name:"):
        return to_text(route[5:])
    return labels.get(route, to_text(route))


# Categories never listed: datums, view furniture, sketches, links.
EXCLUDED_CATEGORIES = [
    "OST_Levels", "OST_Grids", "OST_RvtLinks", "OST_Cameras", "OST_Viewers",
    "OST_SectionBox", "OST_SketchLines", "OST_CLines", "OST_VolumeOfInterest",
    "OST_Matchline", "OST_IOSSketchGrid", "OST_RoomSeparationLines",
    "OST_MEPSpaceSeparationLines", "OST_AreaSchemeLines", "OST_PointClouds",
    "OST_RasterImages", "OST_ProjectBasePoint", "OST_SharedBasePoint",
    "OST_InternalOrigin", "OST_ImportObjectStyles", "OST_Elev",
    "OST_ReferenceViewer", "OST_DSR_LeaderTickMarkStyleId",
]


# =========================================================================
# Geometry comparison
# =========================================================================

def deviation(before, after):
    """Largest coordinate change between two snapshots (tuples of floats)."""
    if before is None and after is None:
        return 0.0
    if before is None or after is None:
        return 1.0e9
    if len(before) != len(after):
        return 1.0e9
    worst = 0.0
    for a, b in zip(before, after):
        diff = abs(float(a) - float(b))
        if diff > worst:
            worst = diff
    return worst


def has_moved(before, after, tol=None):
    return deviation(before, after) > (MOVE_TOL_FT if tol is None else tol)


def z_shift(before, after):
    """Vertical shift of a snapshot's anchor (its first point)."""
    if not before or not after or len(before) < 3 or len(after) < 3:
        return 0.0
    return float(after[2]) - float(before[2])


def xy_shift(before, after):
    if not before or not after or len(before) < 3 or len(after) < 3:
        return 0.0
    dx = float(after[0]) - float(before[0])
    dy = float(after[1]) - float(before[1])
    return (dx * dx + dy * dy) ** 0.5


def compensated_offset(offset_now, dz):
    """Offset that cancels a vertical shift of dz (feet)."""
    return float(offset_now) - float(dz)


# =========================================================================
# The table model
# =========================================================================

COLUMNS = [
    # key, heading, min width, star weight, filterable, numeric
    ("name", u"Level / Category / Element", 280, 3.0, True, False),
    ("count", u"Count", 74, 0.6, False, True),
    ("id", u"Element ID", 86, 0.7, True, True),
    ("family", u"Family", 130, 1.4, True, False),
    ("type", u"Type", 130, 1.4, True, False),
    ("workset", u"Workset", 110, 1.0, True, False),
    ("elev", u"Elevation (mm)", 104, 0.8, True, True),
    ("above", u"Above level (mm)", 112, 0.8, True, True),
    ("note", u"Note", 140, 1.2, True, False),
]

NUMERIC = set(["id", "elev", "above", "count"])
BLANK = u"(blank)"


def param_key(name):
    return u"p:" + to_text(name)


def is_param_key(key):
    return to_text(key).startswith(u"p:")


def param_name(key):
    return to_text(key)[2:]


class Model(object):
    """Levels, the elements on them, ticks, filters and sort. No WPF."""

    def __init__(self, levels, elements, params=None):
        self.levels = []
        self.level_by_id = {}
        self.elements = {}
        self.by_level = {}
        self.ticked = set()
        self.expanded = set()
        self.filter_collapsed = set()
        self.col_filters = {}
        self.val_filters = {}
        self.search = u""
        self.sort_stack = []
        self.param_cols = list(params or [])
        self.show_workset = True
        self.last_match = 0
        self._hay = {}
        self.load(levels, elements)

    # ---- data -----------------------------------------------------------
    def load(self, levels, elements):
        self.levels = sorted(levels, key=lambda lv: (float(lv.get("proj", 0.0)),
                                                     natural_key(lv.get("name"))))
        self.level_by_id = dict((lv["id"], lv) for lv in self.levels)
        self.elements = {}
        self.by_level = {}
        for lv in self.levels:
            self.by_level[lv["id"]] = {}
        for info in elements:
            lid = info.get("level")
            if lid not in self.level_by_id:
                continue
            self.elements[info["id"]] = info
            cats = self.by_level[lid]
            cats.setdefault(info.get("category") or u"(no category)", []).append(info["id"])
        self.ticked = set(i for i in self.ticked if i in self.elements)
        self._hay = {}

    def reset_cache(self):
        """Forget the search text built per element (columns or values changed)."""
        self._hay = {}

    def total(self):
        return len(self.elements)

    def set_param_values(self, name, values):
        for eid, info in self.elements.items():
            info.setdefault("params", {})[name] = to_text(values.get(eid, u""))
        self._hay = {}

    # ---- values -----------------------------------------------------------
    def value(self, info, key):
        if is_param_key(key):
            return to_text(info.get("params", {}).get(param_name(key), u""))
        if key == "id":
            return to_text(info.get("id"))
        if key == "elev":
            return fmt_mm(info.get("z_disp"))
        if key == "above":
            lv = self.level_by_id.get(info.get("level"))
            if lv is None or info.get("z") is None:
                return u""
            return fmt_mm(float(info["z"]) - float(lv.get("proj", 0.0)))
        return to_text(info.get(key, u""))

    def sort_value(self, info, key):
        text = self.value(info, key)
        if key in NUMERIC:
            try:
                return (0, float(text), [])
            except Exception:
                return (1, 0.0, natural_key(text))
        return (0, 0.0, natural_key(text))

    def visible_keys(self):
        keys = [c[0] for c in COLUMNS if c[0] != "workset" or self.show_workset]
        note = keys.pop(keys.index("note"))
        keys.extend([param_key(p) for p in self.param_cols])
        keys.append(note)
        return keys

    # ---- filtering --------------------------------------------------------
    def filter_active(self):
        if self.search.strip():
            return True
        for text in self.col_filters.values():
            if to_text(text).strip():
                return True
        for allowed in self.val_filters.values():
            if allowed is not None:
                return True
        return False

    def haystack(self, info):
        cached = self._hay.get(info["id"])
        if cached is not None:
            return cached
        lv = self.level_by_id.get(info.get("level"), {})
        parts = [lv.get("name", u""), info.get("category", u"")]
        for key in self.visible_keys():
            if key == "count":
                continue
            parts.append(self.value(info, key))
        text = u" ".join([to_text(p) for p in parts]).lower()
        self._hay[info["id"]] = text
        return text

    def passes(self, info, exclude=None):
        terms = words(self.search)
        if terms:
            hay = self.haystack(info)
            for term in terms:
                if term not in hay:
                    return False
        for key, text in self.col_filters.items():
            if key == exclude:
                continue
            terms = words(text)
            if not terms:
                continue
            value = self.value(info, key).lower()
            for term in terms:
                if term not in value:
                    return False
        for key, allowed in self.val_filters.items():
            if key == exclude or allowed is None:
                continue
            value = self.value(info, key) or BLANK
            if value not in allowed:
                return False
        return True

    def values_for(self, key, limit=3000):
        """Distinct values for a column's tick list. The column's own filter
        is left out, so a value it hides can be ticked back on."""
        seen = set()
        for info in self.elements.values():
            if not self.passes(info, exclude=key):
                continue
            seen.add(self.value(info, key) or BLANK)
            if len(seen) >= limit:
                break
        return sorted(seen, key=lambda v: (v == BLANK, natural_key(v)))

    def clear_filters(self):
        self.search = u""
        self.col_filters = {}
        self.val_filters = {}
        self.filter_collapsed = set()

    # ---- sorting ----------------------------------------------------------
    def click_sort(self, key, shift):
        for i, (k, desc) in enumerate(self.sort_stack):
            if k == key:
                if shift:
                    self.sort_stack[i] = (k, not desc)
                else:
                    self.sort_stack = [(k, not desc)] if len(self.sort_stack) == 1 else [(k, False)]
                return
        if shift and len(self.sort_stack) < 6:
            self.sort_stack.append((key, False))
        else:
            self.sort_stack = [(key, False)]

    def sort_badge(self, key):
        for i, (k, desc) in enumerate(self.sort_stack):
            if k == key:
                return u"{0}{1}".format(i + 1, u"\u25BC" if desc else u"\u25B2")
        return u""

    def ordered(self, ids):
        infos = [self.elements[i] for i in ids]
        infos.sort(key=lambda r: (natural_key(r.get("name")), r.get("id")))
        for level in range(len(self.sort_stack) - 1, -1, -1):
            key, desc = self.sort_stack[level]
            infos.sort(key=lambda r, k=key: self.sort_value(r, k), reverse=desc)
            infos.sort(key=lambda r, k=key: self.value(r, k) == u"")   # blanks last
        return infos

    # ---- tree -------------------------------------------------------------
    def is_open(self, key):
        if self.filter_active():
            return key not in self.filter_collapsed
        return key in self.expanded

    def toggle_open(self, key):
        if self.filter_active():
            if key in self.filter_collapsed:
                self.filter_collapsed.discard(key)
            else:
                self.filter_collapsed.add(key)
            return
        if key in self.expanded:
            self.expanded.discard(key)
        else:
            self.expanded.add(key)

    def expand_all(self, categories=True):
        self.filter_collapsed = set()
        for lv in self.levels:
            self.expanded.add(level_key(lv["id"]))
            if categories:
                for cat in self.by_level[lv["id"]]:
                    self.expanded.add(cat_key(lv["id"], cat))

    def collapse_all(self):
        self.expanded = set()
        if self.filter_active():
            for lv in self.levels:
                self.filter_collapsed.add(level_key(lv["id"]))

    def visible_ids(self, lid, cat=None):
        cats = self.by_level.get(lid, {})
        out = []
        names = [cat] if cat is not None else list(cats.keys())
        for name in names:
            for eid in cats.get(name, []):
                if self.passes(self.elements[eid]):
                    out.append(eid)
        return out

    def tick_state(self, ids):
        if not ids:
            return "0"
        hit = 0
        for i in ids:
            if i in self.ticked:
                hit += 1
        if hit == 0:
            return "0"
        if hit == len(ids):
            return "1"
        return "p"

    def rows(self):
        """The rows on screen, in order. Each row is a plain dict."""
        out = []
        filtered = self.filter_active()
        self.last_match = 0
        for lv in self.levels:
            lid = lv["id"]
            lkey = level_key(lid)
            cats = self.by_level.get(lid, {})
            total = sum([len(v) for v in cats.values()])
            vis_by_cat = {}
            for name in cats:
                vis_by_cat[name] = self.visible_ids(lid, name)
            shown = sum([len(v) for v in vis_by_cat.values()])
            self.last_match += shown
            all_vis = []
            for v in vis_by_cat.values():
                all_vis.extend(v)
            lopen = self.is_open(lkey) and (shown > 0 or not filtered)
            out.append({
                "key": lkey, "kind": "L", "depth": 0, "level": lid,
                "name": lv.get("name", u""),
                "count": fmt_count(shown, total, filtered),
                "arrow": (ARROW_DOWN if lopen else ARROW_RIGHT) if total else ARROW_NONE,
                "tick": self.tick_state(all_vis), "state": "ok",
                "elev": fmt_mm(lv.get("disp")), "id": to_text(lid),
            })
            if not lopen:
                continue
            for name in sorted(cats.keys(), key=natural_key):
                vis = vis_by_cat[name]
                if not vis:
                    continue
                ckey = cat_key(lid, name)
                copen = self.is_open(ckey)
                out.append({
                    "key": ckey, "kind": "C", "depth": 1, "level": lid,
                    "name": name,
                    "count": fmt_count(len(vis), len(cats[name]), filtered),
                    "arrow": ARROW_DOWN if copen else ARROW_RIGHT,
                    "tick": self.tick_state(vis), "state": "ok",
                })
                if not copen:
                    continue
                for info in self.ordered(vis):
                    row = {
                        "key": elem_key(info["id"]), "kind": "E", "depth": 2,
                        "level": lid, "eid": info["id"],
                        "arrow": ARROW_NONE,
                        "tick": "1" if info["id"] in self.ticked else "0",
                        "state": "ok" if info.get("assignable", True) else "locked",
                    }
                    for key in self.visible_keys():
                        if key == "count":
                            continue
                        row[key] = self.value(info, key)
                    out.append(row)
        return out

    # ---- ticks and selection ----------------------------------------------
    def ids_for_key(self, key):
        kind, lid, cat, eid = parse_key(key)
        if kind == "E":
            return [eid] if eid in self.elements else []
        if kind == "L":
            return self.visible_ids(lid)
        if kind == "C":
            return self.visible_ids(lid, cat)
        return []

    def toggle_tick(self, key, highlighted=None):
        """Tick or untick a row. Ticking a highlighted row applies to every
        highlighted row; a row outside the highlight changes alone."""
        keys = [key]
        if highlighted and key in highlighted:
            keys = list(highlighted)
        ids = []
        for k in keys:
            ids.extend(self.ids_for_key(k))
        ids = list(set(ids))
        if not ids:
            return 0
        if self.tick_state(ids) == "1":
            for i in ids:
                self.ticked.discard(i)
        else:
            for i in ids:
                self.ticked.add(i)
        return len(ids)

    def tick_ids(self, ids):
        n = 0
        for i in ids:
            if i in self.elements:
                self.ticked.add(i)
                n += 1
        return n

    def untick_all(self):
        self.ticked = set()

    def selection(self, highlighted=None):
        """Elements the Assign button acts on: everything ticked, plus the
        highlighted rows (a highlighted heading means its shown elements)."""
        out = set(self.ticked)
        for key in highlighted or []:
            out.update(self.ids_for_key(key))
        return sorted(out)

    def open_levels_of(self, ids):
        for i in ids:
            info = self.elements.get(i)
            if info is None:
                continue
            self.expanded.add(level_key(info["level"]))
            self.expanded.add(cat_key(info["level"], info.get("category")))


def level_key(lid):
    return u"L|{0}".format(lid)


def cat_key(lid, cat):
    return u"C|{0}|{1}".format(lid, to_text(cat))


def elem_key(eid):
    return u"E|{0}".format(eid)


def parse_key(key):
    parts = to_text(key).split(u"|", 2)
    kind = parts[0]
    try:
        if kind == "L":
            return "L", int(parts[1]), None, None
        if kind == "C":
            return "C", int(parts[1]), parts[2], None
        if kind == "E":
            return "E", None, None, int(parts[1])
    except Exception:
        pass
    return None, None, None, None


# =========================================================================
# Assigning a level
# =========================================================================

def plan_assign(model, ids, target):
    """Split a selection into what will change and what will not."""
    plan = {"do": [], "already": [], "locked": [], "levels": set()}
    for i in ids:
        info = model.elements.get(i)
        if info is None:
            continue
        plan["levels"].add(info.get("level"))
        if info.get("level") == target:
            plan["already"].append(i)
        elif not info.get("assignable", True) or not info.get("route"):
            plan["locked"].append((i, info.get("note") or u"Level cannot be changed"))
        else:
            plan["do"].append(i)
    return plan


def plan_summary(model, plan, target):
    lv = model.level_by_id.get(target, {})
    parts = [u"Assign {0} element{1} to {2}".format(
        thousands(len(plan["do"])), u"" if len(plan["do"]) == 1 else u"s",
        lv.get("name", u"?"))]
    if plan["already"]:
        parts.append(u"{0} already on it".format(thousands(len(plan["already"]))))
    if plan["locked"]:
        parts.append(u"{0} cannot be changed".format(thousands(len(plan["locked"]))))
    return u" - ".join(parts) + u"."


def new_result():
    return {"done": [], "refused": [], "skipped": [], "held": [],
            "compensated": {}, "rolled_back": False, "moved": [],
            "errors": []}


def _try_batch(api, chunk, target, log):
    """Change one batch inside one transaction, measuring before and after.

    Returns (status, info). status is 'ok', 'moved', 'commit' or 'none'.
    The element is held still by measurement, not by reasoning: change the
    level, regenerate, measure; if it moved, put its offset back by the
    amount it moved; if it still moved, move it back; if anything in the
    batch or connected to it is still out, the whole batch rolls back.
    """
    watch = []
    for item in chunk:
        if item["id"] not in watch:
            watch.append(item["id"])
        for n in api.neighbours(item["id"]):
            if n not in watch:
                watch.append(n)
    before = dict((i, api.snapshot(i)) for i in watch)
    api.begin(u"RevoBIM Level Manager - assign level")
    changed = []
    failed = []
    for item in chunk:
        try:
            ok = api.set_level(item["id"], item["route"], target)
            reason = u"Revit would not set {0}".format(route_label(item["route"]))
        except Exception as ex:
            ok = False
            reason = u"Revit refused: {0}".format(to_text(ex))
        if ok:
            changed.append(item)
        else:
            failed.append((item["id"], reason))
    if not changed:
        api.rollback()
        return "none", {"failed": failed}
    api.regenerate()
    comp = {}
    movers = []
    for item in changed:
        i = item["id"]
        now = api.snapshot(i)
        if has_moved(before[i], now):
            movers.append(item)
            if xy_shift(before[i], now) > MOVE_TOL_FT:
                log(u"  {0} moved sideways after the level change".format(i))
                continue
            dz = z_shift(before[i], now)
            used = api.compensate(i, item["route"], dz)
            comp[i] = list(used)
            log(u"  {0} moved {1}mm; offset put back via {2}".format(
                i, fmt_mm(dz), u", ".join(used) or u"nothing"))
    if movers:
        api.regenerate()
        still = []
        for item in movers:
            i = item["id"]
            now = api.snapshot(i)
            if has_moved(before[i], now) and xy_shift(before[i], now) <= MOVE_TOL_FT:
                dz = z_shift(before[i], now)
                if api.move(i, -dz):
                    comp.setdefault(i, []).append(u"moved back")
                    still.append(i)
                    log(u"  {0} still {1}mm out; moved back".format(i, fmt_mm(dz)))
        if still:
            api.regenerate()
    bad = []
    for i in watch:
        d = deviation(before[i], api.snapshot(i))
        if d > MOVE_TOL_FT:
            bad.append((i, d))
    if bad:
        api.rollback()
        return "moved", {"bad": bad, "failed": failed, "changed": changed}
    if not api.commit():
        return "commit", {"errors": list(api.last_errors()), "failed": failed,
                          "changed": changed}
    return "ok", {"changed": changed, "failed": failed, "comp": comp}


def assign_levels(api, items, target, progress=None, log=None):
    """Associate every item with the target level without moving anything.

    items: [{'id', 'route'}]. api: the adapter (see RevitAdapter / FakeApi).
    Nothing is kept unless the final measurement of every element, and
    everything connected to it, matches where it started.
    """
    log = log or (lambda msg: None)
    progress = progress or (lambda done, total: None)
    res = new_result()
    ids = [it["id"] for it in items]
    held, refused = api.checkout(ids)
    held = set(held)
    for eid, why in refused:
        res["skipped"].append((eid, why))
    work = [it for it in items if it["id"] in held]
    if not work:
        return res
    baseline = {}
    for it in work:
        baseline[it["id"]] = api.snapshot(it["id"])
        for n in api.neighbours(it["id"]):
            if n not in baseline:
                baseline[n] = api.snapshot(n)
    api.group_start(u"RevoBIM Level Manager - assign level")
    done_ids = []
    total = len(work)
    count = 0
    try:
        for chunk in chunks(work, CHUNK):
            status, info = _try_batch(api, chunk, target, log)
            for eid, why in info.get("failed", []):
                res["refused"].append((eid, why))
            if status == "ok":
                for it in info["changed"]:
                    done_ids.append(it["id"])
                res["compensated"].update(info.get("comp", {}))
            elif status != "none":
                log(u"batch of {0} not kept ({1}); one at a time".format(len(chunk), status))
                failed_ids = set([f[0] for f in info.get("failed", [])])
                for it in chunk:
                    if it["id"] in failed_ids:
                        continue
                    st1, inf1 = _try_batch(api, [it], target, log)
                    for eid, why in inf1.get("failed", []):
                        res["refused"].append((eid, why))
                    if st1 == "ok":
                        done_ids.append(it["id"])
                        res["compensated"].update(inf1.get("comp", {}))
                    elif st1 == "moved":
                        bad = inf1.get("bad", [])
                        own = [b for b in bad if b[0] == it["id"]]
                        if own:
                            why = u"would move {0}mm - its offset could not hold it in place".format(
                                fmt_mm(own[0][1]))
                        else:
                            why = u"changing its level moved a connected element ({0})".format(
                                u", ".join([to_text(b[0]) for b in bad]))
                        res["refused"].append((it["id"], why))
                    elif st1 == "commit":
                        errs = inf1.get("errors") or [u"Revit rolled the change back"]
                        res["refused"].append((it["id"], u"Revit refused: " + u"; ".join(errs)))
            count += len(chunk)
            progress(count, total)
        # proof: every change on the target level, then - last word -
        # everything where it started
        route_of = dict((it["id"], it["route"]) for it in work)
        not_on = [i for i in done_ids if api.level_of(i, route_of.get(i)) != target]
        for i in not_on:
            res["refused"].append((i, u"level did not change when read back"))
        done_ids = [i for i in done_ids if i not in set(not_on)]
        moved = []
        for i, snap in baseline.items():
            d = deviation(snap, api.snapshot(i))
            if d > MOVE_TOL_FT:
                moved.append((i, d))
        if moved:
            api.group_rollback()
            res["rolled_back"] = True
            res["moved"] = moved
            res["refused"].extend([(i, u"nothing kept - run rolled back") for i in done_ids])
            res["compensated"] = {}
            log(u"proof failed: {0} element(s) out of place; whole run rolled back".format(len(moved)))
        else:
            api.group_commit()
            res["done"] = done_ids
    except Exception as ex:
        try:
            api.group_rollback()
        except Exception:
            pass
        res["rolled_back"] = True
        res["errors"].append(to_text(ex))
        res["done"] = []
    return res


def result_summary(res):
    if res.get("rolled_back"):
        if res.get("moved"):
            return u"Nothing changed - {0} element(s) would have moved, so the run was rolled back.".format(
                len(res["moved"]))
        return u"Nothing changed - the run hit an error and was rolled back."
    parts = [u"{0} element{1} reassigned".format(
        thousands(len(res["done"])), u"" if len(res["done"]) == 1 else u"s")]
    if res["refused"]:
        parts.append(u"{0} refused".format(len(res["refused"])))
    if res["skipped"]:
        parts.append(u"{0} not borrowed".format(len(res["skipped"])))
    return u", ".join(parts) + u". Nothing moved."


def needs_a_look(res):
    return bool(res.get("rolled_back") or res.get("refused") or res.get("skipped")
                or res.get("errors"))


# =========================================================================
# Deleting a level
# =========================================================================

def single_level(highlighted):
    """The level to delete: exactly one level row highlighted."""
    lids = []
    for key in highlighted or []:
        kind, lid, cat, eid = parse_key(key)
        if kind == "L" and lid not in lids:
            lids.append(lid)
    return lids[0] if len(lids) == 1 else None


def delete_impact(model, source, preview):
    """What deleting `source` does, from Revit's own answer.

    preview: {'items': [{'id', 'kind', 'name', 'sheet'}], 'active_blocked',
    'active_name'} - the ids doc.Delete(level) returned inside a transaction
    that was rolled back. Elements the tool can move are moved first, so they
    are not lost; every other model element in the list goes with the level.
    """
    moving = []
    for cat_ids in model.by_level.get(source, {}).values():
        for i in cat_ids:
            info = model.elements[i]
            if info.get("assignable", True) and info.get("route"):
                moving.append(i)
    moving_set = set(moving)
    views, sheets, lost, other = [], [], [], 0
    for item in preview.get("items", []):
        kind = item.get("kind")
        if kind == "view":
            views.append(to_text(item.get("name")))
        elif kind == "viewport":
            sheet = to_text(item.get("sheet"))
            if sheet and sheet not in sheets:
                sheets.append(sheet)
        elif kind == "sheet":
            sheets.append(to_text(item.get("name")) + u" (deleted)")
        elif kind == "model":
            if item["id"] not in moving_set:
                info = model.elements.get(item["id"])
                why = info.get("note") if info else u""
                lost.append((item["id"], to_text(item.get("name")), why or u"cannot change level"))
        else:
            other += 1
    views.sort(key=natural_key)
    sheets.sort(key=natural_key)
    deleted_sheets = [s for s in sheets if s.endswith(u"(deleted)")]
    return {
        "moving": moving, "views": views, "sheets": sheets, "lost": lost, "other": other,
        "sheets_deleted": len(deleted_sheets), "sheets_affected": len(sheets) - len(deleted_sheets),
        "blocked": bool(preview.get("active_blocked")),   # set even when items is empty
        "active_name": to_text(preview.get("active_name")),
        "error": to_text(preview.get("error", u"")),
    }


def impact_lines(model, source, target, impact, limit=8):
    lv = model.level_by_id.get(source, {}).get("name", u"?")
    tg = model.level_by_id.get(target, {}).get("name", u"(pick a level)") if target else u"(pick a level)"
    def few(names):
        names = list(names)
        if len(names) > limit:
            return u", ".join(names[:limit]) + u" and {0} more".format(len(names) - limit)
        return u", ".join(names)
    if impact["moving"]:
        out = [u"{0} element{1} move to {2} - nothing moves in the model.".format(
            thousands(len(impact["moving"])), u"" if len(impact["moving"]) == 1 else u"s", tg)]
    else:
        out = [u"No elements to move - the level is empty of anything that can change level."]
    if impact["lost"]:
        out.append(u"{0} element{1} cannot change level and will be DELETED with {2}: {3}.".format(
            len(impact["lost"]), u"" if len(impact["lost"]) == 1 else u"s", lv,
            few([u"{0} ({1})".format(n, i) for i, n, why in impact["lost"]])))
    if impact["views"]:
        out.append(u"{0} view{1} will be deleted: {2}.".format(
            len(impact["views"]), u"" if len(impact["views"]) == 1 else u"s", few(impact["views"])))
    else:
        out.append(u"No views will be deleted.")
    out.append(u"Sheets deleted: {0}.".format(impact["sheets_deleted"]))
    if impact["sheets_affected"]:
        out.append(u"{0} sheet{1} lose{2} a view: {3}.".format(
            impact["sheets_affected"], u"" if impact["sheets_affected"] == 1 else u"s",
            u"s" if impact["sheets_affected"] == 1 else u"",
            few([s for s in impact["sheets"] if not s.endswith(u"(deleted)")])))
    if impact["other"]:
        out.append(u"{0} other item{1} go with them (tags, dimensions, sketch planes).".format(
            impact["other"], u"" if impact["other"] == 1 else u"s"))
    return out


def delete_level(api, items, source, target, progress=None, log=None):
    """Move everything that can move to `target`, then delete `source` -
    all inside one TransactionGroup, so it is all or nothing. The delete is
    refused (and everything rolled back) if Revit would still take any of the
    moved elements with the level."""
    log = log or (lambda msg: None)
    res = {"ok": False, "assign": None, "deleted": [], "blocked": [], "reason": u"", "errors": []}
    api.group_start(u"RevoBIM Level Manager - delete level")
    try:
        r = assign_levels(api, items, target, progress, log)
        res["assign"] = r
        if r.get("rolled_back") or r.get("refused") or r.get("skipped"):
            api.group_rollback()
            if r.get("skipped") and not r.get("refused") and not r.get("rolled_back"):
                res["reason"] = (u"{0} element(s) are owned by another user, so they could not move "
                                 u"and the level was not deleted - nothing changed.").format(len(r["skipped"]))
            else:
                res["reason"] = u"Not every element could move to the new level, so the level was not deleted - nothing changed."
            return res
        status, ids, errors = api.delete_level(source, set([it["id"] for it in items]))
        if status == "blocked":
            api.group_rollback()
            res["blocked"] = ids
            res["reason"] = u"Revit would still delete {0} moved element(s) with the level - nothing changed.".format(len(ids))
            return res
        if status != "ok":
            api.group_rollback()
            res["errors"] = list(errors)
            res["reason"] = u"Revit refused to delete the level: " + (u"; ".join(errors) or u"no reason given")
            return res
        api.group_commit()
        res["ok"] = True
        res["deleted"] = ids
        log(u"deleted level {0}: {1} element(s) went with it".format(source, len(ids)))
    except Exception as ex:
        try:
            api.group_rollback()
        except Exception:
            pass
        res["errors"].append(to_text(ex))
        res["reason"] = u"The delete hit an error and was rolled back: " + to_text(ex)
    return res


# =========================================================================
# Isolate in 3D
# =========================================================================

SECTION_MARGIN_MM = 300


def box_around(boxes, margin_ft):
    """One box round every (min xyz, max xyz) given, grown by the margin."""
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    lo = [min([b[0][k] for b in boxes]) - margin_ft for k in range(3)]
    hi = [max([b[1][k] for b in boxes]) + margin_ft for k in range(3)]
    return tuple(lo), tuple(hi)


def default_3d_names(username):
    """Revit's default 3D view names, the user's own first on a workshared model."""
    out = []
    if username:
        out.append(u"{3D - " + to_text(username) + u"}")
    out.append(u"{3D}")
    return out


# =========================================================================
# Easter egg timing
# =========================================================================

SLOW_FLOOR_MS = 250
SLOW_CEILING_MS = 2000


def slow_clicks(times):
    """Three clicks, each gap between 250ms and 2s (event timestamps, ms)."""
    if len(times) < 3:
        return False
    a, b, c = times[-3:]
    for gap in (b - a, c - b):
        if gap < SLOW_FLOOR_MS or gap > SLOW_CEILING_MS:
            return False
    return True


class LogoClicks(object):
    """Counts clicks on the logo, and only the logo. Three in a row, each gap
    250ms to 2s, fire once. A duplicate event (same timestamp - WPF can route
    one click twice), a gap outside that window, or a click anywhere else in
    the window (reset) all start the count again."""

    def __init__(self):
        self.times = []
        self.last = None

    def click(self, timestamp):
        if timestamp == self.last:
            return False
        self.last = timestamp
        if self.times:
            gap = timestamp - self.times[-1]
            if gap < SLOW_FLOOR_MS or gap > SLOW_CEILING_MS:
                self.times = []
        self.times.append(timestamp)
        if len(self.times) >= 3:
            self.times = []
            return True
        return False

    def reset(self):
        self.times = []


# =========================================================================
# Shrink to taskbar - the drawer arithmetic (no WPF, so the bench proves it)
# =========================================================================

DRAWER_SECONDS = 0.28        # length of the slide
DRAWER_TICK_MS = 15          # timer interval
DRAWER_MARGIN = 8            # bar sits this far above the working area's bottom
DRAWER_GAP = 4               # between stacked bars
MOVED_PX = 2                 # a bar dragged further than this counts as moved


def ease_out(p):
    """Cubic ease-out: quick start, soft landing, like a drawer closing."""
    p = max(0.0, min(1.0, float(p)))
    return 1.0 - (1.0 - p) ** 3


def lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def free_slot(used):
    """Lowest slot nobody holds, so a freed slot is reused."""
    used = set(used)
    i = 0
    while i in used:
        i += 1
    return i


def slot_heights(slot, occupied, own_bar):
    """Bar heights of the slots below this one; an empty slot counts as ours."""
    return [occupied.get(i, own_bar) for i in range(slot)]


def shrunk_top(area_bottom, bar, below, margin=DRAWER_MARGIN, gap=DRAWER_GAP):
    """Top of a parked bar: the working area's bottom, less the margin, the
    bars already stacked below it and the gaps between them."""
    return float(area_bottom) - margin - float(bar) - sum([float(b) for b in below]) - gap * len(below)


def bar_moved(parked, now, tol=MOVED_PX):
    return abs(float(now[0]) - float(parked[0])) > tol or abs(float(now[1]) - float(parked[1])) > tol


def expand_rect(saved, parked, now, bar, area):
    """Where the window opens to: back where it was, or - if the bar has been
    dragged somewhere else - upward from where the bar now sits. Always kept
    on the screen the bar is on.

    saved (left, top, width, height), parked / now (left, top),
    area (left, top, right, bottom) in DIPs.
    """
    left, top, width, height = [float(v) for v in saved]
    al, at, ar, ab = [float(v) for v in area]
    if bar_moved(parked, now):
        left = float(now[0])
        top = float(now[1]) + float(bar) - height
    width = min(width, ar - al)
    height = min(height, ab - at)
    left = max(al, min(left, ar - width))
    top = max(at, min(top, ab - height))
    return left, top, width, height


def frame_at(start, end, p):
    """(top, height) part way through a slide."""
    e = ease_out(p)
    return lerp(start[0], end[0], e), lerp(start[1], end[1], e)


# =========================================================================
# Debug table
# =========================================================================

def debug_table(rows, headings):
    """Plain fixed-width table for the debug log."""
    widths = [len(h) for h in headings]
    text_rows = []
    for row in rows:
        cells = [to_text(c) for c in row]
        text_rows.append(cells)
        for i, c in enumerate(cells):
            if i < len(widths):
                widths[i] = min(60, max(widths[i], len(c)))
    def line(cells):
        return u" | ".join([to_text(c)[:widths[i]].ljust(widths[i]) for i, c in enumerate(cells)])
    out = [line(headings), u"-+-".join([u"=" * w for w in widths])]
    for cells in text_rows:
        out.append(line(cells))
    return u"\n".join(out)
