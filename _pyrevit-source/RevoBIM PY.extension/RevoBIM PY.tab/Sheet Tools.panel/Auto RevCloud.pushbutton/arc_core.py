# -*- coding: utf-8 -*-
"""Auto RevCloud - version, settings, sheet matching and the grid maths.

Nothing in this module touches .NET or Revit, so bench_logic.py can run every
rule under plain CPython.
"""
import io
import math
import os
import re

__version__ = u"2.13.0"
TOOL_NAME = u"Auto RevCloud"
SETTINGS_FILE = u"auto_revcloud.txt"
LOG_FILE = u"auto_revcloud.log"
ERROR_FILE = u"auto_revcloud_last_error.txt"

MM_PER_FT = 304.8

# A scale this close to 1 is inside the noise of an ink bounding box and is
# treated as no scaling at all.
SCALE_NOISE = 0.03

# The categories a change has to touch to be worth clouding. MEP services
# first, because that is what a re-cloud is about, plus the fittings and
# accessories that move with them - a run that shifted moves its elbows too,
# and clouding the pipe but not the bend it turns on looks like a mistake.
DEFAULT_CATEGORIES = [
    u"Pipes", u"Pipe Fittings", u"Pipe Accessories", u"Pipe Insulations",
    u"Flex Pipes", u"Plumbing Fixtures", u"Sprinklers",
    u"Ducts", u"Duct Fittings", u"Duct Accessories", u"Duct Insulations",
    u"Duct Linings", u"Flex Ducts", u"Air Terminals",
    u"Mechanical Equipment", u"Mechanical Control Devices",
    u"Cable Trays", u"Cable Tray Fittings",
    u"Conduits", u"Conduit Fittings",
    u"Electrical Equipment", u"Electrical Fixtures",
    u"Lighting Devices", u"Lighting Fixtures",
    u"Data Devices", u"Fire Alarm Devices", u"Communication Devices",
    u"Security Devices", u"Nurse Call Devices", u"Telephone Devices",
    u"Wires", u"Electrical Circuits",
    u"Generic Models", u"Specialty Equipment",
    # For schematics, where the drawing is drafted rather than modelled: a
    # riser or a control diagram is lines and detail components, and without
    # these a schematic sheet has no elements on it at all and nothing to
    # compare. They are drafting categories, so on a modelled plan they also
    # pick up detail lines and hatching - which is usually what you want, and
    # is the reason they can be taken out of the list again.
    u"Lines", u"Detail Items",
]

# Every set of defaults this tool has shipped. A saved list that still matches
# one of these was never customised, so it is quietly brought up to date when
# categories are added; a list somebody has actually edited is left alone. The
# alternative - a migration that resets the key - would throw away a list
# somebody had spent time on to give them three names they could have typed.
PREVIOUS_CATEGORY_DEFAULTS = [
    [
        u"Pipes", u"Pipe Fittings", u"Pipe Accessories", u"Pipe Insulations",
        u"Flex Pipes", u"Plumbing Fixtures", u"Sprinklers",
        u"Ducts", u"Duct Fittings", u"Duct Accessories", u"Duct Insulations",
        u"Duct Linings", u"Flex Ducts", u"Air Terminals",
        u"Mechanical Equipment", u"Mechanical Control Devices",
        u"Cable Trays", u"Cable Tray Fittings",
        u"Conduits", u"Conduit Fittings",
        u"Electrical Equipment", u"Electrical Fixtures",
        u"Lighting Devices", u"Lighting Fixtures",
        u"Data Devices", u"Fire Alarm Devices", u"Communication Devices",
        u"Security Devices", u"Nurse Call Devices", u"Telephone Devices",
        u"Wires", u"Electrical Circuits",
        u"Generic Models", u"Specialty Equipment",
    ],
]

