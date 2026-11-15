# -*- coding: utf-8 -*-
"""RevoBIM PY | MEP Link - shared core.

Geometry, connectivity, settings and the routines behind every button in the
MEP Link pulldown.

This module lives in the extension's own lib folder, which pyRevit puts on
sys.path itself, so no button has to touch sys.path to import it. The name is
deliberately unique across every RevoBIM extension - it is a single module,
not a package, so it cannot collide with or overwrite lib\revobim.

Raising and lowering elements is deliberately NOT here: that job belongs to
the Nudge extension. The buttons themselves are a few lines each: read the
settings, call one function here.

The module sits inside the pulldown folder rather than in the extension's
lib\\revobim, so the tool stays self-contained and nothing else in the
extension has to change to install it. Each button adds its parent folder to
sys.path to import it.

Revit 2024-2027 | IronPython 2.7 and 3 | metric (mm)
"""

# MAJOR - changes what the tools do to the model
# MINOR - a new capability
# PATCH - a fix
VERSION = "2.4.0"

import os
import math

from Autodesk.Revit.DB import (XYZ, Line, LocationCurve, Transaction,
                               ElementTransformUtils, BuiltInParameter,
                               ConnectorProfileType, IFailuresPreprocessor,
                               FailureProcessingResult, FailureSeverity)
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Electrical import CableTray, Conduit
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException


# ---------------------------------------------------------------------------
# units and tolerances
# ---------------------------------------------------------------------------

FT = 304.8                      # mm per foot


def mm(value):
    """millimetres -> internal feet"""
    return value / FT


def ft2mm(value):
    return value * FT


TOL_ALIGN = mm(2.0)             # max X-Y offset still counted as "aligned"
TOL_FLAT = mm(1.0)              # max rise still counted as "level"
TOL_CONN = mm(10.0)             # connector search radius
TOL_SNAP = mm(30.0)             # how far a connector may be snapped to close a joint
SIZE_TOL = mm(0.5)              # sizes this close are the same size
MIN_LEN = mm(10.0)              # shortest straight worth creating at all
PARALLEL_DOT = 0.9995           # dot product above which two runs are parallel

GAP_START_FACTOR = 2.0          # opening guess for a straight, x the profile
GAP_START_MIN_MM = 250.0
GAP_ATTEMPTS = 5

# Angles to fall back through when the set one cannot make the level change.
# A small offset at 90 degrees gives a leg with no room for two fittings; the
# shallower the angle, the longer the leg for the same rise (leg = rise /
# sin(angle)), so working down this list is what turns an impossible vertical
# drop into a buildable angled one.
#
# Every one is a multiple of five degrees. An angle that came out of the
# geometry rather than off a drawing board is no use to anyone setting the job
# out, and fitting families are rarely happy with the odd fractions either.
FALLBACK_ANGLES = (60.0, 45.0, 40.0, 35.0, 30.0, 25.0, 20.0, 15.0, 10.0, 5.0)
ANGLE_STEP = 5.0


def round_angle(angle):
    """To the nearest five degrees, kept inside 5 - 90."""
    stepped = round(float(angle) / ANGLE_STEP) * ANGLE_STEP
    return max(ANGLE_STEP, min(90.0, stepped))

MEP_CURVES = (Pipe, Duct, CableTray, Conduit)

SIZE_PARAMS = (
    BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
    BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
    BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
    BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
    BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
    BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
)


# ---------------------------------------------------------------------------
# settings - plain key=value under %APPDATA%\RevoBIM
# ---------------------------------------------------------------------------

SETTINGS_DIR = os.path.join(os.getenv('APPDATA') or '', 'RevoBIM')
SETTINGS_PATH = os.path.join(SETTINGS_DIR, 'mep_link.txt')

DEFAULTS = {
    'riser_angle': '90',            # 90 / 45 / a number
    'corner_angle': '90',
    'align_mode': 'xy',             # xy / z / both
    'report': 'problems',           # problems / always / never
    'keep_going': 'yes',            # keep picking pairs until Escape
}


def load_settings():
    """Read the settings, falling back to the defaults key by key.

    A missing or damaged file, or a key from an older version, must not stop
    the tool - each key is taken on its own and anything unreadable is simply
    left at its default.
    """
    values = dict(DEFAULTS)
    try:
        handle = open(SETTINGS_PATH, 'r')
    except Exception:
        return values
    try:
        for line in handle:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            if key in values:
                values[key] = value.strip()
    except Exception:
        pass
    finally:
        try:
            handle.close()
        except Exception:
            pass
    return values


def save_settings(values):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(SETTINGS_PATH, 'w')
        try:
            handle.write('# RevoBIM PY - MEP Link settings\n')
            for key in sorted(values.keys()):
                handle.write('{0}={1}\n'.format(key, values[key]))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def setting_angle(values, key):
    """An angle setting as a number, whatever spelling it was saved in.

    Rounded to the nearest five degrees on the way out, so a file edited by
    hand cannot put an odd angle into the model.
    """
    try:
        angle = float(str(values.get(key, '90')).strip())
    except Exception:
        return 90.0
    if angle <= 0 or angle > 90:
        return 90.0
    return round_angle(angle)


# ---------------------------------------------------------------------------
# document handles - set once per command by begin()
# ---------------------------------------------------------------------------

doc = None
uidoc = None
_logger = None


def begin(ui_document, logger=None):
    """Point the module at the active document. Call this first."""
    global doc, uidoc, _logger
    uidoc = ui_document
    doc = ui_document.Document
    _logger = logger


def _debug(message):
    if _logger:
        try:
            _logger.debug(message)
        except Exception:
            pass


def alert(message, title="RevoBIM"):
    TaskDialog.Show(title, message)


def angle_text(angle):
    return "{0:g}".format(round(angle, 2))


# ---------------------------------------------------------------------------
# warnings
# ---------------------------------------------------------------------------

