# -*- coding: utf-8 -*-
"""Logic bench for Click to RVT Element (CPython 3).

    python bench_logic.py             run every check
    python bench_logic.py --selftest  patch the thing each check tests and
                                      prove the check fails

Synthetic scans (bench_scene) go through the real recognition and type
choice; the drawer is driven through a fake window and a fake timer that
never runs ticks inside Start() and records whatever escapes a tick the way
WPF's dispatcher would.
"""
from __future__ import division
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402
bench_stubs.install()

import c2r_core as core  # noqa: E402
import c2r_drawer  # noqa: E402
import bench_scene as bs  # noqa: E402

ST = core.load_settings(u'')

CAT = {
    u'pipe': [
        {u'name': u'Copper', u'id': u'P1', u'sizes': [(15, 15.0), (22, 22.0), (28, 28.0), (35, 35.0), (42, 42.0), (54, 54.0)]},
        {u'name': u'Steel', u'id': u'P2', u'sizes': [(15, 21.3), (20, 26.9), (25, 33.7), (32, 42.4), (40, 48.3), (50, 60.3),
                                                     (65, 76.1), (80, 88.9), (100, 114.3), (125, 139.7), (150, 168.3),
                                                     (200, 219.1)]},
    ],
    u'conduit': [{u'name': u'Conduit', u'id': u'C1', u'sizes': [(20, 20.0), (25, 25.0), (32, 32.0)]}],
    u'duct': [{u'name': u'Rect duct', u'id': u'D1', u'shape': u'rect'},
              {u'name': u'Round duct', u'id': u'D2', u'shape': u'round'}],
    u'duct_round_sizes': [100, 125, 160, 200, 250, 315, 400, 500],
    u'duct_rect_sizes': list(range(100, 2001, 50)),
    u'tray': [{u'name': u'Ladder', u'id': u'T1'}],
    u'tray_widths': [100, 150, 225, 300, 450, 600],
    u'wall': [{u'name': u'Block 100', u'id': u'W1', u'width': 100.0},
              {u'name': u'Block 140', u'id': u'W2', u'width': 140.0},
              {u'name': u'Stud 215', u'id': u'W3', u'width': 215.0}],
    u'floor': [{u'name': u'Slab 200', u'id': u'F1'}],
    u'ceiling': [{u'name': u'Tile', u'id': u'CL1'}],
    u'column': [{u'name': u'UC 400x400', u'id': u'K1', u'w': 400.0, u'd': 400.0},
                {u'name': u'RC 300x600', u'id': u'K2', u'w': 300.0, u'd': 600.0}],
    u'beam': [{u'name': u'RC 300x500', u'id': u'B1', u'w': 300.0, u'd': 500.0},
              {u'name': u'UB 200x400', u'id': u'B2', u'w': 200.0, u'd': 400.0}],
}
OPTS = {u'enabled': core.KIND_KEYS, u'types': {}, u'insulation_mm': 0}
WIDTHS = [t[u'width'] for t in CAT[u'wall']]

FAILS = []


def check(name, cond, detail=u''):
    if not cond:
        FAILS.append(u'{0}: {1}'.format(name, detail))
    return cond


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


# =====================================================================
# maths
# =====================================================================

def t_eigen():
    rnd = random.Random(1)
    for _k in range(30):
        a = [[rnd.uniform(-5, 5) for _c in range(3)] for _r in range(3)]
        m = [[a[r][c] + a[c][r] for c in range(3)] for r in range(3)]
        vals, vecs = core.eig_sym3(m)
        for lam, v in zip(vals, vecs):
            mv = [sum(m[r][c] * v[c] for c in range(3)) for r in range(3)]
            err = max(abs(mv[r] - lam * v[r]) for r in range(3))
            if not check(u'eigen', err < 1e-6, u'|Av - lv| = {0}'.format(err)):
                return
        check(u'eigen order', vals[0] >= vals[1] >= vals[2], u'{0}'.format(vals))


