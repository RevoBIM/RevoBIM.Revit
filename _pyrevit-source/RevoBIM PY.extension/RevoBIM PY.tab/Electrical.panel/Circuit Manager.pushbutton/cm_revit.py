# -*- coding: utf-8 -*-
"""Circuit Manager - reading circuits from the model and writing them back.

Every write goes out through an ExternalEvent (the window is modeless), in
one transaction with a sub-transaction per circuit so one refusal does not
lose the batch. Every write is read back; a void API call is not evidence.
Cross version 2024-2027: ElementId through eid_value(), BuiltInParameter
looked up by name at call time, no System.Uri.
"""
import cm_clr  # noqa: F401
import cm_logic
from cm_logic import to_text

from System.Collections.Generic import List
from Autodesk.Revit.DB import (FilteredElementCollector, ElementId,
                               StorageType, Transaction, SubTransaction,
                               TransactionStatus, IFailuresPreprocessor,
                               FailureProcessingResult, FailureSeverity,
                               WorksharingUtils)
from Autodesk.Revit.DB.Electrical import ElectricalSystem
import Autodesk.Revit.DB.Electrical as _elec
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

# ======================================================================
# Fixed columns - key, heading, kind, editable
# ======================================================================
FIXED = [
    ('panel', u'Panel', 'string', False),
    ('num', u'Circuit Number', 'string', False),
    ('load', u'Load Name', 'string', False),
    ('stype', u'System Type', 'string', False),
    ('pm', u'Path Mode', 'pm', True),
    ('po', u'Path Offset (mm)', 'po', True),
    ('len', u'Length (mm)', 'string', False),
    ('nelem', u'Elements', 'string', False),
]
FIXED_KEYS = [f[0] for f in FIXED]
PARAM_PREFIX = 'p:'

VARIES = u'Varies'


def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return getattr(element_id, 'IntegerValue')
    except Exception:
        return 0


def bip(name):
    """BuiltInParameter member by name, at call time; None where missing."""
    try:
        from Autodesk.Revit.DB import BuiltInParameter
        return getattr(BuiltInParameter, name, None)
    except Exception:
        return None


def elem_name(element):
    if element is None:
        return u''
    try:
        return to_text(element.Name)
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element
        return to_text(Element.Name.GetValue(element))
    except Exception:
        return u''


# ======================================================================
# Reading
# ======================================================================
def collect_circuits(doc):
    out = []
    for es in FilteredElementCollector(doc).OfClass(ElectricalSystem):
        out.append(es)
    return out


def _panel_name(es):
    try:
        name = es.PanelName
        if name:
            return to_text(name)
    except Exception:
        pass
    try:
        return elem_name(es.BaseEquipment)
    except Exception:
        return u''


def _length_mm(es):
    p = None
    b = bip('RBS_ELEC_CIRCUIT_LENGTH_PARAM')
    if b is not None:
        try:
            p = es.get_Parameter(b)
        except Exception:
            p = None
    try:
        if p is not None and p.HasValue:
            return cm_logic.feet_to_mm_text(p.AsDouble())
    except Exception:
        pass
    try:
        return cm_logic.feet_to_mm_text(es.Length)
    except Exception:
        return u''


def path_mode_name(es):
    try:
        return to_text(es.CircuitPathMode)
    except Exception:
        return u''


def path_offset_text(es):
    try:
        if not es.HasPathOffset:
            return VARIES
    except Exception:
        pass
    try:
        return cm_logic.feet_to_mm_text(es.PathOffset)
    except Exception:
        return u''


def param_kind(p):
    """Column kind for a parameter, from its storage type."""
    try:
        st = p.StorageType
    except Exception:
        return 'string'
    if st == StorageType.String:
        return 'string'
    if st == StorageType.Integer:
        try:
            from Autodesk.Revit.DB import SpecTypeId
            if p.Definition.GetDataType() == SpecTypeId.Boolean.YesNo:
                return 'yesno'
        except Exception:
            pass
        return 'int'
    if st == StorageType.Double:
        return 'double'
    return 'id'


