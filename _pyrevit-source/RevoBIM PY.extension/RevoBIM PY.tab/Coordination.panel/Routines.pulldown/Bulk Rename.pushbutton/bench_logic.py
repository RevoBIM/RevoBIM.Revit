# -*- coding: utf-8 -*-
"""Bulk Rename logic checks under CPython. --selftest proves each one can fail."""
import importlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def load(folder):
    sys.path.insert(0, folder)
    import bench_stubs
    importlib.reload(bench_stubs)
    bench_stubs.install()
    modules = {}
    for name in ('brn_core', 'brn_drawer', 'brn_revit'):
        modules[name] = importlib.import_module(name)
    return bench_stubs, modules


class Doc(object):
    def __init__(self, stubs, workshared=False):
        self.elements = {}
        self.stubs = stubs
        self.IsWorkshared = workshared
        self.owned = {}
        self.refuse = set()
        self.silent = set()
        self.undo_on_commit = set()

    def add(self, element):
        self.elements[element.Id.Value] = element

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)

    def scope(self, element):
        return getattr(element, 'ViewType', type(element).__name__)

    def check_name(self, element, value):
        if element.Id.Value in self.refuse:
            raise ValueError('Revit said no')
        for other in self.elements.values():
            if other is element or self.scope(other) != self.scope(element):
                continue
            if self.scope(element) == 'DrawingSheet':
                continue
            if other.stored_name == value:
                raise ValueError('The name entered is already in use.')

    def check_number(self, element, value):
        for other in self.elements.values():
            if other is not element and getattr(other, 'stored_number', None) == value:
                raise ValueError('number in use')

    def snapshot(self):
        return dict((k, (e.stored_name, getattr(e, 'stored_number', None)))
                    for k, e in self.elements.items())

    def restore(self, snap):
        for key, value in snap.items():
            element = self.elements[key]
            element.stored_name = value[0]
            if value[1] is not None:
                element.stored_number = value[1]

    def on_commit(self):
        for key, value in self.undo_on_commit:
            self.elements[key].stored_name = value


def views(stubs, *names):
    doc = Doc(stubs)
    return doc, [stubs.View(i + 1, n, doc) for i, n in enumerate(names)]


def run(stubs, m, doc, picked, rules_name=None, rules_number=None):
    core = m['brn_core']
    rows, _ = m['brn_revit'].read_selection(doc, [e.Id for e in picked])
    rules = {core.FIELD_NAME: rules_name or core.Rules(),
             core.FIELD_NUMBER: rules_number or core.Rules()}
    return m['brn_revit'].apply_job(doc, rows, rules, lambda text: None)


@check
def find_replace_case(s, m):
    c = m['brn_core']
    assert c.apply_rules(u'Level 01 level', c.Rules(find=u'level', replace=u'L'))[0] == u'L 01 L'
    assert c.apply_rules(u'Level 01 level', c.Rules(find=u'level', replace=u'L', case=True))[0] == u'Level 01 L'


@check
def find_is_literal(s, m):
    c = m['brn_core']
    assert c.apply_rules(u'A.B AxB', c.Rules(find=u'.', replace=u'-'))[0] == u'A-B AxB'


@check
def prefix_suffix_order(s, m):
    c = m['brn_core']
    new, segs = c.apply_rules(u'Plan', c.Rules(find=u'la', replace=u'LA', prefix=u'A-', suffix=u'-Z'))
    assert new == u'A-PLANn-Z'.replace(u'PLANn', u'PLAn')
    assert segs == [(u'A-', True), (u'P', False), (u'LA', True), (u'n', False), (u'-Z', True)]


@check
def nothing_typed_is_same(s, m):
    c = m['brn_core']
    row = c.Row(1, 1, u'x', u'Plan', name_scope=u'v')
    items = c.evaluate([row], {'name': c.Rules(), 'number': c.Rules()}, {})
    assert items[0].state == c.SAME and not c.changes(items)


def _eval(c, names, rules, taken=None):
    rows = [c.Row(i, i, u'x', n, name_scope=u'v') for i, n in enumerate(names)]
    return c.evaluate(rows, {'name': rules, 'number': c.Rules()}, taken or {})


@check
def clash_outside_batch(s, m):
    c = m['brn_core']
    items = _eval(c, [u'A'], c.Rules(find=u'A', replace=u'B'), {u'v': set([u'B'])})
    assert items[0].state == c.CLASH


@check
def two_landing_together_both_clash(s, m):
    c = m['brn_core']
    items = _eval(c, [u'A1', u'A2'], c.Rules(find=u'1', replace=u'2'))
    assert items[0].state == c.CLASH