def t_circle():
    rnd = random.Random(2)
    for od in (60.3, 114.3, 219.1):
        r = od / 2
        pts = []
        for k in range(300):
            a = math.radians(-120 + 240 * k / 299.0)
            rr = r + rnd.gauss(0, 2.0)
            pts.append((40 + rr * math.cos(a), -25 + rr * math.sin(a)))
        fit = core.circle_fit(pts)
        check(u'circle {0}'.format(od), fit and near(2 * fit[u'r'], od, 2.0),
              u'got {0}'.format(2 * fit[u'r'] if fit else None))
        check(u'circle coverage {0}'.format(od), fit and fit[u'cov'] > 200, u'{0}'.format(fit and fit[u'cov']))


def t_outline():
    cells = set((i, j) for i in range(10) for j in range(8) if not (i >= 6 and j >= 5))
    poly = core.grid_outline(cells)
    check(u'outline L corners', len(poly) == 6, u'{0}'.format(poly))
    check(u'outline L area', near(core.polygon_area(poly), len(cells), 1e-9), u'{0}'.format(core.polygon_area(poly)))
    pinch = set([(0, 0), (1, 1)])
    fixed = core.remove_pinches(pinch)
    poly = core.grid_outline(fixed)
    check(u'outline pinch removed', len(fixed) == 3 and len(poly) == 6, u'{0} {1}'.format(sorted(fixed), poly))
    ring = set((i, j) for i in range(5) for j in range(5)) - set([(2, 2)])
    check(u'holes filled', len(core.fill_holes(ring)) == 25)
    ins = core.inset_orthogonal([(0, 0), (4, 0), (4, 3), (0, 3)], 0.5)
    check(u'inset', ins == [(0.5, 0.5), (3.5, 0.5), (3.5, 2.5), (0.5, 2.5)], u'{0}'.format(ins))


def t_rect():
    rnd = random.Random(4)
    ang = math.radians(20)
    pts = []
    for k in range(400):
        u = rnd.uniform(-300, 300)
        v = rnd.choice((-100, 100)) + rnd.gauss(0, 1)
        if k % 2:
            u, v = rnd.choice((-300, 300)) + rnd.gauss(0, 1), rnd.uniform(-100, 100)
        pts.append((u * math.cos(ang) - v * math.sin(ang), u * math.sin(ang) + v * math.cos(ang)))
    r = core.min_area_rect(pts)
    check(u'min rect size', near(r[u'w'], 600, 15) and near(r[u'h'], 200, 15), u'{0}'.format(r))
    check(u'min rect angle', near(math.degrees(r[u'angle']), 20, 2), u'{0}'.format(math.degrees(r[u'angle'])))


# =====================================================================
# recognition on synthetic scans
# =====================================================================

def recog(scene, click, trace=True):
    logs = []
    try:
        rec = core.recognise(click, scene.harvest, bs.LEVELS, ST, widths=WIDTHS, trace=trace, log=logs.append)
    except core.RecogniseError as ex:
        return None, None, u'{0} | {1}'.format(ex, u' / '.join(logs))
    cands = core.candidates(rec, CAT, OPTS, ST)
    return rec, cands, u' / '.join(logs)


def run_len(rec):
    return core.v_dist(rec[u'p0'], rec[u'p1'])


def t_pipes():
    for od, noise, kind, type_name, nom in ((60.3, 2, u'pipe', u'Steel', 50), (114.3, 2, u'pipe', u'Steel', 100),
                                            (219.1, 3, u'pipe', u'Steel', 200), (54.0, 2, u'pipe', u'Copper', 54),
                                            (22.0, 1.5, u'pipe', u'Copper', 22)):
        s = bs.Scene(noise=noise)
        bs.room(s, spacing=30)
        s.cylinder((1000, 2500, 2400), (1, 0, 0), 3000, od / 2, 4 if od < 40 else 5)
        rec, cands, log = recog(s, (2500, 2500, 2400 - od / 2))
        name = u'pipe {0}'.format(od)
        if not check(name, rec is not None and rec[u'shape'] == u'round', log):
            continue
        check(name + u' diameter', near(rec[u'D'], od, 2.0), u'{0:.1f}'.format(rec[u'D']))
        check(name + u' run length', near(run_len(rec), 3000, 40), u'{0:.0f}'.format(run_len(rec)))
        check(name + u' level axis', abs(rec[u'axis'][2]) < 1e-9, u'{0}'.format(rec[u'axis']))
        c = cands[0]
        check(name + u' chosen', c[u'kind'] == kind and c[u'type'][u'name'] == type_name and
              c[u'size'][u'diameter'] == nom, u'{0} {1} {2}'.format(c[u'kind'], c[u'type'][u'name'], c[u'size']))


