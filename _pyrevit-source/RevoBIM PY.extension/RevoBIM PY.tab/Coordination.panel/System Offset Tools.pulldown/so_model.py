# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - reading and rewriting the model
#
# Everything that touches Revit geometry lives here. The
# arithmetic it leans on is in so_core, which is bench
# testable on its own.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

import math

from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, TransactionGroup,
    ElementTransformUtils, BuiltInParameter, IFailuresPreprocessor,
    FailureProcessingResult, ConnectorType,
)

import so_core
from so_core import (
    mm_to_ft, ft_to_mm, eid_value, to_text, as_float,
    MIN_SEGMENT_MM, CONN_TOL_MM, PARALLEL_TOL,
)  # noqa: F401


# ---------------------------------------------------------
# Categories the tool will work on
#
# BuiltInCategory members are looked up late, inside a
# function, never at import time - one less thing that can
# die before the tool runs.
# ---------------------------------------------------------

# The four the tool works on, and only these four. Flex pipe
# and flex duct are deliberately out: they have no straight
# centreline to break and offset.
KIND_BY_CATEGORY = (
    ('OST_PipeCurves', u'pipe'),
    ('OST_DuctCurves', u'duct'),
    ('OST_CableTray', u'tray'),
    ('OST_Conduit', u'conduit'),
)


_KIND_BY_ID = {}


# Revit shortens the two pieces either side of a bend to make
# room for the fitting, so each elbow needs the model caught up
# before the next one is measured.
#
# v4.1.0 turned this off for speed, on the reasoning that every
# connector is re-fetched live and the ends the previous elbow
# touched are not the ones the next one measures. That was
# wrong. Re-fetching a connector does not help when the model
# has not been regenerated: the second bend of every offset
# read the piece as it was BEFORE the first elbow shortened it,
# and Revit answered with "the angle between them is too small
# or too large". Two of the four bends took a fitting and two
# did not, every single time.
#
# The cost is three regenerates per offset. Correctness wins.
REGEN_BETWEEN_BENDS = True

# The two things this toolset does with the same two clicks.
#
#   jog    out and back  - the run rejoins its own line, four
#                          bends, and nothing is left loose
#   break  out and stop  - the run is cut at the second click
#                          and steps onto a new line, two
#                          bends, and what lies beyond is left
#                          where it was
#
# Only the turns that head back ALONG the run eat into it, so a
# break has twice the room a jog does at the same angle.
MODE_JOG = u'jog'
MODE_BREAK = u'break'

BENDS_ALONG_RUN = {MODE_JOG: 2, MODE_BREAK: 1}
LABELS = {MODE_JOG: u'RevoBIM System Offset',
          MODE_BREAK: u'RevoBIM Offset Break'}


# A record carries two lists, and the difference decides
# whether the user ever sees a window.
#
#   notes     what happened, for the record. "Broken by
#             BreakCurve", "Copied BGL_Service Type". A clean
#             offset produces several and must stay silent.
#   problems  what did not go the way it should. A missing
#             fitting, a bend that would not take one, a
#             refusal. These are the only thing worth
#             interrupting somebody for.
#
# Collapsing the two is what made the tool pop a window after
# every single offset.

def note(record, text):
    record.setdefault('notes', []).append(text)


def problem(record, text):
    record.setdefault('problems', []).append(text)


def _kind_map():
    """Category id -> kind, built once and kept.

    kind_of runs from ISelectionFilter.AllowElement, which
    Revit calls for every element the cursor passes over. Doing
    an import, four getattr calls and four int conversions in
    there is the difference between a filter that feels instant
    and one that does not.
    """
    if not _KIND_BY_ID:
        from Autodesk.Revit.DB import BuiltInCategory as BIC
        for name, kind in KIND_BY_CATEGORY:
            try:
                _KIND_BY_ID[int(getattr(BIC, name))] = kind
            except Exception:
                continue
    return _KIND_BY_ID


def target_categories():
    """BuiltInCategory members, looked up at call time.

    Never at import time - a member a release has moved or
    renamed would otherwise kill the module before any of the
    tool runs.
    """
    from Autodesk.Revit.DB import BuiltInCategory as BIC
    found = []
    for name, _kind in KIND_BY_CATEGORY:
        try:
            found.append(getattr(BIC, name))
        except Exception:
            pass
    return found


def category_id(element):
    try:
        return eid_value(element.Category.Id)
    except Exception:
        return 0


def category_name(element):
    try:
        return to_text(element.Category.Name)
    except Exception:
        return u''


def kind_of(element):
    """'pipe', 'duct', 'tray', 'conduit' or ''.

    Matched on the category id, not on words in the category
    name. Name matching swept in Flex Ducts and Flex Pipes,
    neither of which has a straight centreline to offset.
    """
    try:
        return _kind_map().get(eid_value(element.Category.Id), u'')
    except Exception:
        return u''


