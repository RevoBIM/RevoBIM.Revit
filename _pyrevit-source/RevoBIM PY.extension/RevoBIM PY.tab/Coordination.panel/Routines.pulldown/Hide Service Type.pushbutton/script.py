# -*- coding: utf-8 -*-
__title__ = "RevoBIM Hide Service Type"
__doc__ = ("Hides everything in the view sharing the selected element's "
           "service type. With nothing selected, opens a list of what is "
           "in the view and in its links. "
           "Settings sit on the button beside this one.")
__author__ = "RevoBIM PY"

# The floating Reset Hide window lives on in this engine after the command
# ends; without this pyRevit disposes the engine and its buttons go dead.
__persistentengine__ = True

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
    text = u"Hide Service Type failed while {0}.\n\n{1}".format(
        stage, traceback.format_exc())
    try:
        folder = os.path.join(os.getenv(u"APPDATA") or u"", u"RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, u"ist_hide_last_error.txt"), u"w")
        try:
            handle.write(text.encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u"RevoBIM Hide Service Type", text)
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

    try:
        nothing = uidoc.Selection.GetElementIds().Count == 0
    except Exception:
        nothing = False

    if nothing and ist_core.is_on(values, u"hide_browse"):
        import ist_browser
        import ist_templates
        report = ist_core.Report()
        report.verb = u"hidden"
        last = ist_templates.last_name()
        how = (values.get(u"template_run") or u"apply").strip().lower()
        if last and how == u"apply":
            # One click: the last template, straight away.  The Reset Hide
            # window's New selection opens a clean list.
            STAGE = u"applying template {0}".format(last)
            picked = ist_browser.run_template(uidoc, values, report, last)
            if picked is not None:
                picked[u"template"] = last
        else:
            STAGE = u"opening the category list"
            picked = ist_browser.run(
                uidoc, values, report,
                preselect=last if how == u"list" else None)
        if picked is not None:
            STAGE = u"hiding from the list"
            report = ist_core.hide_from_list(uidoc, values, picked, report)
            if not picked.get(u"reset") and not picked.get(u"empty"):
                ist_templates.set_last(picked.get(u"template"))
        elif report.refused is None:
            report.cancelled = True
    else:
        STAGE = u"hiding"
        report = ist_core.hide(uidoc, values)

    STAGE = u"reporting"
    if ist_ui.report_wanted(report, values):
        ist_ui.show_results(report, values.get(u"theme", u"dark"),
                            title=u"Hide Service Type",
                            icon_folder=u"Hide Service Type.pushbutton")

    if getattr(report, u"memory", False):
        STAGE = u"opening Reset Hide"
        import ist_resethide
        ist_resethide.show(uidoc.Document, values)

except Exception as _err:
    _fail(STAGE, _err)
