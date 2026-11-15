# -*- coding: utf-8 -*-
"""RevoBIM Number Sequencer

Numbers every element along a duct or fabrication duct system into a
parameter you choose - branches first, then on up the main - and can tag
each numbered element. Modeless: Revit stays usable behind the window.
"""
__title__ = "Number Sequencer"
__author__ = "RevoBIM"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STAGE = "assemblies"


def _report(stage, text):
    msg = u"RevoBIM Number Sequencer failed while loading ({0}).\n\n{1}".format(stage, text)
    try:
        folder = os.path.join(os.environ.get("APPDATA") or HERE, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, "number_sequencer_load_error.txt"), "w") as fh:
            fh.write(msg)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Number Sequencer", msg)
    except Exception:
        pass


try:
    import nsq_clr  # noqa: F401
    STAGE = "modules"
    import nsq_window
    STAGE = "reading the project and showing the window"
    nsq_window.launch(__revit__)  # noqa: F821  (pyRevit global)
except Exception:
    _report(STAGE, traceback.format_exc())
