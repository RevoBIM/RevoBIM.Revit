# -*- coding: utf-8 -*-
"""Reading the selection, and the write. Every model change is in apply_job."""
import brn_clr  # noqa: F401  must stay first
import brn_core as core

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    BuiltInParameter, CADLinkType, Element, ElementId, ElementType, Family,
    FilteredElementCollector, IFailuresPreprocessor, FailureProcessingResult,
    RevitLinkType, SubTransaction, Transaction, TransactionGroup, View,
    ViewSheet,
    WorksharingUtils,
)
from Autodesk.Revit.UI import IExternalEventHandler

VIEW_LABELS = {
    'FloorPlan': u'Floor plan', 'CeilingPlan': u'Ceiling plan',
    'EngineeringPlan': u'Structural plan', 'AreaPlan': u'Area plan',
    'Section': u'Section', 'Detail': u'Detail', 'Elevation': u'Elevation',
    'ThreeD': u'3D view', 'Walkthrough': u'Walkthrough',
    'DraftingView': u'Drafting view', 'Legend': u'Legend',
    'Schedule': u'Schedule', 'ColumnSchedule': u'Schedule',
    'PanelSchedule': u'Panel schedule', 'Rendering': u'Rendering',
    'Report': u'Report', 'CostReport': u'Report',
}


def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def read_name(element):
    try:
        return core.to_text(element.Name)
    except Exception:
        pass
    try:
        return core.to_text(Element.Name.GetValue(element))
    except Exception:
        return u''


def _type_scope(element):
    try:
        family = element.FamilyName
    except Exception:
        family = u''
    return u'type:{0}'.format(family)


def _family_scope(family):
    try:
        return u'family:{0}'.format(family.FamilyCategory.Name)
    except Exception:
        return u'family:'


def make_row(element):
    """A Row for anything the Project Browser lists, else None."""
    key = eid_value(element.Id)
    if isinstance(element, ViewSheet):
        return core.Row(element.Id, key, u'Sheet', read_name(element),
                        number=core.to_text(element.SheetNumber),
                        number_scope=u'sheet:number')
    if isinstance(element, View):
        if element.IsTemplate:
            return None
        view_type = str(element.ViewType)
        return core.Row(element.Id, key,
                        VIEW_LABELS.get(view_type, u'View'),
                        read_name(element),
                        name_scope=u'view:{0}'.format(view_type))
    if isinstance(element, Family):
        return core.Row(element.Id, key, u'Family', read_name(element),
                        name_scope=_family_scope(element))
    if isinstance(element, ElementType):
        if isinstance(element, (RevitLinkType, CADLinkType)):
            return None
        return core.Row(element.Id, key, u'Type', read_name(element),
                        name_scope=_type_scope(element))
    return None


def read_selection(doc, element_ids):
    """(rows, how many selected things cannot be renamed here)."""
    rows = []
    left_out = 0
    for element_id in element_ids:
        element = doc.GetElement(element_id)
        row = make_row(element) if element is not None else None
        if row is None:
            left_out += 1
        else:
            rows.append(row)
    return core.sort_rows(rows), left_out


def read_taken(doc, rows):
    """{scope: names used by elements outside the batch}."""
    batch = set([row.key for row in rows])
    taken = {}

    def note(scope, value):
        taken.setdefault(scope, set()).add(value)

    views = False
    types = False
    families = False
    for row in rows:
        scope = row.scopes.get(core.FIELD_NAME) or u''
        number = row.has(core.FIELD_NUMBER)
        views = views or number or scope.startswith(u'view:')
        types = types or scope.startswith(u'type:')
        families = families or scope.startswith(u'family:')
    if views:
        for view in FilteredElementCollector(doc).OfClass(View):
            if eid_value(view.Id) in batch:
                continue
            if isinstance(view, ViewSheet):
                note(u'sheet:number', core.to_text(view.SheetNumber))
            else:
                note(u'view:{0}'.format(str(view.ViewType)), read_name(view))
    if types:
        for element in FilteredElementCollector(doc).OfClass(ElementType):
            if eid_value(element.Id) not in batch:
                note(_type_scope(element), read_name(element))
    if families:
        for family in FilteredElementCollector(doc).OfClass(Family):
            if eid_value(family.Id) not in batch:
                note(_family_scope(family), read_name(family))
    return taken


