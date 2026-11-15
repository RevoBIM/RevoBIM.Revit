# -*- coding: utf-8 -*-
"""Schematic Builder - pure Python logic.

Nothing in here touches .NET or Revit, so ``bench_logic.py`` can exercise it
under plain CPython: settings load/save and migration, the row encodings used
in the settings file, level abbreviations, view naming, and the whole paper
layout (level lines, room clusters, room boxes).

All layout arithmetic is in PAPER millimetres. The caller converts to model
units with the view scale.
"""
import os
import re

__version__ = "3.4.0"
TOOL_NAME = u"Schematic Builder"
SETTINGS_VERSION = 3

try:
    text_type = unicode  # noqa: F821  (IronPython 2.7)
except NameError:
    text_type = str


def as_text(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    try:
        return text_type(value)
    except Exception:
        try:
            return value.decode("utf-8")
        except Exception:
            return u""


def to_float(text, fallback):
    try:
        return float(as_text(text).strip())
    except Exception:
        return fallback


def to_int(text, fallback):
    try:
        return int(float(as_text(text).strip()))
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# SCHEMATIC TYPES (the tabs)
# ---------------------------------------------------------------------------

# key, tab label, default view name prefix, built (True) or placeholder
TABS = [
    ("ventilation", u"Ventilation", u"SCH_M_Ventilation Schematic", True),
    ("lv", u"LV", u"SCH_E_LV Schematic", True),
    ("drainage", u"Drainage", u"SCH_P_Drainage Schematic", False),
    ("rainwater", u"Rainwater", u"SCH_P_Rainwater Schematic", False),
    ("water", u"Water Services", u"SCH_P_Water Service Schematic", False),
]

TAB_KEYS = [t[0] for t in TABS]

# paper sizes, landscape, mm
SHEETS = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
}

LEVEL_LABEL_FORMATS = [u"{name}", u"{abbr}", u"{abbr} - {name}", u"{name} ({abbr})"]

# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "RevoBIM")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "schematic_builder.txt")

DEFAULTS = {
    "settings_version": as_text(SETTINGS_VERSION),
    "theme": u"follow",               # follow Revit's canvas | dark | light
    "active_tab": u"ventilation",
    "scale": u"1",
    "sheet_size": u"A1",
    "margin_mm": u"20",
    "open_view": u"1",
    "show_results": u"issues",          # issues | always | never
    "level_line_style": u"",
    "room_line_style": u"",
    "level_text_type": u"",
    "room_text_type": u"",
    "room_source": u"room",          # room | element
    "room_name_param": u"Name",      # the parameter on the ROOM
    "room_element_param": u"",       # the parameter on the ELEMENT, when room_source is element

    "level_label": u"{name}",
    "levels": u"",                      # name=>abbr=>1|...
    "room_offset_mm": u"10",
    "room_text_dx_mm": u"3",
    "room_text_dy_mm": u"3",
    "item_gap_mm": u"5",
    "room_gap_mm": u"15",
    "level_clear_mm": u"8",
    "text_gap_mm": u"2",
    "transfer": u"BGL_Instance Mark=>BGL_Instance Mark|Mark=>Mark|Type Mark=>Type Mark",
    "link_param": u"BGL_Linked Element ID",   # written onto every detail item at Create
    "lv_panels_only": u"1",          # only equipment with a panel schedule
    "lv_line_gap_mm": u"18",         # between feeders leaving one panel
    "lv_jog_mm": u"6",               # the jog band's first line above the level line
    "lv_jog_step_mm": u"4",          # between staggered jogs
    "lv_lane_clear_mm": u"4",        # a panel keeps this far from a rising feeder
    "lv_level_clear_mm": u"30",      # panels sit at least this far above their level line
    "lv_circuit_line_style": u"",
    "lv_row_gap_mm": u"28",          # between rows of boards on one floor
    "lv_main_panel": u"",            # the Main LV board, by name or mark
    "lv_stretch_main": u"1",         # stretch a line-based main LV symbol to its slot
    "lv_stretch_over_mm": u"9",      # how far a stretched board runs past its last circuit
    "templates": u"",                          # name=>src::dst;;src::dst|...
    "active_template": u"",
    "assignments": u"",              # project=>detailId::template;;...|next project...
}
for _key, _label, _prefix, _built in TABS:
    DEFAULTS["name_" + _key] = _prefix
    DEFAULTS["browser_" + _key] = u""
    DEFAULTS["equipment_" + _key] = u""

