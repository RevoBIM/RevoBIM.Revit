# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer

Modeless window, so Revit stays navigable while it is open. Every write
goes out through an ExternalEvent, so the handler and window are both
parked in AppDomain under a version-stamped key - otherwise the persistent
engine can collect the window out from under the user, or a stale handler
from an earlier load of this tool gets reused.

Loads in stages and reports which stage failed, into a Revit TaskDialog
and into %APPDATA%\\RevoBIM\\fpc_last_error.txt - a blank white pyRevit
window means the script died before any of it ran, and this is how that
stops being a guessing game.
"""
__persistentengine__ = True

import os
import sys
import traceback

THIS_DIR = os.path.dirname(__file__)
if THIS_DIR not in sys.path:
    sys.path.append(THIS_DIR)

ERROR_LOG = os.path.join(os.environ.get('APPDATA', THIS_DIR), 'RevoBIM', 'fpc_last_error.txt')


def _fail(stage, ex):
    message = u'Family Parameter Changer failed at stage: {0}\n\n{1}'.format(stage, traceback.format_exc())
    try:
        folder = os.path.dirname(ERROR_LOG)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        f = open(ERROR_LOG, 'w')
        try:
            f.write(message)
        finally:
            f.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u'RevoBIM PY - Family Parameter Changer', message)
    except Exception:
        pass


try:
    import fpc_clr  # noqa - assemblies referenced first
except Exception as ex:
    _fail('assemblies', ex)
    raise

try:
    import fpc_core
    import fpc_model
    import fpc_ops
    import fpc_ui
except Exception as ex:
    _fail('modules', ex)
    raise

try:
    try:
        from pyrevit import revit
        doc = revit.doc
        uiapp = revit.uiapp
    except Exception:
        doc = __revit__.ActiveUIDocument.Document
        uiapp = __revit__
except Exception as ex:
    _fail('reaching the active document', ex)
    raise

try:
    families = fpc_model.scan_families(doc)
except Exception as ex:
    _fail('reading the project', ex)
    raise

try:
    import System
    from Autodesk.Revit.UI import ExternalEvent

    APP_DOMAIN_HANDLER_KEY = u'RevoBIM_FPC_Handler_{0}'.format(fpc_core.__version__)
    APP_DOMAIN_WINDOW_KEY = u'RevoBIM_FPC_Window'

    handler = System.AppDomain.CurrentDomain.GetData(APP_DOMAIN_HANDLER_KEY)
    if handler is None:
        handler = fpc_ops.RebindHandler()
        System.AppDomain.CurrentDomain.SetData(APP_DOMAIN_HANDLER_KEY, handler)

    ext_event = ExternalEvent.Create(handler)

    window = fpc_ui.build_window(THIS_DIR, families, doc, handler, ext_event, uiapp)
    System.AppDomain.CurrentDomain.SetData(APP_DOMAIN_WINDOW_KEY, window)
    window.Show()
except Exception as ex:
    _fail('showing the window', ex)
    raise
