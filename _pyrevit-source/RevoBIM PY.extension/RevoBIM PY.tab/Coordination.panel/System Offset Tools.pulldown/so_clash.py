# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM Clash Offset - reading the clash and working out
# the way round it
#
# Pick the services, pick what is in the way - in this model
# or in a link - and the tool works out where the clash sits
# along the run, which way out is cheapest, which way out the
# shape of the obstruction calls for, and how far.
#
# Everything after that is the jog the offset tools already
# build: the cuts and the distance are handed to
# so_model.analyse and so_model.apply_offset, so a bank of
# parallel services stays parallel and evenly spaced round the
# clash for free.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from Autodesk.Revit.DB import (
    Options, Transform, Solid, GeometryInstance, SolidUtils,
    BooleanOperationsUtils, BooleanOperationsType)

import so_core
import so_model
from so_core import mm_to_ft, ft_to_mm, eid_value, to_text


# ---------------------------------------------------------
# What is in the way
# ---------------------------------------------------------

def resolve_reference(doc, reference):
    """The element a pick landed on, and how to place it.

    A pick inside a link gives the link instance as the
    element and the real thing as LinkedElementId, so both
    have to be unpicked and the link's transform carried
    through. A pick in this model has no linked id.
    """
    try:
        linked_id = reference.LinkedElementId
    except Exception:
        linked_id = None

    if linked_id is not None and eid_value(linked_id) > 0:
        link = doc.GetElement(reference.ElementId)
        try:
            link_doc = link.GetLinkDocument()
            return (link_doc.GetElement(linked_id),
                    link.GetTotalTransform(), True)
        except Exception:
            return None, None, False

    return doc.GetElement(reference.ElementId), Transform.Identity, False


def element_solids(element, transform):
    """An element's solids, moved into host coordinates."""
    found = []
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    try:
        options.DetailLevel = _fine()
    except Exception:
        pass

    try:
        geometry = element.get_Geometry(options)
    except Exception:
        return found
    if geometry is None:
        return found

    raw = []
    _collect(geometry, raw)

    identity = True
    try:
        identity = transform.IsIdentity
    except Exception:
        identity = False

    for solid in raw:
        if identity:
            found.append(solid)
            continue
        try:
            found.append(SolidUtils.CreateTransformed(solid, transform))
        except Exception:
            found.append(solid)
    return found


def _collect(geometry, found):
    try:
        items = list(geometry)
    except Exception:
        return
    for item in items:
        if isinstance(item, GeometryInstance):
            try:
                _collect(item.GetInstanceGeometry(), found)
            except Exception:
                pass
            continue
        if not isinstance(item, Solid):
            continue
        try:
            if item.Volume > 0:
                found.append(item)
        except Exception:
            continue


def solid_points(solids):
    """Corner points of solids.

    Edge endpoints rather than a bounding box: a box is axis
    aligned, so a beam running at an angle reads as far bigger
    than it is and the service gets pushed further than it needs
    to go.
    """
    found = []
    for solid in solids or []:
        try:
            for edge in solid.Edges:
                curve = edge.AsCurve()
                found.append(curve.GetEndPoint(0))
                found.append(curve.GetEndPoint(1))
        except Exception:
            continue
    return found


def service_points(doc, element):
    """A service's own body, insulation and lining included.

    Insulation is a separate element in Revit, so a bare
    geometry read misses it and the service is offset by its
    core size while its lagging still fouls what it was meant
    to clear.
    """
    points = solid_points(element_solids(element, Transform.Identity))

    for reader in ('InsulationLiningBase',):
        try:
            from Autodesk.Revit.DB import InsulationLiningBase
        except Exception:
            break
        for getter in ('GetInsulationIds', 'GetLiningIds'):
            try:
                ids = getattr(InsulationLiningBase, getter)(doc, element.Id)
            except Exception:
                continue
            for wrap_id in ids or []:
                wrap = doc.GetElement(wrap_id)
                if wrap is None:
                    continue
                points.extend(solid_points(
                    element_solids(wrap, Transform.Identity)))
    return points


def clash_points(service, obstruction_solids):
    """Just the part where the two actually overlap.

    Cutting to the whole obstruction is safe but coarse: a beam
    running nearly along a service reaches for metres, and the
    jog would be built to clear all of it. The real overlap is
    what matters, so it is taken where Revit will give it and
    the whole obstruction is the fallback.
    """
    try:
        own = element_solids(service, Transform.Identity)
    except Exception:
        return None
    if not own or not obstruction_solids:
        return None

    found = []
    for mine in own:
        for theirs in obstruction_solids:
            try:
                cut = BooleanOperationsUtils.ExecuteBooleanOperation(
                    mine, theirs, BooleanOperationsType.Intersect)
            except Exception:
                continue
            if cut is None:
                continue
            try:
                if cut.Volume <= 0:
                    continue
            except Exception:
                continue
            found.extend(solid_points([cut]))
    return found or None


