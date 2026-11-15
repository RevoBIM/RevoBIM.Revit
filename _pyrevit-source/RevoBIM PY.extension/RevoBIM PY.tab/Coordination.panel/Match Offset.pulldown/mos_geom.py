# -*- coding: utf-8 -*-
"""RevoBIM Match Offset Slope - the geometry, with no Revit in it.

Everything that decides where a pipe ends up lives here as a plain function
over plain points, so the whole rule set runs under CPython in bench_logic.py.
The Revit side hands these functions numbers and does what it is told.

The datum is the crossing point of the two centrelines **in plan**, not the
main's mid point or either end. That is what makes it right on a sloping main:
the branch has to land where the two lines actually cross, and the main's own
fall decides the height there.
"""

import math

EPS = 1e-9
MM_PER_FT = 304.8


class Pt(object):
    """A point. Plain numbers, so the bench can make one without Revit."""

    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __repr__(self):
        return 'Pt({0:.4f}, {1:.4f}, {2:.4f})'.format(self.x, self.y, self.z)


def to_pt(xyz):
    """A Revit XYZ, or anything with X/Y/Z, as a Pt."""
    try:
        return Pt(xyz.X, xyz.Y, xyz.Z)
    except Exception:
        return Pt(xyz.x, xyz.y, xyz.z)


# ======================================================================
# lengths, directions and gradients
# ======================================================================

def plan_length(a, b):
    return math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2)


def length(a, b):
    return math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2 + (b.z - a.z) ** 2)


def plan_direction(a, b):
    """Unit direction in plan from a to b, or None for a vertical line."""
    dx, dy = b.x - a.x, b.y - a.y
    run = math.sqrt(dx * dx + dy * dy)
    if run < EPS:
        return None
    return (dx / run, dy / run)


def gradient(a, b):
    """Rise over plan run, signed along a to b. None when a is above b."""
    run = plan_length(a, b)
    if run < EPS:
        return None
    return (b.z - a.z) / run


def pitch_degrees(a, b):
    """How far off level a segment is, always positive."""
    run = plan_length(a, b)
    rise = abs(b.z - a.z)
    if run < EPS:
        return 90.0 if rise > EPS else 0.0
    return math.degrees(math.atan2(rise, run))


def one_in_n(grad):
    """A gradient as the number plumbers use. None for level."""
    if grad is None:
        return None
    if abs(grad) < 1e-7:
        return None
    return 1.0 / abs(grad)


def gradient_from_n(n):
    """1 in N back to a gradient magnitude. A silly N is treated as level."""
    try:
        value = float(n)
    except Exception:
        return 0.0
    if abs(value) < 1.0:
        return 0.0
    return 1.0 / abs(value)


def plan_angle_between(v1, v2):
    """The angle between two plan directions, 0 to 180 degrees."""
    if v1 is None or v2 is None:
        return 90.0
    dot = max(-1.0, min(1.0, v1[0] * v2[0] + v1[1] * v2[1]))
    return math.degrees(math.acos(dot))


def is_in_line(v1, v2, tolerance_deg=2.0):
    """Two directions that are the same line, either way round."""
    angle = plan_angle_between(v1, v2)
    return angle <= tolerance_deg or angle >= 180.0 - tolerance_deg


# ======================================================================
# where the two centrelines cross, in plan
# ======================================================================

PARALLEL = u"parallel"
VERTICAL = u"vertical"


def plan_intersection(a0, a1, b0, b1):
    """Where the two lines cross in plan, as parameters along each.

    Returns a dict with t_a, t_b and the crossing point in plan, or a dict
    carrying only 'refusal' when there is no answer. The parameters are not
    clamped: a t outside 0 to 1 is the apparent intersection, which is the
    whole point of the beyond-the-end case.
    """
    ax, ay = a1.x - a0.x, a1.y - a0.y
    bx, by = b1.x - b0.x, b1.y - b0.y
    if math.sqrt(ax * ax + ay * ay) < EPS:
        return {u"refusal": VERTICAL}
    if math.sqrt(bx * bx + by * by) < EPS:
        return {u"refusal": VERTICAL}

    denominator = ax * by - ay * bx
    if abs(denominator) < 1e-12:
        return {u"refusal": PARALLEL}

    dx, dy = b0.x - a0.x, b0.y - a0.y
    t_a = (dx * by - dy * bx) / denominator
    t_b = (dx * ay - dy * ax) / denominator
    return {
        u"t_a": t_a,
        u"t_b": t_b,
        u"x": a0.x + ax * t_a,
        u"y": a0.y + ay * t_a,
    }


