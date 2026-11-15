# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - version, settings and geometry
#
# The whole of this module is plain Python plus the Revit
# API. Nothing in it touches WPF, so every rule in it can be
# bench tested under CPython with a stub API.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

import os
import math

__version__ = '5.5.0'

TOOL_NAME = u'System Offset'
RIBBON_NAME = u'RevoBIM System Offset'

# ---------------------------------------------------------
# Units. The model works in feet; everything the user sees
# is millimetres.
# ---------------------------------------------------------

MM_PER_FT = 304.8


def mm_to_ft(value):
    return float(value) / MM_PER_FT


def ft_to_mm(value):
    return float(value) * MM_PER_FT


# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------

MIN_SEGMENT_MM = 10.0      # shortest straight piece allowed
CONN_TOL_MM = 25.0         # connector search radius
ANGLE_STEP = 5.0           # bend angles are multiples of five degrees
PARALLEL_TOL = 1.0e-6

# Not settings. The house 5mm grid and a sensible floor, held
# here so the settings window stays down to the two things
# anybody actually changes.
ROUND_MM = 5.0
MIN_OFFSET_MM = 25.0

ALLOWED_ANGLES = (22.5, 30.0, 45.0, 60.0, 90.0)

DIRECTIONS = (u'up', u'down', u'left', u'right')


# ---------------------------------------------------------
# ElementId across releases
#
# .IntegerValue was deprecated in 2024 and removed in 2026.
# Everything goes through here; the bench check rejects a
# bare .IntegerValue anywhere else.
# ---------------------------------------------------------

def eid_value(element_id):
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


def to_text(value):
    if value is None:
        return u''
    try:
        if isinstance(value, unicode):  # noqa: F821  IronPython 2.7
            return value
    except NameError:
        pass
    try:
        return u'{0}'.format(value)
    except Exception:
        return u''


# ---------------------------------------------------------
# Settings
#
# Plain key=value text under %APPDATA%\RevoBIM\, not JSON -
# no dependency on a module whose availability varies with
# the IronPython engine, and it stays hand editable. A
# missing or damaged file falls back to the defaults key by
# key, and keys from an older version are ignored rather
# than breaking the load.
# ---------------------------------------------------------

SETTINGS_VERSION = 5

# Two settings, and the theme the header chip writes. Anything
# else the tool needs is a constant above - a setting nobody
# changes is a setting that only adds a way to get it wrong.
DEFAULTS = {
    'settings_version': to_text(SETTINGS_VERSION),
    'width_factor':     u'1.0',
    'angle':            u'45',
    'theme':            u'revit',
    # Clash Offset's own. Not in the Settings window - it is
    # set in that tool's own window, where the number can be
    # seen against the clash it applies to.
    'clash_clearance':  u'50',
    'clash_lead':       u'100',
}

# A key whose meaning or default changes needs a migration,
# not just a new default. v4 dropped the direction, distance
# mode and reporting keys, and the width factor has now moved
# twice - 2, then 3, then 1 - so a file written before each of
# those must not carry the old number in.
MIGRATIONS = {
    4: ('width_factor', 'angle'),
    5: ('width_factor',),
}


def settings_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path():
    return os.path.join(settings_dir(), 'system_offset.txt')


def _parse(text):
    found = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        # split on the FIRST '=' only, so a value may contain one
        key, value = line.split('=', 1)
        found[key.strip()] = value.strip()
    return found


def load_settings():
    values = dict(DEFAULTS)
    try:
        path = settings_path()
        if not os.path.isfile(path):
            return values
        handle = open(path, 'rb')
        try:
            raw = handle.read().decode('utf-8', 'replace')
        finally:
            handle.close()
        found = _parse(raw)
    except Exception:
        return values

    try:
        was = int(found.get('settings_version', '0') or '0')
    except Exception:
        was = 0

    reset = set()
    for version, keys in MIGRATIONS.items():
        if was < version:
            for key in keys:
                reset.add(key)

    for key in DEFAULTS:
        if key in reset:
            continue
        if key in found:
            values[key] = found[key]
    values['settings_version'] = to_text(SETTINGS_VERSION)
    return values


