# -*- coding: utf-8 -*-
"""Click a scanned object in a linked point cloud and get the Revit element
it is - pipe, duct, cable tray, conduit, wall, floor, ceiling, column or
beam - at the closest type and size the project has."""
__title__ = 'Click to RVT Element'
__author__ = 'RevoBIM'
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _report(stage, text):
    """Fallback reporter for when c2r_ui itself could not load."""
    try:
        folder = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, 'click_to_rvt_error.txt'), 'w') as f:
            f.write(stage + '\n' + text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('Click to RVT Element', stage + ' failed:\n\n' + text[-1500:])
    except Exception:
        pass


def _main():
    stage = 'Loading assemblies'
    try:
        import c2r_clr  # noqa: F401
        stage = 'Loading modules'
        import c2r_version  # noqa: F401
        import c2r_core  # noqa: F401
        import c2r_cloud  # noqa: F401
        import c2r_build  # noqa: F401
        import c2r_jobs  # noqa: F401
        import c2r_drawer  # noqa: F401
        import c2r_ui
    except Exception:
        _report(stage, traceback.format_exc())
        return
    stage = 'Reading the project'
    try:
        uiapp = __revit__  # noqa: F821  (pyRevit global)
        if uiapp.ActiveUIDocument is None:
            _report(stage, 'Open a model first.')
            return
        stage = 'Opening the window'
        c2r_ui.launch(uiapp)
    except Exception:
        c2r_ui.report_error(stage, traceback.format_exc())


_main()
