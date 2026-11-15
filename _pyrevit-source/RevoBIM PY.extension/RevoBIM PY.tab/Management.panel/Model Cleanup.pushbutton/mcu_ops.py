# -*- coding: utf-8 -*-
"""Every write the tool makes.

The window is modal, so these run inside the command's own API context and
need no ExternalEvent. Progress is only ever reported between transactions:
pumping the dispatcher inside an open transaction can leave it with nothing
committed.
"""
import os
import time

import mcu_clr  # noqa: F401 - must come before any System.* / Autodesk.* import
import mcu_core as core
import mcu_model as model

from System import EventHandler
from System.Collections.Generic import List, HashSet
from System.IO import File
from Autodesk.Revit.DB import (Transaction, TransactionGroup, TransactionStatus,
                               ElementId, IFailuresPreprocessor,
                               FailureProcessingResult, FailureSeverity,
                               OpenOptions, DetachFromCentralOption,
                               WorksetConfiguration, WorksetConfigurationOption,
                               SaveAsOptions, WorksharingSaveAsOptions,
                               SaveOptions, TransactWithCentralOptions,
                               SynchronizeWithCentralOptions, RelinquishOptions,
                               ModelPathUtils, WorksharingUtils,
                               FilteredWorksetCollector, WorksetKind, WorksetId)
from Autodesk.Revit.UI.Events import DialogBoxShowingEventArgs


def to_element_id(value):
    """ElementId(Int64) on 2024+; the int constructor is the fallback."""
    try:
        from System import Int64
        return ElementId(Int64(value))
    except Exception:
        return ElementId(int(value))


# ============================================================
# dialogs and warnings
# ============================================================

class DialogSuppressor(object):
    """Answers any Revit dialog raised during a run and records it.

    The delegate object is created once and the same object is removed
    again - removing a fresh bound-method delegate from a .NET event is not
    reliable in IronPython."""

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.seen = []
        self.active = False
        self.delegate = EventHandler[DialogBoxShowingEventArgs](self._on_dialog)
        self.hooked = False

    def _on_dialog(self, sender, args):
        if not self.active:
            return
        try:
            self.seen.append(core.to_text(args.DialogId))
        except Exception:
            self.seen.append(u"(unnamed dialog)")
        try:
            args.OverrideResult(1)
        except Exception:
            pass

    def __enter__(self):
        self.active = True
        if not self.hooked:
            try:
                self.uiapp.DialogBoxShowing += self.delegate
                self.hooked = True
            except Exception:
                self.hooked = False
        return self

    def __exit__(self, kind, value, trace):
        self.active = False
        if self.hooked:
            try:
                self.uiapp.DialogBoxShowing -= self.delegate
                self.hooked = False
            except Exception:
                pass
        if self.seen:
            core.log(u"dialogs answered: " + u", ".join(self.seen))
        return False


class RollbackOnError(IFailuresPreprocessor):
    """Warnings deleted; any error rolls the transaction back so the caller
    can replay one element at a time."""

    def PreprocessFailures(self, accessor):
        has_error = False
        try:
            for message in accessor.GetFailureMessages():
                if message.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(message)
                else:
                    has_error = True
        except Exception:
            has_error = True
        if has_error:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def _start(doc, name):
    transaction = Transaction(doc, name)
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(RollbackOnError())
    options.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(options)
    transaction.Start()
    return transaction


def _finish(transaction):
    try:
        status = transaction.Commit()
    except Exception:
        try:
            if transaction.HasStarted() and not transaction.HasEnded():
                transaction.RollBack()
        except Exception:
            pass
        return False
    return status == TransactionStatus.Committed


# ============================================================
# step 1 - sync or save
# ============================================================

