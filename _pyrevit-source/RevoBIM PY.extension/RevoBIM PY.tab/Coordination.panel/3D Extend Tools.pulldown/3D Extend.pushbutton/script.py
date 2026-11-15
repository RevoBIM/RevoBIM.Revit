# -*- coding: utf-8 -*-
"""Extends cable trays, pipes or ducts up or down onto another run.

Select the runs you want to extend - all of one category - then run the tool
and click the run you want them to reach. Each source is trimmed to the point
where the two centrelines cross in plan, and a branch is modelled with a bend
landing on the target's centreline.

Pipes and ducts get a tee where the crossing falls inside the target. If the
target stops short of the crossing it is brought out to meet the branch and
joined with a bend instead. Cable trays can be connected with no fitting.

Angles are set in the Settings button.
"""

__title__ = '3D Extend'
__author__ = 'RevoBIM PY'
__version__ = '4.1.0'

import io
import json
import math
import os

from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, SubTransaction,
    FailureProcessingResult, FailureSeverity, IFailuresPreprocessor,
    ElementTransformUtils, BuiltInParameter, ElementId
)
from Autodesk.Revit.DB.Electrical import CableTray
from Autodesk.Revit.DB.Plumbing import Pipe, PlumbingUtils
from Autodesk.Revit.DB.Mechanical import Duct, MechanicalUtils
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

from System.Collections.Generic import List

from pyrevit import forms, script


# ------------------------------------------------------------------ SETTINGS
# Angles and the tray connect option are set in the Settings button next to
# this one in the dropdown. These are the fallbacks if nothing is saved yet.
DEFAULT_TRAY_ANGLE = 90.0
DEFAULT_TRAY_CONNECT = True
DEFAULT_PIPE_ANGLE = 90.0
DEFAULT_DUCT_ANGLE = 90.0
DEFAULT_DUCT_FITTING = 'tap'   # 'tap' for a shoe, 'tee' to break and tee
DEFAULT_SHOW_REPORT = False

SETTINGS_FILE = os.path.join(os.getenv('APPDATA') or '', 'RevoBIM PY',
                             '3d_extend_settings.json')

# Stop this far short of the target centreline. 0.0 = dead on it.
CLEARANCE_MM = 0.0

# Keep a vertical tray branch's width facing the same way as the horizontal run.
ALIGN_SECTION = True

# Set to 90.0 if a vertical tray branch ever comes in flipped.
EXTRA_ROTATION_DEG = 0.0

# How close a target connector has to be before a tray branch will be
# connected into it digitally.
CONNECT_SNAP_MM = 15.0

# How far past its own end the source may be stretched to reach a node.
MAX_SOURCE_EXTEND_MM = 3000.0

# Whether the tool reports when it finishes is set in the Settings window.
# ---------------------------------------------------------------------------

MM = 304.8          # feet -> mm
TOL = 0.0016        # ~0.5mm in feet

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
logger = script.get_logger()

def load_settings():
    """Read the values saved by the 3D Extend Settings button.

    Settings live in %APPDATA%\\RevoBIM PY\\3d_extend_settings.json so they
    survive pyRevit reloads and are shared by both buttons.
    """
    data = {}
    try:
        if os.path.isfile(SETTINGS_FILE):
            handle = io.open(SETTINGS_FILE, 'r', encoding='utf-8')
            try:
                data = json.loads(handle.read())
            finally:
                handle.close()
    except Exception:
        data = {}

    def clamp(value, fallback):
        try:
            number = float(value)
        except Exception:
            return fallback
        return min(90.0, max(5.0, number))

    return (clamp(data.get('tray_angle', DEFAULT_TRAY_ANGLE),
                  DEFAULT_TRAY_ANGLE),
            bool(data.get('tray_connect', DEFAULT_TRAY_CONNECT)),
            clamp(data.get('pipe_angle', DEFAULT_PIPE_ANGLE),
                  DEFAULT_PIPE_ANGLE),
            clamp(data.get('duct_angle', DEFAULT_DUCT_ANGLE),
                  DEFAULT_DUCT_ANGLE),
            ('tee' if data.get('duct_fitting') == 'tee'
             else DEFAULT_DUCT_FITTING),
            bool(data.get('show_report', DEFAULT_SHOW_REPORT)))


# ---------------------------------------------------------------- utilities
class CategoryFilter(ISelectionFilter):
    """Restricts picking to one class, so the target matches the sources."""
    def __init__(self, wanted):
        self.wanted = wanted

    def AllowElement(self, elem):
        return isinstance(elem, self.wanted)

    def AllowReference(self, ref, point):
        return False