@check
def clash_cascades(s, m):
    c = m['brn_core']
    items = _eval(c, [u'x1', u'x2'], c.Rules(find=u'x', replace=u'y'), {u'v': set([u'y1'])})
    assert items[0].state == c.CLASH and items[1].state == c.CHANGE
    rows = [c.Row(0, 0, u'x', u'a', name_scope=u'v'), c.Row(1, 1, u'x', u'ab', name_scope=u'v')]
    items = c.evaluate(rows, {'name': c.Rules(suffix=u'b'), 'number': c.Rules()}, {u'v': set([u'abb'])})
    assert items[1].state == c.CLASH and items[0].state == c.CLASH


@check
def sheet_names_not_checked(s, m):
    c = m['brn_core']
    rows = [c.Row(i, i, u'Sheet', u'P%d' % i, number=u'N%d' % i, number_scope=u'n') for i in range(2)]
    items = c.evaluate(rows, {'name': c.Rules(find=u'P0', replace=u'P1'), 'number': c.Rules()}, {})
    assert [i.state for i in items if i.field == 'name'] == [c.CHANGE, c.SAME]


@check
def illegal_and_empty(s, m):
    c = m['brn_core']
    assert _eval(c, [u'A'], c.Rules(prefix=u'x:'))[0].state == c.BAD
    assert _eval(c, [u'A'], c.Rules(find=u'A', replace=u''))[0].state == c.BAD
    assert _eval(c, [u'A:B'], c.Rules(prefix=u'x'))[0].state == c.CHANGE


@check
def status_counts(s, m):
    c = m['brn_core']
    assert c.status_line(_eval(c, [u'A', u'B'], c.Rules(prefix=u'x'))) == u'2 will change'


@check
def natural_order_sheets_first(s, m):
    c = m['brn_core']
    rows = [c.Row(1, 1, u'Floor plan', u'L10'), c.Row(2, 2, u'Floor plan', u'L2'),
            c.Row(3, 3, u'Sheet', u's', number=u'M-10'), c.Row(4, 4, u'Sheet', u's', number=u'M-9')]
    assert [r.key for r in c.sort_rows(rows)] == [4, 3, 2, 1]


@check
def selection_keeps_browser_items_only(s, m):
    doc, (a,) = views(s, u'Plan')
    sheet = s.ViewSheet(5, u'S', u'M1', doc)
    family = s.Family(6, u'F', doc)
    etype = s.ElementType(7, u'T', doc)
    link = s.RevitLinkType(8, u'L', doc)
    wall = s.Element(9, u'wall', doc)
    tmpl = s.View(10, u'tmpl', doc)
    tmpl.IsTemplate = True
    rows, left = m['brn_revit'].read_selection(doc, [e.Id for e in (a, sheet, family, etype, link, wall, tmpl)])
    assert len(rows) == 4 and left == 3


@check
def canvas_selection_gives_no_rows(s, m):
    doc = Doc(s)
    pipe = s.Element(1, u'pipe', doc)
    assert m['brn_revit'].read_selection(doc, [pipe.Id])[0] == []


@check
def taken_excludes_batch(s, m):
    doc, (a, b) = views(s, u'A', u'B')
    rows, _ = m['brn_revit'].read_selection(doc, [a.Id])
    assert m['brn_revit'].read_taken(doc, rows) == {u'view:FloorPlan': set([u'B'])}


@check
def apply_writes_and_counts(s, m):
    doc, (a, b) = views(s, u'A', u'B')
    report = run(s, m, doc, [a, b], m['brn_core'].Rules(prefix=u'X-'))
    assert (a.stored_name, b.stored_name, report.done) == (u'X-A', u'X-B', 2)
    assert not report.failed


@check
def swap_goes_through_park(s, m):
    c = m['brn_core']
    doc, (a, b) = views(s, u'L1', u'L2')
    rows, _ = m['brn_revit'].read_selection(doc, [a.Id, b.Id])
    # a two-way swap cannot come from one rule, so drive the chain case
    doc2, (x, y) = views(s, u'L1', u'L1X')
    report = run(s, m, doc2, [x, y], c.Rules(suffix=u'X'))
    assert (x.stored_name, y.stored_name) == (u'L1X', u'L1XX') and report.done == 2


@check
def sheet_name_and_number_both_write(s, m):
    c = m['brn_core']
    doc = Doc(s)
    sheet = s.ViewSheet(1, u'Plan', u'M1', doc)
    report = run(s, m, doc, [sheet], c.Rules(prefix=u'A '), c.Rules(prefix=u'E'))
    assert (sheet.stored_name, sheet.stored_number, report.done) == (u'A Plan', u'EM1', 2)


