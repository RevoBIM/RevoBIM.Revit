# =========================================================================
# Family Editor Tools - core
#
# Version, settings, the shared parameter file parser, templates and the
# preset stores.  NOTHING in this module touches the Revit API or .NET, so
# every rule in it is a plain function that can be run under CPython on the
# bench with no Revit and no window.
# =========================================================================

import os
import re

__version__ = u"1.6.0"

TOOL_NAME = u"Family Editor Tools"

# =========================================================================
# Paths
# =========================================================================

def appdata_root():
    base = os.environ.get(u"APPDATA") or os.path.expanduser(u"~")
    return os.path.join(base, u"RevoBIM")


def tool_root():
    return os.path.join(appdata_root(), u"family_editor_tools")


def settings_path():
    return os.path.join(appdata_root(), u"family_editor_tools.txt")


def templates_dir():
    return os.path.join(tool_root(), u"parameter_templates")


def presets_path(kind):
    return os.path.join(tool_root(), u"{0}_presets.txt".format(kind))


def log_path():
    return os.path.join(appdata_root(), u"family_editor_tools.log")


def diagnostics_path():
    return os.path.join(appdata_root(), u"fet_diagnostics.txt")


def ensure_dir(path):
    try:
        if path and not os.path.isdir(path):
            os.makedirs(path)
        return True
    except Exception:
        return False


# =========================================================================
# Settings - plain key=value text, split on the FIRST = only
# =========================================================================

SETTINGS_VERSION = 1

DEFAULTS = {
    u"settings_version": u"1",
    u"theme": u"follow",                 # follow | dark | light
    u"last_spf": u"",
    u"default_binding": u"type",         # type | instance
    u"default_group": u"Data",
    u"group_by_spf_group": u"on",
    u"width_mm": u"600",
    u"depth_mm": u"400",
    u"height_mm": u"900",
    u"plane_extent_mm": u"1500",
    u"dim_offset_mm": u"250",
    u"dim_step_mm": u"150",
    u"clearance_mm": u"800",
    u"radius_mm": u"300",
    u"param_width": u"Width",
    u"param_depth": u"Depth",
    u"param_height": u"Height",
    u"param_clearance": u"Clearance",
    u"param_radius": u"Radius",
    u"layout_params": u"",
    u"last_scan_source": u"",

    # Family icon
    u"icon_view_name": u"Thumbnail View",
    u"icon_3d_style": u"Realistic",
    u"icon_2d_style": u"HiddenLine",
    u"icon_3d_detail": u"Fine",
    u"icon_2d_detail": u"Fine",
    u"icon_3d_scale": u"1",
    u"icon_2d_scale": u"1",
    u"icon_view_type": u"top_back_left",
    u"icon_export_images": u"off",
    u"icon_lock_orientation": u"off",
    u"icon_gradient": u"off",
    u"icon_hide_dimensions": u"on",
    u"icon_hide_reference_points": u"on",
    u"icon_hide_reference_lines": u"on",
    u"icon_hide_reference_planes": u"on",
    u"icon_hide_text_notes": u"on",
    u"icon_hide_invisible_lines": u"on",
    u"icon_hide_flip_controls": u"on",
    u"icon_hide_room_points": u"on",
    u"icon_hide_host": u"on",
    u"icon_hide_connectors": u"on",
    u"icon_hide_voids": u"on",
    u"icon_hide_imported": u"off",

    # Family naming
    u"name_company_list": u"",
    u"name_type_list": u"",
    u"name_discipline_list": u"",
    u"last_company": u"",
    u"last_type": u"",
    u"last_discipline": u"",
    u"last_family_name": u"",
    u"last_save_folder": u"",

    # Flex test
    u"flex_steps": u"3",
    u"flex_spread": u"50",
    u"flex_types": u"all",              # all | current
    u"flex_restore": u"on",
    u"plane_params_binding": u"type",
    u"create_plane_params": u"on",
    u"label_plane_dims": u"on",
    u"last_layout": u"centred_box",
    u"last_section": u"builder",      # builder | flex | icon
    u"overwrite_existing": u"off",
    u"show_results": u"needed",          # needed | always | never
    u"debug": u"off",
    u"window_width": u"1180",
    u"window_height": u"740",
}

# A settings key whose MEANING changes needs a migration, not just a new
# default.  List the keys each version resets.
MIGRATIONS = {
    # 2: [u"dim_offset_mm"],
}

def _as_text(value):
    if value is None:
        return u""
    try:
        if isinstance(value, bytes):
            return value.decode(u"utf-8", u"ignore")
    except Exception:
        pass
    return u"{0}".format(value)


def parse_settings_text(text):
    u"""Parse key=value lines.  Split on the first = only, so a value may
    itself contain = signs.  Unknown and removed keys are ignored."""
    out = dict(DEFAULTS)
    for raw in _as_text(text).splitlines():
        line = raw.strip()
        if not line or line.startswith(u"#"):
            continue
        if u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        key = key.strip()
        if not key:
            continue
        # DEFAULTS is the whitelist: a key from an older version, or a
        # typo, is ignored rather than breaking the load.
        if key in DEFAULTS:
            out[key] = value.strip()
    return apply_migrations(out)


def apply_migrations(values):
    try:
        found = int(values.get(u"settings_version", u"0") or u"0")
    except Exception:
        found = 0
    if found < SETTINGS_VERSION:
        for version in sorted(MIGRATIONS.keys()):
            if version > found:
                for key in MIGRATIONS[version]:
                    if key in DEFAULTS:
                        values[key] = DEFAULTS[key]
        values[u"settings_version"] = u"{0}".format(SETTINGS_VERSION)
    return values


