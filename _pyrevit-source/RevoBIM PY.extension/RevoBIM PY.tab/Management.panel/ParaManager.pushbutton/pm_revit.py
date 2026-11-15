# -*- coding: utf-8 -*-
"""Everything that touches the Revit API."""
import pm_clr
import os
import tempfile
import traceback

from System import Action
from System.Collections.Generic import List
from System.Windows.Threading import DispatcherTimer
from System import TimeSpan
from Autodesk.Revit.DB import (
    ElementId, ExternalDefinitionCreationOptions, FailureProcessingResult,
    FailureSeverity, FilteredElementCollector, ForgeTypeId, IFailuresPreprocessor,
    InstanceBinding, LabelUtils, ParameterUtils, SharedParameterElement, SpecUtils,
    SubTransaction, Transaction, UnitUtils, WorksharingUtils,
)
from Autodesk.Revit.DB import Category as RevitCategory
from Autodesk.Revit.UI import ExternalEvent, ExternalEventRequest, IExternalEventHandler

import pm_core as core

OTHER_GROUP = u'Other'
TEMP_GROUP = u'ParaManager'


def _label(call, value, fallback=u''):
    try:
        return call(value)
    except Exception:
        return fallback


def _cat_label(cat):
    parent = None
    try:
        parent = cat.Parent
    except Exception:
        pass
    return u'{0} | {1}'.format(parent.Name, cat.Name) if parent is not None else cat.Name


def read_categories(doc):
    """{label: Category} for everything that can carry a project parameter."""
    found = {}
    for cat in doc.Settings.Categories:
        try:
            if cat.AllowsBoundParameters:
                found[_cat_label(cat)] = cat
            for sub in cat.SubCategories:
                if sub.AllowsBoundParameters:
                    found[_cat_label(sub)] = sub
        except Exception:
            continue
    return found


def read_groups():
    """{label: ForgeTypeId} for Group Under."""
    groups = {OTHER_GROUP: ForgeTypeId(u'')}
    for gid in ParameterUtils.GetAllBuiltInGroups():
        label = _label(LabelUtils.GetLabelForGroup, gid)
        if label:
            groups[label] = gid
    return groups


def spec_discipline(spec):
    try:
        if UnitUtils.IsMeasurableSpec(spec):
            return _label(LabelUtils.GetLabelForDiscipline, UnitUtils.GetDiscipline(spec), u'Common')
    except Exception:
        pass
    return u'Common'


def spec_label(spec):
    try:
        if RevitCategory.IsBuiltInCategory(spec):
            return u'Family Type: {0}'.format(
                LabelUtils.GetLabelFor(RevitCategory.GetBuiltInCategory(spec)))
    except Exception:
        pass
    return _label(LabelUtils.GetLabelForSpec, spec, u'Text')


def read_specs():
    """{discipline: {label: spec}} for typing a new parameter in."""
    specs = {}
    for spec in SpecUtils.GetAllSpecs():
        label = spec_label(spec)
        if label:
            specs.setdefault(spec_discipline(spec), {})[label] = spec
    return specs


def read_project(doc):
    data = {'recs': [], 'cats': read_categories(doc), 'groups': read_groups(),
            'specs': read_specs()}
    binding_map = doc.ParameterBindings
    walker = binding_map.ForwardIterator()
    walker.Reset()
    rid = 0
    while walker.MoveNext():
        defn = walker.Key
        binding = walker.Current
        rid += 1
        try:
            rec = _read_binding(doc, data, rid, defn, binding)
            data['recs'].append(rec)
        except Exception:
            core.log(u'Could not read a parameter:\n' + traceback.format_exc())
    data['recs'].sort(key=lambda r: core.natural_key(r.name))
    return data


