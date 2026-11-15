# -*- coding: utf-8 -*-
"""Sheet Manager - version, settings and the naming rules.

Nothing in this module touches the Revit API, so bench_logic.py can run every
rule in it under plain CPython with no stubs at all.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import os
import re

__version__ = "1.10.0"

TOOL_NAME = "Sheet Manager"
SETTINGS_FILE = "sheet_manager.txt"

# ====================== settings ======================

# Must be at least the highest key in MIGRATIONS. A migration whose version is
# above this one runs on EVERY load, not once - 1.2.0 to 1.5.0 shipped with this
# at "1" and a migration at "2", so the sheet name mapping was wiped every time
# the tool opened. The bench checks the two agree.
SETTINGS_VERSION = "3"

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "theme": "auto",

    # which sheets get listed
    "include_placeholders": "1",
    "only_in_sheet_list": "0",

    # columns and grouping
    "columns": "",                 # blank - take them from the browser organisation
    "grouping_parameters": "",     # blank - read the current browser organisation
    "group_by": "",                # last used group-by, pipe separated
    "group_by_sort": "1",          # group the table by whatever it is sorted by
    "debug": "0",                  # write and show a full report of the run
    # the sort levels the table was left with, restored when it opens:
    # "column:asc|column:desc", primary first
    "table_sorts": "",
    "preview_sorts": "",           # the same, for Duplicate's preview
    # view template presets: what each template brings with it when it is
    # added to Duplicate's table of sets. One JSON value, keyed by template
    # name, so a preset follows the template into every project.
    "template_presets": "",
    # the parameters the new sheet NAME is pushed into, split on underscores and
    # in order: MECHANICAL SERVICES_VENTILATION_LAYOUT goes to Sheet Name 1, 2
    # and 3. A different job from the browser grouping - the two must never
    # share a default, or the name parts are written over the grouping values.
    "name_parameters": "BGL_Sheet Name 1|BGL_Sheet Name 2|BGL_Sheet Name 3",
    "name_delimiter": "[_]",        # what the sheet name is split on, in brackets

    # behaviour
    "confirm_before_write": "1",
    "show_results": "needed",      # needed | always | never

    # duplicate options, remembered between runs
    "dup_number_find": "",
    "dup_number_replace": "",
    "dup_number_prefix": "",
    "dup_name_find": "",
    "dup_name_replace": "",
    "dup_name_prefix": "",
    "dup_sheet_match_case": "0",
    "dup_write_name_params": "1",
    "dup_copy_sheet_params": "1",
    "dup_copy_titleblock_params": "1",
    "dup_copy_revisions": "0",

    "dup_view_find": "",
    "dup_view_replace": "",
    "dup_view_prefix": "",
    "dup_view_match_case": "0",
    "dup_with_detailing": "1",
    "dup_retain_room_names": "1",
    "dup_grid_extents": "1",
    "dup_parents": "1",
    "dup_all_dependents": "1",
    "dup_place_new_parent": "1",
    "dup_legends": "reuse",
    "dup_include_legends": "0",    # legends from the original sheets: off
    "dup_strip_annotation": "0",   # take text notes and tags off the copies
    "dup_strip_lines": "0",        # take detail lines and filled regions off
    "dup_tag_rooms": "0",          # tag every room, drop '?' room tags
    "find_presets": "",            # saved text-to-find, one line of JSON
    "dup_schedules": "reuse",
    "dup_drafting": "duplicate",
    "dup_templates": "",           # viewtype=templatename pairs, pipe separated
}

# A settings key whose meaning changes needs a migration, not just a new
# default. MIGRATIONS lists the keys each version resets on load.
MIGRATIONS = {
    # the name parameters used to default to the four browser grouping
    # parameters, which is what made the two features fight
    "2": ["name_parameters"],
}

# Keys whose default changed from blank to something: a file older than the
# version takes the new default ONLY where its own value is blank. A value the
# user set is theirs and is kept - a plain migration would throw it away.
FILL_IF_BLANK = {
    # the sheet name push defaults to BGL_Sheet Name 1, 2 and 3
    "3": ["name_parameters"],
}

DUP_OPTION_KEYS = [k for k in DEFAULTS if k.startswith("dup_")]

# the browser grouping parameters to fall back on when neither Settings nor the
# project browser names any - the BGL organisation
DEFAULT_GROUPING = [u"BGL_Sheet Stage", u"BGL_Sheet Discipline",
                    u"BGL_Sheet Series", u"BGL_WIP_Tag"]


def plural(count, word, many=None):
    """'1 sheet', '3 sheets' - no '(s)'. `many` for the irregular ones."""
    try:
        count = int(count)
    except Exception:
        count = 0
    if count == 1:
        return u"1 {0}".format(word)
    return u"{0} {1}".format(count, many or (word + u"s"))


def sorts_to_text(sorts):
    """[(column, ascending)] -> 'column:asc|column:desc', primary first."""
    parts = []
    for column, up in sorts or []:
        if not column:
            continue
        parts.append(u"{0}:{1}".format(column, u"asc" if up else u"desc"))
    return u"|".join(parts)


def sorts_from_text(text, columns=None):
    """The other way. A column the table no longer carries is dropped, as is
    anything that does not read - a sort that cannot be restored is better
    forgotten than half restored. Split on the LAST colon, because a parameter
    name can have one in it."""
    out = []
    seen = set()
    for part in u"{0}".format(text or u"").split(u"|"):
        part = part.strip()
        if u":" not in part:
            continue
        column, direction = part.rsplit(u":", 1)
        column = column.strip()
        direction = direction.strip().lower()
        if not column or direction not in (u"asc", u"desc") or column in seen:
            continue
        if columns is not None and column not in columns:
            continue
        seen.add(column)
        out.append((column, direction == u"asc"))
    return out

MODE_CHOICES = {
    "dup_legends": ["reuse", "duplicate"],
    "dup_schedules": ["reuse", "duplicate"],
    "dup_drafting": ["duplicate", "reuse"],
}

MODE_LABELS = {
    "reuse": "Place the same view on the new sheet",
    "duplicate": "Duplicate it",
}

RESULT_CHOICES = ["needed", "always", "never"]
RESULT_LABELS = {
    "needed": "Only if something needs a look",
    "always": "Always",
    "never": "Never",
}


def settings_folder():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RevoBIM")


def settings_path():
    return os.path.join(settings_folder(), SETTINGS_FILE)


def load_settings(path=None):
    """Plain key=value text, not JSON.

    A missing or damaged file falls back to the defaults key by key, and keys
    from an older version are ignored rather than breaking the load.
    """
    values = dict(DEFAULTS)
    path = path or settings_path()
    raw = {}
    try:
        if os.path.isfile(path):
            handle = open(path, "rb")
            try:
                text = handle.read().decode("utf-8", "replace")
            finally:
                handle.close()
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)   # first = only
                raw[key.strip()] = value.strip()
    except Exception:
        return values

    found_version = raw.get("settings_version", "0")
    reset = set()
    for version in sorted(MIGRATIONS.keys()):
        if _int(found_version) < _int(version):
            for key in MIGRATIONS[version]:
                reset.add(key)
    for version in sorted(FILL_IF_BLANK.keys()):
        if _int(found_version) < _int(version):
            for key in FILL_IF_BLANK[version]:
                if not (raw.get(key) or u"").strip(" |"):
                    reset.add(key)

    for key in values:
        if key in raw and key not in reset:
            values[key] = raw[key]
    values["settings_version"] = SETTINGS_VERSION
    return values


def save_settings(values, path=None):
    path = path or settings_path()
    folder = os.path.dirname(path)
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    lines = ["# RevoBIM Sheet Manager settings"]
    for key in sorted(values.keys()):
        lines.append(u"{0}={1}".format(key, values[key]))
    text = u"\n".join(lines) + u"\n"
    handle = open(path, "wb")
    try:
        handle.write(text.encode("utf-8"))
    finally:
        handle.close()
    return path


def reset_duplicate_options(values):
    for key in DUP_OPTION_KEYS:
        values[key] = DEFAULTS[key]
    return values


def _int(text):
    try:
        return int(str(text).strip())
    except Exception:
        return 0


def as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def bool_text(value):
    return "1" if value else "0"


def split_list(text):
    """Pipe separated list, blanks dropped, order kept, duplicates dropped."""
    out = []
    for part in (text or "").split("|"):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def join_list(items):
    return "|".join([str(i).strip() for i in items if str(i).strip()])


# ====================== element ids ======================

def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026; .Value is the answer."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


# ====================== naming ======================

def apply_find_replace(text, find, replace, match_case=False):
    """Plain text find and replace. No regex - a sheet number full of dots
    would otherwise turn into a wildcard nobody asked for."""
    text = u"" if text is None else u"{0}".format(text)
    if not find:
        return text
    find = u"{0}".format(find)
    replace = u"" if replace is None else u"{0}".format(replace)
    if match_case:
        return text.replace(find, replace)
    pattern = re.compile(re.escape(find), re.IGNORECASE)
    return pattern.sub(lambda m: replace, text)


def apply_rule(text, find, replace, prefix, match_case=False):
    """Find and replace first, then the prefix goes on the front of the result."""
    out = apply_find_replace(text, find, replace, match_case)
    if prefix:
        out = u"{0}{1}".format(prefix, out)
    return out


LINE_TOLERANCE = 0.003          # feet, a shade under a millimetre


def same_line(one, other, tolerance=LINE_TOLERANCE):
    """Whether two lines, given as pairs of xyz tuples, are the same line.

    Either way round: a grid copied from one view into another can come back
    with its ends reported in the opposite order, and that is the same line,
    not a failure to copy.
    """
    if one is None or other is None:
        return one is None and other is None
    forwards = (_close(one[0], other[0], tolerance)
                and _close(one[1], other[1], tolerance))
    backwards = (_close(one[0], other[1], tolerance)
                 and _close(one[1], other[0], tolerance))
    return forwards or backwards


def _close(one, other, tolerance):
    try:
        for index in range(3):
            if abs(one[index] - other[index]) > tolerance:
                return False
    except Exception:
        return False
    return True


def fit_line(current, wanted):
    """Put the wanted line's ends onto the current line.

    `SetCurveInView` refuses anything that is not exactly coincident with the
    datum's own line in the target view - and the curve read out of another
    view is on the same grid but at *that* view's cut plane, so a view
    template that moves the cut plane makes it a parallel line a few hundred
    millimetres above or below, and Revit says no.

    The head and tail are what matter, not the Z. So each end of the wanted
    line is projected onto the current line - same direction, same Z - and the
    two projected points are handed back in the current line's own order, so
    the ends stay the ends they were. Returns None when the projection
    collapses to a point, which is not a line Revit will take either.
    """
    if current is None or wanted is None:
        return None
    origin = current[0]
    direction = _minus(current[1], current[0])
    length = _length(direction)
    if length < 1e-9:
        return None
    direction = tuple(component / length for component in direction)
    projected = []
    for point in wanted:
        along = _dot(_minus(point, origin), direction)
        projected.append(tuple(origin[i] + direction[i] * along
                               for i in range(3)))
    first, second = projected
    if _length(_minus(second, first)) < 1e-6:
        return None
    if _dot(_minus(second, first), direction) < 0:
        first, second = second, first
    return (first, second)


def _minus(one, other):
    return tuple(one[i] - other[i] for i in range(3))


def _dot(one, other):
    return sum(one[i] * other[i] for i in range(3))


def _length(vector):
    return _dot(vector, vector) ** 0.5


def datum_needs_curve(end_kinds, view_specific):
    """Whether a grid's or level's 2D line should be copied into another view.

    Only when at least one end is really view specific. A datum whose ends are
    both 3D has no line of its own - asking for one hands back the model extent,
    and writing it into the other view pins that view to the model extent, which
    is how a duplicated plan ended up with its grids running off the sheet.
    """
    for kind in end_kinds or []:
        if kind is None:
            continue
        if kind == view_specific:
            return True
    return False


def split_slots(text):
    """Like split_list, but a blank keeps its place.

    The name parameters are ordered slots, one per segment of the sheet name,
    so an empty second slot has to go on meaning 'the second segment is not
    written' rather than shuffling the third segment up into its place.
    Trailing blanks are dropped, since they are just unused slots.
    """
    values = [v.strip() for v in u"{0}".format(text or u"").split(u"|")]
    while values and not values[-1]:
        values.pop()
    return values


def join_slots(values):
    out = list(values or [])
    while out and not out[-1]:
        out.pop()
    return u"|".join([u"{0}".format(v or u"") for v in out])


DEFAULT_DELIMITER = u"_"


def delimiter_of(text):
    """The delimiter as set - any text, spaces included - or the default when
    it is empty. Reads the stored form too: the settings file strips every
    value, so a delimiter is kept in brackets (see delimiter_stored) or " - "
    would come back as "-"."""
    text = u"" if text is None else u"{0}".format(text)
    if len(text) >= 2 and text.startswith(u"[") and text.endswith(u"]"):
        text = text[1:-1]
    return text if text != u"" else DEFAULT_DELIMITER


def delimiter_stored(text):
    """The delimiter as it goes into the settings file: in brackets, so the
    file's strip cannot take its spaces."""
    return u"[{0}]".format(delimiter_of(text))


