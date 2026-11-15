# -*- coding: utf-8 -*-
"""Take one circuit's wires and tags out and redraw them."""

__title__ = "RevoBIM Re-Route Wires"
__author__ = "RevoBIM PY"
# The Shuffle prompt floats by default, so it outlives the command that
# opened it. Without this pyRevit tears the engine down on return and takes
# the window's handlers with it.
__persistentengine__ = True
__doc__ = ("Select a wire or a fitting on a circuit that is already wired. "
           "Its existing wires and their tags come out, and the circuit is "
           "redrawn to the same rules Auto Wire In View uses.\n\n"
           "Shuffle re-routes it a different way; Keep leaves one undo step "
           "and Cancel puts the view back exactly as it was.")

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_PULLDOWN = os.path.dirname(_HERE)
if _PULLDOWN not in sys.path:
    sys.path.append(_PULLDOWN)

_LOAD_ERROR = None
try:
    import wires_core as core
    import circuit_core
    import results_window
    import shuffle_window
except Exception:
    _LOAD_ERROR = traceback.format_exc()


def _say(title, message):
    try:
        import clr
        clr.AddReference('RevitAPIUI')
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(title, message)
    except Exception:
        pass


def main():
    if _LOAD_ERROR is not None:
        _say('RevoBIM Wires',
             'The shared modules would not load, so nothing ran.\n\n'
             'This is almost always a mis-namespaced import. Run '
             'import_check.py in the pulldown folder to find it.\n\n'
             + _LOAD_ERROR)
        return

    uiapp = __revit__
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        _say('RevoBIM Re-Route Wires', 'No document is open.')
        return

    settings = core.load_settings()

    def prompt(session, headline):
        return shuffle_window.show(session, headline, 'Re-Route Wires')

    with core.DialogSuppressor(uiapp):
        report = circuit_core.run_rejig(uiapp, settings, prompt)
    if report is not None and not report.deferred:
        results_window.show(report, settings, uiapp=uiapp)


try:
    main()
except Exception:
    _say('RevoBIM Re-Route Wires',
         'The tool stopped with an error and nothing was left half done.\n\n'
         + traceback.format_exc())
