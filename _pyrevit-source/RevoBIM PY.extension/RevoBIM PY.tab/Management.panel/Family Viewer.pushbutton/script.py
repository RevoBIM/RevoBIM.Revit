# -*- coding: utf-8 -*-
"""RevoBIM Family Viewer.

Every family and type in the project in one list, grouped family then type,
with the family image, a live element count, any project parameter you like as
a column, and Select all instances across the project or the active view.

The script loads in STAGES and reports which stage failed.  A blank white
pyRevit window means the script died before any of it ran - there is no
traceback to read because there was no runtime to raise one - so each stage
sits in its own try/except that raises a Revit TaskDialog with the traceback
and writes the same text to %APPDATA%\\RevoBIM\\family_viewer_last_error.txt.
"""

__title__ = "Family Viewer"
__author__ = "RevoBIM PY"
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

PARKED = 'RevoBIM.FamilyViewer.live'

_stage = 'starting'


def _shout(stage, text):
    """Fail loudly.  A silent exception is the worst outcome."""
    try:
        import fv_core
        fv_core.write_error(stage, text)
        where = fv_core.error_path()
    except Exception:
        where = '%APPDATA%\\RevoBIM\\'
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog('RevoBIM Family Viewer')
        dialog.MainInstruction = 'Family Viewer stopped while ' + stage + '.'
        dialog.MainContent = text
        dialog.FooterText = 'The same text is in ' + str(where)
        dialog.Show()
    except Exception:
        pass


def _build(uiapp, handler, event, settings, host, pane, fv_window, fv_dock,
           fv_core):
    """Build the tool onto one host or the other, and park it.

    Both hosts run exactly the same body, so moving between them is building it
    again on the other one rather than two code paths that can drift apart.
    """
    from System import AppDomain

    view = fv_window.FamilyViewerWindow(uiapp, handler, event, settings,
                                        dock_host=host)
    # parked so the persistent engine cannot collect the window, the handler or
    # the ExternalEvent out from under the user
    AppDomain.CurrentDomain.SetData(PARKED, view)
    view.handler_ref = handler
    view.event_ref = event

    if host is None and pane is not None:
        # floating, but there IS a pane to move into
        def move_to_pane():
            settings['open_in'] = 'pane'
            fv_core.save_settings(settings)
            moved = _build(uiapp, handler, event, settings, fv_dock.host(),
                           pane, fv_window, fv_dock, fv_core)
            try:
                pane.Show()
            except Exception:
                pass
            try:
                view.window.Close()
            except Exception:
                pass
            return moved
        view.on_move_to_pane = move_to_pane

    view.show()
    return view


def main():
    global _stage

    # ---- stage 1: assemblies -------------------------------------------
    _stage = 'referencing the .NET assemblies'
    try:
        import fv_clr
    except Exception:
        _shout(_stage, traceback.format_exc())
        return

    # ---- stage 2: modules ----------------------------------------------
    _stage = 'loading its own modules'
    try:
        import fv_core
        import theme
        import fv_ui
        import fv_model
        import fv_grid
        import fv_ops
        import fv_dock
        import fv_window
    except Exception:
        _shout(_stage, traceback.format_exc())
        return

    # ---- stage 3: the project ------------------------------------------
    _stage = 'reading the project'
    try:
        from System import AppDomain

        uiapp = __revit__                                   # noqa: F821
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None or uidoc.Document is None:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show('RevoBIM Family Viewer',
                            'Open a project first - there is nothing to list.')
            return
        if uidoc.Document.IsFamilyDocument:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show(
                'RevoBIM Family Viewer',
                'This is a family document. Family Viewer lists the families '
                'in a project, so open a project and run it again.')
            return

        domain = AppDomain.CurrentDomain
        live = None
        try:
            live = domain.GetData(PARKED)
        except Exception:
            live = None
        if live is not None:
            try:
                if not live.closed:
                    # already open: bring it to the front rather than opening a
                    # second one on the same document
                    if live.docked:
                        pane = fv_dock.pane(uiapp)
                        if pane is not None:
                            pane.Show()
                            return
                    else:
                        # already open and possibly behind Revit: bring it back
                        # rather than opening a second one
                        try:
                            live.chrome.bring_to_front()
                        except Exception:
                            live.window.Activate()
                        return
            except Exception:
                pass
            try:
                domain.SetData(PARKED, None)
            except Exception:
                pass

        settings = fv_core.load_settings()
    except Exception:
        _shout(_stage, traceback.format_exc())
        return

    # ---- stage 4: the window, or Revit's own dockable pane ---------------
    _stage = 'building the window'
    try:
        handler, event = fv_ops.build()

        # The pane is registered by startup.py at the root of the extension,
        # because RegisterDockablePane can only be called while Revit is
        # starting up.  Where that has not run - a fresh install before a
        # restart, or an extension that kept its own startup.py - the tool
        # falls back to the floating window, which is a complete tool in its
        # own right rather than a degraded one.
        pane = None
        host = None
        try:
            pane = fv_dock.pane(uiapp)
            if pane is not None:
                host = fv_dock.host()
            if host is None:
                pane = None
        except Exception:
            fv_core.log('dockable pane unavailable:\n' + fv_core.format_exc())
            pane = None
            host = None

        wanted = settings.get('open_in', 'pane')
        use_pane = pane is not None and wanted != 'window'

        view = _build(uiapp, handler, event, settings,
                      host if use_pane else None, pane, fv_window, fv_dock,
                      fv_core)
        if use_pane:
            pane.Show()
        fv_core.log('Family Viewer ' + fv_core.__version__ + ' opened ' +
                    ('docked' if use_pane else 'floating') + ' on ' +
                    str(getattr(uidoc.Document, 'Title', '')))
    except Exception:
        _shout(_stage, traceback.format_exc())
        return


try:
    main()
except Exception:
    _shout(_stage, traceback.format_exc())