def save_settings(values):
    try:
        folder = settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        lines = [u'# RevoBIM System Offset settings',
                 u'# One key=value per line. Delete a line to take its default.']
        merged = dict(DEFAULTS)
        merged.update(values or {})
        merged['settings_version'] = to_text(SETTINGS_VERSION)
        for key in sorted(merged.keys()):
            lines.append(u'{0}={1}'.format(key, to_text(merged[key])))
        handle = open(settings_path(), 'wb')
        try:
            handle.write((u'\n'.join(lines) + u'\n').encode('utf-8'))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def as_bool(value):
    return to_text(value).strip().lower() in ('1', 'true', 'yes', 'on')


def as_float(value, fallback=0.0):
    try:
        return float(to_text(value).strip())
    except Exception:
        return float(fallback)


def snap_angle(value):
    """Bend angles are multiples of five degrees, held between
    the smallest and largest the tool offers."""
    try:
        number = float(value)
    except Exception:
        return 45.0
    number = round(number / ANGLE_STEP) * ANGLE_STEP
    if number < ALLOWED_ANGLES[0]:
        return ALLOWED_ANGLES[0]
    if number > 90.0:
        return 90.0
    return number


def round_to(value_mm, step_mm):
    """Round an offset distance up to the nearest step."""
    step = float(step_mm or 0)
    if step <= 0:
        return float(value_mm)
    return math.ceil(float(value_mm) / step) * step


# ---------------------------------------------------------
# The offset arithmetic
#
# For an offset of distance d at angle a, each bend eats
# d / tan(a) of run along the axis. At 90 degrees that is
# zero and the offset is square; at 45 degrees it is d, so
# the two clicks have to be at least 2d + MIN_SEGMENT apart.
# ---------------------------------------------------------

def run_back_mm(distance_mm, angle_deg):
    angle = float(angle_deg)
    if angle >= 90.0 - 1.0e-9:
        return 0.0
    radians = math.radians(angle)
    tangent = math.tan(radians)
    if abs(tangent) < PARALLEL_TOL:
        return 0.0
    return abs(float(distance_mm) / tangent)


def minimum_span_mm(distance_mm, angle_deg, min_segment_mm=MIN_SEGMENT_MM,
                    bends=2):
    """How far apart the two clicks have to be.

    Only the bends that turn ALONG the run eat into it. A jog
    turns out and back, so it pays twice; a break turns out and
    stops, so it pays once and has twice the room.
    """
    return bends * run_back_mm(distance_mm, angle_deg) + float(min_segment_mm)


def plan_offset(distance_mm, angle_deg, span_mm, min_segment_mm=MIN_SEGMENT_MM,
                bends=2):
    """Work out the whole offset, or say why it cannot be done.

    Returns a dict rather than raising, so the caller can put
    the shortfall in front of the user rather than failing
    silently. Pure arithmetic - no Revit in here at all.
    """
    distance = abs(float(distance_mm))
    angle = snap_angle(angle_deg)
    span = abs(float(span_mm))

    if distance <= 0.0:
        return {'ok': False, 'reason': u'The offset distance works out at zero.'}

    needed = minimum_span_mm(distance, angle, min_segment_mm, bends)
    # tan(45 degrees) is 0.9999999999999999, so a run with
    # exactly enough room comes out a fraction of a micron
    # short. Refusing on that is wrong.
    if span < needed - 1.0e-6:
        return {
            'ok': False,
            'reason': (u'The two clicks are {0:.0f}mm apart and a {1:.0f}mm '
                       u'offset at {2:.0f} degrees needs {3:.0f}mm. Move them '
                       u'{4:.0f}mm further apart, drop the offset, or use '
                       u'90 degree bends.').format(span, distance, angle,
                                                   needed, needed - span),
            'needed_mm': needed,
            'span_mm': span,
        }

    back = run_back_mm(distance, angle)
    return {
        'ok': True,
        'distance_mm': distance,
        'angle_deg': angle,
        'run_back_mm': back,
        'bends': bends,
        'middle_mm': span - bends * back,
        'span_mm': span,
        'square': angle >= 90.0 - 1.0e-9,
    }


def offset_distance_mm(settings, width_mm):
    """The distance the prompt opens with.

    A multiple of the service's own width or diameter, rounded
    up onto the 5mm grid and never below the floor. The prompt
    puts it in an editable box, so this is a starting point
    rather than a decision.
    """
    factor = as_float(settings.get('width_factor'), 1.0)
    raw = factor * float(width_mm or 0.0)
    if raw < MIN_OFFSET_MM:
        raw = MIN_OFFSET_MM
    return round_to(raw, ROUND_MM)