def is_supported(element):
    return kind_of(element) in (u'pipe', u'duct', u'tray', u'conduit')


# ---------------------------------------------------------
# Geometry basics
# ---------------------------------------------------------

def location_line(element):
    """The element's own straight centreline, or None."""
    try:
        curve = element.Location.Curve
    except Exception:
        return None
    if curve is None:
        return None
    try:
        start = curve.GetEndPoint(0)
        end = curve.GetEndPoint(1)
    except Exception:
        return None
    try:
        if not isinstance(curve, Line):
            return None
    except Exception:
        pass
    return (start, end)


def axis_of(element):
    ends = location_line(element)
    if ends is None:
        return None
    start, end = ends
    vector = end - start
    if vector.GetLength() < PARALLEL_TOL:
        return None
    return vector.Normalize()


def project_onto_axis(point, start, direction):
    """How far along the axis a point sits, in feet."""
    return (point - start).DotProduct(direction)


def width_mm(element):
    """Diameter for round, the wider side for rectangular.

    Read from the element's own parameters rather than from
    its bounding box, which is axis aligned and overstates a
    diagonal run.
    """
    names = (
        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
        BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
        BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
        BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM,
        BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
    )
    best = 0.0
    for name in names:
        try:
            parameter = element.get_Parameter(name)
        except Exception:
            continue
        if parameter is None:
            continue
        try:
            value = ft_to_mm(parameter.AsDouble())
        except Exception:
            continue
        if value > best:
            best = value

    if best <= 0.0:
        # Fall back to the bounding box's smaller horizontal
        # side, which is the honest answer for a family that
        # carries no size parameter at all.
        try:
            box = element.get_BoundingBox(None)
            if box is not None:
                dx = ft_to_mm(box.Max.X - box.Min.X)
                dy = ft_to_mm(box.Max.Y - box.Min.Y)
                dz = ft_to_mm(box.Max.Z - box.Min.Z)
                sides = sorted([dx, dy, dz])
                best = sides[1]
        except Exception:
            best = 0.0
    return best


# ---------------------------------------------------------
# The four offset directions
# ---------------------------------------------------------

def direction_vectors(axis, view=None):
    """Up, down, left and right as real vectors square to the run.

    Up and down are elevation, which is what an MEP engineer
    means by them: the part of world Z square to the run.

    Left and right are horizontal and square to the run, with
    the sign taken from the view's own right direction, so
    "left" on the prompt is left on the screen rather than
    left in world coordinates.

    A vertical run has no up or down, and those two are simply
    absent from the dict - the prompt greys the buttons out.
    """
    up_world = XYZ.BasisZ
    vertical = abs(axis.DotProduct(up_world)) > 0.999

    screen_right, screen_up = None, None
    try:
        if view is not None:
            for name, keep in (('RightDirection', 'right'),
                               ('UpDirection', 'up')):
                candidate = getattr(view, name, None)
                if candidate is None or candidate.GetLength() < PARALLEL_TOL:
                    continue
                if keep == 'right':
                    screen_right = candidate.Normalize()
                else:
                    screen_up = candidate.Normalize()
    except Exception:
        screen_right, screen_up = None, None

    vectors = {}

    if not vertical:
        along = axis.Multiply(axis.DotProduct(up_world))
        up = up_world - along
        if up.GetLength() > PARALLEL_TOL:
            up = up.Normalize()
            vectors[u'up'] = up
            vectors[u'down'] = up.Negate()

        # Right is the right hand of somebody walking the run
        # the way it reads on screen. Taking it from the
        # element's own axis instead makes left and right swap
        # depending on which way the duct happened to be drawn,
        # and the old test for that - the side vector against
        # the view's right - is exactly zero for a run lying
        # across the view, so it never corrected anything.
        side = so_core.side_of_travel(axis, up_world, screen_right, screen_up)
        if side is not None:
            vectors[u'right'] = side
            vectors[u'left'] = side.Negate()
    else:
        side = screen_right if screen_right is not None else XYZ.BasisX
        along = axis.Multiply(axis.DotProduct(side))
        side = side - along
        if side.GetLength() > PARALLEL_TOL:
            side = side.Normalize()
        else:
            side = XYZ.BasisX
        vectors[u'right'] = side
        vectors[u'left'] = side.Negate()

    return vectors


# ---------------------------------------------------------
# Connectors
# ---------------------------------------------------------

def end_connectors(element):
    found = []
    try:
        manager = element.ConnectorManager
    except Exception:
        return found
    if manager is None:
        return found
    try:
        for connector in manager.Connectors:
            try:
                if connector.ConnectorType == ConnectorType.End:
                    found.append(connector)
            except Exception:
                found.append(connector)
    except Exception:
        pass
    return found


