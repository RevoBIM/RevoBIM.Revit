# -*- coding: utf-8 -*-
"""RevoBIM PY - Callout to 3D.

Loads in stages and says which stage failed, because a script that dies at
module load shows as a blank white pyRevit window with no traceback in it.
"""

# the window is modeless, so pyRevit must not tear the engine down when the
# command returns
__persistentengine__ = True

__title__ = "Callout to 3D"
__doc__ = ("Create a 3D and a section array from a callout and lay them out "
           "on a new sheet.")

import os
import sys
import traceback

STAGE = "start"


def _folder():
    # one button now: the modules sit beside this script
    return os.path.dirname(os.path.abspath(__file__))


def _report(stage, error):
    text = u"Callout to 3D could not start.\n\nStage: {0}\n\n{1}".format(stage, error)
    try:
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, "callout_to_3d_last_error.txt"), "w")
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog("RevoBIM Callout to 3D")
        dialog.MainInstruction = u"Could not start - stage: {0}".format(stage)
        dialog.MainContent = u"{0}".format(error)[:2000]
        dialog.Show()
    except Exception:
        pass


try:
    STAGE = "path"
    parent = _folder()
    if parent not in sys.path:
        sys.path.insert(0, parent)

    STAGE = "assemblies"
    import c3d_clr
    if c3d_clr.FAILED:
        raise ImportError(c3d_clr.report())

    STAGE = "modules"
    import c3d_core as core
    import c3d_ops as ops
    import c3d_window

    STAGE = "the project"
    uidoc = __revit__.ActiveUIDocument                       # noqa: F821
    if uidoc is None or uidoc.Document is None:
        raise Exception("no document is open")
    doc = uidoc.Document
    if doc.IsFamilyDocument:
        raise Exception("this tool runs in a project, not in the family editor")

    STAGE = "the external events"
    from Autodesk.Revit.UI import ExternalEvent
    from System import AppDomain

    # a versioned key, so upgrading the tool inside a Revit session cannot
    # leave a stale handler from the previous version behind
    KEY = "RevoBIM.CalloutTo3D.{0}".format(core.__version__)
    store = AppDomain.CurrentDomain.GetData(KEY)
    if store is None:
        run_handler = ops.RunHandler()
        open_handler = ops.OpenViewHandler()
        store = {
            "run_handler": run_handler,
            "open_handler": open_handler,
            # ExternalEvent.Create has to be called from the command context,
            # never from a WPF button click
            "run_event": ExternalEvent.Create(run_handler),
            "open_event": ExternalEvent.Create(open_handler),
            "window": None,
        }
        AppDomain.CurrentDomain.SetData(KEY, store)

    STAGE = "the window"
    existing = store.get("window")
    if existing is not None:
        try:
            existing.window.Activate()
            raise SystemExit
        except SystemExit:
            raise
        except Exception:
            store["window"] = None

    tool = c3d_window.CalloutWindow(uidoc,
                                    store["run_event"], store["run_handler"],
                                    store["open_event"], store["open_handler"])

    def _forget(sender, args):
        store["window"] = None

    tool.window.Closed += _forget
    store["window"] = tool
    tool.show(__revit__)                                      # noqa: F821
    core.log("opened v{0}".format(core.__version__))

except SystemExit:
    pass
except Exception as _error:
    _report(STAGE, traceback.format_exc())
