# -*- coding: utf-8 -*-
"""RevoBIM Tag Tidy - the layout engine.

Deliberately free of any Revit or .NET import, so every decision the tool
makes can be bench tested under plain CPython.

Units and axes
--------------
Everything in here is in **paper millimetres** in the view's own flat frame:
u runs along View.RightDirection and v along View.UpDirection.  tidy_ops
converts model feet to this frame (and back) with the view scale, so a 2mm gap
is 2mm on the sheet at every scale, and a rotated view behaves exactly like a
square one.

What a layout is
----------------
Tags are grouped into clusters by how close their targets are.  Each cluster
becomes one column beside its targets: tags stacked one under another with a
fixed paper gap between their real outlines, aligned on the edge facing the
leaders.  Each leader leaves its tag horizontally at the tag's vertical middle
(the shoulder), then turns and runs at a fixed angle to its target (the leg).

The layout is a pure function of the targets, the tag sizes and the obstacles.
It never looks at where the tags currently are, which is what makes running the
tool twice a no-op.

Tag Tidy is the RevoBIM PY build of Sam BIM Tag Stack 1.1.0: the same engine,
in the RevoBIM house style (Revit-matched dark and light palettes following
the canvas, shrink-to-taskbar drawer on every window, settings and logs under
%APPDATA%\\RevoBIM).  The window drawer's arithmetic and its controller live
here too, free of WPF, so the bench can drive them with a fake timer.
"""

import math
import os

__version__ = "1.0.0"
BASED_ON = "Sam BIM Tag Stack 1.1.0"

TOOL_NAME = "Tag Tidy"
RIBBON_NAME = "RevoBIM Tag Tidy"

# Revit's internal length unit is the decimal foot on every release.
MM_PER_FOOT = 304.8

EPS = 1e-9

SETTINGS_VERSION = "1"

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "theme": "follow",           # follow (Revit's canvas) | dark | light
    "debug": "1",                # write tag_tidy_debug.txt after every run
    # the column
    "side": "auto",              # auto | left | right | point
    "align": "leader",           # leader | left
    "gap_mm": "2",
    "min_shoulder_mm": "3",
    "leg_angle": "45",           # 30 | 45 | 60 | 90 | free
    "column_clear_mm": "3",
    "cluster_mm": "60",
    "reach_mm": "30",
    "keep_single": "1",
    # clash avoidance
    "clearance_mm": "1",
    "slot_depth": "3",
    "column_step_mm": "4",
    "max_shift_mm": "40",
    "second_column": "1",
    "budget_s": "2",
    "obs_annotation": "1",
    "obs_pipes": "1",
    "obs_ducts": "1",
    "obs_trays": "1",
    "obs_conduit": "1",
    "obs_walls": "1",
    "obs_grids": "1",
    "obs_other": "0",
    "obs_links": "0",
    # what it runs on
    "include_spatial_tags": "0",
    "prompt_when_empty": "1",
    "no_leader": "switch_on",    # switch_on | skip
    "pinned": "unpin",           # unpin | skip
    "leader_end": "keep",        # keep | free
    # reporting
    "preview": "always",         # always | needed | never
}

CHOICES = {
    "theme": ("follow", "dark", "light"),
    "debug": ("0", "1"),
    "side": ("auto", "left", "right", "point"),
    "align": ("leader", "left"),
    "leg_angle": ("30", "45", "60", "90", "free"),
    "no_leader": ("switch_on", "skip"),
    "pinned": ("unpin", "skip"),
    "leader_end": ("keep", "free"),
    "preview": ("always", "needed", "never"),
}

# number settings: (smallest allowed, largest allowed)
NUMBERS = {
    "gap_mm": (0.0, 50.0),
    "min_shoulder_mm": (0.0, 100.0),
    "column_clear_mm": (0.0, 100.0),
    "cluster_mm": (0.0, 10000.0),
    "reach_mm": (5.0, 1000.0),
    "clearance_mm": (0.0, 20.0),
    "slot_depth": (0.0, 10.0),
    "column_step_mm": (0.5, 100.0),
    "max_shift_mm": (0.0, 1000.0),
    "budget_s": (0.2, 30.0),
}

MIGRATIONS = {}


# ============================================================================
# settings, as plain key=value text
# ============================================================================

def settings_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), "tag_tidy.txt")


def log_path():
    return os.path.join(settings_dir(), "tag_tidy_last_error.txt")


def debug_path():
    return os.path.join(settings_dir(), "tag_tidy_debug.txt")


def write_debug(cfg, lines, path=None):
    """The run's report as plain text, for sending back when something looks
    wrong.  On by default; never allowed to take the tool down."""
    if not as_bool(cfg, "debug"):
        return None
    path = path or debug_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        body = ["RevoBIM Tag Tidy v{0} ({1})".format(__version__, BASED_ON)]
        body.extend(str(line) for line in lines)
        handle = open(path, "w")
        try:
            handle.write("\n".join(body) + "\n")
        finally:
            handle.close()
        return path
    except Exception:
        return None


def _number_ok(key, value):
    try:
        number = float(value)
    except Exception:
        return False
    low, high = NUMBERS[key]
    return low <= number <= high


def load_settings(path=None):
    """Defaults, overlaid key by key with whatever the file actually holds.

    A missing or damaged file falls back to the defaults key by key; unknown
    keys, values outside their choices and numbers outside their range are
    ignored rather than breaking the load.
    """
    cfg = dict(DEFAULTS)
    path = path or settings_path()
    try:
        handle = open(path, "r")
        try:
            lines = handle.read().splitlines()
        finally:
            handle.close()
    except Exception:
        return cfg

    raw = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip()

    was = raw.get("settings_version", "0")
    reset = set()
    if was != SETTINGS_VERSION:
        for version, keys in MIGRATIONS.items():
            if _version_number(was) < _version_number(version):
                reset.update(keys)

    for key, value in raw.items():
        if key not in DEFAULTS or key in reset:
            continue
        if key in CHOICES and value not in CHOICES[key]:
            continue
        if key in NUMBERS and not _number_ok(key, value):
            continue
        cfg[key] = value

    cfg["settings_version"] = SETTINGS_VERSION
    return cfg


def _version_number(text):
    try:
        return int(text)
    except Exception:
        return 0