def write_value(doc, row, field, value):
    """Sets it and reads it back. A write that did not land raises."""
    element = doc.GetElement(row.eid)
    if field == core.FIELD_NUMBER:
        element.SheetNumber = value
        if core.to_text(element.SheetNumber) == value:
            return
    else:
        for route in (_set_property, _set_static, _set_sheet_param):
            try:
                route(element, value)
            except Exception:
                continue
            if read_name(element) == value:
                return
    raise ValueError(u'Revit did not take the new text')


def _set_property(element, value):
    element.Name = value


def _set_static(element, value):
    Element.Name.SetValue(element, value)


def _set_sheet_param(element, value):
    enum = getattr(BuiltInParameter, 'SHEET_NAME')
    element.get_Parameter(enum).Set(value)


def read_value(doc, row, field):
    element = doc.GetElement(row.eid)
    if element is None:
        return None
    if field == core.FIELD_NUMBER:
        return core.to_text(element.SheetNumber)
    return read_name(element)


class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        for message in accessor.GetFailureMessages():
            if str(message.GetSeverity()) == 'Warning':
                accessor.DeleteWarning(message)
        return FailureProcessingResult.Continue


def borrow(doc, rows):
    """{row key: who holds it} for rows that could not be borrowed."""
    if not doc.IsWorkshared:
        return {}
    ids = List[ElementId]()
    for row in rows:
        ids.Add(row.eid)
    held = WorksharingUtils.CheckoutElements(doc, ids)
    got = set([eid_value(i) for i in held])
    owners = {}
    for row in rows:
        if row.key not in got:
            try:
                info = WorksharingUtils.GetWorksharingTooltipInfo(doc, row.eid)
                owners[row.key] = core.to_text(info.Owner) or u'another user'
            except Exception:
                owners[row.key] = u'another user'
    return owners


class Report(object):
    def __init__(self):
        self.done = 0
        self.written = 0
        self.failed = []
        self.taken = None


def _sub(doc, action):
    sub = SubTransaction(doc)
    sub.Start()
    try:
        action()
        sub.Commit()
        return None
    except Exception as error:
        try:
            sub.RollBack()
        except Exception:
            pass
        return core.to_text(error) or u'Revit refused it'


def apply_job(doc, rows, rules_by_field, log):
    """Names are read again here: a modeless window can be left open while the
    model moves on, so the preview is not what gets written."""
    report = Report()
    live = []
    for row in rows:
        if doc.GetElement(row.eid) is None:
            report.failed.append((row, u'No longer in the model'))
            continue
        for field in core.FIELDS:
            if row.has(field):
                row.values[field] = read_value(doc, row, field)
        live.append(row)
    items = core.evaluate(live, rules_by_field, read_taken(doc, live))
    for item in items:
        if item.state in (core.CLASH, core.BAD):
            report.failed.append((item.row, item.reason))
    work = core.changes(items)
    if not work:
        report.taken = read_taken(doc, live)
        return report

    seen = {}
    for item in work:
        seen[item.row.key] = item.row
    owners = borrow(doc, list(seen.values()))
    for item in [i for i in work if i.row.key in owners]:
        report.failed.append((item.row, u'Owned by {0}'.format(owners[item.row.key])))
    work = [i for i in work if i.row.key not in owners]

    tx = Transaction(doc, u'Bulk Rename')
    options = tx.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    options.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(options)
    tx.Start()
    try:
        parked = []
        for item in core.needs_parking(work):
            name = u'{0}{1}'.format(core.PARK_PREFIX, item.row.key)
            error = _sub(doc, lambda i=item, n=name: write_value(doc, i.row, i.field, n))
            if error:
                log(u'park refused {0}: {1}'.format(item.row.key, error))
            else:
                parked.append(item)
        pending = []
        # Parked items land first: one Revit refuses can still go back to its
        # old name, because nothing has moved onto it yet.
        for item in parked + [i for i in work if i not in parked]:
            error = _sub(doc, lambda i=item: write_value(doc, i.row, i.field, i.new))
            if error:
                log(u'refused {0}: {1}'.format(item.row.key, error))
                report.failed.append((item.row, error))
                if item in parked:
                    _sub(doc, lambda i=item: write_value(doc, i.row, i.field, i.old))
            else:
                pending.append(item)
    except Exception:
        tx.RollBack()
        raise
    status = tx.Commit()
    if str(status) != 'Committed':
        report.failed.append((None, u'Revit rolled the rename back ({0})'.format(status)))
        report.taken = read_taken(doc, live)
        return report

    # Commit regenerates, so the count is what is really there afterwards.
    for item in pending:
        actual = read_value(doc, item.row, item.field)
        if actual == item.new:
            report.done += 1
        else:
            report.failed.append((item.row, u'Did not stay renamed'))
        item.row.values[item.field] = actual if actual is not None else item.old
    report.taken = read_taken(doc, live)
    return report