class QuietFailures(IFailuresPreprocessor):
    """Dismisses Revit's dialogs while the tool is trying things out.

    Building a connection is an attempt that may be rolled back, and a failed
    attempt raises "insufficient space to create the required fittings" and
    friends. Those are Revit talking to itself mid-experiment; the outcome is
    reported once at the end instead.
    """

    def PreprocessFailures(self, accessor):
        try:
            messages = list(accessor.GetFailureMessages())
        except Exception:
            return FailureProcessingResult.Continue

        has_error = False
        for failure in messages:
            try:
                severity = failure.GetSeverity()
            except Exception:
                severity = FailureSeverity.Warning
            if severity == FailureSeverity.Warning:
                try:
                    accessor.DeleteWarning(failure)
                except Exception:
                    pass
            else:
                has_error = True

        if has_error:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def quiet_transaction(name):
    """A started transaction that will not stop to ask about warnings."""
    trans = Transaction(doc, name)
    trans.Start()
    try:
        options = trans.GetFailureHandlingOptions()
        options = options.SetFailuresPreprocessor(QuietFailures())
        options = options.SetClearAfterRollback(True)
        trans.SetFailureHandlingOptions(options)
    except Exception as err:
        _debug("could not attach the failure handler: {0}".format(err))
    return trans


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

class MEPCurveFilter(ISelectionFilter):
    """Straight pipes, ducts, cable trays and conduits only."""

    def AllowElement(self, element):
        return isinstance(element, MEP_CURVES)

    def AllowReference(self, reference, position):
        return False


def pick_element(prompt, selection_filter=None):
    """One element, or None if the user pressed Escape."""
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, selection_filter or MEPCurveFilter(), prompt)
    except OperationCanceledException:
        return None
    except Exception as err:
        _debug("pick failed: {0}".format(err))
        return None
    return doc.GetElement(ref.ElementId)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def get_line(element):
    """The element's LocationCurve as a straight Line, or None."""
    try:
        loc = element.Location
    except Exception:
        return None
    if not isinstance(loc, LocationCurve):
        return None
    curve = loc.Curve
    if not isinstance(curve, Line):
        return None
    return curve


def plan_direction(line):
    d = line.Direction
    v = XYZ(d.X, d.Y, 0)
    if v.GetLength() < 1.0e-9:
        return None
    return v.Normalize()


def is_level(line):
    return abs(line.GetEndPoint(0).Z - line.GetEndPoint(1).Z) < TOL_FLAT


def slope_degrees(line):
    """How far off horizontal a run is, in degrees."""
    d = line.Direction.Normalize()
    return abs(math.degrees(math.asin(max(-1.0, min(1.0, d.Z)))))


def element_kind(element):
    if isinstance(element, Pipe):
        return "Pipe"
    if isinstance(element, Duct):
        return "Duct"
    if isinstance(element, CableTray):
        return "Cable Tray"
    if isinstance(element, Conduit):
        return "Conduit"
    return "Element"


def closest_points(line_a, line_b):
    """The two points where two infinite 3D lines come closest.

    This is what makes the tools work on sloped and skew runs: instead of
    assuming both are level and crossing in plan, it solves for the real
    common perpendicular. Returns (point on a, point on b, distance) or None
    when the lines are parallel.
    """
    p = line_a.GetEndPoint(0)
    u = line_a.Direction.Normalize()
    q = line_b.GetEndPoint(0)
    v = line_b.Direction.Normalize()

    w = p - q
    b = u.DotProduct(v)
    d = u.DotProduct(w)
    e = v.DotProduct(w)
    denom = 1.0 - b * b
    if abs(denom) < 1.0e-9:
        return None                         # parallel, no unique perpendicular

    s = (b * e - d) / denom
    t = (e - b * d) / denom
    point_a = p + u.Multiply(s)
    point_b = q + v.Multiply(t)
    return point_a, point_b, point_a.DistanceTo(point_b)


def param_on(line, point):
    """How far along a line's direction a point sits, from its start."""
    return (point - line.GetEndPoint(0)).DotProduct(line.Direction.Normalize())


def span(line):
    """(low, high) parameters of a line's own two ends."""
    return tuple(sorted([param_on(line, line.GetEndPoint(0)),
                         param_on(line, line.GetEndPoint(1))]))


def point_on(line, t):
    return line.GetEndPoint(0) + line.Direction.Normalize().Multiply(t)


def turn_between(dir_in, dir_out):
    """The angle a fitting has to turn through, in degrees."""
    dot = max(-1.0, min(1.0, dir_in.Normalize().DotProduct(dir_out.Normalize())))
    return math.degrees(math.acos(dot))


# ---------------------------------------------------------------------------
# sizes and profiles
# ---------------------------------------------------------------------------

def size_key(element):
    values = []
    for bip in SIZE_PARAMS:
        try:
            param = element.get_Parameter(bip)
        except Exception:
            param = None
        if param:
            value = param.AsDouble()
            if value > 0:
                values.append(value)
    return tuple(values)


def sizes_match(el_1, el_2):
    """Are these two the same size, to within half a millimetre.

    Exact equality was the wrong test: a rectangular duct reports width,
    height and an equivalent diameter Revit derives from them, and two ducts
    the same size on paper can differ in the last decimal of the derived one.
    """
    keys_1 = sorted(size_key(el_1))
    keys_2 = sorted(size_key(el_2))
    if len(keys_1) != len(keys_2):
        return False
    for value_1, value_2 in zip(keys_1, keys_2):
        if abs(value_1 - value_2) > SIZE_TOL:
            return False
    return True


def size_text(element):
    dims = []
    for bip in (BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
                BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
                BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
                BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM):
        try:
            param = element.get_Parameter(bip)
        except Exception:
            param = None
        if param and param.AsDouble() > 0:
            dims.append(param.AsDouble())
    if not dims:
        for bip in (BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
                    BuiltInParameter.RBS_CURVE_DIAMETER_PARAM):
            try:
                param = element.get_Parameter(bip)
            except Exception:
                param = None
            if param and param.AsDouble() > 0:
                dims.append(param.AsDouble())
                break
    if not dims:
        return "unknown size"
    return " x ".join("{0:.0f}mm".format(ft2mm(v)) for v in dims)


