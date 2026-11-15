# -*- coding: utf-8 -*-
"""Family Viewer - Revit's own dockable pane.

A real dockable pane - one that tabs in beside Project Browser and Properties,
and that Revit remembers the position of between sessions - can only be created
by calling `RegisterDockablePane` during `IExternalApplication.OnStartup`.  A
pyRevit pushbutton runs long after that, so a button alone can never make one.

pyRevit does give us that moment: `startup.py` at the root of an extension runs
at load with `__revit__` bound to the `UIControlledApplication`, which is the
same object `OnStartup` is handed.  So the registration lives there, and this
module holds everything both ends need:

    startup.py   ->  register(uicontrolled_app)
    script.py    ->  pane(uiapp)  and  host()

The pane's content has to exist at registration time, before any document is
open, so what gets registered is an EMPTY host Grid.  The button fills it in
the first time it is pressed.  The host is parked in the AppDomain rather than
passed between the two, because pyRevit runs startup.py and a pushbutton in
different engines: a .NET object crosses that line safely, an IronPython one
does not, so nothing but the Grid is shared.
"""

import fv_clr  # noqa: F401  - must be first

from System import AppDomain, Guid
from System.Windows.Controls import Grid

import fv_core

HOST_KEY = 'RevoBIM.FamilyViewer.dockhost'
PROVIDER_KEY = 'RevoBIM.FamilyViewer.dockprovider'


def pane_guid():
    return Guid(fv_core.DOCK_GUID)


def _park(key, value):
    try:
        AppDomain.CurrentDomain.SetData(key, value)
        return True
    except Exception:
        return False


def _parked(key):
    try:
        return AppDomain.CurrentDomain.GetData(key)
    except Exception:
        return None


def host(create=False):
    """The Grid the pane shows.  Created once and parked, so the button and
    the startup script are always talking about the same one."""
    found = _parked(HOST_KEY)
    if found is not None:
        return found
    if not create:
        return None
    grid = Grid()
    _park(HOST_KEY, grid)
    return grid


def register(uicontrolled_app):
    """Called from startup.py.  Returns True where the pane now exists.

    Everything is inside try/except: a tool that cannot register its pane
    should fall back to its floating window, never take pyRevit's load down
    with it.
    """
    try:
        from Autodesk.Revit.UI import (DockablePaneId, DockablePaneState,
                                       DockablePanes, DockPosition,
                                       IDockablePaneProvider)
    except Exception:
        fv_core.log('dockable pane: not registering\n' + fv_core.format_exc())
        return False

    # pyRevit runs the startup block again on every reload, while Revit keeps
    # the pane it registered earlier in the session - registering again throws
    # "Cannot register the same dockable pane ID more than once" and filled
    # the log with tracebacks that buried everything else.  Already there is
    # already done.
    try:
        from Autodesk.Revit.UI import DockablePane
        if DockablePane.PaneIsRegistered(DockablePaneId(pane_guid())):
            return True
    except Exception:
        pass

    grid = host(create=True)

    class FamilyViewerPaneProvider(IDockablePaneProvider):
        """Hands Revit the parked Grid and asks to be tabbed in behind the
        Project Browser, which is where a browser-shaped panel belongs."""

        def SetupDockablePane(self, data):
            data.FrameworkElement = grid
            try:
                state = DockablePaneState()
                state.DockPosition = DockPosition.Tabbed
                state.TabBehind = DockablePanes.BuiltInDockablePanes.ProjectBrowser
                data.InitialState = state
            except Exception:
                # a release that will not take the tabbed state still gets a
                # pane, it just opens floating
                try:
                    data.InitialState = DockablePaneState()
                    data.InitialState.DockPosition = DockPosition.Left
                except Exception:
                    pass

    provider = FamilyViewerPaneProvider()
    # parked as well as held locally: startup.py's engine goes away, and a
    # provider Revit still holds a reference to must not be collected with it
    _park(PROVIDER_KEY, provider)

    try:
        uicontrolled_app.RegisterDockablePane(
            DockablePaneId(pane_guid()), 'RevoBIM Family Viewer', provider)
    except Exception:
        fv_core.log('dockable pane: RegisterDockablePane refused\n' +
                    fv_core.format_exc())
        return False

    fv_core.log('dockable pane registered')
    return True


def pane(uiapp):
    """The registered pane, or None where startup.py never ran."""
    try:
        from Autodesk.Revit.UI import DockablePane, DockablePaneId
    except Exception:
        return None
    try:
        pane_id = DockablePaneId(pane_guid())
    except Exception:
        return None
    try:
        if not DockablePane.PaneIsRegistered(pane_id):
            return None
    except Exception:
        pass
    try:
        return uiapp.GetDockablePane(pane_id)
    except Exception:
        return None
