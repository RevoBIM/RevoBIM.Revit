# -*- coding: utf-8 -*-
"""Callout to 3D - version, settings, naming rules, logging.

Nothing in here touches the Revit API, so every rule in it is testable on the
bench under plain CPython (see bench_logic.py).
"""

import c3d_clr  # noqa: F401  assemblies first, always

import os
import re
import datetime

__version__ = "2.7.0"

TOOL_NAME = "Callout to 3D"
SETTINGS_VERSION = 5

MM_PER_FT = 304.8

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


def appdata_dir():
    try:
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    except Exception:
        base = os.path.expanduser("~")
    path = os.path.join(base, "RevoBIM")
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass
    return path


def settings_path():
    return os.path.join(appdata_dir(), "callout_to_3d.txt")


def log_path():
    return os.path.join(appdata_dir(), "callout_to_3d.log")


def log(message):
    """Append one stamped line.  Never raises - logging must not take a run down."""
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        handle = open(log_path(), "a")
        try:
            handle.write("{0}  {1}\n".format(stamp, message))
        finally:
            handle.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# units and ids
# ---------------------------------------------------------------------------


def mm_to_ft(value):
    try:
        return float(value) / MM_PER_FT
    except Exception:
        return 0.0


def ft_to_mm(value):
    try:
        return float(value) * MM_PER_FT
    except Exception:
        return 0.0


def apply_counts(rows, x_count, y_count, depth_mm, size):
    """Write the band's values onto the rows it applies to.

    Returns how many rows actually moved, so the caller can leave the table
    alone when nothing did.  Kept out of the window because it is a rule, not
    a control: the band describes what will be built, and a band that does not
    write through is a preview of one thing and a run of another.
    """
    changed = 0
    for row in rows or []:
        before = (row.get("x_count"), row.get("y_count"),
                  row.get("depth_mm"), row.get("size"))
        after = (x_count, y_count, depth_mm, size)
        if before == after:
            continue
        row["x_count"] = x_count
        row["y_count"] = y_count
        row["depth_mm"] = depth_mm
        row["size"] = size
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# the drawer - shrink to taskbar
#
# Pure arithmetic, kept out of WPF so the bench can prove it: where a bar
# parks, where it stacks, where a window opens back to.  Every area is
# (left, top, width, height) in device-independent units, and a top can be
# negative - a second monitor above the primary has a working area above zero,
# which is exactly what sends a bar to the wrong screen if it is assumed away.
# ---------------------------------------------------------------------------

DRAWER_STEP_MS = 15
DRAWER_LENGTH_MS = 280.0
DRAWER_MARGIN = 4.0          # clear of the taskbar
DRAWER_GAP = 8.0             # between bars stacked above each other


def ease_out(progress):
    """1-(1-p)^3: quick to start, gentle to land.  Clamped, so a late tick
    can never overshoot."""
    try:
        p = float(progress)
    except Exception:
        return 1.0
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


# the three groups stacked in the main window, top to bottom
GROUP_KEYS = ("selection", "array", "sheet")
FOLD_LENGTH_MS = 220.0


def fold_height(start, end, progress):
    """A group sliding open or shut: the body height part way there."""
    return float(start) + (float(end) - float(start)) * ease_out(progress)


def clamp_height(value, low, high):
    """A panel dragged taller or shorter, held between its limits."""
    try:
        value = float(value)
    except Exception:
        value = float(low)
    if value != value:                       # NaN from an unmeasured panel
        value = float(low)
    return max(float(low), min(float(high), value))


GROUP_HEIGHTS = {"selection": 300.0, "array": 300.0, "sheet": 340.0}


def group_height(settings, key):
    """How tall a group's main panel was left, or its default."""
    saved = get_map(settings, "group_heights")
    return clamp_height(saved.get(key, GROUP_HEIGHTS.get(key, 300.0)), 160.0, 1400.0)


SCALES = (1, 2, 5, 10, 20, 25, 50, 75, 100, 200, 250, 500)