def connector_near(element, point, tolerance_mm=CONN_TOL_MM):
    """The end connector nearest a point.

    Always re-fetched after a Regenerate. A Connector handle
    held across a regenerate goes stale, and a stale handle
    joins two elements that then behave as loose parts.
    """
    limit = mm_to_ft(tolerance_mm)
    best, best_distance = None, None
    for connector in end_connectors(element):
        try:
            distance = connector.Origin.DistanceTo(point)
        except Exception:
            continue
        if best_distance is None or distance < best_distance:
            best, best_distance = connector, distance
    if best is None:
        return None
    if best_distance is not None and best_distance > limit:
        return None
    return best


def disconnect_all(first, second):
    """Break any join between two elements."""
    broken = 0
    for connector in end_connectors(first):
        try:
            refs = list(connector.AllRefs)
        except Exception:
            continue
        for other in refs:
            try:
                if eid_value(other.Owner.Id) != eid_value(second.Id):
                    continue
                if connector.IsConnectedTo(other):
                    connector.DisconnectFrom(other)
                    broken += 1
            except Exception:
                continue
    return broken


# ---------------------------------------------------------
# Breaking a run
# ---------------------------------------------------------

def midpoint(element):
    ends = location_line(element)
    if ends is None:
        return None
    start, end = ends
    return start + (end - start).Multiply(0.5)


def _native_break(doc, element, point):
    """Revit's own split, where the category has one.

    Cable tray and conduit have none, which is why they were
    the only things working before this was fixed.
    """
    kind = kind_of(element)
    try:
        if kind == u'pipe':
            from Autodesk.Revit.DB.Plumbing import PlumbingUtils
            new_id = PlumbingUtils.BreakCurve(doc, element.Id, point)
        elif kind == u'duct':
            from Autodesk.Revit.DB.Mechanical import MechanicalUtils
            new_id = MechanicalUtils.BreakCurve(doc, element.Id, point)
        else:
            return None
    except Exception:
        return None

    if new_id is None or eid_value(new_id) <= 0:
        return None
    doc.Regenerate()
    return doc.GetElement(new_id)


def split_at(doc, element, point, direction):
    """Cut a run at a point. Returns (behind, ahead, how).

    WHICH HALF IS WHICH IS MEASURED, NOT ASSUMED.

    BreakCurve returns "the new element" without saying which
    side of the cut it is on, and it is not always the far one.
    Taking it for the far half left the original run at its
    full length with the offset pieces laid over the top of it,
    and every following cut then landed on the wrong piece -
    which is why pipes and ducts came out wrong while cable
    tray and conduit, which have no BreakCurve and go through
    the copy-and-re-cut below, were fine all along.
    """
    ends = location_line(element)
    if ends is None:
        return None, None, u'no straight centreline'

    start, end = ends
    if (end - start).DotProduct(direction) < 0:
        start, end = end, start

    reach = (point - start).DotProduct(direction)
    total = (end - start).DotProduct(direction)
    floor = mm_to_ft(MIN_SEGMENT_MM)
    if reach < floor or reach > total - floor:
        return None, None, u'the cut lands at the end of the run'

    other = _native_break(doc, element, point)
    how = u'BreakCurve'
    if other is None:
        other, how = _copy_break(doc, element, point, start, end)
        if other is None:
            return None, None, how

    doc.Regenerate()

    first, second = midpoint(element), midpoint(other)
    if first is None or second is None:
        return None, None, u'a half of the run lost its centreline'

    order = so_core.halves_in_order(first, second, start, direction)
    pieces = (element, other)
    return pieces[order[0]], pieces[order[1]], how


def _copy_break(doc, element, point, start, end):
    """Split by copy and re-cut, for anything with no BreakCurve.

    One regenerate, not two: the copy's own curve can be set
    before the model has caught up, and only reading connectors
    back needs it.
    """
    copies = ElementTransformUtils.CopyElement(doc, element.Id, XYZ.Zero)
    new_id = None
    for item in copies:
        new_id = item
        break
    if new_id is None:
        return None, u'copy refused'

    far = doc.GetElement(new_id)
    try:
        element.Location.Curve = Line.CreateBound(start, point)
        far.Location.Curve = Line.CreateBound(point, end)
    except Exception:
        return None, u'the halves would not re-cut'

    doc.Regenerate()

    # Join the halves, so the run is still continuous if the
    # offset is later abandoned.
    try:
        near_conn = connector_near(element, point)
        far_conn = connector_near(far, point)
        if near_conn is not None and far_conn is not None:
            near_conn.ConnectTo(far_conn)
    except Exception:
        pass

    return far, u'copy and re-cut'