def param_text(p):
    if p is None:
        return u''
    try:
        st = p.StorageType
        if st == StorageType.String:
            return to_text(p.AsString())
        vs = p.AsValueString()
        if vs is not None:
            return to_text(vs)
        if st == StorageType.Integer:
            return to_text(p.AsInteger())
        if st == StorageType.Double:
            return to_text(p.AsDouble())
        if st == StorageType.ElementId:
            return to_text(eid_value(p.AsElementId()))
    except Exception:
        pass
    return u''


def param_writable(p):
    try:
        return (not p.IsReadOnly) and param_kind(p) in (
            'string', 'int', 'yesno', 'double')
    except Exception:
        return False


def find_param(es, name):
    try:
        return es.LookupParameter(name)
    except Exception:
        return None


def available_parameters(circuits, sample=200):
    """[(name, kind, writable)] carried by circuits, sorted by name.

    Reads the full parameter list of up to `sample` circuits so a parameter
    bound to one circuit type only (power vs data) still shows up.
    """
    found = {}
    for es in circuits[:sample]:
        try:
            params = list(es.Parameters)
        except Exception:
            continue
        for p in params:
            try:
                name = to_text(p.Definition.Name)
            except Exception:
                continue
            if not name or name in found:
                continue
            found[name] = (param_kind(p), param_writable(p))
    return sorted([(n, k, w) for n, (k, w) in found.items()],
                  key=lambda t: cm_logic.natural_key(t[0]))


class CircuitRow(object):
    """One circuit as the table sees it. Values are text, keyed by column."""

    def __init__(self, es):
        self.eid = eid_value(es.Id)
        self.element_id = es.Id
        self.values = {}
        self.editable = {}
        self.kinds = {}
        self.custom_ok = False
        self.reasons = {}


def read_row(es, param_keys):
    row = CircuitRow(es)
    v = row.values
    v['panel'] = _panel_name(es)
    try:
        v['num'] = to_text(es.CircuitNumber)
    except Exception:
        v['num'] = u''
    try:
        v['load'] = to_text(es.LoadName)
    except Exception:
        v['load'] = u''
    try:
        v['stype'] = to_text(es.SystemType)
    except Exception:
        v['stype'] = u''
    v['pm'] = cm_logic.path_mode_label(path_mode_name(es))
    v['po'] = path_offset_text(es)
    v['len'] = _length_mm(es)
    try:
        v['nelem'] = to_text(es.Elements.Size)
    except Exception:
        v['nelem'] = u''
    for key, name, kind, editable in FIXED:
        row.kinds[key] = kind
        row.editable[key] = editable
    try:
        row.custom_ok = bool(es.HasCustomCircuitPath)
    except Exception:
        row.custom_ok = False
    if v['pm'] == u'':
        row.editable['pm'] = False
        row.reasons['pm'] = u'path mode not available on this circuit'
    for key in param_keys:
        name = key[len(PARAM_PREFIX):]
        p = find_param(es, name)
        if p is None:
            v[key] = u''
            row.kinds[key] = 'string'
            row.editable[key] = False
            row.reasons[key] = u'this circuit does not carry the parameter'
            continue
        v[key] = param_text(p)
        row.kinds[key] = param_kind(p)
        row.editable[key] = param_writable(p)
        if not row.editable[key]:
            row.reasons[key] = u'read only'
    return row


def read_rows(doc, param_keys):
    return [read_row(es, param_keys) for es in collect_circuits(doc)]


