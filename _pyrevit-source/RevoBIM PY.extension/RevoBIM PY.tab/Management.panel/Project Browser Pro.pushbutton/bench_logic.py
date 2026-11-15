# -*- coding: utf-8 -*-
u"""Project Browser Pro - logic bench, run under plain CPython 3.

    python bench_logic.py              run every check
    python bench_logic.py --selftest   break the tool one way at a time, in a
                                       copy, and prove a check catches each

The pure modules (tree, settings, hand-off, palette, icons) are tested
against tables of cases. The rest of the tool is imported and driven
against bench_stub's fake .NET and Revit, which catches what a stub can
catch: typos, attributes read before they are set, wrong calls into our own
code, and wrong logic in the browser's handlers.
"""
import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def temp_appdata():
    folder = tempfile.mkdtemp(prefix='pbp_bench_')
    os.environ['APPDATA'] = folder
    return folder


# ============================================================
# pure logic
# ============================================================

@check
def natural_sort():
    from pbp_compat import natural_key
    names = ['Level 10', 'Level 2', 'level 1', 'B1', 'A', '10', '9']
    got = sorted(names, key=natural_key)
    assert got == ['9', '10', 'A', 'B1', 'level 1', 'Level 2', 'Level 10'], got


@check
def search_words():
    from pbp_compat import words, matches
    assert words('  Level  2 ') == ['level', '2']
    assert matches('Level 2 - Mechanical', words('mech 2'))
    assert not matches('Level 2 - Mechanical', words('mech 3'))
    assert matches('anything', [])


@check
def element_ids():
    from pbp_compat import eid_value

    class New(object):
        Value = 12345678901

    class Old(object):
        IntegerValue = 42

        @property
        def Value(self):
            raise AttributeError('Value')

    assert eid_value(New()) == 12345678901
    assert eid_value(Old()) == 42
    assert eid_value(None) == 0


def _leaf(key, tab, text, folders=(), values=None, kind='plan', number='', sort_text=''):
    from pbp_tree import Leaf
    return Leaf(key, tab, kind, text, folders=list(folders), values=values or {},
                number=number, sort_text=sort_text)


@check
def tree_revit_grouping():
    import pbp_tree as t
    leaves = [_leaf('a', 'views', 'Level 10', ['Mech', 'Floor Plans']),
              _leaf('b', 'views', 'Level 2', ['Mech', 'Floor Plans']),
              _leaf('c', 'views', 'Loose', ['', 'Sections']),
              _leaf('d', 'views', 'Elec 1', ['Elec', 'Floor Plans'])]
    root = t.build_tab('views', leaves, {'source': 'revit'})
    assert [c.label for c in root.children] == ['Elec', 'Mech', t.UNSET], [c.label for c in root.children]
    assert root.count == 4
    rows = t.flatten([root], set(), [], False)
    texts = [(r.text, r.level) for r in rows]
    assert texts[:3] == [('Elec', 0), ('Floor Plans', 1), ('Elec 1', 2)], texts
    mech = [r.text for r in rows if r.level == 2 and r.text.startswith('Level')]
    assert mech == ['Level 2', 'Level 10'], mech


@check
def tree_custom_sort_desc():
    import pbp_tree as t
    leaves = [_leaf(str(i), 'sheets', 'S%d' % i, values={'Disc': d, 'Num': n})
              for i, (d, n) in enumerate([('M', '3'), ('M', '10'), ('E', '1'), ('', '2')])]
    org = {'source': 'custom', 'levels': ['Disc'], 'sort': 'Num', 'desc': True}
    root = t.build_tab('sheets', leaves, org)
    labels = [c.label for c in root.children]
    assert labels == ['E', 'M', t.UNSET], labels
    m = [c for c in root.children if c.label == 'M'][0]
    assert [l.values['Num'] for l in m.leaves] == ['10', '3'], [l.values['Num'] for l in m.leaves]


@check
def tree_flat_sort():
    import pbp_tree as t
    leaves = [_leaf('1', 'schedules', 'b 10'), _leaf('2', 'schedules', 'b 9'), _leaf('3', 'schedules', 'A')]
    root = t.build_tab('schedules', leaves, {'source': 'none', 'levels': [], 'sort': '', 'desc': False})
    assert [l.text for l in root.leaves] == ['A', 'b 9', 'b 10']
    rows = t.flatten([root], set(), [], False)
    assert [r.text for r in rows] == ['A', 'b 9', 'b 10']


@check
def flatten_defaults():
    import pbp_tree as t
    v = t.build_tab('views', [_leaf('a', 'views', 'L1', ['F', 'Floor Plans'])], {'source': 'revit'})
    s = t.build_tab('sheets', [_leaf('b', 'sheets', 'M-01', [], kind='sheet')], {'source': 'revit'})
    roots = [v, s]
    # Default: everything expanded on every tab.
    rows = t.flatten(roots, t.default_collapsed(), [], True)
    assert [(r.text, r.level) for r in rows] == [('Views', 0), ('F', 1), ('Floor Plans', 2), ('L1', 3),
                                                 ('Sheets', 0), ('M-01', 1)], \
        [(r.text, r.level) for r in rows]
    single = t.flatten([v], t.default_collapsed(), [], False)
    assert [r.text for r in single] == ['F', 'Floor Plans', 'L1'], [r.text for r in single]
    assert not t.is_collapsed(t.default_collapsed(), roots, True)
    # Collapse all keeps the type roots open on the All tab.
    shut = t.collapse_all_state(roots, True)
    rows = t.flatten(roots, shut, [], True)
    assert [r.text for r in rows] == ['Views', 'F', 'Sheets', 'M-01'], [r.text for r in rows]
    assert t.is_collapsed(shut, roots, True)
    opened = t.toggle(shut, v.children[0].key)
    assert not t.is_collapsed(opened, roots, True)
    assert t.toggle(opened, v.children[0].key) == shut
    # A folder that appears after a refresh starts open, not closed.
    v2 = t.build_tab('views', [_leaf('a', 'views', 'L1', ['F', 'Floor Plans']),
                               _leaf('b', 'views', 'X1', ['G', 'Sections'])], {'source': 'revit'})
    rows = t.flatten([v2], set([v.children[0].key]), [], False)
    assert [r.text for r in rows] == ['F', 'G', 'Sections', 'X1'], [r.text for r in rows]


@check
def flatten_search():
    import pbp_tree as t
    leaves = [_leaf('a', 'views', 'Pipework L1', ['Mech', 'Floor Plans']),
              _leaf('b', 'views', 'Ductwork L1', ['Mech', 'Floor Plans']),
              _leaf('c', 'views', 'Lighting L1', ['Elec', 'Floor Plans'])]
    root = t.build_tab('views', leaves, {'source': 'revit'})
    # Every folder closed by hand: a search must still open the ones
    # holding a match, or the match is hidden inside a closed folder.
    closed = t.all_group_keys([root])
    rows = t.flatten([root], closed, ['pipe'], False)
    assert [r.text for r in rows] == ['Mech', 'Floor Plans', 'Pipework L1'], [r.text for r in rows]
    assert rows[0].count == 1 and rows[0].expanded
    rows = t.flatten([root], closed, ['elec'], False)
    assert [r.text for r in rows] == ['Elec', 'Floor Plans', 'Lighting L1'], [r.text for r in rows]
    assert t.flatten([root], set(), ['nothing'], False) == []


def _dependents():
    from pbp_tree import Leaf
    def view(key, text, parent=u'', sortv='5'):
        return Leaf(key, 'views', 'dependent' if parent else 'plan', text,
                    folders=['Mech', 'Floor Plans'], values={'Disc': 'M', 'S': sortv}, parent=parent)
    return [view('p0', 'VRF_L00', sortv='2'), view('p1', 'VRF_L01', sortv='3'),
            view('d1', 'DEP_VRF_L00_Admin Building B', 'p0', '9'),
            view('d0', 'DEP_VRF_L00_Admin Building A', 'p0', '1'),
            view('d2', 'DEP_VRF_L01_Admin Building A', 'p1', '0'),
            view('x', 'Loose', 'missing')]


@check
def dependents_nested():
    u"""Dependents sit straight under their parent, nested, whatever the
    sort parameter says; a parent is flagged; search keeps the parent."""
    import pbp_tree as t
    leaves = _dependents()
    for org in ({'source': 'revit'},
                {'source': 'custom', 'levels': ['Disc'], 'sort': 'S', 'desc': False},
                {'source': 'none', 'levels': [], 'sort': 'S', 'desc': True}):
        root = t.build_tab('views', leaves, org)
        rows = [r for r in t.flatten([root], set(), [], False) if not r.heading]
        texts = [r.text for r in rows]
        i = texts.index('VRF_L00')
        assert texts[i + 1:i + 3] == ['DEP_VRF_L00_Admin Building A', 'DEP_VRF_L00_Admin Building B'], (org, texts)
        j = texts.index('VRF_L01')
        assert texts[j + 1] == 'DEP_VRF_L01_Admin Building A', (org, texts)
        flags = dict((r.text, (r.is_parent, r.nested)) for r in rows)
        assert flags['VRF_L00'] == (True, False) and flags['DEP_VRF_L00_Admin Building A'] == (False, True)
        assert flags['Loose'] == (False, False), 'a dependent whose parent is elsewhere stays loose'
        assert root.count == 6, root.count
    root = t.build_tab('views', leaves, {'source': 'revit'})
    # 'admin' is only in the dependent's name: its parent comes along for context
    rows = t.flatten([root], set(), ['admin', 'l01'], False)
    texts = [r.text for r in rows if not r.heading]
    assert texts == ['VRF_L01', 'DEP_VRF_L01_Admin Building A'], texts
    assert [r.nested for r in rows if not r.heading] == [False, True]
    under = [l.key for l in t.leaves_under(root)]
    assert set(under) == set(['p0', 'p1', 'd0', 'd1', 'd2', 'x']), under
    root = t.build_tab('views', leaves, {'source': 'revit'})
    assert len(leaves[0].children) == 2, 'rebuilding must not double the children'


@check
def dependents_drawn():
    u"""Parent bold, no fill of its own; dependent a small step right."""
    control = browser()
    snap = snapshot_for_tests()
    snap.tabs['views'] = _dependents()
    control._on_snapshot(snap, False)
    control.tab = 'views'
    control.colour = True
    control._expand_all()
    rows = dict((r.text, r) for r in control.rows)
    parent = cells(control, rows['VRF_L00'])
    child = cells(control, rows['DEP_VRF_L00_Admin Building A'])
    plain = cells(control, rows['Loose'])
    import pbp_browser, pbp_palette
    assert parent['weight'] == 'Bold' and child['weight'] == 'Normal' and plain['weight'] == 'Normal'
    assert parent['fill'] == pbp_palette.TRANSPARENT, 'the parent gets no fill of its own'
    assert parent['pillvis'] == 'Collapsed' and child['pillvis'] == 'Collapsed'
    assert child['pad'] - parent['pad'] == pbp_browser.NEST_INDENT, (parent['pad'], child['pad'])


@check
def dark_matches_revit():
    u"""The dark palette is Revit's own dark theme, as measured from its
    Properties palette - not the RevoBIM near-black."""
    import pbp_palette as p
    revit = {'BgBrush': '#3B4453', 'FieldBrush': '#3B4453', 'BarBrush': '#222933',
             'BottomBrush': '#2E3440', 'EdgeBrush': '#444E5E', 'ChromeEdgeBrush': '#515C6B',
             'SelectBrush': '#3A7392'}
    for key, value in revit.items():
        assert p.DARK[key] == value, (key, p.DARK[key], value)
    assert 'BottomBrush' in p.LIGHT


@check
def stale_panes_noticed():
    u"""After an update without a Revit restart, the button says so."""
    stubbed()
    import pbp_store
    data = fake_domain(pbp_store)
    import pbp_dock
    assert pbp_dock.stale_note('1.0.8') == '', 'no panes registered: nothing to say'
    data[pbp_dock.VERSION_KEY] = '1.0.8'
    assert pbp_dock.stale_note('1.0.8') == ''
    data[pbp_dock.VERSION_KEY] = '1.0.1'
    note = pbp_dock.stale_note('1.0.8')
    assert 'v1.0.1' in note and 'v1.0.8' in note and 'Close Revit' in note, note


@check
def open_order():
    import pbp_tree as t
    leaves = [_leaf('1', 'schedules', 'Z sched', kind='schedule'),
              _leaf('2', 'sheets', 'M-10 - X', number='M-10', kind='sheet'),
              _leaf('3', 'views', 'b view'), _leaf('4', 'sheets', 'M-2 - Y', number='M-2', kind='sheet'),
              _leaf('5', 'panels', 'DB1', kind='panel'), _leaf('6', 'views', 'A view'),
              _leaf('7', 'families', 'Type', kind='type')]
    got = [l.key for l in t.open_order(leaves)]
    assert got == ['6', '3', '4', '2', '1', '5'], got


@check
def settings_defaults_and_damage():
    import pbp_settings as s
    folder = tempfile.mkdtemp()
    data = s.load(folder)
    assert data['theme'] == 'follow' and data['debug'] == '1' and data['colour'] == 'colour'
    assert data['highlight_dark_text'] == '#FFFFFF' and data['highlight_bold'] == '1', \
        'dark highlights: white bold text by default'
    with open(s.settings_path(folder), 'w') as handle:
        handle.write('theme=purple\nzoom=9\nno equals here\nlast_tab=views\ncolour=0\n'
                     'highlight_dark=yellow\n')
    data = s.load(folder)
    assert data['theme'] == 'follow', data
    assert float(data['zoom']) == 2.0, data
    assert data['last_tab'] == 'views' and data['colour'] == 'grey', '1.4\'s colour off reads as greyscale'
    assert data['highlight_dark'] == '#8A7420', 'a colour that is not #RRGGBB: the default'
    assert [s.colour_mode(v) for v in ('1', '0', 'custom', 'nonsense')] == ['colour', 'grey', 'custom', 'colour']
    assert [s.next_colour_mode(m) for m in s.COLOUR_MODES] == ['grey', 'custom', 'colour']
    data['theme'] = 'light'
    assert s.save(folder, data)
    assert s.load(folder)['theme'] == 'light'


@check
def settings_migrations_run():
    import pbp_settings as s
    folder = tempfile.mkdtemp()
    with open(s.settings_path(folder), 'w') as handle:
        handle.write('settings_version=0\ncolour=1\n')
    seen = []
    s.MIGRATIONS[1] = lambda pairs: (seen.append(1), pairs.__setitem__('zoom', '1.5'))
    try:
        data = s.load(folder)
    finally:
        del s.MIGRATIONS[1]
    assert seen == [1] and data['zoom'] == '1.5', data


@check
def orgs_round_trip():
    import pbp_settings as s
    names = ['A|B', 'C\\D', 'plain', 'E\\pF']
    assert s.unescape_list(s.escape_list(names)) == names, s.unescape_list(s.escape_list(names))
    org = s.normalise_org({'source': 'custom', 'levels': ['x', 'x', '1', '2', '3', '4', '5', '6', '7'],
                           'sort': ' N ', 'desc': '1'}, 'views')
    assert org['levels'] == ['x', '1', '2', '3', '4', '5'], org
    assert org['sort'] == 'N' and org['desc'] is True
    assert s.normalise_org({'source': 'bogus'}, 'panels')['source'] == 'none'
    folder = tempfile.mkdtemp()
    orgs = s.default_orgs()
    orgs['sheets'] = {'source': 'custom', 'levels': ['BGL_Sheet Discipline', 'A|B'], 'sort': 'Sheet Number', 'desc': False}
    assert s.save_orgs(folder, 'Job: 45306/WLS', orgs)
    assert os.path.isfile(s.orgs_path(folder, 'Job: 45306/WLS'))
    back = s.load_orgs(folder, 'Job: 45306/WLS')
    assert back['sheets']['levels'] == ['BGL_Sheet Discipline', 'A|B'], back['sheets']
    assert back['views']['source'] == 'revit'
    assert s.load_orgs(folder, 'Other')['sheets']['source'] == 'revit'
    assert 'sorted by' in s.describe_org(back['sheets']) and 'Revit' in s.describe_org(back['views'], 'Discipline')


@check
def handoff_round_trip():
    import pbp_handoff as h
    folder = tempfile.mkdtemp()
    token = h.write_request(folder, 'express', 'Proj', [('uid-1', 'M-01'), ('uid|2', 'M-02')], now=1000.0)
    assert h.poll(folder, token) is None
    assert h.take(folder, 'Other proj', now=1001.0) is None
    got = h.take(folder, 'Proj', now=1001.0)
    assert got['request'] == 'express' and got['sheet_uids'] == ['uid-1', 'uid|2'], got
    assert h.poll(folder, token)['status'] == 'started'
    assert h.take(folder, 'Proj', now=1002.0) is None, 'a request must be taken once'
    h.finish(folder, token, True, 'C:\\Out', 2, 'ok')
    answer = h.poll(folder, token)
    assert answer['status'] == 'done' and answer['folder'] == 'C:\\Out' and answer['files'] == '2'
    assert h.poll(folder, 'another token') is None
    token2 = h.write_request(folder, 'print', 'Proj', [('u', 'M')], now=2000.0)
    assert h.poll(folder, token) is None and h.poll(folder, token2) is None, 'old result must go'
    assert h.take(folder, 'Proj', now=2000.0 + h.MAX_AGE + 1) is None, 'stale request taken'
    token3 = h.write_request(folder, 'print', 'Proj', [('u', 'M')], now=3000.0)
    assert h.take(folder, 'Proj', now=2990.0) is None, 'request from the future taken'
    assert token3
    assert h.waiting_too_long(0.0, h.ACK_TIMEOUT + 1, None)
    assert not h.waiting_too_long(0.0, h.ACK_TIMEOUT + 1, {'status': 'started'})
    try:
        h.write_request(folder, 'fax', 'Proj', [])
        raise AssertionError('unknown kind accepted')
    except ValueError:
        pass


@check
def palettes():
    import pbp_palette as p
    assert set(p.DARK) == set(p.LIGHT)
    assert p.tint('#4FA3E3', 0x38) == '#384FA3E3'
    assert p.tint('#FF4FA3E3', 255) == '#FF4FA3E3'
    assert p.tint('bad', 10) == p.TRANSPARENT
    assert p.stable_index('g:views|Mech', 10) == p.stable_index('g:views|Mech', 10)
    assert p.stable_index('g:views|Mech', 10) == 7, p.stable_index('g:views|Mech', 10)
    assert p.group_colour('x', 'light') != p.group_colour('x', 'dark')
    assert p.kind_colour('sheet', 'dark') == '#E8912D'


TOKEN = re.compile(r'[A-Za-z]|-?\d*\.?\d+')
ARGS = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2, 'A': 7, 'Z': 0}


def path_ok(data):
    tokens = TOKEN.findall(data.replace(',', ' '))
    if tokens[:1] == ['F']:
        tokens = tokens[2:]
    if not tokens or tokens[0].upper() != 'M':
        return False
    command = None
    numbers = 0
    for tok in tokens:
        if tok.isalpha():
            if command is not None and ARGS[command.upper()] and numbers % ARGS[command.upper()]:
                return False
            if tok.upper() not in ARGS:
                return False
            command, numbers = tok, 0
        else:
            numbers += 1
    return not (ARGS[command.upper()] and numbers % ARGS[command.upper()])


@check
def icon_geometry():
    stubbed()
    import pbp_icons as i
    import pbp_theme
    datas = list(i.ICONS.values()) + [i.CHEV_RIGHT, i.CHEV_DOWN] + list(pbp_theme.GLYPHS.values())
    import pbp_browser
    datas += [pbp_browser.GLYPH_COLLAPSE, pbp_browser.GLYPH_EXPAND]
    for data in datas:
        assert path_ok(data), data
    for kind in i.TAB_ICON.values():
        assert kind in i.ICONS


# ============================================================
# the tool against stub .NET / Revit
# ============================================================

def stubbed():
    import bench_stub
    bench_stub.install()
    bench_stub.fresh()
    temp_appdata()
    return bench_stub


@check
def every_module_loads():
    stubbed()
    import importlib
    for name in sorted(os.listdir(HERE)):
        if name.startswith('pbp_') and name.endswith('.py'):
            importlib.import_module(name[:-3])


@check
def script_loads():
    import runpy
    for registered in (True, False):
        stub = stubbed()
        import Autodesk.Revit.UI as ui

        class Pane(object):
            @staticmethod
            def PaneIsRegistered(pane_id):
                return registered
        ui.DockablePane = Pane
        runpy.run_path(os.path.join(HERE, 'script.py'),
                       init_globals={'__revit__': stub.make('UIApplication')()})
        del ui.DockablePane
        error = os.path.join(os.environ['APPDATA'], 'RevoBIM', 'project_browser_pro_load_error.txt')
        assert not os.path.isfile(error), open(error).read()


@check
def revit_theme_dark_is_zero():
    stub = stubbed()
    import Autodesk.Revit.UI as ui

    class Falsy(object):
        def __init__(self, name):
            self.name = name

        def __bool__(self):
            return False

        def __str__(self):
            return self.name

    class Manager(object):
        # Revit's UI dark, its canvas light: the browser follows the UI
        CurrentTheme = Falsy('Dark')
        CurrentCanvasTheme = Falsy('Light')
    ui.UIThemeManager = Manager
    import pbp_theme
    assert pbp_theme.read_revit_theme() == 'dark', pbp_theme.read_revit_theme()
    assert pbp_theme.resolve('light') == 'light'
    assert pbp_theme.next_mode('follow') == 'dark' and pbp_theme.next_mode('light') == 'follow'
    del ui.UIThemeManager
    assert stub


@check
def theme_before_2024_is_light():
    u"""Revit 2021-2023 have no UIThemeManager: Auto must show light."""
    stubbed()
    import pbp_theme
    pbp_theme.read_revit_theme = lambda: None
    assert pbp_theme.resolve('follow') == 'light', pbp_theme.resolve('follow')
    assert pbp_theme.resolve('dark') == 'dark'


class FakeEvent(object):
    def __init__(self, answers):
        self.answers = list(answers)

    def Raise(self):
        return self.answers.pop(0) if self.answers else 'Accepted'


@check
def runner_queue():
    stubbed()
    import pbp_runner
    runner = pbp_runner.Runner()
    assert not runner.queue('x', lambda app: 1), 'queued with no event'
    runner.event = FakeEvent(['Accepted', 'Pending', 'Denied'])
    got = []
    assert runner.queue('a', lambda app: 'A', lambda r, e: got.append(r))
    assert runner.queue('b', lambda app: 'B', lambda r, e: got.append(r))
    assert not runner.queue('c', lambda app: 'C')
    assert len(runner.jobs) == 2, 'a refused job must not take the queued ones with it'
    runner.Execute(None)
    assert got == ['A', 'B'] and not runner.jobs and runner.done_count == 2
    runner.queue('boom', lambda app: 1 / 0, lambda r, e: got.append(('err', r is None, bool(e))))
    runner.Execute(None)
    assert got[-1] == ('err', True, True)
    runner.raised_at = 1.0
    assert runner.stalled(100.0) and not runner.stalled(2.0)


class FakeRunner(object):
    def __init__(self):
        self.jobs = []

    def ready(self):
        return True

    def queue(self, name, work, done=None):
        self.jobs.append((name, work, done))
        return True

    def stalled(self, now=None):
        return False

    def describe(self):
        return 'fake'


def fake_domain(store):
    data = {}
    store.domain_get = lambda key, default=None: data.get(key, default)
    store.domain_set = lambda key, value: data.__setitem__(key, value) or True
    return data


@check
def store_coalesces_reads():
    stubbed()
    import pbp_store
    fake_domain(pbp_store)
    store = pbp_store.Store()
    runner = FakeRunner()
    heard = []
    store.subscribe(lambda snap, views_only: heard.append(views_only))
    assert store.request_read(runner, 'one')
    assert store.request_read(runner, 'two')
    assert len(runner.jobs) == 1 and store.again
    import pbp_revit
    snap = pbp_revit.Snapshot()
    snap.key = 'k'
    runner.jobs[0][2](snap, None)
    assert store.snapshot is snap and heard == [False]
    assert len(runner.jobs) == 2, 'the asked-for second read did not happen'
    runner.jobs[1][2](snap, None)
    assert len(runner.jobs) == 2
    store.read_dirty = pbp_store.dirty_count()
    assert store.ensure_fresh(runner, 'x') and len(runner.jobs) == 2
    pbp_store.bump_dirty()
    store.ensure_fresh(runner, 'x')
    assert len(runner.jobs) == 3


@check
def document_changed_filter():
    stub = stubbed()
    import pbp_store
    data = fake_domain(pbp_store)
    import pbp_dock

    class Id(object):
        def __init__(self, v):
            self.Value = v

    class Ids(list):
        @property
        def Count(self):
            return len(self)

    class Doc(object):
        def __init__(self, elements):
            self.elements = elements

        def GetElement(self, eid):
            return self.elements.get(eid.Value)

    class Args(object):
        def __init__(self, added=(), modified=(), deleted=(), elements=None):
            self.a, self.m, self.d = Ids(added), Ids(modified), Ids(deleted)
            self.doc = Doc(elements or {})

        def GetDocument(self):
            return self.doc

        def GetAddedElementIds(self):
            return self.a

        def GetModifiedElementIds(self):
            return self.m

        def GetDeletedElementIds(self):
            return self.d

    import pbp_revit

    def element(cls, **attrs):
        item = cls()
        for name, value in attrs.items():
            object.__setattr__(item, name, value)
        return item
    plan = lambda kind: element(pbp_revit.View, IsTemplate=False, ViewType=kind)
    pipe = object()
    view = plan('FloorPlan')
    data[pbp_store.KNOWN_KEY] = {5: 'views', 2: 'views', 70: 'placed'}
    pbp_dock.on_document_changed(None, Args(added=[Id(1)], elements={1: pipe}))
    assert pbp_store.dirty_count() == 0, 'a pipe should not refresh the browser'
    pbp_dock.on_document_changed(None, Args(deleted=[Id(9)]))
    assert pbp_store.dirty_count() == 0, 'deleting something unknown should not refresh'
    pbp_dock.on_document_changed(None, Args(deleted=[Id(5)]))
    assert pbp_store.dirty_count() == 1, 'deleting a known view must refresh'
    assert pbp_store.section_counts()['views'] == 1 and pbp_store.section_counts()['all'] == 0, \
        'deleting a view reads the views again, not everything'
    pbp_dock.on_document_changed(None, Args(modified=[Id(2)], elements={2: view}))
    assert pbp_store.dirty_count() == 2, 'renaming a view must refresh'
    assert pbp_store.journal_since(0)[0] == set([2]), 'a modified view is looked at alone'
    assert pbp_store.section_counts()['views'] == 1, 'and its tab is not read again whole'
    assert stub