# settings version -> keys reset to default when a file older than it is read
MIGRATIONS = {
    2: [],   # v1 was a JSON file at a different path and is simply ignored
    3: ["theme"],   # 3.4.0: the default became "follow Revit's canvas"
}


def load_settings(path=SETTINGS_FILE):
    data = dict(DEFAULTS)
    stored = {}
    try:
        if os.path.isfile(path):
            handle = open(path, "rb")
            raw = handle.read()
            handle.close()
            try:
                raw = raw.decode("utf-8")
            except Exception:
                raw = as_text(raw)
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith(u"#") or u"=" not in line:
                    continue
                key, value = line.split(u"=", 1)
                stored[key.strip()] = value.strip()
    except Exception:
        stored = {}
    file_version = to_int(stored.get("settings_version"), 1)
    for version in sorted(MIGRATIONS.keys()):
        if file_version < version:
            for key in MIGRATIONS[version]:
                stored.pop(key, None)
    for key in DEFAULTS:
        if key in stored:
            data[key] = stored[key]
    data["settings_version"] = as_text(SETTINGS_VERSION)
    return data


def save_settings(data, path=SETTINGS_FILE):
    lines = [u"# RevoBIM PY - Schematic Builder settings"]
    for key in sorted(data.keys()):
        if key not in DEFAULTS:
            continue
        lines.append(u"{0}={1}".format(key, as_text(data[key]).replace(u"\n", u" ")))
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(path, "wb")
        handle.write((u"\n".join(lines) + u"\n").encode("utf-8"))
        handle.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# ROW ENCODING  (rows separated by | , fields by =>)
# ---------------------------------------------------------------------------

REC = u"|"
FLD = u"=>"
SUB = u";;"      # between the family:type pairs inside one field
PAIR = u"::"     # between a family and its type


def clean_field(value):
    """Scrub the record and field separators only - SUB and PAIR are left
    alone, because an already-encoded pair list is passed through here."""
    return as_text(value).replace(REC, u" ").replace(FLD, u"-").strip()


def clean_name(value):
    return clean_field(value).replace(SUB, u" ").replace(PAIR, u" ").strip()


def encode_rows(rows):
    return REC.join([FLD.join([clean_field(f) for f in row]) for row in rows])


def decode_rows(text, width):
    rows = []
    for record in as_text(text).split(REC):
        if not record.strip():
            continue
        fields = record.split(FLD)
        while len(fields) < width:
            fields.append(u"")
        rows.append([f.strip() for f in fields[:width]])
    return rows


def encode_pairs(pairs):
    """[(family, type)] -> 'family::type;;family::type'."""
    parts = []
    for family, type_name in pairs:
        family = clean_name(family)
        if not family:
            continue
        parts.append(family + PAIR + (clean_name(type_name) or u"*"))
    return SUB.join(parts)


def decode_pairs(text):
    pairs = []
    for chunk in as_text(text).split(SUB):
        chunk = chunk.strip()
        if not chunk:
            continue
        if PAIR in chunk:
            family, type_name = chunk.split(PAIR, 1)
        else:
            family, type_name = chunk, u"*"
        family = family.strip()
        if family:
            pairs.append((family, type_name.strip() or u"*"))
    return pairs


def room_key_of(text):
    """Elements whose room parameter reads the same share one room box."""
    key = as_text(text).strip()
    return key.lower() if key else None


def row_families(row):
    """The model families of an equipment row.

    Field 1 holds the encoded pair list. A row saved by 2.0.0 held a single
    family in field 1 and its type in field 2, so that shape is still read."""
    field = as_text(row[1]) if len(row) > 1 else u""
    if SUB in field or PAIR in field:
        return decode_pairs(field)
    family = field.strip()
    if not family:
        return []
    type_name = as_text(row[2]).strip() if len(row) > 2 else u""
    return [(family, type_name or u"*")]


def pair_text(family, type_name):
    if not family:
        return u""
    if not type_name or type_name == u"*":
        return u"{0} : (all types)".format(family)
    return u"{0} : {1}".format(family, type_name)