@check
def one_refusal_keeps_the_rest(s, m):
    doc, (a, b) = views(s, u'A', u'B')
    doc.refuse.add(1)
    report = run(s, m, doc, [a, b], m['brn_core'].Rules(prefix=u'X'))
    assert (a.stored_name, b.stored_name, report.done, len(report.failed)) == (u'A', u'XB', 1, 1)


@check
def refused_parked_goes_back(s, m):
    c = m['brn_core']
    doc, (x, y) = views(s, u'L1', u'L1X')
    original = doc.check_name

    def picky(element, value):
        if value == u'L1XX':
            raise ValueError('no')
        original(element, value)
    doc.check_name = picky
    report = run(s, m, doc, [x, y], c.Rules(suffix=u'X'))
    assert (x.stored_name, y.stored_name) == (u'L1', u'L1X') and report.failed


@check
def owned_is_reported_with_name(s, m):
    doc, (a, b) = views(s, u'A', u'B')
    doc.IsWorkshared = True
    doc.owned[1] = u'jsmith'
    report = run(s, m, doc, [a, b], m['brn_core'].Rules(prefix=u'X'))
    assert a.stored_name == u'A' and b.stored_name == u'XB'
    assert u'jsmith' in report.failed[0][1]


@check
def rechecks_at_write_time(s, m):
    c = m['brn_core']
    doc, (a,) = views(s, u'A')
    rows, _ = m['brn_revit'].read_selection(doc, [a.Id])
    s.View(2, u'XA', doc)       # appeared after the preview
    rules = {c.FIELD_NAME: c.Rules(prefix=u'X'), c.FIELD_NUMBER: c.Rules()}
    report = m['brn_revit'].apply_job(doc, rows, rules, lambda t: None)
    assert a.stored_name == u'A' and report.failed[0][1].startswith(u'Already')


@check
def deleted_while_open(s, m):
    c = m['brn_core']
    doc, (a, b) = views(s, u'A', u'B')
    rows, _ = m['brn_revit'].read_selection(doc, [a.Id, b.Id])
    del doc.elements[1]
    rules = {c.FIELD_NAME: c.Rules(prefix=u'X'), c.FIELD_NUMBER: c.Rules()}
    report = m['brn_revit'].apply_job(doc, rows, rules, lambda t: None)
    assert report.done == 1 and report.failed[0][1] == u'No longer in the model'


@check
def count_is_what_stayed(s, m):
    doc, (a,) = views(s, u'A')
    doc.undo_on_commit.add((1, u'A'))
    report = run(s, m, doc, [a], m['brn_core'].Rules(prefix=u'X'))
    assert report.done == 0 and report.failed


@check
def eid_helper(s, m):
    class Old(object):
        IntegerValue = 7
    assert m['brn_revit'].eid_value(s.ElementId(5)) == 5
    assert m['brn_revit'].eid_value(Old()) == 7
    assert m['brn_revit'].eid_value(None) == 0


@check
def runner_queue(s, m):
    logged = []
    runner = m['brn_revit'].Runner(logged.append)

    class Event(object):
        answer = 'Pending'

        def Raise(self):
            return self.answer
    event = Event()
    runner.attach(event)
    ran, refused = [], []
    assert runner.submit(lambda: ran.append(1), refused.append)
    assert runner.submit(lambda: ran.append(2), refused.append)   # not queued twice
    assert len(runner.jobs) == 1
    runner.Execute(None)
    assert ran == [1]
    event.answer = 'Denied'
    assert not runner.submit(lambda: ran.append(3), refused.append)
    assert refused == ['Denied'] and not runner.jobs


@check
def runner_survives_a_throwing_job(s, m):
    runner = m['brn_revit'].Runner(lambda t: None)

    class Event(object):
        def Raise(self):
            return 'Accepted'
    runner.attach(Event())

    def bad():
        raise ValueError('x')
    runner.submit(bad, None)
    runner.Execute(None)
    assert not runner.jobs


@check
def settings_round_trip(s, m):
    c = m['brn_core']
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'x', 's.txt')
    c.save_settings({'theme': 'dark', 'debug': '0'}, path)
    assert c.load_settings(path)['theme'] == 'dark'
    assert c.parse_settings('garbage\ntheme=purple\nx=y=z\n')['theme'] == 'auto'
    shutil.rmtree(folder)


