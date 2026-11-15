# -*- coding: utf-8 -*-
"""Every write the tool makes, and the route it takes to Revit.

A modeless window cannot start a transaction, so work is queued on an
ExternalEvent and reported back through the window's dispatcher - never
waited for, because Revit raises the event on the thread the window lives on.
"""
import msm_clr  # noqa: F401  - assemblies first

import time
import traceback

from System.Collections.Generic import List
from Autodesk.Revit.DB import (Transaction, TransactionGroup, ElementId,
                               IFailuresPreprocessor, FailureProcessingResult,
                               FailureSeverity, FailureResolutionType,
                               StorageType, TemporaryViewMode,
                               View3D, ViewFamilyType, ViewFamily,
                               FilteredElementCollector, BoundingBoxXYZ, XYZ,
                               WorksharingUtils, CheckoutStatus,
                               RoutingPreferenceRuleGroupType, RoutingConditions,
                               RoutingCondition, RoutingPreferenceErrorLevel,
                               OverrideGraphicSettings, Color, FillPatternElement,
                               RevitLinkInstance, LinePatternElement,
                               ElementTransformUtils, Line)
from Autodesk.Revit.UI import (IExternalEventHandler, ExternalEvent, ExternalEventRequest,
                               PostableCommand, RevitCommandId)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

import msm_core as core
import msm_model as model
from msm_model import eid_value, make_id


# ============================================================
# plumbing
# ============================================================

class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for failure in list(accessor.GetFailureMessages()):
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def quiet(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction


class FailureRecorder(IFailuresPreprocessor):
    """Writes down every failure Revit raises in a transaction - what it said
    and which elements it named. Warnings are recorded and dismissed; an
    error rolls the transaction back, so the model is never left in the state
    Revit objected to, and the elements it named are kept for highlighting.

    allow_disconnect answers one question Revit asks: "The family is connected
    in a network and can no longer keep the connectivity. Disconnect the
    family from the network?" Off, the answer is no and the pipe is left as
    it was. On, Revit is allowed to disconnect, and everything it disconnects
    is written down so it can be reconnected."""

    def __init__(self, allow_disconnect=False):
        self.errors = []        # [(text, [ids])]
        self.warnings = []
        self.disconnected = []
        self.allow_disconnect = allow_disconnect

    def _disconnect(self, accessor, failure):
        """Answer Revit's "disconnect?" question with yes, where that is the
        resolution it offers."""
        try:
            resolution = FailureResolutionType.DisconnectElements
            if not failure.HasResolutionOfType(resolution):
                return False
            failure.SetCurrentResolutionType(resolution)
            accessor.ResolveFailure(failure)
            return True
        except Exception:
            return False

    def PreprocessFailures(self, accessor):
        has_error = False
        try:
            for failure in list(accessor.GetFailureMessages()):
                text = u""
                ids = []
                try:
                    text = failure.GetDescriptionText()
                except Exception:
                    pass
                for getter in (u"GetFailingElementIds", u"GetAdditionalElementIds"):
                    try:
                        ids.extend([eid_value(i) for i in getattr(failure, getter)()])
                    except Exception:
                        pass
                if failure.GetSeverity() == FailureSeverity.Warning:
                    self.warnings.append((text, ids))
                    accessor.DeleteWarning(failure)
                elif self.allow_disconnect and self._disconnect(accessor, failure):
                    self.disconnected.append((text, ids))
                else:
                    self.errors.append((text, ids))
                    has_error = True
        except Exception:
            pass
        if has_error:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def recorded(transaction, allow_disconnect=False):
    """Like quiet(), but the failures are kept: (transaction, recorder)."""
    recorder = FailureRecorder(allow_disconnect)
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(recorder)
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction, recorder


def committed(status):
    return u"{0}".format(status).endswith(u"Committed")


class DialogGuard(object):
    """DialogBoxShowing is hooked once and switched with a flag: unhooking an
    IronPython bound method from a .NET event is not reliable, because every
    attribute access makes a fresh delegate."""
    hooked = False
    active = False
    seen = []

    @classmethod
    def arm(cls, uiapp):
        if not cls.hooked:
            try:
                uiapp.DialogBoxShowing += cls.on_dialog
                cls.hooked = True
            except Exception:
                pass
        cls.active = True
        cls.seen = []

    @classmethod
    def disarm(cls):
        cls.active = False

    @staticmethod
    def on_dialog(sender, args):
        if not DialogGuard.active:
            return
        try:
            DialogGuard.seen.append(u"{0}".format(args.DialogId))
            args.OverrideResult(1)
        except Exception:
            pass


def id_list(numbers):
    out = List[ElementId]()
    for number in numbers:
        out.Add(make_id(number))
    return out


class Result(object):
    def __init__(self):
        self.data = {}
        self.error = u""

    def get(self, key, default=None):
        return self.data.get(key, default)


# ============================================================
# runners
# ============================================================

class JobHandler(IExternalEventHandler):
    started = None          # the window sets this: Revit has begun the work

    def __init__(self):
        self.queue = []

    def Execute(self, uiapp):
        jobs = list(self.queue)
        del self.queue[:]
        # Revit has the work in hand now: the window's watchdog is for a
        # request Revit has not started, never for one still running
        if self.started is not None:
            try:
                self.started()
            except Exception:
                pass
        for job, done in jobs:
            run_job(uiapp, job, done)

    def GetName(self):
        return u"RevoBIM MEP System Manager"


def run_job(uiapp, job, done):
    result = Result()
    DialogGuard.arm(uiapp)
    try:
        job(uiapp, result)
    except Exception:
        result.error = traceback.format_exc()
    finally:
        DialogGuard.disarm()
    result.data[u"dialogs"] = list(DialogGuard.seen)
    try:
        done(result)
    except Exception:
        pass


class ModelessRunner(object):
    """Queue the job, raise the event, return. The callback is marshalled
    onto the window's dispatcher by the caller."""

    def __init__(self):
        self.handler = JobHandler()
        self.event = ExternalEvent.Create(self.handler)

    def _set_started(self, callback):
        self.handler.started = callback

    started = property(lambda self: self.handler.started, _set_started)

    def run(self, job, done):
        """Accepted: the job runs when Revit is next idle. Pending: an earlier
        request is still waiting - this job is queued behind it and runs in the
        same pass, so it is not an error and nothing is dropped. Anything else:
        only this job is taken back out of the queue. (Emptying the whole queue
        here lost the earlier job's callback, and the window waited for it for
        ever.) Returns the request status as text."""
        entry = (job, done)
        self.handler.queue.append(entry)
        try:
            status = self.event.Raise()
        except Exception:
            status = None
        text = u"{0}".format(status)
        if status == ExternalEventRequest.Accepted or text.endswith(u"Pending"):
            return text
        try:
            self.handler.queue.remove(entry)
        except ValueError:
            pass
        result = Result()
        result.error = u"Revit did not accept the request ({0}). Close any " \
                       u"open Revit dialog or command and try again.".format(status)
        done(result)
        return text


class DirectRunner(object):
    """Modal fallback: the window blocks the command, so the job runs now."""

    started = None

    def __init__(self, uiapp):
        self.uiapp = uiapp

    def run(self, job, done):
        if self.started is not None:
            self.started()
        run_job(self.uiapp, job, done)
        return u"Direct"


# ============================================================
# 3D view
# ============================================================

def find_or_make_default_3d(doc, uiapp):
    user = u""
    try:
        user = doc.Application.Username
    except Exception:
        pass
    views = {}
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if not v.IsTemplate:
                views[model.elem_name(v)] = v
        except Exception:
            pass
    name = core.pick_default_3d(list(views.keys()), user, doc.IsWorkshared)
    if name is not None:
        return views[name], False
    vft = None
    for candidate in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if candidate.ViewFamily == ViewFamily.ThreeDimensional:
                vft = candidate
                break
        except Exception:
            pass
    if vft is None:
        return None, False
    view = View3D.CreateIsometric(doc, vft.Id)
    wanted = core.default_3d_name(user, doc.IsWorkshared)
    try:
        view.Name = wanted
    except Exception:
        try:
            view.Name = u"{0} RevoBIM".format(wanted)
        except Exception:
            pass
    return view, True


def elements_bounds(doc, numbers, margin_mm):
    low = None
    high = None
    for number in numbers:
        try:
            box = doc.GetElement(make_id(number)).get_BoundingBox(None)
        except Exception:
            box = None
        if box is None:
            continue
        if low is None:
            low = [box.Min.X, box.Min.Y, box.Min.Z]
            high = [box.Max.X, box.Max.Y, box.Max.Z]
        else:
            low = [min(low[0], box.Min.X), min(low[1], box.Min.Y), min(low[2], box.Min.Z)]
            high = [max(high[0], box.Max.X), max(high[1], box.Max.Y), max(high[2], box.Max.Z)]
    if low is None:
        return None
    pad = core.mm_to_feet(margin_mm)
    bounds = BoundingBoxXYZ()
    bounds.Min = XYZ(low[0] - pad, low[1] - pad, low[2] - pad)
    bounds.Max = XYZ(high[0] + pad, high[1] + pad, high[2] + pad)
    return bounds


def isolate_job(pipe_ids, view_id, settings):
    """Build the job: find what is on the picked pipes' own systems, isolate
    it temporarily in the chosen 3D view (made if it is the default and
    missing), keeping the section box visible, switch to it, zoom."""
    def job(uiapp, result):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        what = settings.get(u"isolate_what", u"fittings")
        ids, dropped = model.isolate_ids(doc, pipe_ids, what,
                                         settings.get(u"domain", u"pipe"), settings)
        result.data[u"count"] = len(ids)
        result.data[u"dropped"] = dropped
        if dropped:
            log_lines = [u"{0}: {1}".format(k, v) for k, v in sorted(dropped.items())]
            result.data[u"dropped_text"] = u", ".join(log_lines)

        # one undo step for the reset and the new isolate together
        group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Isolate")
        group.Start()
        try:
            view, made, status = _isolate_checked(doc, uiapp, view_id, ids, settings, result,
                                                  settings.get(u"isolated_view") or 0)
            if view is None:
                group.RollBack()
                return
            if not committed(status):
                group.RollBack()
                result.error = u"Revit rolled the isolate back ({0}).".format(status)
                return
            group.Assimilate()
        except Exception:
            try:
                if group.HasStarted() and not group.HasEnded():
                    group.RollBack()
            except Exception:
                pass
            raise
        result.data[u"view_name"] = model.elem_name(view)
        result.data[u"made_view"] = made

        try:
            uidoc.ActiveView = view
        except Exception:
            try:
                uidoc.RequestViewChange(view)
            except Exception:
                result.data[u"switch_failed"] = True
        if core.to_bool(settings.get(u"isolate_select")):
            try:
                uidoc.Selection.SetElementIds(id_list(ids))
            except Exception:
                pass
        if core.to_bool(settings.get(u"isolate_zoom")):
            result.data[u"zoomed"] = zoom_to(uidoc, view, doc, ids)
        _show_now(uidoc, view, result)
    return job


def _show_now(uidoc, view, result):
    """Make sure the view on screen is the one isolated, and redraw it. Revit
    does not always repaint a view changed from a modeless window until it is
    touched, which made a good isolate look like nothing had happened."""
    try:
        active = uidoc.ActiveView
        result.data[u"active_view"] = model.elem_name(active)
        if active is None or eid_value(active.Id) != eid_value(view.Id):
            uidoc.RequestViewChange(view)
            result.data[u"switch_requested"] = True
    except Exception:
        pass
    try:
        uidoc.RefreshActiveView()
        result.data[u"refreshed"] = True
    except Exception:
        result.data[u"refreshed"] = False


def _isolate_mode_on(view):
    try:
        return bool(view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate))
    except Exception:
        return False