def _read_binding(doc, data, rid, defn, binding):
    element = doc.GetElement(defn.Id)
    shared = isinstance(element, SharedParameterElement)
    spec = defn.GetDataType()
    labels = []
    for cat in binding.Categories:
        label = _cat_label(cat)
        data['cats'].setdefault(label, cat)
        labels.append(label)
    group = _label(LabelUtils.GetLabelForGroup, defn.GetGroupTypeId(), OTHER_GROUP) or OTHER_GROUP
    data['groups'].setdefault(group, defn.GetGroupTypeId())
    disc = spec_discipline(spec)
    ptype = spec_label(spec)
    data['specs'].setdefault(disc, {}).setdefault(ptype, spec)
    return core.Rec(rid, defn.Name, core.KIND_SHARED if shared else core.KIND_PROJECT, disc,
                    ptype, group, core.INSTANCE if isinstance(binding, InstanceBinding) else core.TYPE,
                    labels, guid=u'{0}'.format(element.GuidValue) if shared else u'',
                    handle=defn)


class Swallow(IFailuresPreprocessor):
    """Warnings are deleted. Errors are kept, in Revit's own words, for the report."""

    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, accessor):
        for message in accessor.GetFailureMessages():
            if message.GetSeverity() == FailureSeverity.Warning:
                accessor.DeleteWarning(message)
            else:
                self.errors.append(message.GetDescriptionText())
        return FailureProcessingResult.Continue


def _binding_for(doc, rec, cats):
    app = doc.Application
    category_set = app.Create.NewCategorySet()
    for label in sorted(rec.cats):
        if label in cats:
            category_set.Insert(cats[label])
    if rec.scope == core.INSTANCE:
        return app.Create.NewInstanceBinding(category_set)
    return app.Create.NewTypeBinding(category_set)


def _external_definitions(app, plan, specs):
    """{rid: ExternalDefinition}. The file Revit points at is always put back."""
    found = {}
    errors = {}
    original = app.SharedParametersFilename
    folder = tempfile.mkdtemp(prefix='parama')
    temp = os.path.join(folder, 'new_parameters.txt')
    try:
        with open(temp, 'w'):
            pass
        for rec in plan['create']:
            try:
                if rec.source == u'file':
                    app.SharedParametersFilename = rec.sp_path
                    found[rec.rid] = _find_definition(app.OpenSharedParameterFile(), rec.guid)
                else:
                    app.SharedParametersFilename = temp
                    opened = app.OpenSharedParameterFile()
                    group = opened.Groups.get_Item(TEMP_GROUP) or opened.Groups.Create(TEMP_GROUP)
                    options = ExternalDefinitionCreationOptions(rec.name, specs[rec.disc][rec.ptype])
                    found[rec.rid] = group.Definitions.Create(options)
                if found[rec.rid] is None:
                    errors[rec.rid] = u'not found in its shared parameter file'
            except Exception as error:
                errors[rec.rid] = core.to_text(error)
    finally:
        app.SharedParametersFilename = original or u''
        try:
            os.remove(temp)
            os.rmdir(folder)
        except Exception:
            pass
    return found, errors


def _find_definition(opened, guid):
    wanted = guid.lower()
    for group in opened.Groups:
        for defn in group.Definitions:
            if u'{0}'.format(defn.GUID).lower() == wanted:
                return defn
    return None


def _borrow(doc, plan):
    """Workshared: take the parameter elements first. Anything held elsewhere is refused below."""
    if not doc.IsWorkshared:
        return
    ids = List[ElementId]()
    for rec in plan['delete'] + plan['modify']:
        ids.Add(rec.handle.Id)
    if ids.Count:
        try:
            WorksharingUtils.CheckoutElements(doc, ids)
        except Exception as error:
            core.log(u'Borrow failed: {0}'.format(error))


def _one(doc, step, name, failed):
    sub = SubTransaction(doc)
    sub.Start()
    try:
        ok = step()
        if ok is False:
            raise ValueError(u'Revit refused the change')
        sub.Commit()
        return True
    except Exception as error:
        try:
            sub.RollBack()
        except Exception:
            pass
        failed.append((name, core.to_text(error)))
        return False


