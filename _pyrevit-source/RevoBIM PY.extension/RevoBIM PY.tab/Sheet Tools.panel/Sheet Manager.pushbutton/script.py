# -*- coding: utf-8 -*-
"""RevoBIM Sheet Manager.

Loads in stages and reports which stage failed. A blank white pyRevit window
means the script died before any of it ran, and there is no traceback to read
because there was no runtime to raise one - so every stage is caught here and
put into a dialog and a file instead.
"""

__title__ = "Sheet Manager"
__author__ = "RevoBIM"
__doc__ = ("Every sheet in the project in one table, grouped and cascaded the "
           "way you want it, with multi-select duplication of sheets and the "
           "views on them.")
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STAGE = "assemblies"


def _write_error(stage, text):
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, "sheet_manager_last_error.txt"), "wb")
        try:
            handle.write((u"stage: {0}\n\n{1}".format(stage, text)).encode("utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def _fail(stage, text):
    _write_error(stage, text)
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog("RevoBIM Sheet Manager")
        dialog.MainInstruction = "Sheet Manager could not start"
        dialog.MainContent = ("It failed at the '{0}' stage.\n\n{1}"
                              .format(stage, text))
        dialog.Show()
    except Exception:
        pass


try:
    STAGE = "assemblies"
    import shtm_clr

    STAGE = "modules"
    import shtm_core
    import theme
    import shtm_ui
    import shtm_model
    import shtm_plan
    import shtm_grid
    import shtm_dup
    import shtm_duplicate
    import shtm_settings
    import shtm_window

    STAGE = "reading the project"
    from System import AppDomain

    uidoc = __revit__.ActiveUIDocument
    if uidoc is None:
        raise Exception("no document is open")
    doc = uidoc.Document
    settings = shtm_core.load_settings()

    # what is selected in Revit right now - sheets picked in the Project
    # Browser come through here. Only the sheets among it filter the table.
    picked = []
    try:
        picked = [shtm_core.eid_value(i) for i in uidoc.Selection.GetElementIds()]
    except Exception:
        picked = []

    STAGE = "showing the window"
    PARK = u"RevoBIM.SheetManager.window.v{0}".format(shtm_core.__version__)
    domain = AppDomain.CurrentDomain

    existing = None
    try:
        existing = domain.GetData(PARK)
    except Exception:
        existing = None

    reused = False
    if existing is not None:
        try:
            existing.Activate()
            reused = True
            # pressed again while shrunk to the taskbar: bring it back up
            try:
                existing.Tag.bring_forward()
            except Exception:
                pass
            # opened again with sheets selected: the open window takes them
            if picked:
                try:
                    existing.Tag.use_revit_selection(picked, reopened=True)
                except Exception:
                    pass
        except Exception:
            reused = False
            try:
                domain.SetData(PARK, None)
            except Exception:
                pass

    if not reused:
        tool = shtm_window.SheetManagerWindow(__revit__, doc, settings, picked)
        window = tool.show()
        try:
            # so a second press of the ribbon button can reach the open tool
            window.Tag = tool
        except Exception:
            pass
        try:
            domain.SetData(PARK, window)
        except Exception:
            pass

        def _forget(sender, event):
            try:
                domain.SetData(PARK, None)
            except Exception:
                pass

        try:
            window.Closed += _forget
        except Exception:
            pass

except Exception:
    _fail(STAGE, traceback.format_exc())