def pairs_text(pairs):
    """One line describing the families on a row."""
    if not pairs:
        return u""
    if len(pairs) == 1:
        return pair_text(pairs[0][0], pairs[0][1])
    names = []
    for family, type_name in pairs:
        if family not in names:
            names.append(family)
    shown = u", ".join(names[:3])
    if len(names) > 3:
        shown += u", +{0} more".format(len(names) - 3)
    return u"{0} selected: {1}".format(len(pairs), shown)


# a transfer source can be a parameter name or one of these
TOKENS = [u"{level}", u"{level_abbr}", u"{room}", u"{mark}", u"{type_mark}",
          u"{equipment}", u"{family}", u"{type}"]

# an equipment row is
# [equipment, families, (legacy type), detail_family, detail_type, transfer, stretch]
ROW_WIDTH = 7
TRANSFER_NONE = u"*none*"
TEMPLATE_MARK = u"@"      # a transfer field naming a saved template


def decode_templates(text):
    """'name=>src::dst;;src::dst|...' -> [(name, [(src, dst), ...]), ...]"""
    out = []
    for name, pairs in decode_rows(text, 2):
        if name:
            out.append((name, decode_pairs(pairs)))
    return out


def encode_templates(templates):
    rows = []
    for name, pairs in templates:
        name = clean_name(name)
        if name:
            rows.append([name, encode_pairs(pairs)])
    return encode_rows(rows)


def upsert_template(templates, name, pairs):
    """Replace the template of that name, or add it; returns the new list."""
    name = clean_name(name)
    out = []
    replaced = False
    for existing_name, existing_pairs in templates:
        if existing_name == name:
            out.append((name, list(pairs)))
            replaced = True
        else:
            out.append((existing_name, existing_pairs))
    if not replaced:
        out.append((name, list(pairs)))
    return out


def remove_template(templates, name):
    return [(n, p) for n, p in templates if n != name]


def template_pairs(templates, name):
    for existing_name, pairs in templates:
        if existing_name == name:
            return list(pairs)
    return []


def decode_assignments(text, project):
    """{detail id: template name} for one project."""
    out = {}
    for name, pairs in decode_rows(text, 2):
        if name != clean_name(project):
            continue
        for detail_id, template in decode_pairs(pairs):
            try:
                out[int(detail_id)] = template
            except Exception:
                continue
    return out


def encode_assignments(text, project, mapping):
    """Put this project's assignments back, leaving other projects alone."""
    project = clean_name(project)
    pairs = []
    for detail_id in sorted(mapping.keys()):
        template = clean_name(mapping[detail_id])
        if template:
            pairs.append((as_text(detail_id), template))
    rows = []
    replaced = False
    for name, existing in decode_rows(text, 2):
        if name == project:
            if pairs:
                rows.append([name, encode_pairs(pairs)])
            replaced = True
        else:
            rows.append([name, existing])
    if not replaced and pairs:
        rows.append([project, encode_pairs(pairs)])
    return encode_rows(rows)


def batch_by_template(detail_ids, assignments, templates, fallback):
    """Group the ticked detail items by the template assigned to them.

    An item with no assignment falls back to the template on screen, so
    ticking a few and pressing run still does the obvious thing.

    Returns ([{'template', 'pairs', 'detail_ids'}], [ids with no template])."""
    order = []
    grouped = {}
    orphans = []
    for detail_id in detail_ids:
        name = assignments.get(detail_id) or fallback
        pairs = template_pairs(templates, name) if name else []
        if not pairs:
            orphans.append(detail_id)
            continue
        if name not in grouped:
            grouped[name] = {"template": name, "pairs": pairs, "detail_ids": []}
            order.append(name)
        grouped[name]["detail_ids"].append(detail_id)
    return ([grouped[name] for name in order], orphans)


def keyword_matches(items, text):
    """The entries a search box should be offering.

    Empty text means everything - opening a drop-down must never show a
    narrowed list. Otherwise every word typed has to appear somewhere in the
    entry, so word order does not matter."""
    words = [w for w in as_text(text).lower().split() if w]
    if not words:
        return list(items)
    out = []
    for item in items:
        haystack = as_text(item).lower()
        if not [w for w in words if w not in haystack]:
            out.append(item)
    return out