def max_offset_mm(span_mm, angle_deg, bends=2):
    """The largest offset the two clicks leave room for.

    Each turn along the run eats offset / tan(angle), and the
    piece between has to survive, so bends * d / tan(a) plus
    MIN_SEGMENT must fit inside the span. A square offset has
    no limit.
    """
    angle = snap_angle(angle_deg)
    if angle >= 90.0 - 1.0e-9:
        return None
    room = float(span_mm) - MIN_SEGMENT_MM
    if room <= 0.0:
        return 0.0
    return (room * math.tan(math.radians(angle))) / float(bends)


# A bend needs something to sit on at each end. Closer to the
# axis than STRAIGHT_TOL_MM and a click counts as straight on,
# so the length simply carries on with no bend at all.
MIN_LEG_MM = MIN_SEGMENT_MM
STRAIGHT_TOL_MM = 5.0


PARALLEL_DEG = 0.5


def axes_parallel(axes, tolerance_deg=PARALLEL_DEG):
    """Are these run directions all parallel to one another?

    Sign is ignored - two pipes running at each other are still
    parallel. Anything past the tolerance is reported rather
    than quietly banked, because a bank built from runs that
    are nearly parallel comes out wrong in a way that is very
    hard to see afterwards.
    """
    axes = [a for a in axes if a is not None]
    if len(axes) < 2:
        return True, 0.0
    limit = math.cos(math.radians(tolerance_deg))
    worst = 1.0
    first = axes[0]
    for other in axes[1:]:
        dot = abs(first.DotProduct(other))
        if dot < worst:
            worst = dot
    worst = max(-1.0, min(1.0, worst))
    return worst >= limit, math.degrees(math.acos(worst))


def intersect_in_plane(point_a, direction_a, point_b, direction_b, normal):
    """Where two lines in a plane cross.

    Returns the point, or None where they are parallel. Solved
    with the scalar triple product rather than by inverting a
    matrix, so it needs nothing but the three vector methods.
    """
    across = cross(direction_a, direction_b).DotProduct(normal)
    if abs(across) < PARALLEL_TOL:
        return None
    offset = point_b - point_a
    along = cross(offset, direction_b).DotProduct(normal) / across
    return point_a + direction_a.Multiply(along)


def cross(first, second):
    """A cross product from the methods every vector has.

    Revit's XYZ carries CrossProduct; a bench vector need not,
    and this keeps the geometry rules testable without one.
    """
    try:
        return first.CrossProduct(second)
    except Exception:
        pass
    return first.__class__(
        first.y * second.z - first.z * second.y,
        first.z * second.x - first.x * second.z,
        first.x * second.y - first.y * second.x)


# Below this a run counts as level and none of the slope
# work applies. 1:2000 is far flatter than any drainage.
FLAT_GRADE = 0.0005


def gradient(axis, up):
    """Rise per unit of PLAN length. None for a vertical run.

    Rise over plan run, not rise over slope length, because
    that is what a fall of 1:60 means and what has to be held
    when a route is set out in plan.
    """
    rise = axis.DotProduct(up)
    flat = axis - up.Multiply(rise)
    length = flat.GetLength()
    if length < PARALLEL_TOL:
        return None
    return rise / length


def is_sloped(grade):
    return grade is not None and abs(grade) > FLAT_GRADE


def with_fall(start, plan_point, up, grade):
    """Give a plan position its level, falling from a start.

    The clicks and the corners are all worked out in plan; this
    is what puts them back on the gradient afterwards, so every
    piece comes out at the run's own fall by construction
    rather than by being nudged into it.
    """
    across = plan_point - start
    across = across - up.Multiply(across.DotProduct(up))
    return start + across + up.Multiply(across.GetLength() * grade)


def jog_fall_shortfall(distance_mm, angle_deg, grade):
    """How far low a true-gradient jog would arrive.

    A jog out and back is longer in plan than the straight run
    it replaces, by 2d(1/sin - 1/tan). At a fixed gradient the
    extra length is extra fall, so a route that holds the
    gradient on every piece cannot come back to the run it left
    - it arrives low by this much, and no choice of span
    changes it.

    Which is why the jog keeps its two ends and its long middle
    exactly on gradient and lets the two short diagonals be
    slightly shallow, rather than the other way round.
    """
    if not is_sloped(grade):
        return 0.0
    angle = math.radians(snap_angle(angle_deg))
    if abs(math.sin(angle)) < PARALLEL_TOL:
        return 0.0
    extra = 2.0 * abs(distance_mm) * (1.0 / math.sin(angle)
                                      - 1.0 / math.tan(angle))
    return abs(grade) * extra


