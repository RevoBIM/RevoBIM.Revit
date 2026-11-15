# -*- coding: utf-8 -*-
"""3D Align - the picks, the move, and the proof that it landed.

Windowless: settings are read from file and the tool goes straight to the
picks. The themed results window only opens when something needs a look
(Settings can make that always or never).
"""
import a3d_clr  # noqa: F401  - assemblies first, always

import io
import os

from System.Collections.Generic import List
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, ElementId,
                               ElementTransformUtils, FailureProcessingResult,
                               FailureSeverity, IFailuresPreprocessor, Line,
                               LocationCurve, Transaction, TransactionStatus,
                               WorksharingUtils, XYZ)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

import a3d_geom as geom
import a3d_settings as cfg

TARGET_CATEGORIES = ('OST_PipeCurves', 'OST_DuctCurves', 'OST_CableTray', 'OST_Conduit')
TRANSACTION_NAME = u'RevoBIM 3D Align'
NEEDS_LOOK = ('warn', 'refused', 'failed')


# ==========================================================================
# small helpers
# ==========================================================================

def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def ft_to_mm(value):
    return value * cfg.MM_PER_FT


class DebugLog(object):
    """Reset each run, written once at the end."""

    def __init__(self, enabled, path=None):
        self.enabled = enabled
        self.path = path or cfg.debug_path()
        self.lines = []

    def write(self, text):
        if self.enabled:
            self.lines.append(u'{0}'.format(text))

    def flush(self):
        if not self.enabled:
            return
        try:
            folder = os.path.dirname(self.path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            with io.open(self.path, 'w', encoding='utf-8') as handle:
                handle.write(u'\n'.join(self.lines) + u'\n')
        except Exception:
            pass


def target_category_ids():
    """Looked up at call time, never at import."""
    out = set()
    for name in TARGET_CATEGORIES:
        member = getattr(BuiltInCategory, name, None)
        if member is None:
            continue
        try:
            out.add(int(member))
        except Exception:
            pass
    return out


def point(xyz):
    return (xyz.X, xyz.Y, xyz.Z)


def axis_of(element):
    """The two ends of the element's centreline, or None if it is not a
    straight location line."""
    if element is None:
        return None
    try:
        location = element.Location
    except Exception:
        return None
    if not isinstance(location, LocationCurve):
        return None
    try:
        curve = location.Curve
    except Exception:
        return None
    if not isinstance(curve, Line):
        return None
    return (point(curve.GetEndPoint(0)), point(curve.GetEndPoint(1)))


def is_target(element, categories=None):
    categories = categories if categories is not None else target_category_ids()
    try:
        category_id = eid_value(element.Category.Id)
    except Exception:
        return False
    return category_id in categories and axis_of(element) is not None


def describe(element):
    if element is None:
        return u'(nothing)'
    name = u'Element'
    try:
        name = element.Category.Name
    except Exception:
        pass
    size = u''
    member = getattr(BuiltInParameter, 'RBS_CALCULATED_SIZE', None)
    if member is not None:
        try:
            parameter = element.get_Parameter(member)
            if parameter is not None:
                size = parameter.AsString() or u''
        except Exception:
            pass
    text = u'{0} {1}'.format(name, size).strip()
    return u'{0} [{1}]'.format(text, eid_value(element.Id))


# ==========================================================================
# picking
# ==========================================================================

class AlignFilter(ISelectionFilter):
    """Straight pipes, ducts, cable trays and conduits. The datum cannot be
    picked twice, and after a horizontal datum only uprights are offered,
    because two horizontals is not an alignment this tool makes."""

    def __init__(self, exclude_id=None, need_kind=None):
        self.categories = target_category_ids()
        self.exclude_id = exclude_id
        self.need_kind = need_kind

    def AllowElement(self, element):
        try:
            if self.exclude_id is not None and eid_value(element.Id) == self.exclude_id:
                return False
            if not is_target(element, self.categories):
                return False
            if self.need_kind is not None:
                return geom.classify(axis_of(element)) == self.need_kind
            return True
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


def pick(uidoc, prompt, exclude_id=None, need_kind=None):
    """The picked element, or None on Escape."""
    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.Element, AlignFilter(exclude_id, need_kind), prompt)
    except OperationCanceledException:
        return None
    if reference is None:
        return None
    return uidoc.Document.GetElement(reference.ElementId)


