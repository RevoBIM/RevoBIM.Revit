# -*- coding: utf-8 -*-
"""Find Room - pick a room or space (this model or a linked one), pick a
floor plan on its level, and go: the plan opens in Temporary View Properties
with room references and colour fill on, the room coloured and zoomed to.

Thin loader: loads in stages and names the stage that failed, rather than
leaving a blank pyRevit window. No clr.AddReference here - frm_clr owns them.
"""
__title__ = "Find Room"
__author__ = "RevoBIM"
__doc__ = ("Find a room or space by level and go to it on a floor plan: "
           "room references and colour fill switched on temporarily, the room "
           "coloured and zoomed to.")
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _fail(stage, exc_text):
    text = u"RevoBIM Find Room could not {0}.\n\n{1}".format(stage, exc_text)
    try:
        import frm_ui
        frm_ui.write_error(text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Find Room", text)
    except Exception:
        pass


def main():
    stage = u"load its assemblies"
    try:
        import frm_clr  # noqa: F401
        stage = u"load its modules"
        import frm_core  # noqa: F401
        import frm_revit  # noqa: F401
        import frm_ui  # noqa: F401
        import frm_window
        stage = u"read the open model"
        uiapp = __revit__  # noqa: F821 - provided by pyRevit
        if uiapp.ActiveUIDocument is None:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show("RevoBIM Find Room", "Open a model first.")
            return
        stage = u"show its window"
        frm_window.launch(uiapp)
    except Exception:
        _fail(stage, traceback.format_exc())


main()
