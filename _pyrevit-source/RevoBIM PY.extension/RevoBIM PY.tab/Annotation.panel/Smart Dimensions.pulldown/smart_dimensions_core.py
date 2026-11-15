# -*- coding: utf-8 -*-
"""RevoBIM Smart Dimensions - shared core.

Geometry, reference gathering, settings and the dimension routine used by both
buttons in the Smart Dimensions pulldown.

Written to run unchanged on Revit 2024 / 2025 / 2026 / 2027 and on both the
IronPython 2.7 and IronPython 3 engines pyRevit may select:
  - no f-strings, no print statements, ``.format()`` for interpolation
  - ``ElementId.Value`` preferred over the removed ``.IntegerValue``
  - no ``System.Uri`` anywhere (it moved assemblies in 2025)
  - anything not needed to do the work is imported on its own inside a
    try/except, so a name missing on one release cannot kill module load
"""

__version__ = "1.4.0"

import os
import math

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Dimension,
    DimensionType,
    Element,
    ElementId,
    FailureProcessingResult,
    FailureSeverity,
    FilteredElementCollector,
    GeometryInstance,
    IFailuresPreprocessor,
    Line,
    LocationCurve,
    LocationPoint,
    Options,
    PlanarFace,
    Reference,
    ReferenceArray,
    RevitLinkInstance,
    Solid,
    SubTransaction,
    Transaction,
    ViewDetailLevel,
    ViewType,
    XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

# --- optional names, each on its own so a missing one is simply skipped ------

UnitUtils = None
UnitTypeId = None
try:
    from Autodesk.Revit.DB import UnitUtils as _UnitUtils

    UnitUtils = _UnitUtils
except Exception:
    pass
try:
    from Autodesk.Revit.DB import UnitTypeId as _UnitTypeId

    UnitTypeId = _UnitTypeId
except Exception:
    pass

DimensionStyleType = None
try:
    from Autodesk.Revit.DB import DimensionStyleType as _DimensionStyleType

    DimensionStyleType = _DimensionStyleType
except Exception:
    pass

FamilyInstanceReferenceType = None
try:
    from Autodesk.Revit.DB import (
        FamilyInstanceReferenceType as _FamilyInstanceReferenceType,
    )

    FamilyInstanceReferenceType = _FamilyInstanceReferenceType
except Exception:
    pass

OperationCanceledException = Exception
try:
    from Autodesk.Revit.Exceptions import (
        OperationCanceledException as _OperationCanceledException,
    )

    OperationCanceledException = _OperationCanceledException
except Exception:
    pass


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

MM_PER_FT = 304.8