def name_push_plan(name, name_params, reserved, delimiter=DEFAULT_DELIMITER):
    """Which segment of the sheet name goes into which parameter.

    Splitting the sheet name on underscores and pushing the segments out is a
    different job from setting the browser grouping, and the two are only
    related by having been pointed at the same parameters by an unlucky
    default. Where they do overlap the typed grouping value wins, because it
    was chosen and the name segment is merely derived - and the parameter is
    reported as skipped rather than quietly written twice.

    Skipping does not shift the mapping: the segment index still comes from the
    full list, so taking one parameter out - whether because it is left as
    (none) or because the grouping has claimed it - does not move every later
    segment up by one.
    """
    params = list(name_params or [])
    while params and not params[-1]:
        params.pop()
    segments = split_name_segments(name, len(params), delimiter)
    reserved = set(reserved or [])
    writes = []
    skipped = []
    for index, param in enumerate(params):
        if not param:
            continue
        if param in reserved:
            skipped.append(param)
            continue
        writes.append((param, segments[index]))
    return writes, skipped


def titleblock_copy_names(titleblock_names, sheet_names, skip):
    """Which of a title block's parameters are actually its own.

    A title block instance also shows the sheet's parameters - Sheet Number,
    Sheet Name, the issue date and the rest - and writing one of those writes
    through to the sheet. So anything the sheet itself carries is not the title
    block's to copy: it has already been copied onto the sheet, where it
    belongs. Getting this wrong put the old sheet number back on the new sheet
    and cost the whole transaction.
    """
    belongs_to_the_sheet = set(sheet_names or []) | set(skip or [])
    return [name for name in (titleblock_names or [])
            if name not in belongs_to_the_sheet]


