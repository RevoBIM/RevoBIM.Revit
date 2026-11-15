# -*- coding: utf-8 -*-
"""Set wire types from the settings, without touching the drawing."""

__title__ = "RevoBIM Apply Wire Types"
__author__ = "RevoBIM PY"
__doc__ = ("Sets the wire type on existing wires and changes nothing else - "
           "no wire is moved, redrawn, retagged or deleted.\n\n"
           "Select a circuit, or a wire or fitting on one, and only those "
           "circuits are done. Select nothing and it asks before doing every "
           "circuit with wires in the active plan.\n\n"
           "The type is decided by the same three questions Auto Wire uses: "
           "an emergency circuit is emergency throughout, a wire bridging two "
           "legs is permanent live, everything else takes the lighting or "
           "power type.")

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
        _say('RevoBIM Apply Wire Types', 'No document is open.')
        return

    settings = core.load_settings()

    def confirm(message, detail):
        return confirm_window.ask(message, detail, 'Apply Wire Types',
                                  'Apply to the view')

    with core.DialogSuppressor(uiapp):
        report = circuit_core.run_apply_types(uiapp, settings, confirm)
    if report is not None:
        results_window.show(report, settings, uiapp=uiapp)


try:
    main()
except Exception:
    _say('RevoBIM Apply Wire Types',
         'The tool stopped with an error and nothing was left half done.\n\n'
         + traceback.format_exc())