def lateral_offset(a0, a1, point):
    """How far a point sits off a line, measured in plan.

    Two runs meant to be one run are drawn on the same line but rarely on
    it to the millimetre, so "are these in line" is a question about how far
    off rather than a yes or no.
    """
    direction = plan_direction(a0, a1)
    if direction is None:
        return None
    return abs((point.x - a0.x) * -direction[1] +
               (point.y - a0.y) * direction[0])


def parameter_along(a0, a1, point):
    """Where a point falls along a line in plan, as a fraction of it."""
    run = plan_length(a0, a1)
    if run < EPS:
        return None
    direction = plan_direction(a0, a1)
    return ((point.x - a0.x) * direction[0] +
            (point.y - a0.y) * direction[1]) / run


def nearer_end(a0, a1, point):
    """Which end of a line a point is nearest, in plan."""
    return a0 if plan_length(a0, point) <= plan_length(a1, point) else a1


def point_on_line(a0, a1, t):
    """The 3D point at parameter t along a line, extrapolated freely.

    Past t = 1 this is the main's own fall carried on beyond its end, which
    is exactly the height the branch has to reach for an apparent
    intersection.
    """
    return Pt(a0.x + (a1.x - a0.x) * t,
              a0.y + (a1.y - a0.y) * t,
              a0.z + (a1.z - a0.z) * t)


# ======================================================================
# what kind of junction this is
# ======================================================================

INSIDE = u"inside"
IN_LINE = u"in line"
AT_START = u"at start"
AT_END = u"at end"
BEFORE_START = u"before start"
BEYOND_END = u"beyond end"


def classify_main(t_a, main_plan_length, end_tolerance_ft):
    """Where along the main the crossing falls.

    An end tolerance rather than an exact comparison, because a crossing a
    millimetre inside the end is a bend in anybody's drawing and a tee that
    Revit will refuse to place.
    """
    if main_plan_length < EPS:
        return VERTICAL
    slack = end_tolerance_ft / main_plan_length
    if t_a < -slack:
        return BEFORE_START
    if t_a > 1.0 + slack:
        return BEYOND_END
    if t_a <= slack:
        return AT_START
    if t_a >= 1.0 - slack:
        return AT_END
    return INSIDE


EXTEND = u"extend"
TRIM = u"trim"
BEHIND = u"behind"


def classify_branch(t_b, end_tolerance_ft, branch_plan_length):
    """What the branch has to do to reach the crossing.

    The branch line is always oriented anchor to free end, so t_b is read
    from the end that is going to move: past 1 it stretches out to the main,
    between 0 and 1 the two cross in plan and it is trimmed back, and at or
    below 0 the crossing is behind the run's own anchor - the branch is
    pointing away from the main and there is nothing sensible to do.
    """
    if branch_plan_length < EPS:
        return VERTICAL
    slack = end_tolerance_ft / branch_plan_length
    if t_b <= slack:
        return BEHIND
    if t_b >= 1.0 - slack:
        return EXTEND
    return TRIM


# ======================================================================
# the gradient the branch is put on
# ======================================================================

TOWARDS = u"towards"
AWAY = u"away"
KEEP_DIRECTION = u"keep"

FROM_MAIN = u"main"
FIXED = u"fixed"
KEEP_SLOPE = u"keep"


def target_gradient(main_gradient, branch_gradient, source=FROM_MAIN,
                    direction=TOWARDS, fixed_n=80.0):
    """The gradient the branch's horizontal run is put on, along anchor to
    free end.

    Negative means falling towards the junction, which is what drainage
    wants and what the default asks for. "keep" hands back the branch's own
    gradient untouched, which is the tick cleared: elevation is matched and
    the slope is left alone.
    """
    if source == KEEP_SLOPE:
        return branch_gradient if branch_gradient is not None else 0.0

    if source == FIXED:
        size = gradient_from_n(fixed_n)
    else:
        size = abs(main_gradient) if main_gradient is not None else 0.0

    if direction == AWAY:
        return size
    if direction == KEEP_DIRECTION:
        if branch_gradient is not None and branch_gradient > 0:
            return size
        return -size
    return -size