def row_transfer_mode(row):
    """'inherit'  - use the shared list in Settings
    'none'     - write nothing for this equipment
    'template' - the row names a saved parameter template
    'custom'   - a row saved before templates, carrying its own list"""
    field = as_text(row[5]).strip() if len(row) > 5 else u""
    if not field:
        return "inherit"
    if field == TRANSFER_NONE:
        return "none"
    if field.startswith(TEMPLATE_MARK):
        return "template"
    return "custom"


def row_template_name(row):
    field = as_text(row[5]).strip() if len(row) > 5 else u""
    return field[len(TEMPLATE_MARK):] if field.startswith(TEMPLATE_MARK) else u""


def encode_row_template(name):
    name = clean_name(name)
    return (TEMPLATE_MARK + name) if name else u""


def row_stretch_param(row):
    """The dimension parameter this row's detail item is stretched by."""
    return as_text(row[6]).strip() if len(row) > 6 else u""


def row_transfer_pairs(row):
    if row_transfer_mode(row) != "custom":
        return []
    return decode_pairs(row[5])


def effective_transfer(row, shared_pairs, templates=None):
    """What this equipment row actually writes onto its detail items."""
    mode = row_transfer_mode(row)
    if mode == "none":
        return []
    if mode == "custom":
        return row_transfer_pairs(row)
    if mode == "template":
        return template_pairs(templates or [], row_template_name(row))
    return list(shared_pairs)


def transfer_summary(row, shared_count, templates=None):
    mode = row_transfer_mode(row)
    if mode == "none":
        return u"none - skipped"
    if mode == "template":
        name = row_template_name(row)
        count = len(template_pairs(templates or [], name))
        return u"{0} ({1})".format(name, count) if count else u"{0} - missing".format(name)
    if mode == "custom":
        return u"{0} of its own".format(len(row_transfer_pairs(row)))
    return u"shared ({0})".format(shared_count)


# ---------------------------------------------------------------------------
# PARAMETER TEMPLATES (the Married Element List tab)
# ---------------------------------------------------------------------------

def link_id_of(text):
    """The element id stored in a link parameter, or None if it is not one."""
    text = as_text(text).strip()
    if not text:
        return None
    try:
        value = int(float(text))
    except Exception:
        return None
    return value if value > 0 else None


def parse_transfer(text):
    """'src=>dst|src=>dst' or one pair per line -> [(src, dst), ...]."""
    pairs = []
    for chunk in as_text(text).replace(u"\r", u"").replace(u"\n", REC).split(REC):
        if FLD not in chunk:
            continue
        src, dst = chunk.split(FLD, 1)
        src = src.strip()
        dst = dst.strip()
        if src and dst:
            pairs.append((src, dst))
    return pairs


# ---------------------------------------------------------------------------
# LEVELS
# ---------------------------------------------------------------------------

def abbreviate(name):
    """'Level 02' -> 'L02', 'Ground Floor' -> 'GF', 'Roof' -> 'RO', 'Basement 1' -> 'B1'."""
    words = re.findall(r"[A-Za-z]+|\d+", as_text(name))
    letters = [w for w in words if not w.isdigit()]
    digits = [w for w in words if w.isdigit()]
    if len(letters) >= 2:
        out = u"".join([w[0].upper() for w in letters])
    elif len(letters) == 1:
        out = letters[0][0].upper() if digits else letters[0][:2].upper()
    else:
        out = u""
    return out + u"".join(digits)


def level_rows(settings, level_names):
    """Merge the saved level table with the levels actually in the model.

    Returns [(name, abbr, include)] in the order of level_names."""
    saved = {}
    for name, abbr, include in decode_rows(settings.get("levels", u""), 3):
        saved[name] = (abbr, include != u"0")
    rows = []
    for name in level_names:
        abbr, include = saved.get(name, (u"", True))
        if not abbr:
            abbr = abbreviate(name)
        rows.append((name, abbr, include))
    return rows


def level_bucket(level_id, ticked_ids, known_ids):
    """Where an element's level puts it.

    'ticked'   - a level that is on the schematic
    'unticked' - a real level the user has switched off, so leave the element out
    'unknown'  - no level could be worked out at all, so it needs a home and a note
    """
    if level_id in ticked_ids:
        return "ticked"
    if level_id in known_ids:
        return "unticked"
    return "unknown"