# straight-line tolerances
PARALLEL_TOL = 0.9962          # ~5 degrees, for "is this element on the run"
FACE_NORMAL_TOL = 0.999        # ~2.5 degrees, for "is this face a side face"
TINY = 1.0e-9


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026 - go through here."""
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


def mm_to_ft(value):
    if UnitUtils is not None and UnitTypeId is not None:
        try:
            return UnitUtils.ConvertToInternalUnits(float(value), UnitTypeId.Millimeters)
        except Exception:
            pass
    return float(value) / MM_PER_FT


def ft_to_mm(value):
    if UnitUtils is not None and UnitTypeId is not None:
        try:
            return UnitUtils.ConvertFromInternalUnits(float(value), UnitTypeId.Millimeters)
        except Exception:
            pass
    return float(value) * MM_PER_FT


def bic_value(bic):
    """Integer id of a BuiltInCategory, without touching .IntegerValue."""
    try:
        return eid_value(ElementId(bic))
    except Exception:
        pass
    try:
        return int(bic)
    except Exception:
        return 0


_CAT_PIPE = bic_value(BuiltInCategory.OST_PipeCurves)
_CAT_DUCT = bic_value(BuiltInCategory.OST_DuctCurves)
_CAT_TRAY = bic_value(BuiltInCategory.OST_CableTray)
_CAT_CONDUIT = bic_value(BuiltInCategory.OST_Conduit)
_CAT_GENERIC = bic_value(BuiltInCategory.OST_GenericModel)
_CAT_WALL = bic_value(BuiltInCategory.OST_Walls)
_CAT_COLUMN = bic_value(BuiltInCategory.OST_Columns)
_CAT_STRUCT_COLUMN = bic_value(BuiltInCategory.OST_StructuralColumns)

_SERVICE_CATS = (_CAT_PIPE, _CAT_DUCT, _CAT_TRAY, _CAT_CONDUIT, _CAT_GENERIC)
_LINK_CATS = (_CAT_WALL, _CAT_COLUMN, _CAT_STRUCT_COLUMN)

PLAN_VIEW_TYPES = []
for _name in ("FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan"):
    try:
        PLAN_VIEW_TYPES.append(getattr(ViewType, _name))
    except Exception:
        pass


def category_id_of(element):
    try:
        cat = element.Category
        if cat is None:
            return 0
        return eid_value(cat.Id)
    except Exception:
        return 0


def element_label(element, doc=None):
    """A short human label - category, type name, id."""
    bits = []
    try:
        if element.Category is not None:
            bits.append(element.Category.Name)
    except Exception:
        pass
    try:
        name = Element.Name.GetValue(element)
        if name:
            bits.append(name)
    except Exception:
        try:
            if element.Name:
                bits.append(element.Name)
        except Exception:
            pass
    bits.append("id {0}".format(eid_value(element.Id)))
    return " - ".join([b for b in bits if b])


# ---------------------------------------------------------------------------
# settings - plain key=value text, no JSON dependency
# ---------------------------------------------------------------------------

SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "RevoBIM")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "smart_dimensions.txt")

DEFAULTS = {
    # per category: "centre" (centreline) or "edges" (both outer faces)
    "pipe_mode": "centre",
    "conduit_mode": "centre",
    "round_duct_mode": "centre",
    "rect_duct_mode": "edges",
    "tray_mode": "edges",
    # generic models: auto handles them like ducts - flat sides get edges,
    # anything curved falls to the family's centre plane
    "generic_mode": "auto",        # auto | centre | edges
    # linked walls and columns
    "link_step": "on",             # on | off
    "link_multi": "off",           # off = one click, no Finish; on = multi-pick
    "link_ref": "closest_face",    # closest_face | centre
    # dimension
    "dim_type": "",                # empty = the view's current type
    "line_margin_mm": "150",
    "min_gap_mm": "1.0",
    "repeat": "off",               # off | on  (keep running after each string)
    # small dimensions - text leadered out of the string
    "pull_out": "on",                          # on | off
    "pull_threshold_table": "50=200; 100=250",  # view scale = mm
    "pull_threshold_base": "150",               # any other scale: base + scale
    "pull_layout": "stacked",                  # stacked | row
    "pull_side": "start",                      # start | end of the string
    "pull_datum": "mep_edge",                  # mep_edge | dim_line
    # model millimetres, not paper - these are set out from the services
    "pull_offset_mm": "200",                   # to the first displaced value
    "pull_gap_mm": "50",                       # between each one after that
    "pull_clear_mm": "50",                     # clear of other leadered text
    "settings_version": "3",
    # reporting
    "results": "issues",           # never | issues | always
}

MODE_KEYS = (
    "pipe_mode",
    "conduit_mode",
    "round_duct_mode",
    "rect_duct_mode",
    "tray_mode",
)

# Keys whose default changed, by the settings version that changed it. A file
# written by an older version has these put back to the new default rather than
# quietly keeping a number that no longer means what it used to.
SETTINGS_VERSION = "3"
MIGRATIONS = {
    # v1.3.0 stacked the numbers instead of spreading them along the string, so
    # the gap stopped being "room for a number beside another" and became
    # "line spacing" - 9 paper mm was 450mm at 1:50, far too airy for a stack
    "2": ("pull_gap_mm",),
    # v1.4.0 set the stack out from the services in model millimetres rather
    # than from the dimension line in paper millimetres - the same three keys
    # now mean something completely different and a saved number from before
    # would be read as, say, 6mm rather than 200mm
    "3": ("pull_offset_mm", "pull_gap_mm", "pull_clear_mm"),
}


def load_settings():
    """Read the settings file, falling back key by key to the defaults.

    A missing or damaged file, or keys left over from an older version, must
    never stop the tool running.
    """
    values = {}
    for key in DEFAULTS:
        values[key] = DEFAULTS[key]
    try:
        if os.path.isfile(SETTINGS_PATH):
            handle = open(SETTINGS_PATH, "r")
            try:
                for raw in handle.readlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip()
                    if key in DEFAULTS:
                        values[key] = val
            finally:
                handle.close()
    except Exception:
        pass
    # sanity-check the enumerated ones
    for key in MODE_KEYS:
        if values.get(key) not in ("centre", "edges"):
            values[key] = DEFAULTS[key]
    if values.get("generic_mode") not in ("auto", "centre", "edges"):
        values["generic_mode"] = DEFAULTS["generic_mode"]
    if values.get("link_step") not in ("on", "off"):
        values["link_step"] = DEFAULTS["link_step"]
    if values.get("link_multi") not in ("on", "off"):
        values["link_multi"] = DEFAULTS["link_multi"]
    if values.get("link_ref") not in ("closest_face", "centre"):
        values["link_ref"] = DEFAULTS["link_ref"]
    if values.get("repeat") not in ("on", "off"):
        values["repeat"] = DEFAULTS["repeat"]
    if values.get("pull_out") not in ("on", "off"):
        values["pull_out"] = DEFAULTS["pull_out"]
    if values.get("pull_side") not in ("start", "end"):
        values["pull_side"] = DEFAULTS["pull_side"]
    if values.get("pull_layout") not in ("stacked", "row"):
        values["pull_layout"] = DEFAULTS["pull_layout"]
    if values.get("pull_datum") not in ("mep_edge", "dim_line"):
        values["pull_datum"] = DEFAULTS["pull_datum"]
    if values.get("results") not in ("never", "issues", "always"):
        values["results"] = DEFAULTS["results"]
    for key in (
        "line_margin_mm",
        "min_gap_mm",
        "pull_threshold_base",
        "pull_offset_mm",
        "pull_gap_mm",
        "pull_clear_mm",
    ):
        try:
            float(values.get(key))
        except Exception:
            values[key] = DEFAULTS[key]

    # a file from an older version has the keys whose meaning changed put back
    if values.get("settings_version") != SETTINGS_VERSION:
        for version in MIGRATIONS:
            for key in MIGRATIONS[version]:
                values[key] = DEFAULTS[key]
        values["settings_version"] = SETTINGS_VERSION
    return values


def save_settings(values):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(SETTINGS_PATH, "w")
        try:
            handle.write("# RevoBIM Smart Dimensions settings\n")
            keys = list(DEFAULTS.keys())
            keys.sort()
            for key in keys:
                handle.write("{0}={1}\n".format(key, values.get(key, DEFAULTS[key])))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def setting_float(values, key):
    try:
        return float(values.get(key, DEFAULTS[key]))
    except Exception:
        return float(DEFAULTS[key])


def parse_threshold_table(text):
    """'50=200; 100=250' -> {50: 200.0, 100: 250.0}.

    Accepts '1:50' as well as '50', and either ';' or ',' between entries. A
    malformed entry is dropped rather than taking the whole table with it.
    """
    table = {}
    if not text:
        return table
    try:
        chunks = str(text).replace(",", ";").split(";")
    except Exception:
        return table
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        left, _, right = chunk.partition("=")
        left = left.strip()
        if ":" in left:
            left = left.split(":")[-1]
        try:
            table[int(float(left))] = float(right.strip())
        except Exception:
            continue
    return table


def pull_threshold_mm(settings, view_scale):
    """Below this, in model mm, a dimension's text gets leadered out.

    The table wins where it names the view's scale; anything else falls to
    ``base + the scale``, which reproduces the table's own numbers (150 + 50 =
    200 at 1:50, 150 + 100 = 250 at 1:100) rather than inventing a rule.
    """
    try:
        scale = int(view_scale)
    except Exception:
        scale = 100
    table = parse_threshold_table(settings.get("pull_threshold_table", ""))
    if scale in table:
        return table[scale]
    return setting_float(settings, "pull_threshold_base") + float(scale)


def paper_mm_to_ft(paper_mm, view_scale):
    """Paper millimetres at the view's scale, in internal units."""
    try:
        scale = float(view_scale)
    except Exception:
        scale = 100.0
    if scale <= 0:
        scale = 100.0
    return mm_to_ft(float(paper_mm) * scale)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


class Report(object):
    def __init__(self):
        self.placed = 0
        self.references = 0
        self.services = 0
        self.links = 0
        self.pulled = 0
        self.issues = []
        self.notes = []
        self.error = None
        self.cancelled = False

    def issue(self, text):
        if text not in self.issues:
            self.issues.append(text)

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    @property
    def needs_a_look(self):
        return bool(self.error) or bool(self.issues)


# ---------------------------------------------------------------------------
# dialog and warning suppression
# ---------------------------------------------------------------------------