def set_line(element, start, end):
    try:
        element.Location.Curve = Line.CreateBound(start, end)
        return True
    except Exception:
        return False


def copy_piece(doc, element, start, end):
    """A new length of the same thing, on a given line.

    No regenerate in here: the caller makes both legs and then
    regenerates once. Copying carries the size, type, insulation
    and lining across, which is why the legs are copied rather
    than rebuilt.
    """
    copies = ElementTransformUtils.CopyElement(doc, element.Id, XYZ.Zero)
    new_id = None
    for item in copies:
        new_id = item
        break
    if new_id is None:
        return None
    piece = doc.GetElement(new_id)
    if piece is None or not set_line(piece, start, end):
        try:
            if piece is not None:
                doc.Delete(piece.Id)
        except Exception:
            pass
        return None
    return piece


# ---------------------------------------------------------
# Fittings
# ---------------------------------------------------------

def _connector_angle(first, second):
    """The angle between two connectors, for the record.

    Revit refuses a bend it thinks is too shallow or too sharp
    without saying what it measured, and the measurement is the
    one thing that tells you whether the geometry is wrong or
    the family simply does not cover that angle.
    """
    try:
        one = first.CoordinateSystem.BasisZ
        two = second.CoordinateSystem.BasisZ
        dot = max(-1.0, min(1.0, one.DotProduct(two)))
        return 180.0 - math.degrees(math.acos(dot))
    except Exception:
        return None


def place_elbow(doc, first, second, point):
    """An elbow across two pieces meeting at a point.

    Connectors are re-fetched here rather than passed in,
    because the caller has almost certainly regenerated
    since it last held them.
    """
    a = connector_near(first, point)
    b = connector_near(second, point)
    if a is None or b is None:
        return None, u'no connector within {0:.0f}mm of the bend'.format(CONN_TOL_MM)

    try:
        if a.IsConnectedTo(b):
            a.DisconnectFrom(b)
    except Exception:
        pass

    measured = _connector_angle(a, b)

    try:
        fitting = doc.Create.NewElbowFitting(a, b)
        if fitting is not None:
            return fitting, u''
    except Exception as error:
        message = to_text(error)
        if measured is not None:
            message = u'{0} [measured {1:.1f} degrees]'.format(message, measured)
        # Fall through to a direct join rather than leaving
        # the run in pieces.
        try:
            a = connector_near(first, point)
            b = connector_near(second, point)
            if a is not None and b is not None:
                a.ConnectTo(b)
                return None, (u'no elbow family would take this bend, so the '
                              u'pieces are joined directly ({0})').format(message[:120])
        except Exception:
            pass
        return None, u'the bend would not take a fitting ({0})'.format(message[:160])

    return None, u'the bend would not take a fitting'


# ---------------------------------------------------------
# Copying values onto the new pieces
# ---------------------------------------------------------

SERVICE_PARAM_NAMES = (
    u'BGL_Service Type', u'Service Type', u'BGL_Function',
    u'BGL_Type Mark', u'Type Mark',
)


def copy_text_params(source, targets, names):
    """Push a value from one element onto others by name.

    GetParameters is used rather than LookupParameter,
    because a family can carry two parameters of the same
    name and the two calls do not always hand back the same
    object.
    """
    written = []
    for name in names:
        try:
            found = source.GetParameters(name)
        except Exception:
            found = None
        if not found:
            continue
        value = None
        for parameter in found:
            try:
                value = parameter.AsString()
            except Exception:
                value = None
            if value:
                break
        if not value:
            continue
        for target in targets:
            try:
                slots = target.GetParameters(name)
            except Exception:
                slots = None
            if not slots:
                continue
            for slot in slots:
                try:
                    if slot.IsReadOnly:
                        continue
                    slot.Set(value)
                    written.append(name)
                    break
                except Exception:
                    continue
    return written


# ---------------------------------------------------------
# Dialog and warning suppression
# ---------------------------------------------------------

