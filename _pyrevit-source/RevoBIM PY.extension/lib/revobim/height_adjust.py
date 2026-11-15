# -*- coding: utf-8 -*-
"""revobim.height_adjust - raise / lower MEP elements, click by click.

No dependency on pyRevit, only on the Revit API, so it drops into a plain
IExternalCommand add-in too, not just pyRevit buttons.

Typical use from a modeless window's external event handler:

    from revobim.height_adjust import run_height_loop

    moved = run_height_loop(uidoc, step_mm=100.0, up=True)
    # -> list of ElementId, one per element you clicked

Or one element at a time, when you already have it:

    from revobim.height_adjust import nudge
    nudge(doc, element, 100.0, up=False)     # drop it 100 mm

Written for Revit 2024 / pyRevit 2.7 (IronPython 2.7).
"""

from Autodesk.Revit import DB
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.DB.Plumbing import Pipe, FlexPipe
from Autodesk.Revit.DB.Mechanical import Duct, FlexDuct
from Autodesk.Revit.DB.Electrical import CableTray, Conduit


MM = 1.0 / 304.8                # millimetres -> internal feet
DEFAULT_STEP_MM = 100.0
TRANSACTION_NAME = 'RevoBIM Height Adjust'

# tried in order; the first writable one wins
ELEVATION_PARAMS = ('RBS_OFFSET_PARAM',)                    # Middle Elevation
SLOPED_PARAMS = ('RBS_START_OFFSET_PARAM', 'RBS_END_OFFSET_PARAM')
HOSTED_PARAMS = ('INSTANCE_FREE_HOST_OFFSET_PARAM',)

MOVEABLE_TYPES = (Pipe, Duct, CableTray, Conduit, FlexPipe, FlexDuct)


class MoveableFilter(ISelectionFilter):
    """Services and their fittings; everything else stays un-clickable."""

    def AllowElement(self, element):
        if isinstance(element, MOVEABLE_TYPES):
            return True
        try:
            return (isinstance(element, DB.FamilyInstance)
                    and element.MEPModel is not None)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return True


def _writable(element, bip_name):
    """A writable double parameter by built-in name, or None."""
    bip = getattr(DB.BuiltInParameter, bip_name, None)
    if bip is None:
        return None
    try:
        prm = element.get_Parameter(bip)
    except Exception:
        return None
    if prm is None or prm.IsReadOnly:
        return None
    if prm.StorageType != DB.StorageType.Double:
        return None
    return prm


def adjust_elevation(doc, element, delta):
    """Shift one element's middle elevation by delta FEET. No transaction.

    Middle Elevation first; on a sloped run that parameter is read-only, so
    fall back to start + end elevation together (which keeps the slope), then
    to host offset, then to a plain move.

    Returns a short string saying which route it took.
    """
    for name in ELEVATION_PARAMS:
        prm = _writable(element, name)
        if prm is not None:
            prm.Set(prm.AsDouble() + delta)
            return 'middle elevation'

    start = _writable(element, SLOPED_PARAMS[0])
    end = _writable(element, SLOPED_PARAMS[1])
    if start is not None and end is not None:
        start.Set(start.AsDouble() + delta)
        end.Set(end.AsDouble() + delta)
        return 'start / end elevation'

    for name in HOSTED_PARAMS:
        prm = _writable(element, name)
        if prm is not None:
            prm.Set(prm.AsDouble() + delta)
            return 'host offset'

    DB.ElementTransformUtils.MoveElement(doc, element.Id,
                                         DB.XYZ(0, 0, delta))
    return 'moved'


def nudge(doc, element, step_mm=DEFAULT_STEP_MM, up=True,
          transaction_name=TRANSACTION_NAME):
    """One element, one transaction. Returns the route taken, or None."""
    delta = (step_mm if up else -step_mm) * MM
    trans = DB.Transaction(doc, transaction_name)
    trans.Start()
    try:
        how = adjust_elevation(doc, element, delta)
        trans.Commit()
        return how
    except Exception:
        if trans.HasStarted():
            trans.RollBack()
        raise


def run_height_loop(uidoc, step_mm=DEFAULT_STEP_MM, up=True, prompt=None,
                    selection_filter=None, logger=None,
                    transaction_name=TRANSACTION_NAME):
    """Click elements one after another; each jumps by step_mm as you click.

    Esc ends the loop. Each click is its own transaction, so Ctrl+Z steps
    back through them one element at a time. A click that cannot be moved is
    logged and skipped rather than killing the loop.

    Returns the list of ElementId that actually moved, in click order.
    """
    doc = uidoc.Document
    verb = 'Raise' if up else 'Lower'
    if prompt is None:
        prompt = '{0} by {1:.0f} mm - click an element ' \
                 '(Esc when finished)'.format(verb, step_mm)
    if selection_filter is None:
        selection_filter = MoveableFilter()

    moved = []
    while True:
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element,
                                             selection_filter, prompt)
        except OperationCanceledException:
            break

        element = doc.GetElement(ref.ElementId)
        if element is None:
            continue

        try:
            how = nudge(doc, element, step_mm, up, transaction_name)
            moved.append(element.Id)
            if logger:
                logger.debug('%s %s by %s', verb, element.Id, how)
        except Exception as err:
            if logger:
                logger.warning('Could not move element %s: %s',
                               element.Id, err)
    return moved


def describe(moved, step_mm=DEFAULT_STEP_MM, up=True):
    """One-line status for a window footer or the output panel."""
    if not moved:
        return 'Height adjust cancelled'
    return '{0} {1} element(s) by {2:.0f} mm'.format(
        'Raised' if up else 'Lowered', len(moved), step_mm)