@check
def value_split_on_first_equals(s, m):
    c = m['brn_core']
    c.DEFAULTS['extra'] = ''
    try:
        assert c.parse_settings('extra=a=b')['extra'] == 'a=b'
    finally:
        del c.DEFAULTS['extra']


@check
def theme_rules(s, m):
    c = m['brn_core']
    assert c.next_theme('auto') == 'dark' and c.next_theme('light') == 'auto'
    assert c.resolve_theme('auto', 'light') == 'light'
    assert c.resolve_theme('dark', 'light') == 'dark'
    assert c.canvas_from_rgb(255, 255, 255) == 'light'
    assert c.canvas_from_rgb(30, 30, 30) == 'dark'


@check
def parking_maths(s, m):
    c = m['brn_core']
    assert c.parked_top(0, 1000, 40, 0) == 952
    assert c.parked_top(-1080, 1040, 40, 0) == -88      # monitor above the primary
    assert c.parked_top(0, 1000, 40, 44) == 908
    assert c.free_slot([None, 1]) == 0 and c.free_slot([1]) == 1
    assert c.expand_rect((10, 20, 300, 400), 10, 900, 10, 900, (0, 0, 1000, 1000)) == (10, 20)
    assert c.expand_rect((10, 20, 300, 400), 500, 300, 10, 900, (0, 0, 1000, 1000)) == (500, 0)
    assert c.ease(0) == 0 and c.ease(1) == 1 and c.ease(0.5) == 0.875


@check
def resize_maths(s, m):
    c = m['brn_core']
    assert c.resize((0, 0, 100, 100), 'BR', 10, 20, 50, 50) == (0, 0, 110, 120)
    assert c.resize((0, 0, 100, 100), 'TL', 90, 90, 50, 50) == (50, 50, 50, 50)


@check
def slow_clicks(s, m):
    c = m['brn_core']
    clicks = c.SlowClicks()
    assert not clicks.click(1000) and not clicks.click(1500) and clicks.click(2000)
    clicks = c.SlowClicks()
    assert not clicks.click(1000) and not clicks.click(1100) and not clicks.click(1400)
    clicks = c.SlowClicks()
    assert not clicks.click(1000) and not clicks.click(1500) and not clicks.click(1500) and clicks.click(2000)


@check
def list_width_takes_longest_line(s, m):
    c = m['brn_core']
    assert c.list_width([(50, 300), (200, 0)], gap=10, chrome=30) == 390
    assert c.list_width([(200, 0)], gap=10, chrome=30) == 230
    assert c.list_width([], chrome=30) == 30


@check
def widening_stays_on_screen(s, m):
    c = m['brn_core']
    assert c.widened(100, 600, 200, 0, 1920) == (100, 800)
    assert c.widened(1200, 600, 300, 0, 1920) == (1020, 900)    # right edge kept on
    assert c.widened(100, 600, 5000, 0, 1920) == (0, 1920)
    assert c.widened(100, 600, -50, 0, 1920) == (100, 600)      # never narrower
    assert c.widened(-1800, 600, 300, -1920, 1920) == (-1800, 900)


def _settings(**kw):
    out = {'sheet_param_1': u'T1', 'sheet_param_2': u'T2', 'sheet_param_3': u'T3',
           'sheet_delimiter': u'_'}
    out.update(kw)
    return out


def _sheet(s, doc, key, name):
    sheet = s.ViewSheet(key, name, u'M%d' % key, doc)
    sheet.params = dict((n, s.Param()) for n in (u'T1', u'T2', u'T3'))
    return sheet


def _write(s, m, doc, sheets, settings=None, rename=False, rules=None):
    c = m['brn_core']
    rows, _ = m['brn_revit'].read_selection(doc, [e.Id for e in sheets])
    by_field = {c.FIELD_NAME: rules or c.Rules(), c.FIELD_NUMBER: c.Rules()}
    return m['brn_revit'].rename_and_write(doc, rows, by_field, settings or _settings(),
                                           rename, lambda t: None)


def _values(sheet):
    return [sheet.params[n].value for n in (u'T1', u'T2', u'T3')]


@check
def split_three_parts(s, m):
    c = m['brn_core']
    assert c.split_sheet_name(u'A_B_C', u'_') == [u'A', u'B', u'C']


@check
def split_short_name_blanks_the_rest(s, m):
    c = m['brn_core']
    assert c.split_sheet_name(u'A_B', u'_') == [u'A', u'B', u'']
    assert c.split_sheet_name(u'A', u'') == [u'A', u'', u'']