def settings_to_text(values):
    lines = []
    for key in sorted(DEFAULTS.keys()):
        lines.append(u"{0}={1}".format(key, _as_text(values.get(key, DEFAULTS[key]))))
    return u"\n".join(lines) + u"\n"


def load_settings():
    path = settings_path()
    try:
        handle = open(path, u"rb")
        try:
            raw = handle.read()
        finally:
            handle.close()
        return parse_settings_text(raw.decode(u"utf-8", u"ignore"))
    except Exception:
        return dict(DEFAULTS)


def save_settings(values):
    ensure_dir(appdata_root())
    try:
        handle = open(settings_path(), u"wb")
        try:
            handle.write(settings_to_text(values).encode(u"utf-8"))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def setting_on(values, key):
    return _as_text(values.get(key, DEFAULTS.get(key, u""))).strip().lower() in (
        u"on", u"true", u"yes", u"1")


def setting_mm(values, key):
    raw = _as_text(values.get(key, DEFAULTS.get(key, u"0")))
    return to_number(raw, float(DEFAULTS.get(key, u"0") or 0))


def to_number(text, fallback=0.0):
    try:
        return float(_as_text(text).strip().replace(u",", u""))
    except Exception:
        return fallback


# =========================================================================
# Shared parameter file
#
# The file is parsed AS TEXT for the listing.  The Revit API is only used
# at the moment of adding, matched on GUID.  Reading the listing through
# the API means writing Application.SharedParametersFilename, which changes
# a setting the user did not ask to change, and is slow.
# =========================================================================

class SharedParam(object):
    __slots__ = (u"guid", u"name", u"data_type", u"data_category", u"group",
                 u"visible", u"description", u"user_modifiable")

    def __init__(self, guid, name, data_type, data_category, group,
                 visible, description, user_modifiable):
        self.guid = guid
        self.name = name
        self.data_type = data_type
        self.data_category = data_category
        self.group = group
        self.visible = visible
        self.description = description
        self.user_modifiable = user_modifiable

    def __repr__(self):
        return u"<SharedParam {0} {1}>".format(self.name, self.guid)


def parse_shared_parameter_text(text):
    u"""Return (params, groups, problems).

    The file is tab delimited:
        GROUP  <id>  <name>
        PARAM  <guid> <name> <datatype> <datacategory> <group> <visible>
               <description> <usermodifiable> <hidewhennovalue>

    Trailing columns vary by Revit release, so anything past the ones we
    need is ignored rather than making the line unreadable.
    """
    groups = {}
    params = []
    problems = []
    seen = {}
    for number, raw in enumerate(_as_text(text).splitlines(), 1):
        line = raw.rstrip(u"\r\n")
        if not line.strip() or line.startswith(u"#") or line.startswith(u"*"):
            continue
        cells = line.split(u"\t")
        tag = cells[0].strip().upper()
        if tag == u"GROUP":
            if len(cells) < 3:
                problems.append(u"Line {0}: a GROUP line with no name".format(number))
                continue
            groups[cells[1].strip()] = cells[2].strip()
        elif tag == u"PARAM":
            if len(cells) < 6:
                problems.append(u"Line {0}: a PARAM line with too few columns".format(number))
                continue
            guid = cells[1].strip()
            name = cells[2].strip()
            if not guid or not name:
                problems.append(u"Line {0}: a PARAM line with no GUID or no name".format(number))
                continue
            if guid in seen:
                problems.append(u"Line {0}: {1} repeats a GUID already used by {2}".format(
                    number, name, seen[guid]))
                continue
            seen[guid] = name
            params.append(SharedParam(
                guid=guid,
                name=name,
                data_type=cells[3].strip(),
                data_category=(cells[4].strip() if len(cells) > 4 else u""),
                group=cells[5].strip(),
                visible=(cells[6].strip() == u"1" if len(cells) > 6 else True),
                description=(cells[7].strip() if len(cells) > 7 else u""),
                user_modifiable=(cells[8].strip() == u"1" if len(cells) > 8 else True),
            ))
    for item in params:
        item.group = groups.get(item.group, item.group)
    params.sort(key=lambda p: (natural_key(p.group), natural_key(p.name)))
    return params, groups, problems


def read_shared_parameter_file(path):
    handle = open(path, u"rb")
    try:
        raw = handle.read()
    finally:
        handle.close()
    for codec in (u"utf-16", u"utf-8", u"latin-1"):
        try:
            text = raw.decode(codec)
        except Exception:
            continue
        if u"PARAM" in text or u"GROUP" in text:
            return parse_shared_parameter_text(text)
    return parse_shared_parameter_text(raw.decode(u"utf-8", u"ignore"))


# =========================================================================
# Searching and ordering
# =========================================================================

_NUM = re.compile(u"(\\d+)")


def natural_key(text):
    u"""P-9 before P-10 before P-100, rather than string order."""
    parts = _NUM.split(_as_text(text).lower())
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part), u""))
        elif part:
            key.append((0, 0, part))
    return key


def matches_search(haystack, needle):
    u"""Every word typed has to appear somewhere in the row, in any order.
    An empty search matches everything."""
    words = [w for w in _as_text(needle).lower().split() if w]
    if not words:
        return True
    hay = _as_text(haystack).lower()
    for word in words:
        if word not in hay:
            return False
    return True


def filter_params(params, needle, group=None):
    out = []
    for item in params:
        if group and item.group != group:
            continue
        hay = u" ".join([item.name, item.group, item.data_type,
                         item.description, item.guid])
        if matches_search(hay, needle):
            out.append(item)
    return out


