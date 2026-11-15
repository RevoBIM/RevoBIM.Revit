# -*- coding: utf-8 -*-
"""RevoBIM Pipe Slope Assigner - version, settings and every rule.

Nothing in this module touches Revit or WPF. The Revit side hands it an
adapter that answers a handful of questions about elements (what kind is it,
where are its ends, what is it connected to) and it hands back a plan: where
every pipe end goes, how far each fitting turns and moves, which uprights
stretch. That keeps the whole rule set runnable under plain CPython in
bench_logic.py.

The rule
--------
Every horizontal pipe in scope falls at exactly 1:N along its own axis, towards
one outlet. The run is modelled as a graph: a node at each pipe end and at the
centre of each fitting, edges weighted by their length in plan. The height of
every node is

    z = z_outlet + (plan distance from the outlet along the run) / N

so the extended centrelines of every pipe meet at the centre of the fitting
between them, in 3D, whatever the run does in plan. A run that turns a corner
falls correctly on both legs - there is no cross-fall, which is what a single
rigid tilt of the whole run would give.

Fittings are moved rigidly: the best-fit rotation that carries each connector
onto its pipe's new axis, then a move of the centre to its new height. The
pipe ends are then cut to the fittings' new connector positions, so every
joint coincides exactly and reconnects.
"""

from __future__ import division

import heapq
import io
import math
import os

__version__ = "1.2.0"

TOOL_NAME = u"Pipe Slope Assigner"
RIBBON_NAME = u"RevoBIM Pipe Slope Assigner"

SETTINGS_FILE = u"pipe_slope_assigner.txt"
DEBUG_FILE = u"pipe_slope_assigner_debug.txt"
ERROR_FILE = u"pipe_slope_assigner_last_error.txt"
ALIVE_FILE = u"pipe_slope_assigner_window_check.txt"
SETTINGS_VERSION = 1

MM_PER_FT = 304.8
STEEP_DEG = 15.0              # steeper than this is a set up / set down / upright
UPRIGHT_CHOICES = (5, 10, 15, 30)
SLOPES = (100, 80, 60, 40)
MAX_ELEMENTS = 1500
PREVIEW_RUNS = 20             # runs the live preview walks before it stops counting
FLAT_MM = 5.0                 # a run whose ends sit within this is level
LOOSE_MM = 0.5                # a fixed joint moving further than this breaks
JOIN_TOL_MM = 2.0             # connectors this close are joined without comment
JOIN_GIVE_UP_MM = 10.0        # connectors further apart than this are not joined
SLOPE_TOL = 0.02              # relative tolerance on the fall read back
BOUNDARY_WEIGHT = 0.005       # a fitting leg with no pipe in scope, in the best fit
FALL_ABS_MM = 0.3             # a fall this close in height is right, however short the pipe
SIDEWAYS_MM = 5.0             # a pipe end moving further than this in plan is refused
MAX_TURN_DEG = 10.0           # a fitting turning further than this is refused
HEAD_ON_DEG = 1.0             # a leg missing its pipe's axis by more than this is refused
REANGLE_DEG = 1.0             # a stretched set up / down changing angle more than this is flagged

try:
    text_type = unicode       # noqa: F821  (IronPython 2.7)
except NameError:
    text_type = str


def mm_to_ft(mm):
    return float(mm) / MM_PER_FT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FT


class Refusal(Exception):
    """A run the tool will not touch, with a sentence saying why."""


# ====================== settings ======================

DEFAULTS = (
    ('settings_version', text_type(SETTINGS_VERSION)),
    ('slope', u'100'),
    ('scope', u'run'),
    ('upright', u'15'),
    ('direction', u'auto'),
    ('anchor', u'low'),
    ('theme', u'auto'),
    ('debug', u'0'),
    ('show_results', u'issues'),
    ('window', u'modeless'),
    ('left', u''),
    ('top', u''),
)

CHOICES = {
    'slope': tuple(text_type(n) for n in SLOPES),
    'scope': (u'run', u'network', u'selection'),
    'upright': tuple(text_type(n) for n in UPRIGHT_CHOICES),
    'direction': (u'auto', u'pick'),
    'anchor': (u'low', u'high'),
    'theme': (u'auto', u'dark', u'light'),
    'debug': (u'0', u'1'),
    'show_results': (u'issues', u'always', u'never'),
    'window': (u'modeless', u'modal'),
}

# settings_version -> keys whose meaning changed at that version. A file written
# before that version has those keys reset to the default rather than read.
MIGRATIONS = {}


def to_number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value != value or abs(value) > 1e6:
        return None
    return value


def default_settings():
    return dict(DEFAULTS)


def settings_folder():
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'RevoBIM')


def settings_path(folder=None):
    return os.path.join(folder or settings_folder(), SETTINGS_FILE)


def parse_settings(text):
    """key=value lines into a settings dict, key by key.

    Splits on the first '=' only. A key that is unknown is ignored; a value
    that is not one of its choices falls back to the default; keys a migration
    reset since the file was written fall back to the default too.
    """
    values = default_settings()
    found = {}
    for raw in (text or u'').splitlines():
        line = raw.strip()
        if not line or line.startswith(u'#') or u'=' not in line:
            continue
        key, value = line.split(u'=', 1)
        found[key.strip()] = value.strip()
    try:
        written = int(found.get('settings_version', '0'))
    except ValueError:
        written = 0
    reset = set()
    for version, keys in MIGRATIONS.items():
        if written < version:
            reset.update(keys)
    for key, value in found.items():
        if key not in values or key == 'settings_version' or key in reset:
            continue
        allowed = CHOICES.get(key)
        if allowed is not None and value not in allowed:
            continue
        if key in ('left', 'top') and value and to_number(value) is None:
            continue
        values[key] = value
    values['settings_version'] = text_type(SETTINGS_VERSION)
    return values