def profile_span(element):
    sizes = size_key(element)
    return max(sizes) if sizes else mm(50.0)


# ---------------------------------------------------------------------------
# connectors
# ---------------------------------------------------------------------------

def get_connectors(element):
    """Connectors of an MEP curve or of a fitting family instance."""
    if element is None:
        return []
    manager = None
    try:
        manager = element.ConnectorManager
    except Exception:
        manager = None
    if manager is None:
        try:
            manager = element.MEPModel.ConnectorManager
        except Exception:
            manager = None
    if manager is None:
        return []
    try:
        return list(manager.Connectors)
    except Exception:
        return []


def connector_at(element, point, tolerance=TOL_CONN):
    best = None
    best_dist = 1.0e9
    for conn in get_connectors(element):
        try:
            dist = conn.Origin.DistanceTo(point)
        except Exception:
            continue
        if dist < best_dist:
            best_dist = dist
            best = conn
    if best is not None and best_dist <= tolerance:
        return best
    return None


def free_connector_at(element, point):
    conn = connector_at(element, point, TOL_CONN)
    if conn is None or not conn.IsConnected:
        return
    for ref in list(conn.AllRefs):
        try:
            if ref.Owner.Id != element.Id:
                conn.DisconnectFrom(ref)
        except Exception:
            pass


def is_open(conn):
    try:
        return not conn.IsConnected
    except Exception:
        return False


def open_connectors(element):
    """Fresh, currently-open connectors on one element.

    Always read again rather than held. A Connector is a handle into the
    document's current state, and a doc.Regenerate() in between invalidates
    it: a ConnectTo on a stale handle raises nothing and joins nothing, which
    is exactly how a run ends up looking right and behaving like loose parts.
    """
    return [conn for conn in get_connectors(element) if is_open(conn)]


def nearest_open(elements, target, tolerance):
    """(element, connector, distance) nearest an open connector to target."""
    best = (None, None, 1.0e9)
    for element in elements:
        for conn in open_connectors(element):
            try:
                dist = conn.Origin.DistanceTo(target)
            except Exception:
                continue
            if dist < best[2]:
                best = (element, conn, dist)
    if best[1] is not None and best[2] <= tolerance:
        return best
    return (None, None, 1.0e9)


def join_one(fitting, target, straights):
    """Close one open joint at target. Returns True if it took.

    Every handle is re-read after anything that changes the document, so the
    ConnectTo is always made between two live connectors.
    """
    element, conn, dist = nearest_open(straights, target, TOL_SNAP)
    if conn is None:
        return False

    # a bend trims the straight back to its own face, and sometimes stops a
    # few millimetres short of it - pull the straight onto the face first
    if dist > mm(0.2):
        if not snap_end(element, conn.Origin, target):
            return False
        doc.Regenerate()
        conn = connector_at(element, target, TOL_SNAP)
        if conn is None or not is_open(conn):
            return False

    f_conn = connector_at(fitting, target, TOL_SNAP)
    if f_conn is None or not is_open(f_conn):
        return False

    try:
        f_conn.ConnectTo(conn)
        return True
    except Exception as err:
        _debug("could not close a joint: {0}".format(err))
        return False


def close_joints(straights, fittings):
    """Make the run a real system, not just parts that touch.

    Cable trays are the reason this exists. NewElbowFitting places the fitting
    and trims the trays to it, but frequently leaves the connectors merely
    coincident rather than connected - the run looks right, schedules wrong,
    and comes apart the moment anything is dragged.

    Each open fitting connector is closed in turn, and the pass repeats while
    it is still making progress: closing one joint regenerates the document
    and can move the next one, so a single sweep is not enough.
    """
    joined = 0

    for _ in range(3):
        # positions first, handles second - the positions survive a regenerate
        targets = []
        for fitting in fittings:
            if fitting is None:
                continue
            for conn in open_connectors(fitting):
                try:
                    targets.append((fitting, conn.Origin))
                except Exception:
                    continue

        if not targets:
            break

        made = 0
        for fitting, target in targets:
            if join_one(fitting, target, straights):
                made += 1
                doc.Regenerate()

        joined += made
        if not made:
            break

    # anything left over - two straights meeting with no fitting between them
    for _ in range(2):
        made = 0
        pairs = []
        for i, element in enumerate(straights):
            for conn in open_connectors(element):
                try:
                    pairs.append((element.Id, conn.Origin))
                except Exception:
                    continue

        for owner_id, point in pairs:
            for element in straights:
                if element.Id == owner_id:
                    continue
                conn_b = connector_at(element, point, mm(1.5))
                if conn_b is None or not is_open(conn_b):
                    continue
                owner = doc.GetElement(owner_id)
                conn_a = connector_at(owner, point, mm(1.5))
                if conn_a is None or not is_open(conn_a):
                    continue
                try:
                    conn_a.ConnectTo(conn_b)
                    made += 1
                    doc.Regenerate()
                except Exception:
                    pass
                break

        joined += made
        if not made:
            break

    return joined


def snap_end(element, from_point, to_point):
    """Stretch a straight along its own axis so one end lands on to_point."""
    line = get_line(element)
    if line is None:
        return False
    start = line.GetEndPoint(0)
    end = line.GetEndPoint(1)
    try:
        if start.DistanceTo(from_point) <= end.DistanceTo(from_point):
            new_line = Line.CreateBound(to_point, end)
        else:
            new_line = Line.CreateBound(start, to_point)
        if new_line.Length < MIN_LEN:
            return False
        element.Location.Curve = new_line
        return True
    except Exception as err:
        _debug("could not snap an end: {0}".format(err))
        return False


def connected_to(element, other):
    """Is element genuinely joined to other, asked of the model itself."""
    for conn in get_connectors(element):
        try:
            if not conn.IsConnected:
                continue
            for ref in conn.AllRefs:
                if ref.Owner is not None and ref.Owner.Id == other.Id:
                    return True
        except Exception:
            continue
    return False