class SwallowWarnings(IFailuresPreprocessor):
    """Stops Revit throwing warning dialogs mid-run."""
    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return FailureProcessingResult.Continue


def get_param(elem, bip_names, lookup_names):
    for name in bip_names:
        bip = getattr(BuiltInParameter, name, None)
        if bip is not None:
            try:
                p = elem.get_Parameter(bip)
            except Exception:
                p = None
            if p is not None:
                return p
    for name in lookup_names:
        p = elem.LookupParameter(name)
        if p is not None:
            return p
    return None


P_WIDTH = (['RBS_CABLETRAY_WIDTH_PARAM'], ['Width'])
P_HEIGHT = (['RBS_CABLETRAY_HEIGHT_PARAM'], ['Height'])
P_BEND = (['RBS_CABLETRAY_BENDRADIUS_PARAM',
           'RBS_CURVE_BEND_RADIUS_PARAM'], ['Bend Radius'])
P_SERVICE = (['RBS_CTC_SERVICE_TYPE'], ['Service Type'])
P_WORKSET = (['ELEM_PARTITION_PARAM'], [])
P_DIAMETER = (['RBS_PIPE_DIAMETER_PARAM'], ['Diameter'])
P_PIPE_SYSTEM = (['RBS_PIPING_SYSTEM_TYPE_PARAM'], ['System Type'])
P_DUCT_WIDTH = (['RBS_CURVE_WIDTH_PARAM'], ['Width'])
P_DUCT_HEIGHT = (['RBS_CURVE_HEIGHT_PARAM'], ['Height'])
P_DUCT_DIAMETER = (['RBS_CURVE_DIAMETER_PARAM'], ['Diameter'])
P_DUCT_SYSTEM = (['RBS_DUCT_SYSTEM_TYPE_PARAM'], ['System Type'])


def size_of(elem):
    """Rough cross section size, used to work out how much room a bend needs."""
    if isinstance(elem, CableTray):
        return read_double(elem, P_WIDTH, 0.0)
    if isinstance(elem, Duct):
        width = read_double(elem, P_DUCT_WIDTH, 0.0)
        return width if width > 0.0 else read_double(elem, P_DUCT_DIAMETER, 0.0)
    return read_double(elem, P_DIAMETER, 0.0)


def system_type_id(elem, spec):
    param = get_param(elem, spec[0], spec[1])
    if param is not None:
        try:
            return param.AsElementId()
        except Exception:
            pass
    return ElementId.InvalidElementId


def break_curve(elem, point):
    """Split a pipe or duct at a point, returning the new element's id."""
    if isinstance(elem, Duct):
        return MechanicalUtils.BreakCurve(doc, elem.Id, point)
    return PlumbingUtils.BreakCurve(doc, elem.Id, point)


def read_double(elem, spec, default=0.0):
    p = get_param(elem, spec[0], spec[1])
    if p is not None and p.HasValue:
        try:
            return p.AsDouble()
        except Exception:
            return default
    return default


def read_string(elem, spec):
    p = get_param(elem, spec[0], spec[1])
    if p is not None and p.HasValue:
        try:
            return p.AsString()
        except Exception:
            return None
    return None


def write_double(elem, spec, value):
    p = get_param(elem, spec[0], spec[1])
    if p is not None and not p.IsReadOnly:
        try:
            p.Set(value)
        except Exception:
            pass


def write_string(elem, spec, value):
    if value is None:
        return
    p = get_param(elem, spec[0], spec[1])
    if p is not None and not p.IsReadOnly:
        try:
            p.Set(value)
        except Exception:
            pass


def copy_workset(source, target):
    sp = get_param(source, P_WORKSET[0], P_WORKSET[1])
    tp = get_param(target, P_WORKSET[0], P_WORKSET[1])
    if sp is not None and tp is not None and not tp.IsReadOnly:
        try:
            tp.Set(sp.AsInteger())
        except Exception:
            pass


def curve_of(elem):
    if elem is None:
        return None
    loc = elem.Location
    if loc is None or not hasattr(loc, 'Curve'):
        return None
    return loc.Curve


def connector_at(elem, point, limit=None):
    try:
        cm = elem.ConnectorManager
    except Exception:
        return None
    if cm is None:
        return None
    best = None
    best_dist = 1.0e9
    for con in cm.Connectors:
        try:
            d = con.Origin.DistanceTo(point)
        except Exception:
            continue
        if d < best_dist:
            best_dist = d
            best = con
    if limit is not None and best_dist > limit:
        return None
    return best


