# -*- coding: utf-8 -*-
"""Bench test of the Pipe Slope Assigner rules, under plain CPython.

    python bench_logic.py              run every check
    python bench_logic.py --selftest   break the rules on purpose and confirm
                                       the checks notice

psa_core is the real code, driven by a fake adapter that builds runs of pipes
and fittings in memory - straight runs, L-shaped runs, tees, stacks, loops -
so the walk, the outlet choice, the fall and the fitting rotation are all
tested exactly as they run in Revit. psa_theme and the parameter-retention
half of psa_revit are loaded against a small stub Revit/.NET API.

Units are Revit's: feet.
"""

from __future__ import division, print_function

import contextlib
import math
import os
import random
import sys
import tempfile
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import psa_core as core  # noqa: E402

R = 0.25          # fitting connector offset from centre, ft
Z = 10.0          # a level run's height, ft


# ====================== a fake model ======================

class El(object):
    def __init__(self, eid, kind, ends=None, centre=None, group=False, name=u''):
        self.eid = eid
        self.kind = kind
        self.ends = ends
        self.centre = centre
        self.group = group
        self.name = name or kind
        self.conns = []


class Model(object):
    def __init__(self):
        self.els = {}
        self.next_id = 1000

    def _id(self):
        self.next_id += 1
        return self.next_id

    def pipe(self, a, b, eid=None):
        eid = eid or self._id()
        el = El(eid, 'pipe', ends=[tuple(map(float, a)), tuple(map(float, b))])
        for i, (p, q) in enumerate(((a, b), (b, a))):
            el.conns.append({'id': i, 'origin': tuple(map(float, p)),
                             'dir': core.v_norm(core.v_sub(p, q)), 'end': i,
                             'curve': False, 'partners': []})
        self.els[eid] = el
        return el

    def fitting(self, centre, dirs, kind='fitting', eid=None, r=R, group=False):
        eid = eid or self._id()
        el = El(eid, kind, centre=tuple(map(float, centre)), group=group)
        for i, d in enumerate(dirs):
            d = core.v_norm(d)
            el.conns.append({'id': i, 'origin': core.v_add(el.centre, core.v_scale(d, r)),
                             'dir': d, 'end': None, 'curve': False, 'partners': []})
        self.els[eid] = el
        return el

    def fitting_at(self, located, legs, kind='fitting', eid=None):
        """A fitting whose insertion point is NOT where its axes meet - the way
        a real 45 degree junction family is built. legs: [(origin, dir)]."""
        eid = eid or self._id()
        el = El(eid, kind, centre=tuple(map(float, located)))
        for i, (o, d) in enumerate(legs):
            el.conns.append({'id': i, 'origin': tuple(map(float, o)), 'dir': core.v_norm(d),
                             'end': None, 'curve': False, 'partners': []})
        self.els[eid] = el
        return el

    def join(self, a, ca, b, cb, curve=False):
        a.conns[ca]['partners'].append((b, cb))
        b.conns[cb]['partners'].append((a, ca))
        if curve:
            b.conns[cb]['curve'] = True


class FakeAdapter(object):
    def eid(self, el):
        return el.eid

    def kind(self, el):
        return el.kind

    def ends(self, el):
        return list(el.ends)

    def centre(self, el):
        return el.centre

    def connectors(self, el):
        return el.conns

    def in_group(self, el):
        return el.group

    def describe(self, el):
        return u'{0} {1}'.format(el.name, el.eid)


A = FakeAdapter()


def cp(el, i):
    """A fitting connector's origin."""
    return el.conns[i]['origin']


# ---------- run builders ----------

def straight_run(z0=Z, z1=Z, count=3, length=4.0):
    m = Model()
    total = count * length
    pipes, fits = [], []

    def zat(x):
        return z0 + (z1 - z0) * x / total

    left = None
    for k in range(count):
        x0 = k * length + (R if k else 0.0)
        x1 = (k + 1) * length - (R if k < count - 1 else 0.0)
        p = m.pipe((x0, 0.0, zat(x0)), (x1, 0.0, zat(x1)))
        pipes.append(p)
        if left is not None:
            m.join(left, 1, p, 0)
        if k < count - 1:
            cx = (k + 1) * length
            f = m.fitting((cx, 0.0, zat(cx)), [(-1, 0, 0), (1, 0, 0)])
            fits.append(f)
            m.join(p, 1, f, 0)
            left = f
    return m, pipes, fits


def l_run_to_stack(stack=True):
    """P1 along +X, elbow, P2 along +Y, elbow down into a stack (upright)."""
    m = Model()
    p1 = m.pipe((0.0, 0.0, Z), (4.0 - R, 0.0, Z))
    e1 = m.fitting((4.0, 0.0, Z), [(-1, 0, 0), (0, 1, 0)])
    p2 = m.pipe((4.0, R, Z), (4.0, 5.0, Z))
    e2 = m.fitting((4.0, 5.0 + R, Z), [(0, -1, 0), (0, 0, -1)])
    m.join(p1, 1, e1, 0)
    m.join(e1, 1, p2, 0)
    m.join(p2, 1, e2, 0)
    up = None
    if stack:
        up = m.pipe((4.0, 5.0 + R, Z - R), (4.0, 5.0 + R, Z - 9.0))
        m.join(e2, 1, up, 0)
    return m, [p1, p2], [e1, e2], up


def tee_run():
    """Main P1 - tee - P2 along +X, branch P3 off the tee along +Y, all level."""
    m = Model()
    p1 = m.pipe((0.0, 0.0, Z), (4.0 - R, 0.0, Z))
    t = m.fitting((4.0, 0.0, Z), [(-1, 0, 0), (1, 0, 0), (0, 1, 0)])
    p2 = m.pipe((4.0 + R, 0.0, Z), (8.0, 0.0, Z))
    p3 = m.pipe((4.0, R, Z), (4.0, 5.0, Z))
    m.join(p1, 1, t, 0)
    m.join(t, 1, p2, 0)
    m.join(t, 2, p3, 0)
    return m, p1, p2, p3, t