def sync_current(uiapp, doc, comment, relinquish, compact):
    if not doc.IsWorkshared:
        if not core.to_text(doc.PathName):
            return False, u"This model has never been saved. Save it in Revit first."
        with DialogSuppressor(uiapp):
            doc.Save()
        return True, u"Saved " + model.model_title(doc)

    transact = TransactWithCentralOptions()
    options = SynchronizeWithCentralOptions()
    options.SetRelinquishOptions(RelinquishOptions(bool(relinquish)))
    options.Comment = core.to_text(comment)
    options.Compact = bool(compact)
    try:
        options.SaveLocalBefore = True
        options.SaveLocalAfter = True
    except Exception:
        pass
    with DialogSuppressor(uiapp) as dialogs:
        doc.SynchronizeWithCentral(transact, options)
    note = u""
    if dialogs.seen:
        note = u" (Revit asked {0} question(s), answered automatically)".format(len(dialogs.seen))
    return True, u"Synced with central" + note


# ============================================================
# step 2 - the send copy
# ============================================================

def _save_as(doc, target, compact):
    options = SaveAsOptions()
    options.OverwriteExistingFile = True
    try:
        options.Compact = bool(compact)
    except Exception:
        pass
    if doc.IsWorkshared:
        sharing = WorksharingSaveAsOptions()
        sharing.SaveAsCentral = True
        options.SetWorksharingOptions(sharing)
    doc.SaveAs(target, options)


class SaveAsFailed(Exception):
    """The detached copy opened but could not be saved where asked."""


def open_detached_copy(uiapp, doc, target, template, on_stage=None):
    """Open the central detached, save it to `target`, return the new
    (background) document. The live model is never modified.
    on_stage(label, fraction) is called between the open and the save."""
    def stage(label, fraction):
        if on_stage is not None:
            try:
                on_stage(label, fraction)
            except Exception:
                pass

    app = uiapp.Application
    preserve = template.get(u"detach_mode") != core.DETACH_DISCARD
    compact = core.as_bool(template.get(u"compact"), True)
    with DialogSuppressor(uiapp):
        if doc.IsWorkshared:
            source = model.central_path(doc)
            if source is None:
                raise RuntimeError(u"The central model path could not be read.")
            options = OpenOptions()
            if preserve:
                options.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
            else:
                options.DetachFromCentralOption = DetachFromCentralOption.DetachAndDiscardWorksets
            options.Audit = core.as_bool(template.get(u"audit"), False)
            try:
                options.SetOpenWorksetsConfiguration(
                    WorksetConfiguration(WorksetConfigurationOption.OpenAllWorksets))
            except Exception:
                pass
            copy = app.OpenDocumentFile(source, options)
        else:
            stage(u"Copying the model file", 0.1)
            File.Copy(doc.PathName, target, True)
            path = ModelPathUtils.ConvertUserVisiblePathToModelPath(target)
            options = OpenOptions()
            options.Audit = core.as_bool(template.get(u"audit"), False)
            stage(u"Opening the copied file", 0.4)
            # the copied file already is the send copy - nothing to save yet
            return app.OpenDocumentFile(path, options)
        stage(u"Saving the detached copy to " + core.to_text(target), 0.7)
        try:
            _save_as(copy, target, compact)
        except Exception as error:
            # never leave an invisible detached document open for the rest of
            # the session
            try:
                copy.Close(False)
            except Exception:
                pass
            raise SaveAsFailed(core.to_text(error))
    return copy


def save_active_as_copy(uiapp, doc, target, template):
    """Fallback when the central cannot be opened a second time: the open
    model is saved as the send copy (a new central). Worksets are kept."""
    compact = core.as_bool(template.get(u"compact"), True)
    with DialogSuppressor(uiapp):
        _save_as(doc, target, compact)
    return doc


# ============================================================
# step 3 - clean up
# ============================================================

def _still_there(doc):
    def check(value):
        try:
            return doc.GetElement(to_element_id(value)) is not None
        except Exception:
            return False
    return check


def _ids_of(collection):
    out = []
    try:
        for element_id in collection:
            out.append(core.eid_value(element_id))
    except Exception:
        pass
    return out


def _roll_back(transaction):
    try:
        transaction.RollBack()
    except Exception:
        pass


def _delete_batch(doc, label, guard=None):
    def delete(values):
        transaction = _start(doc, u"Model Cleanup - " + label)
        try:
            ids = List[ElementId]()
            for value in values:
                ids.Add(to_element_id(value))
            removed = doc.Delete(ids)
        except Exception:
            _roll_back(transaction)
            return False
        if core.cascade_hits(_ids_of(removed), guard):
            # something that stays went with this chunk: undo it, and the
            # chunk is replayed one element at a time to find which
            _roll_back(transaction)
            return False
        return _finish(transaction)
    return delete