def plan_intersection(c_src, c_tgt):
    """Where the two centrelines cross in plan.

    Returns (x, y, t_src, s_tgt) as fractions along each curve, which may sit
    outside 0-1. None if the two runs are parallel in plan.
    """
    a0 = c_src.GetEndPoint(0)
    a1 = c_src.GetEndPoint(1)
    b0 = c_tgt.GetEndPoint(0)
    b1 = c_tgt.GetEndPoint(1)

    dax = a1.X - a0.X
    day = a1.Y - a0.Y
    dbx = b1.X - b0.X
    dby = b1.Y - b0.Y

    denom = (dax * dby) - (day * dbx)
    if abs(denom) < 1.0e-9:
        return None

    wx = b0.X - a0.X
    wy = b0.Y - a0.Y

    t_src = ((wx * dby) - (wy * dbx)) / denom
    s_tgt = ((wx * day) - (wy * dax)) / denom

    return (a0.X + (t_src * dax), a0.Y + (t_src * day), t_src, s_tgt)


def align_vertical_section(branch, want_dir, point):
    con = connector_at(branch, point)
    if con is None:
        return
    try:
        basis = con.CoordinateSystem.BasisX
    except Exception:
        return

    flat = XYZ(basis.X, basis.Y, 0.0)
    if flat.GetLength() < 1.0e-6:
        return
    flat = flat.Normalize()

    angle = flat.AngleOnPlaneTo(want_dir, XYZ.BasisZ)
    while angle > math.pi / 2.0:
        angle -= math.pi
    while angle < -math.pi / 2.0:
        angle += math.pi

    angle += math.radians(EXTRA_ROTATION_DEG)

    if abs(angle) < 1.0e-6:
        return

    axis = Line.CreateBound(point, XYZ(point.X, point.Y, point.Z + 1.0))
    try:
        ElementTransformUtils.RotateElement(doc, branch.Id, axis, angle)
    except Exception:
        pass


# ------------------------------------------------------------ branch making
def make_branch(source, start, end):
    """Create the sloped or vertical run, matching the source element."""
    level_id = ElementId.InvalidElementId
    try:
        if source.ReferenceLevel is not None:
            level_id = source.ReferenceLevel.Id
    except Exception:
        pass
    if level_id == ElementId.InvalidElementId:
        try:
            level_id = doc.ActiveView.GenLevel.Id
        except Exception:
            pass

    if isinstance(source, CableTray):
        branch = CableTray.Create(doc, source.GetTypeId(), start, end, level_id)
        doc.Regenerate()
        width = read_double(source, P_WIDTH, 0.0)
        height = read_double(source, P_HEIGHT, 0.0)
        bend = read_double(source, P_BEND, 0.0)
        if width > 0.0:
            write_double(branch, P_WIDTH, width)
        if height > 0.0:
            write_double(branch, P_HEIGHT, height)
        if bend > 0.0:
            write_double(branch, P_BEND, bend)
        write_string(branch, P_SERVICE, read_string(source, P_SERVICE))
    elif isinstance(source, Duct):
        branch = Duct.Create(doc, system_type_id(source, P_DUCT_SYSTEM),
                             source.GetTypeId(), level_id, start, end)
        doc.Regenerate()
        width = read_double(source, P_DUCT_WIDTH, 0.0)
        height = read_double(source, P_DUCT_HEIGHT, 0.0)
        dia = read_double(source, P_DUCT_DIAMETER, 0.0)
        if width > 0.0 and height > 0.0:
            write_double(branch, P_DUCT_WIDTH, width)
            write_double(branch, P_DUCT_HEIGHT, height)
        elif dia > 0.0:
            write_double(branch, P_DUCT_DIAMETER, dia)
    else:
        branch = Pipe.Create(doc, system_type_id(source, P_PIPE_SYSTEM),
                             source.GetTypeId(), level_id, start, end)
        doc.Regenerate()
        dia = read_double(source, P_DIAMETER, 0.0)
        if dia > 0.0:
            write_double(branch, P_DIAMETER, dia)

    copy_workset(source, branch)
    doc.Regenerate()
    return branch


def segment_holding(segments, point):
    """Which of the target's pipe segments actually contains this point.

    Breaking a pipe leaves two elements behind, so with several sources the
    later crossing points may sit on a piece created by an earlier tee. This
    finds the right piece each time.
    """
    best = None
    best_dist = 1.0e9
    for seg in segments:
        curve = curve_of(seg)
        if curve is None:
            continue
        try:
            result = curve.Project(point)
        except Exception:
            continue
        if result is None:
            continue
        # Project returns the nearest point ON the bounded segment, so a
        # distance near zero means the point genuinely falls within it
        if result.Distance < best_dist:
            best_dist = result.Distance
            best = seg
    if best is None or best_dist > (10.0 / MM):
        return None
    return best