class WarningSwallower(IFailuresPreprocessor):
    """Deletes every warning raised inside the transaction."""

    def PreprocessFailures(self, failures_accessor):
        try:
            for failure in failures_accessor.GetFailureMessages():
                try:
                    if failure.GetSeverity() == FailureSeverity.Warning:
                        failures_accessor.DeleteWarning(failure)
                except Exception:
                    pass
        except Exception:
            pass
        return FailureProcessingResult.Continue


def quiet_transaction(doc, name):
    """A transaction that will not stop to show a warning dialog."""
    trans = Transaction(doc, name)
    try:
        options = trans.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        try:
            options.SetForcedModalHandling(False)
        except Exception:
            pass
        trans.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return trans


class DialogMuffler(object):
    """Auto-dismisses any Revit dialog raised while the routine runs.

    Used as a context-managed pair of enable()/disable() calls rather than a
    ``with`` block, so a failure to hook the event can never take the tool
    down.
    """

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.handler = None

    def _on_dialog(self, sender, args):
        try:
            args.OverrideResult(1)  # IDOK / TaskDialogResult.Ok
        except Exception:
            pass

    def enable(self):
        try:
            from System import EventHandler
            from Autodesk.Revit.UI.Events import DialogBoxShowingEventArgs

            self.handler = EventHandler[DialogBoxShowingEventArgs](self._on_dialog)
            self.uiapp.DialogBoxShowing += self.handler
        except Exception:
            self.handler = None

    def disable(self):
        if self.handler is None:
            return
        try:
            self.uiapp.DialogBoxShowing -= self.handler
        except Exception:
            pass
        self.handler = None


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def curve_direction(element):
    """Unit vector along the element's location curve, in plan. None if there
    is no curve, or it is vertical."""
    try:
        loc = element.Location
    except Exception:
        return None
    if not isinstance(loc, LocationCurve):
        return None
    try:
        curve = loc.Curve
        vec = curve.GetEndPoint(1) - curve.GetEndPoint(0)
    except Exception:
        return None
    flat = XYZ(vec.X, vec.Y, 0.0)
    try:
        if flat.GetLength() < TINY:
            return None
        return flat.Normalize()
    except Exception:
        return None


def plan_direction(element):
    """As ``curve_direction``, then the family's own left-right axis.

    Generic models are usually placed as a point, not a run, so there is no
    location curve to read. The instance transform's X axis is the family's
    left-right direction and is the best available stand-in.
    """
    direction = curve_direction(element)
    if direction is not None:
        return direction
    try:
        transform = element.GetTransform()
        vec = transform.BasisX
        flat = XYZ(vec.X, vec.Y, 0.0)
        if flat.GetLength() >= TINY:
            return flat.Normalize()
    except Exception:
        pass
    return None


def element_midpoint(element):
    try:
        loc = element.Location
    except Exception:
        return None
    if isinstance(loc, LocationCurve):
        try:
            curve = loc.Curve
            return (curve.GetEndPoint(0) + curve.GetEndPoint(1)) / 2.0
        except Exception:
            return None
    if isinstance(loc, LocationPoint):
        try:
            return loc.Point
        except Exception:
            return None
    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            return (box.Min + box.Max) / 2.0
    except Exception:
        pass
    return None


def dominant_direction(elements):
    """The direction most of the selected elements run in.

    Elements with a real location curve decide it on their own; a selection of
    nothing but point-placed families falls back to their instance axes.
    """
    pairs = []
    for element in elements:
        direction = curve_direction(element)
        if direction is not None:
            pairs.append(direction)
    if not pairs:
        for element in elements:
            direction = plan_direction(element)
            if direction is not None:
                pairs.append(direction)
    if not pairs:
        return None
    best = None
    best_count = -1
    for candidate in pairs:
        count = 0
        for other in pairs:
            try:
                if abs(candidate.DotProduct(other)) >= PARALLEL_TOL:
                    count += 1
            except Exception:
                pass
        if count > best_count:
            best_count = count
            best = candidate
    return best


def dimension_axis(run_direction):
    """The direction the dimension string runs in: across the services."""
    try:
        axis = XYZ.BasisZ.CrossProduct(run_direction)
        if axis.GetLength() < TINY:
            return None
        axis = axis.Normalize()
    except Exception:
        return None
    # keep the sign consistent so strings always read the same way round
    if axis.X < -TINY or (abs(axis.X) <= TINY and axis.Y < 0.0):
        try:
            axis = axis.Negate()
        except Exception:
            axis = XYZ(-axis.X, -axis.Y, -axis.Z)
    return axis


def geometry_options(view, include_hidden):
    """View-bound options where possible - references must match the view."""
    options = Options()
    options.ComputeReferences = True
    if view is not None:
        try:
            options.View = view
        except Exception:
            try:
                options.DetailLevel = ViewDetailLevel.Fine
            except Exception:
                pass
    else:
        try:
            options.DetailLevel = ViewDetailLevel.Fine
        except Exception:
            pass
    if include_hidden:
        try:
            options.IncludeNonVisibleObjects = True
        except Exception:
            pass
    return options


def walk_geometry(geometry):
    """Flatten a GeometryElement, stepping into instances."""
    results = []
    if geometry is None:
        return results
    try:
        items = list(geometry)
    except Exception:
        return results
    for item in items:
        if isinstance(item, GeometryInstance):
            inner = None
            try:
                inner = item.GetInstanceGeometry()
            except Exception:
                inner = None
            if inner is not None:
                results.extend(walk_geometry(inner))
        else:
            results.append(item)
    return results


def centreline_reference(element, view):
    """The element's own centreline, as a reference a dimension will take."""
    axis = plan_direction(element)
    for use_view in (True, False):
        geometry = None
        try:
            geometry = element.get_Geometry(geometry_options(view if use_view else None, True))
        except Exception:
            geometry = None
        best = None
        best_length = 0.0
        for item in walk_geometry(geometry):
            if not isinstance(item, Line):
                continue
            reference = None
            try:
                reference = item.Reference
            except Exception:
                reference = None
            if reference is None:
                continue
            try:
                direction = item.Direction
            except Exception:
                continue
            flat = XYZ(direction.X, direction.Y, 0.0)
            try:
                if flat.GetLength() < TINY:
                    continue
                flat = flat.Normalize()
            except Exception:
                continue
            if axis is not None and abs(flat.DotProduct(axis)) < 0.99:
                continue
            try:
                length = item.Length
            except Exception:
                length = 0.0
            if length > best_length:
                best_length = length
                best = reference
        if best is not None:
            return best
    # last resort - some releases hand back a usable reference off the location
    try:
        loc = element.Location
        if isinstance(loc, LocationCurve):
            reference = loc.Curve.Reference
            if reference is not None:
                return reference
    except Exception:
        pass
    return None