def in_line_gradient(main_gradient, same_way, source=FROM_MAIN,
                     branch_gradient=None, fixed_n=80.0):
    """The gradient a run has to be on to carry another one on.

    Not the "falls towards the junction" rule: two pipes being made into one
    run have to fall the same way along the same line, and which way that is
    comes from the main, not from a setting. A branch pointing back along
    the main takes the opposite sign for the same physical fall.
    """
    if source == KEEP_SLOPE:
        return branch_gradient if branch_gradient is not None else 0.0
    if source == FIXED:
        size = gradient_from_n(fixed_n)
        if main_gradient is not None and main_gradient < 0:
            size = -size
    else:
        size = main_gradient if main_gradient is not None else 0.0
    return size if same_way else -size


def tilt_angle(now, target):
    """The rotation that turns one gradient into another.

    The axis is z cross v, where v is the run's plan direction towards the
    junction. Rotating v about that axis by a positive angle takes it
    downwards, so the angle is atan(now) minus atan(target) rather than the
    other way round - which is the sign that is easy to get backwards and
    impossible to spot by reading it.
    """
    if now is None:
        now = 0.0
    if target is None:
        target = 0.0
    return math.atan(now) - math.atan(target)


def tilt_axis(v):
    """z cross v, for a plan direction v."""
    if v is None:
        return (0.0, 0.0)
    return (-v[1], v[0])


def apply_tilt(anchor, point, angle, axis_unit):
    """Rotate a point about a horizontal axis through the anchor.

    Here so the bench can check the transform agrees with the angle the
    tool asks Revit for, rather than trusting that it does.
    """
    ux, uy = axis_unit[0], axis_unit[1]
    px = point.x - anchor.x
    py = point.y - anchor.y
    pz = point.z - anchor.z
    cos = math.cos(angle)
    sin = math.sin(angle)
    dot = ux * px + uy * py
    # Rodrigues, with the axis flat so its z is zero. The cross product
    # terms are the ones that decide which way the run tips, and getting
    # one of them backwards rotates by minus the angle - which still looks
    # like a tilt, just the wrong one. The bench checks the result against
    # the gradient tilt_angle was asked for rather than reading this.
    rx = px * cos + (uy * pz) * sin + ux * dot * (1 - cos)
    ry = py * cos + (-ux * pz) * sin + uy * dot * (1 - cos)
    rz = pz * cos + (ux * py - uy * px) * sin
    return Pt(anchor.x + rx, anchor.y + ry, anchor.z + rz)


# ======================================================================
# stretching the end pipe along its own axis
# ======================================================================

def stretch_to_plan_point(fixed_end, direction3, target_x, target_y):
    """The point on a ray whose plan position is the crossing point.

    The ray already carries the target gradient, so the z that comes back is
    the branch's own new fall carried out to the junction. Only the plan
    distance is solved for; the height falls out.
    """
    dx, dy, dz = direction3
    run = math.sqrt(dx * dx + dy * dy)
    if run < EPS:
        return None
    travel = ((target_x - fixed_end.x) * dx +
              (target_y - fixed_end.y) * dy) / run
    if abs(travel) < EPS:
        return None
    scale = travel / run
    return Pt(fixed_end.x + dx * scale,
              fixed_end.y + dy * scale,
              fixed_end.z + dz * scale)


def unit3(a, b):
    dx, dy, dz = b.x - a.x, b.y - a.y, b.z - a.z
    size = math.sqrt(dx * dx + dy * dy + dz * dz)
    if size < EPS:
        return None
    return (dx / size, dy / size, dz / size)


# ======================================================================
# 3D vectors, for orienting a fitting by hand
# ======================================================================
# Revit refuses NewTeeFitting whenever the branch is not square to the run,
# with "the angle between them is too small or too large" - so an angled
# junction has to be placed as a family instance and turned onto the three
# directions by hand. All of that turning is these functions, and it is here
# rather than in the Revit module so the bench can check it.

def v_sub(a, b):
    return (b.x - a.x, b.y - a.y, b.z - a.z)


def v_dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def v_cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def v_size(u):
    return math.sqrt(v_dot(u, u))


def v_unit(u):
    size = v_size(u)
    if size < EPS:
        return None
    return (u[0] / size, u[1] / size, u[2] / size)


def v_scale(u, factor):
    return (u[0] * factor, u[1] * factor, u[2] * factor)


def v_add(u, v):
    return (u[0] + v[0], u[1] + v[1], u[2] + v[2])


def angle_between(u, v):
    """The angle between two directions, 0 to 180 degrees."""
    a, b = v_unit(u), v_unit(v)
    if a is None or b is None:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, v_dot(a, b)))))