# ======================================================================
# Writing
# ======================================================================
class _Failures(IFailuresPreprocessor):
    """Delete warnings; record errors so a refusal reports Revit's words."""

    def __init__(self):
        self.messages = []

    def PreprocessFailures(self, accessor):
        try:
            for f in list(accessor.GetFailureMessages()):
                try:
                    text = to_text(f.GetDescriptionText())
                except Exception:
                    text = u''
                if f.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(f)
                elif text:
                    self.messages.append(text)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _mode_enum(name):
    enum = getattr(_elec, 'ElectricalCircuitPathMode', None)
    if enum is None:
        return None
    return getattr(enum, name, None)


def _borrow(doc, eids):
    """Return {eid: reason} for elements that could not be borrowed."""
    refused = {}
    if not doc.IsWorkshared or not eids:
        return refused
    ids = List[ElementId]()
    lookup = {}
    for e in eids:
        ids.Add(e)
        lookup[eid_value(e)] = e
    held = set()
    try:
        for e in WorksharingUtils.CheckoutElements(doc, ids):
            held.add(eid_value(e))
    except Exception as ex:
        for k in lookup:
            refused[k] = u'could not borrow: {0}'.format(to_text(ex))
        return refused
    for k, e in lookup.items():
        if k in held:
            continue
        owner = u''
        try:
            info = WorksharingUtils.GetWorksharingTooltipInfo(doc, e)
            owner = to_text(info.Owner)
        except Exception:
            pass
        refused[k] = u'owned by {0} - ask them to sync and relinquish'.format(
            owner or u'another user')
    return refused


def _write_one(doc, es, key, value):
    """Make one change and read it back. Returns None or a refusal reason."""
    if key == 'pm':
        name = cm_logic.parse_path_mode(value)
        member = _mode_enum(name) if name else None
        if member is None:
            return u'Revit has no path mode called {0}'.format(value)
        if name == 'Custom':
            try:
                if not es.HasCustomCircuitPath:
                    return (u'no custom path stored - edit the path in '
                            u'Revit first')
            except Exception:
                pass
        es.CircuitPathMode = member
        if cm_logic.parse_path_mode(path_mode_name(es)) != name:
            return u'Revit kept {0}'.format(
                cm_logic.path_mode_label(path_mode_name(es)))
        return None
    if key == 'po':
        mm = cm_logic.parse_mm(value)
        if mm is None:
            return u'not a length'
        target = cm_logic.mm_to_feet(mm)
        es.PathOffset = target
        try:
            got = es.PathOffset
        except Exception:
            got = None
        if got is None or abs(got - target) > 1e-5:
            return u'Revit kept {0}'.format(path_offset_text(es))
        return None
    if key.startswith(PARAM_PREFIX):
        name = key[len(PARAM_PREFIX):]
        p = find_param(es, name)
        if p is None:
            return u'parameter not on this circuit'
        if p.IsReadOnly:
            return u'read only'
        kind = param_kind(p)
        if kind == 'string':
            p.Set(to_text(value))
            ok = to_text(p.AsString()) == to_text(value)
        elif kind == 'yesno':
            want = 1 if to_text(value).strip().lower() in cm_logic.YES else 0
            p.Set(want)
            ok = p.AsInteger() == want
        elif kind == 'int':
            p.Set(int(to_text(value).strip()))
            ok = p.AsInteger() == int(to_text(value).strip())
        elif kind == 'double':
            ok = bool(p.SetValueString(to_text(value)))
            if not ok:
                return u'Revit could not read {0} as a value'.format(value)
        else:
            return u'this kind of parameter cannot be edited here'
        if not ok:
            return u'Revit did not keep the value'
        return None
    return u'column cannot be edited'