def fully_connected(straights, fittings):
    """Every fitting joined on every side, and joined to a real straight.

    Checking the fitting's own connectors is not enough on its own. A cable
    tray elbow can report both sides connected while the trays either side of
    it are not actually joined to it, which is the failure that leaves a run
    looking right and behaving like loose parts. So the test is made from both
    ends: no open connector anywhere on a fitting, and every fitting joined to
    at least two neighbours it is supposed to be joined to.
    """
    for element in straights:
        line = get_line(element)
        if line is None or line.Length < mm(1.0):
            return False

    neighbours = list(straights) + [f for f in fittings if f is not None]

    for fitting in fittings:
        if fitting is None:
            return False

        connectors = get_connectors(fitting)
        if not connectors:
            return False
        for conn in connectors:
            if is_open(conn):
                return False

        joined = 0
        for other in neighbours:
            if other.Id == fitting.Id:
                continue
            if connected_to(fitting, other):
                joined += 1
        if joined < 2:
            return False

    return True


# ---------------------------------------------------------------------------
# creating elements
# ---------------------------------------------------------------------------

def source_workset_id(element):
    if not doc.IsWorkshared:
        return None
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    except Exception:
        return None
    return param.AsInteger() if param else None


def apply_workset(element, workset_id):
    if element is None or workset_id is None:
        return
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if param is not None and not param.IsReadOnly:
            param.Set(workset_id)
    except Exception as err:
        _debug("workset failed: {0}".format(err))


def copy_as_line(source, p_start, p_end, workset_id=None, reference=None):
    """A copy of source (type, system, size, service type, parameters kept)
    stretched between two points, squared up if it is rectangular."""
    try:
        new_ids = ElementTransformUtils.CopyElement(doc, source.Id, XYZ(0, 0, 0))
    except Exception:
        new_ids = ElementTransformUtils.CopyElement(
            doc, source.Id, XYZ(p_start.X, p_start.Y, p_start.Z))
    element = doc.GetElement(list(new_ids)[0])
    element.Location.Curve = Line.CreateBound(p_start, p_end)
    doc.Regenerate()

    reference = reference if reference is not None else source
    set_profile_rotation(element, profile_axis(reference))
    square_up_profile(element, reference)
    doc.Regenerate()

    apply_workset(element, workset_id)
    return element


def profile_axis(element):
    """The width direction of a rectangular element, from a connector."""
    for conn in get_connectors(element):
        try:
            if conn.Shape == ConnectorProfileType.Round:
                return None
        except Exception:
            pass
        try:
            return conn.CoordinateSystem.BasisX
        except Exception:
            continue
    return None


def is_round(element):
    """True when the profile has no orientation at all.

    A round pipe or duct does not care which way up it is, so a bend may turn
    in any plane.
    """
    return rect_connector(element) is None


def is_square(element):
    """True when a rectangular profile is as tall as it is wide.

    A square duct does have an orientation, but turning it a quarter turn
    leaves it identical - the connector still reads the same width and height,
    so the two sides of a bend still match. That is enough to let it take the
    straight vertical drop that an unequal-sided duct cannot.
    """
    conn = rect_connector(element)
    if conn is None:
        return False
    try:
        return abs(conn.Width - conn.Height) <= SIZE_TOL
    except Exception:
        return False


def profile_shape(element):
    """'round', 'rect', or None where the element gives nothing to read."""
    for conn in get_connectors(element):
        try:
            return 'round' if conn.Shape == ConnectorProfileType.Round \
                else 'rect'
        except Exception:
            continue
    return None


def shapes_match(el_1, el_2):
    """Round to round, or rectangular to rectangular.

    This is the check that actually matters when linking two runs. Revit will
    not put an elbow between a round connector and a rectangular one, and this
    tool does not place a shape transition, so a mismatch has to be refused -
    but a difference of TYPE does not, which is what 2.2.0 got wrong.
    """
    shape_1, shape_2 = profile_shape(el_1), profile_shape(el_2)
    if shape_1 is None or shape_2 is None:
        return True                     # nothing to read, let Revit decide
    return shape_1 == shape_2


def type_name(element):
    try:
        return doc.GetElement(element.GetTypeId()).Name
    except Exception:
        return "its own type"


def turns_freely(element):
    """Can this profile take a bend that drops and turns at the same time."""
    return is_round(element) or is_square(element)


def plan_turn_between(line_a, line_b):
    """The angle between two runs measured in plan, in degrees."""
    d_a, d_b = plan_direction(line_a), plan_direction(line_b)
    if d_a is None or d_b is None:
        return 0.0
    dot = max(-1.0, min(1.0, abs(d_a.DotProduct(d_b))))
    return math.degrees(math.acos(dot))


def rect_connector(element):
    for conn in get_connectors(element):
        try:
            if conn.Shape != ConnectorProfileType.Round:
                return conn
        except Exception:
            continue
    return None


def set_profile_rotation(element, target_dir):
    """Spin a rectangular element about its own axis to match target_dir.

    Only ever call this while the element is still free. Rotating a tray that
    is already connected to a bend raises "the family is connected in a
    network and can no longer keep the connectivity", and once the bend is in
    it sets the orientation itself.
    """
    if element is None or target_dir is None:
        return False
    line = get_line(element)
    if line is None:
        return False

    p_start, p_end = line.GetEndPoint(0), line.GetEndPoint(1)
    conn = (connector_at(element, p_start, mm(150.0))
            or connector_at(element, p_end, mm(150.0)))
    if conn is None:
        return False
    try:
        if conn.Shape == ConnectorProfileType.Round:
            return False
    except Exception:
        pass

    axis_vector = (p_end - p_start).Normalize()

    def perpendicular_part(vector):
        flat = vector - axis_vector.Multiply(vector.DotProduct(axis_vector))
        return None if flat.GetLength() < 1.0e-7 else flat.Normalize()

    try:
        current = perpendicular_part(conn.CoordinateSystem.BasisX)
    except Exception:
        return False
    target = perpendicular_part(target_dir)
    if current is None or target is None:
        return False

    angle = math.atan2(current.CrossProduct(target).DotProduct(axis_vector),
                       current.DotProduct(target))
    while angle > math.pi / 2.0 + 1.0e-9:
        angle -= math.pi
    while angle <= -math.pi / 2.0 - 1.0e-9:
        angle += math.pi
    if abs(angle) < math.radians(0.05):
        return False

    try:
        ElementTransformUtils.RotateElement(
            doc, element.Id, Line.CreateBound(p_start, p_end), angle)
        return True
    except Exception as err:
        _debug("profile rotation failed: {0}".format(err))
        return False


