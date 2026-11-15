# -*- coding: utf-8 -*-
"""Family Param - Replace: swap family parameters for shared ones and keep what
the project held. A swapped parameter is a different parameter to Revit, so
instance values do not follow it through a reload. The order is what keeps them:

  1. read every value in the project, and save a copy to disk
  2. borrow the family, its types and everything holding a value
  3. EditFamily, ReplaceParameter (keeps formulas and labels), all or nothing
  4. LoadFamily, which refuses while a transaction is open on the project
  5. write the values to the new parameter, read them back after the group closes
"""
import fpp_clr  # noqa: F401  (must stay first)
import os
import time

from Autodesk.Revit.DB import (FamilySource, IFamilyLoadOptions, Transaction,
                               TransactionGroup)

import fpp_core
from fpp_core import (BATCH_SIZE, ParamRef, ProgressMeter, SharedRef, Write,
                      holds, new_replace_report, tally, to_text)
from fpp_revit import (QuietFailures, apply_batch, checkout, eid_value,
                       elem_label, find_param, instances_of, prove, snapshot,
                       spec_of)


class LoadOptions(IFamilyLoadOptions):
    """IronPython hands the out parameters in as references: set `.Value`."""
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source,
                            overwriteParameterValues):
        source.Value = FamilySource.Project   # nested families stay as they are
        overwriteParameterValues.Value = False
        return True


# ===================== reading =====================

def read_shared(app):
    """(file path, definitions) from the shared parameter file set in Revit."""
    path = to_text(app.SharedParametersFilename)
    try:
        opened = app.OpenSharedParameterFile()
    except Exception:
        opened = None
    if opened is None:
        return path, []
    out = []
    for group in opened.Groups:
        for definition in group.Definitions:
            out.append(SharedRef(definition.Name, group.Name,
                                 definition.GetDataType().TypeId,
                                 definition.GUID))
    out.sort(key=lambda r: fpp_core.natural_key(r.name))
    return path, out


def shared_definitions(app):
    opened = app.OpenSharedParameterFile()
    out = {}
    if opened is None:
        return out
    for group in opened.Groups:
        for definition in group.Definitions:
            out[to_text(definition.GUID).lower()] = definition
    return out


def family_ref(param):
    """A built-in parameter cannot be replaced, so it is not offered."""
    if eid_value(param.Id) < 0:
        return None
    guid = to_text(param.GUID) if param.IsShared else None
    spec = spec_of(param)
    ref = ParamRef(param.Definition.Name, 'I' if param.IsInstance else 'T',
                   to_text(param.StorageType), spec, 'bool' in spec.lower(),
                   guid)
    if param.IsDeterminedByFormula:
        ref.locked = True
        ref.sample = u'Formula'
    elif param.IsReporting:
        ref.locked = True
        ref.sample = u'Reporting'
    return ref


def read_family_params(doc, pick):
    """EditFamily hands back an independent copy; closing it unsaved changes
    nothing in the project."""
    family = doc.GetElement(pick.fam.family_id)
    famdoc = doc.EditFamily(family)
    try:
        refs = [family_ref(p) for p in famdoc.FamilyManager.Parameters]
    finally:
        famdoc.Close(False)
    return sorted([r for r in refs if r is not None],
                  key=lambda r: fpp_core.natural_key(r.name))


# ===================== keeping the values =====================

def new_ref(mapping):
    src, tgt = mapping.src, mapping.tgt
    return ParamRef(tgt.name, src.scope, src.storage, tgt.spec, src.yesno,
                    tgt.guid)


def capture(doc, pick, rep):
    """Everything to write back, read before anything changes. A blank text
    value is kept too, or the family's default would appear on those elements.
    Returns (writes, backup lines)."""
    instances = instances_of(doc, pick)
    writes, lines = [], []
    for typ in pick.fam.types:
        elem = doc.GetElement(typ.eid)
        if elem is None:
            continue
        placed = instances.get(typ.idv, [])
        for mapping in pick.maps:
            if mapping.src.locked:
                continue
            ref = new_ref(mapping)
            owners = [elem] if mapping.src.scope == 'T' else placed
            for owner in owners:
                param = find_param(owner, mapping.src)
                if param is None:
                    tally(rep['no_source'], mapping.src.name)
                    continue
                value = snapshot(doc, param)
                if value.empty and value.storage != u'String':
                    rep['empty'] += 1
                    continue
                idv = eid_value(owner.Id)
                label = elem_label(pick.fam.name, typ.name, idv)
                writes.append(Write(owner.Id, idv, ref, u'set', value.raw,
                                    label, False))
                lines.append(u'{0}\t{1}\t{2}\t{3}\t{4}'.format(
                    to_text(owner.UniqueId), idv, mapping.src.name, ref.name,
                    value.text))
    return writes, lines


