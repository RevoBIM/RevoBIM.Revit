# -*- coding: utf-8 -*-
"""Circuit Manager - logic bench. Plain CPython 3, no Revit:

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the code on purpose and confirm
                                      each breakage is caught

Covers the rules that decide values (path modes, offsets, clipboard, paste
plans, filters, sorting, staging, settings, theme) and the shrink-to-taskbar
drawer driven against a fake window and a fake timer. The fake timer never
runs ticks inside Start() - like a real DispatcherTimer - and records any
exception escaping a tick the way the dispatcher would; any record fails.
"""
import importlib
import io
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))


# ======================================================================
# fakes
# ======================================================================
class Vis(object):
    Visible = 'Visible'
    Collapsed = 'Collapsed'


class VA(object):
    Top = 'Top'
    Stretch = 'Stretch'


class STC(object):
    Manual = 'Manual'
    Height = 'Height'


class FakeTimer(object):
    def __init__(self, env, tick):
        self.env, self.tick, self.running = env, tick, False

    def Start(self):
        self.running = True
        self.env.timers.append(self)

    def Stop(self):
        self.running = False


class FakeEnv(object):
    Visibility = Vis
    VerticalAlignment = VA
    SizeToContent = STC
    NaN = float('nan')

    def __init__(self, work=(0.0, 1040.0), bar_h=50.0, explode_at=None):
        self.work = work
        self.bar_h = bar_h
        self.clock = 0.0
        self.timers = []
        self.released = 0
        self.escaped = []
        self.explode_at = explode_at

    def make_timer(self, ms, tick):
        return FakeTimer(self, tick)

    def release(self, window):
        self.released += 1

    def work_area(self, window):
        return self.work

    def bar_height(self, header):
        return self.bar_h

    def now_ms(self):
        if self.explode_at is not None and self.clock >= self.explode_at:
            raise RuntimeError('frame blew up')
        return self.clock

    def run(self, ms=600.0, step=15.0):
        """The dispatcher: tick running timers, record what escapes."""
        end = self.clock + ms
        while self.clock < end:
            self.clock += step
            for t in list(self.timers):
                if t.running:
                    try:
                        t.tick(t, None)
                    except Exception as ex:
                        self.escaped.append(ex)


class El(object):
    def __init__(self, name):
        self.name = name
        self.Visibility = Vis.Visible
        self.Height = float('nan')
        self.ActualHeight = 600.0
        self.VerticalAlignment = VA.Stretch
        self.Tag = ''
        self.ToolTip = ''


class Win(object):
    def __init__(self):
        self.Left, self.Top, self.Height = 100.0, 120.0, 700.0
        self.ActualHeight = 700.0
        self.MinHeight = 400.0
        self.SizeToContent = STC.Manual


def make_drawer(env, win=None):
    import cm_drawer
    if win is None:
        cm_drawer._SLOTS.clear()       # each check starts with no bars parked
    win = win or Win()
    els = dict((n, El(n)) for n in ('header', 'body', 'btn', 'sg', 'eg',
                                    'grips', 'toolbar', 'footer'))
    els['eg'].Visibility = Vis.Collapsed
    d = cm_drawer.WindowDrawer(win, els['header'], els['body'], els['btn'],
                               els['sg'], els['eg'], grips=els['grips'],
                               env=env, siblings=[els['body'], els['toolbar'],
                                                  els['footer']])
    return d, win, els


# ======================================================================
# checks
# ======================================================================
CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def eq(a, b, what):
    if a != b:
        raise AssertionError('{0}: {1!r} != {2!r}'.format(what, a, b))


def near(a, b, what, tol=0.01):
    if abs(a - b) > tol:
        raise AssertionError('{0}: {1} != {2}'.format(what, a, b))


