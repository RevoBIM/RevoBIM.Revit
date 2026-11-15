# -*- coding: utf-8 -*-
"""Family Param Push: everything that talks to the Revit API. Reads the
families, discovers parameters, plans a push with no transaction open, borrows
what will change, writes in batches inside one undo step and proves every value
by reading it back after the group has closed."""
import fpp_clr  # noqa: F401  (must stay first)
from System import Guid
from System.Collections.Generic import List
from Autodesk.Revit.DB import (ElementId, Element, FilteredElementCollector,
                               IFailuresPreprocessor, SubTransaction,
                               Transaction, TransactionGroup, WorksharingUtils)
from fpp_core import (BATCH_SIZE, PARAM_SAMPLE_MAX, PARAM_SAMPLE_PER_TYPE,
                      FamilyRec, ParamRef, Plan, ProgressMeter, TypeRec, Value,
                      Write, holds, new_report, plan_value, sort_families,
                      tally, to_text)

SKIP_CLASSES = ('GroupType', 'RevitLinkType', 'CADLinkType', 'ImageType',
                'ViewFamilyType', 'AssemblyType')
CATEGORY_KINDS = ('Model', 'Annotation')


def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return getattr(element_id, 'Integer' + 'Value')
    except Exception:
        return 0


def elem_name(elem):
    try:
        return to_text(elem.Name)
    except Exception:
        pass
    try:
        return to_text(Element.Name.GetValue(elem))
    except Exception:
        return u''


def family_name(elem_type):
    try:
        name = elem_type.FamilyName
        if name:
            return to_text(name)
    except Exception:
        pass
    try:
        return to_text(elem_type.Family.Name)
    except Exception:
        return u''


def read_model(doc, progress=None):
    """Every family with its types, and how many of each are placed."""
    counts = {}
    for elem in FilteredElementCollector(doc).WhereElementIsNotElementType():
        idv = eid_value(elem.GetTypeId())
        if idv > 0:
            counts[idv] = counts.get(idv, 0) + 1
    families = {}
    for typ in FilteredElementCollector(doc).WhereElementIsElementType():
        try:
            if typ.GetType().Name in SKIP_CLASSES:
                continue
            cat = typ.Category
            if cat is None or to_text(cat.CategoryType) not in CATEGORY_KINDS:
                continue
            fname = family_name(typ)
            if not fname:
                continue
            cname = to_text(cat.Name)
            key = u'{0}|{1}'.format(cname, fname)
            fam = families.get(key)
            if fam is None:
                fam = FamilyRec(fname, cname, cat.Id)
                families[key] = fam
                family = getattr(typ, 'Family', None)
                if family is not None:
                    fam.family_id = family.Id
                    fam.editable = bool(family.IsEditable) \
                        and not bool(family.IsInPlace)
            idv = eid_value(typ.Id)
            fam.types.append(TypeRec(idv, typ.Id, elem_name(typ),
                                     counts.get(idv, 0)))
        except Exception:
            continue
    return sort_families(list(families.values()))


def instances_of(doc, pick):
    """Fresh at every use, so a model that moved on is not pushed stale."""
    out = {}
    collector = FilteredElementCollector(doc).OfCategoryId(pick.fam.cat_id) \
        .WhereElementIsNotElementType()
    for elem in collector:
        idv = eid_value(elem.GetTypeId())
        if idv in pick.type_ids:
            out.setdefault(idv, []).append(elem)
    return out


# ===================== parameters =====================

def spec_of(param):
    try:
        return to_text(param.Definition.GetDataType().TypeId)
    except Exception:
        return u''


def bip_of(param):
    try:
        bip = param.Definition.BuiltInParameter
        if int(bip) == -1:
            return None
        return bip
    except Exception:
        return None


def snapshot(doc, param):
    storage = to_text(param.StorageType)
    if storage == u'String':
        raw = param.AsString() or u''
        return Value(storage, raw, raw, raw == u'')
    if not param.HasValue:
        return Value(storage, None, u'', True)
    if storage == u'Double':
        raw = param.AsDouble()
        return Value(storage, raw, param.AsValueString() or to_text(raw))
    if storage == u'Integer':
        raw = param.AsInteger()
        return Value(storage, raw, param.AsValueString() or to_text(raw))
    if storage == u'ElementId':
        raw = param.AsElementId()
        if eid_value(raw) <= 0:
            return Value(storage, raw, param.AsValueString() or u'', True)
        target = doc.GetElement(raw)
        text = elem_name(target) if target is not None else u''
        return Value(storage, raw, text or param.AsValueString() or u'')
    return Value(storage, None, u'', True)


def make_ref(doc, param, scope):
    try:
        guid = to_text(param.GUID) if param.IsShared else None
    except Exception:
        guid = None
    spec = spec_of(param)
    return ParamRef(param.Definition.Name, scope, to_text(param.StorageType),
                    spec, 'bool' in spec.lower(), guid, bip_of(param),
                    not param.IsReadOnly, snapshot(doc, param).text)


