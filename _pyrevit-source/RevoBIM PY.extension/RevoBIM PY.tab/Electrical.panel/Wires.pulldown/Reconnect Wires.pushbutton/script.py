# -*- coding: utf-8 -*-
"""Join loose wire ends onto the circuited elements beside them."""

__title__ = "RevoBIM Reconnect Wires"
__author__ = "RevoBIM PY"
__doc__ = ("Select the wires that have come away from their fittings and run "
           "this. Each loose end is joined to the nearest lighting or "
           "electrical element that carries a circuit and has no wire on it "
           "yet, which puts the wire on that circuit.\n\n"
           "Version and settings live in the pulldown's shared module; the "
           "Settings button beside this one edits them.")

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
    import results_window
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
             'The shared module would not load, so nothing ran.\n\n'
             'This is almost always a mis-namespaced import. Run '
             'import_check.py in the pulldown folder to find it.\n\n'
             + _LOAD_ERROR)
        return

    uiapp = __revit__
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        _say('RevoBIM Reconnect Wires', 'No document is open.')
        return

    settings = core.load_settings()
    keep_running = core._settings_bool(settings, 'keep_running')

    with core.DialogSuppressor(uiapp):
        while True:
            report = core.run_reconnect(uiapp, settings)
            if report is None:      # Escape
                return
            results_window.show(report, settings, uiapp=uiapp)
            if not keep_running:
                return


try:
    main()
except Exception:
    _say('RevoBIM Reconnect Wires',
         'The tool stopped with an error and nothing was left half done.\n\n'
         + traceback.format_exc())