def save_settings(cfg, path=None):
    path = path or settings_path()
    folder = os.path.dirname(path)
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    body = ["# RevoBIM PY - Tag Tidy settings"]
    for key in sorted(DEFAULTS.keys()):
        body.append("{0}={1}".format(key, cfg.get(key, DEFAULTS[key])))
    handle = open(path, "w")
    try:
        handle.write("\n".join(body) + "\n")
    finally:
        handle.close()
    return path


def as_bool(cfg, key):
    return str(cfg.get(key, DEFAULTS.get(key, "0"))).strip() in (
        "1", "true", "True", "yes", "on")


def as_float(cfg, key):
    try:
        value = float(str(cfg.get(key, DEFAULTS.get(key, "0"))).strip())
    except Exception:
        value = float(DEFAULTS.get(key, "0"))
    if key in NUMBERS:
        low, high = NUMBERS[key]
        if value < low or value > high:
            value = float(DEFAULTS[key])
    return value


# ============================================================================
# units and the view's own frame
# ============================================================================

def mm_to_ft(mm):
    return float(mm) / MM_PER_FOOT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FOOT


class Frame(object):
    """The view's flat frame, on plain (x, y, z) tuples.

    to_paper turns a model point (feet) into (u, v) paper millimetres measured
    from the view origin; to_model goes back, at a given depth along the view
    direction, so a moved tag keeps the depth it had.
    """

    def __init__(self, origin, right, up, scale):
        self.origin = tuple(float(c) for c in origin)
        self.right = _unit3(right)
        self.up = _unit3(up)
        self.depth = _unit3(_cross3(self.right, self.up))
        self.scale = float(scale) if scale and float(scale) > 0 else 100.0
        self.k = MM_PER_FOOT / self.scale   # paper mm per model foot

    def to_paper(self, point):
        rel = _sub3(point, self.origin)
        return (_dot3(rel, self.right) * self.k, _dot3(rel, self.up) * self.k)

    def depth_of(self, point):
        return _dot3(_sub3(point, self.origin), self.depth)

    def to_model(self, u, v, depth=0.0):
        uf = float(u) / self.k
        vf = float(v) / self.k
        return (self.origin[0] + self.right[0] * uf + self.up[0] * vf + self.depth[0] * depth,
                self.origin[1] + self.right[1] * uf + self.up[1] * vf + self.depth[1] * depth,
                self.origin[2] + self.right[2] * uf + self.up[2] * vf + self.depth[2] * depth)

    def length_to_paper(self, feet):
        return float(feet) * self.k


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit3(a):
    size = math.sqrt(_dot3(a, a))
    if size < EPS:
        return (1.0, 0.0, 0.0)
    return (a[0] / size, a[1] / size, a[2] / size)


# ============================================================================
# 2D geometry
# ============================================================================

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def box_norm(box):
    return (min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3]))


def box_grow(box, d):
    return (box[0] - d, box[1] - d, box[2] + d, box[3] + d)


def box_of_points(points):
    us = [p[0] for p in points]
    vs = [p[1] for p in points]
    return (min(us), min(vs), max(us), max(vs))


def box_overlap(a, b, tol=0.0):
    """True when the two boxes share an area more than tol deep.  Boxes that
    only touch along an edge do not overlap."""
    return (a[0] < b[2] - tol and b[0] < a[2] - tol and
            a[1] < b[3] - tol and b[1] < a[3] - tol)


def box_inside(inner, outer, tol=1e-6):
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and
            inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def point_in_box(p, box):
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def point_segment_distance(p, a, b):
    ab = sub(b, a)
    size = dot(ab, ab)
    if size < EPS:
        return dist(p, a)
    t = dot(sub(p, a), ab) / size
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return dist(p, (a[0] + ab[0] * t, a[1] + ab[1] * t))


def _orient(a, b, c):
    value = cross(sub(b, a), sub(c, a))
    if abs(value) < 1e-12:
        return 0
    return 1 if value > 0 else -1


def _on_segment(a, b, p):
    return (min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9 and
            min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9)


def segments_intersect(p1, p2, q1, q2):
    """True when the two segments share any point, touching included.
    Zero-length segments are points and collinear overlaps count."""
    o1 = _orient(p1, p2, q1)
    o2 = _orient(p1, p2, q2)
    o3 = _orient(q1, q2, p1)
    o4 = _orient(q1, q2, p2)
    if o1 != o2 and o3 != o4 and o1 != 0 and o2 != 0 and o3 != 0 and o4 != 0:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1) and _point_near_line(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, p2, q2) and _point_near_line(p1, p2, q2):
        return True
    if o3 == 0 and _on_segment(q1, q2, p1) and _point_near_line(q1, q2, p1):
        return True
    if o4 == 0 and _on_segment(q1, q2, p2) and _point_near_line(q1, q2, p2):
        return True
    if o1 != o2 and o3 != o4:
        # one endpoint lies on the other line but strictly inside: a T junction
        return True
    return False


def _point_near_line(a, b, p):
    return point_segment_distance(p, a, b) < 1e-7


def segment_distance(p1, p2, q1, q2):
    if segments_intersect(p1, p2, q1, q2):
        return 0.0
    return min(point_segment_distance(p1, q1, q2), point_segment_distance(p2, q1, q2),
               point_segment_distance(q1, p1, p2), point_segment_distance(q2, p1, p2))


def segment_box_intersects(p, q, box):
    """Liang-Barsky: True when any part of the segment lies in the box,
    touching the edge included."""
    x0, y0 = p
    dx = q[0] - x0
    dy = q[1] - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - box[0]), (dx, box[2] - x0),
                   (-dy, y0 - box[1]), (dy, box[3] - y0)):
        if abs(pp) < EPS:
            if qq < 0:
                return False
            continue
        r = qq / pp
        if pp < 0:
            if r > t1:
                return False
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return False
            if r < t1:
                t1 = r
    return t0 <= t1


def point_box_distance(p, box):
    du = max(box[0] - p[0], 0.0, p[0] - box[2])
    dv = max(box[1] - p[1], 0.0, p[1] - box[3])
    return math.sqrt(du * du + dv * dv)


def segment_box_distance(p, q, box):
    if segment_box_intersects(p, q, box):
        return 0.0
    corners = ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))
    best = min(point_box_distance(p, box), point_box_distance(q, box))
    for c in corners:
        best = min(best, point_segment_distance(c, p, q))
    return best


def trim_end(a, b, amount):
    """The segment a-b with `amount` taken off its b end, or None if that
    leaves nothing."""
    size = dist(a, b)
    if size <= amount + EPS:
        return None
    t = (size - amount) / size
    return (a, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))