def concourse():
    """The run in the concourse drawing, cut down: a main at 1:40 along +X
    with 45 degree junctions whose insertion points sit off their axes, short
    pipes into 45 degree bends, branches running up to stacks, a stack down
    at the low end - and a 45 degree set down at the high end with more pipe
    beyond it that must not be touched."""
    m = Model()
    s = 1.0 / 40.0
    x_end = 12.0

    def zm(x):                          # main centreline, falling towards +X
        return Z + (x_end - x) * s

    q = 1.0 / math.sqrt(2.0)
    parts = {'main': [], 'wyes': [], 'branch': [], 'short': [], 'bends': []}
    # set down at the high end: bend, 45 degree pipe down, bend, pipe beyond
    sd_bend = m.fitting((0.0, 0.0, zm(0.0)), [(1, 0, 0), (-q, 0, -q)])
    sd_pipe = m.pipe(cp(sd_bend, 1), core.v_add(cp(sd_bend, 1), (-1.0, 0.0, -1.0)))
    m.join(sd_bend, 1, sd_pipe, 0)
    low_bend = m.fitting(core.v_add(sd_pipe.ends[1], (-R * q, 0.0, -R * q)),
                         [(q, 0, q), (-1, 0, 0)])
    m.join(sd_pipe, 1, low_bend, 0)
    beyond = m.pipe(cp(low_bend, 1), core.v_add(cp(low_bend, 1), (-3.0, 0.0, 0.0)))
    m.join(low_bend, 1, beyond, 0)
    parts.update({'sd_pipe': sd_pipe, 'beyond': beyond, 'sd_bend': sd_bend})

    left, left_c = sd_bend, 0
    x = R
    for k, xw in enumerate((3.0, 6.0, 9.0)):
        a = (x, 0.0, zm(x))
        b = (xw - R, 0.0, zm(xw - R))
        p = m.pipe(a, b)
        m.join(left, left_c, p, 0)
        parts['main'].append(p)
        hub = (xw, 0.0, zm(xw))
        legs = [((xw - R, 0.0, zm(xw - R)), (-1, 0, s)),
                ((xw + R, 0.0, zm(xw + R)), (1, 0, -s)),
                (core.v_add(hub, (R * q, R * q, 0.0)), (q, q, 0.0))]
        w = m.fitting_at((xw + 0.35, 0.12, zm(xw)), legs)   # insertion point off the axes
        parts['wyes'].append(w)
        m.join(p, 1, w, 0)
        # short 45 degree pipe, a 45 degree bend, a branch along +Y, an elbow up
        sp = m.pipe(cp(w, 2), core.v_add(cp(w, 2), (0.15, 0.15, 0.0)))
        m.join(w, 2, sp, 0)
        parts['short'].append(sp)
        bh = core.v_add(sp.ends[1], (R * q, R * q, 0.0))
        bend = m.fitting_at(core.v_add(bh, (0.05, -0.08, 0.0)),
                            [(sp.ends[1], (-q, -q, 0)), (core.v_add(bh, (0.0, R, 0.0)), (0, 1, 0))])
        m.join(sp, 1, bend, 0)
        br = m.pipe(cp(bend, 1), core.v_add(cp(bend, 1), (0.0, 3.0, 0.0)))
        m.join(bend, 1, br, 0)
        parts['branch'].append(br)
        up = m.fitting(core.v_add(br.ends[1], (0.0, R, 0.0)), [(0, -1, 0), (0, 0, 1)])
        m.join(br, 1, up, 0)
        stack = m.pipe(core.v_add(up.centre, (0.0, 0.0, R)), core.v_add(up.centre, (0.0, 0.0, 6.0)))
        m.join(up, 1, stack, 0)
        left, left_c = w, 1
        x = xw + R
    last = m.pipe((x, 0.0, zm(x)), (x_end - R, 0.0, zm(x_end - R)))
    m.join(left, left_c, last, 0)
    parts['main'].append(last)
    down = m.fitting((x_end, 0.0, zm(x_end)), [(-1, 0, 0), (0, 0, -1)])
    m.join(last, 1, down, 0)
    stack = m.pipe(core.v_add(down.centre, (0.0, 0.0, -R)), core.v_add(down.centre, (0.0, 0.0, -9.0)))
    m.join(down, 1, stack, 0)
    parts['down'] = down
    return m, parts


def geometry_after(m, plan):
    """New end points of every pipe and stretched pipe."""
    out = {}
    for pid, ends in plan.pipes.items():
        out[pid] = ends
    for sid, ends in plan.stretch.items():
        out[sid] = ends
    return out


# ====================== the checks ======================

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


class Fail(Exception):
    pass


def check(cond, text):
    if not cond:
        raise Fail(text)


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def plan_for(m, start, scope='run', n=100, anchor=None, picks=None):
    rm = core.walk(A, start, scope)
    g = core.build_graph(rm)
    if picks is not None:
        (fp, fpt), (tp, tpt) = picks
        sf, _ = core.click_sources(rm, fp.eid, fpt)
        st, _ = core.click_sources(rm, tp.eid, tpt)
        root, reason = core.choose_outlet_picked(g, sf, st)
    else:
        root, reason = core.choose_outlet_auto(g)
    check(root is not None, u'no outlet: {0}'.format(reason))
    plan = core.make_plan(rm, g, n, root, anchor or ('node', root))
    return rm, g, plan, reason


def assert_exact_fall(rm, plan, n, tol=1e-3):
    target = 1.0 / n
    for pid, (a, b) in plan.pipes.items():
        g = core.gradient(a, b)
        height_err = core.ft_to_mm(abs(abs(b[2] - a[2]) - core.plan_dist(a, b) * target))
        check(abs(g - target) <= tol * target or height_err < 0.05,
              u'pipe {0} at {1}, wanted 1:{2} ({3:.3f}mm out)'.format(
                  pid, core.ratio_text(g), n, height_err))
    check(not core.check_plan(rm, plan), u'check_plan: {0}'.format(core.check_plan(rm, plan)))


def assert_joints_meet(rm, plan, tol=1e-9):
    for (a, ca, b, cb) in plan.joins:
        pa = core.new_point_of(rm, plan, a, ca)
        if b in rm.stretch:
            s = rm.stretch[b]
            c = [x for x in s['conns'] if x['id'] == cb][0]
            pb = plan.stretch[b][c['end']]
        else:
            pb = core.new_point_of(rm, plan, b, cb)
        gap = core.v_len(core.v_sub(pa, pb))
        check(gap <= tol, u'joint {0}/{1} - {2}/{3} opens {4:.4f} mm'.format(
            a, ca, b, cb, core.ft_to_mm(gap)))


# ---------- settings ----------

@test
def settings_defaults():
    d = core.default_settings()
    check(d['slope'] == '100' and d['scope'] == 'run' and d['direction'] == 'auto',
          u'defaults changed: {0}'.format(d))
    check(d['debug'] == '0' and d['show_results'] == 'issues' and d['theme'] == 'auto',
          u'defaults changed: {0}'.format(d))


@test
def settings_round_trip():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'x', core.SETTINGS_FILE)
    v = core.default_settings()
    v.update({'slope': '40', 'scope': 'network', 'direction': 'pick',
              'anchor': 'high', 'theme': 'light', 'debug': '1', 'show_results': 'always'})
    check(core.save_settings(v, path), u'save failed')
    back = core.load_settings(path)
    for k, _ in core.DEFAULTS:
        check(back[k] == v[k], u'{0}: {1} != {2}'.format(k, back[k], v[k]))


