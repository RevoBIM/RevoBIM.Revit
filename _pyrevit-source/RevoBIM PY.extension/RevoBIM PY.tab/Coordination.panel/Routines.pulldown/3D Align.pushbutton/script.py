# -*- coding: utf-8 -*-
"""3D Align - centre one service on another in plan.

Thin loader: imports the tool inside a try/except so a failure arrives as a
dialog naming the stage, not a blank white pyRevit window.
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def report(stage, text):
    message = u'3D Align stopped while {0}.\n\n{1}'.format(stage, text)
    try:
        folder = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, '3d_align_last_error.txt'), 'w') as handle:
            handle.write(message.encode('utf-8') if sys.version_info[0] < 3 else message)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('3D Align', message)
    except Exception:
        pass


def show_results(rows, settings):
    try:
        import a3d_ui
        a3d_ui.show_results(rows, settings)
    except Exception:
        report('showing the results', traceback.format_exc())


stage = 'loading assemblies'
try:
    import a3d_clr  # noqa: F401
    stage = 'loading the tool'
    import a3d_core
    stage = 'running'
    a3d_core.main(__revit__, show_results)
except Exception:
    report(stage, traceback.format_exc())