def _delete_one(doc, label, guard=None):
    def delete(value):
        transaction = _start(doc, u"Model Cleanup - " + label)
        try:
            removed = doc.Delete(to_element_id(value))
        except Exception as error:
            _roll_back(transaction)
            return False, core.to_text(error)
        hits = core.cascade_hits(_ids_of(removed), guard)
        if hits:
            _roll_back(transaction)
            # read after the rollback - until then they are deleted
            names = [model.element_name(doc.GetElement(to_element_id(h))) for h in hits]
            return False, core.cascade_reason(names)
        if _finish(transaction):
            return True, u""
        return False, u"Revit rolled the delete back"
    return delete


def delete_ids(doc, ids, label, progress=None, guard=None):
    return core.delete_in_chunks(ids, _delete_batch(doc, label, guard),
                                 _delete_one(doc, label, guard), _still_there(doc),
                                 25, progress)


VIEW_STAGE_KEYS = (u"delete_views_off_sheet", u"delete_schedules_off_sheet",
                   u"delete_legends_off_sheet")


def _guard_for(doc, key, template, active_view_id):
    """For the view stages: every view and sheet the plan keeps, so a delete
    that would cascade into one is undone."""
    if key not in VIEW_STAGE_KEYS:
        return None
    protected = set([model.starting_view_id(doc), active_view_id])
    plan = model.view_sheet_plan(doc, template, protected)
    every = [v[u"id"] for v in plan[u"views"]] + [s[u"id"] for s in plan[u"sheets"]]
    return core.view_guard(every, model.all_doomed(plan), model.on_sheet_ids(doc))


def borrow_everything(doc):
    """A workshared copy: take every user workset before deleting, so a
    delete cannot quietly ask a question and write nothing."""
    if not doc.IsWorkshared:
        return u""
    try:
        worksets = HashSet[WorksetId]()
        for workset in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            worksets.Add(workset.Id)
        WorksharingUtils.CheckoutWorksets(doc, worksets)
        return u""
    except Exception as error:
        return core.to_text(error)


class RunReport(object):
    def __init__(self):
        self.lines = []
        self.deleted = {}
        self.failures = {}
        self.protected = {}
        self.saved = False

    def add(self, text):
        self.lines.append(core.to_text(text))
        core.log(text)

    def record(self, key, label, deleted, failures):
        """Refusals are Revit saying no. Views the cascade guard held back are
        not failures - they stayed because something under them stays - and
        are counted apart so they do not read as a problem."""
        refused, kept = core.split_refusals(failures)
        self.deleted[key] = len(deleted)
        if refused:
            self.failures[key] = refused
        if kept:
            self.protected[key] = kept
        text = u"{0}: {1} removed".format(label, len(deleted))
        if kept:
            text += u", {0} kept because a view that stays depends on them".format(len(kept))
        if refused:
            text += u", {0} refused".format(len(refused))
        self.add(text)
        listed = list(kept.items()) + list(refused.items())
        for value, reason in listed[:15]:
            self.add(u"    id {0}: {1}".format(value, reason))
        if len(listed) > 15:
            self.add(u"    ... {0} more in the log".format(len(listed) - 15))
            for value, reason in listed[15:]:
                core.log(u"    id {0}: {1}".format(value, reason))

    def total(self):
        return sum(self.deleted.values())

    def refused(self):
        return sum(len(item) for item in self.failures.values())

    def kept(self):
        return sum(len(item) for item in self.protected.values())