def side_face_references(element, axis, view, transform=None):
    """The two outer faces square-on to the dimension axis, low side first.

    Returns a list of ``(t, reference)`` or None. ``t`` is the position of the
    face along the dimension axis, so callers can order the string.
    """
    found = []
    for use_view in (True, False):
        geometry = None
        try:
            geometry = element.get_Geometry(geometry_options(view if use_view else None, False))
        except Exception:
            geometry = None
        for item in walk_geometry(geometry):
            if not isinstance(item, Solid):
                continue
            try:
                if item.Faces.Size == 0:
                    continue
            except Exception:
                continue
            for face in item.Faces:
                if not isinstance(face, PlanarFace):
                    continue
                try:
                    normal = face.FaceNormal
                    origin = face.Origin
                except Exception:
                    continue
                if transform is not None:
                    try:
                        normal = transform.OfVector(normal)
                        origin = transform.OfPoint(origin)
                    except Exception:
                        continue
                try:
                    if abs(normal.DotProduct(axis)) < FACE_NORMAL_TOL:
                        continue
                except Exception:
                    continue
                reference = None
                try:
                    reference = face.Reference
                except Exception:
                    reference = None
                if reference is None:
                    continue
                try:
                    found.append((origin.DotProduct(axis), reference))
                except Exception:
                    continue
        if found:
            break
    if len(found) < 2:
        return None
    found.sort(key=lambda pair: pair[0])
    low = found[0]
    high = found[-1]
    if abs(high[0] - low[0]) < TINY:
        return None
    return [low, high]


# ---------------------------------------------------------------------------
# category and shape
# ---------------------------------------------------------------------------


def duct_is_round(element):
    """Round and oval ducts get the centreline; rectangular ones get edges."""
    try:
        manager = element.ConnectorManager
        if manager is not None:
            for connector in manager.Connectors:
                try:
                    shape = str(connector.Shape)
                except Exception:
                    continue
                if shape in ("Round", "Oval"):
                    return True
                if shape == "Rectangular":
                    return False
    except Exception:
        pass
    try:
        param = element.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
        if param is not None and param.HasValue and param.AsDouble() > TINY:
            return True
    except Exception:
        pass
    return False


def service_kind(element):
    """One of pipe / conduit / tray / duct_round / duct_rect, or None."""
    if element is None:
        return None
    cat = category_id_of(element)
    if cat == _CAT_PIPE:
        return "pipe"
    if cat == _CAT_CONDUIT:
        return "conduit"
    if cat == _CAT_TRAY:
        return "tray"
    if cat == _CAT_DUCT:
        return "duct_round" if duct_is_round(element) else "duct_rect"
    if cat == _CAT_GENERIC:
        return "generic"
    return None


KIND_SETTING = {
    "pipe": "pipe_mode",
    "conduit": "conduit_mode",
    "tray": "tray_mode",
    "duct_round": "round_duct_mode",
    "duct_rect": "rect_duct_mode",
    "generic": "generic_mode",
}

KIND_LABEL = {
    "pipe": "pipe",
    "conduit": "conduit",
    "tray": "cable tray",
    "duct_round": "round duct",
    "duct_rect": "rectangular duct",
    "generic": "generic model",
}


def family_centre_reference(element, axis):
    """A generic model's own centre reference plane, square-on to the string.

    A generic model has no MEP centreline to point at, so the family's built-in
    centre planes stand in for one. ``Center (Left/Right)`` has its normal
    along the instance's X axis and ``Center (Front/Back)`` along its Y, so the
    instance transform decides which of the two the dimension can see.
    """
    if FamilyInstanceReferenceType is None:
        return None
    order = ["CenterLeftRight", "CenterFrontBack"]
    try:
        transform = element.GetTransform()
        if abs(transform.BasisY.DotProduct(axis)) > abs(transform.BasisX.DotProduct(axis)):
            order = ["CenterFrontBack", "CenterLeftRight"]
    except Exception:
        pass
    for name in order:
        kind = getattr(FamilyInstanceReferenceType, name, None)
        if kind is None:
            continue
        try:
            references = element.GetReferences(kind)
        except Exception:
            continue
        try:
            for reference in references:
                if reference is not None:
                    return reference
        except Exception:
            continue
    return None


def is_wall_or_column(element):
    return category_id_of(element) in _LINK_CATS


# ---------------------------------------------------------------------------
# selection filters
# ---------------------------------------------------------------------------


class ServiceFilter(ISelectionFilter):
    """Pipes, ducts, cable trays and conduits only."""

    def AllowElement(self, element):
        try:
            return service_kind(element) is not None
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


class LinkedWallColumnFilter(ISelectionFilter):
    """Walls and columns inside linked models."""

    def __init__(self, doc):
        self.doc = doc

    def AllowElement(self, element):
        try:
            if isinstance(element, RevitLinkInstance):
                return True
            return is_wall_or_column(element)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        try:
            link = self.doc.GetElement(reference.ElementId)
            if not isinstance(link, RevitLinkInstance):
                return False
            link_doc = link.GetLinkDocument()
            if link_doc is None:
                return False
            linked = link_doc.GetElement(reference.LinkedElementId)
            return is_wall_or_column(linked)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# linked references
# ---------------------------------------------------------------------------


def to_host_reference(reference, link, doc):
    """Turn a reference made in a link document into one the host can use."""
    try:
        made = reference.CreateLinkReference(link)
        if made is not None:
            return made
    except Exception:
        pass
    # the pre-2018 route, still valid: <linkInstanceId>:0:RVTLINK:<stableRef>
    try:
        link_doc = link.GetLinkDocument()
        stable = reference.ConvertToStableRepresentation(link_doc)
        host_stable = "{0}:0:RVTLINK:{1}".format(eid_value(link.Id), stable)
        return Reference.ParseFromStableRepresentation(doc, host_stable)
    except Exception:
        return None


