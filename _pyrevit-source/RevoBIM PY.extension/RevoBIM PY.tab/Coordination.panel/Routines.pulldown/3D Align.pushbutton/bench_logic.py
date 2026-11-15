# -*- coding: utf-8 -*-
"""3D Align - logic bench. Run under plain CPython from this folder:

    python bench_logic.py              every check
    python bench_logic.py --selftest   break the tool on purpose, one thing at
                                       a time, and confirm a check catches it
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FT = 1.0 / 304.8          # one millimetre in feet

RESULTS = []


def check(name, condition, detail=''):
    RESULTS.append((name, bool(condition), detail))


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def run_checks():
    sys.path.insert(0, HERE)
    import bench_stubs as s
    s.install()
    s.purge()
    os.environ['APPDATA'] = tempfile.mkdtemp()
    import a3d_geom as g
    import a3d_settings as cfg
    import a3d_core as core
    import theme

    # ---- classification ---------------------------------------------------
    check('plumb is vertical', g.classify(((0, 0, 0), (0, 0, 10))) == g.VERTICAL)
    check('level is horizontal', g.classify(((0, 0, 0), (10, 0, 0))) == g.HORIZONTAL)
    a45 = ((0, 0, 0), (1, 0, math.tan(math.radians(45))))
    a47 = ((0, 0, 0), (1, 0, math.tan(math.radians(47))))
    check('45 degrees is horizontal', g.classify(a45) == g.HORIZONTAL)
    check('47 degrees is vertical', g.classify(a47) == g.VERTICAL)
    check('zero length has no class', g.classify(((1, 1, 1), (1, 1, 1))) is None)
    check('1 in 40 fall is horizontal', g.classify(((0, 0, 0), (40, 0, -1))) == g.HORIZONTAL)

    # ---- vertical then vertical -------------------------------------------
    riser = ((10, 20, 0), (10, 20, 12))
    other = ((10.3, 19.6, 2), (10.3, 19.6, 8))
    plan = g.plan_alignment(riser, other)
    check('V-V moves the difference in X and Y',
          plan['ok'] and near(plan['move'][0], -0.3) and near(plan['move'][1], 0.4))
    check('V-V never moves in Z', plan['move'][2] == 0.0)
    check('V-V distance', near(plan['distance'], 0.5))
    after = g.translate(other, plan['move'])
    check('V-V reads back aligned', g.is_aligned(g.plan_alignment(riser, after)['distance']))

    # ---- vertical then horizontal -----------------------------------------
    run = ((0, 5.25, 3), (30, 5.25, 3))          # along X, 0.25ft off the riser in Y
    riser = ((12, 5, 0), (12, 5, 10))
    plan = g.plan_alignment(riser, run)
    check('V-H moves square to the run only',
          plan['ok'] and near(plan['move'][0], 0.0) and near(plan['move'][1], -0.25))
    check('V-H never moves in Z', plan['move'][2] == 0.0)
    after = g.translate(run, plan['move'])
    check('V-H reads back aligned', g.is_aligned(g.plan_alignment(riser, after)['distance']))

    diag = ((0, 0, 3), (10, 10, 3))               # a run at 45 degrees in plan
    riser = ((5, 6, 0), (5, 6, 9))
    plan = g.plan_alignment(riser, diag)
    mx, my = plan['move'][0], plan['move'][1]
    check('V-H on a skew run stays square to it', near(mx * 1 + my * 1, 0.0))
    check('V-H on a skew run lands', g.is_aligned(
        g.plan_alignment(riser, g.translate(diag, plan['move']))['distance']))

    lean = ((0, 0, 0), (1, 0, 10))                 # steep but not plumb
    run = ((3, -5, 8), (3, 5, 8))                  # at z = 8 the lean sits at x = 0.8
    plan = g.plan_alignment(lean, run)
    check('V-H on a leaning upright uses the run\'s height', near(plan['move'][0], -2.2))

    falling = ((0, 1, 4), (40, 1, 3))              # 1 in 40
    riser = ((20, 0, 0), (20, 0, 9))
    plan = g.plan_alignment(riser, falling)
    check('V-H on a falling run keeps the fall', plan['move'][2] == 0.0 and near(plan['move'][1], -1.0))

    # ---- horizontal then vertical -----------------------------------------
    run = ((0, 0, 3), (30, 0, 3))
    riser = ((7, 0.4, 0), (7, 0.4, 10))
    plan = g.plan_alignment(run, riser)
    check('H-V moves the upright onto the run, square to it',
          plan['ok'] and near(plan['move'][0], 0.0) and near(plan['move'][1], -0.4))
    after = g.translate(riser, plan['move'])
    check('H-V reads back aligned', g.is_aligned(g.plan_alignment(run, after)['distance']))
    check('H-V describes itself', 'onto the horizontal' in plan['mode'])

    # ---- refusals and thresholds ------------------------------------------
    plan = g.plan_alignment(((0, 0, 0), (10, 0, 0)), ((0, 1, 0), (10, 1, 0)))
    check('H-H refused with a reason', not plan['ok'] and 'both are horizontal' in plan['reason'])
    plan = g.plan_alignment(((0, 0, 0), (0, 0, 0)), ((0, 1, 0), (0, 1, 5)))
    check('zero length refused', not plan['ok'])
    plan = g.plan_alignment(((0, 0, 0), (0, 0, 9)), ((0.05 * FT, 0, 0), (0.05 * FT, 0, 9)))
    check('under 0.1mm is already aligned', plan['already'])
    plan = g.plan_alignment(((0, 0, 0), (0, 0, 9)), ((0.5 * FT, 0, 0), (0.5 * FT, 0, 9)))
    check('0.5mm is not already aligned', not plan['already'])

    # ---- settings ---------------------------------------------------------
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 's.txt')
    check('missing file gives defaults', cfg.load(path) == cfg.DEFAULTS)
    with open(path, 'w') as handle:
        handle.write('# comment\nkeep_running=off\ntheme=purple\nnonsense\nunknown=1\n'
                     'max_move_mm=-4\nshow_results=always\non_refusal=leave=x\n')
    loaded = cfg.load(path)
    check('valid keys load', loaded['keep_running'] == 'off' and loaded['show_results'] == 'always')
    check('bad values fall back key by key',
          loaded['theme'] == 'follow' and loaded['max_move_mm'] == '3000' and loaded['on_refusal'] == 'detach')
    check('unknown keys ignored', 'unknown' not in loaded)
    loaded['max_move_mm'] = '250'
    check('save round trip', cfg.save(loaded, path) and cfg.load(path)['max_move_mm'] == '250')
    check('save_theme keeps the rest', cfg.save_theme('light', path) and
          cfg.load(path)['theme'] == 'light' and cfg.load(path)['keep_running'] == 'off')
    check('0 means no limit', cfg.max_move_ft({'max_move_mm': '0'}) is None)
    check('limit in feet', near(cfg.max_move_ft({'max_move_mm': '304.8'}), 1.0))
    check('theme cycle', [cfg.next_theme(m) for m in ('follow', 'dark', 'light', 'x')] ==
          ['dark', 'light', 'follow', 'follow'])

    # ---- theme follows Revit's canvas -------------------------------------
    class Manager(object):
        pass

    def ui_with(**values):
        manager = Manager()
        for key, value in values.items():
            setattr(manager, key, value)
        return type('UI', (object,), {'UIThemeManager': manager})

    dark = ui_with(CurrentCanvasTheme=s.FakeEnum(0, 'Dark'))
    light = ui_with(CurrentCanvasTheme=s.FakeEnum(1, 'Light'))
    check('UITheme.Dark (0) reads as dark', theme.revit_theme(dark) == 'dark')
    check('Light canvas reads as light', theme.revit_theme(light) == 'light')
    check('falls back to CurrentTheme', theme.revit_theme(ui_with(CurrentTheme=s.FakeEnum(1, 'Light'))) == 'light')
    check('no manager, no answer', theme.revit_theme(type('UI', (object,), {})) is None)
    check('follow on a light canvas draws light', theme.resolve('follow', light) == 'light')
    check('pinned dark beats a light canvas', theme.resolve('dark', light) == 'dark')
    check('follow with no answer draws dark', theme.resolve('follow', type('UI', (object,), {})) == 'dark')
    check('chip says Auto when following', theme.chip_label('follow', 'light') == u'Auto')
    check('palettes carry the same keys', set(theme.DARK) == set(theme.LIGHT))

    # ---- the move, against the fake Revit ---------------------------------
    settings = dict(cfg.DEFAULTS)
    log = core.DebugLog(False)

    def pair(**kw):
        riser = s.FakeElement(1, (0, 0, 0), (0, 0, 10))
        run = s.FakeElement(2, (-10, 0.2, 4), (10, 0.2, 4), **kw)
        return s.FakeDoc([riser, run]), riser, run

    doc, riser, run = pair()
    row = core.align(doc, riser, run, settings, log)
    check('aligns and proves it', row['kind'] == 'ok' and near(run.axis()[0][1], 0.0), row)
    check('reports the distance', near(row['moved_mm'], 0.2 * 304.8, 1e-6))

    doc, riser, run = pair(pinned=True)
    row = core.align(doc, riser, run, settings, log)
    check('pinned is moved and re-pinned', row['kind'] == 'ok' and run.Pinned, row)

    doc, riser, run = pair()
    run.Location.Curve.p = [s.XYZ(-10, 0, 4), s.XYZ(10, 0, 4)]
    row = core.align(doc, riser, run, settings, log)
    check('already aligned opens no transaction', row['kind'] == 'already' and doc.transactions == 0, row)

    doc, riser, run = pair(group=55)
    row = core.align(doc, riser, run, settings, log)
    check('grouped is refused', row['kind'] == 'refused' and 'group' in row['note'], row)

    doc, riser, run = pair()
    doc.IsWorkshared = True
    doc.held_by_other[2] = u'jsmith'
    row = core.align(doc, riser, run, settings, log)
    check('borrowed by someone else is refused and named',
          row['kind'] == 'refused' and 'jsmith' in row['note'] and doc.transactions == 0, row)

    doc, riser, run = pair()
    run.Location.Curve.p = [s.XYZ(-10, 20, 4), s.XYZ(10, 20, 4)]
    row = core.align(doc, riser, run, settings, log)
    check('over the move limit is refused', row['kind'] == 'refused' and 'limit' in row['note'], row)

    doc, riser, run = pair(connections=2, refuse_connected=True)
    row = core.align(doc, riser, run, settings, log)
    check('refused with connections: released, moved, flagged',
          row['kind'] == 'warn' and 'released' in row['note'] and near(run.axis()[0][1], 0.0), row)

    doc, riser, run = pair(connections=2, refuse_connected=True)
    leave = dict(settings, on_refusal='leave')
    row = core.align(doc, riser, run, leave, log)
    check('refused with connections and set to leave: untouched, Revit quoted',
          row['kind'] == 'failed' and 'joined' in row['note'] and near(run.axis()[0][1], 0.2), row)

    doc, riser, run = pair()
    doc.silent_noop = True
    row = core.align(doc, riser, run, settings, log)
    check('a move that does not land is caught on read-back', row['kind'] == 'failed', row)

    doc, riser, run = pair()
    doc.warnings_on_commit = [u'a warning']
    row = core.align(doc, riser, run, settings, log)
    check('warnings are swallowed, not fatal', row['kind'] == 'ok', row)

    riser = s.FakeElement(1, (0, 0, 0), (0, 0, 10))
    run = s.FakeElement(2, (-10, 0.2, 10), (0, 0.2, 10), drags=[1])
    doc = s.FakeDoc([riser, run])
    row = core.align(doc, riser, run, settings, log)
    check('a datum dragged along by its connection is flagged', row['kind'] == 'warn' and
          'first element' in row['note'], row)

    fitting = s.FakeElement(3, (0, 0, 0), (1, 0, 0), category='fitting')
    check('fittings are not offered', not core.is_target(fitting))
    check('cable trays are offered', core.is_target(s.FakeElement(4, (0, 0, 0), (1, 0, 0), category='tray')))
    flt = core.AlignFilter(exclude_id=1, need_kind=g.VERTICAL)
    check('after a horizontal only uprights are offered',
          not flt.AllowElement(s.FakeElement(5, (0, 0, 0), (9, 0, 0))) and
          flt.AllowElement(s.FakeElement(6, (0, 0, 0), (0, 0, 9))))
    check('the datum cannot be picked twice', not flt.AllowElement(s.FakeElement(1, (0, 0, 0), (0, 0, 9))))

    rows_ok = [{'kind': 'ok'}, {'kind': 'already'}]
    check('clean run shows nothing', not core.should_show(rows_ok, 'needs_look'))
    check('a check shows the window', core.should_show(rows_ok + [{'kind': 'warn'}], 'needs_look'))
    check('never means never', not core.should_show([{'kind': 'failed'}], 'never'))
    check('always means always', core.should_show(rows_ok, 'always'))

    # ---- the command loop -------------------------------------------------
    def scene():
        riser = s.FakeElement(1, (0, 0, 0), (0, 0, 10))
        run_a = s.FakeElement(2, (-10, 0.2, 4), (10, 0.2, 4))
        run_b = s.FakeElement(3, (0.1, -10, 6), (0.1, 10, 6))
        return s.FakeDoc([riser, run_a, run_b]), riser, run_a, run_b

    doc, riser, run_a, run_b = scene()
    uidoc = s.FakeUIDoc(doc, [run_a, riser, run_b], selected=[riser])
    rows = core.main(s.FakeUIApp(uidoc))
    check('pre-selection is the first pick, then it keeps going',
          len(rows) == 2 and near(run_a.axis()[0][1], 0.0) and near(run_b.axis()[0][0], 0.0), rows)
    check('selection cleared at the end', uidoc.Selection.selected == [])

    doc, riser, run_a, run_b = scene()
    uidoc = s.FakeUIDoc(doc, [riser, None, riser, run_a])
    rows = core.main(s.FakeUIApp(uidoc))
    check('Esc on the second pick goes back to the first', len(rows) == 1 and rows[0]['kind'] == 'ok', rows)

    doc, riser, run_a, run_b = scene()
    cfg.save(dict(cfg.DEFAULTS, keep_running='off'))
    uidoc = s.FakeUIDoc(doc, [riser, run_a, riser, run_b])
    rows = core.main(s.FakeUIApp(uidoc))
    check('stop after one', len(rows) == 1 and near(run_b.axis()[0][0], 0.1), rows)
    cfg.save(dict(cfg.DEFAULTS))

    doc, riser, run_a, run_b = scene()
    uidoc = s.FakeUIDoc(doc, [riser])
    seen = []
    core.main(s.FakeUIApp(uidoc), lambda r, st: seen.append(r))
    check('Esc straight away exits with no report', seen == [] and len(uidoc.Selection.prompts) == 3)

    doc, riser, run_a, run_b = scene()
    uidoc = s.FakeUIDoc(doc, [run_a, riser])
    core.main(s.FakeUIApp(uidoc))
    check('horizontal first asks for an upright', uidoc.Selection.filters[1].need_kind == g.VERTICAL and
          near(riser.axis()[0][1], 0.2))


def report():
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        if not ok:
            sys.stdout.write('FAIL  {0}  {1}\n'.format(name, detail))
    sys.stdout.write('{0} checks, {1} failed\n'.format(len(RESULTS), len(failed)))
    return 1 if failed else 0


# Each breakage is (file, text to find, replacement, what it breaks).
BREAKAGES = [
    ('a3d_geom.py', 'STEEP_DEG = 46.0', 'STEEP_DEG = 4.0', 'vertical threshold'),
    ('a3d_geom.py', 'move = (-offset[0], -offset[1])', 'move = (offset[0], offset[1])', 'H-V direction'),
    ('a3d_geom.py', "'move': (move[0], move[1], 0.0)", "'move': (move[0], move[1], 0.01)", 'plan only'),
    ('a3d_geom.py', 'target = xy_at_z(first, z)\n            move, along',
     'target = xy_at_z(first, mid_z(first))\n            move, along', 'height of the crossing'),
    ('theme.py', 'if value is not None:', 'if value:', 'UITheme.Dark is 0'),
    ('a3d_settings.py', 'return value if value in CHOICES[key] else None', 'return value', 'bad values'),
    ('a3d_core.py', '            element.Pinned = True', '            pass', 're-pin'),
    ('a3d_core.py', "if check is None or not check['ok'] or not geom.is_aligned(check['distance']):",
     'if False:', 'read-back'),
    ('a3d_core.py', 'return False, owner_of(doc, element_id)', "return True, u''", 'borrowing'),
    ('a3d_core.py', "if settings.get('on_refusal') == 'detach' and joined_before > 0:", 'if False:',
     'release and move'),
    ('a3d_core.py', "if plan['already']:", 'if False:', 'already aligned'),
    ('a3d_core.py', "if limit is not None and plan['distance'] > limit:", 'if False:', 'move limit'),
    ('a3d_core.py', 'in_group = eid_value(second.GroupId) > 0', 'in_group = False', 'groups'),
    ('a3d_core.py', "return any(row['kind'] in NEEDS_LOOK for row in rows)", 'return True', 'quiet runs'),
    ('a3d_core.py', '                if keep_running:\n                    continue',
     '                if False:\n                    continue', 'Esc goes back'),
    ('a3d_core.py', 'first = preselected(uidoc, log)', 'first = None', 'pre-selection'),
    ('a3d_core.py', 'need = geom.VERTICAL if kind == geom.HORIZONTAL else None', 'need = None',
     'uprights only after a horizontal'),
    ('a3d_core.py', 'datum_moved = geom.moved_by(first_axis, first_after) > geom.ALIGNED_FT',
     'datum_moved = False', 'dragged datum'),
]


def selftest():
    failures = 0
    for filename, old, new, label in BREAKAGES:
        work = tempfile.mkdtemp()
        target = os.path.join(work, 'tool')
        shutil.copytree(HERE, target, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(target, filename)
        with open(path) as handle:
            text = handle.read()
        if text.count(old) != 1:
            sys.stdout.write('BROKEN BREAKAGE  {0}: anchor found {1} times\n'.format(label, text.count(old)))
            failures += 1
            continue
        with open(path, 'w') as handle:
            handle.write(text.replace(old, new))
        code = subprocess.call([sys.executable, os.path.join(target, 'bench_logic.py')],
                               stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
        caught = code != 0
        sys.stdout.write('{0}  {1}\n'.format('caught ' if caught else 'MISSED ', label))
        if not caught:
            failures += 1
        shutil.rmtree(work, ignore_errors=True)
    sys.stdout.write('{0} breakages, {1} missed\n'.format(len(BREAKAGES), failures))
    return 1 if failures else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    run_checks()
    sys.exit(report())