@check
def split_long_name_keeps_it_all(s, m):
    c = m['brn_core']
    assert c.split_sheet_name(u'A_B_C_D', u'_') == [u'A', u'B', u'C_D']


@check
def split_other_delimiter_and_spaces(s, m):
    c = m['brn_core']
    assert c.split_sheet_name(u'A - B - C', u' - ') == [u'A', u'B', u'C']
    assert c.split_sheet_name(u'A _ B', u'_') == [u'A', u'B', u'']


@check
def blank_slot_is_skipped(s, m):
    c = m['brn_core']
    writes = c.sheet_writes(u'A_B_C', _settings(sheet_param_2=u''))
    assert writes == [(u'T1', u'A'), (u'T3', u'C')]


@check
def delimiter_space_survives_settings(s, m):
    c = m['brn_core']
    assert c.parse_settings('sheet_delimiter= - \n')['sheet_delimiter'] == ' - '
    settings = dict(c.DEFAULTS, sheet_delimiter=' ')
    assert c.parse_settings(c.format_settings(settings))['sheet_delimiter'] == ' '


@check
def write_sheet_names_writes(s, m):
    doc = Doc(s)
    sheet = _sheet(s, doc, 1, u'L00_POWER_LAYOUT')
    report = _write(s, m, doc, [sheet])
    assert _values(sheet) == [u'L00', u'POWER', u'LAYOUT'] and report.written == 1


@check
def write_only_touches_sheets(s, m):
    doc, (a,) = views(s, u'A_B')
    sheet = _sheet(s, doc, 2, u'X_Y')
    report = _write(s, m, doc, [a, sheet])
    assert report.written == 1 and not report.failed


@check
def write_old_value_cleared(s, m):
    doc = Doc(s)
    sheet = _sheet(s, doc, 1, u'A_B')
    sheet.params[u'T3'].value = u'OLD'
    _write(s, m, doc, [sheet])
    assert sheet.params[u'T3'].value == u''


@check
def write_missing_parameter_reported(s, m):
    doc = Doc(s)
    bad = _sheet(s, doc, 1, u'A_B')
    del bad.params[u'T2']
    good = _sheet(s, doc, 2, u'C_D')
    report = _write(s, m, doc, [bad, good])
    assert report.written == 1 and u'T2' in report.failed[0][1]
    assert good.params[u'T1'].value == u'C'


@check
def write_read_only_reported(s, m):
    doc = Doc(s)
    sheet = _sheet(s, doc, 1, u'A_B')
    sheet.params[u'T1'].IsReadOnly = True
    report = _write(s, m, doc, [sheet])
    assert report.failed and not report.written


@check
def write_value_that_did_not_land(s, m):
    doc = Doc(s)
    sheet = _sheet(s, doc, 1, u'A_B')
    sheet.params[u'T1'].stick = False
    report = _write(s, m, doc, [sheet])
    assert u'did not take' in report.failed[0][1] and not report.written


@check
def write_owned_sheet_named(s, m):
    doc = Doc(s, workshared=True)
    doc.owned[1] = u'jsmith'
    sheet = _sheet(s, doc, 1, u'A_B')
    report = _write(s, m, doc, [sheet])
    assert u'jsmith' in report.failed[0][1] and sheet.params[u'T1'].value is None


@check
def write_already_right_not_borrowed(s, m):
    doc = Doc(s, workshared=True)
    doc.owned[1] = u'jsmith'
    sheet = _sheet(s, doc, 1, u'A_B')
    for name, value in zip((u'T1', u'T2', u'T3'), (u'A', u'B', u'')):
        sheet.params[name].value = value
    report = _write(s, m, doc, [sheet])
    assert report.written == 1 and not report.failed


@check
def write_uses_name_after_rename(s, m):
    c = m['brn_core']
    doc = Doc(s)
    sheet = _sheet(s, doc, 1, u'OLD_B')
    report = _write(s, m, doc, [sheet], rename=True, rules=c.Rules(find=u'OLD', replace=u'NEW'))
    assert sheet.stored_name == u'NEW_B' and sheet.params[u'T1'].value == u'NEW'
    assert report.done == 1 and report.written == 1


@check
def text_parameters_only_editable_text(s, m):
    c = m['brn_core']
    doc = Doc(s)
    sheet = _sheet(s, doc, 1, u'A')

    class P(object):
        def __init__(self, name, kind, ro):
            class D(object):
                Name = name
            self.Definition, self.StorageType, self.IsReadOnly = D, kind, ro
    sheet.Parameters = [P(u'b', 'String', False), P(u'A', 'String', False),
                        P(u'n', 'Integer', False), P(u'r', 'String', True)]
    rows, _ = m['brn_revit'].read_selection(doc, [sheet.Id])
    assert m['brn_revit'].text_parameters(doc, rows) == [u'A', u'b']


