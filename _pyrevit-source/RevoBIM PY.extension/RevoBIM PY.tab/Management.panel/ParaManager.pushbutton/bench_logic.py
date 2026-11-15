# -*- coding: utf-8 -*-
"""Logic checks under plain CPython. --selftest breaks the source and proves the checks notice."""
import codecs
import os
import shutil
import subprocess
import sys
import tempfile
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index('--root') + 1] if '--root' in sys.argv else HERE
sys.path.insert(0, HERE)
import bench_stubs
bench_stubs.install()
sys.path.insert(0, ROOT)
import pm_core as core
import pm_drawer
import pm_revit
import pm_spfile as sp
import pm_xlsx

G1 = u'41530d00-34c0-4d24-aceb-c9d67ac00001'
G2 = u'cee06500-c960-4fe9-8b52-578b7190c002'
SAMPLE = (u'# This is a Revit shared parameter file.\r\n# Do not edit manually.\r\n'
          u'*META\tVERSION\tMINVERSION\r\nMETA\t2\t1\r\n*GROUP\tID\tNAME\r\nGROUP\t7\tBGL_Acoustic\r\n'
          u'GROUP\t12\t*x_Electrical\r\n'
          u'*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE\r\n'
          u'PARAM\t' + G1 + u'\tBGL_Elec\tTEXT\t\t12\t1\t\t1\t0\r\n'
          u'PARAM\t' + G2 + u'\tBGL_Air\tHVAC_AIR_FLOW\t\t7\t1\tMax Air Flow\t1\t0\r\n')
OLD = (u'*GROUP\tID\tNAME\nGROUP\t1\tA\n*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\n'
       u'PARAM\t' + G1 + u'\tOne\tTEXT\t\t1\t1\n')


def utf16(text):
    return codecs.BOM_UTF16_LE + text.encode('utf-16-le')


def check_round_trip_exact():
    for data in (utf16(SAMPLE), SAMPLE.encode('utf-8'), codecs.BOM_UTF8 + SAMPLE.encode('utf-8'),
                 (SAMPLE.replace(u'Max', u'Caf\u00e9')).encode('cp1252'),
                 SAMPLE.replace(u'\r\n', u'\n').encode('utf-8'),
                 SAMPLE.rstrip().encode('utf-8'), OLD.encode('utf-8'),
                 SAMPLE.replace(u'\t\t1\t0\r\n', u'\r\n', 1).encode('utf-8'),
                 (SAMPLE + u'# trailing note\r\nJUNK\tkeep me\r\n').encode('utf-8')):
        assert sp.to_bytes(sp.parse_bytes(data)) == data


def check_only_edited_line_changes():
    f = sp.parse_bytes(utf16(SAMPLE))
    f.rows[1].desc = u'New text'
    out = sp.render(f).split(u'\r\n')
    was = SAMPLE.split(u'\r\n')
    assert [i for i in range(len(was)) if was[i] != out[i]] == [9]
    assert out[9].split(u'\t')[7] == u'New text'
    assert sp.to_bytes(f)[:2] == codecs.BOM_UTF16_LE


def check_unknown_column_kept():
    text = SAMPLE.replace(u'HIDEWHENNOVALUE\r\n', u'HIDEWHENNOVALUE\tFUTURE\r\n').replace(
        u'\t1\t0\r\nPARAM', u'\t1\t0\tx1\r\nPARAM')
    f = sp.parse_text(text)
    f.rows[0].name = u'Renamed'
    line = sp.render(f).split(u'\r\n')[8].split(u'\t')
    assert line[2] == u'Renamed' and line[-1] == u'x1'


def check_add_at_bottom_delete_and_group():
    f = sp.parse_text(SAMPLE)
    new = sp.add_row(f, u'Parameter 001', u'12')
    assert not new.tick and new.state() == 'new'
    f.rows[0].deleted = True
    g = f.add_group(u'New')
    assert g.gid == u'13'
    back = sp.parse_text(sp.render(f))
    assert [r.name for r in back.rows] == [u'BGL_Air', u'Parameter 001']
    assert [x.name for x in back.groups] == [u'BGL_Acoustic', u'*x_Electrical', u'New']


def check_group_rename_and_remove():
    f = sp.parse_text(SAMPLE)
    f.groups[0].name = u'Sound'
    assert f.is_dirty()
    back = sp.parse_text(sp.render(f))
    assert back.groups[0].name == u'Sound' and back.groups[0].gid == u'7'
    f = sp.parse_text(SAMPLE)
    gone = f.groups[0]
    f.rows[1].group_id = u'12'
    f.groups.remove(gone)
    assert f.is_dirty()
    assert u'GROUP\t7' not in sp.render(f)