# ============================================================================
# obstacles and the spatial grid
# ============================================================================

class Obstacle(object):
    """Something in the view a tag or a leader must keep off.

    kind "box": geom is (u0, v0, u1, v1).
    kind "seg": geom is (p, q) and radius is half its drawn thickness; a pipe
    seen end on is a seg of zero length, which is a disc.
    hard obstacles (annotation, things already placed) must never be hit; soft
    ones (model elements) may be crossed by a leader at a cost.
    """

    def __init__(self, kind, geom, hard, label, key=None, radius=0.0, group="annotation"):
        self.kind = kind
        self.hard = bool(hard)
        self.label = label
        self.key = key
        self.radius = float(radius)
        self.group = group
        if kind == "box":
            self.geom = box_norm(geom)
        else:
            self.geom = (tuple(geom[0]), tuple(geom[1]))

    def bbox(self):
        if self.kind == "box":
            return self.geom
        return box_grow(box_of_points(self.geom), self.radius)

    def touches_box(self, box):
        if self.kind == "box":
            return box_overlap(self.geom, box)
        p, q = self.geom
        return segment_box_distance(p, q, box) < self.radius - 1e-9 or (
            self.radius <= 0.0 and segment_box_intersects(p, q, box_grow(box, -0.05)))

    def touches_segment(self, a, b):
        if self.kind == "box":
            return segment_box_intersects(a, b, box_grow(self.geom, -0.05))
        p, q = self.geom
        if self.radius > 0.0:
            return segment_distance(a, b, p, q) < self.radius - 1e-9
        return segments_intersect(a, b, p, q)


class Grid(object):
    """A uniform grid of cells, so a clash test only looks at what is near."""

    BIG = 4000  # an item spanning more cells than this goes in a short list

    def __init__(self, cell=10.0):
        self.cell = float(cell)
        self.cells = {}
        self.items = []
        self.big = []

    def _range(self, box):
        c = self.cell
        return (int(math.floor(box[0] / c)), int(math.floor(box[1] / c)),
                int(math.floor(box[2] / c)), int(math.floor(box[3] / c)))

    def add(self, item):
        index = len(self.items)
        self.items.append(item)
        i0, j0, i1, j1 = self._range(item.bbox())
        if (i1 - i0 + 1) * (j1 - j0 + 1) > self.BIG:
            self.big.append(index)
            return
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                self.cells.setdefault((i, j), []).append(index)

    def query(self, box):
        found = set(self.big)
        i0, j0, i1, j1 = self._range(box)
        if (i1 - i0 + 1) * (j1 - j0 + 1) > self.BIG:
            return [self.items[k] for k in range(len(self.items))]
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                bucket = self.cells.get((i, j))
                if bucket:
                    found.update(bucket)
        return [self.items[k] for k in sorted(found)]


# ============================================================================
# the parameters, taken from the settings
# ============================================================================

class Params(object):

    def __init__(self, **values):
        self.gap = 2.0
        self.min_shoulder = 3.0
        self.angle = "45"
        self.column_clear = 3.0
        self.cluster = 60.0
        self.reach = 30.0           # furthest a tag lines up from its target
        self.keep_single = True     # a lone tag already clear stays put
        self.clearance = 1.0
        self.slot_depth = 3
        self.column_step = 4.0
        self.max_shift = 40.0
        self.second_column = True
        self.side = "auto"
        self.align = "leader"
        self.budget = 2.0
        self.straight_tol = 0.5      # a leg flatter than this is drawn straight
        self.end_allow = 2.0         # leader may touch things this close to its end
        self.shared_anchor = 0.5     # two leaders ending this close share a target
        # the cost function
        self.w_hard = 1000.0
        self.w_soft_tag = 30.0
        self.w_soft_leader = 6.0
        self.w_length = 0.05
        self.w_height = 0.02
        self.w_columns = 40.0
        for key, value in values.items():
            setattr(self, key, value)

    @classmethod
    def from_cfg(cls, cfg):
        return cls(
            gap=as_float(cfg, "gap_mm"),
            min_shoulder=as_float(cfg, "min_shoulder_mm"),
            angle=cfg.get("leg_angle", "45") if cfg.get("leg_angle") in CHOICES["leg_angle"] else "45",
            column_clear=as_float(cfg, "column_clear_mm"),
            cluster=as_float(cfg, "cluster_mm"),
            reach=as_float(cfg, "reach_mm"),
            keep_single=as_bool(cfg, "keep_single"),
            clearance=as_float(cfg, "clearance_mm"),
            slot_depth=int(round(as_float(cfg, "slot_depth"))),
            column_step=as_float(cfg, "column_step_mm"),
            max_shift=as_float(cfg, "max_shift_mm"),
            second_column=as_bool(cfg, "second_column"),
            side=cfg.get("side", "auto") if cfg.get("side") in CHOICES["side"] else "auto",
            align=cfg.get("align", "leader") if cfg.get("align") in CHOICES["align"] else "leader",
            budget=as_float(cfg, "budget_s"),
        )

    def slope(self):
        """tan of the leg angle; None for a vertical leg, "free" for free."""
        if self.angle == "free":
            return "free"
        try:
            degrees = float(self.angle)
        except Exception:
            degrees = 45.0
        if degrees >= 89.99:
            return None
        return math.tan(math.radians(degrees))


# ============================================================================
# tags in, placements out
# ============================================================================

class TagInput(object):
    """One tag, as the engine sees it.

    head    where its head is now (only used to report how far it moved)
    rel     its outline relative to its head: (du0, dv0, du1, dv1), measured
            with its leader switched off
    anchors where each of its leaders lands, one per tagged reference
    own     obstacle keys it may touch: the elements it tags
    current_elbows  where its leaders bend now, (u, v) or None for a straight
            leader, one per anchor; None altogether when not known.  Only used
            to decide whether a lone tag is already fine where it is.
    has_leader  whether it has a leader now
    """

    def __init__(self, key, label, head, rel, anchors, own=None, current_elbows=None,
                 has_leader=True):
        self.key = key
        self.label = label
        self.head = (float(head[0]), float(head[1]))
        self.rel = box_norm(rel)
        self.anchors = [(float(a[0]), float(a[1])) for a in (anchors or [])] or [self.head]
        self.own = set(own or ())
        self.width = self.rel[2] - self.rel[0]
        self.height = self.rel[3] - self.rel[1]
        n = float(len(self.anchors))
        self.centre = (sum(a[0] for a in self.anchors) / n, sum(a[1] for a in self.anchors) / n)
        self.current_elbows = None if current_elbows is None else list(current_elbows)
        self.has_leader = bool(has_leader)


