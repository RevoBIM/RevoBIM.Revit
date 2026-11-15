# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : everything that reads or writes Revit.

Revit 2024 - 2027.  ElementId objects are kept as Revit hands them over and
never rebuilt from integers; enums are compared by name; BuiltInParameter and
BuiltInCategory members are looked up when they are used, not at load.

Order of work on Apply, which the API dictates:
  1. check worksets / elements out      - outside any transaction
  2. write                              - inside one TransactionGroup
  3. read everything back               - after the group has closed
"""

import wsm_clr  # noqa: F401  (assemblies first)

from System.Collections.Generic import List          # noqa: E402
from Autodesk.Revit import DB                         # noqa: E402

import wsm_core as core                               # noqa: E402


# ================================================================ ids

def eid_value(element_id):
    """ElementId -> int: .Value from 2024, .IntegerValue as a guarded fallback
    (removed in 2026)."""
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


def wsid_value(workset_id):
    """WorksetId -> int.  WorksetId is not an ElementId; it still carries
    IntegerValue, so try that first and .Value second."""
    if workset_id is None:
        return -1
    try:
        return int(workset_id.IntegerValue)
    except Exception:
        pass
    try:
        return int(workset_id.Value)
    except Exception:
        return -1


def enum_name(value):
    try:
        return core.to_text(value.ToString())
    except Exception:
        return core.to_text(value)


# ================================================================ theme

def canvas_theme(document=None):
    """'dark' / 'light' from Revit's canvas, or None.

    UIThemeManager exists from 2024 and is reached by getattr.  UITheme.Dark
    is 0, so a read is tested with 'is not None', never for truthiness."""
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, "UIThemeManager", None)
    except Exception:
        manager = None
    if manager is not None:
        for name in ("CurrentCanvasTheme", "CurrentTheme"):
            try:
                value = getattr(manager, name)
            except Exception:
                value = None
            if value is None:
                continue
            text = enum_name(value).lower()
            if "dark" in text:
                return "dark"
            if "light" in text:
                return "light"
    try:
        colour = document.Application.BackgroundColor
        luminance = 0.299 * colour.Red + 0.587 * colour.Green + 0.114 * colour.Blue
        return "dark" if luminance < 128 else "light"
    except Exception:
        return None


# ================================================================ reading

class WorksetRecord(object):
    def __init__(self, workset, active_iid, username):
        self.ws_id = workset.Id
        self.iid = wsid_value(workset.Id)
        self.name = core.to_text(workset.Name)
        self.editable = False
        self.owner = u""
        self.is_open = True
        try:
            self.editable = bool(workset.IsEditable)
        except Exception:
            pass
        try:
            self.owner = core.to_text(workset.Owner)
        except Exception:
            pass
        try:
            self.is_open = bool(workset.IsOpen)
        except Exception:
            pass
        self.visible = True
        try:
            self.visible = bool(workset.IsVisibleByDefault)
        except Exception:
            pass
        self.active = self.iid == active_iid
        self.mine = bool(self.owner) and self.owner.lower() == username.lower()
        self.count = 0
        self.categories = []


def username(document):
    try:
        return core.to_text(document.Application.Username)
    except Exception:
        return u""


def is_workshared(document):
    try:
        return bool(document.IsWorkshared)
    except Exception:
        return False


def active_workset_iid(document):
    try:
        return wsid_value(document.GetWorksetTable().GetActiveWorksetId())
    except Exception:
        return -1


def read_worksets(document):
    """Every user workset, sorted naturally by name."""
    records = []
    if document is None or not is_workshared(document):
        return records
    active = active_workset_iid(document)
    user = username(document)
    try:
        collector = DB.FilteredWorksetCollector(document).OfKind(DB.WorksetKind.UserWorkset)
        for workset in collector:
            records.append(WorksetRecord(workset, active, user))
    except Exception:
        return records
    records.sort(key=lambda r: core.natural_key(r.name))
    return records


def _builtin_category_int(name):
    try:
        bic = getattr(DB.BuiltInCategory, name)
        return eid_value(DB.ElementId(bic))
    except Exception:
        return None


def _param_text(param):
    if param is None:
        return u""
    try:
        if enum_name(param.StorageType) == "String":
            return core.to_text(param.AsString()).strip()
    except Exception:
        pass
    try:
        return core.to_text(param.AsValueString()).strip()
    except Exception:
        return u""


def service_type_of(element, document, cache):
    """Service Type as the model spells it, instance first, then type (cached
    per type - a tray run is thousands of elements on a handful of types)."""
    for name in core.SERVICE_PARAM_NAMES:
        try:
            text = _param_text(element.LookupParameter(name))
        except Exception:
            text = u""
        if text:
            return text
    try:
        type_id = element.GetTypeId()
        type_int = eid_value(type_id)
    except Exception:
        type_id, type_int = None, 0
    if type_int in cache:
        return cache[type_int]
    type_element = None
    try:
        type_element = document.GetElement(type_id)
    except Exception:
        type_element = None
    found = u""
    if type_element is not None:
        for name in core.SERVICE_PARAM_NAMES:
            try:
                found = _param_text(type_element.LookupParameter(name))
            except Exception:
                found = u""
            if found:
                break
    if not found:
        for bip_name in ("RBS_CTC_SERVICE_TYPE",):
            try:
                bip = getattr(DB.BuiltInParameter, bip_name)
            except Exception:
                continue
            for holder in (element, type_element):
                if holder is None:
                    continue
                try:
                    found = _param_text(holder.get_Parameter(bip))
                except Exception:
                    found = u""
                if found:
                    break
            if found:
                break
    cache[type_int] = found or core.NO_SERVICE
    return cache[type_int]


def scan_model(document, hide_empty=True, subgroup_services=True):
    """One pass over the model: element count per workset, the model
    categories in use, the elements behind each, and Service Type sub groups
    under cable tray and cable tray fittings."""
    scan = core.ModelScan()
    if document is None:
        scan.error = u"No document is open."
        return scan
    subgroup_ints = []
    if subgroup_services:
        for name in core.SUBGROUP_BICS:
            value = _builtin_category_int(name)
            if value is not None:
                subgroup_ints.append(value)

    try:
        elements = list(DB.FilteredElementCollector(document).WhereElementIsNotElementType())
    except Exception as err:
        scan.error = u"Could not read the model: {0}".format(err)
        return scan

    names = {}
    by_cat = {}
    by_svc = {}
    cache = {}
    for element in elements:
        try:
            ws_int = wsid_value(element.WorksetId)
        except Exception:
            ws_int = -1
        try:
            category = element.Category
        except Exception:
            category = None
        if ws_int >= 0:
            # every element counts here, whatever its category, so a workset's
            # breakdown always adds up to its Elements figure
            scan.workset_counts[ws_int] = scan.workset_counts.get(ws_int, 0) + 1
            label = core.NO_CATEGORY
            if category is not None:
                try:
                    label = core.to_text(category.Name) or core.NO_CATEGORY
                except Exception:
                    label = core.NO_CATEGORY
            per = scan.workset_categories.setdefault(ws_int, {})
            per[label] = per.get(label, 0) + 1
        try:
            if element.ViewSpecific:
                continue
        except Exception:
            pass
        if category is None:
            continue
        try:
            if enum_name(category.CategoryType) != "Model":
                continue
        except Exception:
            continue
        cat_int = eid_value(category.Id)
        if not cat_int:
            continue
        if cat_int not in names:
            names[cat_int] = core.to_text(category.Name)
            by_cat[cat_int] = []
        by_cat[cat_int].append(element.Id)
        scan.total += 1
        if cat_int in subgroup_ints:
            service = service_type_of(element, document, cache)
            by_svc.setdefault((cat_int, service), []).append(element.Id)

    for cat_int in names:
        ids = by_cat.get(cat_int, [])
        if hide_empty and not ids:
            continue
        key = u"cat:{0}".format(cat_int)
        entry = core.CategoryEntry(key, names[cat_int], len(ids))
        entry.element_ids = ids
        scan.add(entry)
        if cat_int in subgroup_ints:
            for (owner_int, service), child_ids in by_svc.items():
                if owner_int != cat_int:
                    continue
                child = core.CategoryEntry(u"svc:{0}:{1}".format(cat_int, service),
                                           service, len(child_ids), key)
                child.element_ids = child_ids
                scan.add(child)
    scan.finish()
    return scan


def read_model(document, settings):
    records = read_worksets(document)
    scan = scan_model(document,
                      core.as_bool(settings.get("hide_empty_categories"), True),
                      core.as_bool(settings.get("subgroup_service_type"), True))
    for record in records:
        record.count = scan.workset_counts.get(record.iid, 0)
        record.categories = core.category_breakdown(
            scan.workset_categories.get(record.iid, {}))
    return records, scan


# ================================================================ failures

class WarningSwallower(DB.IFailuresPreprocessor):
    """Deletes warnings so a bulk write never stops on a dialog; errors are
    left for Revit, which rolls the transaction back and says why."""

    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def _transaction(document, name):
    transaction = DB.Transaction(document, name)
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction


def _committed(status):
    return enum_name(status) == "Committed"


# ================================================================ checking out

def checkout_worksets(document, ws_ids, log):
    """Make worksets editable.  Outside any transaction.  Returns the set of
    workset ints that are editable afterwards - read back, never assumed."""
    wanted = [w for w in ws_ids if w is not None]
    if not wanted or not is_workshared(document):
        return set()
    collection = List[DB.WorksetId]()
    for ws_id in wanted:
        collection.Add(ws_id)
    try:
        DB.WorksharingUtils.CheckoutWorksets(document, collection)
    except Exception as err:
        log.add(u"CheckoutWorksets refused: {0}", err)
    editable = set()
    table = document.GetWorksetTable()
    for ws_id in wanted:
        try:
            if table.GetWorkset(ws_id).IsEditable:
                editable.add(wsid_value(ws_id))
        except Exception:
            pass
    log.add(u"Checked out {0} of {1} worksets", len(editable), len(wanted))
    return editable


def checkout_elements(document, element_ids, log):
    """Borrow elements.  Outside any transaction.  Returns the element ints
    the user now holds; only those missing are asked about owners (per
    element GetCheckoutStatus is slow on a big model)."""
    if not element_ids or not is_workshared(document):
        return set(eid_value(e) for e in element_ids)
    collection = List[DB.ElementId]()
    for element_id in element_ids:
        collection.Add(element_id)
    held = set()
    try:
        for element_id in DB.WorksharingUtils.CheckoutElements(document, collection):
            held.add(eid_value(element_id))
    except Exception as err:
        log.add(u"CheckoutElements refused: {0}", err)
    log.add(u"Borrowed {0} of {1} elements", len(held), len(element_ids))
    return held


def owner_of(document, element_id):
    try:
        status = enum_name(DB.WorksharingUtils.GetCheckoutStatus(document, element_id))
    except Exception:
        return u"unknown", u""
    if status != "OwnedByOtherUser":
        return status, u""
    try:
        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(document, element_id)
        return status, core.to_text(info.Owner)
    except Exception:
        return status, u""


# ================================================================ manage worksets

def _records_by_iid(document):
    return dict((record.iid, record) for record in read_worksets(document))


def _delete_settings(target_ws_id):
    """MoveElementsToWorkset, always - this tool never deletes elements."""
    option = getattr(DB.DeleteWorksetOption, "MoveElementsToWorkset")
    return DB.DeleteWorksetSettings(option, target_ws_id)


def apply_manage(document, plan, auto_editable, log):
    """plan from core.build_plan.  Creates and renames in one transaction,
    each delete in its own, all inside one group - one undo step, and one
    refused delete does not lose the rest."""
    result = {
        "created": [], "renamed": [], "deleted": [], "merged": [], "refused": [],
        "checked_out": 0, "error": u"",
    }
    before = _records_by_iid(document)
    log.add(u"Plan: {0} create, {1} rename, {2} delete", len(plan["creates"]),
            len(plan["renames"]), len(plan["deletes"]))

    # 1. check out, outside any transaction
    touch = [item["iid"] for item in plan["renames"]] + \
            [item["iid"] for item in plan["deletes"]]
    needs = [before[iid].ws_id for iid in touch
             if iid in before and not before[iid].editable]
    if needs and auto_editable:
        editable = checkout_worksets(document, needs, log)
        result["checked_out"] = len(editable)
        before = _records_by_iid(document)

    def blocked(iid, verb, name):
        record = before.get(iid)
        if record is None:
            result["refused"].append((name, u"it is no longer in the model"))
            return True
        if record.editable:
            return False
        owner = record.owner
        if owner and owner.lower() != username(document).lower():
            reason = u"{0} has it - it could not be made editable".format(owner)
        elif not auto_editable:
            reason = (u"it is not editable - tick 'Make worksets editable "
                      u"automatically' or press Make editable")
        else:
            reason = u"Revit would not make it editable - synchronise and try again"
        result["refused"].append((u"{0} {1}".format(verb, name), reason))
        return True

    renames = [item for item in plan["renames"]
               if not blocked(item["iid"], u"Rename", item["old"])]
    deletes = [item for item in plan["deletes"]
               if not blocked(item["iid"], u"Merge" if item.get("merge") else u"Delete",
                              item["name"])]

    group = DB.TransactionGroup(document, u"RevoBIM - Workset changes")
    try:
        group.Start()
    except Exception as err:
        result["error"] = u"Could not start: {0}".format(err)
        return result

    any_committed = False
    try:
        # 2a. creates and renames
        if plan["creates"] or renames:
            transaction = _transaction(document, u"RevoBIM - Create and rename worksets")
            transaction.Start()
            for name in plan["creates"]:
                try:
                    if DB.WorksetTable.IsWorksetNameUnique(document, name):
                        DB.Workset.Create(document, name)
                    else:
                        result["refused"].append((u"Create " + name,
                                                  u"a workset of that name exists"))
                except Exception as err:
                    result["refused"].append((u"Create " + name, core.to_text(err)))
            for item in renames:
                try:
                    DB.WorksetTable.RenameWorkset(document, before[item["iid"]].ws_id,
                                                  item["new"])
                except Exception as err:
                    result["refused"].append((u"Rename " + item["old"], core.to_text(err)))
            status = transaction.Commit()
            log.add(u"Create/rename transaction: {0}", enum_name(status))
            if _committed(status):
                any_committed = True
            else:
                result["refused"].append((u"Create and rename",
                                          u"Revit rolled the transaction back"))

        # 2b. deletes, one transaction each
        if deletes:
            now = read_worksets(document)
            by_name = dict((r.name.strip().lower(), r) for r in now)
            by_iid = dict((r.iid, r) for r in now)
            active = active_workset_iid(document)
            for item in deletes:
                target = by_iid.get(item["target_iid"]) if not item["target_new"] else None
                if target is None:
                    target = by_name.get(item["target_name"].strip().lower())
                victim = by_iid.get(item["iid"])
                label = (u"Merge " if item.get("merge") else u"Delete ") + item["name"]
                if victim is None:
                    result["refused"].append((label, u"it is no longer in the model"))
                    continue
                if target is None:
                    result["refused"].append((label, u"{0}, which was to take its "
                                                     u"elements, does not exist".format(
                                                         item["target_name"])))
                    continue
                transaction = _transaction(document, u"RevoBIM - Delete workset")
                transaction.Start()
                try:
                    if active == victim.iid:
                        try:
                            document.GetWorksetTable().SetActiveWorksetId(target.ws_id)
                            active = target.iid
                        except Exception as err:
                            log.add(u"Could not move the active workset: {0}", err)
                    settings = _delete_settings(target.ws_id)
                    if not DB.WorksetTable.CanDeleteWorkset(document, victim.ws_id, settings):
                        transaction.RollBack()
                        result["refused"].append((label, (
                            u"Revit will not delete it - an element on it is "
                            u"borrowed by another user, or it holds the last "
                            u"open view")))
                        continue
                    DB.WorksetTable.DeleteWorkset(document, victim.ws_id, settings)
                    status = transaction.Commit()
                    log.add(u"{0}: {1}", label, enum_name(status))
                    if _committed(status):
                        any_committed = True
                    else:
                        result["refused"].append((label, u"Revit rolled it back"))
                except Exception as err:
                    try:
                        transaction.RollBack()
                    except Exception:
                        pass
                    result["refused"].append((label, core.to_text(err)))

        if any_committed:
            group.Assimilate()
        else:
            group.RollBack()
    except Exception as err:
        try:
            group.RollBack()
        except Exception:
            pass
        result["error"] = core.to_text(err)
        log.add(u"Rolled back: {0}", err)
        return result

    # 3. read back - the counts reported are what exists, not what was asked
    after = read_worksets(document)
    after_iid = dict((r.iid, r) for r in after)
    after_names = set(r.name.strip().lower() for r in after)
    for name in plan["creates"]:
        if name.strip().lower() in after_names:
            result["created"].append(name)
    for item in renames:
        record = after_iid.get(item["iid"])
        if record is not None and record.name == item["new"]:
            result["renamed"].append((item["old"], item["new"]))
        elif not any(r[0].endswith(item["old"]) for r in result["refused"]):
            result["refused"].append((u"Rename " + item["old"],
                                      u"Revit accepted it but the name did not change"))
    for item in deletes:
        if item["iid"] not in after_iid:
            bucket = "merged" if item.get("merge") else "deleted"
            result[bucket].append((item["name"], item["target_name"], item["count"]))
    log.add(u"Read back: {0} created, {1} renamed, {2} deleted, {3} merged",
            len(result["created"]), len(result["renamed"]), len(result["deleted"]),
            len(result["merged"]))
    return result


def make_editable(document, iids, log):
    """The Make editable button: returns (made, refused [(name, reason)])."""
    records = _records_by_iid(document)
    wanted = [records[iid] for iid in iids if iid in records]
    needs = [r.ws_id for r in wanted if not r.editable]
    made = checkout_worksets(document, needs, log) if needs else set()
    after = _records_by_iid(document)
    refused = []
    for record in wanted:
        now = after.get(record.iid)
        if now is not None and not now.editable:
            reason = (u"{0} has it".format(now.owner) if now.owner
                      else u"Revit would not check it out - synchronise and try again")
            refused.append((record.name, reason))
    return made, refused


# ================================================================ assigner

def apply_assignments(document, plan, auto_editable, log):
    """plan: [(workset iid, workset name, [ElementId])].  Borrows what has to
    move, writes the workset parameter in one transaction, then reads every
    element back."""
    result = {"moved": 0, "already": 0, "owned": 0, "not_borrowed": 0,
              "refused": 0, "lines": [], "owners": {}, "error": u""}
    records = _records_by_iid(document)
    targets = {}
    for ws_iid, ws_name, element_ids in plan:
        if ws_iid not in records:
            result["lines"].append(u"{0}: no longer in the model".format(ws_name))
            continue
        for element_id in element_ids:
            targets[eid_value(element_id)] = (element_id, ws_iid, ws_name)

    to_move = []
    for key, (element_id, ws_iid, ws_name) in targets.items():
        element = document.GetElement(element_id)
        if element is None:
            continue
        if wsid_value(element.WorksetId) == ws_iid:
            result["already"] += 1
            continue
        to_move.append((element_id, ws_iid, ws_name))
    log.add(u"{0} elements to move, {1} already in place", len(to_move), result["already"])
    if not to_move:
        return result

    if auto_editable and is_workshared(document):
        held = checkout_elements(document, [m[0] for m in to_move], log)
        keep = []
        for element_id, ws_iid, ws_name in to_move:
            if eid_value(element_id) in held:
                keep.append((element_id, ws_iid, ws_name))
                continue
            status, owner = owner_of(document, element_id)
            if owner:
                result["owned"] += 1
                result["owners"][owner] = result["owners"].get(owner, 0) + 1
            else:
                result["not_borrowed"] += 1
        to_move = keep

    partition = getattr(DB.BuiltInParameter, "ELEM_PARTITION_PARAM")
    transaction = _transaction(document, u"RevoBIM - Assign worksets")
    try:
        transaction.Start()
        for element_id, ws_iid, ws_name in to_move:
            try:
                param = document.GetElement(element_id).get_Parameter(partition)
                if param is None or param.IsReadOnly:
                    result["refused"] += 1
                    continue
                param.Set(ws_iid)
            except Exception:
                result["refused"] += 1
        status = transaction.Commit()
        log.add(u"Assign transaction: {0}", enum_name(status))
        if not _committed(status):
            result["error"] = u"Revit rolled the change back."
            return result
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        result["error"] = core.to_text(err)
        return result

    per_workset = {}
    for element_id, ws_iid, ws_name in to_move:
        element = document.GetElement(element_id)
        if element is not None and wsid_value(element.WorksetId) == ws_iid:
            result["moved"] += 1
            per_workset[ws_name] = per_workset.get(ws_name, 0) + 1
    silent = len(to_move) - result["moved"] - result["refused"]
    if silent > 0:
        result["refused"] += silent
        log.add(u"{0} writes were accepted but did not read back", silent)
    for name in sorted(per_workset.keys(), key=core.natural_key):
        result["lines"].append(u"{0}: {1} moved".format(name, per_workset[name]))
    return result


# ================================================================ the 3D view

VIEW_NAME = u"Workset Management"

# Categories hidden in the view: "no links".
LINK_CATEGORIES = ("OST_RvtLinks", "OST_PointClouds")


def _enum(type_name, member):
    """An enum member looked up when used, by name - never at load."""
    kind = getattr(DB, type_name)
    return getattr(kind, member)


def find_view(document):
    """The tool's own 3D view, or None."""
    try:
        for view in DB.FilteredElementCollector(document).OfClass(DB.View3D):
            try:
                if not view.IsTemplate and core.to_text(view.Name) == VIEW_NAME:
                    return view
            except Exception:
                continue
    except Exception:
        pass
    return None