class FakeTimer(object):
    def __init__(self, tick):
        self.tick = tick
        self.running = False
        self.escaped = []

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    def fire(self):
        try:
            self.tick(None, None)
        except Exception as error:
            self.escaped.append(error)


class Thing(object):
    def __init__(self, **kw):
        self.Visibility = 'V'
        self.__dict__.update(kw)


class Parent(object):
    def __init__(self):
        self.Children = []


class FakeWindow(object):
    def __init__(self):
        self.Left, self.Top, self.ActualWidth, self.ActualHeight = 100., 100., 600., 400.
        self.Height = 400.
        self.MinHeight = 300.
        self.SizeToContent = 'Height'


def rig(s, m, explode=False):
    drawer_mod = m['brn_drawer']
    drawer_mod._slots[:] = []
    parent = Parent()
    header = Thing(ActualHeight=36., Parent=parent)
    body = Thing()
    grips = Thing()
    parent.Children = [header, body, grips]
    root = Thing(Height=float('nan'), VerticalAlignment='Stretch')
    clock = {'t': 0.0}
    timers = []

    def make(tick):
        if explode:
            raise RuntimeError('no timer')
        timers.append(FakeTimer(tick))
        return timers[-1]
    window = FakeWindow()
    drawer = drawer_mod.Drawer(window, header, root, Thing(), Thing(Visibility='C'), grips,
                               lambda: (0., 0., 1000., 1000.), make, ('V', 'C'),
                               clock=lambda: clock['t'])
    return drawer, window, body, grips, root, timers, clock


def finish(timers, clock):
    timer = timers[-1]
    while timer.running:
        clock['t'] += 0.1
        timer.fire()
    assert not timer.escaped


@check
def drawer_parks_and_returns(s, m):
    drawer, window, body, grips, root, timers, clock = rig(s, m)
    drawer.shrink()
    assert drawer.sliding and grips.Visibility == 'C' and window.MinHeight == 0
    finish(timers, clock)
    assert drawer.parked and body.Visibility == 'C' and window.Height == 40
    assert window.Top == 1000 - 40 - 8
    assert drawer.expand_glyph.Visibility == 'V' and drawer.shrink_glyph.Visibility == 'C'
    drawer.expand()
    finish(timers, clock)
    assert not drawer.parked and window.Top == 100 and window.Height == 400
    assert body.Visibility == 'V' and grips.Visibility == 'V'
    assert window.MinHeight == 300 and window.SizeToContent == 'Height'


@check
def drawer_restores_what_was_hidden(s, m):
    drawer, window, body, grips, root, timers, clock = rig(s, m)
    body.Visibility = 'C'
    drawer.shrink()
    finish(timers, clock)
    drawer.expand()
    finish(timers, clock)
    assert body.Visibility == 'C'


@check
def drawer_no_timer_still_lands(s, m):
    drawer, window, body, grips, root, timers, clock = rig(s, m, explode=True)
    drawer.shrink()
    assert drawer.parked and not drawer.sliding


@check
def drawer_throwing_frame_lands(s, m):
    drawer, window, body, grips, root, timers, clock = rig(s, m)
    drawer.shrink()

    class Stop(object):
        def __call__(self):
            raise RuntimeError('frame')
    drawer.clock = Stop()
    clock['t'] += 0.01
    timers[-1].fire()
    assert not timers[-1].escaped
    assert drawer.parked and not drawer.sliding


@check
def drawer_owner_goes_down_and_comes_back(s, m):
    owner, owner_win = rig(s, m)[:2]
    d2 = m['brn_drawer']
    keep = list(d2._slots)
    drawer, window, body, grips, root, timers, clock = rig(s, m)
    d2._slots[:] = keep
    drawer.owner = owner
    drawer.shrink()
    assert owner.parked
    finish(timers, clock)
    assert window.Top < owner_win.Top
    drawer.settle()
    assert not owner.parked


@check
def drawer_carried_bar_opens_from_there(s, m):
    drawer, window, body, grips, root, timers, clock = rig(s, m)
    drawer.shrink()
    finish(timers, clock)
    window.Left, window.Top = 300., 500.
    drawer.expand()
    finish(timers, clock)
    assert window.Left == 300 and window.Top == 140


