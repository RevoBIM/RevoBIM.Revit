# -*- coding: utf-8 -*-
"""Logic checks for Excel for Revit. Plain CPython, no Revit.

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the logic and confirm it is caught

import_check.py proves the tool loads; this proves it gives the right answers.
The rules under test are the plain functions in efr_core — no WPF, no Revit —
imported against the same stub API the import check uses.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import import_check                      # noqa: E402
os.environ['REVOBIM_BENCH'] = '1'
import_check.install_stubs()
import efr_core                          # noqa: E402


class FakeId(object):
    def __init__(self, n):
        self.Value = n


class FakeParam(object):
    def __init__(self, text):
        self.text = text


def fake_read(doc, param):
    return param.text if param is not None else u''


efr_core.read_param = fake_read          # the stub API cannot format values


def check_join(problems):
    """The combining rule itself."""
    join = efr_core.join_combined
    cases = [
        ([(u'', u'FD', u'', u'-'), (u'', u'00', u'', u'-'), (u'', u'001', u'', u'')],
         u'FD-00-001', 'three parts with separators'),
        ([(u'L', u'00', u'', u'/'), (u'', u'001', u'.', u'')],
         u'L00/001.', 'prefix and suffix kept'),
        ([(u'', u'FD', u'', u' / ')],
         u'FD', 'a single part takes no separator'),
        ([(u'', u'FD', u'', u'-'), (u'', u'', u'', u'-'), (u'', u'001', u'', u'')],
         u'FD--001', 'an empty value keeps its separators, as Revit shows it'),
        ([(u'', u'A', u'', u'|'), (u'', u'B', u'', u'NEVER')],
         u'A|B', "the last part's separator is never written"),
        ([], u'', 'no parts'),
    ]
    for pieces, want, label in cases:
        got = join(pieces)
        if got != want:
            problems.append('join_combined: {0} — wanted {1!r}, got {2!r}'.format(
                label, want, got))


def check_lookup(problems):
    """Instance parameters first, the type's second, missing ones blank."""
    parts = [(FakeId(1), u'', u'', u'-'),      # type mark: on the type
             (FakeId(2), u'', u'', u'-'),      # level: on the instance
             (FakeId(3), u'', u'', u'')]       # mark: on the instance
    imap = {2: FakeParam(u'00'), 3: FakeParam(u'001')}
    tmap = {1: FakeParam(u'FD')}
    got = efr_core.combined_value(None, parts, imap, tmap)
    if got != u'FD-00-001':
        problems.append('combined_value: wanted FD-00-001, got {0!r}'.format(got))

    # an instance value wins over a type value of the same parameter
    imap2 = {1: FakeParam(u'INST')}
    tmap2 = {1: FakeParam(u'TYPE')}
    got = efr_core.combined_value(None, [(FakeId(1), u'', u'', u'')], imap2, tmap2)
    if got != u'INST':
        problems.append('combined_value: instance should win over type, '
                        'got {0!r}'.format(got))

    # a parameter on neither is blank, not an error
    got = efr_core.combined_value(None, [(FakeId(9), u'<', u'>', u'')], {}, {})
    if got != u'<>':
        problems.append('combined_value: a missing parameter should read blank, '
                        'got {0!r}'.format(got))


def check_parts(problems):
    """A field that is not combined, or a release without the API, is None."""
    class Plain(object):
        IsCombinedParameterField = False

    class Old(object):
        pass                              # Revit 2021: no such property

    class Data(object):
        def __init__(self, n, pre, suf, sep):
            self.ParamId = FakeId(n)
            self.Prefix = pre
            self.Suffix = suf
            self.Separator = sep

    class Combined(object):
        IsCombinedParameterField = True

        def GetCombinedParameters(self):
            return [Data(1, u'', u'', u'-'), Data(2, u'L', u'', u'')]

    if efr_core.combined_parts(Plain()) is not None:
        problems.append('combined_parts: a plain field was treated as combined')
    if efr_core.combined_parts(Old()) is not None:
        problems.append('combined_parts: an old release should give None')
    parts = efr_core.combined_parts(Combined())
    if not parts or len(parts) != 2 or parts[1][1] != u'L':
        problems.append('combined_parts: did not read the parts, got {0!r}'.format(
            parts))