def discover_params(doc, pick):
    """Instance parameters from a sample of what is placed, type parameters
    from the picked types. A parameter is writable if any sample allows it."""
    found = {}
    def harvest(elem, scope):
        for param in elem.Parameters:
            try:
                if to_text(param.StorageType) == u'None':
                    continue
                ref = make_ref(doc, param, scope)
            except Exception:
                continue
            have = found.get(ref.key)
            if have is None:
                found[ref.key] = ref
            else:
                have.writable = have.writable or ref.writable
                if not have.sample:
                    have.sample = ref.sample
    instances = instances_of(doc, pick)
    taken = 0
    for typ in pick.fam.types:
        if typ.idv not in pick.type_ids:
            continue
        elem = doc.GetElement(typ.eid)
        if elem is not None:
            harvest(elem, 'T')
        for inst in instances.get(typ.idv, [])[:PARAM_SAMPLE_PER_TYPE]:
            if taken >= PARAM_SAMPLE_MAX:
                break
            harvest(inst, 'I')
            taken += 1
    return list(found.values())


def find_param(elem, ref):
    """The same parameter on any element: by GUID, built-in, then name."""
    try:
        if ref.guid:
            found = elem.get_Parameter(Guid(ref.guid))
            if found is not None:
                return found
        if ref.bip is not None:
            found = elem.get_Parameter(ref.bip)
            if found is not None:
                return found
        return elem.LookupParameter(ref.name)
    except Exception:
        return None


# ===================== planning =====================

def elem_label(fam_name, type_name, idv):
    return u'{0} : {1} [{2}]'.format(fam_name, type_name, idv)


def plan_one(doc, plan, rep, source, target, mapping, clear_empty, label):
    src, tgt = mapping.src, mapping.tgt
    source_param = find_param(source, src)
    if source_param is None:
        tally(rep['no_source'], src.name)
        return
    target_param = find_param(target, tgt)
    if target_param is None:
        tally(rep['no_target'], tgt.name)
        return
    if target_param.IsReadOnly:
        tally(rep['read_only'], tgt.name)
        return
    value = snapshot(doc, source_param)
    tgt_storage = to_text(target_param.StorageType)
    mode, payload = plan_value(value, tgt_storage, src.spec == tgt.spec,
                               clear_empty)
    if mode == u'empty':
        rep['empty'] += 1
        return
    if mode == u'refused':
        rep['refused'].append(u'{0}, {1}: {2}'.format(label, tgt.name, payload))
        return
    already = holds(snapshot(doc, target_param), mode, payload, eid_value)
    idv = eid_value(target.Id)
    state = plan.add(Write(target.Id, idv, tgt, mode, payload, label, already))
    if state == u'conflict':
        rep['conflicts'].append(
            u'{0}, {1}: elements disagree, kept the first value'
            .format(label, tgt.name))


def plan_mapping(doc, plan, rep, type_elem, instances, mapping, clear_empty,
                 fam_name, type_name):
    src, tgt = mapping.src, mapping.tgt
    label = elem_label(fam_name, type_name, eid_value(type_elem.Id))
    if src.scope == 'T' and tgt.scope == 'T':
        plan_one(doc, plan, rep, type_elem, type_elem, mapping, clear_empty,
                 label)
        return
    if not instances:
        rep['no_elements'].append(u'{0} ({1})'.format(label, tgt.name))
        return
    for inst in instances:
        source = type_elem if src.scope == 'T' else inst
        target = type_elem if tgt.scope == 'T' else inst
        plan_one(doc, plan, rep, source, target, mapping, clear_empty,
                 elem_label(fam_name, type_name, eid_value(inst.Id)))


def build_plan(doc, picks, clear_empty, progress=None):
    plan = Plan()
    rep = new_report()
    ready = picks.ready()
    meter = ProgressMeter(progress)
    for index, pick in enumerate(ready):
        meter.report(index, len(ready), pick.fam.name)
        instances = instances_of(doc, pick)
        for typ in pick.fam.types:
            if typ.idv not in pick.type_ids:
                continue
            elem = doc.GetElement(typ.eid)
            if elem is None:
                rep['refused'].append(u'{0} : {1} is no longer in the model'
                                      .format(pick.fam.name, typ.name))
                continue
            for mapping in pick.mappings:
                plan_mapping(doc, plan, rep, elem,
                             instances.get(typ.idv, []), mapping, clear_empty,
                             pick.fam.name, typ.name)
    rep['already'] = plan.already()
    return plan, rep


# ===================== writing =====================