def clear_highlight(doc, view, highlighted, result):
    """Take the red off whatever this tool coloured in this view last time."""
    view_id, ids = core.decode_highlight(highlighted)
    if not ids or view is None or view_id != eid_value(view.Id):
        return
    plain = OverrideGraphicSettings()
    cleared = 0
    for number in ids:
        try:
            if doc.GetElement(make_id(number)) is not None:
                view.SetElementOverrides(make_id(number), plain)
                cleared += 1
        except Exception:
            pass
    result.data[u"highlight_cleared"] = cleared


def _solid_fill_id(doc):
    try:
        for fill in FilteredElementCollector(doc).OfClass(FillPatternElement):
            try:
                if fill.GetFillPattern().IsSolidFill:
                    return fill.Id
            except Exception:
                pass
    except Exception:
        pass
    return None


def paint_red(doc, view, ids):
    """Broken elements in red: lines and surfaces. Returns how many took."""
    red = Color(217, 83, 79)
    ogs = OverrideGraphicSettings()
    for setter, value in ((u"SetProjectionLineColor", red), (u"SetProjectionLineWeight", 8),
                          (u"SetSurfaceForegroundPatternColor", red)):
        try:
            getattr(ogs, setter)(value)
        except Exception:
            pass
    solid = _solid_fill_id(doc)
    if solid is not None:
        try:
            ogs.SetSurfaceForegroundPatternId(solid)
        except Exception:
            pass
    painted = 0
    for number in ids:
        try:
            view.SetElementOverrides(make_id(number), ogs)
            painted += 1
        except Exception:
            pass
    return painted


TEMPORARY_MODES = (u"TemporaryHideIsolate", u"RevealHiddenElements")


def _reset_view(doc, view, highlighted, result):
    """Everything Reset Isolate does to one view: temporary hide / isolate off,
    Reveal Hidden Elements off (a view left in it shows the new isolate
    muddled), and the red this tool painted taken off."""
    for name in TEMPORARY_MODES:
        mode = getattr(TemporaryViewMode, name, None)
        if mode is None:
            continue
        try:
            view.DisableTemporaryViewMode(mode)
        except Exception:
            pass
    clear_highlight(doc, view, highlighted, result)


def _reset_before_isolate(doc, uiapp, view_id, result, highlighted=u"", previous_view=0):
    """Step one of every isolate: exactly what Reset Isolate does, committed
    on its own, in the view about to be isolated in and in the view the last
    isolate went into, if that was another. Revit isolates within what is
    already isolated, so an earlier isolate left on shows through the new one.
    The reset is done whether or not the view says it is isolated - asking
    first is how the earlier one got left behind - and then checked.
    (view, made); view None and result.error set if there is nothing to
    isolate in, or the reset did not take."""
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - Reset isolate"))
    t.Start()
    try:
        if view_id:
            view = doc.GetElement(make_id(view_id))
            made = False
        else:
            view, made = find_or_make_default_3d(doc, uiapp)
        if view is None:
            t.RollBack()
            result.error = u"No 3D view to isolate in, and none could be made."
            return None, False
        result.data[u"was_isolated"] = _isolate_mode_on(view)
        reset = []
        for number in core.views_to_reset(eid_value(view.Id), previous_view):
            other = view if number == eid_value(view.Id) else doc.GetElement(make_id(number))
            if other is None:
                continue
            _reset_view(doc, other, highlighted, result)
            reset.append(model.elem_name(other))
        result.data[u"reset_views"] = reset
        status = t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    if not committed(status):
        result.error = u"Revit rolled back the reset of the earlier isolate ({0}).".format(status)
        return None, False
    if _isolate_mode_on(view):
        result.error = (u"The earlier isolate in {0} would not come off, so the new one was not "
                        u"added on top of it. Use Reset Temporary Hide/Isolate in the view, then "
                        u"isolate again.".format(model.elem_name(view)))
        return None, False
    return view, made


def _visible_services(doc, view):
    """Every pipe, duct, tray, conduit, fitting and accessory the view shows
    now - after an isolate, only what was isolated should be here."""
    wanted = set()
    for domain in core.DISCIPLINES:
        wanted |= model.isolate_category_numbers(domain)
    out = []
    try:
        for element in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
            try:
                if model.category_number(element) in wanted:
                    out.append(eid_value(element.Id))
            except Exception:
                pass
    except Exception:
        return None
    return out


def _isolate_checked(doc, uiapp, view_id, ids, settings, result, previous_view=0):
    """Reset, isolate, then look: if anything is still showing that is not in
    the new isolate, reset and isolate once more; whatever is left after
    that is reported, not hidden. Returns (view, made, status)."""
    view, made = _reset_before_isolate(doc, uiapp, view_id, result,
                                       settings.get(u"highlighted", u""), previous_view)
    if view is None:
        return None, False, None
    status = _isolate_in(doc, view, ids, view_id, settings, result)
    if not committed(status):
        return view, made, status
    left = core.leftovers(_visible_services(doc, view) or [], ids)
    if left:
        result.data[u"retried"] = len(left)
        view, _made = _reset_before_isolate(doc, uiapp, eid_value(view.Id), result,
                                            settings.get(u"highlighted", u""), 0)
        if view is None:
            return None, made, None
        status = _isolate_in(doc, view, ids, view_id, settings, result)
        if committed(status):
            left = core.leftovers(_visible_services(doc, view) or [], ids)
            if left:
                result.data[u"leftovers"] = left[:200]
    result.data[u"view_id"] = eid_value(view.Id)
    return view, made, status


def _isolate_in(doc, view, ids, view_id, settings, result):
    """Step two: fit the section box, find it, isolate the new selection with
    it. Returns the commit status."""
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - Isolate selection"))
    t.Start()
    try:
        # the box goes on before the isolate, so it exists to be kept
        if core.fit_section_box(not view_id, settings):
            bounds = elements_bounds(doc, ids, core.to_float(
                settings.get(u"section_margin_mm"), 300.0))
            if bounds is None:
                result.data[u"section_box_failed"] = True
            else:
                try:
                    view.IsSectionBoxActive = True
                    view.SetSectionBox(bounds)
                    result.data[u"section_box"] = True
                except Exception:
                    result.data[u"section_box_failed"] = True
        show = list(ids)
        box_active = False
        try:
            box_active = bool(view.IsSectionBoxActive)
        except Exception:
            pass
        if box_active:
            doc.Regenerate()
            box = model.section_box_id(doc, view)
            if box:
                show.append(box)
                result.data[u"box_kept"] = True
            else:
                result.data[u"box_hidden"] = True
        view.IsolateElementsTemporary(id_list(show))
        return t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise


def zoom_to(uidoc, view, doc, ids):
    try:
        for ui_view in uidoc.GetOpenUIViews():
            if eid_value(ui_view.ViewId) == eid_value(view.Id):
                bounds = elements_bounds(doc, ids, 500.0)
                if bounds is not None:
                    ui_view.ZoomAndCenterRectangle(bounds.Min, bounds.Max)
                    return True
    except Exception:
        pass
    try:
        uidoc.ShowElements(id_list(ids))
        return True
    except Exception:
        return False


def reset_job(view_id, highlighted=u"", previous_view=0):
    """Reset Isolate: the chosen view, and the view the last isolate went into
    if that was another - temporary hide / isolate, Reveal Hidden Elements and
    the red, all off."""
    def job(uiapp, result):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        if view_id:
            view = doc.GetElement(make_id(view_id))
        else:
            view, made = find_or_make_default_3d(doc, uiapp)
            if made:
                view = None
        numbers = core.views_to_reset(eid_value(view.Id) if view is not None else 0,
                                      previous_view)
        if not numbers:
            result.error = u"That 3D view does not exist yet - nothing to reset."
            return
        t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - Reset isolate"))
        t.Start()
        names = []
        try:
            for number in numbers:
                other = doc.GetElement(make_id(number))
                if other is None:
                    continue
                _reset_view(doc, other, highlighted, result)
                names.append(model.elem_name(other))
            status = t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise
        result.data[u"view_name"] = u", ".join(names)
        result.data[u"reset_views"] = names
        result.data[u"ok"] = committed(status)
        result.data[u"highlight_cleared"] = result.data.get(u"highlight_cleared", 0)
    return job


# ============================================================
# change pipe type, keeping parameter data
# ============================================================

def snapshot_params(element, names):
    """{name: (storage, value)} for each named parameter the element has and
    can write. Every route to the parameter is tried - LookupParameter and
    GetParameters do not always hand back the same object."""
    out = {}
    for name in names:
        p = find_param(element, name)
        if p is None:
            continue
        try:
            if p.IsReadOnly:
                continue
            storage = u"{0}".format(p.StorageType)
            if p.StorageType == StorageType.String:
                value = p.AsString()
            elif p.StorageType == StorageType.Integer:
                value = p.AsInteger()
            elif p.StorageType == StorageType.Double:
                value = p.AsDouble()
            elif p.StorageType == StorageType.ElementId:
                value = eid_value(p.AsElementId())
            else:
                continue
            out[name] = (storage, value)
        except Exception:
            pass
    return out


def find_param(element, name):
    try:
        found = element.GetParameters(name)
        for p in found:
            if not p.IsReadOnly:
                return p
        if found.Count:
            return found[0]
    except Exception:
        pass
    try:
        return element.LookupParameter(name)
    except Exception:
        return None


def write_param(element, name, storage, value):
    p = find_param(element, name)
    if p is None:
        return False
    try:
        if storage.endswith(u"ElementId"):
            return bool(p.Set(make_id(value)))
        if storage.endswith(u"String"):
            return bool(p.Set(value or u""))
        if storage.endswith(u"Integer"):
            return bool(p.Set(int(value)))
        if storage.endswith(u"Double"):
            return bool(p.Set(float(value)))
    except Exception:
        return False
    return False


def snapshot_attached(doc, pipe_numbers, retain):
    """Retained values on every fitting and accessory joined to the pipes,
    taken before anything changes. Revit can replace a fitting when the pipes
    either side change type, so each one also records where it sits and
    which pipes it joins - enough to find its replacement afterwards."""
    out = {}
    if not retain:
        return out
    for number in pipe_numbers:
        pipe = doc.GetElement(make_id(number))
        if pipe is None:
            continue
        for owner in model.neighbours(pipe):
            oid = eid_value(owner.Id)
            if oid in out or not model.is_fitting_or_accessory(owner):
                continue
            params = snapshot_params(owner, retain)
            if not params:
                continue
            out[oid] = {
                u"params": params,
                u"point": model.point_of(owner),
                u"pipes": [eid_value(n.Id) for n in model.neighbours(owner)
                           if model.is_pipe(n)],
            }
    return out


REPLACED_TOLERANCE_FT = core.mm_to_feet(5.0)


def resolve_fitting(doc, oid, info):
    """The fitting as it is now: the same element if it survived, else the
    fitting or accessory sitting in the same place on the same pipes."""
    element = doc.GetElement(make_id(oid))
    if model.is_live(element):
        return element, False
    candidates = []
    seen = set()
    for pid in info.get(u"pipes") or []:
        pipe = doc.GetElement(make_id(pid))
        if not model.is_live(pipe):
            continue
        for owner in model.neighbours(pipe):
            cid = eid_value(owner.Id)
            if cid in seen or not model.is_fitting_or_accessory(owner):
                continue
            seen.add(cid)
            candidates.append((cid, model.point_of(owner)))
    found = core.nearest_within(info.get(u"point"), candidates, REPLACED_TOLERANCE_FT)
    if found is None:
        return None, True
    return doc.GetElement(make_id(found)), True


def _restore_targets(doc, pipe_snaps, fit_snaps, data):
    targets = []
    for number, params in pipe_snaps.items():
        pipe = doc.GetElement(make_id(number))
        if model.is_live(pipe):
            targets.append((u"{0}".format(number), pipe, params))
    for oid, info in fit_snaps.items():
        element, replaced = resolve_fitting(doc, oid, info)
        if element is None:
            data[u"not_restored"].append(
                u"{0} - fitting was replaced by Revit and the new one could not be found"
                .format(oid))
            continue
        label = u"{0}".format(oid)
        if replaced:
            label = u"{0} (now {1})".format(oid, eid_value(element.Id))
            data[u"replaced_fittings"] += 1
        targets.append((label, element, info[u"params"]))
    return targets