def check_fill(problems):
    """The fill rules, which live in the same module and are easy to break."""
    fill = efr_core.fill_plan
    cases = [
        ([u'AHU-1'], 3, True, [u'AHU-2', u'AHU-3', u'AHU-4']),
        ([u'SD-005'], 2, False, [u'SD-004', u'SD-003']),
        ([u'AHU-10'], 1, False, [u'AHU-9']),
        ([u'Duct'], 2, True, [u'Duct', u'Duct']),
        ([u'10', u'20'], 2, True, [u'30', u'40']),
    ]
    for seeds, n, down, want in cases:
        got = fill(seeds, n, down)
        if got != want:
            problems.append('fill_plan {0} {1}: wanted {2}, got {3}'.format(
                seeds, 'down' if down else 'up', want, got))


def check_duplicates(problems):
    """Which values count as duplicates."""
    find = efr_core.find_duplicates
    cases = [
        ([u'SD-01', u'SD-02', u'SD-01'], [u'SD-01'], 'a repeated value'),
        ([u'A', u'B', u'C'], [], 'nothing repeated'),
        ([u'', u'', u'', u'X'], [], 'blanks are not duplicates'),
        ([u'  ', u'  '], [], 'whitespace is blank too'),
        ([u'P-10', u'P-9', u'P-10', u'P-9'], [u'P-9', u'P-10'],
         'natural order, P-9 before P-10'),
    ]
    for values, want, label in cases:
        got = find(values)
        if got != want:
            problems.append('find_duplicates: {0} — wanted {1}, got {2}'.format(
                label, want, got))


class FakeField(object):
    def __init__(self, index, name):
        self.index = index
        self.name = name


class FakeItems(object):
    Count = 3


class FakeGrid(object):
    Items = FakeItems()


class FakeHost(object):
    """Just enough of the window for isolate_duplicates to run."""

    def __init__(self, dups):
        self._dups = dups
        self.col_picks = {}
        self.dup_isolated = set()
        self.dup_saved_picks = {}
        self.dg = FakeGrid()
        self.filters_applied = 0

    def duplicate_values(self, fi):
        return list(self._dups)

    def apply_filters(self):
        self.filters_applied += 1

    def set_status(self, text):
        pass


def check_isolate(problems):
    """Isolate narrows to the clashes; un-isolate gives the old filter back."""
    isolate = efr_core.ExcelForRevitWindow.isolate_duplicates
    fi = FakeField(2, 'Mark')

    host = FakeHost([u'SD-01'])
    host.col_picks[2] = set([u'L01', u'L02'])          # a filter the user set
    isolate(host, fi, True)
    if host.col_picks.get(2) != set([u'SD-01']):
        problems.append('isolate: did not narrow to the duplicates')
    if 2 not in host.dup_isolated:
        problems.append('isolate: did not record that the column is isolated')
    isolate(host, fi, False)
    if host.col_picks.get(2) != set([u'L01', u'L02']):
        problems.append('un-isolate: the filter the column had before was lost, '
                        'got {0}'.format(host.col_picks.get(2)))
    if 2 in host.dup_isolated:
        problems.append('un-isolate: still recorded as isolated')

    host = FakeHost([u'SD-01'])                         # no filter beforehand
    isolate(host, fi, True)
    isolate(host, fi, False)
    if 2 in host.col_picks:
        problems.append('un-isolate: left a filter behind where there was none')

    host = FakeHost([])                                 # nothing to isolate
    if isolate(host, fi, True):
        problems.append('isolate: claimed success with no duplicates')
    if 2 in host.col_picks:
        problems.append('isolate: filtered a column with no duplicates')

    host = FakeHost([u'SD-01'])                         # isolating twice
    host.col_picks[2] = set([u'L01'])
    isolate(host, fi, True)
    isolate(host, fi, True)
    isolate(host, fi, False)
    if host.col_picks.get(2) != set([u'L01']):
        problems.append('isolating twice then un-isolating lost the original '
                        'filter, got {0}'.format(host.col_picks.get(2)))


def check_default_3d(problems):
    """Which 3D view counts as the default one."""
    rank = efr_core.default_3d_rank
    order = [u'Coordination 3D', u'{3D - drew}', u'{3D}']
    best = sorted(order, key=rank)[0]
    if best != u'{3D}':
        problems.append('default 3D: {{3D}} should win, got {0}'.format(best))
    if rank(u'{3D - drew}') >= rank(u'Coordination 3D'):
        problems.append('default 3D: a per-user {3D - ...} should beat a named '
                        'working view')
    if rank(u'') != rank(u'Coordination 3D'):
        problems.append('default 3D: an unnamed view should rank with the '
                        'ordinary ones, not above them')