def t_vertical_pipe():
    s = bs.Scene(noise=2)
    bs.room(s, spacing=30)
    s.cylinder((3000, 2500, 0), (0, 0, 1), 2700, 44.45, 5, view=(-1, 0, 0))
    rec, cands, log = recog(s, (2955.5, 2500, 1200))
    if check(u'vertical pipe', rec is not None and rec[u'shape'] == u'round' and rec[u'vertical'], log):
        check(u'vertical pipe height', near(run_len(rec), 2700, 40), u'{0:.0f}'.format(run_len(rec)))
        check(u'vertical pipe size', cands[0][u'size'][u'diameter'] == 80, u'{0}'.format(cands[0][u'text']))


def t_pipe_near_wall():
    s = bs.Scene(noise=2)
    bs.room(s, spacing=25)
    s.cylinder((1000, 70, 1800), (1, 0, 0), 3000, 27, 4, view=(0, 1, 0))
    rec, cands, log = recog(s, (2500, 97, 1800))
    check(u'pipe beside a wall', rec is not None and rec[u'shape'] == u'round' and near(rec[u'D'], 54, 2.0),
          log if rec is None else u'{0}'.format(core.describe(rec)))


def t_click_end():
    s = bs.Scene(noise=2)
    bs.room(s, spacing=30)
    s.cylinder((1000, 2500, 2400), (1, 0, 0), 3000, 57.15, 5)
    rec, _c, log = recog(s, (1500, 2500, 2342.85), trace=False)
    if check(u'click-end recognise', rec is not None, log):
        core.end_from_click(rec, (3700, 2510, 2350))
        check(u'click-end length', near(run_len(rec), 2200, 5), u'{0:.0f}'.format(run_len(rec)))


def t_wall():
    s = bs.Scene(noise=3)
    bs.room(s, spacing=25)
    rec, cands, log = recog(s, (3000, 0, 1400))
    if check(u'wall', rec is not None and rec[u'shape'] == u'wall', log):
        check(u'wall length', near(rec[u'length'], 6000, 60), u'{0:.0f}'.format(rec[u'length']))
        check(u'wall height', near(rec[u'top_z'] - rec[u'base_z'], 2700, 40),
              u'{0:.0f}'.format(rec[u'top_z'] - rec[u'base_z']))
        check(u'wall body behind the face', rec[u'body'][1] < -0.99, u'{0}'.format(rec[u'body']))
        check(u'wall unscanned -> fallback type', cands[0][u'type'][u'name'] == u'Block 100',
              u'{0}'.format(cands[0][u'text']))
    s2 = bs.Scene(noise=3)
    bs.room(s2, spacing=25)
    bs.room(s2, y0=-140 - 4000, ly=4000, spacing=25)
    rec, cands, log = recog(s2, (3000, 0, 1400))
    if check(u'wall both faces', rec is not None and rec[u'shape'] == u'wall', log):
        check(u'wall thickness', near(rec[u'thickness'], 140, 8), u'{0}'.format(rec[u'thickness']))
        check(u'wall type by thickness', cands[0][u'type'][u'name'] == u'Block 140', u'{0}'.format(cands[0][u'text']))