def describe_gradient(grade):
    """A fall as engineers write it."""
    if not is_sloped(grade):
        return u'level'
    return u'1:{0:.0f}'.format(1.0 / abs(grade))


def rise_step(start, plan_direction, up, height_mm, angle_deg, going_up):
    """Where a run ends after gaining a height at an angle.

    The plan run it takes to gain that height is
    height / tan(angle) - nothing at 90 degrees, which is a
    plain riser, and the same as the height at 45.

    Returns (top, direction).
    """
    angle = float(angle_deg or 45.0)
    rise_mm = abs(float(height_mm)) * (1.0 if going_up else -1.0)

    plan_mm = 0.0
    if angle < 90.0 - 1.0e-9:
        tangent = math.tan(math.radians(angle))
        if abs(tangent) > PARALLEL_TOL:
            plan_mm = abs(float(height_mm)) / tangent

    top = (start + plan_direction.Multiply(mm_to_ft(plan_mm))
           + up.Multiply(mm_to_ft(rise_mm)))
    span = top - start
    return top, span.Normalize()


def fit_level_change(total_mm, height_mm, angle_deg, lead_mm,
                     min_mm=MIN_LEG_MM):
    """Fit a run on, a rise and a landing into the room there is.

    The height is the point of the move, so it is never given
    up. Everything else bends to fit, in the order that costs
    least:

      1  use the run on as asked, if it fits
      2  shorten the run on, down to nothing
      3  steepen the angle, up to a square riser, which takes
         no run in plan at all

    Only a click with less than two short pieces' worth of room
    in it is refused, and by then there is genuinely nowhere to
    put a rise.

    Returns the numbers to build with, and what had to give.
    """
    total = float(total_mm)
    height = abs(float(height_mm))
    angle = snap_to_range(angle_deg)
    lead = max(0.0, float(lead_mm or 0.0))
    floor = float(min_mm)

    if total < 2.0 * floor:
        return {'ok': False,
                'reason': (u'The click is only {0:.0f}mm along the run, which '
                           u'is not enough to turn in at all. Click further '
                           u'along.').format(total)}

    changed = []
    run = rise_plan_run_mm(height, angle)

    # The rise itself does not fit: steepen it until it does.
    if run > total - 2.0 * floor + 1.0e-9:
        room = total - 2.0 * floor
        steeper = math.degrees(math.atan2(height, room))
        angle = min(90.0, steeper)
        run = rise_plan_run_mm(height, angle)
        changed.append(u'steepened to {0:.1f} degrees'.format(angle))

    spare = total - run
    if lead + floor > spare + 1.0e-9:
        lead = max(0.0, spare - floor)
        changed.append(u'ran on {0:.0f}mm instead'.format(lead))

    landing = spare - lead
    return {'ok': True, 'lead_mm': lead, 'angle_deg': angle,
            'rise_run_mm': run, 'landing_mm': landing, 'changed': changed}


def snap_to_range(angle_deg):
    try:
        value = float(angle_deg)
    except Exception:
        return 45.0
    return max(1.0, min(90.0, value))


def rise_plan_run_mm(height_mm, angle_deg):
    """How much run a rise eats, in plan."""
    angle = float(angle_deg or 45.0)
    if angle >= 90.0 - 1.0e-9:
        return 0.0
    tangent = math.tan(math.radians(angle))
    if abs(tangent) < PARALLEL_TOL:
        return 0.0
    return abs(float(height_mm)) / tangent


# What a clash should be walked around, by the shape of the
# thing in the way. The order is a preference, not a rule: a
# preferred way out that costs far more than another is given
# up in favour of the cheaper one.
ESCAPE_ORDER = {
    u'column':  (u'left', u'right', u'down', u'up'),
    u'beam':    (u'down', u'up', u'left', u'right'),
    u'slab':    (u'down', u'up', u'left', u'right'),
    u'wall':    (u'left', u'right', u'up', u'down'),
    u'service': (u'down', u'up', u'left', u'right'),
    u'':        (u'down', u'up', u'left', u'right'),
}

