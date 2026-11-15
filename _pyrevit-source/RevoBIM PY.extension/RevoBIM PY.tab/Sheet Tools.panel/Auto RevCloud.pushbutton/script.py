# -*- coding: utf-8 -*-
"""RevoBIM Auto RevCloud - compare PDFs of the previous issue with the sheets
in the project and cloud the changes on a chosen revision.

Loads in stages and reports which stage failed, so a broken import shows up
as a message naming the file rather than a blank white pyRevit window.
"""
__title__ = u"Auto RevCloud"
__author__ = u"RevoBIM"
__doc__ = (u"Auto RevCloud - pick the PDFs of the previous issue and the sheets they "
           u"belong to, choose a revision, and cloud every substantial change on "
           u"each sheet, inside the views where possible.")
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STAGE = [u"starting"]


def _report(stage, text):
    body = u"Auto RevCloud failed while {0}.\n\n{1}".format(stage, text)
    try:
        base = os.path.join(os.environ.get(u"APPDATA", HERE), u"RevoBIM")
        if not os.path.isdir(base):
            os.makedirs(base)
        with open(os.path.join(base, u"auto_revcloud_last_error.txt"), u"w") as handle:
            handle.write(body)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog(u"RevoBIM Auto RevCloud")
        dialog.MainInstruction = u"Auto RevCloud failed while {0}".format(stage)
        dialog.MainContent = text[-1800:]
        dialog.Show()
    except Exception:
        pass


def main():
    STAGE[0] = u"referencing assemblies"
    import arc_clr  # noqa: F401

    STAGE[0] = u"loading modules"
    import arc_core
    import arc_model  # noqa: F401
    import arc_ops  # noqa: F401
    import arc_ui  # noqa: F401
    import arc_window

    STAGE[0] = u"reading settings"
    settings = arc_core.load_settings()

    STAGE[0] = u"opening the window"
    uiapp = __revit__  # noqa: F821  (pyRevit provides it)
    if uiapp.ActiveUIDocument is None:
        _report(STAGE[0], u"Open a project first.")
        return
    # The window is parked on the arc_window module, which stays in
    # sys.modules across clicks under the persistent engine; script.py's own
    # globals are re-run every click.
    existing = arc_window.OPEN[0]
    if existing is not None:
        try:
            existing.window.Activate()
            return
        except Exception:
            arc_window.OPEN[0] = None
    icon = os.path.join(HERE, u"icon.png")
    window = arc_window.MainWindow(uiapp, settings, icon)

    def forget(sender, args):
        arc_window.OPEN[0] = None
    window.window.Closed += forget
    arc_window.OPEN[0] = window
    window.show()


try:
    main()
except Exception:
    _report(STAGE[0], traceback.format_exc())