@check
def changes_noted_by_kind():
    u"""DocumentChanged notes each change by what it is - cheap, by class:
    a modified item it shows is looked at alone, an added one reads its tab,
    a viewport reads the placements, Revit's organisation reads everything,
    and anything else costs nothing."""
    stubbed()
    import pbp_store
    fake_domain(pbp_store)
    import pbp_dock, pbp_revit

    class Id(object):
        def __init__(self, v):
            self.Value = v

    class Doc(object):
        def __init__(self, elements):
            self.elements = elements

        def GetElement(self, eid):
            return self.elements.get(eid.Value)

    def element(cls, **attrs):
        item = cls()
        for name, value in attrs.items():
            object.__setattr__(item, name, value)
        return item

    class Category(object):
        CategoryType = 'Model'
    things = {
        1: element(pbp_revit.View, IsTemplate=False, ViewType='FloorPlan'),
        2: element(pbp_revit.View, IsTemplate=False, ViewType='Legend'),
        3: element(pbp_revit.ViewSheet),
        4: element(pbp_revit.View, IsTemplate=True, ViewType='FloorPlan'),
        5: element(pbp_revit.Viewport),
        6: element(pbp_revit.ViewSheetSet),
        7: element(pbp_revit.ElementType, Category=Category(), FamilyName='Elbow'),
        8: element(pbp_revit.ElementType, Category=None, FamilyName=''),
        9: element(pbp_revit.BrowserOrganization),
        10: object(),
        11: element(pbp_revit.Family),
    }
    doc = Doc(things)
    known = {1: 'views', 2: 'legends', 3: 'sheets', 7: 'families', 50: 'placed', 60: 'sets'}
    note = lambda added=(), modified=(), deleted=(), known=known: pbp_dock.note_changes(
        doc, [Id(v) for v in added], [Id(v) for v in modified], [Id(v) for v in deleted], known)
    assert note(modified=[1, 2, 3, 7]) == (set(), [1, 2, 3, 7]), 'modified known items: alone'
    assert note(modified=[10, 5, 8]) == (set(), []), 'a pipe, a moved viewport, a type not shown: nothing'
    assert note(modified=[4]) == (set(), [4]), 'a template is looked at (its name names icons)'
    sections, ids = note(modified=[1], known={})
    assert ids == [], 'a view no read has seen is not looked at alone'
    assert note(added=[1])[0] == set(['views']) and note(added=[2])[0] == set(['legends'])
    assert note(added=[3])[0] == set(['sheets']) and note(added=[5])[0] == set(['placed'])
    assert note(added=[7])[0] == set(['families']) and note(added=[8])[0] == set()
    assert note(added=[4])[0] == set(), 'a new template changes nothing until a view uses it'
    assert note(modified=[6])[0] == set(['sets']) and note(modified=[9])[0] == set(['all'])
    assert note(modified=[11])[0] == set(['families'])
    assert note(deleted=[50, 60, 99])[0] == set(['placed', 'sets'])
    assert note(deleted=[1], known=set([1]))[0] == set(['all']), 'an older copy\'s set: read everything'
    old = pbp_dock.INSPECT_LIMIT
    pbp_dock.INSPECT_LIMIT = 3
    try:
        assert 'all' in note(modified=[10, 10, 10, 10])[0], 'too many to look at: read everything'
    finally:
        pbp_dock.INSPECT_LIMIT = old


@check
def journal_keeps_each_id_once():
    stubbed()
    import pbp_store
    fake_domain(pbp_store)
    first = pbp_store.journal_add([5, 6])
    second = pbp_store.journal_add([6, 7])
    ids, complete = pbp_store.journal_since(first)
    assert ids == set([6, 7]) and complete
    assert pbp_store.journal_since(0)[0] == set([5, 6, 7])
    assert pbp_store._journal_entries().count((second, 6)) == 1 and (first, 6) not in pbp_store._journal_entries(), \
        'an id modified again is kept once, at its newest'
    assert pbp_store.dirty_count() == 2
    old = pbp_store.JOURNAL_LIMIT
    pbp_store.JOURNAL_LIMIT = 4
    try:
        seen = pbp_store.journal_seq()
        pbp_store.journal_add([1, 2, 3])
        ids, complete = pbp_store.journal_since(0)
        assert not complete, 'a reader behind what the journal kept must read everything'
        assert pbp_store.journal_since(seen) == (set([1, 2, 3]), True)
    finally:
        pbp_store.JOURNAL_LIMIT = old


def _plan_store():
    stubbed()
    import pbp_store
    fake_domain(pbp_store)
    import pbp_revit
    store = pbp_store.Store()
    runner = FakeRunner()
    store.snapshot = pbp_revit.Snapshot()
    store.read_dirty = pbp_store.dirty_count()
    return store, runner, pbp_store, pbp_revit


@check
def store_reads_only_changes():
    u"""The store reads what changed: modified ids alone, added items' tabs
    whole, everything only when it must - and nothing for nothing."""
    store, runner, pbp_store, pbp_revit = _plan_store()
    asked = []
    pbp_revit.read_changes = lambda app, previous, sections, ids, load: asked.append((sections, ids))
    assert store.refresh(runner, 'x') and not runner.jobs, 'nothing changed: nothing read'
    pbp_store.journal_add([12])
    store.refresh(runner, 'x')
    assert runner.jobs[-1][0].startswith('read changes'), runner.jobs
    runner.jobs[-1][1](None)
    assert asked[-1] == (set(), set([12]))
    store.reading = False
    pbp_store.bump_dirty('sheets')
    store.refresh(runner, 'x')
    runner.jobs[-1][1](None)
    assert asked[-1] == (set(['sheets']), set()), 'the journal entry already read is not read twice'
    store.reading = False
    pbp_store.bump_dirty()
    store.refresh(runner, 'x')
    assert runner.jobs[-1][0].startswith('read ('), 'another document reads everything'
    store.reading = False
    pbp_store.journal_add([40])
    store.request_sections(runner, ['views'], 'organisation changed')
    runner.jobs[-1][1](None)
    assert asked[-1] == (set(['views']), set([40])), 'an organisation change takes waiting changes along'
    # results
    heard = []
    store.subscribe(lambda snap, how: heard.append(how))
    before = store.snapshot
    newer = pbp_revit.Snapshot()
    store._changes_done((newer, set()), None)
    assert heard == [] and store.snapshot is before, 'nothing drawn changed: nobody redraws'
    store._changes_done((newer, set(['views'])), None)
    assert heard == [pbp_store.PATCH] and store.changed_tabs == set(['views']) and store.snapshot is newer
    store._changes_done((before, None), None)
    assert heard[-1] is False, 'a change read that read everything publishes as one'
    store._changes_done(None, 'boom')
    assert runner.jobs[-1][0].startswith('read ('), 'a failed change read falls back to reading everything'
    store.reading = False
    store.read_dirty = pbp_store.dirty_count()
    old = pbp_store.JOURNAL_LIMIT
    pbp_store.JOURNAL_LIMIT = 2
    try:
        pbp_store.journal_add([1, 2, 3, 4])
        store.refresh(runner, 'x')
        assert runner.jobs[-1][0].startswith('read ('), 'fallen behind the journal: read everything'
    finally:
        pbp_store.JOURNAL_LIMIT = old


@check
def views_publish_only_moved_dots():
    store, runner, pbp_store, pbp_revit = _plan_store()
    from pbp_tree import Leaf
    a, b = Leaf('e:1', 'views', 'plan', 'A', eid=Id(1)), Leaf('e:2', 'views', 'plan', 'B', eid=Id(2))
    store.snapshot.tabs['views'] = [a, b]
    store.snapshot.key = 'k'
    store.snapshot.open_ids = set([1])
    store.snapshot.active_id = 1
    heard = []
    store.subscribe(lambda snap, how: heard.append(how))
    store._views_done({'key': 'k', 'open': set([1]), 'active': 1}, None)
    assert heard == [], 'the same views open: nothing to tell'
    store._views_done({'key': 'k', 'open': set([1, 2]), 'active': 2}, None)
    assert heard == [True] and store.changed_ids == set([1, 2])
    assert b.is_active and b.is_open and not a.is_active and a.is_open
    store.reading = True
    assert not store.request_views(runner), 'a view change during a read is not taken yet'
    store.reading = False
    assert store.request_views(runner) and store.request_views(runner)
    assert [job[0] for job in runner.jobs].count('open views') == 1, 'one look for every pane asking'


class Id(object):
    def __init__(self, value):
        self.Value = value
        self.IntegerValue = value

    def __eq__(self, other):
        return getattr(other, 'Value', None) == self.Value

    def __hash__(self):
        return hash(self.Value)


class _FakeView(object):
    IsTemplate = False

    def __init__(self, value, name, kind='FloorPlan', primary=-1, template=-1, scale=100):
        self.Id = Id(value)
        self.Name = name
        self.ViewType = kind
        self.UniqueId = 'uid%d' % value
        self.ViewTemplateId = Id(template)
        self.primary = primary
        self.Scale = scale
        self.Parameters = []

    def GetPrimaryViewId(self):
        return Id(self.primary)

    def GetTypeId(self):
        return Id(-1)

    def LookupParameter(self, name):
        return None


class _FakeSheet(_FakeView):
    IsPlaceholder = False

    def __init__(self, value, number, name):
        _FakeView.__init__(self, value, name, 'DrawingSheet')
        self.SheetNumber = number


class _FakeDoc(object):
    def __init__(self, elements, key='C:/bench.rvt'):
        self.elements = elements
        self.PathName = key
        self.Title = 'bench'

    def GetElement(self, eid):
        return self.elements.get(getattr(eid, 'Value', eid))


class _FakeUIDoc(object):
    def __init__(self, doc):
        self.Document = doc
        self.ActiveView = doc.elements[1]

    def GetOpenUIViews(self):
        return []


class _FakeApp(object):
    def __init__(self, doc):
        self.ActiveUIDocument = _FakeUIDoc(doc)


def _fake_model():
    u"""pbp_revit pointed at a small fake model: views (one a dependent),
    a legend, two sheets; returns (pbp_revit, doc, app, collected)."""
    stubbed()
    import pbp_revit
    views = [_FakeView(1, 'L1 Power'), _FakeView(2, 'L1 Power - A', primary=1),
             _FakeView(3, 'Key', 'Legend'), _FakeView(4, 'L2 Heating', template=90)]
    sheets = [_FakeSheet(10, 'E-01', 'Power'), _FakeSheet(11, 'M-01', 'Heating')]
    template = _FakeView(90, 'Mechanical Plan')
    template.IsTemplate = True
    doc = _FakeDoc(dict([(v.Id.Value, v) for v in views + sheets] + [(90, template)]))
    collected = []

    def collect(doc, cls):
        collected.append(cls.__name__)
        if cls is pbp_revit.ViewSheet:
            return list(sheets)
        if cls is pbp_revit.View:
            return list(views)
        return []
    pbp_revit._collect = collect
    pbp_revit.folders_of = lambda org, element: []
    pbp_revit.revit_org = lambda doc, tab: None
    pbp_revit.is_tab_view = lambda view, tab: (
        not isinstance(view, _FakeSheet) and ((view.ViewType == 'Legend') == (tab == 'legends')))
    pbp_revit.read_placed = lambda doc, snap: (setattr(snap, 'placed', {1: ['E-01']}),
                                               setattr(snap, 'by_sheet', {10: [1]}),
                                               setattr(snap, 'placement_ids', set([500])))
    load = lambda title: __import__('pbp_settings').default_orgs()
    app = _FakeApp(doc)
    return pbp_revit, doc, app, collected, load, views, sheets


@check
def read_changes_reads_alone():
    u"""After a change only the changed element is read again - and if its
    row would draw the same (a scale, a detail level) nothing is redrawn."""
    pbp_revit, doc, app, collected, load, views, sheets = _fake_model()
    first = pbp_revit.read_snapshot(app, load)
    assert sorted(l.text for l in first.tabs['views']) == ['L1 Power', 'L1 Power - A', 'L2 Heating']
    assert first.known_ids[1] == 'views' and first.known_ids[10] == 'sheets' and first.known_ids[500] == 'placed'
    assert first.templates == {90: 'Mechanical Plan'}
    dependent = [l for l in first.tabs['views'] if l.text == 'L1 Power - A'][0]
    assert dependent.kind == 'dependent' and dependent.parent == 'e:1'
    assert set(first.timings) >= set(['views', 'sheets', 'families', 'placed']), first.timings
    # a scale change: looked at, nothing drawn changes
    views[0].Scale = 50
    del collected[:]
    snap, tabs = pbp_revit.read_changes(app, first, set(), set([1]), load)
    assert tabs == set(), tabs
    assert collected == [], 'one view changed: nothing collected'
    assert snap.tabs['views'] == first.tabs['views'] and all(
        a is b for a, b in zip(snap.tabs['views'], first.tabs['views'])), 'the same leaves are kept'
    # a rename: that tab alone changes, the rest are the very same leaves
    views[0].Name = 'L1 Power Plan'
    snap, tabs = pbp_revit.read_changes(app, first, set(), set([1]), load)
    assert tabs == set(['views']), tabs
    renamed = [l for l in snap.tabs['views'] if l.key == 'e:1'][0]
    assert renamed.text == 'L1 Power Plan' and renamed.sheets == [s for s in snap.tabs['sheets'] if s.key == 'e:10']
    assert snap.tabs['sheets'][0].placed[0] is renamed, 'the sheet opens to the renamed leaf'
    dependent = [l for l in snap.tabs['views'] if l.key == 'e:2'][0]
    assert dependent.sort_text.startswith('L1 Power Plan'), 'a dependent follows its primary'
    assert all(a is b for a, b in zip(snap.tabs['legends'], first.tabs['legends']))
    assert collected == []
    # a template renamed: every view using it may draw differently
    doc.elements[90].Name = 'Mechanical Plans'
    snap, tabs = pbp_revit.read_changes(app, first, set(), set([90]), load)
    assert 'View' in collected, 'a renamed template reads the views again'
    assert [l.template for l in snap.tabs['views'] if l.key == 'e:4'] == ['Mechanical Plans']
    assert snap.templates[90] == 'Mechanical Plans', 'the new name is remembered'
    assert pbp_revit.read_changes(app, snap, set(), set([90]), load)[1] == set(), \
        'a template edited, not renamed: nothing'
    # a sheet renumbered: the placements name sheets by number
    sheets[0].SheetNumber = 'E-02'
    snap, tabs = pbp_revit.read_changes(app, first, set(), set([10]), load)
    assert 'sheets' in tabs and 'placed' in snap.timings
    # added: that tab alone, whole
    del collected[:]
    snap, tabs = pbp_revit.read_changes(app, first, set(['sheets']), set(), load)
    assert collected == ['ViewSheet'], collected
    # another document: everything
    snap, tabs = pbp_revit.read_changes(_FakeApp(_FakeDoc(doc.elements, 'C:/other.rvt')), first,
                                        set(), set([1]), load)
    assert tabs is None and snap.key == 'C:/other.rvt'


@check
def browser_redraws_only_what_changed():
    u"""A dot moving redraws that row; a tab this browser does not show
    changing redraws nothing; a hidden browser draws once, when shown."""
    control = browser()
    snap = sheets_snapshot()
    for index, leaf in enumerate(snap.tabs['views']):
        leaf.eid = Id(100 + index)
    feed(control, snap)
    control.tab = 'views'
    control._render()
    renders = []
    real = control._render
    control._render = lambda: (renders.append(1), real())
    first = snap.tabs['views'][0]
    first.is_open = True
    control.store.changed_ids = set([100])
    control._on_snapshot(snap, True)
    assert renders == [], 'a view opened: no redraw of everything'
    row = [i for i, r in enumerate(control.rows) if r.leaf is first][0]
    assert control.shown[row][control_columns().index('dot')] == 'Visible'
    control.store.changed_tabs = set(['families'])
    control._on_snapshot(snap, __import__('pbp_store').PATCH)
    assert renders == [], 'families changed: the Views tab does not redraw'
    first.text = 'Renamed'
    control.store.changed_tabs = set(['views'])
    control._on_snapshot(snap, __import__('pbp_store').PATCH)
    assert len(renders) == 1 and 'redrawn' in control.last_fill, control.last_fill
    control.tab = 'sheets'
    control._render()
    del renders[:]
    control._on_snapshot(snap, __import__('pbp_store').PATCH)
    assert renders == [1], 'a sheet opens to its views: the Sheets tab redraws for a view'
    control.root.IsVisible = False
    control._on_snapshot(snap, False)
    control._on_snapshot(snap, __import__('pbp_store').PATCH)
    assert renders == [1] and control.stale, 'hidden: nothing drawn'
    control.root.IsVisible = True
    control._visible_changed(None, None)
    assert renders == [1, 1] and not control.stale, 'shown again: drawn once'
    import pbp_store
    control.store.read_dirty = pbp_store.dirty_count()
    control.store.reading = True
    pbp_store.bump_views()
    control._tick(None, None)
    assert control.last_views != pbp_store.views_count(), 'a view closed during a read is kept for after it'
    control.store.reading = False
    control._tick(None, None)
    assert control.last_views == pbp_store.views_count()


def control_columns():
    import pbp_browser
    return list(pbp_browser.COLUMNS)


@check
def fill_table_sets_only_differing_cells():
    control = browser()
    feed(control, sheets_snapshot())
    control.tab = 'views'
    control._render()
    assert 'loaded' in control.last_fill
    sets = []

    class Row(object):
        def __setitem__(self, key, value):
            sets.append(key)

    class Rows(object):
        def __getitem__(self, index):
            return Row()

        def Clear(self):
            sets.append('clear')

        def Add(self, *cells):
            pass
    control.table.Rows = Rows()
    shown = list(control.shown)
    changed = list(shown[1])
    changed[control_columns().index('dot')] = 'Visible'
    assert control._fill_table(shown[:1] + [tuple(changed)] + shown[2:]) == 1
    assert sets == ['dot'], sets
    assert control._fill_table(shown[1:]) == len(shown) - 1, 'different rows load afresh'


def snapshot_for_tests():
    import pbp_revit
    from pbp_tree import Leaf
    snap = pbp_revit.Snapshot()
    snap.title = 'Bench Project'
    snap.key = 'C:/bench.rvt'
    snap.orgs = __import__('pbp_settings').default_orgs()
    snap.tabs['views'] = [Leaf('e:1', 'views', 'plan', 'Level 1', folders=['Mech', 'Floor Plans'], uid='u1'),
                          Leaf('e:2', 'views', 'section', 'Section A', folders=['Mech', 'Sections'], uid='u2')]
    snap.tabs['sheets'] = [Leaf('e:3', 'sheets', 'sheet', 'M-01 - Plan', number='M-01', folders=['M'], uid='u3'),
                           Leaf('e:4', 'sheets', 'sheet', 'M-02 - Plan', number='M-02', folders=['M'], uid='u4')]
    snap.tabs['schedules'] = [Leaf('e:5', 'schedules', 'schedule', 'Pipe Schedule', uid='u5')]
    snap.tabs['panels'] = [Leaf('e:6', 'panels', 'panel', 'DB-L1', uid='u6')]
    snap.tabs['families'] = [Leaf('e:7', 'families', 'type', '15mm',
                                  values={'Main Group': 'Mechanical & Plumbing',
                                          'Category': 'Pipe Fittings', 'Family': 'Elbow'}, uid='u7')]
    snap.tabs['views'][0].is_open = True
    snap.tabs['views'][0].is_active = True
    snap.catalogues['views'] = ['Name', 'View Type', 'BGL_Sub Discipline']
    return snap


def cells(control, row):
    u"""A row's cells by column name - the tests never count positions."""
    import pbp_browser
    return dict(zip(pbp_browser.COLUMNS, control._cells(row)))


def menu_headers(control, opener):
    u"""The menu item labels an opener adds, in order."""
    seen = []
    real = control._item

    def record(menu, header, handler, enabled=True, gesture='', icon=None):
        seen.append((header, handler, enabled))
        return real(menu, header, handler, enabled, gesture, icon)
    control._item = record
    try:
        opener()
    finally:
        control._item = real
    return seen


def browser(tab=None, host='pane'):
    stubbed()
    import pbp_store
    fake_domain(pbp_store)
    import pbp_browser
    # the checks below were written for folders that start open (the
    # setting 'start_open'); folders_start_closed checks the default. Saved,
    # so every browser a check builds in this engine starts the same way.
    import pbp_settings, pbp_log
    settings = pbp_settings.load(pbp_log.appdata_folder())
    settings['start_open'] = '1'
    pbp_settings.save(pbp_log.appdata_folder(), settings)
    control = pbp_browser.BrowserControl(host, tab)
    control.runner = FakeRunner()
    return control


@check
def browser_builds_and_renders():
    control = browser()
    control.tab = 'all'
    control._on_snapshot(snapshot_for_tests(), False)
    texts = [r.text for r in control.rows]
    assert texts[:1] == ['Views'] and 'Sheets' in texts, texts
    control.tab = 'views'
    control._render()
    full = ['Mech', 'Floor Plans', 'Level 1', 'Sections', 'Section A']
    assert [r.text for r in control.rows] == full, 'every tab opens expanded: %r' % [r.text for r in control.rows]
    control._collapse_toggle(None, None)
    assert [r.text for r in control.rows] == ['Mech']
    control._collapse_toggle(None, None)
    assert [r.text for r in control.rows] == full
    control.tab = 'families'
    control._render()
    assert [r.text for r in control.rows] == ['Mechanical & Plumbing', 'Pipe Fittings', 'Elbow', '15mm'], \
        [r.text for r in control.rows]


@check
def browser_cells():
    control = browser()
    control._on_snapshot(snapshot_for_tests(), False)
    control.tab = 'views'
    control._expand_all()
    rows = dict((r.text, r) for r in control.rows)
    control.colour = True
    import pbp_browser, pbp_palette
    raw = control._cells(rows['Mech'])
    assert len(raw) == len(pbp_browser.COLUMNS) == len(control._cells(rows['Level 1']))
    heading = cells(control, rows['Mech'])
    leaf = cells(control, rows['Level 1'])
    assert isinstance(heading['pad'], float) and isinstance(heading['rowh'], float)
    assert heading['chevvis'] == 'Visible' and leaf['chevvis'] == 'Hidden'
    assert heading['fill'].startswith('#') and len(heading['fill']) == 7, heading['fill']
    assert heading['pillvis'] == 'Visible' and heading['rowh'] == pbp_browser.HEAD_HEIGHTS[1]
    assert heading['fore'] == pbp_palette.text_on(heading['fill']) == heading['chevfill']
    assert leaf['fill'] == pbp_palette.TRANSPARENT and leaf['pillvis'] == 'Collapsed', \
        'colour is on headings only - never on a view'
    assert leaf['rowh'] == pbp_browser.ROW_HEIGHT
    assert leaf['weight'] == 'Normal', 'the active view is no longer marked bold - parents are'
    assert leaf['dot'] == 'Visible'
    assert leaf['dotfill'] == pbp_palette.palette(control.theme_name)['OrangeBrush']
    assert leaf['dottip'] == 'Active view'
    control.colour = False
    off = cells(control, rows['Mech'])
    assert off['pillvis'] == 'Visible' and off['fill'] == pbp_palette.grey_pill(1, control.theme_name)[0], \
        'colour off: the bar stays, grey'
    assert off['rowh'] == pbp_browser.HEAD_HEIGHTS[1] and off['size'] == pbp_browser.HEAD_SIZES[1], \
        'a main heading stands out with the colour off too'
    assert off['fore'] == pbp_palette.palette(control.theme_name)['TextBrush']


@check
def browser_print_buttons():
    control = browser()
    control._on_snapshot(snapshot_for_tests(), False)
    control.tab = 'sheets'
    control._expand_all()
    sheet_rows = [r for r in control.rows if r.leaf is not None]
    import pbp_browser
    shown, hidden = pbp_browser.Visibility.Visible, pbp_browser.Visibility.Collapsed
    control._selected_rows = lambda: []
    control._update_toolbar()
    assert control.print_bar.Visibility is hidden, 'no sheets selected: no print bar'
    assert control.print_button.IsEnabled is False and control.express_button.IsEnabled is False
    control._selected_rows = lambda: sheet_rows
    control._update_toolbar()
    assert control.print_bar.Visibility is shown and control.print_bar_text.Text == '2 sheets'
    assert control.print_button.IsEnabled is True and control.express_button.IsEnabled is True
    control.tab = 'all'
    control._update_toolbar()
    assert control.print_bar.Visibility is shown, 'sheets selected on any tab'
    control._selected_rows = lambda: [r for r in control.rows if r.leaf is not None and r.leaf.tab == 'views']
    control._update_toolbar()
    assert control.print_bar.Visibility is hidden, 'views selected: no print bar'
    import xml.etree.ElementTree as ET
    root = ET.parse(os.path.join(HERE, 'Browser.xaml')).getroot()
    xname = '{http://schemas.microsoft.com/winfx/2006/xaml}Name'
    bar = [e for e in root.iter() if e.attrib.get(xname) == 'PrintBar'][0]
    names = [e.attrib.get(xname) for e in bar.iter() if e.attrib.get(xname)]
    assert 'PrintButton' in names and 'ExpressButton' in names, names
    toolbar = [e for e in root.iter() if e.attrib.get(xname) == 'ToolBar'][0]
    assert not [e for e in toolbar.iter() if e.attrib.get(xname) in ('PrintButton', 'ExpressButton')], \
        'the buttons left the tool row'
    assert bar.attrib.get('VerticalAlignment') == 'Top' and bar.attrib.get('Visibility') == 'Collapsed'
    control._selected_rows = lambda: sheet_rows
    control._print_clicked(None, None)
    assert control.runner.jobs[-1][0] == 'prosheets print'


class FakeProgress(object):
    def __init__(self):
        self.sets = []
        self.failed = None
        self.closed = False

    def set(self, percent, detail):
        self.sets.append((percent, detail))

    def fail(self, message):
        self.failed = message

    def close(self):
        self.closed = True


def express_browser():
    control = browser()
    control._on_snapshot(snapshot_for_tests(), False)
    import pbp_ui  # after browser(): the stub reload replaces the module
    opened = []
    pbp_ui.shell_open = lambda path: opened.append(path) or True
    return control, opened


def start_express(control, token):
    control._prosheets_posted('express', 2, {'ok': True, 'token': token}, None)
    control.progress = FakeProgress()
    return control.progress