def rotate_vector(u, axis, angle):
    """Rodrigues, in full - the axis here is not flat."""
    k = v_unit(axis)
    if k is None or abs(angle) < EPS:
        return u
    cos, sin = math.cos(angle), math.sin(angle)
    return v_add(v_add(v_scale(u, cos), v_scale(v_cross(k, u), sin)),
                 v_scale(k, v_dot(k, u) * (1.0 - cos)))


def rotation_to(u, v):
    """The axis and angle that turn direction u onto direction v.

    Where the two are already opposite the cross product is nothing and any
    perpendicular axis will do, so one is made rather than the caller being
    handed a zero axis and a half turn it cannot apply.
    """
    a, b = v_unit(u), v_unit(v)
    if a is None or b is None:
        return None, 0.0
    dot = max(-1.0, min(1.0, v_dot(a, b)))
    if dot > 1.0 - 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    axis = v_unit(v_cross(a, b))
    if axis is None:
        axis = v_unit(v_cross(a, (0.0, 0.0, 1.0)))
        if axis is None:
            axis = v_unit(v_cross(a, (0.0, 1.0, 0.0)))
        return axis, math.pi
    return axis, math.acos(dot)


def spin_angle(u, v, about):
    """The angle about a given axis that best takes u onto v.

    Both are flattened onto the plane square to the axis first, because the
    component along the axis cannot be turned by turning about it and
    including it just makes the answer wrong.
    """
    k = v_unit(about)
    if k is None:
        return 0.0
    flat_u = v_unit(v_add(u, v_scale(k, -v_dot(k, u))))
    flat_v = v_unit(v_add(v, v_scale(k, -v_dot(k, v))))
    if flat_u is None or flat_v is None:
        return 0.0
    cos = max(-1.0, min(1.0, v_dot(flat_u, flat_v)))
    angle = math.acos(cos)
    if v_dot(k, v_cross(flat_u, flat_v)) < 0:
        angle = -angle
    return angle


def orientation_for(from_run, from_branch, to_run, to_branch):
    """Two turns that put a fitting's own axes onto the ones it has to meet.

    First swing the run axis onto the main, then spin about the main until
    the branch axis lines up. Returns (axis, angle, axis, angle) and the
    angle the branch is left off by, which is what decides whether the
    family suits the junction at all.
    """
    axis_one, angle_one = rotation_to(from_run, to_run)
    branch = rotate_vector(from_branch, axis_one, angle_one) \
        if axis_one is not None else from_branch
    axis_two = v_unit(to_run)
    angle_two = spin_angle(branch, to_branch, axis_two)
    left = rotate_vector(branch, axis_two, angle_two)
    return (axis_one, angle_one, axis_two, angle_two,
            angle_between(left, to_branch))


def square_junction(crossing, main_dir, branch_dir, stub):
    """Where to put a square tee and a bend so an angled branch can meet it.

    Revit will only ever place a tee square to the run, so an angled branch
    is brought in the way a drainage layout actually does it: the tee slides
    a little way along the main, a short stub runs square out of it, and a
    bend turns the branch into the stub.

    branch_dir is the way the branch travels towards the crossing. Returns
    (tee point on the main, bend point on the branch line), both exact: the
    bend point is on the branch's own centreline so the run it was just put
    on does not have to move again, and the stub is square to the main in
    three dimensions, not just in plan.
    """
    along = v_dot(main_dir, branch_dir)
    across = v_add(branch_dir, v_scale(main_dir, -along))
    size = v_size(across)
    if size < 1e-9:
        return None, None
    reach = float(stub) / size
    tee = Pt(crossing.x + main_dir[0] * (-along * reach),
             crossing.y + main_dir[1] * (-along * reach),
             crossing.z + main_dir[2] * (-along * reach))
    bend = Pt(crossing.x - branch_dir[0] * reach,
              crossing.y - branch_dir[1] * reach,
              crossing.z - branch_dir[2] * reach)
    return tee, bend


UPSTREAM_FIRST = 0
UPSTREAM_SECOND = 1
UPSTREAM_UNKNOWN = -1


def upstream_of(first_end, second_end, tolerance_ft=1e-6):
    """Which of a main's two ends water comes from: the higher one.

    Drainage falls, so the higher end is upstream. On a level main there is
    no answer from the geometry and the caller has to fall back on
    something else.
    """
    if abs(first_end.z - second_end.z) <= tolerance_ft:
        return UPSTREAM_UNKNOWN
    return UPSTREAM_FIRST if first_end.z > second_end.z else UPSTREAM_SECOND