class Placement(object):
    """Where a tag goes and the leaders it gets.

    starts[i] is where leader i leaves the tag and elbows[i] where it turns;
    an elbow of None means a straight leader.
    """

    def __init__(self, tag, head, starts, elbows, side=0, column=0):
        self.tag = tag
        self.key = tag.key
        self.head = (float(head[0]), float(head[1]))
        self.box = (self.head[0] + tag.rel[0], self.head[1] + tag.rel[1],
                    self.head[0] + tag.rel[2], self.head[1] + tag.rel[3])
        self.anchors = list(tag.anchors)
        self.starts = list(starts)
        self.elbows = list(elbows)
        self.side = side
        self.column = column
        self.kept = False       # True: left exactly where it was, not written

    def reach(self):
        """The longest level run of any of its leaders: tag edge to bend, or
        for a straight leader, its whole width across the view.  This is what
        grows when a tag is dragged sideways to line up with others; the leg
        itself only ever runs as far as the angle needs."""
        runs = []
        for start, elbow, anchor in zip(self.starts, self.elbows, self.anchors):
            runs.append(abs(start[0] - (elbow[0] if elbow is not None else anchor[0])))
        return max(runs or [0.0])

    def segments(self):
        """(a, b, part, leader index) for every straight run of every leader;
        the leg always ends at the anchor."""
        out = []
        for index, anchor in enumerate(self.anchors):
            start = self.starts[index]
            elbow = self.elbows[index]
            if elbow is None:
                out.append((start, anchor, "leg", index))
                continue
            if dist(start, elbow) > 1e-6:
                out.append((start, elbow, "shoulder", index))
            out.append((elbow, anchor, "leg", index))
        return out

    def leader_length(self):
        return sum(dist(a, b) for a, b, _, _ in self.segments())

    def extent(self):
        """The box round the tag and all its leaders, for a quick rejection."""
        points = [(self.box[0], self.box[1]), (self.box[2], self.box[3])]
        for a, b, _, _ in self.segments():
            points.append(a)
            points.append(b)
        return box_of_points(points)

    def moved(self):
        return dist(self.head, self.tag.head)


def actual_placement(tag, head, elbows):
    """A Placement for geometry read back out of Revit after writing, where the
    leader leaves the tag from whichever side of its box faces the elbow."""
    box = (head[0] + tag.rel[0], head[1] + tag.rel[1], head[0] + tag.rel[2], head[1] + tag.rel[3])
    mid = (box[1] + box[3]) / 2.0
    centre_u = (box[0] + box[2]) / 2.0
    starts = []
    clean = []
    for index, anchor in enumerate(tag.anchors):
        elbow = elbows[index] if index < len(elbows) else None
        towards = elbow if elbow is not None else anchor
        edge = box[2] if towards[0] >= centre_u else box[0]
        starts.append((edge, mid))
        clean.append(elbow)
    side = 1 if all(s[0] <= (b[0] if b else a[0]) for s, b, a in zip(starts, clean, tag.anchors)) else -1
    return Placement(tag, head, starts, clean, side=side)


class Clash(object):

    def __init__(self, key, part, label, hard, other_key=None):
        self.key = key
        self.part = part          # "tag" or "leader"
        self.label = label
        self.hard = bool(hard)
        self.other_key = other_key

    def describe(self):
        what = "the tag" if self.part == "tag" else "its leader"
        verb = "sits on" if self.part == "tag" else "crosses"
        return "{0} {1} {2}{3}".format(what, verb, self.label, "" if self.hard else " (model, allowed)")

    def ident(self):
        return (self.key, self.part, self.label)


CROP_LABEL = "the edge of the crop region"


# ============================================================================
# clusters
# ============================================================================

def clusters(tags, threshold, reach=None):
    """Tags whose targets sit within `threshold` of each other, chained, form
    one cluster and one column.  With `reach`, two targets further apart than
    that across the view are never linked: lining their tags up would drag one
    tag a long way from what it tags.  Deterministic: clusters come out top
    first, then left first, and keep the input order inside."""
    n = len(tags)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if dist(tags[i].centre, tags[j].centre) > threshold:
                continue
            if reach is not None and abs(tags[i].centre[0] - tags[j].centre[0]) > reach:
                continue
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = [[tags[i] for i in members] for members in groups.values()]
    out.sort(key=lambda group: (-max(t.centre[1] for t in group),
                                min(t.centre[0] for t in group)))
    return out


# ============================================================================
# building a column
# ============================================================================

class State(object):
    """One candidate layout of a cluster: which side, the order top to bottom,
    how many steps further out the column sits (k), how many slots the whole
    column is shifted up (t), and the extra empty slots opened above each tag."""

    def __init__(self, side, order, k=0, t=0, gaps=None):
        self.side = 1 if side > 0 else -1
        self.order = tuple(order)
        self.k = int(k)
        self.t = int(t)
        self.gaps = tuple(gaps) if gaps is not None else (0,) * len(order)

    def ident(self):
        return (self.side, self.order, self.k, self.t, self.gaps)

    def copy(self, **changes):
        values = dict(side=self.side, order=self.order, k=self.k, t=self.t, gaps=self.gaps)
        values.update(changes)
        return State(**values)