def restore_pass(doc, pipe_snaps, fit_snaps, data, attempts=2):
    """The last thing a type change does: every retained value is compared
    with what was read before anything changed, and written back wherever it
    differs. Done after every pipe and fitting has changed, because changing
    one pipe can reset the fittings - and so the values - of the one before
    it. The check is repeated after the commit, which regenerates; anything
    that still differs is reported by element and parameter."""
    if not pipe_snaps and not fit_snaps:
        return
    targets = _restore_targets(doc, pipe_snaps, fit_snaps, data)
    still = {}
    for _attempt in range(attempts):
        t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - retain parameters"))
        t.Start()
        refused = {}
        try:
            for label, element, params in targets:
                now = snapshot_params(element, list(params.keys()))
                for name in core.plan_restore(params, now):
                    storage, value = params[name]
                    if write_param(element, name, storage, value):
                        data[u"values_restored"] += 1
                    else:
                        refused[(label, name)] = True
            doc.Regenerate()
            status = t.Commit()
        except Exception as error:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            data[u"failed"].append(u"restoring parameters - {0}".format(error))
            return
        if not committed(status):
            data[u"failed"].append(u"restoring parameters - Revit rolled it back ({0})"
                                   .format(status))
            return
        still = {}
        for label, element, params in targets:
            now = snapshot_params(element, list(params.keys()))
            for name in core.plan_restore(params, now):
                still[(label, name)] = refused.get((label, name), False)
        if not still:
            break
    for (label, name), was_refused in sorted(still.items()):
        data[u"not_restored"].append(u"{0} - {1}{2}".format(
            label, name, u" (Revit refused the write)" if was_refused else u""))


def change_type_of(pipe, type_id):
    try:
        pipe.ChangeTypeId(type_id)
    except Exception:
        try:
            pipe.PipeType = pipe.Document.GetElement(type_id)
        except Exception:
            pass
    return eid_value(pipe.GetTypeId()) == eid_value(type_id)


def _owner(doc, number):
    try:
        return WorksharingUtils.GetWorksharingTooltipInfo(doc, make_id(number)).Owner
    except Exception:
        return u""


def borrow(doc, numbers):
    """On a workshared model a write to an element nobody has borrowed writes
    nothing and says nothing. Borrow first; name anyone who holds one.

    CheckoutElements answers with everything the user now holds, so only the
    elements missing from that answer are looked at one by one - asking about
    every element as well turned a 5000-element apply into a long wait. If
    the call itself fails, every element is asked about, as before."""
    locked = {}
    numbers = list(numbers)
    if not numbers or not doc.IsWorkshared:
        return locked
    held = None
    try:
        held = set([eid_value(i) for i in
                    WorksharingUtils.CheckoutElements(doc, id_list(numbers))])
    except Exception:
        held = None
    if held is not None:
        for number in numbers:
            if number not in held:
                locked[number] = _owner(doc, number) or u"another user"
        return locked
    for number in numbers:
        try:
            status = WorksharingUtils.GetCheckoutStatus(doc, make_id(number))
            if status == CheckoutStatus.OwnedByOtherUser:
                locked[number] = _owner(doc, number) or u"another user"
        except Exception:
            pass
    return locked


def routing_part_for(pipe_type, fitting):
    """The routing preference fitting the new pipe type wants in place of this
    one, or (None, reason)."""
    try:
        part = u"{0}".format(fitting.MEPModel.PartType)
    except Exception:
        return None, u"no part type"
    group_name = core.routing_group_for(part)
    if group_name is None:
        return None, u"{0} is not set by routing preferences".format(part)
    group = getattr(RoutingPreferenceRuleGroupType, group_name, None)
    if group is None:
        return None, u"this Revit has no {0} routing group".format(group_name)
    try:
        manager = pipe_type.RoutingPreferenceManager
    except Exception:
        return None, u"the type has no routing preferences"
    try:
        if manager.GetNumberOfRules(group) < 1:
            return None, u"no {0} rule on the new type".format(group_name)
    except Exception:
        pass
    size = None
    for connector in model.connectors_of(fitting):
        try:
            size = connector.Radius * 2.0
            break
        except Exception:
            pass
    if size is not None:
        try:
            conditions = RoutingConditions(getattr(RoutingPreferenceErrorLevel, u"None"))
            conditions.AppendCondition(RoutingCondition(size))
            part_id = manager.GetMEPPartId(group, conditions)
            if part_id is not None and eid_value(part_id) > 0:
                return part_id, u""
        except Exception:
            pass
    try:
        part_id = manager.GetRule(group, 0).MEPPartId
        if eid_value(part_id) > 0:
            return part_id, u""
    except Exception:
        pass
    return None, u"no {0} family on the new type".format(group_name)


def slot_parts_for(doc, fittings, new_type):
    """Containment has no routing preferences: a tray or conduit type names
    its fittings in slots (Horizontal Bend, Tee...). A fitting is swapped to
    whatever the new type holds in the slot the old type used it for.
    Worked out before anything changes, while the old type is still on the
    elements around the fitting. {fitting id: (symbol id or None, reason)}"""
    new_slots = model.fitting_slots(new_type)
    out = {}
    for number in fittings:
        fitting = doc.GetElement(make_id(number))
        if fitting is None:
            continue
        symbol = eid_value(fitting.GetTypeId())
        slot = None
        for curve in model.neighbours(fitting):
            if not model.is_curve(curve):
                continue
            old_type = doc.GetElement(curve.GetTypeId())
            for name, value in model.fitting_slots(old_type).items():
                if value == symbol:
                    slot = name
                    break
            if slot:
                break
        if slot is None:
            out[number] = (None, u"not one of the old type's own fittings")
        elif not new_slots.get(slot):
            out[number] = (None, u"the new type has nothing in its {0} slot".format(slot))
        else:
            out[number] = (make_id(new_slots[slot]), u"")
    return out


def change_type_job(pipe_ids, type_id, settings, size_map=None):
    retain = core.split_list(settings.get(u"retain", u""))
    keep_size = core.to_bool(settings.get(u"keep_size"))
    swap = core.to_bool(settings.get(u"swap_fittings"))
    domain = settings.get(u"domain", u"pipe")

    def job(uiapp, result):
        doc = uiapp.ActiveUIDocument.Document
        target = make_id(type_id)
        pipe_type = doc.GetElement(target)
        data = result.data
        data.update({u"changed": 0, u"failed": [], u"locked": [],
                     u"not_restored": [], u"size_changed": [],
                     u"fittings_swapped": 0, u"fitting_failed": [],
                     u"fittings_left": 0, u"already": 0,
                     u"values_restored": 0, u"replaced_fittings": 0,
                     u"wrong_kind": [], u"group_skipped": [], u"groups_reclosed": [],
                     u"swapped_ids": [], u"log_ok": [], u"log_err": [],
                     u"accessories_resized": 0, u"accessories_left": [],
                     u"_accessory_ids": [], u"fittings_already": 0, u"resized": 0,
                     u"to_resize": 0, u"accessories_seen": 0, u"disconnected": [],
                     u"retried": 0})
        if pipe_type is None:
            result.error = u"The chosen type no longer exists."
            return
        to_name = model.elem_name(pipe_type)

        todo = []
        wanted = []
        before = {}
        group_plans = {}

        def consider(number, pipe):
            if number in before:
                return
            wanted.append(number)
            before[number] = (model.elem_name(doc.GetElement(pipe.GetTypeId())),
                              core.feet_to_mm(pipe.Diameter) if hasattr(pipe, u"Diameter")
                              else None)
            if eid_value(pipe.GetTypeId()) == type_id and not \
                    (size_map and number in size_map and before[number][1] is not None and
                     abs(before[number][1] - size_map[number]) > 0.5):
                data[u"already"] += 1
            else:
                todo.append(number)

        for number in pipe_ids:
            pipe = doc.GetElement(make_id(number))
            if pipe is None:
                continue
            if not model.accepts(pipe_type, pipe):
                data[u"wrong_kind"].append(u"{0} - {1} cannot take a {2} type".format(
                    number, model.element_kind(pipe) or u"element",
                    model.type_kind(pipe_type) or u"different"))
                continue
            # a pipe in a group: collected per group type, decided below
            group, instances, nested = model.group_of(doc, pipe)
            if group is not None:
                if nested:
                    data[u"group_skipped"].append(u"{0} - {1}".format(
                        number, core.group_decision(True)[1]))
                    continue
                tid = eid_value(group.GroupType.Id)
                plan = group_plans.setdefault(tid, {u"type": group.GroupType, u"copies": {},
                                                    u"picked": {}})
                gid = eid_value(group.Id)
                plan[u"copies"][gid] = group
                plan[u"picked"].setdefault(gid, []).append(number)
                continue
            consider(number, pipe)

        # groups: one copy is opened and edited, every other copy follows
        groups = _plan_groups(doc, group_plans, size_map, data, consider)

        fittings = []
        if swap:
            changing = set(wanted)
            seen = set()
            for number in wanted:
                pipe = doc.GetElement(make_id(number))
                if pipe is None:
                    continue
                for owner in model.neighbours(pipe):
                    oid = eid_value(owner.Id)
                    if oid in seen or not model.is_fitting(owner):
                        continue
                    seen.add(oid)
                    pipes_around = [eid_value(n.Id) for n in model.neighbours(owner)
                                    if model.is_pipe(n)]
                    if core.fitting_swap_allowed(pipes_around, changing):
                        fittings.append(oid)
                    else:
                        data[u"fittings_left"] += 1

        attached = snapshot_attached(doc, todo, retain)
        locked = borrow(doc, sorted(set(todo + fittings + list(attached.keys()))))
        for number, owner in locked.items():
            data[u"locked"].append(u"{0} - held by {1}".format(number, owner))
        todo = [n for n in todo if n not in locked]
        fittings = [n for n in fittings if n not in locked]
        for number in list(attached.keys()):
            if number in locked:
                del attached[number]

        # every retained value is read now, before anything changes
        pipe_snaps = {}
        for number in todo:
            params = snapshot_params(doc.GetElement(make_id(number)), retain)
            if params:
                pipe_snaps[number] = params

        # containment fittings are matched by slot, so read the old types now
        slot_parts = slot_parts_for(doc, fittings, pipe_type) if domain == u"cont" else None

        group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Change Type")
        group.Start()
        opened = []
        try:
            opened = _open_groups(doc, groups, data)
            # each phase reports its own trouble: a failure part way through
            # must not throw the finished work away, and an opened group has
            # to be closed again whatever happened
            allow_disconnect = core.to_bool(settings.get(u"allow_disconnect"))
            mode = settings.get(u"fitting_mode", u"size_second")
            if not swap:
                mode = u"none"
            data[u"fitting_mode"] = mode
            by_pipe = _fittings_by_pipe(doc, fittings, set(todo)) \
                if mode in (u"together", u"size_second") else {}
            if mode == u"size_second":
                # one thing at a time: the type and its fittings at the size
                # each pipe already has, then the sizes. A routing preference
                # picks a fitting by size, so doing both at once asks Revit to
                # swap every fitting and resize the run in the same move.
                _change_batches(doc, todo, target, True, data, None, mode, by_pipe,
                                pipe_type, slot_parts, True, allow_disconnect)
                resize = core.pipes_to_resize(before, size_map)
                data[u"to_resize"] = len(resize)
                if resize:
                    _change_batches(doc, resize, target, False, data, size_map, mode, by_pipe,
                                    pipe_type, slot_parts, False, allow_disconnect)
                    # one more go at what Revit refused, now its neighbours have
                    # moved - a pipe refused between two old-size pipes often
                    # takes the change once they are done
                    sizes = {}
                    for number in resize:
                        pipe = doc.GetElement(make_id(number))
                        if pipe is not None and hasattr(pipe, u"Diameter"):
                            sizes[number] = core.feet_to_mm(pipe.Diameter)
                    again = core.retry_candidates(core.still_wrong_size(sizes, size_map),
                                                  data.get(u"failed"))
                    data[u"retried"] = len(again)
                    if again:
                        _change_batches(doc, again, target, False, data, size_map, mode,
                                        by_pipe, pipe_type, slot_parts, False,
                                        allow_disconnect)
            else:
                _change_batches(doc, todo, target, keep_size, data, size_map, mode, by_pipe,
                                pipe_type, slot_parts, True, allow_disconnect)
            try:
                if mode == u"after":
                    for number in fittings:
                        _swap_fitting(doc, number, pipe_type, data,
                                      slot_parts.get(number) if slot_parts is not None else None)
                elif mode in (u"together", u"size_second"):
                    # anything a rolled-back chunk left behind
                    done = set(data[u"swapped_ids"])
                    for number in fittings:
                        if number not in done:
                            _swap_fitting(doc, number, pipe_type, data,
                                          slot_parts.get(number) if slot_parts is not None
                                          else None)
            except Exception as error:
                data[u"fitting_failed"].append(u"swapping the fittings stopped: {0}".format(error))
            try:
                restore_pass(doc, pipe_snaps, attached, data)
            except Exception as error:
                data[u"not_restored"].append(u"putting the values back stopped: {0}".format(error))
            try:
                sized = {}
                for number in wanted:
                    pipe = doc.GetElement(make_id(number))
                    if pipe is None or not hasattr(pipe, u"Diameter"):
                        continue
                    sized[number] = (before.get(number, (u"", None))[1],
                                     core.feet_to_mm(pipe.Diameter))
                _resize_accessories(doc, sized, data,
                                    core.split_list(settings.get(u"accessory_params", u"")))
            except Exception as error:
                data[u"accessories_left"].append(u"the accessories stopped: {0}".format(error))
            _close_groups(doc, opened, data)
            group.Assimilate()
        except Exception as error:
            # only something the phases could not contain gets here
            try:
                _close_groups(doc, opened, data)
            except Exception:
                pass
            try:
                group.Assimilate()
            except Exception:
                try:
                    group.RollBack()
                except Exception:
                    pass
            data[u"failed"].append(u"the run stopped: {0}".format(error))
            result.data[u"stopped"] = u"{0}".format(error)
            result.data[u"_stopped_at"] = traceback.format_exc()

        if data.get(u"fitting_mode") == u"reapply" and (todo or fittings):
            # Revit runs a posted command once this job returns, so this is the
            # last thing done here; the log says the fittings follow
            if not _reapply_type_command(uiapp, doc, list(todo) + list(fittings), data):
                for number in fittings:
                    _swap_fitting(doc, number, pipe_type, data,
                                  slot_parts.get(number) if slot_parts is not None else None)

        # prove it: count what is actually on the new type now
        on_type = 0
        for number in wanted:
            pipe = doc.GetElement(make_id(number))
            if pipe is not None and eid_value(pipe.GetTypeId()) == type_id:
                on_type += 1
        data[u"on_type"] = on_type
        data[u"asked"] = len(wanted)
        _change_log(doc, wanted, before, type_id, to_name, size_map, keep_size, data)
    return job