def move_off_doomed_views(uidoc, doc, plan, report, debug):
    """Before cleaning the open model: if the active view is not retained,
    open a retained sheet (or view) and close the old one. Any other open
    view that is going is closed too. Returns the id active afterwards."""
    eid = core.eid_value
    active = uidoc.ActiveView
    active_id = eid(active.Id)
    doomed = model.all_doomed(plan)
    sheet_ids = [s[u"id"] for s in sorted(
        [s for s in plan[u"sheets"] if s[u"number"] in plan[u"retained_sheets"]
         and not s.get(u"placeholder")],
        key=lambda s: core.natural_key(s[u"number"]))]
    view_ids = [v[u"id"] for v in plan[u"views"]
                if core.view_key(v[u"kind"], v[u"name"]) in plan[u"retained_views"]
                and not v.get(u"template")]
    target_id = core.view_to_open(active_id, sheet_ids, view_ids, doomed,
                                  model.switch_candidates(plan, model.starting_view_id(doc)))
    debug.section(u"Active view")
    debug.values([(u"Active view", u"{0} ({1})".format(model.element_name(active), active_id)),
                  (u"Retained", active_id in sheet_ids or active_id in view_ids),
                  (u"Going in this run", active_id in doomed),
                  (u"Move to", target_id)])
    old_id = active_id
    if target_id is None:
        if active_id in doomed:
            report.add(u"The active view {0} is going, but no view that stays could be "
                       u"opened instead, so it is kept.".format(model.element_name(active)))
    else:
        target = doc.GetElement(to_element_id(target_id))
        try:
            uidoc.ActiveView = target
        except Exception as error:
            debug.line(u"Revit would not open {0}: {1}".format(
                model.element_name(target), core.to_text(error)))
        new_id = eid(uidoc.ActiveView.Id)
        if new_id != target_id:
            report.add(u"Revit did not switch views, so {0} is kept.".format(model.element_name(active)))
            debug.line(u"Switch refused; active is still {0}".format(new_id))
        else:
            report.add(u"Opened {0} and closed {1}.".format(
                model.element_name(target), model.element_name(active)))
            active_id = new_id
    closed = []
    for ui_view in list(uidoc.GetOpenUIViews()):
        view_id = eid(ui_view.ViewId)
        if view_id == active_id:
            continue
        if view_id != old_id and view_id not in doomed:
            continue
        name = model.element_name(doc.GetElement(ui_view.ViewId))
        try:
            ui_view.Close()
            closed.append(name)
        except Exception as error:
            debug.line(u"Could not close {0}: {1}".format(name, core.to_text(error)))
    if closed:
        debug.values([(u"Closed", u", ".join(closed))])
    debug.flush()
    return active_id


# ============================================================
# NWC export
# ============================================================

def nwc_options(plan, view_id):
    """NavisworksExportOptions from the plain plan. Each property is set on
    its own, so one a release lacks is reported, not fatal."""
    import Autodesk.Revit.DB as revit
    options = revit.NavisworksExportOptions()
    applied, refused = [], []
    order = [u"ExportScope"] + sorted(k for k in plan if k != u"ExportScope")
    for prop in order:
        value = plan[prop]
        try:
            if prop == u"ExportScope":
                value = getattr(revit.NavisworksExportScope, value)
            elif prop == u"Coordinates":
                value = getattr(revit.NavisworksCoordinates, value)
            elif prop == u"Parameters":
                value = getattr(revit.NavisworksParameters, value)
            setattr(options, prop, value)
            applied.append(prop)
        except Exception as error:
            refused.append(u"{0} ({1})".format(prop, core.to_text(error)))
    options.ViewId = to_element_id(view_id)
    return options, applied, refused


