# -*- coding: utf-8 -*-
"""Every electrical circuit in one Excel-style table: filter any column, add circuit parameters as columns, change Path Mode on many circuits from a dropdown and set Path Offset with Ctrl+C / Ctrl+V."""
__title__ = "Circuit Manager"
__author__ = "RevoBIM"
__persistentengine__ = True

# Thin loader. The tool lives in the cm_*.py modules beside this file. Each
# stage reports itself, so a failure arrives as a dialog naming the stage
# and the traceback - never a blank pyRevit window.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# an upgrade must never be shadowed by modules cached from the last version
for _name in list(sys.modules.keys()):
    if _name.startswith('cm_'):
        del sys.modules[_name]


def _report(stage, detail):
    text = u'Circuit Manager could not start.\n\nStage: {0}\n\n{1}'.format(
        stage, detail)
    try:
        folder = os.path.join(os.environ.get('APPDATA', HERE), 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        import io
        with io.open(os.path.join(folder, 'circuit_manager_last_error.txt'),
                     'w', encoding='utf-8') as fh:
            fh.write(text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM - Circuit Manager', text[:1800])
    except Exception:
        pass


def _main():
    import traceback
    stage = u'referencing assemblies'
    try:
        import cm_clr  # noqa: F401
        stage = u'loading modules'
        import cm_main
        stage = u'reading the project and opening the window'
        cm_main.launch(__revit__)  # noqa: F821  (pyRevit global)
    except Exception:
        _report(stage, traceback.format_exc())


_main()