def check_older_file_widens_only_when_needed():
    f = sp.parse_text(OLD)
    assert (f.rows[0].user, f.rows[0].hide) == (u'1', u'0')
    assert u'HIDEWHENNOVALUE' not in sp.render(f)
    f.rows[0].hide = u'1'
    back = sp.parse_text(sp.render(f))
    assert back.rows[0].hide == u'1' and u'HIDEWHENNOVALUE' in back.cols


def check_blank_file():
    f = sp.blank()
    f.add_group(u'General')
    sp.add_row(f, u'P', u'1')
    back = sp.parse_bytes(sp.to_bytes(f))
    assert len(back.rows) == 1 and back.rows[0].dtype == u'TEXT' and back.groups[0].name == u'General'


def check_clean_tabs():
    f = sp.parse_text(SAMPLE)
    f.rows[0].desc = u'a\tb\nc'
    assert sp.parse_text(sp.render(f)).rows[0].desc == u'a b c'


def check_duplicate_and_guid():
    f = sp.parse_text(SAMPLE)
    copy = sp.duplicate(f, f.rows[0])
    second = sp.duplicate(f, f.rows[0])
    assert copy.name == u'BGL_Elec Copy' and second.name == u'BGL_Elec Copy 2'
    assert copy.guid != f.rows[0].guid and copy.state() == 'new' and not copy.tick


def check_validate():
    f = sp.parse_text(SAMPLE)
    f.rows[0].guid = sp.new_guid()
    errors, warnings = sp.validate(f, core.name_problem)
    assert not errors and [w for w in warnings if u'new GUID' in w]
    f.rows[0].guid = G2
    assert [e for e in sp.validate(f, core.name_problem)[0] if u'same GUID' in e]
    f = sp.parse_text(SAMPLE)
    f.rows[0].name = u'bad:name'
    assert sp.validate(f, core.name_problem)[0]
    f = sp.parse_text(SAMPLE)
    f.rows[0].dtype = u'FAMILYTYPE'
    assert sp.validate(f, core.name_problem)[0]
    f = sp.parse_text(SAMPLE)
    f.rows[0].group_id = u'99'
    assert sp.validate(f, core.name_problem)[0]
    f = sp.parse_text(SAMPLE)
    f.rows[0].deleted = True
    assert [w for w in sp.validate(f, core.name_problem)[1] if u'removed' in w]


def check_type_labels():
    assert sp.type_label(u'HVAC_AIR_FLOW') == u'Air Flow'
    assert sp.type_token(sp.type_label(u'autodesk.spec.x')) == u'autodesk.spec.x'
    labels = [label for _token, label in sp.SP_TYPES]
    assert len(labels) == len(set(labels))


def rec(rid=1, name=u'A', cats=(u'Doors',), source=u'', scope=core.INSTANCE, group=u'Text'):
    return core.Rec(rid, name, core.KIND_SHARED, u'Common', u'Text', group, scope, cats, source=source)


def check_states_and_plan():
    r = rec()
    assert r.state() == 'ok'
    r.group = u'Other'
    assert r.state() == 'mod' and r.group_changed() and not r.needs_rebind()
    r.group = u'Text'
    assert r.state() == 'ok'
    r.cats = set([u'Walls'])
    assert r.needs_rebind()
    d = rec(2)
    d.deleted = True
    n = rec(3, source=u'typed')
    plan = core.build_plan([r, d, n])
    assert plan['modify'] == [r] and plan['delete'] == [d] and plan['create'] == [n]
    assert u'create 1 | modify 2 | existing 2' in core.status_line([r, d, n])


def check_validate_plan():
    assert [e for e in core.validate_plan([rec(source=u'typed', cats=())]) if u'category' in e]
    assert core.validate_plan([rec(1, u'A'), rec(2, u'a', source=u'typed')])
    assert core.validate_plan([rec(source=u'typed', name=u'x|y')])
    empty = rec()
    empty.cats = set()
    assert core.validate_plan([empty])
    assert not core.validate_plan([rec(source=u'typed')])


def check_mixed_categories_stay():
    every, some = core.shared_state([[u'A', u'B'], [u'A', u'C']])
    assert every == set([u'A']) and some == set([u'B', u'C'])
    assert core.apply_category_choice([u'A', u'B'], [u'A', u'D'], [u'C']) == set([u'A', u'B', u'D'])
    assert core.apply_category_choice([u'A', u'C'], [u'D'], [u'A']) == set([u'C', u'D'])


