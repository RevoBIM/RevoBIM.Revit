# -*- coding: utf-8 -*-
"""Every level in the project with the elements associated to it, grouped by
category. Tick or Shift/Ctrl-select elements and assign them to another level
- nothing moves, only the level they are associated with changes."""
__title__ = "Level Manager"
__author__ = "RevoBIM"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _report(stage, text):
    body = u"Level Manager failed while {0}.\n\n{1}".format(stage, text)
    try:
        folder = os.path.join(os.environ.get("APPDATA", HERE), "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, "level_manager_error.txt"), "wb") as handle:
            handle.write(body.encode("utf-8"))
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Level Manager", body[:1800])
    except Exception:
        pass


def _main():
    stage = "loading assemblies"
    try:
        import lvm_clr  # noqa: F401
        stage = "loading modules"
        import lvm_core  # noqa: F401
        import lvm_revit  # noqa: F401
        import lvm_ops  # noqa: F401
        import lvm_ui  # noqa: F401
        import lvm_window
        stage = "reading the model and opening the window"
        lvm_window.launch(__revit__)  # noqa: F821
    except Exception:
        _report(stage, traceback.format_exc())


_main()