def place_tee(segments, branch, point, notes):
    """Break the right target segment and drop a tee in.

    Works for pipes and ducts. Adds the newly created half to `segments` so
    later branches can find it.
    """
    host = segment_holding(segments, point)
    if host is None:
        notes.append('no target segment found at the crossing point - an '
                     'earlier tee may have consumed it')
        return False

    host_curve = curve_of(host)
    if host_curve is not None:
        gap = min(host_curve.GetEndPoint(0).DistanceTo(point),
                  host_curve.GetEndPoint(1).DistanceTo(point))
        if gap < TOL:
            notes.append('the crossing point lands on the very end of the '
                         'target, too close to break for a tee')
            return False

    try:
        new_id = break_curve(host, point)
    except Exception as err:
        notes.append('could not break the target for a tee ({0})'.format(err))
        return False

    doc.Regenerate()
    other_half = doc.GetElement(new_id)
    if other_half is None:
        notes.append('breaking the target did not produce a second element')
        return False

    c_main_a = connector_at(host, point)
    c_main_b = connector_at(other_half, point)
    c_branch = connector_at(branch, point)

    if c_main_a is None or c_main_b is None or c_branch is None:
        notes.append('tee not placed, connectors not found at the break')
        return False

    try:
        if c_main_a.IsConnectedTo(c_main_b):
            c_main_a.DisconnectFrom(c_main_b)
    except Exception:
        pass

    try:
        doc.Create.NewTeeFitting(c_main_a, c_main_b, c_branch)
        doc.Regenerate()
    except Exception as err:
        notes.append('tee not placed ({0})'.format(err))
        return False

    segments.append(other_half)
    return True


def place_takeoff(segments, target, branch, point, notes):
    """Tap the branch into the main duct with a shoe.

    NewTakeoffFitting pulls the fitting from the duct type's Tap routing
    preference, which is where shoes and other takeoffs live. The main duct is
    left whole - nothing is broken - so several branches can tap the same run
    without getting in each other's way.
    """
    host = segment_holding(segments, point) or target

    con = connector_at(branch, point)
    if con is None:
        notes.append('branch connector not found for the shoe')
        return False
    try:
        if con.IsConnected:
            notes.append('branch end is already connected, no shoe placed')
            return False
    except Exception:
        pass

    try:
        doc.Create.NewTakeoffFitting(con, host)
        doc.Regenerate()
        return True
    except Exception as err:
        notes.append('shoe not placed - check the duct type has a tap in its '
                     'routing preferences ({0})'.format(err))
        return False


def free_connector(elem, near_point):
    """The unconnected end of `elem` nearest a point - its open node."""
    best = None
    best_dist = 1.0e9
    try:
        for con in elem.ConnectorManager.Connectors:
            try:
                if con.IsConnected:
                    continue
                distance = con.Origin.DistanceTo(near_point)
            except Exception:
                continue
            if distance < best_dist:
                best_dist = distance
                best = con
    except Exception:
        return None
    return best


def bend_for_node(other, run_dir, plan_len, z_src, gradient, node, angle_deg):
    """Where on the source the bend goes so the branch reaches `node` at the
    angle asked for.

    Walking out along the source from the end being kept, the branch to the
    node gets steeper the closer the bend sits to the node in plan. That makes
    it a plain bisection between the far end and the point of closest approach.

    Returns (point, reason). Point is None when the angle cannot be met.
    """
    reach = plan_len + (MAX_SOURCE_EXTEND_MM / MM)

    def point_at(t):
        return XYZ(other.X - (run_dir.X * t),
                   other.Y - (run_dir.Y * t),
                   z_src + (gradient * (plan_len - t)))

    def angle_at(t):
        spot = point_at(t)
        flat = math.sqrt(((spot.X - node.X) ** 2) + ((spot.Y - node.Y) ** 2))
        drop = abs(spot.Z - node.Z)
        if flat < 1.0e-9:
            return 90.0
        return math.degrees(math.atan2(drop, flat))

    # plan distance along the source at which it passes closest to the node
    closest = ((node.X - other.X) * -run_dir.X) + \
              ((node.Y - other.Y) * -run_dir.Y)
    closest = max(0.0, min(reach, closest))

    low, high = 0.0, closest
    if angle_at(high) < angle_deg - 0.01:
        return None, ('the node is too far out for a {0:g} deg branch - the '
                      'steepest this source can reach it at is {1:.0f} deg'
                      .format(angle_deg, angle_at(high)))
    if angle_at(low) > angle_deg + 0.01:
        return None, ('the node sits too close under the source for a {0:g} '
                      'deg branch - it would need at least {1:.0f} deg'
                      .format(angle_deg, angle_at(low)))

    for _ in range(80):
        mid = (low + high) / 2.0
        if angle_at(mid) < angle_deg:
            low = mid
        else:
            high = mid

    return point_at((low + high) / 2.0), None