GROUP_MATCH_FT = 10.0 / 304.8       # a pipe matches its counterpart within 10 mm
GROUP_MOVED_FT = 250.0 / 304.8      # a copy whose extents move further was not placed right


def _member_points(doc, group):
    """The middle of every pipe in a group copy, in the model."""
    out = []
    for member in model.group_members(group):
        element = doc.GetElement(make_id(member))
        if element is not None and model.is_curve(element):
            point = model.mid_point(element)
            if point is not None:
                out.append((member, point))
    return out


def _member_frame(doc, group):
    """((centre, angle), {member: its place in that frame}) for a group copy,
    taken from its own members - nothing depends on the group's origin."""
    points = _member_points(doc, group)
    centre, angle = core.local_frame([p for _m, p in points])
    local = {}
    if centre is not None:
        for member, point in points:
            local[member] = core.to_local(point, centre, angle)
    return (centre, angle), local


def _fittings_by_pipe(doc, fittings, changing):
    """{pipe id: [fittings on it]} - which fittings travel with which chunk."""
    out = {}
    for number in fittings or []:
        fitting = doc.GetElement(make_id(number))
        if fitting is None:
            continue
        for owner in model.neighbours(fitting):
            try:
                oid = eid_value(owner.Id)
                if oid in changing:
                    out.setdefault(oid, []).append(number)
            except Exception:
                pass
    return out


def _fittings_for(by_pipe, numbers):
    """Every fitting on this chunk's pipes, once each."""
    out = []
    for number in numbers:
        for fid in by_pipe.get(number, []):
            if fid not in out:
                out.append(fid)
    return out


def _plan_groups(doc, group_plans, size_map, data, consider):
    """Per group type holding a selected pipe: every copy is borrowed (one
    held by somebody else stops the group - changing some copies and not
    others would split it); the copy with most of the selection is the one
    edited; a pipe picked in any other copy is matched to the same pipe in
    that one by where it sits in its group, so the edit covers it."""
    work = []
    for tid, plan in group_plans.items():
        group_type = plan[u"type"]
        name = model.elem_name(group_type)
        try:
            copies = [eid_value(g.Id) for g in group_type.Groups]
        except Exception:
            copies = list(plan[u"copies"].keys())
        held = borrow(doc, sorted(set(copies + [tid])))
        if held:
            owner = sorted(set(held.values()))[0]
            why = core.group_decision(False, owner)[1]
            for ids in plan[u"picked"].values():
                for number in ids:
                    data[u"group_skipped"].append(u"{0} - {1}".format(number, why))
            continue
        edited = max(plan[u"picked"], key=lambda g: len(plan[u"picked"][g]))
        group = plan[u"copies"][edited]
        local = _member_frame(doc, group)[1]
        for number in plan[u"picked"][edited]:
            consider(number, doc.GetElement(make_id(number)))
        via = {}
        for gid, ids in plan[u"picked"].items():
            if gid == edited:
                continue
            copy_frame = _member_frame(doc, plan[u"copies"][gid])[0]
            for number in ids:
                point = model.mid_point(doc.GetElement(make_id(number)))
                match = None
                if point is not None and copy_frame[0] is not None:
                    match = core.counterpart(
                        core.to_local(point, copy_frame[0], copy_frame[1]),
                        local, GROUP_MATCH_FT)
                if match is None:
                    data[u"group_skipped"].append(
                        u"{0} - no matching pipe in the copy of group '{1}' being edited"
                        .format(number, name))
                    continue
                if size_map is not None and number in size_map and match not in size_map:
                    size_map[match] = size_map[number]
                consider(match, doc.GetElement(make_id(match)))
                via.setdefault(gid, []).append(number)
        others = []
        for cid in copies:
            if cid == edited:
                continue
            copy = doc.GetElement(make_id(cid))
            if copy is None:
                continue
            others.append({u"id": cid, u"points": _member_points(doc, copy),
                           u"extents": model.extents(copy)})
        work.append({u"name": name, u"type_id": group_type.Id, u"group": group,
                     u"others": others, u"via": via})
    return work


def _open_groups(doc, work, data):
    """Edit Group, done by hand: ungroup the copy being edited."""
    if not work:
        return []
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - open groups"))
    t.Start()
    opened = []
    try:
        for item in work:
            try:
                item[u"members"] = [eid_value(i) for i in item[u"group"].UngroupMembers()]
                opened.append(item)
            except Exception as error:
                data[u"failed"].append(u"{0} - its group could not be opened: {1}".format(
                    eid_value(item[u"group"].Id), error))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return opened


def _group_replacements(doc, alive, known):
    """What Revit created in place of members it deleted: an element joined to
    a surviving member, in no group, that was not in the group before."""
    known = set(known or [])
    found = []
    for number in alive:
        element = doc.GetElement(make_id(number))
        if element is None:
            continue
        for owner in model.neighbours(element):
            try:
                oid = eid_value(owner.Id)
                if oid in known or oid in found:
                    continue
                if eid_value(owner.GroupId) > 0:
                    continue                    # already in some group
                if not (model.is_curve(owner) or model.is_fitting_or_accessory(owner)):
                    continue
                found.append(oid)
            except Exception:
                pass
    return found


def _rebuild_group(doc, item, data):
    """Put the opened group back together. Anything Revit will not take is
    dropped one at a time rather than losing the group: the elements must
    never be left loose."""
    name = item[u"name"]
    alive = [n for n in item[u"members"] if doc.GetElement(make_id(n)) is not None]
    replacements = _group_replacements(doc, alive, item[u"members"])
    members = core.group_members_now(item[u"members"], alive, replacements)
    if replacements:
        data[u"groups_reclosed"].append(u"{0} - {1} element{2} Revit replaced during the "
                                        u"change went back into the group".format(
                                            name, len(replacements),
                                            u"" if len(replacements) == 1 else u"s"))
    refused = []
    while members:
        t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - close group"))
        t.Start()
        try:
            new_group = doc.Create.NewGroup(id_list(members))
            if committed(t.Commit()):
                if refused:
                    data[u"failed"].append(u"group '{0}' - {1} element{2} Revit would not take "
                                           u"back into it: {3}".format(
                                               name, len(refused),
                                               u"" if len(refused) == 1 else u"s",
                                               u", ".join([u"{0}".format(r) for r in refused[:20]])))
                return new_group
            raise Exception(u"Revit rolled the group back")
        except Exception as error:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            # drop the element Revit named, or the last one, and try again
            named = [n for n in members if u"{0}".format(n) in u"{0}".format(error)]
            drop = named[0] if named else members[-1]
            refused.append(drop)
            members = [n for n in members if n != drop]
    data[u"failed"].append(u"group '{0}' could not be put back together, so its elements are "
                           u"left ungrouped: {1}".format(
                               name, u", ".join([u"{0}".format(n) for n in alive[:30]])))
    return None


def _close_groups(doc, opened, data):
    """Rebuild the edited copy as a group, then move every other copy onto
    that group type - corrected for where Revit put the new type's origin -
    and measure it: a copy whose extents moved is put back on the old group
    and named, never left out of place. When every copy made it, the old
    type goes and the new one takes its name."""
    for item in opened:
        if item.get(u"closed"):
            continue                # never close the same group twice
        item[u"closed"] = True
        name = item[u"name"]
        try:
            new_group = _rebuild_group(doc, item, data)
        except Exception as error:
            data[u"failed"].append(u"group '{0}' - putting it back stopped: {1}".format(
                name, error))
            continue
        if new_group is None:
            continue
        new_type = new_group.GroupType
        stuck = []
        for other in item[u"others"]:
            if not _move_copy(doc, other, new_type):
                stuck.append(other[u"id"])
                data[u"failed"].append(u"{0} - this copy of group '{1}' would not land where it "
                                       u"was on the changed group, so it was left as it was"
                                       .format(other[u"id"], name))
        t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - name group"))
        t.Start()
        try:
            old_type = doc.GetElement(item[u"type_id"])
            if not stuck:
                try:
                    doc.Delete(item[u"type_id"])
                except Exception:
                    pass
            elif old_type is not None:
                old_type.Name = u"{0} (copies not changed)".format(name)
            try:
                new_type.Name = name
            except Exception:
                pass
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        updated = len(item[u"others"]) - len(stuck)
        data[u"groups_reclosed"].append(u"{0} - edited, and {1} of {2} other cop{3} updated"
                                        .format(name, updated, len(item[u"others"]),
                                                u"y" if len(item[u"others"]) == 1 else u"ies"))
        for gid, ids in item[u"via"].items():
            for number in ids:
                if gid in stuck:
                    data[u"group_skipped"].append(u"{0} - its copy of group '{1}' was left as it "
                                                  u"was".format(number, name))
                else:
                    data[u"log_ok"].append(u"{0} - changed through its group '{1}'".format(
                        number, name))


