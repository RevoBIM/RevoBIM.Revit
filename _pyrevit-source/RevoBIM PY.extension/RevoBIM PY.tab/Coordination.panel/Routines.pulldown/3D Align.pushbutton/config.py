# -*- coding: utf-8 -*-
"""3D Align settings - Shift+Click on the 3D Align button.

Thin loader, the same shape as script.py.
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def report(stage, text):
    message = u'3D Align settings stopped while {0}.\n\n{1}'.format(stage, text)
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


stage = 'loading assemblies'
try:
    import a3d_clr  # noqa: F401
    stage = 'loading the settings window'
    import a3d_ui
    stage = 'showing the settings'
    a3d_ui.show_settings()
except Exception:
    report(stage, traceback.format_exc())