def export_nwc(uiapp, doc, template, folder, model_stem, progress=None, debug=None):
    """Export every ticked 3D view to folder. Returns (written, failures)
    where written is [(view, path)] and failures is [(view, reason)]. Each
    file is checked on disk afterwards - a quiet export is not proof."""
    import mcu_nwc as nwc
    debug = debug or core.DebugReport(False)
    views, primary = nwc.selection(template)
    planned = nwc.file_names(model_stem, views, primary)
    found, missing = nwc.resolve(model.three_d_views(doc), planned)
    plan = nwc.options_plan(template)
    written, failures = [], [(v, u"no 3D view with this name in the model") for v in missing]
    debug.section(u"NWC export")
    debug.values([(u"folder", folder), (u"primary", primary),
                  (u"settings", template.get(u"nwc_source")),
                  (u"exporter installed", model.nwc_available())] +
                 [(u"option " + k, v) for k, v in sorted(plan.items())])
    total = max(1, len(found))
    with DialogSuppressor(uiapp):
        for index, (view_id, view, file_name) in enumerate(found):
            if progress is not None:
                progress(float(index) / total, u"Exporting NWC {0} of {1}: {2}".format(
                    index + 1, len(found), view))
            path = os.path.join(folder, file_name + u".nwc")
            started = time.time()
            try:
                options, applied, refused = nwc_options(plan, view_id)
                if refused:
                    debug.line(u"{0}: options not set: {1}".format(view, u"; ".join(refused)))
                doc.Export(folder, file_name, options)
            except Exception as error:
                failures.append((view, core.to_text(error)))
                debug.line(u"{0}: export failed: {1}".format(view, core.format_exception()))
                continue
            if nwc_written(path, started):
                written.append((view, path))
            else:
                failures.append((view, u"Revit reported no error, but no new file appeared"))
    if progress is not None:
        progress(1.0, u"NWC export done")
    debug.table([u"view", u"file", u"result"],
                [(v, p, u"written") for v, p in written] +
                [(v, u"", r) for v, r in failures])
    debug.flush()
    return written, failures


def nwc_written(path, started):
    try:
        return (os.path.isfile(path) and os.path.getsize(path) > 0
                and os.path.getmtime(path) >= started - 2)
    except Exception:
        return False


def _debug_plan(debug, plan, title):
    if not debug.enabled:
        return
    placed = plan[u"placed"]
    debug.section(title + u" - sheets")
    debug.table([u"id", u"number", u"name", u"retained", u"decision"],
                [(s[u"id"], s[u"number"], s[u"name"], s[u"number"] in plan[u"retained_sheets"],
                  plan[u"decisions"].get(s[u"id"], u"")) for s in plan[u"sheets"]])
    debug.section(title + u" - views")
    debug.table([u"id", u"type", u"name", u"retain key", u"retained", u"placed on a kept sheet",
                 u"parent", u"template", u"decision"],
                [(v[u"id"], v[u"kind"], v[u"name"], core.view_key(v[u"kind"], v[u"name"]),
                  core.view_key(v[u"kind"], v[u"name"]) in plan[u"retained_views"],
                  v[u"id"] in placed, v[u"parent"], v[u"template"],
                  plan[u"decisions"].get(v[u"id"], u"")) for v in plan[u"views"]])
    debug.section(title + u" - retained entries not found in this model")
    view_keys = set(core.view_key(v[u"kind"], v[u"name"]) for v in plan[u"views"])
    numbers = set(s[u"number"] for s in plan[u"sheets"])
    missing = sorted(plan[u"retained_views"] - view_keys) + sorted(plan[u"retained_sheets"] - numbers)
    debug.line(u"\n".join(missing) if missing else u"(none)")
    debug.flush()