def apply_changes(doc, changes, log=None):
    """changes: {eid int: [(key, value)]} (from Stage.by_element()).

    Returns {(eid, key): None or refusal reason}.
    """
    results = {}
    if not changes:
        return results
    elements = {}
    for es in collect_circuits(doc):
        k = eid_value(es.Id)
        if k in changes:
            elements[k] = es
    for eid, items in changes.items():
        if eid not in elements:
            for key, value in items:
                results[(eid, key)] = u'circuit no longer in the model'
    live = [elements[k].Id for k in elements]
    not_held = _borrow(doc, live)
    for eid, reason in not_held.items():
        for key, value in changes.get(eid, []):
            results[(eid, key)] = reason
    todo = [k for k in elements if k not in not_held]
    if not todo:
        return results
    fails = _Failures()
    t = Transaction(doc, u'Circuit Manager - apply')
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(fails)
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        for eid in todo:
            es = elements[eid]
            for key, value in changes[eid]:
                st = SubTransaction(doc)
                st.Start()
                try:
                    reason = _write_one(doc, es, key, value)
                except Exception as ex:
                    reason = to_text(ex) or u'Revit refused the change'
                if reason is None:
                    st.Commit()
                else:
                    st.RollBack()
                results[(eid, key)] = reason
                if log is not None:
                    log(u'{0} {1} -> {2}: {3}'.format(
                        eid, key, value, reason or u'ok'))
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        for eid in todo:
            for key, value in changes[eid]:
                results[(eid, key)] = u'rolled back: {0}'.format(to_text(ex))
        return results
    if status != TransactionStatus.Committed:
        why = u'; '.join(fails.messages) or u'Revit rolled the change back'
        for eid in todo:
            for key, value in changes[eid]:
                results[(eid, key)] = why
        return results
    # commit regenerates - prove what landed against the model as it now is
    for eid in todo:
        es = elements[eid]
        for key, value in changes[eid]:
            if results.get((eid, key)) is not None:
                continue
            now = read_row(es, [key] if key.startswith(PARAM_PREFIX) else [])
            kind = now.kinds.get(key, 'string')
            if kind == 'double':
                continue        # Revit formats it its own way; SetValueString said yes
            want = value
            if key == 'pm':
                want = cm_logic.path_mode_label(cm_logic.parse_path_mode(value))
            if not cm_logic.same_value(kind, now.values.get(key), want):
                results[(eid, key)] = u'Revit reset it to {0} on commit'.format(
                    now.values.get(key))
    return results


# ======================================================================
# ExternalEvent runner
# ======================================================================
class _Handler(IExternalEventHandler):

    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        self.runner.execute(uiapp)

    def GetName(self):
        return u'RevoBIM Circuit Manager'


class Runner(object):
    """Queue jobs for Revit's API context.

    Never clears the queue when Raise() is not Accepted: Pending means an
    earlier request is still waiting. A watchdog frees a window left busy.
    In modal mode (dead engine fallback) jobs run at once.
    """

    def __init__(self, uiapp=None, modal=False, log=None):
        self.uiapp = uiapp
        self.modal = modal
        self.log = log
        self.queue = []
        self.busy = False
        self.handler = None
        self.event = None
        if not modal:
            self.handler = _Handler(self)
            self.event = ExternalEvent.Create(self.handler)

    def submit(self, job, done):
        """job(uiapp) -> result; done(result, error) called after."""
        self.queue.append((job, done))
        if self.modal:
            self.execute(self.uiapp)
            return True
        status = self.event.Raise()
        name = to_text(status)
        if self.log is not None:
            self.log(u'Raise -> {0}'.format(name))
        if name in ('Accepted', 'Pending'):
            self.busy = True
            return True
        self.queue.remove((job, done))
        try:
            done(None, u'Revit refused the request ({0})'.format(name))
        except Exception:
            pass
        return False

    def execute(self, uiapp):
        jobs, self.queue = self.queue, []
        for job, done in jobs:
            result, error = None, None
            try:
                result = job(uiapp)
            except Exception as ex:
                import traceback
                error = traceback.format_exc() or to_text(ex)
            try:
                done(result, error)
            except Exception:
                if self.log is not None:
                    import traceback
                    self.log(traceback.format_exc())
        self.busy = False

    def free(self):
        self.busy = False