# =========================================================================
# Which family parameter each layout drives
#
# Held as ONE setting so it round trips through a plain key=value file:
#
#   layout_params=centred_box:w=BGL_Width,d=BGL_Depth;height_elevation:h=Ht
#
# The value carries = and : and , and the loader splits the line on the
# first = only, so it comes back intact.
# =========================================================================

PLANE_PARAM_KEYS = (u"w", u"d", u"h", u"c", u"r")

PLANE_PARAM_LABEL = {
    u"w": u"Width",
    u"d": u"Depth",
    u"h": u"Height",
    u"c": u"Clearance",
    u"r": u"Radius",
}

# A parameter name the tool should create rather than reuse.
CREATE_NEW = u"\x00new"


def parse_layout_params(text):
    u"""{layout key: {w: parameter name}}.  Anything unreadable is dropped
    rather than taking the rest of the map with it."""
    out = {}
    for chunk in _as_text(text).split(u";"):
        chunk = chunk.strip()
        if not chunk or u":" not in chunk:
            continue
        layout, rest = chunk.split(u":", 1)
        layout = layout.strip()
        if not layout:
            continue
        pairs = {}
        for item in rest.split(u","):
            if u"=" not in item:
                continue
            key, name = item.split(u"=", 1)
            key = key.strip()
            name = name.strip()
            if key in PLANE_PARAM_KEYS and name:
                pairs[key] = name
        if pairs:
            out[layout] = pairs
    return out


def format_layout_params(mapping):
    chunks = []
    for layout in sorted(mapping.keys()):
        pairs = mapping[layout]
        items = []
        for key in PLANE_PARAM_KEYS:
            name = _as_text(pairs.get(key, u"")).strip()
            # A name carrying one of the separators would come back as two
            # broken halves, so it is refused rather than written.
            if name and not [bad for bad in (u";", u":", u",", u"=")
                             if bad in name]:
                items.append(u"{0}={1}".format(key, name))
        if items:
            chunks.append(u"{0}:{1}".format(layout, u",".join(items)))
    return u";".join(chunks)


def assigned_param(mapping, layout_key, param_key):
    u"""The parameter this page was pointed at, or nothing."""
    return _as_text(mapping.get(layout_key, {}).get(param_key, u"")).strip()


def should_label(assigned, label_dims, create_params):
    u"""A parameter picked for the page on purpose is labelled whatever the
    ticks say.  The ticks decide what happens when nothing was picked: they
    govern INVENTING a parameter, not using one that was chosen."""
    if assigned:
        return True
    return bool(label_dims) and bool(create_params)


def layout_param_name(mapping, layout_key, param_key, settings):
    u"""What this page should drive: the parameter picked for this page,
    else the house default name from settings."""
    chosen = mapping.get(layout_key, {}).get(param_key, u"")
    if chosen:
        return chosen
    fallback = {u"w": u"param_width", u"d": u"param_depth",
                u"h": u"param_height", u"c": u"param_clearance",
                u"r": u"param_radius"}.get(param_key)
    if fallback:
        return _as_text(settings.get(fallback, DEFAULTS.get(fallback, u"")))
    return u""

# =========================================================================
# Data type kinds and their colours
#
# Two spellings have to land on the same kind: the tokens a shared
# parameter FILE uses (LENGTH, YESNO, HVAC_AIRFLOW) and the labels Revit
# gives a family parameter's spec (Length, Yes/No, Air Flow).  Both are
# normalised here, so a staged parameter and the family parameter it would
# replace carry the same colour and can be matched by eye.
# =========================================================================

KIND_LENGTH = u"length"
KIND_AREA_VOLUME = u"area_volume"
KIND_ANGLE = u"angle"
KIND_NUMBER = u"number"
KIND_INTEGER = u"integer"
KIND_TEXT = u"text"
KIND_YESNO = u"yesno"
KIND_MATERIAL = u"material"
KIND_FAMILY_TYPE = u"family_type"
KIND_URL_IMAGE = u"url_image"
KIND_FLOW = u"flow"
KIND_OTHER = u"other"

KIND_ORDER = (KIND_LENGTH, KIND_AREA_VOLUME, KIND_ANGLE, KIND_NUMBER,
              KIND_INTEGER, KIND_TEXT, KIND_YESNO, KIND_MATERIAL,
              KIND_FAMILY_TYPE, KIND_URL_IMAGE, KIND_FLOW, KIND_OTHER)

KIND_LABEL = {
    KIND_LENGTH: u"Length",
    KIND_AREA_VOLUME: u"Area and volume",
    KIND_ANGLE: u"Angle and slope",
    KIND_NUMBER: u"Number",
    KIND_INTEGER: u"Integer",
    KIND_TEXT: u"Text",
    KIND_YESNO: u"Yes/No",
    KIND_MATERIAL: u"Material",
    KIND_FAMILY_TYPE: u"Family type",
    KIND_URL_IMAGE: u"URL and image",
    KIND_FLOW: u"MEP and structural",
    KIND_OTHER: u"Other",
}

KIND_BRUSH = {
    KIND_LENGTH: u"DataLength",
    KIND_AREA_VOLUME: u"DataAreaVolume",
    KIND_ANGLE: u"DataAngle",
    KIND_NUMBER: u"DataNumber",
    KIND_INTEGER: u"DataInteger",
    KIND_TEXT: u"DataText",
    KIND_YESNO: u"DataYesNo",
    KIND_MATERIAL: u"DataMaterial",
    KIND_FAMILY_TYPE: u"DataFamilyType",
    KIND_URL_IMAGE: u"DataUrlImage",
    KIND_FLOW: u"DataFlow",
    KIND_OTHER: u"DataOther",
}