def format_settings(values):
    lines = [u'# RevoBIM Pipe Slope Assigner settings - key=value, hand editable']
    for key, default in DEFAULTS:
        lines.append(u'{0}={1}'.format(key, values.get(key, default)))
    return u'\n'.join(lines) + u'\n'


def load_settings(path=None):
    path = path or settings_path()
    try:
        handle = io.open(path, 'r', encoding='utf-8')
        try:
            text = handle.read()
        finally:
            handle.close()
    except Exception:
        return default_settings()
    return parse_settings(text)


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        text = format_settings(values)
        handle = io.open(path, 'w', encoding='utf-8')
        try:
            handle.write(text)
        finally:
            handle.close()
        return True
    except Exception:
        return False


# ====================== slope wording ======================

def slope_label(n):
    return u'1:{0}'.format(int(n))


def slope_percent_text(n):
    pct = 100.0 / float(n)
    text = u'{0:.2f}'.format(pct).rstrip(u'0').rstrip(u'.')
    return text + u' %'


def slope_mm_per_m_text(n):
    value = 1000.0 / float(n)
    text = u'{0:.1f}'.format(value)
    if text.endswith(u'.0'):
        text = text[:-2]
    return text + u' mm/m'


def ratio_text(gradient):
    """A gradient (fall / plan length) as the 1:N a drainage engineer reads."""
    g = abs(float(gradient))
    if g < 1e-5:
        return u'level'
    n = 1.0 / g
    if n >= 10:
        return u'1:{0}'.format(int(round(n)))
    return u'1:{0:.1f}'.format(n)


# ====================== vectors ======================

def v(x, y, z):
    return (float(x), float(y), float(z))


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def v_len(a):
    return math.sqrt(v_dot(a, a))


def v_norm(a):
    n = v_len(a)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def plan_dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pitch_deg(a, b):
    """Angle of the line a->b above or below the horizontal, in degrees."""
    run = plan_dist(a, b)
    rise = abs(b[2] - a[2])
    if run < 1e-12 and rise < 1e-12:
        return 0.0
    return math.degrees(math.atan2(rise, run))


def set_upright(settings_or_deg):
    """The set up / set down line in degrees, from a settings dict or a number.
    Read by is_steep() at call time, so the pick filter follows it too."""
    global STEEP_DEG
    value = settings_or_deg
    if isinstance(value, dict):
        value = value.get('upright', u'15')
    number = to_number(value)
    if number is not None and 1.0 <= number <= 80.0:
        STEEP_DEG = number
    return STEEP_DEG


def is_steep(a, b, limit=None):
    # read at call time, not bound as a default, so the constant is the rule
    if limit is None:
        limit = STEEP_DEG
    return pitch_deg(a, b) > limit


def gradient(a, b):
    run = plan_dist(a, b)
    if run < 1e-12:
        return float('inf')
    return abs(b[2] - a[2]) / run


# ====================== rotations (quaternions w, x, y, z) ======================

Q_IDENTITY = (1.0, 0.0, 0.0, 0.0)


def q_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def q_normalise(q):
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-15:
        return Q_IDENTITY
    q = tuple(c / n for c in q)
    if q[0] < 0:                  # one hemisphere, so angles come out <= 180
        q = tuple(-c for c in q)
    return q


def q_rotate(q, vec):
    w, x, y, z = q
    p = (0.0, vec[0], vec[1], vec[2])
    r = q_mul(q_mul(q, p), (w, -x, -y, -z))
    return (r[1], r[2], r[3])


def q_from_axis_angle(axis, angle):
    a = v_norm(axis)
    s = math.sin(angle / 2.0)
    return q_normalise((math.cos(angle / 2.0), a[0] * s, a[1] * s, a[2] * s))


def q_to_axis_angle(q):
    q = q_normalise(q)
    w = max(-1.0, min(1.0, q[0]))
    angle = 2.0 * math.acos(w)
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    return (q[1] / s, q[2] / s, q[3] / s), angle


def q_between(a, b):
    """The smallest rotation carrying direction a onto direction b."""
    a = v_norm(a)
    b = v_norm(b)
    d = v_dot(a, b)
    if d > 1.0 - 1e-14:
        return Q_IDENTITY
    if d < -1.0 + 1e-14:
        # half turn about any axis square to a
        axis = v_cross(a, (1.0, 0.0, 0.0))
        if v_len(axis) < 1e-6:
            axis = v_cross(a, (0.0, 1.0, 0.0))
        return q_from_axis_angle(axis, math.pi)
    c = v_cross(a, b)
    return q_normalise((1.0 + d, c[0], c[1], c[2]))


def jacobi_eigen(matrix, sweeps=60):
    """Eigenvalues and eigenvectors (as columns) of a small symmetric matrix."""
    n = len(matrix)
    a = [list(map(float, row)) for row in matrix]
    vecs = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(sweeps):
        off = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                off += a[i][j] * a[i][j]
        if off < 1e-26:
            break
        for p in range(n):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-30:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                sign = 1.0 if theta >= 0 else -1.0
                t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    akp = a[k][p]
                    akq = a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk = a[p][k]
                    aqk = a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(n):
                    vkp = vecs[k][p]
                    vkq = vecs[k][q]
                    vecs[k][p] = c * vkp - s * vkq
                    vecs[k][q] = s * vkp + c * vkq
    return [a[i][i] for i in range(n)], vecs


