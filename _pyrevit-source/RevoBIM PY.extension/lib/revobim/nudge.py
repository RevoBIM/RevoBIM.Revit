# -*- coding: utf-8 -*-
"""revobim.nudge - move elements up or down by a fixed amount.

Two ways in:

    from revobim.nudge import nudge_selection, run_click_loop

    nudge_selection(uidoc, 50.0, up=True)     # move what is already selected
    run_click_loop(uidoc, 50.0, up=False)     # click elements one at a time

WHAT CAN BE NUDGED
  - pipes, ducts, cable tray, conduit and flex                 always
  - fabrication ductwork, pipework and containment straights  always
  - their fittings and accessories, equipment, fixtures,
    sprinklers, generic models                                 'fittings'
  - fabrication fittings, fabrication hangers, and
    MEP ancillary framing (strut, channel, trapeze)           'fabrication'

HOW THE ELEVATION IS WRITTEN - first route that applies wins
  1. Middle Elevation                RBS_OFFSET_PARAM
  2. Start + End Elevation           sloped runs, shifted together
  3. Offset from host / from level   family instances, ancillary framing
  4. Start + End Level Offset        line-based ancillary framing
  5. measured move in Z              fabrication parts, and anything else

Fabrication parts always take route 5. Their Top and Bottom of Part are
measured from the part's level on some releases and some service templates
and from the project base on others (learned on Match Offset), so writing
them is a guess. Measuring the part's own centreline against its level and
moving by the difference is not.

A fabrication hanger hangs from the soffit, so once it has moved its rods
are re-cut to keep their tops where they were. Rods Revit is hosting it
re-solves itself; rods set to manual are re-cut here.

Every BuiltInParameter and BuiltInCategory is looked up by name at call time,
never at import, so a member missing on one Revit release (MEP ancillary
framing is 2024+) cannot stop the module loading.

Depends only on the Revit API, not on pyRevit. Revit 2024-2027, IronPython.
"""

import math

from Autodesk.Revit import DB
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.DB.Plumbing import Pipe, FlexPipe
from Autodesk.Revit.DB.Mechanical import Duct, FlexDuct
from Autodesk.Revit.DB.Electrical import CableTray, Conduit


MM = 1.0 / 304.8                     # millimetres -> internal feet
TRANSACTION_NAME = u'RevoBIM Nudge'

# a manual hanger rod shorter than this after a re-cut is left alone - a rod
# of zero or negative length is something nobody would see until site
MIN_ROD_MM = 10.0

RUN_TYPES = (Pipe, Duct, CableTray, Conduit, FlexPipe, FlexDuct)

FITTING_CAT_NAMES = (
    'OST_PipeFitting',
    'OST_DuctFitting',
    'OST_CableTrayFitting',
    'OST_ConduitFitting',
    'OST_PipeAccessory',
    'OST_DuctAccessory',
    'OST_MechanicalEquipment',
    'OST_ElectricalEquipment',
    'OST_ElectricalFixtures',
    'OST_PlumbingFixtures',
    'OST_LightingFixtures',
    'OST_Sprinklers',
    'OST_GenericModel',
)

FAB_RUN_CAT_NAMES = (
    'OST_FabricationDuctwork',
    'OST_FabricationPipework',
    'OST_FabricationContainment',
)

FAB_HANGER_CAT_NAMES = (
    'OST_FabricationHangers',
)

FRAMING_CAT_NAMES = (
    'OST_MEPAncillaryFraming',
)

MID_PARAM = 'RBS_OFFSET_PARAM'
START_PARAM = 'RBS_START_OFFSET_PARAM'
END_PARAM = 'RBS_END_OFFSET_PARAM'
HOST_OFFSET_PARAMS = (
    'INSTANCE_FREE_HOST_OFFSET_PARAM',
    'INSTANCE_ELEVATION_PARAM',
)
FRAMING_END_PARAMS = (
    'STRUCTURAL_BEAM_END0_ELEVATION',
    'STRUCTURAL_BEAM_END1_ELEVATION',
)


# ---------------------------------------------------------------------------
# lookups - by name, at call time, cached once resolved
# ---------------------------------------------------------------------------

_CAT_IDS = {}