def scale_text(scale):
    return u"1:{0}".format(int(scale))


def parse_scale(text):
    """'1:50', '50' or '1 : 50' to 50; anything else to 0 (not set)."""
    raw = u"{0}".format(text or "").replace(" ", "")
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    try:
        value = int(float(raw))
    except Exception:
        return 0
    return value if value > 0 else 0


def three_d_scale_for(row, settings):
    """The 3D's scale: its own when one is set, else as every other view."""
    own = parse_scale(settings.get("3d_scale", ""))
    return float(own) if own else view_scale_for(row, settings)


def callout_scale_for(row, settings):
    """The callout's scale on the sheet: the one asked for, else its own."""
    own = parse_scale(settings.get("callout_scale", ""))
    if own:
        return float(own)
    try:
        return max(1.0, float(row.get("scale") or 50))
    except Exception:
        return 50.0


# which view each scale setting belongs to, for the run and its messages
SCALE_KEYS = (("callout_scale", "callout"), ("3d_scale", "3D"), ("sec_scale", "section"))


def section_scale_for(row, settings):
    """The scale the sections are made at: their own when one is set, else
    the same as every other view."""
    own = parse_scale(settings.get("sec_scale", ""))
    return float(own) if own else view_scale_for(row, settings)


# ---------------------------------------------------------------------------
# the custom setout - a layout the boxes were dragged into
# ---------------------------------------------------------------------------

CUSTOM = "custom"


def custom_moves(settings):
    """role -> (x, y) on the sheet, from layout_custom."""
    out = {}
    for role, text in get_map(settings, "layout_custom").items():
        try:
            x_text, y_text = text.split(",", 1)
            out[role] = (float(x_text), float(y_text))
        except Exception:
            continue
    return out


def set_custom_moves(settings, moves):
    set_map(settings, "layout_custom", dict(
        [(role, u"{0:.0f},{1:.0f}".format(point[0], point[1])) for role, point in moves.items()]))


def resolve_layout(settings, presets):
    """The layout to lay a sheet out with and the moves on top of it.

    A custom setout is a preset plus the positions the boxes were dragged to,
    so the run and the preview both start from the preset and put the moved
    viewports where they were left.
    """
    chosen = settings.get("layout_preset", "columns")
    if chosen == CUSTOM:
        base = settings.get("layout_custom_base", "columns")
        return (base if base in presets else presets[0]), custom_moves(settings)
    return (chosen if chosen in presets else presets[0]), {}


# ---------------------------------------------------------------------------
# headers that stay in sight, and a window stretched to the screen's height
# ---------------------------------------------------------------------------


def dock_sides(header_tops, header_height, viewport_height):
    """For each group header, where it shows: 'top' when it has scrolled up
    out of sight, 'bottom' when it is below what is on show, else None."""
    out = []
    for top in header_tops:
        if top < 0.0:
            out.append("top")
        elif top + float(header_height) > float(viewport_height):
            out.append("bottom")
        else:
            out.append(None)
    return out


def fill_height(viewport, group_height, panel_height, low=160.0, high=1400.0):
    """How tall a group's main panel must be for the whole group to fill the
    scrolling area: what is on show, less everything in the group that is
    not the panel."""
    around = float(group_height) - float(panel_height)
    return clamp_height(float(viewport) - around - 4.0, low, high)


def tall_toggle(area, top, height, saved):
    """Double click on the top or bottom edge: stretch to the screen's full
    height, or back to the height it had.  Returns (top, height, saved)."""
    if saved is not None:
        return saved[0], saved[1], None
    return float(area[1]), float(area[3]), (float(top), float(height))


def match_selection(rows, keys, names):
    """The callout rows Revit had selected when the tool opened - by view id,
    or by name for a callout marker picked in a view, whose element is the
    marker rather than the view it opens."""
    keys = set(keys or [])
    names = set([u"{0}".format(name).strip().lower() for name in (names or []) if name])
    out = []
    for row in rows:
        if row.get("key") in keys or u"{0}".format(row.get("name", "")).strip().lower() in names:
            out.append(row)
    return out


