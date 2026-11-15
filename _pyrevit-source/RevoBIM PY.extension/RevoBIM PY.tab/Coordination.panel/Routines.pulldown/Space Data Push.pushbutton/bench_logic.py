# -*- coding: utf-8 -*-
"""Bench test of Space Data Push's rules, under plain CPython 3.

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break each rule on purpose and confirm the
                                      checks notice (a check nobody has seen fail
                                      is a check that may not work)

The rules are the real code: the Revit API is stubbed (bench_stub.py) and the
model layer is driven with fake elements, parameters, documents and transactions.
"""
import os
import sys
import tempfile
import shutil
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stub as S

S.install()
S.purge()

import sdp_logic as L
import sdp_model as M
import sdp_runner as R
import sdp_ui as UI
import sdp_window as W
from sdp_logic import Snap

RESULTS = []


def check(name, condition, detail=u''):
    RESULTS.append((name, bool(condition), detail))


def failures():
    return [r for r in RESULTS if not r[1]]


# ================================================================== fake Revit

class FId(object):
    def __init__(self, value):
        self.Value = value


class FDefType(object):
    def __init__(self, type_id):
        self.TypeId = type_id


class FDef(object):
    def __init__(self, name, spec):
        self.Name = name
        self._spec = spec

    def GetDataType(self):
        return FDefType(self._spec)


class FParam(object):
    """A parameter. takes=False is the nasty one: Set returns True and nothing
    changes, which is what Revit does when a write does not take."""

    def __init__(self, name, storage, value=None, spec=u'', read_only=False,
                 takes=True, refuses=False, text=None):
        self.Definition = FDef(name, spec)
        self.StorageType = storage
        self.value = value
        self.IsReadOnly = read_only
        self.takes = takes
        self.refuses = refuses
        self.text = text
        self.sets = 0

    @property
    def HasValue(self):
        return self.value is not None

    def AsString(self):
        return self.value if self.StorageType == 'String' else None

    def AsDouble(self):
        return self.value

    def AsInteger(self):
        return self.value

    def AsElementId(self):
        return self.value

    def AsValueString(self):
        if self.text is not None:
            return self.text
        return u'%s' % (self.value,) if self.value is not None else u''

    def Set(self, v):
        self.sets += 1
        if self.refuses:
            return False
        if self.takes:
            self.value = v
        return True

    def SetValueString(self, text):
        self.sets += 1
        if self.refuses:
            return False
        if self.takes:
            self.value = 1.0
            self.text = text
        return True


class FCat(object):
    def __init__(self, name, value, parent=None, ctype='Model', bound=True):
        self.Name = name
        self.Id = FId(value)
        self.Parent = parent
        self.CategoryType = ctype
        self.AllowsBoundParameters = bound


class FEl(object):
    def __init__(self, eid, params, cat=None, type_id=1, name=u'', workset=None):
        self.Id = FId(eid)
        self.Parameters = list(params)
        self.Category = cat
        self._type_id = type_id
        self.Name = name
        self.WorksetId = workset
        self.Level = None
        self.rooms = {}

    def GetTypeId(self):
        return FId(self._type_id)

    def GetParameters(self, name):
        return [p for p in self.Parameters if p.Definition.Name == name]

    def LookupParameter(self, name):
        found = self.GetParameters(name)
        return found[0] if found else None

    def get_Parameter(self, key):
        return self.rooms.get(key)


class FSettings(object):
    def __init__(self, cats):
        self.Categories = cats


class FDoc(object):
    def __init__(self, title=u'Job', elements=None, cats=None, workshared=False):
        self.Title = title
        self.elements = elements or {}
        self.Settings = FSettings(cats or [])
        self.IsWorkshared = workshared
        self.ParameterBindings = FBindings([])

    def GetElement(self, eid):
        return self.elements.get(eid.Value if hasattr(eid, 'Value') else eid)


class FBindings(object):
    def __init__(self, items):
        self.items = items

    def ForwardIterator(self):
        return FIter(self.items)


class FIter(object):
    def __init__(self, items):
        self.items = items
        self.i = -1

    def MoveNext(self):
        self.i += 1
        return self.i < len(self.items)

    @property
    def Current(self):
        return self.items[self.i][1]

    @property
    def Key(self):
        return self.items[self.i][0]


class FType(object):
    def __init__(self, name):
        self.Name = name


class FBinding(object):
    def __init__(self, kind, cats):
        self._kind = kind
        self.Categories = cats

    def GetType(self):
        return FType(self._kind)


class FKey(object):
    def __init__(self, name):
        self.Name = name


class FTransaction(object):
    log = []
    commit_status = 'Committed'
    raise_on_start = False

    def __init__(self, doc, name):
        self.doc = doc

    def Start(self):
        if FTransaction.raise_on_start:
            raise RuntimeError('cannot start')
        FTransaction.log.append('start')

    def Commit(self):
        FTransaction.log.append('commit')
        return FTransaction.commit_status

    def RollBack(self):
        FTransaction.log.append('rollback')

    def GetFailureHandlingOptions(self):
        return FOptions()

    def SetFailureHandlingOptions(self, options):
        FTransaction.log.append('options')


class FOptions(object):
    def SetFailuresPreprocessor(self, p):
        FTransaction.log.append('preprocessor')


def reset_tx(status='Committed', raise_start=False):
    FTransaction.log = []
    FTransaction.commit_status = status
    FTransaction.raise_on_start = raise_start


@contextlib.contextmanager
def patched(pairs):
    """pairs: [(object, attribute, replacement)] - restored on exit."""
    saved = []
    for obj, attr, new in pairs:
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, new)
    try:
        yield
    finally:
        for obj, attr, old in reversed(saved):
            setattr(obj, attr, old)


def hold_of(**values):
    """A SpaceHold built directly from (name -> Snap) keyword pairs."""
    return M.SpaceHold(u'Job', FId(900), values, u'101 - Plant Room')