def check_drawer(problems):
    """Where the shrink-to-taskbar drawer parks the bar, and where it reopens.

    All of it is arithmetic against a screen rectangle, which is exactly the
    sort of thing that is wrong by one monitor and impossible to see on the
    machine it was written on.
    """
    park = efr_core.drawer_park_top
    gap = efr_core.DRAWER_GAP_PX
    bar = 48.0

    # primary screen, taskbar at the bottom: the bar sits clear of it
    top = park(0.0, 1040.0, bar)
    if top != 1040.0 - bar - gap:
        problems.append('drawer: parked at {0} on the primary screen, '
                        'expected {1}'.format(top, 1040.0 - bar - gap))

    # a screen above the primary one has a negative top, and the bar must
    # follow it rather than landing on the primary screen
    top = park(-1080.0, 1080.0, bar)
    if top != -1080.0 + 1080.0 - bar - gap:
        problems.append('drawer: ignored the monitor offset, parked at '
                        '{0}'.format(top))

    # a work area shorter than the bar must not push it off the desktop
    if park(100.0, 20.0, bar) != 100.0:
        problems.append('drawer: parked below a screen too short to hold it')

    moved = efr_core.drawer_moved
    if moved(10.0, 900.0, None):
        problems.append('drawer: called it moved before it was ever parked')
    if moved(10.0, 900.0, (10.0, 900.0)):
        problems.append('drawer: a bar sitting still counts as moved')
    if moved(11.0, 901.0, (10.0, 900.0)):
        problems.append('drawer: a one pixel nudge counts as moved')
    if not moved(10.0, 400.0, (10.0, 900.0)):
        problems.append('drawer: a bar carried up the screen does not count '
                        'as moved')

    opened = efr_core.drawer_open_top
    # left where it was parked, it goes back exactly where it came from
    if opened(982.0, bar, 880.0, 0.0, 140.0, False) != 140.0:
        problems.append('drawer: an untouched bar did not reopen where the '
                        'window started')
    # carried elsewhere, it opens upward from the bar it now is
    if opened(600.0, bar, 300.0, 0.0, 140.0, True) != 600.0 + bar - 300.0:
        problems.append('drawer: a moved bar did not open upward from where '
                        'it sits')
    # and never off the top of the screen
    if opened(100.0, bar, 880.0, 0.0, 140.0, True) != 0.0:
        problems.append('drawer: opened off the top of the work area')


# -- the fast parameter read -------------------------------------------------

class LParam(object):
    """A parameter as the lookup sees it: an id and a definition."""
    def __init__(self, pid, owner):
        self.Id = FakeId(pid)
        self.Definition = ('def', pid)
        self.owner = owner


class FakeCat(object):
    def __init__(self, n):
        self.Id = FakeId(n)


class LElem(object):
    """An element with a parameter list and a get_Parameter that can be made
    to lie, or to throw, the way an API surprise would."""
    def __init__(self, n, pids, lie=None, throws=False, category=1):
        self.n = n
        self.Category = FakeCat(category)
        self.params = dict((p, LParam(p, n)) for p in pids)
        self.lie = lie            # pid whose fast answer is the wrong parameter
        self.throws = throws

    @property
    def Parameters(self):
        return list(self.params.values())

    def get_Parameter(self, definition):
        if self.throws:
            raise ValueError('not on this release')
        pid = definition[1]
        if pid == self.lie:
            others = [p for p in self.params.values() if p.Id.Value != pid]
            return others[0] if others else None
        return self.params.get(pid)


def read_all(elements, pids):
    lookup = efr_core.ParamLookup()
    got = []
    for e in elements:
        view = lookup.view(e)
        row = []
        for p in pids:
            found = view.get(p)          # once, as the reader asks
            row.append(found.Id.Value if found is not None else None)
        got.append(tuple(row))
    return lookup, got


def expected(elements, pids):
    return [tuple((p if p in e.params else None) for p in pids)
            for e in elements]