@test
def settings_bad_values_fall_back():
    text = u'slope=33\nscope=everything\nnope=1\ndebug=1\n=\ngarbage line\nanchor = high \n'
    v = core.parse_settings(text)
    check(v['slope'] == '100', u'invalid slope kept: {0}'.format(v['slope']))
    check(v['scope'] == 'run', u'invalid scope kept')
    check('nope' not in v, u'unknown key kept')
    check(v['debug'] == '1' and v['anchor'] == 'high', u'valid keys lost')


@test
def settings_missing_file():
    v = core.load_settings(os.path.join(tempfile.mkdtemp(), 'none.txt'))
    check(v == core.default_settings(), u'missing file did not give defaults')


@test
def settings_migration_resets():
    old = dict(core.MIGRATIONS)
    old_v = core.SETTINGS_VERSION
    try:
        core.MIGRATIONS[2] = ('slope',)
        core.SETTINGS_VERSION = 2
        v = core.parse_settings(u'settings_version=1\nslope=40\nscope=network\n')
        check(v['slope'] == '100', u'migrated key not reset')
        check(v['scope'] == 'network', u'unmigrated key lost')
        v = core.parse_settings(u'settings_version=2\nslope=40\n')
        check(v['slope'] == '40', u'current file was reset')
    finally:
        core.MIGRATIONS.clear()
        core.MIGRATIONS.update(old)
        core.SETTINGS_VERSION = old_v


@test
def settings_window_and_place():
    d = core.default_settings()
    check(d['window'] == 'modeless', u'window does not default to modeless')
    v = core.parse_settings(u'window=floating\nleft=120\ntop=abc\n')
    check(v['window'] == 'modeless', u'invalid window mode kept')
    check(v['left'] == '120' and v['top'] == '', u'place: {0} {1}'.format(v['left'], v['top']))
    v = core.parse_settings(u'window=modal\nleft=nan\n')
    check(v['window'] == 'modal' and v['left'] == '', u'modal / nan not handled')


# ---------- the modeless job ----------

@test
def job_always_reports_back():
    heard = []
    errors = []
    core.run_safely(lambda: 5, lambda r, e: heard.append((r, e)), errors.append)
    check(heard == [(5, None)], u'result not handed back: {0}'.format(heard))

    def boom():
        raise ValueError('nope')
    heard[:] = []
    core.run_safely(boom, lambda r, e: heard.append((r, e)), errors.append)
    check(len(heard) == 1 and heard[0][0] is None and 'nope' in heard[0][1],
          u'a failing job left the window waiting: {0}'.format(heard))
    check(any('nope' in e for e in errors), u'the failure was not written down')

    def bad_done(r, e):
        raise RuntimeError('done broke')
    try:
        core.run_safely(lambda: 1, bad_done, errors.append)
    except Exception:
        check(False, u'an exception escaped into Revit\'s event handler')
    check(any('done broke' in e for e in errors), u'a broken done() was not written down')


@test
def preview_is_capped():
    m = Model()
    starts = [m.pipe((0.0, 10.0 * k, Z), (4.0, 10.0 * k, Z)) for k in range(27)]
    text, hint = core.make_preview(A, starts)('run')
    check(text.startswith(u'20 runs'), u'preview: {0}'.format(text))
    check(u'7 more selected pipes not previewed' in text, u'skipped count missing: {0}'.format(text))
    text, hint = core.make_preview(A, starts[:1])('run')
    check(text.startswith(u'1 run: 1 pipe'), u'single preview: {0}'.format(text))
    check(u'not previewed' not in text, u'single run said it skipped something')


@test
def selection_wording():
    m, pipes, fits = straight_run(z0=Z + 0.12, z1=Z)
    t = core.selection_text(A, pipes[:2], 3)
    check(t.startswith(u'Pipe {0} selected - currently 1:100'.format(pipes[0].eid)),
          u'selection text: {0}'.format(t))
    check(u'(+1 more pipe, 3 other elements)' in t, u'counts: {0}'.format(t))
    check(u'Nothing selected' in core.selection_text(A, [], 0), u'empty selection text')


# ---------- wording ----------

@test
def slope_wording():
    check([core.slope_label(n) for n in core.SLOPES] == [u'1:100', u'1:80', u'1:60', u'1:40'],
          u'labels')
    check([core.slope_percent_text(n) for n in core.SLOPES]
          == [u'1 %', u'1.25 %', u'1.67 %', u'2.5 %'], u'percent')
    check([core.slope_mm_per_m_text(n) for n in core.SLOPES]
          == [u'10 mm/m', u'12.5 mm/m', u'16.7 mm/m', u'25 mm/m'], u'mm/m')
    check(core.ratio_text(0.0) == u'level' and core.ratio_text(0.01) == u'1:100',
          u'ratio_text')


@test
def steep_line():
    check(core.STEEP_DEG == 15.0, u'set up / down line is {0}, not 15'.format(core.STEEP_DEG))
    check(core.is_steep((0, 0, 0), (1, 0, 1.0)), u'a 45 degree set down counted as horizontal')
    check(core.is_steep((0, 0, 0), (1, 0, 0.5)), u'a 26 degree set down counted as horizontal')
    check(not core.is_steep((0, 0, 0), (1, 0, 0.1)), u'1:10 counted as a set down')
    check(core.is_steep((0, 0, 0), (0, 0, 3)), u'vertical not an upright')
    try:
        check(core.set_upright({'upright': '30'}) == 30.0, u'setting not taken')
        check(not core.is_steep((0, 0, 0), (1, 0, 0.5)), u'26 degrees steep at a 30 line')
        check(core.set_upright('nonsense') == 30.0, u'nonsense changed the line')
    finally:
        core.set_upright(15)


# ---------- rotations ----------

@test
def rotation_recovered():
    rnd = random.Random(7)
    for _ in range(40):
        axis = (rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))
        angle = rnd.uniform(0.0, 3.0)
        q = core.q_from_axis_angle(axis, angle)
        dirs = [core.v_norm((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)))
                for _ in range(3)]
        got = core.best_fit_rotation([(d, core.q_rotate(q, d), 1.0) for d in dirs])
        for d in dirs:
            err = core.v_len(core.v_sub(core.q_rotate(got, d), core.q_rotate(q, d)))
            check(err < 1e-7, u'rotation not recovered ({0})'.format(err))


@test
def rotation_rank_one_is_smallest():
    a = (1.0, 0.0, 0.0)
    b = core.v_norm((1.0, 0.0, -0.01))
    q = core.best_fit_rotation([(a, b, 1.0), ((-1.0, 0.0, 0.0), core.v_scale(b, -1), 1.0)])
    axis, angle = core.q_to_axis_angle(q)
    check(close(angle, math.atan(0.01), 1e-9), u'union turned {0}'.format(angle))
    check(abs(abs(axis[1]) - 1.0) < 1e-9, u'union turned about {0}'.format(axis))