BREAKAGES = [
    ('brn_core.py', "parts = parts[:count - 1] + [delimiter.join(parts[count - 1:])]", "parts = parts[:count]", 'split_long_name_keeps_it_all'),
    ('brn_core.py', "return parts + [u''] * (count - len(parts))", "return parts", 'split_short_name_blanks_the_rest'),
    ('brn_core.py', "parts = [p.strip() for p in parts]", "pass", 'split_other_delimiter_and_spaces'),
    ('brn_core.py', "        if param:\n            out.append((param, value))", "        out.append((param, value))", 'blank_slot_is_skipped'),
    ('brn_core.py', "            out[key] = value        # a space is a real delimiter", "            out[key] = value.strip()", 'delimiter_space_survives_settings'),
    ('brn_revit.py', "        if not row.has(core.FIELD_NUMBER):\n            continue\n        sheet = doc.GetElement(row.eid)\n        if sheet is None:", "        sheet = doc.GetElement(row.eid)\n        if sheet is None:", 'write_only_touches_sheets'),
    ('brn_revit.py', "error = _sub(doc, lambda r=row, p=pairs: write_sheet_row(doc, r, p))", "error = write_sheet_row(doc, row, pairs)", 'write_missing_parameter_reported'),
    ('brn_revit.py', "    if param.IsReadOnly or str(param.StorageType) != 'String':", "    if False:", 'write_read_only_reported'),
    ('brn_revit.py', "        if core.to_text(param.AsString()) != value:\n            raise ValueError(u'{0} did not take the value'.format(param_name))", "        pass", 'write_value_that_did_not_land'),
    ('brn_revit.py', "            if row.key in owners:\n                report.failed.append((row, u'Owned by {0}'.format(owners[row.key])))\n                continue\n", "", 'write_owned_sheet_named'),
    ('brn_revit.py', "        if _needs_write(sheet, pairs):\n            work.append((row, pairs))\n        else:\n            report.written += 1", "        work.append((row, pairs))", 'write_already_right_not_borrowed'),
    ('brn_revit.py', "        if rename:\n            report = apply_job", "        if False:\n            report = apply_job", 'write_uses_name_after_rename'),
    ('brn_revit.py', "if str(param.StorageType) == 'String' and not param.IsReadOnly:", "if True:", 'text_parameters_only_editable_text'),
    ('brn_core.py', "main + (side + gap if side else 0.0)", "main", 'list_width_takes_longest_line'),
    ('brn_core.py', "new_left = max(work_left, min(left, right_limit - new_width))", "new_left = left", 'widening_stays_on_screen'),
    ('brn_core.py', "new_width = min(width + extra, work_width)", "new_width = width + extra", 'widening_stays_on_screen'),
    ('brn_core.py', "    if extra <= 0:\n        return (left, width)\n", "", 'widening_stays_on_screen'),
    ('brn_core.py', "if not rules.case:", "if rules.case:", 'find_replace_case'),
    ('brn_core.py', "re.escape(rules.find)", "rules.find", 'find_is_literal'),
    ('brn_core.py', "[(rules.prefix, True)] + middle + [(rules.suffix, True)]", "[(rules.suffix, True)] + middle + [(rules.prefix, True)]", 'prefix_suffix_order'),
    ('brn_core.py', "if item.new in taken.get(item.scope, ()):", "if False:", 'clash_outside_batch'),
    ('brn_core.py', "elif len(landing[(item.scope, item.new)]) > 1:", "elif False:", 'two_landing_together_both_clash'),
    ('brn_core.py', "    moved = True\n    while moved:", "    moved = True\n    for _once in [1]:", 'clash_cascades'),
    ('brn_core.py', "if ch in new and ch not in old:", "if ch in new:", 'illegal_and_empty'),
    ('brn_core.py', "return (0, natural_key(row.values[FIELD_NUMBER]))", "return (2, natural_key(row.values[FIELD_NUMBER]))", 'natural_order_sheets_first'),
    ('brn_core.py', "line.split('=', 1)", "line.split('=')[:2]", 'value_split_on_first_equals'),
    ('brn_core.py', "if self.last == stamp:", "if False:", 'slow_clicks'),
    ('brn_core.py', "return 1.0 - (1.0 - progress) ** 3", "return progress", 'parking_maths'),
    ('brn_revit.py', "if element.IsTemplate:", "if False:", 'selection_keeps_browser_items_only'),
    ('brn_revit.py', "if isinstance(element, (RevitLinkType, CADLinkType)):", "if False:", 'selection_keeps_browser_items_only'),
    ('brn_revit.py', "if eid_value(view.Id) in batch:", "if False:", 'taken_excludes_batch'),
    ('brn_revit.py', "for item in core.needs_parking(work):", "for item in []:", 'swap_goes_through_park'),
    ('brn_revit.py', "for item in parked + [i for i in work if i not in parked]:", "for item in work:", 'refused_parked_goes_back'),
    ('brn_revit.py', "error = _sub(doc, lambda i=item: write_value(doc, i.row, i.field, i.new))", "error = write_value(doc, item.row, item.field, item.new)", 'one_refusal_keeps_the_rest'),
    ('brn_revit.py', "    items = core.evaluate(live, rules_by_field, read_taken(doc, live))", "    items = core.evaluate(live, rules_by_field, {})\n    items = [i for i in items if not doc.GetElement(i.row.eid) is None]", 'rechecks_at_write_time'),
    ('brn_revit.py', "if doc.GetElement(row.eid) is None:", "if False:", 'deleted_while_open'),
    ('brn_revit.py', "if actual == item.new:", "if True:", 'count_is_what_stayed'),
    ('brn_revit.py', "owners = borrow(doc, list(seen.values()))", "owners = {}", 'owned_is_reported_with_name'),
    ('brn_revit.py', "        self.jobs.remove(job)\n", "        self.jobs = []\n        job = None\n        self.jobs.append(1)\n", 'runner_queue'),
    ('brn_revit.py', "        if self.jobs:\n            return True\n", "", 'runner_queue'),
    ('brn_revit.py', "            try:\n                job()\n            except Exception as error:\n                self.log(u'job failed: {0}'.format(error))", "            job()", 'runner_survives_a_throwing_job'),
    ('brn_revit.py', "    return element_id.Value", "    return element_id.IntegerValue", 'eid_helper'),
    ('brn_drawer.py', "self.hidden.append((child, child.Visibility))", "self.hidden.append((child, self.collapsed[0]))", 'drawer_restores_what_was_hidden'),
    ('brn_drawer.py', "window.MinHeight = 0", "pass", 'drawer_parks_and_returns'),
    ('brn_drawer.py', "self.window.MinHeight = self.relaxed[0]", "pass", 'drawer_parks_and_returns'),
    ('brn_drawer.py', "self.grips.Visibility = self.collapsed[1]", "pass", 'drawer_parks_and_returns'),
    ('brn_drawer.py', "        except Exception:\n            finish()\n\n    # ----", "        except ZeroDivisionError:\n            finish()\n\n    # ----", 'drawer_no_timer_still_lands'),
    ('brn_drawer.py', "            except Exception:\n                finish()\n\n        try:", "            except ZeroDivisionError:\n                finish()\n\n        try:", 'drawer_throwing_frame_lands'),
    ('brn_drawer.py', "self.owner.shrink(False)", "pass", 'drawer_owner_goes_down_and_comes_back'),
    ('brn_drawer.py', "            self.owner.expand(False)\n\n    # ---------- the slide", "            pass\n\n    # ---------- the slide", 'drawer_owner_goes_down_and_comes_back'),
]


