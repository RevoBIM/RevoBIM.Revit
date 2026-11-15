# -*- coding: utf-8 -*-
"""RevoBIM PY - Service Spacing : shared core.

Geometry, settings and the spacing routine, shared by the command button and
the Settings button.  Written to run unchanged on Revit 2024 - 2027 and on
both IronPython 2.7 and IronPython 3:  no f-strings, no System.Uri, no bare
ElementId.IntegerValue, integer division with //.
"""

__version__ = "1.2.0"

import os
import io
import math

from Autodesk.Revit import DB
from Autodesk.Revit.DB import XYZ, Transform, ElementId, BuiltInParameter

# --- optional namespaces -----------------------------------------------------
# Anything not needed to do the work is imported on its own inside a
# try/except, so a name missing on one release cannot take the tool down at
# module load (a blank white pyRevit window).

try:
    from Autodesk.Revit.DB.Plumbing import Pipe
except Exception:
    Pipe = None
try:
    from Autodesk.Revit.DB.Mechanical import Duct
except Exception:
    Duct = None
try:
    from Autodesk.Revit.DB.Electrical import CableTray, Conduit
except Exception:
    CableTray = None
    Conduit = None
try:
    from Autodesk.Revit.DB import InsulationLiningBase
except Exception:
    InsulationLiningBase = None


# =============================================================================
# units
# =============================================================================

FT_TO_MM = 304.8


def mm_to_ft(value_mm):
    return float(value_mm) / FT_TO_MM