@test
def q_between_opposite():
    q = core.q_between((1, 0, 0), (-1, 0, 0))
    r = core.q_rotate(q, (1, 0, 0))
    check(core.v_len(core.v_sub(r, (-1, 0, 0))) < 1e-9, u'half turn wrong')


# ---------- the walk ----------

@test
def walk_straight_run():
    m, pipes, fits = straight_run()
    rm = core.walk(A, pipes[1], 'run')
    check(set(rm.pipes) == set(p.eid for p in pipes), u'pipes: {0}'.format(sorted(rm.pipes)))
    check(set(rm.fittings) == set(f.eid for f in fits), u'fittings')
    check(len(rm.links) == 4, u'links: {0}'.format(len(rm.links)))


@test
def walk_tee_run_goes_straight_through():
    m, p1, p2, p3, t = tee_run()
    rm = core.walk(A, p1, 'run')
    check(set(rm.pipes) == {p1.eid, p2.eid}, u'run scope took {0}'.format(sorted(rm.pipes)))
    check(t.eid in rm.fittings, u'tee not in the run')
    check(p3.eid in rm.stretch and rm.stretch[p3.eid]['kind'] == 'branch',
          u'branch pipe not stretched')


@test
def walk_tee_network_takes_all():
    m, p1, p2, p3, t = tee_run()
    rm = core.walk(A, p1, 'network')
    check(set(rm.pipes) == {p1.eid, p2.eid, p3.eid}, u'network took {0}'.format(sorted(rm.pipes)))
    check(not rm.stretch, u'network stretched something')


@test
def walk_from_branch_leaves_main_alone():
    m, p1, p2, p3, t = tee_run()
    rm = core.walk(A, p3, 'run')
    check(set(rm.pipes) == {p3.eid}, u'branch run took {0}'.format(sorted(rm.pipes)))
    check(t.eid in rm.fixed and rm.fixed[t.eid]['kind'] == 'main', u'tee not fixed as main')


@test
def walk_upright_stretches():
    m, pipes, fits, up = l_run_to_stack()
    rm = core.walk(A, pipes[0], 'run')
    check(set(rm.pipes) == set(p.eid for p in pipes), u'pipes')
    check(up.eid in rm.stretch and rm.stretch[up.eid]['kind'] == 'upright', u'stack not stretched')
    check(rm.stretch[up.eid]['down'], u'stack not seen as going down')


@test
def walk_refuses_upright_start_and_groups():
    m, pipes, fits, up = l_run_to_stack()
    try:
        core.walk(A, up, 'run')
        check(False, u'upright start accepted')
    except core.Refusal:
        pass
    m, pipes, fits = straight_run()
    fits[0].group = True
    try:
        core.walk(A, pipes[0], 'run')
        check(False, u'group accepted')
    except core.Refusal:
        pass