def example_line(lead, before, after):
    """The worked example under a find and replace pair. A rule that has not
    changed anything says so rather than showing the same text twice with an
    arrow between it, which reads as though it has done something."""
    before = before or u""
    after = after or u""
    if before == after:
        return u"{0}  {1}  -  unchanged".format(lead, before)
    return u"{0}  {1}   \u2192   {2}".format(lead, before, after)


def unique_name(base, taken, separator=u" "):
    """Revit will not take a name that already exists, so step it along."""
    base = u"" if base is None else u"{0}".format(base)
    if not base:
        base = u"Unnamed"
    key = base.strip().lower()
    if key not in taken:
        taken.add(key)
        return base
    index = 2
    while True:
        candidate = u"{0}{1}{2}".format(base, separator, index)
        if candidate.strip().lower() not in taken:
            taken.add(candidate.strip().lower())
            return candidate
        index += 1
        if index > 9999:
            taken.add(candidate.strip().lower())
            return candidate


_NAT = re.compile(r"(\d+)")


def natural_key(text):
    """Drawing numbers sort as people read them: A9 before A10."""
    text = u"" if text is None else u"{0}".format(text)
    parts = _NAT.split(text)
    key = []
    for index, part in enumerate(parts):
        if index % 2:
            key.append((1, int(part), u""))
        elif part:
            key.append((0, 0, part.lower()))
    if not key:
        key.append((0, 0, u""))
    return key


