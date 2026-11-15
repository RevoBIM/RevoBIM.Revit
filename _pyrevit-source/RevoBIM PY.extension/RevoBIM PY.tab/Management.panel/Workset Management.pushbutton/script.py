# -*- coding: utf-8 -*-
"""Workset Management - manage worksets in a table and assign categories to them.

Manage Worksets: every workset with its element count, sortable and filterable;
rename in place or in bulk (find and replace, prefix, suffix, trim, case);
delete several at once, choosing one workset for all their elements; create
and rename through Excel.  Worksets are checked out automatically when needed.
Workset Assigner: put whole categories - Cable Tray split by Service Type -
onto worksets.

Modeless: the window floats over Revit, so the model can be panned with it
open; every read and write goes to Revit through an ExternalEvent.

Thin loader: the tool lives in the wsm_ modules beside this file.  Each stage
runs inside its own try/except, so a failure arrives as a dialog naming the
stage instead of a blank pyRevit window.  Revit 2024 - 2027.
"""

import os
import sys
import traceback

__title__ = "Workset Management"
__author__ = "RevoBIM PY"

# The window is modeless - Revit stays usable while it is open - so the engine
# has to outlive the command, or every handler in the window dies with it.
__persistentengine__ = True

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STAGE = {"name": "starting"}


def _report(stage, detail):
    text = u"Workset Management stopped while {0}.\n\n{1}".format(stage, detail)
    try:
        folder = os.path.join(os.getenv("APPDATA") or HERE, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        import io
        handle = io.open(os.path.join(folder, "workset_management_last_error.txt"),
                         "w", encoding="utf-8")
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM PY - Workset Management", text)
    except Exception:
        pass


def _main():
    STAGE["name"] = "loading the .NET assemblies"
    import wsm_clr  # noqa: F401

    STAGE["name"] = "loading the tool's modules"
    import wsm_core
    import wsm_revit
    import wsm_window

    STAGE["name"] = "reading the document"
    uidoc = __revit__.ActiveUIDocument  # noqa: F821
    if uidoc is None:
        _report("starting", u"Open a project first.")
        return
    document = uidoc.Document
    if document.IsFamilyDocument:
        _report("starting", u"Worksets live in projects - open a project, not a family.")
        return
    if not wsm_revit.is_workshared(document):
        _report("starting", u"This model is not workshared, so it has no worksets yet.\n\n"
                            u"Collaborate > Collaborate turns worksharing on; then run "
                            u"Workset Management again.")
        return

    STAGE["name"] = "building and showing the window"
    wsm_window.run(__revit__, document)  # noqa: F821
    STAGE["name"] = "finished (v{0})".format(wsm_core.VERSION)


try:
    _main()
except Exception:
    _report(STAGE["name"], traceback.format_exc())