# what the Views box at the top of the selection group offers
VIEW_FILTERS = (("callouts", "Callouts only"),
                ("both", "Callouts and floor plans"),
                ("plans", "Floor plans only"))


def view_filter(settings):
    wanted = str(settings.get("view_filter", "callouts")).strip().lower()
    return wanted if wanted in dict(VIEW_FILTERS) else "callouts"


def keeps_view(row, mode):
    """Whether the Views box shows this row.  A row is a callout when one of
    the callout routes found it; one found only as a cropped plan is a floor
    plan."""
    callout = bool(row.get("is_callout", True))
    if mode == "plans":
        return not callout
    if mode == "both":
        return True
    return callout


def open_groups(settings):
    """Which groups were left open, in their own order; an unknown name in
    the file is ignored rather than trusted."""
    raw = settings.get("groups_open", DEFAULTS["groups_open"])
    named = [part.strip().lower() for part in (raw or "").split("|")]
    return [key for key in GROUP_KEYS if key in named]


def groups_text(open_keys):
    return "|".join([key for key in GROUP_KEYS if key in open_keys])


NAMING_TOKENS = {
    "number": "{level} {abbrev} {callout}  {n} {nn} {nnn} count up until the number is free",
    "name": "{level} {abbrev} {callout}  {d} {dd} count the details on a level",
}


def naming_example(number_pattern, name_pattern, tokens, start=1):
    """What one sheet would be numbered and called, for the live example
    under each rule.  Fresh sets every time, so the example is the first
    free one rather than whatever an earlier keystroke used up."""
    number = sheet_number_for(number_pattern or DEFAULTS["sheet_number_pattern"],
                              tokens, set(), start)
    name = sheet_name_for(name_pattern or DEFAULTS["sheet_name_pattern"], tokens, {})
    return number, name


def unknown_tokens(pattern, allowed):
    """Placeholders in a rule that nothing will fill, so they can be pointed
    at before a sheet ends up called {levle}."""
    found = re.findall(r"\{([^{}]*)\}", pattern or "")
    return [token for token in found if token not in allowed]


SHEET_NUMBER_TOKENS = ("level", "abbrev", "callout", "n", "nn", "nnn")
SHEET_NAME_TOKENS = ("level", "abbrev", "callout", "d", "dd")


def view_scale_for(row, settings):
    """The scale every view for this callout is made at."""
    if str(settings.get("view_scale_rule", "match_callout")).strip().lower() == "fixed":
        return max(1.0, get_float(settings, "view_scale_fixed", 50.0))
    try:
        return max(1.0, float(row.get("scale") or 50))
    except Exception:
        return 50.0


def bar_height(header_height, edge=1.0):
    """The parked bar is the header plus the window's own edge above and
    below it."""
    try:
        return max(24.0, float(header_height) + 2.0 * float(edge))
    except Exception:
        return 50.0


def parked_top(area, bar, below=0):
    """Where a bar parks: on the bottom of the working area, clear of the
    taskbar, above any bars already parked there."""
    top = float(area[1]) + float(area[3]) - DRAWER_MARGIN - float(bar)
    return top - int(below) * (float(bar) + DRAWER_GAP)