def preselected(uidoc, log=None):
    """The element selected before the button was pressed, if it is exactly
    one straight pipe, duct, cable tray or conduit."""
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return None
    if len(ids) != 1:
        if ids and log is not None:
            log.write(u'{0} elements were selected - picking the datum instead'.format(len(ids)))
        return None
    element = uidoc.Document.GetElement(ids[0])
    if element is None or not is_target(element):
        if log is not None:
            log.write(u'The selected element is not a straight pipe, duct, tray or conduit')
        return None
    return element


def highlight(uidoc, element):
    try:
        ids = List[ElementId]()
        if element is not None:
            ids.Add(element.Id)
        uidoc.Selection.SetElementIds(ids)
    except Exception:
        pass


# ==========================================================================
# writing
# ==========================================================================

class Failures(IFailuresPreprocessor):
    """Warnings deleted; an error rolls the transaction back quietly and its
    text is kept so the report can say what Revit said."""

    def __init__(self):
        self.errors = []
        self.warnings = 0

    def PreprocessFailures(self, accessor):
        rollback = False
        try:
            for message in list(accessor.GetFailureMessages()):
                try:
                    severity = message.GetSeverity()
                except Exception:
                    severity = None
                if severity == FailureSeverity.Warning:
                    try:
                        accessor.DeleteWarning(message)
                        self.warnings += 1
                    except Exception:
                        pass
                else:
                    rollback = True
                    try:
                        self.errors.append(message.GetDescriptionText())
                    except Exception:
                        self.errors.append(u'Revit raised an error')
        except Exception:
            pass
        if rollback:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def run_transaction(doc, work):
    """(committed, failures). One transaction, failures handled, and the
    commit status checked rather than assumed."""
    failures = Failures()
    transaction = Transaction(doc, TRANSACTION_NAME)
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(failures)
    options.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(options)
    transaction.Start()
    try:
        work()
    except Exception as error:
        failures.errors.append(u'{0}'.format(error))
        try:
            transaction.RollBack()
        except Exception:
            pass
        return False, failures
    status = transaction.Commit()
    return status == TransactionStatus.Committed, failures


def connectors_of(element):
    try:
        return list(element.ConnectorManager.Connectors)
    except Exception:
        return []


def connected_count(element):
    count = 0
    for connector in connectors_of(element):
        try:
            if connector.IsConnected:
                count += 1
        except Exception:
            pass
    return count


def _physical_ref(element, other):
    """A connector joined to another element, not the logical link to the
    element's own MEP system."""
    try:
        if eid_value(other.Owner.Id) == eid_value(element.Id):
            return False
        if u'System' in type(other.Owner).__name__:
            return False
        return (int(other.ConnectorType) & 3) != 0
    except Exception:
        return False


def disconnect_all(element):
    released = 0
    for connector in connectors_of(element):
        try:
            if not connector.IsConnected:
                continue
            for other in list(connector.AllRefs):
                if not _physical_ref(element, other):
                    continue
                try:
                    connector.DisconnectFrom(other)
                    released += 1
                except Exception:
                    pass
        except Exception:
            pass
    return released


def move_job(doc, element, move, detach):
    state = {'detached': 0}

    def work():
        was_pinned = bool(element.Pinned)
        if was_pinned:
            element.Pinned = False
        if detach:
            state['detached'] = disconnect_all(element)
        ElementTransformUtils.MoveElement(doc, element.Id, XYZ(move[0], move[1], move[2]))
        if was_pinned:
            element.Pinned = True
    return work, state