@check
def path_modes():
    import cm_logic as L
    eq(L.path_mode_label('FarthestDevice'), u'Farthest Device', 'label')
    eq(L.path_mode_label('AllDevices'), u'All Devices', 'label')
    eq(L.parse_path_mode(u'Farthest Device'), 'FarthestDevice', 'parse label')
    eq(L.parse_path_mode(u'all devices'), 'AllDevices', 'parse lower')
    eq(L.parse_path_mode(u'Custom'), 'Custom', 'parse custom')
    eq(L.parse_path_mode(u'far'), 'FarthestDevice', 'alias')
    eq(L.parse_path_mode(u'2750'), None, 'junk')
    eq(L.parse_path_mode(u''), None, 'blank')


@check
def custom_needs_a_stored_path():
    import cm_logic as L
    ok, refused = L.mode_targets([1, 2, 3], 'Custom', {1: True, 2: False})
    eq(ok, [1], 'only circuits with a custom path take Custom')
    eq([r for r, why in refused], [2, 3], 'the rest are refused')
    ok, refused = L.mode_targets([1, 2], 'AllDevices', {})
    eq((ok, refused), ([1, 2], []), 'other modes need no path')


@check
def offsets():
    import cm_logic as L
    eq(L.parse_mm(u'2750'), 2750.0, 'plain')
    eq(L.parse_mm(u'2,750.0 mm'), 2750.0, 'comma and unit')
    eq(L.parse_mm(u'2.75m'), 2750.0, 'metres')
    eq(L.parse_mm(u'-150'), -150.0, 'negative')
    eq(L.parse_mm(u'Varies'), None, 'Varies is not a length')
    eq(L.parse_mm(u''), None, 'blank')
    eq(L.parse_mm(u'1e3'), None, 'no exponents')
    eq(L.parse_mm(u'99999999'), None, 'over Revit 30000 ft limit')
    eq(L.format_mm(2750), u'2750.0', 'formats like Revit')
    near(L.mm_to_feet(304.8), 1.0, 'feet')
    eq(L.feet_to_mm_text(2750 / 304.8), u'2750.0', 'round trip')


@check
def input_rules():
    import cm_logic as L
    eq(L.normalise_input('po', u' 2750mm '), (u'2750.0', None), 'po')
    eq(L.normalise_input('po', u'abc')[0], None, 'po junk')
    eq(L.normalise_input('pm', u'all'), (u'All Devices', None), 'pm')
    eq(L.normalise_input('yesno', u'TRUE'), (u'Yes', None), 'yes')
    eq(L.normalise_input('int', u'7'), (u'7', None), 'int')
    eq(L.normalise_input('int', u'7.5')[0], None, 'int junk')
    eq(L.same_value('po', u'2750', u'2750.0'), True, 'po equal')
    eq(L.same_value('pm', u'Farthest Device', u'FarthestDevice'), True,
       'pm equal')


@check
def clipboard():
    import cm_logic as L
    eq(L.parse_clipboard(u'2750\r\n'), [[u'2750']], 'Excel trailing newline')
    eq(L.parse_clipboard(u'a\tb\r\nc\td'), [[u'a', u'b'], [u'c', u'd']],
       'block')
    block = [[u'1', u'2'], [u'3', u'']]
    eq(L.parse_clipboard(L.to_clipboard(block)), block, 'round trip')
    eq(L.copy_block([(0, 0, u'a'), (2, 0, u'c')]), [[u'a'], [u'c']],
       'ragged rows close up')


@check
def paste_one_value_fills_the_selection():
    import cm_logic as L
    sel = [(0, 5), (3, 5), (7, 5)]
    plan = L.paste_plan([[u'2750']], sel, list(range(10)), [4, 5])
    eq(plan, [(0, 5, u'2750'), (3, 5, u'2750'), (7, 5, u'2750')],
       'one value into every selected cell')


@check
def paste_block_from_top_left():
    import cm_logic as L
    clip = [[u'a', u'b'], [u'c', u'd'], [u'e', u'f']]
    plan = L.paste_plan(clip, [(1, 4)], [0, 1, 2], [4, 5])
    eq(plan, [(1, 4, u'a'), (1, 5, u'b'), (2, 4, u'c'), (2, 5, u'd')],
       'clipped at the last row')
    eq(L.paste_plan(clip, [(9, 4)], [0, 1], [4]), [],
       'top-left outside the view pastes nothing')