def format_level_label(fmt, name, abbr):
    text = as_text(fmt) or u"{name}"
    return text.replace(u"{name}", as_text(name)).replace(u"{abbr}", as_text(abbr))


# ---------------------------------------------------------------------------
# NAMING
# ---------------------------------------------------------------------------

def next_view_name(prefix, existing_names):
    used = set([as_text(n).strip().lower() for n in existing_names])
    prefix = as_text(prefix).strip() or u"Schematic"
    index = 1
    while True:
        candidate = u"{0} {1}".format(prefix, index)
        if candidate.lower() not in used:
            return candidate
        index += 1


def natural_key(text):
    out = []
    for chunk in re.split(r"(\d+)", as_text(text)):
        if chunk.isdigit():
            out.append((1, int(chunk), u""))
        elif chunk:
            out.append((0, 0, chunk.lower()))
    return out


# ---------------------------------------------------------------------------
# TEXT METRICS (estimates, paper mm)
# ---------------------------------------------------------------------------

def text_width(text, size_mm, width_factor=1.0):
    return len(as_text(text)) * float(size_mm) * 0.62 * float(width_factor)


def text_height(size_mm):
    return float(size_mm) * 1.35


# ---------------------------------------------------------------------------
# WINDOW DRAWER (shrink to the bottom of the screen)
# ---------------------------------------------------------------------------
#
# Bounds are (left, top, width, height) and work areas (left, top, right,
# bottom), all in device independent pixels. A work area is NEVER clamped at
# zero: a monitor above the primary has a negative top, and treating that as
# an error is what sends a parked bar to the wrong screen.

DRAWER_MARGIN = 8.0     # between the parked bar and the bottom of the work area
DRAWER_GAP = 4.0        # between stacked bars (a dialog parked over its owner)
DRAWER_SAME = 1.0       # moved less than this means the bar was not moved


def drawer_park(bounds, work, bar_height, slot=0, margin=DRAWER_MARGIN, gap=DRAWER_GAP):
    """Where a shrunk window goes: only its header bar, just above the bottom
    of the work area it is on, ``slot`` bars up when several are stacked."""
    left, top, width, height = [float(v) for v in bounds]
    w_left, w_top, w_right, w_bottom = [float(v) for v in work]
    bar = max(float(bar_height), 1.0)
    width = min(width, w_right - w_left)
    left = min(max(left, w_left), w_right - width)
    parked_top = w_bottom - margin - bar - slot * (bar + gap)
    return (left, max(parked_top, w_top), width, bar)


def drawer_reopen(now, parked_at, saved, work):
    """Where a parked window opens to.

    Left where it was parked, it goes straight back to where it came from.
    Dragged somewhere else, it opens **upward from where the bar now sits**
    rather than jumping back to a place the user has moved on from - and
    either way it is kept on the work area."""
    n_left, n_top, n_width, n_bar = [float(v) for v in now]
    s_left, s_top, s_width, s_height = [float(v) for v in saved]
    w_left, w_top, w_right, w_bottom = [float(v) for v in work]
    width = min(s_width, w_right - w_left)
    height = min(s_height, w_bottom - w_top)
    moved = parked_at is None or (abs(n_left - parked_at[0]) > DRAWER_SAME
                                  or abs(n_top - parked_at[1]) > DRAWER_SAME)
    if moved:
        left = n_left
        top = n_top + n_bar - height
    else:
        left = s_left
        top = s_top
    left = min(max(left, w_left), w_right - width)
    top = min(max(top, w_top), w_bottom - height)
    return (left, top, width, height)


# ---------------------------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------------------------

def sheet_frame(sheet, margin_mm):
    width, height = SHEETS.get(as_text(sheet).upper(), SHEETS["A1"])
    margin = float(margin_mm)
    return (margin, margin, width - margin, height - margin)   # left, bottom, right, top


def pack_rows(items, max_w, gap):
    """items: [(id, w, h)] -> rows of items no wider than max_w (an oversize
    single item is allowed on a row of its own)."""
    rows = [[]]
    width = 0.0
    for item in items:
        w = item[1]
        if rows[-1] and width + gap + w > max_w:
            rows.append([])
            width = 0.0
        if rows[-1]:
            width += gap
        rows[-1].append(item)
        width += w
    return rows