@check
def browser_express_flow():
    u"""Express: progress strip moves with Pro Sheets' reports, the folder
    opens by itself on done and the strip closes - nothing else is shown."""
    import pbp_handoff
    control, opened = express_browser()
    token = pbp_handoff.write_request(control.folder, 'express', 'Bench Project',
                                      [('u1', 'M-01'), ('u2', 'M-02')])
    progress = start_express(control, token)
    assert control.express is not None and control.express_button.IsEnabled is False
    request = pbp_handoff.take(control.folder, 'Bench Project')
    assert request['headless'] is True and request['open_folder'] is False, request
    control._poll_express()
    assert control.express['acked'] and progress.sets[-1][0] == 0
    pbp_handoff.progress(control.folder, token, 1, 2, 'M-02')
    control._poll_express()
    assert progress.sets[-1][0] == 50 and 'M-02' in progress.sets[-1][1], progress.sets[-1]
    pbp_handoff.finish(control.folder, token, True, control.folder, 2)
    control._poll_express()
    assert control.express is None and control.last_folder == control.folder
    assert opened == [control.folder], 'the export folder must open by itself: %r' % opened
    assert progress.closed and progress.failed is None
    # A partial run: the folder still opens and what did not write is said.
    token = pbp_handoff.write_request(control.folder, 'express', 'Bench Project', [('u1', 'M-01')])
    start_express(control, token)
    pbp_handoff.take(control.folder, 'Bench Project')
    pbp_handoff.finish(control.folder, token, True, control.folder, 1, '1 did not write - M-02 [PDF]: offline')
    control._poll_express()
    assert 'M-02 [PDF]: offline' in control.status.Text, control.status.Text
    assert len(opened) == 2


@check
def browser_express_failures():
    u"""Never started, failed, or stalled: the strip turns red and says why;
    no folder is opened."""
    import pbp_handoff
    control, opened = express_browser()
    progress = start_express(control, 'never-answered')
    control.express['started'] -= pbp_handoff.ACK_TIMEOUT + 5
    control._poll_express()
    assert control.express is None and 'express hook' in progress.failed, progress.failed
    token = pbp_handoff.write_request(control.folder, 'express', 'Bench Project', [('u', 'M')])
    progress = start_express(control, token)
    pbp_handoff.take(control.folder, 'Bench Project')
    pbp_handoff.finish(control.folder, token, False, message='Printer offline')
    control._poll_express()
    assert 'Printer offline' in progress.failed and not progress.closed
    token = pbp_handoff.write_request(control.folder, 'express', 'Bench Project', [('u', 'M')])
    progress = start_express(control, token)
    pbp_handoff.take(control.folder, 'Bench Project')
    pbp_handoff.progress(control.folder, token, 0, 1, 'M')
    control._poll_express()
    control.express['changed'] -= pbp_handoff.STALL_TIMEOUT + 5
    control._poll_express()
    assert progress.failed and 'stopped reporting' in progress.failed, progress.failed
    assert opened == [], opened


@check
def express_percent_and_detail():
    import pbp_handoff
    stubbed()
    import pbp_progress
    assert pbp_handoff.percent(None) == 0
    assert pbp_handoff.percent({'status': 'started', 'done': 0, 'total': 4}) == 0
    assert pbp_handoff.percent({'status': 'running', 'done': 1, 'total': 4}) == 25
    assert pbp_handoff.percent({'status': 'running', 'done': 4, 'total': 4}) == 99, 'not 100 until done'
    assert pbp_handoff.percent({'status': 'done', 'done': 4, 'total': 4}) == 100
    assert pbp_handoff.percent({'status': 'running', 'done': 1, 'total': 0}) == 0
    assert pbp_progress.bar_lengths(130) == (100.0, 0.0) and pbp_progress.bar_lengths('x') == (0.0, 100.0)
    line = pbp_progress.detail_for({'status': 'running', 'done': 2, 'total': 5, 'current': 'M-03'}, 5)
    assert line.startswith('2 of 5') and 'M-03' in line, line
    win = pbp_progress.ExpressProgress(3, 'dark')
    win.set(40, 'x')
    win.fail('nope')


@check
def express_button_look():
    u"""Print icon left of the word Express; orange outline style."""
    import xml.etree.ElementTree as ET
    root = ET.parse(os.path.join(HERE, 'Browser.xaml')).getroot()
    xname = '{http://schemas.microsoft.com/winfx/2006/xaml}Name'
    button = [e for e in root.iter() if e.attrib.get(xname) == 'ExpressButton'][0]
    assert button.attrib['Style'] == '{DynamicResource ExpressButton}', button.attrib['Style']
    panel = [c for c in button][0]
    kinds = [c.tag.split('}')[-1] for c in panel]
    assert kinds == ['Path', 'TextBlock'], kinds
    assert 'M3.5,4.5 L3.5,1' in [c for c in panel][0].attrib['Data'], 'the icon must be the printer'
    assert [c for c in panel][1].attrib['Text'] == 'Express'
    theme = ET.parse(os.path.join(HERE, 'Theme.xaml')).getroot()
    xkey = '{http://schemas.microsoft.com/winfx/2006/xaml}Key'
    style = [e for e in theme.iter() if e.attrib.get(xkey) == 'ExpressButton'][0]
    setters = dict((e.attrib['Property'], e.attrib.get('Value')) for e in style
                   if e.tag.endswith('Setter') and 'Value' in e.attrib)
    assert setters['BorderBrush'] == '{DynamicResource OrangeBrush}', setters
    assert setters['Background'] == 'Transparent'


@check
def browser_zoom_theme_menus():
    control = browser()
    control._on_snapshot(snapshot_for_tests(), False)
    control._apply_zoom(5)
    assert control.zoom == 2.0 and control.zoom_text.Text == '200%'
    control._apply_zoom(0.1)
    assert control.zoom == 0.6
    import pbp_settings
    assert pbp_settings.load(control.folder)['zoom'] == '0.6'
    mode = control.theme_mode
    control._cycle_theme(None, None)
    assert control.theme_mode != mode
    control._colour_toggle(None, None)
    control.tab = 'views'
    control._expand_all()
    control._selected_rows = lambda: [r for r in control.rows if r.leaf is not None]
    control._list_menu_opening(None, None)
    control._tab_menu_opener('sheets')(None, None)
    lines = control.report_lines()
    assert any('organisation views' in line for line in lines), lines
    import pbp_log
    assert 'debug report' in pbp_log.report(lines)


@check
def tab_strip_order_and_labels():
    u"""Icon-only tabs along the top - All, Views, Sheets, Schedules, Panel
    schedules, Families - in that order, matching TABS in the code, each a
    22px icon in a colour of its own, named in its tooltip."""
    import xml.etree.ElementTree as ET
    stubbed()
    import pbp_browser
    import pbp_icons
    root = ET.parse(os.path.join(HERE, 'Browser.xaml')).getroot()
    xname = '{http://schemas.microsoft.com/winfx/2006/xaml}Name'
    strip = [e for e in root.iter() if e.attrib.get(xname) == 'TabStrip'][0]
    assert strip.tag.endswith('UniformGrid') and strip.attrib.get('Rows') == '1', strip.tag
    buttons = [e for e in strip if e.tag.endswith('RadioButton')]
    names = [b.attrib[xname] for b in buttons]
    assert names == [t[1] for t in pbp_browser.TABS], (names, [t[1] for t in pbp_browser.TABS])
    assert names == ['TabAll', 'TabFavourites', 'TabViews', 'TabLegends', 'TabSheets', 'TabSchedules',
                     'TabPanels', 'TabFamilies'], names
    fills = []
    for b in buttons:
        assert b.attrib.get('Style') == '{DynamicResource IconTab}', b.attrib.get('Style')
        assert not [t for t in b.iter() if t.tag.endswith('TextBlock')], 'tabs are icons only - no words'
        assert b.attrib.get('ToolTip'), 'an icon-only tab needs its name in the tooltip'
        boxes = [v for v in b.iter() if v.tag.endswith('Viewbox')]
        assert boxes and boxes[0].attrib['Width'] == '22', 'tab icon must be 22px'
        fills.append([p.attrib['Fill'] for p in b.iter() if p.tag.endswith('Path')][0])
    assert len(set(fills)) == len(fills), 'every type needs its own colour: ' + repr(fills)
    for tab in ('all', 'favourites', 'views', 'legends', 'sheets', 'schedules', 'panels', 'families',
                'pin'):
        assert tab in pbp_icons.TAB_GLYPHS, tab
        assert path_ok(pbp_icons.tab_glyph(tab)), tab
    import pbp_tree
    assert pbp_tree.TAB_ORDER == ('views', 'legends', 'sheets', 'schedules', 'panels', 'families')


@check
def bar_folds():
    control = browser()
    assert control.bar_open is True
    control._bar_clicked(None, None)
    assert control.bar_open is False
    import pbp_settings
    assert pbp_settings.load(control.folder)['bar'] == '0'
    from System.Windows import Visibility
    assert control.top_bar.Visibility == Visibility.Collapsed, 'pane: the whole top bar folds'
    assert control.footer.Visibility == Visibility.Collapsed, 'the footer folds with it'
    control._bar_clicked(None, None)
    assert control.top_bar.Visibility == Visibility.Visible and control.tool_bar.Visibility == Visibility.Visible
    assert control.footer.Visibility == Visibility.Visible
    window = browser(host='window')
    window.bar_open = False
    window._apply_bar()
    assert window.top_bar.Visibility == Visibility.Visible, 'a floating window keeps its close button'
    assert window.tool_bar.Visibility == Visibility.Collapsed
    assert window.footer.Visibility == Visibility.Collapsed, 'in a window too'


@check
def tab_counts_shown():
    control = browser()
    control._on_snapshot(snapshot_for_tests(), False)
    assert control.tab_buttons['sheets'].ToolTip.startswith('Sheets: 2'), control.tab_buttons['sheets'].ToolTip
    assert control.tab_buttons['all'].ToolTip.startswith('Everything: 7'), control.tab_buttons['all'].ToolTip
    control.tab = 'sheets'
    control._render()
    assert control.org_text.Text.startswith('2 items'), control.org_text.Text


@check
def fixed_tab_browser():
    control = browser('sheets')
    control._on_snapshot(snapshot_for_tests(), False)
    assert control.tab == 'sheets'
    control._tab_checker('views')(None, None)
    assert control.tab == 'sheets', 'a pane fixed to one tab must stay on it'


@check
def organisation_dialog():
    stubbed()
    import pbp_orgwin
    import pbp_settings
    win = pbp_orgwin.OrganisationWindow('views', pbp_settings.DEFAULT_ORGS['views'],
                                        ['Name', 'A', 'B', 'C', 'D', 'E', 'F', 'G'], 'Discipline', 'dark')
    for name in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'A']:
        win._picked = (lambda n: (lambda: n))(name)
        win._add(None, None)
    assert win.org['source'] == 'custom' and win.org['levels'] == ['A', 'B', 'C', 'D', 'E', 'F'], win.org
    win._picked = lambda: 'Name'
    win._sort_by(None, None)
    win._toggle_dir(None, None)
    win._apply(None, None)
    assert win.result == {'source': 'custom', 'levels': ['A', 'B', 'C', 'D', 'E', 'F'],
                          'sort': 'Name', 'desc': True, 'colours': [1, 2], 'group_colours': {}}, win.result
    win._reset(None, None)
    assert win.org['source'] == 'revit'
    assert win.sort_box.Opacity == 0.45, 'sort box must fade with the disabled panel'
    win.source_custom.IsChecked = True
    win.source_revit.IsChecked = False
    win._source(None, None)
    assert win.sort_box.Opacity == 1.0


@check
def organisation_revit_prefill_and_colours():
    u"""Leaving Revit's organisation for parameters starts from Revit's own
    grouping and sort; the coloured levels are ticked, saved and read back."""
    stubbed()
    import pbp_orgwin
    import pbp_settings
    win = pbp_orgwin.OrganisationWindow('views', pbp_settings.DEFAULT_ORGS['views'], ['Name', 'X'],
                                        'BGL', 'dark', ['BGL_View Group', 'BGL_View Purpose', 'View Type'],
                                        'BGL_Sort')
    assert win.org['source'] == 'revit'
    win.source_custom.IsChecked = True
    win.source_revit.IsChecked = False
    win._source(None, None)
    assert win.org['levels'] == ['BGL_View Group', 'BGL_View Purpose', 'View Type'], win.org
    assert win.org['sort'] == 'BGL_Sort'
    for level, tick in enumerate(win.colour_ticks, 1):
        tick.IsChecked = level in (1, 3)
    win._colours_changed(None, None)
    win._apply(None, None)
    assert win.result['colours'] == [1, 3]
    folder = tempfile.mkdtemp()
    orgs = pbp_settings.default_orgs()
    orgs['views'] = win.result
    orgs['sheets']['colours'] = []
    assert pbp_settings.save_orgs(folder, 'P', orgs)
    back = pbp_settings.load_orgs(folder, 'P')
    assert back['views']['colours'] == [1, 3] and back['sheets']['colours'] == [], back
    assert back['schedules']['colours'] == [1, 2], 'unset: the default two levels'
    assert pbp_settings.parse_colours('2, 9, x, 2') == [2]
    other = pbp_orgwin.OrganisationWindow('views', pbp_settings.DEFAULT_ORGS['views'], ['Name'], 'BGL', 'dark')
    other.source_custom.IsChecked = True
    other.source_revit.IsChecked = False
    other._source(None, None)
    assert other.org['levels'] == [], 'nothing known from Revit: nothing filled'


# ============================================================
# runner
# ============================================================

# ============================================================
# 1.1.0: disciplines, marks, favourites, sheet sets, panel groups, pills
# ============================================================
DISCIPLINE_CASES = [
    # folder headings
    ('PIPEWORK', 'pipework'), ('Mechanical Pipework', 'pipework'), ('DUCTWORK', 'ductwork'),
    ('MECHANICAL', 'mechanical'), ('PUBLIC HEALTH', 'plumbing'), ('Plumbing Fixtures', 'plumbing'),
    ('Lighting', 'lighting'), ('Lighting Fixtures', 'lighting'), ('Data Devices', 'comms'),
    ('Communication Devices', 'comms'), ('AVAILABLE', None), ('MECH', 'mechanical'),
    ('VENTILATION', 'ductwork'), ('ELECTRICAL CONTAINMENT', 'containment'),
    ('Cable Tray', 'containment'), ('ELECTRICAL POWER', 'power'), ('Small Power', 'power'),
    ('LV Distribution', 'power'), ('ELECTRICAL', 'power'),
    # view template names
    ('BGL_E_Power', 'power'), ('BGL_E_Security & Fire Alarm', 'security'),
    ('Fire Alarm Plans', 'security'), ('BGL_P_Fire Protection', 'fire'), ('Sprinklers', 'fire'),
    ('BGL_M_Ductwork', 'ductwork'), ('BGL_M_Heating Pipework', 'heating'), ('LTHW', 'heating'),
    ('HEATING & COOLING', 'heating'), ('BGL_P_Drainage', 'drainage'), ('Soil Vent Pipe', 'drainage'),
    ('Waste water', 'drainage'), ('BGL_P_Water Services', 'water'), ('Domestic Cold Water', 'water'),
    ('Chilled Water', 'pipework'), ('BGL-M-Heating_Plan', 'heating'),
    ('Ducts', 'ductwork'), ('Pipes', 'pipework'), ('Air Terminals', 'ductwork'),
    # words that must not match anything
    ('LEVEL 01', None), ('SOLVENT', None), ('PREVENT', None), ('PORTRAY', None),
    ('FAN COIL', None), ('ADMIN BUILDING', None), ('', None), ('Fabric', None),
]


@check
def disciplines_matched():
    u"""Folder headings and view template names read as the right
    discipline - on whole words, first match wins - and every discipline
    has an icon and two colours."""
    import pbp_disc
    wrong = [(text, pbp_disc.match(text), want) for text, want in DISCIPLINE_CASES
             if pbp_disc.match(text) != want]
    assert not wrong, wrong
    for key in pbp_disc.keys():
        assert path_ok(pbp_disc.icon(key)), key
        for theme in ('dark', 'light'):
            colour = pbp_disc.colour(key, theme)
            assert colour.startswith('#') and len(colour) == 7, (key, theme, colour)
        assert pbp_disc.label(key)
    assert pbp_disc.icon('nope') is None and pbp_disc.colour('nope', 'dark') is None
    families = dict((key, pbp_disc.family(key)) for key in pbp_disc.keys())
    assert set(k for k, f in families.items() if f == 'electrical') == \
        set(['security', 'lighting', 'comms', 'power', 'containment']), families
    assert set(k for k, f in families.items() if f == 'mechanical') == \
        set(['ductwork', 'heating', 'pipework', 'mechanical']), families
    assert set(k for k, f in families.items() if f == 'plumbing') == \
        set(['drainage', 'water', 'plumbing']), families
    assert pbp_disc.family(None) == 'other' and pbp_disc.family('fire') == 'other'


def feed(control, snap):
    u"""Hand a snapshot over as the store would - the store keeps it, so
    the marks know which project they are for."""
    control.store.snapshot = snap
    control._on_snapshot(snap, False)


def _mleaf(key, tab, text, uid, **kw):
    from pbp_tree import Leaf
    return Leaf(key, tab, kw.pop('kind', 'plan'), text, uid=uid, **kw)


@check
def marks_round_trip():
    u"""Favourites, colours, panel groups and the sheet set survive a save
    and a load, by UniqueId; a damaged line is dropped, not fatal."""
    stubbed()
    import pbp_marks
    folder = tempfile.mkdtemp()
    a = _mleaf('e:1', 'views', 'A', 'ua')
    b = _mleaf('e:2', 'sheets', 'B', 'ub')
    p1 = _mleaf('e:3', 'panels', 'DB-1', 'up1')
    p2 = _mleaf('e:4', 'panels', 'DB-2', 'up2')
    nouid = _mleaf('e:5', 'views', 'C', '')
    marks = pbp_marks.Marks(folder, 'Proj: one/two')
    assert marks.add_favs([a, b, a, nouid]) == 2
    assert marks.set_colour([a, nouid], 'c3') == 1 and marks.colour_of('ua') == 'c3'
    assert marks.set_colour([p1], 'c1') == 0, 'only a favourite can be coloured'
    assert marks.set_group([p1, p2], '  Level 1\n boards ') == 2
    assert marks.group_of('up1') == 'Level 1 boards'
    marks.sheet_set = 'Issue A'
    assert marks.save()
    back = pbp_marks.Marks.load(folder, 'Proj: one/two')
    assert back.favs == {'ua': 'views', 'ub': 'sheets'}, back.favs
    assert back.colours == {'ua': 'c3'} and back.sheet_set == 'Issue A'
    assert back.group_names() == ['Level 1 boards']
    assert back.rename_group('Level 1 boards', 'L1') == 2 and back.group_names() == ['L1']
    assert back.set_group([p2], '') == 1 and back.group_of('up2') == ''
    assert back.drop_group('L1') == 1 and not back.groups
    assert back.remove_favs([a]) == 1 and 'ua' not in back.colours, 'a removed favourite loses its colour'
    assert back.fav_leaves({'views': [a], 'sheets': [b]}) == {'sheets': [b]}
    path = pbp_marks.marks_path(folder, 'Proj: one/two')
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write('colour.ub=purple\nrubbish line\ngroup.up1=\n')
    damaged = pbp_marks.Marks.load(folder, 'Proj: one/two')
    assert 'ub' not in damaged.colours and 'up1' not in damaged.groups
    assert pbp_marks.colour_slot('C9') == 'c9' and pbp_marks.colour_slot('c10') == ''
    assert pbp_marks.Marks.load(folder, 'Other').favs == {}, 'marks are per project'


@check
def favourites_tab():
    u"""Add from any tab, grouped by type in browser order, flat (a parent
    view's dependents stay on the Views tab), Collapse all closes the type
    headings, colour shows as a pill on the Favourites tab only, and every
    pane hears the change."""
    control = browser()
    import pbp_browser
    pane = pbp_browser.BrowserControl('pane', 'favourites')   # a second pane, same store
    pane.runner = FakeRunner()
    snap = snapshot_for_tests()
    deps = _dependents()
    for leaf in deps:
        leaf.uid = 'dep-' + leaf.key
    snap.tabs['views'] = snap.tabs['views'] + deps
    feed(control, snap)
    heard = []
    control.store.subscribe(lambda s, how: heard.append(how))
    control.tab = 'views'
    control._expand_all()   # builds the views tree: VRF_L00 gets its children
    rows = dict((r.text, r) for r in control.rows)
    picked = [rows['VRF_L00'].leaf, rows['Level 1'].leaf]
    control._selected_rows = lambda: [rows['VRF_L00'], rows['Level 1']]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Open selected (2)' in labels and 'Add 2 to favourites' in labels, labels
    control._add_favourites(picked)
    assert heard and heard[-1] == __import__('pbp_store').MARKS
    sheet = snap.tabs['sheets'][1]
    control._add_favourites([sheet, snap.tabs['families'][0]])
    control.tab = 'favourites'
    control._render()
    texts = [r.text for r in control.rows]
    assert texts == ['Views', 'Level 1', 'VRF_L00', 'Sheets', 'M-02 - Plan', 'Families', '15mm'], texts
    assert not [r for r in control.rows if r.nested], 'favourites are flat'
    assert [r.text for r in pane.rows] == texts, 'the Favourites pane hears the change too'
    assert rows['VRF_L00'].leaf.children, 'the Views tab keeps its dependents'
    assert control.tab_buttons['favourites'].ToolTip.startswith('Favourites: 4'), \
        control.tab_buttons['favourites'].ToolTip
    control._collapse_all()
    assert [r.text for r in control.rows] == ['Views', 'Sheets', 'Families'], [r.text for r in control.rows]
    control._expand_all()
    favrows = dict((r.text, r) for r in control.rows)
    control._selected_rows = lambda: [favrows['Level 1']]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Remove from favourites' in labels and 'Add to favourites' not in labels, labels
    control._set_colour([favrows['Level 1'].leaf], 'c2')
    coloured = cells(control, favrows['Level 1'])
    import pbp_palette
    assert coloured['pillvis'] == 'Visible', 'a coloured favourite sits on a pill'
    assert coloured['fill'][3:] == pbp_palette.slot_colour('c2', control.theme_name)[1:], coloured['fill']
    assert cells(control, favrows['VRF_L00'])['pillvis'] == 'Collapsed'
    assert labels and 'Clear colour' in [h for h, f, e in menu_headers(
        control, lambda: control._list_menu_opening(None, None))]
    control.tab = 'views'
    control._render()
    plain = dict((r.text, r) for r in control.rows)
    assert cells(control, plain['Level 1'])['pillvis'] == 'Collapsed', 'the colour is the Favourites tab\'s'
    control.tab = 'favourites'
    control._render()
    control._remove_favourites([favrows['Level 1'].leaf, favrows['15mm'].leaf])
    assert [r.text for r in control.rows] == ['Views', 'VRF_L00', 'Sheets', 'M-02 - Plan']
    control._selected_rows = lambda: [r for r in control.rows if r.leaf is not None]
    control._update_toolbar()
    assert control.print_button.Visibility is not None
    lines = control.report_lines()
    assert any(line.startswith('marks: 2 favourite') for line in lines), lines


@check
def favourites_pane_registered():
    u"""Favourites has a dockable pane of its own, with a GUID that is not
    any other pane's and a tab glyph."""
    import pbp_panes
    import pbp_icons
    guids = [p[3] for p in pbp_panes.PANES]
    assert len(set(guids)) == len(guids)
    assert pbp_panes.guid_for('favourites') not in (pbp_panes.MAIN_GUID,)
    assert pbp_panes.title_for('favourites') == 'RevoBIM Favourites'
    assert path_ok(pbp_icons.tab_glyph('favourites'))


@check
def sheet_set_filter():
    u"""The Sheets tab shows one sheet set or all; the All tab always shows
    every sheet; a set deleted in Revit falls back to all."""
    control = browser()
    snap = snapshot_for_tests()
    snap.sheet_sets = {'Issue A': set(['u4']), 'Empty': set()}
    feed(control, snap)
    control.tab = 'sheets'
    control._render()
    assert [r.text for r in control.rows if r.leaf] == ['M-01 - Plan', 'M-02 - Plan']
    assert control.sheet_set_text.Text == 'All sheets'
    control._choose_sheet_set('Issue A')
    assert [r.text for r in control.rows if r.leaf] == ['M-02 - Plan'], [r.text for r in control.rows]
    assert control.sheet_set_text.Text == 'Issue A'
    assert control.org_text.Text.startswith('1 items'), control.org_text.Text
    labels = [h for h, f, e in menu_headers(control, lambda: control._sheet_set_clicked(None, None))]
    assert labels[0] == 'All sheets' and 'Issue A  (1)' in labels, labels
    control.tab = 'all'
    control._render()
    assert [r.text for r in control.rows if r.leaf and r.tab == 'sheets'] == ['M-01 - Plan', 'M-02 - Plan']
    snap.sheet_sets = {}
    feed(control, snap)
    control.tab = 'sheets'
    control._render()
    assert [r.text for r in control.rows if r.leaf] == ['M-01 - Plan', 'M-02 - Plan'], \
        'a deleted set shows all sheets'
    labels = [h for h, f, e in menu_headers(control, lambda: control._sheet_set_clicked(None, None))]
    assert any(h.startswith('No sheet sets') for h in labels), labels


@check
def panel_groups():
    u"""Panels go into the user's groups; Ungrouped comes last; with no
    group at all the tab looks as it always did."""
    control = browser()
    snap = snapshot_for_tests()
    snap.tabs['panels'] = [_mleaf('e:6', 'panels', 'DB-L1', 'u6', kind='panel'),
                           _mleaf('e:8', 'panels', 'DB-L2', 'u8', kind='panel'),
                           _mleaf('e:9', 'panels', 'MCC-1', 'u9', kind='panel')]
    feed(control, snap)
    control.tab = 'panels'
    control._render()
    assert [r.text for r in control.rows] == ['DB-L1', 'DB-L2', 'MCC-1'], [r.text for r in control.rows]
    rows = dict((r.text, r) for r in control.rows)
    control._selected_rows = lambda: [rows['DB-L1'], rows['DB-L2']]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'New group...' in labels and 'Remove from group' not in labels, labels
    control._group_panels([rows['DB-L1'].leaf, rows['DB-L2'].leaf], 'Distribution boards')
    assert [r.text for r in control.rows] == ['Distribution boards', 'DB-L1', 'DB-L2', 'Ungrouped', 'MCC-1'], \
        [r.text for r in control.rows]
    rows = dict((r.text, r) for r in control.rows)
    control._selected_rows = lambda: [rows['MCC-1']]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Move to group: Distribution boards' in labels, labels
    control._selected_rows = lambda: [rows['Distribution boards']]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Rename group...' in labels and 'Ungroup' in labels, labels
    control._selected_rows = lambda: [rows['Ungrouped']]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Ungroup' not in labels, 'Ungrouped is not a group to rename'
    import pbp_ui
    pbp_ui.ask_text = lambda *a, **k: ' Boards '
    control._rename_group('Distribution boards')
    assert [r.text for r in control.rows][0] == 'Boards'
    control._ungroup('Boards')
    assert [r.text for r in control.rows] == ['DB-L1', 'DB-L2', 'MCC-1']