def run_all(folder, only=None):
    stubs, modules = load(folder)
    failed = []
    for fn in CHECKS:
        if only and fn.__name__ != only:
            continue
        try:
            fn(stubs, modules)
        except Exception as error:
            failed.append((fn.__name__, repr(error)))
    sys.path.remove(folder)
    for name in ('bench_stubs', 'brn_core', 'brn_drawer', 'brn_revit', 'brn_version'):
        sys.modules.pop(name, None)
    return failed


def selftest():
    missed = []
    for filename, old, new, name in BREAKAGES:
        folder = tempfile.mkdtemp()
        for item in os.listdir(HERE):
            if item.endswith('.py'):
                shutil.copy(os.path.join(HERE, item), folder)
        path = os.path.join(folder, filename)
        text = open(path).read()
        if old not in text:
            missed.append('target missing: ' + old)
            continue
        open(path, 'w').write(text.replace(old, new))
        try:
            failed = run_all(folder, name)
        except Exception as error:
            failed = [(name, repr(error))]
        if not failed:
            missed.append(name + ' missed: ' + old)
        shutil.rmtree(folder)
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), len(missed)))
    for line in missed:
        print('  ' + line)
    return not missed


def main():
    if '--selftest' in sys.argv:
        return 0 if selftest() else 1
    failed = run_all(HERE)
    print('{0} checks, {1} failed'.format(len(CHECKS), len(failed)))
    for name, why in failed:
        print('  {0}: {1}'.format(name, why))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