def best_fit_rotation(pairs):
    """The rotation carrying each old direction closest onto its new one.

    pairs is a list of (old, new, weight). Horn's method: the quaternion is the
    eigenvector of the largest eigenvalue of a 4x4 symmetric matrix. Where every
    old direction is on one line (a union, a reducer, a cap) the spin about that
    line is undetermined, so the smallest rotation of the heaviest pair is used
    instead - which is also the rotation a straight leg actually makes.
    """
    pairs = [(v_norm(a), v_norm(b), float(w)) for (a, b, w) in pairs
             if w > 0 and v_len(a) > 1e-9 and v_len(b) > 1e-9]
    if not pairs:
        return Q_IDENTITY
    ref = pairs[0][0]
    spread = max(v_len(v_cross(ref, p[0])) for p in pairs)
    if spread < 1e-6:
        heaviest = max(pairs, key=lambda p: p[2])
        return q_between(heaviest[0], heaviest[1])
    s = [[0.0] * 3 for _ in range(3)]
    for a, b, w in pairs:
        for i in range(3):
            for j in range(3):
                s[i][j] += w * a[i] * b[j]
    sxx, sxy, sxz = s[0]
    syx, syy, syz = s[1]
    szx, szy, szz = s[2]
    n = [[sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
         [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
         [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
         [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz]]
    values, vecs = jacobi_eigen(n)
    best = max(range(4), key=lambda i: values[i])
    return q_normalise(tuple(vecs[r][best] for r in range(4)))


# ====================== the run model ======================

class RunModel(object):
    """Everything the walk found, as plain records keyed by element id."""

    def __init__(self, scope):
        self.scope = scope
        self.pipes = {}       # eid -> {'el','ends','conns'}
        self.fittings = {}    # eid -> {'el','centre','conns'}
        self.stretch = {}     # eid -> {'el','ends','conns','nears','kind','down'}
        self.fixed = {}       # eid -> {'el','kind','desc'}
        self.links = []       # (a_eid, a_cid, b_eid, b_cid), a in scope
        self._link_keys = set()
        self.notes = []
        self.start_ids = []

    def in_scope(self, eid):
        return eid in self.pipes or eid in self.fittings

    def record(self, eid):
        return self.pipes.get(eid) or self.fittings.get(eid)

    def kind_of(self, eid):
        if eid in self.pipes:
            return 'pipe'
        if eid in self.fittings:
            return 'fitting'
        if eid in self.stretch:
            return 'stretch'
        if eid in self.fixed:
            return 'fixed'
        return None

    def conn(self, eid, cid):
        rec = (self.pipes.get(eid) or self.fittings.get(eid)
               or self.stretch.get(eid))
        if rec is None:
            return None
        for c in rec['conns']:
            if c['id'] == cid:
                return c
        return None

    def link(self, a, ca, b, cb):
        key = frozenset([(a, ca), (b, cb)])
        if key in self._link_keys:
            return
        self._link_keys.add(key)
        self.links.append((a, ca, b, cb))

    def element_count(self):
        return len(self.pipes) + len(self.fittings)

    def partners_of(self, eid, cid):
        out = []
        for (a, ca, b, cb) in self.links:
            if a == eid and ca == cid:
                out.append((b, cb))
            elif b == eid and cb == cid:
                out.append((a, ca))
        return out


def solve3(a, b):
    """Solve a 3x3 system by elimination with pivoting; None if singular."""
    m = [list(a[i]) + [b[i]] for i in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-15:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(3):
            if r != col:
                f = m[r][col] / m[col][col]
                for k in range(col, 4):
                    m[r][k] -= f * m[col][k]
    return (m[0][3] / m[0][0], m[1][3] / m[1][1], m[2][3] / m[2][2])


def fitting_hub(conns, fallback=None):
    """Where a fitting's connector axes meet - the point the run's centrelines
    actually pass through.

    The family's insertion point is not always there: on a 45 degree junction
    the branch axis meets the main a way along from it, and measuring the fall
    through the insertion point put the short pipes beside it on the wrong
    fall, some falling the wrong way. Each leg is a line in 3D through its
    connector along its direction; the hub is the least-squares meeting point.
    Legs all on one line (a coupling, a reducer) or a single leg (a cap) have
    no meeting point along that line, so there it stays at the middle of the
    connectors - which is what the small regularising term does.
    """
    usable = [c for c in conns if v_len(c['dir']) > 1e-9]
    if not usable:
        return fallback
    k = 1.0 / len(usable)
    mean = (sum(c['origin'][0] for c in usable) * k, sum(c['origin'][1] for c in usable) * k,
            sum(c['origin'][2] for c in usable) * k)
    eps = 1e-9
    a = [[eps if i == j else 0.0 for j in range(3)] for i in range(3)]
    rhs = [eps * mean[i] for i in range(3)]
    for c in usable:
        d = v_norm(c['dir'])
        o = c['origin']
        for i in range(3):
            for j in range(3):
                mij = (1.0 if i == j else 0.0) - d[i] * d[j]
                a[i][j] += mij
                rhs[i] += mij * o[j]
    hub = solve3(a, rhs)
    if hub is None:
        return mean
    reach = max(v_len(v_sub(c['origin'], mean)) for c in usable)
    if v_len(v_sub(hub, mean)) > 3.0 * reach + 1e-6:
        return mean                   # near-parallel legs meeting far away: not a hub
    return hub


def opposite_ids(conns, arrived_id, tol=0.9):
    """Connectors of a fitting in line with, and opposite, the one arrived at."""
    arrived = None
    for c in conns:
        if c['id'] == arrived_id:
            arrived = c
    if arrived is None:
        return set()
    out = set()
    for c in conns:
        if c['id'] == arrived_id:
            continue
        if v_dot(v_norm(arrived['dir']), v_norm(c['dir'])) < -tol:
            out.add(c['id'])
    return out


def walk(adapter, start, scope, allowed=None):
    """Walk a horizontal run out from one pipe through its connectors.

    scope 'run'     - the line of pipe the start is on: through elbows and
                      in-line fittings, straight on through a tee, never out
                      of a tee's branch. A pipe off a branch stretches to stay
                      joined; a tee arrived at by its branch belongs to another
                      run and is left where it is.
    scope 'network' - every horizontal pipe joined to it, through tees too.
    scope 'selection' - every horizontal pipe and fitting in `allowed` (the
                      ids selected) joined to it, as one system. A horizontal
                      pipe joined to it but not selected stretches to stay
                      joined; a fitting not selected is left where it is.

    Every scope stops at any pipe pitched more than STEEP_DEG (15 degrees by
    default): that is a set up, a set down or an upright. It is not re-sloped;
    it stretches to stay joined, and the walk goes no further along it.
    """
    m = RunModel(scope)
    if adapter.kind(start) != 'pipe':
        raise Refusal(u'The element picked is not a pipe.')
    ends = adapter.ends(start)
    if is_steep(ends[0], ends[1]):
        raise Refusal(u'Pipe {0} is an upright ({1:.0f} degrees). Pick a '
                      u'horizontal pipe in the run.'.format(
                          adapter.eid(start), pitch_deg(ends[0], ends[1])))
    conn_cache = {}

    def conns_of(el):
        key = adapter.eid(el)
        if key not in conn_cache:
            conn_cache[key] = adapter.connectors(el)
        return conn_cache[key]

    def admit(el, kind):
        eid = adapter.eid(el)
        if adapter.in_group(el):
            raise Refusal(u'The run reaches element {0}, which is in a Revit '
                          u'group. Ungroup it first.'.format(eid))
        if m.element_count() >= MAX_ELEMENTS:
            raise Refusal(u'The run reaches more than {0} elements. Split it, '
                          u'or use Current horizontal run.'.format(MAX_ELEMENTS))
        if kind == 'pipe':
            m.pipes[eid] = {'el': el, 'ends': adapter.ends(el),
                            'conns': conns_of(el)}
        else:
            conns = conns_of(el)
            located = adapter.centre(el)
            m.fittings[eid] = {'el': el, 'centre': fitting_hub(conns, located),
                               'located': located, 'conns': conns}

    def add_stretch(el, pcid, kind, scope_eid, scope_cid):
        eid = adapter.eid(el)
        rec = m.stretch.get(eid)
        pconn = None
        for c in conns_of(el):
            if c['id'] == pcid:
                pconn = c
        if rec is None:
            pends = adapter.ends(el)
            rec = {'el': el, 'ends': pends, 'conns': conns_of(el), 'nears': {},
                   'kind': kind, 'down': False}
            m.stretch[eid] = rec
        if pconn is None or pconn.get('end') is None:
            return
        near = pconn['end']
        rec['nears'][near] = (scope_eid, scope_cid)
        far = rec['ends'][1 - near]
        rec['down'] = far[2] < rec['ends'][near][2]

    def add_fixed(el, kind):
        eid = adapter.eid(el)
        if eid not in m.fixed:
            m.fixed[eid] = {'el': el, 'kind': kind,
                            'desc': adapter.describe(el)}

    admit(start, 'pipe')
    m.start_ids.append(adapter.eid(start))
    queue = [(start, None)]
    while queue:
        el, arrived = queue.pop(0)
        eid = adapter.eid(el)
        rec = m.record(eid)
        conns = rec['conns']
        through = None
        if (eid in m.fittings and scope == 'run' and arrived is not None
                and len(conns) >= 3):
            through = opposite_ids(conns, arrived)
        for c in conns:
            branch_side = (through is not None and c['id'] != arrived
                           and c['id'] not in through)
            for (pel, pcid) in c['partners']:
                pid = adapter.eid(pel)
                if pid == eid:
                    continue
                if m.in_scope(pid):
                    m.link(eid, c['id'], pid, pcid)
                    continue
                pk = adapter.kind(pel)
                if pk == 'pipe':
                    pconn = None
                    for pc in conns_of(pel):
                        if pc['id'] == pcid:
                            pconn = pc
                    pends = adapter.ends(pel)
                    if c.get('curve') or (pconn is not None and pconn.get('curve')):
                        add_fixed(pel, 'takeoff')
                        m.notes.append(u'Takeoff joint between {0} and {1} is '
                                       u'not moved by this tool.'.format(eid, pid))
                    elif branch_side:
                        kind = 'upright' if is_steep(pends[0], pends[1]) else 'branch'
                        add_stretch(pel, pcid, kind, eid, c['id'])
                    elif is_steep(pends[0], pends[1]):
                        add_stretch(pel, pcid, 'upright', eid, c['id'])
                    elif allowed is not None and pid not in allowed:
                        add_stretch(pel, pcid, 'branch', eid, c['id'])
                    else:
                        admit(pel, 'pipe')
                        queue.append((pel, pcid))
                elif pk == 'fitting':
                    if c.get('curve'):
                        add_fixed(pel, 'takeoff')
                        m.notes.append(u'Takeoff {0} on pipe {1} is not moved '
                                       u'by this tool.'.format(pid, eid))
                    elif branch_side:
                        add_fixed(pel, 'fitting')
                    elif allowed is not None and pid not in allowed:
                        add_fixed(pel, 'fitting')
                    else:
                        pconns = conns_of(pel)
                        if (scope == 'run' and len(pconns) >= 3
                                and not opposite_ids(pconns, pcid)):
                            add_fixed(pel, 'main')
                        else:
                            admit(pel, 'fitting')
                            queue.append((pel, pcid))
                else:
                    add_fixed(pel, 'fixture')
                m.link(eid, c['id'], pid, pcid)
    return m


# ====================== the graph ======================

class Graph(object):
    def __init__(self):
        self.pos = {}         # node -> (x, y, z) as it is now
        self.adj = {}         # node -> {neighbour: plan length}
        self.tags = {}        # node -> [boundary class, ...]

    def add_node(self, key, pt):
        if key not in self.pos:
            self.pos[key] = pt
            self.adj[key] = {}
            self.tags[key] = []

    def add_edge(self, a, b, length=None):
        if a == b:
            return
        if length is None:
            length = plan_dist(self.pos[a], self.pos[b])
        old = self.adj[a].get(b)
        if old is None or length < old:
            self.adj[a][b] = length
            self.adj[b][a] = length

    def degree(self, key):
        return len(self.adj.get(key, {}))

    def dijkstra(self, sources):
        """Shortest plan distance to every node from a {node: start} dict."""
        dist = {}
        heap = [(float(d0), repr(k), k) for k, d0 in sources.items()]
        heapq.heapify(heap)
        while heap:
            d, _, k = heapq.heappop(heap)
            if k in dist:
                continue
            dist[k] = d
            for nb, length in self.adj[k].items():
                if nb not in dist:
                    heapq.heappush(heap, (d + length, repr(nb), nb))
        return dist


BOUNDARY_CLASS = {
    ('stretch', 'upright', True): 'stack_down',
    ('stretch', 'upright', False): 'stack_up',
    ('stretch', 'branch', True): 'branch',
    ('stretch', 'branch', False): 'branch',
}

FIXED_CLASS = {'main': 'main', 'fitting': 'main', 'fixture': 'fixture',
               'takeoff': 'takeoff'}

# How strongly a run end says "the water leaves here".
PRIORITY = {'stack_down': 3, 'main': 3, 'branch': 1, 'free': 0,
            'takeoff': 0, 'stack_up': -1, 'fixture': -1}


def node_of(m, eid, cid):
    if eid in m.pipes:
        c = m.conn(eid, cid)
        if c is None or c.get('end') is None:
            return None
        return ('p', eid, c['end'])
    if eid in m.fittings:
        return ('f', eid)
    return None


def build_graph(m):
    g = Graph()
    for pid, p in m.pipes.items():
        g.add_node(('p', pid, 0), p['ends'][0])
        g.add_node(('p', pid, 1), p['ends'][1])
        g.add_edge(('p', pid, 0), ('p', pid, 1))
    for fid, f in m.fittings.items():
        g.add_node(('f', fid), f['centre'])
    for (a, ca, b, cb) in m.links:
        na = node_of(m, a, ca)
        nb = node_of(m, b, cb)
        if na is not None and nb is not None:
            if na[0] == 'p' and nb[0] == 'p':
                g.add_edge(na, nb, 0.0)
            else:
                g.add_edge(na, nb)
            continue
        inside, other = (na, b) if na is not None else (nb, a)
        if inside is None:
            continue
        g.tags[inside].append(boundary_class(m, other))
    return g


def boundary_class(m, eid):
    if eid in m.stretch:
        s = m.stretch[eid]
        return BOUNDARY_CLASS.get(('stretch', s['kind'], s['down']), 'branch')
    if eid in m.fixed:
        return FIXED_CLASS.get(m.fixed[eid]['kind'], 'main')
    return 'free'


def terminals(g):
    if len(g.pos) <= 1:
        return list(g.pos.keys())
    return sorted([k for k in g.pos if g.degree(k) <= 1], key=repr)


def node_class(g, key):
    tags = g.tags.get(key) or []
    if not tags:
        return 'free'
    return max(tags, key=lambda t: PRIORITY.get(t, 0))


def choose_outlet_auto(g):
    """Which end the water leaves by, when nobody has said.

    A run that already falls keeps falling the same way: the outlet is its
    lowest end. A level run falls towards the one end that joins a stack going
    down or another run's fitting; with no such end, or more than one, the
    answer is None and the tool asks for two clicks.
    """
    terms = terminals(g)
    if not terms:
        return None, u'The run has no ends to fall towards (it is a loop).'
    zs = [g.pos[t][2] for t in terms]
    spread = ft_to_mm(max(zs) - min(zs))
    if spread > FLAT_MM:
        low = min(terms, key=lambda t: (g.pos[t][2], repr(t)))
        return low, u'falls towards its lowest end, as it does now'
    best = max(PRIORITY.get(node_class(g, t), 0) for t in terms)
    tops = [t for t in terms if PRIORITY.get(node_class(g, t), 0) == best]
    if best >= 2 and len(tops) == 1:
        return tops[0], u'level now - falls towards the {0}'.format(
            {'stack_down': u'stack it drops into',
             'main': u'run it joins'}.get(node_class(g, tops[0]), u'outlet'))
    return None, (u'The run is level and nothing says which way it should fall.')


def click_sources(m, pid, pt):
    """A click on a pipe as Dijkstra start distances to the pipe's two ends,
    plus the height of the pipe's centreline under the click."""
    ends = m.pipes[pid]['ends']
    a, b = ends
    run = plan_dist(a, b)
    if run < 1e-12:
        t = 0.0
    else:
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / (run * run)
        t = max(0.0, min(1.0, t))
    z = a[2] + (b[2] - a[2]) * t
    return {('p', pid, 0): run * t, ('p', pid, 1): run * (1.0 - t)}, z


def choose_outlet_picked(g, src_from, src_to):
    """The outlet for a fall-from click and a fall-to click: the run end
    closest to the fall-to click that lies beyond it, seen from fall-from."""
    terms = terminals(g)
    if not terms:
        return None, u'The run has no ends to fall towards (it is a loop).'
    d_from = g.dijkstra(src_from)
    d_to = g.dijkstra(src_to)
    beyond = [t for t in terms if t in d_from and t in d_to
              and d_from[t] > d_to[t] + 1e-9]
    pool = beyond or [t for t in terms if t in d_to]
    if not pool:
        return None, u'The two clicks are not on this run.'
    root = min(pool, key=lambda t: (d_to[t], repr(t)))
    if not beyond:
        return root, u'the end nearest the fall-to click (the clicks were very close)'
    return root, u'falls from the first click towards the second'


# ====================== the plan ======================

class Plan(object):
    def __init__(self):
        self.n = 100
        self.root = None
        self.z_root = 0.0
        self.node_z = {}
        self.dist = {}
        self.pipes = {}       # pid -> (new end 0, new end 1)
        self.fittings = {}    # fid -> {'quat','axis','angle','centre','move','conns'}
        self.stretch = {}     # eid -> (new end 0, new end 1)
        self.loose = []       # (scope eid, scope cid, other eid, mm moved)
        self.joins = []       # (a eid, a cid, b eid, b cid) to reconnect
        self.warnings = []
        self.notes = []
        self.reason = u''


def _pipe_away(ends, i):
    return v_sub(ends[1 - i], ends[i])


def make_plan(m, g, n, root, anchor):
    """Where everything goes.

    anchor is ('node', key) to hold that node's present height, or
    ('point', pid, xyz) to hold the height of a pipe's centreline under a click.
    """
    n = float(n)
    plan = Plan()
    plan.n = n
    plan.root = root
    dist = g.dijkstra({root: 0.0})
    missing = [k for k in g.pos if k not in dist]
    if missing:
        raise Refusal(u'The run is not joined up - {0} part(s) could not be '
                      u'reached from the outlet.'.format(len(missing)))
    plan.dist = dist
    if anchor[0] == 'node':
        key = anchor[1]
        plan.z_root = g.pos[key][2] - dist[key] / n
    else:
        _, pid, pt = anchor
        sources, z_here = click_sources(m, pid, pt)
        d_here = min(dist[k] + d0 for k, d0 in sources.items())
        plan.z_root = z_here - d_here / n
    for key, d in dist.items():
        plan.node_z[key] = plan.z_root + d / n

    # pipe ends on their node heights, before the fittings are placed
    rough = {}
    for pid, p in m.pipes.items():
        rough[pid] = [(p['ends'][i][0], p['ends'][i][1], plan.node_z[('p', pid, i)])
                      for i in (0, 1)]
        run = plan_dist(p['ends'][0], p['ends'][1])
        d0, d1 = dist[('p', pid, 0)], dist[('p', pid, 1)]
        if run > 1e-6 and abs(d0 - d1) < 0.9 * run:
            plan.warnings.append(u'Pipe {0} sits in a loop, so it cannot fall '
                                 u'one way along its whole length.'.format(pid))

    # fittings: best-fit rotation, then up or down to their node height
    for fid, f in m.fittings.items():
        c0 = f['centre']
        pairs = []
        for c in f['conns']:
            partners = m.partners_of(fid, c['id'])
            added = False
            for (oid, ocid) in partners:
                if oid in m.pipes:
                    oc = m.conn(oid, ocid)
                    if oc is None or oc.get('end') is None:
                        continue
                    # the connector should end up pointing along its pipe's
                    # new axis - aimed at directly, so a fitting that sat a
                    # fraction off its pipe before is squared up, not carried
                    new_away = _pipe_away(rough[oid], oc['end'])
                    pairs.append((c['dir'], new_away, 1.0))
                    added = True
                elif oid in m.fittings:
                    oc0 = m.fittings[oid]['centre']
                    old_edge = v_sub(oc0, c0)
                    if plan_dist(oc0, c0) < 1e-6:
                        continue
                    new_edge = (old_edge[0], old_edge[1],
                                plan.node_z[('f', oid)] - plan.node_z[('f', fid)])
                    pairs.append((c['dir'], new_edge, 1.0))
                    added = True
            if not added:
                # A leg into a stack, a fixture or nothing only settles the
                # spin about the run's own legs. Weighted any heavier it drags
                # the pipe legs off their fall - at 0.25 the leg beside a stack
                # came out 1:99 instead of 1:100. The upright stretches to the
                # connector instead, so it may lean a fraction of a degree.
                pairs.append((c['dir'], c['dir'], BOUNDARY_WEIGHT))
        quat = best_fit_rotation(pairs)
        axis, angle = q_to_axis_angle(quat)
        miss = 0.0
        for (old_d, want, weight) in pairs:
            if weight < 1.0:
                continue
            got = v_norm(q_rotate(quat, old_d))
            cosang = max(-1.0, min(1.0, v_dot(got, v_norm(want))))
            miss = max(miss, math.degrees(math.acos(cosang)))
        new_c = (c0[0], c0[1], plan.node_z[('f', fid)])
        conns = {}
        for c in f['conns']:
            off = q_rotate(quat, v_sub(c['origin'], c0))
            conns[c['id']] = {'origin': v_add(new_c, off),
                              'dir': q_rotate(quat, c['dir'])}
        plan.fittings[fid] = {'quat': quat, 'axis': axis, 'angle': angle, 'miss': miss,
                              'centre': c0, 'new_centre': new_c,
                              'move': v_sub(new_c, c0), 'conns': conns}

    # pipe ends cut to the fittings' new connectors
    for pid, p in m.pipes.items():
        out = list(rough[pid])
        for c in p['conns']:
            if c.get('end') is None:
                continue
            for (oid, ocid) in m.partners_of(pid, c['id']):
                if oid in plan.fittings:
                    out[c['end']] = plan.fittings[oid]['conns'][ocid]['origin']
        plan.pipes[pid] = (out[0], out[1])

    # uprights and branch pipes: the near end follows, the far end stays
    for sid, s in m.stretch.items():
        out = list(s['ends'])
        for near, (oid, ocid) in s['nears'].items():
            out[near] = new_point_of(m, plan, oid, ocid)
        plan.stretch[sid] = (out[0], out[1])
        before, after = pitch_deg(*s['ends']), pitch_deg(out[0], out[1])
        if s['kind'] == 'upright' and before < 80.0 and abs(after - before) > REANGLE_DEG:
            plan.warnings.append(u'Set {0} pipe {1} stretched from {2:.1f} to {3:.1f} degrees '
                                 u'to stay joined (its far end stays put) - check the '
                                 u'bends either side.'.format(
                                     u'down' if s['down'] else u'up', sid, before, after))
        elif s['kind'] == 'branch':
            plan.notes.append(u'Pipe {0} is joined on but not part of this {1} - stretched '
                              u'to stay joined, now {2}.'.format(
                                  sid, u'system' if m.scope == 'selection' else u'run',
                                  ratio_text(gradient(out[0], out[1]))))

    # joints: everything reconnects, except a fixed joint that had to move
    for (a, ca, b, cb) in m.links:
        a_in, b_in = m.in_scope(a), m.in_scope(b)
        if a_in and b_in:
            plan.joins.append((a, ca, b, cb))
            continue
        inside, icid, other, ocid = (a, ca, b, cb) if a_in else (b, cb, a, ca)
        if other in m.stretch:
            plan.joins.append((inside, icid, other, ocid))
            continue
        old = old_point_of(m, inside, icid)
        new = new_point_of(m, plan, inside, icid)
        moved = ft_to_mm(v_len(v_sub(new, old)))
        if moved > LOOSE_MM:
            plan.loose.append((inside, icid, other, moved))
        else:
            plan.joins.append((inside, icid, other, ocid))
    return plan


def old_point_of(m, eid, cid):
    c = m.conn(eid, cid)
    if eid in m.pipes and c is not None and c.get('end') is not None:
        return m.pipes[eid]['ends'][c['end']]
    return c['origin']


def new_point_of(m, plan, eid, cid):
    if eid in plan.fittings:
        return plan.fittings[eid]['conns'][cid]['origin']
    c = m.conn(eid, cid)
    if eid in plan.pipes and c is not None and c.get('end') is not None:
        return plan.pipes[eid][c['end']]
    return old_point_of(m, eid, cid)


def fall_ok(a, b, n, tol=SLOPE_TOL):
    """Is a->b at 1:n? Within tol of the fall, or within FALL_ABS_MM in height -
    whichever is looser, so a 7mm pipe between two fittings is not failed for
    a hundredth of a millimetre."""
    want = plan_dist(a, b) / float(n)
    got = abs(b[2] - a[2])
    return abs(got - want) <= max(tol * want, mm_to_ft(FALL_ABS_MM))


def fall_matters(a, b, n):
    """Whether a pipe is long enough for its direction of fall to be judged."""
    return plan_dist(a, b) / float(n) > mm_to_ft(FALL_ABS_MM)


def fall_text(a, b, n):
    want = ft_to_mm(plan_dist(a, b) / float(n))
    got = ft_to_mm(abs(b[2] - a[2]))
    if want < 5.0:
        return u'{0:.1f}mm of fall instead of {1:.1f}mm'.format(got, want)
    return u'{0}, not {1}'.format(ratio_text(gradient(a, b)), slope_label(n))


def check_plan(m, plan, tol=SLOPE_TOL):
    """Every pipe at 1:N falling towards the outlet, nothing moving sideways,
    no fitting turned hard or asked to fall two ways. Returns problem lines."""
    problems = []
    for pid, (a, b) in sorted(plan.pipes.items()):
        if not fall_ok(a, b, plan.n, tol):
            problems.append(u'Pipe {0} would have {1}.'.format(pid, fall_text(a, b, plan.n)))
        d0 = plan.dist[('p', pid, 0)]
        d1 = plan.dist[('p', pid, 1)]
        low_should = 0 if d0 < d1 else 1
        low_is = 0 if a[2] < b[2] else 1
        if (abs(d0 - d1) > 1e-6 and low_should != low_is
                and fall_matters(a, b, plan.n)):
            problems.append(u'Pipe {0} would fall the wrong way.'.format(pid))
        old = m.pipes[pid]['ends']
        side = ft_to_mm(max(plan_dist(a, old[0]), plan_dist(b, old[1])))
        if side > SIDEWAYS_MM:
            problems.append(u'Pipe {0} would move {1:.0f}mm sideways.'.format(pid, side))
    for fid, fp in sorted(plan.fittings.items()):
        turn = math.degrees(fp['angle'])
        if turn > MAX_TURN_DEG:
            problems.append(u'Fitting {0} would turn {1:.1f} degrees.'.format(fid, turn))
        if fp.get('miss', 0.0) > HEAD_ON_DEG:
            problems.append(u'Fitting {0} cannot follow the fall on every leg ({1:.1f} '
                            u'degrees out) - the runs meet at it from both sides.'.format(
                                fid, fp['miss']))
    return problems


def fall_summary(m, plan):
    """(pipes, fittings, uprights, branches) counts for a report line."""
    ups = len([s for s in m.stretch.values() if s['kind'] == 'upright'])
    brs = len([s for s in m.stretch.values() if s['kind'] == 'branch'])
    return len(m.pipes), len(m.fittings), ups, brs


# ====================== the prompt's live preview ======================

def plural(count, word):
    return u'{0} {1}{2}'.format(count, word, u'' if count == 1 else u's')


def horizontal_starts(adapter, starts):
    """(horizontal pipes, how many set ups / downs / uprights were left out)."""
    keep, steep = [], 0
    for el in starts:
        ends = adapter.ends(el)
        if is_steep(ends[0], ends[1]):
            steep += 1
        else:
            keep.append(el)
    return keep, steep


def make_preview(adapter, starts, limit=None, allowed=None):
    """A function (scope, upright) -> (text, hint) for the prompt, cached.

    It is run again every time the selection changes in Revit, so it walks at
    most PREVIEW_RUNS runs and says how many it left out rather than stalling
    Revit on a box-select of a whole floor. Apply always walks everything.
    `allowed` is the selected ids, for the 'selection' scope.
    """
    limit = PREVIEW_RUNS if limit is None else limit
    cache = {}

    def preview(scope, upright=None):
        if upright is not None:
            set_upright(upright)
        key = (scope, STEEP_DEG)
        if not starts:
            return (u'After Apply you will click the {0}.'.format(
                u'pipes and fittings' if scope == 'selection' else u'run'), None)
        if key in cache:
            return cache[key]
        pool, steep = starts, 0
        if scope == 'selection':
            pool, steep = horizontal_starts(adapter, starts)
        pipes, fits, ups, brs, runs = 0, 0, 0, 0, 0
        covered = set()
        problems = []
        first_model = None
        skipped = 0
        for s in pool:
            if adapter.eid(s) in covered:
                continue
            if runs + len(problems) >= limit:
                skipped += 1
                continue
            try:
                m = walk(adapter, s, scope, allowed if scope == 'selection' else None)
            except Refusal as r:
                problems.append(text_type(r))
                continue
            except Exception:
                problems.append(u'Could not read the run from pipe {0}.'.format(adapter.eid(s)))
                continue
            first_model = first_model or m
            covered.update(m.pipes.keys())
            runs += 1
            a, b, c, d = fall_summary(m, None)
            pipes += a
            fits += b
            ups += c
            brs += d
        parts = [plural(pipes, u'pipe'), plural(fits, u'fitting')]
        if ups:
            parts.append(plural(ups, u'set up / down') + u' will stretch')
        if brs:
            parts.append(plural(brs, u'joined pipe') + u' will stretch')
        noun = u'system' if scope == 'selection' else u'run'
        text = plural(runs, noun) + u': ' + u'  |  '.join(parts)
        if steep:
            text += u'\n{0} steeper than {1:.0f} degrees - left as they are.'.format(
                plural(steep, u'selected pipe'), STEEP_DEG)
        if skipped:
            text += u'\n{0} more selected pipe{1} not previewed - Apply takes them all.'.format(
                skipped, u'' if skipped == 1 else u's')
        if problems:
            text += u'\n' + u'\n'.join(problems)
        hint = None
        if first_model is not None:
            root, reason = choose_outlet_auto(build_graph(first_model))
            if root is None:
                hint = (u'This {0} is level and nothing says which way it falls - '
                        u'Apply will ask for the two clicks.'.format(noun))
            else:
                hint = u'Keeps its direction: {0}.'.format(reason)
        cache[key] = (text, hint)
        return cache[key]
    return preview


def selection_text(adapter, starts, others):
    if not starts:
        return u'Nothing selected - select a horizontal pipe in Revit, or Apply and click one.'
    first = starts[0]
    ends = adapter.ends(first)
    size = u''
    try:
        size = u' \u00d8{0:.0f}'.format(ft_to_mm(first.Diameter))
    except Exception:
        pass
    if is_steep(ends[0], ends[1]):
        now = u'a set up / down ({0:.0f} degrees)'.format(pitch_deg(ends[0], ends[1]))
    else:
        now = u'currently ' + ratio_text(gradient(ends[0], ends[1]))
    text = u'Pipe {0}{1} selected - {2}'.format(adapter.eid(first), size, now)
    extra = []
    if len(starts) > 1:
        extra.append(u'+' + plural(len(starts) - 1, u'more pipe'))
    if others:
        extra.append(plural(others, u'other element'))
    if extra:
        text += u' (' + u', '.join(extra) + u')'
    return text


# ====================== running a job ======================

def run_safely(work, done, on_error=None):
    """Run work(), then hand done() either (result, None) or (None, traceback).

    This is the body of the ExternalEvent handler. Revit swallows anything an
    event handler raises, which would leave the window stuck on "working" with
    nothing said - so nothing is allowed out, and done() is always called.
    """
    import traceback
    result, error = None, None
    try:
        result = work()
    except Exception:
        error = traceback.format_exc()
        if on_error is not None:
            try:
                on_error(error)
            except Exception:
                pass
    try:
        done(result, error)
    except Exception:
        if on_error is not None:
            try:
                on_error(traceback.format_exc())
            except Exception:
                pass
    return result, error


# ====================== reporting ======================

class Log(object):
    """A plain text log. Always written; shown when Debug is ticked."""

    def __init__(self):
        self.lines = []

    def add(self, text, *args):
        try:
            if args:
                text = text.format(*args)
        except Exception:
            pass
        self.lines.append(text_type(text))

    def section(self, title):
        self.lines.append(u'')
        self.lines.append(u'==== {0} ===='.format(title))

    def text(self):
        return u'\n'.join(self.lines)

    def write(self, path=None):
        path = path or os.path.join(settings_folder(), DEBUG_FILE)
        try:
            folder = os.path.dirname(path)
            if not os.path.isdir(folder):
                os.makedirs(folder)
            handle = io.open(path, 'w', encoding='utf-8')
            try:
                handle.write(self.text())
            finally:
                handle.close()
            return path
        except Exception:
            return None


def fmt_pt(pt):
    return u'({0:.1f}, {1:.1f}, {2:.1f})'.format(
        ft_to_mm(pt[0]), ft_to_mm(pt[1]), ft_to_mm(pt[2]))


def node_text(key):
    if key is None:
        return u'-'
    if key[0] == 'p':
        return u'pipe {0} end {1}'.format(key[1], key[2])
    return u'fitting {0}'.format(key[1])