def ft_to_mm(value_ft):
    return float(value_ft) * FT_TO_MM


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026.  Prefer .Value."""
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


def fmt(value, places=0):
    """Format a number without f-strings."""
    try:
        if places == 0:
            return "{0:.0f}".format(value)
        return ("{0:." + str(places) + "f}").format(value)
    except Exception:
        return str(value)


# =============================================================================
# settings
# =============================================================================

SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or "", "RevoBIM")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "service_spacing.txt")

SETTINGS_VERSION = 3

DEFAULTS = {
    "settings_version": str(SETTINGS_VERSION),
    # the rule
    "gap_services": "75",           # clear gap, service to service (mm)
    "gap_containment": "50",        # clear gap where a cable tray is involved
    "gap_trunking": "70",           # clear gap where trunking is involved
    "trunking_token": "Trunking",   # family name token that means trunking
    "trunking_gap_wins": "1",       # trunking overrides the mixed rule
    "mixed_gap": "larger",          # larger | services | containment
    "round_to": "5",                # round centre-to-centre up to (mm), 0 = off
    "include_insulation": "1",      # add insulation / lining thickness
    # geometry
    "spacing_axis": "auto",         # auto | horizontal | vertical
    "anchor": "first_along_axis",   # first_along_axis | first_selected | largest
    "order": "spatial",             # spatial | selection
    "angle_tolerance_deg": "5",
    # rows
    "row_split": "1",               # split the selection into rows by level
    "row_clear_mm": "60",           # more than this top-to-bottom = a new row
    "space_rows": "0",              # also space the rows apart vertically
    # behaviour
    "move_run": "1",                # carry connected fittings and inline runs
    "max_run_elements": "400",
    "unpin": "1",
    "show_results": "auto",         # auto | always | never
}

# A settings key whose meaning changes needs a migration, not just a new
# default.  MIGRATIONS lists the keys each version resets on load.
MIGRATIONS = {
    # 1.1.0 raised the service clear gap from 25mm to 75mm edge to edge.  A
    # file saved at 25 would otherwise keep spacing on the old figure without
    # anything on screen saying so.
    2: ["gap_services"],
    # 1.2.0 introduced the trunking gap and row splitting; nothing saved at
    # version 2 can carry a value for them, so there is nothing to reset.
}


class Settings(object):
    def __init__(self, data=None):
        self.data = dict(DEFAULTS)
        if data:
            self.data.update(data)

    # -- typed access ---------------------------------------------------------
    def text(self, key):
        return self.data.get(key, DEFAULTS.get(key, ""))

    def number(self, key):
        try:
            return float(self.data.get(key, DEFAULTS.get(key, "0")))
        except Exception:
            try:
                return float(DEFAULTS.get(key, "0"))
            except Exception:
                return 0.0

    def flag(self, key):
        return str(self.data.get(key, DEFAULTS.get(key, "0"))).strip() in (
            "1", "true", "True", "yes", "on")

    def set(self, key, value):
        self.data[key] = str(value)


def load_settings():
    """Missing or damaged file falls back to the defaults key by key; keys
    from an older version are ignored rather than breaking the load."""
    data = dict(DEFAULTS)
    raw = {}
    try:
        if os.path.isfile(SETTINGS_PATH):
            handle = None
            try:
                handle = io.open(SETTINGS_PATH, "r", encoding="utf-8")
                lines = handle.readlines()
            except Exception:
                handle = open(SETTINGS_PATH, "r")
                lines = handle.readlines()
            finally:
                try:
                    if handle is not None:
                        handle.close()
                except Exception:
                    pass
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # split on the first = only, so a value may contain =
                parts = line.split("=", 1)
                key = parts[0].strip()
                value = parts[1].strip()
                if key:
                    raw[key] = value
    except Exception:
        raw = {}

    try:
        found_version = int(raw.get("settings_version", "0"))
    except Exception:
        found_version = 0

    for key in DEFAULTS.keys():
        if key in raw:
            data[key] = raw[key]

    # reset keys whose meaning changed since the saved version
    for version in sorted(MIGRATIONS.keys()):
        if found_version < version:
            for key in MIGRATIONS[version]:
                data[key] = DEFAULTS.get(key, "")

    data["settings_version"] = str(SETTINGS_VERSION)
    return Settings(data)


def save_settings(settings):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
    except Exception:
        pass
    lines = []
    lines.append("# RevoBIM PY - Service Spacing settings")
    for key in sorted(settings.data.keys()):
        lines.append("{0}={1}".format(key, settings.data[key]))
    body = "\n".join(lines) + "\n"
    try:
        handle = io.open(SETTINGS_PATH, "w", encoding="utf-8")
        try:
            handle.write(body if isinstance(body, type(u"")) else body.decode("utf-8"))
        finally:
            handle.close()
        return True
    except Exception:
        try:
            handle = open(SETTINGS_PATH, "w")
            try:
                handle.write(body)
            finally:
                handle.close()
            return True
        except Exception:
            return False


# =============================================================================
# element classification
# =============================================================================

CONTAINMENT_BICS = ["OST_CableTray", "OST_CableTrayFitting"]
SERVICE_BICS = [
    "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory",
    "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting",
    "OST_DuctAccessory", "OST_FlexPipeCurves",
    "OST_Conduit", "OST_ConduitFitting",
    "OST_GenericModel",
]


def _bic_name(element):
    try:
        cat = element.Category
        if cat is None:
            return ""
        try:
            return str(DB.BuiltInCategory.ToObject(cat.Id).ToString())
        except Exception:
            pass
        # fall back on the id value against the enum
        value = eid_value(cat.Id)
        for name in CONTAINMENT_BICS + SERVICE_BICS:
            try:
                if int(getattr(DB.BuiltInCategory, name)) == value:
                    return name
            except Exception:
                continue
    except Exception:
        pass
    return ""


def is_containment(element):
    """Cable tray (and tray fittings) are spaced edge to edge, not on the
    service clear-gap rule."""
    try:
        if CableTray is not None and isinstance(element, CableTray):
            return True
    except Exception:
        pass
    name = _bic_name(element)
    return name in CONTAINMENT_BICS


def family_name(element):
    """The family the element's type belongs to.

    Trunking and basket are Cable Tray system types, not separate Revit
    categories, and what identifies them lives in the family naming rather
    than in the type name - the same rule the Containment System Creator
    resolves kinds by.  The type name and the fitting family names are read
    as well, because a type carrying no token in its own name may still sit
    in a trunking family.
    """
    names = []
    try:
        symbol = element.Symbol
        if symbol is not None and symbol.Family is not None:
            names.append(symbol.Family.Name)
    except Exception:
        pass
    try:
        element_type = element.Document.GetElement(element.GetTypeId())
        if element_type is not None:
            try:
                if element_type.FamilyName:
                    names.append(element_type.FamilyName)
            except Exception:
                pass
            try:
                names.append(element_type.Name)
            except Exception:
                pass
    except Exception:
        pass
    try:
        names.append(element.Name)
    except Exception:
        pass
    return " ".join([n for n in names if n])


def _squash(text):
    """Trunking / TrunkingTray / Trunking Tray / trunking_tray all resolve to
    the same token."""
    return "".join([c for c in str(text).lower() if c.isalnum()])


def is_trunking(element, settings=None):
    token = "trunking"
    if settings is not None:
        token = _squash(settings.text("trunking_token")) or "trunking"
    if not is_containment(element):
        return False
    return token in _squash(family_name(element))


def gap_class(element, settings):
    """Which clear gap this element brings to a pair."""
    if is_containment(element):
        if is_trunking(element, settings):
            return "trunking"
        return "containment"
    return "service"


def kind_label(element, settings=None):
    if is_containment(element):
        if is_trunking(element, settings):
            return "Trunking"
        return "Cable tray"
    try:
        if Pipe is not None and isinstance(element, Pipe):
            return "Pipe"
        if Duct is not None and isinstance(element, Duct):
            return "Duct"
        if Conduit is not None and isinstance(element, Conduit):
            return "Conduit"
    except Exception:
        pass
    try:
        return element.Category.Name
    except Exception:
        return "Element"


def describe(element, settings=None):
    try:
        name = element.Name
    except Exception:
        name = ""
    return "{0} {1} [{2}]".format(kind_label(element, settings), name,
                                  eid_value(element.Id))


# =============================================================================
# geometry helpers
# =============================================================================

def location_curve(element):
    try:
        loc = element.Location
        if loc is not None and hasattr(loc, "Curve"):
            return loc.Curve
    except Exception:
        pass
    return None


def location_point(element):
    curve = location_curve(element)
    if curve is not None:
        try:
            return curve.Evaluate(0.5, True)
        except Exception:
            pass
    try:
        loc = element.Location
        if loc is not None and hasattr(loc, "Point"):
            return loc.Point
    except Exception:
        pass
    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            return (box.Min + box.Max) * 0.5
    except Exception:
        pass
    return None


def element_direction(element):
    curve = location_curve(element)
    if curve is None:
        return None
    try:
        vector = curve.GetEndPoint(1) - curve.GetEndPoint(0)
        if vector.GetLength() < 1e-9:
            return None
        return vector.Normalize()
    except Exception:
        return None


def dominant_direction(elements):
    """Majority wins where they are not all parallel.  The sign is normalised
    so the axis always comes out the same way round."""
    vectors = []
    for element in elements:
        direction = element_direction(element)
        if direction is None:
            continue
        if direction.Z < 0:
            direction = direction.Negate()
        vectors.append(direction)
    if not vectors:
        return None

    best = None
    best_count = -1
    for candidate in vectors:
        count = 0
        for other in vectors:
            if abs(candidate.DotProduct(other)) > 0.996:   # ~5 degrees
                count += 1
        if count > best_count:
            best_count = count
            best = candidate
    if best is None:
        return None
    # normalise the sign: positive X, then positive Y
    if best.X < -1e-9 or (abs(best.X) < 1e-9 and best.Y < -1e-9):
        best = best.Negate()
    return best


def spacing_axis(elements, settings):
    """The axis the elements are spread along.

    horizontal : square to the run, in plan
    vertical   : world Z, for a stacked bank
    """
    mode = settings.text("spacing_axis")
    if mode == "vertical":
        return XYZ(0, 0, 1), "vertical"

    run = dominant_direction(elements)
    if run is None:
        return XYZ(1, 0, 0), "horizontal"

    flat = XYZ(run.X, run.Y, 0)
    if flat.GetLength() < 1e-6:
        # a bank of vertical risers has no plan direction to be square to
        if mode == "horizontal":
            return XYZ(1, 0, 0), "horizontal"
        return XYZ(0, 0, 1), "vertical"

    axis = flat.Normalize().CrossProduct(XYZ(0, 0, 1))
    if axis.GetLength() < 1e-6:
        return XYZ(1, 0, 0), "horizontal"
    axis = axis.Normalize()
    if axis.X < -1e-9 or (abs(axis.X) < 1e-9 and axis.Y < -1e-9):
        axis = axis.Negate()
    return axis, "horizontal"


def _walk_geometry(geometry, solids):
    """Steps into GeometryInstance, which is what makes the same code work on
    family instances as on MEP curves."""
    if geometry is None:
        return
    for item in geometry:
        try:
            if isinstance(item, DB.Solid):
                if item.Volume > 1e-9:
                    solids.append(item)
            elif isinstance(item, DB.GeometryInstance):
                _walk_geometry(item.GetInstanceGeometry(), solids)
            elif hasattr(item, "__iter__"):
                _walk_geometry(item, solids)
        except Exception:
            continue


def element_solids(element):
    solids = []
    for detail in (DB.ViewDetailLevel.Fine, DB.ViewDetailLevel.Medium):
        try:
            options = DB.Options()
            options.DetailLevel = detail
            options.IncludeNonVisibleObjects = False
            _walk_geometry(element.get_Geometry(options), solids)
        except Exception:
            solids = []
        if solids:
            break
    return solids


def insulation_mm(document, element):
    """Insulation is a separate element, so its thickness has to be added to
    the solid extent rather than read from it."""
    thickness = 0.0
    if InsulationLiningBase is not None:
        try:
            ids = InsulationLiningBase.GetInsulationIds(document, element.Id)
            for insulation_id in ids:
                item = document.GetElement(insulation_id)
                if item is None:
                    continue
                parameter = item.get_Parameter(
                    BuiltInParameter.RBS_INSULATION_THICKNESS_FOR_DUCT)
                if parameter is None:
                    parameter = item.LookupParameter("Insulation Thickness")
                if parameter is not None:
                    thickness = max(thickness, ft_to_mm(parameter.AsDouble()))
        except Exception:
            pass
    if thickness <= 0.0:
        for name in ("Insulation Thickness", "Lining Thickness"):
            try:
                parameter = element.LookupParameter(name)
                if parameter is not None:
                    thickness = max(thickness, ft_to_mm(parameter.AsDouble()))
            except Exception:
                continue
    return thickness


def _param_half_width_mm(element):
    """Fallback when there is no solid geometry - a Coarse view, a line-only
    symbol, or a family Revit will not give geometry up for."""
    names = [
        BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
        BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
        BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
    ]
    for bip in names:
        try:
            parameter = element.get_Parameter(bip)
            if parameter is not None and parameter.HasValue:
                value = ft_to_mm(parameter.AsDouble())
                if value > 0.0:
                    return value / 2.0
        except Exception:
            continue
    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            width = max(ft_to_mm(box.Max.X - box.Min.X),
                        ft_to_mm(box.Max.Y - box.Min.Y))
            if width > 0.0:
                return width / 2.0
    except Exception:
        pass
    return 0.0


def half_extent_mm(document, element, axis, settings):
    """Half the element's own width measured square to the run - taken from
    the solids' own vertices, so a rotated tray or an angled run is measured
    correctly rather than inflated by an axis-aligned bounding box.
    """
    centre = location_point(element)
    solids = element_solids(element)
    extent = 0.0
    if centre is not None and solids:
        for solid in solids:
            try:
                for edge in solid.Edges:
                    curve = edge.AsCurve()
                    for point in (curve.GetEndPoint(0), curve.GetEndPoint(1)):
                        offset = abs((point - centre).DotProduct(axis))
                        if offset > extent:
                            extent = offset
            except Exception:
                continue
        extent = ft_to_mm(extent)

    if extent <= 0.0:
        extent = _param_half_width_mm(element)

    if settings.flag("include_insulation"):
        extent += insulation_mm(document, element)
    return extent


def vertical_span_mm(document, element, settings):
    """The element's top and bottom in world Z, in millimetres.

    Rows are decided on the real clear distance between a top edge and a
    bottom edge, so this has to be the actual extents rather than a symmetric
    half width off the centreline - a tray and a pipe at the same centreline
    Z do not have the same top edge.
    """
    solids = element_solids(element)
    low = None
    high = None
    for solid in solids:
        try:
            for edge in solid.Edges:
                curve = edge.AsCurve()
                for point in (curve.GetEndPoint(0), curve.GetEndPoint(1)):
                    z = ft_to_mm(point.Z)
                    if low is None or z < low:
                        low = z
                    if high is None or z > high:
                        high = z
        except Exception:
            continue

    if low is None or high is None:
        try:
            box = element.get_BoundingBox(None)
            if box is not None:
                low = ft_to_mm(box.Min.Z)
                high = ft_to_mm(box.Max.Z)
        except Exception:
            pass

    if low is None or high is None:
        point = location_point(element)
        centre = ft_to_mm(point.Z) if point is not None else 0.0
        half = _param_half_width_mm(element)
        low = centre - half
        high = centre + half

    if settings.flag("include_insulation"):
        thickness = insulation_mm(document, element)
        low -= thickness
        high += thickness
    return low, high


def split_into_rows(rows, settings):
    """Group the string into rows by elevation.

    Two services belong to the same row while the clear distance between the
    top edge of the lower and the bottom edge of the upper is no more than
    the row clearance.  Anything further apart is a separate row and is
    spaced on its own, so a tray in the ceiling is never spaced against a
    pipe at low level just because both were selected.
    """
    if not settings.flag("row_split") or len(rows) < 2:
        for row in rows:
            row.row = 0
        return [list(rows)]

    clearance = settings.number("row_clear_mm")
    ordered = sorted(rows, key=lambda item: item.bottom)

    groups = []
    current = [ordered[0]]
    ceiling = ordered[0].top
    for row in ordered[1:]:
        if (row.bottom - ceiling) > clearance:
            groups.append(current)
            current = [row]
            ceiling = row.top
        else:
            current.append(row)
            if row.top > ceiling:
                ceiling = row.top
    groups.append(current)

    for index, group in enumerate(groups):
        for row in group:
            row.row = index
    return groups


# =============================================================================
# the rule
# =============================================================================

def round_up(value_mm, step_mm):
    if step_mm is None or step_mm <= 0:
        return value_mm
    return math.ceil(value_mm / float(step_mm) - 1e-9) * float(step_mm)


def pair_gap_mm(class_a, class_b, settings):
    """The clear gap a pair of elements is entitled to.

    Trunking takes precedence: where either element is trunking the trunking
    gap applies against anything else, which is the whole point of it having
    its own figure rather than being swept up by the cable tray gap.
    """
    services = settings.number("gap_services")
    containment = settings.number("gap_containment")
    trunking = settings.number("gap_trunking")

    if settings.flag("trunking_gap_wins") and (
            class_a == "trunking" or class_b == "trunking"):
        return trunking, "trunking"

    a_containment = class_a in ("containment", "trunking")
    b_containment = class_b in ("containment", "trunking")

    if a_containment and b_containment:
        return containment, "cable tray"
    if a_containment or b_containment:
        mode = settings.text("mixed_gap")
        if mode == "services":
            return services, "service"
        if mode == "containment":
            return containment, "cable tray"
        if services >= containment:
            return services, "service"
        return containment, "cable tray"
    return services, "service"


def required_spacing_mm(half_a, half_b, class_a, class_b, settings):
    """Centre to centre = (w1 / 2) + (w2 / 2) + clear gap + insulation,
    rounded up to the nearest step.  Insulation is already inside the half
    extents.

    Service, cable tray and trunking are the same calculation with a
    different gap, so a mixed bank needs no special case.
    """
    gap, label = pair_gap_mm(class_a, class_b, settings)
    raw = half_a + half_b + gap
    return round_up(raw, settings.number("round_to")), gap, raw, label


# =============================================================================
# run collection
# =============================================================================

def _connectors(element):
    try:
        manager = None
        if hasattr(element, "ConnectorManager"):
            manager = element.ConnectorManager
        if manager is None and hasattr(element, "MEPModel"):
            model = element.MEPModel
            if model is not None:
                manager = model.ConnectorManager
        if manager is None:
            return []
        return [c for c in manager.Connectors]
    except Exception:
        return []


def collect_run(document, element, axis, limit):
    """Everything that has to travel with the picked element: the element
    itself, the fittings and accessories joined to it, and any inline segment
    running the same way.  The walk stops at anything that turns off the run,
    so a branch or a riser is never dragged sideways.
    """
    seed_direction = element_direction(element)
    found = {}
    found[eid_value(element.Id)] = element
    stack = [element]
    guard = 0

    while stack:
        guard += 1
        if guard > limit:
            return list(found.values()), True
        current = stack.pop()
        for connector in _connectors(current):
            try:
                if not connector.IsConnected:
                    continue
                for other in connector.AllRefs:
                    try:
                        owner = other.Owner
                    except Exception:
                        continue
                    if owner is None:
                        continue
                    key = eid_value(owner.Id)
                    if key in found or key == 0:
                        continue
                    try:
                        if owner.Category is None:
                            continue
                    except Exception:
                        continue
                    direction = element_direction(owner)
                    if direction is None:
                        # a fitting: it has no run direction, it belongs to
                        # whatever it joins, so it travels
                        found[key] = owner
                        stack.append(owner)
                        continue
                    if seed_direction is None:
                        continue
                    if abs(direction.DotProduct(seed_direction)) > 0.996:
                        found[key] = owner
                        stack.append(owner)
            except Exception:
                continue
    return list(found.values()), False


# =============================================================================
# dialog and warning suppression
# =============================================================================

class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == DB.FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


class DialogSuppressor(object):
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.handler = None

    def _on_dialog(self, sender, args):
        try:
            args.OverrideResult(1)
        except Exception:
            pass

    def __enter__(self):
        try:
            self.handler = self._on_dialog
            self.uiapp.DialogBoxShowing += self.handler
        except Exception:
            self.handler = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.handler is not None:
                self.uiapp.DialogBoxShowing -= self.handler
        except Exception:
            pass
        return False


# =============================================================================
# the routine
# =============================================================================

class Row(object):
    """One element in the spaced string, for the report."""

    def __init__(self, element, settings=None):
        self.element = element
        self.label = describe(element, settings)
        self.klass = "service"
        self.half = 0.0
        self.bottom = 0.0
        self.top = 0.0
        self.row = 0
        self.start = 0.0
        self.target = 0.0
        self.move = 0.0
        self.lift = 0.0
        self.gap = 0.0
        self.gap_label = ""
        self.raw = 0.0
        self.spacing = 0.0
        self.carried = 0


class Result(object):
    def __init__(self):
        self.rows = []
        self.skipped = []
        self.notes = []
        self.axis_label = ""
        self.row_count = 1
        self.moved = 0
        self.ok = False

    def needs_a_look(self):
        return bool(self.skipped) or bool(self.notes)


def _pick_anchor(group, settings, first_id):
    mode = settings.text("anchor")
    if mode == "first_selected":
        for index, row in enumerate(group):
            if eid_value(row.element.Id) == first_id:
                return index
        return 0
    if mode == "largest":
        index = 0
        widest = -1.0
        for position, row in enumerate(group):
            if row.half > widest:
                widest = row.half
                index = position
        return index
    return 0


def _lay_out(group, settings, first_id):
    """Set the target position of every element in one row, from the anchor
    outwards in both directions, so the anchor stays exactly where it is."""
    anchor_index = _pick_anchor(group, settings, first_id)
    group[anchor_index].target = group[anchor_index].start

    for index in range(anchor_index + 1, len(group)):
        previous = group[index - 1]
        current = group[index]
        spacing, gap, raw, label = required_spacing_mm(
            previous.half, current.half, previous.klass, current.klass,
            settings)
        current.target = previous.target + spacing
        current.spacing = spacing
        current.gap = gap
        current.raw = raw
        current.gap_label = label

    for index in range(anchor_index - 1, -1, -1):
        following = group[index + 1]
        current = group[index]
        spacing, gap, raw, label = required_spacing_mm(
            current.half, following.half, current.klass, following.klass,
            settings)
        current.target = following.target - spacing
        following.spacing = spacing
        following.gap = gap
        following.raw = raw
        following.gap_label = label

    for row in group:
        row.move = row.target - row.start


def _lay_out_rows(groups, settings):
    """Space the rows apart vertically, bottom row held.

    The gap between two rows is the widest gap any pair across them is
    entitled to, so a row carrying trunking clears the row beneath it by the
    trunking figure.
    """
    if len(groups) < 2:
        return

    ordered = sorted(groups, key=lambda group: min(r.bottom for r in group))
    lift = 0.0
    for index in range(1, len(ordered)):
        below = ordered[index - 1]
        above = ordered[index]

        gap = 0.0
        for lower in below:
            for upper in above:
                value, _ = pair_gap_mm(lower.klass, upper.klass, settings)
                if value > gap:
                    gap = value

        below_top = max(r.top + r.lift for r in below)
        above_bottom = min(r.bottom for r in above)
        wanted = round_up(below_top + gap, settings.number("round_to"))
        lift = wanted - above_bottom
        for row in above:
            row.lift = lift


def space_elements(uidoc, elements, settings):
    """Space the given elements centre to centre along the axis square to the
    run, one row at a time.  One transaction, so a failure rolls back clean.
    """
    document = uidoc.Document
    result = Result()

    usable = []
    for element in elements:
        if element is None:
            continue
        if location_point(element) is None:
            result.skipped.append(describe(element, settings) +
                                  " - no location to space from")
            continue
        usable.append(element)

    if len(usable) < 2:
        result.notes.append(
            "Two or more services are needed - {0} usable in the selection."
            .format(len(usable)))
        return result

    axis, axis_label = spacing_axis(usable, settings)
    result.axis_label = axis_label

    # anything well off the dominant direction would sit across the string
    # rather than in it, so it is reported and left out
    run = dominant_direction(usable)
    tolerance = math.cos(math.radians(
        max(0.0, settings.number("angle_tolerance_deg"))))
    kept = []
    for element in usable:
        direction = element_direction(element)
        if direction is None or run is None:
            kept.append(element)          # point-placed: taken as picked
            continue
        if abs(direction.DotProduct(run)) < tolerance:
            result.skipped.append(
                describe(element, settings) + " - more than " +
                fmt(settings.number("angle_tolerance_deg")) +
                " degrees off the run direction")
            continue
        kept.append(element)

    if len(kept) < 2:
        result.notes.append("Fewer than two services share a run direction.")
        return result

    rows = []
    for element in kept:
        row = Row(element, settings)
        row.klass = gap_class(element, settings)
        row.half = half_extent_mm(document, element, axis, settings)
        row.bottom, row.top = vertical_span_mm(document, element, settings)
        point = location_point(element)
        row.start = ft_to_mm(point.DotProduct(axis))
        if row.half <= 0.0:
            result.notes.append(
                describe(element, settings) + " - no width could be measured; "
                "spaced on its centreline only")
        rows.append(row)

    # --- rows: a bank at a different level is spaced on its own -----------
    groups = split_into_rows(rows, settings)
    result.row_count = len(groups)
    if len(groups) > 1:
        result.notes.append(
            "The selection sits at {0} levels more than {1}mm apart top edge "
            "to bottom edge; each was spaced as its own row.".format(
                len(groups), fmt(settings.number("row_clear_mm"))))

    first_id = eid_value(kept[0].Id)
    for group in groups:
        if settings.text("order") == "spatial":
            group.sort(key=lambda item: item.start)
        if len(group) < 2:
            group[0].target = group[0].start
            continue
        _lay_out(group, settings, first_id)

    if settings.flag("space_rows"):
        _lay_out_rows(groups, settings)

    ordered_rows = []
    for group in groups:
        ordered_rows.extend(group)

    # --- what travels with each element ------------------------------------
    move_run = settings.flag("move_run")
    limit = int(settings.number("max_run_elements"))
    claimed = {}
    plan = []
    for row in ordered_rows:
        if not move_run:
            plan.append((row, [row.element]))
            row.carried = 0
            continue
        members, hit_limit = collect_run(document, row.element, axis, limit)
        if hit_limit:
            result.notes.append(
                describe(row.element, settings) + " - run reaches more than " +
                str(limit) + " elements; only the element itself was moved")
            members = [row.element]
        clean = []
        for member in members:
            key = eid_value(member.Id)
            if key in claimed:
                if key != eid_value(row.element.Id):
                    continue
            claimed[key] = True
            clean.append(member)
        plan.append((row, clean))
        row.carried = max(0, len(clean) - 1)

    # --- move ---------------------------------------------------------------
    transaction = DB.Transaction(document, "RevoBIM Service Spacing")
    try:
        transaction.Start()
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)

        unpin = settings.flag("unpin")
        repin = []
        moved = 0

        for row, members in plan:
            if abs(row.move) < 1e-4 and abs(row.lift) < 1e-4:
                continue
            translation = axis.Multiply(mm_to_ft(row.move))
            if abs(row.lift) > 1e-4:
                translation = translation + XYZ(0, 0, mm_to_ft(row.lift))
            ids = []
            for member in members:
                try:
                    if member.Pinned:
                        if not unpin:
                            result.skipped.append(
                                describe(member, settings) + " - pinned")
                            continue
                        member.Pinned = False
                        repin.append(member)
                except Exception:
                    pass
                ids.append(member.Id)
            if not ids:
                continue
            try:
                collection = List_of_ids(ids)
                DB.ElementTransformUtils.MoveElements(
                    document, collection, translation)
                moved += 1
            except Exception as error:
                result.skipped.append(
                    row.label + " - Revit refused the move (" +
                    str(error).split("\n")[0] + ")")

        for member in repin:
            try:
                member.Pinned = True
            except Exception:
                pass

        transaction.Commit()
        result.moved = moved
        result.ok = True
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        result.notes.append("The run was rolled back: " + str(error))
        result.ok = False

    result.rows = ordered_rows
    return result


def List_of_ids(ids):
    """A .NET List[ElementId] for the transform call."""
    from System.Collections.Generic import List
    collection = List[ElementId]()
    for item in ids:
        collection.Add(item)
    return collection