def check_category_groups_file():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'g.txt')
    core.save_category_groups(path, {u'Mech': [u'Ducts', u'Abutments | Abutment Piles']})
    assert core.load_category_groups(path) == {u'Mech': [u'Abutments | Abutment Piles', u'Ducts']}
    assert core.load_category_groups(path + 'x') == {}
    shutil.rmtree(folder)


def check_settings():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 's.txt')
    assert core.load_settings(path)['theme'] == 'follow'
    data = core.load_settings(path)
    data['last_sp_folder'] = u'C:\\a=b'
    core.save_settings(path, data)
    assert core.load_settings(path)['last_sp_folder'] == u'C:\\a=b'
    shutil.rmtree(folder)


def check_disciplines_match_revit_dialog():
    table = {u'Abutments | Abutment Piles': u'Infrastructure', u'Air Systems': u'Mechanical',
             u'Air Terminals': u'Mechanical', u'Alignments': u'General', u'Analytical Links': u'Structure',
             u'Analytical Members': u'General', u'Analytical Nodes': u'Structure',
             u'Cable Tray Fittings': u'Electrical', u'Pipe Fittings': u'Piping', u'Doors': u'Architecture'}
    for label in table:
        assert core.category_discipline(label) == table[label], label


def check_sort_filter():
    assert sorted([u'P-10', u'P-9', u'P-100'], key=core.natural_key) == [u'P-9', u'P-10', u'P-100']
    recs = [rec(1, u'B'), rec(2, u'Z', source=u'typed'), rec(3, u'A')]
    ranks = core.sort_ranks(recs, lambda r: r.name, True, lambda r: r.is_new)
    assert ranks == {0: 0, 2: 1, 1: 2}
    assert core.rec_visible(recs[0], core.KIND_ALL, u'b doors', True)
    assert not core.rec_visible(recs[0], core.KIND_PROJECT, u'', True)
    assert not core.rec_visible(recs[0], core.KIND_ALL, u'', False)
    assert core.rec_visible(recs[1], core.KIND_ALL, u'', False)


def check_rename_and_names():
    assert core.rename_preview(u'BGL_A', u'BGL', u'X', u'p_', u'_s') == u'p_X_A_s'
    assert core.next_free_name([u'parameter 001']) == u'Parameter 002'
    assert core.name_problem(u' ')


def check_import():
    recs = [rec(1, u'A')]
    head = list(core.EXPORT_HEADINGS)
    rows = [head, [u'A', u'', u'', u'', u'Other', u'Type', u'Doors; Walls; Nope'], [u'Missing'] + [u''] * 6]
    changes, notes = core.plan_import(rows, recs, [u'Other', u'Text'], [u'Doors', u'Walls'])
    assert changes[0][1:] == (u'Other', u'Type', set([u'Doors', u'Walls']))
    assert len(notes) == 2
    assert core.plan_import([[u'x']], recs, [], [])[1]
    odd = [head, [u'A', u'', u'', u'', u'Nope', u'Instance', u'Walls']]
    changes, notes = core.plan_import(odd, recs, [u'Text'], [u'Walls'])
    assert changes[0][1] == u'Text' and notes
    back = pm_xlsx.rows_from_parts(pm_xlsx.build_parts(core.export_rows(recs)))
    assert back[0] == head and back[1][0] == u'A'
    assert not core.plan_import(back, recs, [u'Text'], [u'Doors'])[0]


def check_xlsx_parts():
    parts = pm_xlsx.build_parts([[u'a&b', u'<c>'], [u'd']])
    for name in parts:
        minidom.parseString(parts[name].encode('utf-8'))
    sheet = parts['xl/worksheets/sheet1.xml']
    order = [sheet.index(t) for t in (u'<sheetViews', u'<cols', u'<sheetData', u'<autoFilter')]
    assert order == sorted(order)
    shared = {'xl/sharedStrings.xml': u'<sst><si><t>Name</t></si><si><t>x &amp; y</t></si></sst>',
              'xl/worksheets/sheet1.xml': u'<sheetData><row r="1"><c r="B1" t="s"><v>1</v></c></row></sheetData>'}
    assert pm_xlsx.rows_from_parts(shared) == [[u'', u'x & y']]
    assert pm_xlsx.column_name(27) == u'AB' and pm_xlsx.column_index(u'AB3') == 27