def linked_element_reference(doc, link, linked_element, axis, target_t, mode):
    """Reference on a linked wall or column, and where it sits on the axis.

    ``mode`` "closest_face" picks the planar face square-on to the dimension
    axis that sits nearest ``target_t`` - the surface facing the service that
    is next to it. "centre" falls back to the element's own centreline.
    """
    transform = None
    try:
        transform = link.GetTotalTransform()
    except Exception:
        transform = None

    if mode == "closest_face":
        candidates = []
        geometry = None
        try:
            geometry = linked_element.get_Geometry(geometry_options(None, False))
        except Exception:
            geometry = None
        for item in walk_geometry(geometry):
            if not isinstance(item, Solid):
                continue
            try:
                if item.Faces.Size == 0:
                    continue
            except Exception:
                continue
            for face in item.Faces:
                if not isinstance(face, PlanarFace):
                    continue
                try:
                    normal = face.FaceNormal
                    origin = face.Origin
                except Exception:
                    continue
                if transform is not None:
                    try:
                        normal = transform.OfVector(normal)
                        origin = transform.OfPoint(origin)
                    except Exception:
                        continue
                try:
                    if abs(normal.DotProduct(axis)) < FACE_NORMAL_TOL:
                        continue
                    position = origin.DotProduct(axis)
                except Exception:
                    continue
                reference = None
                try:
                    reference = face.Reference
                except Exception:
                    reference = None
                if reference is None:
                    continue
                candidates.append((abs(position - target_t), position, reference))
        if candidates:
            candidates.sort(key=lambda triple: triple[0])
            _, position, reference = candidates[0]
            host_reference = to_host_reference(reference, link, doc)
            if host_reference is not None:
                return (position, host_reference)

    # centreline fallback (also the "centre" mode)
    reference = centreline_reference(linked_element, None)
    if reference is not None:
        host_reference = to_host_reference(reference, link, doc)
        if host_reference is not None:
            point = element_midpoint(linked_element)
            if point is not None and transform is not None:
                try:
                    point = transform.OfPoint(point)
                except Exception:
                    pass
            position = target_t
            if point is not None:
                try:
                    position = point.DotProduct(axis)
                except Exception:
                    position = target_t
            return (position, host_reference)
    return None


def linked_element_anchor(link, linked_element, axis):
    """Where a linked wall or column sits along the dimension axis."""
    point = element_midpoint(linked_element)
    if point is None:
        return None
    try:
        transform = link.GetTotalTransform()
        if transform is not None:
            point = transform.OfPoint(point)
    except Exception:
        pass
    try:
        return point.DotProduct(axis)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# dimension types
# ---------------------------------------------------------------------------


def linear_dimension_type_names(doc):
    names = []
    try:
        collector = FilteredElementCollector(doc).OfClass(DimensionType)
        for dim_type in collector:
            try:
                if DimensionStyleType is not None:
                    style = dim_type.StyleType
                    if str(style) not in ("Linear", "LinearFixed"):
                        continue
            except Exception:
                pass
            try:
                name = Element.Name.GetValue(dim_type)
            except Exception:
                try:
                    name = dim_type.Name
                except Exception:
                    name = None
            if name and name not in names:
                names.append(name)
    except Exception:
        pass
    names.sort()
    return names


def find_dimension_type(doc, name):
    if not name:
        return None
    try:
        collector = FilteredElementCollector(doc).OfClass(DimensionType)
        for dim_type in collector:
            try:
                current = Element.Name.GetValue(dim_type)
            except Exception:
                try:
                    current = dim_type.Name
                except Exception:
                    current = None
            if current == name:
                return dim_type
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# the routine
# ---------------------------------------------------------------------------


def collect_service_entries(doc, view, elements, axis, run_direction, settings, report):
    """Build the (t, reference, label) list for the selected services.

    Returns ``(entries, fallback)``. ``fallback`` is the same selection taken
    to centrelines only - kept ready in case Revit refuses the edge
    references, so the string can still be placed rather than lost.
    """
    entries = []
    fallback = []

    def add_centreline(element, into, kind):
        reference = None
        if kind == "generic":
            reference = family_centre_reference(element, axis)
        if reference is None:
            reference = centreline_reference(element, view)
        if reference is None:
            return False
        point = element_midpoint(element)
        position = 0.0
        if point is not None:
            try:
                position = point.DotProduct(axis)
            except Exception:
                position = 0.0
        into.append((position, reference, element_label(element) + " (centreline)"))
        return True

    for element in elements:
        kind = service_kind(element)
        if kind is None:
            continue

        # a generic model is usually placed as a point rather than run, so
        # there is no direction to test it against - it is taken as picked
        if kind != "generic":
            direction = curve_direction(element)
            if direction is None:
                report.issue(
                    "{0}: no straight run to work from - skipped".format(element_label(element))
                )
                continue
            try:
                if abs(direction.DotProduct(run_direction)) < PARALLEL_TOL:
                    report.issue(
                        "{0}: not parallel to the rest of the selection - skipped".format(
                            element_label(element)
                        )
                    )
                    continue
            except Exception:
                continue

        mode = settings.get(KIND_SETTING.get(kind, "pipe_mode"), "centre")
        if kind == "generic" and mode == "auto":
            # like ducts: flat sides get both edges, anything curved has none
            # to find and drops through to the centre plane below
            mode = "edges"
        placed = False

        if mode == "edges":
            pair = side_face_references(element, axis, view)
            if pair:
                entries.append((pair[0][0], pair[0][1], element_label(element) + " (edge 1)"))
                entries.append((pair[1][0], pair[1][1], element_label(element) + " (edge 2)"))
                placed = True
            elif not (kind == "generic" and settings.get("generic_mode") == "auto"):
                report.note(
                    "{0}: no side faces available - dimensioned to its centreline instead "
                    "(raise the view detail level to Medium or Fine for edges)".format(
                        element_label(element)
                    )
                )

        # the centreline is always worked out: it is either the answer, or the
        # standby for a refused edge reference
        got_centreline = add_centreline(element, fallback, kind)

        if not placed:
            if not got_centreline:
                report.issue(
                    "{0}: Revit would not give up a reference for it - skipped".format(
                        element_label(element)
                    )
                )
                continue
            entries.append(fallback[-1])

        report.services += 1
    return entries, fallback


def collect_link_entries(doc, link_references, axis, service_positions, settings, report):
    entries = []
    mode = settings.get("link_ref", "closest_face")
    for reference in link_references:
        link = None
        linked = None
        try:
            link = doc.GetElement(reference.ElementId)
            link_doc = link.GetLinkDocument()
            linked = link_doc.GetElement(reference.LinkedElementId)
        except Exception:
            linked = None
        if link is None or linked is None:
            report.issue("A linked element could not be read back - skipped")
            continue

        anchor = linked_element_anchor(link, linked, axis)
        target = anchor if anchor is not None else 0.0
        if service_positions:
            if anchor is None:
                target = service_positions[0]
            else:
                nearest = None
                for position in service_positions:
                    gap = abs(position - anchor)
                    if nearest is None or gap < nearest[0]:
                        nearest = (gap, position)
                if nearest is not None:
                    target = nearest[1]

        made = linked_element_reference(doc, link, linked, axis, target, mode)
        if made is None:
            report.issue(
                "{0} (linked): no face square-on to the dimension - skipped".format(
                    element_label(linked)
                )
            )
            continue
        position, host_reference = made
        entries.append((position, host_reference, element_label(linked) + " (linked, nearest face)"))
        report.links += 1
    return entries