def split_name_segments(name, count, delimiter=DEFAULT_DELIMITER):
    """Split a sheet name on the delimiter (underscore unless set otherwise)
    onto `count` parameters.

    Segments past the last parameter are joined back onto it with the same
    delimiter, so nothing is thrown away - the same rule Sheet Management uses.
    """
    name = u"" if name is None else u"{0}".format(name)
    delimiter = delimiter_of(delimiter)
    if count <= 0:
        return []
    parts = name.split(delimiter)
    if len(parts) <= count:
        out = [p.strip() for p in parts] + [u""] * (count - len(parts))
        return out
    # each part is trimmed: "MECH - VENT" split on "-" must not write "MECH "
    out = [p.strip() for p in parts[:count - 1]]
    out.append(delimiter.join(parts[count - 1:]).strip())
    return out


# ====================== the preview ======================

def preview_sheets(sources, rules, existing_numbers):
    """Work out every new sheet number and name, and flag the clashes.

    `sources`  list of dicts with 'number' and 'name'
    `rules`    dict of find/replace/prefix/match_case for number and name
    Returns a list of dicts the preview table draws straight from.

    Sheet numbers must be unique in a Revit project and are not auto-stepped:
    a clash is reported red rather than quietly renamed, because a number is a
    decision. Sheet names are not stepped either, and for the opposite reason -
    Revit is perfectly happy with two sheets of the same name, so making one up
    would be inventing a difference nobody asked for. View names are the ones
    that have to be unique, and those are stepped.
    """
    taken_numbers = set([u"{0}".format(n).strip().lower() for n in existing_numbers])
    rows = []
    for source in sources:
        number = apply_rule(source.get("number"), rules.get("number_find"),
                            rules.get("number_replace"), rules.get("number_prefix"),
                            rules.get("match_case"))
        name = apply_rule(source.get("name"), rules.get("name_find"),
                          rules.get("name_replace"), rules.get("name_prefix"),
                          rules.get("match_case"))
        status = "ok"
        note = u""
        key = number.strip().lower()
        if not number.strip():
            status = "bad"
            note = u"the new sheet number is empty"
        elif key in taken_numbers:
            status = "bad"
            note = u"sheet number already exists"
        elif key == u"{0}".format(source.get("number", u"")).strip().lower():
            status = "warn"
            note = u"same number as the source - set a find and replace or a prefix"
        if status != "bad":
            taken_numbers.add(key)
        rows.append({
            "id": source.get("id"),
            "old_number": source.get("number"),
            "new_number": number,
            "old_name": source.get("name"),
            "new_name": name,
            "status": status,
            "note": note,
        })
    return rows


