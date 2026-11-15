# -*- coding: utf-8 -*-
"""Pull wire ends onto the fittings they are joined to."""

__title__ = "RevoBIM Align Wire Ends"
__author__ = "RevoBIM PY"
__doc__ = ("Moves the point where a wire meets its fitting onto where it "
           "belongs - the node you would otherwise drag by hand - and "
           "changes nothing else. No wire is retyped, retagged, reconnected "
           "or deleted, and none changes its element id.\n\n"
           "Select wires and only those are done. Select circuits and every "
           "wire on them is done. Select nothing and it asks before doing "
           "every wire in the active plan.\n\n"
           "Where the end sits is the same rule Auto Wire draws with: short "
           "of the symbol by the trim setting, or on the connector at the "
           "symbol centre.")

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
    import confirm_window
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
        _say('RevoBIM Align Wire Ends', 'No document is open.')
        return

    settings = core.load_settings()

    def confirm(message, detail):
        return confirm_window.ask(message, detail, 'Align Wire Ends',
                                  'Align the view')

    with core.DialogSuppressor(uiapp):
        report = circuit_core.run_align_ends(uiapp, settings, confirm)
    if report is not None:
        results_window.show(report, settings, uiapp=uiapp)


try:
    main()
except Exception:
    _say('RevoBIM Align Wire Ends',
         'The tool stopped with an error and nothing was left half done.\n\n'
         + traceback.format_exc())