def t_slabs():
    s = bs.Scene(noise=3)
    s.plane((0, 0, 0), (1, 0, 0), (0, 1, 0), 6000, 5000, 30, skip=lambda a, b: a > 4000 and b > 3000)
    s.plane((0, 0, 2700), (1, 0, 0), (0, 1, 0), 6000, 5000, 30)
    rec, cands, log = recog(s, (2000, 2000, 0))
    if check(u'floor', rec is not None and rec[u'shape'] == u'slab' and rec[u'which'] == u'floor', log):
        check(u'floor L outline', len(rec[u'loop']) == 6, u'{0}'.format(rec[u'loop']))
        check(u'floor area', near(rec[u'area_m2'], 26.0, 1.0), u'{0:.2f}'.format(rec[u'area_m2']))
        check(u'floor candidate first', cands[0][u'kind'] == u'floor', u'{0}'.format(cands[0][u'kind']))
    rec, cands, log = recog(s, (2000, 2000, 2700))
    if check(u'ceiling', rec is not None and rec[u'shape'] == u'slab' and rec[u'which'] == u'ceiling', log):
        check(u'ceiling area', near(rec[u'area_m2'], 30.0, 1.2), u'{0:.2f}'.format(rec[u'area_m2']))


def t_rect_runs():
    s = bs.Scene(noise=3)
    bs.room(s, spacing=30)
    s.box_run((500, 2500, 2400), (1, 0, 0), 4000, 600, 400, 6)
    for label, click in ((u'duct underside', (2000, 2500, 2200)), (u'duct side', (2000, 2200, 2400))):
        rec, cands, log = recog(s, click)
        if check(label, rec is not None and rec[u'shape'] == u'rect', log):
            check(label + u' size', near(rec[u'W'], 600, 20) and near(rec[u'H'], 400, 20),
                  u'{0:.0f} x {1:.0f}'.format(rec[u'W'], rec[u'H']))
            check(label + u' length', near(run_len(rec), 4000, 50), u'{0:.0f}'.format(run_len(rec)))
            c = cands[0]
            check(label + u' chosen', c[u'kind'] == u'duct' and c[u'size'][u'width'] == 600 and c[u'size'][u'height'] == 400,
                  u'{0}'.format(c[u'text']))
    s = bs.Scene(noise=3)
    bs.room(s, spacing=30)
    s.box_run((500, 2500, 2300), (1, 0, 0), 4000, 300, 100, 6)
    rec, cands, log = recog(s, (2000, 2500, 2250))
    if check(u'tray', rec is not None and rec[u'shape'] == u'rect', log):
        c = cands[0]
        check(u'tray chosen', c[u'kind'] == u'tray' and c[u'size'][u'width'] == 300 and c[u'size'][u'height'] == 100,
              u'{0}'.format(c[u'text']))


def t_structure():
    s = bs.Scene(noise=3)
    bs.room(s, spacing=30, ceiling=False)
    s.plane((0, 0, 2700), (1, 0, 0), (0, 1, 0), 6000, 5000, 25, skip=lambda a, b: 2350 < b < 2650)
    s.box_run((0, 2500, 2450), (1, 0, 0), 6000, 300, 500, 8)
    rec, cands, log = recog(s, (2000, 2500, 2200))
    if check(u'beam', rec is not None and rec[u'shape'] == u'rect' and rec[u'slab_above'], log):
        check(u'beam chosen', cands[0][u'kind'] == u'beam' and cands[0][u'type'][u'name'] == u'RC 300x500',
              u'{0}'.format(cands[0][u'text']))
    s = bs.Scene(noise=3)
    bs.room(s, spacing=30)
    s.column((3000, 2500), 400, 400, 0, 2700, 10)
    rec, cands, log = recog(s, (3000, 2300, 1400))
    if check(u'column', rec is not None and rec[u'shape'] == u'rect' and rec[u'vertical'], log):
        check(u'column chosen', cands[0][u'kind'] == u'column' and cands[0][u'type'][u'name'] == u'UC 400x400',
              u'{0}'.format(cands[0][u'text']))


def t_disabled_kind():
    s = bs.Scene(noise=2)
    bs.room(s, spacing=30)
    s.cylinder((1000, 2500, 2400), (1, 0, 0), 3000, 57.15, 5)
    rec, _c, log = recog(s, (2500, 2500, 2342.85))
    if check(u'disabled kind recognise', rec is not None, log):
        cands = core.candidates(rec, CAT, {u'enabled': [u'duct', u'conduit'], u'types': {}}, ST)
        check(u'unticked pipe not offered', all(c[u'kind'] != u'pipe' for c in cands), u'{0}'.format(
            [c[u'kind'] for c in cands]))
        cands = core.candidates(rec, CAT, {u'enabled': core.KIND_KEYS, u'types': {u'pipe': u'Copper'}}, ST)
        check(u'chosen type honoured', cands[0][u'type'][u'name'] == u'Copper' or cands[0][u'kind'] != u'pipe',
              u'{0}'.format(cands[0][u'text']))