@check
def filters():
    import cm_logic as L
    rows = [{'panel': u'DB-1', 'pm': u'All Devices'},
            {'panel': u'DB-2', 'pm': u'Farthest Device'},
            {'panel': u'DB-10', 'pm': u'All Devices'}]
    eq(L.row_visible(rows[0], {'panel': u'db 1'}, {}), True, 'words any order')
    eq(L.row_visible(rows[1], {}, {'pm': set([u'All Devices'])}), False,
       'tick list')
    vals = L.list_values(rows, 'pm', {}, {'pm': set([u'All Devices'])})
    eq(vals, [u'All Devices', u'Farthest Device'],
       'own filter excluded from its own list')
    vals = L.list_values(rows, 'panel', {}, {'pm': set([u'All Devices'])})
    eq(vals, [u'DB-1', u'DB-10'], 'other filters narrow the list')
    eq(L.is_filtered('pm', {}, {'pm': None}), False, 'all ticked = none')
    vals = L.list_values(rows, 'panel', {'panel': u'DB-2'}, {})
    eq(vals, [u'DB-1', u'DB-2', u'DB-10'],
       'own keyword filter excluded from its own list too')


@check
def natural_sort():
    import cm_logic as L
    vals = [{'n': u'P-10'}, {'n': u'P-9'}, {'n': u'P-100'}, {'n': u'p-2'}]
    order = [vals[i]['n'] for i in L.sort_order(vals, 'n', False)]
    eq(order, [u'p-2', u'P-9', u'P-10', u'P-100'], 'natural')
    order = [vals[i]['n'] for i in L.sort_order(vals, 'n', True)]
    eq(order[0], u'P-100', 'descending')


@check
def staging():
    import cm_logic as L
    st = L.Stage()
    orig = {(1, 'po'): u'2750.0', (2, 'po'): u'2750.0', (1, 'pm'): u'All Devices'}
    kinds = {'po': 'po', 'pm': 'pm'}
    st.apply_batch([(1, 'po', u'3000.0'), (2, 'po', u'3000.0')], orig, kinds)
    eq(st.count(), 2, 'paste of two')
    st.apply_batch([(1, 'po', u'2750')], orig, kinds)
    eq(st.has(1, 'po'), False, 'back to the original unstages')
    st.apply_batch([(1, 'pm', u'Farthest Device')], orig, kinds)
    eq(st.by_element()[1][0][0], 'pm', 'mode before offset')
    st.undo_last()
    st.undo_last()
    eq(st.get(1, 'po'), u'3000.0', 'undo is per batch')
    st.undo_last()
    eq(st.count(), 0, 'all undone')
    st.apply_batch([(1, 'po', u'1.0'), (1, 'pm', u'Custom')], orig, kinds)
    eq([k for k, v in st.by_element()[1]], ['pm', 'po'], 'pm, po order')


@check
def settings():
    import cm_logic as L
    s = L.parse_settings(u'theme=dark\ncolumns=Rating|Wire=Size\nbogus\n')
    eq(s['theme'], 'dark', 'value')
    eq(s['columns'], u'Rating|Wire=Size', 'split on the first = only')
    eq(L.split_columns(s['columns']), [u'Rating', u'Wire=Size'], 'columns')
    eq(L.parse_settings(u'')['debug'], '1', 'debug on by default')
    eq(L.parse_settings(u'settings_version=0')['settings_version'],
       str(L.SETTINGS_VERSION), 'migrated')
    back = L.parse_settings(L.dump_settings(s))
    eq(back['columns'], s['columns'], 'round trip')


@check
def theme():
    import cm_logic as L
    eq(L.resolve_theme('follow', True), 'dark', 'canvas dark')
    eq(L.resolve_theme('follow', False), 'light', 'canvas light')
    eq(L.resolve_theme('follow', None), 'dark', 'unreadable -> dark')
    eq(L.resolve_theme('light', True), 'light', 'forced light')
    eq([L.next_theme('follow'), L.next_theme('dark'), L.next_theme('light')],
       ['dark', 'light', 'follow'], 'chip cycle')