# Ordered so the settings file is written in a readable order.
DEFAULTS = [
    (u"settings_version", u"7"),
    (u"theme", u"auto"),                 # auto | dark | light
    (u"move_tol_mm", u"1"),              # model mm an element may move unnoticed
    (u"match_method", u"id"),            # id | spatial
    # Option 1 - VersionGuid. off: not read. flag: same guid skips every
    # test, a different one only counts if a test can say what changed.
    # trust: a different guid is clouded even when nothing else can say why.
    (u"guid_mode", u"off"),
    # Option 2 - only cloud a move or resize that shows in THIS view.
    (u"only_visible", u"0"),
    (u"visible_tol_mm", u"0.5"),         # paper mm a change must show by
    (u"match_by_eid", u"1"),             # also match on ElementId, not just UniqueId
    (u"spatial_tol_mm", u"5"),           # how exactly geometry must line up
    (u"spatial_search_mm", u"3000"),     # how far to look for a moved element
    (u"size_tol_mm", u"1"),              # model mm a side may change unnoticed
    (u"check_type", u"1"),               # a changed type is a change
    (u"rotate_tol_deg", u"0.5"),         # degrees an element may turn unnoticed
    (u"check_params", u"1"),             # compare the parameters below
    (u"compare_params", u"|".join([
        u"Reference Level", u"Offset", u"Middle Elevation",
        u"System Type", u"System Name", u"System Classification",
        u"Diameter", u"Width", u"Height", u"Size",
        u"Comments", u"Mark"])),
    (u"cloud_removed", u"1"),            # cloud what has been taken out
    (u"write_comments", u"1"),           # describe the change on the cloud
    (u"comment_items", u"4"),            # how many kinds a comment lists
    (u"merge_mm", u"8"),                 # paper mm; changes closer than this share a cloud
    (u"offset_mm", u"10"),               # paper mm of clearance around a change
    (u"cloud_arc_mm", u"0"),             # scallop size on paper; 0 leaves the type alone
    (u"clouds_in_views", u"1"),          # draw in the view when inside a viewport
    (u"compare_categories", u"|".join(DEFAULT_CATEGORIES)),
    (u"cloud_arc_side", u"out"),          # out | in - which way the arcs bulge
    (u"max_clouds", u"250"),
    (u"show_results", u"needed"),        # needed | always | never
]

DEFAULT_MAP = dict(DEFAULTS)

# Keys whose meaning changed between settings versions and must be reset.
# Keys whose DEFAULT changed and must be reset rather than kept from an older
# file - version 2 tightened the clouds, and a saved copy of the old looser
# numbers would quietly undo that.
MIGRATIONS = {
    2: [u"cell_mm", u"merge_mm", u"offset_mm"],
    # 3 replaced the density comparison with a tolerance comparison; a saved
    # ink_threshold tuned against the old one would be read the wrong way.
    3: [],
    # 4 is the change of method: the raster comparison is gone and the
    # clouds are grouped in model millimetres now, so distances tuned against
    # paper density cells mean nothing.
    4: [u"merge_mm", u"offset_mm", u"max_clouds"],
    # 5 puts the theme back to following Revit's canvas once. A theme saved
    # by an older version is a held choice made when the chip had only two
    # states and no way back to auto.
    5: [u"theme", u"offset_mm"],
    # 6 tightened the comparison. 5mm was chosen before there was any evidence
    # and is coarse for services: a 5mm move is a real move on a drawing, and
    # anything smaller than 1mm is round-off in the model rather than work.
    6: [u"move_tol_mm", u"size_tol_mm", u"rotate_tol_deg", u"merge_mm"],
    # 7 raised the cloud cap. 60 was low enough to silently drop real changes
    # on a busy services view, and the run reported the cap in a note nobody
    # was looking for.
    7: [u"max_clouds", u"match_method", u"match_by_eid"],
}


# ==========================================================================
# settings
# ==========================================================================

def appdata_dir():
    base = os.environ.get(u"APPDATA") or os.path.expanduser(u"~")
    return os.path.join(base, u"RevoBIM")


def settings_path():
    return os.path.join(appdata_dir(), SETTINGS_FILE)


def log_path():
    return os.path.join(appdata_dir(), LOG_FILE)


def error_path():
    return os.path.join(appdata_dir(), ERROR_FILE)