def sweeps_with_the_flow(run_to_branch_angle, run_is_upstream):
    """Whether a swept junction placed this way round faces the flow.

    A swept junction's branch arm leans back towards where the water comes
    from, so its arm makes the acute angle with the run connector on the
    upstream side and the obtuse one with the connector downstream. Put it
    on the other way round and the branch merges against the flow: it still
    joins, it is still the right size, and it is wrong.

    This is the one thing about a junction that its three connector
    directions do not pin down on their own, which is why it has to be
    asked separately rather than falling out of the geometry.
    """
    acute = run_to_branch_angle <= 90.0
    return acute == bool(run_is_upstream)


def branch_arrives_with_the_flow(main_dir, branch_dir):
    """Whether the branch is already heading downstream when it arrives.

    A branch arriving against the flow cannot be swept in at all - it wants
    a junction facing the other way, which is a different fitting and a
    different piece of design.
    """
    return v_dot(main_dir, branch_dir) > 0


def closest_point_between(p1, d1, p2, d2):
    """Where two lines meet, or the middle of where they come nearest.

    A lateral's branch axis meets its run axis somewhere along the run, not
    at the family's origin, so this is what the fitting has to be registered
    on rather than its insertion point.
    """
    u, v = v_unit(d1), v_unit(d2)
    if u is None or v is None:
        return p1
    w0 = (p1.x - p2.x, p1.y - p2.y, p1.z - p2.z)
    a, b, c = v_dot(u, u), v_dot(u, v), v_dot(v, v)
    d, e = v_dot(u, w0), v_dot(v, w0)
    denominator = a * c - b * b
    if abs(denominator) < 1e-10:
        return p1
    s = (b * e - c * d) / denominator
    t = (a * e - b * d) / denominator
    first = (p1.x + u[0] * s, p1.y + u[1] * s, p1.z + u[2] * s)
    second = (p2.x + v[0] * t, p2.y + v[1] * t, p2.z + v[2] * t)
    return Pt((first[0] + second[0]) / 2.0,
              (first[1] + second[1]) / 2.0,
              (first[2] + second[2]) / 2.0)


# ======================================================================
# the whole plan, worked out before anything is touched
# ======================================================================

TEE = u"tee"
BEND = u"bend"
UNION = u"union"
NONE = u"none"


class SlopePlan(object):
    """What the tool is about to do, and why - decided from numbers only."""

    def __init__(self):
        self.ok = False
        self.refusal = u""
        self.main_gradient = None
        self.branch_gradient = None
        self.target_gradient = 0.0
        self.tilt = 0.0
        self.axis = (0.0, 0.0)
        self.crossing = None
        self.main_case = u""
        self.branch_case = u""
        self.junction = NONE
        self.extends_main = False
        self.plan_angle = 0.0
        self.t_a = 0.0
        self.t_b = 0.0
        self.lateral = 0.0


def build_in_line_plan(main_start, main_end, anchor, free_end, source,
                       fixed_n, end_tolerance_ft, main_end_free,
                       lateral_tolerance_ft):
    """Two runs on the same line at different heights, made into one run.

    There is no crossing to work to - the lines never meet in plan because
    they are the same line - so the point to work to is the main's own free
    end, and the fall to work to is the main's carried on through it.
    """
    plan = SlopePlan()
    plan.main_case = IN_LINE

    v_main = plan_direction(main_start, main_end)
    v_branch = plan_direction(anchor, free_end)
    plan.plan_angle = plan_angle_between(v_main, v_branch)

    off = max(lateral_offset(main_start, main_end, anchor) or 0.0,
              lateral_offset(main_start, main_end, free_end) or 0.0)
    plan.lateral = off
    if off > lateral_tolerance_ft:
        plan.refusal = u"side by side"
        return plan

    if not main_end_free:
        plan.refusal = u"main end connected"
        return plan

    meeting = nearer_end(main_start, main_end, free_end)
    plan.crossing = Pt(meeting.x, meeting.y, meeting.z)
    plan.t_a = 0.0 if meeting is main_start else 1.0

    branch_run = plan_length(anchor, free_end)
    t_b = parameter_along(anchor, free_end, plan.crossing)
    if t_b is None:
        plan.refusal = VERTICAL
        return plan
    plan.t_b = t_b
    plan.branch_case = classify_branch(t_b, end_tolerance_ft, branch_run)
    if plan.branch_case == BEHIND:
        plan.refusal = BEHIND
        return plan

    plan.main_gradient = gradient(main_start, main_end)
    plan.branch_gradient = gradient(anchor, free_end)
    same_way = (v_dot((v_main[0], v_main[1], 0.0),
                      (v_branch[0], v_branch[1], 0.0)) > 0) \
        if (v_main is not None and v_branch is not None) else True
    plan.target_gradient = in_line_gradient(
        plan.main_gradient, same_way, source, plan.branch_gradient, fixed_n)
    plan.tilt = tilt_angle(plan.branch_gradient, plan.target_gradient)
    plan.axis = tilt_axis(v_branch)
    plan.junction = UNION
    plan.ok = True
    return plan


