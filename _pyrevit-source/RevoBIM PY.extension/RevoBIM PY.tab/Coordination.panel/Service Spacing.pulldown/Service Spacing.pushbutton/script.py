# -*- coding: utf-8 -*-
"""RevoBIM Service Spacing - space selected services centre to centre.

Runs on the current selection with no window and no prompts.  With nothing
selected it asks for the services and Return (or Finish) completes the pick.

The picks run inside the command itself, so there is no modeless window and
therefore no need for __persistentengine__ and none of the engine-teardown
problems that come with it.
"""

__title__ = "RevoBIM Service Spacing"
__author__ = "RevoBIM PY"

import os
import sys
import traceback

HERE = os.path.dirname(__file__)
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.append(PARENT)

# A failure to load the shared module is caught and said properly, rather than
# showing up as a blank white pyRevit window.
try:
    import service_spacing_core as core
    import results_window
except Exception:
    from pyrevit import forms as _forms
    _forms.alert("Service Spacing could not load its shared module.\n\n" +
                 traceback.format_exc(), title="RevoBIM Service Spacing")
    raise

from Autodesk.Revit import DB
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

__version__ = core.__version__

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
uiapp = __revit__


PICKABLE = [
    "OST_PipeCurves", "OST_FlexPipeCurves", "OST_DuctCurves",
    "OST_FlexDuctCurves", "OST_CableTray", "OST_Conduit",
    "OST_GenericModel",
]


def _pickable_ids():
    values = []
    for name in PICKABLE:
        try:
            values.append(int(getattr(DB.BuiltInCategory, name)))
        except Exception:
            continue
    return values


class ServiceFilter(ISelectionFilter):
    def __init__(self):
        self.allowed = _pickable_ids()

    def AllowElement(self, element):
        try:
            if element.Category is None:
                return False
            return core.eid_value(element.Category.Id) in self.allowed
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


def _selected_elements():
    elements = []
    try:
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if element is None:
                continue
            try:
                if element.Category is None:
                    continue
            except Exception:
                continue
            elements.append(element)
    except Exception:
        pass
    return elements


def _pick_elements():
    """PickObjects is the only way to take several, and it cannot return
    without Return or Finish - that is the one keypress in the run."""
    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.Element, ServiceFilter(),
            "Pick the services to space, then press Return")
    except Exception:
        return []
    elements = []
    for reference in references:
        element = doc.GetElement(reference.ElementId)
        if element is not None:
            elements.append(element)
    return elements


def main():
    settings = core.load_settings()

    elements = _selected_elements()
    if not elements:
        elements = _pick_elements()
    if not elements:
        return

    with core.DialogSuppressor(uiapp):
        result = core.space_elements(uidoc, elements, settings)

    mode = settings.text("show_results")
    if mode == "never":
        return
    if mode == "always" or result.needs_a_look() or not result.ok:
        try:
            results_window.show_results(result, settings)
        except Exception:
            pass


try:
    main()
except Exception:
    from pyrevit import forms
    forms.alert("Service Spacing stopped:\n\n" + traceback.format_exc(),
                title="RevoBIM Service Spacing")