def block_for_group(group, max_inner_w, p):
    """Size one room cluster.

    The room name sits in the **top left corner of the box**, set in by its
    own small x and y offsets, and the equipment is centred in the room
    beneath it. The box is whichever is wider: the equipment plus its offset
    each side, or the name plus its offset and the room offset.

    Returns w, h, item positions relative to the block's bottom-left corner,
    and the top-left point the room name is written from."""
    boxed = group.get("key") is not None
    gap = p["item_gap"]
    offset = p["offset"] if boxed else 0.0
    text_dx = p.get("text_dx", 3.0) if boxed else 0.0
    text_dy = p.get("text_dy", 3.0) if boxed else 0.0
    items = [(i["id"], i["w"], i["h"]) for i in group["items"]]
    rows = pack_rows(items, max(max_inner_w, 1.0), gap)

    laid = []
    inner_w = 0.0
    y = 0.0
    for index, row in enumerate(rows):
        row_h = max([h for _, _, h in row])
        row_w = sum([w for _, w, _ in row]) + gap * (len(row) - 1)
        laid.append((row, row_w, y))
        inner_w = max(inner_w, row_w)
        y += row_h
        if index < len(rows) - 1:
            y += gap
    inner_h = y

    label_w = group.get("label_w", 0.0) if boxed else 0.0
    label_h = group.get("label_h", 0.0) if boxed else 0.0
    # the name is set in from the top left corner by its own two offsets; the
    # right hand edge keeps the room offset, so a long name widens the room
    block_w = max(inner_w + 2.0 * offset, label_w + text_dx + offset)
    block_h = inner_h + offset
    if boxed:
        block_h += p["text_gap"] + label_h + text_dy
    else:
        block_h += offset

    rel = {}
    for row, row_w, row_y in laid:
        x = (block_w - row_w) / 2.0        # the equipment is centred in the room
        for item_id, w, h in row:
            rel[item_id] = (x, row_y + offset)
            x += w + gap

    return {
        "w": block_w,
        "h": block_h,
        "rel": rel,
        "boxed": boxed,
        "label_top": (text_dx, block_h - text_dy),
    }


def layout_band(groups, x_start, right, p):
    """Lay one level's room clusters out along its line, wrapping into rows
    upwards when the sheet width runs out. Nothing is clipped: the band is as
    tall as its contents need, and the level above is moved up to suit.

    Coordinates are relative to the level line, which is y = 0.

    Returns items {id: (x, y) bottom-left}, boxes [(x0, y0, x1, y1)],
    labels [(x, y_top, text)], rows (how many rows it wrapped into) and
    height (how far above the line it reaches)."""
    max_inner_w = max(right - x_start - 2.0 * p["offset"], 10.0)
    cursor_x = x_start
    cursor_y = p["level_clear"]
    row_h = 0.0
    rows = 1 if groups else 0
    out = {"items": {}, "boxes": [], "labels": [], "rows": rows, "height": 0.0}
    for group in groups:
        block = block_for_group(group, max_inner_w, p)
        if cursor_x > x_start and cursor_x + block["w"] > right:
            cursor_x = x_start
            cursor_y += row_h + p["room_gap"]
            row_h = 0.0
            out["rows"] += 1
        for item_id in block["rel"]:
            rx, ry = block["rel"][item_id]
            out["items"][item_id] = (cursor_x + rx, cursor_y + ry)
        if block["boxed"]:
            out["boxes"].append((cursor_x, cursor_y, cursor_x + block["w"], cursor_y + block["h"]))
            lx, ly = block["label_top"]
            out["labels"].append((cursor_x + lx, cursor_y + ly, group.get("label", u"")))
        cursor_x += block["w"] + p["room_gap"]
        row_h = max(row_h, block["h"])
        out["height"] = max(out["height"], cursor_y + block["h"])
    return out


def level_pitch(band_height, label_height, p):
    """How far the next level line has to sit above this one: clear of this
    level's contents, of its own label, and of the room gap between them."""
    return max(band_height, label_height + p["text_gap"]) + p["room_gap"]


