# -*- coding: utf-8 -*-
"""RevoBIM Tag All - the ribbon command.

A thin loader and nothing else. The tool lives in the modules beside this
file, imported inside a try/except so a failure arrives as a dialog naming
the stage with its traceback, rather than as a blank white pyRevit window
with nothing in it to read.

This button opens a modeless window, so the engine has to stay alive after
the command returns - hence __persistentengine__ below. Without it every
handler in the window is dead the moment the command ends, which looks
exactly like a broken tool and cannot report itself.
"""
__title__ = "Tag All"
__author__ = "RevoBIM"
__doc__ = ("Tag every family or room in the current view or a set of views.\n"
           "Pick the categories, families and types, choose the tag for each,\n"
           "set the offset and the leader, and tag them all in one run.\n"
           "Works on linked models as well as this one.")
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

STAGE = ["starting"]


def breadcrumb(text):
    """Written before anything that can fail, so a load that dies without a
    runtime still leaves something behind to read."""
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        root = os.path.join(base, "RevoBIM")
        if not os.path.isdir(root):
            os.makedirs(root)
        handle = open(os.path.join(root, "tag_all_last_error.txt"), "w")
        try:
            handle.write(text.encode("utf-8") if isinstance(text, type(u"")) else text)
        finally:
            handle.close()
    except Exception:
        pass


def report(stage, detail):
    message = u"RevoBIM Tag All could not start.\n\nStage: {0}\n\n{1}".format(stage, detail)
    breadcrumb(message)
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog("RevoBIM Tag All")
        dialog.MainInstruction = u"Tag All could not start"
        dialog.MainContent = u"It failed at: {0}".format(stage)
        dialog.ExpandedContent = detail
        dialog.Show()
    except Exception:
        pass


def main():
    STAGE[0] = "referencing assemblies"
    breadcrumb(u"in progress: {0}".format(STAGE[0]))
    import tagall_clr  # noqa: F401

    STAGE[0] = "loading the tool"
    breadcrumb(u"in progress: {0}".format(STAGE[0]))
    import tagall_core as core
    import tagall_window as window_module

    STAGE[0] = "finding Revit"
    breadcrumb(u"in progress: {0}".format(STAGE[0]))
    uiapp = None
    handle = None
    try:
        uiapp = __revit__          # noqa: F821  (pyRevit puts it in the builtins)
    except Exception:
        uiapp = None
    if uiapp is None:
        try:
            from pyrevit import HOST_APP
            uiapp = HOST_APP.uiapp
        except Exception:
            uiapp = None
    if uiapp is None:
        raise RuntimeError("No UIApplication - run this from the Revit ribbon.")
    try:
        handle = uiapp.MainWindowHandle
    except Exception:
        handle = None

    STAGE[0] = "reading the project"
    breadcrumb(u"in progress: {0}".format(STAGE[0]))
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        raise RuntimeError("No open project. Open a model and run it again.")
    if uidoc.Document.IsFamilyDocument:
        raise RuntimeError("Tag All runs on a project, not on a family document.")

    STAGE[0] = "showing the window"
    breadcrumb(u"in progress: {0}".format(STAGE[0]))
    core.log(u"opening Tag All v{0}".format(core.__version__))
    window_module.open_window(uiapp, handle)

    # nothing failed, so the breadcrumb is cleared - a file left behind is
    # always the record of a load that did not finish
    core.remove_file(core.breadcrumb_path())


try:
    main()
except Exception:
    report(STAGE[0], traceback.format_exc())