# How much dearer than the cheapest way out a preferred one may
# be and still be taken. Going round a column is the right
# answer right up until it costs four metres and going under it
# costs three hundred.
ESCAPE_TOLERANCE = 0.35


def span_along(points, origin, direction):
    """How far a set of points reaches, either way along a line.

    Returned in millimetres, relative to the origin. Duck typed
    on the three vector methods, so it is bench tested against
    plain vectors rather than against Revit.
    """
    if not points:
        return None
    reaches = [(point - origin).DotProduct(direction) for point in points]
    return ft_to_mm(min(reaches)), ft_to_mm(max(reaches))


def half_extent(points, centre, direction):
    """How far a service's own body sticks out, one way.

    Measured from its centreline in the direction it is about to
    move, off its real geometry, so a 600 x 300 duct is 150 when
    it goes up and 300 when it goes sideways. Taking the larger
    dimension both ways over-clears the narrow way by 150mm -
    safe, but it moves services further than they need to go and
    it is measurable, so it is measured.
    """
    reach = span_along(points, centre, direction)
    if reach is None:
        return None
    return max(0.0, reach[1])


def choose_escape(required, kind, tolerance=ESCAPE_TOLERANCE):
    """Which way to go round, and how far.

    required maps each of the four directions to the offset it
    would take, or None where that way is not available.

    The shape of the obstruction says what SHOULD be preferred;
    the numbers say whether that preference is affordable. A
    column is gone round, a beam is gone under - unless doing
    so costs far more than the alternative, in which case the
    cheaper way wins and the reason is reported.
    """
    viable = dict((key, value) for key, value in (required or {}).items()
                  if value is not None and value > 0.0)
    if not viable:
        return None

    cheapest = min(viable.values())
    limit = cheapest * (1.0 + float(tolerance)) + 1.0

    for key in ESCAPE_ORDER.get(kind, ESCAPE_ORDER[u'']):
        if key in viable and viable[key] <= limit:
            return {'direction': key, 'distance_mm': viable[key],
                    'preferred': True, 'cheapest_mm': cheapest}

    for key in sorted(viable.keys(), key=lambda k: viable[k]):
        return {'direction': key, 'distance_mm': viable[key],
                'preferred': False, 'cheapest_mm': cheapest}
    return None


def clash_cuts(along_min_mm, along_max_mm, distance_mm, angle_deg, lead_mm):
    """Where to cut, so the offset middle clears the obstruction.

    The middle of a jog does not start at the cut - it starts a
    bend's worth further in. So the cuts have to sit back by
    that bend, plus the clearance, or the sloping legs clip the
    very thing being avoided.
    """
    back = run_back_mm(distance_mm, angle_deg)
    return (float(along_min_mm) - float(lead_mm) - back,
            float(along_max_mm) + float(lead_mm) + back)


def halves_in_order(first_point, second_point, origin, direction):
    """Which of two pieces lies behind, and which ahead.

    Revit's BreakCurve returns "the new element" and does not
    say which side of the cut it is. Assuming it is the far
    half is how a duct ended up with its original still running
    the full length and the offset pieces overlapping it.

    Measure instead: whichever piece's midpoint sits further
    along the direction is the far one.
    """
    first = (first_point - origin).DotProduct(direction)
    second = (second_point - origin).DotProduct(direction)
    return (0, 1) if first <= second else (1, 0)


def travel_direction(axis, screen_right=None, screen_up=None):
    """Which way along a run counts as "forwards".

    A run's own axis points whichever way it happened to be
    drawn, so left and right cannot be taken from it: the same
    duct drawn the other way round swaps them. Forwards is
    therefore the way the run reads on screen - left to right,
    and bottom to top where it runs straight up the view.

    Duck typed, so it is bench tested against plain vectors.
    """
    for reference in (screen_right, screen_up):
        if reference is None:
            continue
        along = axis.DotProduct(reference)
        if abs(along) > 1.0e-6:
            return axis if along > 0 else axis.Negate()
    return axis


def side_of_travel(axis, up_world, screen_right=None, screen_up=None):
    """The vector to the right of somebody walking the run.

    Returns None where the run is vertical and there is no
    meaningful side to it.
    """
    forwards = travel_direction(axis, screen_right, screen_up)
    side = cross(forwards, up_world)
    if side.GetLength() < PARALLEL_TOL:
        return None
    return side.Normalize()


