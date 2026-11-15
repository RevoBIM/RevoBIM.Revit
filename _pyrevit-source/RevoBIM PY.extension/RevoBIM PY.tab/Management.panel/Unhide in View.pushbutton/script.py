# -*- coding: utf-8 -*-
"""Lists the elements hidden in each view and the categories hidden in them, and unhides what you tick."""
# Thin loader. The tool lives in the uiv_*.py modules beside this file, so a
# failure to import arrives as a dialog naming the stage instead of a blank
# white window. Version: uiv_core.__version__ (shown top right of the window).

__title__ = 'Unhide in View'
__author__ = 'RevoBIM'
__persistentengine__ = True

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _report(stage, text):
    path = os.path.join(os.environ.get('APPDATA') or _HERE, 'RevoBIM',
                        'unhide_in_view_last_error.txt')
    try:
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        f = open(path, 'w')
        try:
            f.write('Stage: ' + stage + '\n\n' + text)
        finally:
            f.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        td = TaskDialog('RevoBIM Unhide in View')
        td.MainInstruction = 'Unhide in View stopped while: ' + stage
        td.MainContent = 'The details are saved in ' + path
        td.ExpandedContent = text[-3500:]
        td.Show()
    except Exception:
        pass


_stage = 'loading .NET assemblies'
try:
    import uiv_clr  # noqa: F401
    _stage = 'loading the tool modules'
    import uiv_core  # noqa: F401
    import uiv_window
    _stage = 'opening the window'
    uiv_window.launch(__revit__)  # noqa: F821  (pyRevit provides __revit__)
except Exception:
    _report(_stage, traceback.format_exc())