def run_cleanup(uiapp, doc, template, active_view_id=0, on_step=None, save=True,
                uidoc=None, debug=None):
    """The whole clean up on `doc`, then save. on_step(label, fraction) is
    called between transactions only - after every chunk, every replayed
    element and every purge pass - with the fraction of the whole run,
    weighted by how long each stage usually takes. uidoc is given only when
    `doc` is the open model, so the active view can be moved off."""
    debug = debug or core.DebugReport(False)
    report = RunReport()
    report.saved = False
    get = core.as_bool
    keep = core.split_words(template.get(u"keep_view_words"))
    retained = {
        u"views": set(core.split_retain(template.get(u"retain_views"))),
        u"sheets": set(core.split_retain(template.get(u"retain_sheets"))),
    }
    excluded = core.split_list(template.get(u"purge_exclude"))
    passes = core.as_int(template.get(u"purge_passes"), 4, 1, 10)
    ops = core.enabled_ops(template)
    plan = core.stage_plan([key for key, _ in ops] + ([u"save"] if save else []))

    debug.section(u"Clean up run")
    debug.values(model.environment(uiapp, doc))
    debug.values([(u"Runs on", u"the open model" if uidoc is not None else u"the saved copy"),
                  (u"Saves afterwards", save),
                  (u"Stages", u", ".join(key for key, _ in ops))])
    debug.section(u"Template")
    debug.values(sorted((k, v) for k, v in template.items()
                        if k not in (u"retain_views", u"retain_sheets")))
    debug.values([(u"retained views", len(retained[u"views"])),
                  (u"retained sheets", len(retained[u"sheets"]))])
    warnings = core.retention_warnings(template)
    if warnings:
        debug.line(u"Retention warnings: " + core.retention_message(template, warnings))
    debug.flush()

    def step(label, key, local=0.0):
        if on_step is not None:
            try:
                on_step(label, core.plan_fraction(plan, key, local))
            except Exception:
                pass

    with DialogSuppressor(uiapp) as dialogs:
        if uidoc is not None or debug.enabled:
            step(u"Working out which views and sheets go", plan[0][0] if plan else u"save", 0.0)
            before = model.view_sheet_plan(doc, template,
                                           set([model.starting_view_id(doc)]))
            _debug_plan(debug, before, u"Before the run")
            if uidoc is not None:
                active_view_id = move_off_doomed_views(uidoc, doc, before, report, debug)

        # Taking every workset is only right where they will be given back:
        # a run that saves (it syncs and relinquishes), or a model that is
        # its own central. On a local of a live central it would lock the
        # whole team out until the next sync.
        if save or core.save_route(model.describe(doc)) == core.SAVE_SYNC:
            step(u"Taking every workset in the copy", plan[0][0], 0.0)
            problem = borrow_everything(doc)
            if problem:
                report.add(u"Could not take every workset: " + problem)
                debug.line(u"Borrowing worksets failed: " + problem)
        else:
            debug.line(u"Worksets not borrowed: this run does not save, and the model "
                       u"is a local of a live central.")

        group = TransactionGroup(doc, u"Model Cleanup")
        group.Start()
        try:
            for key, label in ops:
                if key == u"export_nwc":
                    continue
                step(label + u" - finding what to remove", key, 0.0)
                progress = _progress_for(step, label, key)
                if key == u"purge":
                    _run_purge(doc, report, excluded, passes, label, progress, debug)
                    continue
                ids = _ids_for(doc, key, keep, active_view_id, retained, debug)
                if ids is None:
                    continue
                names = _names(doc, ids) if debug.enabled else {}
                guard = _guard_for(doc, key, template, active_view_id)
                step(u"{0} ({1})".format(label, len(ids)), key, 0.0)
                deleted, failures = delete_ids(doc, ids, label, progress, guard)
                report.record(key, label, deleted, failures)
                debug.section(u"Stage: " + label)
                debug.values([(u"asked", len(ids)), (u"removed", len(deleted)),
                               (u"refused", len(failures))] + debug.take_pending())
                if failures:
                    debug.table([u"id", u"name", u"reason"],
                                [(i, names.get(i, u""), r) for i, r in failures.items()])
                debug.flush()
                step(label, key, 1.0)
            debug.line(u"")
            debug.line(u"Transaction group: assimilating")
            group.Assimilate()
        except Exception:
            debug.exception(u"the clean up stages", core.format_exception())
            try:
                group.RollBack()
            except Exception:
                pass
            raise

        after = (model.view_sheet_plan(doc, template, set([model.starting_view_id(doc)]))
                 if debug.enabled else {u"sheets": [], u"views": [], u"doomed": {}})
        debug.section(u"After the run")
        debug.values([(u"sheets left", len(after[u"sheets"])),
                      (u"views left", len(after[u"views"])),
                      (u"sheets that should have gone but remain",
                       len(after[u"doomed"].get(u"delete_sheets_not_retained", []))),
                      (u"views that should have gone but remain",
                       sum(len(after[u"doomed"].get(k, [])) for k, _ in model.VIEW_STAGES))])
        leftovers = model.all_doomed(after) if debug.enabled else set()
        if leftovers:
            _debug_plan(debug, after, u"Left after the run")
        debug.flush()

        compact = get(template.get(u"compact"), True)
        if not save:
            report.add(u"Not saved and not synced: steps 1 and 2 were skipped. Check the "
                       u"model, then save it yourself.")
        elif doc.IsWorkshared:
            step(u"Syncing the copy to its own central (Revit is busy)", u"save", 0.05)
            transact = TransactWithCentralOptions()
            options = SynchronizeWithCentralOptions()
            options.SetRelinquishOptions(RelinquishOptions(True))
            options.Comment = u"Model Cleanup - cleaned for issue"
            options.Compact = compact
            try:
                doc.SynchronizeWithCentral(transact, options)
                report.add(u"Copy synced as its own central and relinquished.")
            except Exception:
                # the clean up is already committed; a refused sync must not
                # leave it unsaved for the window to throw away on close
                debug.exception(u"final sync (falling back to a save)", core.format_exception())
                fallback = SaveOptions()
                fallback.Compact = compact
                doc.Save(fallback)
                report.add(u"Revit would not sync the copy, so it was saved compact instead. "
                           u"Worksets were not relinquished.")
            report.saved = True
        else:
            step(u"Saving the copy (Revit is busy)", u"save", 0.05)
            options = SaveOptions()
            options.Compact = compact
            doc.Save(options)
            report.saved = True
            report.add(u"Copy saved.")
        if save:
            step(u"Saved", u"save", 1.0)
        if dialogs.seen:
            report.add(u"Revit asked {0} question(s) during the run; each was answered "
                       u"automatically and listed in the log.".format(len(dialogs.seen)))
            debug.section(u"Revit dialogs answered")
            debug.line(u"\n".join(dialogs.seen))
    debug.section(u"Run log")
    debug.line(u"\n".join(report.lines))
    debug.flush()
    return report


