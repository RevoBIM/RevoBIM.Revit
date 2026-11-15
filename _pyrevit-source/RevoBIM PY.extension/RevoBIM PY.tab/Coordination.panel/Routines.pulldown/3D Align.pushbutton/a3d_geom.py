# -*- coding: utf-8 -*-
"""3D Align - the alignment rules. Plain tuples in, plain tuples out.

No Revit and no WPF in here, so every rule is tested on the bench against a
table of cases. Lengths are Revit's internal decimal feet; an axis is a pair of
(x, y, z) end points taken from the element's location line, which is its
centreline for pipes, ducts, cable trays and conduits.
"""
import math

from a3d_settings import MM_PER_FT

# Steeper than this is an upright, the same line Drainage Elevation Match uses.
STEEP_DEG = 46.0
# Closer than this in plan counts as aligned: nothing is moved.
ALIGNED_MM = 0.1
ALIGNED_FT = ALIGNED_MM / MM_PER_FT

VERTICAL = 'vertical'
HORIZONTAL = 'horizontal'

MODE_LABELS = {
    (VERTICAL, VERTICAL): u'vertical to vertical - centred in X and Y',
    (VERTICAL, HORIZONTAL): u'horizontal centreline run through the vertical',
    (HORIZONTAL, VERTICAL): u'vertical moved onto the horizontal centreline',
}

_EPS = 1e-9


def pitch_deg(axis):
    """Angle of the axis above the horizontal plane, 0 to 90, or None if it
    has no length."""
    (x0, y0, z0), (x1, y1, z1) = axis
    plan = math.hypot(x1 - x0, y1 - y0)
    rise = abs(z1 - z0)
    if plan < _EPS and rise < _EPS:
        return None
    return math.degrees(math.atan2(rise, plan))


def classify(axis):
    if axis is None:
        return None
    pitch = pitch_deg(axis)
    if pitch is None:
        return None
    return VERTICAL if pitch > STEEP_DEG else HORIZONTAL


def mid_z(axis):
    return (axis[0][2] + axis[1][2]) / 2.0


def xy_at_z(axis, z):
    """Where an upright's centreline sits in plan at height z. Exact for a
    plumb upright; follows the lean of one that is steep but not plumb, so the
    datum is where the other element's height actually crosses it."""
    (x0, y0, z0), (x1, y1, z1) = axis
    dz = z1 - z0
    if abs(dz) < _EPS:
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    t = (z - z0) / dz
    return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))


def plan_frame(axis):
    """Origin and unit direction of an axis in plan, or None if it has no
    plan length."""
    (x0, y0, z0), (x1, y1, z1) = axis
    length = math.hypot(x1 - x0, y1 - y0)
    if length < _EPS:
        return None
    return (x0, y0), ((x1 - x0) / length, (y1 - y0) / length), length


def z_along(axis, frame, along):
    """Height of a (possibly falling) run at a plan distance along it."""
    (x0, y0, z0), (x1, y1, z1) = axis
    return z0 + (along / frame[2]) * (z1 - z0)


def offset_from_line(point, frame):
    """The plan vector from the nearest point on the line to the point, and
    how far along the line that nearest point is."""
    (ox, oy), (dx, dy), _length = frame
    vx = point[0] - ox
    vy = point[1] - oy
    along = vx * dx + vy * dy
    return (vx - along * dx, vy - along * dy), along


def is_aligned(distance_ft):
    return distance_ft < ALIGNED_FT


def plan_alignment(first, second):
    """How far, and which way, the second element has to move in plan.

    The move is always horizontal (dz = 0) and, where a horizontal run is
    involved, always square to that run - so nothing slides along its own
    length and no height or fall changes.
    """
    kind1 = classify(first)
    kind2 = classify(second)
    out = {'ok': False, 'first_kind': kind1, 'second_kind': kind2,
           'move': (0.0, 0.0, 0.0), 'distance': 0.0, 'already': False,
           'mode': u'', 'reason': u''}
    if kind1 is None or kind2 is None:
        out['reason'] = u'one of the elements has no length to take a centreline from'
        return out
    if kind1 == HORIZONTAL and kind2 == HORIZONTAL:
        out['reason'] = (u'both are horizontal - click a vertical first to centre a run on it, '
                         u'or a horizontal first and then a vertical')
        return out

    if kind1 == VERTICAL and kind2 == VERTICAL:
        z = mid_z(second)
        target = xy_at_z(first, z)
        current = xy_at_z(second, z)
        move = (target[0] - current[0], target[1] - current[1])

    elif kind1 == VERTICAL:
        frame = plan_frame(second)
        z = mid_z(second)
        move = (0.0, 0.0)
        for _ in range(3):
            target = xy_at_z(first, z)
            move, along = offset_from_line(target, frame)
            z = z_along(second, frame, along)

    else:
        frame = plan_frame(first)
        z = mid_z(first)
        move = (0.0, 0.0)
        for _ in range(3):
            current = xy_at_z(second, z)
            offset, along = offset_from_line(current, frame)
            move = (-offset[0], -offset[1])
            z = z_along(first, frame, along)

    distance = math.hypot(move[0], move[1])
    out.update({'ok': True, 'move': (move[0], move[1], 0.0), 'distance': distance,
                'already': is_aligned(distance), 'mode': MODE_LABELS[(kind1, kind2)]})
    return out


def moved_by(before, after):
    """The largest distance either end point of an axis travelled."""
    if before is None or after is None:
        return 0.0
    worst = 0.0
    for a, b in zip(before, after):
        worst = max(worst, math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b))))
    return worst


def translate(axis, move):
    return tuple(tuple(p + m for p, m in zip(point, move)) for point in axis)