def geometry_points(element, transform):
    """Corner points of an element's solids, in host coordinates.

    Edge endpoints rather than a bounding box: a box is axis
    aligned, so a beam running at an angle reads as far bigger
    than it is and the service is pushed further than it needs
    to go. Where there is no usable solid the box is the
    fallback, which only ever overstates.
    """
    found = []
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    try:
        options.DetailLevel = _fine()
    except Exception:
        pass

    try:
        geometry = element.get_Geometry(options)
    except Exception:
        geometry = None

    if geometry is not None:
        _walk(geometry, transform, found)

    if not found:
        try:
            box = element.get_BoundingBox(None)
            if box is not None:
                base = box.Transform
                for x in (box.Min.X, box.Max.X):
                    for y in (box.Min.Y, box.Max.Y):
                        for z in (box.Min.Z, box.Max.Z):
                            from Autodesk.Revit.DB import XYZ
                            point = base.OfPoint(XYZ(x, y, z))
                            found.append(transform.OfPoint(point))
        except Exception:
            pass
    return found


def _fine():
    from Autodesk.Revit.DB import ViewDetailLevel
    return ViewDetailLevel.Fine


def _walk(geometry, transform, found):
    try:
        items = list(geometry)
    except Exception:
        return
    for item in items:
        if isinstance(item, GeometryInstance):
            try:
                _walk(item.GetInstanceGeometry(), transform, found)
            except Exception:
                pass
            continue
        if not isinstance(item, Solid):
            continue
        try:
            if item.Volume <= 0:
                continue
            for edge in item.Edges:
                curve = edge.AsCurve()
                for index in (0, 1):
                    found.append(transform.OfPoint(curve.GetEndPoint(index)))
        except Exception:
            continue


# ---------------------------------------------------------
# What kind of thing it is
# ---------------------------------------------------------

CATEGORY_KINDS = (
    ('OST_StructuralColumns', u'column'),
    ('OST_Columns', u'column'),
    ('OST_StructuralFraming', u'beam'),
    ('OST_Floors', u'slab'),
    ('OST_StructuralFoundation', u'slab'),
    ('OST_Roofs', u'slab'),
    ('OST_Walls', u'wall'),
    ('OST_PipeCurves', u'service'),
    ('OST_DuctCurves', u'service'),
    ('OST_CableTray', u'service'),
    ('OST_Conduit', u'service'),
)


def classify(element):
    """'column', 'beam', 'slab', 'wall', 'service' or ''.

    The category first, because it is what the model actually
    says. Where the category means nothing the shape decides:
    something far taller than it is wide is a post and gets
    walked round, something long and flat is a beam and gets
    gone under.
    """
    from Autodesk.Revit.DB import BuiltInCategory as BIC
    try:
        mine = eid_value(element.Category.Id)
    except Exception:
        mine = 0

    for name, kind in CATEGORY_KINDS:
        try:
            if mine == int(getattr(BIC, name)):
                return kind
        except Exception:
            continue
    return u''


def classify_by_shape(points, up):
    """A fallback for anything the category does not name."""
    if not points:
        return u''
    heights = [point.DotProduct(up) for point in points]
    tall = max(heights) - min(heights)

    spread = 0.0
    first = points[0]
    for point in points:
        flat = point - first
        flat = flat - up.Multiply(flat.DotProduct(up))
        length = flat.GetLength()
        if length > spread:
            spread = length

    if spread < 1.0e-9:
        return u''
    if tall > spread * 1.5:
        return u'column'
    if spread > tall * 2.5:
        return u'beam'
    return u''


# ---------------------------------------------------------
# The clash itself
# ---------------------------------------------------------

def nearest_on_run(element, points):
    """The point on the run closest to the middle of the clash."""
    ends = so_model.location_line(element)
    axis = so_model.axis_of(element)
    if ends is None or axis is None or not points:
        return None, None

    start = ends[0]
    middle = points[0]
    for point in points[1:]:
        middle = middle + point
    middle = middle.Multiply(1.0 / float(len(points)))

    along = (middle - start).DotProduct(axis)
    return start + axis.Multiply(along), axis