def make_view(document, log):
    """A new isometric view named for the tool.  Inside a transaction."""
    family_type = None
    for candidate in DB.FilteredElementCollector(document).OfClass(DB.ViewFamilyType):
        try:
            if enum_name(candidate.ViewFamily) == "ThreeDimensional":
                family_type = candidate
                break
        except Exception:
            continue
    if family_type is None:
        raise Exception(u"This model has no 3D view type to make the view from.")
    view = DB.View3D.CreateIsometric(document, family_type.Id)
    taken = set()
    for other in DB.FilteredElementCollector(document).OfClass(DB.View):
        try:
            taken.add(core.to_text(other.Name))
        except Exception:
            continue
    name = VIEW_NAME
    number = 2
    while name in taken:
        name = u"{0} ({1})".format(VIEW_NAME, number)
        number += 1
    view.Name = name
    log.add(u"Made 3D view {0}", name)
    return view


def solid_fill_id(document):
    for pattern in DB.FilteredElementCollector(document).OfClass(DB.FillPatternElement):
        try:
            if pattern.GetFillPattern().IsSolidFill:
                return pattern.Id
        except Exception:
            continue
    return None


def prepare_view(document, view, records, log):
    """Everything showing, links hidden.  Inside a transaction.  Each setting
    is tried on its own: a view refuses some on some releases, and one refusal
    must not stop the rest."""
    def attempt(label, func):
        try:
            func()
        except Exception as err:
            log.add(u"View setting {0} skipped: {1}", label, err)

    attempt("template", lambda: setattr(view, "ViewTemplateId", DB.ElementId.InvalidElementId))
    attempt("section box", lambda: setattr(view, "IsSectionBoxActive", False))
    attempt("discipline", lambda: setattr(view, "Discipline",
                                          _enum("ViewDiscipline", "Coordination")))
    attempt("detail level", lambda: setattr(view, "DetailLevel",
                                            _enum("ViewDetailLevel", "Fine")))
    attempt("display style", lambda: setattr(view, "DisplayStyle",
                                             _enum("DisplayStyle", "ShadingWithEdges")))
    link_ids = set()
    for name in LINK_CATEGORIES:
        try:
            link_ids.add(eid_value(DB.ElementId(getattr(DB.BuiltInCategory, name))))
        except Exception:
            continue
    shown = 0
    for category in document.Settings.Categories:
        try:
            if enum_name(category.CategoryType) != "Model" and \
                    eid_value(category.Id) not in link_ids:
                continue
            if not view.CanCategoryBeHidden(category.Id):
                continue
            hide = eid_value(category.Id) in link_ids
            view.SetCategoryHidden(category.Id, hide)
            if not hide:
                shown += 1
        except Exception:
            continue
    for record in records:
        attempt(u"workset " + record.name, lambda r=record: view.SetWorksetVisibility(
            r.ws_id, _enum("WorksetVisibility", "Visible")))
    # CAD links are import instances rather than a category of their own
    cad = List[DB.ElementId]()
    try:
        for instance in DB.FilteredElementCollector(document).OfClass(DB.ImportInstance):
            try:
                if instance.IsLinked and instance.CanBeHidden(view):
                    cad.Add(instance.Id)
            except Exception:
                continue
        if cad.Count:
            view.HideElements(cad)
    except Exception as err:
        log.add(u"CAD links not hidden: {0}", err)
    log.add(u"View prepared: {0} categories on, {1} CAD links hidden", shown, cad.Count)


