# -*- coding: utf-8 -*-
"""Resize ducts and a duct accessory family together, to one new size.

Pick the shape and the accessory's size parameters, select the ducts and
accessories, type the new size and press Resize. Revit stays usable while
the window is open.
"""

# The window is modeless: without a persistent engine pyRevit tears the
# engine down when this command returns and every handler goes dead.
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ERROR_FILE = "duct_accessory_resize_last_error.txt"


def report(stage, detail):
    """A failure arrives as a dialog naming the stage, and in a file -
    never as a blank white pyRevit window."""
    text = u"RevoBIM Duct Accessory Resize failed while {0}.\n\n{1}".format(
        stage, detail)
    try:
        folder = os.path.join(os.environ.get("APPDATA", HERE), "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        import io
        with io.open(os.path.join(folder, ERROR_FILE), "w",
                     encoding="utf-8") as handle:
            handle.write(text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Duct Accessory Resize", text[:1800])
    except Exception:
        pass


def main():
    stage = "loading the tool's modules"
    try:
        import dar_window
    except Exception:
        report(stage, traceback.format_exc())
        return
    stage = "opening the window"
    try:
        dar_window.launch(__revit__)  # noqa: F821 - pyRevit's UIApplication
    except Exception:
        report(stage, traceback.format_exc())


main()