def square_up_profile(element, reference):
    """Turn a leg 90 degrees more if its width and height came out swapped.

    A copied rectangular duct set on a new line can come back with its profile
    turned, so a 400 x 200 run meets a leg reading 200 x 400. Revit will not
    elbow two connectors of different dimensions, so the bend never gets
    placed. Matching the coordinate systems is not enough on its own - the
    basis can line up while the dimensions read the other way round.
    """
    conn = rect_connector(element)
    ref = rect_connector(reference)
    if conn is None or ref is None:
        return False
    try:
        width, height = conn.Width, conn.Height
        ref_width, ref_height = ref.Width, ref.Height
    except Exception:
        return False

    if abs(width - ref_width) <= SIZE_TOL and abs(height - ref_height) <= SIZE_TOL:
        return False
    if abs(width - ref_height) > SIZE_TOL or abs(height - ref_width) > SIZE_TOL:
        return False

    line = get_line(element)
    if line is None:
        return False
    try:
        ElementTransformUtils.RotateElement(
            doc, element.Id,
            Line.CreateBound(line.GetEndPoint(0), line.GetEndPoint(1)),
            math.pi / 2.0)
        return True
    except Exception as err:
        _debug("could not square up the profile: {0}".format(err))
        return False


def build_elbow(element_a, element_b, point):
    """An elbow between two elements meeting at point, or None."""
    conn_a = connector_at(element_a, point)
    conn_b = connector_at(element_b, point)
    if conn_a is None or conn_b is None:
        return None
    try:
        return doc.Create.NewElbowFitting(conn_a, conn_b)
    except Exception as err:
        _debug("elbow failed: {0}".format(err))
        return None


def build_transition(element_a, element_b, point):
    """A reducer between two different-sized elements meeting at point."""
    conn_a = connector_at(element_a, point)
    conn_b = connector_at(element_b, point)
    if conn_a is None or conn_b is None:
        return None
    try:
        return doc.Create.NewTransitionFitting(conn_a, conn_b)
    except Exception as err:
        _debug("transition failed: {0}".format(err))
        return None


# ---------------------------------------------------------------------------
# validation shared by Riser Link and Corner Link
# ---------------------------------------------------------------------------

def type_note(el_1, el_2):
    """A line to add to the result when the two picks are different types.

    Everything created is a copy of the first pick, so the new legs and the
    fittings carry the first pick's type. That is worth saying out loud rather
    than leaving to be noticed in a schedule later.
    """
    if el_1.GetTypeId() == el_2.GetTypeId():
        return ""
    return (" The two are different types, so the new lengths and fittings "
            "took \"{0}\" from the first pick.".format(type_name(el_1)))


def check_pair(el_1, el_2):
    if el_1.Id == el_2.Id:
        return False, "That is the same element twice."
    if type(el_1) is not type(el_2):
        return False, ("These are different categories ({0} and {1}). Pick two "
                       "elements of the same service.".format(
                           element_kind(el_1), element_kind(el_2)))
    if not shapes_match(el_1, el_2):
        return False, ("One of these is round and the other is rectangular. "
                       "No shape transition is placed, so put one in by hand "
                       "and link to that.")
    if get_line(el_1) is None or get_line(el_2) is None:
        return False, "Both picks must be straight runs (not fittings or flex)."
    return True, ""


# ---------------------------------------------------------------------------
# the route builder - one place that creates, fits and connects
# ---------------------------------------------------------------------------

class Route(object):
    """A chain of points to run straights along, built inside one transaction.

    Everything is built, then measured. If any straight vanished, any fitting
    is missing, or any joint is open, the whole transaction is rolled back and
    the model is left exactly as it was.
    """

    def __init__(self, el_1, el_2, name):
        self.el_1 = el_1
        self.el_2 = el_2
        self.name = name
        self.workset_id = source_workset_id(el_1)
        self.same_size = sizes_match(el_1, el_2)

    def build(self, end_1, points, end_2, reducer_gap=0.0):
        """end_1 / end_2 are the far ends kept; points are the bend positions
        between them, in order from element one to element two."""
        first = points[0]
        last = points[-1]

        # hold element two back if a reducer has to fit in front of it
        target_2 = last
        if not self.same_size and reducer_gap > 0:
            toward = end_2 - last
            if toward.GetLength() > 1.0e-7:
                target_2 = last + toward.Normalize().Multiply(reducer_gap)

        trans = quiet_transaction(self.name)
        try:
            free_connector_at(self.el_1, nearest_end(self.el_1, first))
            free_connector_at(self.el_2, nearest_end(self.el_2, last))

            self.el_1.Location.Curve = Line.CreateBound(end_1, first)
            self.el_2.Location.Curve = Line.CreateBound(end_2, target_2)
            doc.Regenerate()

            straights = [self.el_1, self.el_2]
            chain = [self.el_1]

            for i in range(len(points) - 1):
                leg = copy_as_line(self.el_1, points[i], points[i + 1],
                                   self.workset_id)
                straights.append(leg)
                chain.append(leg)

            stub = None
            if not self.same_size and target_2.DistanceTo(last) > mm(1.0):
                stub = copy_as_line(self.el_1, last, target_2, self.workset_id)
                straights.append(stub)
                chain.append(stub)
            chain.append(self.el_2)

            fittings = []
            for i in range(len(chain) - 1):
                point = points[i] if i < len(points) else target_2
                if stub is not None and i == len(chain) - 2:
                    fittings.append(build_transition(chain[i], chain[i + 1],
                                                     target_2))
                else:
                    fittings.append(build_elbow(chain[i], chain[i + 1], point))
                doc.Regenerate()

            for fitting in fittings:
                apply_workset(fitting, self.workset_id)

            close_joints(straights, fittings)
            doc.Regenerate()

            if not fully_connected(straights, fittings):
                trans.RollBack()
                missing = len([f for f in fittings if f is None])
                return False, missing

            trans.Commit()
            return True, 0
        except Exception as err:
            try:
                trans.RollBack()
            except Exception:
                pass
            _debug("route failed: {0}".format(err))
            return False, -1