def join_at_node(target, branch, point, notes):
    """Join the branch onto the target's open end.

    An elbow if the two arrive at an angle to each other, a straight
    connection if they happen to line up.
    """
    target_con = connector_at(target, point, limit=(50.0 / MM))
    branch_con = connector_at(branch, point)
    if target_con is None or branch_con is None:
        notes.append('could not find the connectors at the node')
        return False

    try:
        doc.Create.NewElbowFitting(target_con, branch_con)
        doc.Regenerate()
        return True
    except Exception as elbow_err:
        pass

    try:
        branch_con.ConnectTo(target_con)
        doc.Regenerate()
        return True
    except Exception as err:
        notes.append('could not join at the node - no bend placed and Revit '
                     'refused a straight connection ({0})'.format(err))
        return False


def connect_tray(segments, target, branch, point, notes):
    """Join a tray branch onto the target run, leaving the target whole.

    The main tray is never cut. Three things are tried in order:

      1. the branch lands on a free end of the target - connect the two
         directly;
      2. mid-run - tap into the target with a takeoff from the tray type's
         routing preferences, which leaves the main tray intact;
      3. neither works - trim the branch so it stops just short of the main
         tray and leave it unconnected, which is what you would do by hand.
    """
    snap = CONNECT_SNAP_MM / MM

    if connector_at(branch, point) is None:
        notes.append('branch connector not found')
        return False

    host = segment_holding(segments, point) or target

    # --- 1. landing on an open end ---------------------------------------
    end_con = None
    end_dist = 1.0e9
    try:
        for con in host.ConnectorManager.Connectors:
            try:
                if con.IsConnected:
                    continue
                distance = con.Origin.DistanceTo(point)
            except Exception:
                continue
            if distance < end_dist:
                end_dist = distance
                end_con = con
    except Exception:
        pass

    if end_con is not None and end_dist <= snap:
        try:
            line = branch.Location.Curve
            far = line.GetEndPoint(0)
            if far.DistanceTo(point) < line.GetEndPoint(1).DistanceTo(point):
                far = line.GetEndPoint(1)
            branch.Location.Curve = Line.CreateBound(far, end_con.Origin)
            doc.Regenerate()
            connector_at(branch, end_con.Origin).ConnectTo(end_con)
            doc.Regenerate()
            return True
        except Exception as err:
            notes.append('connection at the tray end refused by Revit '
                         '({0})'.format(err))
            return False

    # --- 2. tap into the run, main tray left whole ------------------------
    try:
        doc.Create.NewTakeoffFitting(connector_at(branch, point), host)
        doc.Regenerate()
        return True
    except Exception:
        pass

    # --- 3. stop the branch just short of the main tray -------------------
    trimmed = trim_clear_of(host, branch, point, notes)
    if trimmed:
        notes.append('branch could not be connected without cutting the main '
                     'tray, so it was run up close to it and left loose - add '
                     'a tee or takeoff to the tray type to have it connect')
    return False


def trim_clear_of(host, branch, point, notes):
    """Pull the branch back so it stops at the face of the main tray rather
    than running through it."""
    clear = 0.0
    height = read_double(host, P_HEIGHT, 0.0)
    if height > 0.0:
        clear = height / 2.0

    if clear <= 0.0:
        return True

    try:
        line = branch.Location.Curve
        a = line.GetEndPoint(0)
        b = line.GetEndPoint(1)
        far = a if a.DistanceTo(point) > b.DistanceTo(point) else b

        direction = point - far
        length = direction.GetLength()
        if length <= clear + TOL:
            return True
        direction = direction.Normalize()

        stop = XYZ(point.X - (direction.X * clear),
                   point.Y - (direction.Y * clear),
                   point.Z - (direction.Z * clear))
        branch.Location.Curve = Line.CreateBound(far, stop)
        doc.Regenerate()
        return True
    except Exception as err:
        notes.append('could not trim the branch clear of the main tray '
                     '({0})'.format(err))
        return False


