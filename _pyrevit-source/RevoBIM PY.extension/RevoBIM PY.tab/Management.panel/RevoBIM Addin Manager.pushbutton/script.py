# -*- coding: utf-8 -*-
u"""Open the RevoBIM Addin Manager pane."""

# Required: where Revit will not give up a dockable pane the tool falls back
# to a modeless window, and pyRevit tears the engine down when the command
# returns unless this is set - leaving the window on screen with every handler
# in it dead, which is indistinguishable from a broken tool.
__persistentengine__ = True

__title__ = "RevoBIM Addin Manager"
__author__ = "RevoBIM"
__doc__ = ("Every pyRevit addin in your extensions folder, in one searchable "
           "dockable panel. Search by name, or by what an addin does. Click to "
           "show the panel, click again to hide it.")

import os
import sys
import traceback

# A thin loader. Everything that can fail lives in the modules beside it,
# imported in stages, so a failure arrives as a dialog naming the stage rather
# than as a blank white pyRevit window with no traceback in it.

STAGE = ["starting"]


def _tool_folder():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def _report(message):
    text = "RevoBIM Addin Manager failed while {0}.\n\n{1}".format(STAGE[0], message)
    try:
        base = os.environ.get("APPDATA")
        if base:
            root = os.path.join(base, "RevoBIM")
            if not os.path.isdir(root):
                os.makedirs(root)
            handle = open(os.path.join(root, "revobim_addins_last_error.txt"), "wb")
            try:
                handle.write(text.encode("utf-8"))
            finally:
                handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Addin Manager", text)
    except Exception:
        pass


try:
    STAGE[0] = "putting its own folder on the path"
    shared = _tool_folder()
    if shared not in sys.path:
        sys.path.append(shared)

    STAGE[0] = "loading its modules"
    import rba_pane

    STAGE[0] = "opening the pane"
    ok, message = rba_pane.show(__revit__)  # noqa: F821  - pyRevit supplies it
    if not ok and message:
        _report(message)

except Exception:
    _report(traceback.format_exc())