def preview_views(records, rules, existing_names):
    """New names for every view that will actually be created.

    `records` list of dicts with 'name', 'action' and 'kind'. Only records whose
    action creates something get renamed; a reused legend keeps its name.
    """
    taken = set([u"{0}".format(n).strip().lower() for n in existing_names])
    rows = []
    for record in records:
        action = record.get("action", "duplicate")
        if action == "reuse":
            new_name = record.get("name")
        else:
            new_name = apply_rule(record.get("name"), rules.get("find"),
                                  rules.get("replace"), rules.get("prefix"),
                                  rules.get("match_case"))
            new_name = unique_name(new_name, taken)
        row = dict(record)
        row["new_name"] = new_name
        rows.append(row)
    return rows


# ====================== the found text, highlighted ======================

def highlight_spans(text, needle, match_case=False):
    """`text` cut into (piece, found) pairs, every place `needle` appears
    marked found - what the source sheet list paints bold and coloured, so
    what a find will catch can be seen before anything is made.

    It finds what apply_find_replace replaces: the same case rule, every
    occurrence, left to right, never overlapping.
    """
    text = u"{0}".format(text or u"")
    needle = u"{0}".format(needle or u"")
    if not needle or not text:
        return [(text, False)] if text else []
    haystack = text if match_case else text.lower()
    wanted = needle if match_case else needle.lower()
    spans = []
    start = 0
    while True:
        at = haystack.find(wanted, start)
        if at < 0:
            break
        if at > start:
            spans.append((text[start:at], False))
        spans.append((text[at:at + len(needle)], True))
        start = at + len(needle)
    if start < len(text):
        spans.append((text[start:], False))
    return spans


