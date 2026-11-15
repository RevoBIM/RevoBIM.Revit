# -*- coding: utf-8 -*-
"""Reading the model. Nothing in here writes.

Every function takes the document it reads, so the same code counts the live
model (for the preview) and the saved copy (for the real run). The rules that
decide what goes are in mcu_core and take plain ids, so they are tested on
the bench.
"""
import mcu_clr  # noqa: F401 - must come before any System.* / Autodesk.* import
import mcu_core as core

from System.Collections.Generic import HashSet
from Autodesk.Revit.DB import (FilteredElementCollector, ElementId, View,
                               ViewSheet, ViewSchedule, Viewport,
                               ScheduleSheetInstance, ElementType,
                               Material, LinePatternElement,
                               FillPatternElement, Family,
                               ParameterFilterElement, RevitLinkType,
                               ImportInstance, CADLinkType, ViewFamilyType)
import Autodesk.Revit.DB as revit_db

eid = core.eid_value


def element_name(element):
    """Element.Name can raise in IronPython - every read is guarded."""
    if element is None:
        return u""
    try:
        return core.to_text(element.Name)
    except Exception:
        pass
    try:
        return core.to_text(revit_db.Element.Name.GetValue(element))
    except Exception:
        return u""


def class_name(element):
    try:
        return core.to_text(element.GetType().Name)
    except Exception:
        return u""


def category_name(element):
    try:
        if isinstance(element, Family):
            category = element.FamilyCategory
        else:
            category = element.Category
        if category is not None:
            return core.to_text(category.Name)
    except Exception:
        pass
    return u""


def display_name(element):
    name = element_name(element)
    try:
        family = getattr(element, u"FamilyName", None)
        if family and family != name:
            return u"{0} : {1}".format(family, name)
    except Exception:
        pass
    return name


def model_title(doc):
    try:
        return core.to_text(doc.Title)
    except Exception:
        return u""


def optional_class(name):
    """A DB class a release may not have, looked up late."""
    return getattr(revit_db, name, None)


# ============================================================
# model identity
# ============================================================

def is_cloud(doc):
    try:
        return bool(doc.IsModelInCloud)
    except Exception:
        return False


def central_path(doc):
    """ModelPath of the central (or cloud) model, else None."""
    if not doc.IsWorkshared:
        return None
    if is_cloud(doc):
        try:
            return doc.GetCloudModelPath()
        except Exception:
            pass
    try:
        return doc.GetWorksharingCentralModelPath()
    except Exception:
        return None


def visible_path(model_path):
    if model_path is None:
        return u""
    try:
        from Autodesk.Revit.DB import ModelPathUtils
        return core.to_text(ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path))
    except Exception:
        return u""


def same_document(first, second):
    """Two handles on the same open model. Equals first; title and path as
    the fallback for a release where Equals is only reference equality."""
    if first is None or second is None:
        return False
    try:
        if first.Equals(second):
            return True
    except Exception:
        pass
    try:
        return (core.to_text(first.PathName) == core.to_text(second.PathName) and
                core.to_text(first.Title) == core.to_text(second.Title))
    except Exception:
        return False


def describe(doc):
    central = central_path(doc)
    return {
        u"title": model_title(doc),
        u"path": core.to_text(doc.PathName),
        u"workshared": bool(doc.IsWorkshared),
        u"cloud": is_cloud(doc),
        u"central": visible_path(central),
    }


# ============================================================
# views, sheets, schedules
# ============================================================

def on_sheet_ids(doc, sheet_ids=None):
    """Views placed on a sheet. With sheet_ids, only placements on those
    sheets count - the sheets that will still exist after the sheet stage."""
    ids = set()
    for viewport in FilteredElementCollector(doc).OfClass(Viewport):
        try:
            if sheet_ids is not None and eid(viewport.SheetId) not in sheet_ids:
                continue
            ids.add(eid(viewport.ViewId))
        except Exception:
            pass
    for instance in FilteredElementCollector(doc).OfClass(ScheduleSheetInstance):
        try:
            if sheet_ids is not None and eid(instance.OwnerViewId) not in sheet_ids:
                continue
            ids.add(eid(instance.ScheduleId))
        except Exception:
            pass
    return ids