def check_param_lookup(problems):
    """The targeted read gives exactly the full listing's answers, and
    stops listing once it has earned the right to."""
    pids = [-1001, -1002, 7, 8]
    elems = [LElem(i, pids) for i in range(200)]
    lookup, got = read_all(elems, pids)
    if got != expected(elems, pids):
        problems.append('param lookup: honest elements read wrongly')
    if lookup.listings > efr_core.PARAM_VERIFY + 2:
        problems.append('param lookup: listed every parameter {0} times for '
                        '200 elements — the fast path is never '
                        'taken'.format(lookup.listings))

    # an API that hands back the wrong parameter for one id
    elems = [LElem(i, pids, lie=8) for i in range(60)]
    lookup, got = read_all(elems, pids)
    if got != expected(elems, pids):
        problems.append('param lookup: trusted a fast answer that disagreed '
                        'with the full listing')
    if 8 not in lookup.slow:
        problems.append('param lookup: a lying parameter was not sent back '
                        'to the slow path')

    # an API where the call is not there at all
    elems = [LElem(i, pids, throws=True) for i in range(40)]
    lookup, got = read_all(elems, pids)
    if got != expected(elems, pids):
        problems.append('param lookup: a throwing get_Parameter lost values')

    # a field only some elements carry, and those not the first ones
    elems = ([LElem(i, [7]) for i in range(40)] +
             [LElem(i, [7, 8]) for i in range(40, 80)])
    lookup, got = read_all(elems, [7, 8])
    if got != expected(elems, [7, 8]):
        problems.append('param lookup: a parameter first seen late was read '
                        'wrongly')

    # ducts first, every one honest, then pipes where the fast answer is
    # wrong — checking only the first rows of the schedule would miss it
    elems = ([LElem(i, pids, category=10) for i in range(80)] +
             [LElem(i, pids, lie=7, category=20) for i in range(80, 160)])
    lookup, got = read_all(elems, pids)
    if got != expected(elems, pids):
        problems.append('param lookup: a category further down the schedule '
                        'was never checked')

    # one type shared by a hundred rows, then other types in the same
    # category whose fast answer is wrong: the shared type must not use up
    # the category's checks by being asked a hundred times
    lookup = efr_core.ParamLookup()
    shared = lookup.view(LElem(0, pids, category=30))
    for _ in range(100):
        shared.get(7)
        shared.get(8)
    wrong = 0
    for i in range(1, 12):
        found = lookup.view(LElem(i, pids, lie=8, category=30)).get(8)
        if found is None or found.Id.Value != 8:
            wrong += 1
    if wrong:
        problems.append('param lookup: a type shared by many rows used up the '
                        'checks, and {0} other types were trusted '
                        'wrongly'.format(wrong))

    view = efr_core.ParamLookup().view(LElem(0, [7]))
    if view.get(99, 'nothing') != 'nothing':
        problems.append('param lookup: .get() ignores its default, so it is '
                        'not a drop-in for the dict it replaced')
    if efr_core.ParamLookup().view(None).get(7) is not None:
        problems.append('param lookup: a missing type element did not read '
                        'as empty')


# -- the grid's row layout ---------------------------------------------------

class GField(object):
    def __init__(self, index):
        self.index = index


class GModel(object):
    def __init__(self, n):
        self.fields = [GField(i) for i in range(n)]

    def current_text(self, row, index):
        return u'v{0}'.format(index)


class GRow(object):
    elem_id = FakeId(4242)


def check_grid_row_values(problems):
    """Each row's values land under the columns they were meant for."""
    cols = efr_core.GRID_META_COLS
    values = efr_core.grid_row_values(GModel(3), GRow(), 6)
    if len(values) != len(cols) + 3:
        problems.append('grid row: {0} values for {1} columns'.format(
            len(values), len(cols) + 3))
        return
    want = {'ridx': u'6', 'rn': u'7', 'eid': u'4242', 'vis': '1',
            'gkey': '', 'grp': '', 'show': '1'}
    for name, value in want.items():
        if name not in cols:
            problems.append('grid row: no {0} column'.format(name))
            continue
        if values[cols.index(name)] != value:
            problems.append('grid row: {0} holds {1!r}, expected {2!r}'.format(
                name, values[cols.index(name)], value))
    if values[len(cols):] != [u'v0', u'v1', u'v2']:
        problems.append('grid row: the schedule values are out of order')


# -- writing flags into the bound table --------------------------------------

class FlagRow(object):
    def __init__(self, **values):
        self.values = dict(values)
        self.writes = 0

    def __getitem__(self, name):
        return self.values[name]

    def __setitem__(self, name, value):
        self.writes += 1
        self.values[name] = value


def check_set_flag(problems):
    """A flag that is already right is not written again."""
    row = FlagRow(vis='1')
    efr_core.set_flag(row, 'vis', '1')
    if row.writes:
        problems.append('set_flag: rewrote a flag that had not changed — each '
                        'write is a notification to the grid')
    efr_core.set_flag(row, 'vis', '0')
    if row.values['vis'] != '0' or row.writes != 1:
        problems.append('set_flag: did not write a flag that changed')


