# -*- coding: utf-8 -*-
"""Tag Leader Elbow - version, settings and the decision rules.

Deliberately free of any Revit or .NET import, so the rules can be bench
tested under plain CPython without stubbing anything.
"""

import os

__version__ = "3.2.0"

TOOL_NAME = "Tag Leader Elbow"
RIBBON_NAME = "RevoBIM Tag Leader Elbow"

# Revit's internal length unit is always the decimal foot, on every release.
# Doing the conversion with the constant rather than through UnitUtils avoids
# the DisplayUnitType / ForgeTypeId split between 2020 and 2021+ entirely.
MM_PER_FOOT = 304.8

SETTINGS_VERSION = "2"

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "theme": "dark",
    # the elbow itself
    "elbow_mm": "150",
    "base_scale": "50",
    "scale_with_view": "1",
    "direction": "leader",          # leader | reverse
    "existing_elbow": "replace",    # replace | keep
    "ambiguous": "left",            # left | right | skip
    "ambiguous_tol_mm": "1.0",
    "tag_extent": "measured",       # measured | text
    "start_from": "edge",           # edge | head
    "justification": "left",        # left | centre | right
    "head_vertical": "top",         # top | middle | bottom
    "line_pitch": "1.2",
    "glyph_width": "0.52",
    # what it runs on
    "include_spatial_tags": "1",
    "prompt_when_empty": "1",
    "keep_head_fixed": "1",
    "unpin": "1",
    # reporting
    "show_results": "needed",       # needed | always | never
}

# Keys whose meaning or default changed in a given settings version, reset on
# load.  A changed default is not enough on its own: a file written before the
# change carries the old value and would go on quietly using it.
MIGRATIONS = {
    "2": ("ambiguous",),
}

CHOICES = {
    "direction": ("leader", "reverse"),
    "existing_elbow": ("replace", "keep"),
    "ambiguous": ("skip", "left", "right"),
    "tag_extent": ("measured", "text"),
    "start_from": ("edge", "head"),
    "justification": ("left", "centre", "right"),
    "head_vertical": ("top", "middle", "bottom"),
    "show_results": ("needed", "always", "never"),
    "theme": ("dark", "light"),
}


# ============================================================================
# paths
# ============================================================================

def settings_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), "tag_leader_elbow.txt")


def log_path():
    return os.path.join(settings_dir(), "tag_leader_elbow_last_error.txt")


# ============================================================================
# settings, as plain key=value text
# ============================================================================

def load_settings(path=None):
    """Defaults, overlaid key by key with whatever the file actually holds.

    A missing or damaged file falls back to the defaults key by key, and keys
    from an older version are ignored rather than breaking the load.
    """
    cfg = dict(DEFAULTS)
    path = path or settings_path()
    try:
        handle = open(path, "r")
        try:
            lines = handle.read().splitlines()
        finally:
            handle.close()
    except Exception:
        return cfg

    raw = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip()

    was = raw.get("settings_version", "0")
    reset = set()
    if was != SETTINGS_VERSION:
        for version, keys in MIGRATIONS.items():
            if was < version:
                reset.update(keys)

    for key, value in raw.items():
        if key not in DEFAULTS or key in reset:
            continue
        if key in CHOICES and value not in CHOICES[key]:
            continue
        cfg[key] = value

    cfg["settings_version"] = SETTINGS_VERSION
    return cfg


def save_settings(cfg, path=None):
    path = path or settings_path()
    folder = os.path.dirname(path)
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    body = ["# RevoBIM PY - Tag Leader Elbow settings"]
    for key in sorted(DEFAULTS.keys()):
        body.append("{0}={1}".format(key, cfg.get(key, DEFAULTS[key])))
    handle = open(path, "w")
    try:
        handle.write("\n".join(body) + "\n")
    finally:
        handle.close()
    return path


def as_bool(cfg, key):
    return str(cfg.get(key, DEFAULTS.get(key, "0"))).strip() in ("1", "true", "True", "yes", "on")


def as_float(cfg, key, floor=None):
    try:
        value = float(str(cfg.get(key, DEFAULTS.get(key, "0"))).strip())
    except Exception:
        value = float(DEFAULTS.get(key, "0"))
    if floor is not None and value < floor:
        value = float(DEFAULTS.get(key, floor))
    return value


# ============================================================================
# the rules
# ============================================================================

def mm_to_ft(mm):
    return float(mm) / MM_PER_FOOT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FOOT


def elbow_length_mm(cfg, view_scale):
    """How long the horizontal leg is, in model millimetres, for this view.

    The elbow is a paper-space shape: 150mm at 1:50 is 3mm on the sheet, and
    3mm on the sheet at 1:100 is 300mm in the model.  So the model length is
    the nominal length times the ratio of the view's scale to the scale the
    nominal length was quoted at.  Turn scale_with_view off and the model
    length is the same at every scale instead.
    """
    nominal = as_float(cfg, "elbow_mm", floor=0.0)
    if not as_bool(cfg, "scale_with_view"):
        return nominal
    base = as_float(cfg, "base_scale", floor=1.0)
    try:
        scale = float(view_scale)
    except Exception:
        scale = base
    if scale <= 0:
        scale = base
    return nominal * (scale / base)


