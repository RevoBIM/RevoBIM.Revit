# -*- coding: utf-8 -*-
"""Model Cleanup - sync, save a detached copy, then clean and purge
the copy ready to send.

This file is a thin loader. The tool lives in the modules beside it, loaded
in stages, so a failure arrives as a dialog naming the stage rather than as a
blank pyRevit window. The window is modeless; a second press of the ribbon
button brings it back rather than opening another.
"""
import os
import sys
import io
import traceback

# The window is modeless: it outlives this command and runs its Revit work
# through an ExternalEvent, so the engine has to stay alive with it.
__persistentengine__ = True

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def report(stage, text):
    folder = os.path.join(os.environ.get(u"APPDATA") or HERE, u"RevoBIM")
    path = os.path.join(folder, u"model_cleanup_last_error.txt")
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(path, u"w", encoding=u"utf-8") as handle:
            handle.write(u"Model Cleanup\nStage: {0}\n\n{1}\n".format(stage, text))
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog(u"Model Cleanup")
        dialog.MainInstruction = u"Model Cleanup stopped while {0}.".format(stage)
        dialog.MainContent = u"The full text is in\n" + path
        dialog.ExpandedContent = u"{0}".format(text)[-3000:]
        dialog.Show()
    except Exception:
        pass


def host_uiapp():
    try:
        return __revit__  # noqa: F821 - injected by pyRevit
    except NameError:
        from pyrevit import HOST_APP
        return HOST_APP.uiapp


def main():
    stage = u"loading assemblies"
    try:
        import mcu_clr  # noqa: F401
        stage = u"loading modules"
        import mcu_core
        import mcu_window
        stage = u"reading the project"
        uiapp = host_uiapp()
        if uiapp is None or uiapp.ActiveUIDocument is None:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show(u"Model Cleanup", u"Open a model first.")
            return
        if uiapp.ActiveUIDocument.Document.IsFamilyDocument:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show(u"Model Cleanup",
                            u"Model Cleanup works on project models, not families.")
            return
        stage = u"bringing back the open window"
        if mcu_window.bring_back_existing():
            return
        stage = u"building the window"
        window = mcu_window.CleanupWindow(uiapp)
        stage = u"showing the window"
        window.show()
        mcu_core.log(u"window open (modeless)")
    except Exception:
        report(stage, traceback.format_exc())


main()