def workset_elements(document, view, ws_id):
    """Elements on one workset that the view shows."""
    collector = DB.FilteredElementCollector(document, view.Id)
    collector = collector.WherePasses(DB.ElementWorksetFilter(ws_id))
    return [element for element in collector.WhereElementIsNotElementType()
            if element.Category is not None]


def colour_settings(rgb, solid_id):
    colour = DB.Color(rgb[0], rgb[1], rgb[2])
    settings = DB.OverrideGraphicSettings()
    for name, value in (("SetProjectionLineColor", colour), ("SetCutLineColor", colour),
                        ("SetSurfaceForegroundPatternColor", colour),
                        ("SetCutForegroundPatternColor", colour)):
        try:
            getattr(settings, name)(value)
        except Exception:
            pass
    if solid_id is not None:
        for name in ("SetSurfaceForegroundPatternId", "SetCutForegroundPatternId"):
            try:
                getattr(settings, name)(solid_id)
            except Exception:
                pass
        for name in ("SetSurfaceForegroundPatternVisible", "SetCutForegroundPatternVisible"):
            try:
                getattr(settings, name)(True)
            except Exception:
                pass
    return settings


def colour_view(document, view, records, colours, log):
    """Every element the view shows takes its workset's colour.  Inside a
    transaction; prepare_view's transaction must have been committed first
    (a commit regenerates), so the collector sees what is now visible."""
    solid_id = solid_fill_id(document)
    counts = {}
    for record in records:
        rgb = core.hex_rgb(colours.get(record.iid, u""))
        if rgb is None:
            continue
        settings = colour_settings(rgb, solid_id)
        done = 0
        for element in workset_elements(document, view, record.ws_id):
            try:
                view.SetElementOverrides(element.Id, settings)
                done += 1
            except Exception:
                continue
        counts[record.name] = done
    log.add(u"Coloured {0} elements over {1} worksets", sum(counts.values()), len(counts))
    return counts