def gradient_snapshot():
    snap = snapshot_for_tests()
    data = [
        ('ELECTRICAL', 'POWER', 'Floor Plans', 'L1 Power', 'BGL_E_Power'),
        ('ELECTRICAL', 'CONTAINMENT', 'Floor Plans', 'L1 Containment', ''),
        ('ELECTRICAL', 'LIGHTING', 'Floor Plans', 'L1 Lighting', ''),
        ('ELECTRICAL', 'WORKING', 'Power Plans', 'L1 Working', ''),
        ('MECHANICAL', 'DUCTWORK', 'Floor Plans', 'L1 Ductwork', ''),
        ('MECHANICAL', 'HEATING', 'Floor Plans', 'L1 Heating', 'BGL_M_Heating Pipework'),
        ('PUBLIC HEALTH', 'DRAINAGE', 'Floor Plans', 'L1 Drainage', ''),
        ('PUBLIC HEALTH', 'WATER SERVICES', 'Floor Plans', 'L1 Water', ''),
        ('COORDINATION', 'MODEL', 'Floor Plans', 'L1 Coord', 'Some template'),
    ]
    snap.tabs['views'] = []
    for i, (group, purpose, kind, name, template) in enumerate(data):
        leaf = _mleaf('e:%d' % (20 + i), 'views', name, 'g%d' % i, folders=[group, purpose, kind])
        leaf.template = template
        snap.tabs['views'].append(leaf)
    return snap


@check
def heading_gradients():
    u"""Electrical headings are greens, mechanical blues, plumbing browns,
    the rest violets - each run dark to light; main headings at the dark
    end, the level below lighter. Text, icon and chevron take black or
    white for contrast. Only the first two levels; a view's icon comes
    from its view template."""
    control = browser()
    feed(control, gradient_snapshot())
    control.tab = 'views'
    control.colour = True
    control._expand_all()
    import pbp_disc, pbp_palette, pbp_icons, pbp_browser
    rows = control.rows
    c = lambda text: cells(control, [r for r in rows if r.text == text][0])
    elec, power, cont, light, work = [c(t) for t in ('ELECTRICAL', 'POWER', 'CONTAINMENT', 'LIGHTING', 'WORKING')]
    mech, duct, heat = [c(t) for t in ('MECHANICAL', 'DUCTWORK', 'HEATING')]
    ph, drain, water = [c(t) for t in ('PUBLIC HEALTH', 'DRAINAGE', 'WATER SERVICES')]
    coord, model = c('COORDINATION'), c('MODEL')
    plan = control.plan
    key = lambda text: [r for r in rows if r.text == text][0].node.key
    fam = lambda text: plan[key(text)][0]
    assert [fam(t) for t in ('ELECTRICAL', 'POWER', 'CONTAINMENT', 'LIGHTING', 'WORKING')] == ['electrical'] * 5
    assert [fam(t) for t in ('MECHANICAL', 'DUCTWORK', 'HEATING')] == ['mechanical'] * 3
    assert [fam(t) for t in ('PUBLIC HEALTH', 'DRAINAGE', 'WATER SERVICES')] == ['plumbing'] * 3
    assert fam('COORDINATION') == fam('MODEL') == 'other'
    for cell in (elec, power, mech, heat, ph, drain, coord, model):
        assert cell['pillvis'] == 'Visible' and len(cell['fill']) == 7, cell
        assert cell['fore'] == pbp_palette.text_on(cell['fill']) == cell['chevfill'] == cell['iconfill'], cell
    lum = pbp_palette.luminance
    run = [cont, light, power, work]   # browser order: A-Z
    assert [lum(x['fill']) for x in run] == sorted(lum(x['fill']) for x in run), 'electrical: dark to light'
    assert len(set(x['fill'] for x in run)) == 4, 'each a shade of its own'
    assert lum(elec['fill']) < lum(power['fill']), 'main heading at the dark end'
    assert elec['fill'] == pbp_palette.shade('electrical', plan[key('ELECTRICAL')][1])
    assert lum(duct['fill']) < lum(heat['fill']) and lum(drain['fill']) < lum(water['fill'])
    greenish = lambda h: int(h[3:5], 16) > int(h[1:3], 16) and int(h[3:5], 16) > int(h[5:7], 16)
    bluish = lambda h: int(h[5:7], 16) > int(h[1:3], 16)
    assert greenish(power['fill']) and bluish(duct['fill']) and not bluish(drain['fill'])
    assert elec['size'] == pbp_browser.HEAD_SIZES[1] and elec['weight'] == 'Bold'
    assert power['size'] == pbp_browser.HEAD_SIZES[2] and power['rowh'] == pbp_browser.HEAD_HEIGHTS[2]
    assert heat['icon'] == pbp_disc.icon('heating') and elec['icon'] == pbp_disc.icon('power')
    assert work['icon'] == pbp_disc.icon('power'), 'WORKING under ELECTRICAL inherits its icon'
    assert coord['iconvis'] == 'Collapsed', 'COORDINATION names no discipline'
    plans = cells(control, [r for r in rows if r.text == 'Power Plans'][0])
    assert plans['pillvis'] == 'Collapsed' and plans['iconvis'] == 'Collapsed' and \
        plans['rowh'] == pbp_browser.ROW_HEIGHT, 'a third level folder is plain'
    leaf = c('L1 Heating')
    assert leaf['icon'] == pbp_icons.framed(pbp_disc.icon('heating')) and leaf['pillvis'] == 'Collapsed'
    assert leaf['iconfill'] == pbp_palette.palette(control.theme_name)['TextBrush'], \
        'view icons are plain: the text colour, no discipline colour'
    assert leaf['fill'] == pbp_palette.TRANSPARENT, 'views are never coloured'
    assert c('L1 Coord')['icon'] == pbp_icons.framed(pbp_icons.icon_for('plan'))
    control.colour = False
    off = c('HEATING')
    assert off['pillvis'] == 'Visible' and off['icon'] == pbp_disc.icon('heating')
    assert off['fill'] == pbp_palette.grey_pill(2, control.theme_name)[0]
    assert off['iconfill'] == pbp_palette.palette(control.theme_name)['MutedBrush']
    for rank in (1, 2):
        light = pbp_palette.grey_pill(rank, 'light')[0]
        assert pbp_palette.luminance(light) > 0.8, 'light theme: a really faint grey'
        r, g, b = pbp_palette._rgb(light)
        assert abs(r - g) < 8 and abs(g - b) < 8, 'grey, not tinted'
    assert c('Floor Plans')['pillvis'] == 'Collapsed', 'only bars that were coloured turn grey'
    control.colour = True
    control.tab = 'all'
    control._render()
    root = cells(control, control.rows[0])
    assert root['pillvis'] == 'Collapsed', 'the type roots are not pilled'
    for family in pbp_palette.RAMPS:
        for t in (0.0, 0.5, 1.0):
            fill, edge, text = pbp_palette.heading_pill(family, t)
            assert len(fill) == len(edge) == 7 and text in (pbp_palette.DARK_TEXT, pbp_palette.LIGHT_TEXT)
    assert pbp_palette.ladder(3, 0.4, 1.0) == [0.4, 0.7, 1.0] and pbp_palette.ladder(1, 0, 0.3) == [0.15]
    for family in pbp_palette.RAMPS:
        assert pbp_palette.heading_pill(family, 0.0)[2] == pbp_palette.LIGHT_TEXT, 'white on the dark end'
        assert pbp_palette.heading_pill(family, 1.0)[2] == pbp_palette.DARK_TEXT, 'black on the light end'


CATEGORY_CASES = [
    ('OST_DuctTags', 'Duct Tags', 'Annotation', 'Tags'),
    ('OST_MultiCategoryTags', 'Multi-Category Tags', 'Annotation', 'Tags'),
    ('OST_RoomTags', 'Room Tags', 'Annotation', 'Tags'),
    ('OST_Dimensions', 'Dimensions', 'Annotation', 'Annotations'),
    ('OST_GenericAnnotation', 'Generic Annotations', 'Annotation', 'Annotations'),
    ('OST_DetailComponents', 'Detail Items', 'Model', 'Annotations'),
    ('OST_TitleBlocks', 'Title Blocks', 'Annotation', 'Annotations'),
    ('OST_SomethingNew', 'Some Symbol', 'Annotation', 'Annotations'),
    ('OST_Walls', 'Walls', 'Model', 'Architecture'),
    ('OST_Doors', 'Doors', 'Model', 'Architecture'),
    ('OST_Furniture', 'Furniture', 'Model', 'Architecture'),
    ('OST_StructuralColumns', 'Structural Columns', 'Model', 'Structure'),
    ('OST_StructuralFraming', 'Structural Framing', 'Model', 'Structure'),
    ('OST_Rebar', 'Structural Rebar', 'Model', 'Structure'),
    ('OST_CableTray', 'Cable Trays', 'Model', 'Electrical'),
    ('OST_LightingFixtures', 'Lighting Fixtures', 'Model', 'Electrical'),
    ('OST_ElectricalEquipment', 'Electrical Equipment', 'Model', 'Electrical'),
    ('OST_FireAlarmDevices', 'Fire Alarm Devices', 'Model', 'Electrical'),
    ('OST_FabricationContainment', 'MEP Fabrication Containment', 'Model', 'Electrical'),
    ('OST_PlumbingFixtures', 'Plumbing Fixtures', 'Model', 'Mechanical & Plumbing'),
    ('OST_MechanicalEquipment', 'Mechanical Equipment', 'Model', 'Mechanical & Plumbing'),
    ('OST_DuctTerminal', 'Air Terminals', 'Model', 'Mechanical & Plumbing'),
    ('OST_PipeCurves', 'Pipes', 'Model', 'Mechanical & Plumbing'),
    ('OST_Sprinklers', 'Sprinklers', 'Model', 'Mechanical & Plumbing'),
    ('OST_FabricationHangers', 'MEP Fabrication Hangers', 'Model', 'Mechanical & Plumbing'),
    ('OST_GenericModel', 'Generic Models', 'Model', 'Other'),
    # no OST name: the English name decides
    ('', 'Structural Stiffeners', 'Model', 'Structure'),
    ('', 'Duct Accessories', 'Model', 'Mechanical & Plumbing'),
    ('', 'Conduits', 'Model', 'Electrical'),
    ('', 'Site', 'Model', 'Architecture'),
    ('', 'Composite Things', 'Model', 'Other'),
    ('', 'Pipe Tags', 'Annotation', 'Tags'),
]


@check
def categories_grouped():
    u"""Every category lands in its main group - MEP-shared categories in
    MEP, tags before anything else - by OST name, else by English name."""
    import pbp_catgroups as g
    wrong = [(o, n, g.main_group(o, n, t), want) for o, n, t, want in CATEGORY_CASES
             if g.main_group(o, n, t) != want]
    assert not wrong, wrong
    assert g.ORDER == ('Tags', 'Annotations', 'Architecture', 'Structure', 'Electrical',
                       'Mechanical & Plumbing', 'Other')
    for group in g.ORDER:
        assert path_ok(g.icon(group)), group
    assert g.ramp('Electrical') == 'electrical' and g.ramp('Mechanical & Plumbing') == 'mechanical'
    assert g.ramp('Tags') == 'other'
    stubbed()
    import pbp_revit

    class Id(object):
        def __init__(self, value):
            self.Value = value

    class Category(object):
        def __init__(self, value, ost, name, kind='Model'):
            self.Id = Id(value)
            self.BuiltInCategory = ost
            self.Name = name
            self.CategoryType = kind

    class Element(object):
        def __init__(self, category):
            self.Category = category
    ctx = {}
    assert pbp_revit.main_group_of(Element(Category(-2008130, 'OST_CableTray', 'Kabeltrassen')), ctx) == \
        'Electrical', 'the OST name decides, whatever language the name is in'
    assert pbp_revit.main_group_of(Element(Category(5, 'INVALID', 'Pipe Tags', 'Annotation')), ctx) == 'Tags'
    assert pbp_revit.main_group_of(Element(None), ctx) == 'Other'
    assert pbp_revit.ost_of(Category(7, 'OST_Walls', 'Walls'), 7) == '', 'a user category has no OST'


@check
def families_tab_grouped():
    u"""Families open as main group > category > family > type, the main
    groups in their own order, each with its icon on a pill; the category
    level pilled too, families not."""
    control = browser()
    snap = snapshot_for_tests()
    snap.tabs['families'] = []
    for i, (group, category, family) in enumerate([
            ('Other', 'Generic Models', 'Box'), ('Electrical', 'Cable Trays', 'Ladder'),
            ('Tags', 'Duct Tags', 'Duct Tag'), ('Architecture', 'Walls', 'Basic Wall'),
            ('Electrical', 'Lighting Fixtures', 'Downlight'),
            ('Mechanical & Plumbing', 'Ducts', 'Rect Duct'),
            ('Mechanical & Plumbing', 'Plumbing Fixtures', 'WC')]):
        snap.tabs['families'].append(_mleaf('e:%d' % (40 + i), 'families', 'Type %d' % i, 'f%d' % i,
                                            kind='type', values={'Main Group': group,
                                                                 'Category': category,
                                                                 'Family': family}))
    feed(control, snap)
    control.tab = 'families'
    control.colour = True
    control._render()
    heads = [r.text for r in control.rows if r.heading and r.node.level == 1]
    assert heads == ['Tags', 'Architecture', 'Electrical', 'Mechanical & Plumbing', 'Other'], heads
    import pbp_catgroups, pbp_disc, pbp_palette
    row = lambda text: [r for r in control.rows if r.text == text][0]
    elec = cells(control, row('Electrical'))
    assert elec['icon'] == pbp_catgroups.icon('Electrical') and elec['pillvis'] == 'Visible'
    assert control.plan[row('Electrical').node.key][0] == 'electrical'
    trays, lights = cells(control, row('Cable Trays')), cells(control, row('Lighting Fixtures'))
    assert trays['icon'] == pbp_disc.icon('containment') and lights['icon'] == pbp_disc.icon('lighting')
    assert pbp_palette.luminance(trays['fill']) < pbp_palette.luminance(lights['fill'])
    walls = cells(control, row('Walls'))
    assert walls['icon'] == pbp_catgroups.icon('Architecture'), 'a category with no discipline: its group\'s icon'
    assert control.plan[row('Duct Tags').node.key][0] == 'other', 'tags stay in the Tags gradient'
    assert cells(control, row('Ducts'))['icon'] == pbp_disc.icon('ductwork'), 'plural names match too'
    assert control.plan[row('Plumbing Fixtures').node.key][0] == 'plumbing', \
        'plumbing stays brown inside Mechanical & Plumbing'
    assert control.plan[row('Ducts').node.key][0] == 'mechanical'
    assert cells(control, row('Ladder'))['pillvis'] == 'Collapsed'
    assert 'Main group › Category › Family › Type' in control.org_text.Text, control.org_text.Text


@check
def legends_tab():
    u"""Legends are a tab of their own (and a pane), between Views and
    Sheets, with an organisation of their own."""
    control = browser()
    snap = snapshot_for_tests()
    snap.tabs['legends'] = [
        _mleaf('e:60', 'legends', 'Electrical Legend', 'l1', kind='legend',
               values={'View Template': 'BGL_E_Power'}),
        _mleaf('e:61', 'legends', 'Mechanical Legend', 'l2', kind='legend',
               values={'View Template': 'BGL_M_Ductwork'})]
    snap.orgs['legends'] = {'source': 'custom', 'levels': ['View Template'], 'sort': '', 'desc': False}
    feed(control, snap)
    control.tab = 'legends'
    control._render()
    assert [r.text for r in control.rows] == ['BGL_E_Power', 'Electrical Legend', 'BGL_M_Ductwork',
                                              'Mechanical Legend'], [r.text for r in control.rows]
    assert control.rows[0].level == 0, 'the master is the sub tab now, not a heading'
    control.colour_mode = 'colour'
    control._render()
    assert cells(control, control.rows[0])['pillvis'] == 'Visible', \
        'headings are coloured as on the whole tab, masters and all'
    import pbp_settings, pbp_panes, pbp_tree, pbp_revit
    assert 'legends' in pbp_settings.ORGANISABLE and pbp_settings.DEFAULT_ORGS['legends']['source'] == 'none'
    assert pbp_panes.title_for('legends') == 'RevoBIM Legends and Drafting Views'
    assert pbp_tree.OPEN_ORDER.index('legends') == 1
    assert 'legends' in pbp_revit.Snapshot().tabs and 'legends' in pbp_revit.ZOOM_TABS
    labels = [h for h, f, e in menu_headers(control, lambda: control._tab_menu_opener('legends')(None, None))]
    assert 'Browser Organisation...' in labels
    control.tab = 'all'
    control._render()
    assert 'Legends and Drafting Views' in [r.text for r in control.rows if r.is_root]


@check
def pinned_copy():
    u"""A heading dragged out shows as a copy on its own - same colours as
    the browser it came from - in a pane slot that re-reads its pin when a
    pin is written, or a floating window."""
    control = browser()
    snap = gradient_snapshot()
    feed(control, snap)
    control.tab = 'views'
    control.colour = True
    control._expand_all()
    source = dict((r.text, cells(control, r)) for r in control.rows)
    import pbp_browser, pbp_settings, pbp_store, pbp_panes
    copy = pbp_browser.BrowserControl('window', None, pin=('views', ('ELECTRICAL', 'POWER')))
    copy.runner = FakeRunner()
    copy._on_snapshot(snap, False)
    assert copy.tab == 'views' and copy.fixed_tab == 'views'
    texts = [r.text for r in copy.rows]
    assert texts == ['Floor Plans', 'L1 Power'], texts
    assert copy.org_text.Text == '1 items · pinned copy of Views › ELECTRICAL › POWER', \
        copy.org_text.Text
    assert copy.title_text.Text.endswith('POWER')
    gone = pbp_browser.BrowserControl('window', None, pin=('views', ('NOPE',)))
    gone._on_snapshot(snap, False)
    assert gone.rows == [] and 'is not in this model' in gone.empty_text.Text
    # a pane slot: the pin comes from the file and follows it
    pbp_settings.save_pin(control.folder, 2, 'views', ('ELECTRICAL',))
    pane = pbp_browser.BrowserControl('pane', 'pin:2')
    pane.runner = FakeRunner()
    pane._on_snapshot(snap, False)
    assert pane.pin == ('views', ('ELECTRICAL',)) and pane.rows[0].text == 'CONTAINMENT'
    power = cells(pane, [r for r in pane.rows if r.text == 'POWER'][0])
    assert power['fill'] == source['POWER']['fill'], 'a copy keeps the browser\'s colours'
    pbp_settings.save_pin(control.folder, 2, 'views', ('MECHANICAL',))
    pane._tick(None, None)
    assert pane.pin == ('views', ('ELECTRICAL',)), 'nothing re-read until a pin is written'
    pbp_store.bump_pins()
    pane._tick(None, None)
    assert pane.pin == ('views', ('MECHANICAL',)) and pane.rows[0].text == 'DUCTWORK'
    assert len(pbp_panes.pin_guids()) == 8 and pbp_panes.pin_slot_for(pbp_panes.pin_guids()[2]) == 3


class _P(object):
    def __init__(self, x, y):
        self.X, self.Y = x, y


class _MouseArgs(object):
    def __init__(self, x, y, pressed=True):
        import pbp_browser
        self.point = _P(x, y)
        self.LeftButton = pbp_browser.MouseButtonState.Pressed if pressed else None
        self.Handled = False

    def GetPosition(self, element):
        return self.point


@check
def drag_heading_out():
    u"""Dragging a heading past the browser's edge pins it: into the first
    free pane slot, else a floating copy. Released inside, nothing. The drag
    is Windows' own (DoDragDrop): the release point and Esc come from its
    QueryContinueDrag, so the drag always ends - 1.3.0's own mouse capture
    froze the browser when the button came up outside it."""
    control = browser()
    feed(control, gradient_snapshot())
    control.tab = 'views'
    control._expand_all()
    heading = [r for r in control.rows if r.text == 'HEATING'][0]
    import pbp_window, pbp_store, pbp_revit, pbp_settings, pbp_browser
    floated = []
    pbp_window.open_pinned = lambda pin, placement=None: floated.append(pin)
    outcomes = []
    real_do_drag = control._do_drag
    control._do_drag = lambda drag: outcomes.pop(0)
    control.drag = {'row': heading, 'start': _P(50, 50), 'live': False}
    control._drag_move(None, _MouseArgs(53, 52))
    assert control.drag is not None, 'a small move is still a click'
    outcomes.append(('inside', None))
    control._drag_move(None, _MouseArgs(100, 80))
    assert control.drag is None and floated == [], 'released inside: nothing'
    control.drag = {'row': heading, 'start': _P(50, 50), 'live': False}
    outcomes.append(('outside', (4000.0, 300.0)))
    control._drag_move(None, _MouseArgs(120, 90))
    assert floated == [('views', ('MECHANICAL', 'HEATING'))], floated
    control.drag = {'row': heading, 'start': _P(50, 50), 'live': False}
    control._drag_move(None, _MouseArgs(120, 90, pressed=False))
    assert control.drag is None and len(floated) == 1, 'button already up: no drag at all'
    # the drag itself, through a stand-in for Windows: the button comes up
    # at a screen point Windows reports, outside the browser
    control._do_drag = real_do_drag
    import System.Windows as W
    keys = type('Keys', (), {'LeftMouseButton': 1})
    pbp_browser.DragDropKeyStates = keys
    pbp_browser.mouse_screen = lambda: (4000.0, 300.0)
    control._outside_screen = lambda x, y: x > 1000

    def windows_drag(source, data, effects):
        args = type('Q', (), {'EscapePressed': False, 'KeyStates': 1})()
        control._drag_query(None, args)
        args.KeyStates = 0
        control._drag_query(None, args)
    W.DragDrop.DoDragDrop = staticmethod(windows_drag)
    drag = {'row': heading, 'start': _P(50, 50), 'live': True}
    assert control._do_drag(drag) == ('outside', (4000.0, 300.0))
    assert pbp_browser.DRAGGING[0] is None, 'the drag is always cleared'

    def escaped(source, data, effects):
        control._drag_query(None, type('Q', (), {'EscapePressed': True, 'KeyStates': 1})())
    W.DragDrop.DoDragDrop = staticmethod(escaped)
    assert control._do_drag(dict(drag)) == ('cancel', None)

    def broken(source, data, effects):
        raise Exception('drag refused')
    W.DragDrop.DoDragDrop = staticmethod(broken)
    assert control._do_drag(dict(drag)) == ('cancel', None) and pbp_browser.DRAGGING[0] is None
    # panes registered: the first free slot gets the pin
    pbp_store.domain_set(pbp_store.PANES_KEY, 'registered')
    pbp_revit.free_pane = lambda app, guids: guids[2]
    pbp_revit.show_pane = lambda app, guid: {'ok': True}
    before = pbp_store.pins_count()
    control._pin_heading(heading)
    name, work, done = control.runner.jobs[-1]
    result = work(None)
    done(result, None)
    assert result['slot'] == 3 and pbp_settings.load_pins(control.folder)[3] == ('views', ('MECHANICAL', 'HEATING'))
    assert pbp_store.pins_count() == before + 1 and 'Pinned 3' in control.status.Text
    pbp_revit.free_pane = lambda app, guids: None
    control._pin_heading(heading)
    name, work, done = control.runner.jobs[-1]
    done(work(None), None)
    assert len(floated) == 2, 'no free slot: a floating copy'


@check
def rename_in_place():
    u"""A slow second click (or F2) renames in the row; a sheet's number and
    name are both editable; nothing changed, nothing sent."""
    control = browser()
    snap = snapshot_for_tests()
    feed(control, snap)
    import pbp_browser, pbp_revit
    sheet = snap.tabs['sheets'][0]   # M-01 - Plan
    view = snap.tabs['views'][0]
    parts = pbp_browser.rename_parts
    assert parts(sheet, 'M-01 - Plan') == (None, None)
    assert parts(sheet, 'M-01 - Layout') == ('Layout', None)
    assert parts(sheet, 'M-10 - Plan') == (None, 'M-10')
    assert parts(sheet, 'M-10 - Layout') == ('Layout', 'M-10')
    assert parts(sheet, 'Layout') == ('Layout', None)
    assert parts(view, 'Level 1 ') == (None, None) and parts(view, 'L1') == ('L1', None)
    control.tab = 'sheets'
    control._render()
    row = [r for r in control.rows if r.leaf is sheet][0]
    assert control._renamable(row) and not control._renamable([r for r in control.rows if r.heading][0])
    sent = []
    pbp_revit.rename_leaf = lambda app, leaf, name, number: sent.append((leaf.key, name, number)) or {'ok': True}
    control._commit_rename(row, 'M-02A - Plan')
    control.runner.jobs[-1][1](None)
    assert sent == [(sheet.key, None, 'M-02A')], sent
    jobs = len(control.runner.jobs)
    control._commit_rename(row, row.text)
    assert len(control.runner.jobs) == jobs, 'unchanged: nothing sent'
    begun = []
    control._begin_edit = lambda r: begun.append(r.key) or True
    control._selected_rows = lambda: [row]
    control.slow = row.key
    control._rename_tick(None, None)
    assert begun == [row.key] and control.slow is None
    control.slow = row.key
    control._list_double(None, type('A', (), {'OriginalSource': None, 'Handled': False})())
    assert control.slow is None, 'a double click is not a rename'