def snap_s(name, text):
    return Snap(name, u'String', bool(text), text, text, u'')


def snap_d(name, raw, text, spec=u'autodesk.spec.aec:area-2.0.0'):
    return Snap(name, u'Double', True, text, raw, spec)


def snap_i(name, raw, text=None):
    return Snap(name, u'Integer', True, text if text is not None else u'%s' % raw, raw, u'')


def run(fn):
    """Run a check group; an exception counts as a failure of that group."""
    try:
        fn()
    except Exception as ex:
        import traceback
        check(fn.__name__ + u' raised', False, traceback.format_exc())


# ===================================================================== checks

def t_keyword_filter():
    names = [u'Area', u'Room Name', u'Room Number', u'Comments']
    got, ok = L.keyword_filter(names, u'room')
    check(u'filter: one word', got == [u'Room Name', u'Room Number'] and ok)
    got, ok = L.keyword_filter(names, u'ROOM num')
    check(u'filter: every word must match, any case', got == [u'Room Number'] and ok)
    got, ok = L.keyword_filter(names, u'zzz')
    check(u'filter: a miss keeps the full list', got == names and not ok)
    got, ok = L.keyword_filter(names, u'')
    check(u'filter: empty query is everything', got == names and ok)
    got, ok = L.keyword_filter(names, None)
    check(u'filter: None query is everything', got == names and ok)


