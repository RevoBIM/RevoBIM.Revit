# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM Clash Offset - the picks and the run
#
# Pick the services, pick what is in the way, look at what it
# worked out, press the button.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

import so_core
import so_model
import so_clash
import so_command_host
import clash_window


class ServiceFilter(ISelectionFilter):
    """Pipes, ducts, cable tray and conduit."""

    def AllowElement(self, element):
        try:
            return so_model.is_supported(element)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return True


class AnythingFilter(ISelectionFilter):
    """Whatever is in the way, here or in a link."""

    def AllowElement(self, element):
        return True

    def AllowReference(self, reference, point):
        return True


class NotTheseFilter(ISelectionFilter):
    """Anything in this model except the services being moved.

    A run cannot be offset around itself, and leaving it
    pickable is an easy way to end up with a jog built to clear
    its own body.
    """

    def __init__(self, services):
        self.ids = set(so_core.eid_value(e.Id) for e in services)

    def AllowElement(self, element):
        try:
            if so_core.eid_value(element.Id) in self.ids:
                return False
            return not _is_link(element)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return True


def _is_link(element):
    """A whole link instance is the entire building, not an
    obstruction. Its contents are picked with LinkedElement."""
    try:
        from Autodesk.Revit.DB import RevitLinkInstance
        return isinstance(element, RevitLinkInstance)
    except Exception:
        return False


def _refusal(element, reason):
    return {
        'ok': False,
        'element_id': so_core.eid_value(element.Id) if element is not None else 0,
        'kind': so_model.kind_of(element) if element is not None else u'',
        'notes': [], 'problems': [], 'created': [],
        'reason': reason, 'mode': u'jog',
    }


def read_selection(uidoc, doc):
    """Split whatever was selected into services and obstacles.

    A selection is allowed to hold both: the pipes, ducts,
    cable tray and conduit are what moves, and anything else in
    it is what they move around. That means the whole tool can
    be a selection and one button press.
    """
    services, others = [], []
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return services, others

    for element_id in ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue
        if so_model.is_supported(element) and so_model.axis_of(element) is not None:
            services.append(element)
        elif not _is_link(element):
            others.append(element)

    services.sort(key=lambda e: so_core.eid_value(e.Id))
    others.sort(key=lambda e: so_core.eid_value(e.Id))
    return services, others


def _label(element, linked):
    try:
        name = element.Category.Name
    except Exception:
        name = u'Element'
    try:
        type_name = so_core.to_text(
            element.Document.GetElement(element.GetTypeId()).Name)
    except Exception:
        type_name = u''
    parts = [so_core.to_text(name)]
    if type_name:
        parts.append(type_name)
    parts.append(u'id {0}'.format(so_core.eid_value(element.Id)))
    if linked:
        parts.append(u'in a link')
    return u'  -  '.join(parts)


def _add_obstruction(doc, element, transform, linked, out, seen):
    """Read one thing to go round, once."""
    key = (so_core.eid_value(element.Id), bool(linked))
    if key in seen:
        return
    seen.add(key)

    solids = so_clash.element_solids(element, transform)
    points = so_clash.solid_points(solids)
    if not points:
        points = so_clash.geometry_points(element, transform)
    if not points:
        return

    kind = so_clash.classify(element)
    if not kind:
        from Autodesk.Revit.DB import XYZ
        kind = so_clash.classify_by_shape(points, XYZ.BasisZ)

    out.append({'element': element, 'points': points, 'solids': solids,
                'kind': kind, 'label': _label(element, linked)})


def _pick_obstructions(uidoc, doc, services, out, seen):
    """This model first, then links. Either can be skipped.

    They have to be two picks. ObjectType.Element hovers a link
    as one whole building rather than the beam inside it, and
    ObjectType.LinkedElement will not pick anything in this
    model at all - which is why model elements could not be
    picked before this.
    """
    from Autodesk.Revit.DB import Transform

    try:
        picked = uidoc.Selection.PickObjects(
            ObjectType.Element, NotTheseFilter(services),
            u'Pick what is in the way IN THIS MODEL, then Finish  -  '
            u'Escape to skip to linked models')
        for reference in picked or []:
            element = doc.GetElement(reference.ElementId)
            if element is not None:
                _add_obstruction(doc, element, Transform.Identity, False,
                                 out, seen)
    except OperationCanceledException:
        pass
    except Exception:
        pass

    try:
        picked = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, AnythingFilter(),
            u'Pick what is in the way IN A LINK, then Finish  -  '
            u'Escape to skip')
        for reference in picked or []:
            element, transform, linked = so_clash.resolve_reference(
                doc, reference)
            if element is not None:
                _add_obstruction(doc, element, transform, linked, out, seen)
    except OperationCanceledException:
        pass
    except Exception:
        pass


def run(uiapp):
    """One command press. Returns the list of records."""
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

    # --- the services, and anything selected alongside them ---
    services, selected_others = read_selection(uidoc, doc)

    if not services:
        try:
            picked = uidoc.Selection.PickObjects(
                ObjectType.Element, ServiceFilter(),
                u'Pick the services to move, then Finish  -  Escape to stop')
        except OperationCanceledException:
            return []
        except Exception:
            return []
        for reference in picked or []:
            element = doc.GetElement(reference.ElementId)
            if element is not None and so_model.axis_of(element) is not None:
                services.append(element)

    if not services:
        return [_refusal(None, u'No pipes, ducts, cable tray or conduit were '
                               u'picked.')]

    if len(services) > 1:
        axes = [so_model.axis_of(s) for s in services]
        parallel, worst = so_core.axes_parallel(axes)
        if not parallel:
            return [_refusal(services[0],
                             u'Elements not parallel. User must manually '
                             u'review them.\n\nThe worst pair is {0:.2f} '
                             u'degrees apart, and this tool allows {1:.2f}. '
                             u'Nothing has been changed.'
                             .format(worst, so_core.PARALLEL_DEG))]

    # --- what is in the way ---
    from Autodesk.Revit.DB import Transform
    obstructions, seen = [], set()
    for element in selected_others:
        _add_obstruction(doc, element, Transform.Identity, False,
                         obstructions, seen)

    if not obstructions:
        _pick_obstructions(uidoc, doc, services, obstructions, seen)

    if not obstructions:
        return [_refusal(services[0],
                         u'Nothing was picked to go round. Select it with the '
                         u'services, or pick it when asked - this model and '
                         u'linked models are both offered.')]

    # --- look at it, then do it ---
    chosen = clash_window.ask(doc, view, services, obstructions, settings)
    if not chosen:
        return []

    records = []
    for found in chosen:
        records.append(so_model.apply_offset(doc, found['analysis'],
                                             found['distance_mm'],
                                             found['direction'], settings))
    return records
