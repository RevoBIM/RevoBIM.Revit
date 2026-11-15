# -*- coding: utf-8 -*-
"""Tag Aligner: one run of Align Left / Center / Right or Untangle Vertical /
Horizontal.

Order of a run:
  read the selection (or ask for tags), read the reference click if the
  settings want one, read text heights (EditFamily, outside any transaction),
  check the tags out on a workshared model, then ONE transaction:
  measure with leaders off -> work out the moves -> move -> regenerate ->
  measure again and compare with what was promised -> commit.
The count reported is of tags measured in their new place, not of calls that
did not throw.
"""
import ta_clr  # noqa: F401  must stay first

import traceback

from Autodesk.Revit.DB import (
    FailureProcessingResult,
    FailureSeverity,
    IFailuresPreprocessor,
    Transaction,
    TransactionStatus,
)
from Autodesk.Revit.Exceptions import OperationCanceledException

import ta_core as core
import ta_model as model

MODES = {
    u"align_left": (u"align", u"left", u"Align Left"),
    u"align_centre": (u"align", u"centre", u"Align Center"),
    u"align_right": (u"align", u"right", u"Align Right"),
    u"untangle_v": (u"untangle", u"vertical", u"Untangle Vertical"),
    u"untangle_h": (u"untangle", u"horizontal", u"Untangle Horizontal"),
}

REFERENCE_WORDS = {
    u"first": u"the first tag selected",
    u"average": u"the average of all of them",
    u"pick": u"the tag you clicked",
}