# Checked in order, first match wins, so the specific tokens are listed
# before the loose ones.  Matching is on a normalised, lowercased string
# with every separator removed, which is what makes HVAC_AIRFLOW and
# "Air Flow" land in the same place.
_KIND_RULES = (
    (KIND_YESNO, (u"yesno",)),
    (KIND_FAMILY_TYPE, (u"familytype",)),
    (KIND_URL_IMAGE, (u"url", u"image")),
    (KIND_MATERIAL, (u"material",)),
    (KIND_AREA_VOLUME, (u"area", u"volume")),
    (KIND_ANGLE, (u"angle", u"slope", u"rotation")),
    (KIND_LENGTH, (u"length", u"distance", u"pipesize", u"ductsize",
                   u"wiresize", u"barsize", u"cablesize")),
    (KIND_INTEGER, (u"integer",)),
    (KIND_FLOW, (u"hvac", u"electrical", u"piping", u"structural", u"force",
                 u"moment", u"flow", u"pressure", u"power", u"current",
                 u"voltage", u"temperature", u"energy", u"stress", u"mass",
                 u"density", u"velocity")),
    (KIND_TEXT, (u"text", u"multilinetext")),
    (KIND_NUMBER, (u"number", u"currency")),
)


def normalise_data_type(text):
    out = []
    for char in _as_text(text).lower():
        if char.isalnum():
            out.append(char)
    return u"".join(out)


def data_kind(text):
    u"""The kind a data type belongs to, from either spelling."""
    flat = normalise_data_type(text)
    if not flat:
        return KIND_OTHER
    for kind, tokens in _KIND_RULES:
        for token in tokens:
            if token in flat:
                return kind
    return KIND_OTHER


def data_brush_key(text):
    return KIND_BRUSH.get(data_kind(text), KIND_BRUSH[KIND_OTHER])


def kinds_present(items):
    u"""The kinds actually in a list, in KIND_ORDER, for a filter that
    only offers what is there."""
    found = set([data_kind(text) for text in items])
    return [kind for kind in KIND_ORDER if kind in found]


def swap_is_clean(new_type, existing_type):
    u"""Revit will replace a family parameter with a shared one of a
    different spec, but the formulas and labels that referred to it will
    not survive.  Same kind is reported as a clean swap; anything else is
    flagged rather than refused, because a deliberate Text to Length change
    is a real thing to want."""
    return data_kind(new_type) == data_kind(existing_type)

# =========================================================================
# Parameter templates
#
# A template is a named selection: which shared parameters, whether each is
# type or instance, and which parameter group it lands in.  Stored as plain
# key=value text, one param per line, fields separated by |.
# =========================================================================

ACTION_NEW = u"new"
ACTION_REPLACE = u"replace"


class TemplateRow(object):
    __slots__ = (u"guid", u"name", u"binding", u"group", u"data_type",
                 u"action", u"target")

    def __init__(self, guid, name, binding, group, data_type=u"",
                 action=ACTION_NEW, target=u""):
        self.guid = guid
        self.name = name
        self.binding = binding if binding in (u"type", u"instance") else u"type"
        self.group = group
        self.data_type = data_type
        self.action = action if action in (ACTION_NEW, ACTION_REPLACE) \
            else ACTION_NEW
        self.target = target
        if self.action == ACTION_REPLACE and not self.target:
            # A replace with nothing to replace is a new parameter, not a
            # half-set row that fails at the moment of writing.
            self.action = ACTION_NEW

    @property
    def is_instance(self):
        return self.binding == u"instance"

    @property
    def replaces(self):
        return self.action == ACTION_REPLACE and bool(self.target)

    @property
    def brush_key(self):
        return data_brush_key(self.data_type)


class ParamEdit(object):
    u"""A pending change to one family parameter.  Plain data, keyed to the
    parameter's CURRENT name, so the window can hold it across a refresh
    without holding a Revit handle."""

    __slots__ = (u"current", u"new_name", u"binding", u"group", u"formula")

    def __init__(self, current, new_name=None, binding=None, group=None,
                 formula=None):
        self.current = current
        self.new_name = new_name
        self.binding = binding
        self.group = group
        self.formula = formula

    @property
    def renames(self):
        return bool(self.new_name) and self.new_name != self.current

    def touches_anything(self):
        return (self.renames or self.binding is not None or
                self.group is not None or self.formula is not None)


PARK_PREFIX = u"RevoBIM_parked_"


def plan_renames(pairs, all_names):
    u"""Work out the order to rename in.  Returns (steps, problems).

    Swapping two names round, or shuffling a set along by one, fails on a
    clash with itself if the renames are done one at a time in the order
    they were typed.  Where any wanted name is currently held by something
    else in the batch, every rename goes through a parked name first.
    """
    steps = []
    problems = []
    moving = {}
    for current, wanted in pairs:
        if not wanted or wanted == current:
            continue
        moving[current] = wanted

    held_elsewhere = set([_as_text(n) for n in all_names]) - set(moving.keys())
    seen = {}
    for current, wanted in moving.items():
        if wanted in held_elsewhere:
            problems.append(
                u"{0} cannot become '{1}' - another parameter already has "
                u"that name".format(current, wanted))
        if wanted.lower() in seen:
            problems.append(
                u"{0} and {1} would both become '{2}'".format(
                    seen[wanted.lower()], current, wanted))
        seen[wanted.lower()] = current
    if problems:
        return [], problems

    needs_parking = any(wanted in moving for wanted in moving.values())
    ordered = sorted(moving.items(), key=lambda pair: natural_key(pair[0]))
    if not needs_parking:
        for current, wanted in ordered:
            steps.append((current, wanted))
        return steps, problems

    parked = {}
    for index, pair in enumerate(ordered):
        current, wanted = pair
        park = u"{0}{1}".format(PARK_PREFIX, index)
        parked[park] = wanted
        steps.append((current, park))
    for park in sorted(parked.keys(), key=natural_key):
        steps.append((park, parked[park]))
    return steps, problems