def stack_levels(pitches, frame):
    """Level line heights from the space each level actually needs.

    Where there is room to spare it is shared out evenly, so a light
    schematic still reads as evenly spaced lines. Where a level has wrapped
    into several rows it simply pushes everything above it up.

    Returns the heights, the top of the highest band, and whether it fits."""
    left, bottom, right, top = frame
    if not pitches:
        return [], bottom, True
    total = sum(pitches)
    available = top - bottom
    slack = (available - total) / float(len(pitches)) if available > total else 0.0
    ys = []
    y = bottom
    for pitch in pitches:
        ys.append(y)
        y += pitch + slack
    return ys, y, y <= top + 0.001


def layout_schematic(levels, groups_by_level, frame, p):
    """levels: [(key, label, label_w, label_h)] lowest first.
    groups_by_level: {key: [group, ...]}  (see block_for_group for a group).

    Returns {"lines": [(x0, y, x1)], "level_labels": [(x, y_top, text)],
             "items": {id: (x, y)}, "boxes": [...], "labels": [...],
             "ys": {key: y}, "rows": {key: rows}, "height", "fits"}"""
    left, bottom, right, top = frame
    widest = 0.0
    for key, label, label_w, label_h in levels:
        widest = max(widest, label_w)
    x_start = left + max(widest + 10.0, 25.0)

    bands = []
    pitches = []
    for key, label, label_w, label_h in levels:
        band = layout_band(groups_by_level.get(key, []), x_start, right, p)
        bands.append(band)
        pitches.append(level_pitch(band["height"], label_h, p))
    ys, used_top, fits = stack_levels(pitches, frame)

    out = {"lines": [], "level_labels": [], "items": {}, "boxes": [], "labels": [],
           "ys": {}, "rows": {}, "height": used_top - bottom, "fits": fits, "overflow": []}
    for index, (key, label, label_w, label_h) in enumerate(levels):
        y = ys[index]
        band = bands[index]
        out["ys"][key] = y
        out["rows"][key] = band["rows"]
        out["lines"].append((left, y, right))
        out["level_labels"].append((left, y + p["text_gap"] + label_h, label))
        for item_id in band["items"]:
            x, ry = band["items"][item_id]
            out["items"][item_id] = (x, y + ry)
        for x0, y0, x1, y1 in band["boxes"]:
            out["boxes"].append((x0, y + y0, x1, y + y1))
        for x, y_top, text in band["labels"]:
            out["labels"].append((x, y + y_top, text))
    return out


def layout_params(settings):
    return {
        "offset": to_float(settings.get("room_offset_mm"), 10.0),
        "item_gap": to_float(settings.get("item_gap_mm"), 5.0),
        "room_gap": to_float(settings.get("room_gap_mm"), 15.0),
        "level_clear": to_float(settings.get("level_clear_mm"), 8.0),
        "text_gap": to_float(settings.get("text_gap_mm"), 2.0),
        "text_dx": to_float(settings.get("room_text_dx_mm"), 3.0),
        "text_dy": to_float(settings.get("room_text_dy_mm"), 3.0),
    }


def build_groups(records, room_label_size, room_width_factor):
    """records: [dict(id, level_key, room_key, room_label, sort, w, h)]
    -> {level_key: [group, ...]} sorted by room label then mark."""
    by_level = {}
    for rec in records:
        level = by_level.setdefault(rec["level_key"], {})
        room_key = rec.get("room_key")
        group = level.get(room_key)
        if group is None:
            group = {"key": room_key, "label": rec.get("room_label", u""), "items": []}
            level[room_key] = group
        group["items"].append({"id": rec["id"], "w": rec["w"], "h": rec["h"],
                               "sort": rec.get("sort", u"")})
    out = {}
    for level_key in by_level:
        groups = []
        for room_key in by_level[level_key]:
            group = by_level[level_key][room_key]
            group["items"].sort(key=lambda i: natural_key(i["sort"]))
            if room_key is None:
                # unroomed items stand alone, no box each
                for item in group["items"]:
                    groups.append({"key": None, "label": u"", "items": [item]})
            else:
                group["label_w"] = text_width(group["label"], room_label_size, room_width_factor)
                group["label_h"] = text_height(room_label_size)
                groups.append(group)
        groups.sort(key=lambda g: (1 if g["key"] is None else 0,
                                   natural_key(g["label"]),
                                   natural_key(g["items"][0]["sort"])))
        out[level_key] = groups
    return out