# ------------------------------------------------------------------- worker
def build_extend(source, target, target_curve, segments,
                 angle_deg, tray_connect, duct_tap):
    """Run `source` onto the target. `target_curve` is the target's ORIGINAL
    centreline, captured before any tees were placed, so the geometry stays
    consistent across a whole selection. Returns (ok, message)."""

    if source is None:
        return False, 'Missing element.'
    if source.Id == target.Id:
        return False, 'Source and target are the same element.'

    is_tray = isinstance(source, CableTray)
    is_duct = isinstance(source, Duct)

    c_src = curve_of(source)
    if c_src is None or target_curve is None:
        return False, 'One of the elements has no location line.'

    hit = plan_intersection(c_src, target_curve)
    if hit is None:
        return False, 'Runs parallel to the target in plan, no crossing point.'
    ix, iy, t_src, s_tgt = hit

    p0 = c_src.GetEndPoint(0)
    p1 = c_src.GetEndPoint(1)
    b0 = target_curve.GetEndPoint(0)
    b1 = target_curve.GetEndPoint(1)

    # keep the far end, move the near end towards the crossing
    if t_src <= 0.5:
        pick, other = p0, p1
    else:
        pick, other = p1, p0

    z_src = p0.Z + (t_src * (p1.Z - p0.Z))
    z_tgt = b0.Z + (s_tgt * (b1.Z - b0.Z))

    # crossing point lands beyond the ends of the target
    target_short = s_tgt < -0.001 or s_tgt > 1.001

    clearance = CLEARANCE_MM / MM

    # which way the source runs, and its own gradient going back towards the
    # end that is being kept
    plan_run = XYZ(other.X - ix, other.Y - iy, 0.0)
    plan_len = plan_run.GetLength()
    if plan_len < 1.0e-6:
        return False, 'Source element has no length in plan.'
    run_dir = plan_run.Normalize()
    gradient = (other.Z - z_src) / plan_len

    extended = 0.0

    if target_short:
        # The crossing sits off the end of the target. Dragging the target out
        # to meet it runs away badly once either run has a fall, so the branch
        # goes to the target's nearest open end instead and the bend is placed
        # wherever on the source gives the angle asked for.
        node = free_connector(target, pick)
        if node is None:
            return False, ('the crossing point is off the end of the target, '
                           'and the target has no free end to connect to')
        landing = node.Origin
        bend_point, why = bend_for_node(other, run_dir, plan_len, z_src,
                                        gradient, landing, angle_deg)
        if bend_point is None:
            return False, why
        reached = math.sqrt(((bend_point.X - other.X) ** 2) +
                            ((bend_point.Y - other.Y) ** 2))
        extended = max(0.0, reached - plan_len)

        # how far the node sits off to the side of the source's own line. Any
        # real offset means the branch leaves at a compound angle, which most
        # fitting families will not take.
        skew = abs(((landing.X - other.X) * -run_dir.Y) +
                   ((landing.Y - other.Y) * run_dir.X))
    else:
        skew = 0.0
        if z_tgt > z_src + TOL:
            z_end = z_tgt - clearance
        elif z_tgt < z_src - TOL:
            z_end = z_tgt + clearance
        else:
            return False, 'Both elements are at the same height.'
        landing = XYZ(ix, iy, z_end)

        # For anything shallower than vertical the bend sits back along the
        # source. On a level source that is just drop / tan(angle), but a
        # sloped source climbs or falls as you go back, which changes the drop
        # the branch has to make - so the two are solved together.
        if angle_deg >= 89.999:
            setback = 0.0
        else:
            tan_a = math.tan(math.radians(angle_deg))
            drop = abs(z_end - z_src)
            denom = (tan_a - gradient) if z_end < z_src else (tan_a + gradient)
            if denom <= 1.0e-9:
                return False, ('the source slopes too steeply for a {0:g} deg '
                               'branch - raise the angle in '
                               'Settings.'.format(angle_deg))
            setback = drop / denom

        # a shallow angle, or a source already falling the same way, can push
        # the bend past the far end and fold the run back on itself
        if setback >= plan_len:
            return False, ('the source is not long enough for a {0:g} deg '
                           'branch - the bend would sit {1:.0f}mm past its '
                           'far end. Use a steeper '
                           'angle.'.format(angle_deg,
                                           (setback - plan_len) * MM))

        bend_point = XYZ(ix + (run_dir.X * setback),
                         iy + (run_dir.Y * setback),
                         z_src + (gradient * setback))

    rise = abs(landing.Z - bend_point.Z)
    direction = 'down' if landing.Z < bend_point.Z else 'up'
    if rise < TOL:
        return False, 'No vertical distance between the elements.'

    # --- sizes and the room the bend needs -------------------------------
    size = size_of(source)
    if is_tray:
        bend_r = read_double(source, P_BEND, 0.0)
        if bend_r <= 0.0:
            bend_r = size if size > 0.0 else (100.0 / MM)
    else:
        bend_r = size if size > 0.0 else (50.0 / MM)
    needed = bend_r + (size / 2.0)

    notes = []
    if skew > (5.0 / MM):
        notes.append('the node sits {0:.0f}mm off the side of the source, so '
                     'the bend is a compound angle and may not place'
                     .format(skew * MM))

    branch_len = bend_point.DistanceTo(landing)
    if branch_len < needed:
        notes.append('the branch is only {0:.0f}mm long, the bend needs about '
                     '{1:.0f}mm'.format(branch_len * MM, needed * MM))

    kept_length = other.DistanceTo(bend_point)
    if kept_length < needed:
        notes.append('source would be only {0:.0f}mm long at the bend, which '
                     'needs about {1:.0f}mm'.format(kept_length * MM,
                                                    needed * MM))

    # --- is the end we need to move free? ---------------------------------
    src_con = connector_at(source, pick)
    if src_con is None:
        return False, 'No connector found on the source element.'
    try:
        if src_con.IsConnected:
            return False, 'The end that needs moving is already connected.'
    except Exception:
        pass

    run = XYZ(other.X - bend_point.X, other.Y - bend_point.Y, 0.0)
    if run.GetLength() < 1.0e-6:
        want_dir = XYZ.BasisY
    else:
        want_dir = run.Normalize().CrossProduct(XYZ.BasisZ).Normalize()

    # the turn the elbow actually has to make. On a level source running into a
    # vertical branch that is 90, but any slope on the source shifts it, and
    # the fitting family has to be able to take that angle.
    bend_angle = 90.0
    try:
        incoming = (bend_point - other).Normalize()
        outgoing = (landing - bend_point).Normalize()
        bend_angle = math.degrees(incoming.AngleTo(outgoing))
    except Exception:
        pass

    if abs(gradient) > 1.0e-6:
        notes_slope = ('source slopes {0:.2f} in 1, so the bend works out at '
                       '{1:.1f} deg'.format(abs(gradient), bend_angle))
    else:
        notes_slope = None

    # --- build ------------------------------------------------------------
    bend_ok = False
    joined = False
    t = Transaction(doc, '3D Extend')
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(SwallowWarnings())
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        if pick.DistanceTo(bend_point) > TOL:
            try:
                source.Location.Curve = Line.CreateBound(other, bend_point)
                doc.Regenerate()
            except Exception as trim_err:
                t.RollBack()
                return False, ('Could not trim the source to the bend point: '
                               '{0}'.format(trim_err))

        branch = make_branch(source, bend_point, landing)

        if ALIGN_SECTION and is_tray and angle_deg >= 89.999:
            align_vertical_section(branch, want_dir, bend_point)
            doc.Regenerate()

        # the bend, in its own sub transaction so a failure here does not
        # throw away the branch
        st = SubTransaction(doc)
        st.Start()
        try:
            a = connector_at(source, bend_point)
            b = connector_at(branch, bend_point)
            if a is not None and b is not None:
                doc.Create.NewElbowFitting(a, b)
                doc.Regenerate()
                bend_ok = True
                st.Commit()
            else:
                st.RollBack()
                notes.append('bend not placed, connectors not found')
        except Exception as bend_err:
            st.RollBack()
            notes.append('bend not placed ({0})'.format(bend_err))

        # the landing end
        st2 = SubTransaction(doc)
        st2.Start()
        keep = False
        try:
            if target_short:
                if not is_tray or tray_connect:
                    joined = join_at_node(target, branch, landing, notes)
            elif is_duct and duct_tap:
                joined = place_takeoff(segments, target, branch, landing,
                                       notes)
            elif not is_tray:
                joined = place_tee(segments, branch, landing, notes)
            elif tray_connect:
                joined = connect_tray(segments, target, branch, landing,
                                      notes)
                # connect_tray trims the branch clear of the main tray when it
                # cannot join, and that trim is wanted either way, so its work
                # is kept rather than rolled back
                keep = True
            if joined or keep:
                st2.Commit()
            else:
                st2.RollBack()
        except Exception as join_err:
            st2.RollBack()
            notes.append('connection not made ({0})'.format(join_err))

        t.Commit()
    except Exception as err:
        try:
            t.RollBack()
        except Exception:
            pass
        return False, 'Could not model the branch: {0}'.format(err)

    if extended > TOL:
        notes.append('source stretched {0:.0f}mm past its own end to reach '
                     'the node'.format(extended * MM))

    if bend_ok and not notes:
        return True, 'Ran {0} {1:.0f}mm at {2:.0f} deg.'.format(
            direction, rise * MM, angle_deg)

    msg = 'Ran {0} {1:.0f}mm at {2:.0f} deg'.format(
        direction, rise * MM, angle_deg)
    if notes_slope and not bend_ok:
        notes.append(notes_slope)
    if notes:
        msg += ' - ' + '; '.join(notes)
    return False, msg