def required_offsets(doc, element, points, vectors, origin, clearance_mm,
                     own_points=None):
    """How far to move, each of the four ways, to get clear.

    Moving by d along v puts the service's near face at
    d - half. That has to pass the far face of the obstruction
    plus the clearance, so d is the obstruction's reach that
    way, plus the service's own half size THAT way, plus the
    clearance.

    The half size is measured off the service's real geometry
    per direction, insulation included, so a 600 x 300 duct is
    150 going up and 300 going sideways rather than 300 both
    ways.
    """
    if own_points is None:
        own_points = service_points(doc, element)

    fallback = so_model.width_mm(element) / 2.0
    out = {}
    for key, vector in (vectors or {}).items():
        reach = so_core.span_along(points, origin, vector)
        if reach is None:
            out[key] = None
            continue
        half = so_core.half_extent(own_points, origin, vector)
        if half is None:
            half = fallback
        out[key] = reach[1] + half + float(clearance_mm)
    return out


def find_clash(doc, services, obstruction_points, settings, view,
               clearance_mm, lead_mm, kind, direction=None,
               obstruction_solids=None):
    """Everything needed to jog a bank of services round a clash.

    Returns a dict carrying the analysis the offset builder
    wants, the way out chosen and why, or a reason it cannot.
    """
    leader = services[0]
    origin, axis = nearest_on_run(leader, obstruction_points)
    if origin is None:
        return {'ok': False,
                'reason': u'That run has no straight centreline to work along.'}

    vectors = so_model.direction_vectors(axis, view)
    if not vectors:
        return {'ok': False,
                'reason': u'There is no direction square to that run to move it in.'}

    # A bank moves as one, so the way out has to clear the
    # service that needs the most room, not the one picked -
    # and each is measured on its own size, not the leader's.
    required = {}
    measured = []
    for service in services:
        point, _axis = nearest_on_run(service, obstruction_points)
        if point is None:
            continue
        own = service_points(doc, service)
        measured.append(required_offsets(doc, service, obstruction_points,
                                         vectors, point, clearance_mm, own))
    for key in vectors:
        worst = None
        for one in measured:
            value = one.get(key)
            if value is None:
                continue
            if worst is None or value > worst:
                worst = value
        required[key] = worst

    if direction:
        chosen = {'direction': direction,
                  'distance_mm': required.get(direction),
                  'preferred': True,
                  'cheapest_mm': min([v for v in required.values()
                                      if v is not None] or [0.0])}
        if chosen['distance_mm'] is None:
            return {'ok': False,
                    'reason': u'A {0} offset is not available on that run.'
                              .format(direction)}
    else:
        chosen = so_core.choose_escape(required, kind)
        if chosen is None:
            return {'ok': False,
                    'reason': u'No way round that clash could be worked out.'}

    distance_mm = so_core.round_to(chosen['distance_mm'], so_core.ROUND_MM)
    angle = so_core.snap_angle(so_core.as_float(settings.get('angle'), 45.0))

    # Cut to the real overlap where Revit will give it, and to
    # the whole obstruction otherwise.
    overlap = clash_points(leader, obstruction_solids)
    reach = so_core.span_along(overlap or obstruction_points, origin, axis)
    touched = overlap is not None
    cut_a_mm, cut_b_mm = so_core.clash_cuts(reach[0], reach[1], distance_mm,
                                            angle, lead_mm)

    point_a = origin + axis.Multiply(mm_to_ft(cut_a_mm))
    point_b = origin + axis.Multiply(mm_to_ft(cut_b_mm))

    others = [s for s in services[1:]]
    analysis = so_model.analyse(doc, leader, point_a, point_b, settings, view,
                                so_model.MODE_JOG,
                                bank=([leader] + others) if others else None)
    if not analysis.get('ok'):
        return {'ok': False, 'reason': analysis.get('reason', u'')}

    return {
        'ok': True,
        'analysis': analysis,
        'direction': chosen['direction'],
        'distance_mm': distance_mm,
        'required': required,
        'preferred': chosen['preferred'],
        'cheapest_mm': chosen['cheapest_mm'],
        'kind': kind,
        'span_mm': reach[1] - reach[0],
        'touched': touched,
        'cut_a_mm': cut_a_mm,
        'cut_b_mm': cut_b_mm,
    }


def explain(found):
    """One line saying what it decided and why."""
    kind = found.get('kind') or u'obstruction'
    what = (u'The overlap' if found.get('touched')
            else u'{0} is'.format(kind.title()))
    line = (u'{0} {1}mm across the run; going {2} {3:.0f}mm clears it.'
            .format(what, u'{0:.0f}'.format(found.get('span_mm', 0.0)),
                    found.get('direction'), found.get('distance_mm', 0.0)))
    if not found.get('touched'):
        line += (u' Nothing was found actually overlapping, so the whole of '
                 u'it was cleared.')
    if not found.get('preferred'):
        line += (u' The usual way round a {0} would have cost far more, so '
                 u'the shorter way was taken.'.format(kind))
    if kind == u'wall':
        line += (u' A wall is usually penetrated rather than gone round - '
                 u'BWIC Penetration may be the better tool.')
    return line
