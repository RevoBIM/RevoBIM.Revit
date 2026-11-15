# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - bench_logic.py

Pure logic tests under plain CPython, no real Revit API. A minimal `clr`
stub is installed into sys.modules first, since every module in this tool
imports fpc_clr before anything else and fpc_clr calls clr.AddReference -
that is the one concession CPython needs to load the real modules
unmodified.
"""
import os
import shutil
import sys
import tempfile
import types

if 'clr' not in sys.modules:
    stub = types.ModuleType('clr')
    stub.AddReference = lambda name: None
    sys.modules['clr'] = stub


# ==================== a fake Revit, just enough to run fpc_ops for real ====================
#
# fpc_ops reaches into Autodesk.Revit.UI and Autodesk.Revit.DB at module
# level, so those namespaces are stubbed here with the handful of names it
# uses. The point is to run the shipped Execute unmodified - the queue
# handling, the per-family isolation, the read-back - against families
# and a shared parameter file that behave the way the real ones do,
# including the ways they fail.

def _install_fake_revit():
    autodesk = types.ModuleType('Autodesk')
    revit = types.ModuleType('Autodesk.Revit')
    ui = types.ModuleType('Autodesk.Revit.UI')
    db = types.ModuleType('Autodesk.Revit.DB')

    class IExternalEventHandler(object):
        pass

    class IFailuresPreprocessor(object):
        pass

    class IFamilyLoadOptions(object):
        pass

    class _Enum(object):
        def __init__(self, name):
            self.name = name

        def __repr__(self):
            return self.name

    class FailureProcessingResult(object):
        Continue = _Enum('Continue')

    class FailureSeverity(object):
        Warning = _Enum('Warning')
        Error = _Enum('Error')

    class TransactionStatus(object):
        Committed = _Enum('Committed')
        RolledBack = _Enum('RolledBack')

    class FamilySource(object):
        Family = _Enum('Family')
        Project = _Enum('Project')

    class _FailureOptions(object):
        def __init__(self):
            self.preprocessor = None

        def SetFailuresPreprocessor(self, p):
            self.preprocessor = p

    class Transaction(object):
        def __init__(self, doc, name):
            self.doc = doc
            self.name = name
            self.started = False
            self.status = None
            self.options = _FailureOptions()
            doc.transactions.append(self)

        def GetFailureHandlingOptions(self):
            return self.options

        def SetFailureHandlingOptions(self, options):
            self.options = options

        def Start(self):
            self.started = True

        def Commit(self):
            self.status = TransactionStatus.Committed
            return self.status

        def RollBack(self):
            self.status = TransactionStatus.RolledBack
            return self.status

    ui.IExternalEventHandler = IExternalEventHandler
    db.IFailuresPreprocessor = IFailuresPreprocessor
    db.IFamilyLoadOptions = IFamilyLoadOptions
    db.FailureProcessingResult = FailureProcessingResult
    db.FailureSeverity = FailureSeverity
    db.TransactionStatus = TransactionStatus
    db.FamilySource = FamilySource
    db.Transaction = Transaction

    sys.modules['Autodesk'] = autodesk
    sys.modules['Autodesk.Revit'] = revit
    sys.modules['Autodesk.Revit.UI'] = ui
    sys.modules['Autodesk.Revit.DB'] = db
    autodesk.Revit = revit
    revit.UI = ui
    revit.DB = db


_install_fake_revit()


class FakeGuid(object):
    def __init__(self, text):
        self.text = text

    def ToString(self):
        return self.text


class FakeElementId(object):
    def __init__(self, value):
        self.Value = value


class FakeParam(object):
    """A project-side Parameter as seen on a FamilySymbol or instance."""
    def __init__(self, name, guid=None):
        self.name = name
        self.IsShared = guid is not None
        self.GUID = FakeGuid(guid) if guid is not None else None


class FakeSymbol(object):
    def __init__(self, params):
        self.params = params  # {name: FakeParam}

    def GetParameters(self, name):
        p = self.params.get(name)
        return [p] if p is not None else []


class FakeFamily(object):
    def __init__(self, key, name, symbol_id):
        self.Id = FakeElementId(key)
        self.Name = name
        self.symbol_id = symbol_id

    def GetFamilySymbolIds(self):
        return [self.symbol_id]


class FakeDefinition(object):
    def __init__(self, name):
        self.Name = name

    def GetGroupTypeId(self):
        return 'autodesk.parameter.group:data-1.0.0'


class FakeFamilyParam(object):
    def __init__(self, name, is_instance=False):
        self.Definition = FakeDefinition(name)
        self.IsInstance = is_instance


class FakeFamilyManager(object):
    def __init__(self, names, refuse=None):
        self.params = [FakeFamilyParam(n) for n in names]
        self.refuse = set(refuse or [])
        self.replaced = []

    def GetParameters(self):
        return list(self.params)

    def ReplaceParameter(self, fp, ext_def, group, is_instance):
        if fp.Definition.Name in self.refuse:
            raise Exception('Revit refused to replace {0}'.format(fp.Definition.Name))
        self.replaced.append((fp.Definition.Name, ext_def.GUID.ToString(), group, is_instance))
        return fp


class FakeOutBox(object):
    """How IronPython hands an `out` parameter to an interface method
    implemented in Python: an object whose .Value is set."""
    def __init__(self):
        self.Value = None


class FakeFamilyDoc(object):
    def __init__(self, project, family, manager, apply_on_load=True, fail_load=False):
        self.project = project
        self.family = family
        self.FamilyManager = manager
        self.apply_on_load = apply_on_load
        self.fail_load = fail_load
        self.transactions = []
        self.closed = None
        self.load_options_seen = None

    def LoadFamily(self, doc, options):
        if self.fail_load:
            raise Exception('load refused')
        box = FakeOutBox()
        overwrite = options.OnFamilyFound(True, box)
        self.load_options_seen = (overwrite, box.Value)
        if self.apply_on_load:
            sym = doc.elements[self.family.symbol_id.Value]
            for name, guid, _g, _i in self.FamilyManager.replaced:
                sym.params[name] = FakeParam(name, guid)
        return self.family

    def Close(self, save):
        self.closed = save


class FakeProject(object):
    def __init__(self, title='Bench Project'):
        self.Title = title
        self.IsWorkshared = False
        self.elements = {}
        self.family_docs = {}
        self.transactions = []

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)

    def EditFamily(self, family):
        fam_doc = self.family_docs.get(family.Id.Value)
        if fam_doc is None:
            raise Exception('EditFamily refused')
        return fam_doc


class FakeSharedDefinition(object):
    def __init__(self, name, guid):
        self.Name = name
        self.GUID = FakeGuid(guid)


class FakeGroup(object):
    def __init__(self, name, defs):
        self.Name = name
        self.Definitions = defs


class FakeSharedFile(object):
    def __init__(self, groups):
        self.Groups = groups


class FakeEvent(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeUIApp(object):
    def __init__(self, project, shared_file):
        self.project = project
        self.shared_file = shared_file
        self.DialogBoxShowing = FakeEvent()

        class _App(object):
            def __init__(inner):
                pass

            def OpenSharedParameterFile(inner):
                return self.shared_file
        self.Application = _App()

        class _UIDoc(object):
            Document = project
        self.ActiveUIDocument = _UIDoc()


def build_bench_world():
    """Two families, one shared parameter file, one refusal to make."""
    project = FakeProject()
    shared = FakeSharedFile([FakeGroup('BGL', [
        FakeSharedDefinition('BGL_Function', 'guid-function'),
        FakeSharedDefinition('BGL_Type Mark', 'guid-typemark'),
    ])])

    fam_a = FakeFamily(10, 'BGL_Ladder_LV_SubMain', FakeElementId(11))
    sym_a = FakeSymbol({'BGL_Function': FakeParam('BGL_Function'), 'BGL_Type Mark': FakeParam('BGL_Type Mark')})
    project.elements[10] = fam_a
    project.elements[11] = sym_a
    project.family_docs[10] = FakeFamilyDoc(project, fam_a, FakeFamilyManager(['BGL_Function', 'BGL_Type Mark']))

    fam_b = FakeFamily(20, 'BGL_Fire Damper 100', FakeElementId(21))
    sym_b = FakeSymbol({'BGL_Function': FakeParam('BGL_Function')})
    project.elements[20] = fam_b
    project.elements[21] = sym_b
    project.family_docs[20] = FakeFamilyDoc(project, fam_b,
                                           FakeFamilyManager(['BGL_Function'], refuse=['BGL_Function']))

    return project, FakeUIApp(project, shared)


def job_for(family, changes):
    return {
        'family_id': family.Id,
        'family_key': family.Id.Value,
        'family_name': family.Name,
        'sample_instance_id': None,
        'changes': [{'param_name': n, 'shared_guid': g, 'shared_name': n} for n, g in changes],
    }

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fpc_core  # noqa

CHECKS_RUN = [0]
CHECKS_FAILED = [0]


def check(label, condition):
    CHECKS_RUN[0] += 1
    if condition:
        print(u'ok    {0}'.format(label))
    else:
        CHECKS_FAILED[0] += 1
        print(u'FAIL  {0}'.format(label))


class FakeId(object):
    def __init__(self, value, has_value=True, has_integer=True):
        self._value = value
        self._has_value = has_value
        self._has_integer = has_integer

    @property
    def Value(self):
        if not self._has_value:
            raise AttributeError('no Value on this stub Revit release')
        return self._value

    @property
    def IntegerValue(self):
        if not self._has_integer:
            raise AttributeError('no IntegerValue either')
        return self._value


def test_eid_value():
    check('eid_value: None returns 0', fpc_core.eid_value(None) == 0)
    check('eid_value: prefers .Value', fpc_core.eid_value(FakeId(101)) == 101)
    check('eid_value: falls back to .IntegerValue when .Value is absent (pre-2024)',
          fpc_core.eid_value(FakeId(202, has_value=False)) == 202)
    check('eid_value: returns 0 when neither is present',
          fpc_core.eid_value(FakeId(303, has_value=False, has_integer=False)) == 0)


def test_settings_round_trip():
    tmp_dir = tempfile.mkdtemp(prefix='fpc_bench_')
    original_path = fpc_core.SETTINGS_PATH
    fpc_core.SETTINGS_PATH = os.path.join(tmp_dir, 'settings.txt')
    try:
        check('settings: missing file falls back to defaults',
              fpc_core.load_settings() == fpc_core.DEFAULTS)

        saved = fpc_core.save_settings({'theme': 'light', 'confirm_before_apply': 'off'})
        check('settings: save reports success', saved is True)

        reloaded = fpc_core.load_settings()
        check('settings: theme round-trips', reloaded.get('theme') == 'light')
        check('settings: confirm_before_apply round-trips', reloaded.get('confirm_before_apply') == 'off')
        check('settings: unset keys keep their default', reloaded.get('window_w') == fpc_core.DEFAULTS['window_w'])

        f = open(fpc_core.SETTINGS_PATH, 'w')
        f.write(u'not a valid line at all\ntheme=dark\n')
        f.close()
        damaged = fpc_core.load_settings()
        check('settings: a damaged file still yields a usable dict',
              damaged.get('theme') == 'dark' and 'confirm_before_apply' in damaged)
    finally:
        fpc_core.SETTINGS_PATH = original_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_migrations_drop_stale_keys():
    tmp_dir = tempfile.mkdtemp(prefix='fpc_bench_mig_')
    original_path = fpc_core.SETTINGS_PATH
    original_migrations = dict(fpc_core.MIGRATIONS)
    original_defaults = dict(fpc_core.DEFAULTS)
    fpc_core.SETTINGS_PATH = os.path.join(tmp_dir, 'settings.txt')
    fpc_core.DEFAULTS['some_new_meaning_key'] = 'new_default'
    fpc_core.MIGRATIONS['2'] = ['some_new_meaning_key']
    try:
        f = open(fpc_core.SETTINGS_PATH, 'w')
        f.write(u'settings_version=1\nsome_new_meaning_key=old_value_meant_something_else\n')
        f.close()
        values = fpc_core.load_settings()
        check('migrations: a key whose meaning changed is reset rather than carried across',
              values.get('some_new_meaning_key') == 'new_default')
    finally:
        fpc_core.SETTINGS_PATH = original_path
        fpc_core.MIGRATIONS.clear()
        fpc_core.MIGRATIONS.update(original_migrations)
        fpc_core.DEFAULTS.clear()
        fpc_core.DEFAULTS.update(original_defaults)
        shutil.rmtree(tmp_dir, ignore_errors=True)


class FakeGroupTypeId(object):
    def __init__(self, type_id):
        self.TypeId = type_id


class FakeDefinitionForgeTypeId(object):
    """Simulates a Revit 2022+ Definition: GetGroupTypeId exists."""
    def GetGroupTypeId(self):
        return FakeGroupTypeId('autodesk.parameter.group:data-1.0.0')


class FakeDefinitionBuiltInGroup(object):
    """Simulates a Revit 2021 Definition: only the old enum exists."""
    ParameterGroup = 'PG_DATA'

    def GetGroupTypeId(self):
        raise AttributeError('GetGroupTypeId does not exist pre-2022')


def test_get_group_label_falls_back_across_versions():
    label_modern = fpc_core.get_group_label(FakeDefinitionForgeTypeId())
    is_string_modern = isinstance(label_modern, str)
    if sys.version_info[0] < 3:
        is_string_modern = isinstance(label_modern, (str, unicode))  # noqa: F821
    check('get_group_label: reads the modern ForgeTypeId group without raising', is_string_modern)

    label_legacy = fpc_core.get_group_label(FakeDefinitionBuiltInGroup())
    check('get_group_label: falls back to BuiltInParameterGroup on a pre-2022 stub',
          'PG_DATA' in label_legacy)


class FakeSharedDef(object):
    def __init__(self, name, guid):
        self._name = name
        self._guid = guid

    @property
    def Name(self):
        return self._name

    @property
    def GUID(self):
        class _G(object):
            def __init__(self, g):
                self._g = g

            def ToString(self):
                return self._g
        return _G(self._guid)


def test_shared_param_helpers():
    d = FakeSharedDef('BGL_Fire Rating', 'abc-123')
    check('shared_param_display_name reads Name', fpc_core.shared_param_display_name(d) == 'BGL_Fire Rating')
    check('shared_param_guid reads GUID.ToString()', fpc_core.shared_param_guid(d) == 'abc-123')


def test_pending_change_dedupe_by_param_name():
    """Mirrors fpc_ui.MainController.pick_for_row's dict-keyed-by-name
    behaviour without touching WPF: queuing two picks for the same
    parameter keeps only the second, the family keeps only one entry."""
    pending = {}
    fam_key = 42

    def queue_pick(param_name, shared_name, shared_guid):
        if fam_key not in pending:
            pending[fam_key] = {'family_name': 'BGL_Ladder_LV_SubMain', 'changes': {}}
        pending[fam_key]['changes'][param_name] = {
            'param_name': param_name, 'shared_guid': shared_guid, 'shared_name': shared_name,
        }

    queue_pick('BGL_Function', 'BGL_Function (shared)', 'guid-1')
    queue_pick('BGL_Function', 'BGL_Function (shared, corrected)', 'guid-2')
    queue_pick('BGL_Type Mark', 'BGL_Type Mark (shared)', 'guid-3')

    check('pending: re-picking a parameter overwrites rather than duplicates',
          len(pending[fam_key]['changes']) == 2)
    check('pending: the later pick wins',
          pending[fam_key]['changes']['BGL_Function']['shared_guid'] == 'guid-2')


def test_category_grouping():
    """Mirrors MainController._grouped without touching WPF: families are
    bucketed by category in first-appearance order, the filter matches on
    either the family name or the category name, and a category whose own
    name matches keeps all of its families."""
    families = [
        {'name': 'BGL_Ladder_LV_SubMain', 'category': 'Cable Trays'},
        {'name': 'BGL_TrunkingTray_Tee', 'category': 'Cable Trays'},
        {'name': 'BGL_Fire Damper 100', 'category': 'Duct Accessories'},
        {'name': 'BGL_Volume Control Damper', 'category': 'Duct Accessories'},
        {'name': 'BGL_DB_Distribution Board', 'category': 'Electrical Equipment'},
    ]

    def grouped(filter_text):
        ft = filter_text.strip().lower()
        order = []
        index = {}
        for fam in families:
            cat = fam['category']
            if ft and ft not in fam['name'].lower() and ft not in cat.lower():
                continue
            if cat not in index:
                index[cat] = []
                order.append(cat)
            index[cat].append(fam)
        return [(cat, index[cat]) for cat in order]

    unfiltered = grouped(u'')
    check('grouping: three categories with no filter', len(unfiltered) == 3)
    check('grouping: categories keep first-appearance order',
          [c for c, _ in unfiltered] == ['Cable Trays', 'Duct Accessories', 'Electrical Equipment'])
    check('grouping: members land under their own category',
          len(unfiltered[0][1]) == 2 and len(unfiltered[2][1]) == 1)

    by_family = grouped(u'damper')
    check('grouping: a family-name filter keeps only matching categories', len(by_family) == 1)
    check('grouping: a family-name filter narrows within the category',
          len(by_family[0][1]) == 2 and by_family[0][0] == 'Duct Accessories')

    by_category = grouped(u'cable trays')
    check('grouping: a category-name filter keeps every family in it',
          len(by_category) == 1 and len(by_category[0][1]) == 2)

    check('grouping: a filter matching nothing yields no groups', grouped(u'zzzz') == [])


def test_collapse_state_is_per_category():
    """Collapsing is held as a set of category names, so it survives a
    re-read of the model that changes family ids."""
    collapsed = set()

    def toggle(cat):
        if cat in collapsed:
            collapsed.discard(cat)
        else:
            collapsed.add(cat)

    toggle('Cable Trays')
    check('collapse: toggling once collapses', 'Cable Trays' in collapsed)
    toggle('Cable Trays')
    check('collapse: toggling twice expands again', 'Cable Trays' not in collapsed)

    toggle('Duct Accessories')
    searching = True
    expanded_while_searching = searching or 'Duct Accessories' not in collapsed
    check('collapse: a live search always shows what it found', expanded_while_searching is True)


def test_merge_families():
    import fpc_model
    families = [
        {'key': 1, 'name': 'A'},
        {'key': 2, 'name': 'B'},
        {'key': 3, 'name': 'C'},
    ]
    merged = fpc_model.merge_families(families, {2: {'key': 2, 'name': 'B (refreshed)'}, 3: None})
    check('merge: a refreshed entry replaces the old one in place',
          merged[1]['name'] == 'B (refreshed)')
    check('merge: an entry refreshed to None is dropped (family deleted)', len(merged) == 2)
    check('merge: untouched entries and order are kept',
          merged[0]['name'] == 'A' and merged[1]['key'] == 2)
    check('merge: the input list is not mutated', len(families) == 3)


def test_progress_arithmetic():
    """Mirrors MainController._update_progress: the strip is two star
    columns weighted done / remaining, and the header percent is rounded."""
    def strip(done, total):
        total = total if total else 1
        return float(done), float(max(total - done, 0)), int(round(100.0 * done / total))

    check('progress: 0 of 4 is an empty strip at 0%', strip(0, 4) == (0.0, 4.0, 0))
    check('progress: 1 of 3 rounds to 33%', strip(1, 3) == (1.0, 2.0, 33))
    check('progress: 4 of 4 is a full strip at 100%', strip(4, 4) == (4.0, 0.0, 100))
    check('progress: a zero total cannot divide by zero', strip(0, 0)[2] == 0)


def test_handler_one_family_per_execute():
    import fpc_ops
    project, uiapp = build_bench_world()
    handler = fpc_ops.RebindHandler()
    handler.doc_title = project.Title
    steps = []
    handler.on_step = lambda job, results: steps.append((job['family_name'], results))

    fam_a = project.elements[10]
    fam_b = project.elements[20]
    handler.queue = [
        job_for(fam_a, [('BGL_Function', 'guid-function'), ('BGL_Type Mark', 'guid-typemark')]),
        job_for(fam_b, [('BGL_Function', 'guid-function')]),
    ]

    handler.Execute(uiapp)
    check('handler: one Execute processes exactly one family', len(steps) == 1 and len(handler.queue) == 1)
    check('handler: the first family was the first queued', steps[0][0] == 'BGL_Ladder_LV_SubMain')

    results_a = [r for r in steps[0][1] if not r.get('info')]
    check('handler: both changes on the first family rebound and read back OK',
          len(results_a) == 2 and all(r['ok'] for r in results_a))
    fam_doc_a = project.family_docs[10]
    check('handler: ReplaceParameter was called with the shared definition and group',
          fam_doc_a.FamilyManager.replaced[0][1] == 'guid-function'
          and fam_doc_a.FamilyManager.replaced[0][2] == 'autodesk.parameter.group:data-1.0.0')
    check('handler: the family was loaded back with overwrite and parameter values kept',
          fam_doc_a.load_options_seen == (True, True))
    check('handler: the family document was closed without saving', fam_doc_a.closed is False)
    check('handler: a failure preprocessor was attached to the family transaction',
          fam_doc_a.transactions and
          fam_doc_a.transactions[0].options.preprocessor is not None)
    check('handler: dialog suppression was hooked once and switched off afterwards',
          handler.dialogs_hooked and handler.suppress_dialogs is False)

    handler.Execute(uiapp)
    check('handler: the second Execute drains the queue', len(steps) == 2 and len(handler.queue) == 0)
    results_b = [r for r in steps[1][1] if not r.get('info')]
    check('handler: a refused ReplaceParameter is reported as a failure on that parameter',
          len(results_b) == 1 and results_b[0]['ok'] is False
          and 'refused' in results_b[0]['message'])
    fam_doc_b = project.family_docs[20]
    check('handler: a family with nothing applied is not loaded back',
          fam_doc_b.load_options_seen is None)
    check('handler: but its family document is still closed', fam_doc_b.closed is False)
    check('handler: the refused transaction was rolled back, not committed',
          fam_doc_b.transactions[-1].status.name == 'RolledBack')

    handler.Execute(uiapp)
    check('handler: an Execute on an empty queue does nothing', len(steps) == 2)


def test_handler_read_back_catches_a_silent_no_op():
    """A load that raises nothing but leaves the project unchanged must
    be reported as a failure - a void API call is not evidence."""
    import fpc_ops
    project, uiapp = build_bench_world()
    project.family_docs[10].apply_on_load = False
    handler = fpc_ops.RebindHandler()
    steps = []
    handler.on_step = lambda job, results: steps.append(results)
    handler.queue = [job_for(project.elements[10], [('BGL_Function', 'guid-function')])]
    handler.Execute(uiapp)
    results = [r for r in steps[0] if not r.get('info')]
    check('read-back: a load that changed nothing in the project is a failure, not a success',
          len(results) == 1 and results[0]['ok'] is False and 'old binding' in results[0]['message'])


def test_handler_isolation_and_guards():
    import fpc_ops

    # a family that has gone from the project
    project, uiapp = build_bench_world()
    handler = fpc_ops.RebindHandler()
    steps = []
    handler.on_step = lambda job, results: steps.append(results)
    ghost = FakeFamily(99, 'Deleted Family', FakeElementId(98))
    handler.queue = [job_for(ghost, [('BGL_Function', 'guid-function')]),
                     job_for(project.elements[10], [('BGL_Function', 'guid-function')])]
    handler.Execute(uiapp)
    check('isolation: a missing family is reported, not raised',
          steps[0][0]['ok'] is False and 'no longer exists' in steps[0][0]['message'])
    handler.Execute(uiapp)
    check('isolation: the family after it is still processed normally',
          [r for r in steps[1] if not r.get('info')][0]['ok'] is True)

    # the active document changed under the tool
    project, uiapp = build_bench_world()
    handler = fpc_ops.RebindHandler()
    handler.doc_title = 'Some Other Project'
    steps = []
    handler.on_step = lambda job, results: steps.append(results)
    handler.queue = [job_for(project.elements[10], [('BGL_Function', 'guid-function')])]
    handler.Execute(uiapp)
    check('guard: a different active document is skipped, never written into',
          steps[0][0]['ok'] is False and 'active document changed' in steps[0][0]['message']
          and project.family_docs[10].closed is None)

    # EditFamily itself refuses
    project, uiapp = build_bench_world()
    del project.family_docs[10]
    handler = fpc_ops.RebindHandler()
    steps = []
    handler.on_step = lambda job, results: steps.append(results)
    handler.queue = [job_for(project.elements[10], [('BGL_Function', 'guid-function')])]
    handler.Execute(uiapp)
    check('isolation: a refused EditFamily is reported plainly',
          steps[0][0]['ok'] is False and 'family editor' in steps[0][0]['message'])

    # LoadFamily refuses after a successful rebind
    project, uiapp = build_bench_world()
    project.family_docs[10].fail_load = True
    handler = fpc_ops.RebindHandler()
    steps = []
    handler.on_step = lambda job, results: steps.append(results)
    handler.queue = [job_for(project.elements[10], [('BGL_Function', 'guid-function')])]
    handler.Execute(uiapp)
    r = [x for x in steps[0] if not x.get('info')][0]
    check('isolation: a refused load is reported against the parameter, and the doc still closed',
          r['ok'] is False and 'loading it back' in r['message']
          and project.family_docs[10].closed is False)

    # a shared parameter that is not in the file
    project, uiapp = build_bench_world()
    handler = fpc_ops.RebindHandler()
    steps = []
    handler.on_step = lambda job, results: steps.append(results)
    handler.queue = [job_for(project.elements[10], [('BGL_Function', 'guid-not-in-file')])]
    handler.Execute(uiapp)
    r = [x for x in steps[0] if not x.get('info')][0]
    check('guard: a GUID missing from the shared parameter file is reported and nothing is loaded',
          r['ok'] is False and 'shared parameter file' in r['message'].lower()
          and project.family_docs[10].load_options_seen is None)


def test_run_chain_decisions():
    """Mirrors MainController._on_family_step's decision: after each
    family, raise again unless cancelled or the queue is empty - and a
    cancel stops after the family in hand, never mid-family."""
    def decide(queue_remaining, cancel_requested):
        if cancel_requested or queue_remaining == 0:
            return 'finish'
        return 'raise_next'

    check('chain: more queued and no cancel raises the next step', decide(3, False) == 'raise_next')
    check('chain: an empty queue finishes', decide(0, False) == 'finish')
    check('chain: a cancel finishes even with families still queued', decide(3, True) == 'finish')

    # what the summary reports when cancelled with two of five done
    run_done, run_total, queue_left = 2, 5, 3
    touched_keys = ['k1', 'k2', 'k3', 'k4', 'k5'][:run_done]
    check('chain: only families actually processed are re-read afterwards', touched_keys == ['k1', 'k2'])
    check('chain: the families never started are counted as not started', queue_left == run_total - run_done)


def _bulk_families():
    def fam(key, name, category, params, blocked=None):
        return {'key': key, 'name': name, 'category': category, 'blocked': blocked,
                'params': [{'name': n, 'is_shared': g is not None, 'guid': g or u'',
                            'is_type': True, 'storage': 'String'} for n, g in params]}
    return [
        fam(1, 'BGL_Ladder_LV', 'Cable Trays', [('BGL_Function', None), ('BGL_Type Mark', None)]),
        fam(2, 'BGL_Tray_ELV', 'Cable Trays', [('BGL_Function', 'guid-right')]),
        fam(3, 'BGL_Fire Damper', 'Duct Accessories', [('BGL_Function', 'guid-wrong')]),
        fam(4, 'BGL_VCD', 'Duct Accessories', [('BGL_Type Mark', None)]),
        fam(5, 'In-place Thing', 'Generic Models', [('BGL_Function', None)], blocked=u'in-place family'),
    ]


def test_parameter_census():
    fams = _bulk_families()
    all_scope = fpc_core.parameter_census(fams, fpc_core.BULK_ALL)
    check('census: counts families carrying each parameter across all families',
          all_scope['BGL_Function']['families'] == 3 and all_scope['BGL_Type Mark']['families'] == 2)
    check('census: splits shared from not shared',
          all_scope['BGL_Function']['shared'] == 2 and all_scope['BGL_Function']['unshared'] == 1)
    check('census: blocked families are left out - they cannot be rebound',
          all_scope['BGL_Function']['families'] == 3)  # the in-place one would make 4
    trays = fpc_core.parameter_census(fams, 'Cable Trays')
    check('census: a category scope narrows to that category',
          trays['BGL_Function']['families'] == 2 and 'BGL_Type Mark' in trays)
    check('census: None scope means everything', fpc_core.parameter_census(fams, None) == all_scope)


def test_plan_bulk():
    fams = _bulk_families()

    targets, skipped = fpc_core.plan_bulk(fams, fpc_core.BULK_ALL, 'BGL_Function', 'guid-right', True)
    names = sorted(f['name'] for f in targets)
    check('plan: queues every unblocked family carrying the parameter, in any category',
          names == ['BGL_Fire Damper', 'BGL_Ladder_LV'])
    check('plan: a family already bound to exactly this GUID is skipped, and says so',
          ('BGL_Tray_ELV', u'already bound to this shared parameter') in skipped)
    check('plan: a family bound to a *different* shared parameter is still a target',
          'BGL_Fire Damper' in names)
    check('plan: a blocked family is skipped with its reason',
          ('In-place Thing', u'in-place family') in skipped)
    check('plan: families without the parameter are neither targets nor skipped',
          len(targets) + len(skipped) == 4)

    targets, skipped = fpc_core.plan_bulk(fams, fpc_core.BULK_ALL, 'BGL_Function', 'guid-right', False)
    check('plan: with skip off, the already-bound family is queued too',
          len(targets) == 3 and not any(r == u'already bound to this shared parameter' for _n, r in skipped))

    targets, skipped = fpc_core.plan_bulk(fams, 'Duct Accessories', 'BGL_Function', 'guid-right', True)
    check('plan: a category scope only touches that category',
          [f['name'] for f in targets] == ['BGL_Fire Damper'] and skipped == [])

    targets, skipped = fpc_core.plan_bulk(fams, 'Cable Trays', 'No Such Parameter', 'guid-right', True)
    check('plan: an unknown parameter plans nothing', targets == [] and skipped == [])


def test_run_log():
    tmp_dir = tempfile.mkdtemp(prefix='fpc_bench_log_')
    path = os.path.join(tmp_dir, 'sub', 'run.log')
    try:
        ok = fpc_core.append_log([u'=== run started', u'line two'], path=path)
        check('log: writes, creating the folder', ok is True and os.path.isfile(path))
        fpc_core.append_log([u'=== run finished'], path=path)
        text = open(path).read()
        check('log: appends rather than overwrites', text.count('===') == 2)
        check('log: every line is timestamped', all(line[:4].isdigit() for line in text.strip().splitlines()))
        bad = fpc_core.append_log([u'x'], path=os.path.join(path, 'x.log'))  # a file used as a folder
        check('log: a path that cannot be written returns False instead of raising', bad is False)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    line_ok = fpc_core.format_result_line({'family': 'F', 'param': 'P', 'ok': True, 'message': 'Rebound'})
    line_fail = fpc_core.format_result_line({'family': 'F', 'param': '', 'ok': False, 'message': 'Skipped'})
    line_info = fpc_core.format_result_line({'family': 'F', 'param': '', 'ok': True, 'message': '1 dialog', 'info': True})
    check('log line: OK / FAILED / INFO marks',
          line_ok.startswith('OK') and line_fail.startswith('FAILED') and line_info.startswith('INFO'))
    check('log line: a family-level result has no dangling parameter separator',
          ' . ' not in line_fail and 'F  -  Skipped' in line_fail)


def run():
    test_eid_value()
    test_settings_round_trip()
    test_migrations_drop_stale_keys()
    test_get_group_label_falls_back_across_versions()
    test_shared_param_helpers()
    test_pending_change_dedupe_by_param_name()
    test_category_grouping()
    test_collapse_state_is_per_category()
    test_merge_families()
    test_progress_arithmetic()
    test_handler_one_family_per_execute()
    test_handler_read_back_catches_a_silent_no_op()
    test_handler_isolation_and_guards()
    test_run_chain_decisions()
    test_parameter_census()
    test_plan_bulk()
    test_run_log()
    print(u'{0}/{1} checks passed'.format(CHECKS_RUN[0] - CHECKS_FAILED[0], CHECKS_RUN[0]))
    return CHECKS_FAILED[0] == 0


if __name__ == '__main__':
    ok = run()
    sys.exit(0 if ok else 1)