# -- staged-edit keys --------------------------------------------------------

def check_key_cache(problems):
    """A cell's key is worked out once, and is the same answer every time."""
    calls = {'n': 0}
    original = efr_core.eid_value

    def counting(element_id):
        calls['n'] += 1
        return original(element_id)

    row = efr_core.RowInfo()
    row.ridx = 3
    ci = efr_core.CellInfo()
    ci.target_id = FakeId(11)
    ci.param_id = FakeId(-22)
    row.cells.append(ci)
    scratch = efr_core.CellInfo()
    scratch.scratch = True
    row.cells.append(scratch)
    efr_core.eid_value = counting
    try:
        first = efr_core.ScheduleModel.key_of(None, row, 0)
        for _ in range(50):
            again = efr_core.ScheduleModel.key_of(None, row, 0)
    finally:
        efr_core.eid_value = original
    if first != (11, -22) or again != first:
        problems.append('key cache: the key changed between calls')
    if calls['n'] > 2:
        problems.append('key cache: {0} calls into .NET for 51 lookups of one '
                        'cell — it is not being kept'.format(calls['n']))
    if efr_core.ScheduleModel.key_of(None, row, 1) != ('S', 3, 1):
        problems.append('key cache: a scratch cell lost its per-row key')
    blank = efr_core.RowInfo()
    blank.cells.append(efr_core.CellInfo())
    if efr_core.ScheduleModel.key_of(None, blank, 0) is not None:
        problems.append('key cache: a cell with no target got a key')


# -- window settings migration ------------------------------------------------

def run_migration(start):
    """Run the migration against an in-memory settings store."""
    store = dict(start)
    load, save = efr_core.load_settings, efr_core.save_settings
    efr_core.load_settings = lambda: dict(store)
    efr_core.save_settings = lambda values: store.update(values or {})
    try:
        efr_core.migrate_window_settings()
    finally:
        efr_core.load_settings, efr_core.save_settings = load, save
    return store


def check_window_migration(problems):
    """The modal setting the old false alarm caused is undone once, and a
    choice made after the fix is left alone."""
    old = run_migration({'modeless': False, 'modeless_pending': True,
                         'modeless_proved': False, 'theme': 'light'})
    if old.get('modeless') is not True:
        problems.append('window settings: an install left modal by the old '
                        'false alarm stays modal')
    if old.get('modeless_pending') or old.get('modeless_proved'):
        problems.append('window settings: the old health record survived, so '
                        'the next launch can raise the false alarm again')
    if old.get('theme') != 'light':
        problems.append('window settings: the reset touched unrelated settings')
    chosen = dict(old)
    chosen['modeless'] = False                   # chosen deliberately, later
    again = run_migration(chosen)
    if again.get('modeless') is not False:
        problems.append('window settings: a modal choice made after the fix '
                        'was overridden on the next launch')
    fresh = run_migration({})
    if fresh.get('modeless') is not True:
        problems.append('window settings: a first run does not open modeless')


# -- worksets ------------------------------------------------------------------

WORKSETS = [(u'Level 1 - Mechanical', 101), (u'Level 2 - Mechanical', 102),
            (u'Level 10 - Mechanical', 110), (u'Shared Levels and Grids', 1)]


def check_workset_names(problems):
    """A typed or pasted name finds its workset, spelled the model's way."""
    find = efr_core.workset_named
    if find(WORKSETS, u'level 2  -  mechanical') != (u'Level 2 - Mechanical', 102):
        problems.append('worksets: case and spacing stopped a name matching')
    if find(WORKSETS, u'Level 3 - Mechanical') is not None:
        problems.append('worksets: a name that is no workset was accepted')
    if find(WORKSETS, u'   ') is not None or find(WORKSETS, u'') is not None:
        problems.append('worksets: a blank was accepted as a workset')
    if find(WORKSETS, u'Level 1') is not None:
        problems.append('worksets: part of a name was taken as the whole')