class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings so Revit raises no dialog mid run; errors still
    stop the transaction and are reported."""

    def PreprocessFailures(self, accessor):
        try:
            for message in accessor.GetFailureMessages():
                if message.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(message)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _quiet(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass


def _mm(feet):
    return core.format_number(feet * core.MM_PER_FOOT)


def _paper_mm(model_feet, scale):
    return core.format_number(model_feet * core.MM_PER_FOOT / float(scale))


def run(uidoc, mode, settings, log):
    kind, which, label = MODES[mode]
    report = core.Report(u"Tag " + label)
    doc = uidoc.Document
    view = uidoc.ActiveView
    log.add(u"mode {0}".format(mode))

    axes = model.view_axes(view)
    if axes is None:
        report.error(u"Tags cannot be moved in this view. Open a plan, "
                     u"section, elevation or drafting view.")
        return report
    right, up = axes
    scale = model.view_scale(view)
    log.add(u"view {0} scale 1:{1} right {2} up {3}".format(
        model.eid_value(view.Id), scale, right, up))

    # ======================================================================
    # Which tags
    # ======================================================================
    tags, selected, elsewhere = model.selected_tags(uidoc, view)
    if not tags and selected == 0:
        try:
            tags = model.pick_tags(uidoc, view)
        except OperationCanceledException:
            report.cancelled = True
            return report
    if elsewhere:
        report.warn(u"{0} selected tag(s) belong to another view and were "
                    u"left alone.".format(elsewhere))
    if not tags:
        report.error(u"None of the {0} selected element(s) is a tag in this "
                     u"view.".format(selected) if selected else
                     u"No tags were selected.")
        return report

    ref_tag = None
    if kind == u"align" and settings[u"align_reference"] == u"pick":
        try:
            ref_tag = model.pick_reference(uidoc)
        except OperationCanceledException:
            report.cancelled = True
            return report
        if ref_tag is not None and \
                model.eid_value(ref_tag.OwnerViewId) != \
                model.eid_value(view.Id):
            report.error(u"The reference tag is in another view.")
            return report

    by_key = dict((model.eid_value(t.Id), t) for t in tags)
    ref_key = model.eid_value(ref_tag.Id) if ref_tag is not None else None
    movers = len(tags)
    if kind == u"untangle" and movers < 2:
        report.error(u"Select at least two tags to untangle.")
        return report
    if kind == u"align" and movers < 2 and \
            (ref_tag is None or ref_key in by_key):
        report.error(u"Select at least two tags to align.")
        return report

    text_feet = 0.0
    text_source = u""
    if kind == u"untangle":
        paper, text_source = model.text_height(doc, tags, settings, log)
        text_feet = core.paper_to_model(paper, scale)
        log.add(u"text height {0} mm paper from {1}".format(
            _mm(paper), text_source))

    # ======================================================================
    # Who may move
    # ======================================================================
    editable = model.checkout(doc, tags)
    blocked = {}
    for key, t in by_key.items():
        if key not in editable:
            blocked[key] = u"is owned by another user"
            continue
        pinned = False
        try:
            pinned = bool(t.Pinned)
        except Exception:
            pinned = False
        if pinned and settings[u"pinned"] == u"skip":
            blocked[key] = u"is pinned"

    # ======================================================================
    # One transaction
    # ======================================================================
    tx = Transaction(doc, u"RevoBIM Tag " + label)
    _quiet(tx)
    if tx.Start() != TransactionStatus.Started:
        report.error(u"Revit would not start a transaction.")
        return report
    moved = []
    unchanged = 0
    try:
        measure = list(tags)
        if ref_tag is not None and ref_key not in by_key:
            measure.append(ref_tag)
        before = model.measure_boxes(doc, view, measure, right, up)
        boxes = []
        for t in tags:
            key = model.eid_value(t.Id)
            if key in before:
                boxes.append(before[key])
            else:
                report.warn(u"{0} has no size in this view and was left "
                            u"alone.".format(model.tag_label(doc, t)))
        for b in boxes:
            log.add(u"before {0}".format(b))

        if kind == u"align":
            ref_box = before.get(ref_key) if ref_key is not None else None
            if ref_tag is not None and ref_box is None:
                raise ValueError(u"The reference tag could not be measured.")
            deltas = core.align_deltas(boxes, which,
                                       settings[u"align_reference"], ref_box)
            vector_of = right
        else:
            prefix = u"v_" if which == u"vertical" else u"h_"
            deltas, order = core.untangle_deltas(
                boxes, which, text_feet, settings[prefix + u"mode"],
                settings[prefix + u"gap"], settings[prefix + u"pitch"],
                settings[u"untangle_anchor"])
            log.add(u"order {0}".format(order))
            vector_of = up if which == u"vertical" else right

        tol = core.tolerance(scale)
        promised = {}
        for key, delta in deltas:
            log.add(u"delta {0} {1:.6f}".format(key, delta))
            if abs(delta) < tol / 10.0:
                unchanged += 1
                continue
            t = by_key[key]
            if key in blocked:
                report.warn(u"{0} {1}, so it was not moved.".format(
                    model.tag_label(doc, t), blocked[key]))
                continue
            try:
                repin = False
                try:
                    if t.Pinned:
                        t.Pinned = False
                        repin = True
                except Exception:
                    repin = False
                elbows = model.move_tag(doc, t, vector_of.Multiply(delta),
                                        settings[u"move_elbows"])
                if repin:
                    t.Pinned = True
                moved.append(key)
                promised[key] = (delta, elbows)
            except Exception as ex:
                report.warn(u"{0} could not be moved: {1}".format(
                    model.tag_label(doc, t), ex))

        # ==================================================================
        # Prove it: measure again
        # ==================================================================
        doc.Regenerate()
        after = model.measure_boxes(doc, view, [by_key[k] for k in moved],
                                    right, up)
        landed = 0
        for key in moved:
            delta, elbows = promised[key]
            t = by_key[key]
            if key not in after:
                report.warn(u"{0} could not be measured after the move."
                            .format(model.tag_label(doc, t)))
                continue
            along, across = core.drift(before[key], after[key], kind, which,
                                       delta)
            log.add(u"after {0} drift along {1:.6f} across {2:.6f}".format(
                after[key], along, across))
            if along > tol or across > tol:
                report.warn(u"{0} landed {1} mm (paper) away from where it "
                            u"was sent.".format(model.tag_label(doc, t),
                                                _paper_mm(max(along, across),
                                                          scale)))
                continue
            elbow_ok = True
            if elbows:
                now = model.read_elbows(t)
                for i, (ref, target) in enumerate(elbows):
                    if i >= len(now) or now[i][1].DistanceTo(target) > tol:
                        elbow_ok = False
            if not elbow_ok:
                report.warn(u"{0} moved, but Revit put its leader elbow "
                            u"somewhere else.".format(model.tag_label(doc, t)))
            landed += 1

        status = tx.Commit()
        if status != TransactionStatus.Committed:
            report.error(u"Revit refused the change ({0}); nothing was moved."
                         .format(status))
            return report
        report.moved = landed
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        log.add(traceback.format_exc())
        report.error(u"Stopped and rolled back: {0}".format(ex))
        return report

    model.set_selection(uidoc, tags)

    # ======================================================================
    # Summary
    # ======================================================================
    if kind == u"align":
        side = {u"left": u"left edge", u"centre": u"centre",
                u"right": u"right edge"}[which]
        ref_words = REFERENCE_WORDS[settings[u"align_reference"]]
        report.summary = u"Aligned {0} tag(s) to the {1} of {2}.".format(
            report.moved, side, ref_words)
    else:
        prefix = u"v_" if which == u"vertical" else u"h_"
        if settings[prefix + u"mode"] == u"pitch":
            rule = u"{0} x text height centre to centre".format(
                core.format_number(settings[prefix + u"pitch"]))
        else:
            rule = u"tag size + {0} x text height clear".format(
                core.format_number(settings[prefix + u"gap"]))
        report.summary = (u"Spaced {0} tag(s) {1}ly, {2}. Text height "
                          u"{3} mm on paper from {4}, 1:{5}.").format(
            report.moved, which, rule, _paper_mm(text_feet, scale),
            text_source, scale)
    if unchanged and not report.moved:
        report.summary = u"Nothing to move: the tags are already in place."
    report.ok(report.summary)
    log.add(report.summary)
    return report
