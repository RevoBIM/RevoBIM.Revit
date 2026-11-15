# -*- coding: utf-8 -*-
__title__ = "RevoBIM Isolate Service Type"
__doc__ = ("Isolates everything in the view sharing the selected element's "
           "service type. With nothing selected, pick several then Finish. "
           "Settings sit on the button beside this one.")
__author__ = "RevoBIM PY"

u"""Loads in stages and says which stage failed.

A blank white pyRevit window means the script died before any of it ran -
there is no traceback to read because there was no runtime to raise one.  Each
stage below sits in its own try/except and reports into a Revit dialog and into
%APPDATA%\\RevoBIM\\ist_last_error.txt.
"""

import os
import sys
import traceback

STAGE = u"start"

HERE = os.path.dirname(os.path.abspath(__file__))
PULLDOWN = os.path.dirname(HERE)
if PULLDOWN not in sys.path:
    sys.path.append(PULLDOWN)


def _fail(stage, err):
    text = u"Isolate Service Type failed while {0}.\n\n{1}".format(
        stage, traceback.format_exc())
    try:
        folder = os.path.join(os.getenv(u"APPDATA") or u"", u"RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, u"ist_last_error.txt"), u"w")
        try:
            handle.write(text.encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u"RevoBIM Isolate Service Type", text)
    except Exception:
        pass


try:
    STAGE = u"referencing assemblies"
    import ist_clr  # noqa: F401

    STAGE = u"loading modules"
    import ist_core
    import ist_ui

    STAGE = u"reading the document"
    uidoc = __revit__.ActiveUIDocument  # noqa: F821  - pyRevit provides it
    if uidoc is None or uidoc.Document is None:
        raise Exception(u"No document is open.")

    values = ist_core.load_settings()

    STAGE = u"isolating"
    report = ist_core.isolate(uidoc, values)

    STAGE = u"reporting"
    if ist_ui.report_wanted(report, values):
        ist_ui.show_results(report, values.get(u"theme", u"dark"))

except Exception as _err:
    _fail(STAGE, _err)