def read_sheets(doc):
    out = []
    for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
        try:
            if sheet.IsTemplate:
                continue
            out.append({
                u"id": eid(sheet.Id),
                u"number": core.to_text(sheet.SheetNumber),
                u"name": element_name(sheet),
                u"placeholder": bool(getattr(sheet, u"IsPlaceholder", False)),
            })
        except Exception:
            continue
    return out


# ============================================================
# the project browser organisation
# ============================================================

def browser_organisation(doc, sheets):
    """The organisation the browser is using now, or None (any release that
    lacks the call simply falls back to grouping by type)."""
    try:
        from Autodesk.Revit.DB import BrowserOrganization
        if sheets:
            return BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc)
        return BrowserOrganization.GetCurrentBrowserOrganizationForViews(doc)
    except Exception:
        return None


def browser_folders(organisation, element_id):
    if organisation is None:
        return []
    try:
        return [core.to_text(info.Name) for info in organisation.GetFolderItems(element_id)]
    except Exception:
        return []


def organisation_name(organisation):
    return element_name(organisation) if organisation is not None else u"type only"


LISTED_VIEW_KINDS = set(core.VIEW_TYPE_LABELS)


def view_retain_items(doc):
    """Every view, schedule and legend someone might keep, grouped the way
    the project browser shows them right now."""
    organisation = browser_organisation(doc, False)
    names = {}
    views = []
    for view in FilteredElementCollector(doc).OfClass(View):
        try:
            if view.IsTemplate or isinstance(view, ViewSheet):
                continue
            kind = core.to_text(view.ViewType)
            if kind not in LISTED_VIEW_KINDS:
                continue
            if isinstance(view, ViewSchedule) and _is_internal_schedule(view):
                continue
            names[eid(view.Id)] = element_name(view)
            views.append((view, kind))
        except Exception:
            continue
    items = []
    for view, kind in views:
        name = names.get(eid(view.Id), u"")
        label = name
        try:
            parent = eid(view.GetPrimaryViewId())
            if parent > 0:
                label = u"{0}   (dependent of {1})".format(name, names.get(parent, u"?"))
        except Exception:
            pass
        folders = core.view_folders(browser_folders(organisation, view.Id), kind)
        items.append({u"key": core.view_key(kind, name), u"label": label,
                      u"folders": folders, u"id": eid(view.Id)})
    return items, organisation_name(organisation)


def sheet_retain_items(doc):
    organisation = browser_organisation(doc, True)
    items = []
    for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
        try:
            if sheet.IsTemplate:
                continue
            number = core.to_text(sheet.SheetNumber)
            label = u"{0} - {1}".format(number, element_name(sheet))
            if getattr(sheet, u"IsPlaceholder", False):
                label += u"   (placeholder)"
            items.append({u"key": number, u"label": label, u"id": eid(sheet.Id),
                          u"folders": core.sheet_folders(browser_folders(organisation, sheet.Id))})
        except Exception:
            continue
    return items, organisation_name(organisation)


def starting_view_id(doc):
    try:
        from Autodesk.Revit.DB import StartingViewSettings
        settings = StartingViewSettings.GetStartingViewSettings(doc)
        return eid(settings.ViewId)
    except Exception:
        return 0


def _is_internal_schedule(view):
    for attribute in (u"IsTitleblockRevisionSchedule", u"IsInternalKeynoteSchedule"):
        try:
            if getattr(view, attribute):
                return True
        except Exception:
            pass
    return False


def read_views(doc):
    items = []
    for view in FilteredElementCollector(doc).OfClass(View):
        try:
            if isinstance(view, ViewSheet):
                continue
            parent = 0
            try:
                parent = eid(view.GetPrimaryViewId())
                if parent < 0:
                    parent = 0
            except Exception:
                parent = 0
            internal = False
            if isinstance(view, ViewSchedule):
                internal = _is_internal_schedule(view)
            items.append({
                u"id": eid(view.Id),
                u"name": element_name(view),
                u"kind": core.to_text(view.ViewType),
                u"template": bool(view.IsTemplate),
                u"parent": parent,
                u"internal": internal,
            })
        except Exception:
            continue
    return items