def t_insulation():
    rec = {u'shape': u'round', u'D': 114.3 + 2 * 25, u'rms': 1.0, u'p0': (0, 0, 0), u'p1': (1000, 0, 0)}
    c = core.candidates(rec, CAT, {u'enabled': [u'pipe'], u'types': {}, u'insulation_mm': 25}, ST)
    check(u'insulation deducted', c and c[0][u'size'][u'diameter'] == 100, u'{0}'.format(c and c[0][u'text']))


def t_axis_snap():
    a = core._snap_axis((1.0, 0.0, 0.03), 3)
    check(u'near-level run squared', a[2] == 0.0, u'{0}'.format(a))
    a = core._snap_axis((0.02, 0.0, -1.0), 3)
    check(u'near-plumb run squared', a == (0.0, 0.0, 1.0), u'{0}'.format(a))
    a = core._snap_axis((1.0, 0.0, 0.2), 3)
    check(u'a real fall is kept', a[2] > 0.1, u'{0}'.format(a))


# =====================================================================
# settings, theme
# =====================================================================

def t_settings():
    d = core.load_settings(u'')
    text = core.dump_settings(d)
    check(u'settings round trip', core.load_settings(text) == d)
    d2 = core.load_settings(u'noise_mm=banana\ntrace_max_m=9999\nspacing_mm=8\nnot_a_key=1\nfloor_outline=oval\n'
                            u'kinds=pipe,wall\nsettings_version=0\n')
    check(u'bad number falls back', d2[u'noise_mm'] == core.DEFAULTS[u'noise_mm'])
    check(u'out of range falls back', d2[u'trace_max_m'] == core.DEFAULTS[u'trace_max_m'])
    check(u'good value kept', d2[u'spacing_mm'] == u'8')
    check(u'unknown key ignored', u'not_a_key' not in d2)
    check(u'bad choice falls back', d2[u'floor_outline'] == u'traced')
    check(u'free text kept', d2[u'kinds'] == u'pipe,wall')
    check(u'version stamped', d2[u'settings_version'] == u'{0}'.format(core.SETTINGS_VERSION))
    check(u'split on first =', core.load_settings(u'column_w_params=a=b,c')[u'column_w_params'] == u'a=b,c')


def t_theme():
    seq = [u'follow']
    for _k in range(3):
        seq.append(core.next_theme(seq[-1]))
    check(u'theme cycle', seq == [u'follow', u'dark', u'light', u'follow'], u'{0}'.format(seq))
    check(u'auto follows canvas', core.resolve_theme(u'follow', True) == u'dark' and
          core.resolve_theme(u'follow', False) == u'light')
    for name, pal in core.PALETTES.items():
        for fg, bg in core.TEXT_PAIRS:
            r = core.contrast(pal[fg], pal[bg])
            check(u'contrast {0} {1} on {2}'.format(name, fg, bg), r >= 4.5, u'{0:.2f}'.format(r))


# =====================================================================
# drawer
# =====================================================================

class FakeTimer(object):
    live = []
    escaped = []

    def __init__(self, ms, tick):
        self.tick = tick
        self.on = False

    def Start(self):
        self.on = True           # a real DispatcherTimer never ticks inside Start()
        FakeTimer.live.append(self)

    def Stop(self):
        self.on = False


def pump(limit=500):
    for _k in range(limit):
        running = [t for t in FakeTimer.live if t.on]
        if not running:
            FakeTimer.live = []
            return
        for t in running:
            try:
                t.tick(None, None)
            except Exception as ex:          # what the dispatcher would see
                FakeTimer.escaped.append(ex)
                t.on = False


class El(object):
    def __init__(self, h=0.0):
        self.Visibility = u'Visible'
        self.ActualHeight = h
        self.Height = float('nan')
        self.VerticalAlignment = u'Stretch'
        self.Tag = u''