def _bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def _cat_ids(names):
    """Integer ids of the named categories that exist on this release."""
    key = tuple(names)
    found = _CAT_IDS.get(key)
    if found is None:
        found = set()
        for name in names:
            bic = getattr(DB.BuiltInCategory, name, None)
            if bic is None:
                continue
            try:
                found.add(int(bic))
            except Exception:
                pass
        _CAT_IDS[key] = found
    return found


def _fitting_ids():
    return _cat_ids(FITTING_CAT_NAMES)


def eid_value(element_id):
    """ElementId as an int - .Value on 2024+, .IntegerValue before it."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def _category_id(element):
    category = getattr(element, 'Category', None)
    if category is None:
        return None
    try:
        return eid_value(category.Id)
    except Exception:
        return None


def _is_fab_part(element):
    fab = getattr(DB, 'FabricationPart', None)
    return fab is not None and isinstance(element, fab)


def _is_hanger(element):
    if not _is_fab_part(element):
        return False
    try:
        return bool(element.IsAHanger())
    except Exception:
        return _category_id(element) in _cat_ids(FAB_HANGER_CAT_NAMES)


def _is_fab_straight(element):
    try:
        return bool(element.IsAStraight())
    except Exception:
        # no answer either way - treat it as a run rather than hide it
        return True


# ---------------------------------------------------------------------------
# what may be clicked
# ---------------------------------------------------------------------------

class NudgeFilter(ISelectionFilter):
    """Runs always; fittings and fabrication extras as the settings allow."""

    def __init__(self, allow_fittings=True, allow_fabrication=True):
        self.allow_fittings = allow_fittings
        self.allow_fabrication = allow_fabrication

    def AllowElement(self, element):
        return is_nudgeable(element, self.allow_fittings,
                            self.allow_fabrication)

    def AllowReference(self, reference, point):
        return False


def is_nudgeable(element, allow_fittings=True, allow_fabrication=True):
    if element is None:
        return False
    if isinstance(element, RUN_TYPES):
        return True

    cat_id = _category_id(element)
    if cat_id is None:
        return False

    # fabrication ductwork, pipework, containment: a straight is a run and is
    # always allowed; a fabrication fitting goes with the fabrication setting
    if cat_id in _cat_ids(FAB_RUN_CAT_NAMES):
        if _is_fab_straight(element):
            return True
        return allow_fabrication

    if cat_id in _cat_ids(FAB_HANGER_CAT_NAMES) \
            or cat_id in _cat_ids(FRAMING_CAT_NAMES):
        return allow_fabrication

    if cat_id in _fitting_ids():
        return allow_fittings
    return False


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------

def _snap_to(value_ft, snap_ft, direction=1.0):
    """Round a value to the nearest multiple of snap_ft."""
    if snap_ft <= 0:
        return value_ft
    return math.floor(value_ft / snap_ft + 0.5) * snap_ft


def _snapped_target(current_ft, delta_ft, snap_ft):
    """Where the element should end up, snapped, given where it is now."""
    target = current_ft + delta_ft
    if snap_ft <= 0:
        return target

    direction = 1.0 if delta_ft > 0 else -1.0
    snapped = _snap_to(target, snap_ft, direction)

    # a small step against an untidy start can round back to the original
    # position - move it a whole snap rather than appear to do nothing
    if abs(snapped - current_ft) < 1e-9:
        snapped = _snap_to(current_ft + direction * snap_ft, snap_ft,
                           direction)
        if abs(snapped - current_ft) < 1e-9:
            snapped = current_ft + direction * snap_ft
    return snapped


# ---------------------------------------------------------------------------
# measuring - for the parts with no parameter worth trusting
# ---------------------------------------------------------------------------

def _level_elevation(element):
    """Project elevation of the element's own level, or 0.0.

    ProjectElevation, never Level.Elevation - on a survey-point-based project
    the latter reports shared coordinates and comes back tens of metres out.
    """
    try:
        level_id = element.LevelId
        if level_id is None or level_id == DB.ElementId.InvalidElementId:
            return 0.0
        level = element.Document.GetElement(level_id)
        if level is None:
            return 0.0
        try:
            return level.ProjectElevation
        except AttributeError:
            return level.Elevation
    except Exception:
        return 0.0


def _connector_mid_z(element):
    manager = None
    try:
        manager = element.ConnectorManager
    except Exception:
        manager = None
    if manager is None:
        try:
            manager = element.MEPModel.ConnectorManager
        except Exception:
            manager = None
    if manager is None:
        return None
    total = 0.0
    count = 0
    try:
        for connector in manager.Connectors:
            try:
                total += connector.Origin.Z
                count += 1
            except Exception:
                pass
    except Exception:
        return None
    return (total / count) if count else None


def _reference_z(element):
    """A height that moves one-for-one with the element, in project terms.

    Fabrication parts: the average of their connector origins, which is the
    centreline the part was laid out on. Everything else: its location point
    or the middle of its location line, then connectors, then the middle of
    its box as a last resort.
    """
    if _is_fab_part(element) and not _is_hanger(element):
        z = _connector_mid_z(element)
        if z is not None:
            return z

    location = getattr(element, 'Location', None)
    point = getattr(location, 'Point', None)
    if point is not None:
        return point.Z
    curve = getattr(location, 'Curve', None)
    if curve is not None:
        try:
            return curve.Evaluate(0.5, True).Z
        except Exception:
            pass

    z = _connector_mid_z(element)
    if z is not None:
        return z

    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            return (box.Min.Z + box.Max.Z) / 2.0
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# the move itself
# ---------------------------------------------------------------------------

def _writable(element, bip_name):
    bip = _bip(bip_name)
    if bip is None:
        return None
    try:
        param = element.get_Parameter(bip)
    except Exception:
        return None
    if param is None or param.IsReadOnly:
        return None
    if param.StorageType != DB.StorageType.Double:
        return None
    return param


def _shift_pair(element, first_name, second_name, delta_ft, snap_ft):
    """Snap the first of a pair and shift the second by the same amount."""
    first = _writable(element, first_name)
    second = _writable(element, second_name)
    if first is None or second is None:
        return None
    was = first.AsDouble()
    now = _snapped_target(was, delta_ft, snap_ft)
    first.Set(now)
    second.Set(second.AsDouble() + (now - was))
    return now - was


def _move_measured(element, delta_ft, snap_ft):
    """Measure the element against its level, snap that, move the difference.

    Returns the distance actually moved, or None.
    """
    reference = _reference_z(element)
    if reference is None:
        # nothing to measure - snap the step instead of the result
        move = delta_ft
        if snap_ft > 0:
            direction = 1.0 if delta_ft > 0 else -1.0
            move = _snap_to(delta_ft, snap_ft, direction)
            if abs(move) < 1e-9:
                move = direction * snap_ft
    else:
        offset = reference - _level_elevation(element)
        move = _snapped_target(offset, delta_ft, snap_ft) - offset

    if abs(move) < 1e-9:
        return None

    repin = False
    try:
        if element.Pinned:
            element.Pinned = False
            repin = True
    except Exception:
        pass
    try:
        DB.ElementTransformUtils.MoveElement(
            element.Document, element.Id, DB.XYZ(0, 0, move))
    finally:
        if repin:
            try:
                element.Pinned = True
            except Exception:
                pass
    return move


def _recut_rods(hanger, moved_ft):
    """Keep a hanger's rod tops at the soffit after it has moved.

    Raising a hanger shortens its rods; lowering it lengthens them. Rods Revit
    is hosting re-solve themselves, so only manual rods are touched. A rod
    that would come out shorter than MIN_ROD_MM is left as it was - the
    hanger has gone further than the rod is long.

    Returns (recut, left).
    """
    recut = 0
    left = 0
    try:
        info = hanger.GetRodInfo()
    except Exception:
        return (0, 0)
    if info is None:
        return (0, 0)
    try:
        if info.CanRodsBeHosted:
            return (0, 0)
    except Exception:
        pass
    try:
        count = int(info.RodCount)
    except Exception:
        return (0, 0)

    for index in range(count):
        try:
            length = info.GetRodLength(index)
        except Exception:
            left += 1
            continue
        new_length = length - moved_ft
        if new_length < MIN_ROD_MM * MM:
            left += 1
            continue
        try:
            info.SetRodLength(index, new_length)
            recut += 1
        except Exception:
            left += 1
    return (recut, left)


def shift(element, delta_ft, snap_ft=0.0, recut_rods=True):
    """Move one element by delta_ft (signed, internal feet).

    With snap_ft set, the resulting elevation is rounded to the nearest
    multiple of it rather than carrying whatever odd figure the element
    started on.

    Must be called inside an open transaction. Returns the route used as a
    short string, or None if nothing could be written.
    """
    if element is None:
        return None

    # fabrication parts - measured, never written through Top/Bottom of Part
    if _is_fab_part(element):
        moved = _move_measured(element, delta_ft, snap_ft)
        if moved is None:
            return None
        if recut_rods and _is_hanger(element):
            recut, left = _recut_rods(element, moved)
            if left:
                return u'fabrication hanger, {0} rod(s) left - too short' \
                    .format(left)
            if recut:
                return u'fabrication hanger, {0} rod(s) re-cut'.format(recut)
            return u'fabrication hanger'
        return u'fabrication part'

    # 1. middle elevation - the normal case for a level run
    mid = _writable(element, MID_PARAM)
    if mid is not None:
        mid.Set(_snapped_target(mid.AsDouble(), delta_ft, snap_ft))
        return u'middle elevation'

    # 2. sloped run - start snapped, end shifted the same, slope kept
    if _shift_pair(element, START_PARAM, END_PARAM,
                   delta_ft, snap_ft) is not None:
        return u'start and end elevation'

    # 3. offset from host or level - fittings, accessories, family instances,
    #    face-hosted ancillary framing
    for name in HOST_OFFSET_PARAMS:
        param = _writable(element, name)
        if param is not None:
            param.Set(_snapped_target(param.AsDouble(), delta_ft, snap_ft))
            return u'offset from level'

    # 4. line-based ancillary framing - both end offsets together
    if _shift_pair(element, FRAMING_END_PARAMS[0], FRAMING_END_PARAMS[1],
                   delta_ft, snap_ft) is not None:
        return u'start and end level offset'

    # 5. measured move in Z
    try:
        if _move_measured(element, delta_ft, snap_ft) is not None:
            return u'moved in Z'
    except Exception:
        pass
    return None


def describe(element):
    """A short readable label for an element, for status messages."""
    try:
        name = element.Name
    except Exception:
        name = u'Element'
    try:
        category = element.Category.Name
    except Exception:
        category = u'Element'
    return u'{0}: {1}'.format(category, name)


# ---------------------------------------------------------------------------
# mode one - nudge what is already selected
# ---------------------------------------------------------------------------

def nudge_selection(uidoc, step_mm, up=True, snap_mm=0.0,
                    allow_fittings=True, keep_selection=True,
                    allow_fabrication=True, recut_rods=True):
    """Shift every currently selected element once.

    Returns (moved_count, skipped_count). Press the button again - or its
    keyboard shortcut - and the same elements move again, because the
    selection is put back afterwards.
    """
    doc = uidoc.Document
    selection = uidoc.Selection
    ids = selection.GetElementIds()
    if ids is None or ids.Count == 0:
        return (0, 0)

    delta = (step_mm * MM) * (1.0 if up else -1.0)
    snap = max(0.0, float(snap_mm)) * MM

    # resolve the elements once, outside the transaction, so the transaction
    # is open for as little time as possible
    get = doc.GetElement
    targets = []
    skipped = 0
    for element_id in ids:
        element = get(element_id)
        if is_nudgeable(element, allow_fittings, allow_fabrication):
            targets.append(element)
        else:
            skipped += 1

    if not targets:
        return (0, skipped)

    # A hanger selected along with the part it carries may be dragged up by
    # Revit when the part moves - nudging it as well would move it twice. So
    # hangers go last: their heights are read before anything moves, the
    # model is regenerated once the parts are done, and a hanger that has
    # already travelled is counted as moved and left alone. Measured, not
    # assumed - whether Revit carries it depends on how it was hosted.
    hangers = [e for e in targets if _is_hanger(e)]
    others = [e for e in targets if not _is_hanger(e)]
    before = {}
    for hanger in hangers:
        before[eid_value(hanger.Id)] = _reference_z(hanger)

    moved = 0
    transaction = DB.Transaction(doc, TRANSACTION_NAME)
    transaction.Start()
    try:
        for element in others:
            try:
                route = shift(element, delta, snap, recut_rods)
            except Exception:
                route = None
            if route:
                moved += 1
            else:
                skipped += 1

        if hangers and others:
            try:
                doc.Regenerate()
            except Exception:
                pass

        for hanger in hangers:
            was = before.get(eid_value(hanger.Id))
            now = _reference_z(hanger)
            if was is not None and now is not None \
                    and abs(now - was) > 0.5 * MM:
                moved += 1          # carried with its part already
                continue
            try:
                route = shift(hanger, delta, snap, recut_rods)
            except Exception:
                route = None
            if route:
                moved += 1
            else:
                skipped += 1
        transaction.Commit()
    except Exception:
        if transaction.HasStarted():
            transaction.RollBack()
        raise

    # Revit normally keeps the selection through a parameter change, so only
    # write it back when it has actually been dropped - SetElementIds is not
    # free and this runs on every press.
    if keep_selection:
        try:
            current = selection.GetElementIds()
            if current is None or current.Count != ids.Count:
                from System.Collections.Generic import List
                keep = List[DB.ElementId]()
                for element in targets:
                    keep.Add(element.Id)
                selection.SetElementIds(keep)
        except Exception:
            pass

    return (moved, skipped)


# ---------------------------------------------------------------------------
# mode two - click elements one at a time
# ---------------------------------------------------------------------------

def run_click_loop(uidoc, step_mm, up=True, snap_mm=0.0,
                   allow_fittings=True, repeat=True, status=None,
                   allow_fabrication=True, recut_rods=True):
    """Ask for an element, move it, ask again. Escape ends the loop.

    Each click is its own transaction, so Ctrl+Z steps back one element at a
    time rather than undoing the whole session. Returns the list of ElementIds
    that were moved.
    """
    doc = uidoc.Document
    delta = (step_mm * MM) * (1.0 if up else -1.0)
    snap = max(0.0, float(snap_mm)) * MM
    selection_filter = NudgeFilter(allow_fittings, allow_fabrication)
    prompt = u'{0} by {1:g} mm - click an element{2}'.format(
        u'Raise' if up else u'Lower', step_mm,
        u' (Esc when finished)' if repeat else u'')

    moved = []
    while True:
        try:
            reference = uidoc.Selection.PickObject(
                ObjectType.Element, selection_filter, prompt)
        except OperationCanceledException:
            break
        except Exception:
            break
        if reference is None:
            break

        element = doc.GetElement(reference.ElementId)
        transaction = DB.Transaction(doc, TRANSACTION_NAME)
        transaction.Start()
        try:
            route = shift(element, delta, snap, recut_rods)
            if route:
                transaction.Commit()
                moved.append(element.Id)
                if status:
                    status(u'{0} {1:g} mm - {2} ({3})'.format(
                        u'Raised' if up else u'Lowered', step_mm,
                        describe(element), route))
            else:
                transaction.RollBack()
                if status:
                    status(u'Could not move {0}'.format(describe(element)))
        except Exception as err:
            if transaction.HasStarted():
                transaction.RollBack()
            if status:
                status(u'Skipped {0} - {1}'.format(describe(element), err))

        if not repeat:
            break

    return moved


# ---------------------------------------------------------------------------
# what the buttons actually call
# ---------------------------------------------------------------------------

def run(uidoc, up=True, config=None):
    """Selection first, click loop second. This is the whole button.

    Returns a short summary string. Nothing is shown to the user - the tools
    finish silently.
    """
    if config is None:
        from revobim import nudge_settings
        config = nudge_settings.load()

    step = float(config.get('step_mm', 50.0))
    allow_fittings = bool(config.get('allow_fittings', True))
    allow_fabrication = bool(config.get('allow_fabrication', True))
    recut_rods = bool(config.get('recut_rods', True))
    snap = float(config.get('snap_mm', 5.0)) \
        if config.get('snap_enabled', True) else 0.0

    if uidoc.Selection.GetElementIds().Count > 0:
        moved, skipped = nudge_selection(
            uidoc, step, up=up, snap_mm=snap,
            allow_fittings=allow_fittings,
            keep_selection=bool(config.get('keep_selection', True)),
            allow_fabrication=allow_fabrication,
            recut_rods=recut_rods)
        return u'{0} element(s) moved, {1} skipped.'.format(moved, skipped)

    moved = run_click_loop(
        uidoc, step, up=up, snap_mm=snap,
        allow_fittings=allow_fittings,
        repeat=bool(config.get('repeat_loop', True)),
        allow_fabrication=allow_fabrication,
        recut_rods=recut_rods)
    return u'{0} element(s) moved.'.format(len(moved))
