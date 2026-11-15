# -*- coding: utf-8 -*-
"""Settings for Reconnect Wires and Tidy Wires."""

__title__ = "RevoBIM Wires Settings"
__author__ = "RevoBIM PY"
__doc__ = ("Search radius, which categories count as wireable, how far out of "
           "true an end has to be before it is worth pulling, and how results "
           "are reported.\n\n"
           "Written to %APPDATA%\\RevoBIM\\wires.txt as plain key=value "
           "text.")

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
    import settings_window
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
             'The shared module would not load, so the settings window did '
             'not open.\n\nRun import_check.py in the pulldown folder to find '
             'the import that failed.\n\n' + _LOAD_ERROR)
        return
    settings_window.show(__revit__)


try:
    main()
except Exception:
    _say('RevoBIM Wires Settings', traceback.format_exc())