@check
def canvas_dark_is_zero():
    """UITheme.Dark is 0 - a truthiness test reports Dark as Light."""
    stubs = install_stubs()
    try:
        ui = stubs['Autodesk.Revit.UI']
        import cm_theme
        importlib.reload(cm_theme)
        ui.UIThemeManager.CurrentCanvasTheme = 0
        eq(cm_theme.canvas_is_dark(), True, 'Dark (0) reads as dark')
        ui.UIThemeManager.CurrentCanvasTheme = 1
        eq(cm_theme.canvas_is_dark(), False, 'Light reads as light')
        del ui.UIThemeManager
        eq(cm_theme.canvas_is_dark(), None, 'pre-2024: unreadable')
    finally:
        remove_stubs(stubs)


@check
def park_maths():
    import cm_logic as L
    eq(L.park_top(0, 1040, 50, 0), 1040 - 8 - 50, 'slot 0')
    eq(L.park_top(0, 1040, 50, 1), 1040 - 8 - 50 - 54, 'slot 1 stacks')
    eq(L.park_top(-1080, -40, 50, 0), -40 - 8 - 50,
       'monitor above the primary keeps its negative top')
    eq(L.reopen_top(120, 982, 982, 700, 0, 1040), 120, 'back where it was')
    eq(L.reopen_top(120, 982, 600, 700, 0, 1040), 340,
       'dragged bar opens from where it sits, kept on screen')
    eq(L.free_slot(set([0, 2])), 1, 'freed slot reused')


@check
def drawer_full_cycle():
    env = FakeEnv()
    d, win, els = make_drawer(env)
    d.toggle()
    eq(d.sliding, True, 'slides')
    eq(els['body'].Visibility, Vis.Visible, 'body stays for the slide')
    eq(els['body'].VerticalAlignment, VA.Top, 'body pinned')
    eq(win.MinHeight, 0, 'MinHeight relaxed')
    env.run()
    eq(env.escaped, [], 'nothing escaped a tick')
    eq((d.parked, d.sliding), (True, False), 'parked')
    near(win.Top, 1040 - 8 - 50, 'bar above the taskbar')
    eq(win.Height, 50, 'cut to the bar')
    eq(els['eg'].Visibility, Vis.Visible, 'green up arrow shows')
    eq(els['sg'].Visibility, Vis.Collapsed, 'shrink glyph hides')
    eq(els['body'].Visibility, Vis.Collapsed, 'body collapsed when parked')
    eq(els['grips'].Visibility, Vis.Collapsed, 'grips parked too')
    d.toggle()
    env.run()
    eq(env.escaped, [], 'nothing escaped a tick')
    eq(d.parked, False, 'open again')
    near(win.Top, 120, 'back where it was')
    eq(win.Height, 700, 'full height')
    eq(win.MinHeight, 400, 'MinHeight back')
    eq(els['body'].Visibility, Vis.Visible, 'body back')
    eq(els['eg'].Visibility, Vis.Collapsed, 'arrow gone')
    eq(els['body'].VerticalAlignment, VA.Stretch, 'body unpinned')
    if env.released < 4:
        raise AssertionError('animations not released before every slide')


@check
def drawer_eases():
    env = FakeEnv()
    d, win, els = make_drawer(env)
    d.shrink()
    env.run(ms=30)
    first = win.Top
    env.run(ms=30)
    second = win.Top
    if not (120 < first < second < 982):
        raise AssertionError('not easing down: {0} {1}'.format(first, second))
    if (second - first) >= (first - 120):
        raise AssertionError('ease out: fast first, slow later')
    env.run()


@check
def drawer_keys():
    env = FakeEnv()
    d, win, els = make_drawer(env)
    eq(d.on_key('Escape', False, False), False, 'open: Esc not taken')
    eq(d.on_key('H', True, True), True, 'Ctrl+Shift+H shrinks')
    eq(d.on_key('A', False, False), True, 'keys swallowed mid-slide')
    env.run()
    eq(d.on_key('C', True, False), True, 'parked: keys swallowed')
    eq(d.parked, True, 'still parked')
    eq(d.on_key('Escape', False, False), True, 'Esc reopens')
    env.run()
    eq(d.parked, False, 'reopened')
    d.shrink()
    env.run()
    eq(d.on_header_double_click(), True, 'double click reopens when parked')
    env.run()
    eq(d.on_header_double_click(), False, 'open: double click is full screen')