def owner_of(doc, element_id):
    try:
        owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id).Owner
        if owner:
            return u'{0} has it borrowed'.format(owner)
    except Exception:
        pass
    try:
        element = doc.GetElement(element_id)
        workset = doc.GetWorksetTable().GetWorkset(element.WorksetId)
        if workset.Owner:
            return u'workset "{0}" is owned by {1}'.format(workset.Name, workset.Owner)
    except Exception:
        pass
    return u'another user has it'


def borrow(doc, element_id):
    """(True, '') when the element can be written, else (False, who has it).
    On a workshared model a write to an element that is not borrowed writes
    nothing and says nothing, so it is borrowed before the transaction."""
    try:
        if not doc.IsWorkshared:
            return True, u''
    except Exception:
        return True, u''
    wanted = eid_value(element_id)
    try:
        ids = List[ElementId]()
        ids.Add(element_id)
        for held in WorksharingUtils.CheckoutElements(doc, ids):
            if eid_value(held) == wanted:
                return True, u''
    except Exception:
        pass
    return False, owner_of(doc, element_id)


# ==========================================================================
# one alignment
# ==========================================================================

def new_row(first, second, kind, note, mode=u'', moved_mm=None):
    return {'kind': kind, 'first': describe(first), 'second': describe(second),
            'mode': mode, 'moved_mm': moved_mm, 'note': note}


def align(doc, first, second, settings, log):
    """Move the second element onto the first in plan, then prove it."""
    if eid_value(first.Id) == eid_value(second.Id):
        return new_row(first, second, 'refused', u'the same element was clicked twice')
    first_axis = axis_of(first)
    second_axis = axis_of(second)
    if first_axis is None or second_axis is None:
        return new_row(first, second, 'refused', u'not a straight run - no centreline to align')

    plan = geom.plan_alignment(first_axis, second_axis)
    mode = plan['mode']
    log.write(u'{0} -> {1}: {2} / {3}, move {4:.2f}mm'.format(
        describe(first), describe(second), plan['first_kind'], plan['second_kind'],
        ft_to_mm(plan['distance'])))
    if not plan['ok']:
        return new_row(first, second, 'refused', plan['reason'], mode)
    moved_mm = ft_to_mm(plan['distance'])
    if plan['already']:
        return new_row(first, second, 'already',
                       u'already aligned to within {0}mm - nothing moved'.format(geom.ALIGNED_MM),
                       mode, moved_mm)

    limit = cfg.max_move_ft(settings)
    if limit is not None and plan['distance'] > limit:
        return new_row(first, second, 'refused',
                       u'would move {0:.0f}mm, more than the {1:.0f}mm limit in Settings'.format(
                           moved_mm, ft_to_mm(limit)), mode, moved_mm)
    try:
        in_group = eid_value(second.GroupId) > 0
    except Exception:
        in_group = False
    if in_group:
        return new_row(first, second, 'refused',
                       u'it is inside a model group - edit the group to move it', mode, moved_mm)
    allowed, holder = borrow(doc, second.Id)
    if not allowed:
        return new_row(first, second, 'refused', u'cannot be moved: {0}'.format(holder), mode, moved_mm)

    joined_before = connected_count(second)
    work, state = move_job(doc, second, plan['move'], False)
    committed, failures = run_transaction(doc, work)
    detached = 0
    if not committed:
        revit_says = u'; '.join(failures.errors) or u'Revit refused the move'
        log.write(u'  refused with its connections: {0}'.format(revit_says))
        if settings.get('on_refusal') == 'detach' and joined_before > 0:
            work, state = move_job(doc, second, plan['move'], True)
            committed, failures = run_transaction(doc, work)
            detached = state['detached']
            if not committed:
                return new_row(first, second, 'failed',
                               u'Revit refused the move even detached: {0}'.format(
                                   u'; '.join(failures.errors) or revit_says), mode, moved_mm)
        else:
            return new_row(first, second, 'failed',
                           u'{0} - left where it was'.format(revit_says), mode, moved_mm)

    # A void API call is not evidence: read both centrelines back.
    first_after = axis_of(doc.GetElement(first.Id))
    second_after = axis_of(doc.GetElement(second.Id))
    check = geom.plan_alignment(first_after, second_after) if first_after and second_after else None
    datum_moved = geom.moved_by(first_axis, first_after) > geom.ALIGNED_FT
    if check is None or not check['ok'] or not geom.is_aligned(check['distance']):
        residual = ft_to_mm(check['distance']) if check and check['ok'] else -1.0
        log.write(u'  read back {0:.2f}mm out, datum moved: {1}'.format(residual, datum_moved))
        if datum_moved:
            return new_row(first, second, 'warn',
                           u'moved, but the first element was dragged with it through their '
                           u'connection and they now read {0:.1f}mm apart - check the joint'.format(residual),
                           mode, moved_mm)
        return new_row(first, second, 'failed',
                       u'Revit accepted the move but it reads back {0:.1f}mm out'.format(residual),
                       mode, moved_mm)

    notes = []
    kind = 'ok'
    if detached:
        kind = 'warn'
        notes.append(u'Revit would not move it with its connections, so {0} connection(s) were '
                     u'released - reconnect by hand'.format(detached))
    else:
        joined_after = connected_count(second)
        if joined_after < joined_before:
            kind = 'warn'
            notes.append(u'{0} connection(s) came apart in the move'.format(joined_before - joined_after))
    if datum_moved:
        kind = 'warn'
        notes.append(u'the first element moved too - the two are connected, check the joint')
    if not notes:
        notes.append(u'aligned and read back')
    log.write(u'  {0}: {1}'.format(kind, u'; '.join(notes)))
    return new_row(first, second, kind, u'; '.join(notes), mode, moved_mm)


