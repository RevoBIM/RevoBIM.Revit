# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : modeless plumbing.

A modeless window cannot start a transaction directly - every write has to
go out through an ExternalEvent, and the window itself has to be parked in
storage that survives the command returning, or the persistent engine
collects it out from under the user.
"""

import fm_clr  # noqa  - must be first

import traceback

from System import AppDomain
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

from fm_core import VERSION

# version stamped, so an upgrade cannot pick up a stale handler from the
# previous build still sitting in the AppDomain
_WINDOW_KEY = "RevoBIM.FilterManager.Window." + VERSION


class ActionHandler(IExternalEventHandler):
    """Runs whatever the window queued, on Revit's own thread."""

    def __init__(self):
        self._queue = []
        self.on_error = None

    def enqueue(self, fn):
        self._queue.append(fn)

    def Execute(self, uiapp):
        while self._queue:
            fn = self._queue.pop(0)
            try:
                fn(uiapp)
            except Exception:
                if self.on_error is not None:
                    try:
                        self.on_error(traceback.format_exc())
                    except Exception:
                        pass

    def GetName(self):
        return "RevoBIM Filter Manager"


class Runner(object):
    """Hands a callable to Revit and asks for it to be run.

    The ExternalEvent is created on first use rather than when the window is
    built, so opening the tool cannot fail on it and a failure to create it
    is reported against an action the user actually took.
    """

    def __init__(self, direct=False):
        self.handler = ActionHandler()
        self.direct = direct
        self.event = None
        self.create_error = None
        self.on_refused = None

        # Created here, while the command is still running and Revit is in a
        # valid API context. Creating it later from a button click - which is
        # a plain WPF callback with no API context - is not reliable, and a
        # raised event that was never created means the write silently never
        # happens.
        if not direct:
            try:
                self.event = ExternalEvent.Create(self.handler)
            except Exception:
                self.create_error = traceback.format_exc()
                self.direct = True

    def run(self, fn):
        """Hand the work to Revit, and check that Revit took it.

        Raise() returns a status. A refused request queues nothing and
        raises nothing, so the write simply never happens and the tool has
        no idea - which looks exactly like a button that does nothing.
        """
        self.handler.enqueue(fn)

        if self.direct or self.event is None:
            self.handler.Execute(None)
            return "Direct"

        try:
            request = self.event.Raise()
        except Exception:
            request = None

        accepted = request is None or "Accept" in str(request)
        if accepted:
            return str(request)

        # Revit would not take it. Rather than lose the work quietly, run it
        # here and let the transaction itself report if the context is wrong.
        try:
            self.handler.Execute(None)
        except Exception:
            pass
        if self.on_refused is not None:
            try:
                self.on_refused(str(request))
            except Exception:
                pass
        return str(request)

    def set_error_reporter(self, fn):
        self.handler.on_error = fn


# ---------------------------------------------------------------------------
#  Parking the window
# ---------------------------------------------------------------------------
def park(window):
    try:
        AppDomain.CurrentDomain.SetData(_WINDOW_KEY, window)
    except Exception:
        pass


def parked():
    try:
        return AppDomain.CurrentDomain.GetData(_WINDOW_KEY)
    except Exception:
        return None


def unpark():
    try:
        AppDomain.CurrentDomain.SetData(_WINDOW_KEY, None)
    except Exception:
        pass


def own_to_revit(window, uiapp):
    """Own the window to Revit's main window handle.

    An unowned modeless window slips behind Revit and reads as a crash.
    """
    try:
        from System.Windows.Interop import WindowInteropHelper
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
        return True
    except Exception:
        return False