def reopen_top(saved_top, saved_height, parked, bar_top, bar, area):
    """Where the window opens back to.

    Left where it parked, it goes back where it came from.  Carried somewhere
    else, it opens UPWARD from where the bar now sits - jumping back to a spot
    the user has already moved on from is the surprise to avoid - and is then
    held inside the working area.
    """
    if abs(float(bar_top) - float(parked)) < 1.0:
        top = float(saved_top)
    else:
        top = float(bar_top) + float(bar) - float(saved_height)
    area_top = float(area[1])
    area_bottom = area_top + float(area[3])
    if top + float(saved_height) > area_bottom:
        top = area_bottom - float(saved_height)
    return max(area_top, top)


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026 - prefer .Value."""
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


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

DEFAULTS = {
    "settings_version": str(SETTINGS_VERSION),

    # appearance
    "theme": "auto",                      # auto | dark | light
    "results": "needed",                  # never | needed | always
    "view_filter": "callouts",            # callouts | both | plans
    "route_viewer": "1",                  # the view markers drawn in the parent views
    "scan_scope": "plans",                # plans | plans_sections | every
    "route_reference": "1",               # GetReferenceCallouts on every view
    "route_marker": "1",                  # the OST_Callouts marker elements
    "route_type": "1",                    # the view family type name
    "route_reference_always": "0",        # run the slow route even when the others answered
    "type_contains": "Callout",           # comma separated; any one matching is enough
    "debug_report": "0",                  # open the full report when the run ends
    "after_run": "ask",                   # ask | always | never - open the new sheets
    "hide_on_sheet": "1",                 # show only callouts not on a sheet yet
    "remember_size": "1",
    "window_w": "1380",
    "window_h": "840",

    # 3D view
    "3d_view_family_type": "",
    "3d_template": "",
    "3d_bottom_offset_mm": "50",
    "3d_top_rule": "view_range",          # next_level | fixed | callout
    "3d_top_fixed_mm": "4000",
    "3d_top_offset_mm": "-200",   # from the top of the band; negative is below it
    "3d_xy_margin_mm": "0",
    "3d_orientation": "se_iso",
    "3d_pitch_degrees": "35",             # above the horizontal, looking down           # se_iso | sw_iso | ne_iso | nw_iso | keep
    "3d_section_box_visible": "1",
    "3d_crop_tight": "1",                 # pull the crop in round the section box
    "3d_crop_margin_mm": "150",           # a little air round it, in model mm
    "3d_crop_active": "1",                # ie "do not crop view" off
    "3d_crop_visible": "1",

    # sections
    "sec_view_family_type": "",
    "sec_template": "",
    "template_follows_type": "1",         # picking a type offers its own template
    "template_list_all": "0",             # offer every template, not just the kind
    "sec_x_count": "1",
    "sec_y_count": "1",
    "sec_depth_mm": "500",
    "sec_top_rule": "match_3d",           # match_3d | fixed
    "sec_side_margin_mm": "250",
    "sec_below_mm": "0",                  # sections reach this far below the bottom level
    "sec_above_mm": "0",                  # and this far above the top of the band
    "sec_tag_rooms": "1",                 # tag the untagged rooms each section cuts
    "sec_crop_grids": "1",                # cut the grids in each section down to its crop
    "sec_grid_inset_mm": "0",             # how far inside the crop the grid ends stop
    "title_gap_mm": "2",                  # viewport titles this far under the view; blank leaves them
    "sec_room_tag_type": "",              # Family : Type, blank for the default room tag
    "sec_room_tag_lift_mm": "1200",       # how far above the floor the tag sits
    "sec_title_on_sheet": "1",            # write the axis label under the viewport
    "sec_title_pattern": "Section {label}",
    "sec_sign": "-1",                     # learned: which way Revit's BasisZ faces
    "sec_flip_x": "0",
    "sec_flip_y": "0",
    "sec_far_clip_active": "1",

    # naming
    "view_name_pattern": "CO_{kind}_{level}_{abbrev}_{n}",
    "kind_token_3d": "3D",
    "kind_token_section": "Section",
    "rename_callouts": "1",
    "callout_rename_pattern": "CO_{callout}_{level}_{n}",
    "abbrev_stopwords": ("documentation,floorplan,floor plan,plan,plans,section,sections,elevation,"
                         "3d,three dimensional,view,views,template,templates,coordination,coord,"
                         "wip,working,issue,model,revit,master,default,standard"),
    "abbrev_drop_numeric": "1",
    "abbrev_case": "camel",               # camel | as_is | upper
    "abbrev_max_tokens": "3",
    "abbrev_source": "callout",           # callout | new_template
    "level_token": "name",                # name | short

    # sheets
    "sheet_size_default": "A1",
    "sheet_sizes": "A0|A1|A2|A3",
    "sheet_titleblocks": "",              # A1=Some Title Block : A0=...  (pipe separated)
    "sheet_number_pattern": "CO_{level}_{nn}",
    "sheet_number_start": "1",
    "sheet_name_pattern": "Callout_{abbrev}_{level} Detail {d}",
    "sheet_group_rule": "per_callout",    # per_callout | per_level
    "callout_on_sheet": "report",         # report | duplicate

    # layout
    "sheet_margin_left_mm": "15",
    "sheet_margin_right_mm": "120",
    "sheet_margin_top_mm": "15",
    "sheet_margin_bottom_mm": "15",
    "sheet_gap_mm": "12",
    "section_gap_mm": "6",                # between one section and the next
    "layout_preset": "columns",           # columns | mirror | rows | plan_left
    "groups_open": "selection",           # which groups the window left open
    "sec_scale": "",                      # blank: as the other views; else 1:n for the sections
    "3d_scale": "",                       # blank: as the other views; else 1:n for the 3D
    "callout_scale": "",                  # blank: the callout keeps its own; else 1:n
    "layout_custom": "",                  # the custom setout: role=x,y on the sheet, mm
    "layout_custom_base": "columns",      # the layout the custom setout was dragged from
    "group_heights": "",                  # selection=300|array=300|sheet=340
    "section_min_gap_mm": "2",            # the gap is squeezed to this before giving up
    "layout_pad_mm": "4",                 # a little clear air round every viewport
    "view_scale_rule": "match_callout",   # match_callout | fixed
    "view_scale_fixed": "50",

    # viewports
    "vp_type_callout": "",
    "vp_type_3d": "",
    "vp_type_section": "",

    # sheet name push
    "push_enabled": "1",
    "push_separator": "_",
    "push_params": "BGL_Sheet Discipline|BGL_Sheet Series|BGL_Sheet Stage",
    "push_overwrite": "1",
    "push_prove": "1",
}

# Keys whose meaning changed in a given settings version are reset on load.
MIGRATIONS = {
    # v2 renamed 3d_top_extra_mm to 3d_top_offset_mm and gave it a real
    # default, so a saved 0 has to be reset rather than carried forward
    2: ["3d_top_offset_mm"],
    # v3 dropped sec_below_level_mm - the sections take the 3D box band
    3: [],
    # v4 opens with only the callout selection group showing, so the saved
    # all-open state from 2.1.0 is not carried forward
    4: ["groups_open"],
    # v5 applies the 3D's top offset to the view range too, and starts it at
    # 200 below the top - a value saved for the level rule alone is not kept
    5: ["3d_top_offset_mm"],
}


def _coerce(text):
    return text if text is not None else ""


def load_settings(path=None):
    """Plain key=value text.  A missing or damaged file falls back to the
    defaults key by key; unknown keys from a newer version are ignored."""
    values = dict(DEFAULTS)
    target = path or settings_path()
    raw = {}
    try:
        if os.path.isfile(target):
            handle = open(target, "r")
            try:
                for line in handle.read().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)      # first '=' only
                    raw[key.strip()] = value
            finally:
                handle.close()
    except Exception as err:
        log("settings load failed: {0}".format(err))
        raw = {}

    try:
        found_version = int(raw.get("settings_version", "0") or "0")
    except Exception:
        found_version = 0

    stale = set()
    for version in sorted(MIGRATIONS.keys()):
        if found_version < version:
            for key in MIGRATIONS[version]:
                stale.add(key)

    for key in DEFAULTS:
        if key in raw and key not in stale:
            values[key] = _coerce(raw[key])
    values["settings_version"] = str(SETTINGS_VERSION)
    return values


def save_settings(values, path=None):
    target = path or settings_path()
    lines = ["# RevoBIM PY - Callout to 3D settings",
             "# plain key=value; the loader splits on the first '=' only"]
    for key in sorted(values.keys()):
        lines.append("{0}={1}".format(key, values[key]))
    try:
        handle = open(target, "w")
        try:
            handle.write("\n".join(lines))
        finally:
            handle.close()
        return True
    except Exception as err:
        log("settings save failed: {0}".format(err))
        return False


def get_int(values, key, fallback=0):
    try:
        return int(str(values.get(key, fallback)).strip())
    except Exception:
        try:
            return int(float(str(values.get(key, fallback)).strip()))
        except Exception:
            return fallback


def get_float(values, key, fallback=0.0):
    try:
        return float(str(values.get(key, fallback)).strip())
    except Exception:
        return fallback


def get_bool(values, key, fallback=False):
    raw = str(values.get(key, "1" if fallback else "0")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_list(values, key):
    raw = str(values.get(key, "") or "")
    return [part.strip() for part in raw.split("|") if part.strip()]


def get_map(values, key):
    """A pipe separated list of name=value pairs, split on the first '='."""
    result = {}
    for part in get_list(values, key):
        if "=" in part:
            name, value = part.split("=", 1)
            result[name.strip()] = value.strip()
    return result


def set_map(values, key, mapping):
    parts = []
    for name in sorted(mapping.keys()):
        parts.append("{0}={1}".format(name, mapping[name]))
    values[key] = "|".join(parts)


# ---------------------------------------------------------------------------
# view template abbreviation
# ---------------------------------------------------------------------------

_TOKEN_SPLIT = re.compile(r"[_\-/\\|\.\s]+")


def _is_numeric_token(token):
    return bool(re.match(r"^[0-9]+[a-zA-Z]?$", token or ""))


def camel(token):
    """Title-case a token but leave an already mixed-case word alone, so
    'RCP' stays 'RCP' and 'drainage' becomes 'Drainage'."""
    if not token:
        return ""
    if token.upper() == token and len(token) <= 4:
        return token                       # an acronym stays an acronym
    if token[:1].isupper() and token[1:] != token[1:].lower():
        return token                       # already mixed case, e.g. AboveCeiling
    return token[:1].upper() + token[1:].lower()


def abbreviate_template(name, settings=None):
    """04_Documentation_Floorplan_Drainage -> Drainage

    The most informative part of a view template's name: split on the usual
    separators, drop leading numbers and the generic words that appear on
    every template, camel case what is left and join it.  Falls back to the
    last token so it can never return nothing.
    """
    settings = settings or DEFAULTS
    if not name:
        return ""
    stop_raw = str(settings.get("abbrev_stopwords", DEFAULTS["abbrev_stopwords"]) or "")
    stops = set([s.strip().lower() for s in stop_raw.split(",") if s.strip()])
    drop_numeric = str(settings.get("abbrev_drop_numeric", "1")).strip() in ("1", "true", "yes", "on")
    try:
        max_tokens = int(str(settings.get("abbrev_max_tokens", "3")).strip())
    except Exception:
        max_tokens = 3
    style = str(settings.get("abbrev_case", "camel")).strip().lower()

    tokens = [t for t in _TOKEN_SPLIT.split(name) if t]

    # multi word stop phrases ("floor plan") are matched across adjacent tokens
    kept = []
    index = 0
    while index < len(tokens):
        pair = None
        if index + 1 < len(tokens):
            pair = "{0} {1}".format(tokens[index], tokens[index + 1]).lower()
        if pair and pair in stops:
            index += 2
            continue
        token = tokens[index]
        index += 1
        if drop_numeric and _is_numeric_token(token):
            continue
        if token.lower() in stops:
            continue
        kept.append(token)

    if not kept:
        kept = [tokens[-1]] if tokens else []
    if max_tokens > 0:
        kept = kept[-max_tokens:]

    if style == "as_is":
        return "".join(kept)
    if style == "upper":
        return "".join([t.upper() for t in kept])
    return "".join([camel(t) for t in kept])


# ---------------------------------------------------------------------------
# name patterns
# ---------------------------------------------------------------------------


def expand(pattern, tokens):
    """Replace {token} placeholders.  An unknown token is left alone rather
    than blanking the name, so a typo in settings is visible."""
    result = pattern or ""
    for key in sorted(tokens.keys(), key=len, reverse=True):
        result = result.replace("{" + key + "}", u"{0}".format(tokens[key]))
    return result


def clean_name(name):
    """Revit will not accept these characters in a view or sheet name."""
    bad = "\\:{}[]|;<>?`~"
    out = []
    for char in (name or ""):
        out.append(" " if char in bad else char)
    text = "".join(out)
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def unique_name(base_pattern, tokens, taken, start=1, limit=999):
    """Expand the pattern with {n} counting up until the name is free.

    ``taken`` is a set of lower case names already in use; the chosen name is
    added to it so a run of calls cannot collide with itself.
    """
    lowered = taken
    number = max(1, int(start or 1))
    while number <= limit:
        local = dict(tokens)
        local["n"] = str(number)
        local["nn"] = "{0:02d}".format(number)
        candidate = clean_name(expand(base_pattern, local))
        if candidate and candidate.lower() not in lowered:
            lowered.add(candidate.lower())
            return candidate
        number += 1
    fallback = clean_name(expand(base_pattern, dict(tokens, n=str(limit + 1))))
    lowered.add(fallback.lower())
    return fallback


def callout_new_name(current_name, level_name, settings, taken):
    """CO_<Callout>_<Level>_1, without stacking the prefix twice."""
    pattern = settings.get("callout_rename_pattern") or DEFAULTS["callout_rename_pattern"]
    base = current_name or ""
    stripped = base
    match = re.match(r"^CO_(.+?)_[^_]*_[0-9]+$", base)
    if match:
        stripped = match.group(1)
    elif base.upper().startswith("CO_"):
        stripped = base[3:]
    tokens = {"callout": stripped, "level": level_name or ""}
    proposed = clean_name(expand(pattern, dict(tokens, n="1")))
    if proposed.lower() == (current_name or "").lower():
        return current_name, False
    return unique_name(pattern, tokens, taken), True


def sheet_number_for(pattern, tokens, taken, start=1, limit=999):
    number = max(1, int(start or 1))
    while number <= limit:
        local = dict(tokens)
        local["n"] = str(number)
        local["nn"] = "{0:02d}".format(number)
        local["nnn"] = "{0:03d}".format(number)
        candidate = clean_name(expand(pattern, local))
        if candidate and candidate.lower() not in taken:
            taken.add(candidate.lower())
            return candidate
        number += 1
    return clean_name(expand(pattern, dict(tokens, n=str(limit + 1))))


def sheet_name_for(pattern, tokens, detail_counts):
    """{d} counts details within one level+abbreviation group."""
    key = u"{0}|{1}".format(tokens.get("level", ""), tokens.get("abbrev", ""))
    detail_counts[key] = detail_counts.get(key, 0) + 1
    local = dict(tokens)
    local["d"] = str(detail_counts[key])
    local["dd"] = "{0:02d}".format(detail_counts[key])
    return clean_name(expand(pattern, local))


def split_for_push(sheet_name, separator, parameters):
    """The sheet name push: split on the separator and pair the pieces with
    the configured parameters in order.  Spare pieces are reported, spare
    parameters are left alone rather than cleared."""
    sep = separator or "_"
    pieces = [p.strip() for p in (sheet_name or "").split(sep)]
    pairs = []
    for index, param in enumerate(parameters):
        if index < len(pieces):
            pairs.append((param, pieces[index]))
    spare = pieces[len(parameters):] if len(pieces) > len(parameters) else []
    return pairs, spare


def short_level(name):
    """A level name reduced to its most useful token, for {level} in short mode."""
    tokens = [t for t in _TOKEN_SPLIT.split(name or "") if t]
    if not tokens:
        return name or ""
    for token in tokens:
        if re.search(r"[0-9]", token):
            return token
    return tokens[-1]


def level_token(name, settings):
    if str(settings.get("level_token", "name")).strip().lower() == "short":
        return short_level(name)
    return name or ""