def _move_copy(doc, other, new_type):
    """One copy onto the rebuilt group type, then put back where it was: its
    members' places before and after give the turn and the move
    (core.align_transform) - no group origin involved. Measured afterwards;
    a copy that still moved is rolled back."""
    copy = doc.GetElement(make_id(other[u"id"]))
    if copy is None or not other[u"points"]:
        return False
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - update group copy"))
    t.Start()
    try:
        copy.GroupType = new_type
        doc.Regenerate()
        was = [p for _m, p in other[u"points"]]
        now = [p for _m, p in _member_points(doc, copy)]
        alignment = core.align_transform(was, now)
        if alignment is None:
            t.RollBack()
            return False
        turn, about, move = alignment
        if abs(turn) > 1e-9:
            centre = XYZ(*about)
            axis = Line.CreateBound(centre, XYZ(centre.X, centre.Y, centre.Z + 1.0))
            ElementTransformUtils.RotateElement(doc, copy.Id, axis, turn)
        if abs(move[0]) + abs(move[1]) + abs(move[2]) > 1e-9:
            ElementTransformUtils.MoveElement(doc, copy.Id, XYZ(*move))
        doc.Regenerate()
        if core.bbox_moved(other[u"extents"], model.extents(copy), GROUP_MOVED_FT):
            t.RollBack()
            return False
        return committed(t.Commit())
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return False


def _accessory_params(element):
    """[(name, value mm, writable, instance)] of an accessory's length
    parameters, instance ones marked as such."""
    out = []
    try:
        parameters = list(element.Parameters)
    except Exception:
        return out
    for p in parameters:
        try:
            if u"{0}".format(p.StorageType) != u"Double":
                continue
            out.append((p.Definition.Name, core.feet_to_mm(p.AsDouble()),
                        not p.IsReadOnly, True))
        except Exception:
            pass
    try:
        type_element = element.Document.GetElement(element.GetTypeId())
        for p in list(type_element.Parameters):
            try:
                if u"{0}".format(p.StorageType) != u"Double":
                    continue
                out.append((p.Definition.Name, core.feet_to_mm(p.AsDouble()),
                            not p.IsReadOnly, False))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _accessories_near(doc, number, depth=2):
    """The accessories on a pipe: joined to it, or one fitting away - a valve
    usually sits past an elbow or a tee, not against the pipe, which is why
    looking only at what touches the pipe found none at all."""
    found = []
    seen = set()
    edge = [doc.GetElement(make_id(number))]
    for _step in range(depth):
        nxt = []
        for element in edge:
            if element is None:
                continue
            for owner in model.neighbours(element):
                try:
                    oid = eid_value(owner.Id)
                    if oid in seen:
                        continue
                    seen.add(oid)
                    if model.is_fitting(owner):
                        nxt.append(owner)            # look through a fitting
                    elif model.is_fitting_or_accessory(owner):
                        found.append(owner)
                except Exception:
                    pass
        edge = nxt
    return found


def _resize_accessories(doc, sized, data, names=None):
    """Every pipe accessory joined to a pipe that has changed size takes the
    new size. The parameters named in Settings (BGL_Diameter and any others)
    are set first, by name; where an accessory carries none of them, its own
    size parameters are matched by name and old value instead.
    sized: {pipe id: (old mm, new mm)}."""
    seen = {}
    for number, (old_mm, new_mm) in sized.items():
        if old_mm is None or new_mm is None or abs(old_mm - new_mm) <= 0.5:
            continue
        pipe = doc.GetElement(make_id(number))
        if pipe is None:
            continue
        for owner in _accessories_near(doc, number):
            try:
                seen.setdefault(eid_value(owner.Id), (owner, old_mm, new_mm))
            except Exception:
                pass
    data[u"accessories_seen"] = len(seen)
    if not seen:
        return
    locked = borrow(doc, sorted(seen.keys()))
    for number, owner in locked.items():
        data[u"locked"].append(u"{0} - held by {1}".format(number, owner))
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - accessories"))
    t.Start()
    try:
        for number, (accessory, old_mm, new_mm) in seen.items():
            if number in locked:
                continue
            params = _accessory_params(accessory)
            todo, left = core.accessory_named_plan(params, names or [], new_mm)
            if not todo:
                spare, why = core.accessory_size_plan(params, old_mm, new_mm)
                todo = spare
                left = left + why
            done = 0
            for name, mm in todo:
                try:
                    accessory.LookupParameter(name).Set(core.mm_to_feet(mm))
                    done += 1
                except Exception as error:
                    data[u"accessories_left"].append(u"{0} - {1} would not take the new size "
                                                     u"({2})".format(number, name, error))
            if done:
                data[u"accessories_resized"] += 1
                data[u"_accessory_ids"].append(number)
            elif left:
                data[u"accessories_left"].append(u"{0} - {1}".format(number, u"; ".join(left)))
            else:
                carried = u", ".join([n for n, _v, _w, instance in params if instance][:12])
                data[u"accessories_left"].append(
                    u"{0} - none of the named parameters, and no instance size parameter "
                    u"holding {1}; it carries: {2}".format(
                        number, core.format_size(old_mm), carried or u"no length parameters"))
        doc.Regenerate()
        t.Commit()
    except Exception as error:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        data[u"accessories_left"].append(u"resizing the accessories stopped: {0}".format(error))


def _change_log(doc, wanted, before, type_id, to_name, size_map, keep_size, data):
    """Every pipe and fitting as a line: what it went from and to, or why not.
    success_ids and error_ids feed the 3D error view."""
    reasons = {}
    for key in (u"failed", u"locked", u"fitting_failed", u"group_skipped", u"not_restored",
                u"wrong_kind", u"size_changed"):
        for line in data.get(key) or []:
            head = u"{0}".format(line).split(u" - ", 1)
            if head[0].strip().isdigit() and len(head) == 2:
                reasons.setdefault(int(head[0]), []).append(head[1])
    for number in reasons:
        reasons[number] = core.unique_reasons(reasons[number])
    ok_ids = []
    for number in wanted:
        pipe = doc.GetElement(make_id(number))
        from_type, from_size = before.get(number, (u"", None))
        if pipe is None:
            reasons.setdefault(number, []).append(u"no longer in the model")
            continue
        now = core.feet_to_mm(pipe.Diameter) if hasattr(pipe, u"Diameter") else None
        expected = size_map.get(number) if size_map and number in size_map else \
            (from_size if keep_size else now)
        on_type = eid_value(pipe.GetTypeId()) == type_id
        right_size = expected is None or now is None or abs(now - expected) <= 0.5
        if on_type and right_size and number not in reasons:
            ok_ids.append(number)
            data[u"log_ok"].append(u"{0} - {1} {2} \u2192 {3} {4}".format(
                number, from_type, core.format_size(from_size), to_name, core.format_size(now)))
        elif not on_type and number not in reasons:
            reasons.setdefault(number, []).append(u"still {0}".format(
                model.elem_name(doc.GetElement(pipe.GetTypeId()))))
        elif not right_size and number not in reasons:
            reasons.setdefault(number, []).append(u"size is {0}, wanted {1}".format(
                core.format_size(now), core.format_size(expected)))
    for number in data.get(u"swapped_ids") or []:
        ok_ids.append(number)
        data[u"log_ok"].append(u"{0} - fitting swapped to the routing preferences".format(number))
    for number in data.get(u"_accessory_ids") or []:
        ok_ids.append(number)
        data[u"log_ok"].append(u"{0} - accessory resized with its pipe".format(number))
    for number in sorted(reasons):
        note = u""
        try:
            element = doc.GetElement(make_id(number))
            if element is not None and model.is_curve(element):
                note = core.length_note(element.Location.Curve.Length)
        except Exception:
            note = u""
        data[u"log_err"].append(u"{0} - {1}{2}".format(
            number, u"; ".join(reasons[number]), note))
    for line in data.get(u"failed") or []:
        if not u"{0}".format(line).split(u" - ", 1)[0].strip().isdigit():
            data[u"log_err"].append(u"{0}".format(line))
    data[u"failed"] = core.unique_reasons(data.get(u"failed"))
    data[u"_success_ids"] = sorted(set(ok_ids))
    data[u"_error_ids"] = sorted(set(reasons.keys()))
    try:
        data[u"_system_ids"] = model.whole_system_ids(doc, wanted, u"pipe")
    except Exception:
        data[u"_system_ids"] = list(wanted)


def _pipe_chunk(doc, numbers, target, keep_size, data, batch, size_map=None,
                fittings=None, pipe_type=None, slot_parts=None, change_type=True,
                allow_disconnect=False):
    """One transaction for a chunk - its pipes and, with the fittings joined
    to them, their fittings too. Changing the pipes first and the fittings
    afterwards leaves every fitting on the wrong size in between, which is
    where Revit's warnings and refusals came from. A chunk Revit refuses is
    rolled back and replayed a pipe at a time, so only the one at fault is
    lost."""
    # recorded, not quiet: Revit says why it refuses, and "rolled it back"
    # on its own tells nobody anything
    t, recorder = recorded(Transaction(doc, u"RevoBIM MEP System Manager - change type"),
                           allow_disconnect)
    t.Start()
    pending = {u"changed": 0, u"resized": 0, u"size_changed": [], u"failed": [],
               u"fittings_swapped": 0, u"fittings_already": 0, u"swapped_ids": [],
               u"fitting_failed": []}
    try:
        snaps = {}
        for number in numbers:
            pipe = doc.GetElement(make_id(number))
            snaps[number] = model.size_state(pipe)
            # a size-only pass leaves the type alone
            if change_type and not change_type_of(pipe, target):
                raise Exception(u"type did not change")
        doc.Regenerate()
        wanted = {}
        for number in numbers:
            pipe = doc.GetElement(make_id(number))
            if size_map and number in size_map:
                # the size chosen for it in the mapping, on the new type
                wanted[number] = {u"RBS_PIPE_DIAMETER_PARAM": core.mm_to_feet(size_map[number])}
            else:
                wanted[number] = snaps[number]
            if (keep_size or number in (size_map or {})) and \
                    not core.sizes_equal(wanted[number], model.size_state(pipe)):
                model.set_size_state(pipe, wanted[number])
        doc.Regenerate()
        for number in numbers:
            pipe = doc.GetElement(make_id(number))
            now = model.size_state(pipe)
            expected = wanted[number] if (keep_size or number in (size_map or {})) else now
            if not core.sizes_equal(expected, now):
                pending[u"size_changed"].append(u"{0} - {1} became {2}".format(
                    number, model.size_label(expected), model.size_label(now)))
            pending[u"changed" if change_type else u"resized"] += 1
        # the fittings on these pipes, in the same transaction
        for number in fittings or []:
            _apply_fitting(doc, number, pipe_type, data,
                           (slot_parts or {}).get(number), pending)
        if fittings:
            doc.Regenerate()
        status = t.Commit()
    except Exception as error:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        if batch:
            return False
        data[u"failed"].append(u"{0} - {1}".format(numbers[0], error))
        return True
    if not committed(status):
        if batch:
            return False
        data.setdefault(u"failed", []).append(u"{0} - {1}".format(
            numbers[0], core.failure_text(recorder.errors, recorder.warnings, status)))
        return True
    # counters, never by direct key: a key the job did not set up threw here
    # and took the whole run with it (3.6.0 changed one pipe of 27)
    for key in (u"changed", u"resized", u"fittings_swapped", u"fittings_already"):
        data[key] = data.get(key, 0) + pending.get(key, 0)
    for key in (u"size_changed", u"swapped_ids", u"fitting_failed"):
        data.setdefault(key, []).extend(pending.get(key, []))
    for text, ids in recorder.disconnected:
        data.setdefault(u"disconnected", []).append(u"{0} - {1}".format(
            u", ".join([u"{0}".format(i) for i in ids[:8]]) or u"an element", text[:160]))
    return True


