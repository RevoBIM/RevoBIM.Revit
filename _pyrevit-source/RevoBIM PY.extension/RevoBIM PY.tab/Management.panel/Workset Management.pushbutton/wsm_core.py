# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : version, settings, palettes and rules.

Nothing in here touches .NET or the Revit API, so every rule the tool runs on
- renaming, filtering, sorting, validation, the delete plan, the spreadsheet
diff and the category claims - is a plain function tested by bench_logic.py
under CPython.

IronPython 2.7 and 3: no f-strings, no print statements, .format() only.
"""

import os
import re

VERSION = "2.3.1"
__version__ = VERSION

TOOL_NAME = "Workset Management"
TOOL_KEY = "workset_management"

APPDATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"),
                           "RevoBIM")
SETTINGS_PATH = os.path.join(APPDATA_DIR, TOOL_KEY + ".txt")
DEBUG_PATH = os.path.join(APPDATA_DIR, TOOL_KEY + "_debug.txt")
ERROR_PATH = os.path.join(APPDATA_DIR, TOOL_KEY + "_last_error.txt")
ROUTINE_DIR = os.path.join(APPDATA_DIR, "workset_routines")
ALIVE_PATH = os.path.join(APPDATA_DIR, TOOL_KEY + "_modeless.txt")

SETTINGS_VERSION = "2"

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "theme": "follow",                  # follow | dark | light
    "tab": "manage",                    # manage | assign
    "auto_editable": "true",
    "new_rows": "10",
    "show_results": "needed",           # needed | always | never
    "hide_empty_categories": "true",
    "subgroup_service_type": "true",
    "last_export_dir": "",
    "debug": "true",
    "width": "1260",
    "height": "820",
}

# version -> keys reset to their default when a file older than it is read
MIGRATIONS = {
    "2": ["theme", "auto_editable", "width", "height"],
}

NEW_ROW_PLACEHOLDER = "<type a new workset name here>"
NEW_ROW_KEY = "NEW"

# Characters Revit refuses in names of this kind.
BAD_NAME_CHARS = ":{}[]|;<>?`~\\"
MAX_NAME_LENGTH = 255

SUBGROUP_BICS = ("OST_CableTray", "OST_CableTrayFitting")
SERVICE_PARAM_NAMES = ("Service Type", "BGL_Service Type", "Service")
NO_SERVICE = "(no service type)"


# ================================================================ text

def to_text(value):
    if value is None:
        return u""
    try:
        return u"{0}".format(value)
    except Exception:
        try:
            return str(value)
        except Exception:
            return u""


def as_bool(value, fallback=False):
    text = to_text(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return fallback


def as_int(value, fallback=0):
    try:
        return int(float(to_text(value).strip()))
    except Exception:
        return fallback


_NUM_RE = re.compile(r"(\d+)")


def natural_key(value):
    """'P-9' before 'P-10' before 'P-100'; case folded."""
    text = to_text(value).lower()
    parts = _NUM_RE.split(text)
    key = []
    for index, part in enumerate(parts):
        if index % 2:
            key.append((1, int(part), u""))
        elif part:
            key.append((2, 0, part))
    return tuple(key)


# ================================================================ settings

def _read_lines(path):
    lines = []
    try:
        import io
        handle = io.open(path, "r", encoding="utf-8-sig")
    except Exception:
        return lines
    try:
        for line in handle:
            lines.append(to_text(line).rstrip(u"\r\n"))
    except Exception:
        pass
    finally:
        handle.close()
    return lines


def _write_lines(path, lines):
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    body = u"\n".join([to_text(line) for line in lines]) + u"\n"
    try:
        import io
        handle = io.open(path, "w", encoding="utf-8")
        try:
            handle.write(body)
        finally:
            handle.close()
        return True
    except Exception:
        return False


def parse_settings(lines):
    """key=value lines -> settings.  Split on the first '=' only; defaults key
    by key; keys from another version ignored; migrations reset keys whose
    meaning or default changed since the file was written."""
    values = dict(DEFAULTS)
    stored = {}
    for line in lines:
        text = to_text(line).strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if key in DEFAULTS:
            stored[key] = value.strip()
    values.update(stored)

    written = as_int(stored.get("settings_version", "1"), 1)
    for version in sorted(MIGRATIONS.keys(), key=lambda v: as_int(v)):
        if written < as_int(version):
            for key in MIGRATIONS[version]:
                values[key] = DEFAULTS.get(key, u"")
    values["settings_version"] = SETTINGS_VERSION
    return values


def settings_lines(values):
    lines = [u"# RevoBIM PY - Workset Management settings"]
    for key in sorted(DEFAULTS.keys()):
        lines.append(u"{0}={1}".format(key, to_text(values.get(key, DEFAULTS[key]))))
    return lines


def load_settings(path=None):
    return parse_settings(_read_lines(path or SETTINGS_PATH))


def save_settings(values, path=None):
    return _write_lines(path or SETTINGS_PATH, settings_lines(values))


# ================================================================ debug log

class Log(object):
    """Lines collected over a run; written out only when debug is on."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.lines = []

    def add(self, text, *args):
        try:
            line = to_text(text).format(*args) if args else to_text(text)
        except Exception:
            line = to_text(text)
        self.lines.append(line)

    def write(self, path=None, header=u""):
        if not self.enabled:
            return False
        out = [u"RevoBIM PY - Workset Management v{0}".format(VERSION)]
        if header:
            out.append(header)
        out.extend(self.lines)
        return _write_lines(path or DEBUG_PATH, out)


