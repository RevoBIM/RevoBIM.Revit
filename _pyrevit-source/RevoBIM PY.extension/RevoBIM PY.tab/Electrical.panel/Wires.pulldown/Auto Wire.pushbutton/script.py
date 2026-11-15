# -*- coding: utf-8 -*-
"""Draw the wires for every circuited fitting in the active view."""

__title__ = "RevoBIM Auto Wire"
__author__ = "RevoBIM PY"
# The Shuffle prompt floats by default, so it outlives the command that
# opened it. Without this pyRevit tears the engine down on return and takes
# the window's handlers with it.
__persistentengine__ = True
# The Shuffle prompt floats by default, so it outlives the command that
# opened it. Without this pyRevit tears the engine down on return and takes
# the window's handlers with it.
__doc__ = ("Select fittings and only their circuits are wired. Select "
           "nothing and every circuit in the view that has no wires yet is "
           "wired.\n\n"
           "One continuous snake per circuit, arc wires between fitting "
           "centres trimmed back off each symbol, the wire type taken from "
           "the fitting's emergency parameter, a home run arc pointing at the "
           "switch, and one tag per circuit.\n\n"
           "Shuffle and Previous step through the route options before it is "
           "kept.")

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
        _say('RevoBIM Auto Wire', 'No document is open.')
        return

    settings = core.load_settings()

    def prompt(session, headline):
        return shuffle_window.show(session, headline, 'Auto Wire')

    with core.DialogSuppressor(uiapp):
        report = circuit_core.run_wire_circuits(uiapp, settings, prompt)
    if report is not None and not report.deferred:
        results_window.show(report, settings, uiapp=uiapp)


try:
    main()
except Exception:
    _say('RevoBIM Auto Wire',
         'The tool stopped with an error and nothing was left half done.\n\n'
         + traceback.format_exc())
