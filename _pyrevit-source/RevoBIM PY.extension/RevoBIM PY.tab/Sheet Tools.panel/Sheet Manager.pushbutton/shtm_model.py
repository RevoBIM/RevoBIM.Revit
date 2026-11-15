# -*- coding: utf-8 -*-
"""Everything that reads the Revit model.

Read in one pass, not per sheet: at 400 sheets a collector per sheet is
unusable, and the read runs again on every refresh.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core
from shtm_core import eid_value

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSheet, Viewport, ScheduleSheetInstance,
    View, ViewSchedule, ViewType, ElementId, BuiltInParameter, BuiltInCategory,
    BrowserOrganization, LabelUtils, StorageType, WorksharingUtils,
    CheckoutStatus, ElementTransformUtils,
)
from System.Collections.Generic import List as NetList
from System import Enum


# ====================== small helpers ======================

def category_id(name):
    """BuiltInCategory members are looked up at call time, never at import
    time - one less thing that can die before the tool runs."""
    try:
        return ElementId(getattr(BuiltInCategory, name))
    except Exception:
        return ElementId.InvalidElementId


def new_element_id(value):
    """ElementId construction takes Int32 on some releases and Int64 on others."""
    try:
        return ElementId(value)
    except Exception:
        pass
    try:
        from System import Int64
        return ElementId(Int64(value))
    except Exception:
        return ElementId.InvalidElementId


def param_text(param):
    """The value of a parameter as the user would read it."""
    if param is None:
        return u""
    try:
        if param.StorageType == StorageType.String:
            return param.AsString() or u""
        text = param.AsValueString()
        if text:
            return text
        if param.StorageType == StorageType.Integer:
            return u"{0}".format(param.AsInteger())
        if param.StorageType == StorageType.Double:
            return u"{0}".format(param.AsDouble())
        if param.StorageType == StorageType.ElementId:
            return u"{0}".format(eid_value(param.AsElementId()))
    except Exception:
        pass
    return u""


def find_parameter(element, name):
    """GetParameters first: LookupParameter picks one object and a family can
    carry two parameters of the same name, one of them read only."""
    best = None
    try:
        for param in element.GetParameters(name):
            if not param.IsReadOnly:
                return param
            if best is None:
                best = param
    except Exception:
        pass
    if best is not None:
        return best
    try:
        return element.LookupParameter(name)
    except Exception:
        return None


def element_name(element):
    try:
        value = element.Name
        if value is None:
            return u""
        return u"{0}".format(value)
    except Exception:
        return u""


# ====================== the browser organisation ======================

def parameter_name_from_id(doc, param_id):
    value = eid_value(param_id)
    if value == 0:
        return u""
    if value < 0:
        try:
            member = Enum.ToObject(BuiltInParameter, value)
            label = LabelUtils.GetLabelFor(member)
            if label:
                return u"{0}".format(label)
        except Exception:
            pass
        return u""
    try:
        element = doc.GetElement(param_id)
        if element is not None:
            return element_name(element)
    except Exception:
        pass
    return u""


def browser_organisation(doc):
    """The grouping parameters the project browser is actually using.

    Returns a list of parameter names, outermost group first. That is exactly
    the Group by / Then by list in Browser Organization Properties.
    """
    names = []
    try:
        org = BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc)
    except Exception:
        return names
    if org is None:
        return names
    sheet = None
    try:
        for element in FilteredElementCollector(doc).OfClass(ViewSheet):
            sheet = element
            break
    except Exception:
        sheet = None
    if sheet is None:
        return names
    try:
        for item in org.GetFolderItems(sheet.Id):
            name = parameter_name_from_id(doc, item.GetFolderParameterId())
            if name and name not in names:
                names.append(name)
    except Exception:
        pass
    return names


def browser_organisation_name(doc):
    try:
        org = BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc)
        if org is not None:
            return element_name(org)
    except Exception:
        pass
    return u""


# ====================== sheets ======================

def sheet_parameter_names(doc):
    """Every parameter a sheet in this project actually carries."""
    names = set()
    try:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            for param in sheet.Parameters:
                try:
                    names.add(u"{0}".format(param.Definition.Name))
                except Exception:
                    pass
    except Exception:
        pass
    ordered = sorted(names, key=lambda n: n.lower())
    return ordered


def read_sheets(doc, settings, progress=None):
    """One record per sheet, with every parameter value read once."""
    include_placeholders = shtm_core.as_bool(settings.get("include_placeholders"))
    only_in_list = shtm_core.as_bool(settings.get("only_in_sheet_list"))

    sheets = []
    try:
        collected = list(FilteredElementCollector(doc).OfClass(ViewSheet))
    except Exception:
        collected = []

    counts = placed_counts(doc)
    total = len(collected) or 1
    done = 0
    last_percent = -1

    for sheet in collected:
        done += 1
        if progress is not None:
            percent = done * 100 // total
            if percent != last_percent:
                last_percent = percent
                progress(percent, done, total)
        try:
            is_placeholder = bool(sheet.IsPlaceholder)
        except Exception:
            is_placeholder = False
        if is_placeholder and not include_placeholders:
            continue
        if only_in_list:
            param = sheet.get_Parameter(BuiltInParameter.SHEET_SCHEDULED)
            if param is not None and param.AsInteger() == 0:
                continue

        values = {}
        readonly = set()
        try:
            for param in sheet.Parameters:
                try:
                    name = u"{0}".format(param.Definition.Name)
                except Exception:
                    continue
                text = param_text(param)
                if name not in values or (not values[name] and text):
                    values[name] = text
                # a parameter the sheet will not let anyone write - a
                # calculated one, a locked one, a type one surfaced here - is
                # painted read only so an edit is refused before Apply
                try:
                    if param.IsReadOnly:
                        readonly.add(name)
                    else:
                        readonly.discard(name)
                except Exception:
                    pass
        except Exception:
            pass

        record = {
            "id": eid_value(sheet.Id),
            "number": element_sheet_number(sheet),
            "name": element_name(sheet),
            "placeholder": is_placeholder,
            "values": values,
            "readonly": readonly,
            "views": counts.get(eid_value(sheet.Id), 0),
        }
        record["values"][u"Sheet Number"] = record["number"]
        record["values"][u"Sheet Name"] = record["name"]
        record["values"][u"Views on sheet"] = u"{0}".format(record["views"])
        readonly.discard(u"Sheet Number")
        readonly.discard(u"Sheet Name")
        readonly.add(u"Views on sheet")
        sheets.append(record)

    sheets.sort(key=lambda r: shtm_core.natural_key(r["number"]))
    return sheets


def element_sheet_number(sheet):
    try:
        return u"{0}".format(sheet.SheetNumber)
    except Exception:
        return u""


def placed_counts(doc):
    """How many viewports and schedule instances sit on each sheet."""
    counts = {}
    try:
        for viewport in FilteredElementCollector(doc).OfClass(Viewport):
            key = eid_value(viewport.SheetId)
            counts[key] = counts.get(key, 0) + 1
    except Exception:
        pass
    try:
        for instance in FilteredElementCollector(doc).OfClass(ScheduleSheetInstance):
            try:
                if instance.IsTitleblockRevisionSchedule:
                    continue
            except Exception:
                pass
            key = eid_value(instance.OwnerViewId)
            counts[key] = counts.get(key, 0) + 1
    except Exception:
        pass
    return counts


def distinct_values(sheets, key):
    values = set()
    for sheet in sheets:
        values.add(sheet["values"].get(key, u""))
    ordered = sorted([v for v in values if v], key=lambda v: shtm_core.natural_key(v))
    if u"" in values:
        ordered.append(u"")
    return ordered


def project_values(doc, parameter_name):
    """Every value that parameter already holds across the project's sheets -
    what the grouping picker offers when it is clicked."""
    values = set()
    try:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            param = find_parameter(sheet, parameter_name)
            text = param_text(param)
            if text:
                values.add(text)
    except Exception:
        pass
    return sorted(values, key=lambda v: shtm_core.natural_key(v))


# ====================== views ======================

def view_kind(view):
    try:
        if isinstance(view, ViewSchedule):
            return "schedule"
    except Exception:
        pass
    try:
        if view.ViewType == ViewType.Legend:
            return "legend"
        if view.ViewType == ViewType.DraftingView:
            return "drafting"
    except Exception:
        pass
    return "model"


def primary_of(view):
    try:
        pid = view.GetPrimaryViewId()
        if pid is not None and eid_value(pid) > 0:
            return eid_value(pid)
    except Exception:
        pass
    return 0


def view_type_name(view):
    try:
        return u"{0}".format(view.ViewType)
    except Exception:
        return u"View"


def read_views(doc):
    """Every non-template view, keyed by id."""
    views = {}
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            try:
                if view.IsTemplate:
                    continue
            except Exception:
                continue
            key = eid_value(view.Id)
            views[key] = {
                "id": key,
                "name": element_name(view),
                "kind": view_kind(view),
                "type": view_type_name(view),
                "primary": primary_of(view),
                "sheet": 0,
            }
    except Exception:
        pass
    return views


def placed_on_sheets(doc, sheet_ids):
    """What is on each of the given sheets.

    Returns (viewports, schedules) as lists of dicts. Title block revision
    schedules are left out - they belong to the title block, not the sheet.
    """
    wanted = set(sheet_ids)
    viewports = []
    schedules = []
    try:
        for viewport in FilteredElementCollector(doc).OfClass(Viewport):
            sheet_id = eid_value(viewport.SheetId)
            if sheet_id not in wanted:
                continue
            viewports.append({
                "id": eid_value(viewport.Id),
                "sheet": sheet_id,
                "view": eid_value(viewport.ViewId),
            })
    except Exception:
        pass
    try:
        for instance in FilteredElementCollector(doc).OfClass(ScheduleSheetInstance):
            try:
                if instance.IsTitleblockRevisionSchedule:
                    continue
            except Exception:
                pass
            sheet_id = eid_value(instance.OwnerViewId)
            if sheet_id not in wanted:
                continue
            schedules.append({
                "id": eid_value(instance.Id),
                "sheet": sheet_id,
                "view": eid_value(instance.ScheduleId),
            })
    except Exception:
        pass
    return viewports, schedules


def grouping_parameters(doc, settings):
    """The browser grouping parameters - Settings first, then the project
    browser's own sheet grouping, then the BGL four. One place, because the
    Duplicate window's columns and the template presets in Settings have to
    agree on them."""
    names = shtm_core.split_list(settings.get("grouping_parameters"))
    if not names:
        try:
            names = browser_organisation(doc)
        except Exception:
            names = []
    return list(names) or list(shtm_core.DEFAULT_GROUPING)


def dependents_of(views, primary_id):
    return [v["id"] for v in views.values() if v["primary"] == primary_id]


def view_templates(doc):
    """Templates grouped by the view type they can be put on."""
    grouped = {}
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            try:
                if not view.IsTemplate:
                    continue
            except Exception:
                continue
            key = view_type_name(view)
            grouped.setdefault(key, []).append(
                {"id": eid_value(view.Id), "name": element_name(view)})
    except Exception:
        pass
    for key in grouped:
        grouped[key].sort(key=lambda t: shtm_core.natural_key(t["name"]))
    return grouped


def titleblock_type_of(doc, sheet_id):
    """The title block type on a sheet, so the copy gets the same one."""
    try:
        collector = FilteredElementCollector(doc, new_element_id(sheet_id))
        collector = collector.OfCategoryId(category_id("OST_TitleBlocks"))
        collector = collector.WhereElementIsNotElementType()
        for instance in collector:
            return eid_value(instance.GetTypeId()), eid_value(instance.Id)
    except Exception:
        pass
    return 0, 0


# ====================== worksharing ======================

def is_workshared(doc):
    try:
        return bool(doc.IsWorkshared)
    except Exception:
        return False


def locked_by(doc, element):
    """Two different things lock an element and both have to be asked about."""
    if not is_workshared(doc):
        return u""
    try:
        status = WorksharingUtils.GetCheckoutStatus(doc, element.Id)
        if status == CheckoutStatus.OwnedByOtherUser:
            info = WorksharingUtils.GetWorksharingTooltipInfo(doc, element.Id)
            return u"borrowed by {0}".format(info.Owner or u"another user")
    except Exception:
        pass
    try:
        table = doc.GetWorksetTable()
        workset = table.GetWorkset(element.WorksetId)
        owner = workset.Owner
        if owner and owner.strip() and owner != doc.Application.Username:
            return u'workset "{0}" is owned by {1}'.format(workset.Name, owner)
    except Exception:
        pass
    return u""


def borrow(doc, element_ids):
    """Borrow before writing: a write to an element that has not been borrowed
    writes nothing and says nothing, because Revit asks in a dialog and a run
    suppressing dialogs answers it."""
    if not is_workshared(doc) or not element_ids:
        return
    try:
        wanted = NetList[ElementId]()
        for value in element_ids:
            wanted.Add(new_element_id(value))
        WorksharingUtils.CheckoutElements(doc, wanted)
    except Exception:
        pass


def _touch():
    """Keeps ElementTransformUtils referenced for the bench import rule."""
    return ElementTransformUtils is not None