def elbow_length_ft(cfg, view_scale):
    return mm_to_ft(elbow_length_mm(cfg, view_scale))


# ---- how far out the leg starts -------------------------------------------

def estimate_text_width_mm(text, size_mm, width_factor=1.0, glyph=0.52):
    """A character count standing in for a real measurement.

    Only reached when WPF will not measure the string.  0.52 of the em is
    about right for Arial and the sans fonts tag types actually use; it is a
    setting because a condensed or a wide font moves it.
    """
    if not text:
        return 0.0
    lines = str(text).splitlines() or [str(text)]
    widest = max(len(line) for line in lines)
    return widest * float(size_mm) * float(width_factor) * float(glyph)


def text_ahead_ft(text_width_ft, sign, cfg):
    """How much tag text lies between the head and the side the leg goes.

    Which is not half the width unless the text is centred on the head.  A
    left justified tag has its head at the left hand end of the text: going
    left there is nothing in the way at all, and going right the whole width
    is.  A right justified tag is the mirror of that.
    """
    width = float(text_width_ft or 0.0)
    where = cfg.get("justification", "left")
    if where == "centre":
        return width / 2.0
    if where == "right":
        return width if sign < 0 else 0.0
    return width if sign > 0 else 0.0


def ahead_from_box_ft(box, sign, cfg):
    """How much tag lies between the head and the side the leg goes, taken
    from the tag's own measured extent rather than from its text.

    `box` is (up min, up max, right min, right max), each measured from the tag
    head along the view's own axes.
    """
    if not box:
        return None
    right_min, right_max = box[2], box[3]
    ahead = right_max if sign > 0 else -right_min
    return ahead if ahead > 0.0 else 0.0


def centre_from_box_ft(box):
    """How far the elbow drops, or rises, to sit on the tag's own vertical
    middle.  Positive is up the view."""
    if not box:
        return None
    return (box[0] + box[1]) / 2.0


def vertical_shift_ft(line_ft, line_count, cfg):
    """How far the elbow has to drop, or rise, to sit on the tag's own
    vertical centre.  Positive is up the view.

    Revit draws the run from the tag to the elbow **horizontally only when the
    elbow is level with where the leader meets the tag**, which is the vertical
    middle of the text block.  On a multi-line tag `TagHeadPosition` is at the
    top line, so an elbow left level with the head lands above the text and the
    shoulder comes out sloped.
    """
    try:
        lines = int(line_count or 1)
    except Exception:
        lines = 1
    where = cfg.get("head_vertical", "top")
    if lines < 2 or where == "middle":
        return 0.0
    span = (lines - 1) / 2.0 * float(line_ft or 0.0)
    return -span if where == "top" else span


def leg_offset_ft(text_width_ft, leg_ft, sign, cfg):
    """Where the elbow lands, measured from the tag head along the view's
    horizontal.  Measuring from the edge is what puts the elbow clear of the
    text rather than inside it."""
    if cfg.get("start_from", "edge") == "head":
        return leg_ft
    return text_ahead_ft(text_width_ft, sign, cfg) + leg_ft


def choose_sign(along, cfg):
    """Which way along the view's horizontal the elbow leg goes.

    `along` is the distance from the tag head to the leader's far end measured
    along the view's right direction, in feet.  Positive means the leader runs
    to the right of the head on the sheet.
    """
    tol = mm_to_ft(as_float(cfg, "ambiguous_tol_mm", floor=0.0))
    mode = cfg.get("ambiguous", "skip")
    if along > tol:
        sign = 1
    elif along < -tol:
        sign = -1
    else:
        # No side to take from the leader, so the fallback decides, and it
        # decides absolutely: "reverse" is the opposite of a direction the
        # leader does not have here, so it is not applied to the fallback.
        if mode == "left":
            return -1, None
        if mode == "right":
            return 1, None
        return 0, "leader runs square to the view, no side to elbow towards"
    if cfg.get("direction", "leader") == "reverse":
        sign = -sign
    return sign, None


def decide(has_leader, along, has_elbow, cfg):
    """The whole per-leader decision, on plain numbers.

    Returns (sign, reason).  A sign of 0 means leave this leader alone and
    report `reason`; anything else is the direction to place the elbow in.
    """
    if not has_leader:
        return 0, "no leader turned on"
    if has_elbow and cfg.get("existing_elbow", "replace") == "keep":
        return 0, "already has an elbow, left alone"
    if along is None:
        return 0, "leader end could not be located"
    return choose_sign(along, cfg)


def describe_length(cfg, view_scale):
    mm = elbow_length_mm(cfg, view_scale)
    if as_bool(cfg, "scale_with_view"):
        return "{0:.0f}mm at 1:{1:.0f}  ({2:.0f}mm nominal at 1:{3:.0f})".format(
            mm, float(view_scale), as_float(cfg, "elbow_mm"), as_float(cfg, "base_scale"))
    return "{0:.0f}mm at every scale".format(mm)


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026; .Value is the one."""
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