def nearest_end(element, point):
    line = get_line(element)
    if line is None:
        return point
    start, end = line.GetEndPoint(0), line.GetEndPoint(1)
    return start if start.DistanceTo(point) <= end.DistanceTo(point) else end


def failure_text(missing, el_1, extra=""):
    if missing < 0:
        return ("Nothing was changed - Revit rejected the connection. " + extra)
    if missing:
        return ("Nothing was changed. Revit would not place {0} of the "
                "fittings - check the type's routing preferences. "
                "{1}".format(missing, extra))
    return ("Nothing was changed. The fittings would not sit in the space "
            "available, or would not connect. {0}Try a shallower angle, move "
            "the {1}s further apart, or lengthen them.".format(
                extra, element_kind(el_1).lower()))


# ---------------------------------------------------------------------------
# Riser Link
# ---------------------------------------------------------------------------

def leg_run(rise, angle):
    """Horizontal distance a connecting leg covers at the given angle."""
    if angle >= 89.95:
        return 0.0
    return abs(rise) / math.tan(math.radians(angle))


def riser_link_pair(el_1, el_2, angle):
    """Two parallel runs on the same X-Y line at different levels."""
    ok, message = check_pair(el_1, el_2)
    if not ok:
        return False, message

    line_1, line_2 = get_line(el_1), get_line(el_2)
    if not is_level(line_1) or not is_level(line_2):
        return False, ("Riser Link expects two level runs. One of these is "
                       "sloped - use Corner Link, which handles slopes.")

    dir_1, dir_2 = plan_direction(line_1), plan_direction(line_2)
    if dir_1 is None or dir_2 is None:
        return False, "One of these is already vertical."
    if abs(dir_1.DotProduct(dir_2)) < PARALLEL_DOT:
        return False, ("These are not parallel in plan. Use Corner Link, or "
                       "Centreline Snap them first.")

    origin = line_1.GetEndPoint(0)

    def param_of(point):
        return (point.X - origin.X) * dir_1.X + (point.Y - origin.Y) * dir_1.Y

    def offset_of(point):
        vx, vy = point.X - origin.X, point.Y - origin.Y
        t = vx * dir_1.X + vy * dir_1.Y
        return math.sqrt((vx - t * dir_1.X) ** 2 + (vy - t * dir_1.Y) ** 2)

    for pt in (line_2.GetEndPoint(0), line_2.GetEndPoint(1)):
        if offset_of(pt) > TOL_ALIGN:
            return False, ("These are not on the same X-Y line (offset "
                           "{0:.0f}mm). Use Centreline Snap first, or Corner "
                           "Link, which does not need them aligned.".format(
                               ft2mm(offset_of(pt))))

    z_1, z_2 = line_1.GetEndPoint(0).Z, line_2.GetEndPoint(0).Z
    dz = z_2 - z_1
    if abs(dz) < TOL_FLAT:
        return False, ("These are at the same level - nothing to link. Drag "
                       "them together in plan instead.")

    a_lo, a_hi = sorted([param_of(line_1.GetEndPoint(0)),
                         param_of(line_1.GetEndPoint(1))])
    b_lo, b_hi = sorted([param_of(line_2.GetEndPoint(0)),
                         param_of(line_2.GetEndPoint(1))])

    if b_lo >= a_hi:
        meet, first_is_low = (a_hi + b_lo) / 2.0, True
    elif a_lo >= b_hi:
        meet, first_is_low = (b_hi + a_lo) / 2.0, False
    else:
        meet = (max(a_lo, b_lo) + min(a_hi, b_hi)) / 2.0
        first_is_low = (a_lo + a_hi) <= (b_lo + b_hi)

    angle = round_angle(angle)
    half = leg_run(dz, angle) / 2.0
    t_1, t_2 = ((meet - half, meet + half) if first_is_low
                else (meet + half, meet - half))
    far_1 = a_lo if first_is_low else a_hi
    far_2 = b_hi if first_is_low else b_lo

    if abs(t_1 - far_1) < MIN_LEN or abs(t_2 - far_2) < MIN_LEN:
        return False, ("There is no length left to work with at {0} degrees - "
                       "the rise is {1:.0f}mm and the leg needs {2:.0f}mm of "
                       "run. Move them apart, lengthen them, or use a steeper "
                       "angle.".format(angle_text(angle), abs(ft2mm(dz)),
                                       ft2mm(leg_run(dz, angle))))

    def at(t, z):
        return XYZ(origin.X + dir_1.X * t, origin.Y + dir_1.Y * t, z)

    route = Route(el_1, el_2, "RevoBIM - Riser Link")
    gap = min(max(profile_span(el_1), profile_span(el_2)) * 2.0,
              abs(t_2 - far_2) - MIN_LEN)
    missing = 0

    for attempt in range(3):
        reducer_gap = 0.0 if route.same_size else max(gap, MIN_LEN)
        ok, missing = route.build(at(far_1, z_1), [at(t_1, z_1), at(t_2, z_2)],
                                  at(far_2, z_2), reducer_gap)
        if ok:
            note = "" if route.same_size else " and a reducer"
            return True, ("Linked and connected with {0} degree bends{1}."
                          "{2}".format(angle_text(angle), note,
                                       type_note(el_1, el_2)))
        if route.same_size:
            break
        gap *= 2.0
        if gap > abs(t_2 - far_2) - MIN_LEN:
            break

    return False, failure_text(missing, el_1)


# ---------------------------------------------------------------------------
# Corner Link
# ---------------------------------------------------------------------------