def t_rows_and_settings():
    pairs = [(u'Area', u'Comments'), (u'a|b', u'c>>d'), (u'100%', u'x\ny'), (u'Caf\u00e9', u'')]
    check(u'rows: round trip with | > % newline and unicode',
          L.decode_rows(L.encode_rows(pairs)) == pairs)
    check(u'rows: empty text decodes to nothing', L.decode_rows(u'') == [])
    check(u'rows: a chunk with no separator keeps its left side',
          L.decode_rows(u'Area') == [(u'Area', u'')])
    check(u'rows: blank left side is dropped', L.decode_rows(u'>>Comments|Area>>Mark') == [(u'Area', u'Mark')])
    check(u'esc: pipe and percent are escaped', u'|' not in L.esc(u'a|b') and L.esc(u'%') == u'%25')
    check(u'dupes: case-insensitive, blank ignored, reported once',
          L.find_duplicate_targets([(u'a', u'Mark'), (u'b', u'MARK'), (u'c', u''), (u'd', u''), (u'e', u'mark')]) == [u'MARK'])
    check(u'dupes: none', L.find_duplicate_targets([(u'a', u'x'), (u'b', u'y')]) == [])

    parsed = L.parse_settings(u'# c\ntheme=dark\nrows=a>>b=c\nbroken\n')
    check(u'settings: split on the first = only', parsed.get('rows') == u'a>>b=c')
    clean = L.clean_settings({'theme': 'purple', 'overwrite': 'banana', 'category': 'abc',
                              'unknown_old_key': '1', 'keep_picking': 'true'})
    check(u'settings: bad theme falls back', clean['theme'] == 'follow')
    check(u'settings: bad bool is off, true is on', clean['overwrite'] == '0' and clean['keep_picking'] == '1')
    check(u'settings: non-numeric category cleared', clean['category'] == '')
    check(u'settings: unknown key ignored', 'unknown_old_key' not in clean)
    check(u'settings: negative category id kept', L.clean_settings({'category': '-2000'})['category'] == '-2000')
    check(u'settings: defaults all present', all(k in clean for k in L.DEFAULTS))

    tmp = tempfile.mkdtemp()
    try:
        with patched([(L, 'appdata_dir', lambda: tmp)]):
            check(u'settings: missing file gives defaults', L.load_settings() == L.clean_settings({}))
            want = L.clean_settings({'theme': 'light', 'category': '-2000', 'rows': L.encode_rows(pairs),
                                     'rows_saved': '1', 'overwrite': '0'})
            check(u'settings: save reports success', L.save_settings(want))
            check(u'settings: file round trip', L.load_settings() == want)
            with open(L.settings_path(), 'w') as fh:
                fh.write(u'theme=dark\nrows_saved=1\nrows=Area>>Mark\ngarbage line\nold_key=zzz\n')
            got = L.load_settings()
            check(u'settings: damaged file loads key by key', got['theme'] == 'dark' and got['rows'] == u'Area>>Mark')
            L.set_debug(True)
            L.log_debug(u'hello')
            check(u'debug: log written', os.path.exists(os.path.join(tmp, L.DEBUG_FILE)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_plan_value():
    P = L.plan_value
    a, v, _n = P(snap_s(u'Name', u'Plant'), u'String', u'', True)
    check(u'plan: text into text', (a, v) == (u'string', u'Plant'))
    a, v, _n = P(snap_d(u'Area', 12.5, u'12.5 m2'), u'String', u'', True)
    check(u'plan: a number shows as its displayed text in a text parameter', (a, v) == (u'string', u'12.5 m2'))
    a, _v, n = P(snap_s(u'Comments', u''), u'String', u'', True)
    check(u'plan: blank is skipped when asked', a == u'skip' and u'blank' in n)
    a, v, _n = P(snap_s(u'Comments', u''), u'String', u'', False)
    check(u'plan: blank clears a text parameter when not skipping', (a, v) == (u'string', u''))
    a, _v, _n = P(snap_s(u'Comments', u''), u'Double', u'', False)
    check(u'plan: blank never goes into a number parameter', a == u'skip')
    a, v, _n = P(snap_i(u'Count', 4), u'Integer', u'', True)
    check(u'plan: int into int', (a, v) == (u'int', 4))
    a, v, _n = P(snap_s(u'Count', u'7'), u'Integer', u'', True)
    check(u'plan: whole-number text into int', (a, v) == (u'int', 7))
    a, _v, _n = P(snap_s(u'Count', u'7.5'), u'Integer', u'', True)
    check(u'plan: fractional text does not fit an int', a == u'skip')
    a, v, _n = P(snap_d(u'Area', 3.0, u'3'), u'Double', u'autodesk.spec.aec:area-1.0.0', True)
    check(u'plan: same unit family copies the raw value (version suffix ignored)', (a, v) == (u'double', 3.0))
    a, _v, n = P(snap_d(u'Area', 3.0, u'3'), u'Double', u'autodesk.spec.aec:length-2.0.0', True)
    check(u'plan: different unit family is skipped and says so', a == u'skip' and u'units differ' in n)
    a, v, _n = P(snap_s(u'Length', u'2500'), u'Double', u'autodesk.spec.aec:length-2.0.0', True)
    check(u'plan: text into a number goes through SetValueString', (a, v) == (u'valuestring', u'2500'))
    a, _v, _n = P(snap_s(u'x', u'1'), u'ElementId', u'', True)
    check(u'plan: element-id targets are refused', a == u'skip')
    a, _v, _n = P(snap_s(u'x', u'1'), u'None', u'', True)
    check(u'plan: no storage type is refused', a == u'skip')
    src = Snap(u'Level', u'ElementId', True, u'Level 1', object(), u'')
    a, _v, _n = P(src, u'Double', u'', True)
    check(u'plan: a reference cannot go into a number', a == u'skip')
    check(u'spec_key: strips the version', L.spec_key(u'autodesk.spec.aec:area-2.0.0') == u'autodesk.spec.aec:area')
    check(u'spec_key: unversioned unchanged', L.spec_key(u'Area') == u'area')
    check(u'short_spec', L.short_spec(u'autodesk.spec.aec:area') == u'area')
    check(u'parse_number: comma decimal and junk', L.parse_number(u'1,5') == 1.5 and L.parse_number(u'1 m') is None)


def t_verify_and_results():
    V = L.verify_write
    check(u'verify: string equal', V(u'string', u'a', u'a'))
    check(u'verify: string differs', not V(u'string', u'a', u'b'))
    check(u'verify: None reads as blank string', V(u'string', u'', None))
    check(u'verify: int', V(u'int', 3, 3) and not V(u'int', 3, 4) and not V(u'int', 3, None))
    check(u'verify: double within tolerance', V(u'double', 1000.0, 1000.0000001) and not V(u'double', 1.0, 1.1))
    check(u'verify: double None fails', not V(u'double', 1.0, None))
    check(u'verify: valuestring wants a value', V(u'valuestring', u'5', True) and not V(u'valuestring', u'5', False))
    check(u'blank target: string empty', L.target_is_blank(u'String', True, u'') and not L.target_is_blank(u'String', True, u'x'))
    check(u'blank target: no value', L.target_is_blank(u'Double', False, u''))
    rs = [L.RowResult(u'a', u'b', u'ok'), L.RowResult(u'c', u'd', u'skip', u'why'), L.RowResult(u'e', u'f', u'fail')]
    c = L.result_counts(rs)
    check(u'results: counts', c == {u'ok': 1, u'same': 0, u'skip': 1, u'fail': 1})
    check(u'results: level fail beats skip beats ok',
          L.result_level(c) == u'fail' and L.result_level({u'skip': 1}) == u'warn' and L.result_level({u'ok': 2}) == u'ok')
    check(u'results: summary words', L.result_summary(c) == u'1 written, 1 skipped, 1 failed')
    check(u'results: empty summary', L.result_summary(L.result_counts([])) == u'nothing to write')
    check(u'results: line', L.result_line(rs[1]) == u'c  ->  d    why')
    check(u'preview: no space', L.preview_text(None, False) == (u'-', u'none'))
    check(u'preview: missing parameter', L.preview_text(None, True)[1] == u'blank')
    check(u'preview: blank value', L.preview_text(snap_s(u'x', u''), True) == (u'(blank)', u'blank'))
    check(u'preview: value', L.preview_text(snap_s(u'x', u'A'), True) == (u'A', u'value'))
    check(u'caption: number and name and level', L.space_caption(u'101', u'Plant', u'L1') == u'101 - Plant  (L1)')
    check(u'caption: unnamed', L.space_caption(u'', u'', u'') == u'(unnamed space)')
    check(u'caption: name only', L.space_caption(None, u'Plant', None) == u'Plant')


def t_theme_and_misc():
    check(u'theme: cycle', [L.next_theme_mode(m) for m in L.THEME_MODES] == [u'dark', u'light', u'follow'])
    check(u'theme: unknown mode restarts the cycle', L.next_theme_mode(u'x') == u'follow')
    check(u'theme: follow takes Revit light', L.resolve_theme(u'follow', u'light') == u'light')
    check(u'theme: follow takes Revit dark', L.resolve_theme(u'follow', u'dark') == u'dark')
    check(u'theme: follow with unreadable Revit theme is dark', L.resolve_theme(u'follow', None) == u'dark')
    check(u'theme: an explicit choice beats Revit', L.resolve_theme(u'dark', u'light') == u'dark'
          and L.resolve_theme(u'light', u'dark') == u'light')
    check(u'alive: stale note of this version', L.note_is_stale(L.alive_note(u'1.0.0', 5), u'1.0.0'))
    check(u'alive: note of another version proves nothing', not L.note_is_stale(L.alive_note(u'0.9', 5), u'1.0.0'))
    check(u'alive: empty and junk notes', not L.note_is_stale(u'', u'1.0.0') and not L.note_is_stale(u'junk', u'1.0.0'))
    check(u'merge_names: adds new, no case duplicates, sorted',
          L.merge_names([u'b', u'A'], [u'a', u'C', u'']) == [u'A', u'b', u'C'])


def t_queue_and_runner():
    q = L.JobQueue()
    a, b, c = (lambda: 1), (lambda: 2), (lambda: 3)
    q.push(a)
    q.push(b)
    q.push(c)
    q.discard(b)
    check(u'queue: discard removes only that job', len(q) == 2)
    got = q.drain()
    check(u'queue: drain returns jobs in order and empties', got == [a, c] and len(q) == 0)
    q.discard(b)
    check(u'queue: discarding an unknown job is harmless', len(q) == 0)

    class FEvent(object):
        answer = 'Accepted'

        def Raise(self):
            if FEvent.answer == 'boom':
                raise RuntimeError('no')
            return FEvent.answer

    class FExternalEvent(object):
        @staticmethod
        def Create(handler):
            return FEvent()

    with patched([(R, 'ExternalEvent', FExternalEvent)]):
        runner = R.Runner()
        j1 = lambda uiapp: None
        FEvent.answer = 'Accepted'
        check(u'runner: Accepted queues the job', runner.submit(j1) and len(runner.queue) == 1)
        j2 = lambda uiapp: None
        FEvent.answer = 'Pending'
        check(u'runner: Pending keeps the job queued behind the earlier one',
              runner.submit(j2) and len(runner.queue) == 2)
        j3 = lambda uiapp: None
        FEvent.answer = 'TimedOut'
        check(u'runner: a refusal removes only the refused job',
              (not runner.submit(j3)) and len(runner.queue) == 2)
        FEvent.answer = 'boom'
        j4 = lambda uiapp: None
        check(u'runner: Raise raising is a refusal too', (not runner.submit(j4)) and len(runner.queue) == 2)

        ran = []
        runner.queue.drain()
        runner.queue.push(lambda uiapp: ran.append(1))
        runner.queue.push(lambda uiapp: (_ for _ in ()).throw(RuntimeError('bad job')))
        runner.queue.push(lambda uiapp: ran.append(3))

        class FEv(object):
            def __iadd__(self, other):
                return self

        class FUi(object):
            DialogBoxShowing = FEv()

        with patched([(L, 'log_debug', lambda t: None)]):
            runner.Execute(FUi())
        check(u'runner: a job that raises does not stop the ones after it', ran == [1, 3])
        check(u'runner: name', runner.GetName() == u'RevoBIM Space Data Push')

        class FArgs(object):
            DialogId = u'Dialog_X'
            result = None

            def OverrideResult(self, n):
                FArgs.result = n

        runner.suppress = False
        runner._on_dialog(None, FArgs())
        check(u'runner: dialogs are left alone when not suppressing', FArgs.result is None)
        runner.suppress = True
        runner._on_dialog(None, FArgs())
        check(u'runner: dialogs are answered while suppressing, and logged',
              FArgs.result == 1 and runner.dialogs == [u'Dialog_X'])


# ------------------------------------------------------------------ model layer

def cat_detail():
    return FCat(u'Detail Items', M.detail_items_value(), ctype='Annotation')


def t_model_reading():
    cats = [FCat(u'Walls', -2000011), cat_detail(), FCat(u'Sub', -5, parent=object()),
            FCat(u'Views', -3, ctype='Internal'), FCat(u'Unboundable', -4, bound=False),
            FCat(u'Air Terminals', -2008013)]
    doc = FDoc(cats=cats)
    got = M.read_categories(doc)
    check(u'categories: only top-level model/annotation categories that take parameters, sorted',
          [c.name for c in got] == [u'Air Terminals', u'Detail Items', u'Walls'])
    check(u'categories: value is the id value', [c.value for c in got if c.name == u'Walls'] == [-2000011])
    check(u'default category: saved wins', W.pick_default_category(got, str(-2000011)).name == u'Walls')
    check(u'default category: none saved gives Detail Items', W.pick_default_category(got, u'').name == u'Detail Items')
    check(u'default category: a stale saved id falls back to Detail Items',
          W.pick_default_category(got, u'-99999').name == u'Detail Items')
    check(u'default category: no Detail Items gives the first',
          W.pick_default_category([c for c in got if c.name != u'Detail Items'], u'').name == u'Air Terminals')
    check(u'default category: nothing at all', W.pick_default_category([], u'') is None)

    class FCollector(object):
        items = []

        def __init__(self, doc):
            pass

        def OfCategory(self, c):
            return self

        def OfCategoryId(self, i):
            return self

        def WhereElementIsNotElementType(self):
            return iter(FCollector.items)

    space_a = FEl(1, [FParam(u'Number', 'String', u'1'), FParam(u'Area', 'Double', 2.0),
                      FParam(u'Ghost', 'None')])
    space_b = FEl(2, [FParam(u'area', 'Double', 3.0), FParam(u'BGL_Zone', 'String', u'x')])
    with patched([(M, 'FilteredElementCollector', FCollector)]):
        FCollector.items = [space_a, space_b]
        names = M.read_space_params(doc)
        check(u'space params: union, case-insensitive dedupe, no storage-less ones, sorted',
              names == [u'Area', u'BGL_Zone', u'Number'])
        FCollector.items = []
        check(u'space params: none in the project gives the fallback list',
              names != M.read_space_params(doc) and u'Number' in M.read_space_params(doc))

        rec = M.CatRec(u'Detail Items', FId(M.detail_items_value()), M.detail_items_value())
        e1 = FEl(10, [FParam(u'Comments', 'String', u''), FParam(u'Mark', 'String', u'', read_only=True),
                      FParam(u'Host', 'ElementId'), FParam(u'Width', 'Double', 1.0)], type_id=1)
        e1b = FEl(11, [FParam(u'OnlyOnSecondOfSameType', 'String')], type_id=1)
        e2 = FEl(12, [FParam(u'Comments', 'String', u''), FParam(u'BGL_Tag', 'String', u'')], type_id=2)
        FCollector.items = [e1, e1b, e2]
        doc2 = FDoc()
        doc2.ParameterBindings = FBindings([
            (FKey(u'BGL_Bound'), FBinding('InstanceBinding', [FCat(u'Detail Items', M.detail_items_value())])),
            (FKey(u'BGL_TypeOnly'), FBinding('TypeBinding', [FCat(u'Detail Items', M.detail_items_value())])),
            (FKey(u'BGL_Other'), FBinding('InstanceBinding', [FCat(u'Walls', -2000011)])),
        ])
        got = M.read_category_params(doc2, rec)
        check(u'category params: writable non-reference params of one element per type, plus instance bindings',
              got == [u'BGL_Bound', u'BGL_Tag', u'Comments', u'Width'], got)
        FCollector.items = []
        doc3 = FDoc()
        check(u'category params: nothing found gives the fallback',
              M.read_category_params(doc3, rec) == list(M.FALLBACK_TARGET_PARAMS))


def t_model_helpers():
    a = FParam(u'Mark', 'String', u'', read_only=True)
    b = FParam(u'Mark', 'String', u'')
    el = FEl(5, [a, b])
    check(u'find_param: prefers the writable one of two same-named', M.find_param(el, u'Mark') is b)
    only_ro = FEl(6, [a])
    check(u'find_param: read-only is still returned when it is all there is', M.find_param(only_ro, u'Mark') is a)
    check(u'find_param: missing is None', M.find_param(el, u'Nope') is None)
    check(u'eid_value: Value attribute', M.eid_value(FId(7)) == 7 and M.eid_value(None) == 0)

    class OldId(object):
        IntegerValue = 9

    check(u'eid_value: falls back to IntegerValue', M.eid_value(OldId()) == 9)

    space_cat = FCat(u'Spaces', M.space_category_value())
    sp = FEl(20, [], cat=space_cat)

    class FSel(object):
        def __init__(self, ids):
            self.ids = ids
            self.cancel = False
            self.ref = None

        def GetElementIds(self):
            return self.ids

        def PickObject(self, *args):
            if self.cancel:
                raise S.OperationCanceledException()
            return self.ref

    class FUiDoc(object):
        def __init__(self, doc, sel):
            self.Document = doc
            self.Selection = sel

    doc = FDoc(elements={20: sp})
    check(u'selected_space: exactly one space selected', M.selected_space(FUiDoc(doc, FSel([FId(20)]))) is sp)
    check(u'selected_space: nothing selected', M.selected_space(FUiDoc(doc, FSel([]))) is None)
    check(u'selected_space: two selected', M.selected_space(FUiDoc(doc, FSel([FId(20), FId(21)]))) is None)
    wall = FEl(30, [], cat=FCat(u'Walls', -2000011))
    doc.elements[30] = wall
    check(u'selected_space: a wall is not a space', M.selected_space(FUiDoc(doc, FSel([FId(30)]))) is None)

    sel = FSel([])
    sel.cancel = True
    check(u'pick_one: Esc gives None', M.pick_one(FUiDoc(doc, sel), None, u'p') is None)

    class FRef(object):
        ElementId = FId(30)

    sel = FSel([])
    sel.ref = FRef()
    check(u'pick_one: a click gives the element', M.pick_one(FUiDoc(doc, sel), None, u'p') is wall)
    sel.ref = None
    check(u'pick_one: no reference gives None', M.pick_one(FUiDoc(doc, sel), None, u'p') is None)

    flt = M.CategoryFilter(M.space_category_value())
    check(u'filter: allows the category', flt.AllowElement(sp))
    check(u'filter: refuses another category', not flt.AllowElement(wall))
    check(u'filter: refuses no category', not flt.AllowElement(FEl(31, [])))
    check(u'filter: never allows a reference', not flt.AllowReference(None, None))

    class FSev(object):
        def __init__(self, sev):
            self.sev = sev

        def GetSeverity(self):
            return self.sev

    class FAccessor(object):
        def __init__(self, msgs):
            self.msgs = msgs
            self.deleted = []

        def GetFailureMessages(self):
            return self.msgs

        def DeleteWarning(self, m):
            self.deleted.append(m)

    warn, err = FSev(M.FailureSeverity.Warning), FSev(M.FailureSeverity.Error)
    acc = FAccessor([warn, err])
    result = M.WarningSwallower().PreprocessFailures(acc)
    check(u'swallower: deletes warnings only', acc.deleted == [warn])
    check(u'swallower: lets the transaction continue', result == M.FailureProcessingResult.Continue)

    label = M.element_label(FEl(40, [], cat=FCat(u'Detail Items', -1), name=u'Tag'))
    check(u'element_label: category, name, id', label == (u'Detail Items', u'Tag', 40), label)


def sample_element(eid=100, **kw):
    return FEl(eid, [
        FParam(u'Comments', 'String', u''),
        FParam(u'Mark', 'String', u'old'),
        FParam(u'RoomArea', 'Double', 0.0, spec=u'autodesk.spec.aec:area-2.0.0'),
        FParam(u'Count', 'Integer', 0),
        FParam(u'Length', 'Double', 0.0, spec=u'autodesk.spec.aec:length-2.0.0'),
        FParam(u'Locked', 'String', u'', read_only=True),
        FParam(u'Silent', 'String', u'', takes=False),
        FParam(u'Refuses', 'String', u'', refuses=True),
        FParam(u'Ref', 'ElementId', None),
    ], cat=FCat(u'Detail Items', M.detail_items_value()), **kw)


def push(hold, maps, el=None, overwrite=True, skip_blank=True, doc=None):
    el = el or sample_element()
    doc = doc or FDoc(elements={el.Id.Value: el})
    with patched([(M, 'Transaction', FTransaction)]):
        results = M.push_to_element(doc, hold, el, maps, overwrite, skip_blank)
    return results, el


def status_of(results, dst):
    for r in results:
        if r.dst == dst:
            return r.status, r.detail
    return None, None


def t_push():
    hold = hold_of(Number=snap_s(u'Number', u'101'), Name=snap_s(u'Name', u'Plant Room'),
                   Area=snap_d(u'Area', 12.5, u'12.5 m2'), Count=snap_i(u'Count', 4),
                   Blank=snap_s(u'Blank', u''), Len=snap_d(u'Len', 3.0, u'3000', u'autodesk.spec.aec:length-2.0.0'))

    reset_tx()
    res, el = push(hold, [(u'Number', u'Comments'), (u'Name', u'Mark')])
    check(u'push: two text rows written', status_of(res, u'Comments')[0] == u'ok' and status_of(res, u'Mark')[0] == u'ok')
    check(u'push: the values really landed', el.LookupParameter(u'Comments').value == u'101'
          and el.LookupParameter(u'Mark').value == u'Plant Room')
    check(u'push: one transaction with the warning preprocessor',
          FTransaction.log == ['start', 'preprocessor', 'options', 'commit'], FTransaction.log)

    reset_tx()
    res, el = push(hold, [(u'Area', u'RoomArea'), (u'Len', u'Length')])
    check(u'push: double into same-unit double', status_of(res, u'RoomArea')[0] == u'ok'
          and el.LookupParameter(u'RoomArea').value == 12.5)
    check(u'push: unit mismatch is skipped, not written', status_of(res, u'Length')[0] == u'ok')
    res, el = push(hold, [(u'Area', u'Length')])
    check(u'push: area into a length parameter is skipped with the reason',
          status_of(res, u'Length')[0] == u'skip' and u'units differ' in status_of(res, u'Length')[1]
          and el.LookupParameter(u'Length').value == 0.0)

    res, el = push(hold, [(u'Count', u'Count')])
    check(u'push: int into int', status_of(res, u'Count')[0] == u'ok' and el.LookupParameter(u'Count').value == 4)

    reset_tx()
    res, el = push(hold, [(u'Number', u'Silent')])
    check(u'push: a write that did not stick is a FAILURE, not a success',
          status_of(res, u'Silent')[0] == u'fail' and u'did not stick' in status_of(res, u'Silent')[1])
    res, el = push(hold, [(u'Number', u'Refuses')])
    check(u'push: Revit refusing the value is a failure', status_of(res, u'Refuses')[0] == u'fail'
          and u'refused' in status_of(res, u'Refuses')[1])
    res, el = push(hold, [(u'Number', u'Locked')])
    check(u'push: read-only target is a failure with the reason', status_of(res, u'Locked')[0] == u'fail'
          and u'read-only' in status_of(res, u'Locked')[1])
    res, el = push(hold, [(u'Number', u'NoSuchParam')])
    check(u'push: a parameter the element lacks is a failure', status_of(res, u'NoSuchParam')[0] == u'fail')
    res, el = push(hold, [(u'NoSuchSpaceParam', u'Comments')])
    check(u'push: a space parameter the space lacks is a failure', status_of(res, u'Comments')[0] == u'fail')
    res, el = push(hold, [(u'Number', u'Ref')])
    check(u'push: element-reference target is skipped', status_of(res, u'Ref')[0] == u'skip')

    res, el = push(hold, [(u'Blank', u'Comments')], skip_blank=True)
    check(u'push: blank space value skipped when asked', status_of(res, u'Comments')[0] == u'skip')
    el = sample_element()
    el.LookupParameter(u'Comments').value = u'keep me'
    res, el = push(hold, [(u'Blank', u'Comments')], el=el, skip_blank=False)
    check(u'push: blank clears the target when not skipping',
          status_of(res, u'Comments')[0] == u'ok' and el.LookupParameter(u'Comments').value == u'')

    el = sample_element()
    reset_tx()
    res, el = push(hold, [(u'Name', u'Mark')], el=el, overwrite=False)
    check(u'push: overwrite off leaves a filled target alone',
          status_of(res, u'Mark')[0] == u'skip' and el.LookupParameter(u'Mark').value == u'old')
    check(u'push: nothing to write means no transaction at all', FTransaction.log == [], FTransaction.log)
    res, el = push(hold, [(u'Name', u'Comments')], overwrite=False)
    check(u'push: overwrite off still fills a blank target', status_of(res, u'Comments')[0] == u'ok')

    el = sample_element()
    el.LookupParameter(u'Mark').value = u'Plant Room'
    reset_tx()
    res, el = push(hold, [(u'Name', u'Mark')], el=el)
    check(u'push: already the right value is reported unchanged and not rewritten',
          status_of(res, u'Mark')[0] == u'same' and el.LookupParameter(u'Mark').sets == 0)
    check(u'push: unchanged only means no transaction', FTransaction.log == [])

    reset_tx(status='RolledBack')
    res, el = push(hold, [(u'Number', u'Comments')])
    check(u'push: a transaction that does not commit fails every row',
          status_of(res, u'Comments')[0] == u'fail' and u'did not commit' in status_of(res, u'Comments')[1])
    reset_tx(raise_start=True)
    res, el = push(hold, [(u'Number', u'Comments')])
    check(u'push: a transaction that cannot start fails the row instead of raising',
          status_of(res, u'Comments')[0] == u'fail')
    reset_tx()

    res, el = push(hold, [(u'Number', u'Comments'), (u'Number', u'NoSuchParam'), (u'Name', u'Mark')])
    check(u'push: one bad row does not cost the others',
          [r.status for r in res].count(u'ok') == 2 and status_of(res, u'NoSuchParam')[0] == u'fail')


def t_lock():
    el = sample_element(workset=None)
    doc = FDoc(elements={100: el}, workshared=True)

    class FTip(object):
        Owner = u'jsmith'

    class FWork(object):
        mine = []
        status = 'OwnedByOtherUser'

        @staticmethod
        def CheckoutElements(doc, ids):
            return StubMine(FWork.mine)

        @staticmethod
        def GetCheckoutStatus(doc, eid):
            return FWork.status

        @staticmethod
        def GetWorksharingTooltipInfo(doc, eid):
            return FTip()

    class StubMine(list):
        pass

    with patched([(M, 'WorksharingUtils', FWork)]):
        FWork.mine = []
        check(u'lock: element held by someone else names the owner',
              M.lock_reason(doc, el) == u'checked out by jsmith')
        FWork.mine = [FId(100)]
        check(u'lock: borrowed by us is free', M.lock_reason(doc, el) is None)
        FWork.mine = []
        FWork.status = 'NotOwned'
        check(u'lock: not owned and no workset problem is free', M.lock_reason(doc, el) is None)
    check(u'lock: a non-workshared model is never locked', M.lock_reason(FDoc(workshared=False), el) is None)

    hold = hold_of(Number=snap_s(u'Number', u'101'))
    reset_tx()
    with patched([(M, 'WorksharingUtils', FWork), (M, 'Transaction', FTransaction)]):
        FWork.mine = []
        FWork.status = 'OwnedByOtherUser'
        res = M.push_to_element(doc, hold, el, [(u'Number', u'Comments')], True, True)
    check(u'lock: a locked element fails its rows with the owner and starts no transaction',
          status_of(res, u'Comments')[0] == u'fail' and u'jsmith' in status_of(res, u'Comments')[1]
          and FTransaction.log == [])


def t_hold_space():
    from Autodesk.Revit.DB import BuiltInParameter
    sp = FEl(50, [FParam(u'Number', 'String', u'101'), FParam(u'Area', 'Double', 12.5, text=u'12.5 m2',
                                                              spec=u'autodesk.spec.aec:area-2.0.0'),
                  FParam(u'Number', 'String', u'dupe-should-lose')])

    class FNamed(object):
        Name = u'Level 1'

    sp.Level = FNamed()
    sp.rooms = {BuiltInParameter.ROOM_NUMBER: FParam(u'Number', 'String', u'101'),
                BuiltInParameter.ROOM_NAME: FParam(u'Name', 'String', u'Plant Room')}
    doc = FDoc(title=u'Job.rvt')
    h = M.hold_space(doc, sp)
    check(u'hold: caption from number, name and level', h.caption == u'101 - Plant Room  (Level 1)', h.caption)
    check(u'hold: first parameter of a name wins', h.values[u'Number'].text == u'101')
    check(u'hold: a double keeps raw value, text and unit spec',
          h.values[u'Area'].raw == 12.5 and h.values[u'Area'].text == u'12.5 m2'
          and L.spec_key(h.values[u'Area'].spec) == u'autodesk.spec.aec:area')
    check(u'hold: remembers the project it came from', h.doc_title == u'Job.rvt' and h.eid.Value == 50)


# ------------------------------------------------- the dropdown that searches

class FEvent(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FCombo(object):
    """Just enough ComboBox for FilterCombo: an item list, text, a selection and
    the events it wires. Template is deliberately absent, the way it is before the
    control has been rendered, so text_box() has to cope with that."""

    def __init__(self):
        self.Items = StubItems()
        self.Text = u''
        self.SelectedIndex = -1
        self.IsEditable = False
        self.IsTextSearchEnabled = True
        self.StaysOpenOnEdit = False
        self.IsDropDownOpen = False
        self.SelectionChanged = FEvent()
        self.DropDownOpened = FEvent()
        self.DropDownClosed = FEvent()
        self.LostKeyboardFocus = FEvent()
        self.PreviewKeyDown = FEvent()
        self.added = []

    def AddHandler(self, event, handler):
        self.added.append(handler)

    @property
    def Template(self):
        raise AttributeError('not rendered yet')

    @property
    def SelectedItem(self):
        if 0 <= self.SelectedIndex < len(self.Items):
            return self.Items[self.SelectedIndex]
        return None

    def items(self):
        return list(self.Items)

    def type_text(self, text):
        self.Text = text

    def pick(self, text):
        self.SelectedIndex = self.items().index(text)


class StubItems(list):
    def Add(self, item):
        self.append(item)

    def Clear(self):
        del self[:]


def t_filter_combo():
    picked = []
    combo = FCombo()
    fc = UI.FilterCombo(combo, lambda v: picked.append(v))
    check(u'combo: made editable with Revit\'s own type-ahead off',
          combo.IsEditable and not combo.IsTextSearchEnabled and combo.StaysOpenOnEdit)
    check(u'combo: a text handler is added for the inner box', len(combo.added) == 1)

    names = [u'Area', u'Room Name', u'Room Number', u'Comments']
    fc.set_items(names, u'Area')
    check(u'combo: the list is offered and the value shown', combo.items() == names and combo.Text == u'Area')

    combo.type_text(u'room')
    fc.on_text(None, object())
    check(u'combo: typing narrows the list to the matches',
          combo.items() == [u'Room Name', u'Room Number'])
    check(u'combo: what was typed stays in the box', combo.Text == u'room')
    check(u'combo: typing opens the list', combo.IsDropDownOpen)
    check(u'combo: typing is not picking', picked == [] and fc.value == u'Area')

    combo.pick(u'Room Number')
    fc.on_selection(None, None)
    check(u'combo: picking sets the value and reports it once',
          fc.value == u'Room Number' and picked == [u'Room Number'])
    check(u'combo: the whole list comes back after a pick, with the value shown',
          combo.items() == names and combo.Text == u'Room Number')

    combo.type_text(u'zzz')
    fc.on_text(None, object())
    check(u'combo: a search matching nothing keeps the full list', combo.items() == names)
    fc.revert()
    check(u'combo: text that was never picked is put back', combo.Text == u'Room Number')

    combo.type_text(u'Room Name')
    fc.on_text(None, object())
    fc.revert()
    check(u'combo: half-typed text is not taken as a choice',
          fc.value == u'Room Number' and picked == [u'Room Number'])

    fc.set_items([u'Mark', u'Comments'], u'Mark')
    check(u'combo: a new list replaces the old one', combo.items() == [u'Mark', u'Comments'])
    fc.set_items([u'Mark'], u'Gone')
    check(u'combo: a value missing from the new list is kept so it is not lost silently',
          combo.items() == [u'Gone', u'Mark'])

    blank = FCombo()
    taken = []
    fb = UI.FilterCombo(blank, lambda v: taken.append(v), blank_label=L.NONE_LABEL)
    fb.set_items([u'Mark', u'Comments'], u'')
    check(u'combo: the blank entry heads the list', blank.items()[0] == L.NONE_LABEL)
    blank.pick(u'Comments')
    fb.on_selection(None, None)
    check(u'combo: picking a real value', fb.value == u'Comments')
    blank.pick(L.NONE_LABEL)
    fb.on_selection(None, None)
    check(u'combo: picking the blank entry clears the value', fb.value == u'' and taken[-1] == u'')

    got, ok = UI.keyword_filter([u'Room Name', u'Area'], u'ROOM nam')
    check(u'combo: its filter matches every word, any case', got == [u'Room Name'] and ok)
    got, ok = UI.keyword_filter([u'Room Name', u'Area'], u'zz')
    check(u'combo: its filter never empties the list', got == [u'Room Name', u'Area'] and not ok)


def t_window_settings():
    s = L.clean_settings({'win_w': '1200', 'win_h': 'tall'})
    check(u'settings: a good window size is kept, a bad one dropped',
          s['win_w'] == '1200' and s['win_h'] == '')
    check(u'settings: window size has a default and is written out',
          'win_w' in L.DEFAULTS and 'win_w' in L.KEY_ORDER and 'win_h' in L.KEY_ORDER)
    text = L.dump_settings(L.clean_settings({'win_w': '1200', 'win_h': '800', 'theme': 'light'}))
    back = L.clean_settings(L.parse_settings(text))
    check(u'settings: size and theme survive the round trip',
          back['win_w'] == '1200' and back['win_h'] == '800' and back['theme'] == 'light')


def all_checks():
    for fn in (t_keyword_filter, t_rows_and_settings, t_plan_value, t_verify_and_results,
               t_theme_and_misc, t_queue_and_runner, t_model_reading, t_model_helpers,
               t_push, t_lock, t_hold_space, t_filter_combo, t_window_settings):
        run(fn)


# =================================================================== selftest

def _drop_clear():
    def drain(self):
        jobs = list(self._jobs)
        return jobs
    return drain


def selftest():
    """Break each rule on purpose and confirm at least one check fails."""
    real_esc = L.esc
    breakages = [
        (u'verify_write believes every write',
         [(L, 'verify_write', lambda a, v, b: True)]),
        (u'keyword_filter empties the list on a miss',
         [(L, 'keyword_filter', lambda names, q: ([n for n in names if all(
             w in n.lower() for w in L.to_text(q or u'').lower().split())], True))]),
        (u'plan_value ignores skip_blank',
         [(L, 'plan_value', (lambda orig: lambda s, st, sp, skip=True: orig(s, st, sp, False))(L.plan_value))]),
        (u'esc does not escape',
         [(L, 'esc', lambda t: L.to_text(t))]),
        (u'resolve_theme ignores Revit',
         [(L, 'resolve_theme', lambda mode, revit: mode if mode in ('dark', 'light') else 'dark')]),
        (u'JobQueue.drain leaves the jobs in place',
         [(L.JobQueue, 'drain', _drop_clear())]),
        (u'JobQueue.discard wipes the whole queue',
         [(L.JobQueue, 'discard', lambda self, job: self._jobs.clear())]),
        (u'unit check removed',
         [(L, 'spec_key', lambda t: u'')]),
        (u'find_param returns the first even when read-only',
         [(M, 'find_param', lambda el, name: (el.GetParameters(name) or [None])[0])]),
        (u'lock_reason never finds a lock',
         [(M, 'lock_reason', lambda doc, el: None)]),
        (u'target_is_blank always blank (overwrite off would overwrite)',
         [(L, 'target_is_blank', lambda s, h, t: True)]),
        (u'result_level ignores failures',
         [(L, 'result_level', lambda c: u'ok')]),
        (u'merge_names drops duplicates wrongly',
         [(L, 'merge_names', lambda names, extra: list(names))]),
        (u'default category ignores Detail Items',
         [(W, 'pick_default_category', lambda cats, saved: cats[-1] if cats else None)]),
        (u'the dropdown filter empties the list on a miss',
         [(UI, 'keyword_filter', lambda names, q: ([n for n in names if all(
             w in n.lower() for w in L.to_text(q or u'').lower().split())], True))]),
        (u'typing in a dropdown is taken as picking',
         [(UI.FilterCombo, 'on_text', lambda self, sender, args: self.on_selection(sender, args))]),
        (u'a dropdown keeps only the filtered list after a pick',
         [(UI.FilterCombo, 'show_all', lambda self: None)]),
        (u'window size is not validated',
         [(L, 'clean_settings', (lambda orig: lambda raw: dict(orig(raw), win_h=L.to_text(
             (raw or {}).get('win_h', ''))))(L.clean_settings))]),
    ]
    caught = 0
    for name, pairs in breakages:
        del RESULTS[:]
        with patched(pairs):
            all_checks()
        n = len(failures())
        if n:
            caught += 1
        print(u'  %-62s %s' % (name, u'caught (%d failing)' % n if n else u'NOT CAUGHT'))
    del RESULTS[:]
    if caught != len(breakages):
        print(u'\nselftest FAILED: %d of %d breakages went unnoticed' % (len(breakages) - caught, len(breakages)))
        return 1
    print(u'\nselftest passed: all %d breakages were caught' % len(breakages))
    return 0


def main():
    if '--selftest' in sys.argv:
        return selftest()
    all_checks()
    bad = failures()
    for name, ok, detail in RESULTS:
        if not ok:
            print(u'FAIL  %s  %s' % (name, detail))
    print(u'%d checks, %d failed' % (len(RESULTS), len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