def reset_isolate(view):
    """Clear a temporary isolate - and Reveal Hidden Elements, which otherwise
    leaves hidden elements showing through the next isolate."""
    view.DisableTemporaryViewMode(_enum("TemporaryViewMode", "TemporaryHideIsolate"))
    try:
        view.DisableTemporaryViewMode(_enum("TemporaryViewMode", "RevealHiddenElements"))
    except Exception:
        pass


def is_isolated(view):
    try:
        return bool(view.IsTemporaryHideIsolateActive())
    except Exception:
        return False


def active_uidoc(uiapp, document):
    """The UIDocument for this document, only when it is the active one: view
    work needs it on screen."""
    try:
        uidoc = uiapp.ActiveUIDocument
        if uidoc is not None and uidoc.Document.Equals(document):
            return uidoc
    except Exception:
        pass
    return None


def show_view(uidoc, view, direct):
    """Bring the view up.  From a modeless window the change is requested and
    happens once the job has returned; from a dialog it can be set straight."""
    try:
        if uidoc.ActiveView is not None and uidoc.ActiveView.Id.Equals(view.Id):
            return
    except Exception:
        pass
    if direct:
        try:
            uidoc.ActiveView = view
            return
        except Exception:
            pass
    uidoc.RequestViewChange(view)