# ================================================================ theme

THEMES = ("follow", "dark", "light")
THEME_LABELS = {"follow": u"Auto", "dark": u"Dark", "light": u"Light"}

PALETTES = {
    "dark": {
        "WindowBrush": "#232326",
        "CardBrush": "#2B2B2E",
        "FieldBrush": "#1C1C1F",
        "BarBrush": "#1C1C1F",
        "EdgeBrush": "#3E3E42",
        "ChromeBrush": "#4A4A50",
        "TextBrush": "#E4E4E4",
        "MutedBrush": "#9A9A9E",
        "BlueBrush": "#4FA3E3",
        "OrangeBrush": "#E8912D",
        "GreenBrush": "#3FA75A",
        "GreenHoverBrush": "#4EC06D",
        "RedBrush": "#E0605C",
        "RedFillBrush": "#D9534F",
        "RedSoftBrush": "#3A2424",
        "OrangeSoftBrush": "#3A2E1E",
        "SelectionBrush": "#2B5473",
        "HoverBrush": "#303036",
        "RowAltBrush": "#202023",
        "OnAccentBrush": "#FFFFFF",
        "TickBrush": "#12222E",
        "ShadowBrush": "#66000000",
    },
    "light": {
        "WindowBrush": "#F3F3F5",
        "CardBrush": "#FFFFFF",
        "FieldBrush": "#FAFAFB",
        "BarBrush": "#E6E6EA",
        "EdgeBrush": "#C9C9CF",
        "ChromeBrush": "#B4B4BC",
        "TextBrush": "#1E1E22",
        "MutedBrush": "#6B6B73",
        "BlueBrush": "#1B72BE",
        "OrangeBrush": "#B96A12",
        "GreenBrush": "#2E8546",
        "GreenHoverBrush": "#379A53",
        "RedBrush": "#C0392B",
        "RedFillBrush": "#C9443F",
        "RedSoftBrush": "#FBE4E2",
        "OrangeSoftBrush": "#FCEFDD",
        "SelectionBrush": "#CFE3F5",
        "HoverBrush": "#EEF2F7",
        "RowAltBrush": "#F5F5F7",
        "OnAccentBrush": "#FFFFFF",
        "TickBrush": "#FFFFFF",
        "ShadowBrush": "#33000000",
    },
}


def normalise_theme(name):
    text = to_text(name).strip().lower()
    if text in ("auto", "follow", ""):
        return "follow"
    if text in THEMES:
        return text
    return "follow"


def next_theme(name):
    name = normalise_theme(name)
    return THEMES[(THEMES.index(name) + 1) % len(THEMES)]


def resolve_theme(setting, canvas):
    """setting follow|dark|light, canvas dark|light|None -> dark|light."""
    setting = normalise_theme(setting)
    if setting in ("dark", "light"):
        return setting
    if canvas in ("dark", "light"):
        return canvas
    return "dark"


# ================================================================ names

def name_problem(name):
    """Why Revit would refuse this as a workset name, or ''."""
    text = to_text(name)
    if not text.strip():
        return u"the name is blank"
    if len(text) > MAX_NAME_LENGTH:
        return u"the name is longer than {0} characters".format(MAX_NAME_LENGTH)
    for bad in BAD_NAME_CHARS:
        if bad in text:
            return u"the name contains {0}".format(bad)
    return u""


CASE_MODES = ("keep", "upper", "lower", "title")


_WORD_START = u" -_./("


def title_case(text):
    """First letter of every word capitalised, the rest lower case.  A word
    starts after a space, hyphen, underscore, dot, slash or bracket, so
    'mep-hvac_services' becomes 'Mep-Hvac_Services'."""
    out = []
    start = True
    for character in to_text(text):
        if character in _WORD_START:
            out.append(character)
            start = True
            continue
        out.append(character.upper() if start else character.lower())
        start = False
    return u"".join(out)


def rename_name(name, ops):
    """Apply the bulk rename operations to one name.

    ops keys (all optional): find, replace, match_case, remove_first,
    remove_last, case, prefix, suffix, tidy.
    Order: find/replace, remove characters, case, prefix and suffix, tidy -
    so a prefix is never cut by 'remove first' and never re-cased.
    """
    text = to_text(name)
    find = to_text(ops.get("find", u""))
    if find:
        replace = to_text(ops.get("replace", u""))
        if ops.get("match_case"):
            text = text.replace(find, replace)
        else:
            pattern = re.compile(re.escape(find), re.IGNORECASE)
            text = pattern.sub(lambda match: replace, text)

    first = max(0, as_int(ops.get("remove_first", 0)))
    last = max(0, as_int(ops.get("remove_last", 0)))
    if first:
        text = text[first:]
    if last:
        text = text[:-last] if last < len(text) else u""

    case = to_text(ops.get("case", "keep")).lower()
    if case == "upper":
        text = text.upper()
    elif case == "lower":
        text = text.lower()
    elif case == "title":
        text = title_case(text)

    text = to_text(ops.get("prefix", u"")) + text + to_text(ops.get("suffix", u""))

    if ops.get("tidy"):
        text = u" ".join(text.split())
    return text