class Root(El):
    def __init__(self, header, others, h):
        El.__init__(self, h)
        self.Children = [header] + others


class FakeWin(object):
    def __init__(self, top=200.0, height=600.0, fail_after=None):
        self._top = top
        self.Height = height
        self.Left = 100.0
        self.Width = 800.0
        self.MinHeight = 560.0
        self.SizeToContent = u'WidthAndHeight'
        self.released = []
        self.sets = 0
        self.fail_after = fail_after

    @property
    def Top(self):
        return self._top

    @Top.setter
    def Top(self, v):
        self.sets += 1
        if self.fail_after is not None and self.sets > self.fail_after:
            raise RuntimeError(u'frame failed')
        self._top = v

    @property
    def ActualHeight(self):
        return self.Height

    def BeginAnimation(self, prop, clock):
        self.released.append(prop)


AREA = (0.0, 0.0, 1920.0, 1040.0)


def make_drawer(win=None, area=AREA):
    win = win or FakeWin()
    header = El(44.0)
    body = El(500.0)
    foot = El(40.0)
    grips = El()
    root = Root(header, [body, foot, grips], 598.0)
    btn = El()
    errs = []
    dr = c2r_drawer.WindowDrawer(win, header, root, btn, grips, area_fn=lambda w: area,
                                 timer_factory=FakeTimer, on_error=errs.append)
    return dr, win, root, btn, body, grips, errs


def collapsed(v):
    return getattr(v, u'__name__', u'{0}'.format(v)) == u'Collapsed'


def t_drawer_maths():
    bar = core.bar_height(44.0)
    check(u'bar height', bar == 46.0)
    check(u'parked top', core.parked_top(1040.0, bar) == 1040.0 - core.DRAWER_GAP - bar)
    check(u'slot above', core.parked_top(1040.0, bar, 1) < core.parked_top(1040.0, bar, 0) - bar)
    p = core.parked_top(1040.0, bar)
    check(u'expand where it was', core.expand_top(200.0, p, p, 600.0, 0.0, 1040.0) == 200.0)
    check(u'expand upward from a moved bar', core.expand_top(200.0, p, 300.0, 600.0, 0.0, 1040.0) == 300.0)
    check(u'expand kept on screen', core.expand_top(200.0, p, 900.0, 600.0, 0.0, 1040.0) == 440.0)
    screens = [(0.0, 0.0, 1920.0, 1040.0), (0.0, -1080.0, 1920.0, -40.0)]
    sc = core.screen_for(100.0, -900.0, 800.0, 600.0, screens)
    check(u'monitor above primary', sc == screens[1], u'{0}'.format(sc))
    check(u'parked on the upper monitor', core.parked_top(sc[3], bar) < -40.0)
    check(u'ease ends', core.ease(0) == 0.0 and core.ease(1) == 1.0 and core.ease(0.5) > 0.5)


def t_drawer_run():
    FakeTimer.escaped = []
    dr, win, root, btn, body, grips, errs = make_drawer()
    dr.shrink()
    check(u'drawer slides, not jumps', dr.sliding and win.Top == 200.0)
    pump()
    bar = core.bar_height(44.0)
    check(u'drawer parked', dr.parked and not dr.sliding, u'parked {0} sliding {1}'.format(dr.parked, dr.sliding))
    check(u'drawer parked top', near(win.Top, core.parked_top(AREA[3], bar), 1e-6), u'{0}'.format(win.Top))
    check(u'drawer bar height', near(win.Height, bar, 1e-6), u'{0}'.format(win.Height))
    check(u'drawer button tagged', btn.Tag == u'shrunk')
    check(u'drawer body collapsed', collapsed(body.Visibility), u'{0}'.format(body.Visibility))
    check(u'drawer header kept', root.Children[0].Visibility == u'Visible')
    check(u'drawer grips parked', collapsed(grips.Visibility))
    check(u'drawer MinHeight relaxed', win.MinHeight == 0)
    check(u'drawer releases animations', len(win.released) >= 4, u'{0}'.format(len(win.released)))
    dr.expand()
    pump()
    check(u'drawer reopened', not dr.parked and win.Top == 200.0 and near(win.Height, 600.0, 1e-6),
          u'{0} {1}'.format(win.Top, win.Height))
    check(u'drawer MinHeight back', win.MinHeight == 560.0)
    check(u'drawer body restored', body.Visibility == u'Visible')
    check(u'drawer button untagged', btn.Tag == u'')
    check(u'drawer nothing escaped', not FakeTimer.escaped and not errs, u'{0} {1}'.format(FakeTimer.escaped, errs))
    dr.shrink()
    pump()
    win.Top = 300.0
    dr.expand()
    pump()
    check(u'drawer opens from a moved bar', win.Top == 300.0, u'{0}'.format(win.Top))