def text_parameters(doc, rows, sample=40):
    """Names of the editable text parameters on the selected sheets."""
    names = set()
    sheets = [r for r in rows if r.has(core.FIELD_NUMBER)][:sample]
    for row in sheets:
        for param in doc.GetElement(row.eid).Parameters:
            try:
                if str(param.StorageType) == 'String' and not param.IsReadOnly:
                    names.add(core.to_text(param.Definition.Name))
            except Exception:
                pass
    return sorted(names, key=lambda n: n.lower())


def _param_problem(sheet, param_name):
    param = sheet.LookupParameter(param_name)
    if param is None:
        return None, u'No parameter {0} on this sheet'.format(param_name)
    if param.IsReadOnly or str(param.StorageType) != 'String':
        return None, u'{0} is not an editable text parameter'.format(param_name)
    return param, None


def write_sheet_row(doc, row, pairs):
    sheet = doc.GetElement(row.eid)
    for param_name, value in pairs:
        param, problem = _param_problem(sheet, param_name)
        if problem:
            raise ValueError(problem)
        param.Set(value)
        if core.to_text(param.AsString()) != value:
            raise ValueError(u'{0} did not take the value'.format(param_name))


def _needs_write(sheet, pairs):
    for param_name, value in pairs:
        param = sheet.LookupParameter(param_name)
        if param is None or core.to_text(param.AsString()) != value:
            return True
    return False


def write_sheet_names(doc, rows, settings, report, log):
    """The sheet's name as it stands in the model goes into the parameters.
    Sheets already right are not borrowed or touched."""
    work = []
    for row in rows:
        if not row.has(core.FIELD_NUMBER):
            continue
        sheet = doc.GetElement(row.eid)
        if sheet is None:
            report.failed.append((row, u'No longer in the model'))
            continue
        pairs = core.sheet_writes(read_name(sheet), settings)
        if _needs_write(sheet, pairs):
            work.append((row, pairs))
        else:
            report.written += 1
    if not work:
        return
    owners = borrow(doc, [item[0] for item in work])
    tx = Transaction(doc, u'Write Sheet names')
    options = tx.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    options.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(options)
    tx.Start()
    done = []
    try:
        for row, pairs in work:
            if row.key in owners:
                report.failed.append((row, u'Owned by {0}'.format(owners[row.key])))
                continue
            error = _sub(doc, lambda r=row, p=pairs: write_sheet_row(doc, r, p))
            if error:
                log(u'sheet {0}: {1}'.format(row.key, error))
                report.failed.append((row, error))
            else:
                done.append((row, pairs))
    except Exception:
        tx.RollBack()
        raise
    status = tx.Commit()
    if str(status) != 'Committed':
        report.failed.append((None, u'Revit rolled the write back ({0})'.format(status)))
        return
    for row, pairs in done:
        if _needs_write(doc.GetElement(row.eid), pairs):
            report.failed.append((row, u'Values did not stay'))
        else:
            report.written += 1


def rename_and_write(doc, rows, rules_by_field, settings, rename, log):
    """One undo step. rename is False when no rename is waiting."""
    group = TransactionGroup(doc, u'Write Sheet names')
    group.Start()
    try:
        report = Report()
        if rename:
            report = apply_job(doc, rows, rules_by_field, log)
        write_sheet_names(doc, rows, settings, report, log)
    except Exception:
        group.RollBack()
        raise
    group.Assimilate()
    return report


class Runner(IExternalEventHandler):
    """One queued job at a time. A Pending answer means an earlier request is
    still waiting, so only a refused job is ever dropped."""

    def __init__(self, log):
        self.log = log
        self.jobs = []
        self.event = None

    def GetName(self):
        return 'RevoBIM Bulk Rename'

    def attach(self, event):
        self.event = event

    def submit(self, job, on_refused):
        if self.jobs:
            return True
        self.jobs.append(job)
        answer = str(self.event.Raise())
        self.log(u'raise: {0}'.format(answer))
        if answer in ('Accepted', 'Pending'):
            return True
        self.jobs.remove(job)
        on_refused(answer)
        return False

    def Execute(self, uiapp):
        while self.jobs:
            job = self.jobs.pop(0)
            try:
                job()
            except Exception as error:
                self.log(u'job failed: {0}'.format(error))