def safe_build(source, target, target_curve, segments,
               angle_deg, tray_connect, duct_tap):
    try:
        return build_extend(source, target, target_curve, segments,
                            angle_deg, tray_connect, duct_tap)
    except Exception as err:
        return False, 'Unexpected error: {0}'.format(err)


# ---------------------------------------------------------------- selection
def sort_selection():
    """Split the current selection into trays, pipes and ducts."""
    groups = [('cable tray', CableTray, []),
              ('pipe', Pipe, []),
              ('duct', Duct, [])]
    try:
        ids = uidoc.Selection.GetElementIds()
    except Exception:
        return groups
    for eid in ids:
        el = doc.GetElement(eid)
        for _, kind, bucket in groups:
            if isinstance(el, kind):
                bucket.append(el)
                break
    return groups


def clear_selection():
    try:
        uidoc.Selection.SetElementIds(List[ElementId]())
    except Exception:
        pass


def order_along(sources, target_curve):
    """Work along the target so the tees go in in a predictable order."""
    origin = target_curve.GetEndPoint(0)
    direction = target_curve.GetEndPoint(1) - origin

    def key(elem):
        curve = curve_of(elem)
        if curve is None:
            return 0.0
        mid = (curve.GetEndPoint(0) + curve.GetEndPoint(1)) / 2.0
        return (mid - origin).DotProduct(direction)

    try:
        return sorted(sources, key=key)
    except Exception:
        return sources