@check
def zoom_and_sync():
    u"""Opened views and sheets are zoomed to fit (a second pass for windows
    Revit made late); selecting in the browser selects in Revit once the
    selection settles, unless turned off."""
    stubbed()
    import pbp_revit
    from pbp_tree import Leaf

    class Id(object):
        def __init__(self, value):
            self.Value = value

    class Window(object):
        def __init__(self, value):
            self.ViewId = Id(value)
            self.zoomed = 0

        def ZoomToFit(self):
            self.zoomed += 1

    windows = [Window(1), Window(3)]

    class UIDoc(object):
        def GetOpenUIViews(self):
            return windows

    class App(object):
        ActiveUIDocument = UIDoc()
    leaves = [Leaf('e:1', 'views', 'plan', 'A', eid=Id(1)), Leaf('e:2', 'views', 'plan', 'B', eid=Id(2)),
              Leaf('e:3', 'sheets', 'sheet', 'S', eid=Id(3))]
    later = pbp_revit.zoom_leaves(App(), leaves)
    assert [w.zoomed for w in windows] == [1, 1] and [l.text for l in later] == ['B']
    control = browser()
    feed(control, snapshot_for_tests())
    control._opened({'opened': 3, 'failed': [], 'zoom_later': later}, None)
    assert control.zoom_pending == later
    control._zoom_tick(None, None)
    assert control.runner.jobs[-1][0] == 'zoom to fit' and control.zoom_pending == []
    control.tab = 'views'
    control._render()
    leaf_rows = [r for r in control.rows if r.leaf is not None]
    control._selected_rows = lambda: leaf_rows
    assert control.sync is True, 'on by default'

    class Timer(object):
        starts = 0

        def Start(self):
            Timer.starts += 1

        def Stop(self):
            pass
    control.sync_timer = Timer()
    control._selection_changed(None, None)
    assert Timer.starts == 1, 'a selection arms the sync'
    control._sync_tick(None, None)
    assert control.runner.jobs[-1][0] == 'sync selection'
    jobs = len(control.runner.jobs)
    control._sync_toggle()
    import pbp_settings
    assert pbp_settings.load(control.folder)['sync'] == '0'
    control._sync_tick(None, None)
    assert len(control.runner.jobs) == jobs, 'turned off: nothing sent'
    control._selection_changed(None, None)
    assert Timer.starts == 1, 'turned off: a selection arms nothing'
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Select in Revit as I click' in labels and 'Rename' not in labels


@check
def legends_read_apart():
    u"""The read puts legends on the Legends tab only, with no Revit
    folders (Revit's browser shows them flat), and views without them."""
    stubbed()
    import pbp_revit

    class Id(object):
        def __init__(self, value):
            self.Value = value

    class FakeView(object):
        IsTemplate = False
        Parameters = []

        def __init__(self, value, name, kind):
            self.Id = Id(value)
            self.Name = name
            self.ViewType = kind
            self.UniqueId = 'uid%d' % value
            self.ViewTemplateId = Id(-1)

        def GetPrimaryViewId(self):
            return Id(-1)

        def GetTypeId(self):
            return Id(-1)
    views = [FakeView(1, 'Level 1', 'FloorPlan'), FakeView(2, 'Key', 'Legend'),
             FakeView(3, 'Section A', 'Section'), FakeView(4, 'Typical Detail', 'DraftingView')]
    pbp_revit._collect = lambda doc, cls: list(views)
    pbp_revit.folders_of = lambda org, element: ['Folder']
    snap = pbp_revit.Snapshot()
    snap.orgs = __import__('pbp_settings').default_orgs()
    ctx = {'placed': {}}
    pbp_revit._read_views(None, snap, ctx)
    pbp_revit._read_views(None, snap, ctx, 'legends')
    assert sorted(l.text for l in snap.tabs['views']) == ['Level 1', 'Section A'], snap.tabs['views']
    assert sorted(l.text for l in snap.tabs['legends']) == ['Key', 'Typical Detail'], \
        'drafting views live with the legends'
    legend = [l for l in snap.tabs['legends'] if l.text == 'Key'][0]
    assert legend.tab == 'legends' and legend.kind == 'legend' and legend.folders == []


@check
def row_template_has_pill():
    u"""The row template draws the pill as its own Border with a shadow,
    bound to fill / edge / pillvis, and the row height to rowh; every
    binding in it is a column of the table."""
    import re
    import pbp_browser
    text = open(os.path.join(HERE, 'Theme.xaml'), encoding='utf-8').read()
    template = text[text.index('x:Key="RowTemplate"'):text.index('</DataTemplate>')]
    assert 'DropShadowEffect' in template and 'CornerRadius="4"' in template
    assert 'Visibility="{Binding pillvis}"' in template and 'Height="{Binding rowh}"' in template
    bound = set(re.findall(r'\{Binding (\w+)\}', template))
    assert bound <= set(pbp_browser.COLUMNS), bound - set(pbp_browser.COLUMNS)
    assert '{Binding bar}' not in template, 'the leaf colour bar is gone'
    import pbp_palette
    for pal in (pbp_palette.DARK, pbp_palette.LIGHT):
        assert pal['PillShadowColor'].startswith('#') and len(pal['PillShadowColor']) == 7



# ============================================================
# 1.3.0
# ============================================================
def sheets_snapshot():
    snap = gradient_snapshot()
    views = dict((l.text, l) for l in snap.tabs['views'])
    snap.tabs['sheets'] = [
        _mleaf('e:80', 'sheets', 'E-101 - Power', 's80', kind='sheet', number='E-101',
               folders=['ELECTRICAL', 'POWER']),
        _mleaf('e:81', 'sheets', 'E-102 - Containment', 's81', kind='sheet', number='E-102',
               folders=['ELECTRICAL', 'CONTAINMENT']),
        _mleaf('e:82', 'sheets', 'M-101 - Heating', 's82', kind='sheet', number='M-101',
               folders=['MECHANICAL', 'HEATING'])]
    snap.tabs['sheets'][0].placed = [views['L1 Power'], snap.tabs['schedules'][0]]
    snap.tabs['sheets'][1].placed = [views['L1 Containment']]
    return snap


@check
def sheets_open_to_views():
    u"""A sheet opens like a folder to the views placed on it (shut to
    start, as in Revit); a heading shows or hides them for every sheet in
    it; a placed view row is the view, not another sheet."""
    control = browser()
    feed(control, sheets_snapshot())
    control.tab = 'sheets'
    control._render()
    row = lambda text: [r for r in control.rows if r.text == text][0]
    power = row('E-101 - Power')
    assert power.opens and not power.expanded and not row('M-101 - Heating').opens
    assert cells(control, power)['chevvis'] == 'Visible'
    assert cells(control, row('M-101 - Heating'))['chevvis'] == 'Hidden'
    assert 'L1 Power' not in [r.text for r in control.rows]
    control._toggle(power)
    texts = [r.text for r in control.rows]
    i = texts.index('E-101 - Power')
    assert texts[i + 1:i + 3] == ['L1 Power', 'Pipe Schedule'], texts
    placed = row('L1 Power')
    assert placed.on_sheet is power.leaf and placed.nested and placed.leaf.tab == 'views'
    assert placed.key != placed.leaf.key, 'a placed view has a row key of its own'
    import pbp_browser
    assert pbp_browser.sheets_of_rows([placed]) == [], 'a placed view is not a sheet to print'
    control._toggle(row('E-101 - Power'))
    assert 'L1 Power' not in [r.text for r in control.rows]
    elec = row('ELECTRICAL')
    control._selected_rows = lambda: [elec]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Show views on sheets' in labels and 'Hide views on sheets' not in labels, labels
    control._sheet_views(elec, True)
    texts = [r.text for r in control.rows]
    assert 'L1 Power' in texts and 'L1 Containment' in texts
    elec = row('ELECTRICAL')
    control._selected_rows = lambda: [elec]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Hide views on sheets' in labels and 'Show views on sheets' not in labels, labels
    control._sheet_views(elec, False)
    assert 'L1 Power' not in [r.text for r in control.rows]
    import pbp_revit
    snap = sheets_snapshot()
    sheet = snap.tabs['sheets'][2]
    sheet.placed = []
    view = snap.tabs['views'][0]

    class Id(object):
        def __init__(self, value):
            self.Value = value
    for i, leaf in enumerate(snap.tabs['views'] + snap.tabs['sheets']):
        leaf.eid = Id(500 + i)
    pbp_revit.attach_placed(snap, {pbp_revit.eid_value(sheet.eid): [pbp_revit.eid_value(view.eid), 999]})
    assert sheet.placed == [view], 'the read hands each sheet the leaves placed on it'
    assert view.sheets == [sheet], '...and each view the sheets it is on'


@check
def heading_menu_folds_inside():
    u"""Right click a heading: Collapse all inside closes every folder in
    it but leaves it open; Expand all inside opens them again."""
    control = browser()
    feed(control, gradient_snapshot())
    control.tab = 'views'
    control._render()
    control._toggle([r for r in control.rows if r.text == 'ELECTRICAL'][0])
    elec = [r for r in control.rows if r.text == 'ELECTRICAL'][0]
    assert not elec.expanded
    control._selected_rows = lambda: [elec]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Collapse all inside' in labels and 'Expand all inside' in labels
    control._fold_inside(elec, True)
    texts = [r.text for r in control.rows]
    i = texts.index('ELECTRICAL')
    assert texts[i + 1:i + 5] == ['CONTAINMENT', 'LIGHTING', 'POWER', 'WORKING'], texts
    assert 'Floor Plans' not in texts[i + 1:i + 6]
    assert 'DUCTWORK' in texts and texts[texts.index('DUCTWORK') + 1] == 'Floor Plans', 'other headings untouched'
    control._fold_inside([r for r in control.rows if r.text == 'ELECTRICAL'][0], False)
    texts = [r.text for r in control.rows]
    assert texts[texts.index('POWER') + 1] == 'Floor Plans'


@check
def favourite_groups():
    u"""A whole folder can be a favourite: under its type on Favourites,
    with everything in it and the colours it has on its own tab; a single
    favourite inside it is shown once; it saves and can be removed."""
    control = browser()
    snap = gradient_snapshot()
    feed(control, snap)
    control.tab = 'views'
    control.colour = True
    control._render()
    power = [r for r in control.rows if r.text == 'POWER'][0]
    source = cells(control, power)
    control._selected_rows = lambda: [power]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Add group to favourites' in labels, labels
    control._add_favourites([[l for l in snap.tabs['views'] if l.text == 'L1 Power'][0],
                             [l for l in snap.tabs['views'] if l.text == 'L1 Heating'][0]])
    control._favourite_group(power.node, True)
    control.tab = 'favourites'
    control._render()
    texts = [r.text for r in control.rows]
    assert texts == ['Views', 'POWER', 'Floor Plans', 'L1 Power', 'L1 Heating'], texts
    fav_power = [r for r in control.rows if r.text == 'POWER'][0]
    assert cells(control, fav_power)['fill'] == source['fill'], 'the group keeps its colours'
    assert control.tab_buttons['favourites'].ToolTip.startswith('Favourites: 2'), \
        control.tab_buttons['favourites'].ToolTip
    import pbp_marks
    back = pbp_marks.Marks.load(control.store.folder, snap.title)
    assert back.fav_groups == [('views', ('ELECTRICAL', 'POWER'))], back.fav_groups
    control._selected_rows = lambda: [fav_power]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Remove group from favourites' in labels, labels
    import pbp_tree
    outer = pbp_tree.find_node(control._root_for('views'), ('ELECTRICAL',))
    roots = pbp_tree.build_favourites({}, {'views': [fav_power.node, outer]})
    assert [n.label for n in roots[0].children] == ['ELECTRICAL'], 'a group inside a group shows once'
    control._favourite_group(fav_power.node, False)
    assert [r.text for r in control.rows] == ['Views', 'L1 Heating', 'L1 Power'], [r.text for r in control.rows]


@check
def sheet_heading_prints():
    u"""Selecting a sheet heading lights Print and Express for every sheet
    under it, and its menu offers to print them all."""
    control = browser()
    feed(control, sheets_snapshot())
    control.tab = 'sheets'
    control._render()
    elec = [r for r in control.rows if r.text == 'ELECTRICAL'][0]
    control._selected_rows = lambda: [elec]
    control._update_toolbar()
    assert control.print_button.IsEnabled is True
    assert sorted(l.number for l in control._selected_sheets()) == ['E-101', 'E-102']
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Print all 2 sheets in ProSheets' in labels and 'Express print all 2 sheets' in labels, labels


@check
def express_needs_the_hook():
    u"""Express asks whether Pro Sheets has its hook first: without it the
    user is told (Pro Sheets would only open its first page) and nothing
    is sent; with it, or with Pro Sheets nowhere to be found, it is sent."""
    import pbp_handoff
    base = tempfile.mkdtemp()
    tab = os.path.join(base, 'RevoBIM PY.tab')
    here = os.path.join(tab, 'Management.panel', 'Project Browser Pro.pushbutton')
    prosheets = os.path.join(tab, 'Sheet Tools.panel', 'Pro Sheets Exporter.pushbutton')
    os.makedirs(here)
    assert pbp_handoff.hook_state(here) == (None, True, '')
    os.makedirs(prosheets)
    with open(os.path.join(prosheets, 'ps_version.py'), 'w') as handle:
        handle.write("__version__ = '1.47.0'\n")
    folder, has_hook, version = pbp_handoff.hook_state(here)
    assert folder == prosheets and has_hook is False and version == '1.47.0'
    open(os.path.join(prosheets, 'ps_express.py'), 'w').close()
    assert pbp_handoff.hook_state(here)[1] is True
    control = browser()
    feed(control, sheets_snapshot())
    import pbp_handoff as live, pbp_ui
    told = []
    pbp_ui.message = lambda title, text, theme: told.append(text)
    live.hook_state = lambda here: ('X', False, '1.47.0')
    sheets = control.snapshot.tabs['sheets'][:1]
    jobs = len(control.runner.jobs)
    control._prosheets('express', sheets)
    assert len(control.runner.jobs) == jobs and told and '1.47.0 has no express hook' in told[0], told
    control._prosheets('print', sheets)
    assert control.runner.jobs[-1][0] == 'prosheets print', 'Print does not need the hook'
    live.hook_state = lambda here: ('X', True, '1.48.0')
    control._prosheets('express', sheets)
    assert control.runner.jobs[-1][0] == 'prosheets express'


@check
def coloured_levels_follow_the_organisation():
    u"""Only the levels ticked in the organisation are coloured main
    headings; the first ticked one is the darkest and largest; none ticked,
    no colour. Legends and Drafting Views are fixed masters above them."""
    control = browser()
    snap = gradient_snapshot()
    snap.orgs['views'] = dict(snap.orgs['views'], colours=[1, 3])
    feed(control, snap)
    control.tab = 'views'
    control.colour = True
    control._render()
    levels = lambda: sorted(set(r.node.level for r in control.rows
                                if r.heading and cells(control, r)['pillvis'] == 'Visible'))
    assert levels() == [1, 3], levels()
    import pbp_browser
    plans = cells(control, [r for r in control.rows if r.text == 'Floor Plans'][0])
    assert plans['size'] == pbp_browser.HEAD_SIZES[2]
    snap.orgs['views'] = dict(snap.orgs['views'], colours=[2])
    feed(control, snap)
    control._render()
    assert levels() == [2]
    power = cells(control, [r for r in control.rows if r.text == 'POWER'][0])
    assert power['size'] == pbp_browser.HEAD_SIZES[1], 'the first coloured level is the main one'
    snap.orgs['views'] = dict(snap.orgs['views'], colours=[])
    feed(control, snap)
    control._render()
    assert levels() == [] and control.plan == {}


@check
def legends_and_drafting_masters():
    u"""Legends and drafting views are the Legends tab's two sub tabs, a
    grey strip under the search box - one shown at a time, the choice
    kept. On the All tab they stay two fixed, bold master headings."""
    control = browser()
    snap = snapshot_for_tests()
    snap.tabs['legends'] = [
        _mleaf('e:90', 'legends', 'Typical Detail', 'd1', kind='drafting', values={'View Template': 'X'}),
        _mleaf('e:92', 'legends', 'Riser Detail', 'd2', kind='drafting', values={'View Template': 'X'}),
        _mleaf('e:91', 'legends', 'Symbols', 'l1', kind='legend', values={'View Template': 'X'})]
    feed(control, snap)
    import pbp_browser, pbp_tree, pbp_settings
    control.tab = 'legends'
    control._render()
    texts = lambda: [r.text for r in control.rows]
    assert control.legend_sub == pbp_tree.LEGENDS and texts() == ['Symbols'], texts()
    assert control.sub_texts[pbp_tree.LEGENDS].Text == 'Legends  1'
    assert control.sub_texts[pbp_tree.DRAFTING].Text == 'Drafting Views  2'
    control._show_sub(pbp_tree.DRAFTING)
    assert texts() == ['Riser Detail', 'Typical Detail'], texts()
    assert pbp_settings.load(control.folder)['legend_sub'] == pbp_tree.DRAFTING, 'the choice is kept'
    again = pbp_browser_for(control)
    assert again.legend_sub == pbp_tree.DRAFTING
    assert pbp_browser.legend_sub('nonsense') == pbp_tree.LEGENDS
    # searching: the other sub tab's matches are counted, and said so
    control.search_words = ['symb']
    control._render()
    assert texts() == [] and control.sub_texts[pbp_tree.LEGENDS].Text == 'Legends  1'
    assert control.sub_texts[pbp_tree.DRAFTING].Text == 'Drafting Views  0', 'counts are of matches'
    assert 'in Legends' in control._legend_empty_text(), control._legend_empty_text()
    control.search_words = []
    # Revit's selection on the other sub tab: go there
    control._reveal(['e:91'])
    assert control.legend_sub == pbp_tree.LEGENDS and texts() == ['Symbols']
    # the All tab keeps the masters as headings
    control.tab = 'all'
    control._render()
    master = [r for r in control.rows if r.text == 'Legends' and not r.is_root][0]
    cell = cells(control, master)
    assert cell['weight'] == 'Bold' and cell['size'] == pbp_browser.MASTER_SIZE
    assert cell['rowh'] == pbp_browser.MASTER_HEIGHT and cell['pillvis'] == 'Collapsed'
    assert pbp_tree.TAB_LABELS['legends'] == 'Legends and Drafting Views'
    assert control._colour_levels('legends') == set([2, 3]), 'the organisation\'s levels sit below the masters'
    # none of one kind
    snap.tabs['legends'] = snap.tabs['legends'][2:]
    feed(control, snap)
    control.tab = 'legends'
    control._show_sub(pbp_tree.DRAFTING)
    assert texts() == [] and control._legend_empty_text() == 'No drafting views in this model.'
    xaml = open(os.path.join(HERE, 'Browser.xaml'), encoding='utf-8').read()
    assert xaml.index('x:Name="SearchBox"') < xaml.index('x:Name="SubTabs"') < xaml.index('x:Name="OrgText"'), \
        'the sub tabs sit under the search box'


@check
def view_icons_are_plain():
    u"""Every view kind and discipline symbol makes a well formed framed
    icon; sheets, schedules and families keep their own coloured icons."""
    import pbp_icons, pbp_disc
    for kind in pbp_icons.VIEW_KINDS:
        assert path_ok(pbp_icons.framed(pbp_icons.icon_for(kind))), kind
    for key in pbp_disc.keys():
        assert path_ok(pbp_icons.framed(pbp_disc.icon(key))), key
    assert pbp_icons.scaled('M0,0 L12,12 A2,2 0 1 0 4,4 Z', 0.5, (1, 1)) == \
        'M 1,1 L 7,7 A 1,1 0 1 0 3,3 Z'
    control = browser()
    feed(control, snapshot_for_tests())
    control.tab = 'sheets'
    control._render()
    sheet = cells(control, [r for r in control.rows if r.leaf is not None][0])
    assert not sheet['icon'].startswith('F0 ' + pbp_icons.FRAME), 'a sheet keeps its own icon'


@check
def popped_out_beside():
    u"""A window opened from the browser takes its size and goes beside
    it: left when it fits, else right, kept on screen."""
    import pbp_browser
    beside = pbp_browser.beside
    assert beside(1000, 100, 350, 800, 0, 1920, 0, 1080) == (642.0, 100.0, 350.0, 800.0)
    assert beside(100, 100, 350, 800, 0, 1920, 0, 1080) == (458.0, 100.0, 350.0, 800.0)
    assert beside(1600, 100, 350, 800, 1500, 450, 0, 1080) == (1600.0, 100.0, 350.0, 800.0)
    assert beside(1000, 900, 350, 800, 0, 1920, 0, 1080)[1] == 280.0, 'kept on screen'
    assert beside(1000, 100, 120, 100, 0, 1920, 0, 1080)[2:] == (300.0, 360.0), 'never smaller than usable'
    control = browser()
    feed(control, snapshot_for_tests())
    import pbp_store, pbp_window
    control._placement = lambda: (10.0, 20.0, 330.0, 700.0)
    pbp_store.domain_set(pbp_store.PANES_KEY, 'registered')
    control._pop_out('views')
    guid = __import__('pbp_panes').guid_for('views')
    assert pbp_store.domain_get(pbp_store.PLACE_KEY + guid) == '10.0,20.0,330.0,700.0'
    pbp_store.domain_set(pbp_store.PANES_KEY, '')
    opened = []
    pbp_window.open_floating = lambda tab, placement=None: opened.append((tab, placement))
    control._pop_out('sheets')
    assert opened == [('sheets', (10.0, 20.0, 330.0, 700.0))], opened
    pane = __import__('pbp_browser').BrowserControl('pane', 'views')
    assert pane.pane_guid == guid


@check
def open_the_sheet_a_view_is_on():
    u"""Right click a view (or schedule) placed on a sheet: Open sheet ..."""
    control = browser()
    snap = sheets_snapshot()
    power = [l for l in snap.tabs['views'] if l.text == 'L1 Power'][0]
    power.sheets = [snap.tabs['sheets'][0]]
    feed(control, snap)
    control.tab = 'views'
    control._render()
    row = [r for r in control.rows if r.text == 'L1 Power'][0]
    control._selected_rows = lambda: [row]
    seen = menu_headers(control, lambda: control._list_menu_opening(None, None))
    labels = [h for h, f, e in seen]
    assert 'Open sheet E-101 - Power' in labels, labels
    import pbp_revit
    opened = []
    pbp_revit.open_leaves = lambda app, leaves: opened.extend(l.text for l in leaves) or {'opened': 1, 'failed': []}
    [f for h, f, e in seen if h == 'Open sheet E-101 - Power'][0]()
    control.runner.jobs[-1][1](None)
    assert opened == ['E-101 - Power'], opened
    other = [r for r in control.rows if r.text == 'L1 Heating'][0]
    control._selected_rows = lambda: [other]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert not [h for h in labels if h.startswith('Open sheet')], 'not on a sheet: no item'


@check
def follows_revit_selection():
    u"""What Revit selects (a view in its browser, a viewport, a type) is
    found here: its folders open and it is selected - unless it is the
    browser's own selection coming back, or following is turned off."""
    control = browser()
    snap = gradient_snapshot()
    feed(control, snap)
    control.tab = 'views'
    control._render()
    control._collapse_all()
    import pbp_store
    heating = [l for l in snap.tabs['views'] if l.text == 'L1 Heating'][0]
    picked = []
    control._reselect = lambda keys: picked.append(set(keys))
    pbp_store.publish_selection([('view', heating.key)])
    control._follow_tick(None, None)
    assert picked and picked[-1] == set([heating.key]), picked
    assert 'L1 Heating' in [r.text for r in control.rows], 'its folders opened'
    assert 'Found 1 item' in control.status.Text
    picked[:] = []
    control._follow_tick(None, None)
    assert picked == [], 'nothing new: nothing done'
    control.last_synced = set([heating.key])
    pbp_store.publish_selection([('view', 'e:999')])
    pbp_store.publish_selection([('view', heating.key)])
    control._follow_tick(None, None)
    assert picked == [], 'the browser\'s own selection coming back is not found again'
    control.last_synced = set()
    pbp_store.publish_selection([('type', heating.key)])
    control._follow_tick(None, None)
    assert picked == [], 'a type is only followed on the Families tab'
    control._follow_toggle()
    pbp_store.publish_selection([('view', heating.key)])
    control._follow_tick(None, None)
    assert picked == [] and control.follow is False
    import pbp_settings
    assert pbp_settings.load(control.folder)['follow'] == '0'
    # the Revit side: what a selection is, as browser keys
    import pbp_revit

    class Id(object):
        def __init__(self, value):
            self.Value = value
    viewport = pbp_revit.Viewport()
    viewport.ViewId = Id(11)
    view = pbp_revit.View()
    view.Id = Id(12)
    placed = type('Placed', (), {'ScheduleId': Id(13)})()
    duct = type('Duct', (), {'GetTypeId': lambda self: Id(14)})()
    by_id = {1: viewport, 2: view, 3: placed, 4: duct}

    class Doc(object):
        def GetElement(self, eid):
            return by_id.get(eid.Value)
    targets = pbp_revit.selection_targets(Doc(), [Id(1), Id(2), Id(3), Id(4), Id(9)])
    assert targets == [('view', 'e:11'), ('view', 'e:12'), ('view', 'e:13'), ('type', 'e:14')], targets
    import pbp_dock

    chosen = [Id(2)]

    class Sel(object):
        def GetElementIds(self):
            return list(chosen)

    class UIDoc(object):
        Selection = Sel()
        Document = Doc()
    app = type('App', (), {'ActiveUIDocument': UIDoc()})()
    pbp_dock.LAST_SELECTION[:] = [0.0, '']
    before = pbp_store.selection_count()
    assert pbp_dock.watch_selection(app, now=100.0) is True
    assert pbp_store.read_selection() == [('view', 'e:12')] and pbp_store.selection_count() == before + 1
    assert pbp_dock.watch_selection(app, now=101.0) is False, 'unchanged: nothing published'
    chosen[:] = [Id(1)]
    assert pbp_dock.watch_selection(app, now=101.1) is False, 'not read again so soon'
    assert pbp_dock.watch_selection(app, now=102.0) is True
    count = pbp_store.selection_count()
    assert pbp_store.publish_selection([('view', 'e:11')]) is False and pbp_store.selection_count() == count, \
        'the same selection again is no news'