def parse_settings_text(text):
    """key=value lines -> dict.  Splits on the first '=' only."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(u"#"):
            continue
        if u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        out[key.strip()] = value.strip()
    return out


def merge_settings(loaded):
    """Defaults key by key, unknown keys dropped, migrations applied."""
    settings = dict(DEFAULT_MAP)
    try:
        version = int(loaded.get(u"settings_version", u"0"))
    except Exception:
        version = 0
    reset = set()
    for v, keys in MIGRATIONS.items():
        if version < v:
            reset.update(keys)
    for key in DEFAULT_MAP:
        if key in loaded and key not in reset and key != u"settings_version":
            settings[key] = loaded[key]
    settings[u"settings_version"] = DEFAULT_MAP[u"settings_version"]
    settings[u"compare_categories"] = _refresh_categories(
        settings.get(u"compare_categories", u""))
    return settings


def _refresh_categories(value):
    """A category list that was never edited follows the defaults."""
    current = parse_categories(value)
    if not current:
        return DEFAULT_MAP[u"compare_categories"]
    lowered = [name.lower() for name in current]
    for old_default in PREVIOUS_CATEGORY_DEFAULTS:
        if lowered == [name.lower() for name in old_default]:
            return DEFAULT_MAP[u"compare_categories"]
    return value


def load_settings(path=None):
    path = path or settings_path()
    loaded = {}
    try:
        with open(path, u"r") as handle:
            loaded = parse_settings_text(handle.read())
    except Exception:
        loaded = {}
    return merge_settings(loaded)


def settings_text(settings):
    lines = []
    for key, _default in DEFAULTS:
        lines.append(u"{0}={1}".format(key, settings.get(key, _default)))
    return u"\n".join(lines) + u"\n"


def save_settings(settings, path=None):
    path = path or settings_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, u"w") as handle:
        handle.write(settings_text(settings))


def as_int(settings, key, fallback=None):
    try:
        return int(float(settings.get(key, u"")))
    except Exception:
        if fallback is None:
            return int(float(DEFAULT_MAP[key]))
        return fallback


def as_float(settings, key, fallback=None):
    try:
        return float(settings.get(key, u""))
    except Exception:
        if fallback is None:
            return float(DEFAULT_MAP[key])
        return fallback


def as_bool(settings, key):
    value = settings.get(key, DEFAULT_MAP.get(key, u"0"))
    return unicode_str(value).strip().lower() in (u"1", u"true", u"yes", u"on")


def unicode_str(value):
    try:
        return u"{0}".format(value)
    except Exception:
        return u""


# ==========================================================================
# names and numbers
# ==========================================================================

_NATURAL = re.compile(u"(\\d+)")


def parse_categories(text):
    """A category list from the settings file, or from the settings window.

    Split on newlines, pipes and commas alike, so the value round-trips
    through a plain key=value file (one line, pipes) and is still typed into
    the window the natural way (one per line). Blank entries and duplicates
    are dropped, order kept.
    """
    raw = unicode_str(text).replace(u"\r", u"\n")
    for separator in (u"|", u","):
        raw = raw.replace(separator, u"\n")
    out = []
    seen = set()
    for part in raw.split(u"\n"):
        name = part.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def format_categories(names, separator=u"|"):
    return separator.join(names)


# ==========================================================================
# category templates
# ==========================================================================

TEMPLATE_FILE = u"auto_revcloud_category_templates.txt"


def templates_path():
    return os.path.join(appdata_dir(), TEMPLATE_FILE)


def parse_templates(text):
    """`name=Pipes|Ducts` per line, into an ordered list of (name, [cats]).

    Its own file rather than a key in the settings: a template name is typed
    by a person and will contain an `=` or a comma sooner or later, and the
    settings loader splits on the first `=`. Kept as a list so the order they
    were made in is the order they are offered in.
    """
    out = []
    seen = set()
    for line in unicode_str(text).replace(u"\r", u"\n").split(u"\n"):
        line = line.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        name, _sep, values = line.partition(u"=")
        name = name.strip()
        key = name.lower()
        if not name or key in seen:
            continue
        categories = parse_categories(values)
        if not categories:
            continue
        seen.add(key)
        out.append((name, categories))
    return out


def format_templates(templates):
    lines = []
    for name, categories in templates:
        lines.append(u"{0}={1}".format(name, format_categories(categories)))
    return u"\n".join(lines) + u"\n"


def load_templates(path=None):
    try:
        with io.open(path or templates_path(), u"r", encoding=u"utf-8") as handle:
            return parse_templates(handle.read())
    except Exception:
        return []


def save_templates(templates, path=None):
    try:
        folder = appdata_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(path or templates_path(), u"w", encoding=u"utf-8") as handle:
            handle.write(format_templates(templates))
        return True
    except Exception:
        return False


def put_template(templates, name, categories):
    """Add or replace one template by name, keeping the order of the rest."""
    name = unicode_str(name).strip()
    if not name or not categories:
        return templates
    out = []
    replaced = False
    for existing, values in templates:
        if existing.lower() == name.lower():
            out.append((name, list(categories)))
            replaced = True
        else:
            out.append((existing, values))
    if not replaced:
        out.append((name, list(categories)))
    return out


def drop_template(templates, name):
    key = unicode_str(name).strip().lower()
    return [(n, v) for n, v in templates if n.lower() != key]


def template_named(templates, name):
    key = unicode_str(name).strip().lower()
    for existing, values in templates:
        if existing.lower() == key:
            return values
    return None


# ==========================================================================


def describe_exception(exc):
    """Type and message, because the message on its own is often useless.

    Revit answers most refusals with "A managed exception was thrown by Revit
    or by one of its external applications", which names neither the call nor
    the reason. The .NET exception TYPE usually does say something -
    InvalidOperationException, ArgumentException, InvalidObjectException - and
    it costs nothing to keep.
    """
    try:
        name = type(exc).__name__
    except Exception:
        name = u"Exception"
    try:
        message = unicode_str(exc).strip()
    except Exception:
        message = u""
    if not message:
        return name
    return u"{0}: {1}".format(name, message)


def natural_key(text):
    parts = _NATURAL.split(unicode_str(text))
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part), u""))
        else:
            key.append((1, 0, part.lower()))
    return key


_SEP = re.compile(u"[\\s_\\-\\.,()\\[\\]]+")


def _tokens(text):
    return [t for t in _SEP.split(unicode_str(text).upper()) if t]


def norm_tokens(text):
    """'M-101 P02.pdf' -> '-M-101-P02-PDF-' so a whole sheet number can be
    found between separators whatever separator the file used."""
    return u"-" + u"-".join(_tokens(text)) + u"-"


def _compact(text):
    return re.sub(u"[^A-Z0-9]", u"", unicode_str(text).upper())



# ==========================================================================
# PDF page count (heuristic - no PDF parser is available under IronPython)
# ==========================================================================

_PAGES_A = re.compile(b"/Type\\s*/Pages\\b(?:(?!endobj).){0,400}?/Count\\s+(\\d+)", re.S)
_PAGES_B = re.compile(b"/Count\\s+(\\d+)(?:(?!endobj).){0,400}?/Type\\s*/Pages\\b", re.S)



# ==========================================================================
# grid maths - every grid is a flat list, row major, y down from the top of
# the page, values 0 (white) .. 255 (solid ink) per cell
# ==========================================================================





def collapse(lines):
    """Identical lines folded into one with a count, order kept.

    Eleven copies of "a cloud was refused" is one fact reported eleven times,
    and it buries the two lines underneath that say what actually happened.
    """
    out = []
    counts = {}
    for line in lines:
        if line in counts:
            counts[line] += 1
            continue
        counts[line] = 1
        out.append(line)
    return [(line + (u"  (x{0})".format(counts[line]) if counts[line] > 1 else u""))
            for line in out]


def arc_label(result):
    """How a view is named in the report."""
    name = unicode_str(result.get(u"number", u""))
    against = unicode_str(result.get(u"against", u""))
    if against:
        return u"{0}  (vs {1})".format(name, against)
    return name


def summarise(results):
    """results: list of dicts with 'clouds', 'notes', 'info', 'error'.
    Returns (needs_a_look, text).

    Three kinds of line, and only two of them open the window: an 'error' or
    a 'note' needs a look, an 'info' line is routine and is written into the
    report without forcing it open. Without the split, ordinary running
    commentary - how many elements were read out of each side - would
    interrupt the user on every clean run."""
    lines = []
    needs_look = False
    total = 0
    for r in results:
        label = arc_label(r)
        if r.get(u"error"):
            needs_look = True
            lines.append(u"{0}: FAILED - {1}".format(label, r[u"error"]))
            continue
        clouds = r.get(u"clouds", 0)
        total += clouds
        if clouds == 0:
            lines.append(u"{0}: no change found".format(label))
        else:
            lines.append(u"{0}: {1} cloud(s)".format(label, clouds))
        for note in collapse(r.get(u"notes", [])):
            needs_look = True
            lines.append(u"    {0}".format(note))
        for note in collapse(r.get(u"info", [])):
            lines.append(u"    {0}".format(note))
    head = u"{0} view(s) compared, {1} revision cloud(s) drawn".format(
        len(results), total)
    return needs_look, head + u"\n\n" + u"\n".join(lines)