def _names(doc, ids):
    out = {}
    for value in ids:
        try:
            out[value] = model.element_name(doc.GetElement(to_element_id(value)))
        except Exception:
            out[value] = u""
    return out


def _progress_for(step, label, key):
    def progress(fraction):
        step(label, key, fraction)
    return progress


def _ids_for(doc, key, keep, active_view_id, retained=None, debug=None):
    retained = retained or {u"views": set(), u"sheets": set()}
    debug = debug or core.DebugReport(False)
    protected = set([model.starting_view_id(doc), active_view_id])
    if key == u"delete_sheets_not_retained":
        ids, skipped = core.sheets_to_delete(model.read_sheets(doc), retained[u"sheets"], protected)
        if skipped:
            core.log(u"sheets kept: {0}".format(len(skipped)))
        return ids
    if key == u"remove_revit_links":
        return model.revit_link_ids(doc)
    if key == u"remove_cad":
        return model.cad_ids(doc)
    if key == u"remove_point_clouds":
        return model.point_cloud_ids(doc)
    if key == u"delete_unplaced_images":
        # runs after the sheets and views, so images that were only placed on
        # them are unused by now
        unused = model.unused_image_ids(doc)
        types = model.image_type_ids(doc)
        if unused is None:
            debug.pending = [(u"skipped", u"this release has no purge API")]
            return []
        ids = core.unplaced_images(types, unused)
        debug.pending = [(u"raster images in the model", len(types)),
                         (u"still placed or used", len(types) - len(ids))]
        return ids
    if key in (u"delete_views_off_sheet", u"delete_schedules_off_sheet",
               u"delete_legends_off_sheet"):
        # read after the sheet stage: a deleted sheet took its viewports with
        # it, so "placed" already means placed on a sheet that survived
        views = model.read_views(doc)
        on_sheet = model.on_sheet_ids(doc)
        rule = {
            u"delete_views_off_sheet": core.views_to_delete,
            u"delete_schedules_off_sheet": core.schedules_to_delete,
            u"delete_legends_off_sheet": core.legends_to_delete,
        }[key]
        ids, skipped = rule(views, on_sheet, keep, protected, retained[u"views"])
        if skipped:
            core.log(u"{0}: kept {1}".format(key, len(skipped)))
        debug.pending = [(u"protected ids", sorted(protected)),
                         (u"views on a kept sheet", len(on_sheet)),
                         (u"kept by the rules", len(skipped))]
        return ids
    if key == u"delete_unused_templates":
        templates, used, defaults = model.template_usage(doc)
        return core.unused_ids(templates, used, defaults)
    if key == u"delete_unused_filters":
        filters, used = model.filter_usage(doc)
        return core.unused_ids(filters, used)
    return None