def check_workset_fill(problems):
    """Filling a Workset column copies and never counts."""
    fill = efr_core.fill_copy_only
    one = fill([u'Level 2 - Mechanical'], 3, True)
    if one != [u'Level 2 - Mechanical'] * 3:
        problems.append('workset fill: one seed became {0!r} - counting would '
                        'invent worksets'.format(one))
    block = fill([u'Level 1 - Mechanical', u'Level 2 - Mechanical'], 4, True)
    plain = efr_core.fill_plan([u'A', u'B'], 4, True)
    mapped = [{u'A': u'Level 1 - Mechanical', u'B': u'Level 2 - Mechanical'}[v]
              for v in plain]
    if block != mapped:
        problems.append('workset fill: a block of two did not repeat the way '
                        'any other column repeats it')
    up = fill([u'Level 10 - Mechanical'], 2, False)
    if up != [u'Level 10 - Mechanical'] * 2:
        problems.append('workset fill: filling upward counted down')
    if fill([], 3, True) != [] or fill([u'x'], 0, True) != []:
        problems.append('workset fill: empty seeds or count did not give nothing')


class StageModel(object):
    """Just enough of ScheduleModel for stage() to run."""
    def __init__(self):
        self.worksets = list(WORKSETS)
        self.workset_fields = set([0])
        row = efr_core.RowInfo()
        row.ridx = 0
        for i, original in enumerate((u'Level 1 - Mechanical', u'old mark')):
            ci = efr_core.CellInfo()
            ci.editable = True
            ci.original = original
            ci.target_id = FakeId(500)
            ci.param_id = FakeId(-1002330 if i == 0 else 77)
            row.cells.append(ci)
        self.rows = [row]
        self.edits = {}
        self.failed = set()

    def key_of(self, row, fidx):
        return efr_core.ScheduleModel.key_of(None, row, fidx)

    def store_for(self, key):
        return self.edits


class StageHost(object):
    def __init__(self):
        self.model = StageModel()
        self._batch = None
        self._importing = False
        self.imported = set()
        self.last_refusal = u''

    def push_to_table(self, key):
        pass


def check_workset_stage(problems):
    """Only a real workset reaches the staged edits, in the model's spelling;
    other columns are untouched by the rule."""
    stage = efr_core.ExcelForRevitWindow.stage
    host = StageHost()
    host.refused = 0
    if stage(host, 0, 0, u'Nonsense Workset'):
        problems.append('workset stage: an unknown workset name was staged')
    if 'not a workset' not in host.last_refusal:
        problems.append('workset stage: a refused name gave no reason to show')
    host.last_refusal = u''
    if stage(host, 0, 0, u''):
        problems.append('workset stage: a blank Workset cell was staged')
    if not stage(host, 0, 0, u'shared levels and grids'):
        problems.append('workset stage: a real workset was refused')
    if u'Shared Levels and Grids' not in host.model.edits.values():
        problems.append('workset stage: the name was not staged in the '
                        "model's own spelling")
    if not stage(host, 0, 1, u'anything at all'):
        problems.append('workset stage: the workset rule leaked into another '
                        'column')


def check_skipped_note(problems):
    """Read-only cells and refused values are reported apart."""
    note = efr_core.ExcelForRevitWindow.skipped_note
    host = StageHost()
    host.refused = 0
    host.last_refusal = u''
    if 'read-only' not in note(host, 3):
        problems.append('skipped note: plain read-only cells not reported as such')
    host.refused = 1
    host.last_refusal = u'"Foo" is not a workset in this model'
    text = note(host, 7)
    if '6 read-only' not in text or '1 refused' not in text:
        problems.append('skipped note: 6 read-only and 1 refused came out as '
                        '{0!r}'.format(text))
    if note(host, 0):
        problems.append('skipped note: said something with nothing skipped')


class SetParam(object):
    def __init__(self, accept=True):
        self.value = None
        self.accept = accept

    def Set(self, value):
        self.value = value
        return self.accept


def check_workset_write(problems):
    """Apply writes the workset's id, never its name."""
    param = SetParam()
    ok, msg = efr_core.write_workset(param, u'Level 10 - Mechanical', WORKSETS)
    if not ok or param.value != 110:
        problems.append('workset write: wrote {0!r}, expected the id '
                        '110'.format(param.value))
    ok, msg = efr_core.write_workset(SetParam(), u'Gone Workset', WORKSETS)
    if ok or 'no workset' not in msg:
        problems.append('workset write: a workset deleted since staging was '
                        'written anyway')
    ok, msg = efr_core.write_workset(SetParam(False), u'Level 1 - Mechanical',
                                     WORKSETS)
    if ok or not msg:
        problems.append('workset write: a refusal from Revit was reported as '
                        'success')