@test
def walk_refuses_huge_runs():
    m, pipes, fits = straight_run(count=min(core.MAX_ELEMENTS, 2000) // 2 + 2, length=2.0)
    try:
        core.walk(A, pipes[0], 'run')
        check(False, u'a run of {0} elements was accepted'.format(len(pipes) + len(fits)))
    except core.Refusal:
        pass


@test
def walk_fixture_and_takeoff_are_fixed():
    m, pipes, fits = straight_run(count=2)
    wc = m.fitting((-R, 0.0, Z), [(1, 0, 0)], kind='fixed')
    m.join(pipes[0], 0, wc, 0)
    tk = m.fitting((6.0, 0.0, Z), [(0, 1, 0)])
    m.join(pipes[1], 0, tk, 0, curve=False)
    pipes[1].conns.append({'id': 7, 'origin': (6.0, 0.0, Z), 'dir': (0, 1, 0), 'end': None,
                           'curve': True, 'partners': []})
    tk2 = m.fitting((6.0, 0.1, Z), [(0, -1, 0)])
    pipes[1].conns[-1]['partners'].append((tk2, 0))
    tk2.conns[0]['partners'].append((pipes[1], 7))
    rm = core.walk(A, pipes[0], 'run')
    check(rm.fixed.get(wc.eid, {}).get('kind') == 'fixture', u'fixture not fixed')
    check(rm.fixed.get(tk2.eid, {}).get('kind') == 'takeoff', u'takeoff not fixed')
    check(any(u'akeoff' in n for n in rm.notes), u'takeoff not noted')


# ---------- the outlet ----------

@test
def outlet_follows_existing_fall():
    m, pipes, fits = straight_run(z0=Z + 0.5, z1=Z)
    rm, g, plan, reason = plan_for(m, pipes[0])
    check(plan.root == ('p', pipes[-1].eid, 1), u'outlet {0}'.format(plan.root))
    m, pipes, fits = straight_run(z0=Z, z1=Z + 0.5)
    rm, g, plan, reason = plan_for(m, pipes[0])
    check(plan.root == ('p', pipes[0].eid, 0), u'reversed outlet {0}'.format(plan.root))


@test
def outlet_level_run_to_stack():
    m, pipes, fits, up = l_run_to_stack()
    rm = core.walk(A, pipes[0], 'run')
    root, reason = core.choose_outlet_auto(core.build_graph(rm))
    check(root == ('f', fits[1].eid), u'outlet {0} ({1})'.format(root, reason))


@test
def outlet_level_branch_to_main():
    m, p1, p2, p3, t = tee_run()
    rm = core.walk(A, p3, 'run')
    root, reason = core.choose_outlet_auto(core.build_graph(rm))
    check(root == ('p', p3.eid, 0), u'outlet {0} ({1})'.format(root, reason))


@test
def outlet_level_free_run_asks():
    m, pipes, fits = straight_run()
    rm = core.walk(A, pipes[0], 'run')
    root, reason = core.choose_outlet_auto(core.build_graph(rm))
    check(root is None, u'a level free run picked {0}'.format(root))


@test
def outlet_from_clicks():
    m, pipes, fits = straight_run()
    fpt = (1.0, 0.0, Z)
    tpt = (10.0, 0.0, Z)
    rm, g, plan, reason = plan_for(m, pipes[0], picks=((pipes[0], fpt), (pipes[2], tpt)))
    check(plan.root == ('p', pipes[2].eid, 1), u'outlet {0}'.format(plan.root))
    rm, g, plan, reason = plan_for(m, pipes[0], picks=((pipes[2], tpt), (pipes[0], fpt)))
    check(plan.root == ('p', pipes[0].eid, 0), u'reversed outlet {0}'.format(plan.root))


@test
def clicks_override_existing_fall():
    m, pipes, fits = straight_run(z0=Z + 0.5, z1=Z)       # falls towards +X now
    fpt, tpt = (10.0, 0.0, Z), (1.0, 0.0, Z + 0.4)
    rm, g, plan, reason = plan_for(m, pipes[0], picks=((pipes[2], fpt), (pipes[0], tpt)))
    check(plan.root == ('p', pipes[0].eid, 0), u'clicks ignored: {0}'.format(plan.root))
    a, b = plan.pipes[pipes[0].eid]
    check(a[2] < b[2], u'first pipe falls the old way')


# ---------- the fall ----------

@test
def straight_run_exact_fall_all_slopes():
    for n in core.SLOPES:
        m, pipes, fits = straight_run(z0=Z + 0.2, z1=Z)
        rm, g, plan, reason = plan_for(m, pipes[0], n=n)
        assert_exact_fall(rm, plan, n, tol=1e-9)
        assert_joints_meet(rm, plan)
        lo = plan.pipes[pipes[-1].eid][1]
        check(close(lo[2], Z, 1e-9), u'low anchor moved the outlet: {0}'.format(lo[2]))


@test
def l_run_both_legs_exact():
    for n in core.SLOPES:
        m, pipes, fits, up = l_run_to_stack()
        rm, g, plan, reason = plan_for(m, pipes[0], n=n)
        assert_exact_fall(rm, plan, n, tol=1e-3)
        assert_joints_meet(rm, plan)
        # every connector of every fitting points along its pipe's new axis
        for f in fits:
            fp = plan.fittings[f.eid]
            for c in f.conns:
                for (oid, ocid) in rm.partners_of(f.eid, c['id']):
                    if oid not in plan.pipes:
                        continue
                    oc = rm.conn(oid, ocid)
                    ends = plan.pipes[oid]
                    away = core.v_norm(core.v_sub(ends[1 - oc['end']], ends[oc['end']]))
                    got = fp['conns'][c['id']]['dir']
                    err = math.degrees(math.acos(max(-1.0, min(1.0, core.v_dot(away, got)))))
                    check(err < 0.05, u'fitting {0} connector {1} off by {2:.3f} deg'.format(
                        f.eid, c['id'], err))


@test
def stack_stretches_far_end_fixed():
    m, pipes, fits, up = l_run_to_stack()
    rm, g, plan, reason = plan_for(m, pipes[0], n=40)
    a, b = plan.stretch[up.eid]
    check(b == up.ends[1], u'stack foot moved')
    new_c = plan.fittings[fits[1].eid]['conns'][1]['origin']
    check(core.v_len(core.v_sub(a, new_c)) < 1e-12, u'stack head not on the elbow')
    check(core.pitch_deg(a, b) > 89.0, u'stack no longer upright: {0}'.format(core.pitch_deg(a, b)))


@test
def high_anchor_holds_the_head():
    m, pipes, fits, up = l_run_to_stack()
    rm = core.walk(A, pipes[0], 'run')
    g = core.build_graph(rm)
    root, _ = core.choose_outlet_auto(g)
    dist = g.dijkstra({root: 0.0})
    head = max(core.terminals(g), key=lambda k: dist[k])
    plan = core.make_plan(rm, g, 60, root, ('node', head))
    check(close(plan.pipes[pipes[0].eid][0][2], Z, 1e-9), u'head moved')
    check(plan.node_z[root] < Z, u'outlet did not drop')


@test
def point_anchor_holds_click_height():
    m, pipes, fits = straight_run()
    click = (6.0, 0.0, Z)
    rm = core.walk(A, pipes[0], 'run')
    g = core.build_graph(rm)
    sf, _ = core.click_sources(rm, pipes[0].eid, (1.0, 0.0, Z))
    st, _ = core.click_sources(rm, pipes[1].eid, click)
    root, _ = core.choose_outlet_picked(g, sf, st)
    plan = core.make_plan(rm, g, 100, root, ('point', pipes[1].eid, click))
    a, b = plan.pipes[pipes[1].eid]
    t = (6.0 - a[0]) / (b[0] - a[0])
    zc = a[2] + (b[2] - a[2]) * t
    check(close(zc, Z, 1e-9), u'height under the click moved to {0}'.format(zc))


@test
def tee_network_exact():
    m, p1, p2, p3, t = tee_run()
    down = m.fitting((8.0 + R, 0.0, Z), [(-1, 0, 0), (0, 0, -1)])
    m.join(p2, 1, down, 0)
    stack = m.pipe((8.0 + R, 0.0, Z - R), (8.0 + R, 0.0, Z - 8))
    m.join(down, 1, stack, 0)
    rm, g, plan, reason = plan_for(m, p1, scope='network', n=80)
    check(plan.root == ('f', down.eid), u'outlet {0}'.format(plan.root))
    assert_exact_fall(rm, plan, 80, tol=1e-3)
    assert_joints_meet(rm, plan)


@test
def run_scope_branch_follows_tee():
    m, p1, p2, p3, t = tee_run()
    rm, g, plan, reason = plan_for(m, p1, picks=((p1, (1.0, 0, Z)), (p2, (7.0, 0, Z))))
    a, b = plan.stretch[p3.eid]
    new_c = plan.fittings[t.eid]['conns'][2]['origin']
    check(core.v_len(core.v_sub(a, new_c)) < 1e-12, u'branch not on the tee')
    check(b == p3.ends[1], u'branch far end moved')
    assert_joints_meet(rm, plan)


@test
def fixed_fixture_goes_loose_when_moved():
    m, pipes, fits = straight_run()
    wc = m.fitting((-R, 0.0, Z), [(1, 0, 0)], kind='fixed')
    m.join(pipes[0], 0, wc, 0)
    fpt, tpt = (1.0, 0.0, Z), (11.0, 0.0, Z)
    rm, g, plan, reason = plan_for(m, pipes[0], picks=((pipes[0], fpt), (pipes[2], tpt)))
    check(any(x[2] == wc.eid for x in plan.loose), u'moved fixture joint not reported loose')
    check(not any(j[2] == wc.eid or j[0] == wc.eid for j in plan.joins),
          u'moved fixture joint still rejoined')


@test
def fixed_joint_rejoined_when_it_stays():
    m, p1, p2, p3, t = tee_run()
    rm, g, plan, reason = plan_for(m, p3)     # level branch, falls to the main
    check(not plan.loose, u'held joint reported loose: {0}'.format(plan.loose))
    check(any(t.eid in (j[0], j[2]) for j in plan.joins), u'joint to the main dropped')


@test
def loop_is_warned():
    """An L-shaped ring of pipe. Measured round the ring from one corner, the
    farthest point lands half way along a pipe - that pipe cannot fall one way
    along its whole length, and has to be flagged."""
    m = Model()
    corners = [(0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)]
    count = len(corners)
    elbows = []
    for i, (x, y) in enumerate(corners):
        prev, nxt = corners[i - 1], corners[(i + 1) % count]
        elbows.append(m.fitting((x, y, Z), [(prev[0] - x, prev[1] - y, 0),
                                            (nxt[0] - x, nxt[1] - y, 0)]))
    pipes = []
    for i in range(count):
        e, f = elbows[i], elbows[(i + 1) % count]
        p = m.pipe(cp(e, 1), cp(f, 0))
        m.join(e, 1, p, 0)
        m.join(p, 1, f, 0)
        pipes.append(p)
    rm = core.walk(A, pipes[0], 'run')
    check(len(rm.pipes) == count, u'ring not walked whole')
    g = core.build_graph(rm)
    root, reason = core.choose_outlet_auto(g)
    check(root is None, u'a ring picked an outlet')
    root = ('f', elbows[2].eid)
    plan = core.make_plan(rm, g, 100, root, ('node', root))
    check(any(str(pipes[5].eid) in w for w in plan.warnings),
          u'ring pipe not warned: {0}'.format(plan.warnings))


@test
def concourse_network_to_1_in_60():
    """The failure from site: network scope over a run of 45 degree junctions
    whose insertion points are off their axes, with a set down at one end."""
    for n in (60, 100, 40):
        m, parts = concourse()
        rm, g, plan, reason = plan_for(m, parts['main'][0], scope='network', n=n)
        check(plan.root == ('f', parts['down'].eid), u'outlet {0}'.format(plan.root))
        check(parts['sd_pipe'].eid in rm.stretch, u'the 45 degree set down was re-sloped')
        check(parts['beyond'].eid not in rm.pipes, u'the walk went past the set down')
        check(len(rm.pipes) == 4 + 3 + 3, u'network took {0} pipes'.format(len(rm.pipes)))
        problems = core.check_plan(rm, plan)
        check(not problems, u'1:{0}: {1}'.format(n, problems))
        assert_exact_fall(rm, plan, n, tol=1e-3)
        assert_joints_meet(rm, plan)


@test
def hub_is_where_the_axes_meet():
    m, parts = concourse()
    w = parts['wyes'][0]
    rm = core.walk(A, parts['main'][0], 'network')
    hub = rm.fittings[w.eid]['centre']
    check(core.plan_dist(hub, (3.0, 0.0, 0.0)) < 1e-7, u'wye hub at {0}'.format(hub))
    one = m.fitting((1.0, 2.0, 3.0), [(1, 0, 0)])
    check(core.v_len(core.v_sub(core.fitting_hub(one.conns), cp(one, 0))) < 1e-9,
          u'a cap is not its own connector')
    cpl = m.fitting((1.0, 2.0, 3.0), [(1, 0, 0), (-1, 0, 0)])
    check(core.v_len(core.v_sub(core.fitting_hub(cpl.conns), (1.0, 2.0, 3.0))) < 1e-9,
          u'coupling hub off its middle')
    up = m.fitting((5.0, 5.0, 5.0), [(0, -1, 0), (0, 0, 1)])
    check(core.v_len(core.v_sub(core.fitting_hub(up.conns), (5.0, 5.0, 5.0))) < 1e-9,
          u'elbow-to-stack hub off its corner')


@test
def selection_system_takes_only_the_selection():
    m, p1, p2, p3, t = tee_run()
    allowed = {p1.eid, p2.eid, t.eid}
    rm = core.walk(A, p1, 'selection', allowed)
    check(set(rm.pipes) == {p1.eid, p2.eid}, u'took {0}'.format(sorted(rm.pipes)))
    check(rm.stretch.get(p3.eid, {}).get('kind') == 'branch', u'unselected pipe not stretched')
    rm = core.walk(A, p1, 'selection', allowed | {p3.eid})
    check(set(rm.pipes) == {p1.eid, p2.eid, p3.eid}, u'selected branch left out')
    rm = core.walk(A, p1, 'selection', {p1.eid, p2.eid})
    check(set(rm.pipes) == {p1.eid} and t.eid in rm.fixed, u'unselected tee not held')


@test
def selection_system_falls_together():
    m, parts = concourse()
    allowed = set(e for e in m.els) - {parts['sd_pipe'].eid, parts['beyond'].eid}
    starts = [m.els[e] for e in sorted(allowed) if m.els[e].kind == 'pipe']
    keep, steep = core.horizontal_starts(A, starts)
    check(steep == 4, u'{0} steep pipes left out, wanted the 4 stacks'.format(steep))
    rm = core.walk(A, keep[0], 'selection', allowed)
    check(len(rm.pipes) == 10, u'system took {0} pipes'.format(len(rm.pipes)))
    g = core.build_graph(rm)
    root, reason = core.choose_outlet_auto(g)
    plan = core.make_plan(rm, g, 80, root, ('node', root))
    check(not core.check_plan(rm, plan), u'{0}'.format(core.check_plan(rm, plan)))
    text, hint = core.make_preview(A, starts, allowed=allowed)('selection')
    check(text.startswith(u'1 system: 10 pipes'), u'preview: {0}'.format(text))
    check(u'4 selected pipes steeper than 15 degrees' in text, u'preview: {0}'.format(text))


@test
def two_selected_systems_are_two():
    m1, pipes1, fits1 = straight_run()
    m2, pipes2, fits2 = straight_run()
    for el in m2.els.values():
        m1.els[el.eid + 5000] = el
        el.eid += 5000
    allowed = set(e.eid for e in pipes1 + fits1 + pipes2 + fits2)
    text, hint = core.make_preview(A, pipes1 + pipes2, allowed=allowed)('selection')
    check(text.startswith(u'2 systems: 6 pipes  |  4 fittings'), u'preview: {0}'.format(text))


@test
def checks_refuse_what_should_not_happen():
    m, pipes, fits = straight_run()
    rm, g, plan, reason = plan_for(m, pipes[0], picks=((pipes[0], (1.0, 0, Z)),
                                                       (pipes[2], (11.0, 0, Z))))
    a, b = plan.pipes[pipes[1].eid]
    plan.pipes[pipes[1].eid] = (core.v_add(a, (0.1, 0.0, 0.0)), b)
    check(any(u'sideways' in p for p in core.check_plan(rm, plan)), u'sideways move not caught')
    plan.pipes[pipes[1].eid] = (a, b)
    plan.fittings[fits[0].eid]['angle'] = math.radians(20.0)
    check(any(u'turn' in p for p in core.check_plan(rm, plan)), u'hard turn not caught')
    plan.fittings[fits[0].eid]['angle'] = 0.0
    plan.fittings[fits[0].eid]['miss'] = 3.0
    check(any(u'both sides' in p for p in core.check_plan(rm, plan)), u'head-on not caught')


@test
def short_pipes_judged_in_millimetres():
    n = 60
    a = (0.0, 0.0, 0.0)
    b = (core.mm_to_ft(7.0), 0.0, -core.mm_to_ft(7.0 / n) - core.mm_to_ft(0.1))
    check(core.fall_ok(a, b, n), u'a 7mm pipe failed on 0.1mm')
    b = (core.mm_to_ft(1000.0), 0.0, -core.mm_to_ft(1000.0 / 40))
    check(not core.fall_ok(a, b, n), u'1:40 passed as 1:60')


@test
def nothing_to_do_detected():
    m, pipes, fits = straight_run(z0=Z + 12.0 / 100.0, z1=Z)
    rm, g, plan, reason = plan_for(m, pipes[0], n=100)
    moved = 0.0
    for pid, (a, b) in plan.pipes.items():
        old = rm.pipes[pid]['ends']
        moved = max(moved, core.v_len(core.v_sub(a, old[0])), core.v_len(core.v_sub(b, old[1])))
    check(core.ft_to_mm(moved) < 0.05, u'a run already at 1:100 moves {0} mm'.format(
        core.ft_to_mm(moved)))


# ====================== the stubbed .NET / Revit side ======================

class _Enum(object):
    def __init__(self, name, value):
        self.name, self.value = name, value

    def __int__(self):
        return self.value

    def __bool__(self):
        return bool(self.value)

    __nonzero__ = __bool__

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, _Enum) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