def _apply_fitting(doc, number, pipe_type, data, slot_part, pending):
    """The fitting swap itself, inside whatever transaction is already open -
    used when the fittings change with their pipes."""
    fitting = doc.GetElement(make_id(number))
    if fitting is None:
        return
    if slot_part is not None:
        part_id, reason = slot_part
    else:
        part_id, reason = routing_part_for(pipe_type, fitting)
    if part_id is None:
        pending[u"fitting_failed"].append(u"{0} - {1}".format(number, reason))
        return
    if eid_value(fitting.GetTypeId()) == eid_value(part_id):
        pending[u"fittings_already"] += 1
        return
    joined = model.connected_count(fitting)
    fitting.ChangeTypeId(part_id)
    doc.Regenerate()
    if model.connected_count(fitting) < joined:
        raise Exception(u"{0} - the new fitting would not stay connected".format(number))
    pending[u"fittings_swapped"] += 1
    pending[u"swapped_ids"].append(number)


def _reapply_type_command(uiapp, doc, ids, data):
    """Revit's own Reapply Type, handed the pipes and their fittings. It is a
    posted command: Revit runs it once this job returns, so nothing after it
    can see the result. Returns True if Revit took it."""
    try:
        uiapp.ActiveUIDocument.Selection.SetElementIds(id_list(sorted(ids)))
    except Exception as error:
        data[u"fitting_failed"].append(u"the selection for Reapply Type failed: {0}".format(error))
        return False
    for name in (u"ReapplyType", u"MEPReapplyType", u"PipeReapplyType"):
        member = getattr(PostableCommand, name, None)
        if member is None:
            continue
        try:
            command = RevitCommandId.LookupPostableCommandId(member)
            if command is not None and uiapp.CanPostCommand(command):
                uiapp.PostCommand(command)
                data[u"reapplied"] = len(ids)
                return True
        except Exception:
            pass
    data[u"fitting_failed"].append(u"this Revit does not let an add-in post Reapply Type, so the "
                                   u"fittings were changed with the pipes instead")
    return False


def _change_batches(doc, todo, target, keep_size, data, size_map, mode, by_pipe,
                    pipe_type, slot_parts, change_type=True, allow_disconnect=False):
    """The pipes in batches, each batch with its own fittings. One batch
    cannot stop the rest: whatever goes wrong in a batch is that batch's
    trouble, and a batch Revit refuses is replayed a pipe at a time so only
    the one at fault is lost."""
    with_fittings = mode in (u"together", u"size_second")
    for chunk in core.chunks(todo, 25):
        try:
            fittings = _fittings_for(by_pipe, chunk) if with_fittings else None
            if _pipe_chunk(doc, chunk, target, keep_size, data, True, size_map,
                           fittings, pipe_type, slot_parts, change_type, allow_disconnect):
                continue
        except Exception as error:
            data.setdefault(u"failed", []).append(u"a batch of {0} stopped: {1}".format(
                len(chunk), error))
        for number in chunk:
            try:
                one = _fittings_for(by_pipe, [number]) if with_fittings else None
                _pipe_chunk(doc, [number], target, keep_size, data, False, size_map,
                            one, pipe_type, slot_parts, change_type, allow_disconnect)
            except Exception as error:
                data.setdefault(u"failed", []).append(u"{0} - {1}".format(number, error))


def _swap_fitting(doc, number, pipe_type, data, slot_part=None):
    fitting = doc.GetElement(make_id(number))
    if fitting is None:
        return
    if slot_part is not None:
        part_id, reason = slot_part
    else:
        part_id, reason = routing_part_for(pipe_type, fitting)
    if part_id is None:
        data[u"fitting_failed"].append(u"{0} - {1}".format(number, reason))
        return
    if eid_value(fitting.GetTypeId()) == eid_value(part_id):
        if u"fittings_already" in data:
            data[u"fittings_already"] += 1
        return
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - fitting"))
    t.Start()
    try:
        joined = model.connected_count(fitting)
        fitting.ChangeTypeId(part_id)
        doc.Regenerate()
        if model.connected_count(fitting) < joined:
            t.RollBack()
            data[u"fitting_failed"].append(
                u"{0} - the new fitting would not stay connected, left as it was".format(number))
            return
        status = t.Commit()
    except Exception as error:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        data[u"fitting_failed"].append(u"{0} - {1}".format(number, error))
        return
    if committed(status):
        data[u"fittings_swapped"] += 1
        if u"swapped_ids" in data:
            data[u"swapped_ids"].append(number)
    else:
        data[u"fitting_failed"].append(u"{0} - rolled back ({1})".format(number, status))


def fitting_count_estimate(doc, pipe_ids):
    seen = set()
    for number in pipe_ids:
        try:
            pipe = doc.GetElement(make_id(number))
            for owner in model.neighbours(pipe):
                if model.is_fitting(owner):
                    seen.add(eid_value(owner.Id))
        except Exception:
            pass
    return len(seen)


# ============================================================
# containment: resize runs
# ============================================================

def _runs_for(doc, ids, whole_run, settings):
    """{run key: {"curves": [...], "all": [...]}} for the selected elements -
    the run walk the Run column uses, so a run never crosses into another
    service. Without whole_run only the selected trays and conduits of each
    run are resized."""
    runs = {}
    placed = set()
    for number in sorted(ids):
        if number in placed:
            continue
        element = doc.GetElement(make_id(number))
        if element is None or model.element_kind(element) not in (u"tray", u"conduit"):
            continue
        curves, fittings = model.walk_run(element, settings)
        placed.update(curves)
        chosen = sorted(curves) if whole_run else sorted([c for c in curves if c in ids])
        if chosen:
            runs[min(curves)] = {u"curves": chosen, u"all": sorted(set(curves + fittings)),
                                 u"selected": len([c for c in curves if c in ids])}
    return runs


def _size_mm(element):
    return dict((k, core.feet_to_mm(v)) for k, v in model.size_state(element).items())


def resize_job(ids, width, height, diameter, whole_run, settings=None, mode=u"partial",
               with_fittings=True):
    """Resize containment runs, one transaction per run. A run Revit raises an
    error on is rolled back and reported with the elements it named."""
    def job(uiapp, result):
        doc = uiapp.ActiveUIDocument.Document
        data = result.data
        data.update({u"runs": 0, u"runs_done": 0, u"resized": 0, u"failed_runs": [],
                     u"locked": [], u"warnings": [], u"unchanged": 0, u"no_input": 0,
                     u"not_taken": [], u"run_sizes": [], u"_done_all": [],
                     u"partial_runs": [], u"mode": mode, u"_outcomes": [],
                     u"run_detail": [], u"with_fittings": with_fittings,
                     u"fittings_resized": 0, u"fittings_left": [], u"fitting_params": []})
        runs = _runs_for(doc, set(ids), whole_run, settings or {})
        for key in sorted(runs):
            run = runs[key]
            data[u"run_sizes"].append(u"Run {0} - {1} to resize ({2} selected), {3} "
                                      u"elements with its fittings".format(
                                          key, len(run[u"curves"]), run[u"selected"],
                                          len(run[u"all"])))
        data[u"runs"] = len(runs)
        every = sorted(set([c for r in runs.values() for c in r[u"curves"]]))
        locked = borrow(doc, every)
        for number, owner in locked.items():
            data[u"locked"].append(u"{0} - held by {1}".format(number, owner))

        group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Resize runs")
        group.Start()
        try:
            for key in sorted(runs):
                run = runs[key]
                elements = []
                for number in run[u"curves"]:
                    if number in locked:
                        continue
                    element = doc.GetElement(make_id(number))
                    elements.append({u"id": number, u"kind": model.element_kind(element),
                                     u"size": _size_mm(element)})
                plan, counts = core.resize_plan(elements, width, height, diameter)
                data[u"unchanged"] += counts[u"unchanged"]
                data[u"no_input"] += counts[u"no_input"]
                if not plan:
                    continue
                _resize_run(doc, key, run, plan, data, mode)
            # read the sizes before and after the undo step closes: if they
            # differ, closing it is what moved them, and the table says so
            data[u"before_close"] = _count_at_target(doc, data)
            group.Assimilate()
            _finish_resize(doc, data)
            data[u"after_close"] = data[u"resized"]
        except Exception:
            try:
                group.RollBack()
            except Exception:
                pass
            raise
    return job


def _tray_dims(element):
    """A tray's or conduit's size from its own parameters, in mm."""
    state = model.size_state(element) if element is not None else {}
    out = {}
    for param, dim in ((core.TRAY_WIDTH, u"width"), (core.TRAY_HEIGHT, u"height"),
                       (core.CONDUIT_DIAMETER, u"diameter")):
        if param in state:
            out[dim] = core.feet_to_mm(state[param])
    return out


def _fittings_joined(doc, tray_ids):
    """{fitting id: fitting} joined straight to any of these trays."""
    out = {}
    for number in tray_ids:
        tray = doc.GetElement(make_id(number))
        if tray is None:
            continue
        for owner in model.neighbours(tray):
            try:
                if model.is_fitting(owner):
                    out[eid_value(owner.Id)] = owner
            except Exception:
                pass
    return out


def _fitting_params(fitting):
    """[(name, value mm, writable)] - the fitting's own length parameters."""
    out = []
    try:
        parameters = list(fitting.Parameters)
    except Exception:
        return out
    for p in parameters:
        try:
            if u"{0}".format(p.StorageType) != u"Double":
                continue
            out.append((p.Definition.Name, core.feet_to_mm(p.AsDouble()), not p.IsReadOnly))
        except Exception:
            pass
    return out


def _fitting_plan(fitting):
    """What a fitting needs: its trays' agreed sizes onto its own parameters."""
    trays = [_tray_dims(t) for t in model.neighbours(fitting) if model.is_curve(t)]
    targets = core.fitting_size_targets(trays)
    todo, missing = core.fitting_param_plan(_fitting_params(fitting), targets)
    return targets, todo, missing


def _size_fitting(fitting, stats):
    """Set the fitting's own width / height / diameter parameters to the size
    of the trays joined to it. Never its connectors."""
    _targets, todo, missing = _fitting_plan(fitting)
    for name, mm in todo:
        try:
            fitting.LookupParameter(name).Set(core.mm_to_feet(mm))
            stats[name] = stats.get(name, 0) + 1
        except Exception:
            pass
    if missing:
        stats[u"(no parameter for " + u"/".join(missing) + u")"] = \
            stats.get(u"(no parameter for " + u"/".join(missing) + u")", 0) + 1


def _try_resize(doc, plan, name, with_fittings=True, stats=None):
    """One transaction for these trays' new sizes and, with_fittings, the
    fittings joined to them. Revit gets the first go at the fittings (the
    regenerate after the trays change); any end still at the old size is
    then set here, so trays and fittings are judged by Revit as one change.
    (committed, errors, warnings, exception text) - an error Revit raises
    rolls it all back."""
    t, recorder = recorded(Transaction(doc, u"RevoBIM MEP System Manager - " + name))
    t.Start()
    error = u""
    try:
        for number, changes in plan.items():
            element = doc.GetElement(make_id(number))
            for param, mm in changes.items():
                p = element.get_Parameter(model.bip(param))
                if p is None or p.IsReadOnly:
                    raise Exception(u"{0} has no writable {1}".format(number, param))
                p.Set(core.mm_to_feet(mm))
        doc.Regenerate()
        if with_fittings:
            for _fid, fitting in _fittings_joined(doc, list(plan.keys())).items():
                _size_fitting(fitting, stats if stats is not None else {})
            doc.Regenerate()
        status = t.Commit()
    except Exception as failure:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        status = u"RolledBack"
        error = u"{0}".format(failure)
    return committed(status), recorder.errors, recorder.warnings, error


def _at_target(doc, number, changes):
    element = doc.GetElement(make_id(number))
    if element is None:
        return False, {}
    now = _size_mm(element)
    ok = all([now.get(n) is not None and abs(now[n] - mm) <= 0.01
              for n, mm in changes.items()])
    return ok, now