def build_plan(main_start, main_end, anchor, free_end,
               source=FROM_MAIN, direction=TOWARDS, fixed_n=80.0,
               end_tolerance_ft=1.0 / MM_PER_FT,
               allow_apparent=True, main_end_free=False,
               in_line_tolerance_deg=2.0, allow_in_line=True,
               lateral_tolerance_ft=50.0 / MM_PER_FT):
    """Work the whole move out before touching the model.

    main_start / main_end are the main's centreline. anchor / free_end are
    the branch's end pipe, oriented so free_end is the one that moves.
    """
    plan = SlopePlan()

    crossing = plan_intersection(main_start, main_end, anchor, free_end)
    if u"refusal" in crossing:
        # Two runs on the same line are parallel, which is the one kind of
        # parallel worth doing something about: they are meant to be one
        # run at one fall, and there is nothing to intersect because there
        # is nothing to intersect with.
        if crossing[u"refusal"] == PARALLEL and allow_in_line and \
                is_in_line(plan_direction(main_start, main_end),
                           plan_direction(anchor, free_end),
                           in_line_tolerance_deg):
            return build_in_line_plan(
                main_start, main_end, anchor, free_end, source, fixed_n,
                end_tolerance_ft, main_end_free, lateral_tolerance_ft)
        plan.refusal = crossing[u"refusal"]
        return plan

    plan.t_a = crossing[u"t_a"]
    plan.t_b = crossing[u"t_b"]
    plan.crossing = point_on_line(main_start, main_end, plan.t_a)

    main_run = plan_length(main_start, main_end)
    branch_run = plan_length(anchor, free_end)
    plan.main_case = classify_main(plan.t_a, main_run, end_tolerance_ft)
    plan.branch_case = classify_branch(plan.t_b, end_tolerance_ft, branch_run)

    v_main = plan_direction(main_start, main_end)
    v_branch = plan_direction(anchor, free_end)
    plan.plan_angle = plan_angle_between(v_main, v_branch)

    if plan.main_case == VERTICAL or plan.branch_case == VERTICAL:
        plan.refusal = VERTICAL
        return plan
    if plan.branch_case == BEHIND:
        plan.refusal = BEHIND
        return plan

    beyond = plan.main_case in (BEFORE_START, BEYOND_END)
    if beyond:
        if not allow_apparent:
            plan.refusal = u"apparent"
            return plan
        if not main_end_free:
            plan.refusal = u"main end connected"
            return plan
        plan.extends_main = True

    plan.main_gradient = gradient(main_start, main_end)
    plan.branch_gradient = gradient(anchor, free_end)
    plan.target_gradient = target_gradient(
        plan.main_gradient, plan.branch_gradient, source, direction, fixed_n)
    plan.tilt = tilt_angle(plan.branch_gradient, plan.target_gradient)
    plan.axis = tilt_axis(v_branch)

    if beyond or plan.main_case in (AT_START, AT_END):
        plan.junction = UNION if is_in_line(
            v_main, v_branch, in_line_tolerance_deg) else BEND
    else:
        plan.junction = TEE

    plan.ok = True
    return plan


REFUSAL_TEXT = {
    PARALLEL: u"the two pipes are parallel in plan but not on the same line, "
              u"so they never cross and cannot be made into one run",
    u"side by side": u"the two runs are on nearly the same line but too far "
                     u"apart in plan to be joined end to end - move one onto "
                     u"the other's line first, or widen the in-line tolerance "
                     u"in Settings",
    VERTICAL: u"one of the pipes is vertical in plan - pick a horizontal run",
    BEHIND: u"the branch points away from the main, so the crossing is "
            u"behind its own run",
    u"apparent": u"the crossing falls past the end of the main, and "
                 u"apparent intersections are turned off in Settings",
    u"main end connected": u"the crossing falls past the end of the main and "
                           u"that end already has something joined to it, so "
                           u"there is nowhere to extend it to",
}


def refusal_text(key):
    return REFUSAL_TEXT.get(key, key)