def _enum_class(name, members):
    cls = type(name, (object,), {})
    for i, m in enumerate(members):
        setattr(cls, m, _Enum(m, i))
    return cls


class _Anything(object):
    def __init__(self, *a, **k):
        pass


@contextlib.contextmanager
def stub_revit(ui_theme=None):
    saved = dict(sys.modules)
    mods = {}

    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        mods[name] = m
        return m

    clr = mod('clr', AddReference=lambda name: None)
    mod('System', AppDomain=_Anything)
    mod('System.Collections')
    mod('System.Collections.Generic', List=_Anything)
    db_names = ['BuiltInCategory', 'ConnectorType', 'ElementId', 'ElementTransformUtils',
                'FailureProcessingResult', 'FailureSeverity', 'FamilyInstance',
                'IFailuresPreprocessor', 'Line', 'LocationPoint', 'Transaction',
                'TransactionStatus', 'WorksharingUtils', 'XYZ', 'TransactionGroup']
    db = mod('Autodesk.Revit.DB', **dict((n, type(n, (object,), {})) for n in db_names))
    db.StorageType = _enum_class('StorageType', ['None_', 'Integer', 'Double', 'String',
                                                 'ElementId'])
    bip = type('BuiltInParameter', (object,), {})
    for i, n in enumerate(['RBS_OFFSET_PARAM', 'RBS_PIPE_SLOPE', 'CURVE_ELEM_LENGTH']):
        setattr(bip, n, _Enum(n, -1000 - i))
    db.BuiltInParameter = bip
    mod('Autodesk')
    mod('Autodesk.Revit')
    mod('Autodesk.Revit.DB.Plumbing', Pipe=type('Pipe', (object,), {}))
    ui = mod('Autodesk.Revit.UI')
    if ui_theme is not None:
        ui.UIThemeManager = type('UIThemeManager', (object,), {'CurrentCanvasTheme': ui_theme})
    for k in list(sys.modules):
        if k.startswith('psa_') and k != 'psa_core':
            del sys.modules[k]
    sys.modules.update(mods)
    sys.modules['Autodesk'].Revit = sys.modules['Autodesk.Revit']
    sys.modules['Autodesk.Revit'].DB = sys.modules['Autodesk.Revit.DB']
    sys.modules['Autodesk.Revit'].UI = sys.modules['Autodesk.Revit.UI']
    try:
        yield sys.modules
    finally:
        for k in list(sys.modules):
            if k not in saved:
                del sys.modules[k]
        sys.modules.update(saved)