def template_to_text(name, source_file, rows):
    lines = [u"template_name={0}".format(_as_text(name)),
             u"source_file={0}".format(_as_text(source_file)),
             u"count={0}".format(len(rows))]
    for row in rows:
        lines.append(u"param={0}|{1}|{2}|{3}|{4}|{5}|{6}".format(
            row.guid, row.name, row.binding, row.group, row.data_type,
            row.action, row.target))
    return u"\n".join(lines) + u"\n"


def parse_template_text(text):
    u"""Return (name, source_file, rows, problems)."""
    name = u""
    source = u""
    rows = []
    problems = []
    for number, raw in enumerate(_as_text(text).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        key = key.strip()
        if key == u"template_name":
            name = value.strip()
        elif key == u"source_file":
            source = value.strip()
        elif key == u"param":
            cells = value.split(u"|")
            if len(cells) < 4:
                problems.append(u"Line {0}: a param line with too few fields".format(number))
                continue
            # Templates written before 1.2.0 carry five fields, not seven.
            # A short line is an older template, not a broken one.
            rows.append(TemplateRow(
                guid=cells[0].strip(),
                name=cells[1].strip(),
                binding=cells[2].strip().lower(),
                group=cells[3].strip(),
                data_type=(cells[4].strip() if len(cells) > 4 else u""),
                action=(cells[5].strip().lower() if len(cells) > 5
                        else ACTION_NEW),
                target=(cells[6].strip() if len(cells) > 6 else u""),
            ))
    return name, source, rows, problems


def template_file_name(name):
    u"""A template name is typed by hand, so it has to be made safe for a
    file name without two different names collapsing onto one file."""
    cleaned = re.sub(u"[^A-Za-z0-9 _.-]", u"_", _as_text(name)).strip()
    cleaned = re.sub(u"\\s+", u" ", cleaned)
    if not cleaned:
        cleaned = u"template"
    return cleaned[:60] + u".txt"


def list_templates():
    folder = templates_dir()
    out = []
    try:
        for item in sorted(os.listdir(folder)):
            if item.lower().endswith(u".txt"):
                out.append(os.path.join(folder, item))
    except Exception:
        pass
    return out


def save_template(name, source_file, rows):
    ensure_dir(templates_dir())
    path = os.path.join(templates_dir(), template_file_name(name))
    handle = open(path, u"wb")
    try:
        handle.write(template_to_text(name, source_file, rows).encode(u"utf-8"))
    finally:
        handle.close()
    return path


def load_template(path):
    handle = open(path, u"rb")
    try:
        raw = handle.read()
    finally:
        handle.close()
    return parse_template_text(raw.decode(u"utf-8", u"ignore"))


# =========================================================================
# Presets - materials, line styles, annotation styles
#
# One file per kind, one preset per line, fields separated by |.  Field
# order is fixed per kind and short fields at the end may be absent, so an
# older file still loads.
# =========================================================================

PRESET_FIELDS = {
    u"material": (u"name", u"colour", u"transparency", u"shininess",
                  u"surface_pattern", u"cut_pattern", u"class"),
    u"linestyle": (u"name", u"weight", u"colour", u"pattern", u"scope"),
    u"text": (u"name", u"font", u"size_mm", u"bold", u"italic",
              u"underline", u"width_factor", u"arrowhead", u"background"),
    u"dimension": (u"name", u"font", u"size_mm", u"tick", u"witness_gap_mm",
                   u"units", u"arrowhead"),
}

SEED_PRESETS = {
    u"material": [
        u"BGL_Steel Galvanised|192,192,196|0|64|Steel|Steel|Metal",
        u"BGL_Copper|184,115,51|0|64|Diagonal crosshatch|Diagonal crosshatch|Metal",
        u"BGL_Plastic Black|40,40,44|0|30|Solid fill|Solid fill|Plastic",
        u"BGL_Insulation|236,222,180|0|20|Insulation - Batt|Insulation - Batt|Generic",
        u"BGL_Glass Clear|180,214,232|75|90|Solid fill|Solid fill|Glass",
    ],
    u"linestyle": [
        u"BGL_Hidden|3|0,0,0|Hidden 3mm|lines",
        u"BGL_Centre|1|0,128,192|Center|lines",
        u"BGL_Clearance|2|232,145,45|Dash|lines",
        u"BGL_Heavy|6|0,0,0|Solid|lines",
        u"BGL_Light|1|128,128,128|Solid|lines",
        u"BGL_Service Zone|2|79,163,227|Dash dot|subcategory",
    ],
    u"text": [
        u"BGL_2.5mm Arial|Arial|2.5|0|0|0|1|Arrow Filled 15 Degree|0",
        u"BGL_3.5mm Arial|Arial|3.5|0|0|0|1|Arrow Filled 15 Degree|0",
        u"BGL_2.5mm Arial Bold|Arial|2.5|1|0|0|1|Arrow Filled 15 Degree|0",
        u"BGL_1.8mm Arial|Arial|1.8|0|0|0|1|Arrow Filled 15 Degree|0",
    ],
    u"dimension": [
        u"BGL_Linear 2.5mm|Arial|2.5|Diagonal 3mm|1.5|mm|Arrow Filled 15 Degree",
        u"BGL_Linear 2.5mm Arrow|Arial|2.5|Arrow Filled 15 Degree|1.5|mm|Arrow Filled 15 Degree",
        u"BGL_Angular 2.5mm|Arial|2.5|Diagonal 3mm|1.5|mm|Arrow Filled 15 Degree",
    ],
}


class Preset(object):
    def __init__(self, kind, values):
        self.kind = kind
        self.values = dict(values)

    def get(self, key, fallback=u""):
        return self.values.get(key, fallback)

    @property
    def name(self):
        return self.values.get(u"name", u"")

    def to_line(self):
        fields = PRESET_FIELDS[self.kind]
        return u"|".join([_as_text(self.values.get(f, u"")) for f in fields])


def parse_preset_line(kind, line):
    fields = PRESET_FIELDS[kind]
    cells = _as_text(line).split(u"|")
    values = {}
    for index, field in enumerate(fields):
        values[field] = cells[index].strip() if index < len(cells) else u""
    return Preset(kind, values)


def parse_presets_text(kind, text):
    out = []
    seen = set()
    for raw in _as_text(text).splitlines():
        line = raw.strip()
        if not line or line.startswith(u"#"):
            continue
        if u"=" in line and line.split(u"=", 1)[0].strip() == u"preset":
            line = line.split(u"=", 1)[1].strip()
        preset = parse_preset_line(kind, line)
        if not preset.name:
            continue
        key = preset.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(preset)
    return out


def presets_to_text(presets):
    lines = []
    for preset in presets:
        lines.append(u"preset={0}".format(preset.to_line()))
    return u"\n".join(lines) + u"\n"


def load_presets(kind):
    path = presets_path(kind)
    try:
        handle = open(path, u"rb")
        try:
            raw = handle.read()
        finally:
            handle.close()
        parsed = parse_presets_text(kind, raw.decode(u"utf-8", u"ignore"))
        if parsed:
            return parsed
    except Exception:
        pass
    return parse_presets_text(kind, u"\n".join(SEED_PRESETS.get(kind, [])))


def save_presets(kind, presets):
    ensure_dir(tool_root())
    try:
        handle = open(presets_path(kind), u"wb")
        try:
            handle.write(presets_to_text(presets).encode(u"utf-8"))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def parse_colour(text):
    u"""'192,192,196' or '#C0C0C4' to an (r, g, b) triple, clamped."""
    raw = _as_text(text).strip()
    if not raw:
        return None
    if raw.startswith(u"#"):
        raw = raw[1:]
        if len(raw) == 6:
            try:
                return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
            except Exception:
                return None
        return None
    cells = raw.replace(u";", u",").split(u",")
    if len(cells) != 3:
        return None
    out = []
    for cell in cells:
        try:
            value = int(float(cell.strip()))
        except Exception:
            return None
        out.append(max(0, min(255, value)))
    return tuple(out)


def unique_name(wanted, taken):
    u"""Append New, then New 2, rather than clobbering or failing."""
    existing = set([_as_text(t).lower() for t in taken])
    name = _as_text(wanted).strip()
    if not name:
        name = u"Unnamed"
    if name.lower() not in existing:
        return name
    candidate = name + u" New"
    counter = 2
    while candidate.lower() in existing:
        candidate = u"{0} New {1}".format(name, counter)
        counter += 1
    return candidate


# =========================================================================
# Units and element ids
# =========================================================================

MM_PER_FOOT = 304.8


def mm_to_ft(value):
    u"""Revit's internal length unit is decimal feet, and a foot is 304.8mm
    exactly.  Doing it arithmetically rather than through UnitUtils avoids
    the DisplayUnitType / UnitTypeId / ForgeTypeId split across 2021-2027
    entirely."""
    return float(value) / MM_PER_FOOT


def ft_to_mm(value):
    return float(value) * MM_PER_FOOT


def eid_value(element_id):
    u"""ElementId.IntegerValue was removed in Revit 2026.  Prefer .Value."""
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


# =========================================================================
# Logging
# =========================================================================

def log(message):
    try:
        ensure_dir(appdata_root())
        handle = open(log_path(), u"ab")
        try:
            handle.write((_as_text(message) + u"\n").encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


# =========================================================================
# The diagnostic trace
#
# A plain list of lines, so a run can be described, written to a file and
# put on the clipboard without any of it depending on Revit.  Values are
# truncated, because an asset property can hold a whole texture path and a
# report nobody can read is a report nobody sends.
# =========================================================================

MAX_TRACE_LINES = 6000
MAX_VALUE_CHARS = 300


def short(value, limit=MAX_VALUE_CHARS):
    text = _as_text(value).replace(u"\r", u" ").replace(u"\n", u" ")
    if len(text) <= limit:
        return text
    return text[:limit] + u" ... [{0} more]".format(len(text) - limit)


class Trace(object):
    def __init__(self, title):
        self.title = title
        self.lines = []
        self.dropped = 0

    def note(self, text=u"", indent=0):
        if len(self.lines) >= MAX_TRACE_LINES:
            self.dropped += 1
            return
        self.lines.append(u"{0}{1}".format(u"  " * int(indent),
                                           short(text, 2000)))

    def pair(self, label, value, indent=1):
        self.note(u"{0}: {1}".format(label, short(value)), indent)

    def heading(self, text):
        self.note()
        self.note(text)
        self.note(u"-" * len(_as_text(text)))

    def fail(self, what, detail=u"", indent=1):
        self.note(u"FAILED {0}".format(what), indent)
        for line in _as_text(detail).strip().splitlines():
            self.note(line.rstrip(), indent + 1)

    def to_text(self):
        head = [self.title, u"=" * len(_as_text(self.title))]
        tail = []
        if self.dropped:
            tail = [u"", u"[{0} further lines dropped - the trace hit its "
                        u"ceiling]".format(self.dropped)]
        return u"\n".join(head + self.lines + tail) + u"\n"

    def write(self, path=None):
        target = path or diagnostics_path()
        ensure_dir(os.path.dirname(target))
        handle = open(target, u"wb")
        try:
            handle.write(self.to_text().encode(u"utf-8"))
        finally:
            handle.close()
        return target


# =========================================================================
# The family icon
# =========================================================================

# Label, and the DisplayStyle member behind it.  The member is looked up
# late by name, so a style a release does not carry is a missing entry
# rather than a module that will not load.
DISPLAY_STYLES = (
    (u"Realistic", u"Realistic"),
    (u"Realistic with edges", u"RealisticWithEdges"),
    (u"Shaded", u"Shading"),
    (u"Shaded with edges", u"ShadingWithEdges"),
    (u"Consistent colours", u"FlatColors"),
    (u"Hidden line", u"HiddenLine"),
    (u"Wireframe", u"Wireframe"),
)

DETAIL_LEVELS = ((u"Coarse", u"Coarse"), (u"Medium", u"Medium"),
                 (u"Fine", u"Fine"))

VIEW_SCALES = ((u"1 : 1", u"1"), (u"1 : 2", u"2"), (u"1 : 5", u"5"),
               (u"1 : 10", u"10"), (u"1 : 20", u"20"), (u"1 : 50", u"50"))

# The corner the camera sits in, and the direction it looks.  Held as plain
# tuples so the arithmetic can be checked on the bench.
VIEW_TYPES = (
    (u"top_back_left", u"3D View: Top, Back, Left", (-1.0, 1.0, 1.0)),
    (u"top_back_right", u"3D View: Top, Back, Right", (1.0, 1.0, 1.0)),
    (u"top_front_left", u"3D View: Top, Front, Left", (-1.0, -1.0, 1.0)),
    (u"top_front_right", u"3D View: Top, Front, Right", (1.0, -1.0, 1.0)),
    (u"front", u"Front", (0.0, -1.0, 0.0)),
    (u"back", u"Back", (0.0, 1.0, 0.0)),
    (u"left", u"Left", (-1.0, 0.0, 0.0)),
    (u"right", u"Right", (1.0, 0.0, 0.0)),
    (u"top", u"Top", (0.0, 0.0, 1.0)),
)

# The General Settings ticks, as (settings key, label).
ICON_TICKS = (
    (u"icon_export_images", u"Export Images"),
    (u"icon_lock_orientation", u"Lock 3D View Orientation"),
    (u"icon_hide_dimensions", u"Hide Dimensions"),
    (u"icon_hide_reference_points", u"Hide Reference Points"),
    (u"icon_hide_reference_lines", u"Hide Reference Lines"),
    (u"icon_hide_reference_planes", u"Hide Reference Planes"),
    (u"icon_hide_text_notes", u"Hide Text Notes"),
    (u"icon_gradient", u"Gradient Background"),
    (u"icon_hide_invisible_lines", u"Hide Invisible Lines"),
    (u"icon_hide_flip_controls", u"Hide Flip Controls"),
    (u"icon_hide_room_points", u"Hide Room Calculation Points"),
    (u"icon_hide_host", u"Hide Host Elements"),
    (u"icon_hide_connectors", u"Hide Connector Elements"),
    (u"icon_hide_voids", u"Hide Void Elements"),
    (u"icon_hide_imported", u"Hide Imported Elements"),
)


def _norm(vector):
    length = (vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2) ** 0.5
    if length < 1e-9:
        return (0.0, 0.0, -1.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def view_type_by_key(key):
    for entry in VIEW_TYPES:
        if entry[0] == key:
            return entry
    return VIEW_TYPES[0]


def orientation_for(key):
    u"""(eye direction, up, forward) for a named view type.

    Revit wants the direction the camera LOOKS IN, which is the opposite of
    the corner it sits in, and an up vector square to it.  A straight down
    view has no sensible up from the usual formula, so it is given one.
    """
    corner = _norm(view_type_by_key(key)[2])
    forward = (-corner[0], -corner[1], -corner[2])
    if abs(forward[2]) > 0.999:
        up = (0.0, 1.0, 0.0)
    else:
        right = _norm(_cross(forward, (0.0, 0.0, 1.0)))
        up = _norm(_cross(right, forward))
    return corner, up, forward


# =========================================================================
# Family naming
#
#   Company _ Family type _ Discipline _ Family name
#   BGL_PFX_DOM_Waste Connection
# =========================================================================

NAME_FIELDS = (
    (u"company", u"name_company_list", u"last_company",
     u"Company abbreviation"),
    (u"type", u"name_type_list", u"last_type", u"Family type abbreviation"),
    (u"discipline", u"name_discipline_list", u"last_discipline",
     u"Discipline abbreviation"),
)

NAME_SEPARATOR = u"_"


def parse_abbreviations(text):
    u"""[(code, description)].  One per |, the description after an
    optional =.  An entry with no code is dropped rather than producing a
    blank row in the dropdown."""
    out = []
    seen = set()
    for chunk in _as_text(text).split(u"|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if u"=" in chunk:
            code, description = chunk.split(u"=", 1)
        else:
            code, description = chunk, u""
        code = code.strip()
        if not code or code.lower() in seen:
            continue
        seen.add(code.lower())
        out.append((code, description.strip()))
    return out


def format_abbreviations(items):
    chunks = []
    for code, description in items:
        code = _as_text(code).strip()
        if not code:
            continue
        if description:
            chunks.append(u"{0}={1}".format(code, _as_text(description).strip()))
        else:
            chunks.append(code)
    return u"|".join(chunks)


def abbreviation_lines(items):
    u"""One per line, for editing in a text box."""
    out = []
    for code, description in items:
        out.append(u"{0} = {1}".format(code, description) if description
                   else code)
    return u"\n".join(out)


def parse_abbreviation_lines(text):
    return parse_abbreviations(u"|".join(
        [line.strip() for line in _as_text(text).splitlines()]))


def clean_name_part(text):
    u"""Trim, collapse runs of space, and take out the separator itself -
    an underscore typed into a field would read back as an extra part."""
    cleaned = re.sub(u"\\s+", u" ", _as_text(text).replace(NAME_SEPARATOR, u" "))
    return cleaned.strip()


def build_family_name(parts):
    u"""Joined with the separator, empty parts left out."""
    kept = [clean_name_part(part) for part in parts]
    return NAME_SEPARATOR.join([part for part in kept if part])


def family_name_is_complete(parts):
    return len([1 for part in parts if clean_name_part(part)]) == len(parts) \
        and len(parts) > 0


ILLEGAL_FILE_CHARS = u"\\/:*?\"<>|"


def safe_file_name(name):
    out = []
    for char in _as_text(name):
        out.append(u"-" if char in ILLEGAL_FILE_CHARS else char)
    cleaned = u"".join(out).strip().strip(u".")
    return cleaned or u"Family"


# =========================================================================
# The flex test
#
# Driving a family through its own parameters and seeing what breaks.  The
# values are worked out here, in plain arithmetic, so the table of cases
# can be checked without Revit.
# =========================================================================

MAX_FLEX_TESTS = 400


def flex_values(minimum, maximum, steps):
    u"""The values to drive a parameter through: the minimum, the maximum,
    and `steps` evenly spaced between them.

    The ends are always included - they are where a family breaks - a pair
    given the wrong way round is swapped rather than refused, and values
    that land on each other are collapsed, so a 100 to 100 run is one test
    and not five identical ones.
    """
    low = to_number(minimum, 0.0)
    high = to_number(maximum, 0.0)
    if low > high:
        low, high = high, low
    try:
        count = int(float(steps))
    except Exception:
        count = 0
    count = max(0, min(count, 20))
    out = [low]
    if count and high > low:
        gap = (high - low) / float(count + 1)
        for index in range(1, count + 1):
            out.append(low + gap * index)
    out.append(high)
    cleaned = []
    for value in out:
        rounded = round(value, 4)
        if not [kept for kept in cleaned if abs(kept - rounded) < 1e-6]:
            cleaned.append(rounded)
    return cleaned


def flex_spread(current, percent):
    u"""A sensible pair of ends around the value a parameter already has,
    so the boxes arrive filled in rather than empty."""
    value = to_number(current, 0.0)
    share = to_number(percent, 50.0) / 100.0
    if value <= 0:
        return 100.0, 1000.0
    return round(max(1.0, value * (1.0 - share)), 1), \
        round(value * (1.0 + share), 1)


def flex_test_count(type_count, specs, steps):
    u"""How many set-and-regenerate rounds the run will be.  Every type is
    driven through every value of every parameter, so this grows faster
    than it looks."""
    per_type = 0
    for spec in specs or []:
        per_type += len(flex_values(spec[1], spec[2], steps))
    return per_type * max(1, int(type_count or 1))


def flex_is_too_big(count):
    return int(count or 0) > MAX_FLEX_TESTS


# How a single test came out, worst first - which is the order they are
# worth reading in.
FLEX_BROKE = u"broke"
FLEX_REFUSED = u"refused"
FLEX_NOT_TAKEN = u"not taken"
FLEX_WARNED = u"warned"
FLEX_OK = u"ok"

FLEX_ORDER = (FLEX_BROKE, FLEX_REFUSED, FLEX_NOT_TAKEN, FLEX_WARNED, FLEX_OK)

FLEX_MEANING = {
    FLEX_BROKE: u"the family would not regenerate",
    FLEX_REFUSED: u"Revit would not take the value",
    FLEX_NOT_TAKEN: u"the value was accepted but did not stick",
    FLEX_WARNED: u"it regenerated, with a warning",
    FLEX_OK: u"fine",
}


def flex_summary(rows):
    u"""'3 broke, 1 warned, 40 fine' - worst first, nothing with a count
    of zero."""
    tally = {}
    for row in rows or []:
        tally[row.status] = tally.get(row.status, 0) + 1
    bits = []
    for status in FLEX_ORDER:
        count = tally.get(status, 0)
        if not count:
            continue
        bits.append(u"{0} {1}".format(
            count, u"fine" if status == FLEX_OK else status))
    if not bits:
        return u"Nothing was run"
    return u", ".join(bits)


def flex_worst(rows):
    for status in FLEX_ORDER:
        for row in rows or []:
            if row.status == status:
                return status
    return FLEX_OK


def flex_rows_sorted(rows):
    u"""Worst first, then by parameter, then by value - so the thing that
    broke is the first line you read."""
    order = dict([(status, index) for index, status
                  in enumerate(FLEX_ORDER)])
    return sorted(rows or [],
                  key=lambda row: (order.get(row.status, 99),
                                   natural_key(row.parameter),
                                   to_number(row.value, 0.0)))