def t_drawer_linked():
    FakeTimer.escaped = []
    main, mwin, _r, _b, _body, _g, _e = make_drawer(FakeWin(200.0, 600.0))
    dlg, dwin, _r2, _b2, _body2, _g2, _e2 = make_drawer(FakeWin(250.0, 400.0))
    dlg.linked = main
    dlg.shrink()
    pump()
    check(u'dialog shrink parks the owner', main.parked and dlg.parked)
    check(u'dialog bar above the owner bar', dwin.Top < mwin.Top, u'{0} {1}'.format(dwin.Top, mwin.Top))
    dlg.expand()
    pump()
    check(u'dialog reopen brings the owner back', not main.parked and not dlg.parked)


def t_drawer_tick_failure():
    FakeTimer.escaped = []
    dr, win, _r, _b, _body, _g, errs = make_drawer(FakeWin(fail_after=5))
    dr.shrink()
    pump()
    check(u'a failing frame still lands', not dr.sliding, u'sliding {0}'.format(dr.sliding))
    check(u'nothing escapes a tick', not FakeTimer.escaped, u'{0}'.format(FakeTimer.escaped))
    check(u'the failure is reported', bool(errs))


# =====================================================================
# runner
# =====================================================================

CHECKS = [t_eigen, t_circle, t_outline, t_rect, t_pipes, t_vertical_pipe, t_pipe_near_wall, t_click_end, t_wall,
          t_slabs, t_rect_runs, t_structure, t_disabled_kind, t_insulation, t_axis_snap, t_settings, t_theme,
          t_drawer_maths, t_drawer_run, t_drawer_linked, t_drawer_tick_failure]


def run(checks):
    del FAILS[:]
    for c in checks:
        try:
            c()
        except Exception as ex:
            FAILS.append(u'{0} raised {1!r}'.format(c.__name__, ex))
    return list(FAILS)


def _patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    return lambda: setattr(obj, name, old)


def _drawer_variant(old, new):
    """c2r_drawer with one line of its source changed."""
    import types
    src = open(os.path.join(HERE, u'c2r_drawer.py')).read()
    assert old in src, old
    mod = types.ModuleType(u'c2r_drawer_variant')
    exec(compile(src.replace(old, new, 1), u'c2r_drawer_variant', u'exec'), mod.__dict__)
    return _patch(c2r_drawer, u'WindowDrawer', mod.WindowDrawer)