def check_window_maths():
    assert core.ease_out(1.5) == 1.0 and core.ease_out(0) == 0.0
    assert core.parked_top(-40.0, 44.0) == -92.0
    assert core.parked_top(1000.0, 44.0, 1) == 1000.0 - 8.0 - 48.0 - 44.0
    assert core.reopen_top(100.0, 900.0, 900.0, 600.0, 0.0, 1000.0) == 100.0
    assert core.reopen_top(100.0, 500.0, 900.0, 600.0, 0.0, 1000.0) == 0.0
    assert core.resolve_theme('follow', True) == 'dark' and core.resolve_theme('light', True) == 'light'
    assert core.next_theme('light') == 'follow'


class Thing(object):
    def __init__(self, **values):
        self.__dict__.update(values)

    def BeginAnimation(self, prop, value):
        pass


class FakeTimer(object):
    def __init__(self):
        self.handler = []
        self.stopped = False

    class Tick(object):
        pass

    def Start(self):
        pass

    def Stop(self):
        self.stopped = True


class TickList(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self


class Harness(object):
    def __init__(self, explode=False):
        cls = self
        cls.now = [0.0]

        class Win(object):
            Top = 100.0
            Height = 600.0
            ActualHeight = 600.0
            MinHeight = 420.0
            SizeToContent = 'height'

            def BeginAnimation(s, p, v):
                pass

            def __setattr__(s, key, value):
                if explode and key == 'Top' and value not in (100.0, 948.0):
                    raise RuntimeError('frame')
                object.__setattr__(s, key, value)
        self.win = Win()
        self.timer = FakeTimer()
        self.timer.Tick = TickList()
        self.root = Thing(ActualHeight=600.0, Height=None, VerticalAlignment=None)
        self.header = Thing(ActualHeight=42.0, Parent=Thing(Children=[]))
        self.button = Thing(Tag=None)
        self.grips = Thing(Visibility='v')
        del pm_drawer.PARKED[:]
        self.drawer = pm_drawer.Drawer(self.win, self.header, self.root, self.button, self.grips,
                                       lambda: (0.0, 0.0, 1920.0, 1000.0),
                                       make_timer=lambda: self.timer, clock=lambda: self.now[0])

    def run(self):
        for moment in (0.1, 0.2, 0.3):
            self.now[0] += 0.1
            if self.drawer.sliding:
                self.timer.Tick[-1](None, None)


def check_drawer_round_trip():
    h = Harness()
    h.drawer.toggle()
    h.run()
    assert h.win.Top == 1000.0 - 8.0 - 44.0 and h.win.Height == 44.0
    assert h.button.Tag == 'shrunk' and h.win.MinHeight == 0.0 and h.root.Height == 600.0
    assert not h.drawer.sliding
    h.drawer.toggle()
    h.run()
    assert h.win.Top == 100.0 and h.win.Height == 600.0 and h.win.MinHeight == 420.0
    assert h.button.Tag is None


def check_drawer_throwing_frame_lands():
    h = Harness(explode=True)
    h.drawer.shrink()
    h.now[0] += 0.1
    h.timer.Tick[-1](None, None)
    assert not h.drawer.sliding and h.button.Tag == 'shrunk'


class Fake(object):
    """A model for apply_plan: records order, can refuse."""

    def __init__(self):
        self.calls = []
        self.IsWorkshared = False
        self.ParameterBindings = self
        self.Application = Thing(SharedParametersFilename=u'C:\\live.txt',
                                 Create=Thing(NewCategorySet=lambda: Thing(Insert=lambda c: None),
                                              NewInstanceBinding=lambda s: 'instance',
                                              NewTypeBinding=lambda s: 'type'))
        self.Application.OpenSharedParameterFile = self.open_file
        self.fail_open = False

    def open_file(self):
        if self.fail_open:
            raise RuntimeError('no file')
        group = Thing(Definitions=Thing(Create=lambda o: 'extdef'))
        return Thing(Groups=Thing(get_Item=lambda n: group))

    def Delete(self, element):
        self.calls.append('delete')
        return []

    def Insert(self, defn, binding, group):
        self.calls.append(('insert', binding))
        return True

    def ReInsert(self, defn, binding, group):
        self.calls.append(('reinsert', binding))
        return self.reinsert_result

    reinsert_result = True


class Tx(object):
    def __init__(self, *args):
        pass

    def GetFailureHandlingOptions(self):
        return Thing(SetFailuresPreprocessor=lambda p: None, SetClearAfterRollback=lambda v: None)

    def SetFailureHandlingOptions(self, value):
        pass

    def Start(self):
        pass

    def Commit(self):
        return 'Committed'

    def RollBack(self):
        pass


def apply(fake, recs, after):
    pm_revit.Transaction = Tx
    pm_revit.SubTransaction = Tx
    pm_revit.Swallow = lambda: Thing(errors=[])
    pm_revit.read_project = lambda doc: {'recs': after}
    pm_revit.ExternalDefinitionCreationOptions = lambda a, b: None
    data = {'cats': {u'Doors': 1, u'Walls': 2}, 'groups': {u'Text': 1, u'Other': 2},
            'specs': {u'Common': {u'Text': 1}}}
    return pm_revit.apply_plan(fake, core.build_plan(recs), data)


def handled(rec_):
    rec_.handle = Thing(Id=1, SetGroupTypeId=lambda g: None)
    return rec_


def check_apply_order_and_routes():
    fake = Fake()
    gone = handled(rec(1, u'Gone'))
    gone.deleted = True
    new = rec(2, u'New', source=u'typed')
    group_only = handled(rec(3, u'G'))
    group_only.group = u'Other'
    rebind = handled(rec(4, u'R'))
    rebind.scope = core.TYPE
    now = [rec(2, u'New'), rec(3, u'G', group=u'Other'), rec(4, u'R', scope=core.TYPE)]
    result = apply(fake, [gone, new, group_only, rebind], now)
    assert result['failed'] == [] and result['landed'] == 4, result
    assert fake.calls == ['delete', ('insert', 'instance'), ('reinsert', 'type')]
    assert fake.Application.SharedParametersFilename == u'C:\\live.txt'


def check_shared_file_restored_on_failure():
    fake = Fake()
    fake.fail_open = True
    result = apply(fake, [rec(2, u'New', source=u'typed')], [])
    assert [f for f in result['failed'] if f[0] == u'New'] and result['landed'] == 0
    assert fake.Application.SharedParametersFilename == u'C:\\live.txt'


def check_refusal_and_read_back_are_reported():
    fake = Fake()
    fake.reinsert_result = False
    moved = handled(rec(4, u'R'))
    moved.scope = core.TYPE
    result = apply(fake, [moved], [rec(4, u'R')])
    assert result['landed'] == 0 and result['failed'] == [(u'R', u'Revit refused the change')]
    fake = Fake()
    moved = handled(rec(4, u'R'))
    moved.scope = core.TYPE
    result = apply(fake, [moved], [rec(4, u'R')])
    assert result['landed'] == 0 and u'reads back' in result['failed'][0][1]


def check_runner_keeps_pending():
    pm_revit.ExternalEventRequest = Thing(Accepted='a', Pending='p')
    pm_revit.DispatcherTimer = lambda: Thing(Start=lambda: None, Stop=lambda: None, Tick=TickList(), Interval=0)
    results = []
    pm_revit.ExternalEvent = Thing(Create=lambda h: Thing(Raise=lambda: answers.pop(0)))
    pm_revit.Action = lambda f: f
    answers = ['a', 'p', 'denied']
    runner = pm_revit.Runner(Thing(BeginInvoke=lambda f: f()), lambda: None)
    assert runner.submit(lambda u: 1, results.append)
    assert runner.submit(lambda u: 2, results.append)
    assert not runner.submit(lambda u: 3, results.append)
    assert len(runner.queue) == 2
    runner.run(None)
    assert results == [1, 2]
    answers.append('a')
    runner.submit(lambda u: 1 / 0, results.append)
    runner.run(None)
    assert u'ZeroDivisionError' in results[2]['failed'][0][1]


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith('check_')]

