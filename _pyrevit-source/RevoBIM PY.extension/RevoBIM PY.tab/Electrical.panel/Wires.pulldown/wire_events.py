# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: the external event behind a modeless Shuffle.

A modal window shown from inside a command is still in the command's API
context, so its buttons can open transactions directly. A modeless one is
not: the command has returned, Revit is back at idle, and any transaction has
to be opened from inside an ExternalEvent instead. That is the whole reason
this module exists, and the reason both drawing commands set
__persistentengine__ - without it pyRevit tears the engine down the moment the
command returns and takes the window's handlers with it.
"""

import clr

for _asm in ('RevitAPI', 'RevitAPIUI'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent


class WireEventHandler(IExternalEventHandler):
    """Runs one piece of work inside Revit's API context, then forgets it."""

    def __init__(self):
        self.action = None
        self.after = None
        self.error = None

    def Execute(self, uiapp):
        work = self.action
        self.action = None
        if work is None:
            return
        try:
            self.error = None
            work(uiapp)
        except Exception as error:
            self.error = error
        try:
            if self.after is not None:
                self.after()
        except Exception:
            pass

    def GetName(self):
        return 'RevoBIM Wires'


class EventBridge(object):
    """Hands work to Revit and tells the window when it is done.

    Nothing is queued: a second request while one is in flight is dropped, so
    a repeat button held down cannot stack up transactions.
    """

    def __init__(self):
        self.handler = WireEventHandler()
        self.event = ExternalEvent.Create(self.handler)
        self.busy = False

    def run(self, work, after=None):
        if self.busy:
            return False
        self.busy = True

        def _finish():
            self.busy = False
            if after is not None:
                after()

        self.handler.action = work
        self.handler.after = _finish
        try:
            self.event.Raise()
        except Exception:
            self.busy = False
            return False
        return True