class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings raised inside the transaction."""

    def __init__(self):
        self.seen = []

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                try:
                    self.seen.append(to_text(failure.GetDescriptionText()))
                except Exception:
                    pass
                try:
                    accessor.DeleteWarning(failure)
                except Exception:
                    pass
        except Exception:
            pass
        return FailureProcessingResult.Continue


def guarded_transaction(doc, name):
    transaction = Transaction(doc, name)
    swallower = WarningSwallower()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(swallower)
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction, swallower


# ---------------------------------------------------------
# The offset itself
# ---------------------------------------------------------

def analyse(doc, element, point_a, point_b, settings, view=None,
            mode=MODE_JOG, bank=None):
    """What the two clicks mean, before anything is decided.

    Works out where the run gets cut, how much room there is,
    the default offset distance and which of the four
    directions are available - everything the prompt needs to
    open. Writes nothing.

    Where a click lands at or past an end of the run, the cut
    is CLAMPED inward rather than refused. v3 refused, and
    since the second click is often taken slightly beyond the
    end, that refused most of the offsets anybody tried.
    """
    bends = BENDS_ALONG_RUN.get(mode, 2)
    result = {'ok': False, 'reason': u'', 'notes': [], 'problems': [],
              'mode': mode, 'bends': bends,
              'element_id': eid_value(element.Id),
              'kind': kind_of(element)}

    if not is_supported(element):
        result['reason'] = (u'{0} is not a pipe, duct, cable tray or conduit.'
                            .format(category_name(element) or u'That element'))
        return result

    ends = location_line(element)
    if ends is None:
        result['reason'] = (u'Only straight runs can be offset - that one is '
                            u'an arc or has no straight centreline.')
        return result

    start, end = ends
    axis = axis_of(element)
    if axis is None:
        result['reason'] = u'That run has no length to work along.'
        return result

    length_mm = ft_to_mm(project_onto_axis(end, start, axis))

    along_a = ft_to_mm(project_onto_axis(point_a, start, axis))
    along_b = ft_to_mm(project_onto_axis(point_b, start, axis))
    if along_b < along_a:
        along_a, along_b = along_b, along_a

    # Clamp both cuts inside the run, leaving the shortest
    # allowed piece at each end to hold the existing joints.
    floor = MIN_SEGMENT_MM
    ceiling = length_mm - MIN_SEGMENT_MM
    if ceiling <= floor:
        result['reason'] = (u'That run is only {0:.0f}mm long, which is not '
                            u'enough to cut an offset into.'.format(length_mm))
        return result

    clamped = False
    if along_a < floor:
        along_a, clamped = floor, True
    if along_b > ceiling:
        along_b, clamped = ceiling, True
    if along_b <= along_a:
        result['reason'] = (u'Both clicks landed at the same place along the '
                            u'run. Click the start and the end of the offset.')
        return result
    if clamped:
        note(result,
             u'A click landed at the end of the run, so the cut was moved '
             u'{0:.0f}mm in to leave the existing joint something to hold.'
             .format(MIN_SEGMENT_MM))

    span_mm = along_b - along_a
    angle = so_core.snap_angle(as_float(settings.get('angle'), 45.0))
    vectors = direction_vectors(axis, view)

    if not vectors:
        result['reason'] = u'There is no direction square to that run to offset in.'
        return result

    result.update({
        'ok': True,
        'element': element,
        'axis': axis,
        'start': start,
        'cut_a': start + axis.Multiply(mm_to_ft(along_a)),
        'cut_b': start + axis.Multiply(mm_to_ft(along_b)),
        'span_mm': span_mm,
        'length_mm': length_mm,
        'width_mm': width_mm(element),
        'angle_deg': angle,
        'vectors': vectors,
        'directions': sorted(vectors.keys()),
        'max_distance_mm': so_core.max_offset_mm(span_mm, angle, bends),
    })
    result['default_distance_mm'] = so_core.offset_distance_mm(
        settings, result['width_mm'])

    # Where several parallel runs were selected, each one's
    # position in the bank is worked out once, here, against
    # the leader.
    result['bank'] = []
    for other in (bank or [element]):
        result['bank'].append({'element': other,
                               'offset': _bank_offset(element, other, axis)})
    return result


def _bank_offset(leader, other, axis):
    """Where a run sits relative to the leader, square to them.

    Both are parallel, so the along-the-run part means nothing
    and only the part square to them is kept.
    """
    lead_line = location_line(leader)
    other_line = location_line(other)
    if lead_line is None or other_line is None:
        return XYZ.Zero
    gap = other_line[0] - lead_line[0]
    return gap - axis.Multiply(gap.DotProduct(axis))


def apply_offset(doc, analysis, distance_mm, direction, settings):
    """Do it, in the direction the prompt was answered with.

    Both modes share every line of this: the same fit test, the
    same transaction group, the same rollback. Only which
    pieces get built differs.
    """
    record = {
        'ok': False,
        'element_id': analysis.get('element_id'),
        'kind': analysis.get('kind'),
        'notes': list(analysis.get('notes', [])),
        'problems': [],
        'created': [],
        'reason': u'',
        'distance_mm': distance_mm,
        'angle_deg': analysis.get('angle_deg', 45.0),
        'direction': direction,
        'mode': analysis.get('mode', MODE_JOG),
    }

    vectors = analysis.get('vectors') or {}
    if direction not in vectors:
        record['reason'] = (u'A {0} offset is not available on that run.'
                            .format(direction))
        return record

    plan = so_core.plan_offset(distance_mm, analysis['angle_deg'],
                               analysis['span_mm'], MIN_SEGMENT_MM,
                               analysis.get('bends', 2))
    if not plan.get('ok'):
        record['reason'] = plan.get('reason', u'That offset will not fit.')
        return record

    element = analysis['element']
    axis = analysis['axis']
    offset_vector = vectors[direction].Multiply(mm_to_ft(distance_mm))
    back = mm_to_ft(plan['run_back_mm'])

    axis = analysis['axis']
    sideways = vectors[direction]
    offset_vector = sideways.Multiply(mm_to_ft(distance_mm))
    back = mm_to_ft(plan['run_back_mm'])
    normal = so_core.cross(axis, sideways).Normalize()

    # The leader's route as a polyline: the corners, and the
    # direction of the leg into the first one then out of each.
    # Free ends are listed separately because they only shift
    # sideways - there is no second leg to cross with.
    cut_a, cut_b = analysis['cut_a'], analysis['cut_b']
    inner_a = cut_a + axis.Multiply(back) + offset_vector

    # A sloped run keeps its fall through the offset.
    #
    # A BREAK does not come back to the line it left, so every
    # piece can sit on the run's own gradient: the corner and
    # the far end are worked out in plan and then dropped onto
    # it. Only for a sideways offset - up and down exist to
    # change level, so holding the fall there would defeat them.
    up = XYZ.BasisZ
    grade = so_core.gradient(axis, up)
    level_offset = abs(sideways.DotProduct(up)) < 1.0e-3
    hold_fall = so_core.is_sloped(grade) and level_offset

    if record['mode'] == MODE_BREAK:
        end_b = cut_b + offset_vector
        if hold_fall:
            inner_a = so_core.with_fall(cut_a, inner_a, up, grade)
            end_b = so_core.with_fall(inner_a, end_b, up, grade)
            note(record, u'Held at {0} throughout.'
                         .format(so_core.describe_gradient(grade)))
        corners = [cut_a, inner_a]
        legs = [axis, (inner_a - cut_a).Normalize(), axis]
        free_ends = [(end_b, axis), (cut_b, axis)]
    else:
        inner_b = cut_b - axis.Multiply(back) + offset_vector
        # A JOG has to arrive back on the run it left, and a jog
        # is longer in plan than the straight it replaces. At a
        # fixed gradient extra length is extra fall, so a route
        # holding the fall on every piece would arrive BELOW the
        # pipe it has to join - by 2 x d x tan(half the bend),
        # whatever span is chosen. No arrangement avoids it.
        #
        # So the two ends and the long middle sit exactly on the
        # gradient, which they already do by construction, and
        # the two short diagonals carry the difference. Say so
        # rather than leave it to be found.
        if hold_fall:
            low_mm = so_core.jog_fall_shortfall(distance_mm,
                                                analysis['angle_deg'], grade)
            note(record,
                 u'{0} held on the straight lengths. The two bend legs are '
                 u'{1:.0f}mm shallower over their length between them, which '
                 u'is what lets the run rejoin its own line.'
                 .format(so_core.describe_gradient(grade), low_mm))
        corners = [cut_a, inner_a, inner_b, cut_b]
        legs = [axis,
                (inner_a - cut_a).Normalize(), axis,
                (cut_b - inner_b).Normalize(), axis]
        free_ends = []

    strands = _lay_out_bank(analysis, corners, legs, free_ends, normal,
                            sideways, axis, record['mode'])
    if not strands.get('ok'):
        record['reason'] = strands.get('reason', u'')
        return record

    builder = _build_break if record['mode'] == MODE_BREAK else _build_jog
    group = TransactionGroup(doc, LABELS[record['mode']])
    group.Start()
    try:
        placed = 0
        for strand in strands['strands']:
            own = dict(record)
            own['notes'] = list(record['notes'])
            own['problems'] = []
            own['element_id'] = eid_value(strand['element'].Id)
            own['kind'] = kind_of(strand['element'])
            if builder(doc, strand['element'], strand['points'],
                       analysis['axis'], own):
                placed += 1
                record['notes'] = own['notes']
                for trouble in own['problems']:
                    problem(record, trouble)
            else:
                record['reason'] = own.get('reason', u'')
                group.RollBack()
                return record

        group.Assimilate()
        record['ok'] = True
        if placed > 1:
            note(record, u'{0} runs offset together, parallel and evenly '
                         u'spaced.'.format(placed))
    except Exception as error:
        try:
            group.RollBack()
        except Exception:
            pass
        record['reason'] = u'The offset was rolled back: {0}'.format(to_text(error))
    return record


def _lay_out_bank(analysis, corners, legs, free_ends, normal, sideways, axis,
                  mode):
    """Every run's own corners, and whether they all fit.

    A strand is a parallel OFFSET of the leader's route, not a
    copy of it shifted sideways. At a bend the corner has to
    move along the run as well as across it, so the strand on
    the outside turns later than the one on the inside - which
    is what keeps the diagonals as far apart as the straight
    legs. Shifting every corner to the same station pulls them
    to cos(angle) of the spacing instead: 300mm becomes 212mm
    at 45 degrees.
    """
    out = []
    for entry in analysis.get('bank') or []:
        element = entry['element']
        lateral, through = so_core.bank_split(entry['offset'], axis,
                                              sideways, normal)

        points = so_core.bank_corners(corners, legs, normal, lateral, through)
        for point, leg in free_ends:
            points.append(so_core.offset_end(point, leg, normal, lateral,
                                             through))

        problem_text = _strand_fits(element, points, axis, mode)
        if problem_text:
            return {'ok': False, 'reason': problem_text}
        out.append({'element': element, 'points': points})

    return {'ok': True, 'strands': out}


def _strand_fits(element, points, axis, mode):
    """Enough of this run left either side of its own cuts.

    Checked per run, not once for the leader: staggering moves
    the outer strand's cuts along its own length, so a span
    that suits the middle of a bank can run off the end of the
    outside of it.
    """
    ends = location_line(element)
    if ends is None:
        return u'One of the selected runs has no straight centreline.'
    start, end = ends
    if (end - start).DotProduct(axis) < 0:
        start, end = end, start

    first, last = points[0], points[-1]
    lead_mm = ft_to_mm((first - start).DotProduct(axis))
    tail_mm = ft_to_mm((end - last).DotProduct(axis))

    if lead_mm < MIN_SEGMENT_MM or tail_mm < MIN_SEGMENT_MM:
        return (u'Make second click further away.\n\n'
                u'Keeping the bends parallel moves each run\'s bend along its '
                u'own length, and there is not enough run left on one of them '
                u'to hold its existing joints. Click the two points further '
                u'apart, or further in from the ends.')

    if mode != MODE_BREAK:
        middle_mm = ft_to_mm((points[2] - points[1]).GetLength())
        if middle_mm < MIN_SEGMENT_MM:
            return (u'Make second click further away.\n\n'
                    u'Keeping the bends parallel leaves only {0:.0f}mm between '
                    u'them on one of the runs. Click the two points further '
                    u'apart, or take a squarer angle.'.format(middle_mm))
    return u''


def _build_jog(doc, element, points, axis, record):
    """The pieces, the moves and the fittings, inside the group.

    Regenerating is what this routine costs. On a real model
    each call is a meaningful fraction of a second, and v4 made
    a dozen of them per offset. The work is batched into four
    now: after each break, once after every curve edit, and
    once at the end.
    """

    cut_a, inner_a, inner_b, cut_b = points

    transaction, swallower = guarded_transaction(doc, u'System Offset')
    transaction.Start()
    try:
        pinned = False
        try:
            if element.Pinned:
                element.Pinned = False
                pinned = True
        except Exception:
            pinned = False

        # Cut at the near point, then cut the far half again.
        # split_at hands back both halves in order, so which one
        # Revit chose to call "the new element" does not matter.
        lead, middle, how = split_at(doc, element, cut_a, axis)
        if middle is None:
            record['reason'] = (u'The run would not split at the first click '
                                u'({0}).'.format(how))
            transaction.RollBack()
            return False

        middle, tail, how_b = split_at(doc, middle, cut_b, axis)
        if tail is None:
            record['reason'] = (u'The run would not split at the second click '
                                u'({0}).'.format(how_b))
            transaction.RollBack()
            return False

        note(record, u'Split by {0}.'.format(how))

        # Every curve edit in one batch, then a single
        # regenerate. Disconnecting does not need one, and
        # neither does setting a curve on a freshly copied
        # element - only reading connectors back does.
        disconnect_all(lead, middle)
        disconnect_all(middle, tail)

        if not set_line(middle, inner_a, inner_b):
            record['reason'] = u'The middle length would not move onto the offset.'
            transaction.RollBack()
            return False

        first_leg = copy_piece(doc, middle, cut_a, inner_a)
        second_leg = copy_piece(doc, middle, inner_b, cut_b)
        if first_leg is None or second_leg is None:
            record['reason'] = u'The bend legs would not be created.'
            transaction.RollBack()
            return False

        doc.Regenerate()

        record['created'] = [eid_value(middle.Id),
                             eid_value(first_leg.Id),
                             eid_value(second_leg.Id),
                             eid_value(tail.Id)]

        written = copy_text_params(lead, (middle, first_leg, second_leg, tail),
                                   SERVICE_PARAM_NAMES)
        if written:
            note(record, u'Copied {0}.'.format(
                u', '.join(sorted(set(written)))))

        placed = 0
        for first, second, point in ((lead, first_leg, cut_a),
                                     (first_leg, middle, inner_a),
                                     (middle, second_leg, inner_b),
                                     (second_leg, tail, cut_b)):
            if REGEN_BETWEEN_BENDS:
                doc.Regenerate()
            fitting, trouble = place_elbow(doc, first, second, point)
            if fitting is not None:
                placed += 1
            elif trouble:
                problem(record, trouble)

        record['fittings'] = placed
        if placed < 4:
            problem(record, u'{0} of 4 bends took a fitting.'.format(placed))

        doc.Regenerate()

        if pinned:
            for piece in (lead, middle, first_leg, second_leg, tail):
                try:
                    piece.Pinned = True
                except Exception:
                    pass

        if swallower.seen:
            note(record, u'{0} Revit warning(s) were cleared.'
                         .format(len(swallower.seen)))

        status = transaction.Commit()
        try:
            from Autodesk.Revit.DB import TransactionStatus
            if status != TransactionStatus.Committed:
                record['reason'] = u'Revit did not commit the offset.'
                return False
        except Exception:
            pass
        return True

    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        record['reason'] = to_text(error)
        return False


def _build_break(doc, element, points, axis, record):
    """Out and stop: cut the run and step it onto a new line.

    The piece between the two clicks is cranked over onto the
    offset line. The run is cut at the second click and what
    lies beyond stays exactly where it was, disconnected - the
    gap is the offset distance, square to the run.

    Two bends rather than four, and nothing rejoins.
    """

    cut_a, inner_a, end_b, cut_b = points

    transaction, swallower = guarded_transaction(doc, u'Offset Break')
    transaction.Start()
    try:
        pinned = False
        try:
            if element.Pinned:
                element.Pinned = False
                pinned = True
        except Exception:
            pinned = False

        # Cut at the near point, then cut the far half again.
        # split_at hands back both halves in order, so which one
        # Revit chose to call "the new element" does not matter.
        lead, middle, how = split_at(doc, element, cut_a, axis)
        if middle is None:
            record['reason'] = (u'The run would not split at the first click '
                                u'({0}).'.format(how))
            transaction.RollBack()
            return False

        middle, tail, how_b = split_at(doc, middle, cut_b, axis)
        if tail is None:
            record['reason'] = (u'The run would not split at the second click '
                                u'({0}).'.format(how_b))
            transaction.RollBack()
            return False

        note(record, u'Split by {0}.'.format(how))

        # The tail is let go here and never reconnected. That
        # disconnection IS the gap.
        disconnect_all(lead, middle)
        disconnect_all(middle, tail)

        if not set_line(middle, inner_a, end_b):
            record['reason'] = u'The run would not step onto the offset.'
            transaction.RollBack()
            return False

        leg = copy_piece(doc, middle, cut_a, inner_a)
        if leg is None:
            record['reason'] = u'The bend leg would not be created.'
            transaction.RollBack()
            return False

        doc.Regenerate()

        record['created'] = [eid_value(middle.Id), eid_value(leg.Id),
                             eid_value(tail.Id)]

        written = copy_text_params(lead, (middle, leg, tail),
                                   SERVICE_PARAM_NAMES)
        if written:
            note(record, u'Copied {0}.'.format(
                u', '.join(sorted(set(written)))))

        placed = 0
        for first, second, point in ((lead, leg, cut_a),
                                     (leg, middle, inner_a)):
            if REGEN_BETWEEN_BENDS:
                doc.Regenerate()
            fitting, trouble = place_elbow(doc, first, second, point)
            if fitting is not None:
                placed += 1
            elif trouble:
                problem(record, trouble)

        record['fittings'] = placed
        if placed < 2:
            problem(record, u'{0} of 2 bends took a fitting.'.format(placed))

        # This is what the tool is for, not a problem with it.
        note(record, u'The run is cut at the second click. What lies beyond '
                     u'it is unchanged and now open.')

        doc.Regenerate()

        if pinned:
            for piece in (lead, middle, leg, tail):
                try:
                    piece.Pinned = True
                except Exception:
                    pass

        if swallower.seen:
            note(record, u'{0} Revit warning(s) were cleared.'
                         .format(len(swallower.seen)))

        status = transaction.Commit()
        try:
            from Autodesk.Revit.DB import TransactionStatus
            if status != TransactionStatus.Committed:
                record['reason'] = u'Revit did not commit the offset.'
                return False
        except Exception:
            pass
        return True

    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        record['reason'] = to_text(error)
        return False
