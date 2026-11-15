# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - the pick loop
#
# Click the start, click the end, answer the prompt, and the
# offset runs. The loop then goes straight back to waiting
# for the next first click; Escape on that click finishes.
#
# No modeless window anywhere, so no __persistentengine__ and
# none of the engine teardown problems that come with it. The
# prompt is a modal dialog raised from inside the command,
# which is why it can block for an answer without deadlocking
# the way an ExternalEvent would.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

import so_core
import so_model
import so_command_host
import offset_prompt
import results_window


def selected_runs(uidoc, doc):
    """Supported runs already selected, in a stable order."""
    found = []
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return found
    for element_id in ids:
        element = doc.GetElement(element_id)
        if element is None or not so_model.is_supported(element):
            continue
        if so_model.axis_of(element) is None:
            continue
        found.append(element)
    found.sort(key=lambda e: so_core.eid_value(e.Id))
    return found


def check_parallel(elements):
    """All parallel, or say so and stop.

    A bank built from runs that are only nearly parallel comes
    out wrong in a way that is very hard to see afterwards.
    """
    axes = [so_model.axis_of(e) for e in elements]
    parallel, worst = so_core.axes_parallel(axes)
    if parallel:
        return True, u''
    return False, (u'Elements not parallel. User must manually review them.\n\n'
                   u'The worst pair is {0:.2f} degrees apart, and this tool '
                   u'allows {1:.2f}. Nothing has been changed.'
                   .format(worst, so_core.PARALLEL_DEG))


class ChosenFilter(ISelectionFilter):
    """Only the runs already selected."""

    def __init__(self, elements):
        self.ids = set(so_core.eid_value(e.Id) for e in elements)

    def AllowElement(self, element):
        try:
            return so_core.eid_value(element.Id) in self.ids
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return True


class OffsettableFilter(ISelectionFilter):
    """Pipes, ducts, cable tray and conduit, and nothing else."""

    def AllowElement(self, element):
        try:
            return so_model.is_supported(element)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return True


def _pick(uidoc, prompt, wanted_id=None, chooser=None):
    """One click on a run, returning (element, point).

    PickObject(PointOnElement) for both clicks. v3 used
    PickPoint for the second one to get the direction out of
    it, which put the point on the view's work plane rather
    than on the run - and projecting that back on to the run
    landed past its end often enough to refuse most offsets.
    The direction comes from the prompt now, so both clicks
    can be honest points on the element.
    """
    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.PointOnElement, chooser or OffsettableFilter(), prompt)
    except OperationCanceledException:
        return None, None, u'cancelled'
    except Exception:
        return None, None, u'cancelled'

    if reference is None:
        return None, None, u'cancelled'

    if wanted_id is not None:
        if so_core.eid_value(reference.ElementId) != wanted_id:
            return None, None, u'different element'

    element = uidoc.Document.GetElement(reference.ElementId)
    try:
        point = reference.GlobalPoint
    except Exception:
        point = None
    if point is None:
        return None, None, u'no point'
    return element, point, u'ok'


def _refusal(element, reason):
    return {
        'ok': False,
        'element_id': so_core.eid_value(element.Id) if element is not None else 0,
        'kind': so_model.kind_of(element) if element is not None else u'',
        'notes': [],
        'created': [],
        'reason': reason,
    }


def run(uiapp, mode=so_model.MODE_JOG,
        tool_name=u'System Offset'):
    """One command press. Returns the list of records.

    Both buttons come through here. The mode decides how
    much room the clicks need and which pieces get built;
    everything else - the picks, the prompt, the loop, the
    reporting - is shared.
    """
    so_command_host.set_uiapp(uiapp)

    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return [_refusal(None, u'There is no open model.')]

    doc = uidoc.Document
    settings = so_core.load_settings()
    try:
        view = doc.ActiveView
    except Exception:
        view = None

    records = []

    # A selection made before the button was pressed is offset
    # as a bank: every run together, staying parallel and
    # keeping its spacing.
    bank = selected_runs(uidoc, doc)
    if len(bank) > 1:
        parallel, complaint = check_parallel(bank)
        if not parallel:
            return [_refusal(bank[0], complaint)]
    chooser = ChosenFilter(bank) if bank else None

    while True:
        element, point_a, how = _pick(
            uidoc,
            (u'Click where the {0} STARTS, on one of the {1} selected runs  '
             u'-  Escape to finish'.format(
                 u'break' if mode == so_model.MODE_BREAK else u'offset',
                 len(bank))
             if len(bank) > 1 else
             u'Click where the {0} STARTS, on a pipe, duct, cable tray or '
             u'conduit  -  Escape to finish'.format(
                 u'break' if mode == so_model.MODE_BREAK else u'offset')),
            chooser=chooser)
        if element is None:
            break

        second, point_b, how = _pick(
            uidoc,
            (u'Click where to CUT the run  -  Escape to finish'
             if mode == so_model.MODE_BREAK else
             u'Click the END of the offset on the same run  -  Escape to finish'),
            wanted_id=so_core.eid_value(element.Id), chooser=chooser)

        if second is None:
            if how == u'different element':
                records.append(_refusal(
                    element,
                    u'Both clicks have to be on the same run. Nothing was '
                    u'changed - click the start again.'))
                continue
            break

        others = [e for e in bank
                  if so_core.eid_value(e.Id) != so_core.eid_value(element.Id)]
        analysis = so_model.analyse(doc, element, point_a, point_b,
                                    settings, view, mode,
                                    bank=([element] + others) if others else None)
        if not analysis.get('ok'):
            records.append(_refusal(element, analysis.get('reason', u'')))
            continue

        answer = offset_prompt.ask(analysis, settings, tool_name)
        if answer is None:
            # Cancelled at the prompt. Nothing was written, so
            # go back to waiting for the next first click
            # rather than ending the command.
            continue

        distance_mm, direction = answer
        records.append(so_model.apply_offset(doc, analysis, distance_mm,
                                             direction, settings))

    return records