@check
def drag_views_onto_a_sheet():
    u"""Views dragged onto a sheet row (in any browser window) are placed on
    that sheet, centred; released outside the browsers, on the sheet open
    in Revit; the menu offers the open sheet too; pressing one of several
    selected views keeps them all for the drag."""
    control = browser()
    snap = sheets_snapshot()
    feed(control, snap)
    control.tab = 'all'
    control._render()
    views = [l for l in snap.tabs['views'] if l.text in ('L1 Lighting', 'L1 Working')]
    sheet = snap.tabs['sheets'][2]
    row = [r for r in control.rows if r.leaf is views[0]][0]
    import pbp_revit, pbp_browser
    sent = []
    pbp_revit.place_on_sheet = lambda app, eid, leaves: sent.append(('sheet', eid, [l.text for l in leaves])) or \
        {'ok': True, 'placed': len(leaves), 'refused': [], 'sheet': 'M-101 - Heating'}
    pbp_revit.place_on_active_sheet = lambda app, x, y, leaves: sent.append(('open', x, [l.text for l in leaves])) or \
        {'ok': False, 'why': 'The view open in Revit is not a sheet - open a sheet first.', 'placed': 0,
         'refused': []}
    control._sheet_under = lambda point: sheet if point.X < 300 else None
    drag = {'row': row, 'start': _P(10, 10), 'live': True, 'leaves': views, 'keep': False}
    # over a sheet in a browser: a place to drop, said in the status line

    class Payload(object):
        def GetDataPresent(self, name):
            return name == pbp_browser.DRAG_FORMAT

    class Over(object):
        Data = Payload()
        Effects = None
        Handled = False

        def __init__(self, x):
            self.point = _P(x, 40)

        def GetPosition(self, element):
            return self.point
    pbp_browser.DRAGGING[0] = drag
    over = Over(40)
    control._drag_over(None, over)
    assert over.Effects is pbp_browser.DragDropEffects.Copy and over.Handled
    assert control.status.Text.startswith('Release to place 2 views on M-101 - Heating'), control.status.Text
    off = Over(500)
    control._drag_over(None, off)
    assert off.Effects is pbp_browser.NO_DROP
    control._drop(None, Over(40))
    assert drag['target'] is sheet, 'dropped on the sheet row'
    pbp_browser.DRAGGING[0] = None
    control._finish_drag(drag, ('sheet', sheet))
    name, work, done = control.runner.jobs[-1]
    done(work(None), None)
    assert sent[-1] == ('sheet', sheet.eid, ['L1 Lighting', 'L1 Working']), sent
    assert control.status.Text.startswith('Placed 2 views on M-101 - Heating, centred.')
    control._finish_drag(drag, ('outside', (2000.0, 500.0)))
    name, work, done = control.runner.jobs[-1]
    done(work(None), None)
    assert sent[-1] == ('open', 2000.0, ['L1 Lighting', 'L1 Working']) and 'not a sheet' in control.status.Text
    jobs = len(control.runner.jobs)
    control._finish_drag(drag, ('inside', None))
    control._finish_drag(drag, ('cancel', None))
    assert len(control.runner.jobs) == jobs and control.status.Text.startswith('Drop the views on a sheet')
    # no drag needed: the menu places on the open sheet
    control._selected_rows = lambda: [row]
    seen = menu_headers(control, lambda: control._list_menu_opening(None, None))
    [f for h, f, e in seen if h == 'Place on the open sheet (centred)'][0]()
    control.runner.jobs[-1][1](None)
    assert sent[-1] == ('open', None, ['L1 Lighting']), sent
    # a click (no drag) on one of several selected views selects just it
    picked = []
    control._reselect = lambda keys: picked.append(set(keys))
    control.drag = dict(drag, live=False, keep=True)
    control._mouse_up(None, _MouseArgs(40, 60))
    assert picked == [set([row.key])]
    # the Revit side refuses a drop that is not on a sheet
    stubbed()
    import pbp_revit as revit

    class Area(object):
        Left, Top, Right, Bottom = 0, 0, 1000, 800
    app = type('App', (), {'DrawingAreaExtents': Area(),
                           'ActiveUIDocument': type('U', (), {'ActiveView': object()})()})()
    assert 'not a sheet' in revit.place_on_active_sheet(app, 500, 400, [])['why']
    assert 'Drop the views on a sheet' in revit.place_on_active_sheet(app, 1500, 400, [])['why']
    assert 'not a sheet' in revit.place_on_active_sheet(app, None, None, [])['why'], \
        'from the menu: no drop point to check'


@check
def group_colours_override():
    u"""A colour given to a group in Browser Organisation replaces its
    automatic gradient colour; the dialog lists the coloured groups, sets
    and clears colours, and they save with the organisation."""
    control = browser()
    snap = gradient_snapshot()
    snap.orgs['views'] = dict(snap.orgs['views'], group_colours={'POWER': '#123456'})
    feed(control, snap)
    control.tab = 'views'
    control.colour = True
    control._render()
    import pbp_palette
    power = cells(control, [r for r in control.rows if r.text == 'POWER'][0])
    assert power['fill'] == '#123456' and power['fore'] == pbp_palette.text_on('#123456')
    light = cells(control, [r for r in control.rows if r.text == 'LIGHTING'][0])
    assert light['fill'] != '#123456', 'only that group'
    groups = control.heading_groups('views')
    names = [(level, name) for level, name, colour, coloured in groups]
    assert names[:3] == [(1, 'COORDINATION'), (2, 'MODEL'), (3, 'Floor Plans')], names
    assert (3, 'Power Plans') in names, 'every level is listed, not only the coloured ones'
    info = dict(((l, n), (c, k)) for l, n, c, k in groups)
    assert info[(2, 'POWER')] == ('#123456', True) and info[(3, 'Floor Plans')] == ('', False)
    import pbp_orgwin, pbp_settings
    win = pbp_orgwin.OrganisationWindow('views', snap.orgs['views'], ['Name'], 'BGL', 'dark',
                                        groups=groups)
    assert len(win.group_names) == len(groups)
    win.show_level(3)
    assert win.group_names and set(l for l, n in win.group_names) == set([3]), win.group_names
    win.show_level(None)
    win._set_group_colour('#FF0000', [(1, 'ELECTRICAL')])
    win._set_group_colour('#0000FF', [(3, 'Power Plans')])
    win._set_group_colour('#00FF00', [(2, 'POWER')])
    win._set_group_colour('', [(2, 'POWER')])
    win._apply(None, None)
    assert win.result['group_colours'] == {pbp_settings.group_key(1, 'ELECTRICAL'): '#FF0000',
                                           pbp_settings.group_key(3, 'Power Plans'): '#0000FF'}, win.result
    snap.orgs['views'] = win.result
    feed(control, snap)
    control._render()
    plans = cells(control, [r for r in control.rows if r.text == 'Power Plans'][0])
    assert plans['pillvis'] == 'Visible' and plans['fill'] == '#0000FF', \
        'a value on an uncoloured level can still have a colour of its own'
    other = cells(control, [r for r in control.rows if r.text == 'Floor Plans'][0])
    assert other['pillvis'] == 'Collapsed', 'only that level\'s value'
    folder = tempfile.mkdtemp()
    orgs = pbp_settings.default_orgs()
    orgs['views'] = dict(win.result, group_colours={'A|B=C': '#00FF00', 'Bad': 'red'})
    pbp_settings.save_orgs(folder, 'P', orgs)
    assert pbp_settings.load_orgs(folder, 'P')['views']['group_colours'] == {'A|B=C': '#00FF00'}, \
        'odd names survive the file; a colour that is not #RRGGBB does not'
    choices = pbp_palette.choice_colours()
    assert len(choices) == 31 and all(c in choices for c in pbp_palette.GREYS), 'greys to choose from'
    # colours of the user's own join the choices, for every tab, and can go
    assert win.add_custom('#abcdef') == '#ABCDEF' and '#ABCDEF' in pbp_palette.choice_colours(win.custom)
    again = pbp_orgwin.OrganisationWindow('sheets', snap.orgs['sheets'], ['Name'], 'BGL', 'dark')
    assert again.custom == ['#ABCDEF'], 'kept in the settings'
    again._remove_custom('#ABCDEF')
    assert pbp_orgwin.OrganisationWindow('views', snap.orgs['views'], ['Name'], 'BGL', 'dark').custom == []
    win._picked_groups = lambda: [(1, 'MECHANICAL')]
    pbp_orgwin.pick_colour = lambda start='': '#112233'
    win._add_colour(None, None)
    assert win.org['group_colours'][pbp_settings.group_key(1, 'MECHANICAL')] == '#112233'
    assert '#112233' in win.custom


@check
def docking_set_up_and_toggle():
    u"""Where Revit never took the panels (no block in startup.py) the Dock
    button offers to add it - appended once, the old file kept, nothing in
    it changed. Dock shows the panel and closes the window; Undock hides the
    panel and opens a window in its place."""
    import pbp_startup
    base = tempfile.mkdtemp()
    ext = os.path.join(base, 'RevoBIM PY.extension')
    here = os.path.join(ext, 'RevoBIM PY.tab', 'Management.panel', 'Project Browser Pro.pushbutton')
    os.makedirs(here)
    assert pbp_startup.extension_root(here) == ext
    assert pbp_startup.state(here)[0] == 'no_file'
    startup = os.path.join(ext, 'startup.py')
    with io.open(startup, 'w', encoding='utf-8') as handle:
        handle.write(u'# easter egg\nEGG = 1\n')
    assert pbp_startup.state(here) == ('missing', startup)
    ok, line = pbp_startup.install(here, now=0)
    assert ok and 'kept as' in line, line
    text = io.open(startup, encoding='utf-8').read()
    assert text.startswith(u'# easter egg\nEGG = 1\n') and text.count(pbp_startup.MARKER) == 1
    backups = [n for n in os.listdir(ext) if n.endswith('.bak')]
    assert len(backups) == 1 and io.open(os.path.join(ext, backups[0]), encoding='utf-8').read() == \
        u'# easter egg\nEGG = 1\n'
    assert pbp_startup.state(here)[0] == 'present'
    ok, line = pbp_startup.install(here)
    again = io.open(startup, encoding='utf-8').read()
    assert ok and again.count(pbp_startup.MARKER) == 1 and again.startswith(u'# easter egg'), 'never twice'
    ast.parse(io.open(startup, encoding='utf-8').read())
    assert pbp_startup.state(tempfile.mkdtemp())[0] == 'no_extension'
    # the button
    pane = browser('sheets')
    import pbp_browser, pbp_window, pbp_ui, pbp_store, pbp_revit, pbp_panes
    assert pane.dock_text.Text == 'Undock'
    pane._placement = lambda: (1.0, 2.0, 300.0, 600.0)
    floated = []
    pbp_window.open_floating = lambda tab, placement=None: floated.append((tab, placement))
    pane._dock_clicked(None, None)
    name, work, done = pane.runner.jobs[-1]
    hidden = []
    pbp_revit.hide_pane = lambda app, guid: hidden.append(guid) or {'ok': True}
    done(work(None), None)
    assert hidden == [pbp_panes.guid_for('sheets')] and floated == [('sheets', (1.0, 2.0, 300.0, 600.0))]
    window = browser('sheets', host='window')
    import pbp_window, pbp_ui, pbp_store, pbp_revit, pbp_panes, pbp_startup
    assert window.dock_text.Text == 'Dock'
    closed = []
    window.window = type('W', (), {'close': lambda self: closed.append(1)})()
    told, asked, installed = [], [], []
    pbp_ui.message = lambda title, text, theme: told.append(text)
    pbp_ui.confirm = lambda title, text, theme, ok_text='Yes': asked.append(text) or True
    pbp_startup.state = lambda here: ('missing', 'C:/x/startup.py')
    pbp_startup.install = lambda here: installed.append(here) or (True, 'Added the docking block.')
    pbp_store.domain_set(pbp_store.PANES_KEY, '')
    window._dock_clicked(None, None)
    assert asked and installed and 'Restart Revit' in told[-1] and not closed
    pbp_startup.state = lambda here: ('present', 'C:/x/startup.py')
    asked[:] = []
    window._dock_clicked(None, None)
    assert not asked and 'Restart Revit' in told[-1], 'block there but not taken: restart, nothing added'
    pbp_store.domain_set(pbp_store.PANES_KEY, 'registered')
    shown = []
    pbp_revit.show_pane = lambda app, guid: shown.append(guid) or {'ok': True}
    window._dock_clicked(None, None)
    name, work, done = window.runner.jobs[-1]
    done(work(None), None)
    assert shown == [pbp_panes.guid_for('sheets')] and closed == [1], 'docked: the window closes'


@check
def highlights_and_heading_colour():
    u"""Right click > Highlight marks rows, more can be added, and they stay
    marked - through renders - until Turn off highlight. A coloured
    heading's menu sets its colour right there, saved with the tab's
    organisation; More colours... adds one of your own; Automatic undoes."""
    control = browser()
    snap = gradient_snapshot()
    feed(control, snap)
    control.tab = 'views'
    control.colour = True
    control._render()
    row = lambda text: [r for r in control.rows if r.text == text][0]
    power, heating = row('L1 Power'), row('L1 Heating')
    control._selected_rows = lambda: [power]
    seen = menu_headers(control, lambda: control._list_menu_opening(None, None))
    [f for h, f, e in seen if h == 'Highlight'][0]()
    control._selected_rows = lambda: [row('L1 Heating')]
    seen = menu_headers(control, lambda: control._list_menu_opening(None, None))
    labels = [h for h, f, e in seen]
    assert 'Turn off highlight (1)' in labels, labels
    [f for h, f, e in seen if h == 'Highlight'][0]()
    import pbp_palette
    marked = cells(control, row('L1 Power'))
    assert marked['pillvis'] == 'Visible' and marked['fill'] == pbp_palette.highlight(control.theme_name)[0]
    control._expand_all()
    assert cells(control, row('L1 Heating'))['fill'] == pbp_palette.highlight(control.theme_name)[0], \
        'highlights stay through a render'
    control._selected_rows = lambda: [row('L1 Power')]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Remove highlight' in labels and 'Turn off highlight (2)' in labels, labels
    control._clear_highlights()
    assert cells(control, row('L1 Power'))['pillvis'] == 'Collapsed' and not control.highlights
    # a heading's colour from its menu
    elec = row('ELECTRICAL')
    control._selected_rows = lambda: [elec]
    seen = menu_headers(control, lambda: control._list_menu_opening(None, None))
    labels = [h for h, f, e in seen]
    assert 'More colours...' in labels and 'Automatic colour' not in labels, labels
    heard = []
    control.store.subscribe(lambda s, how: heard.append(how))
    control.set_heading_colour(elec.node, '#445566')
    import pbp_settings, pbp_store
    assert control._org('views')['group_colours'] == {pbp_settings.group_key(1, 'ELECTRICAL'): '#445566'}
    assert pbp_settings.load_orgs(control.store.folder, snap.title)['views']['group_colours'] == \
        {pbp_settings.group_key(1, 'ELECTRICAL'): '#445566'}, 'saved with the organisation'
    assert heard and heard[-1] == pbp_store.MARKS, 'every pane redraws'
    assert cells(control, row('ELECTRICAL'))['fill'] == '#445566'
    control._selected_rows = lambda: [row('ELECTRICAL')]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'Automatic colour' in labels
    import pbp_orgwin
    pbp_orgwin.pick_colour = lambda start='': '#ABCDEF'
    control._heading_more_colours(row('POWER').node)
    assert cells(control, row('POWER'))['fill'] == '#ABCDEF'
    assert '#ABCDEF' in pbp_settings.custom_colours(pbp_settings.load(control.folder)), 'joins your colours'
    control.set_heading_colour(row('ELECTRICAL').node, '')
    assert cells(control, row('ELECTRICAL'))['fill'] != '#445566'
    plans = row('Floor Plans')
    control._selected_rows = lambda: [plans]
    labels = [h for h, f, e in menu_headers(control, lambda: control._list_menu_opening(None, None))]
    assert 'More colours...' not in labels, 'an uncoloured heading has no colour to change'


@check
def colour_modes_and_settings():
    u"""The colour button cycles Colour, Greyscale, Custom. Custom is grey
    except headings given a colour of their own. Highlighted rows take the
    settings' fill and text (white bold on dark by default). The settings
    window sets all of it, and every browser takes it up."""
    control = browser()
    snap = gradient_snapshot()
    import pbp_settings
    snap.orgs['views'] = dict(snap.orgs['views'],
                              group_colours={pbp_settings.group_key(2, 'POWER'): '#123456'})
    feed(control, snap)
    control.tab = 'views'
    control._render()
    import pbp_palette, pbp_store
    row = lambda text: [r for r in control.rows if r.text == text][0]
    assert control.colour_mode == 'colour'
    assert cells(control, row('LIGHTING'))['fill'] not in (pbp_palette.grey_pill(2, 'dark')[0],
                                                           pbp_palette.grey_pill(2, 'light')[0])
    control._colour_toggle(None, None)
    assert control.colour_mode == 'grey' and pbp_settings.load(control.folder)['colour'] == 'grey'
    grey = pbp_palette.grey_pill(2, control.theme_name)[0]
    assert cells(control, row('POWER'))['fill'] == grey, 'greyscale: even a colour of its own is grey'
    control._colour_toggle(None, None)
    assert control.colour_mode == 'custom' and 'Custom' in control.status.Text
    assert cells(control, row('LIGHTING'))['fill'] == grey, 'custom: grey by default'
    assert cells(control, row('POWER'))['fill'] == '#123456', 'custom: a colour of its own shows'
    assert cells(control, row('POWER'))['fore'] == pbp_palette.text_on('#123456')
    control._colour_toggle(None, None)
    assert control.colour_mode == 'colour'
    assert cells(control, row('POWER'))['fill'] == '#123456', 'colour: its own colour wins too'
    # highlights from the settings
    control.highlights = set([row('L1 Power').key])
    control.theme_name = 'dark'
    lit = cells(control, row('L1 Power'))
    assert lit['fore'] == '#FFFFFF' and lit['weight'] == 'Bold', 'dark: white bold text'
    assert lit['fill'] == control.settings['highlight_dark']
    control.theme_name = 'light'
    assert cells(control, row('L1 Power'))['fill'] == control.settings['highlight_light']
    # the settings window
    import pbp_setwin
    win = pbp_setwin.SettingsWindow(control.settings, 'dark')
    win._mode('custom')(None, None)
    win.set_colour('highlight_dark', '#000080')
    win.set_colour('highlight_dark_text', '#ffff00')
    win.set_colour('highlight_dark', 'not a colour')
    win.bold.IsChecked = False
    win._bold(None, None)
    win.add_custom('#ABCDEF')
    win.add_custom('#ABCDEF')
    win.add_custom('#112233')
    win._dropper('#112233')(None, type('A', (), {'Handled': False})())
    win._save(None, None)
    result = win.result
    assert result['colour'] == 'custom' and result['highlight_dark'] == '#000080'
    assert result['highlight_dark_text'] == '#FFFF00' and result['highlight_bold'] == '0'
    assert pbp_settings.custom_colours(result) == ['#ABCDEF']
    other = pbp_browser_for(control)
    pbp_setwin.ask = lambda settings, theme: result
    control.theme_name = 'dark'
    control._settings_clicked(None, None)
    lit = cells(control, row('L1 Power'))
    assert lit['fill'] == '#000080' and lit['fore'] == '#FFFF00' and lit['weight'] != 'Bold'
    assert control.colour_mode == 'custom'
    other._tick(None, None)
    assert other.colour_mode == 'custom', 'the other browsers take the settings up'
    win2 = pbp_setwin.SettingsWindow(control.settings, 'dark')
    win2._reset(None, None)
    win2._cancel(None, None)
    assert win2.result is None


def pbp_browser_for(control):
    u"""A second browser in the same engine as this one (same store)."""
    import pbp_browser
    other = pbp_browser.BrowserControl('pane', 'views')
    other.runner = FakeRunner()
    return other


@check
def placed_views_marked_blue():
    u"""A view on a sheet has the inside of its frame icon in blue; one on
    no sheet does not."""
    control = browser()
    snap = sheets_snapshot()
    power = [l for l in snap.tabs['views'] if l.text == 'L1 Power'][0]
    power.sheets = [snap.tabs['sheets'][0]]
    feed(control, snap)
    control.tab = 'views'
    control._render()
    import pbp_icons, pbp_palette
    row = lambda text: [r for r in control.rows if r.text == text][0]
    on = cells(control, row('L1 Power'))
    off = cells(control, row('L1 Heating'))
    for theme in ('dark', 'light'):
        control.theme_name = theme
        on = cells(control, row('L1 Power'))
        assert on['iconback'] == pbp_icons.INNER and on['iconbackfill'] == pbp_palette.palette(theme)['OnSheetBrush']
    assert off['iconback'] == pbp_icons.NO_INNER and off['iconbackfill'] == pbp_palette.TRANSPARENT
    assert path_ok(pbp_icons.INNER) and path_ok(pbp_icons.NO_INNER)
    text = open(os.path.join(HERE, 'Theme.xaml'), encoding='utf-8').read()
    template = text[text.index('x:Key="RowTemplate"'):text.index('</DataTemplate>')]
    assert template.index('{Binding iconback}') < template.index('{Binding icon}'), 'the blue sits behind the symbol'

@check
def favourites_type_tabs():
    u"""The Favourites tab repeats the header tabs under the search box -
    every type's icon and count - and shows all of them (under their type
    headings) or one type (without its heading). The choice is kept."""
    control = browser()
    snap = snapshot_for_tests()
    feed(control, snap)
    control._add_favourites([snap.tabs['views'][0]] + snap.tabs['sheets'])
    control.tab = 'favourites'
    control._render()
    import pbp_browser, pbp_settings
    texts = lambda: [r.text for r in control.rows]
    count = lambda tab: control.fav_counts[tab].Text
    assert control.fav_sub == 'all' and 'Views' in texts() and 'Sheets' in texts(), texts()
    assert [t for t, b, i, c in pbp_browser.FAV_SUBS] == ['all'] + list(__import__('pbp_tree').TAB_ORDER), \
        'every header tab but Favourites itself, in the header\'s order'
    assert (count('all'), count('views'), count('sheets'), count('families')) == ('3', '1', '2', '0')
    control._show_fav('sheets')
    assert texts() == ['M-01 - Plan', 'M-02 - Plan'] and control.rows[0].level == 0, texts()
    assert pbp_settings.load(control.folder)['fav_sub'] == 'sheets', 'the choice is kept'
    assert pbp_browser_for(control).fav_sub == 'sheets'
    control.search_words = ['m-01']
    control._render()
    assert (count('all'), count('sheets'), count('views')) == ('1', '1', '0'), 'counts are of matches'
    control.search_words = []
    control._show_fav('families')
    assert texts() == [] and 'families and types' in control.empty_text.Text, control.empty_text.Text
    control._show_fav('all')
    assert control.rows[0].is_root
    assert pbp_browser.fav_sub('nonsense') == 'all'
    xaml = open(os.path.join(HERE, 'Browser.xaml'), encoding='utf-8').read()
    assert xaml.index('x:Name="SearchBox"') < xaml.index('x:Name="FavTabs"') < xaml.index('x:Name="OrgText"')


@check
def search_text_starts_left():
    u"""The search box's text and hint start at the left (just past the
    magnifier), set outright - TextAlignment is inherited from whatever
    Revit's pane host sets above us."""
    theme = open(os.path.join(HERE, 'Theme.xaml'), encoding='utf-8').read()
    style = theme[theme.index('<Style TargetType="TextBox">'):]
    style = style[:style.index('</Style>')]
    for needed in ('Property="TextAlignment" Value="Left"', 'Property="HorizontalContentAlignment" Value="Left"',
                   'Style="{DynamicResource TextHostScroller}"', 'HorizontalAlignment="Left" TextAlignment="Left"'):
        assert needed in style, needed
    # 1.7.3: the scroller inside the box has a template of its own, so an
    # implicit ScrollViewer style from Revit's UI cannot centre the text
    scroller = theme[theme.index('x:Key="TextHostScroller"'):]
    scroller = scroller[:scroller.index('</Style>')]
    assert 'Property="OverridesDefaultStyle" Value="True"' in scroller
    assert 'PART_ScrollContentPresenter' in scroller and 'HorizontalAlignment="Stretch"' in scroller
    xaml = open(os.path.join(HERE, 'Browser.xaml'), encoding='utf-8').read()
    box = xaml[xaml.index('x:Name="SearchBox"'):]
    box = box[:box.index('/>')]
    assert 'TextAlignment="Left"' in box and 'HorizontalContentAlignment="Left"' in box
    padding = re.search(r'Padding="(\d+),', box).group(1)
    assert 24 <= int(padding) <= 30, 'text starts just past the magnifier, not further in'


@check
def favourites_organised():
    u"""Each type's favourites can have a Browser Organisation of their own,
    apart from the type's tab: grouped and coloured that way on the
    Favourites tab, saved with the project's organisations, its values read,
    and offered from the toolbar, the tab and the list."""
    control = browser()
    snap = snapshot_for_tests()
    feed(control, snap)
    import pbp_settings, pbp_revit, pbp_orgwin, pbp_tree
    from pbp_tree import Leaf
    control._add_favourites(snap.tabs['views'] + snap.tabs['sheets'])
    control.tab = 'favourites'
    control._render()
    texts = lambda: [r.text for r in control.rows]
    assert texts() == ['Views', 'Level 1', 'Section A', 'Sheets', 'M-01 - Plan', 'M-02 - Plan'], \
        'no organisation yet: as before'
    control.store.save_org('fav.views', {'source': 'revit'})
    control.roots = {}
    control.colour_mode = 'colour'
    # a view with a dependent nested under it on the Views tab: the
    # dependent belongs to that tab, not to the favourites' folders
    snap.tabs['views'][0].children = [Leaf('e:77', 'views', 'dependent', 'Level 1 - A', uid='u77')]
    control._render()
    snap.tabs['views'][0].children = []
    assert texts() == ['Views', 'Mech', 'Floor Plans', 'Level 1', 'Sections', 'Section A',
                       'Sheets', 'M-01 - Plan', 'M-02 - Plan'], texts()
    mech = [r for r in control.rows if r.text == 'Mech'][0]
    assert mech.node.key.startswith('g:fav.views|') and mech.node.org_key == 'fav.views', \
        'its own folders, never the Views tab\'s'
    assert mech.node.key in control.plan and cells(control, mech)['pillvis'] == 'Visible', \
        'coloured by its own organisation'
    assert control._colour_levels('fav.views') == set([1, 2])
    control.set_heading_colour(mech.node, '#123456')
    assert control._org('fav.views')['group_colours'] and not control._org('views')['group_colours'], \
        'a heading colour goes to the favourites organisation'
    control.roots = {}
    control._render()
    assert cells(control, [r for r in control.rows if r.text == 'Mech'][0])['fill'].endswith('123456')
    # the Views tab is untouched
    control.tab = 'views'
    control._render()
    assert [r.text for r in control.rows][:2] == ['Mech', 'Floor Plans']
    assert not control.rows[0].node.key.startswith('g:fav.')
    # saved with the project's organisations
    pairs = pbp_settings.orgs_to_pairs(control.snapshot.orgs)
    assert pairs['fav.views.source'] == 'revit'
    assert pbp_settings.orgs_from_pairs(pairs)['fav.views']['source'] == 'revit'
    assert pbp_settings.default_orgs()['fav.sheets']['source'] == 'none'
    # the read collects the values the favourites' organisation groups by
    snap.orgs['fav.sheets'] = pbp_settings.normalise_org(
        {'source': 'custom', 'levels': ['Drawn By'], 'sort': 'Sheet Issue Date'}, 'fav.sheets')
    assert pbp_revit.Section(None, snap, 'sheets').names == ['Drawn By', 'Sheet Issue Date']
    # the dialog: the type's parameters, named as favourites, saved apart
    asked = []
    pbp_orgwin.ask = lambda *args, **kw: asked.append((args, kw)) or {'source': 'custom', 'levels': ['Drawn By']}
    control.tab = 'favourites'
    control.fav_sub = 'sheets'
    control.runner.jobs[:] = []
    control.store.reading = False
    control._org_clicked(None, None)
    args, kw = asked[-1]
    assert args[0] == 'sheets' and kw['org_key'] == 'fav.sheets' and 'Favourites' in kw['title'], (args, kw)
    assert control._org('fav.sheets')['levels'] == ['Drawn By'] and control._org('sheets')['source'] == 'revit'
    assert any(job[0].startswith('read changes') for job in control.runner.jobs), 'its values are read'
    control.fav_sub = 'all'
    control._org_clicked(None, None)
    shown = [h for h, f, e in menu_headers(control, lambda: control._org_clicked(None, None))]
    assert len(shown) == len(pbp_settings.FAV_TYPES), 'all types showing: the button asks which'
    labels = [h for h, f, e in menu_headers(control, lambda: control._tab_menu_opener('favourites')(None, None))]
    assert 'Browser Organisation: Views...' in labels and 'Browser Organisation: Families...' in labels, labels
    win = pbp_orgwin.OrganisationWindow('sheets', {'source': 'custom', 'levels': ['Drawn By']}, ['Drawn By'],
                                        '', 'dark', org_key='fav.sheets', title='Favourites x')
    win._reset(None, None)
    assert win.org['source'] == 'none', 'reset goes to the favourites default, not the Sheets tab\'s'
    win._apply(None, None)
    assert win.result['source'] == 'none'
    control._render()
    control.fav_sub = 'sheets'
    control._paint_org_line()
    assert 'Drawn By' in control.org_text.Text, control.org_text.Text


