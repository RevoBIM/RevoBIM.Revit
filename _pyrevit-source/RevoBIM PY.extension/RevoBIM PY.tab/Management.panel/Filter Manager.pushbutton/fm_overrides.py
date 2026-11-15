# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : filter graphic overrides.

The same set of properties Revit's own Visibility/Graphics > Filters tab
asks for, read out of and written back into OverrideGraphicSettings.

Revit 2021 - 2027.
"""

import fm_clr  # noqa  - must be first

from Autodesk.Revit.DB import (
    Color,
    ElementId,
    FilteredElementCollector,
    FillPatternElement,
    LinePatternElement,
    OverrideGraphicSettings,
)

from fm_core import eid_value


NO_OVERRIDE = "<no override>"
SOLID_LINE = "<solid line>"

# the spec dict every part of the tool passes around
DEFAULT_SPEC = {
    "visible": True,
    "enabled": True,
    "halftone": False,
    "transparency": 0,

    "proj_colour": None,        # "RRGGBB" or None
    "proj_weight": None,        # 1-16 or None
    "proj_pattern": None,       # ElementId or None

    "cut_colour": None,
    "cut_weight": None,
    "cut_pattern": None,

    "surf_fg_pattern": None,    # ElementId or None
    "surf_fg_colour": None,
    "surf_bg_pattern": None,
    "surf_bg_colour": None,

    "cut_fg_pattern": None,
    "cut_fg_colour": None,
    "cut_bg_pattern": None,
    "cut_bg_colour": None,
}


def new_spec():
    out = {}
    for k in DEFAULT_SPEC:
        out[k] = DEFAULT_SPEC[k]
    return out


# ---------------------------------------------------------------------------
#  Colours
# ---------------------------------------------------------------------------
def parse_hex(text):
    """'#RRGGBB' or 'RRGGBB' -> (r, g, b), or None."""
    if text is None:
        return None
    s = str(text).strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return None


def to_hex(rgb):
    if rgb is None:
        return None
    return "{0:02X}{1:02X}{2:02X}".format(rgb[0], rgb[1], rgb[2])


def revit_colour(text):
    rgb = parse_hex(text)
    if rgb is None:
        return None
    try:
        return Color(rgb[0], rgb[1], rgb[2])
    except Exception:
        return None


def colour_from_revit(c):
    """A Revit Color to 'RRGGBB', or None where it is not a real override."""
    if c is None:
        return None
    try:
        if not c.IsValid:
            return None
    except Exception:
        pass
    try:
        return "{0:02X}{1:02X}{2:02X}".format(c.Red, c.Green, c.Blue)
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  Pattern lists
# ---------------------------------------------------------------------------
def line_patterns(doc):
    """[(ElementId or None, name)] starting with no-override and solid."""
    out = [(None, NO_OVERRIDE)]
    try:
        out.append((LinePatternElement.GetSolidPatternId(), SOLID_LINE))
    except Exception:
        pass
    items = []
    try:
        for lp in FilteredElementCollector(doc)\
                .OfClass(LinePatternElement).ToElements():
            try:
                items.append((lp.Id, lp.Name))
            except Exception:
                continue
    except Exception:
        pass
    try:
        items.sort(key=lambda x: x[1].lower())
    except Exception:
        pass
    return out + items


def fill_patterns(doc):
    """[(ElementId or None, name)] of every fill pattern in the project."""
    out = [(None, NO_OVERRIDE)]
    items = []
    try:
        for fp in FilteredElementCollector(doc)\
                .OfClass(FillPatternElement).ToElements():
            try:
                items.append((fp.Id, fp.Name))
            except Exception:
                continue
    except Exception:
        pass
    try:
        items.sort(key=lambda x: x[1].lower())
    except Exception:
        pass
    return out + items


def line_weights():
    """[(int or None, label)] - Revit line weights are 1 to 16."""
    out = [(None, NO_OVERRIDE)]
    for i in range(1, 17):
        out.append((i, str(i)))
    return out


# ---------------------------------------------------------------------------
#  Reading an existing override off a view
# ---------------------------------------------------------------------------
def read_overrides(view, filter_id):
    """A spec dict describing how this view already overrides the filter."""
    spec = new_spec()
    try:
        spec["visible"] = bool(view.GetFilterVisibility(filter_id))
    except Exception:
        pass
    try:
        spec["enabled"] = bool(view.GetIsFilterEnabled(filter_id))
    except Exception:
        pass

    try:
        ogs = view.GetFilterOverrides(filter_id)
    except Exception:
        return spec
    if ogs is None:
        return spec

    spec["halftone"] = _safe(ogs, "Halftone", False)
    spec["transparency"] = _safe(ogs, "Transparency", 0)

    spec["proj_colour"] = colour_from_revit(_safe(ogs, "ProjectionLineColor", None))
    spec["proj_weight"] = _weight(_safe(ogs, "ProjectionLineWeight", -1))
    spec["proj_pattern"] = _pattern(_safe(ogs, "ProjectionLinePatternId", None))

    spec["cut_colour"] = colour_from_revit(_safe(ogs, "CutLineColor", None))
    spec["cut_weight"] = _weight(_safe(ogs, "CutLineWeight", -1))
    spec["cut_pattern"] = _pattern(_safe(ogs, "CutLinePatternId", None))

    spec["surf_fg_pattern"] = _pattern(
        _safe(ogs, "SurfaceForegroundPatternId", None))
    spec["surf_fg_colour"] = colour_from_revit(
        _safe(ogs, "SurfaceForegroundPatternColor", None))
    spec["surf_bg_pattern"] = _pattern(
        _safe(ogs, "SurfaceBackgroundPatternId", None))
    spec["surf_bg_colour"] = colour_from_revit(
        _safe(ogs, "SurfaceBackgroundPatternColor", None))

    spec["cut_fg_pattern"] = _pattern(_safe(ogs, "CutForegroundPatternId", None))
    spec["cut_fg_colour"] = colour_from_revit(
        _safe(ogs, "CutForegroundPatternColor", None))
    spec["cut_bg_pattern"] = _pattern(_safe(ogs, "CutBackgroundPatternId", None))
    spec["cut_bg_colour"] = colour_from_revit(
        _safe(ogs, "CutBackgroundPatternColor", None))

    return spec


def _safe(obj, attr, fallback):
    try:
        v = getattr(obj, attr)
        return v() if callable(v) else v
    except Exception:
        return fallback


def _weight(value):
    try:
        v = int(value)
        return v if 1 <= v <= 16 else None
    except Exception:
        return None


def _pattern(pid):
    if pid is None:
        return None
    try:
        return pid if eid_value(pid) > 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  Building an override from a spec
# ---------------------------------------------------------------------------
def build_overrides(spec):
    """OverrideGraphicSettings from a spec dict. Anything None is left alone."""
    ogs = OverrideGraphicSettings()

    _set(ogs, "SetProjectionLineColor", revit_colour(spec.get("proj_colour")))
    _set(ogs, "SetProjectionLineWeight", spec.get("proj_weight"))
    _set(ogs, "SetProjectionLinePatternId", spec.get("proj_pattern"))

    _set(ogs, "SetCutLineColor", revit_colour(spec.get("cut_colour")))
    _set(ogs, "SetCutLineWeight", spec.get("cut_weight"))
    _set(ogs, "SetCutLinePatternId", spec.get("cut_pattern"))

    _set(ogs, "SetSurfaceForegroundPatternId", spec.get("surf_fg_pattern"))
    _set(ogs, "SetSurfaceForegroundPatternColor",
         revit_colour(spec.get("surf_fg_colour")))
    _set(ogs, "SetSurfaceBackgroundPatternId", spec.get("surf_bg_pattern"))
    _set(ogs, "SetSurfaceBackgroundPatternColor",
         revit_colour(spec.get("surf_bg_colour")))

    _set(ogs, "SetCutForegroundPatternId", spec.get("cut_fg_pattern"))
    _set(ogs, "SetCutForegroundPatternColor",
         revit_colour(spec.get("cut_fg_colour")))
    _set(ogs, "SetCutBackgroundPatternId", spec.get("cut_bg_pattern"))
    _set(ogs, "SetCutBackgroundPatternColor",
         revit_colour(spec.get("cut_bg_colour")))

    if spec.get("surf_fg_pattern") is not None:
        _set(ogs, "SetSurfaceForegroundPatternVisible", True)
    if spec.get("surf_bg_pattern") is not None:
        _set(ogs, "SetSurfaceBackgroundPatternVisible", True)
    if spec.get("cut_fg_pattern") is not None:
        _set(ogs, "SetCutForegroundPatternVisible", True)
    if spec.get("cut_bg_pattern") is not None:
        _set(ogs, "SetCutBackgroundPatternVisible", True)

    try:
        t = int(spec.get("transparency") or 0)
        ogs.SetSurfaceTransparency(max(0, min(100, t)))
    except Exception:
        pass
    try:
        ogs.SetHalftone(bool(spec.get("halftone")))
    except Exception:
        pass

    return ogs


def _set(ogs, method_name, value):
    if value is None:
        return
    method = getattr(ogs, method_name, None)
    if method is None:
        return
    try:
        method(value)
    except Exception:
        pass


def describe(spec):
    """A short human summary of a spec, for the log."""
    bits = []
    bits.append("visible" if spec.get("visible") else "HIDDEN")
    if not spec.get("enabled"):
        bits.append("filter disabled")
    if spec.get("halftone"):
        bits.append("halftone")
    if spec.get("transparency"):
        bits.append("transparency {0}%".format(spec.get("transparency")))
    if spec.get("proj_colour"):
        bits.append("line #" + spec["proj_colour"])
    if spec.get("proj_weight"):
        bits.append("weight {0}".format(spec["proj_weight"]))
    if spec.get("surf_fg_colour"):
        bits.append("surface #" + spec["surf_fg_colour"])
    if spec.get("cut_colour"):
        bits.append("cut line #" + spec["cut_colour"])
    if spec.get("cut_fg_colour"):
        bits.append("cut surface #" + spec["cut_fg_colour"])
    return ", ".join(bits) if bits else "no overrides"


# ===========================================================================
#  Pushing some settings and not others
# ===========================================================================
# The columns of "Filters to push", in Revit's own V/G order.
PUSH_GROUPS = [
    ("enabled", "Enable Filter"),
    ("visible", "Visibility"),
    ("proj_lines", "Projection Lines"),
    ("proj_patterns", "Projection Patterns"),
    ("transparency", "Transparency"),
    ("cut_lines", "Cut Lines"),
    ("cut_patterns", "Cut Patterns"),
    ("halftone", "Halftone"),
]

# group -> the OverrideGraphicSettings properties it carries:
# (getter, setter, kind). Enable and Visibility are not overrides - they are
# set on the view directly - so they have no entry here.
OVERRIDE_GROUPS = {
    "proj_lines": [
        ("ProjectionLinePatternId", "SetProjectionLinePatternId", "id"),
        ("ProjectionLineColor", "SetProjectionLineColor", "colour"),
        ("ProjectionLineWeight", "SetProjectionLineWeight", "weight"),
    ],
    "proj_patterns": [
        ("SurfaceForegroundPatternId", "SetSurfaceForegroundPatternId", "id"),
        ("SurfaceForegroundPatternColor", "SetSurfaceForegroundPatternColor",
         "colour"),
        ("IsSurfaceForegroundPatternVisible",
         "SetSurfaceForegroundPatternVisible", "shown"),
        ("SurfaceBackgroundPatternId", "SetSurfaceBackgroundPatternId", "id"),
        ("SurfaceBackgroundPatternColor", "SetSurfaceBackgroundPatternColor",
         "colour"),
        ("IsSurfaceBackgroundPatternVisible",
         "SetSurfaceBackgroundPatternVisible", "shown"),
    ],
    "transparency": [
        ("Transparency", "SetSurfaceTransparency", "number"),
    ],
    "cut_lines": [
        ("CutLinePatternId", "SetCutLinePatternId", "id"),
        ("CutLineColor", "SetCutLineColor", "colour"),
        ("CutLineWeight", "SetCutLineWeight", "weight"),
    ],
    "cut_patterns": [
        ("CutForegroundPatternId", "SetCutForegroundPatternId", "id"),
        ("CutForegroundPatternColor", "SetCutForegroundPatternColor", "colour"),
        ("IsCutForegroundPatternVisible", "SetCutForegroundPatternVisible",
         "shown"),
        ("CutBackgroundPatternId", "SetCutBackgroundPatternId", "id"),
        ("CutBackgroundPatternColor", "SetCutBackgroundPatternColor", "colour"),
        ("IsCutBackgroundPatternVisible", "SetCutBackgroundPatternVisible",
         "shown"),
    ],
    "halftone": [
        ("Halftone", "SetHalftone", "flag"),
    ],
}


def all_groups(value=True):
    return dict((key, bool(value)) for key, _label in PUSH_GROUPS)


def groups_all_on(groups):
    return groups is None or all(groups.get(k, True) for k, _l in PUSH_GROUPS)


def _is_override(value, kind):
    """Whether a property holds an override rather than Revit's default.

    Starting from a fresh OverrideGraphicSettings, only overrides need
    writing - which matters, because an invalid colour or id cannot always
    be written back, and "no override" is already what a fresh one holds.
    """
    if value is None:
        return False
    try:
        if kind == "id":
            return eid_value(value) > 0
        if kind == "colour":
            return bool(getattr(value, "IsValid", False))
        if kind == "weight":
            return int(value) > 0
        if kind == "number":
            return int(value) > 0
        if kind == "flag":
            return bool(value)
        if kind == "shown":
            return value is False
    except Exception:
        return False
    return False


def merge_overrides(source, base, groups, factory=None):
    """Overrides taking each ticked group from `source` and each unticked
    one from `base` (the target's own, or None for a filter new to it, so
    an unticked group is simply left at Revit's default)."""
    ogs = (factory or OverrideGraphicSettings)()
    for key, props in OVERRIDE_GROUPS.items():
        provider = source if groups.get(key, True) else base
        if provider is None:
            continue
        for getter, setter, kind in props:
            try:
                value = getattr(provider, getter)
            except Exception:
                continue
            if _is_override(value, kind):
                _set(ogs, setter, value)
    return ogs


def describe_groups(groups):
    """'all settings', or the ones left out, for the log."""
    if groups_all_on(groups):
        return "all settings"
    off = [label for key, label in PUSH_GROUPS if not groups.get(key, True)]
    return "not pushed: " + ", ".join(off)