# --------------------------------------------------------------------- main
def main():
    (tray_angle, tray_connect, pipe_angle, duct_angle,
     duct_fitting, show_report) = load_settings()

    groups = sort_selection()
    filled = [g for g in groups if g[2]]

    if len(filled) > 1:
        forms.alert(
            '{0} are all selected.\n\n'
            'Select one category to work with, then run 3D Extend '
            'again.'.format(' and '.join(g[0] + 's' for g in filled)),
            title='3D Extend  v{0}'.format(__version__),
            warn_icon=True)
        return

    if not filled:
        forms.alert(
            'Nothing to extend.\n\n'
            'Select the cable trays, pipes or ducts you want to extend, then '
            'run 3D Extend and pick the run you want them to reach.',
            title='3D Extend  v{0}'.format(__version__),
            warn_icon=True)
        return

    label, wanted, sources = filled[0]
    angle_by_kind = {CableTray: tray_angle, Pipe: pipe_angle,
                     Duct: duct_angle}

    clear_selection()
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, CategoryFilter(wanted),
            '{0} {1}(s) selected - now pick the {1} to extend them '
            'onto.'.format(len(sources), label))
        target = doc.GetElement(ref.ElementId)
    except OperationCanceledException:
        return
    except Exception:
        return

    # Capture the target's centreline BEFORE anything is broken. Each tee
    # splits the target in two, so without this the second and later sources
    # would be measured against a pipe that had already been shortened.
    original = curve_of(target)
    if original is None:
        return
    target_curve = Line.CreateBound(original.GetEndPoint(0),
                                    original.GetEndPoint(1))

    # Every piece the target gets broken into, so each source can find the
    # piece its own crossing point falls on and get its own tee.
    segments = [target]

    angle_deg = angle_by_kind.get(wanted, 90.0)
    duct_tap = duct_fitting != 'tee'

    log = []
    made = 0
    for src in order_along(sources, target_curve):
        ok, message = safe_build(src, target, target_curve, segments,
                                 angle_deg, tray_connect, duct_tap)
        if ok:
            made += 1
        else:
            log.append('Id {0}: {1}'.format(src.Id.IntegerValue, message))

    clear_selection()

    # Nothing is reported on completion. Anything skipped goes quietly to the
    # pyRevit log, so no output window or dialog appears when the tool ends.
    logger.debug('3D Extend: settings file %s', SETTINGS_FILE)
    logger.debug('3D Extend: %s branch(es) modelled at %s deg, %s skipped.',
                 made, angle_deg, len(log))
    for entry in log:
        logger.debug('3D Extend: %s', entry)

    if show_report:
        td = TaskDialog('RevoBIM PY - 3D Extend  v{0}'.format(__version__))
        td.MainInstruction = ('{0} modelled at {1:g} deg, {2} needing a '
                              'look.'.format(made, angle_deg, len(log)))
        body = ['Settings read from:\n{0}'.format(SETTINGS_FILE)]
        if log:
            body.extend(log[:12])
        td.MainContent = '\n\n'.join(body)
        td.Show()


if __name__ == '__main__':
    main()