def zoom_view(uidoc, view_id):
    for ui_view in uidoc.GetOpenUIViews():
        try:
            if ui_view.ViewId.Equals(view_id):
                ui_view.ZoomToFit()
                return True
        except Exception:
            continue
    return False


def show_in_3d(uiapp, document, colours, direct, log):
    """Find or make the view, show everything but links, colour by workset,
    put it on screen.  One TransactionGroup: one undo step."""
    uidoc = active_uidoc(uiapp, document)
    if uidoc is None:
        raise ToolStop(u"Switch to {0} first - the 3D view opens in the active "
                       u"model.".format(core.to_text(document.Title)))
    records = read_worksets(document)
    group = DB.TransactionGroup(document, u"RevoBIM - Workset Management 3D view")
    group.Start()
    try:
        transaction = _transaction(document, u"RevoBIM - Prepare the 3D view")
        transaction.Start()
        view = find_view(document)
        made = view is None
        if made:
            view = make_view(document, log)
        if is_isolated(view):
            reset_isolate(view)
        prepare_view(document, view, records, log)
        if not _committed(transaction.Commit()):
            raise Exception(u"Revit would not set the view up.")
        transaction = _transaction(document, u"RevoBIM - Colour by workset")
        transaction.Start()
        counts = colour_view(document, view, records, colours, log)
        if not _committed(transaction.Commit()):
            raise Exception(u"Revit would not colour the view.")
        group.Assimilate()
    except Exception:
        try:
            group.RollBack()
        except Exception:
            pass
        raise
    show_view(uidoc, view, direct)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return {"view_id": view.Id, "made": made, "counts": counts,
            "name": core.to_text(view.Name)}


