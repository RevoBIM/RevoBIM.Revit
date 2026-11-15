# -*- coding: utf-8 -*-
"""RevoBIM Pipe Slope Assigner - thin loader.

Click a horizontal pipe, press the button, pick 1:100 / 1:80 / 1:60 / 1:40,
and the run (or the run and the runs joined to it) is set to that fall with
its uprights stretching to follow and every parameter value kept. The window
stays open with Revit fully usable behind it.

This file only finds the tool's own folder and imports the body inside a
try/except, so a failure at load arrives as a dialog naming the stage rather
than as a blank white pyRevit window. __version__ lives in psa_core.py.
"""

__title__ = "RevoBIM Pipe Slope Assigner"
__author__ = "RevoBIM"

# The window is modeless - Revit stays usable while it is open - so pyRevit
# must keep this engine alive after the command returns, or every handler in
# the window is dead the moment it appears.
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ERROR_NAME = u'pipe_slope_assigner_last_error.txt'


def _report(stage, text):
    body = u'RevoBIM Pipe Slope Assigner stopped while {0}.\n\n{1}'.format(stage, text)
    try:
        folder = os.path.join(os.environ.get('APPDATA', HERE), u'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        import io
        handle = io.open(os.path.join(folder, ERROR_NAME), 'w', encoding='utf-8')
        try:
            handle.write(body)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u'RevoBIM Pipe Slope Assigner', body[:1800])
    except Exception:
        pass


_stage = u'loading its modules'
try:
    import psa_main
    _stage = u'running'
    psa_main.main(__revit__)  # noqa: F821  (pyRevit's UIApplication)
except SystemExit:
    pass
except Exception:
    _report(_stage, traceback.format_exc())
