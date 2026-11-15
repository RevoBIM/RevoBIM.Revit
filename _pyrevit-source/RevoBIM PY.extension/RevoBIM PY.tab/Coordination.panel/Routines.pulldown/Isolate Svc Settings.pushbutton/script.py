# -*- coding: utf-8 -*-
__title__ = "RevoBIM Isolate Service Settings"
__doc__ = ("Which parameter holds the service type, which categories travel "
           "with each discipline, and how the tool behaves. Settings are "
           "remembered for next time.")
__author__ = "RevoBIM PY"

import os
import sys
import traceback

STAGE = u"start"

HERE = os.path.dirname(os.path.abspath(__file__))
PULLDOWN = os.path.dirname(HERE)
if PULLDOWN not in sys.path:
    sys.path.append(PULLDOWN)


def _fail(stage, err):
    text = u"Isolate Service Settings failed while {0}.\n\n{1}".format(
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
        TaskDialog.Show(u"RevoBIM Isolate Service Settings", text)
    except Exception:
        pass


try:
    STAGE = u"referencing assemblies"
    import ist_clr  # noqa: F401

    STAGE = u"loading modules"
    import ist_settings

    STAGE = u"reading the document"
    uiapp = __revit__  # noqa: F821  - pyRevit provides it
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        raise Exception(u"No document is open.")

    STAGE = u"showing the window"
    window = ist_settings.SettingsWindow(uiapp, uidoc.Document)
    wants_shortcuts = window.show()

    if wants_shortcuts:
        STAGE = u"opening Keyboard Shortcuts"
        from Autodesk.Revit.UI import PostableCommand, RevitCommandId
        command_id = RevitCommandId.LookupPostableCommandId(
            PostableCommand.KeyboardShortcuts)
        if command_id is not None:
            uiapp.PostCommand(command_id)

except Exception as _err:
    _fail(STAGE, _err)