CHECKS = (check_join, check_lookup, check_parts, check_fill, check_duplicates,
          check_isolate, check_default_3d, check_drawer, check_param_lookup,
          check_grid_row_values, check_set_flag, check_key_cache,
          check_window_migration, check_workset_names, check_workset_fill,
          check_workset_stage, check_workset_write, check_skipped_note)


def run():
    problems = []
    for check in CHECKS:
        try:
            check(problems)
        except Exception:
            import traceback
            problems.append('{0} raised:\n{1}'.format(check.__name__,
                                                      traceback.format_exc()))
    return problems


def selftest():
    """Break the logic on purpose; each break must be caught."""
    print('Self test - each of these must be CAUGHT:')
    ok = True
    original_join = efr_core.join_combined
    original_value = efr_core.combined_value
    original_find = efr_core.find_duplicates
    original_isolate = efr_core.ExcelForRevitWindow.isolate_duplicates
    original_park = efr_core.drawer_park_top
    original_open = efr_core.drawer_open_top
    original_moved = efr_core.drawer_moved

    # -- the speed work: each shortcut broken the way it could go wrong ------
    original_get = efr_core.ParamView.get
    original_rowvals = efr_core.grid_row_values
    original_flag = efr_core.set_flag
    original_key = efr_core.ScheduleModel.key_of

    def trusting_get(self, pid, default=None):
        """The fast path with the verification taken out."""
        if self.elem is None:
            return default
        lk = self.lookup
        defn = lk.defs.get(pid)
        if defn is None:
            p = self.full().get(pid)
            if p is not None:
                lk.defs[pid] = p.Definition
            return default if p is None else p
        try:
            p = self.elem.get_Parameter(defn)
        except Exception:
            p = self.full().get(pid)
        return default if p is None else p

    def listing_get(self, pid, default=None):
        """Correct, but lists every parameter every time — the old speed."""
        if self.elem is None:
            return default
        p = self.full().get(pid)
        return default if p is None else p

    def swapped_rowvals(model, row, n):
        values = original_rowvals(model, row, n)
        values[1], values[2] = values[2], values[1]     # rn and eid crossed
        return values

    def always_write(row, name, value):
        row[name] = value
        return True

    def uncached_key(self, row, field_index):
        ci = row.cells[field_index]
        if getattr(ci, 'scratch', False):
            return ('S', row.ridx, field_index)
        if ci.target_id is None or ci.param_id is None:
            return None
        return (efr_core.eid_value(ci.target_id),
                efr_core.eid_value(ci.param_id))

    original_view = efr_core.ParamLookup.view
    original_migrate = efr_core.migrate_window_settings
    original_named = efr_core.workset_named
    original_copy = efr_core.fill_copy_only
    original_wwrite = efr_core.write_workset

    def named_exact(worksets, text):
        for name, value in worksets:
            if name == text:
                return (name, value)
        return None

    def named_anything(worksets, text):
        return (text, 0)

    def copy_counts(seeds, count, downward):
        return efr_core.fill_plan(seeds, count, downward)

    def write_name(param, text, worksets):
        return bool(param.Set(text)), ''

    for label, attr, bad, original in (
            ('workset names matched only exactly', 'workset_named',
             named_exact, original_named),
            ('any text accepted as a workset', 'workset_named',
             named_anything, original_named),
            ('workset fill counts like any other column', 'fill_copy_only',
             copy_counts, original_copy),
            ('the workset written as its name', 'write_workset',
             write_name, original_wwrite)):
        setattr(efr_core, attr, bad)
        try:
            caught = bool(run())
        finally:
            setattr(efr_core, attr, original)
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught

    def migrate_every_time():
        efr_core.save_settings({'modeless': True, 'modeless_pending': False,
                                'modeless_proved': False,
                                'window_settings': 2})

    def migrate_never():
        return None

    for label, bad in (('the reset overrides a later modal choice',
                        migrate_every_time),
                       ('the old modal setting is never reset', migrate_never)):
        efr_core.migrate_window_settings = bad
        try:
            caught = bool(run())
        finally:
            efr_core.migrate_window_settings = original_migrate
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught

    def unremembered_get(self, pid, default=None):
        if self.elem is None:
            return default
        p = self._resolve(pid)
        return default if p is None else p

    def one_category_view(self, elem):
        return efr_core.ParamView(self, elem, None)

    for label, target, attr, bad, original in (
            ('a shared type spends the checks meant for other types',
             efr_core.ParamView, 'get', unremembered_get, original_get),
            ('fast parameter read only checked on the first category',
             efr_core.ParamLookup, 'view', one_category_view, original_view),
            ('fast parameter read trusted without checking',
             efr_core.ParamView, 'get', trusting_get, original_get),
            ('fast parameter read never actually taken',
             efr_core.ParamView, 'get', listing_get, original_get),
            ('grid row values out of step with the columns',
             efr_core, 'grid_row_values', swapped_rowvals, original_rowvals),
            ('bound table flags rewritten when unchanged',
             efr_core, 'set_flag', always_write, original_flag),
            ('cell keys rebuilt on every lookup',
             efr_core.ScheduleModel, 'key_of', uncached_key, original_key)):
        setattr(target, attr, bad)
        try:
            caught = bool(run())
        finally:
            setattr(target, attr, original)
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught

    for label, bad_park, bad_open, bad_moved in (
            ('drawer parks against the primary screen',
             lambda t, h, b: h - b - efr_core.DRAWER_GAP_PX, None, None),
            ('drawer parks below a screen too short for it',
             lambda t, h, b: t + h - b - efr_core.DRAWER_GAP_PX, None, None),
            ('drawer always reopens where the window started', None,
             lambda bt, b, h, at, st, mv: st, None),
            ('drawer reopens off the top of the screen', None,
             lambda bt, b, h, at, st, mv: st if not mv else bt + b - h, None),
            ('any nudge counts as the user moving the bar', None, None,
             lambda l, t, d: d is not None and (l, t) != tuple(d))):
        efr_core.drawer_park_top = bad_park or original_park
        efr_core.drawer_open_top = bad_open or original_open
        efr_core.drawer_moved = bad_moved or original_moved
        try:
            caught = bool(run())
        finally:
            efr_core.drawer_park_top = original_park
            efr_core.drawer_open_top = original_open
            efr_core.drawer_moved = original_moved
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught

    def counts_blanks(values):
        counts = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return sorted(v for v in counts if counts[v] > 1)

    def counts_singles(values):
        return sorted(set(v for v in values if v.strip()))

    def forgets_filter(self, fi, on):
        if on:
            self.col_picks[fi.index] = set(self.duplicate_values(fi))
            self.dup_isolated.add(fi.index)
        else:
            self.col_picks.pop(fi.index, None)
            self.dup_isolated.discard(fi.index)
        self.apply_filters()
        return on

    original_rank = efr_core.default_3d_rank

    def rank_backwards(name):
        return 2 - original_rank(name)

    efr_core.default_3d_rank = rank_backwards
    try:
        caught = bool(run())
    finally:
        efr_core.default_3d_rank = original_rank
    print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ',
                             'the wrong 3D view chosen'))
    ok = ok and caught

    for label, bad_find, bad_isolate in (
            ('blanks counted as duplicates', counts_blanks, None),
            ('values seen once counted', counts_singles, None),
            ('un-isolate throws the old filter away', None, forgets_filter)):
        efr_core.find_duplicates = bad_find or original_find
        efr_core.ExcelForRevitWindow.isolate_duplicates = (
            bad_isolate or original_isolate)
        try:
            caught = bool(run())
        finally:
            efr_core.find_duplicates = original_find
            efr_core.ExcelForRevitWindow.isolate_duplicates = original_isolate
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught

    breaks = [
        ('separator written after the last part',
         lambda pieces: u''.join(u'{0}{1}{2}{3}'.format(*p) for p in pieces),
         None),
        ('empty values dropped',
         lambda pieces: original_join([p for p in pieces if p[1]]),
         None),
        ('prefix and suffix ignored',
         lambda pieces: original_join([(u'', p[1], u'', p[3]) for p in pieces]),
         None),
        ('type parameters never looked up', None,
         lambda doc, parts, imap, tmap: original_value(doc, parts, imap, {})),
        ('type wins over instance', None,
         lambda doc, parts, imap, tmap: original_value(doc, parts, tmap, imap)),
    ]
    for label, bad_join, bad_value in breaks:
        efr_core.join_combined = bad_join or original_join
        efr_core.combined_value = bad_value or original_value
        try:
            caught = bool(run())
        finally:
            efr_core.join_combined = original_join
            efr_core.combined_value = original_value
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught
    return ok


def main():
    if '--selftest' in sys.argv:
        good = selftest()
        print('\nSelf test {0}'.format('PASSED' if good else 'FAILED'))
        return 0 if good else 1
    problems = run()
    if problems:
        print('FAILED - {0} problem(s):'.format(len(problems)))
        for p in problems:
            print('  ' + p)
        return 1
    print('All logic checks passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