def dedupe_and_sort(entries, min_gap_ft):
    entries = sorted(entries, key=lambda triple: triple[0])
    kept = []
    for entry in entries:
        if kept and abs(entry[0] - kept[-1][0]) < min_gap_ft:
            continue
        kept.append(entry)
    return kept


def build_dimension_line(entries, picked_point, axis, margin_ft, z_value):
    """The dimension line: through the click, spanning the references.

    The click sets the line's offset from the services and nothing else. Along
    its own direction the line is built from the outermost references with the
    same overrun each end, so it stays centred on what it is dimensioning and
    does not drift when text is later leadered off one end.
    """
    positions = [entry[0] for entry in entries]
    low = min(positions) - margin_ft
    high = max(positions) + margin_ft
    try:
        base = picked_point.DotProduct(axis)
    except Exception:
        base = 0.0
    start = picked_point + axis * (low - base)
    end = picked_point + axis * (high - base)
    start = XYZ(start.X, start.Y, z_value)
    end = XYZ(end.X, end.Y, z_value)
    if start.DistanceTo(end) < TINY:
        return None
    return Line.CreateBound(start, end)


def create_dimension(doc, view, attempts, picked_point, axis, settings, report):
    """Place the string.

    ``attempts`` is the preferred entry list followed by any standbys - the
    same selection taken to centrelines only. Each is tried at the picked
    point's own plane first, then at the view's, then at zero, because which
    of the three ``NewDimension`` will accept varies with the view.
    """
    margin_ft = mm_to_ft(setting_float(settings, "line_margin_mm"))
    dim_type = find_dimension_type(doc, settings.get("dim_type", ""))
    if settings.get("dim_type") and dim_type is None:
        report.note(
            "Dimension type '{0}' is not in this project - the view's own type was used".format(
                settings.get("dim_type")
            )
        )

    z_candidates = []
    for value in (picked_point.Z, getattr(view, "Origin", None), 0.0):
        if value is None:
            continue
        if isinstance(value, XYZ):
            value = value.Z
        try:
            value = float(value)
        except Exception:
            continue
        if value not in z_candidates:
            z_candidates.append(value)

    attempts = [attempt for attempt in attempts if attempt and len(attempt) >= 2]
    if not attempts:
        report.error = "A dimension needs two references and only one came back."
        return (None, None)

    last_error = None
    for index, attempt in enumerate(attempts):
        for z_value in z_candidates:
            line = build_dimension_line(attempt, picked_point, axis, margin_ft, z_value)
            if line is None:
                continue
            array = ReferenceArray()
            for entry in attempt:
                array.Append(entry[1])
            sub = SubTransaction(doc)
            try:
                sub.Start()
                if dim_type is not None:
                    dimension = doc.Create.NewDimension(view, line, array, dim_type)
                else:
                    dimension = doc.Create.NewDimension(view, line, array)
                if dimension is None:
                    raise Exception("Revit returned no dimension")
                sub.Commit()
                report.placed += 1
                report.references = len(attempt)
                if index > 0:
                    report.issue(
                        "Revit would not take the edge references, so the string was placed "
                        "to centrelines only"
                    )
                return (dimension, attempt)
            except Exception as err:
                last_error = err
                try:
                    sub.RollBack()
                except Exception:
                    pass
    if last_error is not None:
        report.error = "Revit refused the dimension: {0}".format(last_error)
    else:
        report.error = "Revit refused the dimension"
    return (None, None)


# ---------------------------------------------------------------------------
# small dimensions - text leadered out of the string
# ---------------------------------------------------------------------------


def segment_records(dimension):
    """Every segment of a dimension, or the dimension itself if it has none.

    ``Dimension`` and ``DimensionSegment`` both carry ``Value``,
    ``TextPosition`` and ``IsTextPositionAdjustable()``, so one code path
    covers a two-reference dimension and a multi-segment string alike.
    """
    records = []
    segments = None
    try:
        segments = dimension.Segments
    except Exception:
        segments = None
    count = 0
    try:
        count = segments.Size
    except Exception:
        count = 0
    if count:
        try:
            for segment in segments:
                records.append(segment)
            return records
        except Exception:
            records = []
    return [dimension]


def segment_value_ft(segment):
    try:
        value = segment.Value
    except Exception:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def existing_leadered_text(doc, view):
    """Where leadered dimension text already sits in this view."""
    points = []
    try:
        collector = (
            FilteredElementCollector(doc, view.Id)
            .OfClass(Dimension)
            .WhereElementIsNotElementType()
        )
        for dimension in collector:
            leadered = False
            try:
                leadered = bool(dimension.HasLeader)
            except Exception:
                leadered = False
            if not leadered:
                continue
            for segment in segment_records(dimension):
                try:
                    point = segment.TextPosition
                except Exception:
                    point = None
                if point is not None:
                    points.append(point)
    except Exception:
        pass
    return points


def extent_points(element, view):
    """Points that between them reach every extreme of the element.

    Solid edge endpoints where the solids are there: the extreme along any
    horizontal direction sits on a flat end face, and every point of every
    edge of that face is captured, so this is exact for a pipe, tray, duct or
    box. Where there is no solid - a Coarse view, a line-only symbol - the
    location curve ends and the bounding box corners stand in. The box can
    only over-state the extent, which pushes the text further clear rather
    than closer, so the failure direction is the safe one.
    """
    points = []
    for use_view in (True, False):
        geometry = None
        try:
            geometry = element.get_Geometry(geometry_options(view if use_view else None, False))
        except Exception:
            geometry = None
        for item in walk_geometry(geometry):
            if not isinstance(item, Solid):
                continue
            try:
                edges = item.Edges
            except Exception:
                continue
            try:
                for edge in edges:
                    curve = edge.AsCurve()
                    if curve is None:
                        continue
                    points.append(curve.GetEndPoint(0))
                    points.append(curve.GetEndPoint(1))
            except Exception:
                continue
        if points:
            return points

    try:
        loc = element.Location
        if isinstance(loc, LocationCurve):
            curve = loc.Curve
            points.append(curve.GetEndPoint(0))
            points.append(curve.GetEndPoint(1))
    except Exception:
        pass

    for box_view in (view, None):
        box = None
        try:
            box = element.get_BoundingBox(box_view)
        except Exception:
            box = None
        if box is None:
            continue
        try:
            low = box.Min
            high = box.Max
        except Exception:
            continue
        transform = None
        try:
            transform = box.Transform
        except Exception:
            transform = None
        for x in (low.X, high.X):
            for y in (low.Y, high.Y):
                for z in (low.Z, high.Z):
                    corner = XYZ(x, y, z)
                    if transform is not None:
                        try:
                            corner = transform.OfPoint(corner)
                        except Exception:
                            pass
                    points.append(corner)
        break
    return points