def write_backup(name, lines):
    """If anything goes wrong after the swap, this file still has the values."""
    stamp = time.strftime('%Y%m%d_%H%M%S')
    path = os.path.join(fpp_core.backup_dir(), u'{0}_{1}.txt'.format(
        fpp_core.safe_name(name), stamp))
    head = u'UniqueId\tElementId\tOld parameter\tNew parameter\tValue'
    if fpp_core.write_text(path, u'\n'.join([head] + lines)):
        return path
    return None


# ===================== swapping =====================

def swap_parameters(famdoc, pick, definitions):
    """All or nothing. Returns the count swapped; raises with Revit's words."""
    manager = famdoc.FamilyManager
    failures = QuietFailures()
    trans = Transaction(famdoc, u'Family Param - Replace')
    options = trans.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(failures)
    trans.SetFailureHandlingOptions(options)
    trans.Start()
    try:
        for mapping in pick.maps:
            current = None
            for param in manager.Parameters:
                if to_text(param.Definition.Name) == mapping.src.name \
                        and bool(param.IsInstance) == (mapping.src.scope == 'I'):
                    current = param
                    break
            if current is None:
                raise ValueError(u'{0} is no longer in the family'
                                 .format(mapping.src.name))
            definition = definitions.get(mapping.tgt.guid)
            if definition is None:
                raise ValueError(u'{0} is no longer in the shared parameter '
                                 u'file'.format(mapping.tgt.name))
            manager.ReplaceParameter(current, definition,
                                     current.Definition.GetGroupTypeId(),
                                     current.IsInstance)
        status = trans.Commit()
    except Exception:
        if trans.HasStarted() and not trans.HasEnded():
            trans.RollBack()
        raise
    if to_text(status) != u'Committed':
        raise ValueError(u' '.join(failures.errors)
                         or u'Revit rolled the family change back')
    return len(pick.maps)


def load_family(doc, famdoc, state):
    """One undo step if Revit allows the load inside a group; if it refuses,
    the run carries on without one."""
    group = None
    if state['group']:
        group = TransactionGroup(doc, u'Family Param - Replace')
        group.Start()
    try:
        loaded = famdoc.LoadFamily(doc, LoadOptions())
    except Exception:
        if group is None:
            raise
        group.RollBack()
        state['group'] = False
        return load_family(doc, famdoc, state)
    if loaded is None:
        if group is not None:
            group.RollBack()
        raise ValueError(u'Revit did not load the family back')
    return group


def restore(doc, writes, rep):
    pending = []
    for write in writes:
        elem = doc.GetElement(write.eid)
        param = find_param(elem, write.ref) if elem is not None else None
        if param is None:
            tally(rep['no_target'], write.ref.name)
        elif param.IsReadOnly:
            tally(rep['read_only'], write.ref.name)
        elif holds(snapshot(doc, param), write.mode, write.value, eid_value):
            rep['already'] += 1
        else:
            pending.append(write)
    for start in range(0, len(pending), BATCH_SIZE):
        apply_batch(doc, pending[start:start + BATCH_SIZE], rep)
    return pending


def replace_family(doc, pick, definitions, state, rep):
    name = pick.fam.name
    writes, lines = capture(doc, pick, rep)
    path = write_backup(name, lines)
    if path:
        rep['backups'].append(path)
    if doc.IsWorkshared:
        wanted = {eid_value(pick.fam.family_id): pick.fam.family_id}
        for typ in pick.fam.types:
            wanted[typ.idv] = typ.eid
        for write in writes:
            wanted[write.idv] = write.eid
        held = checkout(doc, wanted)
        if held:
            rep['failed'].append(u'{0}: {1} element(s) held, first by {2}'
                                 .format(name, len(held), held[0][1]))
            return
    famdoc = doc.EditFamily(doc.GetElement(pick.fam.family_id))
    try:
        try:
            count = swap_parameters(famdoc, pick, definitions)
        except Exception as err:
            rep['failed'].append(u'{0}: {1}'.format(name, to_text(err)))
            return
        group = load_family(doc, famdoc, state)
    finally:
        famdoc.Close(False)
    rep['swapped'] += count
    try:
        pending = restore(doc, writes, rep)
        if group is not None:
            group.Assimilate()
    except Exception:
        if group is not None and group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    prove(doc, pending, rep)
    rep['done'].append(pick.fam.key)


def run_replace(doc, app, picks, progress=None):
    rep = new_replace_report()
    definitions = shared_definitions(app)
    state = {'group': True}
    ready = picks.ready()
    meter = ProgressMeter(progress)
    for index, pick in enumerate(ready):
        meter.report(index, len(ready), pick.fam.name)
        try:
            replace_family(doc, pick, definitions, state, rep)
        except Exception as err:
            rep['failed'].append(u'{0}: {1}'.format(pick.fam.name,
                                                    to_text(err)))
    return rep