def ops_empty(ops):
    return not (to_text(ops.get("find", u"")) or to_text(ops.get("prefix", u"")) or
                to_text(ops.get("suffix", u"")) or as_int(ops.get("remove_first", 0)) or
                as_int(ops.get("remove_last", 0)) or
                to_text(ops.get("case", "keep")).lower() != "keep" or
                ops.get("tidy"))


# ================================================================ filters

_NUM_EXPR = re.compile(r"^\s*(>=|<=|<>|!=|>|<|=)?\s*(-?\d+)\s*$")
_NUM_RANGE = re.compile(r"^\s*(\d+)\s*(?:-|\.\.)\s*(\d+)\s*$")


def numeric_match(number, expr):
    """'>0', '<=10', '=0', '5', '10-50', '!=0'.  Anything else is a substring."""
    expr = to_text(expr).strip()
    if not expr:
        return True
    match = _NUM_RANGE.match(expr)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        return low <= number <= high
    match = _NUM_EXPR.match(expr)
    if match:
        op = match.group(1) or "="
        value = int(match.group(2))
        if op == ">":
            return number > value
        if op == "<":
            return number < value
        if op == ">=":
            return number >= value
        if op == "<=":
            return number <= value
        if op in ("<>", "!="):
            return number != value
        return number == value
    return expr.lower() in to_text(number).lower()


def text_match(value, expr):
    """Every space separated word in expr appears in value, case folded.
    A word starting with '-' must NOT appear."""
    words = to_text(expr).lower().split()
    if not words:
        return True
    haystack = to_text(value).lower()
    for word in words:
        if word.startswith("-") and len(word) > 1:
            if word[1:] in haystack:
                return False
        elif word not in haystack:
            return False
    return True


# ================================================================ the manage table

COLUMNS = ("name", "count", "cats", "editable", "visible", "owner", "change")
COLUMN_TITLES = {
    "name": u"Workset",
    "count": u"Elements",
    "editable": u"Editable",
    "visible": u"Visible in all views",
    "owner": u"Owner",
    "change": u"Change",
    "cats": u"Categories",
}
NUMERIC_COLUMNS = ("count",)
TICK_COLUMNS = ("editable", "visible", "owner", "change")

STATE_NONE = ""
STATE_RENAME = "rename"
STATE_NEW = "new"
STATE_DELETE = "delete"
STATE_MERGE = "merge"
STATE_ERROR = "error"


class WsRow(object):
    """One workset in the manage table, with whatever is staged against it."""

    def __init__(self, key, name, count=0, editable=True, owner=u"",
                 is_new=False, iid=-1, active=False):
        self.key = key
        self.iid = iid
        self.orig = u"" if is_new else to_text(name)
        self.name = to_text(name)
        self.count = int(count or 0)
        self.editable = bool(editable)
        self.visible = True             # Revit's "Visible in all views"
        self.owner = to_text(owner)
        self.is_new = bool(is_new)
        self.active = bool(active)
        self.delete_to = None           # key of the row taking its elements
        self.problem = u""
        self.categories = []            # [(category, count)], biggest first
        self.merge = False              # the delete is a merge into delete_to
        self.colour = NO_COLOUR

    def renamed(self):
        return (not self.is_new) and self.name != self.orig

    def staged(self):
        return self.is_new or self.renamed() or self.delete_to is not None

    def state(self):
        if self.problem:
            return STATE_ERROR
        if self.delete_to is not None:
            return STATE_MERGE if self.merge else STATE_DELETE
        if self.is_new:
            return STATE_NEW
        if self.renamed():
            return STATE_RENAME
        return STATE_NONE

    def effective_name(self):
        """The name this workset will carry once Apply has run; a workset
        being deleted keeps its old name until it goes."""
        if self.delete_to is not None:
            return self.orig
        return self.name


NO_CATEGORY = u"(no category)"
NO_COLOUR = u"Transparent"

GOLDEN = 0.6180339887498949


def _hsv_hex(hue, saturation, value):
    import colorsys
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
    return u"#{0:02X}{1:02X}{2:02X}".format(int(round(red * 255)), int(round(green * 255)),
                                           int(round(blue * 255)))


