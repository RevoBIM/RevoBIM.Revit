# -*- coding: utf-8 -*-
__title__ = "RevoBIM Reset Hide"
__doc__ = ("Opens the floating Reset Hide window: everything Hide Service Type "
           "has hidden in this model, view by view, to put back or hide "
           "again from memory.")
__author__ = "RevoBIM PY"

# The window outlives the command; without this its buttons go dead.
__persistentengine__ = True

import os
import sys
import traceback

STAGE = u"start"

HERE = os.path.dirname(os.path.abspath(__file__))
PULLDOWN = os.path.dirname(HERE)
if PULLDOWN not in sys.path:
    sys.path.append(PULLDOWN)


def _fail(stage, err):
    text = u"Reset Hide failed while {0}.\n\n{1}".format(
        stage, traceback.format_exc())
    try:
        folder = os.path.join(os.getenv(u"APPDATA") or u"", u"RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, u"ist_reset_last_error.txt"), u"w")
        try:
            handle.write(text.encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u"RevoBIM Reset Hide", text)
    except Exception:
        pass


try:
    STAGE = u"referencing assemblies"
    import ist_clr  # noqa: F401

    STAGE = u"loading modules"
    import ist_core
    import ist_resethide

    STAGE = u"reading the document"
    uidoc = __revit__.ActiveUIDocument  # noqa: F821  - pyRevit provides it
    if uidoc is None or uidoc.Document is None:
        raise Exception(u"No document is open.")

    STAGE = u"opening the window"
    ist_resethide.show(uidoc.Document, ist_core.load_settings())

except Exception as _err:
    _fail(STAGE, _err)