BREAKAGES = [
    ('pm_spfile.py', "out.append(item.text if row.state() == 'ok' and not widened\n                           else _row_line(cols, row))", "out.append(_row_line(cols, row))"),
    ('pm_spfile.py', "return bom + text.encode(encoding)", "return text.encode(encoding)"),
    ('pm_spfile.py', "sp.newline = u'\\r\\n' if u'\\r\\n' in text else u'\\n'", "sp.newline = u'\\r\\n'"),
    ('pm_spfile.py', "out.append(old[index] if index < len(old) else u'')", "out.append(u'')"),
    ('pm_spfile.py', "out[last_param:last_param] = new_rows", "out[8:8] = new_rows"),
    ('pm_spfile.py', "highest = max(highest, int(group.gid))", "highest = 1"),
    ('pm_spfile.py', "if [r for r in sp.live_rows() if getattr(r, attr) != default]:", "if True:"),
    ('pm_spfile.py', "return re.sub(u'[\\t\\r\\n]+', u' ', value if value is not None else u'')", "return value"),
    ('pm_spfile.py', "if guids[row.guid.lower()] > 1:", "if False:"),
    ('pm_spfile.py', "if row.group_id not in ids:", "if False:"),
    ('pm_spfile.py', "if row.dtype == u'FAMILYTYPE' and not row.dcat:", "if False:"),
    ('pm_spfile.py', "    if moved:\n        warnings.append", "    if False:\n        warnings.append"),
    ('pm_spfile.py', "copy = SpRow(new_guid(),", "copy = SpRow(row.guid,"),
    ('pm_core.py', "return (self.group, self.scope, self.cats) != self.orig", "return (self.group, self.scope) != self.orig[:2]"),
    ('pm_core.py', "return (set(current) - set(cleared)) | set(ticked)", "return set(ticked)"),
    ('pm_core.py', "        if not rec.cats:\n            errors.append", "        if False:\n            errors.append"),
    ('pm_core.py', "order.sort(key=lambda i: 1 if is_new(items[i]) else 0)", "pass"),
    ('pm_core.py', "    (u'Infrastructure', (u'abutment',", "    (u'Infrastructure', (u'zzz',"),
    ('pm_core.py', "return work_bottom - BAR_GAP - (bar_height + BAR_STACK) * slot - bar_height", "return abs(work_bottom) - BAR_GAP - bar_height"),
    ('pm_core.py', "    if abs(bar_top - parked_at) <= 2.0:\n        return saved_top\n", ""),
    ('pm_core.py', "if group not in known_groups:", "if False:"),
    ('pm_xlsx.py', ".replace(u'<', u'&lt;')", ""),
    ('pm_xlsx.py', "value = shared[int(raw)] if kind == u's' and raw else unescape(raw)", "value = raw"),
    ('pm_drawer.py', "        self.window.MinHeight = self.min_height\n", ""),
    ('pm_drawer.py', "            except Exception:\n                finish()\n\n        try:\n            self.timer", "            finally:\n                pass\n\n        try:\n            self.timer"),
    ('pm_revit.py', "    finally:\n        app.SharedParametersFilename = original or u''\n", "    finally:\n        pass\n"),
    ('pm_revit.py', "        if ok is False:\n            raise ValueError(u'Revit refused the change')\n", ""),
    ('pm_revit.py', "    for rec in plan['delete']:\n        _one(", "    for rec in []:\n        _one("),
    ('pm_revit.py', "        elif rec.name not in refused:\n            failed.append((rec.name, u'reads back", "        elif False:\n            failed.append((rec.name, u'reads back"),
    ('pm_revit.py', "(ExternalEventRequest.Accepted, ExternalEventRequest.Pending)", "(ExternalEventRequest.Accepted,)"),
    ('pm_revit.py', "        self.queue.remove(entry)\n        return False", "        return False"),
    ('pm_revit.py', "                result = {'landed': 0, 'failed': [(u'ParaManager', traceback.format_exc())]}", "                raise"),
]


def run():
    bad = 0
    for check in CHECKS:
        try:
            check()
            if '--quiet' not in sys.argv:
                print('ok   ' + check.__name__)
        except Exception as error:
            bad += 1
            print('FAIL {0}: {1!r}'.format(check.__name__, error))
    return bad


def selftest():
    missed = 0
    for name, old, new in BREAKAGES:
        folder = tempfile.mkdtemp()
        root = os.path.join(folder, 'x')
        shutil.copytree(HERE, root, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(root, name)
        with open(path, encoding='utf-8', newline='') as src:
            text = src.read()
        if old not in text:
            print('ANCHOR MISSING ' + old[:50])
            missed += 1
            continue
        with open(path, 'w', encoding='utf-8', newline='') as out:
            out.write(text.replace(old, new, 1))
        code = subprocess.call([sys.executable, os.path.join(HERE, 'bench_logic.py'), '--root', root, '--quiet'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if code == 0:
            print('NOT CAUGHT ' + old[:60])
            missed += 1
        shutil.rmtree(folder)
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), missed))
    return missed


if __name__ == '__main__':
    sys.exit(1 if (selftest() if '--selftest' in sys.argv else run()) else 0)