@check
def drawer_owner_goes_down_and_up():
    env = FakeEnv()
    main, mwin, mels = make_drawer(env)
    dlg, dwin, dels = make_drawer(env, Win())
    dlg.set_owner(main)
    dlg.shrink()
    eq(main.parked, True, 'owner down first, instantly')
    env.run()
    if not dwin.Top < mwin.Top:
        raise AssertionError('dialog bar stacks above the main bar')
    dlg.expand()
    env.run()
    eq(main.parked, False, 'owner back behind the dialog')
    dlg.shrink()
    env.run()
    dlg.released()
    eq(main.parked, False, 'closing a parked dialog brings the owner back')


@check
def drawer_frame_that_throws_lands():
    env = FakeEnv(explode_at=30.0)
    d, win, els = make_drawer(env)
    d.shrink()
    env.run()
    eq(env.escaped, [], 'nothing escaped to the dispatcher')
    eq(d.sliding, False, 'not stuck sliding')
    near(win.Top, 982, 'landed at the end state')
    eq(len(d.errors) > 0, True, 'error recorded')


@check
def drawer_dragged_bar_reopens_there():
    env = FakeEnv()
    d, win, els = make_drawer(env)
    d.shrink()
    env.run()
    win.Top = 600.0          # user dragged the bar
    d.expand()
    env.run()
    near(win.Top, 340, 'opens from the bar, kept on screen')


# ======================================================================
# stubs for cm_theme (System / Autodesk under CPython)
# ======================================================================
STUB_NAMES = ['clr', 'System', 'System.IO', 'System.Windows',
              'System.Windows.Markup', 'System.Windows.Media',
              'Autodesk', 'Autodesk.Revit', 'Autodesk.Revit.UI']


def install_stubs():
    saved = dict((n, sys.modules.get(n)) for n in STUB_NAMES)
    for n in STUB_NAMES:
        sys.modules[n] = types.ModuleType(n)
    sys.modules['clr'].AddReference = lambda name: None
    sys.modules['System.IO'].File = object()
    sys.modules['System.Windows.Markup'].XamlReader = object()
    media = sys.modules['System.Windows.Media']
    media.SolidColorBrush = media.ColorConverter = media.Color = object()
    ui = sys.modules['Autodesk.Revit.UI']

    class UITheme(object):
        Dark = 0
        Light = 1

    class UIThemeManager(object):
        CurrentCanvasTheme = 0
    ui.UITheme = UITheme
    ui.UIThemeManager = UIThemeManager
    sys.modules['Autodesk'].Revit = sys.modules['Autodesk.Revit']
    sys.modules['Autodesk.Revit'].UI = ui
    return {'saved': saved, 'Autodesk.Revit.UI': ui}


def remove_stubs(stubs):
    for n, mod in stubs['saved'].items():
        if mod is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = mod
    for n in ('cm_theme', 'cm_clr'):
        sys.modules.pop(n, None)


# ======================================================================
def run(folder, quiet=False):
    sys.path.insert(0, folder)
    for n in list(sys.modules):
        if n.startswith('cm_'):
            del sys.modules[n]
    failed = []
    try:
        for fn in CHECKS:
            try:
                fn()
                ok = True
            except Exception as ex:
                ok = False
                failed.append(fn.__name__)
                if not quiet:
                    print('FAIL  {0}: {1}'.format(fn.__name__, ex))
            if ok and not quiet:
                print('ok    {0}'.format(fn.__name__))
    finally:
        sys.path.remove(folder)
        for n in list(sys.modules):
            if n.startswith('cm_'):
                del sys.modules[n]
    return failed