def _resize_parts(doc, plan, outcome, budget):
    """Resize what Revit allows, keeping neighbours together.

    The trays of a run are joined by fittings that have to match both ends,
    so resizing them one at a time leaves every fitting half old, half new
    for a moment, and Revit can undo the first tray to make the fitting fit
    - which is what made a whole run come out with one tray changed. So:
    try them together; if Revit objects and names trays in the set, set
    those aside and try the rest together again; if it names none of them,
    split the set in two and try each half the same way. budget caps the
    number of attempts. Returns the ids that took."""
    if not plan:
        return []
    if budget[0] <= 0:
        outcome[u"left"].extend(sorted(plan))
        outcome[u"messages"].append(u"gave up after too many attempts")
        return []
    budget[0] -= 1
    outcome[u"tries"] += 1
    ok, errors, warnings, error = _try_resize(doc, plan, u"Resize run",
                                              outcome.get(u"fittings", True),
                                              outcome[u"params"])
    for text, _ids in warnings:
        outcome[u"warnings"].append(text)
    if ok:
        return sorted(plan)
    named = set([i for _t, ids in errors for i in ids])
    outcome[u"named"].extend(sorted(named))
    for text in [t for t, _ids in errors] + ([error] if error else []):
        if text and text not in outcome[u"messages"]:
            outcome[u"messages"].append(text)
    culprits = sorted([n for n in plan if n in named])
    if culprits and len(culprits) < len(plan):
        outcome[u"left"].extend(culprits)
        rest = dict((n, c) for n, c in plan.items() if n not in named)
        return _resize_parts(doc, rest, outcome, budget)
    if len(plan) == 1:
        outcome[u"left"].extend(sorted(plan))
        return []
    ordered = sorted(plan)
    half = len(ordered) // 2
    first = dict((n, plan[n]) for n in ordered[:half])
    second = dict((n, plan[n]) for n in ordered[half:])
    return (_resize_parts(doc, first, outcome, budget) +
            _resize_parts(doc, second, outcome, budget))


def _resize_run(doc, key, run, plan, data, mode=u"partial"):
    """Resize one run and say what was attempted - not what took. What took
    is only known once every run is done (see _finish_resize), because a
    later change can still move an earlier one."""
    outcome = {u"run": key, u"all": run[u"all"], u"plan": plan, u"left": [],
               u"named": [], u"messages": [], u"warnings": [], u"tries": 0, u"mode": mode,
               u"fittings": data.get(u"with_fittings", True), u"params": {}}
    if mode == u"partial":
        _resize_parts(doc, plan, outcome, [max(6, 3 * len(plan))])
    else:
        outcome[u"tries"] = 1
        ok, errors, warnings, error = _try_resize(doc, plan, u"Resize run",
                                                  outcome[u"fittings"], outcome[u"params"])
        outcome[u"warnings"].extend([t for t, _i in warnings])
        if not ok:
            outcome[u"left"] = sorted(plan)
            outcome[u"named"] = [i for _t, ids in errors for i in ids]
            outcome[u"messages"] = [t for t, _i in errors] + ([error] if error else [])
    for text in outcome[u"warnings"]:
        data[u"warnings"].append(u"Run {0} - {1}".format(key, text))
    data[u"_outcomes"].append(outcome)
    return outcome


def _count_at_target(doc, data):
    total = 0
    for outcome in data[u"_outcomes"]:
        for number, changes in outcome[u"plan"].items():
            if _at_target(doc, number, changes)[0]:
                total += 1
    return total


def _finish_resize(doc, data):
    """After every run: read every tray back. Only a tray at its new size now
    counts as resized; one that was changed and has gone back is reported as
    put back by Revit, so the count can never claim what the model does not
    show."""
    for outcome in data[u"_outcomes"]:
        key = outcome[u"run"]
        plan = outcome[u"plan"]
        took = []
        reverted = []
        finals = []
        for number in sorted(plan):
            ok, now = _at_target(doc, number, plan[number])
            finals.append(u"{0}={1}".format(number, u"x".join(
                [core.format_size(v) for _k, v in sorted(now.items())]) or u"-"))
            if ok:
                took.append(number)
            elif number not in outcome[u"left"]:
                reverted.append(number)
        data[u"resized"] += len(took)
        fittings_left = []
        if outcome.get(u"fittings", True) and took:
            for fid, fitting in _fittings_joined(doc, took).items():
                targets, todo, missing = _fitting_plan(fitting)
                if not todo and not missing:
                    data[u"fittings_resized"] += 1
                    continue
                fittings_left.append(fid)
                why = []
                if todo:
                    why.append(u", ".join([u"{0} is not {1}".format(n, core.format_size(mm))
                                           for n, mm in todo]))
                if missing:
                    why.append(u"no {0} parameter to set".format(u"/".join(missing)))
                data[u"fittings_left"].append(u"{0} - {1}".format(fid, u"; ".join(why)))
        for name, count in sorted(outcome.get(u"params", {}).items()):
            data[u"fitting_params"].append(u"Run {0} - {1} set on {2} fitting{3}".format(
                key, name, count, u"" if count == 1 else u"s"))
        outcome[u"fittings_left"] = fittings_left
        for number in reverted:
            data[u"not_taken"].append(u"{0} - changed, then put back by Revit when the trays "
                                      u"around it changed".format(number))
        data[u"run_detail"].append(u"Run {0} - {1} tr{2}, {3} of {4} at the new size; "
                                   u"sizes now: {5}".format(
                                       key, outcome[u"tries"],
                                       u"y" if outcome[u"tries"] == 1 else u"ies",
                                       len(took), len(plan), u", ".join(finals[:40])))
        if took:
            data[u"_done_all"].extend(outcome[u"all"])
        left = sorted(set([n for n in plan if n not in took]))
        if not left and not fittings_left:
            data[u"runs_done"] += 1
            continue
        if not left:
            data[u"failed_runs"].append({
                u"run": key, u"all": outcome[u"all"], u"broken": sorted(fittings_left),
                u"messages": [u"the trays resized, but {0} fitting{1} kept the old size".format(
                    len(fittings_left), u"" if len(fittings_left) == 1 else u"s")],
                u"resized": len(took), u"left": [], u"mode": outcome[u"mode"]})
            continue
        data[u"failed_runs"].append({
            u"run": key, u"all": outcome[u"all"],
            u"broken": sorted(set(outcome[u"named"] + left + fittings_left)),
            u"messages": outcome[u"messages"] or [u"Revit put the size back"],
            u"resized": len(took), u"left": left, u"mode": outcome[u"mode"]})


def highlight_job(run_ids, broken_ids, view_id, settings):
    """Isolate failed runs - the same reset-then-isolate as Isolate Selected -
    then colour the elements Revit named red and select them."""
    def job(uiapp, result):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Show broken runs")
        group.Start()
        try:
            live = [n for n in sorted(set(list(run_ids) + list(broken_ids)))
                    if doc.GetElement(make_id(n)) is not None]
            view, made, status = _isolate_checked(doc, uiapp, view_id, live, settings, result,
                                                  settings.get(u"isolated_view") or 0)
            if view is None:
                group.RollBack()
                return
            if not committed(status):
                group.RollBack()
                result.error = u"Revit rolled the isolate back ({0}).".format(status)
                return
            t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - Highlight"))
            t.Start()
            painted = paint_red(doc, view, [n for n in broken_ids if n in live])
            t.Commit()
            group.Assimilate()
        except Exception:
            try:
                if group.HasStarted() and not group.HasEnded():
                    group.RollBack()
            except Exception:
                pass
            raise
        result.data[u"count"] = len(live)
        result.data[u"painted"] = painted
        result.data[u"view_name"] = model.elem_name(view)
        result.data[u"highlighted"] = core.encode_highlight(eid_value(view.Id), broken_ids)
        try:
            uidoc.ActiveView = view
        except Exception:
            try:
                uidoc.RequestViewChange(view)
            except Exception:
                pass
        try:
            uidoc.Selection.SetElementIds(id_list([n for n in broken_ids if n in live]))
        except Exception:
            pass
        zoom_to(uidoc, view, doc, live)
        _show_now(uidoc, view, result)
    return job


# ============================================================
# Workset Assigner: apply
# ============================================================

def _set_worksets(doc, work, member, data):
    """Write (label, id, workset) in one transaction; any failure is noted."""
    t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - worksets"))
    t.Start()
    failed = []
    try:
        for label, number, target in work:
            element = doc.GetElement(make_id(number))
            if element is None:
                continue
            try:
                p = element.get_Parameter(member)
                if p is None or p.IsReadOnly:
                    failed.append(u"{0} - its workset cannot be changed ({1})".format(number,
                                                                                    label))
                    continue
                p.Set(int(target))
            except Exception as error:
                failed.append(u"{0} - {1}".format(number, error))
        status = t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return committed(status), status, failed


def workset_job(assignments):
    """assignments: [(label, [element ids], workset number)].

    Elements already on their target are left out before anything is
    borrowed. The rest are borrowed in one call and written in one
    transaction; if Revit refuses that, it is rolled back and done again in
    batches of 200 so one bad element cannot lose the others. All inside one
    transaction group - one undo step. Then every element is read back, and a
    system counts as done only when all its elements are on the new workset."""
    def job(uiapp, result):
        doc = uiapp.ActiveUIDocument.Document
        data = result.data
        data.update({u"systems": len(assignments), u"systems_done": 0, u"changed": 0,
                     u"already": 0, u"elements": 0, u"failed": [], u"locked": [],
                     u"not_taken": []})
        clock = time.time()
        timing = []

        work = []
        for label, ids, target in assignments:
            for number in ids:
                data[u"elements"] += 1
                element = doc.GetElement(make_id(number))
                if element is None:
                    continue
                if model.workset_number(element.WorksetId) == target:
                    data[u"already"] += 1
                else:
                    work.append((label, number, target))
        timing.append(u"sorted {0:.1f}s".format(time.time() - clock))

        clock = time.time()
        locked = borrow(doc, sorted(set([n for _l, n, _t in work])))
        for number, owner in locked.items():
            data[u"locked"].append(u"{0} - held by {1}".format(number, owner))
        work = [w for w in work if w[1] not in locked]
        timing.append(u"borrowed {0} in {1:.1f}s".format(len(work), time.time() - clock))

        clock = time.time()
        member = model.bip(u"ELEM_PARTITION_PARAM")
        if work:
            group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Assign worksets")
            group.Start()
            try:
                ok, status, failed = _set_worksets(doc, work, member, data)
                if ok:
                    data[u"failed"].extend(failed)
                else:
                    data[u"batched"] = u"Revit refused the lot ({0}) - done in batches".format(
                        status)
                    for chunk in core.chunks(work, 200):
                        ok, status, failed = _set_worksets(doc, chunk, member, data)
                        data[u"failed"].extend(failed)
                        if not ok:
                            data[u"failed"].append(u"a batch of {0} was rolled back by Revit "
                                                   u"({1})".format(len(chunk), status))
                group.Assimilate()
            except Exception:
                try:
                    group.RollBack()
                except Exception:
                    pass
                raise
        timing.append(u"wrote {0} in {1:.1f}s".format(len(work), time.time() - clock))

        clock = time.time()
        changing = set([n for _l, n, _t in work])
        for label, ids, target in assignments:
            on = 0
            for number in ids:
                element = doc.GetElement(make_id(number))
                if element is not None and model.workset_number(element.WorksetId) == target:
                    on += 1
                    if number in changing:
                        data[u"changed"] += 1
            if on == len(ids):
                data[u"systems_done"] += 1
            else:
                data[u"not_taken"].append(u"{0} - {1} of {2} elements on the new workset"
                                          .format(label, on, len(ids)))
        timing.append(u"proved in {0:.1f}s".format(time.time() - clock))
        data[u"timing"] = u", ".join(timing)
    return job


# ============================================================
# containment: change service type
# ============================================================