def distinct_colour(index):
    """The index-th colour: hue stepped by the golden angle, saturation and
    brightness alternating, so neighbours never look alike and every colour is
    a mid tone that reads on a dark or a light canvas."""
    hue = (0.07 + index * GOLDEN) % 1.0
    saturation = (0.78, 0.58, 0.68)[index % 3]
    value = (0.92, 0.80, 0.70)[(index // 3) % 3]
    return _hsv_hex(hue, saturation, value)


def workset_colours(iids):
    """{workset id: '#RRGGBB'}.  Ordered by id, which Revit never reuses, so a
    workset keeps its colour while others are added; the same list always
    gives the same colours, in the table and in the 3D view."""
    ordered = sorted(set(int(i) for i in iids if int(i) >= 0))
    return dict((iid, distinct_colour(place)) for place, iid in enumerate(ordered))


def hex_rgb(text):
    text = to_text(text).lstrip(u"#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except Exception:
        return None


def category_breakdown(counts):
    """{category: count} -> [(category, count)], biggest first, ties in
    natural order."""
    items = [(to_text(name) or NO_CATEGORY, int(count)) for name, count in counts.items()
             if count]
    items.sort(key=lambda item: natural_key(item[0]))
    items.sort(key=lambda item: item[1], reverse=True)
    return items


def category_summary(categories, limit=3):
    """One line for the table: the biggest few, then how many more."""
    if not categories:
        return u""
    parts = [u"{0} {1}".format(name, count) for name, count in categories[:limit]]
    if len(categories) > limit:
        parts.append(u"+{0} more".format(len(categories) - limit))
    return u"  \u00B7  ".join(parts)


def category_text(row):
    """Every category name on the row, for the Categories filter - so
    'tray' finds a workset holding cable tray however far down its list."""
    return u" | ".join([name for name, _ in row.categories])


def row_value(row, column):
    if column == "name":
        return row.name
    if column == "count":
        return row.count
    if column == "cats":
        return category_summary(row.categories)
    if column == "visible":
        return u"" if row.is_new else (u"Yes" if row.visible else u"No")
    if column == "editable":
        return u"Yes" if row.editable else u"No"
    if column == "owner":
        return row.owner or u"(nobody)"
    return u""


def change_text(row, rows_by_key):
    if row.problem:
        return u"\u26A0 " + row.problem
    if row.delete_to is not None:
        target = rows_by_key.get(row.delete_to)
        target_name = target.effective_name() if target is not None else u"?"
        if row.merge:
            return u"Merge into {0} - move {1} element{2}".format(
                target_name, row.count, u"" if row.count == 1 else u"s")
        if row.count:
            return u"Delete - move {0} element{1} to {2}".format(
                row.count, u"" if row.count == 1 else u"s", target_name)
        return u"Delete - it is empty"
    if row.is_new:
        return u"New workset"
    if row.renamed():
        return u"Rename from {0}".format(row.orig)
    return u""


def tick_value(row, column, rows_by_key):
    """The value a column's tick list offers for this row."""
    if column == "change":
        state = row.state()
        return {
            STATE_NONE: u"(no change)",
            STATE_RENAME: u"Rename",
            STATE_NEW: u"New",
            STATE_DELETE: u"Delete",
            STATE_MERGE: u"Merge",
            STATE_ERROR: u"Needs a look",
        }.get(state, u"(no change)")
    return to_text(row_value(row, column))


def any_word_matches(categories, expr):
    """The Categories filter.  Every word must appear in ONE category name
    (so 'cable tray' does not match a workset holding 'Cable' and 'Tray
    Fittings' separately); '-word' rules out a workset holding any category
    with that word."""
    words = to_text(expr).lower().split()
    wanted = [w for w in words if not (w.startswith("-") and len(w) > 1)]
    banned = [w[1:] for w in words if w.startswith("-") and len(w) > 1]
    names = [to_text(name).lower() for name, _ in categories]
    for word in banned:
        if any(word in name for name in names):
            return False
    if not wanted:
        return True
    return any(all(word in name for word in wanted) for name in names)


def row_passes(row, filters, ticks, rows_by_key, exclude=None):
    """filters: column -> text; ticks: column -> set of allowed values or None."""
    for column, expr in filters.items():
        if column == exclude or not to_text(expr).strip():
            continue
        if column in NUMERIC_COLUMNS:
            if not numeric_match(row_value(row, column), expr):
                return False
        elif column == "change":
            if not text_match(change_text(row, rows_by_key), expr):
                return False
        elif column == "cats":
            if not any_word_matches(row.categories, expr):
                return False
        else:
            if not text_match(row_value(row, column), expr):
                return False
    for column, allowed in ticks.items():
        if column == exclude or allowed is None:
            continue
        if tick_value(row, column, rows_by_key) not in allowed:
            return False
    return True


def tick_choices(rows, column, filters, ticks, rows_by_key):
    """Values a column's tick list offers: what the OTHER filters allow, so a
    filter can always be widened again from its own list."""
    seen = set()
    for row in rows:
        if row_passes(row, filters, ticks, rows_by_key, exclude=column):
            seen.add(tick_value(row, column, rows_by_key))
    return sorted(seen, key=natural_key)


def sort_rows(rows, stack):
    """stack: [(column, descending)], most significant first.  Layered least
    significant first so each level keeps its own direction."""
    ordered = list(rows)
    ordered.sort(key=lambda r: natural_key(r.orig or r.name))
    for level in range(len(stack) - 1, -1, -1):
        column, descending = stack[level]
        if column in NUMERIC_COLUMNS:
            ordered.sort(key=lambda r, c=column: row_value(r, c), reverse=descending)
        elif column == "cats":
            ordered.sort(key=lambda r: len(r.categories), reverse=descending)
        elif column == "change":
            ordered.sort(key=lambda r: natural_key(tick_value(r, "change", {})),
                         reverse=descending)
        else:
            ordered.sort(key=lambda r, c=column: natural_key(row_value(r, c)),
                         reverse=descending)
    return ordered


def push_sort(stack, column, add_level, limit=3):
    """A click on a heading.  Plain click: that column alone, flipping if it
    was already the only level.  Shift click: add it as a level, or flip that
    level if it is already in the stack."""
    stack = list(stack)
    for index, (existing, descending) in enumerate(stack):
        if existing == column:
            if add_level or len(stack) == 1:
                stack[index] = (column, not descending)
                return stack
            return [(column, False)]
    if add_level and stack:
        if len(stack) >= limit:
            stack = stack[:limit - 1]
        stack.append((column, False))
        return stack
    return [(column, False)]


def validate(rows):
    """Set row.problem on every row that cannot be applied as staged.
    Returns the number of rows with a problem."""
    by_key = dict((row.key, row) for row in rows)
    for row in rows:
        row.problem = u""

    names = {}
    for row in rows:
        key = row.effective_name().strip().lower()
        names.setdefault(key, []).append(row)

    staying = [row for row in rows if row.delete_to is None]
    if rows and not staying:
        for row in rows:
            row.problem = u"at least one workset has to stay"
        return len(rows)

    problems = 0
    for row in rows:
        if row.delete_to is not None:
            target = by_key.get(row.delete_to)
            if target is None:
                row.problem = u"the workset taking its elements has gone - pick another"
            elif target.delete_to is not None:
                row.problem = u"{0} takes its elements but is being deleted too".format(
                    target.effective_name())
            if row.problem:
                problems += 1
            continue
        if not (row.is_new or row.renamed()):
            continue
        problem = name_problem(row.name)
        if not problem:
            clash = names.get(row.name.strip().lower(), [])
            if len(clash) > 1:
                problem = u"another workset is already called {0}".format(row.name.strip())
        if problem:
            row.problem = problem
            problems += 1
    return problems


def bulk_rename_plan(rows, keys, ops):
    """-> [(key, old, new)] for the rows named by keys whose name changes.
    Rows staged for deletion are left alone."""
    wanted = set(keys)
    plan = []
    for row in rows:
        if row.key not in wanted or row.delete_to is not None:
            continue
        new = rename_name(row.name, ops)
        if new != row.name:
            plan.append((row.key, row.name, new))
    return plan


def stage_deletes(rows, keys, target_key):
    """Stage the rows named by keys for deletion, their elements going to
    target_key.  A new (unapplied) workset is simply dropped.
    Returns (rows, message)."""
    wanted = set(keys)
    if target_key in wanted:
        return rows, u"The workset taking the elements cannot be one being deleted."
    kept = []
    for row in rows:
        if row.key in wanted:
            if row.is_new:
                continue
            row.name = row.orig
            row.delete_to = target_key
            row.merge = False
        kept.append(row)
    for row in kept:
        if row.delete_to is not None and row.delete_to not in [r.key for r in kept]:
            row.delete_to = None
    return kept, u""


def revert(rows, keys=None):
    """Undo whatever is staged on the rows named (all rows when keys is None).
    New rows are dropped; a target that loses its staged delete is kept."""
    out = []
    for row in rows:
        if keys is not None and row.key not in keys:
            out.append(row)
            continue
        if row.is_new:
            continue
        row.name = row.orig
        row.delete_to = None
        row.merge = False
        out.append(row)
    keys_left = set(row.key for row in out)
    for row in out:
        if row.delete_to is not None and row.delete_to not in keys_left:
            row.delete_to = None
            row.merge = False
    return out


def stage_merge(rows, keys, master_key):
    """Merge the rows named by keys into master_key: every other one is staged
    to move its elements onto the master and then go.  The master keeps (or
    regains) its place and any rename staged on it.  New rows hold nothing, so
    they are simply dropped.  Returns (rows, message)."""
    wanted = set(keys)
    if master_key not in wanted:
        return rows, u"The master has to be one of the worksets being merged."
    if len(wanted) < 2:
        return rows, u"Select at least two worksets to merge."
    kept = []
    for row in rows:
        if row.key == master_key:
            row.delete_to = None
            row.merge = False
        elif row.key in wanted:
            if row.is_new:
                continue
            row.name = row.orig
            row.delete_to = master_key
            row.merge = True
        kept.append(row)
    return kept, u""


def delete_targets(rows, deleting_keys):
    """Rows that can take the elements of the ones being deleted."""
    wanted = set(deleting_keys)
    return [row for row in rows
            if row.key not in wanted and row.delete_to is None]


def build_plan(rows):
    """What Apply will do, in the order it does it."""
    by_key = dict((row.key, row) for row in rows)
    plan = {"creates": [], "renames": [], "deletes": []}
    for row in rows:
        if row.problem:
            continue
        if row.delete_to is not None:
            target = by_key.get(row.delete_to)
            if target is None:
                continue
            plan["deletes"].append({
                "iid": row.iid, "name": row.orig, "count": row.count,
                "target_iid": target.iid, "target_name": target.effective_name(),
                "target_new": target.is_new, "merge": row.merge,
            })
        elif row.is_new:
            plan["creates"].append(row.name.strip())
        elif row.renamed():
            plan["renames"].append({"iid": row.iid, "old": row.orig,
                                    "new": row.name.strip()})
    return plan


def plan_count(plan):
    return len(plan["creates"]) + len(plan["renames"]) + len(plan["deletes"])


def plan_lines(plan):
    lines = []
    for name in plan["creates"]:
        lines.append(u"Create   {0}".format(name))
    for item in plan["renames"]:
        lines.append(u"Rename   {0}  ->  {1}".format(item["old"], item["new"]))
    for item in plan["deletes"]:
        if item.get("merge"):
            lines.append(u"Merge    {0}  into  {1}  ({2} elements)".format(
                item["name"], item["target_name"], item["count"]))
        else:
            lines.append(u"Delete   {0}  ({1} elements to {2})".format(
                item["name"], item["count"], item["target_name"]))
    return lines


# ================================================================ spreadsheet diff

def import_changes(sheet_rows, rows):
    """sheet_rows: [(row number, id cell, name cell)] read from the workbook.
    rows: the manage table.

    -> (renames {key: new}, creates [name], skipped [(name, reason)]).

    An id that matches a workset renames it when the name cell differs from
    the model's name.  A name in a row with no id - the green rows - is a new
    workset.  Matching is on id, never on position or name, which is what
    tells a rename apart from a new workset."""
    by_iid = dict((row.iid, row) for row in rows if not row.is_new)
    taken = {}
    for row in rows:
        taken[row.effective_name().strip().lower()] = row.key

    renames = {}
    creates = []
    skipped = []
    seen_ids = set()
    for number, id_cell, name_cell in sheet_rows:
        id_text = to_text(id_cell).strip()
        name = to_text(name_cell).strip()
        if not id_text and not name:
            continue
        if name == NEW_ROW_PLACEHOLDER or name.startswith(u"<"):
            continue
        iid = None
        if id_text and id_text.upper() != NEW_ROW_KEY:
            try:
                iid = int(float(id_text))
            except Exception:
                iid = None

        if iid is not None and iid in by_iid:
            row = by_iid[iid]
            if iid in seen_ids:
                skipped.append((name, u"row {0}: that id appears twice".format(number)))
                continue
            seen_ids.add(iid)
            if not name:
                skipped.append((row.orig, u"row {0}: the name cell was emptied - "
                                          u"worksets are deleted from the table, "
                                          u"not the spreadsheet".format(number)))
                continue
            if name == row.orig:
                continue
            problem = name_problem(name)
            owner = taken.get(name.lower())
            if not problem and owner is not None and owner != row.key:
                problem = u"another workset is already called {0}".format(name)
            if problem:
                skipped.append((name, u"row {0}: {1}".format(number, problem)))
                continue
            taken.pop(row.effective_name().strip().lower(), None)
            taken[name.lower()] = row.key
            renames[row.key] = name
            continue

        if iid is not None:
            skipped.append((name, u"row {0}: id {1} is not a workset in this "
                                  u"model".format(number, iid)))
            continue
        if not name:
            continue
        problem = name_problem(name)
        if not problem and name.lower() in taken:
            problem = u"a workset of that name already exists"
        if problem:
            skipped.append((name, u"row {0}: {1}".format(number, problem)))
            continue
        taken[name.lower()] = u"new"
        creates.append(name)
    return renames, creates, skipped


# ================================================================ assigner

class CategoryEntry(object):
    """One tickable line in a workset's category picker."""

    def __init__(self, key, label, count=0, parent_key=None):
        self.key = key
        self.label = label
        self.count = count
        self.parent_key = parent_key
        self.children = []
        self.element_ids = []


class ModelScan(object):
    def __init__(self):
        self.entries = []               # top level CategoryEntry, sorted
        self.by_key = {}                # key -> CategoryEntry
        self.workset_counts = {}        # workset int id -> element count
        self.workset_categories = {}    # workset int id -> {category: count}
        self.total = 0
        self.error = u""

    def add(self, entry):
        self.by_key[entry.key] = entry
        if entry.parent_key is None:
            self.entries.append(entry)
        else:
            parent = self.by_key.get(entry.parent_key)
            if parent is not None:
                parent.children.append(entry)

    def finish(self):
        self.entries.sort(key=lambda e: natural_key(e.label))
        for entry in self.entries:
            entry.children.sort(key=lambda e: natural_key(e.label))


def with_children(selected, scan):
    """A selection, parents implying every one of their sub groups."""
    keys = set()
    for key in selected:
        keys.add(key)
        entry = scan.by_key.get(key)
        if entry is not None:
            for child in entry.children:
                keys.add(child.key)
    return keys


def build_claims(selections, scan):
    """selections: {workset: set(keys)} -> {key: workset}."""
    claims = {}
    for workset in selections:
        for key in with_children(selections[workset], scan):
            claims[key] = workset
    return claims


def free_for(claims, workset, key):
    holder = claims.get(key)
    return holder is None or holder == workset


def picker_lines(workset, claims, scan, needle=u""):
    """What a workset's picker shows: [(entry, depth, enabled)].

    A category another workset holds is not offered.  A parent whose sub
    groups are partly held elsewhere stays, greyed, with only its free sub
    groups tickable; a parent with none free is not offered at all."""
    needle = to_text(needle).strip().lower()
    out = []
    for entry in scan.entries:
        if not free_for(claims, workset, entry.key):
            continue
        children = [child for child in entry.children
                    if free_for(claims, workset, child.key)]
        if entry.children and not children:
            continue
        enabled = len(children) == len(entry.children)
        hit_parent = (not needle) or (needle in entry.label.lower())
        hit_children = [child for child in children
                        if (not needle) or (needle in child.label.lower())]
        if not hit_parent and not hit_children:
            continue
        out.append((entry, 0, enabled))
        for child in (children if hit_parent else hit_children):
            out.append((child, 1, True))
    return out


def toggle(selected, key, ticked, scan):
    """Tick or untick one line.  Ticking a parent ticks all of its sub groups;
    unticking a sub group releases the parent, which no longer means all."""
    result = set(selected)
    entry = scan.by_key.get(key)
    if ticked:
        result.add(key)
    else:
        result.discard(key)
    if entry is not None:
        for child in entry.children:
            if ticked:
                result.add(child.key)
            else:
                result.discard(child.key)
        if entry.parent_key and not ticked:
            result.discard(entry.parent_key)
        if entry.parent_key and ticked:
            parent = scan.by_key.get(entry.parent_key)
            if parent is not None and all(c.key in result for c in parent.children):
                result.add(parent.key)
    return result


def selection_count(selected, scan):
    """Lines a workset holds, not counting sub groups its parent covers."""
    count = 0
    for key in selected:
        entry = scan.by_key.get(key)
        if entry is not None and entry.parent_key in selected:
            continue
        count += 1
    return count


def element_ids_for(selected, scan):
    """Every element a workset's selection covers, each once."""
    ids = []
    for key in sorted(selected):
        entry = scan.by_key.get(key)
        if entry is None:
            continue
        if entry.parent_key and entry.parent_key in selected:
            continue
        ids.extend(entry.element_ids)
    return ids


# ================================================================ routines

def _esc(text):
    return to_text(text).replace(u"%", u"%25").replace(u";", u"%3B") \
        .replace(u"|", u"%7C").replace(u"=", u"%3D")


def _unesc(text):
    return to_text(text).replace(u"%3D", u"=").replace(u"%7C", u"|") \
        .replace(u"%3B", u";").replace(u"%25", u"%")


def routine_lines(routines):
    lines = [u"# RevoBIM PY - Workset Management saved routines"]
    for name in sorted(routines.keys(), key=natural_key):
        block = routines[name]
        for workset in sorted(block.keys(), key=natural_key):
            keys = [k for k in block[workset] if k]
            if keys:
                lines.append(u"routine|{0}|{1}={2}".format(
                    _esc(name), _esc(workset), u";".join([_esc(k) for k in keys])))
    return lines


def parse_routines(lines):
    """-> {routine: {workset: [key]}}"""
    routines = {}
    for line in lines:
        text = to_text(line).strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        left, right = text.split("=", 1)
        parts = left.split("|")
        if len(parts) != 3 or parts[0] != "routine":
            continue
        name = _unesc(parts[1]).strip()
        workset = _unesc(parts[2]).strip()
        keys = [_unesc(k) for k in right.split(";") if k.strip()]
        if name and workset:
            routines.setdefault(name, {})[workset] = keys
    return routines


def project_key(title):
    name = re.split(r"[\\/]", to_text(title))[-1] or u"project"
    name = re.sub(r"\.rvt$", u"", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9_\-. ]+", u"_", name).strip()
    return name or u"project"


def routine_path(title):
    return os.path.join(ROUTINE_DIR, project_key(title) + ".txt")


def load_routines(title):
    return parse_routines(_read_lines(routine_path(title)))


def save_routine(title, routine, mapping):
    routine = to_text(routine).strip()
    if not routine:
        return False
    routines = load_routines(title)
    routines[routine] = dict((k, list(v)) for k, v in mapping.items() if v)
    return _write_lines(routine_path(title), routine_lines(routines))


def delete_routine(title, routine):
    routines = load_routines(title)
    routines.pop(routine, None)
    return _write_lines(routine_path(title), routine_lines(routines))


# ================================================================ scope boxes

SCOPE_COLUMNS = ("name", "used", "views", "datums", "usedby", "change")
SCOPE_TITLES = {
    "name": u"Scope box",
    "used": u"Used",
    "views": u"Views",
    "datums": u"Levels & grids",
    "usedby": u"Used by",
    "change": u"Change",
}
SCOPE_NUMERIC = ("views", "datums")
SCOPE_TICK = ("used", "change")
SCOPE_DELETE = "delete"


class ScopeRow(object):
    """One scope box, with whatever is staged against it.  Shaped like WsRow
    where they overlap, so rename_name, bulk_rename_plan and revert serve both."""

    def __init__(self, eid, name, views=None, datums=None, workset=u""):
        self.key = u"sb:{0}".format(eid)
        self.eid = eid
        self.iid = eid
        self.orig = to_text(name)
        self.name = to_text(name)
        self.views = sorted(views or [], key=natural_key)      # view names
        self.datums = sorted(datums or [], key=natural_key)    # "Level 01", "Grid A"
        self.workset = to_text(workset)
        self.is_new = False
        self.merge = False
        self.delete_to = None          # SCOPE_DELETE when staged to go
        self.problem = u""

    def used(self):
        return bool(self.views or self.datums)

    def renamed(self):
        return self.name != self.orig

    def staged(self):
        return self.renamed() or self.delete_to is not None

    def effective_name(self):
        return self.orig if self.delete_to is not None else self.name

    def state(self):
        if self.problem:
            return STATE_ERROR
        if self.delete_to is not None:
            return STATE_DELETE
        if self.renamed():
            return STATE_RENAME
        return STATE_NONE


def name_list_summary(names, limit=2):
    if not names:
        return u""
    text = u", ".join(names[:limit])
    if len(names) > limit:
        text += u"  +{0} more".format(len(names) - limit)
    return text


def scope_used_by(row):
    """The Used by cell: views first, then levels and grids."""
    return name_list_summary(list(row.views) + list(row.datums))


def scope_used_full(row):
    """Every user, one a line, for the cell's tooltip."""
    lines = []
    if row.views:
        lines.append(u"Views ({0}):".format(len(row.views)))
        lines.extend([u"  " + name for name in row.views])
    if row.datums:
        lines.append(u"Levels and grids ({0}):".format(len(row.datums)))
        lines.extend([u"  " + name for name in row.datums])
    return u"\n".join(lines) or u"Not used by any view, level or grid."


def scope_value(row, column):
    if column == "name":
        return row.name
    if column == "used":
        return u"Yes" if row.used() else u"No"
    if column == "views":
        return len(row.views)
    if column == "datums":
        return len(row.datums)
    if column == "usedby":
        return scope_used_by(row)
    return u""


def scope_change_text(row):
    if row.problem:
        return u"\u26A0 " + row.problem
    if row.delete_to is not None:
        if not row.used():
            return u"Delete - not used"
        parts = []
        if row.views:
            parts.append(u"{0} view{1}".format(len(row.views), u"" if len(row.views) == 1 else u"s"))
        if row.datums:
            parts.append(u"{0} level/grid{1}".format(len(row.datums),
                                                    u"" if len(row.datums) == 1 else u"s"))
        return u"Delete - {0} lose it".format(u" and ".join(parts))
    if row.renamed():
        return u"Rename from {0}".format(row.orig)
    return u""


def scope_tick_value(row, column):
    if column == "change":
        return {STATE_NONE: u"(no change)", STATE_RENAME: u"Rename",
                STATE_DELETE: u"Delete", STATE_ERROR: u"Needs a look"}.get(row.state(),
                                                                            u"(no change)")
    return to_text(scope_value(row, column))


def scope_passes(row, filters, ticks, exclude=None):
    for column, expr in filters.items():
        if column == exclude or not to_text(expr).strip():
            continue
        if column in SCOPE_NUMERIC:
            if not numeric_match(scope_value(row, column), expr):
                return False
        elif column == "usedby":
            names = [(name, 1) for name in list(row.views) + list(row.datums)]
            if not any_word_matches(names, expr):
                return False
        elif column == "change":
            if not text_match(scope_change_text(row), expr):
                return False
        elif not text_match(scope_value(row, column), expr):
            return False
    for column, allowed in ticks.items():
        if column == exclude or allowed is None:
            continue
        if scope_tick_value(row, column) not in allowed:
            return False
    return True


def scope_tick_choices(rows, column, filters, ticks):
    seen = set()
    for row in rows:
        if scope_passes(row, filters, ticks, exclude=column):
            seen.add(scope_tick_value(row, column))
    return sorted(seen, key=natural_key)


def scope_sort(rows, stack):
    ordered = sorted(rows, key=lambda r: natural_key(r.orig))
    for level in range(len(stack) - 1, -1, -1):
        column, descending = stack[level]
        if column in SCOPE_NUMERIC:
            ordered.sort(key=lambda r, c=column: scope_value(r, c), reverse=descending)
        elif column == "change":
            ordered.sort(key=lambda r: natural_key(scope_tick_value(r, "change")),
                         reverse=descending)
        else:
            ordered.sort(key=lambda r, c=column: natural_key(scope_value(r, c)),
                         reverse=descending)
    return ordered


def scope_validate(rows):
    """Deletes run before renames, so a name freed by a delete can be taken in
    the same Apply; every scope box that stays needs its own name."""
    for row in rows:
        row.problem = u""
    names = {}
    for row in rows:
        if row.delete_to is None:
            names.setdefault(row.name.strip().lower(), []).append(row)
    problems = 0
    for row in rows:
        if row.delete_to is not None or not row.renamed():
            continue
        problem = name_problem(row.name)
        if not problem and len(names.get(row.name.strip().lower(), [])) > 1:
            problem = u"another scope box is already called {0}".format(row.name.strip())
        if problem:
            row.problem = problem
            problems += 1
    return problems


def scope_stage_delete(rows, keys):
    """Stage the rows for deletion; a staged rename on them is dropped."""
    wanted = set(keys)
    for row in rows:
        if row.key in wanted:
            row.name = row.orig
            row.delete_to = SCOPE_DELETE
    return rows


def scope_plan(rows):
    plan = {"deletes": [], "renames": []}
    for row in rows:
        if row.problem:
            continue
        if row.delete_to is not None:
            plan["deletes"].append({"eid": row.eid, "name": row.orig,
                                    "views": len(row.views), "datums": len(row.datums)})
        elif row.renamed():
            plan["renames"].append({"eid": row.eid, "old": row.orig, "new": row.name.strip()})
    return plan


def scope_plan_count(plan):
    return len(plan["deletes"]) + len(plan["renames"])


def scope_plan_lines(plan):
    lines = []
    for item in plan["deletes"]:
        used = u""
        if item["views"] or item["datums"]:
            used = u"  - {0} views and {1} levels/grids lose it".format(item["views"],
                                                                         item["datums"])
        lines.append(u"Delete   {0}{1}".format(item["name"], used))
    for item in plan["renames"]:
        lines.append(u"Rename   {0}  ->  {1}".format(item["old"], item["new"]))
    return lines