class FakeId(object):
    def __init__(self, v):
        self.Value = v


class FakeDef(object):
    def __init__(self, name):
        self.Name = name


class FakeParam(object):
    def __init__(self, pid, name, st, value, readonly=False):
        self.Id = FakeId(pid)
        self.Definition = FakeDef(name)
        self.StorageType = st
        self.value = value
        self.IsReadOnly = readonly
        self.HasValue = True

    def AsString(self):
        return self.value

    def AsDouble(self):
        return self.value

    def AsInteger(self):
        return self.value

    def AsElementId(self):
        return self.value

    def Set(self, v):
        self.value = v


class FakeEl(object):
    def __init__(self, eid, params):
        self.Id = FakeId(eid)
        self.Parameters = params

    def LookupParameter(self, name):
        for p in self.Parameters:
            if p.Definition.Name == name:
                return p
        return None


@test
def theme_follows_canvas_even_when_dark_is_zero():
    dark = _Enum('Dark', 0)          # UITheme.Dark == 0: falsy, still an answer
    with stub_revit(ui_theme=dark):
        import psa_theme
        check(psa_theme.canvas_theme() == 'dark', u'dark canvas read as {0}'.format(
            psa_theme.canvas_theme()))
        check(psa_theme.resolve('auto') == 'dark', u'auto did not follow the canvas')
        check(psa_theme.resolve('light') == 'light', u'explicit mode overridden')
    with stub_revit(ui_theme=_Enum('Light', 1)):
        import psa_theme
        check(psa_theme.resolve('auto') == 'light', u'light canvas not followed')
        check(psa_theme.chip_text('auto') == u'Auto \u00b7 Light', u'chip text')
    with stub_revit():
        import psa_theme
        check(psa_theme.resolve('auto') == 'dark', u'no theme manager did not fall back')
        check([psa_theme.next_mode(x) for x in psa_theme.MODES] == ['dark', 'light', 'auto'],
              u'chip cycle')
        check(sorted(psa_theme.DARK) == sorted(psa_theme.LIGHT), u'palettes differ in keys')


@test
def parameters_are_kept():
    with stub_revit() as mods:
        import psa_revit
        _parameters_check(psa_revit, mods)


