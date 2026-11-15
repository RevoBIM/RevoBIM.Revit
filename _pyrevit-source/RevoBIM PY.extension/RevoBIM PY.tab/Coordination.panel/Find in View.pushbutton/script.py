# -*- coding: utf-8 -*-
"""RevoBIM PY - Find in View.

Select elements, press the button, pick a view, press Show Me: the view opens
and zooms to what was selected.

The script loads in stages and reports which stage failed, into a Revit dialog
with the traceback and into %APPDATA%\\RevoBIM\\find_in_view_last_error.txt.
A blank white pyRevit window means the script died before any of it ran, and
there is no traceback to read because there was no runtime to raise one - this
is what turns that into a message naming the stage.
"""

__title__ = "Find in View"
__author__ = "RevoBIM PY"

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

# The assemblies are referenced here, at the very top, before ANY System.* or
# Autodesk.* name is touched anywhere in this file - including inside _report,
# which reaches for Autodesk.Revit.UI.TaskDialog.
_CLR_ERROR = ''
try:
    import fiv_clr  # noqa: F401
except Exception:
    import traceback as _traceback
    _CLR_ERROR = _traceback.format_exc()

_STAGE = 'starting up'


def _report(stage, error_text):
    """Say which stage failed, on screen and on disk."""
    text = 'Find in View could not start.\n\nStage: {0}\n\n{1}'.format(stage, error_text)
    try:
        directory = os.path.join(os.environ.get('APPDATA', ''), 'RevoBIM')
        if not os.path.isdir(directory):
            os.makedirs(directory)
        handle = open(os.path.join(directory, 'find_in_view_last_error.txt'), 'w')
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog('RevoBIM Find in View')
        dialog.MainInstruction = 'Find in View could not start'
        dialog.MainContent = text
        dialog.Show()
    except Exception:
        pass


def main():
    global _STAGE

    # ---------------------------------------------------------- assemblies
    _STAGE = 'referencing assemblies'
    if _CLR_ERROR:
        _report(_STAGE, _CLR_ERROR)
        return

    # ------------------------------------------------------------- modules
    _STAGE = 'loading modules'
    import fiv_core
    import fiv_ui
    import fiv_model
    import fiv_window

    _STAGE = 'reaching Revit'
    uidoc = __revit__.ActiveUIDocument  # noqa: F821 - injected by pyRevit
    uiapp = __revit__  # noqa: F821
    if uidoc is None or uidoc.Document is None:
        _report(_STAGE, 'No document is open.')
        return
    doc = uidoc.Document

    _STAGE = 'reading the settings'
    settings = fiv_core.load_settings()
    palette_name = (settings.get('theme') or 'dark').lower()

    _STAGE = 'reading the selection'
    # the view the run started in: the one the tiled view opens beside
    try:
        host_view_id = doc.ActiveView.Id
    except Exception:
        host_view_id = None
    elements, element_ids, category_ids, category_names = fiv_model.read_selection(uidoc)
    launched_with_a_selection = bool(elements)

    if not elements:
        # nothing selected: ask for element ids instead, the way Revit's own
        # Select Elements by ID does, then carry on with what that finds
        _STAGE = 'asking for element ids'
        by_id = fiv_window.FindByIdWindow(uidoc, uiapp, settings)
        elements, element_ids = by_id.show()
        if not elements and not by_id.skipped:
            return
        if elements:
            fiv_model.select_elements(uidoc, element_ids)
            elements, element_ids, category_ids, category_names = \
                fiv_model.read_selection(uidoc)
            if not elements:
                fiv_ui.message('Those elements could not be selected in this model.',
                               palette_name, uiapp)
                return

    # Launched on a selection that is already drawn in the view you are in:
    # frame it here and stop. Opening a window to ask which view to go to, when
    # the answer is "this one", is the long way round.
    if launched_with_a_selection:
        _STAGE = 'looking in the view you are in'
        try:
            here = doc.ActiveView
        except Exception:
            here = None
        if here is not None:
            zoomed, note = fiv_model.zoom_here(uidoc, here, elements, element_ids,
                                               settings)
            if zoomed:
                return
            if note:
                # it is here, but the zoom would not hold - worth saying rather
                # than quietly opening the window as though it were somewhere else
                fiv_ui.message(note, palette_name, uiapp)
                return

    _STAGE = 'reading the views'
    rows = fiv_model.read_views(doc)
    if not rows:
        fiv_ui.message(
            'This project has no views the tool can open and zoom.\n\n'
            'Drafting views, legends, schedules and sheets are left out '
            'because they cannot show model elements.',
            palette_name, uiapp)
        return

    _STAGE = 'showing the window'
    rects = fiv_model.read_window_rects(uidoc)
    already_tiled = fiv_core.looks_tiled(rects)
    open_view_ids = [rect[0] for rect in rects]
    window = fiv_window.FindInViewWindow(uidoc, uiapp, settings, rows, elements,
                                         element_ids, category_ids, category_names,
                                         already_tiled, open_view_ids)
    chosen = window.show()
    if chosen is None:
        return

    # the selection can have been changed from inside the window, by id, so the
    # zoom has to use what the window ended up with rather than what it opened
    # with
    elements = window.elements
    element_ids = window.element_ids
    category_ids = window.category_ids

    # The window is closed by now: the active view cannot be changed while a
    # modal dialog is open.
    _STAGE = 'opening the view'
    settings = fiv_core.load_settings()
    ok, note = fiv_model.activate_and_zoom(uidoc, chosen.view, elements,
                                           element_ids, settings, uiapp,
                                           host_view_id, category_ids)
    if not ok:
        fiv_ui.message(note, palette_name, uiapp)
    elif note:
        # opened, but the zoom had something to say - report only when there
        # is something that needs a look
        fiv_ui.message(note, palette_name, uiapp)


try:
    main()
except Exception:
    _report(_STAGE, traceback.format_exc())