def offset_corner(corner, leg_in, leg_out, normal, lateral,
                  through_plane=0.0):
    """One corner of a route, offset sideways.

    Both legs are shifted square to THEMSELVES by the same
    distance and the corner is where the shifted legs cross.
    That is what keeps a bank evenly spaced: at a bend the
    corner has to move ALONG the run as well as across it, so
    the strand on the outside turns later than the one on the
    inside.

    Shifting every corner to the same station instead pulls the
    diagonals closer together than the straight legs by
    cos(angle) - 212mm where the straight legs are 300mm apart,
    at 45 degrees - and squashes them onto each other entirely
    at 90.
    """
    first = corner + cross(normal, leg_in).Multiply(lateral)
    second = corner + cross(normal, leg_out).Multiply(lateral)
    crossing = intersect_in_plane(first, leg_in, second, leg_out, normal)
    if crossing is None:
        crossing = first
    return crossing + normal.Multiply(through_plane)


def offset_end(point, leg, normal, lateral, through_plane=0.0):
    """A free end of a route, offset sideways."""
    return (point + cross(normal, leg).Multiply(lateral)
            + normal.Multiply(through_plane))


def bank_corners(corners, legs, normal, lateral, through_plane=0.0):
    """Every corner of a route, offset sideways.

    legs holds one direction more than corners: the leg into
    the first corner, then the leg out of each.
    """
    return [offset_corner(point, legs[index], legs[index + 1], normal,
                          lateral, through_plane)
            for index, point in enumerate(corners)]


def bank_split(offset, direction, sideways, normal):
    """Split a run's position in a bank into the two parts.

    lateral        within the plane the route turns in, which
                   is the part that needs the corners crossed
    through_plane  square out of it, which is a plain shift and
                   needs none of it
    """
    square = offset - direction.Multiply(offset.DotProduct(direction))
    return square.DotProduct(sideways), square.DotProduct(normal)


def strand_route(corner, target, leg_in, leg_out, normal, lateral,
                 through_plane):
    """One strand of a bank, beside the leader rather than on it.

    A bank cannot be routed by translating the whole route: two
    pipes side by side running east, translated 300mm north,
    are 300mm apart on the leg that runs east and EXACTLY ON
    TOP OF EACH OTHER on the leg that turns north. Spacing has
    to be measured square to each leg, which makes a strand a
    parallel OFFSET of the leader's route, not a copy of it.

    So each leg is shifted sideways by the same distance and
    the corner is where the shifted legs cross. The outer
    strand turns later than the inner one, which is what keeps
    the bank square across itself all the way round.

    lateral         how far to the side, in the routing plane
    through_plane   how far out of it - a stacked bank shifts
                    straight across and needs none of the above
    """
    return (offset_corner(corner, leg_in, leg_out, normal, lateral,
                          through_plane),
            offset_end(target, leg_out, normal, lateral, through_plane))


