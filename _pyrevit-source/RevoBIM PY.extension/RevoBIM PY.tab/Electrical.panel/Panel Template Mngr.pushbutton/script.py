# -*- coding: utf-8 -*-
"""RevoBIM Panel Template Mngr (the Panel Schedule Template Manager).

Every panel in the project in one table, with the panel schedule template it is
using and four parameter columns you choose, each heading searchable and
filterable.  Swap templates by hand or let Auto Assign work them out from the
number of ways and the number of phases.  Nothing is written until Apply.

The Template Duplicator tab shows every template with how many panels use it,
isolates the ones nothing uses, deletes or merges them, and duplicates one
template into as many fixed slot counts as you tick.

Settings live behind the gear in the tool's own header rather than as a second
ribbon button.  The window is modeless, so Revit stays fully navigable and
editable while it is open.
"""

__title__ = 'Panel Template\nMngr'
__author__ = 'RevoBIM PY'
__persistentengine__ = True

import os
import sys
import traceback

# The shared modules sit beside this script rather than in lib\revobim, so the
# tool stays self contained and nothing else in the extension is touched.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)


def report(stage, detail):
    """Say why, rather than leaving a blank white pyRevit window.

    A module that will not load takes the whole script down before any of it
    runs, and pyRevit shows an empty output window with nothing in it.  So the
    load is done in pieces and each piece reports what went wrong, into a themed
    Revit dialog and into a text file that can be sent on.
    """
    text = ('RevoBIM Panel Template Mngr could not {0}.\n\n'
            '{1}').format(stage, detail)
    try:
        import pstm_clr
        text += '\n\nAssemblies:\n' + pstm_clr.report()
    except Exception:
        pass

    saved = ''
    try:
        base = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'),
                            'RevoBIM')
        if not os.path.isdir(base):
            os.makedirs(base)
        saved = os.path.join(base, 'pstm_last_error.txt')
        handle = open(saved, 'w')
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        saved = ''
    if saved:
        text += '\n\nSaved to:\n' + saved

    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Panel Template Mngr', text)
    except Exception:
        pass


def revit_handle(uiapp):
    """The Revit main window, so the tool floats above it rather than behind."""
    try:
        return uiapp.MainWindowHandle
    except Exception:
        pass
    try:
        from System.Diagnostics import Process
        return Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        return None


def run():
    # 1. assemblies.  pyRevit does not preload WPF into every engine, and a
    #    module that reaches into System.Windows before PresentationFramework
    #    has been referenced throws ImportError at module load.
    try:
        import pstm_clr                                       # noqa: F401
    except Exception:
        report('reference the .NET assemblies it needs', traceback.format_exc())
        return

    # 2. the tool's own modules
    try:
        import pstm_core as core                              # noqa: F401
        import pstm_window as manager
    except Exception:
        report('load its modules', traceback.format_exc())
        return

    uiapp = __revit__                                  # noqa: F821
    uidoc = getattr(uiapp, 'ActiveUIDocument', None)
    if uidoc is None or uidoc.Document is None:
        report('open', 'There is no open project in Revit.')
        return
    doc = uidoc.Document

    existing = getattr(manager, 'ACTIVE', None)
    if existing is not None:
        try:
            existing.window.Activate()
            return
        except Exception:
            manager.ACTIVE = None

    # 3. build and show
    try:
        window = manager.ManagerWindow(uiapp, doc)
    except Exception:
        report('read the project', traceback.format_exc())
        return

    manager.ACTIVE = window

    def _cleared(sender, args):
        manager.ACTIVE = None

    try:
        window.window.Closed += _cleared
    except Exception:
        pass

    try:
        window.show(revit_handle(uiapp))
    except Exception:
        manager.ACTIVE = None
        report('show its window', traceback.format_exc())


run()