def template_usage(doc, ignore=None):
    """ignore: view ids that are going anyway, so their templates count as
    unused - that is what the run will find once they are gone."""
    ignore = ignore or set()
    templates = []
    used = set()
    defaults = set()
    for view in FilteredElementCollector(doc).OfClass(View):
        try:
            if view.IsTemplate:
                templates.append(eid(view.Id))
            elif eid(view.Id) not in ignore:
                value = eid(view.ViewTemplateId)
                if value > 0:
                    used.add(value)
        except Exception:
            continue
    for family_type in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            value = eid(family_type.DefaultTemplateId)
            if value > 0:
                defaults.add(value)
        except Exception:
            continue
    return templates, used, defaults


def filter_usage(doc, ignore=None):
    ignore = ignore or set()
    filters = [eid(item.Id) for item in
               FilteredElementCollector(doc).OfClass(ParameterFilterElement)]
    used = set()
    for view in FilteredElementCollector(doc).OfClass(View):
        if eid(view.Id) in ignore:
            continue
        try:
            if not view.AreGraphicsOverridesAllowed():
                continue
        except Exception:
            pass
        try:
            for filter_id in view.GetFilters():
                used.add(eid(filter_id))
        except Exception:
            continue
    return filters, used


# ============================================================
# links and imports
# ============================================================

def ids_of_class(doc, cls):
    if cls is None:
        return []
    try:
        return [eid(item.Id) for item in FilteredElementCollector(doc).OfClass(cls)]
    except Exception:
        return []


def revit_link_ids(doc):
    return ids_of_class(doc, RevitLinkType)


def cad_ids(doc):
    # instances first, then the link types they came from
    return ids_of_class(doc, ImportInstance) + ids_of_class(doc, CADLinkType)


def point_cloud_ids(doc):
    return (ids_of_class(doc, optional_class(u"PointCloudInstance")) +
            ids_of_class(doc, optional_class(u"PointCloudType")))


# ============================================================
# NWC export
# ============================================================

def three_d_views(doc):
    """{name: id} of every 3D view that can be exported (not templates)."""
    out = {}
    cls = optional_class(u"View3D")
    if cls is None:
        return out
    for view in FilteredElementCollector(doc).OfClass(cls):
        try:
            if view.IsTemplate:
                continue
            out[element_name(view)] = eid(view.Id)
        except Exception:
            continue
    return out


def nwc_available():
    try:
        from Autodesk.Revit.DB import OptionalFunctionalityUtils
        return bool(OptionalFunctionalityUtils.IsNavisworksExporterAvailable())
    except Exception:
        return False


def image_type_ids(doc):
    return ids_of_class(doc, optional_class(u"ImageType"))


def image_placements(doc):
    """(image type id, view id) for every placed raster image."""
    out = []
    cls = optional_class(u"ImageInstance")
    if cls is None:
        return out
    for instance in FilteredElementCollector(doc).OfClass(cls):
        try:
            out.append((eid(instance.GetTypeId()), eid(instance.OwnerViewId)))
        except Exception:
            continue
    return out


def unused_image_ids(doc):
    """What Revit's purge calls unused in the Raster Images category,
    falling back to the whole purge list when the category filter is refused."""
    if not can_purge(doc):
        return None
    try:
        from Autodesk.Revit.DB import BuiltInCategory
        categories = HashSet[ElementId]()
        categories.Add(ElementId(BuiltInCategory.OST_RasterImages))
        return set(eid(i) for i in doc.GetUnusedElements(categories))
    except Exception:
        return set(value for value, _ in unused_entries(doc))


# ============================================================
# purge
# ============================================================

def can_purge(doc):
    return hasattr(doc, u"GetUnusedElements")


def unused_entries(doc):
    """[(id, group)] for everything Revit's own purge would offer.
    GetUnusedElements arrived in Revit 2024, which is the oldest release this
    tool supports; the check stays so an older engine says so plainly."""
    if not can_purge(doc):
        return []
    ids = doc.GetUnusedElements(HashSet[ElementId]())
    out = []
    for element_id in ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue
        out.append((eid(element_id),
                    core.purge_group(category_name(element), class_name(element))))
    return out


