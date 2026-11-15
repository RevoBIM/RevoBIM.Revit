# -*- coding: utf-8 -*-
u"""RevoBIM PY - Hide Service Type : the ExternalEvent runner.

A floating window cannot write to the model where it stands - Revit only
allows it inside an API context - so every button press is a job handed to one
ExternalEvent.  The rules, learnt the hard way on other RevoBIM tools:

- Raise() is always read.  Accepted: Revit will run it.  Pending: an earlier
  request has not run yet - the job waits behind it, and the queue is NEVER
  cleared (clearing it lost the earlier job's callback and left a window busy
  for ever).  Denied / TimedOut: only that job is dropped, and the caller is
  told.
- The window never waits on Revit: same thread, so waiting is a deadlock.
- A watchdog (in the window) frees it if Revit never picks a request up - a
  dialog open, or Revit in an edit mode.
"""

import ist_clr  # noqa: F401

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

ACCEPTED = (u"Accepted", u"Pending")


class _Handler(IExternalEventHandler):

    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        self.runner.execute(uiapp)

    def GetName(self):
        return u"RevoBIM Reset Hide"


class Runner(object):

    def __init__(self, log=None):
        self.jobs = []
        self.log = log or (lambda text: None)
        self.handler = _Handler(self)
        self.event = ExternalEvent.Create(self.handler)

    def submit(self, job):
        u"""Queue `job(uiapp)`.  Returns (True, "") when Revit will run it,
        (False, why) when it will not."""
        self.jobs.append(job)
        try:
            status = u"{0}".format(self.event.Raise())
        except Exception as err:
            status = u"failed: {0}".format(err)
        if status in ACCEPTED:
            return True, u""
        try:
            self.jobs.remove(job)
        except ValueError:
            pass
        self.log(u"Raise() answered {0}; that job was dropped".format(status))
        return False, status

    def execute(self, uiapp):
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            try:
                job(uiapp)
            except Exception as err:
                self.log(u"job failed: {0}".format(err))

    def dispose(self):
        try:
            self.event.Dispose()
        except Exception:
            pass
