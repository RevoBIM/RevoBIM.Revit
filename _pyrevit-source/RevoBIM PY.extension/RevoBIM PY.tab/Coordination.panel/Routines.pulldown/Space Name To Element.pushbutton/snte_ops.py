# -*- coding: utf-8 -*-
"""Every write, the transactions and the ExternalEvent.

A modeless window cannot start a transaction directly, so everything that
touches the model goes out through an ExternalEvent whose handler runs in
Revit's own API context.
"""

import snte_clr  # noqa: F401  - must be first

from System.Collections.Generic import List

from Autodesk.Revit import DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import snte_core as core


# ---------------------------------------------------------------------------
#  External event plumbing
# ---------------------------------------------------------------------------
class SnteEventHandler(IExternalEventHandler):
    """Runs whatever callable the window parked on it, in Revit's API context."""

    def __init__(self):
        self.job = None
        self.on_error = None

    def Execute(self, uiapp):
        job = self.job
        self.job = None
        if job is None:
            return
        try:
            job(uiapp)
        except Exception:
            import traceback
            if self.on_error is not None:
                try:
                    self.on_error(traceback.format_exc())
                except Exception:
                    pass

    def GetName(self):
        return "RevoBIM Space Name To Element"


def make_event():
    handler = SnteEventHandler()
    return handler, ExternalEvent.Create(handler)


# ---------------------------------------------------------------------------
#  Results
# ---------------------------------------------------------------------------
class RunResult(object):
    def __init__(self):
        self.written = 0
        self.unchanged = 0
        self.cleared = 0
        self.no_param = 0
        self.skipped_filled = 0
        self.no_space = 0
        self.locked = 0
        self.missing_by_cat = {}
        self.locked_names = []
        self.bound_added = []
        self.bound_failed = []
        self.spaces_no_geometry = 0
        self.cancelled = False
        self.error = None

    @property
    def touched(self):
        return self.written + self.cleared


# ---------------------------------------------------------------------------
#  Failure handling
# ---------------------------------------------------------------------------
class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == DB.FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def _transaction(doc, name):
    trans = DB.Transaction(doc, name)
    trans.Start()
    try:
        opts = trans.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        opts.SetClearAfterRollback(True)
        trans.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return trans


# ---------------------------------------------------------------------------
#  Binding a parameter to more categories
# ---------------------------------------------------------------------------
def bind_missing_categories(doc, param_opt, cat_nodes, result):
    """Add the ticked categories to the parameter's existing instance binding."""
    missing = [c for c in cat_nodes
               if not param_opt.bound_to(c.cat_id_value)]
    if not missing:
        return

    if param_opt.builtin or param_opt.definition is None:
        # a built-in parameter has no project binding that can be edited
        result.bound_failed.extend([c.name for c in missing])
        return

    bmap = doc.ParameterBindings
    definition = param_opt.definition
    try:
        binding = bmap.get_Item(definition)
    except Exception:
        binding = None
    if binding is None or not isinstance(binding, DB.InstanceBinding):
        result.bound_failed.extend([c.name for c in missing])
        return

    new_set = doc.Application.Create.NewCategorySet()
    try:
        for cat in binding.Categories:
            new_set.Insert(cat)
    except Exception:
        pass

    added = []
    for cnode in missing:
        try:
            cat = DB.Category.GetCategory(doc, cnode.cat_id)
        except Exception:
            cat = None
        if cat is None or not cat.AllowsBoundParameters:
            result.bound_failed.append(cnode.name)
            continue
        if new_set.Insert(cat):
            added.append(cnode.name)
        else:
            result.bound_failed.append(cnode.name)

    if not added:
        return

    trans = _transaction(doc, "RevoBIM - Bind parameter to categories")
    try:
        new_binding = doc.Application.Create.NewInstanceBinding(new_set)
        ok = False
        try:
            ok = bmap.ReInsert(definition, new_binding,
                               definition.GetGroupTypeId())
        except Exception:
            try:
                ok = bmap.ReInsert(definition, new_binding)
            except Exception:
                ok = False
        if ok:
            trans.Commit()
            doc.Regenerate()
            result.bound_added.extend(added)
            for cnode in cat_nodes:
                param_opt.cat_ids.add(cnode.cat_id_value)
        else:
            trans.RollBack()
            result.bound_failed.extend(added)
    except Exception:
        try:
            trans.RollBack()
        except Exception:
            pass
        result.bound_failed.extend(added)


# ---------------------------------------------------------------------------
#  Phase 1 - which spaces each element is in
# ---------------------------------------------------------------------------
def build_space_map(doc, spaces, element_ids, result, progress, cancelled):
    """{element id value: [space labels]} for the chosen elements."""
    mapping = {}
    if not element_ids:
        return mapping

    all_ids = List[DB.ElementId]()
    for eid in element_ids:
        all_ids.Add(eid)

    opts = core.geometry_options()
    total = len(spaces)

    for index, space in enumerate(spaces):
        if cancelled():
            result.cancelled = True
            return mapping
        progress(index + 1, total)

        label = core.space_label(space)
        if not label:
            continue

        bbox = space.get_BoundingBox(None)
        if bbox is None:
            continue

        try:
            bb_filter = DB.BoundingBoxIntersectsFilter(
                DB.Outline(bbox.Min, bbox.Max))
            near_ids = DB.FilteredElementCollector(doc, all_ids) \
                .WherePasses(bb_filter).ToElementIds()
        except Exception:
            continue
        if near_ids.Count == 0:
            continue

        solids = core.get_space_solids(space, opts)
        if not solids:
            result.spaces_no_geometry += 1
            continue

        near_list = List[DB.ElementId](near_ids)
        hits = set()
        for solid in solids:
            try:
                sfilter = DB.ElementIntersectsSolidFilter(solid)
                for eid in DB.FilteredElementCollector(doc, near_list) \
                        .WherePasses(sfilter).ToElementIds():
                    hits.add(core.eid_value(eid))
            except Exception:
                continue

        for key in hits:
            labels = mapping.get(key)
            if labels is None:
                mapping[key] = [label]
            elif label not in labels:
                labels.append(label)

    return mapping