class QuietFailures(IFailuresPreprocessor):
    """Warnings are deleted. Errors roll the transaction back and are kept so
    the report can give Revit's own words."""
    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, accessor):
        from Autodesk.Revit.DB import FailureProcessingResult
        failed = False
        for message in accessor.GetFailureMessages():
            if to_text(message.GetSeverity()) == u'Warning':
                accessor.DeleteWarning(message)
            else:
                failed = True
                self.errors.append(to_text(message.GetDescriptionText()))
        if failed:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def borrow(doc, writes, rep):
    """On a workshared model a write to an unborrowed element writes nothing
    and says nothing, so what cannot be borrowed is taken out and named."""
    if not doc.IsWorkshared:
        return writes
    wanted = {}
    for write in writes:
        wanted[write.idv] = write.eid
    held = checkout(doc, wanted)
    for idv, owner in held:
        rep['held'].append(u'element {0} ({1})'.format(idv, owner))
    missing = set([idv for idv, _owner in held])
    return [w for w in writes if w.idv not in missing]


def checkout(doc, wanted):
    """wanted is {id value: ElementId}. Returns [(id value, owner)] for what
    could not be borrowed."""
    ids = List[ElementId]()
    for eid in wanted.values():
        ids.Add(eid)
    got = set()
    for eid in WorksharingUtils.CheckoutElements(doc, ids):
        got.add(eid_value(eid))
    out = []
    for idv in sorted(set(wanted) - got):
        owner = u'someone else'
        try:
            info = WorksharingUtils.GetWorksharingTooltipInfo(doc, wanted[idv])
            owner = to_text(info.Owner) or owner
        except Exception:
            pass
        out.append((idv, owner))
    return out


def write_one(doc, write):
    elem = doc.GetElement(write.eid)
    param = find_param(elem, write.ref) if elem is not None else None
    if param is None:
        return False
    if write.mode == u'text':
        for candidate in write.value:
            try:
                if param.SetValueString(candidate):
                    return True
            except Exception:
                continue
        return False
    return bool(param.Set(write.value))


def run_batch(doc, batch, rep):
    """True when Revit committed. A refused Set in a batch does not stop the
    others: each write has its own sub-transaction."""
    failures = QuietFailures()
    trans = Transaction(doc, u'Family Param Push')
    options = trans.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(failures)
    options.SetClearAfterRollback(True)
    trans.SetFailureHandlingOptions(options)
    trans.Start()
    try:
        for write in batch:
            sub = SubTransaction(doc)
            sub.Start()
            try:
                done = write_one(doc, write)
            except Exception:
                done = False
            if done:
                sub.Commit()
            else:
                sub.RollBack()
                rep['refused'].append(u'{0}, {1}: Revit refused the value'
                                      .format(write.label, write.ref.name))
                write.refused = True
        status = trans.Commit()
    except Exception as err:
        if trans.HasStarted() and not trans.HasEnded():
            trans.RollBack()
        failures.errors.append(to_text(err))
        return False, failures.errors
    return to_text(status) == u'Committed', failures.errors


def apply_batch(doc, batch, rep):
    done, errors = run_batch(doc, batch, rep)
    if done:
        return
    for write in batch:
        write.refused = False
    # refused notes from the rolled back attempt are redone by the retries
    labels = [u'{0}, {1}: Revit refused the value'.format(w.label, w.ref.name)
              for w in batch]
    rep['refused'] = [line for line in rep['refused'] if line not in labels]
    if len(batch) == 1:
        batch[0].refused = True
        rep['refused'].append(u'{0}, {1}: {2}'.format(
            batch[0].label, batch[0].ref.name,
            u' '.join(errors) or u'Revit rolled the change back'))
        return
    middle = len(batch) // 2
    apply_batch(doc, batch[:middle], rep)
    apply_batch(doc, batch[middle:], rep)


def prove(doc, writes, rep):
    """Read after the group has closed: the count is what stuck, not what was
    accepted. Commit regenerates, and a value can move there."""
    changed = set()
    for write in writes:
        if write.refused:
            continue
        elem = doc.GetElement(write.eid)
        param = find_param(elem, write.ref) if elem is not None else None
        if param is not None and holds(snapshot(doc, param), write.mode,
                                       write.value, eid_value):
            rep['written'] += 1
            changed.add(write.idv)
        else:
            rep['refused'].append(u'{0}, {1}: the value did not stick'
                                  .format(write.label, write.ref.name))
    rep['elements'] += len(changed)


def run_push(doc, picks, clear_empty, progress=None):
    plan, rep = build_plan(doc, picks, clear_empty, progress)
    writes = borrow(doc, plan.pending(), rep)
    if not writes:
        return rep                          # no empty undo step
    meter = ProgressMeter(progress)
    group = TransactionGroup(doc, u'Family Param Push')
    group.Start()
    try:
        for start in range(0, len(writes), BATCH_SIZE):
            meter.report(start, len(writes), u'Writing')
            apply_batch(doc, writes[start:start + BATCH_SIZE], rep)
        group.Assimilate()
    except Exception:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    prove(doc, writes, rep)
    return rep