def scan_purge(doc, with_used=True):
    """Everything the settings window lists: unused and (optionally) used
    purgeable elements, with names."""
    rows = []
    unused = []
    used = []
    unused_set = set()
    if not can_purge(doc):
        return {u"ok": False, u"reason": u"This release of Revit has no purge API.",
                u"rows": rows, u"unused": unused, u"used": used}
    ids = doc.GetUnusedElements(HashSet[ElementId]())
    for element_id in ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue
        value = eid(element_id)
        group = core.purge_group(category_name(element), class_name(element))
        unused.append((value, group))
        unused_set.add(value)
        rows.append((value, display_name(element), group, u"Unused"))
    if with_used:
        seen = set(unused_set)
        collectors = [
            FilteredElementCollector(doc).WhereElementIsElementType(),
            FilteredElementCollector(doc).OfClass(Material),
            FilteredElementCollector(doc).OfClass(LinePatternElement),
            FilteredElementCollector(doc).OfClass(FillPatternElement),
            FilteredElementCollector(doc).OfClass(Family),
        ]
        for collector in collectors:
            for element in collector:
                try:
                    value = eid(element.Id)
                    if value in seen:
                        continue
                    seen.add(value)
                    group = core.purge_group(category_name(element), class_name(element))
                    used.append((value, group))
                    rows.append((value, display_name(element), group, u"Used"))
                except Exception:
                    continue
    return {u"ok": True, u"reason": u"", u"rows": rows,
            u"unused": unused, u"used": used}


# ============================================================
# the preview counts
# ============================================================

VIEW_STAGES = [
    (u"delete_views_off_sheet", core.views_to_delete),
    (u"delete_schedules_off_sheet", core.schedules_to_delete),
    (u"delete_legends_off_sheet", core.legends_to_delete),
]


def view_sheet_plan(doc, template, protected):
    """What the sheet and view stages will delete, worked out before any of
    it runs. Returns a dict with sheets, views, placed and decisions, where
    decisions maps every sheet and view id to why it goes or stays."""
    get = core.as_bool
    keep = core.split_words(template.get(u"keep_view_words"))
    retained_views = set(core.split_retain(template.get(u"retain_views")))
    retained_sheets = set(core.split_retain(template.get(u"retain_sheets")))
    delete_sheets = get(template.get(u"delete_sheets_not_retained"))
    decisions = {}
    sheets = read_sheets(doc)
    doomed = {}
    if delete_sheets:
        doomed[u"delete_sheets_not_retained"] = core.sheets_to_delete(
            sheets, retained_sheets, protected, decisions)[0]
    else:
        for sheet in sheets:
            decisions[sheet[u"id"]] = u"kept: Delete sheets not retained is off"
    views = read_views(doc)
    surviving = core.surviving_sheet_ids(sheets, delete_sheets, retained_sheets, protected)
    placed = on_sheet_ids(doc, surviving)
    for key, rule in VIEW_STAGES:
        if get(template.get(key)):
            doomed[key] = rule(views, placed, keep, protected, retained_views, decisions)[0]
    for item in views:
        decisions.setdefault(item[u"id"], u"kept: its delete stage is off")
    return {u"sheets": sheets, u"views": views, u"placed": placed,
            u"doomed": doomed, u"decisions": decisions,
            u"retained_views": retained_views, u"retained_sheets": retained_sheets}


def all_doomed(plan):
    out = set()
    for ids in plan[u"doomed"].values():
        out.update(ids)
    return out


def switch_candidates(plan, starting_id):
    """Where to move the active view: retained sheets, then retained plans
    and other views, then retained schedules and legends, then the starting
    view, then anything that stays."""
    openable = [s for s in plan[u"sheets"] if not s.get(u"placeholder")]
    sheets = sorted([s for s in openable if s[u"number"] in plan[u"retained_sheets"]],
                    key=lambda s: core.natural_key(s[u"number"]))
    ids = [s[u"id"] for s in sheets]
    retained = [v for v in plan[u"views"]
                if core.view_key(v[u"kind"], v[u"name"]) in plan[u"retained_views"]
                and not v.get(u"template")]
    ids += [v[u"id"] for v in retained if v[u"kind"] not in core.TOP_LEVEL_KINDS]
    ids += [v[u"id"] for v in retained if v[u"kind"] in core.TOP_LEVEL_KINDS]
    ids.append(starting_id)
    ids += [s[u"id"] for s in openable]
    ids += [v[u"id"] for v in plan[u"views"]
            if not v.get(u"template") and v[u"kind"] not in core.NEVER_DELETE_KINDS]
    return ids


