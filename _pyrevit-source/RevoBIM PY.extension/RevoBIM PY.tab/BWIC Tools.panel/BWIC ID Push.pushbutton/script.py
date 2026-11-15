# -*- coding: utf-8 -*-
"""RevoBIM PY - BWIC ID Push

Click 1: pick a Generic Model element in a LINKED model, read CLM_BWIC ID.
Click 2: pick an element in the HOST model, write it into BGL_BWIC ID.

Loops until Escape. Finishes silently - no completion dialog and no pyRevit
output window. Feedback for the previous pair is carried in the status-bar
prompt of the next pick, so the run is never interrupted by a dialog.
"""
__title__ = 'BWIC ID\nPush'
__author__ = 'RevoBIM PY'
__doc__ = ('Push CLM_BWIC ID from a linked Generic Model element into '
           'BGL_BWIC ID on a host element. Two clicks per pair, repeats '
           'until Escape.')

__version__ = '1.2.0'

from Autodesk.Revit.DB import (BuiltInCategory, StorageType, RevitLinkInstance,
                               Transaction, TransactionGroup)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import revit

doc = revit.doc
uidoc = revit.uidoc

SOURCE_PARAM_NAME = 'CLM_BWIC ID'
TARGET_PARAM_NAME = 'BGL_BWIC ID'

# Resolved once, not per hover - AllowReference is called continuously as the
# cursor moves, so anything avoidable in there is worth hoisting out.
GENERIC_MODEL_ID = int(BuiltInCategory.OST_GenericModel)


def eid_value(element_id):
    """ElementId value across Revit 2024-2027.

    .IntegerValue was deprecated in 2024 in favour of .Value (Int64) and
    removed in 2026, so never touch it directly.
    """
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


class LinkedGenericModelFilter(ISelectionFilter):
    """Restricts picking inside links to Generic Model elements.

    Link documents are cached on first resolve: AllowReference fires on every
    mouse move, and GetElement + GetLinkDocument on each of those is the main
    cost of hovering over a busy view.
    """

    def __init__(self, host_doc):
        self.host_doc = host_doc
        self._link_docs = {}

    def AllowElement(self, element):
        # Real filtering happens in AllowReference, once the linked element
        # behind the reference can be resolved.
        return isinstance(element, RevitLinkInstance)

    def _link_doc(self, link_id):
        key = eid_value(link_id)
        if key in self._link_docs:
            return self._link_docs[key]
        link_doc = None
        link_instance = self.host_doc.GetElement(link_id)
        if isinstance(link_instance, RevitLinkInstance):
            link_doc = link_instance.GetLinkDocument()
        self._link_docs[key] = link_doc
        return link_doc

    def AllowReference(self, reference, position):
        try:
            link_doc = self._link_doc(reference.ElementId)
            if link_doc is None:
                return False
            linked_elem = link_doc.GetElement(reference.LinkedElementId)
            if linked_elem is None:
                return False
            category = linked_elem.Category
            return (category is not None
                    and eid_value(category.Id) == GENERIC_MODEL_ID)
        except Exception:
            return False


def read_param(element, param_name):
    """Parameter value as a string, or None if absent/empty."""
    param = element.LookupParameter(param_name)
    if not param or not param.HasValue:
        return None
    if param.StorageType == StorageType.String:
        return param.AsString()
    return param.AsValueString()


def resolve_linked_element(reference, filter_obj):
    """Linked element behind a picked reference, reusing the filter's cache."""
    link_doc = filter_obj._link_doc(reference.ElementId)
    if link_doc is None:
        return None
    return link_doc.GetElement(reference.LinkedElementId)


def pick(prompt, selection_filter=None):
    """One pick. Returns the Reference, or None when Escape is pressed."""
    try:
        if selection_filter is not None:
            return uidoc.Selection.PickObject(
                ObjectType.LinkedElement, selection_filter, prompt)
        return uidoc.Selection.PickObject(ObjectType.Element, prompt)
    except OperationCanceledException:
        return None


def main():
    source_filter = LinkedGenericModelFilter(doc)
    status = ''

    # One TransactionGroup around the whole session: each pair still commits
    # on its own, so nothing is held open across the picks, but the run shows
    # up as a single undo step.
    tg = TransactionGroup(doc, 'BWIC ID Push')
    tg.Start()
    committed = 0

    try:
        while True:
            source_ref = pick(
                '{}Pick the LINKED source (Esc to finish)'.format(status),
                source_filter)
            if source_ref is None:
                break

            source_element = resolve_linked_element(source_ref, source_filter)
            if source_element is None:
                status = 'Could not resolve that link. '
                continue

            value = read_param(source_element, SOURCE_PARAM_NAME)
            if not value:
                status = '{} was empty. '.format(SOURCE_PARAM_NAME)
                continue

            target_ref = pick(
                'Pick the HOST element to receive "{}" (Esc to finish)'.format(value))
            if target_ref is None:
                break

            target_element = doc.GetElement(target_ref.ElementId)
            if target_element is None:
                status = 'Could not resolve that element. '
                continue

            # Checked before opening a transaction, so a skip costs nothing.
            target_param = target_element.LookupParameter(TARGET_PARAM_NAME)
            if not target_param:
                status = 'No {} on that element. '.format(TARGET_PARAM_NAME)
                continue
            if target_param.IsReadOnly:
                status = '{} is read-only there. '.format(TARGET_PARAM_NAME)
                continue

            t = Transaction(doc, 'Push BWIC ID')
            t.Start()
            try:
                target_param.Set(value)
                t.Commit()
                committed += 1
                status = 'Pushed "{}". '.format(value)
            except Exception as ex:
                if t.HasStarted():
                    t.RollBack()
                status = 'Write failed: {}. '.format(ex)
    finally:
        # Nothing written means nothing to keep on the undo stack.
        if committed:
            tg.Assimilate()
        else:
            tg.RollBack()


if __name__ == '__main__':
    main()