BREAKAGES = [
    (u'Jacobi rotation sign', [t_eigen],
     lambda: _patch(core, u'eig_sym3', lambda m: ([m[0][0], m[1][1], m[2][2]], [(1, 0, 0), (0, 1, 0), (0, 0, 1)]))),
    (u'circle fit off by 3 mm', [t_circle, t_pipes],
     lambda: _patch(core, u'circle_geometric', (lambda f: lambda p, i, iters=10: (lambda c: (c[0], c[1], c[2] + 3.0))(f(p, i, iters)))(core.circle_geometric))),
    (u'outline skips collinear test', [t_outline],
     lambda: _patch(core, u'grid_outline', (lambda f: lambda c: f(c) + [(0, 0)])(core.grid_outline))),
    (u'no pinch removal', [t_outline], lambda: _patch(core, u'remove_pinches', lambda c: set(c))),
    (u'min rect without hull angle', [t_rect], lambda: _patch(core, u'hull2', lambda p: [])),
    (u'no trace', [t_pipes, t_rect_runs], lambda: _patch(core, u'trace_run',
                                                         lambda h, C, fr, a, b, prof, s0, s1, st, log: (s0, s1))),
    (u'axis not squared', [t_axis_snap, t_pipes], lambda: _patch(core, u'_snap_axis', lambda a, deg: core.v_unit(a))),
    (u'walls and slabs not set aside', [t_structure, t_rect_runs],
     lambda: _patch(core, u'section_pass', (lambda f: lambda *a, **k: dict(f(*a, **k), slab_above=False))(core.section_pass))),
    (u'wall thickness ignored', [t_wall], lambda: _patch(core, u'_plane_peak', lambda *a: None)),
    (u'slab wall-crossings kept', [t_rect_runs], lambda: _patch(core, u'flat_points', lambda pts, cell, band: pts)),
    (u'strip read as a slab', [t_rect_runs], lambda: _patch(core, u'min_area_rect',
                                                            (lambda f: lambda p, trim=0.01: dict(f(p, trim), w=5000.0, h=5000.0))(core.min_area_rect))),
    (u'floor/ceiling flipped', [t_slabs], lambda: _patch(core, u'level_below', lambda levels, z, tol=1.0: None)),
    (u'insulation not deducted', [t_insulation],
     lambda: _patch(core, u'candidates', (lambda f: lambda rec, cat, opts, st: f(rec, cat, dict(opts, insulation_mm=0), st))(core.candidates))),
    (u'disabled kinds offered', [t_disabled_kind],
     lambda: _patch(core, u'candidates', (lambda f: lambda rec, cat, opts, st: f(rec, cat, dict(opts, enabled=core.KIND_KEYS), st))(core.candidates))),
    (u'settings keep bad numbers', [t_settings], lambda: _patch(core, u'NUMERIC', {})),
    (u'theme cycle stuck', [t_theme], lambda: _patch(core, u'next_theme', lambda c: u'dark')),
    (u'weak muted text', [t_theme], lambda: _patch(core, u'PALETTES', dict(core.PALETTES, dark=dict(core.PALETTES[u'dark'], Muted=u'#7A808A')))),
    (u'bar lands on the wrong monitor', [t_drawer_maths], lambda: _patch(core, u'screen_for', lambda *a: a[-1][0])),
    (u'expand ignores a moved bar', [t_drawer_maths, t_drawer_run],
     lambda: _patch(core, u'expand_top', lambda s, p, c, f, t, b: s)),
    (u'drawer keeps the animation', [t_drawer_run], lambda: _drawer_variant(
        u'            self.w.BeginAnimation(Window.TopProperty, None)\n', u'            pass\n')),
    (u'drawer never restores MinHeight', [t_drawer_run], lambda: _drawer_variant(
        u"                w.MinHeight = self.saved[u'minh']\n", u'                pass\n')),
    (u'tick without its fallback', [t_drawer_tick_failure], lambda: _drawer_variant(
        u'            except Exception as ex:\n                self._err(ex)\n                land()\n',
        u'            except Exception as ex:\n                self._err(ex)\n                raise\n')),
    (u'dialog not linked to its owner', [t_drawer_linked], lambda: _drawer_variant(
        u'        if self.linked is not None:\n            self.linked.slot = 0\n', u'        if False:\n            pass\n')),
]


def selftest():
    failed = 0
    for name, checks, apply in BREAKAGES:
        clean = run(checks)
        if clean:
            print(u'  ?  {0}: checks fail on clean code: {1}'.format(name, clean[0]))
            failed += 1
            continue
        undo = apply()
        try:
            got = run(checks)
        finally:
            undo()
        if got:
            print(u'  ok {0}: caught - {1}'.format(name, got[0][:110]))
        else:
            failed += 1
            print(u'  XX {0}: NOT caught'.format(name))
    print(u'selftest: {0} breakages, {1} failures'.format(len(BREAKAGES), failed))
    return failed


def main():
    if u'--selftest' in sys.argv:
        sys.exit(1 if selftest() else 0)
    t0 = time.time()
    fails = run(CHECKS)
    for f in fails:
        print(u'FAIL ' + f)
    print(u'{0} checks, {1} failures, {2:.0f} s'.format(len(CHECKS), len(fails), time.time() - t0))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
