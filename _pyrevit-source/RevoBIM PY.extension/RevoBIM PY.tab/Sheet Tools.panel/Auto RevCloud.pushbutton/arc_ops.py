# -*- coding: utf-8 -*-
"""Auto RevCloud - every write to the model, and the ExternalEvent that
carries them.  The window is modeless, so nothing here is ever called from a
button handler directly: the window parks a job on the handler and raises
the event, and Revit calls Execute on its own thread."""
import math
import os
import sys
import time
import traceback

import arc_clr  # noqa: F401
import arc_compare
import arc_core
import arc_diff
import arc_model

from System.Collections.Generic import List
from Autodesk.Revit.DB import (Transaction, SubTransaction,
                               IFailuresPreprocessor, FailureProcessingResult,
                               FailureSeverity, ElementId, XYZ, Line, Curve,
                               RevisionCloud, Revision, ViewType, CategoryType,
                               BuiltInCategory, BuiltInParameter)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent


# ==========================================================================
# failure handling and dialog suppression
# ==========================================================================

class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                try:
                    if failure.GetSeverity() == FailureSeverity.Warning:
                        accessor.DeleteWarning(failure)
                except Exception:
                    pass
        except Exception:
            pass
        return FailureProcessingResult.Continue


def swallowing(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction


def log_line(text):
    try:
        folder = arc_core.appdata_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(arc_core.log_path(), u"a") as handle:
            handle.write(u"{0}  {1}\n".format(time.strftime(u"%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


# ==========================================================================
# the ExternalEvent handler
# ==========================================================================

class RunHandler(IExternalEventHandler):
    def __init__(self):
        self.job = None

    def Execute(self, uiapp):
        job = self.job
        self.job = None
        if job is None:
            return
        try:
            job.run(uiapp)
        except Exception:
            job.fail(traceback.format_exc())

    def GetName(self):
        return u"RevoBIM Auto RevCloud"


def make_event():
    handler = RunHandler()
    return handler, ExternalEvent.Create(handler)


class PairResult(object):
    u"""One view's worth of result."""

    def __init__(self, number, against, sheet_id=0):
        self.number = number
        self.against = against
        # Held by id, not as an Element handle: the Completed button opens
        # these after the run, and a handle captured earlier can be stale.
        self.sheet_id = sheet_id
        self.clouds = 0
        self.in_views = 0
        self.notes = []      # lines that should open the results window
        self.info = []       # routine lines that should not
        self.error = None
        self.rects_ft = []

    def as_dict(self):
        return {u"number": self.number, u"against": self.against,
                u"clouds": self.clouds,
                u"in_views": self.in_views, u"notes": list(self.notes),
                u"info": list(self.info), u"error": self.error}


# ==========================================================================
# drawing the clouds
# ==========================================================================

# Which side of the sketched loop a revision cloud's arcs bulge towards is
# decided by the loop's WINDING ORDER, not by any API flag - there is nothing
# on RevisionCloud to set it and nothing to read it back from.  A loop drawn
# one way round gives arcs outside the rectangle (what a re-cloud should look
# like); the other way round gives the scalloped-inwards version.
#
# CCW_IS_OUTWARD records which way round that is.  It could not be settled on
# the bench - Revit exposes nothing to read the convention back from - so it
# shipped as a guess with `cloud_arc_side` as the escape hatch.  The guess was
# wrong: on Revit 2024 a CLOCKWISE loop gives the arcs outside.  Settled by
# running it, which was the only way it was ever going to be.
CCW_IS_OUTWARD = False


def _flatten(points, right, up):
    """The loop in the VIEW's own 2D basis.

    Measured in the view's basis rather than in world XY on purpose: a section,
    or a plan on a rotated crop, puts the same model-space loop the other way
    round on screen, and measuring in world coordinates would flip the arcs on
    exactly those views.
    """
    flat = []
    for p in points:
        flat.append((p.X * right.X + p.Y * right.Y + p.Z * right.Z,
                     p.X * up.X + p.Y * up.Y + p.Z * up.Z))
    return flat


def _orient_loop(points, right, up, outward=True):
    """Return the loop wound so the cloud's arcs bulge the way asked for."""
    want_ccw = outward if CCW_IS_OUTWARD else not outward
    if arc_compare.should_reverse(_flatten(points, right, up), want_ccw):
        return list(reversed(points))
    return points


def _arcs_outward(settings):
    return arc_core.unicode_str(
        settings.get(u"cloud_arc_side", u"out")).strip().lower() != u"in"


_NO_CLOUD_VIEWS = (u"Legend", u"Schedule", u"ColumnSchedule",
                   u"PanelSchedule", u"DraftingView")


def _view_basis(view):
    """The view's own right/up, falling back to world XY."""
    try:
        return view.RightDirection, view.UpDirection
    except Exception:
        return XYZ(1.0, 0.0, 0.0), XYZ(0.0, 1.0, 0.0)


def _closed_lines(corners):
    curves = List[Curve]()
    count = len(corners)
    for i in range(count):
        a = corners[i]
        b = corners[(i + 1) % count]
        curves.Add(Line.CreateBound(a, b))
    return curves


def _view_takes_clouds(view):
    """Looked up by name so a member missing from one release cannot take
    the whole check down."""
    try:
        kind = view.ViewType
    except Exception:
        return True
    for name in _NO_CLOUD_VIEWS:
        member = getattr(ViewType, name, None)
        if member is not None and kind == member:
            return False
    return True


def _create_cloud(doc, view, revision_id, curves):
    u"""One cloud in its own sub-transaction so a refusal leaves nothing.

    The window carries ids as plain integers - that is what the row dicts hold
    and what gets compared - so anything handed to the API is coerced here
    rather than at each call site. Revit answers a raw integer with "expected
    ElementId, got Int64" and refuses every cloud, which reads as "the run
    worked and drew nothing".
    """
    revision_id = arc_model.make_id(revision_id)
    sub = SubTransaction(doc)
    sub.Start()
    try:
        cloud = RevisionCloud.Create(doc, view, revision_id, curves)
        sub.Commit()
        return cloud
    except Exception:
        try:
            sub.RollBack()
        except Exception:
            pass
        raise


ARC_DONE = []


def apply_arc_length(doc, cloud, arc_mm, result):
    """Set the scallop size on the cloud's TYPE, once per run.

    Deliberately opt-in and reported: arc length lives on the revision cloud
    type, so changing it re-draws every cloud already in the project, not just
    the ones this run made. Nothing wide-reaching happens by default.
    """
    if arc_mm <= 0 or cloud is None:
        return
    try:
        type_id = cloud.GetTypeId()
    except Exception:
        return
    key = arc_model.eid_value(type_id)
    if key in ARC_DONE:
        return
    ARC_DONE.append(key)
    try:
        cloud_type = doc.GetElement(type_id)
        if cloud_type is None:
            return
        param = None
        try:
            bip = getattr(BuiltInParameter, u"REVISION_CLOUD_ARC_LENGTH")
            param = cloud_type.get_Parameter(bip)
        except Exception:
            param = None
        if param is None:
            for candidate in cloud_type.GetParameters(u"Arc length"):
                if not candidate.IsReadOnly:
                    param = candidate
                    break
        if param is None or param.IsReadOnly:
            result.notes.append(u"the revision cloud type would not take an arc length")
            return
        wanted = float(arc_mm) / arc_core.MM_PER_FT
        param.Set(wanted)
        # A void API call is not evidence - read it back.
        got = param.AsDouble()
        if abs(got - wanted) > 1e-6:
            result.notes.append(u"arc length did not take (asked {0:.1f}mm, read "
                                u"back {1:.1f}mm)".format(arc_mm, got * arc_core.MM_PER_FT))
        else:
            result.notes.append(u"revision cloud type arc length set to {0:.1f}mm - "
                                u"this affects every cloud on that type, not just "
                                u"this run".format(arc_mm))
    except Exception as exc:
        result.notes.append(u"arc length could not be set: {0}".format(
            arc_core.unicode_str(exc)[:100]))


def _failed_at():
    """Where the exception actually came from - the deepest frame in this
    tool's own code, which is more use than the one that re-raised it."""
    try:
        frames = traceback.extract_tb(sys.exc_info()[2])
    except Exception:
        return u"unknown"
    for frame in reversed(frames):
        try:
            name = os.path.basename(frame[0])
            if name.startswith(u"arc_"):
                return u"{0}:{1} in {2}()".format(name, frame[1], frame[2])
        except Exception:
            continue
    return u"unknown"


# ==========================================================================
# jobs
# ==========================================================================

class CompareJob(object):
    u"""Compare each view against the same view's elements in a linked model.

    plan: list of (view_id, label, categories or None, revision_id). A view
    with its own category list uses it, None means the list from Settings; the
    revision is per view, already resolved against the default by the window.
    link_id: the RevitLinkInstance to compare against.
    revision_id: the fallback revision, for a plan entry carrying none.
    """

    def __init__(self, window, settings, plan, link_id, revision_id):
        self.window = window
        self.settings = settings
        self.plan = plan
        self.link_id = link_id
        self.revision_id = revision_id
        self.results = []
        self.error = None

    def fail(self, text):
        self.error = text
        log_line(u"compare failed:\n" + text)
        try:
            self.window.job_finished(self)
        except Exception:
            pass

    def run(self, uiapp):
        doc = uiapp.ActiveUIDocument.Document
        total = max(1, len(self.plan))
        # NO TransactionGroup around the run. It used to wrap the whole loop
        # so undo saw one step - and the progress callback pumps the
        # dispatcher between views, which dispatches real mouse and keyboard
        # messages while that group is open. Pumping inside a transaction is
        # the rule this extension has written down twice and broken here; it
        # took Revit down. Reading and comparing need no transaction at all,
        # and each view's clouds get their own, with nothing pumped inside it.
        # The cost is that undo is one step per view rather than one for the
        # run, which is a great deal better than a crash.
        try:
            del ARC_DONE[:]

            log_line(u"run starting: {0} view(s), link id {1}, revision {2}".format(
                len(self.plan), self.link_id, self.revision_id))
            link = arc_diff.link_by_id(doc, self.link_id)
            trouble = arc_diff.link_state(doc, link)
            if trouble:
                raise RuntimeError(trouble)
            link_doc = link.GetLinkDocument()
            transform = link.GetTotalTransform()
            default_names = arc_core.parse_categories(
                self.settings.get(u"compare_categories", u""))

            for index, entry in enumerate(self.plan):
                view_id, label, own = entry[0], entry[1], entry[2]
                revision_id = (entry[3] if len(entry) > 3 else 0) or self.revision_id
                names = own if own else default_names
                view = doc.GetElement(arc_model.make_id(view_id))
                result = PairResult(label, arc_core.unicode_str(link_doc.Title),
                                    view_id)
                self.results.append(result)

                def progress(text, step=0.0, _i=index, _n=total, _label=label):
                    # Logged as well as shown. The log is written and closed
                    # per line, so if Revit goes down mid-view the last entry
                    # names the stage it was in - which is the only thing that
                    # makes a hard crash diagnosable at all.
                    log_line(u"[{0}/{1}] {2}: {3}".format(_i + 1, _n, _label, text))
                    fraction = (_i + max(0.0, min(1.0, step))) / float(_n)
                    self.window.report_progress(fraction, text, sheet=_label,
                                                index=_i + 1, total=_n)

                if view is None:
                    result.error = u"that view no longer exists"
                    continue
                self.window.report_row(index, u"working...", u"muted")
                try:
                    changes, notes, info = compare_view(
                        doc, link_doc, transform, view, self.settings, names,
                        progress)
                    result.notes.extend(notes)
                    result.info.extend(info)
                    if changes:
                        # Reported BEFORE the transaction opens, never inside
                        # it - report_progress pumps.
                        progress(u"Clouding", 0.85)
                        draw_change_clouds(doc, self.settings, view,
                                           revision_id, changes, result)
                    log_line(u"{0}: {1} clouds; {2}".format(
                        label, result.clouds,
                        u"; ".join(result.notes + result.info)))
                    if result.clouds:
                        self.window.report_row(
                            index, u"{0} cloud(s)".format(result.clouds),
                            u"orange" if result.notes else u"green")
                    else:
                        self.window.report_row(index, u"no change", u"green")
                except Exception as exc:
                    result.error = u"{0}  [{1}]".format(
                        arc_core.describe_exception(exc), _failed_at())
                    log_line(u"{0} failed:\n{1}".format(label, traceback.format_exc()))
                    self.window.report_row(index, u"failed", u"red")
            self.window.report_progress(1.0, u"Done")
        except Exception:
            self.fail(traceback.format_exc())
            return
        try:
            self.window.job_finished(self)
        except Exception:
            pass


def compare_view(doc, link_doc, transform, view, settings, names, progress):
    u"""The whole comparison for one view. Returns (clusters, notes, info).

    A cluster is (box_in_view_feet, [change, ...]).
    """
    notes = []
    info = []

    kind = arc_model.view_kind(view)
    if kind in arc_model.NO_COMPARE_KINDS:
        notes.append(u"a {0} cannot be compared - add the views on it, or a "
                     u"plan, section or elevation".format(kind or u"view of this kind"))
        return [], notes, info

    progress(u"Reading the view", 0.10)
    param_names = arc_core.parse_categories(
        settings.get(u"compare_params", u"")) if arc_core.as_bool(
        settings, u"check_params") else []
    host, matched, missing, refused = arc_diff.host_items(
        doc, view, names, log=log_line, param_names=param_names)
    if not matched:
        notes.append(u"none of the listed categories exist in this model - "
                     u"check the list in Settings")
        return [], notes, info
    if missing:
        info.append(u"not in this model: {0}".format(u", ".join(missing[:8])))
    if refused:
        notes.append(u"Revit would not filter on: {0}".format(u", ".join(refused[:8])))

    progress(u"Reading the link", 0.35)
    outline = arc_diff.view_outline(view)
    if outline is None:
        info.append(u"the view has no crop box, so the whole link was read")
    link_side, _m, _x, link_refused = arc_diff.link_items(
        link_doc, transform, names, outline, log=log_line,
        param_names=param_names)
    if link_refused:
        notes.append(u"the link would not filter on: {0}".format(
            u", ".join(link_refused[:8])))
    info.append(u"{0} elements in the view, {1} in the link".format(
        len(host), len(link_side)))

    if not link_side:
        notes.append(u"nothing of these categories was found in the link within "
                     u"this view - check the link is the right model and is "
                     u"positioned on top of the current one")
        return [], notes, info

    progress(u"Comparing", 0.60)
    move_tol = arc_core.as_float(settings, u"move_tol_mm") / arc_core.MM_PER_FT
    size_tol = arc_core.as_float(settings, u"size_tol_mm") / arc_core.MM_PER_FT
    stats = {}
    method = arc_core.unicode_str(settings.get(u"match_method", u"id")).lower()
    if method == u"spatial":
        spatial_tol = arc_core.as_float(settings, u"spatial_tol_mm") / arc_core.MM_PER_FT
        search = arc_core.as_float(settings, u"spatial_search_mm") / arc_core.MM_PER_FT
        info.append(u"compared spatially, {0:.0f}mm tolerance".format(
            arc_core.as_float(settings, u"spatial_tol_mm")))
        changes = arc_compare.diff_spatially(
            host, link_side, spatial_tol, spatial_tol,
            check_type=arc_core.as_bool(settings, u"check_type"),
            search=search)
    else:
        changes = arc_compare.diff_items(
            host, link_side, move_tol, size_tol,
            check_type=arc_core.as_bool(settings, u"check_type"),
            use_eid=arc_core.as_bool(settings, u"match_by_eid"),
            angle_tol=arc_core.as_float(settings, u"rotate_tol_deg") * math.pi / 180.0,
            stats=stats,
            guid_mode=arc_core.unicode_str(settings.get(u"guid_mode", u"off")).lower())
        # The line that says WHY a run found what it found. All three of
        # "nothing matched", "everything matched" and "half matched" look the
        # same from the cloud count alone.
        info.append(u"matched {0} by UniqueId, {1} by ElementId; {2} in the "
                    u"view with no counterpart, {3} in the link with none".format(
                        stats.get(u"by_uid", 0), stats.get(u"by_eid", 0),
                        stats.get(u"unmatched", 0), stats.get(u"link_only", 0)))
        if arc_core.unicode_str(settings.get(u"guid_mode", u"off")).lower() != u"off":
            same = stats.get(u"guid_same", 0)
            differs = stats.get(u"guid_differs", 0)
            unknown = stats.get(u"guid_unknown", 0)
            # This line answers the question the option depends on: does the
            # VersionGuid survive the way the previous version was made? If
            # nearly every matched pair differs, it does not, and the option
            # is reading noise.
            info.append(u"VersionGuid: {0} matched pair(s) identical, {1} "
                        u"differ, {2} unreadable".format(same, differs, unknown))
            if same + differs > 20 and same < (same + differs) * 0.2:
                notes.append(u"the VersionGuid differs on almost every matched "
                             u"element - it does not survive however this link "
                             u"was made, so it is not telling you about changes. "
                             u"Turn the VersionGuid option off for this link.")
        if not stats.get(u"by_uid") and not stats.get(u"by_eid") and host:
            notes.append(u"not one element matched between the two models - "
                         u"the link is probably not a previous version of this "
                         u"model. Settings has a spatial method for that case.")
    if not arc_core.as_bool(settings, u"cloud_removed"):
        changes = [c for c in changes if c[u"kind"] != arc_compare.REMOVED]
    # Option 2: drop a move or a resize that would not show on this drawing.
    if arc_core.as_bool(settings, u"only_visible") and changes:
        origin, right, up = arc_diff.view_frame(view)
        scale = max(1, arc_model.view_scale(view))
        visible_tol = (arc_core.as_float(settings, u"visible_tol_mm") * scale
                       ) / arc_core.MM_PER_FT
        changes, unseen = arc_compare.only_visible(changes, origin, right, up,
                                                   visible_tol)
        if unseen:
            info.append(u"{0} change(s) would not show in this view and were "
                        u"not clouded".format(unseen))

    # A removal means the element is gone from the model, not that this view
    # stopped drawing it.
    changes, hidden_removals = arc_diff.still_in_host(doc, changes)
    if hidden_removals:
        info.append(u"{0} apparent removal(s) are still in the model, just not "
                    u"drawn in this view - not clouded".format(hidden_removals))

    if not changes:
        return [], notes, info

    counts = {}
    new_ids = 0
    for change in changes:
        counts[change[u"kind"]] = counts.get(change[u"kind"], 0) + 1
        if change.get(u"new_id"):
            new_ids += 1
    if new_ids:
        info.append(u"{0} element(s) have ids that are not in the link at "
                    u"all".format(new_ids))
    info.append(u"changes: " + u", ".join(
        u"{0} {1}".format(v, k) for k, v in sorted(counts.items())))

    origin, right, up = arc_diff.view_frame(view)
    scale = max(1, arc_model.view_scale(view))
    # Paper millimetres, so a cloud looks the same at 1:50 and 1:100.
    merge_ft = (arc_core.as_float(settings, u"merge_mm") * scale) / arc_core.MM_PER_FT
    offset_ft = (arc_core.as_float(settings, u"offset_mm") * scale) / arc_core.MM_PER_FT

    boxes = [arc_compare.item_box(c, origin, right, up) for c in changes]
    clusters = arc_compare.cluster_boxes(boxes, merge_ft)
    if len(clusters) != len(changes):
        info.append(u"{0} change(s) grouped into {1} cloud(s)".format(
            len(changes), len(clusters)))

    max_clouds = arc_core.as_int(settings, u"max_clouds")
    if len(clusters) > max_clouds:
        # Kept largest-first, which quietly drops a single new pipe in favour
        # of one big cluster - and a new element is the thing least worth
        # losing. Anything containing something not in the link at all is
        # kept before anything that is merely different.
        def worth(entry):
            members = [changes[i] for i in entry[1]]
            has_new = any(m.get(u"new_id") or m[u"kind"] == arc_compare.ADDED
                          for m in members)
            return (0 if has_new else 1, -len(members))

        ordered = sorted(clusters, key=worth)
        kept_new = len([c for c in ordered[:max_clouds]
                        if any(changes[i].get(u"new_id") for i in c[1])])
        notes.append(u"{0} groups found, only {1} clouded - new elements first, "
                     u"then the largest. If changes are everywhere, the link is "
                     u"probably not a previous version of this model.".format(
                         len(clusters), max_clouds))
        if kept_new:
            info.append(u"{0} of the clouds drawn are elements not in the "
                        u"link at all".format(kept_new))
        clusters = ordered[:max_clouds]

    out = []
    for box, members in clusters:
        out.append((arc_compare.grow_box(box, offset_ft),
                    [changes[i] for i in members]))
    return out, notes, info


def draw_change_clouds(doc, settings, view, revision_id, clusters, result):
    u"""One cloud per cluster, in the view, with a comment saying what moved."""
    transaction = swallowing(Transaction(doc, u"Auto RevCloud clouds"))
    transaction.Start()
    try:
        origin, right, up = arc_diff.view_frame(view)
        outward = _arcs_outward(settings)
        arc_mm = arc_core.as_float(settings, u"cloud_arc_mm")
        comment_on = arc_core.as_bool(settings, u"write_comments")
        limit = arc_core.as_int(settings, u"comment_items")
        for box, members in clusters:
            corners = [
                arc_diff.frame_to_model(box[0], box[1], origin, right, up),
                arc_diff.frame_to_model(box[2], box[1], origin, right, up),
                arc_diff.frame_to_model(box[2], box[3], origin, right, up),
                arc_diff.frame_to_model(box[0], box[3], origin, right, up),
            ]
            corners = _orient_loop(corners, _xyz(right), _xyz(up), outward)
            try:
                cloud = _create_cloud(doc, view, revision_id, _closed_lines(corners))
            except Exception as exc:
                result.notes.append(u"a cloud was refused: {0}".format(
                    arc_core.unicode_str(exc)[:110]))
                continue
            result.clouds += 1
            result.in_views += 1
            apply_arc_length(doc, cloud, arc_mm, result)
            if comment_on:
                text = arc_compare.describe(members, limit)
                if not arc_diff.set_comment(cloud, text):
                    result.notes.append(
                        u"the cloud's Comments would not take '{0}'".format(text))
        transaction.Commit()
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        raise


def _xyz(triple):
    return XYZ(triple[0], triple[1], triple[2])


class AddRevisionJob(object):
    u"""Create one revision from the dialog's details."""

    def __init__(self, window, details):
        self.window = window
        self.details = details or {}
        self.new_id = 0
        self.notes = []
        self.error = None

    def fail(self, text):
        self.error = text
        log_line(u"add revision failed:\n" + text)
        try:
            self.window.job_finished(self)
        except Exception:
            pass

    def run(self, uiapp):
        doc = uiapp.ActiveUIDocument.Document
        transaction = swallowing(Transaction(doc, u"Auto RevCloud - new revision"))
        transaction.Start()
        try:
            revision = Revision.Create(doc)
            self.notes = arc_diff.apply_revision_fields(revision, self.details, doc)
            transaction.Commit()
            check = doc.GetElement(revision.Id)
            if check is None:
                raise RuntimeError(u"the revision did not survive the commit")
            self.new_id = arc_model.eid_value(revision.Id)
        except Exception:
            try:
                transaction.RollBack()
            except Exception:
                pass
            raise
        self.window.job_finished(self)


class EditRevisionJob(object):
    u"""Apply the dialog's fields to a revision that already exists."""

    def __init__(self, window, details):
        self.window = window
        self.details = details or {}
        self.notes = []
        self.error = None

    def fail(self, text):
        self.error = text
        log_line(u"edit revision failed:\n" + text)
        try:
            self.window.job_finished(self)
        except Exception:
            pass

    def run(self, uiapp):
        doc = uiapp.ActiveUIDocument.Document
        revision = doc.GetElement(arc_model.make_id(self.details.get(u"id", 0)))
        if revision is None:
            self.fail(u"that revision is no longer in the project")
            return
        transaction = swallowing(Transaction(doc, u"Auto RevCloud - edit revision"))
        transaction.Start()
        try:
            self.notes = arc_diff.apply_revision_fields(revision, self.details, doc)
            transaction.Commit()
        except Exception:
            try:
                transaction.RollBack()
            except Exception:
                pass
            raise
        log_line(u"edited revision {0}; {1}".format(
            self.details.get(u"id"), u"; ".join(self.notes) or u"all fields took"))
        self.window.job_finished(self)


class OpenSheetsJob(object):
    """Open each sheet that got clouds, on Revit's own thread.

    A modeless window cannot change the active view directly any more than it
    can start a transaction, so this goes out through the same ExternalEvent
    as everything else. Nothing here writes to the model.
    """

    def __init__(self, window, sheet_ids):
        self.window = window
        self.sheet_ids = list(sheet_ids)
        self.opened = 0
        self.skipped = []
        self.error = None

    def fail(self, text):
        self.error = text
        log_line(u"open sheets failed:\n" + text)
        try:
            self.window.job_finished(self)
        except Exception:
            pass

    def run(self, uiapp):
        try:
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            # Opened last-first, so the first sheet in the list is the one
            # left in front when the run finishes rather than the last one.
            for sheet_id in reversed(self.sheet_ids):
                # Views and sheets alike - both are Views to Revit, and
                # RequestViewChange takes either.
                sheet = doc.GetElement(arc_model.make_id(sheet_id))
                if sheet is None:
                    self.skipped.append(u"a view no longer exists")
                    continue
                number = arc_model.element_name(sheet)
                try:
                    uidoc.RequestViewChange(sheet)
                    self.opened += 1
                except Exception as exc:
                    self.skipped.append(u"{0}: {1}".format(
                        number, arc_core.unicode_str(exc)[:80]))
            log_line(u"opened {0} sheet(s), {1} skipped".format(
                self.opened, len(self.skipped)))
            self.window.job_finished(self)
        except Exception:
            self.fail(traceback.format_exc())