def isolate_worksets(uiapp, document, iids, direct, log):
    """Temporary isolate of the elements on these worksets in the tool's view.
    Reset in its own committed transaction first - a leftover isolate shows
    through a new one otherwise - then collect what the view shows, then
    isolate, all in one group."""
    uidoc = active_uidoc(uiapp, document)
    if uidoc is None:
        raise ToolStop(u"Switch to {0} first.".format(core.to_text(document.Title)))
    view = find_view(document)
    if view is None:
        raise ToolStop(u"Press Show in 3D first - it makes the Workset Management view.")
    wanted = set(iids)
    records = [r for r in read_worksets(document) if r.iid in wanted]
    group = DB.TransactionGroup(document, u"RevoBIM - Isolate worksets")
    group.Start()
    try:
        transaction = _transaction(document, u"RevoBIM - Reset isolate")
        transaction.Start()
        reset_isolate(view)
        if not _committed(transaction.Commit()):
            raise Exception(u"Revit would not reset the view.")
        ids = List[DB.ElementId]()
        per = {}
        for record in records:
            found = workset_elements(document, view, record.ws_id)
            per[record.name] = len(found)
            for element in found:
                ids.Add(element.Id)
        if not ids.Count:
            group.RollBack()
            raise ToolStop(u"Nothing on those worksets shows in the Workset Management view.")
        transaction = _transaction(document, u"RevoBIM - Isolate worksets")
        transaction.Start()
        view.IsolateElementsTemporary(ids)
        if not _committed(transaction.Commit()):
            raise Exception(u"Revit would not isolate the elements.")
        group.Assimilate()
    except ToolStop:
        raise
    except Exception:
        try:
            group.RollBack()
        except Exception:
            pass
        raise
    show_view(uidoc, view, direct)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    log.add(u"Isolated {0} elements on {1} worksets", ids.Count, len(records))
    return {"view_id": view.Id, "count": ids.Count, "per": per,
            "isolated": is_isolated(view)}