def corner_link_pair(el_1, el_2, angle):
    """Two runs at any rotation, any slope, any level.

    The route is chosen from the geometry rather than assumed:

    1. If the two axes actually meet, both are trimmed to that point and one
       bend goes in. This is the whole job for two sloped runs that cross.
    2. If they pass each other, the shortest link between them is the common
       perpendicular. Both are trimmed to its feet and it becomes the leg -
       two bends, each in a single plane, which is what cable trays and
       rectangular ducts need.
    3. If that leg is too short to hold two fittings, the route falls back to
       running past the crossing and coming back at the set angle, which
       gives the bends room at the cost of a longer route.

    Sloped runs are handled by 2 and 3 without special-casing: the feet of the
    common perpendicular are correct whatever the pitch.
    """
    ok, message = check_pair(el_1, el_2)
    if not ok:
        return False, message

    line_1, line_2 = get_line(el_1), get_line(el_2)
    d_1 = line_1.Direction.Normalize()
    d_2 = line_2.Direction.Normalize()

    if abs(d_1.DotProduct(d_2)) > PARALLEL_DOT:
        return False, ("These run in the same direction, so there is no corner "
                       "to make. Use Riser Link instead.")

    found = closest_points(line_1, line_2)
    if found is None:
        return False, "Could not work out how these two axes relate."
    foot_1, foot_2, gap_between = found

    a_lo, a_hi = span(line_1)
    b_lo, b_hi = span(line_2)
    t_1 = param_on(line_1, foot_1)
    t_2 = param_on(line_2, foot_2)

    # keep whichever end of each element is further from the meeting point
    far_1 = a_lo if abs(a_lo - t_1) > abs(a_hi - t_1) else a_hi
    far_2 = b_lo if abs(b_lo - t_2) > abs(b_hi - t_2) else b_hi
    end_1 = point_on(line_1, far_1)
    end_2 = point_on(line_2, far_2)

    if abs(t_1 - far_1) < MIN_LEN or abs(t_2 - far_2) < MIN_LEN:
        return False, ("The meeting point falls outside these elements - there "
                       "is nothing to trim back to. Move them so their axes "
                       "cross, or lengthen them.")

    route = Route(el_1, el_2, "RevoBIM - Corner Link")
    reducer = 0.0 if route.same_size else max(profile_span(el_1),
                                              profile_span(el_2)) * 2.0

    # --- 1. the axes meet: one bend ---------------------------------------
    if gap_between < TOL_ALIGN:
        meet = XYZ((foot_1.X + foot_2.X) / 2.0, (foot_1.Y + foot_2.Y) / 2.0,
                   (foot_1.Z + foot_2.Z) / 2.0)
        ok, missing = route.build(end_1, [meet], end_2, reducer)
        if ok:
            return True, ("Trimmed to a single {0:.0f} degree bend."
                          "{1}".format(turn_between(d_1, d_2),
                                       type_note(el_1, el_2)))
        return False, failure_text(missing, el_1)

    # --- 2. the shortest link: two bends ----------------------------------
    #
    # Only ever right for a profile that can turn freely. The direct leg
    # between the two feet is vertical where both runs are level, and a
    # vertical leg has no plan direction of its own - so where the two runs
    # point different ways in plan, the turn has nowhere to happen except
    # inside one of the two bends, which would have to drop and turn at the
    # same time. A pipe elbow can do that. A cable tray or rectangular duct
    # cannot: it would have to twist along its own length.
    turn_in_plan = plan_turn_between(line_1, line_2)
    direct_is_valid = is_round(el_1) or turn_in_plan < 0.5

    if direct_is_valid:
        ok, missing = route.build(end_1, [foot_1, foot_2], end_2, reducer)
        if ok:
            return True, ("Connected on the shortest link between them - a "
                          "{0:.0f}mm leg with a bend each end.{1}".format(
                              ft2mm(gap_between), type_note(el_1, el_2)))

    # --- 3. straight, set up or down, straight, then turn -----------------
    #
    # Four straights and three bends, so the level change and the plan turn
    # are separate moves with a real straight between them. Element one runs
    # past its foot, sets up or down at the chosen angle in its own vertical
    # plane, runs a landing at the new level still in its own direction, and
    # only then turns into element two.
    length_1 = abs(t_1 - far_1)
    length_2 = abs(t_2 - far_2)
    sign_1 = 1.0 if t_1 > far_1 else -1.0

    # the set angle first, then shallower ones. A shallow angle needs more run
    # but gives a longer leg for the same rise, which is what makes a small
    # level change buildable at all.
    landing_dir = plan_direction(line_1) or d_1

    # the set angle first, then every fallback below it. All are multiples of
    # five, and a custom setting is rounded to one before it is used, so the
    # angle that ends up in the model is always something you can set out to.
    angle = round_angle(angle)
    angles = [angle] + [a for a in FALLBACK_ANGLES if a < angle - 0.01]
    best_missing = 0
    tried_any = False

    for try_angle in angles:
        run = leg_run(gap_between, try_angle)
        max_gap = min((length_1 - run) / 2.0, length_2)
        if max_gap < MIN_LEN:
            continue                    # no room to run past at this angle

        tried_any = True
        gap = min(max(profile_span(el_1) * GAP_START_FACTOR,
                      mm(GAP_START_MIN_MM)), max_gap)

        for _ in range(GAP_ATTEMPTS):
            back = point_on(line_1, t_1 - sign_1 * (run + gap))
            top = foot_2 + landing_dir.Multiply(-sign_1 * gap)
            ok, missing = route.build(end_1, [back, top, foot_2], end_2,
                                      reducer)
            if ok:
                note = ""
                if abs(try_angle - angle) > 0.01:
                    note = (" The set {0} degree angle would not make a "
                            "{1:.0f}mm level change with room for the "
                            "fittings, so {2} degrees was used "
                            "instead.".format(angle_text(angle),
                                              ft2mm(gap_between),
                                              angle_text(try_angle)))
                return True, ("Connected with a {0:.0f}mm straight, a {1} "
                              "degree set {2}, a {3:.0f}mm landing and then "
                              "the corner bend.{4}{5}".format(
                                  ft2mm(gap), angle_text(try_angle),
                                  "down" if foot_2.Z < foot_1.Z else "up",
                                  ft2mm(gap), note,
                                  type_note(el_1, el_2)))
            best_missing = missing
            new_gap = min(gap * 1.6, max_gap)
            if new_gap <= gap + mm(5.0):
                break
            gap = new_gap

    if not tried_any:
        return False, ("These are too short to make the corner. The level "
                       "change is {0:.0f}mm and there is not enough length to "
                       "run past it and come back, at any angle. Lengthen "
                       "them or move them apart.".format(ft2mm(gap_between)))

    return failure_note(best_missing, el_1, gap_between, direct_is_valid)


