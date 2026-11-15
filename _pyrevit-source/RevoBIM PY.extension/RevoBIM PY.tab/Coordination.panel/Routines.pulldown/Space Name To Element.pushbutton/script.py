# -*- coding: utf-8 -*-
"""RevoBIM PY - Space Name To Element.

Loads in stages and reports which stage failed, because a namespace whose
assembly was never referenced, or a layout XAML that will not parse, kills the
script before any of it runs - and what shows in Revit is a blank white pyRevit
window with no traceback in it.
"""

__title__ = "Space Name\nTo Element"
__author__ = "RevoBIM"
__doc__ = ("Writes 'Space Name - Space Number' from every intersecting space\n"
           "onto the elements you pick, into an instance parameter you pick.\n"
           "Elements in several spaces get all of them, joined by ' / '.\n"
           "Pick whole categories or expand down to families and types.\n"
           "Revit stays usable while the window is open.")

# a modeless window needs the engine to survive the command returning
__persistentengine__ = True

import os
import sys
import traceback

# the tool's own folder holds every module it uses, so that the shared
# Routines pulldown and lib\revobim are both left alone
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

STAGE = "start"
LOG_DIR = os.path.join(os.getenv("APPDATA") or "", "RevoBIM")
LOG_PATH = os.path.join(LOG_DIR, "snte_last_error.txt")


def _report(stage, text):
    """A Revit dialog with the traceback, and the same text on disk."""
    body = "Space Name To Element failed while {0}.\n\n{1}".format(stage, text)
    try:
        if not os.path.isdir(LOG_DIR):
            os.makedirs(LOG_DIR)
        handle = open(LOG_PATH, "w")
        try:
            handle.write(body)
        finally:
            handle.close()
        body += "\n\nThis was also written to:\n" + LOG_PATH
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM - Space Name To Element", body)
    except Exception:
        try:
            import System.Windows.Forms as WinForms
            WinForms.MessageBox.Show(body, "RevoBIM")
        except Exception:
            pass


def main():
    global STAGE

    # ---- stage 1: assemblies -------------------------------------------
    STAGE = "referencing assemblies"
    import snte_clr

    # ---- stage 2: modules ----------------------------------------------
    STAGE = "loading modules"
    import snte_core
    import snte_ops          # noqa: F401
    import snte_ui           # noqa: F401
    import snte_tree         # noqa: F401
    import snte_window

    # ---- stage 3: the document -----------------------------------------
    STAGE = "reading the project"
    uiapp = __revit__            # noqa: F821  - injected by pyRevit
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        _report("reading the project", "No project is open.")
        return
    doc = uidoc.Document
    if doc.IsFamilyDocument:
        _report("reading the project",
                "Run this tool in a project, not the family editor.")
        return

    spaces = snte_core.get_placed_spaces(doc)
    if not spaces:
        _report("reading the project",
                "No placed Spaces were found in this model.\n\n"
                "Spaces must be placed and have an area greater than zero.")
        return

    # ---- stage 4: the window -------------------------------------------
    STAGE = "showing the window"
    window = snte_window.SpaceNameWindow(uiapp)
    window.show()


try:
    main()
except Exception:
    _report(STAGE, traceback.format_exc())
