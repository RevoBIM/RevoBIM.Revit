# -*- coding: utf-8 -*-
"""RevoBIM MEP System Manager - pipes, ducts and containment, each on its
own tab, grouped by service type; isolate a selection in 3D, or change its
type while keeping chosen parameter data.

A thin loader. The tool lives in the modules beside it, loaded in stages so a
failure names the stage it died in rather than showing a blank white window.
"""
__title__ = "MEP System Manager"
__author__ = "RevoBIM"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _report(stage, text):
    path = u""
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, "mep_system_manager_last_error.txt")
        handle = open(path, "w")
        try:
            handle.write("MEP System Manager failed while {0}\n\n{1}\n".format(stage, text))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog("RevoBIM MEP System Manager")
        dialog.MainInstruction = "The tool stopped while {0}.".format(stage)
        dialog.MainContent = "Details were written to:\n{0}".format(path)
        dialog.ExpandedContent = text[-1800:]
        dialog.Show()
    except Exception:
        pass


_stage = "referencing assemblies"
try:
    import msm_clr  # noqa: F401
    _stage = "loading modules"
    import msm_window
    _stage = "reading the project and opening the window"
    msm_window.launch(__revit__)  # noqa: F821 - pyRevit provides __revit__
except Exception:
    _report(_stage, traceback.format_exc())