def service_job(curve_ids, value, with_fittings, settings):
    """Write a new service type onto trays and conduits - the Service Type
    parameter, or the custom service parameter when that is what groups the
    tab - and, if asked, onto the fittings of their runs. Every value is read
    back."""
    def job(uiapp, result):
        doc = uiapp.ActiveUIDocument.Document
        data = result.data
        data.update({u"changed": 0, u"already": 0, u"failed": [], u"locked": [],
                     u"not_taken": [], u"fittings": 0})
        custom = settings.get(u"group_by") == u"param"
        name = settings.get(u"group_param") if custom else u"Service Type"
        data[u"parameter"] = name
        targets = list(curve_ids)
        if with_fittings:
            seen = set(targets)
            for number in curve_ids:
                element = doc.GetElement(make_id(number))
                if element is None:
                    continue
                old = model.service_of(element, settings)
                _curves, fittings = model.walk_run(element, settings)
                for fid in fittings:
                    if fid in seen:
                        continue
                    fitting = doc.GetElement(make_id(fid))
                    service = model.service_of(fitting, settings) if fitting is not None \
                        else u""
                    # a fitting of another service is the run's edge - leave it
                    if not service or service == old:
                        seen.add(fid)
                        targets.append(fid)
                        data[u"fittings"] += 1
        # already right: not borrowed, not written
        todo = []
        for number in targets:
            element = doc.GetElement(make_id(number))
            if element is None:
                continue
            if model.service_of(element, settings) == value:
                data[u"already"] += 1
            else:
                todo.append(number)
        targets = todo
        locked = borrow(doc, targets)
        for number, owner in locked.items():
            data[u"locked"].append(u"{0} - held by {1}".format(number, owner))
        t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - Change service type"))
        t.Start()
        try:
            for number in targets:
                if number in locked:
                    continue
                element = doc.GetElement(make_id(number))
                if element is None:
                    continue
                if custom:
                    p = find_param(element, name)
                else:
                    p = element.get_Parameter(model.bip(u"RBS_CTC_SERVICE_TYPE"))
                if p is None or p.IsReadOnly:
                    data[u"failed"].append(u"{0} - {1} is missing or read only here (a type "
                                           u"parameter cannot be set per run)".format(number, name))
                    continue
                try:
                    p.Set(value)
                except Exception as error:
                    data[u"failed"].append(u"{0} - {1}".format(number, error))
            status = t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise
        if not committed(status):
            result.error = u"Revit rolled the change back ({0}).".format(status)
            return
        for number in targets:
            if number in locked:
                continue
            element = doc.GetElement(make_id(number))
            if element is None:
                continue
            now = model.service_of(element, settings)
            if now == value:
                data[u"changed"] += 1
            else:
                data[u"not_taken"].append(u"{0} - still reads '{1}'".format(number, now))
    return job


# ============================================================
# Pick System
# ============================================================

def _is_link(element):
    try:
        return isinstance(element, RevitLinkInstance)
    except Exception:
        return False


def _linked_id(reference):
    """The element id inside a linked model a reference points at, or 0 for
    an element of this model."""
    try:
        return eid_value(reference.LinkedElementId)
    except Exception:
        return 0


class PickFilter(ISelectionFilter):
    """Only what sits on a system can be picked: pipes, ducts, trays,
    conduits and their fittings, accessories and flex - and nothing from a
    linked model unless "Look up linked elements" is on
    (core.pick_allowed)."""

    def __init__(self, doc, lookup_linked):
        self.doc = doc
        self.lookup_linked = lookup_linked

    def AllowElement(self, element):
        try:
            if _is_link(element):
                return core.pick_allowed(True, False, False, self.lookup_linked)
            try:
                if element.Document.IsLinked:
                    return core.pick_allowed(False, True, bool(model.domain_of(element)),
                                             self.lookup_linked)
            except Exception:
                pass
            return core.pick_allowed(False, False, bool(model.domain_of(element)),
                                     self.lookup_linked)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        """Only asked in the second step of a linked pick."""
        if not self.lookup_linked:
            return False
        try:
            link = self.doc.GetElement(reference.ElementId)
            inner = link.GetLinkDocument().GetElement(reference.LinkedElementId)
            return core.pick_allowed(False, True, bool(model.domain_of(inner)), True)
        except Exception:
            return False


def pick_job(lookup_linked=False):
    """Ask Revit for one pick. Revit only allows a pick inside a request, so
    this runs as a job like any other. Esc is a cancel, not an error.

    With linked lookup off, anything from a linked model is refused by the
    filter and, should one still come back, thrown away here - result.data
    "linked_refused". With it on, clicking a linked model asks for the
    element inside it, which is reported read-only - "linked"."""
    def job(uiapp, result):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        result.data[u"lookup_linked"] = bool(lookup_linked)
        pick_filter = PickFilter(doc, lookup_linked)
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, pick_filter,
                                             u"Pick a pipe, duct, cable tray or conduit - Esc to cancel")
        except OperationCanceledException:
            result.data[u"cancelled"] = True
            return
        element = doc.GetElement(ref.ElementId)
        if element is None:
            result.error = u"The picked element could not be read."
            return
        if _is_link(element) or _linked_id(ref):
            if not lookup_linked:
                result.data[u"linked_refused"] = True
                return
            _pick_inside_link(uidoc, doc, element, pick_filter, result)
            return
        number = eid_value(element.Id)
        result.data[u"id"] = number
        result.data[u"domain"] = model.domain_of(element)
        try:
            result.data[u"category"] = element.Category.Name
        except Exception:
            result.data[u"category"] = u""
        # a fitting or accessory is found through what it joins
        near = [number]
        if not model.is_curve(element):
            near.extend([eid_value(n.Id) for n in model.neighbours(element)
                         if model.is_curve(n)])
        result.data[u"near"] = near
    return job


def _pick_inside_link(uidoc, doc, link, pick_filter, result):
    """Linked lookup: a linked model was clicked, so ask for the element in
    it and report it - read-only, never changed and never listed."""
    try:
        ref = uidoc.Selection.PickObject(ObjectType.LinkedElement, pick_filter,
                                         u"Now pick the pipe, duct, tray or conduit inside the "
                                         u"linked model - Esc to cancel")
    except OperationCanceledException:
        result.data[u"cancelled"] = True
        return
    try:
        link = doc.GetElement(ref.ElementId)
        link_doc = link.GetLinkDocument()
        inner = link_doc.GetElement(ref.LinkedElementId)
    except Exception:
        result.error = u"The element in the linked model could not be read."
        return
    info = {u"link": model.elem_name(link), u"id": eid_value(inner.Id)}
    try:
        info[u"category"] = inner.Category.Name
    except Exception:
        info[u"category"] = u""
    try:
        system = inner.MEPSystem
        info[u"system"] = model.elem_name(system) if system is not None else u""
    except Exception:
        info[u"system"] = u""
    if not info[u"system"]:
        info[u"system"] = model.builtin_text(inner, u"RBS_SYSTEM_NAME_PARAM") or \
            model.builtin_text(inner, u"RBS_CTC_SERVICE_TYPE")
    try:
        info[u"type"] = model.elem_name(link_doc.GetElement(inner.GetTypeId()))
    except Exception:
        info[u"type"] = u""
    try:
        info[u"size"] = model.size_of(inner)[0]
    except Exception:
        info[u"size"] = u""
    result.data[u"linked"] = info


# ============================================================
# Re-apply Type
# ============================================================

def reapply_job(pipe_ids, settings):
    """What Revit's Reapply Type does, which the API does not offer: every
    fitting on the selected pipes or ducts is put back to what its type's
    routing preferences call for, matched by part type and size. Fittings
    between a selected element and one left alone, or between two types, are
    not touched. Retained parameters are carried over and proved."""
    def job(uiapp, result):
        doc = uiapp.ActiveUIDocument.Document
        data = result.data
        retain = core.split_list(settings.get(u"retain", u""))
        data.update({u"pipes": 0, u"fittings_swapped": 0, u"fittings_already": 0,
                     u"fitting_failed": [], u"locked": [], u"not_restored": [],
                     u"values_restored": 0, u"replaced_fittings": 0, u"failed": [],
                     u"not_selected": 0, u"mixed_types": 0})
        selected = set()
        joined = {}
        for number in pipe_ids:
            pipe = doc.GetElement(make_id(number))
            if pipe is None or not model.is_curve(pipe):
                continue
            selected.add(number)
            for owner in model.neighbours(pipe):
                if not model.is_fitting(owner):
                    continue
                fid = eid_value(owner.Id)
                if fid in joined:
                    continue
                joined[fid] = [(eid_value(n.Id), eid_value(n.GetTypeId()))
                               for n in model.neighbours(owner) if model.is_curve(n)]
        data[u"pipes"] = len(selected)
        plan, left = core.reapply_plan(joined, selected)
        data[u"not_selected"] = left[u"not_selected"]
        data[u"mixed_types"] = left[u"mixed_types"]
        data[u"fittings"] = len(plan)
        attached = snapshot_attached(doc, sorted(selected), retain)
        locked = borrow(doc, sorted(set(list(plan.keys()) + list(attached.keys()))))
        for number, owner in locked.items():
            data[u"locked"].append(u"{0} - held by {1}".format(number, owner))
        for number in list(attached.keys()):
            if number in locked:
                del attached[number]
        group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Re-apply type")
        group.Start()
        try:
            for fid in sorted(plan):
                if fid in locked:
                    continue
                pipe_type = doc.GetElement(make_id(plan[fid]))
                if pipe_type is None:
                    continue
                _swap_fitting(doc, fid, pipe_type, data)
            restore_pass(doc, {}, attached, data)
            group.Assimilate()
        except Exception:
            try:
                group.RollBack()
            except Exception:
                pass
            raise
    return job


# ============================================================
# Change Pipe Type: the errors in 3D
# ============================================================

MAGENTA = (255, 0, 255)


def isolate_errors_job(system_ids, success_ids, error_ids, view_id, settings):
    """The converted systems in full, isolated in the 3D view (reset first,
    as every isolate), then: what changed made 60% transparent, what did not
    drawn with solid magenta projection lines. Reset takes it all off."""
    def job(uiapp, result):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        show = sorted(set([n for n in list(system_ids) + list(error_ids)
                           if doc.GetElement(make_id(n)) is not None]))
        group = TransactionGroup(doc, u"RevoBIM MEP System Manager - Show change errors")
        group.Start()
        try:
            view, made, status = _isolate_checked(doc, uiapp, view_id, show, settings, result,
                                                  settings.get(u"isolated_view") or 0)
            if view is None or not committed(status):
                group.RollBack()
                if not result.error:
                    result.error = u"The isolate did not take ({0}).".format(status)
                return
            t = quiet(Transaction(doc, u"RevoBIM MEP System Manager - Override graphics"))
            t.Start()
            faded = _override(view, [n for n in success_ids if n in set(show)],
                              _transparent(60))
            marked = _override(view, [n for n in error_ids if n in set(show)],
                               _magenta_lines(doc))
            t.Commit()
            group.Assimilate()
        except Exception:
            try:
                if group.HasStarted() and not group.HasEnded():
                    group.RollBack()
            except Exception:
                pass
            raise
        result.data[u"count"] = len(show)
        result.data[u"faded"] = faded
        result.data[u"marked"] = marked
        result.data[u"view_name"] = model.elem_name(view)
        result.data[u"highlighted"] = core.encode_highlight(
            eid_value(view.Id), list(success_ids) + list(error_ids))
        try:
            uidoc.ActiveView = view
        except Exception:
            pass
        zoom_to(uidoc, view, doc, show)
        _show_now(uidoc, view, result)
    return job


def _transparent(percent):
    ogs = OverrideGraphicSettings()
    try:
        ogs.SetSurfaceTransparency(int(percent))
    except Exception:
        pass
    return ogs


def _magenta_lines(doc):
    """As View Specific Element Graphics: projection lines Pattern Solid,
    Colour Magenta."""
    ogs = OverrideGraphicSettings()
    try:
        ogs.SetProjectionLinePatternId(LinePatternElement.GetSolidPatternId())
    except Exception:
        pass
    try:
        ogs.SetProjectionLineColor(Color(*MAGENTA))
    except Exception:
        pass
    return ogs


def _override(view, ids, ogs):
    done = 0
    for number in ids:
        try:
            view.SetElementOverrides(make_id(number), ogs)
            done += 1
        except Exception:
            pass
    return done