def unisolate(uiapp, document, log):
    view = find_view(document)
    if view is None or not is_isolated(view):
        return {"done": False}
    transaction = _transaction(document, u"RevoBIM - Un-isolate")
    transaction.Start()
    reset_isolate(view)
    status = transaction.Commit()
    try:
        uidoc = active_uidoc(uiapp, document)
        if uidoc is not None:
            uidoc.RefreshActiveView()
    except Exception:
        pass
    log.add(u"Un-isolate: {0}", enum_name(status))
    return {"done": _committed(status) and not is_isolated(view)}


class ToolStop(Exception):
    """A refusal to report to the user as it stands, not as a fault."""


# ================================================================ scope boxes

class ScopeRecord(object):
    def __init__(self, element):
        self.element_id = element.Id
        self.eid = eid_value(element.Id)
        self.name = element_name(element)
        self.views = []
        self.datums = []
        self.users = []           # ElementIds of the views and datums using it
        self.workset = u""


def element_name(element):
    """Element.Name raises AttributeError on some elements in IronPython - every
    read is guarded, with the name parameter as a second route."""
    try:
        return core.to_text(element.Name)
    except Exception:
        pass
    try:
        param = element.get_Parameter(getattr(DB.BuiltInParameter, "VOLUME_OF_INTEREST_NAME"))
        return core.to_text(param.AsString())
    except Exception:
        return u""


def set_element_name(element, name):
    """Every route to a name, then read back - which route works varies with
    the IronPython version and none reliably raises when it does nothing."""
    routes = []
    try:
        param = element.get_Parameter(getattr(DB.BuiltInParameter, "VOLUME_OF_INTEREST_NAME"))
        if param is not None and not param.IsReadOnly:
            routes.append(lambda: param.Set(name))
    except Exception:
        pass
    routes.append(lambda: setattr(element, "Name", name))
    routes.append(lambda: DB.Element.Name.SetValue(element, name))
    last = None
    for route in routes:
        try:
            route()
        except Exception as err:
            last = err
            continue
        if element_name(element) == name:
            return u""
    return core.to_text(last) if last is not None else u"Revit did not take the name"


def _scope_of(element, bip_name):
    try:
        param = element.get_Parameter(getattr(DB.BuiltInParameter, bip_name))
        if param is None:
            return 0
        return eid_value(param.AsElementId())
    except Exception:
        return 0