# ---------------------------------------------------------------------------
#  Phase 2 - write the values
# ---------------------------------------------------------------------------
def _checkout(doc, ids):
    """Borrow the elements up front - a write to an element that has not been
    borrowed writes nothing and says nothing, because Revit asks in a dialog
    and a run suppressing dialogs answers it."""
    try:
        if not doc.IsWorkshared:
            return
        wanted = List[DB.ElementId]()
        for eid in ids:
            wanted.Add(eid)
        DB.WorksharingUtils.CheckoutElements(doc, wanted)
    except Exception:
        pass


def _is_locked(doc, element):
    try:
        if not doc.IsWorkshared:
            return None
        status = DB.WorksharingUtils.GetCheckoutStatus(doc, element.Id)
        if status == DB.CheckoutStatus.OwnedByOtherUser:
            try:
                info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, element.Id)
                return info.Owner or "another user"
            except Exception:
                return "another user"
        # nobody has borrowed it but its workset may still be owned
        wtable = doc.GetWorksetTable()
        workset = wtable.GetWorkset(element.WorksetId)
        owner = workset.Owner
        if owner and owner.strip() and owner.strip().lower() != \
                (doc.Application.Username or "").strip().lower():
            return owner
    except Exception:
        pass
    return None


def write_values(doc, element_ids, mapping, param_name, options, result,
                 progress, cancelled):
    chunk_size = options.get("chunk_size", 200)
    overwrite = options.get("overwrite", True)
    clear_empty = options.get("clear_empty", False)

    total = len(element_ids)
    if not total:
        return

    _checkout(doc, element_ids)

    group = DB.TransactionGroup(doc, "RevoBIM - Space Name To Element")
    group.Start()
    try:
        done = 0
        index = 0
        while index < total:
            if cancelled():
                result.cancelled = True
                break

            chunk = element_ids[index:index + chunk_size]
            index += chunk_size

            # no dispatcher pumping between Start and Commit - letting Revit's
            # message loop run inside an open transaction can leave the write
            # with nothing committed
            trans = _transaction(doc, "Space name to element")
            try:
                for eid in chunk:
                    element = doc.GetElement(eid)
                    if element is None:
                        continue

                    labels = mapping.get(core.eid_value(eid))
                    if labels:
                        labels = sorted(labels, key=core.natural_key)
                        value = core.SPACE_DELIM.join(labels)
                    else:
                        result.no_space += 1
                        if not clear_empty:
                            continue
                        value = ""

                    prm = core.get_target_param(element, param_name)
                    if prm is None:
                        result.no_param += 1
                        _note_missing(element, result)
                        continue

                    current = prm.AsString() or ""
                    if current == value:
                        result.unchanged += 1
                        continue
                    if current and not overwrite:
                        result.skipped_filled += 1
                        continue

                    owner = _is_locked(doc, element)
                    if owner:
                        result.locked += 1
                        if owner not in result.locked_names:
                            result.locked_names.append(owner)
                        continue

                    try:
                        prm.Set(value)
                    except Exception:
                        result.no_param += 1
                        _note_missing(element, result)
                        continue

                    # prove the write - Revit does not reliably raise when a
                    # value does not take
                    check = core.get_target_param(element, param_name)
                    landed = (check.AsString() or "") if check else None
                    if landed != value:
                        result.no_param += 1
                        _note_missing(element, result)
                        continue

                    if value:
                        result.written += 1
                    else:
                        result.cleared += 1

                status = trans.Commit()
                if status != DB.TransactionStatus.Committed:
                    result.error = "A chunk of {0} elements did not commit." \
                        .format(len(chunk))
            except Exception:
                try:
                    trans.RollBack()
                except Exception:
                    pass
                raise

            done += len(chunk)
            progress(min(done, total), total)   # between transactions only

        group.Assimilate()
    except Exception:
        try:
            if group.GetStatus() == DB.TransactionStatus.Started:
                group.RollBack()
        except Exception:
            pass
        raise


def _note_missing(element, result):
    try:
        cname = element.Category.Name
    except Exception:
        cname = "<unknown>"
    result.missing_by_cat[cname] = result.missing_by_cat.get(cname, 0) + 1


# ---------------------------------------------------------------------------
#  The whole run
# ---------------------------------------------------------------------------
def run_transfer(doc, cat_nodes, param_opt, options, progress, cancelled):
    """Bind, scan and write. Returns a RunResult."""
    result = RunResult()

    if options.get("auto_bind", True):
        progress(0, 1, "Checking parameter bindings")
        bind_missing_categories(doc, param_opt, cat_nodes, result)

    spaces = core.get_placed_spaces(doc)
    element_ids = core.selected_element_ids(cat_nodes)

    def scan_progress(done, total):
        progress(done, total, "Scanning spaces")

    mapping = build_space_map(doc, spaces, element_ids, result,
                              scan_progress, cancelled)
    if result.cancelled:
        return result

    def write_progress(done, total):
        progress(done, total, "Writing values")

    write_values(doc, element_ids, mapping, param_opt.name, options, result,
                 write_progress, cancelled)
    return result