def found_in(text, needle, match_case=False):
    """Whether highlight_spans would mark anything."""
    return any(found for _piece, found in highlight_spans(text, needle, match_case))


def views_found(names, needle, match_case=False, most=3):
    """The view names a view find will catch, the first `most` of them in the
    order given, and how many more there are."""
    hits = [n for n in names if found_in(n, needle, match_case)]
    return hits[:most], max(0, len(hits) - most)


# ====================== sheets picked before opening ======================

def picked_sheet_ids(selected, sheet_ids):
    """The ids among `selected` that are sheets the tool lists, in the order
    the tool lists them. Anything else selected - a view, a wall - is not a
    sheet and is not a filter."""
    wanted = set(selected or [])
    return [i for i in sheet_ids if i in wanted]


# ====================== the shrink-to-taskbar drawer ======================
#
# The arithmetic of the drawer, kept here so the bench can prove it: where a
# parked bar sits, how bars stack, and where a window opens back to. The
# window side - timers, visibility, the header - lives in shtm_ui.Drawer.

DRAWER_MS = 280
DRAWER_TICK_MS = 15
DRAWER_MARGIN = 8
DRAWER_GAP = 4


def ease_out(progress):
    """Cubic ease-out, 0 to 1: quick off the mark, settling at the end."""
    progress = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - progress) ** 3


def between(start, end, progress):
    return start + (end - start) * ease_out(progress)


def free_slot(taken):
    """The lowest slot number nobody is parked in. Slot 0 is nearest the
    taskbar; a bar that leaves frees its slot for the next one."""
    taken = set(taken or [])
    slot = 0
    while slot in taken:
        slot += 1
    return slot


def parked_top(work_top, work_height, bar_height, below=None,
               margin=DRAWER_MARGIN, gap=DRAWER_GAP):
    """Where a parked bar's top edge sits: `margin` above the bottom of the
    working area (clear of the taskbar), stacked over the bars in `below` -
    the heights of the bars in the lower slots - with `gap` between."""
    bottom = work_top + work_height - margin
    for height in below or []:
        bottom -= height + gap
    return bottom - bar_height


def opened_top(saved_top, full_height, parked_at, bar_top, work_top, work_height):
    """Where a window opens back to.

    Not moved while parked: exactly where it was. Carried somewhere else (more
    than 2px): it opens upward from where the bar now sits, so the header
    stays under the cursor's eye - kept on that screen."""
    if abs(bar_top - parked_at) <= 2:
        return saved_top
    top = bar_top + 0.0
    if top + full_height > work_top + work_height:
        top = work_top + work_height - full_height
    return max(work_top, top)


# ====================== view templates: names and values ======================

def copy_name(name, taken, word=u"Copy"):
    """What a duplicated template is called: '<name> Copy', then
    '<name> Copy 2' and on, never one already taken."""
    return unique_name(u"{0} {1}".format(name, word).strip(), taken)