def apply_plan(doc, plan, data, progress=None):
    """Delete, create, change, in one undo step. Counts come from reading the model back."""
    cats = data['cats']
    groups = data['groups']
    failed = []
    external, bad = _external_definitions(doc.Application, plan, data['specs'])
    for rec in plan['create']:
        if rec.rid in bad:
            failed.append((rec.name, bad[rec.rid]))
    _borrow(doc, plan)
    total = max(1, len(plan['delete']) + len(plan['create']) + len(plan['modify']))
    done = [0]

    def tick():
        done[0] += 1
        if progress:
            progress(done[0], total)

    swallow = Swallow()
    tx = Transaction(doc, 'ParaManager')
    options = tx.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(swallow)
    options.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(options)
    tx.Start()
    bindings = doc.ParameterBindings
    for rec in plan['delete']:
        _one(doc, lambda r=rec: doc.Delete(r.handle.Id) is not None, rec.name, failed)
        tick()
    for rec in plan['create']:
        if rec.rid in external:
            _one(doc, lambda r=rec: bindings.Insert(external[r.rid], _binding_for(doc, r, cats),
                                                    groups[r.group]), rec.name, failed)
        tick()
    for rec in plan['modify']:
        if rec.needs_rebind():
            _one(doc, lambda r=rec: bindings.ReInsert(r.handle, _binding_for(doc, r, cats),
                                                      groups[r.group]), rec.name, failed)
        else:
            _one(doc, lambda r=rec: r.handle.SetGroupTypeId(groups[r.group]), rec.name, failed)
        tick()
    status = tx.Commit()
    if core.to_text(status) != u'Committed':
        failed.append((u'Revit', u'the transaction did not commit: {0}'.format(status)))
    for text in swallow.errors:
        failed.append((u'Revit', text))
    return verify(doc, plan, failed)


def verify(doc, plan, failed):
    """A void API call is not evidence: compare the model against the plan after commit."""
    fresh = read_project(doc)
    current = dict((r.name, r) for r in fresh['recs'])
    refused = set(name for name, _reason in failed)
    landed = 0
    for rec in plan['delete']:
        if rec.name not in current:
            landed += 1
        elif rec.name not in refused:
            failed.append((rec.name, u'still in the project after the delete'))
    for rec in plan['create'] + plan['modify']:
        found = current.get(rec.name)
        if found is None:
            if rec.name not in refused:
                failed.append((rec.name, u'not found after the change'))
        elif (found.group, found.scope, found.cats) == (rec.group, rec.scope, rec.cats):
            landed += 1
        elif rec.name not in refused:
            failed.append((rec.name, u'reads back differently: {0}, {1}'.format(
                found.group, found.scope)))
    return {'landed': landed, 'failed': failed}


class _Handler(IExternalEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        self.runner.run(uiapp)

    def GetName(self):
        return 'ParaManager'


class Runner(object):
    """All writes go through here. Pending keeps the job, only a refusal drops it."""

    def __init__(self, dispatcher, on_stuck):
        self.queue = []
        self.dispatcher = dispatcher
        self.on_stuck = on_stuck
        self.handler = _Handler(self)
        self.event = ExternalEvent.Create(self.handler)
        self.dog = DispatcherTimer()
        self.dog.Interval = TimeSpan.FromSeconds(20)
        self.dog.Tick += self._barked

    def submit(self, job, callback):
        entry = (job, callback)
        self.queue.append(entry)
        status = self.event.Raise()
        if status in (ExternalEventRequest.Accepted, ExternalEventRequest.Pending):
            self.dog.Start()
            return True
        self.queue.remove(entry)
        return False

    def _barked(self, sender, args):
        self.dog.Stop()
        self.on_stuck()

    def run(self, uiapp):
        self.dog.Stop()
        while self.queue:
            job, callback = self.queue.pop(0)
            try:
                result = job(uiapp)
            except Exception:
                result = {'landed': 0, 'failed': [(u'ParaManager', traceback.format_exc())]}
            self.dispatcher.BeginInvoke(Action(lambda c=callback, r=result: c(r)))