def failure_note(missing, el_1, gap_between, direct_was_tried):
    extra = ("The level change is {0:.0f}mm. ".format(ft2mm(gap_between)))
    if not direct_was_tried:
        extra += ("A direct leg was not an option here - the two runs point "
                  "different ways in plan and a {0} cannot drop and turn in "
                  "one bend. ".format(element_kind(el_1).lower()))
    return False, failure_text(missing, el_1, extra)


# ---------------------------------------------------------------------------
# Centreline Snap
# ---------------------------------------------------------------------------

def parallel_rotation(ref_line, tgt_line, mode):
    """Rotation that makes tgt_line parallel to ref_line, the short way."""
    mid = tgt_line.Evaluate(0.5, True)

    if mode == 'xy':
        d_ref, d_tgt = plan_direction(ref_line), plan_direction(tgt_line)
        if d_ref is None or d_tgt is None:
            return None, None
        if d_ref.DotProduct(d_tgt) < 0:
            d_ref = d_ref.Negate()
        angle = math.atan2(d_tgt.CrossProduct(d_ref).Z, d_tgt.DotProduct(d_ref))
        if abs(angle) < 1.0e-6:
            return None, None
        return angle, Line.CreateBound(mid, XYZ(mid.X, mid.Y, mid.Z + 1.0))

    d_ref = ref_line.Direction.Normalize()
    d_tgt = tgt_line.Direction.Normalize()
    if d_ref.DotProduct(d_tgt) < 0:
        d_ref = d_ref.Negate()
    cross = d_tgt.CrossProduct(d_ref)
    if cross.GetLength() < 1.0e-7:
        return None, None
    angle = math.atan2(cross.GetLength(), d_tgt.DotProduct(d_ref))
    if abs(angle) < 1.0e-6:
        return None, None
    return angle, Line.CreateBound(mid, mid.Add(cross.Normalize()))


def snap_pair(ref_el, target_el, mode):
    """Rotate target parallel to ref, then set it on ref's centreline."""
    ref_line, tgt_line = get_line(ref_el), get_line(target_el)
    if ref_line is None or tgt_line is None:
        return False, "Both picks must be straight runs (not fittings or flex)."
    if ref_el.Id == target_el.Id:
        return False, "That is the same element twice."

    turned = moved = 0.0
    trans = quiet_transaction("RevoBIM - Centreline Snap")
    try:
        if target_el.Pinned:
            target_el.Pinned = False

        if mode in ('xy', 'both'):
            angle, axis_line = parallel_rotation(ref_line, tgt_line, mode)
            if angle is not None:
                ElementTransformUtils.RotateElement(doc, target_el.Id,
                                                    axis_line, angle)
                doc.Regenerate()
                turned = math.degrees(angle)
                tgt_line = get_line(target_el)

        centreline = Line.CreateUnbound(ref_line.GetEndPoint(0),
                                        ref_line.Direction)
        mid = tgt_line.Evaluate(0.5, True)
        vector = centreline.Project(mid).XYZPoint - mid
        if mode == 'xy':
            vector = XYZ(vector.X, vector.Y, 0)
        elif mode == 'z':
            vector = XYZ(0, 0, vector.Z)

        if vector.GetLength() >= mm(0.1):
            ElementTransformUtils.MoveElement(doc, target_el.Id, vector)
            doc.Regenerate()
            moved = ft2mm(vector.GetLength())

        trans.Commit()
    except Exception as err:
        try:
            trans.RollBack()
        except Exception:
            pass
        return False, ("Nothing was changed - the element could not be moved: "
                       "{0}\nIt may be held by a connected fitting.".format(err))

    if not turned and not moved:
        return True, "Already aligned."
    parts = []
    if turned:
        parts.append("rotated {0:.1f} degrees parallel".format(abs(turned)))
    if moved:
        parts.append("moved {0:.0f}mm onto the centreline".format(moved))
    return True, " and ".join(parts).capitalize() + "."


# ---------------------------------------------------------------------------
# the pick loops the buttons call
# ---------------------------------------------------------------------------

def run_pair_loop(action, prompt_1, prompt_2, title, keep_going=True):
    """Pick pairs and run action on each. Escape ends it.

    Returns (done, problems) where problems is a list of message strings.
    """
    done = 0
    problems = []
    while True:
        el_1 = pick_element(prompt_1)
        if el_1 is None:
            break
        el_2 = pick_element(prompt_2)
        if el_2 is None:
            break

        ok, message = action(el_1, el_2)
        if ok:
            done += 1
        else:
            problems.append(message)
            alert(message, title)

        if not keep_going:
            break
    return done, problems


def report(done, problems, verb, settings):
    """Say how it went, according to the 'report' setting.

    A windowless command reports only when something needs a look by default:
    a run where everything worked says nothing at all, which is the whole
    point of driving it from a keyboard shortcut.
    """
    mode = settings.get('report', 'problems')
    if mode == 'never':
        return
    if mode == 'problems' and not problems:
        return
    if not done and not problems:
        return

    lines = ["{0} {1}.".format(verb, plural(done, "element"))]
    if problems:
        lines.append("")
        lines.append("{0} left alone:".format(plural(len(problems), "pick")))
        for message in problems[:8]:
            lines.append("  - " + message.replace("\n", " "))
        if len(problems) > 8:
            lines.append("  - and {0} more".format(len(problems) - 8))
    alert("\n".join(lines), "RevoBIM - Riser Link")


def plural(count, noun):
    return "{0} {1}{2}".format(count, noun, "" if count == 1 else "s")