def outermost_extent(elements, direction, view):
    """How far the selected services reach in ``direction``.

    This is the datum the displaced text is set out from: the outermost edge
    of the selection on the side the text is going, so text and leaders start
    beyond the services rather than at some distance from the dimension line
    that happens to land on top of a pipe.
    """
    best = None
    for element in elements:
        for point in extent_points(element, view):
            try:
                value = point.DotProduct(direction)
            except Exception:
                continue
            if best is None or value > best:
                best = value
    return best


def is_clear(point, occupied, clearance):
    for other in occupied:
        try:
            if point.DistanceTo(other) < clearance:
                return False
        except Exception:
            pass
    return True


def pull_out_small_segments(
    doc, view, dimension, entries, elements, picked_point, axis, perp, settings, report
):
    """Leader the text of anything under the threshold out clear of the string.

    The text zone is set out from the **outermost edge of the selected
    services on the side the text is going**, square to the dimension string:
    the first displaced value 200mm beyond it, every one after that a further
    50mm out, all in model millimetres. Every position is measured from that
    one datum, so the leaders never lengthen with the value they carry or with
    the spacing of the pipes, and nothing lands on a service.

    All of it is a straight stack at one position along the string - never
    alternating sides - and the segments stay native Revit dimension segments
    moved by their own ``TextPosition``, so the leaders terminate exactly as
    they would if the text had been dragged by hand.
    """
    scale = 100
    try:
        scale = int(view.Scale)
    except Exception:
        scale = 100
    if scale <= 0:
        scale = 100

    threshold_mm = pull_threshold_mm(settings, scale)
    threshold_ft = mm_to_ft(threshold_mm)

    # model millimetres - these are set out from the services, not from the
    # sheet, so they must not be multiplied by the view scale
    offset_ft = mm_to_ft(setting_float(settings, "pull_offset_mm"))
    spacing_ft = mm_to_ft(setting_float(settings, "pull_gap_mm"))
    clear_ft = mm_to_ft(setting_float(settings, "pull_clear_mm"))
    if spacing_ft < TINY:
        spacing_ft = mm_to_ft(float(DEFAULTS["pull_gap_mm"]))

    small = []
    stuck = 0
    for segment in segment_records(dimension):
        value = segment_value_ft(segment)
        if value is None or value >= threshold_ft:
            continue
        try:
            if not segment.IsTextPositionAdjustable():
                stuck += 1
                continue
        except Exception:
            pass
        anchor = 0.0
        try:
            anchor = segment.TextPosition.DotProduct(axis)
        except Exception:
            anchor = 0.0
        small.append((anchor, segment))

    if stuck:
        report.issue(
            "{0} dimension{1} under {2}mm could not have the text moved - Revit would not "
            "allow it".format(stuck, "" if stuck == 1 else "s", int(round(threshold_mm)))
        )
    if not small:
        return 0

    from_end = settings.get("pull_side") == "end"
    # nearest the string first, so the leaders fan out without crossing
    small.sort(key=lambda pair: pair[0], reverse=from_end)

    positions = [entry[0] for entry in entries]
    edge_t = max(positions) if from_end else min(positions)
    step = spacing_ft if from_end else -spacing_ft

    z_value = picked_point.Z
    try:
        z_value = dimension.Curve.GetEndPoint(0).Z
    except Exception:
        pass
    try:
        picked_out = picked_point.DotProduct(perp)
    except Exception:
        picked_out = 0.0

    # the datum every position is measured from
    datum = None
    if settings.get("pull_datum", "mep_edge") == "mep_edge":
        datum = outermost_extent(elements, perp, view)
        if datum is None:
            report.note(
                "The outermost edge of the services could not be worked out, so the text "
                "was set out from the dimension line instead"
            )
    if datum is None:
        datum = picked_out

    stacked = settings.get("pull_layout", "stacked") != "row"
    # the column sits one gap clear of the last witness line
    column_t = edge_t + step

    def slot_point(index):
        """Where the text for slot ``index`` goes.

        Stacked: a single straight column, the first value ``offset`` beyond
        the datum and each one after that a further ``spacing`` out, square to
        the dimension string. Every position comes off the same datum, so a
        long value or a wide gap between pipes never lengthens a leader.

        Row: the v1.1 layout, along the string beside each other.
        """
        if stacked:
            out = picked_point + perp * (datum + offset_ft + spacing_ft * index - picked_out)
            try:
                out_t = out.DotProduct(axis)
            except Exception:
                out_t = 0.0
            candidate = out + axis * (column_t - out_t)
        else:
            out = picked_point + perp * (datum + offset_ft - picked_out)
            try:
                out_t = out.DotProduct(axis)
            except Exception:
                out_t = 0.0
            candidate = out + axis * ((edge_t + step * (index + 1)) - out_t)
        return XYZ(candidate.X, candidate.Y, z_value)

    # Only text that was already in the view is an obstacle. What this run
    # places is on the slot grid by construction and never collides with
    # itself - and must not be tested against the clearance radius, which is
    # deliberately wider than the stack spacing so a neighbouring annotation
    # pushes the whole column clear rather than interleaving with it.
    occupied = existing_leadered_text(doc, view)

    slot = 0
    placed = 0
    for _anchor, segment in small:
        point = None
        for _try in range(200):
            candidate = slot_point(slot)
            slot += 1
            if is_clear(candidate, occupied, clear_ft):
                point = candidate
                break
        if point is None:
            report.issue(
                "A dimension under {0}mm had nowhere clear to sit and was left where "
                "Revit put it".format(int(round(threshold_mm)))
            )
            continue
        try:
            segment.TextPosition = point
            placed += 1
        except Exception as err:
            report.issue(
                "A dimension under {0}mm would not move: {1}".format(
                    int(round(threshold_mm)), err
                )
            )

    if placed:
        try:
            dimension.HasLeader = True
        except Exception:
            report.note(
                "The text was moved out but Revit would not turn the leader on - check "
                "the dimension type has a leader enabled"
            )
    return placed


def outward_normal(picked_point, service_point, axis):
    """Unit vector from the services towards the dimension line, in plan."""
    fallback = None
    try:
        fallback = XYZ.BasisZ.CrossProduct(axis).Normalize()
    except Exception:
        fallback = None
    if service_point is None:
        return fallback
    try:
        vector = picked_point - service_point
        vector = vector - axis * vector.DotProduct(axis)
        vector = XYZ(vector.X, vector.Y, 0.0)
        if vector.GetLength() < TINY:
            return fallback
        return vector.Normalize()
    except Exception:
        return fallback


