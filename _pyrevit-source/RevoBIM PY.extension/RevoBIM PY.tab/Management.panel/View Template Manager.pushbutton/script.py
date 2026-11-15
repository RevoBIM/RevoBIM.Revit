# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager

Every view template in the project as an editable table: what each one is set
to, how many views use it, and which settings it actually controls. Edits are
staged and coloured until Apply. Unused templates can be isolated and deleted.

Modal: nothing here needs anything picked in the model.

A thin loader. The tool lives in the vtm_* modules beside it and is loaded in
named stages, so a failure arrives as a dialog naming the stage with the
traceback - and is written to %APPDATA%\\RevoBIM\\view_template_manager_error.txt
- rather than as a blank white pyRevit window.
"""

__title__ = "View Template Manager"
__author__ = "RevoBIM PY"
__doc__ = ("Lists every view template in the project with its parameter "
           "settings and how many views use it. Edit cells in place, copy and "
           "paste across them, apply in one go, and delete the templates "
           "nothing is using.")

__version__ = "1.3.1"

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)


def _write_error(stage, detail):
    try:
        folder = os.path.join(os.environ.get("APPDATA") or HERE, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, "view_template_manager_error.txt")
        handle = open(path, "w")
        try:
            handle.write("View Template Manager v{0}\nStage: {1}\n\n{2}".format(
                __version__, stage, detail))
        finally:
            handle.close()
    except Exception:
        pass


def _fail(stage, message, detail=""):
    _write_error(stage, detail or message)
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog("RevoBIM - View Template Manager")
        dialog.MainInstruction = message
        if detail:
            dialog.MainContent = "Stage: {0}\n\n{1}".format(stage, detail)
        dialog.Show()
    except Exception:
        pass


def main():
    stage = "reading the active document"
    try:
        uidoc = __revit__.ActiveUIDocument
    except Exception:
        uidoc = None
    if uidoc is None:
        _fail(stage, "No project open.", "Open a project and run the tool again.")
        return
    doc = uidoc.Document
    if doc.IsFamilyDocument:
        _fail(stage, "This is a family document.",
              "View templates live in projects. Open a project and try again.")
        return

    stage = "loading the tool's modules"
    try:
        import vtm_clr  # noqa: F401
        import vtm_window
    except Exception:
        _fail(stage, "The tool could not load.", traceback.format_exc())
        return

    stage = "reading the project and building the window"
    try:
        window = vtm_window.ManagerWindow(uidoc.Application, doc)
    except Exception:
        _fail(stage, "The tool could not open.", traceback.format_exc())
        return

    stage = "running the window"
    try:
        window.show()
    except Exception:
        _fail(stage, "The tool hit an error.", traceback.format_exc())


main()
