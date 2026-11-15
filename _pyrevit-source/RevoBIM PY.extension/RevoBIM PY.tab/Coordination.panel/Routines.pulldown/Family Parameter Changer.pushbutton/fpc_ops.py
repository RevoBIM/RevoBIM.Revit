# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - the write path.

**One family per Execute.** The handler pops a single family off its
queue, rebinds it, loads it back, and returns. The UI then updates the
progress bar and raises the event again for the next family. That is
what makes a progress bar possible at all: while an ExternalEvent is
executing, Revit's thread is busy and the window cannot repaint, so a
run that did every family inside one Execute would show a frozen bar
until the very end. It also isolates faults - a family Revit refuses
costs that family and nothing else - and gives Revit's idle loop a
breath between family-editor sessions.

The rebind itself is FamilyManager.ReplaceParameter: it swaps a family
parameter's definition for a chosen shared parameter while keeping its
current value, formula and group. The family is then loaded back over
the one in the project with parameter values kept, and the result is
**read back** from the project - a void API call is not evidence.
"""
import fpc_clr  # noqa - assemblies referenced before anything below

from Autodesk.Revit.UI import IExternalEventHandler
from Autodesk.Revit.DB import IFailuresPreprocessor, FailureProcessingResult, FailureSeverity
from Autodesk.Revit.DB import IFamilyLoadOptions



# ==================== helpers Revit calls back into ====================

class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings raised inside the family-editor transaction so
    Revit never stops to ask about one. Errors are left alone: a real
    error should roll the transaction back, and it does."""

    def PreprocessFailures(self, failures_accessor):
        try:
            for message in failures_accessor.GetFailureMessages():
                try:
                    if message.GetSeverity() == FailureSeverity.Warning:
                        failures_accessor.DeleteWarning(message)
                except Exception:
                    continue
        except Exception:
            pass
        return FailureProcessingResult.Continue


class OverwriteLoadOptions(IFamilyLoadOptions):
    """Always overwrite the family already in the project, and keep the
    project's parameter values while doing it - ReplaceParameter has just
    carried them across inside the family, and resetting them to the
    family's on-disk defaults would throw that away."""

    def OnFamilyFound(self, family_in_use, overwrite_parameter_values):
        overwrite_parameter_values.Value = True
        return True

    def OnSharedFamilyFound(self, shared_family, family_in_use, source, overwrite_parameter_values):
        try:
            from Autodesk.Revit.DB import FamilySource
            source.Value = FamilySource.Family
        except Exception:
            pass
        overwrite_parameter_values.Value = True
        return True


def _resolve_group(fp):
    """ForgeTypeId group on 2022+, the BuiltInParameterGroup enum on 2021."""
    try:
        return fp.Definition.GetGroupTypeId()
    except Exception:
        pass
    return fp.Definition.ParameterGroup


def _lock_reason(doc, element_id):
    """Who has this element, if anyone else does. Two different locks
    and both are asked about: the element borrowed by another user, and
    the element on a workset another user owns."""
    try:
        if not doc.IsWorkshared:
            return None
    except Exception:
        return None
    try:
        from Autodesk.Revit.DB import WorksharingUtils, CheckoutStatus
        status = WorksharingUtils.GetCheckoutStatus(doc, element_id)
        if status == CheckoutStatus.OwnedByOtherUser:
            owner = u''
            try:
                owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id).Owner
            except Exception:
                pass
            return u'borrowed by {0}'.format(owner or u'another user')
    except Exception:
        pass
    try:
        element = doc.GetElement(element_id)
        workset = doc.GetWorksetTable().GetWorkset(element.WorksetId)
        owner = workset.Owner
        me = doc.Application.Username
        if owner and owner != me:
            return u'workset "{0}" is owned by {1}'.format(workset.Name, owner)
    except Exception:
        pass
    return None