def pitch_of(tags, p):
    """One slot: the median tag height plus the gap."""
    heights = sorted(t.height for t in tags) or [0.0]
    middle = heights[len(heights) // 2]
    return max(middle + p.gap, 0.5)


def build_column(tags, state, p, pick=None):
    """Place every tag in `state.order` and return the placements.

    The column hugs its targets: it sits exactly as far out as the leg angle
    and the minimum shoulder need, then k column steps further.
    """
    s = state.side
    order = [tags[i] for i in state.order]
    pitch = pitch_of(tags, p)

    total = sum(t.height for t in order) + p.gap * max(len(order) - 1, 0) + sum(state.gaps) * pitch
    if pick is not None:
        top = pick[1]
    else:
        centre_v = sum(t.centre[1] for t in order) / float(len(order))
        top = centre_v + total / 2.0
    top += state.t * pitch

    tops = []
    cursor = top
    for slot, tag in enumerate(order):
        cursor -= state.gaps[slot] * pitch
        tops.append(cursor)
        cursor -= tag.height + p.gap

    slope = p.slope()
    need = -1e18     # s * column line must be at least this
    rows = []
    for slot, tag in enumerate(order):
        mid = tops[slot] - tag.height / 2.0
        off = tag.width if (s < 0 and p.align == "left") else 0.0
        legs = []
        for anchor in tag.anchors:
            drop = mid - anchor[1]
            if slope == "free" or abs(drop) <= p.straight_tol:
                elbow_u = None
            elif slope is None:
                elbow_u = anchor[0]
            else:
                elbow_u = anchor[0] + s * abs(drop) / slope
            legs.append(elbow_u)
            need = max(need, max(p.column_clear, p.min_shoulder) + s * (anchor[0] - off))
            if elbow_u is not None:
                need = max(need, p.min_shoulder + s * (elbow_u - off))
        rows.append((tag, mid, off, legs))
    if pick is not None:
        need = max(need, s * pick[0])
    line = s * (need + state.k * p.column_step)

    placements = []
    for slot, (tag, mid, off, legs) in enumerate(rows):
        inner = line + off
        head_u = inner - tag.rel[0] if s > 0 else inner - tag.rel[2]
        head_v = tops[slot] - tag.rel[3]
        starts = []
        elbows = []
        for index, anchor in enumerate(tag.anchors):
            elbow_u = legs[index]
            if elbow_u is None:
                elbow_u = inner - s * p.min_shoulder
            starts.append((inner, mid))
            elbows.append((elbow_u, mid))
        placements.append(Placement(tag, (head_u, head_v), starts, elbows, side=s))
    return placements


# ============================================================================
# clashes and cost
# ============================================================================

class Context(object):
    """The obstacles of one view, indexed once, and the crop."""

    def __init__(self, obstacles, crop, p, cell=10.0):
        self.p = p
        self.crop = box_norm(crop) if crop else None
        self.obstacles = list(obstacles)
        self.grid = Grid(cell)
        for ob in self.obstacles:
            self.grid.add(ob)

    def with_placed(self, placements):
        """A copy that also treats `placements` as hard obstacles: what an
        earlier cluster already put down."""
        extra = list(self.obstacles)
        for pl in placements:
            extra.append(Obstacle("box", pl.box, True, _tag_label(pl.tag), key=("placed", pl.key),
                                  group="placed"))
            for a, b, _, _ in pl.segments():
                extra.append(Obstacle("seg", (a, b), True, "the leader of " + _tag_label(pl.tag),
                                      key=("placed-leader", pl.key), group="placed"))
        return Context(extra, self.crop, self.p, self.grid.cell)


def _tag_label(tag):
    return str(tag.label)


def find_clashes(placements, ctx):
    """Every clash in a layout, each named, de-duplicated."""
    p = ctx.p
    out = []
    seen = set()

    def note(clash):
        ident = clash.ident()
        if ident not in seen:
            seen.add(ident)
            out.append(clash)

    segments = [pl.segments() for pl in placements]

    for index, pl in enumerate(placements):
        own = pl.tag.own
        padded = box_grow(pl.box, p.clearance)
        for ob in ctx.grid.query(padded):
            if ob.key == ("placed", pl.key):
                continue
            if ob.touches_box(padded):
                hard = ob.hard and ob.key not in own
                note(Clash(pl.key, "tag", ob.label, hard, ob.key))
        if ctx.crop is not None and not box_inside(pl.box, ctx.crop):
            note(Clash(pl.key, "tag", CROP_LABEL, True))

        for a, b, part, _ in segments[index]:
            if part == "leg":
                trimmed = trim_end(a, b, p.end_allow)
                if trimmed is None:
                    continue
                a, b = trimmed
            region = box_of_points((a, b))
            for ob in ctx.grid.query(region):
                if ob.key in own or ob.key == ("placed-leader", pl.key):
                    continue
                if ob.touches_segment(a, b):
                    note(Clash(pl.key, "leader", ob.label, ob.hard, ob.key))

    n = len(placements)
    extents = [box_grow(pl.extent(), 0.1) for pl in placements]
    for i in range(n):
        for j in range(i + 1, n):
            A, B = placements[i], placements[j]
            if not box_overlap(extents[i], extents[j]):
                continue
            if box_overlap(A.box, B.box, 0.01):
                note(Clash(A.key, "tag", _tag_label(B.tag), True, B.key))
            for first, second, segs in ((A, B, segments[i]), (B, A, segments[j])):
                inner = box_grow(second.box, -0.05)
                for a, b, _, _ in segs:
                    if segment_box_intersects(a, b, inner):
                        note(Clash(first.key, "leader", _tag_label(second.tag), True, second.key))
                        break
            crossed = False
            for a, b, part_a, ia in segments[i]:
                if crossed:
                    break
                for c, d, part_b, ib in segments[j]:
                    if part_a == "leg" and part_b == "leg" and \
                            dist(A.anchors[ia], B.anchors[ib]) <= p.shared_anchor:
                        continue
                    if segments_intersect(a, b, c, d):
                        note(Clash(A.key, "leader", "the leader of " + _tag_label(B.tag),
                                   True, B.key))
                        crossed = True
                        break
    return out


def cost_of(placements, clashes, p, columns=1):
    hard = sum(1 for c in clashes if c.hard)
    soft_tag = sum(1 for c in clashes if not c.hard and c.part == "tag")
    soft_leader = sum(1 for c in clashes if not c.hard and c.part == "leader")
    length = sum(pl.leader_length() for pl in placements)
    if placements:
        height = max(pl.box[3] for pl in placements) - min(pl.box[1] for pl in placements)
    else:
        height = 0.0
    return (hard * p.w_hard + soft_tag * p.w_soft_tag + soft_leader * p.w_soft_leader +
            length * p.w_length + height * p.w_height + (columns - 1) * p.w_columns)


def crossing_count(placements, ctx):
    return sum(1 for c in find_clashes(placements, ctx)
               if c.part == "leader" and c.other_key in set(pl.key for pl in placements))


# ============================================================================
# the search
# ============================================================================

class Budget(object):

    def __init__(self, seconds, clock=None):
        if clock is None:
            import time
            clock = time.time
        self.clock = clock
        self.deadline = clock() + float(seconds)
        self.ran_out = False

    def left(self):
        if self.clock() >= self.deadline:
            self.ran_out = True
            return False
        return True


def _evaluate(tags, state, ctx, p, pick, cache):
    ident = state.ident()
    if ident in cache:
        return cache[ident]
    placements = build_column(tags, state, p, pick)
    clashes = find_clashes(placements, ctx)
    result = (cost_of(placements, clashes, p), placements, clashes)
    cache[ident] = result
    return result


def plain_order(tags, side):
    s = 1 if side > 0 else -1
    return tuple(sorted(range(len(tags)),
                        key=lambda i: (-tags[i].centre[1], s * tags[i].centre[0], i)))


def fan_order(tags, state, p, pick=None):
    """The order that keeps legs from crossing for this state's column
    position: sort by where each leg, run on at its angle, would meet the
    column line.  Legs at one angle are parallel lines, and parallel lines met
    in the order they arrive never cross.  Which way a leg goes (up or down)
    depends on the slot it gets, so this settles in a few rounds."""
    n = len(tags)
    s = state.side
    slope = p.slope()
    if slope == "free":
        rate = 0.0
    elif slope is None:
        rate = 1000.0
    else:
        rate = slope
    order = list(state.order)
    if rate <= 0.0 or n < 2:
        return tuple(order)
    for _ in range(5):
        placements = build_column(tags, state.copy(order=tuple(order)), p, pick)
        line = placements[0].starts[0][0]
        mids = dict((pl.key, pl.starts[0][1]) for pl in placements)
        keys = []
        for i in range(n):
            tag = tags[i]
            reach = s * (line - tag.centre[0])
            if mids[tag.key] >= tag.centre[1]:
                meet = tag.centre[1] + rate * reach
            else:
                meet = tag.centre[1] - rate * reach
            keys.append((-meet, s * tag.centre[0], i))
        new = [k[2] for k in sorted(keys)]
        if new == order:
            break
        order = new
    return tuple(order)


def initial_orders(tags, side, p, pick=None):
    """Two starting orders: plain top-to-bottom by target, and the fan order."""
    plain = plain_order(tags, side)
    orders = [plain]
    fan = fan_order(tags, State(side, plain), p, pick)
    if fan not in orders:
        orders.append(fan)
    return orders


def _neighbours(state, n, p, pitch_limit, tags=None, pick=None):
    """Every one-move change to a state, in a fixed order.  A whole-column
    move is offered twice: as it stands, and with the order re-fanned for the
    new position, because a shift changes which way each leg runs."""
    plain = _plain_neighbours(state, n, p, pitch_limit)
    if tags is None:
        return plain
    out = []
    seen = set()
    for candidate in plain:
        if candidate.ident() not in seen:
            seen.add(candidate.ident())
            out.append(candidate)
        if candidate.t != state.t or candidate.k != state.k:
            refanned = candidate.copy(order=fan_order(tags, candidate, p, pick))
            if refanned.ident() not in seen:
                seen.add(refanned.ident())
                out.append(refanned)
    return out


def _plain_neighbours(state, n, p, pitch_limit):
    out = []
    order = list(state.order)
    pairs = []
    if n <= 12:
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((i, j))
    else:
        for i in range(n - 1):
            pairs.append((i, i + 1))
    for i, j in pairs:
        swapped = list(order)
        swapped[i], swapped[j] = swapped[j], swapped[i]
        out.append(state.copy(order=tuple(swapped)))
    depth = max(int(p.slot_depth), 0)
    for i in range(1, n):
        gaps = list(state.gaps)
        if gaps[i] < depth:
            gaps[i] += 1
            out.append(state.copy(gaps=tuple(gaps)))
        gaps = list(state.gaps)
        if gaps[i] > 0:
            gaps[i] -= 1
            out.append(state.copy(gaps=tuple(gaps)))
    # Whole-column moves jump to every allowed position, nearest first, not
    # one notch at a time: an obstacle wider than a notch scores the same
    # until the column is fully past it, and a one-notch search stalls there.
    shifts = sorted(range(-pitch_limit, pitch_limit + 1), key=lambda x: (abs(x - state.t), x))
    for t in shifts:
        if t != state.t:
            out.append(state.copy(t=t))
    steps = int(p.max_shift / p.column_step) if p.column_step > 0 else 0
    for k in sorted(range(0, steps + 1), key=lambda x: (abs(x - state.k), x)):
        if k != state.k:
            out.append(state.copy(k=k))
    return out


class Outcome(object):

    def __init__(self, cost, placements, clashes, sides, columns=1):
        self.cost = cost
        self.placements = placements
        self.clashes = clashes
        self.sides = sides
        self.columns = columns

    def hard(self):
        return sum(1 for c in self.clashes if c.hard)


def search_column(tags, ctx, p, side, budget, pick=None):
    """Best layout of one cluster as one column on one side."""
    n = len(tags)
    cache = {}
    best = None
    for order in initial_orders(tags, side, p, pick):
        state = State(side, order)
        cost, placements, clashes = _evaluate(tags, state, ctx, p, pick, cache)
        if best is None or cost < best[0] - 1e-9:
            best = (cost, state, placements, clashes)

    pitch_limit = max(int(p.slot_depth), 0) + n
    cost, state, placements, clashes = best
    while budget.left():
        found = None
        for candidate in _neighbours(state, n, p, pitch_limit, tags, pick):
            if not budget.left():
                break
            c, pls, cls = _evaluate(tags, candidate, ctx, p, pick, cache)
            if c < cost - 1e-9 and (found is None or c < found[0] - 1e-9):
                found = (c, candidate, pls, cls)
        if found is None:
            break
        cost, state, placements, clashes = found
    for pl in placements:
        pl.side = state.side
    return Outcome(cost, placements, clashes, [state.side])


def solve_cluster(tags, ctx, p, budget, flip_side=None, pick=None):
    """Best layout of one cluster: either side, then two columns if one cannot
    be made clear."""
    centre_u = sum(t.centre[0] for t in tags) / float(len(tags))
    if pick is not None:
        sides = [1 if pick[0] >= centre_u else -1]
    elif flip_side is not None:
        sides = [-flip_side]
    elif p.side == "left":
        sides = [-1]
    elif p.side == "right":
        sides = [1]
    else:
        sides = [1, -1]

    best = None
    for side in sides:
        outcome = search_column(tags, ctx, p, side, budget, pick)
        if best is None or outcome.cost < best.cost - 1e-9:
            best = outcome

    if p.second_column and pick is None and len(tags) >= 2 and best.hard() > 0:
        split = _two_columns(tags, ctx, p, budget, best.sides[0])
        if split is not None and split.cost < best.cost - 1e-9:
            best = split
    return best


def _two_columns(tags, ctx, p, budget, first_side):
    """Half the tags in a column on each side of their targets: the half whose
    targets lie nearer each side goes to that side."""
    ranked = sorted(tags, key=lambda t: (t.centre[0], -t.centre[1]))
    half = len(ranked) // 2
    left, right = ranked[:half], ranked[half:]
    if not left or not right:
        return None
    first = search_column(left, ctx, p, -1, budget)
    for pl in first.placements:
        pl.column = 0
    second = search_column(right, ctx.with_placed(first.placements), p, 1, budget)
    for pl in second.placements:
        pl.column = 1
    placements = first.placements + second.placements
    clashes = find_clashes(placements, ctx)
    return Outcome(cost_of(placements, clashes, p, columns=2), placements, clashes,
                   [-1, 1], columns=2)


def outcome_reach(outcome):
    return max([pl.reach() for pl in outcome.placements] or [0.0])


def split_group(group):
    """Two halves of a group, split at the widest gap between its targets
    across the view, or up the view when they all line up vertically."""
    def at_widest(axis):
        ranked = sorted(group, key=lambda t: (t.centre[axis], -t.centre[1 - axis]))
        best = None
        for i in range(len(ranked) - 1):
            gap = ranked[i + 1].centre[axis] - ranked[i].centre[axis]
            if best is None or gap > best[0] + 1e-9:
                best = (gap, i + 1)
        return best, ranked

    across, ranked = at_widest(0)
    if across is None:
        return [], []
    if across[0] <= 1e-6:
        up, ranked = at_widest(1)
        cut = up[1]
    else:
        cut = across[1]
    first = set(id(t) for t in ranked[:cut])
    return ([t for t in group if id(t) in first], [t for t in group if id(t) not in first])


def keep_as_is(tag, ctx, p):
    """A tag on its own that already sits clear and close to its target is
    left exactly where it is: there is nothing to line it up with."""
    if not p.keep_single or not tag.has_leader or tag.current_elbows is None:
        return None
    if len(tag.current_elbows) != len(tag.anchors):
        return None
    placement = actual_placement(tag, tag.head, tag.current_elbows)
    if placement.reach() > p.reach + 1e-6:
        return None
    clashes = find_clashes([placement], ctx)
    if any(c.hard for c in clashes):
        return None
    placement.kept = True
    return Outcome(cost_of([placement], clashes, p), [placement], clashes, [placement.side])


class Result(object):
    """Everything solve() worked out for one view."""

    def __init__(self):
        self.placements = []
        self.clashes = []
        self.sides = {}
        self.columns = 0
        self.ran_out = False
        self.cost = 0.0
        self.kept = 0

    def by_key(self):
        return dict((pl.key, pl) for pl in self.placements)

    def clashes_for(self, key):
        return [c for c in self.clashes if c.key == key]


def solve(tags, obstacles=(), crop=None, p=None, clock=None, flip=None, pick=None):
    """Lay out every tag of one view.

    flip, when given, is the {cluster index: side} an earlier run chose, and
    every cluster is laid out on the other side of it.  pick, when given, is the
    (u, v) the user clicked for the top of the column: the whole selection then
    becomes one column there.
    """
    p = p or Params()
    tags = list(tags)
    result = Result()
    if not tags:
        return result
    budget = Budget(p.budget, clock)
    base = Context(obstacles, crop, p)
    if pick is not None:
        queue = [tags]
    else:
        queue = clusters(tags, p.cluster, p.reach)

    ctx = base
    column = 0
    index = 0
    while queue:
        group = queue.pop(0)
        outcome = None
        if len(group) == 1 and pick is None:
            outcome = keep_as_is(group[0], ctx, p)
        if outcome is None:
            flip_side = flip.get(index) if flip else None
            outcome = solve_cluster(group, ctx, p, budget, flip_side, pick)
            # Lining up must not drag a tag far from what it tags.  A group
            # whose best column still reaches too far becomes two alignment
            # lines, split where its targets are furthest apart.
            if pick is None and len(group) > 1 and outcome_reach(outcome) > p.reach + 1e-6:
                first, second = split_group(group)
                if first and second:
                    queue[0:0] = [first, second]
                    continue
        if outcome.placements and outcome.placements[0].kept:
            result.kept += 1
        else:
            for pl in outcome.placements:
                pl.column = column + pl.column
            column += outcome.columns
        result.sides[index] = outcome.sides[0] if outcome.columns == 1 else outcome.sides[-1]
        result.placements.extend(outcome.placements)
        ctx = ctx.with_placed(outcome.placements)
        index += 1

    result.columns = column
    result.clashes = find_clashes(result.placements, base)
    result.cost = cost_of(result.placements, result.clashes, p, max(column, 1))
    result.ran_out = budget.ran_out
    return result


# ============================================================================
# which tags may be moved at all
# ============================================================================

def eligibility(info, cfg):
    """What to do with one tag before any layout, on plain flags.

    info keys (all optional): view_ok, has_leader, pinned, owned_by_other,
    updated_in_central, in_group, spatial.
    Returns a dict: ok, reason, unpin, switch_on.
    """
    verdict = {"ok": True, "reason": "", "unpin": False, "switch_on": False}

    def refuse(reason):
        verdict["ok"] = False
        verdict["reason"] = reason
        return verdict

    if info.get("view_ok") is False:
        return refuse("its view is a 3D, drafting or schedule view, which this tool does not lay out")
    if info.get("spatial") and not as_bool(cfg, "include_spatial_tags"):
        return refuse("room and space tags are switched off in the settings")
    if info.get("in_group"):
        return refuse("it is inside a group, and Revit will not move it on its own")
    if info.get("owned_by_other"):
        return refuse("another user has it borrowed; ask them to relinquish it")
    if info.get("updated_in_central"):
        return refuse("it has changed in the central model; synchronise first")
    if info.get("pinned"):
        if cfg.get("pinned", "unpin") == "skip":
            return refuse("it is pinned, and pinned tags are set to be left alone")
        verdict["unpin"] = True
    if not info.get("has_leader", True):
        if cfg.get("no_leader", "switch_on") == "skip":
            return refuse("it has no leader, and tags without one are set to be skipped")
        verdict["switch_on"] = True
    return verdict


# ============================================================================
# reporting helpers
# ============================================================================

def describe_outcome(placement, clashes):
    """One results line for a placed tag."""
    hard = [c for c in clashes if c.hard]
    soft = [c for c in clashes if not c.hard]
    if placement.kept:
        return "on its own and already clear beside its target, so it was left where it is"
    side = "right" if placement.side > 0 else "left"
    text = "column {0}, {1} of its targets, moved {2:.0f}mm on paper".format(
        placement.column + 1, side, placement.moved())
    if hard:
        text += "; still clashing: " + "; ".join(c.describe() for c in hard[:3])
        if len(hard) > 3:
            text += " and {0} more".format(len(hard) - 3)
    elif soft:
        text += "; leader crosses {0} model element{1}".format(
            len(soft), "" if len(soft) == 1 else "s")
    return text


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026; .Value is the one."""
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


# ============================================================================
# theme: following Revit's canvas
# ============================================================================

THEME_CYCLE = ("follow", "dark", "light")
THEME_LABELS = {"follow": "Auto", "dark": "Dark", "light": "Light"}


def canvas_name(raw):
    """Revit's canvas theme as "dark" or "light", or None when unknown.

    raw is whatever UIThemeManager.CurrentCanvasTheme gave back.  UITheme.Dark
    is 0, so a read must never be tested for truthiness: that reports Dark as
    a failed read and falls through to Light.
    """
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if "dark" in text:
        return "dark"
    if "light" in text:
        return "light"
    try:
        number = int(raw)
    except Exception:
        return None
    if number == 0:
        return "dark"
    if number == 1:
        return "light"
    return None


def resolve_theme(setting, canvas):
    """The palette to paint: the setting itself, or for "follow" whatever the
    canvas is (dark when Revit cannot say, as it cannot before 2024)."""
    setting = str(setting or "follow").lower()
    if setting in ("dark", "light"):
        return setting
    return canvas if canvas in ("dark", "light") else "dark"


def next_theme(setting):
    setting = setting if setting in THEME_CYCLE else "follow"
    return THEME_CYCLE[(THEME_CYCLE.index(setting) + 1) % len(THEME_CYCLE)]


# ============================================================================
# the shrink-to-taskbar drawer
# ============================================================================
#
# Pure arithmetic and a controller that talks to its window only through a
# host object, so the bench can drive the whole gesture with a fake window and
# a fake timer.  tidy_ui supplies the real host.

DRAWER_MARGIN = 8.0       # gap left between the parked bar and the taskbar
DRAWER_STEPS = 12
DRAWER_INTERVAL_MS = 15


def park_bounds(work, bar_height, margin=DRAWER_MARGIN):
    """(top, height) of the parked bar: its own header, floating just above
    the bottom of the working area of the screen it is on.  work is (left,
    top, width, height); a monitor above the primary has a negative top."""
    top = work[1] + work[3] - bar_height - margin
    return (max(top, work[1]), bar_height)


def reopen_bounds(saved, bar_top, bar_height, work, parked_top, tolerance=2.0):
    """(top, height) to open back to.  Where the bar has not been moved, the
    window goes back exactly where it was.  Where it has been carried
    somewhere else, it opens upward from where the bar now sits, never above
    the top of that screen."""
    height = min(saved[3], work[3])
    if abs(bar_top - parked_top) <= tolerance:
        top = saved[1]
    else:
        top = bar_top + bar_height - height
    top = max(top, work[1])
    if top + height > work[1] + work[3]:
        top = max(work[1], work[1] + work[3] - height)
    return (top, height)


def ease(t):
    """Smoothstep, so the drawer starts and lands gently."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


def slide_frame(start, end, step, steps=DRAWER_STEPS):
    """(top, height) at one frame of a slide from start to end."""
    t = ease(float(step) / float(max(steps, 1)))
    return (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)


class DrawerCore(object):
    """The drawer's state machine.

    host must offer: bounds() -> (left, top, width, height), set_bounds(top,
    height), work_area() -> (left, top, width, height), bar_height(),
    before_slide(shrinking), after_slide(shrunk), and make_timer(interval_ms,
    tick) returning something with start() and stop().

    after_slide is where the real window releases its animations, puts
    MinHeight back, unpins its body and brings its grips back.  A tick that
    raises lands the window where it was going rather than leaving it half
    shut with sliding stuck on.
    """

    def __init__(self, host, steps=DRAWER_STEPS):
        self.host = host
        self.steps = int(steps)
        self.shrunk = False
        self.sliding = False
        self.saved = None
        self.parked_top = None
        self.timer = None
        self._from = None
        self._to = None
        self._step = 0
        self._target_shrunk = False

    def toggle(self):
        if self.sliding:
            return False
        if self.shrunk:
            self.expand()
        else:
            self.shrink()
        return True

    def shrink(self):
        if self.sliding or self.shrunk:
            return
        self.saved = tuple(self.host.bounds())
        work = self.host.work_area()
        target = park_bounds(work, self.host.bar_height())
        self.parked_top = target[0]
        self._slide((self.saved[1], self.saved[3]), target, True)

    def expand(self):
        if self.sliding or not self.shrunk:
            return
        now = tuple(self.host.bounds())
        work = self.host.work_area()
        saved = self.saved or now
        parked = self.parked_top if self.parked_top is not None else now[1]
        target = reopen_bounds(saved, now[1], now[3], work, parked)
        self._slide((now[1], now[3]), target, False)

    def _slide(self, start, end, shrinking):
        self.sliding = True
        self._from = start
        self._to = end
        self._step = 0
        self._target_shrunk = shrinking
        try:
            self.host.before_slide(shrinking)
        except Exception:
            pass
        try:
            self.timer = self.host.make_timer(DRAWER_INTERVAL_MS, self._tick)
            self.timer.start()
        except Exception:
            # no timer: no slide, just land
            self._land()

    def _tick(self, *args):
        if not self.sliding:
            self._stop_timer()
            return
        try:
            self._step += 1
            top, height = slide_frame(self._from, self._to, self._step, self.steps)
            self.host.set_bounds(top, height)
            if self._step >= self.steps:
                self._stop_timer()
                self._land()
        except Exception:
            self._stop_timer()
            self._land()

    def _stop_timer(self):
        try:
            if self.timer is not None:
                self.timer.stop()
        except Exception:
            pass

    def _land(self):
        if not self.sliding:
            return
        try:
            self.host.set_bounds(self._to[0], self._to[1])
        except Exception:
            pass
        self.shrunk = self._target_shrunk
        self.sliding = False
        try:
            self.host.after_slide(self.shrunk)
        except Exception:
            pass