@check
def folders_start_closed():
    u"""Every folder starts closed (as Collapse all leaves it - the All
    tab's type headings stay open). What is opened or closed is remembered
    per tab, per project, for the next browser and the next session; a
    folder new to the model starts closed."""
    browser()
    import pbp_browser, pbp_settings, pbp_log, pbp_marks
    from pbp_tree import Leaf
    folder = pbp_log.appdata_folder()
    settings = pbp_settings.load(folder)
    settings['start_open'] = '0'
    pbp_settings.save(folder, settings)
    assert pbp_settings.DEFAULTS['start_open'] == '0'

    def fresh():
        made = pbp_browser.BrowserControl('pane', None)
        made.runner = FakeRunner()
        return made
    control = fresh()
    snap = snapshot_for_tests()
    feed(control, snap)
    control.tab = 'views'
    control._render()
    texts = lambda c: [r.text for r in c.rows]
    assert texts(control) == ['Mech'], texts(control)
    control._toggle(control.rows[0])
    assert texts(control) == ['Mech', 'Floor Plans', 'Sections'], texts(control)
    opened, shut = control._marks().folds_of('views')
    assert opened == set([control.rows[0].key]) and not shut
    again = fresh()
    again.tab = 'views'
    again._render()
    assert texts(again) == ['Mech', 'Floor Plans', 'Sections'], 'remembered for the next browser'
    on_disk = pbp_marks.Marks.load(control.store.folder, snap.title).folds_of('views')
    assert on_disk == (opened, shut), 'and saved with the project for next time'
    # a folder new to the model starts closed; the remembered ones stay open
    snap.tabs['views'].append(Leaf('e:9', 'views', 'plan', 'Roof', folders=['Mech', 'Roof Plans'], uid='u9'))
    snap.tabs['views'].append(Leaf('e:10', 'views', 'plan', 'Site', folders=['Arch', 'Site Plans'], uid='u10'))
    feed(again, snap)
    again.tab = 'views'
    again._render()
    assert texts(again) == ['Arch', 'Mech', 'Floor Plans', 'Roof Plans', 'Sections'], texts(again)
    # the All tab: type headings open, their folders closed; closing one is kept
    again.tab = 'all'
    again._render()
    heads = [r.text for r in again.rows if r.level == 0]
    assert 'Views' in heads and 'Sheets' in heads and 'M' in texts(again) and 'M-01 - Plan' not in texts(again)
    views_root = [r for r in again.rows if r.text == 'Views'][0]
    again._toggle(views_root)
    third = fresh()
    third.tab = 'all'
    third._render()
    assert 'Mech' not in texts(third) and 'Views' in texts(third), 'a closed type heading is remembered'
    assert third._marks().folds_of('all')[1] == set([views_root.key])
    # Collapse all / Expand all are remembered too
    third.tab = 'sheets'
    third._render()
    third._expand_all()
    assert 'M-01 - Plan' in texts(third)
    fourth = fresh()
    fourth.tab = 'sheets'
    fourth._render()
    assert 'M-01 - Plan' in texts(fourth)
    fourth._collapse_all()
    assert texts(fourth) == ['M'] and not fourth._marks().folds_of('sheets')[0]
    # Favourites: its type headings start open too, so the favourites show
    fourth._add_favourites(snap.tabs['sheets'][:1])
    fourth.tab = 'favourites'
    fourth._render()
    assert texts(fourth) == ['Sheets', 'M-01 - Plan'], texts(fourth)
    # one sub tab's opened folders survive working on the other
    leg = snap.tabs.setdefault('legends', [])
    leg.append(_mleaf('e:80', 'legends', 'Key A', 'k1', kind='legend', values={'View Template': 'X'}))
    leg.append(_mleaf('e:81', 'legends', 'Detail B', 'k2', kind='drafting', values={'View Template': 'Y'}))
    snap.orgs['legends'] = {'source': 'custom', 'levels': ['View Template'], 'sort': '', 'desc': False}
    feed(fourth, snap)
    fourth.tab = 'legends'
    fourth._render()
    assert texts(fourth) == ['X']
    fourth._toggle(fourth.rows[0])
    fourth._show_sub('Drafting Views')
    fourth._toggle(fourth.rows[0])
    fourth._show_sub('Legends')
    assert texts(fourth) == ['X', 'Key A'], 'opening a drafting folder kept the legend folder open'


@check
def families_heading_colours():
    u"""Families keep their fixed grouping, but their group headings take
    colours of their own: right click a heading, or the colours-only
    Browser Organisation - saved with the project, the grouping untouched."""
    control = browser()
    snap = snapshot_for_tests()
    feed(control, snap)
    import pbp_settings, pbp_orgwin
    control.tab = 'families'
    control.colour_mode = 'colour'
    control._render()
    head = [r for r in control.rows if r.text == 'Mechanical & Plumbing'][0]
    assert pbp_settings.colourable('families') and not pbp_settings.organisable('families')
    control.set_heading_colour(head.node, '#112233')
    assert control._group_colour(head.node) == '#112233'
    control.roots = {}
    control._render()
    head = [r for r in control.rows if r.text == 'Mechanical & Plumbing'][0]
    assert cells(control, head)['fill'].endswith('112233'), cells(control, head)['fill']
    assert control._org('families')['levels'] == ['Main Group', 'Category', 'Family'], 'grouping unchanged'
    pairs = pbp_settings.orgs_to_pairs(control.snapshot.orgs)
    pairs['families.levels'] = 'Something Else'
    back = pbp_settings.orgs_from_pairs(pairs)['families']
    assert back['group_colours'] and back['levels'] == ['Main Group', 'Category', 'Family'], back
    labels = [h for h, f, e in menu_headers(control, lambda: control._tab_menu_opener('families')(None, None))]
    assert 'Heading colours...' in labels, labels
    asked = []
    pbp_orgwin.ask = lambda *args, **kw: asked.append((args, kw)) or dict(control._org('families'), group_colours={})
    control.runner.jobs[:] = []
    control._org_clicked(None, None)
    args, kw = asked[-1]
    assert args[0] == 'families' and kw['colours_only'] and 'heading colours' in kw['title'], kw
    assert not control._org('families')['group_colours'], 'the dialog\'s colours are saved'
    assert not control.runner.jobs, 'colours only: nothing to read'
    win = pbp_orgwin.OrganisationWindow('families', control._org('families'), [], '', 'dark',
                                        colours_only=True)
    assert win.custom_panel.IsEnabled is False and 'Always grouped' in win.preview.Text
    assert all(getattr(tick, 'IsEnabled', None) is not False for tick in win.colour_ticks), \
        'which levels are coloured is theirs to choose'
    # coloured levels: main group and family, not category
    org = dict(control._org('families'))
    org['colours'] = [1, 3]
    control.store.save_org('families', org)
    control.roots = {}
    control._render()
    keys = dict((r.text, r.node.key) for r in control.rows if r.heading)
    assert keys['Mechanical & Plumbing'] in control.plan and keys['Elbow'] in control.plan
    assert keys['Pipe Fittings'] not in control.plan, 'the category level was unticked'
    back = pbp_settings.orgs_from_pairs(pbp_settings.orgs_to_pairs(control.snapshot.orgs))['families']
    assert back['colours'] == [1, 3], back
    win._apply(None, None)
    assert win.result['levels'] == ['Main Group', 'Category', 'Family']


def _registered_providers():
    stubbed()
    import pbp_store
    fake_domain(pbp_store)
    import pbp_dock
    seen = []

    class Host(object):
        def RegisterDockablePane(self, pane_id, title, provider):
            seen.append((title, provider))
    assert pbp_dock.register(Host())
    return pbp_dock, seen


def _off_path():
    u"""sys.path as pyRevit leaves it once startup.py has run: without the
    tool's folder - and the browser's modules not yet imported."""
    before = list(sys.path)
    sys.path[:] = [p for p in sys.path if p and os.path.abspath(p) != HERE]
    for name in list(sys.modules):
        if name.startswith('pbp_') and name not in ('pbp_dock', 'pbp_store', 'pbp_compat', 'pbp_log',
                                                     'pbp_runner', 'pbp_revit', 'pbp_panes', 'pbp_clr',
                                                     'pbp_tree', 'pbp_handoff', 'pbp_catgroups',
                                                     'pbp_settings', 'pbp_marks', 'pbp_version'):
            del sys.modules[name]
    return before


@check
def pane_builds_after_path_reset():
    u"""pyRevit resets the start up engine's sys.path once startup.py has
    run; a pane is built later, the first time it is shown. It must put the
    tool's folder back and build (1.7.1 - before, it stayed black with
    'No module named pbp_browser'). If it still cannot, it says why."""
    pbp_dock, seen = _registered_providers()
    title, provider = seen[0]
    assert title == 'RevoBIM Project Browser'
    before = _off_path()
    try:
        import importlib
        try:
            importlib.import_module('pbp_browser')
            raise AssertionError('the bench could not take the tool off sys.path')
        except ImportError:
            pass
        provider._visible(None, None)
        assert provider.browser is not None, 'the pane did not build after the path reset'
        assert provider.host.Child is provider.browser.root
    finally:
        sys.path[:] = before
    # a pane that still cannot build shows why, not an empty black pane
    pbp_dock, seen = _registered_providers()
    title, provider = seen[1]
    before = _off_path()
    real = pbp_dock.on_path
    pbp_dock.on_path = lambda: False
    try:
        provider._visible(None, None)
    finally:
        pbp_dock.on_path = real
        sys.path[:] = before
    assert provider.browser is None
    note = provider.host.Child
    assert 'could not start' in note.Text and 'pbp_browser' in note.Text, note.Text
    # every event handler and Revit job puts the folder back first
    import pbp_ui, pbp_runner, pbp_compat
    before = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if p and os.path.abspath(p) != HERE]
        pbp_ui.safe(lambda: None)()
        assert pbp_compat.TOOL_DIR in sys.path, 'safe() did not put the folder back'
        sys.path[:] = [p for p in sys.path if p and os.path.abspath(p) != HERE]
        runner = pbp_runner.Runner()
        runner.jobs.append(('x', lambda app: None, None))
        runner.Execute(None)
        assert pbp_compat.TOOL_DIR in sys.path, 'a Revit job did not put the folder back'
    finally:
        sys.path[:] = before


@check
def search_boxes_framed_orange():
    u"""The browser's search box, and Browser Organisation's, sit in an
    orange frame - the palette's orange, so dark and light each have
    theirs - that stays orange while typing (the box's own edge, which
    turns blue on focus, is off)."""
    import xml.etree.ElementTree as ET
    import pbp_palette
    for name, box in (('Browser.xaml', 'SearchBox'), ('Organisation.xaml', 'ParamSearch')):
        root = ET.parse(os.path.join(HERE, name)).getroot()
        parents = dict((child, parent) for parent in root.iter() for child in parent)
        found = [el for el in root.iter() if el.get('{http://schemas.microsoft.com/winfx/2006/xaml}Name') == box]
        assert found, box
        frame = parents[found[0]]
        assert frame.tag.endswith('Border'), (name, frame.tag)
        assert frame.get('BorderBrush') == '{DynamicResource OrangeBrush}', (name, frame.get('BorderBrush'))
        assert frame.get('BorderThickness') == '1' and frame.get('CornerRadius') == '4'
        assert found[0].get('BorderThickness') == '0', (name, 'the box\'s own edge would turn blue inside it')
    for theme in ('dark', 'light'):
        assert pbp_palette.palette(theme)['OrangeBrush']


def run_checks(quiet=False):
    failed = []
    for fn in CHECKS:
        try:
            fn()
            if not quiet:
                print('  ok    ' + fn.__name__)
        except Exception as error:
            failed.append(fn.__name__)
            if not quiet:
                print('  FAIL  {0}: {1!r}'.format(fn.__name__, error))
    if not quiet:
        print('{0} checks, {1} failed'.format(len(CHECKS), len(failed)))
    return failed