def _parameters_check(rv, mods):
    if True:
        st = mods['Autodesk.Revit.DB'].StorageType
        mark = FakeParam(1, u'Mark', st.String, u'P-01')
        comment = FakeParam(2, u'Comments', st.String, u'keep me')
        sys_id = FakeParam(3, u'BGL_System Code', st.Integer, 7)
        offset = FakeParam(4, u'Middle Elevation', st.Double, 10.0)
        slope = FakeParam(-1001, u'Slope', st.Double, 0.0)
        ro = FakeParam(6, u'Size', st.String, u'100', readonly=True)
        el = FakeEl(55, [mark, comment, sys_id, offset, slope, ro])
        snap = rv.snapshot_params([el])
        held = snap[55][1]
        check(set(held) == {1, 2, 3}, u'held the wrong parameters: {0}'.format(sorted(held)))
        check(not rv.changed_params(snap), u'nothing changed but changes reported')
        comment.value = u''
        sys_id.value = 0
        offset.value = 9.0            # geometry: allowed to change
        changes = rv.changed_params(snap)
        check(sorted(c[2] for c in changes) == [u'BGL_System Code', u'Comments'],
              u'changes: {0}'.format([c[2] for c in changes]))
        log = core.Log()
        restored, failed = rv.restore_params(changes, log)
        check(restored == 2 and not failed, u'restore: {0} {1}'.format(restored, failed))
        check(comment.value == u'keep me' and sys_id.value == 7, u'values not put back')
        check(not rv.changed_params(snap), u'still different after restore')


@test
def eid_value_on_every_release():
    with stub_revit():
        import psa_revit as rv
        check(rv.eid_value(FakeId(12)) == 12, u'.Value not read')

        class Old(object):
            IntegerValue = 34
        check(rv.eid_value(Old()) == 34, u'2024 fallback not read')
        check(rv.eid_value(None) == 0, u'None not 0')
        check(rv.eid_value(object()) == 0, u'junk not 0')


# ====================== runner ======================

def run_all(quiet=False):
    failures = []
    for fn in TESTS:
        try:
            fn()
        except Fail as ex:
            failures.append((fn.__name__, u'{0}'.format(ex)))
        except Exception:
            failures.append((fn.__name__, traceback.format_exc().strip().splitlines()[-1]))
    if not quiet:
        for fn in TESTS:
            bad = [f for f in failures if f[0] == fn.__name__]
            print(u'  {0}  {1}{2}'.format(u'FAIL' if bad else u'ok  ', fn.__name__,
                                          u'  - ' + bad[0][1] if bad else u''))
    return failures


@contextlib.contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _silent_run(work, done, on_error=None):
    try:
        done(work(), None)
    except Exception:
        pass


_real_walk = core.walk


def _walk_ignoring_selection(adapter, start, scope, allowed=None):
    return _real_walk(adapter, start, 'network' if scope == 'selection' else scope, None)


_real_picked = core.choose_outlet_picked


def _picked_backwards(g, src_from, src_to):
    return _real_picked(g, src_to, src_from)


def _no_opposites(conns, arrived_id, tol=0.9):
    return set()


def _swap_min(g):
    terms = core.terminals(g)
    return (max(terms, key=lambda t: g.pos[t][2]) if terms else None), u'broken'


BREAKAGES = [
    (u'tees never go straight through', lambda: patched(core, 'opposite_ids', _no_opposites),
     'walk_tee_run_goes_straight_through'),
    (u'fittings are never turned', lambda: patched(core, 'best_fit_rotation',
                                                     lambda pairs: core.Q_IDENTITY),
     'l_run_both_legs_exact'),
    (u'uprights never counted as steep', lambda: patched(core, 'STEEP_DEG', 91.0),
     'walk_upright_stretches'),
    (u'outlet picked as the highest end', lambda: patched(core, 'choose_outlet_auto', _swap_min),
     'outlet_follows_existing_fall'),
    (u'a stack no longer says "outlet"', lambda: patched(core, 'PRIORITY',
                                                         dict(core.PRIORITY, stack_down=0)),
     'outlet_level_run_to_stack'),
    (u'settings values not validated', lambda: patched(core, 'CHOICES', {}),
     'settings_bad_values_fall_back'),
    (u'fixed joints never go loose', lambda: patched(core, 'LOOSE_MM', 1e9),
     'fixed_fixture_goes_loose_when_moved'),
    (u'the element cap is gone', lambda: patched(core, 'MAX_ELEMENTS', 10 ** 9),
     'walk_refuses_huge_runs'),
    (u'the level threshold swallows real falls', lambda: patched(core, 'FLAT_MM', 1e9),
     'outlet_follows_existing_fall'),
    (u'a failing job never reports back', lambda: patched(
        core, 'run_safely', _silent_run), 'job_always_reports_back'),
    (u'the live preview walks everything', lambda: patched(core, 'PREVIEW_RUNS', 10 ** 6),
     'preview_is_capped'),
    (u'fittings measured from their insertion point again', lambda: patched(
        core, 'fitting_hub', lambda conns, fallback=None: fallback),
     'concourse_network_to_1_in_60'),
    (u'45 degree set downs counted as horizontal', lambda: patched(core, 'STEEP_DEG', 46.0),
     'concourse_network_to_1_in_60'),
    (u'the selection is ignored', lambda: patched(core, 'walk', _walk_ignoring_selection),
     'selection_system_takes_only_the_selection'),
    (u'short pipes judged as ratios only', lambda: patched(core, 'FALL_ABS_MM', 0.0),
     'short_pipes_judged_in_millimetres'),
    (u'the two clicks read the wrong way round', lambda: patched(
        core, 'choose_outlet_picked', _picked_backwards), 'outlet_from_clicks'),
    (u'plan distance measured in 3D', lambda: patched(
        core, 'plan_dist', lambda a, b: core.v_len(core.v_sub(a, b)) * 1.3),
     'straight_run_exact_fall_all_slopes'),
]


def selftest():
    ok = True
    for text, make, expect in BREAKAGES:
        with make():
            failures = run_all(quiet=True)
        names = [f[0] for f in failures]
        caught = expect in names
        ok = ok and caught
        print(u'  {0}  {1} -> {2}'.format(u'caught' if caught else u'MISSED', text,
                                           u', '.join(names) or u'nothing failed'))
    # parameter retention: geometry words no longer skipped -> Middle Elevation held
    with stub_revit() as mods:
        import psa_revit
        psa_revit.GEOMETRY_WORDS = ()
        try:
            _parameters_check(psa_revit, mods)
            caught = False
        except Fail:
            caught = True
    ok = ok and caught
    print(u'  {0}  geometry parameters held as data -> parameters_are_kept'.format(
        u'caught' if caught else u'MISSED'))
    return ok


def main(argv):
    if '--selftest' in argv:
        print(u'Deliberate breakages:')
        good = selftest()
        print(u'Every breakage caught.' if good else u'SOME BREAKAGES WERE MISSED.')
        return 0 if good else 1
    print(u'Pipe Slope Assigner v{0} - bench logic'.format(core.__version__))
    failures = run_all()
    print(u'{0} of {1} checks pass.'.format(len(TESTS) - len(failures), len(TESTS)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