def read_scope_boxes(document):
    """Every scope box, with the views, levels, grids and reference planes
    using it."""
    records = {}
    category = getattr(DB.BuiltInCategory, "OST_VolumeOfInterest")
    for element in DB.FilteredElementCollector(document).OfCategory(category) \
            .WhereElementIsNotElementType():
        record = ScopeRecord(element)
        try:
            workset = document.GetWorksetTable().GetWorkset(element.WorksetId)
            record.workset = core.to_text(workset.Name)
        except Exception:
            pass
        records[record.eid] = record
    if not records:
        return []

    for view in DB.FilteredElementCollector(document).OfClass(DB.View):
        try:
            if view.IsTemplate:
                continue
        except Exception:
            continue
        owner = records.get(_scope_of(view, "VIEWER_VOLUME_OF_INTEREST_CROP"))
        if owner is not None:
            owner.views.append(element_name(view))
            owner.users.append(view.Id)

    labels = (("OST_Levels", u"Level"), ("OST_Grids", u"Grid"), ("OST_CLines", u"Ref plane"))
    for bic_name, label in labels:
        try:
            datum_category = getattr(DB.BuiltInCategory, bic_name)
            datums = DB.FilteredElementCollector(document).OfCategory(datum_category) \
                .WhereElementIsNotElementType()
        except Exception:
            continue
        for datum in datums:
            owner = records.get(_scope_of(datum, "DATUM_VOLUME_OF_INTEREST"))
            if owner is not None:
                owner.datums.append(u"{0} {1}".format(label, element_name(datum)))
                owner.users.append(datum.Id)
    out = list(records.values())
    out.sort(key=lambda r: core.natural_key(r.name))
    return out


def apply_scope(document, plan, auto_editable, log):
    """Deletes then renames - so a name a delete frees can be taken in the same
    Apply.  Borrow first, outside any transaction: the scope boxes, and for a
    delete every view and datum using it, since deleting rewrites them.  Each
    delete in its own transaction, the renames in one, all in one group.  Then
    read back."""
    result = {"deleted": [], "renamed": [], "refused": [], "error": u""}
    by_eid = dict((r.eid, r) for r in read_scope_boxes(document))

    wanted = []
    for item in plan["deletes"]:
        record = by_eid.get(item["eid"])
        if record is not None:
            wanted.append(record.element_id)
            wanted.extend(record.users)
    for item in plan["renames"]:
        record = by_eid.get(item["eid"])
        if record is not None:
            wanted.append(record.element_id)

    blocked = {}
    if auto_editable and is_workshared(document) and wanted:
        held = checkout_elements(document, wanted, log)
        for element_id in wanted:
            if eid_value(element_id) not in held:
                status, owner = owner_of(document, element_id)
                blocked[eid_value(element_id)] = owner or u"Revit would not lend it"

    def refusal(item, verb):
        record = by_eid.get(item["eid"])
        if record is None:
            return u"it is no longer in the model"
        ids = [record.element_id] + (record.users if verb == u"Delete" else [])
        for element_id in ids:
            who = blocked.get(eid_value(element_id))
            if who:
                if element_id is record.element_id:
                    return u"{0} has it".format(who)
                return u"{0} has a view or datum that uses it".format(who)
        return u""

    group = DB.TransactionGroup(document, u"RevoBIM - Scope box changes")
    group.Start()
    any_committed = False
    try:
        for item in plan["deletes"]:
            label = u"Delete " + item["name"]
            why = refusal(item, u"Delete")
            if why:
                result["refused"].append((label, why))
                continue
            transaction = _transaction(document, u"RevoBIM - Delete scope box")
            transaction.Start()
            try:
                document.Delete(by_eid[item["eid"]].element_id)
                status = transaction.Commit()
                if _committed(status):
                    any_committed = True
                else:
                    result["refused"].append((label, u"Revit rolled it back"))
            except Exception as err:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                result["refused"].append((label, core.to_text(err)))

        renames = []
        for item in plan["renames"]:
            why = refusal(item, u"Rename")
            if why:
                result["refused"].append((u"Rename " + item["old"], why))
            else:
                renames.append(item)
        if renames:
            transaction = _transaction(document, u"RevoBIM - Rename scope boxes")
            transaction.Start()
            for item in renames:
                element = document.GetElement(by_eid[item["eid"]].element_id)
                problem = set_element_name(element, item["new"]) if element is not None \
                    else u"it is no longer in the model"
                if problem:
                    result["refused"].append((u"Rename " + item["old"], problem))
            if _committed(transaction.Commit()):
                any_committed = True
            else:
                result["refused"].append((u"Rename", u"Revit rolled the renames back"))
        if any_committed:
            group.Assimilate()
        else:
            group.RollBack()
    except Exception as err:
        try:
            group.RollBack()
        except Exception:
            pass
        result["error"] = core.to_text(err)
        return result

    after = dict((r.eid, r) for r in read_scope_boxes(document))
    for item in plan["deletes"]:
        if item["eid"] not in after and item["eid"] in by_eid:
            result["deleted"].append(item["name"])
    for item in plan["renames"]:
        record = after.get(item["eid"])
        if record is not None and record.name == item["new"]:
            result["renamed"].append((item["old"], item["new"]))
    log.add(u"Scope boxes read back: {0} deleted, {1} renamed", len(result["deleted"]),
            len(result["renamed"]))
    return result
