# -*- coding: utf-8 -*-
"""Schematic Marriage - everything that touches the Revit document.

The database lives IN the model, in Extensible Storage:

* one DataStorage element per marriage and one per template, all carrying
  the same schema (Kind + Data text). One element per record rather than one
  big element, because on a workshared ACC model two people adding marriages
  at once would otherwise fight over borrowing a single element.
* a marriage is keyed by the two elements' UniqueIds.

Only called from inside an ExternalEvent handler (or the launching command),
so every write here is in API context.
"""
import sm_clr  # noqa: F401  (must stay first - references the assemblies)

import clr
from System import Guid, String
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    Element, ElementId, FilteredElementCollector, Transaction,
    TransactionGroup, IFailuresPreprocessor, FailureProcessingResult,
    FailureSeverity, WorksharingUtils, OverrideGraphicSettings, Color,
    FillPatternElement, View3D, ViewFamilyType, XYZ, BoundingBoxXYZ,
    ElementCategoryFilter, BuiltInCategory, TemporaryViewMode,
)
from Autodesk.Revit.DB.ExtensibleStorage import (
    SchemaBuilder, Schema, Entity, AccessLevel, DataStorage,
    ExtensibleStorageFilter,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

import sm_store as store
from sm_store import to_text

SCHEMA_GUID = '6ecae81b-a7d7-4a19-b519-2ce6515d1ec1'
SCHEMA_NAME = 'RevoBIMSchematicMarriage'
FIELD_KIND = 'Kind'
FIELD_DATA = 'Data'
CHUNK = 25


# ==========================================================================
# version-safe helpers
# ==========================================================================

def eid_value(element_id):
    """ElementId -> int on every release (.Value from 2024, .IntegerValue gone in 2026)."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def elem_name(e):
    if e is None:
        return u''
    try:
        return to_text(e.Name)
    except Exception:
        pass
    try:
        return to_text(Element.Name.GetValue(e))
    except Exception:
        return u''


def by_uid(doc, uid):
    if not uid:
        return None
    try:
        e = doc.GetElement(to_text(uid))
        if e is not None and e.IsValidObject:
            return e
    except Exception:
        pass
    return None


class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for f in list(accessor.GetFailureMessages()):
                if f.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(f)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _quiet(t):
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass


def _committed(status):
    return to_text(status) == u'Committed'


# ==========================================================================
# describing elements
# ==========================================================================

def family_type(doc, e):
    try:
        sym = e.Symbol
        if sym is not None:
            return u'{0} : {1}'.format(to_text(sym.Family.Name), elem_name(sym))
    except Exception:
        pass
    try:
        tid = e.GetTypeId()
        if eid_value(tid) > 0:
            t = doc.GetElement(tid)
            fam = u''
            try:
                fam = to_text(t.FamilyName)
            except Exception:
                pass
            if fam:
                return u'{0} : {1}'.format(fam, elem_name(t))
            return elem_name(t)
    except Exception:
        pass
    return elem_name(e)


def owner_view_name(doc, e):
    try:
        vid = e.OwnerViewId
        if eid_value(vid) > 0:
            return elem_name(doc.GetElement(vid))
    except Exception:
        pass
    return u''


def describe(doc, e):
    """dict used by both pick cards and table rows."""
    cat = None
    try:
        cat = e.Category
    except Exception:
        pass
    return {
        'uid': to_text(e.UniqueId),
        'eid': to_text(eid_value(e.Id)),
        'cat_id': to_text(eid_value(cat.Id)) if cat is not None else u'',
        'cat_name': to_text(cat.Name) if cat is not None else u'(no category)',
        'label': family_type(doc, e),
        'view': owner_view_name(doc, e),
    }


def resolve(doc, marriages):
    """Fill the runtime labels on each marriage; flag missing elements."""
    for m in marriages:
        s = by_uid(doc, m.src_uid)
        t = by_uid(doc, m.tgt_uid)
        m.src_missing = s is None
        m.tgt_missing = t is None
        if s is not None:
            d = describe(doc, s)
            m.src_label, m.src_eid, m.src_view = d['label'], d['eid'], d['view']
        else:
            m.src_label, m.src_eid, m.src_view = u'(deleted from the model)', u'', u''
        if t is not None:
            d = describe(doc, t)
            m.tgt_label, m.tgt_eid, m.tgt_view = d['label'], d['eid'], d['view']
        else:
            m.tgt_label, m.tgt_eid, m.tgt_view = u'(deleted from the model)', u'', u''


# ==========================================================================
# the database - Extensible Storage
# ==========================================================================

def get_schema(create=True):
    guid = Guid(SCHEMA_GUID)
    schema = Schema.Lookup(guid)
    if schema is not None or not create:
        return schema
    b = SchemaBuilder(guid)
    b.SetSchemaName(SCHEMA_NAME)
    b.SetReadAccessLevel(AccessLevel.Public)
    b.SetWriteAccessLevel(AccessLevel.Public)
    try:
        b.SetDocumentation('RevoBIM Schematic Marriage records (marriages and parameter push templates).')
    except Exception:
        pass
    b.AddSimpleField(FIELD_KIND, clr.GetClrType(String))
    b.AddSimpleField(FIELD_DATA, clr.GetClrType(String))
    return b.Finish()


def _storages(doc, schema):
    try:
        return list(FilteredElementCollector(doc).OfClass(DataStorage)
                    .WherePasses(ExtensibleStorageFilter(schema.GUID)))
    except Exception:
        return list(FilteredElementCollector(doc).OfClass(DataStorage))


def read_all(doc):
    """-> (marriages, templates). Empty lists when the model has none yet."""
    schema = get_schema(create=False)
    if schema is None:
        return [], []
    f_kind = schema.GetField(FIELD_KIND)
    f_data = schema.GetField(FIELD_DATA)
    marriages, templates = [], []
    for ds in _storages(doc, schema):
        try:
            ent = ds.GetEntity(schema)
            if ent is None or not ent.IsValid():
                continue
            kind = to_text(ent.Get[String](f_kind))
            data = to_text(ent.Get[String](f_data))
            obj = store.record_kind_and_object(kind, data)
            if obj is None:
                continue
            obj.storage_id = ds.Id
            if kind == store.KIND_MARRIAGE:
                marriages.append(obj)
            else:
                templates.append(obj)
        except Exception:
            continue
    marriages.sort(key=lambda m: (m.created, m.id))
    templates.sort(key=lambda t: store.natural_key(t.name))
    return marriages, templates


def _write_entity(ds, schema, kind, text):
    ent = Entity(schema)
    ent.Set[String](schema.GetField(FIELD_KIND), to_text(kind))
    ent.Set[String](schema.GetField(FIELD_DATA), to_text(text))
    ds.SetEntity(ent)


def _read_back(doc, storage_id, schema):
    ds = doc.GetElement(storage_id)
    if ds is None:
        return None
    ent = ds.GetEntity(schema)
    if ent is None or not ent.IsValid():
        return None
    return to_text(ent.Get[String](schema.GetField(FIELD_DATA)))


def borrow(doc, ids):
    """-> (held_values, refused{value: owner}). Not workshared: all held."""
    vals = [eid_value(i) for i in ids]
    if not ids or not doc.IsWorkshared:
        return set(vals), {}
    held = set()
    try:
        got = WorksharingUtils.CheckoutElements(doc, List[ElementId](ids))
        held = set(eid_value(i) for i in got)
    except Exception:
        pass
    refused = {}
    for i in ids:
        v = eid_value(i)
        if v in held:
            continue
        owner = u''
        try:
            owner = to_text(WorksharingUtils.GetWorksharingTooltipInfo(doc, i).Owner)
        except Exception:
            pass
        refused[v] = owner or u'another user'
    return held, refused


def save_records(doc, label, creates=None, updates=None, deletes=None):
    """One transaction for a batch of record changes.
    creates: [(kind, obj)]   updates: [obj]   deletes: [obj]
    -> {'done': [obj], 'failed': [(obj, reason)]}"""
    creates = creates or []
    updates = updates or []
    deletes = deletes or []
    report = {'done': [], 'failed': []}
    schema = get_schema(create=True)

    existing = [o.storage_id for o in updates + deletes if o.storage_id is not None]
    _held, refused = borrow(doc, existing)
    live_updates, live_deletes = [], []
    for o in updates:
        if o.storage_id is not None and eid_value(o.storage_id) in refused:
            report['failed'].append((o, u'held by ' + refused[eid_value(o.storage_id)]))
        else:
            live_updates.append(o)
    for o in deletes:
        if o.storage_id is not None and eid_value(o.storage_id) in refused:
            report['failed'].append((o, u'held by ' + refused[eid_value(o.storage_id)]))
        else:
            live_deletes.append(o)

    t = Transaction(doc, u'Schematic Marriage - ' + to_text(label))
    _quiet(t)
    t.Start()
    pending = []
    try:
        for kind, obj in creates:
            try:
                ds = DataStorage.Create(doc)
                _write_entity(ds, schema, kind, obj.to_text())
                obj.storage_id = ds.Id
                pending.append(obj)
            except Exception as ex:
                report['failed'].append((obj, u'could not create: ' + to_text(ex)))
        for obj in live_updates:
            try:
                ds = doc.GetElement(obj.storage_id) if obj.storage_id is not None else None
                if ds is None:
                    ds = DataStorage.Create(doc)
                    obj.storage_id = ds.Id
                kind = store.KIND_TEMPLATE if isinstance(obj, store.Template) else store.KIND_MARRIAGE
                _write_entity(ds, schema, kind, obj.to_text())
                pending.append(obj)
            except Exception as ex:
                report['failed'].append((obj, u'could not update: ' + to_text(ex)))
        for obj in live_deletes:
            try:
                if obj.storage_id is not None and doc.GetElement(obj.storage_id) is not None:
                    doc.Delete(obj.storage_id)
                pending.append(obj)
            except Exception as ex:
                report['failed'].append((obj, u'could not delete: ' + to_text(ex)))
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        for obj in pending:
            report['failed'].append((obj, u'rolled back: ' + to_text(ex)))
        return report

    if not _committed(status):
        for obj in pending:
            report['failed'].append((obj, u'Revit did not commit (' + to_text(status) + u')'))
        return report

    # a void call is not evidence - read every write back
    for obj in pending:
        if obj in live_deletes:
            if obj.storage_id is not None and doc.GetElement(obj.storage_id) is not None:
                report['failed'].append((obj, u'still in the model after delete'))
            else:
                obj.storage_id = None
                report['done'].append(obj)
            continue
        back = _read_back(doc, obj.storage_id, schema)
        if back == obj.to_text():
            if isinstance(obj, store.Marriage):
                obj.applied_tid = obj.template_id     # now what the model holds
            report['done'].append(obj)
        else:
            report['failed'].append((obj, u'did not read back'))
    return report


# ==========================================================================
# picking
# ==========================================================================

class _AnyCategorised(ISelectionFilter):
    def AllowElement(self, e):
        try:
            return e.Category is not None
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


class PickCancelled(Exception):
    pass


def pick_element(uidoc, prompt):
    """A single pre-selected element counts as the pick (then the selection is
    cleared, so the next pick does not reuse it). Otherwise one PickObject -
    the click completes it, Escape cancels."""
    doc = uidoc.Document
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        ids = []
    if len(ids) == 1:
        e = doc.GetElement(ids[0])
        if e is not None and getattr(e, 'Category', None) is not None:
            try:
                uidoc.Selection.SetElementIds(List[ElementId]())
            except Exception:
                pass
            return e, u'selection'
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, _AnyCategorised(), prompt)
    except Exception as ex:
        if 'Cancel' in type(ex).__name__ or 'cancel' in to_text(ex).lower():
            raise PickCancelled()
        raise
    return doc.GetElement(ref.ElementId), u'pick'


def show_element(uidoc, uid):
    """Select it and bring it into view. A detail item opens its own view."""
    doc = uidoc.Document
    e = by_uid(doc, uid)
    if e is None:
        return u'missing'
    try:
        uidoc.Selection.SetElementIds(List[ElementId]([e.Id]))
    except Exception:
        pass
    try:
        owner = e.OwnerViewId
        if eid_value(owner) > 0 and eid_value(owner) != eid_value(uidoc.ActiveView.Id):
            uidoc.RequestViewChange(doc.GetElement(owner))
            return u'view'
    except Exception:
        pass
    try:
        uidoc.ShowElements(e.Id)
    except Exception:
        pass
    return u'shown'


# ==========================================================================
# categories and parameters (for the template editor)
# ==========================================================================

def category_by_value(doc, value):
    want = to_text(value)
    for cat in doc.Settings.Categories:
        try:
            if to_text(eid_value(cat.Id)) == want:
                return cat
        except Exception:
            continue
    return None


def _tick(progress, done, total, every):
    if progress is not None and (done % every == 0 or done == total):
        try:
            progress(done, total)
        except Exception:
            pass


# The categories the template editor offers: MEP plus the two schematic
# targets. Looked up by name at call time - a name missing on an older
# release is simply skipped. Order here is the order of the groups.
CATEGORY_GROUPS = [
    (u'Mechanical', [
        'OST_DuctCurves', 'OST_DuctFitting', 'OST_DuctAccessory', 'OST_DuctTerminal',
        'OST_FlexDuctCurves', 'OST_DuctInsulations', 'OST_DuctLinings', 'OST_PlaceHolderDucts',
        'OST_MechanicalEquipment', 'OST_MechanicalControlDevices', 'OST_MEPSpaces',
        'OST_FabricationDuctwork', 'OST_FabricationHangers']),
    (u'Plumbing', [
        'OST_PipeCurves', 'OST_PipeFitting', 'OST_PipeAccessory', 'OST_FlexPipeCurves',
        'OST_PipeInsulations', 'OST_PlaceHolderPipes', 'OST_PlumbingFixtures',
        'OST_PlumbingEquipment', 'OST_Sprinklers', 'OST_FireProtection', 'OST_FabricationPipework']),
    (u'Electrical', [
        'OST_CableTray', 'OST_CableTrayFitting', 'OST_CableTrayRun', 'OST_Conduit',
        'OST_ConduitFitting', 'OST_ConduitRun', 'OST_ElectricalEquipment', 'OST_ElectricalFixtures',
        'OST_LightingFixtures', 'OST_LightingDevices', 'OST_CommunicationDevices', 'OST_DataDevices',
        'OST_FireAlarmDevices', 'OST_NurseCallDevices', 'OST_SecurityDevices', 'OST_TelephoneDevices',
        'OST_AudioVisualDevices', 'OST_ElectricalCircuit', 'OST_Wire', 'OST_FabricationContainment']),
    (u'Schematic', ['OST_DetailComponents', 'OST_GenericAnnotation']),
]


def list_categories(doc, progress=None):
    """[(cat_id, name, count, group)] for the MEP categories plus Detail Items
    and Generic Annotations that have elements in the model. About 50 quick
    category counts instead of one per category in the model (400+)."""
    cats = []
    seen = set()
    for group, names in CATEGORY_GROUPS:
        for name in names:
            bic = getattr(BuiltInCategory, name, None)
            if bic is None:
                continue
            cat = None
            try:
                cat = doc.Settings.Categories.get_Item(bic)
            except Exception:
                cat = None
            if cat is None:
                continue
            key = eid_value(cat.Id)
            if key in seen:
                continue
            seen.add(key)
            cats.append((cat, group))
    out = []
    total = len(cats)
    for i, (cat, group) in enumerate(cats, 1):
        _tick(progress, i, total, 4)
        try:
            n = (FilteredElementCollector(doc).OfCategoryId(cat.Id)
                 .WhereElementIsNotElementType().GetElementCount())
            if n > 0:
                out.append((to_text(eid_value(cat.Id)), to_text(cat.Name), int(n), group))
        except Exception:
            continue
    order = dict((g, k) for k, (g, _n) in enumerate(CATEGORY_GROUPS))
    out.sort(key=lambda c: (order.get(c[3], 99), store.natural_key(c[1])))
    return out


def _storage_of(p):
    try:
        s = to_text(p.StorageType)
    except Exception:
        return u''
    return u'' if s == u'None' else s


def discover_params(doc, cat_value, limit=80, type_limit=25, progress=None):
    """Parameters seen on up to `limit` elements of the category and their
    types. -> [dict(name, scope, storage, writable, shared)] sorted by name."""
    cat = category_by_value(doc, cat_value)
    if cat is None:
        return []
    found = {}

    def add(p, scope):
        try:
            name = to_text(p.Definition.Name)
        except Exception:
            return
        storage = _storage_of(p)
        if not name or not storage:
            return
        key = (name, scope)
        info = found.get(key)
        if info is None:
            info = {'name': name, 'scope': scope, 'storage': storage,
                    'writable': False, 'shared': False}
            found[key] = info
        try:
            if not p.IsReadOnly:
                info['writable'] = True
        except Exception:
            pass
        try:
            if p.IsShared:
                info['shared'] = True
        except Exception:
            pass

    seen_types = set()
    n = 0
    for e in (FilteredElementCollector(doc).OfCategoryId(cat.Id)
              .WhereElementIsNotElementType()):
        n += 1
        if n > limit:
            break
        _tick(progress, n, limit, 4)
        try:
            for p in e.Parameters:
                add(p, u'instance')
        except Exception:
            pass
        try:
            tid = e.GetTypeId()
            tv = eid_value(tid)
            if tv > 0 and tv not in seen_types and len(seen_types) < type_limit:
                seen_types.add(tv)
                t = doc.GetElement(tid)
                for p in t.Parameters:
                    add(p, u'type')
        except Exception:
            pass
    _tick(progress, limit, limit, 1)
    out = list(found.values())
    out.sort(key=lambda d: (store.natural_key(d['name']), d['scope']))
    return out


# ==========================================================================
# reading and writing parameter values
# ==========================================================================

def find_param(doc, e, name, scope=None):
    """-> (parameter, scope) instance first unless scope says type."""
    if e is None or not name:
        return None, u''
    if scope != u'type':
        try:
            p = e.LookupParameter(name)
            if p is not None:
                return p, u'instance'
        except Exception:
            pass
    if scope != u'instance' or scope is None:
        try:
            tid = e.GetTypeId()
            if eid_value(tid) > 0:
                t = doc.GetElement(tid)
                p = t.LookupParameter(name) if t is not None else None
                if p is not None:
                    return p, u'type'
        except Exception:
            pass
    return None, u''


def read_param(doc, p):
    info = {'storage': _storage_of(p), 'has_value': False, 'text': None,
            'vstring': None, 'raw': None, 'name': u''}
    s = info['storage']
    try:
        info['vstring'] = p.AsValueString()
    except Exception:
        pass
    try:
        if s == store.S_STRING:
            text = p.AsString()
            info['text'] = text
            info['has_value'] = text not in (None, u'')
        elif s == store.S_DOUBLE:
            info['raw'] = p.AsDouble()
            info['has_value'] = bool(p.HasValue)
        elif s == store.S_INT:
            info['raw'] = p.AsInteger()
            info['has_value'] = bool(p.HasValue)
        elif s == store.S_ID:
            eid = p.AsElementId()
            info['raw'] = eid_value(eid)
            info['has_value'] = info['raw'] != -1
            if info['raw'] > 0:
                info['name'] = elem_name(doc.GetElement(eid))
            if not info['name']:
                info['name'] = to_text(info['vstring'])
    except Exception:
        pass
    return info


def _shown(info):
    """How a value reads in Revit, for the report."""
    if info.get('storage') == store.S_STRING:
        return to_text(info.get('text'))
    if info.get('storage') == store.S_ID:
        return to_text(info.get('name'))
    return to_text(info.get('vstring') if info.get('vstring') not in (None, u'') else info.get('raw'))


def value_text(action, payload, src_param):
    if action == u'id':
        try:
            return to_text(eid_value(src_param.AsElementId()))
        except Exception:
            return u''
    return to_text(payload)


def _apply(p, action, payload, src_param):
    if action == u'string':
        return p.Set(to_text(payload))
    if action == u'double':
        return p.Set(float(payload))
    if action == u'int':
        return p.Set(int(payload))
    if action == u'vstring':
        return p.SetValueString(to_text(payload))
    if action == u'id':
        return p.Set(src_param.AsElementId())
    return False


def _verify(doc, p, action, payload, src_param, returned):
    now = read_param(doc, p)
    if action == u'string':
        return to_text(now['text']) == to_text(payload)
    if action == u'double':
        try:
            return abs(float(now['raw']) - float(payload)) < 1e-9
        except Exception:
            return False
    if action == u'int':
        return now['raw'] == int(payload)
    if action == u'vstring':
        return bool(returned) and now['has_value']
    if action == u'id':
        return now['raw'] == eid_value(src_param.AsElementId())
    return False


def _same_id(p, src_param):
    try:
        return eid_value(p.AsElementId()) == eid_value(src_param.AsElementId())
    except Exception:
        return False


def push(doc, marriages, templates_by_id, progress=None, log=None):
    """Update Data. Plans every write first (no transaction), skips writes that
    would change nothing, borrows only what is left, then writes in chunks of
    CHUNK marriages per transaction inside one TransactionGroup - one undo.
    Every write is read back before it is counted."""
    import time as _time
    t0 = _time.time()
    log = log if log is not None else []
    rep = {'marriages': 0, 'writes': 0, 'unchanged': 0, 'failed': [],
           'skipped': [], 'empty': [], 'conflicts': [], 'refused': [], 'timing': u''}
    details = {}

    # ---- plan --------------------------------------------------------------
    plans = []
    flat = []
    for no, m in enumerate(marriages, 1):
        if not m.template_id:
            continue
        tpl = templates_by_id.get(m.template_id)
        if tpl is None:
            m.status, m.status_kind = u'Template missing', u'bad'
            rep['failed'].append((no, u'its template no longer exists'))
            continue
        src = by_uid(doc, m.src_uid)
        tgt = by_uid(doc, m.tgt_uid)
        if src is None or tgt is None:
            m.status = u'Source missing' if src is None else u'Target missing'
            m.status_kind = u'bad'
            rep['failed'].append((no, m.status.lower()))
            continue
        rep['marriages'] += 1
        writes, notes, same = [], [], 0
        lines = details.setdefault(no, [u'   template "{0}"'.format(tpl.name)])
        for mp in tpl.mappings:
            sp, _ss = find_param(doc, src, mp.src_name)
            if sp is None:
                notes.append(u'source has no "{0}"'.format(mp.src_name))
                continue
            tp, tscope = find_param(doc, tgt, mp.tgt_name, mp.tgt_scope)
            if tp is None:
                notes.append(u'target has no "{0}"'.format(mp.tgt_name))
                continue
            try:
                if tp.IsReadOnly:
                    notes.append(u'"{0}" is read-only on the target'.format(mp.tgt_name))
                    continue
            except Exception:
                pass
            sinfo = read_param(doc, sp)
            tinfo = read_param(doc, tp)
            now_text = _shown(tinfo)
            action, payload, note = store.plan_value(sinfo, _storage_of(tp), tpl.clear_empty)
            if action == u'skip':
                if not sinfo['has_value']:
                    # an empty source is left alone on purpose - information, not a fault
                    rep['empty'].append((no, mp.src_name))
                    lines.append(u'   {0} > {1}: source empty, target left as "{2}"'.format(
                        mp.src_name, mp.tgt_name, now_text))
                else:
                    notes.append(u'{0}: {1}'.format(mp.src_name, note))
                    lines.append(u'   {0} > {1}: SKIPPED - {2}'.format(mp.src_name, mp.tgt_name, note))
                continue
            if action == u'id':
                if _same_id(tp, sp):
                    same += 1
                    lines.append(u'   {0} > {1}: already "{2}"'.format(mp.src_name, mp.tgt_name, now_text))
                    continue
            elif store.already_equal(action, payload, tinfo):
                same += 1
                lines.append(u'   {0} > {1}: already "{2}"'.format(mp.src_name, mp.tgt_name, now_text))
                continue
            owner_id = tgt.Id if tscope == u'instance' else tgt.GetTypeId()
            w = {'no': no, 'owner': owner_id, 'scope': tscope, 'name': mp.tgt_name,
                 'action': action, 'payload': payload, 'src_uid': m.src_uid,
                 'src_name': mp.src_name}
            w['text'] = value_text(action, payload, sp)
            w['was'] = now_text
            lines.append(u'   {0} > {1} ({2}): "{3}" -> "{4}"'.format(
                mp.src_name, mp.tgt_name, tscope, now_text,
                sinfo.get('name') or w['text'] if action == u'id' else w['text']))
            writes.append(w)
            flat.append(w)
        rep['unchanged'] += same
        for n_ in notes:
            rep['skipped'].append((no, n_))
        plans.append((no, m, writes, notes, same))
    t_plan = _time.time()

    # ---- one value per target parameter -----------------------------------
    clashes = store.find_conflicts(
        [(eid_value(w['owner']), w['name'], w['text'], w['no']) for w in flat])
    for i in sorted(clashes):
        w = flat[i]
        w['clash'] = clashes[i]
        rep['conflicts'].append((w['no'], u'"{0}" already gets a different value from marriage {1} '
                                          u'(shared type parameter?) - left alone'.format(w['name'], clashes[i])))

    # ---- borrow only what will change -------------------------------------
    t_borrow0 = _time.time()
    owners = {}
    for w in flat:
        if 'clash' not in w:
            owners[eid_value(w['owner'])] = w['owner']
    _held, refused = borrow(doc, list(owners.values()))
    for w in flat:
        if eid_value(w['owner']) in refused and 'clash' not in w:
            w['refused'] = refused[eid_value(w['owner'])]
            rep['refused'].append((w['no'], u'"{0}" not written - element held by {1}'.format(
                w['name'], w['refused'])))

    t_borrow = _time.time()

    # ---- write ------------------------------------------------------------
    todo = [p for p in plans if any('clash' not in w and 'refused' not in w for w in p[2])]
    total = len(todo)
    done_count = 0
    results = {}
    tg = TransactionGroup(doc, u'Schematic Marriage - Update Data')
    if total:                    # nothing to change: no empty undo step in Revit
        tg.Start()
    try:
        for start in range(0, total, CHUNK):
            chunk = todo[start:start + CHUNK]
            t = Transaction(doc, u'Schematic Marriage - push')
            _quiet(t)
            t.Start()
            chunk_written = []
            try:
                for no, m, writes, notes, same in chunk:
                    ok_n, bad = 0, []
                    src_el = by_uid(doc, m.src_uid)          # once per marriage, not per write
                    for w in writes:
                        if 'clash' in w or 'refused' in w:
                            continue
                        try:
                            owner = doc.GetElement(w['owner'])
                            p = owner.LookupParameter(w['name']) if owner is not None else None
                            sp = None
                            if w['action'] == u'id':          # only an element reference needs the source param
                                sp, _s = find_param(doc, src_el, w['src_name'])
                            if p is None:
                                bad.append(u'"{0}" not found at write time'.format(w['name']))
                                continue
                            returned = _apply(p, w['action'], w['payload'], sp)
                            p2 = owner.LookupParameter(w['name'])
                            if _verify(doc, p2, w['action'], w['payload'], sp, returned):
                                ok_n += 1
                            else:
                                bad.append(u'"{0}" did not take "{1}"'.format(w['name'], w['text']))
                        except Exception as ex:
                            bad.append(u'"{0}": {1}'.format(w['name'], to_text(ex)))
                    results[no] = (ok_n, bad)
                    chunk_written.append(no)
                status = t.Commit()
                if not _committed(status):
                    for no in chunk_written:
                        results[no] = (0, [u'Revit did not commit ({0})'.format(to_text(status))])
            except Exception as ex:
                try:
                    t.RollBack()
                except Exception:
                    pass
                for no in chunk_written:
                    results[no] = (0, [u'rolled back: ' + to_text(ex)])
            done_count += len(chunk)
            if progress is not None:
                try:
                    progress(done_count, total)
                except Exception:
                    pass
        if total:
            tg.Assimilate()
    except Exception as ex:
        try:
            tg.RollBack()
        except Exception:
            pass
        log.append(u'TransactionGroup rolled back: ' + to_text(ex))
        rep['failed'].append((0, u'the whole update was rolled back: ' + to_text(ex)))
        return rep

    t_write = _time.time()

    # ---- status per marriage ---------------------------------------------
    stamp = store.now_text()[-5:]
    empty_by = {}
    for no, _name in rep['empty']:
        empty_by[no] = empty_by.get(no, 0) + 1
    for no, m, writes, notes, same in plans:
        ok_n, bad = results.get(no, (0, []))
        rep['writes'] += ok_n
        for b in bad:
            rep['failed'].append((no, b))
        extra = len([w for w in writes if 'clash' in w or 'refused' in w])
        empty = empty_by.get(no, 0)
        tail = (u', {0} source empty'.format(empty) if empty else u'') + u'  ' + stamp
        if bad or extra:
            m.status = u'{0} written, {1} need a look{2}'.format(ok_n, len(bad) + extra, tail)
            m.status_kind = u'bad'
        elif notes:
            m.status = u'{0} written, {1} skipped{2}'.format(ok_n, len(notes), tail)
            m.status_kind = u'warn'
        elif ok_n:
            m.status = u'{0} written{1}'.format(ok_n, tail)
            m.status_kind = u'ok'
        else:
            m.status = (u'Up to date' if not empty else u'Up to date, {0} source empty'.format(empty)) + u'  ' + stamp
            m.status_kind = u'ok'
        log.append(u'#{0}  {1} [{2}]  ->  {3} [{4}]   written {5}, already {6}, empty {7}, skipped {8}, failed {9}'
                   .format(no, m.src_label, m.src_eid, m.tgt_label, m.tgt_eid, ok_n, same, empty,
                           len(notes), len(bad) + extra))
        log.extend(details.get(no, []))
        for b in bad:
            log.append(u'   FAILED: ' + b)
    rep['timing'] = u'plan {0:.0f} ms, borrow {1:.0f} ms, write {2:.0f} ms ({3} transaction(s)), total {4:.0f} ms'.format(
        (t_plan - t0) * 1000, (t_borrow - t_borrow0) * 1000, (t_write - t_borrow) * 1000,
        (total + CHUNK - 1) // CHUNK if total else 0, (t_write - t0) * 1000)
    return rep


# ==========================================================================
# magenta highlights - the tool's own "temporary" overrides
# ==========================================================================
# Revit has no temporary per-element override in the API, so the tool
# records what each element's override was in that view before it paints
# it magenta, and puts exactly that back when the highlight is released
# (new pick, pick cleared, marriage added, Clear Highlights, window closed).
# The registry is keyed (view, element) and each entry carries the tags that
# hold it ('src', 'tgt', 'view'), so an element highlighted twice is only
# restored once nothing holds it, and always to its ORIGINAL override.

MAGENTA = (255, 0, 255)


def _solid_fill_id(doc):
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except Exception:
            continue
    return None


def magenta_overrides(doc):
    ogs = OverrideGraphicSettings()
    c = Color(MAGENTA[0], MAGENTA[1], MAGENTA[2])
    for name, args in (('SetProjectionLineColor', (c,)), ('SetCutLineColor', (c,)),
                       ('SetProjectionLineWeight', (6,)), ('SetCutLineWeight', (6,)),
                       ('SetSurfaceForegroundPatternColor', (c,)), ('SetCutForegroundPatternColor', (c,)),
                       ('SetSurfaceForegroundPatternVisible', (True,)), ('SetCutForegroundPatternVisible', (True,))):
        try:
            getattr(ogs, name)(*args)
        except Exception:
            pass
    solid = _solid_fill_id(doc)
    if solid is not None:
        for name in ('SetSurfaceForegroundPatternId', 'SetCutForegroundPatternId'):
            try:
                getattr(ogs, name)(solid)
            except Exception:
                pass
    return ogs


def _untouch(registry, touched, tag):
    """A highlight that did not commit leaves the registry as it was."""
    for key, is_new, had in touched:
        if is_new:
            registry.pop(key, None)
        elif not had and key in registry:
            registry[key]['tags'].discard(tag)


def highlight(doc, view, elements, registry, tag):
    """Paint elements magenta in view. -> (count painted, problem text)."""
    elements = [e for e in elements if e is not None]
    if view is None or not elements:
        return 0, u''
    _held, refused = borrow(doc, [view.Id])
    if refused:
        return 0, u'the view is held by ' + list(refused.values())[0]
    ogs = magenta_overrides(doc)
    t = Transaction(doc, u'Schematic Marriage - highlight')
    _quiet(t)
    t.Start()
    n = 0
    problem = u''
    touched = []
    try:
        for e in elements:
            key = (eid_value(view.Id), eid_value(e.Id))
            rec = registry.get(key)
            try:
                is_new = rec is None
                if is_new:
                    rec = {'view': view.Id, 'el': e.Id, 'prev': view.GetElementOverrides(e.Id), 'tags': set()}
                view.SetElementOverrides(e.Id, ogs)
                had = tag in rec['tags']
                rec['tags'].add(tag)
                registry[key] = rec
                touched.append((key, is_new, had))
                n += 1
            except Exception as ex:
                problem = to_text(ex)
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        _untouch(registry, touched, tag)
        return 0, to_text(ex)
    if not _committed(status):
        _untouch(registry, touched, tag)
        return 0, u'Revit did not commit the highlight'
    return n, problem


def release(doc, registry, tag=None):
    """Put back the overrides held by tag (every tag when None). -> count restored."""
    keys = [k for k, r in registry.items() if tag is None or tag in r['tags']]
    if not keys:
        return 0
    restore = []
    for k in keys:
        rec = registry[k]
        if tag is None:
            rec['tags'].clear()
        else:
            rec['tags'].discard(tag)
        if not rec['tags']:
            restore.append(k)
    if not restore:
        return 0
    views = {}
    for k in restore:
        views[eid_value(registry[k]['view'])] = registry[k]['view']
    borrow(doc, list(views.values()))
    t = Transaction(doc, u'Schematic Marriage - clear highlight')
    _quiet(t)
    t.Start()
    n = 0
    try:
        for k in restore:
            rec = registry.pop(k)
            try:
                v = doc.GetElement(rec['view'])
                if v is not None and doc.GetElement(rec['el']) is not None:
                    v.SetElementOverrides(rec['el'], rec['prev'])
                    n += 1
            except Exception:
                pass
        t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
    return n


def visible_in_view(doc, view, elements):
    """The elements the view actually contains."""
    try:
        ids = set(eid_value(i) for i in FilteredElementCollector(doc, view.Id)
                  .WhereElementIsNotElementType().ToElementIds())
    except Exception:
        return []
    return [e for e in elements if e is not None and eid_value(e.Id) in ids]


def marriage_elements(doc, marriages, sides=(u'src', u'tgt')):
    out, seen = [], set()
    for m in marriages:
        for side in sides:
            e = by_uid(doc, m.src_uid if side == u'src' else m.tgt_uid)
            if e is not None and eid_value(e.Id) not in seen:
                seen.add(eid_value(e.Id))
                out.append(e)
    return out


def is_model_element(e):
    try:
        return eid_value(e.OwnerViewId) <= 0
    except Exception:
        return True


# ==========================================================================
# isolate in the default 3D view
# ==========================================================================

FALLBACK_3D = u'Schematic Marriage 3D'


def find_default_3d(uiapp, doc):
    """The user's own default 3D ({3D - user} on a workshared model, {3D}
    otherwise), else the one this tool made earlier. None when neither exists."""
    user = u''
    try:
        user = to_text(uiapp.Application.Username)
    except Exception:
        pass
    found = {}
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if not v.IsTemplate:
                found[elem_name(v)] = v
        except Exception:
            continue
    for name in (u'{3D - ' + user + u'}', u'{3D}', FALLBACK_3D):
        if name in found:
            return found[name]
    return None


def _create_3d(doc):
    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if to_text(t.ViewFamily) == u'ThreeDimensional':
                vft = t
                break
        except Exception:
            continue
    v = View3D.CreateIsometric(doc, vft.Id)
    try:
        v.Name = FALLBACK_3D      # braces are not allowed in names set through the API
    except Exception:
        pass
    return v


def _union_box(elements, margin):
    lo, hi = None, None
    for e in elements:
        try:
            bb = e.get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is None:
            continue
        if lo is None:
            lo = [bb.Min.X, bb.Min.Y, bb.Min.Z]
            hi = [bb.Max.X, bb.Max.Y, bb.Max.Z]
        else:
            lo = [min(lo[0], bb.Min.X), min(lo[1], bb.Min.Y), min(lo[2], bb.Min.Z)]
            hi = [max(hi[0], bb.Max.X), max(hi[1], bb.Max.Y), max(hi[2], bb.Max.Z)]
    if lo is None:
        return None
    box = BoundingBoxXYZ()
    box.Min = XYZ(lo[0] - margin, lo[1] - margin, lo[2] - margin)
    box.Max = XYZ(hi[0] + margin, hi[1] + margin, hi[2] + margin)
    return box


def isolate_in_3d(uidoc, elements, margin_mm=500.0):
    """Open the default 3D, fit its section box round the model elements and
    temporarily isolate them (with the section box, so it stays visible).
    -> (view name, count isolated, skipped detail items)."""
    doc = uidoc.Document
    model = [e for e in elements if e is not None and is_model_element(e)]
    skipped = len([e for e in elements if e is not None]) - len(model)
    if not model:
        return None, 0, skipped
    view = find_default_3d(uidoc.Application, doc)
    if view is not None:
        _held, refused = borrow(doc, [view.Id])
        if refused:
            raise Exception(u'The default 3D view is held by ' + list(refused.values())[0])
    tg = TransactionGroup(doc, u'Schematic Marriage - isolate in 3D')
    tg.Start()
    try:
        if view is None:
            t0 = Transaction(doc, u'Schematic Marriage - 3D view')
            _quiet(t0)
            t0.Start()
            view = _create_3d(doc)
            t0.Commit()
        # reset unconditionally, in its own transaction, before isolating -
        # a leftover isolate otherwise shows through the new one
        t1 = Transaction(doc, u'Schematic Marriage - reset isolate')
        _quiet(t1)
        t1.Start()
        for mode in ('TemporaryHideIsolate', 'RevealHiddenElements'):
            try:
                view.DisableTemporaryViewMode(getattr(TemporaryViewMode, mode))
            except Exception:
                pass
        t1.Commit()
        t2 = Transaction(doc, u'Schematic Marriage - isolate')
        _quiet(t2)
        t2.Start()
        box = _union_box(model, margin_mm / 304.8)
        if box is not None:
            try:
                view.SetSectionBox(box)
                view.IsSectionBoxActive = True
            except Exception:
                pass
        doc.Regenerate()
        ids = List[ElementId]([e.Id for e in model])
        try:
            cat_filter = ElementCategoryFilter(getattr(BuiltInCategory, 'OST_SectionBox'))
            for d in view.GetDependentElements(cat_filter):
                ids.Add(d)
        except Exception:
            pass
        view.IsolateElementsTemporary(ids)
        t2.Commit()
        tg.Assimilate()
    except Exception:
        try:
            tg.RollBack()
        except Exception:
            pass
        raise
    try:
        uidoc.ActiveView = view
    except Exception:
        uidoc.RequestViewChange(view)
    try:
        for uv in uidoc.GetOpenUIViews():
            if eid_value(uv.ViewId) == eid_value(view.Id):
                uv.ZoomToFit()
    except Exception:
        pass
    return elem_name(view), len(model), skipped