# (file, anchor, replacement, the check that must catch it)
BREAKAGES = [
    ('pbp_compat.py', 'key.append(int(part))', 'key.append(part)', 'natural_sort'),
    ('pbp_tree.py', 'return (1 if label in (UNSET, UNGROUPED) else 0, natural_key(label))',
     'return (0, natural_key(label))', 'tree_revit_grouping'),
    ('pbp_tree.py', 'is_open = searching or child.key not in collapsed',
     'is_open = child.key not in collapsed', 'flatten_search'),
    ('pbp_tree.py', '    return set()\n\n\ndef collapse_all_state', '    return None\n\n\ndef collapse_all_state',
     'flatten_defaults'),
    ('pbp_tree.py', "    if org.get(u'desc'):\n        node.leaves.reverse()\n", '', 'tree_custom_sort_desc'),
    ('pbp_tree.py', "OPEN_ORDER = (u'views', u'legends', u'sheets', u'schedules', u'panels')",
     "OPEN_ORDER = (u'sheets', u'views', u'legends', u'schedules', u'panels')", 'open_order'),
    ('pbp_tree.py', '        keys -= set(root.key for root in roots if not root.flat)\n', '', 'flatten_defaults'),
    ('pbp_settings.py', "current.append(u'|' if nxt == u'p' else nxt)", 'current.append(nxt)', 'orgs_round_trip'),
    ('pbp_settings.py', 'levels = levels[:MAX_LEVELS]', 'levels = levels', 'orgs_round_trip'),
    ('pbp_settings.py', "data[u'zoom'] = to_text(clamp(data[u'zoom'], 0.6, 2.0))", 'pass',
     'settings_defaults_and_damage'),
    ('pbp_settings.py', 'upgrade(pairs)', 'pass', 'settings_migrations_run'),
    ('pbp_handoff.py', "    pairs[u'status'] = u'taken'\n", '', 'handoff_round_trip'),
    ('pbp_handoff.py', "if to_text(pairs.get(u'project', u'')) != to_text(project):",
     'if False:', 'handoff_round_trip'),
    ('pbp_handoff.py', '        if os.path.isfile(old):\n            os.remove(old)\n',
     '        pass\n', 'handoff_round_trip'),
    ('pbp_palette.py', 'total = (total * 31 + ord(ch)) % 1000003', 'total = total + ord(ch)', 'palettes'),
    ('pbp_palette.py', "    u'ShadowBrush': u'#33000000',\n", '', 'palettes'),
    ('pbp_icons.py', "u'type': u'M6,1.5 L10.5,6 L6,10.5 L1.5,6 Z'", "u'type': u'M6,1.5 L10.5'", 'icon_geometry'),
    ('pbp_theme.py', '        if value is not None:\n', '        if value:\n', 'revit_theme_dark_is_zero'),
    ('pbp_theme.py', "return read if read is not None else u'light'",
     "return read if read is not None else u'dark'", 'theme_before_2024_is_light'),
    ('pbp_runner.py', '        if job in self.jobs:\n            self.jobs.remove(job)\n',
     '        del self.jobs[:]\n', 'runner_queue'),
    ('pbp_store.py', "        if self.reading:\n            self.again = True\n            return True\n",
     '', 'store_coalesces_reads'),
    ('pbp_dock.py', "        elif kind == pbp_revit.TEMPLATE:\n            ids.append(value)", "        elif kind == pbp_revit.TEMPLATE:\n            pass",
     'changes_noted_by_kind'),
    ('pbp_revit.py', "            if is_family_type(element):\n                return u'families'", "            if True:\n                return u'families'",
     'changes_noted_by_kind'),
    ('pbp_browser.py', "            chevvis = u'Visible' if row.opens else u'Hidden'", "            chevvis = u'Visible'",
     'browser_cells'),
    ('pbp_browser.py', "        show(self.footer, self.bar_open)\n", '', 'bar_folds'),
    ('pbp_browser.py', 'self.print_button.IsEnabled = sheets > 0', 'self.print_button.IsEnabled = True',
     'browser_print_buttons'),
    ('pbp_browser.py', "        show(self.print_bar, sheets > 0)\n", "        show(self.print_bar, True)\n",
     'browser_print_buttons'),
    ('pbp_browser.py', 'if pbp_handoff.waiting_too_long(', 'if False and pbp_handoff.waiting_too_long(',
     'browser_express_failures'),
    ('pbp_browser.py', '                pbp_ui.shell_open(self.last_folder)\n', '                pass\n',
     'browser_express_flow'),
    ('pbp_browser.py', '            self.progress.fail(message)\n', '            pass\n', 'browser_express_failures'),
    ('pbp_handoff.py', "    return min(99, int(100.0 * answer.get(u'done', 0) / total))",
     "    return int(100.0 * answer.get(u'done', 0) / total)", 'express_percent_and_detail'),
    ('pbp_handoff.py', "        u'headless': u'1' if kind == u'express' else u'0',\n", '', 'browser_express_flow'),
    ('Browser.xaml', 'Style="{DynamicResource ExpressButton}"', 'Style="{DynamicResource GreenButton}"',
     'express_button_look'),
    ('pbp_browser.py', 'self.zoom = round(float(clamp(value, ZOOM_MIN, ZOOM_MAX)), 2)',
     'self.zoom = round(float(value), 2)', 'browser_zoom_theme_menus'),
    ('pbp_browser.py', "            if self.fixed_tab or self.tab == tab:\n", "            if self.tab == tab:\n",
     'fixed_tab_browser'),
    ('pbp_browser.py', "        self.colour_mode = pbp_settings.colour_mode(self.settings[u'colour'])\n        self.last_settings",
     "        self.colour_mode = u'grey'\n        self.last_settings", 'pinned_copy'),
    ('pbp_tree.py', "TAB_ORDER = (u'views', u'legends', u'sheets', u'schedules', u'panels', u'families')",
     "TAB_ORDER = (u'views', u'sheets', u'legends', u'schedules', u'panels', u'families')",
     'tab_strip_order_and_labels'),
    ('Browser.xaml', 'Fill="{DynamicResource AllBrush}"', 'Fill="{DynamicResource BlueBrush}"',
     'tab_strip_order_and_labels'),
    ('Browser.xaml', '<Viewbox Width="22" Height="22">', '<Viewbox Width="16" Height="16">',
     'tab_strip_order_and_labels'),
    ('pbp_browser.py', '        elif self.host == u\'window\':\n            show(self.top_bar, True)\n',
     '        elif False:\n            pass\n', 'bar_folds'),
    ('pbp_browser.py', "    (u'schedules', u'TabSchedules', u'IconSchedules', u'schedule', u'Schedules'),\n",
     '', 'tab_strip_order_and_labels'),
    ('pbp_browser.py', "counts[u'all'] = sum(counts.values())", "counts[u'all'] = 0", 'tab_counts_shown'),
    ('pbp_tree.py', '            parent.children.append(leaf)\n', '            kept.append(leaf)\n',
     'dependents_nested'),
    ('pbp_tree.py', '        del leaf.children[:]   # leaves are reused across rebuilds\n', '',
     'dependents_nested'),
    ('pbp_tree.py', '                leaf_hits.add(leaf.key)\n    hits[node.key] = total',
     '    hits[node.key] = total', 'dependents_nested'),
    ('pbp_browser.py', "            weight = u'Bold' if row.is_parent else u'Normal'",
     "            weight = u'Bold' if leaf.is_active else u'Normal'", 'dependents_drawn'),
    ('pbp_browser.py', '(NEST_INDENT if row.nested else 0)', '0', 'dependents_drawn'),
    ('pbp_dock.py', "    if not running or running == to_text(installed):", "    if True:",
     'stale_panes_noticed'),
    ('pbp_palette.py', "    u'BarBrush': u'#222933',         # title bar and section bands",
     "    u'BarBrush': u'#1C1C1F',", 'dark_matches_revit'),
    ('pbp_browser.py', "                line += u' ' + answer[u'message']\n", '', 'browser_express_flow'),
    ('pbp_orgwin.py', "self.sort_box.Opacity = 1.0 if source != u'revit' else 0.45",
     "self.sort_box.Opacity = 1.0", 'organisation_dialog'),
    ('pbp_orgwin.py', "if name in self.org[u'levels'] or len(self.org[u'levels']) >= MAX_LEVELS:",
     "if name in self.org[u'levels']:", 'organisation_dialog'),
    ('script.py', '        pbp_dock.hook_events(uiapp)\n', '        pbp_dock.hook_events(uiapp, uiapp)\n',
     'script_loads'),
    # 1.1.0
    ('pbp_disc.py', "            tail = u'(?![A-Z0-9])' if len(phrase) <= 4 else u''",
     "            tail = u''", 'disciplines_matched'),
    ('pbp_disc.py', "        pattern = re.compile(u'(?<![A-Z0-9])(?:'", "        pattern = re.compile(u'(?:'",
     'disciplines_matched'),
    ('pbp_marks.py', "                self.colours.pop(leaf.uid, None)\n                removed += 1",
     "                removed += 1", 'marks_round_trip'),
    ('pbp_marks.py', "            if leaf.uid and leaf.uid not in self.favs:",
     "            if leaf.uid not in self.favs:", 'marks_round_trip'),
    ('pbp_tree.py', "        root.flat = True\n", '', 'favourites_tab'),
    ('pbp_tree.py', "        keys -= set(root.key for root in roots if not root.flat)",
     "        keys -= set(root.key for root in roots)", 'favourites_tab'),
    ('pbp_browser.py', "        else:\n            self.roots = {}\n            if self._hidden():", "        else:\n            if self._hidden():", 'favourites_tab'),
    ('pbp_browser.py', "            if self.tab == u'favourites':\n                colour = pbp_palette.slot_colour(",
     "            if True:\n                colour = pbp_palette.slot_colour(", 'favourites_tab'),
    ('pbp_panes.py', "u'364c5e3f-2026-42dc-a7b8-3808cfd90a39'", "u'6affdb17-3970-4c31-a942-3327bdd36bd9'",
     'favourites_pane_registered'),
    ('pbp_browser.py', "            return [self._root_for(u'sheets', self._sheet_set())]",
     "            return [self._root_for(u'sheets')]", 'sheet_set_filter'),
    ('pbp_browser.py', "        return name if name in self.snapshot.sheet_sets else u''",
     "        return name", 'sheet_set_filter'),
    ('pbp_browser.py', "        cache_key = tab + (u'|set:' + sheet_set if sheet_set else u'')",
     "        cache_key = tab", 'sheet_set_filter'),
    ('pbp_tree.py', "    if not any_groups:\n        return None\n", '', 'panel_groups'),
    ('pbp_browser.py', "                and not row.is_root and row.text in names)",
     "                and not row.is_root)", 'panel_groups'),
    ('pbp_browser.py', "        if found is None and parent is not None:\n            return parent\n", '',
     'heading_gradients'),
    ('pbp_browser.py', "                if leaf.template:\n                    found = self._discipline(leaf.template)",
     "                if False:\n                    found = self._discipline(leaf.template)", 'heading_gradients'),
    # 1.2.0
    ('pbp_palette.py', "    return [first + step * i for i in range(count)]",
     "    return [first] * count", 'heading_gradients'),
    ('pbp_palette.py', "    return LIGHT_TEXT if on_white >= on_black else DARK_TEXT", "    return LIGHT_TEXT",
     'heading_gradients'),
    ('pbp_disc.py', "    u'power': u'electrical', u'containment': u'electrical',",
     "    u'power': u'other', u'containment': u'electrical',", 'disciplines_matched'),
    ('pbp_browser.py', "                    fill, edge, fore = pbp_palette.heading_pill(family, t)\n                    chevfill = iconfill = fore\n",
     "                    fill, edge, fore = pbp_palette.heading_pill(family, t)\n", 'heading_gradients'),
    ('pbp_catgroups.py', "    if key.endswith(u'Tags') or key.endswith(u'Tag') or lower.endswith(u' tags') \\\n",
     "    if False and (key.endswith(u'Tags') or lower.endswith(u' tags')) \\\n", 'categories_grouped'),
    ('pbp_browser.py', "                family = pbp_disc.family(found)\n", '', 'families_tab_grouped'),
    ('pbp_catgroups.py', "    return any((u' ' + word) in name for word in words)",
     "    return any(word in name for word in words)", 'categories_grouped'),
    ('pbp_catgroups.py', "    if key in MECHANICAL_OST:\n        return MECHANICAL\n", '', 'categories_grouped'),
    ('pbp_browser.py', "            elif tab == u'families':\n                order = FAMILY_ORDER\n", '',
     'families_tab_grouped'),
    ('pbp_browser.py', "            return set(self._org(tab).get(u'colours', pbp_settings.DEFAULT_COLOURS))\n        if tab not in pbp_settings.ORGANISABLE:",
     "            return set([1])\n        if tab not in pbp_settings.ORGANISABLE:", 'families_tab_grouped'),
    ('pbp_revit.py', "        return (kind in LEGEND_TYPES) == (tab == u'legends')", "        return True", 'legends_read_apart'),
    ('pbp_revit.py', "    folders = folders_of(sec.rorg, view) + [view_label(doc, view)] if sec.tab == u'views' else []",
     "    folders = folders_of(sec.rorg, view) + [view_label(doc, view)]", 'legends_read_apart'),
    ('pbp_settings.py', "ORGANISABLE = (u'views', u'legends', u'sheets', u'panels', u'schedules')",
     "ORGANISABLE = (u'views', u'sheets', u'panels', u'schedules')", 'legends_tab'),
    ('pbp_browser.py', "            return [node] if node is not None else []",
     "            return [self._root_for(self.pin[0])]", 'pinned_copy'),
    ('pbp_browser.py', "            return [self._root_for(self.pin[0])]\n        if self.tab == u'legends':",
     "            return self._roots()\n        if self.tab == u'legends':", 'pinned_copy'),
    ('pbp_browser.py', "        if pins != self.last_pins:", "        if False:", 'pinned_copy'),
    ('pbp_browser.py', "            if kind == u'outside':\n                self._pin_heading(drag[u'row'])",
     "            if True:\n                self._pin_heading(drag[u'row'])", 'drag_heading_out'),
    ('pbp_browser.py', "        if not int(args.KeyStates) & int(DragDropKeyStates.LeftMouseButton):",
     "        if False:", 'drag_heading_out'),
    ('pbp_browser.py', "        finally:\n            DRAGGING[0] = None", "        finally:\n            pass",
     'drag_heading_out'),
    ('pbp_browser.py', "        drag[u'target'] = self._sheet_under(args.GetPosition(self.root))",
     "        pass", 'drag_views_onto_a_sheet'),
    ('pbp_browser.py', "        if (abs(point.X - drag[u'start'].X) < DRAG_START",
     "            if False and (abs(point.X - drag[u'start'].X) < DRAG_START", 'drag_heading_out'),
    ('pbp_browser.py', "            pbp_settings.save_pin(folder, slot, pin[0], pin[1])\n", '', 'drag_heading_out'),
    ('pbp_browser.py', "            (number if number and number != leaf.number else None))",
     "            None)", 'rename_in_place'),
    ('pbp_browser.py', "    def _list_double(self, sender, args):\n        self.slow = None\n",
     "    def _list_double(self, sender, args):\n", 'rename_in_place'),
    ('pbp_revit.py', "            ui_view.ZoomToFit()", "            pass", 'zoom_and_sync'),
    ('pbp_browser.py', "        if self.sync and leaves and not self.following:\n", "        if False:\n", 'zoom_and_sync'),
    ('pbp_browser.py', "        if not self.sync or not leaves or not self.runner.ready():",
     "        if not leaves or not self.runner.ready():", 'zoom_and_sync'),
    ('Theme.xaml', 'Visibility="{Binding pillvis}"', 'Visibility="Visible"', 'row_template_has_pill'),
    # 1.3.0
    ('pbp_tree.py', "        is_open = opens and leaf.key in open_sheets\n", "        is_open = opens\n",
     'sheets_open_to_views'),
    ('pbp_revit.py', "    for sheet in snap.tabs.get(u'sheets', []):\n        sheet.placed",
     "    for sheet in []:\n        sheet.placed", 'sheets_open_to_views'),
    ('pbp_browser.py', "        state = (state | keys) if show_them else (state - keys)",
     "        state = state | keys", 'sheets_open_to_views'),
    ('pbp_browser.py', "        state.discard(node.key)\n        if close:", "        if close:",
     'heading_menu_folds_inside'),
    ('pbp_tree.py', "        if any(other != path and path[:len(other)] == other for other in paths):\n            continue\n",
     '', 'favourite_groups'),
    ('pbp_tree.py', "        leaves = [leaf for leaf in fav_by_tab.get(tab, []) if leaf.key not in inside]",
     "        leaves = list(fav_by_tab.get(tab, []))", 'favourite_groups'),
    ('pbp_browser.py', "        if self.tab == u'favourites':\n            # each type's own grouping is coloured by its own organisation;\n",
     "        if False:\n", 'favourite_groups'),
    ('pbp_marks.py', "            pairs[u'favgroup.{0}'.format(index)] = escape_list([tab] + list(path))\n", '',
     'favourite_groups'),
    ('pbp_browser.py', "        if headings and not sheets:\n", "        if False:\n", 'sheet_heading_prints'),
    ('pbp_browser.py', "        return sheets_of_rows(self._selected_rows())",
     "        return pbp_tree.sheet_leaves(self._selected_leaves())", 'sheet_heading_prints'),
    ('pbp_browser.py', "            if not has_hook:\n", "            if False:\n", 'express_needs_the_hook'),
    ('pbp_handoff.py', "    has_hook = os.path.isfile(os.path.join(folder, HOOK_FILE))",
     "    has_hook = True", 'express_needs_the_hook'),
    ('pbp_handoff.py', "    if folder is None:\n        return None, True, u''\n",
     "    if folder is None:\n        return None, False, u''\n", 'express_needs_the_hook'),
    ('pbp_browser.py', "            if level in levels:\n", "            if True:\n",
     'coloured_levels_follow_the_organisation'),
    ('pbp_browser.py', "        rank = 1 if level == min(levels) else 2", "        rank = 1 if level == 1 else 2",
     'coloured_levels_follow_the_organisation'),
    ('pbp_settings.py', "            u'colours': pairs.get(prefix + u'colours'),\n", '',
     'organisation_revit_prefill_and_colours'),
    ('pbp_orgwin.py', "        if was == u'revit' and self.org[u'source'] == u'custom':\n            self._take_revit()\n",
     '', 'organisation_revit_prefill_and_colours'),
    ('pbp_browser.py', "            elif tab == u'legends':\n                prefix = legend_master\n                order = LEGEND_ORDER\n",
     '', 'legends_and_drafting_masters'),
    ('pbp_browser.py', "                size = MASTER_SIZE\n", '', 'legends_and_drafting_masters'),
    ('pbp_revit.py', "LEGEND_TYPES = (u'Legend', u'DraftingView')", "LEGEND_TYPES = (u'Legend',)",
     'legends_read_apart'),
    ('pbp_icons.py', "            pairs.append(u'{0},{1}'.format(_num(origin[0] + values[j] * scale),",
     "            pairs.append(u'{0},{1}'.format(_num(values[j] * scale),", 'view_icons_are_plain'),
    ('pbp_browser.py', "                icon = pbp_icons.framed(symbol)\n                iconfill = fore\n",
     "                icon = pbp_icons.framed(symbol)\n", 'heading_gradients'),
    ('pbp_browser.py', "    x = left - width - PLACE_GAP\n    if x < screen_left:",
     "    x = left + width + PLACE_GAP\n    if x < screen_left:", 'popped_out_beside'),
    ('pbp_browser.py', "            self._offer_placement(guid, placement)\n", '', 'popped_out_beside'),
    ('pbp_startup.py', "    if what == u'present':\n        return True, u'The docking block is already in {0}.'.format(path)\n",
     '', 'docking_set_up_and_toggle'),
    ('pbp_startup.py', "            text = existing.rstrip(u'\\r\\n') + u'\\n\\n\\n' + block",
     "            text = block", 'docking_set_up_and_toggle'),
    ('pbp_startup.py', "            handle = io.open(backup, 'w', encoding='utf-8')", "            handle = io.open(os.devnull, 'w', encoding='utf-8')",
     'docking_set_up_and_toggle'),
    ('pbp_browser.py', "        if not pbp_store.panes_registered():\n            self._set_up_docking()\n            return\n",
     '', 'docking_set_up_and_toggle'),
    ('pbp_browser.py', "            self._close_clicked(None, None)\n        self._job(u'dock',",
     "            pass\n        self._job(u'dock',", 'docking_set_up_and_toggle'),
    ('pbp_revit.py', "        for placed in sheet.placed:\n            placed.sheets.append(sheet)",
     "        for placed in []:\n            placed.sheets.append(sheet)", 'sheets_open_to_views'),
    ('pbp_browser.py', "        if len(leaves) == 1 and leaves[0].sheets:\n", "        if False:\n",
     'open_the_sheet_a_view_is_on'),
    ('pbp_browser.py', "        if not keys or set(keys) == self.last_synced:", "        if not keys:",
     'follows_revit_selection'),
    ('pbp_browser.py', "                if kind == u'view' or (kind == u'type' and self.tab == u'families')]",
     "                ]", 'follows_revit_selection'),
    ('pbp_browser.py', "            closed -= set(ancestors)\n", '', 'follows_revit_selection'),
    ('pbp_revit.py', "            if Viewport is not None and isinstance(element, Viewport):\n                kind, target = u'view', element.ViewId\n",
     "            if False:\n                pass\n", 'follows_revit_selection'),
    ('pbp_dock.py', "    if now - LAST_SELECTION[0] < SELECTION_EVERY:\n        return False\n", '',
     'follows_revit_selection'),
    ('pbp_store.py', "    if text == to_text(domain_get(SELECTION_KEY, u'')):\n        return False\n", '',
     'follows_revit_selection'),
    ('pbp_browser.py', "            target = self._sheet_under(args.GetPosition(self.root))",
     "            target = None", 'drag_views_onto_a_sheet'),
    ('pbp_browser.py', "        if drag is not None and drag.get(u'keep'):\n", "        if False:\n",
     'drag_views_onto_a_sheet'),
    ('pbp_revit.py', "    if not isinstance(view, ViewSheet):\n        return {u'ok': False, u'why': u'The view open in Revit is not a sheet",
     "    if False:\n        return {u'ok': False, u'why': u'The view open in Revit is not a sheet",
     'drag_views_onto_a_sheet'),
    ('pbp_browser.py', "                if own and mode != u'grey':\n", "                if False:\n", 'group_colours_override'),
    ('pbp_settings.py', "        pairs[prefix + u'group_colours'] = group_colours_text(org[u'group_colours'])\n", '',
     'group_colours_override'),
    ('pbp_orgwin.py', "                self.org[u'group_colours'].pop(key, None)\n", "                pass\n",
     'group_colours_override'),
    ('pbp_orgwin.py', "            if self.group_level is not None and level != self.group_level:\n                continue\n",
     '', 'group_colours_override'),
    ('pbp_palette.py', "    out.extend(GREYS)\n", '', 'group_colours_override'),
    ('pbp_settings.py', "    settings[u'custom_colours'] = escape_list", "    settings[u'custom_colours_x'] = escape_list",
     'group_colours_override'),
    ('pbp_browser.py', "            elif node is not None and (node.key in self.plan or self._group_colour(node)):",
     "            elif node is not None and node.key in self.plan:", 'group_colours_override'),
    ('pbp_browser.py', "                    fill, edge = pbp_palette.grey_pill(level, theme)\n", '', 'heading_gradients'),
    ('pbp_palette.py', "    (1, u'light'): (u'#EBECEE', u'#DDDFE2'),", "    (1, u'light'): (u'#8A8C90', u'#DDDFE2'),",
     'heading_gradients'),
    ('pbp_browser.py', "        if row.key in self.highlights:\n", "        if False:\n",
     'highlights_and_heading_colour'),
    ('pbp_browser.py', "        self.highlights = set()\n        self._render()", "        self._render()",
     'highlights_and_heading_colour'),
    ('pbp_browser.py', "        self.store.publish_marks_changed()\n", '', 'highlights_and_heading_colour'),
    ('pbp_browser.py', "        if node.key not in self.plan and not self._group_colour(node):\n            return\n",
     '', 'highlights_and_heading_colour'),
    ('pbp_browser.py', "                if own and mode != u'grey':", "                if own:",
     'colour_modes_and_settings'),
    ('pbp_browser.py', "                elif mode == u'colour':", "                elif mode != u'grey':",
     'colour_modes_and_settings'),
    ('pbp_settings.py', "COLOUR_MODES = (u'colour', u'grey', u'custom')", "COLOUR_MODES = (u'colour', u'custom', u'grey')",
     'settings_defaults_and_damage'),
    ('pbp_settings.py', "    if text in (u'0', u'false', u'off', u'no'):\n        return u'grey'\n", '',
     'settings_defaults_and_damage'),
    ('pbp_browser.py', "            if bold:\n                weight = u'Bold'\n", '', 'colour_modes_and_settings'),
    ('pbp_browser.py', "        if pbp_store.settings_count() != self.last_settings:\n", "        if False:\n",
     'colour_modes_and_settings'),
    ('pbp_setwin.py', "        if colour and key in pbp_settings.HIGHLIGHT_KEYS:", "        if key in pbp_settings.HIGHLIGHT_KEYS:",
     'colour_modes_and_settings'),
    ('pbp_setwin.py', "        pbp_settings.set_custom_colours(self.values, self.custom)\n", '',
     'colour_modes_and_settings'),
    ('pbp_browser.py', "                if leaf.sheets:\n                    # placed on a sheet", "                if False:\n                    # placed on a sheet",
     'placed_views_marked_blue'),
    ('pbp_theme.py', "    for attr in (u'CurrentTheme', u'CurrentCanvasTheme'):",
     "    for attr in (u'CurrentCanvasTheme', u'CurrentTheme'):", 'revit_theme_dark_is_zero'),
    # 1.6.2: the Favourites tab's type tabs; the search box's text at the left
    ('pbp_browser.py', "                roots = [root for root in roots if root.tab == self.fav_sub]", "                pass",
     'favourites_type_tabs'),
    ('pbp_browser.py', "        if self.tab == u'favourites' and self.fav_sub != u'all':\n            return False\n", "",
     'favourites_type_tabs'),
    ('pbp_browser.py', "        self.settings[u'fav_sub'] = tab\n", "", 'favourites_type_tabs'),
    ('pbp_browser.py', "                leaves = [leaf for leaf in leaves if matches(leaf.search, self.search_words)]", "                pass",
     'favourites_type_tabs'),
    ('pbp_browser.py', "        counts[u'all'] = sum(counts.values())\n        for tab in FAV_TABS:",
     "        counts[u'all'] = 0\n        for tab in FAV_TABS:", 'favourites_type_tabs'),
    ('Theme.xaml', '        <Setter Property="TextAlignment" Value="Left"/>\n', '', 'search_text_starts_left'),
    ('Browser.xaml', 'Padding="27,2,26,2" TextAlignment="Left"', 'Padding="27,2,26,2"', 'search_text_starts_left'),
    ('Theme.xaml', '                                          Style="{DynamicResource TextHostScroller}"\n', '',
     'search_text_starts_left'),
    ('Theme.xaml', '    <Style x:Key="TextHostScroller" TargetType="ScrollViewer">\n        <Setter Property="OverridesDefaultStyle" Value="True"/>\n',
     '    <Style x:Key="TextHostScroller" TargetType="ScrollViewer">\n', 'search_text_starts_left'),
    # 1.7.0: an organisation for each type's favourites
    ('pbp_tree.py', "        if org.get(u'source', u'none') != u'none' and leaves:", "        if False:",
     'favourites_organised'),
    ('pbp_tree.py', "            key = group_key(space, sub)", "            key = group_key(tab, sub)", 'favourites_organised'),
    ('pbp_tree.py', "            _walk(child, level + 1, collapsed, searching, hits, leaf_hits,\n                  rows, child.key, child.flat, open_sheets)",
     "            _walk(child, level + 1, collapsed, searching, hits, leaf_hits,\n                  rows, child.key, False, open_sheets)", 'favourites_organised'),
    ('pbp_browser.py', "                    self._plan_level(organised, None, 1, plan, levels)", "                    pass",
     'favourites_organised'),
    ('pbp_browser.py', "        own = self._org(org_key(node)).get(u'group_colours', {})", "        own = self._org(node.tab).get(u'group_colours', {})",
     'favourites_organised'),
    ('pbp_browser.py', "        self.store.save_org(whose, org)", "        self.store.save_org(node.tab, org)", 'favourites_organised'),
    ('pbp_settings.py', "SAVED_ORGS = ORGANISABLE + FIXED_ORGS + FAV_ORGS", "SAVED_ORGS = ORGANISABLE + FIXED_ORGS",
     'favourites_organised'),
    ('pbp_revit.py', "        for name in needed_names(snap.orgs.get(u'fav.' + tab, {})):", "        for name in []:",
     'favourites_organised'),
    ('pbp_orgwin.py', "        self.org = normalise_org(DEFAULT_ORGS.get(self.org_key), self.org_key)",
     "        self.org = normalise_org(DEFAULT_ORGS.get(self.tab), self.tab)", 'favourites_organised'),
    ('pbp_browser.py', "            elif tab == u'favourites':\n                self._fav_org_items(menu)", "            elif False:\n                self._fav_org_items(menu)",
     'favourites_organised'),
    # 1.7.0: folders start closed and are remembered
    ('pbp_settings.py', "    u'start_open': u'0',", "    u'start_open': u'1',", 'folders_start_closed'),
    ('pbp_browser.py', "                default -= set(root.key for root in roots)\n", "", 'folders_start_closed'),
    ('pbp_browser.py', "                marks.set_folds(where, opened, shut)\n                marks.save()\n",
     "                marks.set_folds(where, opened, shut)\n", 'folders_start_closed'),
    ('pbp_browser.py', "        state = (default - opened) | (shut & known)", "        state = default - opened",
     'folders_start_closed'),
    ('pbp_browser.py', "            new_opened = (opened - was_known) | (was_default - state)",
     "            new_opened = was_default - state", 'folders_start_closed'),
    ('pbp_marks.py', "        for where, (opened, shut) in self.folds.items():", "        for where, (opened, shut) in []:",
     'folders_start_closed'),
    # 1.7.0: Families heading colours
    ('pbp_settings.py', "    return organisable(key) or key in FIXED_ORGS", "    return organisable(key)", 'families_heading_colours'),
    ('pbp_settings.py', "SAVED_ORGS = ORGANISABLE + FIXED_ORGS + FAV_ORGS", "SAVED_ORGS = ORGANISABLE + FAV_ORGS",
     'families_heading_colours'),
    ('pbp_settings.py', "            fixed[u'group_colours'] = pairs.get(prefix + u'group_colours')\n", "",
     'families_heading_colours'),
    ('pbp_settings.py', "        if tab in FIXED_ORGS:\n            # the grouping is the tool's", "        if False:\n            # the grouping is the tool's",
     'families_heading_colours'),
    ('pbp_browser.py', "            elif tab in pbp_settings.FIXED_ORGS:\n                self._item(menu, u'Heading colours...', lambda: self._organise(tab))\n            if tab != u'all'",
     "            if tab != u'all'", 'families_heading_colours'),
    ('pbp_browser.py', "        if colours_only:\n            # only colours changed", "        if False:\n            # only colours changed",
     'families_heading_colours'),
    ('pbp_orgwin.py', "            for element in (find(w, u'SourcePanel'), self.custom_panel):\n                element.IsEnabled = False\n",
     "", 'families_heading_colours'),
    ('pbp_orgwin.py', "            for element in (find(w, u'SourcePanel'), self.custom_panel):",
     "            for element in [find(w, u'SourcePanel'), self.custom_panel] + self.colour_ticks:", 'families_heading_colours'),
    ('pbp_settings.py', "            fixed[u'colours'] = pairs.get(prefix + u'colours')\n", "", 'families_heading_colours'),
    # 1.7.1: panes build after pyRevit resets sys.path
    ('pbp_dock.py', "                    if on_path():\n                        pbp_log.log(u'pane build: tool folder put back on sys.path')\n",
     "", 'pane_builds_after_path_reset'),
    ('pbp_dock.py', "                self.host.Child = failure_note(text)\n", "", 'pane_builds_after_path_reset'),
    ('pbp_ui.py', "            on_path()\n            return handler(*args)", "            return handler(*args)",
     'pane_builds_after_path_reset'),
    ('pbp_runner.py', "        on_path()\n        for name, work, done in jobs:", "        for name, work, done in jobs:",
     'pane_builds_after_path_reset'),
    ('pbp_compat.py', "            sys.path.append(TOOL_DIR)\n", "            pass\n", 'pane_builds_after_path_reset'),
    # 1.7.2: orange search frames
    ('Browser.xaml', '<Border x:Name="SearchFrame" BorderBrush="{DynamicResource OrangeBrush}"',
     '<Border x:Name="SearchFrame" BorderBrush="{DynamicResource SearchBrush}"', 'search_boxes_framed_orange'),
    ('Browser.xaml', 'Background="{DynamicResource SearchBrush}" BorderThickness="0"\n',
     'Background="{DynamicResource SearchBrush}" BorderThickness="1"\n', 'search_boxes_framed_orange'),
    ('Organisation.xaml', '<TextBox x:Name="ParamSearch" Tag="Search parameters" Height="26" BorderThickness="0"/>',
     '<TextBox x:Name="ParamSearch" Tag="Search parameters" Height="26"/>', 'search_boxes_framed_orange'),
    # 1.6.1: the Legends tab's sub tabs
    ('pbp_browser.py', "        if self.tab == u'legends':\n            # one master at a time", "        if False:\n            # one master at a time",
     'legends_and_drafting_masters'),
    ('pbp_browser.py', "        if self.tab == u'legends':\n            # colours are planned over the whole tab", "        if False:\n            # colours are planned over the whole tab",
     'legends_tab'),
    ('pbp_browser.py', "                self._show_sub(masters[0])", "                pass", 'legends_and_drafting_masters'),
    ('pbp_browser.py', "            self.settings[u'legend_sub'] = master\n", "", 'legends_and_drafting_masters'),
    ('pbp_browser.py', "                count = sum(1 for leaf in leaves if matches(leaf.search, self.search_words))",
     "                count = len(leaves)", 'legends_and_drafting_masters'),
    ('pbp_browser.py', "    return value if value in pbp_tree.MASTERS else pbp_tree.LEGENDS", "    return value or pbp_tree.LEGENDS",
     'legends_and_drafting_masters'),
    # 1.6.0: reading and drawing only what changed
    ('pbp_dock.py', "            if value in known:\n                ids.append(value)",
     "            ids.append(value)", 'changes_noted_by_kind'),
    ('pbp_dock.py', "        if section:\n            sections.add(section)\n", "        if section:\n            pass\n",
     'changes_noted_by_kind'),
    ('pbp_dock.py', "        if kind is None or kind == pbp_revit.PLACED:\n            continue\n",
     "        if kind is None:\n            continue\n        if kind == pbp_revit.PLACED:\n            sections.add(kind)\n",
     'changes_noted_by_kind'),
    ('pbp_dock.py', "            pbp_store.bump_dirty(*sorted(sections))", "            pbp_store.bump_dirty()",
     'document_changed_filter'),
    ('pbp_revit.py', "        if leaf_signature(old) == leaf_signature(new):", "        if False:",
     'read_changes_reads_alone'),
    ('pbp_revit.py', "            sections.add(PLACED)\n        patches.append", "            pass\n        patches.append",
     'read_changes_reads_alone'),
    ('pbp_revit.py', "                sections.update((u'views', u'legends'))", "                pass",
     'read_changes_reads_alone'),
    ('pbp_revit.py', "    ctx = {u'placed': snap.placed}\n",
     "    ctx = {u'placed': snap.placed, u'templates': dict(previous.templates), u'template_ids': dict(previous.template_ids)}\n",
     'read_changes_reads_alone'),
    ('pbp_revit.py', "    for tab in patched_tabs & set((u'views', u'legends')):\n        link_dependents",
     "    for tab in set():\n        link_dependents", 'read_changes_reads_alone'),
    ('pbp_store.py', "        if self.snapshot is None or pbp_revit.ALL in moved or not complete:",
     "        if self.snapshot is None or pbp_revit.ALL in moved:", 'store_reads_only_changes'),
    ('pbp_store.py', "            if tabs:\n                self.snapshot = snapshot", "            if True:\n                self.snapshot = snapshot",
     'store_reads_only_changes'),
    ('pbp_store.py', "set(sections) | waiting, ids, current)", "set(sections), set(), current)", 'store_reads_only_changes'),
    ('pbp_store.py', "        if not changed:\n            return\n        for leaves", "        for leaves",
     'views_publish_only_moved_dots'),
    ('pbp_store.py', "entries = [(s, v) for s, v in _journal_entries() if v not in fresh]",
     "entries = _journal_entries()", 'journal_keeps_each_id_once'),
    ('pbp_browser.py', "                self._repaint_ids(self.store.changed_ids)", "                self._render()",
     'browser_redraws_only_what_changed'),
    ('pbp_browser.py', "            mine |= set(SHEET_CONTENT)", "            pass", 'browser_redraws_only_what_changed'),
    ('pbp_browser.py', "            if not self._shows(tabs):\n                return\n", "",
     'browser_redraws_only_what_changed'),
    ('pbp_browser.py', "                self.stale = self.stale or self._shows(tabs)\n                return\n", "",
     'browser_redraws_only_what_changed'),
    ('pbp_browser.py', "                self.stale = False\n                self._render()\n            self._tick",
     "                self.stale = False\n            self._tick", 'browser_redraws_only_what_changed'),
    ('pbp_browser.py', "            same_rows = differing <= max(40, len(all_cells) // 2)", "            same_rows = False",
     'browser_redraws_only_what_changed'),
    ('pbp_store.py', "        if self.views_pending:\n            return True\n", "", 'views_publish_only_moved_dots'),
    ('pbp_browser.py', "        if views != self.last_views and self.store.request_views(self.runner):",
     "        if views != self.last_views:\n            self.store.request_views(self.runner)", 'browser_redraws_only_what_changed'),
    ('pbp_browser.py', "            if new_value != old_value:\n                row[column] = new_value",
     "            row[column] = new_value", 'fill_table_sets_only_differing_cells'),
]


def selftest():
    caught = 0
    problems = []
    for filename, anchor, replacement, expected in BREAKAGES:
        workdir = tempfile.mkdtemp(prefix='pbp_self_')
        copy = os.path.join(workdir, 'tool')
        shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(copy, filename)
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        if anchor not in source:
            problems.append('{0}: anchor not found ({1!r}) - the breakage has disarmed itself'.format(
                filename, anchor[:60]))
            continue
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(source.replace(anchor, replacement, 1))
        result = subprocess.run([sys.executable, 'bench_logic.py', '--names'], cwd=copy,
                                capture_output=True, text=True)
        failed = result.stdout.split()
        if expected in failed:
            caught += 1
            print('  caught  {0:<16} by {1}'.format(filename, expected))
        else:
            problems.append('{0}: {1!r} broke nothing {2} noticed (failed: {3})'.format(
                filename, anchor[:50], expected, failed))
        shutil.rmtree(workdir, ignore_errors=True)
    for problem in problems:
        print('  MISSED  ' + problem)
    print('{0} breakages, {1} caught'.format(len(BREAKAGES), caught))
    return not problems


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        clean = run_checks(quiet=True)
        if clean:
            print('the bench does not pass on the real tool: ' + ', '.join(clean))
            sys.exit(1)
        sys.exit(0 if selftest() else 1)
    if '--names' in sys.argv:
        print(' '.join(run_checks(quiet=True)))
        sys.exit(0)
    sys.exit(1 if run_checks() else 0)