def plan_corner(anchor_start, direction, target, angle_deg=90.0,
                leg_mm=None):
    """Where the 90 degree corner goes, or why it cannot.

    anchor_start  the fixed end of the length being extended
    direction     the way that length runs
    target        the click, already on the right plane

    The corner is the click projected back onto the length's
    own axis, so the turn is exactly square by construction
    rather than by rounding to it.

    A corner BEHIND the current end is fine - it just shortens
    the length - so long as enough of it survives to hold its
    own joint. That is the real constraint, not "click forwards".

    Duck typed on DotProduct / Multiply / GetLength, so it runs
    against Revit's XYZ and against a plain vector on the bench.
    """
    angle = float(angle_deg or 90.0)
    reach = (target - anchor_start).DotProduct(direction)

    sideways = target - (anchor_start + direction.Multiply(reach))
    sideways_mm = ft_to_mm(sideways.GetLength())

    # With a length given, the click means less: it puts the
    # corner where it projects onto the run and says which side
    # to turn towards, and the new leg is then the length asked
    # for rather than however far the click happened to land.
    if leg_mm:
        kept_mm = ft_to_mm(reach)
        if kept_mm < MIN_LEG_MM:
            return {'ok': False, 'kept_mm': kept_mm,
                    'reason': _no_room(kept_mm, angle, 0.0)}
        corner = anchor_start + direction.Multiply(reach)
        if sideways_mm < STRAIGHT_TOL_MM:
            return {'ok': True, 'straight': True,
                    'corner': corner + direction.Multiply(mm_to_ft(leg_mm)),
                    'target': corner + direction.Multiply(mm_to_ft(leg_mm)),
                    'direction': direction, 'angle_deg': angle,
                    'kept_mm': kept_mm, 'leg_mm': float(leg_mm)}
        radians = math.radians(angle)
        turned = (direction.Multiply(math.cos(radians))
                  + sideways.Normalize().Multiply(math.sin(radians)))
        return {'ok': True, 'straight': False, 'corner': corner,
                'target': corner + turned.Multiply(mm_to_ft(leg_mm)),
                'direction': turned.Normalize(), 'angle_deg': angle,
                'kept_mm': kept_mm, 'leg_mm': float(leg_mm)}

    if sideways_mm < STRAIGHT_TOL_MM:
        kept_mm = ft_to_mm(reach)
        if kept_mm < MIN_LEG_MM:
            return {'ok': False, 'kept_mm': kept_mm,
                    'reason': _no_room(kept_mm, angle, 0.0)}
        return {'ok': True, 'straight': True, 'corner': target,
                'target': target, 'direction': direction,
                'angle_deg': angle, 'kept_mm': kept_mm, 'leg_mm': 0.0}

    if sideways_mm < MIN_LEG_MM:
        return {'ok': False, 'kept_mm': ft_to_mm(reach), 'leg_mm': sideways_mm,
                'reason': (u'That is only {0:.0f}mm off the run - too short a '
                           u'leg to bend into. Click further out, or straight '
                           u'along it.'.format(sideways_mm))}

    # A turn of less than a right angle has to start BEFORE the
    # click's own station, by sideways / tan(angle), or the leg
    # cannot arrive at the click. At 90 degrees that is nothing
    # and the corner sits square under the click, which is the
    # whole of the old behaviour.
    back_mm = 0.0
    if angle < 90.0 - 1.0e-9:
        tangent = math.tan(math.radians(angle))
        if abs(tangent) > PARALLEL_TOL:
            back_mm = sideways_mm / tangent

    corner = anchor_start + direction.Multiply(reach - mm_to_ft(back_mm))
    kept_mm = ft_to_mm(reach) - back_mm

    if kept_mm < MIN_LEG_MM:
        return {'ok': False, 'kept_mm': kept_mm, 'leg_mm': sideways_mm,
                'reason': _no_room(kept_mm, angle, back_mm)}

    leg = target - corner
    return {'ok': True, 'straight': False, 'corner': corner, 'target': target,
            'direction': leg.Normalize(), 'angle_deg': angle,
            'kept_mm': kept_mm, 'leg_mm': ft_to_mm(leg.GetLength())}


def _no_room(kept_mm, angle, back_mm):
    if back_mm > 0.0:
        return (u'A {0:.4g} degree bend has to start {1:.0f}mm before the '
                u'click to arrive at it, which leaves {2:.0f}mm of run - a '
                u'bend needs {3:.0f}mm to sit on. Click further along, or '
                u'take a squarer angle.'
                .format(angle, back_mm, kept_mm, MIN_LEG_MM))
    return (u'That corner would land {0:.0f}mm from the start of the length '
            u'it has to cut, and a bend needs at least {1:.0f}mm to sit on. '
            u'Click further along.'.format(kept_mm, MIN_LEG_MM))


def needs_reporting(records):
    """Whether anything is worth interrupting somebody for.

    A clean offset says nothing at all. Notes are not a reason
    to open a window - every successful offset produces a few,
    and counting them as things needing a look is what made the
    tool pop a report after every single run. Only a refusal or
    a real problem opens it.

    Plain logic on plain dicts, so it can be bench tested; the
    window itself only draws what this decides.
    """
    for record in records or ():
        if not record.get('ok'):
            return True
        if record.get('problems'):
            return True
    return False


def worth_showing(records):
    """Just the records that earned the window."""
    return [r for r in records or ()
            if not r.get('ok') or r.get('problems')]


def describe_run(distance_mm, angle_deg, direction):
    return u'{0:.0f}mm {1} at {2:.0f} degrees'.format(
        distance_mm, direction, angle_deg)