def average_point(elements):
    points = []
    for element in elements:
        point = element_midpoint(element)
        if point is not None:
            points.append(point)
    if not points:
        return None
    total = XYZ(0.0, 0.0, 0.0)
    for point in points:
        total = total + point
    return total * (1.0 / float(len(points)))


def pick_services(uidoc, report):
    """Pre-selection if there is one, otherwise a multi-pick in the view."""
    doc = uidoc.Document
    elements = []
    try:
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if service_kind(element) is not None:
                elements.append(element)
    except Exception:
        elements = []
    if elements:
        return elements, True

    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            ServiceFilter(),
            "Select pipes, ducts, cable trays, conduits or generic models, then press "
            "Enter or click Finish (pre-select them instead to skip this step)",
        )
    except OperationCanceledException:
        report.cancelled = True
        return [], False
    except Exception as err:
        report.error = "Selection failed: {0}".format(err)
        return [], False

    for reference in references:
        try:
            element = doc.GetElement(reference.ElementId)
        except Exception:
            element = None
        if service_kind(element) is not None:
            elements.append(element)
    return elements, False


def pick_linked_walls_columns(uidoc, settings, report):
    """One linked wall or column by default - a single click, no Finish.

    Multi-pick is a setting rather than the default precisely because
    ``PickObjects`` will not return until Finish or Enter is pressed, which
    puts a keystroke in the middle of every run.
    """
    if settings.get("link_step") != "on":
        return []
    doc = uidoc.Document
    try:
        if settings.get("link_multi") == "on":
            references = uidoc.Selection.PickObjects(
                ObjectType.LinkedElement,
                LinkedWallColumnFilter(doc),
                "Optional: add linked walls or columns, then press Enter to complete "
                "(Esc to carry on without any)",
            )
            return list(references)
        reference = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            LinkedWallColumnFilter(doc),
            "Optional: click one linked wall or column, or press Esc to go straight to "
            "placing the dimension",
        )
        return [reference] if reference is not None else []
    except OperationCanceledException:
        # Escape here means "none, carry on" rather than abandon the tool
        return []
    except Exception as err:
        report.note("Linked selection was skipped: {0}".format(err))
        return []


def run_once(uidoc, uiapp, settings, report):
    """One dimension string, start to finish. False means stop looping."""
    doc = uidoc.Document
    view = doc.ActiveView

    try:
        if view.IsTemplate:
            report.error = "Smart Dimensions cannot run on a view template."
            return False
    except Exception:
        pass
    try:
        if PLAN_VIEW_TYPES and view.ViewType not in PLAN_VIEW_TYPES:
            report.error = (
                "Smart Dimensions runs in plan views. Open a floor, ceiling or engineering "
                "plan and run it again."
            )
            return False
    except Exception:
        pass

    elements, pre_selected = pick_services(uidoc, report)
    if report.cancelled or report.error:
        return False
    if not elements:
        report.error = (
            "Nothing usable was selected - pipes, ducts, cable trays, conduits and generic "
            "models only."
        )
        return False

    run_direction = dominant_direction(elements)
    if run_direction is None:
        report.error = "The selected services are vertical in plan - nothing to dimension across."
        return False
    axis = dimension_axis(run_direction)
    if axis is None:
        report.error = "The direction across the selected services could not be worked out."
        return False

    entries, fallback = collect_service_entries(
        doc, view, elements, axis, run_direction, settings, report
    )
    if not entries:
        report.error = "No usable references came back from the selected services."
        return False

    service_positions = [entry[0] for entry in entries]
    link_references = pick_linked_walls_columns(uidoc, settings, report)
    if link_references:
        link_entries = collect_link_entries(
            doc, link_references, axis, service_positions, settings, report
        )
        entries.extend(link_entries)
        fallback.extend(link_entries)

    min_gap = mm_to_ft(setting_float(settings, "min_gap_mm"))
    entries = dedupe_and_sort(entries, min_gap)
    fallback = dedupe_and_sort(fallback, min_gap)
    if len(entries) < 2:
        report.error = (
            "A dimension needs two references and only one came back. Select more than one "
            "service, or add a linked wall or column."
        )
        return False

    attempts = [entries]
    if len(fallback) >= 2 and len(fallback) != len(entries):
        attempts.append(fallback)

    try:
        picked_point = uidoc.Selection.PickPoint("Click where the dimension line should sit")
    except OperationCanceledException:
        report.cancelled = True
        return False
    except Exception as err:
        report.error = "The dimension line position was not picked: {0}".format(err)
        return False

    perp = outward_normal(picked_point, average_point(elements), axis)

    muffler = DialogMuffler(uiapp)
    muffler.enable()
    trans = quiet_transaction(doc, "RevoBIM Smart Dimensions")
    try:
        trans.Start()
        dimension, used = create_dimension(
            doc, view, attempts, picked_point, axis, settings, report
        )
        if dimension is None:
            trans.RollBack()
        else:
            if settings.get("pull_out") == "on" and perp is not None:
                try:
                    doc.Regenerate()
                    report.pulled += pull_out_small_segments(
                        doc,
                        view,
                        dimension,
                        used,
                        elements,
                        picked_point,
                        axis,
                        perp,
                        settings,
                        report,
                    )
                except Exception as err:
                    report.issue(
                        "The small dimensions were left where Revit put them: {0}".format(err)
                    )
            trans.Commit()
    except Exception as err:
        report.error = "Smart Dimensions stopped: {0}".format(err)
        try:
            trans.RollBack()
        except Exception:
            pass
    finally:
        muffler.disable()

    if pre_selected and settings.get("repeat") == "on":
        # otherwise the next lap round the loop would silently reuse the same
        # pre-selection for ever
        try:
            uidoc.Selection.SetElementIds(List[ElementId]())
        except Exception:
            pass

    return report.error is None


def run(uidoc, uiapp, settings=None):
    """Entry point used by the command button."""
    if settings is None:
        settings = load_settings()
    report = Report()
    keep_going = True
    while keep_going:
        report.error = None
        report.cancelled = False
        ok = run_once(uidoc, uiapp, settings, report)
        keep_going = ok and settings.get("repeat") == "on"
        if report.cancelled:
            break
    return report


# ``List`` is only needed to clear the selection - import it late and quietly so
# a missing System.Collections binding cannot stop the module loading.
List = None
try:
    clr.AddReference("System.Core")
    from System.Collections.Generic import List as _List

    List = _List
except Exception:
    List = None
