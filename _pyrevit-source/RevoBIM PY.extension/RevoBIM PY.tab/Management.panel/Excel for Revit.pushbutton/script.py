# -*- coding: utf-8 -*-
"""Excel for Revit - edit the selected schedule in a spreadsheet grid.

This file is deliberately tiny. Everything the tool does lives in efr_core.py,
and this loads it inside a try/except.

The reason: a blank white pyRevit window means the script died before any of it
ran, and there is no traceback to read because there was no runtime left to
raise one. A tool that is one big script cannot report its own import failure.
A loader this short practically cannot fail, so it is still standing to say
what went wrong.
"""

__title__ = "Excel for Revit"
__author__ = "RevoBIM"
__doc__ = "Edit the selected schedule in a spreadsheet grid, then apply in one transaction."
__persistentengine__ = True   # the window is modeless; without this pyRevit
                              # tears the engine down when the command returns
                              # and every button in the window goes dead

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(__file__)
if HERE and HERE not in sys.path:
    sys.path.insert(0, HERE)

# never the tool's own folder: a log written there ships with the next build
LOG_DIR = os.path.join(os.environ.get('APPDATA') or tempfile.gettempdir(),
                       'RevoBIM PY')
LOG_PATH = os.path.join(LOG_DIR, 'excel_for_revit_last_error.txt')


def report(stage, detail):
    """Say what happened, in a dialog and in a file that outlives it."""
    text = ('Excel for Revit could not start.\n\nIt failed while {0}.\n\n'
            '{1}'.format(stage, detail))
    try:
        if not os.path.isdir(LOG_DIR):
            os.makedirs(LOG_DIR)
        handle = open(LOG_PATH, 'w')
        try:
            handle.write(text)
        finally:
            handle.close()
        text += '\n\nThis was also written to:\n' + LOG_PATH
    except Exception:
        pass
    try:
        import clr
        clr.AddReference('RevitAPIUI')
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('Excel for Revit', text)
        return
    except Exception:
        pass
    try:
        import clr
        clr.AddReference('System.Windows.Forms')
        from System.Windows.Forms import MessageBox
        MessageBox.Show(text, 'Excel for Revit')
    except Exception:
        pass


def run():
    stage = 'loading the tool'
    try:
        import efr_core
    except Exception:
        report(stage, traceback.format_exc())
        return
    stage = 'starting the tool'
    try:
        efr_core.main()
    except Exception:
        report(stage, traceback.format_exc())


run()