def plan_counts(doc, template, active_view_id=0, purge_scan=None):
    """{op_key: count} of what the template would remove from `doc`, in the
    same order the run takes them: sheets first, then what is left placed."""
    get = core.as_bool
    protected = set([starting_view_id(doc), active_view_id])
    counts = {}
    plan = view_sheet_plan(doc, template, protected)
    for key, ids in plan[u"doomed"].items():
        counts[key] = len(ids)
    if get(template.get(u"remove_revit_links")):
        counts[u"remove_revit_links"] = len(revit_link_ids(doc))
    if get(template.get(u"remove_cad")):
        going_views = all_doomed(plan)
        surviving = 0
        for instance in FilteredElementCollector(doc).OfClass(ImportInstance):
            try:
                if eid(instance.OwnerViewId) not in going_views:
                    surviving += 1
            except Exception:
                surviving += 1
        counts[u"remove_cad"] = surviving + len(ids_of_class(doc, CADLinkType))
    if get(template.get(u"remove_point_clouds")):
        counts[u"remove_point_clouds"] = len(
            ids_of_class(doc, optional_class(u"PointCloudInstance")))
    if get(template.get(u"delete_unplaced_images")):
        unused = unused_image_ids(doc)
        if unused is not None:
            counts[u"delete_unplaced_images"] = len(core.images_freed(
                image_type_ids(doc), image_placements(doc), all_doomed(plan), unused))
    # sheets and views go first, so count templates and filters as the run
    # will find them: without the views that are going
    going = all_doomed(plan)
    doomed_templates = []
    if get(template.get(u"delete_unused_templates")):
        templates, used, defaults = template_usage(doc, going)
        doomed_templates = core.unused_ids(templates, used, defaults)
        counts[u"delete_unused_templates"] = len(doomed_templates)
    if get(template.get(u"delete_unused_filters")):
        filters, used_filters = filter_usage(doc, going | set(doomed_templates))
        counts[u"delete_unused_filters"] = len(core.unused_ids(filters, used_filters))
    counts[u"_kept"] = core.kept_summary(plan[u"views"], plan[u"decisions"])
    if get(template.get(u"export_nwc")):
        import mcu_nwc as nwc
        views, primary = nwc.selection(template)
        names = three_d_views(doc)
        counts[u"export_nwc"] = len([v for v in views if v in names])
    if get(template.get(u"purge")) and purge_scan is not None:
        excluded = core.split_list(template.get(u"purge_exclude"))
        counts[u"purge"] = len(core.purge_selection(purge_scan, excluded))
    return counts


def environment(uiapp, doc):
    """Versions and model facts for the debug report. Never raises."""
    import sys
    pairs = []

    def add(label, getter):
        try:
            pairs.append((label, getter()))
        except Exception as error:
            pairs.append((label, u"(unavailable: {0})".format(core.to_text(error))))
    app = uiapp.Application
    add(u"Revit", lambda: u"{0} build {1}".format(app.VersionName, app.VersionBuild))
    add(u"Python engine", lambda: sys.version.replace(u"\n", u" "))
    add(u".NET", lambda: core.to_text(__import__(u"System").Environment.Version))
    add(u"Model title", lambda: model_title(doc))
    add(u"Model path", lambda: doc.PathName)
    add(u"Workshared", lambda: doc.IsWorkshared)
    add(u"Cloud model", lambda: is_cloud(doc))
    add(u"Central", lambda: visible_path(central_path(doc)))
    add(u"Views browser organisation", lambda: organisation_name(browser_organisation(doc, False)))
    add(u"Sheets browser organisation", lambda: organisation_name(browser_organisation(doc, True)))
    add(u"Starting view id", lambda: starting_view_id(doc))
    add(u"Has purge API", lambda: can_purge(doc))
    add(u"Has GetFolderItems", lambda: browser_organisation(doc, False) is not None)
    return pairs