def _run_purge(doc, report, excluded, passes, label, progress, debug=None):
    debug = debug or core.DebugReport(False)
    if not model.can_purge(doc):
        report.add(u"Purge skipped: this release of Revit has no purge API.")
        return

    passes_seen = []

    def scan():
        entries = model.unused_entries(doc)
        passes_seen.append(entries)
        return entries

    def delete(ids, sub=None):
        return delete_ids(doc, ids, u"{0} ({1})".format(label, len(ids)), sub)

    deleted, failures, ran = core.purge_loop(scan, delete, excluded, passes, progress)
    report.record(u"purge", u"{0} ({1} pass{2})".format(
        label, ran, u"" if ran == 1 else u"es"), deleted, failures)
    if debug.enabled:
        debug.section(u"Purge")
        debug.values([(u"passes asked", passes), (u"passes run", ran),
                       (u"excluded categories", u", ".join(excluded) or u"(none)"),
                       (u"removed", len(deleted)), (u"refused", len(failures))])
        for index, entries in enumerate(passes_seen):
            counts = core.group_counts(entries, [])
            debug.line(u"Pass {0} found {1} unused: {2}".format(
                index + 1, len(entries),
                u", ".join(u"{0} {1}".format(g, n) for g, n, _ in counts) or u"nothing"))
        if failures:
            debug.table([u"id", u"reason"], sorted(failures.items()))
        debug.flush()


def save_model(uiapp, doc, route, comment, debug=None):
    """Save compact and let go of every workset, the way the route says."""
    debug = debug or core.DebugReport(False)
    with DialogSuppressor(uiapp) as dialogs:
        if route == core.SAVE_SYNC:
            transact = TransactWithCentralOptions()
            options = SynchronizeWithCentralOptions()
            options.SetRelinquishOptions(RelinquishOptions(True))
            options.Comment = core.to_text(comment)
            options.Compact = True
            try:
                options.SaveLocalBefore = False
                options.SaveLocalAfter = False
            except Exception:
                pass
            try:
                doc.SynchronizeWithCentral(transact, options)
                message = u"Synced compact and relinquished every workset."
            except Exception:
                # a central opened directly can refuse a sync on some releases
                debug.exception(u"sync before close (falling back to a save)",
                                core.format_exception())
                fallback = SaveOptions()
                fallback.Compact = True
                doc.Save(fallback)
                message = (u"Revit would not sync this file, so it was saved compact instead. "
                           u"Worksets were not relinquished.")
        else:
            options = SaveOptions()
            options.Compact = True
            doc.Save(options)
            message = u"Saved compact." if route == core.SAVE_PLAIN else \
                u"Saved the local file compact. Worksets are still yours."
    debug.values([(u"save route", route), (u"result", message),
                  (u"dialogs answered", len(dialogs.seen))])
    debug.flush()
    return message


def save_new_file(uiapp, doc, target):
    """A model that has never been saved: Save As, compact, as its own
    central when workshared."""
    with DialogSuppressor(uiapp):
        _save_as(doc, target, True)


def post_close_active(uiapp):
    """Revit will not let an add-in close the active model directly. Its
    own Close command, posted now, runs as soon as this tool returns."""
    from Autodesk.Revit.UI import RevitCommandId, PostableCommand
    command = None
    close = getattr(PostableCommand, u"Close", None)
    if close is not None:
        try:
            command = RevitCommandId.LookupPostableCommandId(close)
        except Exception:
            command = None
    if command is None:
        command = RevitCommandId.LookupCommandId(u"ID_REVIT_FILE_CLOSE")
    if command is None:
        return False
    uiapp.PostCommand(command)
    return True


def close_document(doc, save=False):
    try:
        return bool(doc.Close(bool(save)))
    except Exception:
        core.log(u"could not close the copy: " + core.format_exception())
        return False


def target_exists(path):
    return os.path.isfile(core.to_text(path))