def parse_scale(text):
    """'1 : 50', '1:50' or '50' as 50; None for anything that is not a
    whole scale of 1 or more."""
    text = u"{0}".format(text or u"").replace(u" ", u"")
    if u":" in text:
        lead, _sep, text = text.partition(u":")
        if lead not in (u"1", u""):
            return None
    try:
        value = int(float(text))
    except (TypeError, ValueError):
        return None
    if value < 1 or float(text) != value:
        return None
    return value


def scale_text(value):
    try:
        return u"1 : {0}".format(int(value))
    except (TypeError, ValueError):
        return u""


def template_changes(rows, edits, includes, name_before, name_after):
    """What Apply on the template editor has to write: only what differs from
    what was read. Returns {"name": new name or None, "values": {id: text},
    "include": {id: bool}}."""
    values = {}
    include = {}
    by_id = dict([(r["id"], r) for r in rows])
    for key in edits:
        row = by_id.get(key)
        if row is None or not row.get("editable"):
            continue
        if u"{0}".format(edits[key]) != u"{0}".format(row.get("value", u"")):
            values[key] = edits[key]
    for key in includes:
        row = by_id.get(key)
        if row is not None and bool(includes[key]) != bool(row.get("include")):
            include[key] = bool(includes[key])
    name = (name_after or u"").strip()
    return {"name": name if name and name != name_before else None,
            "values": values, "include": include}


def near_level(z, elevation, tolerance=1.0):
    """Whether a room's point (in feet, Revit's internal unit, both measured
    from the internal origin) sits on a level: within a foot either way - a
    linked architectural floor level is often a little above or below the
    MEP model's own level, and the next storey is metres away."""
    try:
        return abs(float(z) - float(elevation)) <= float(tolerance)
    except (TypeError, ValueError):
        return False


def flag_changes(rows, edits, fields):
    """{id: {field: new value}} for every row whose ticks differ from what was
    read - the categories and filters on the template editor's V/G tabs."""
    out = {}
    by_id = dict([(r["id"], r) for r in rows])
    for key in edits:
        row = by_id.get(key)
        if row is None:
            continue
        changed = {}
        for field in fields:
            if field in edits[key] and bool(edits[key][field]) != bool(row.get(field)):
                changed[field] = bool(edits[key][field])
        if changed:
            out[key] = changed
    return out


MM_PER_FOOT = 304.8


def parse_mm(text):
    """A length typed in millimetres as feet, or None. '1200', '1200 mm',
    '-300', '2,300' all read."""
    text = u"{0}".format(text or u"").strip().lower().replace(u"mm", u"")
    text = text.replace(u",", u"").replace(u" ", u"")
    try:
        return float(text) / MM_PER_FOOT
    except (TypeError, ValueError):
        return None


def mm_text(feet):
    try:
        value = float(feet) * MM_PER_FOOT
    except (TypeError, ValueError):
        return u""
    rounded = round(value, 1)
    if rounded == int(rounded):
        return u"{0}".format(int(rounded))
    return u"{0}".format(rounded)


def range_changes(rows, edits):
    """{plane: {"level": key, "offset": feet}} for each view range plane whose
    level or offset was changed. An offset that does not read is reported back
    under "bad" rather than written."""
    out = {}
    bad = []
    by_plane = dict([(r["plane"], r) for r in rows])
    for plane in edits:
        row = by_plane.get(plane)
        if row is None:
            continue
        edit = edits[plane]
        change = {}
        if edit.get("level") and edit["level"] != row.get("level"):
            change["level"] = edit["level"]
        if "offset" in edit and u"{0}".format(edit["offset"]).strip() != row.get("offset_text"):
            feet = parse_mm(edit["offset"])
            if feet is None:
                bad.append(plane)
            else:
                change["offset"] = feet
        if change:
            out[plane] = change
    return out, bad


def full_height(work_top, work_height, top, height, saved):
    """A double click on a window's top or bottom edge: the first stretches it
    to the full height of its screen's working area and keeps where it was;
    the next puts it back. Returns (top, height, saved) - saved is None once
    it is back."""
    if saved is not None:
        return saved[0], saved[1], None
    return work_top, work_height, (top, height)