def _read_back(doc, family, sample_instance_id, change):
    """Proves the rebind landed in the project: finds the parameter by
    name on the family's first type (or on the sample instance for an
    instance parameter) and checks it is now shared with the wanted
    GUID. Returns (ok, note)."""
    wanted = change.get('shared_guid', u'')
    holders = []
    try:
        for sid in family.GetFamilySymbolIds():
            sym = doc.GetElement(sid)
            if sym is not None:
                holders.append(sym)
                break
    except Exception:
        pass
    if sample_instance_id is not None:
        inst = doc.GetElement(sample_instance_id)
        if inst is not None:
            holders.append(inst)
    if not holders:
        return None, u'no type or instance to read back from'

    seen_any = False
    for holder in holders:
        try:
            params = holder.GetParameters(change['param_name'])
        except Exception:
            params = []
        for p in params:
            seen_any = True
            try:
                if p.IsShared and p.GUID.ToString() == wanted:
                    return True, u''
            except Exception:
                continue
    if not seen_any:
        return None, u'parameter not visible in the project (an instance parameter with no instance placed?)'
    return False, u'loaded, but the project still shows the old binding'


# ==================== the handler ====================

class RebindHandler(IExternalEventHandler):
    """queue: list of jobs, each
        {'family_id', 'family_name', 'sample_instance_id',
         'changes': [{'param_name', 'shared_guid', 'shared_name'}, ...]}
    Execute processes exactly one job per call and hands its results to
    on_step(job, results). results is a list of
        {'family', 'param', 'ok', 'message'}."""

    def __init__(self):
        self.queue = []
        self.on_step = None
        self.doc_title = None
        self.suppress_dialogs = False
        self.dialogs_hooked = False
        self.suppressed = []
        self.last_error = None

    def GetName(self):
        return u'RevoBIM Family Parameter Changer'

    # ----- dialog suppression: hooked once, toggled with a flag -----

    def hook_dialogs(self, uiapp):
        """Unsubscribing an IronPython bound method from a .NET event is
        not reliable, so the hook is made once and switched with a flag."""
        if self.dialogs_hooked:
            return
        try:
            uiapp.DialogBoxShowing += self._on_dialog
            self.dialogs_hooked = True
        except Exception:
            pass

    def _on_dialog(self, sender, args):
        if not self.suppress_dialogs:
            return
        try:
            try:
                self.suppressed.append(args.DialogId)
            except Exception:
                self.suppressed.append(u'(dialog)')
            args.OverrideResult(1)
        except Exception:
            pass

    # ----- one family per call -----

    def Execute(self, uiapp):
        if not self.queue:
            return
        job = self.queue.pop(0)
        results = []
        try:
            doc = uiapp.ActiveUIDocument.Document
        except Exception:
            doc = None
        if doc is None:
            results.append(self._result(job, u'', False, u'No active document.'))
            self._hand_back(job, results)
            return

        # never write into a document other than the one the window read
        try:
            if self.doc_title is not None and doc.Title != self.doc_title:
                results.append(self._result(job, u'', False,
                                            u'The active document changed to "{0}"; skipped.'.format(doc.Title)))
                self._hand_back(job, results)
                return
        except Exception:
            pass

        self.hook_dialogs(uiapp)
        self.suppress_dialogs = True
        self.suppressed = []
        try:
            self._process_family(uiapp, doc, job, results)
        except Exception as ex:
            results.append(self._result(job, u'', False, u'Unexpected failure: {0}'.format(ex)))
        finally:
            self.suppress_dialogs = False
            if self.suppressed:
                results.append(self._result(job, u'', True,
                                            u'{0} Revit dialog(s) suppressed during this family.'.format(
                                                len(self.suppressed)), info=True))
        self._hand_back(job, results)

    def _hand_back(self, job, results):
        if self.on_step is None:
            return
        try:
            self.on_step(job, results)
        except Exception as ex:
            self.last_error = u'{0}'.format(ex)

    def _result(self, job, param, ok, message, info=False):
        return {'family': job.get('family_name', u''), 'param': param,
                'ok': ok, 'message': message, 'info': info}

    def _process_family(self, uiapp, doc, job, results):
        from Autodesk.Revit.DB import Transaction

        fam = doc.GetElement(job['family_id'])
        if fam is None:
            results.append(self._result(job, u'', False, u'Family no longer exists in the project.'))
            return

        lock = _lock_reason(doc, fam.Id)
        if lock:
            results.append(self._result(job, u'', False, u'Skipped - {0}.'.format(lock)))
            return

        # the shared parameter file is read once per family, not once per parameter
        defs_by_guid = {}
        try:
            spf = uiapp.Application.OpenSharedParameterFile()
        except Exception:
            spf = None
        if spf is None:
            results.append(self._result(job, u'', False, u'No shared parameter file is set.'))
            return
        try:
            for g in spf.Groups:
                for d in g.Definitions:
                    try:
                        defs_by_guid[d.GUID.ToString()] = d
                    except Exception:
                        continue
        except Exception:
            pass

        try:
            fam_doc = doc.EditFamily(fam)
        except Exception as ex:
            results.append(self._result(job, u'', False, u'Could not open the family editor: {0}'.format(ex)))
            return

        applied = []
        try:
            fm = fam_doc.FamilyManager
            t = Transaction(fam_doc, u'RevoBIM Family Parameter Changer')
            try:
                options = t.GetFailureHandlingOptions()
                options.SetFailuresPreprocessor(WarningSwallower())
                t.SetFailureHandlingOptions(options)
            except Exception:
                pass
            t.Start()

            by_name = {}
            try:
                for p in fm.GetParameters():
                    try:
                        by_name[p.Definition.Name] = p
                    except Exception:
                        continue
            except Exception:
                pass

            for change in job['changes']:
                pname = change['param_name']
                fp = by_name.get(pname)
                if fp is None:
                    results.append(self._result(job, pname, False,
                                                u'Parameter not found once the family editor opened.'))
                    continue
                ext_def = defs_by_guid.get(change['shared_guid'])
                if ext_def is None:
                    results.append(self._result(job, pname, False,
                                                u'Shared parameter not in the current shared parameter file.'))
                    continue
                try:
                    fm.ReplaceParameter(fp, ext_def, _resolve_group(fp), fp.IsInstance)
                    applied.append(change)
                except AttributeError:
                    results.append(self._result(job, pname, False,
                                                u'FamilyManager.ReplaceParameter is not available on this Revit version.'))
                except Exception as ex:
                    results.append(self._result(job, pname, False, u'{0}'.format(ex)))

            if applied:
                status = t.Commit()
                try:
                    from Autodesk.Revit.DB import TransactionStatus
                    if status != TransactionStatus.Committed:
                        for change in applied:
                            results.append(self._result(job, change['param_name'], False,
                                                        u'Family editor transaction did not commit ({0}).'.format(status)))
                        applied = []
                except Exception:
                    pass
            else:
                t.RollBack()
        except Exception as ex:
            results.append(self._result(job, u'', False, u'Family editor transaction failed: {0}'.format(ex)))
            applied = []

        loaded = None
        if applied:
            try:
                loaded = fam_doc.LoadFamily(doc, OverwriteLoadOptions())
            except Exception as ex:
                for change in applied:
                    results.append(self._result(job, change['param_name'], False,
                                                u'Rebound in the family, but loading it back over the project copy failed: {0}'.format(ex)))
                applied = []

        try:
            fam_doc.Close(False)
        except Exception:
            pass

        if not applied:
            return

        # prove it: read the binding back from the project
        target = loaded if loaded is not None else doc.GetElement(job['family_id'])
        for change in applied:
            ok, note = _read_back(doc, target, job.get('sample_instance_id'), change)
            if ok is True:
                results.append(self._result(job, change['param_name'], True,
                                            u'Rebound to {0}'.format(change.get('shared_name', u''))))
            elif ok is None:
                results.append(self._result(job, change['param_name'], True,
                                            u'Rebound to {0} - {1}'.format(change.get('shared_name', u''), note)))
            else:
                results.append(self._result(job, change['param_name'], False, note))