def should_show(rows, mode):
    if not rows or mode == 'never':
        return False
    if mode == 'always':
        return True
    return any(row['kind'] in NEEDS_LOOK for row in rows)


# ==========================================================================
# the command
# ==========================================================================

def second_prompt(kind):
    if kind == geom.VERTICAL:
        return (u'3D Align: click the element to centre on this upright '
                u'(Esc to choose a different first element)')
    return (u'3D Align: click the upright to move onto this run\'s centreline '
            u'(Esc to choose a different first element)')


def main(uiapp, show_results=None):
    """Picks until Escape. show_results is passed in by the loader so the WPF
    side is only loaded when a report is actually needed."""
    settings = cfg.load()
    log = DebugLog(cfg.is_on(settings, 'debug'))
    log.write(u'3D Align v{0}'.format(cfg.__version__))
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return []
    doc = uidoc.Document
    keep_running = cfg.is_on(settings, 'keep_running')
    rows = []
    first = preselected(uidoc, log)
    if first is not None:
        log.write(u'Using the selection as the first element: {0}'.format(describe(first)))
    try:
        while True:
            if first is None:
                highlight(uidoc, None)
                first = pick(uidoc, u'3D Align: click the first element - the one to align to (Esc to finish)')
                if first is None:
                    break
            kind = geom.classify(axis_of(first))
            highlight(uidoc, first)
            need = geom.VERTICAL if kind == geom.HORIZONTAL else None
            second = pick(uidoc, second_prompt(kind), eid_value(first.Id), need)
            if second is None:
                first = None
                if keep_running:
                    continue
                break
            rows.append(align(doc, first, second, settings, log))
            first = None
            if not keep_running:
                break
    finally:
        highlight(uidoc, None)
        log.flush()
    if show_results is not None and should_show(rows, settings.get('show_results')):
        show_results(rows, settings)
    return rows