BREAKAGES = [
    ('cm_logic.py', "('AllDevices', u'All Devices'),", "('AllDevice', u'All Devices'),"),
    ('cm_logic.py', "        if mode == 'Custom' and not custom_ok.get(r, False):",
     "        if False:"),
    ('cm_logic.py', "    if abs(mm / MM_PER_FOOT) > MAX_OFFSET_FT:\n        return None\n", ""),
    ('cm_logic.py', "    if t.endswith('\\n'):\n        t = t[:-1]\n", ""),
    ('cm_logic.py', "    if len(clip) == 1 and len(clip[0]) == 1:", "    if False:"),
    ('cm_logic.py', "        if r0 + i >= len(row_positions):\n            break\n", ""),
    ('cm_logic.py', "        if key == exclude:\n            continue\n        if not matches_text",
     "        if not matches_text"),
    ('cm_logic.py', "        if key == exclude or allowed is None:", "        if allowed is None:"),
    ('cm_logic.py', "            out.append((0, float(part), u''))", "            out.append((1, 0.0, part))"),
    ('cm_logic.py', "            if same_value(kinds.get(key, 'string'), value, orig):",
     "            if False:"),
    ('cm_logic.py', "        rank = {'pm': 0, 'po': 1}", "        rank = {'pm': 1, 'po': 0}"),
    ('cm_logic.py', "        k, v = line.split('=', 1)", "        k, v = line.split('=')[:2]"),
    ('cm_logic.py', "    if canvas_dark is None:\n        return 'dark'", "    if canvas_dark is None:\n        return 'light'"),
    ('cm_logic.py', "    return max(work_top, top)", "    return max(0.0, top)"),
    ('cm_logic.py', "    if abs(bar_top - parked_top) < 1.0:", "    if True:"),
    ('cm_theme.py', "        if value is not None:", "        if value:"),
    ('cm_drawer.py', "        self._hide_siblings()          # full height on the way down; cut on landing\n", ""),
    ('cm_drawer.py', "            w.MinHeight = self.saved.get('min_height', 0)", "            pass"),
    ('cm_drawer.py', "        self._unpin_body()\n\n    def released", "\n    def released"),
    ('cm_drawer.py', "        if self.owner is not None and not self.owner.parked:\n            self.owner.shrink(instant=True)\n", ""),
    ('cm_drawer.py', "            if self.owner.parked:\n                self.owner.expand(instant=True)\n\n    #", "\n    #"),
    ('cm_drawer.py', "            except Exception as ex:\n                self.errors.append(ex)\n                finish()\n", "            except Exception as ex:\n                raise\n"),
    ('cm_drawer.py', "            return True              # nothing acts on a window nobody sees", "            return False"),
    ('cm_drawer.py', "                k = cm_logic.ease_out_cubic(t)", "                k = t"),
    ('cm_drawer.py', "        env.release(w)\n        full_h", "        full_h"),
]


def selftest():
    if run(HERE, quiet=True):
        print('the clean tool fails - fix that first')
        run(HERE)
        return False
    ok = True
    for f, anchor, repl in BREAKAGES:
        tmp = tempfile.mkdtemp()
        try:
            for name in os.listdir(HERE):
                p = os.path.join(HERE, name)
                if os.path.isfile(p) and name.endswith('.py'):
                    shutil.copy(p, tmp)
            with io.open(os.path.join(tmp, f), 'r', encoding='utf-8') as fh:
                text = fh.read()
            if anchor not in text:
                print('BROKEN SELFTEST  anchor missing in {0}: {1!r}'.format(
                    f, anchor[:50]))
                ok = False
                continue
            with io.open(os.path.join(tmp, f), 'w', encoding='utf-8') as fh:
                fh.write(text.replace(anchor, repl, 1))
            failed = run(tmp, quiet=True)
            print('{0:7s} {1:13s} {2}'.format('caught' if failed else 'MISSED',
                                              f, ', '.join(failed)[:60]))
            ok = ok and bool(failed)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print('SELFTEST ' + ('PASSED ({0} breakages)'.format(len(BREAKAGES))
                         if ok else 'FAILED'))
    return ok


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    failed = run(HERE)
    print('LOGIC BENCH ' + ('FAILED' if failed else 'PASSED ({0} checks)'.format(
        len(CHECKS))))
    sys.exit(1 if failed else 0)
