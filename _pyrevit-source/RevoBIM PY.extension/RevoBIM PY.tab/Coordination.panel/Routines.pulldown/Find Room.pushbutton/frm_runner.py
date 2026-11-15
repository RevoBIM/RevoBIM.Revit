# -*- coding: utf-8 -*-
"""Find Room - the ExternalEvent queue. Every read and write is a job.

- Raise()'s answer is read: Accepted runs; Pending queues behind the earlier
  request (the queue is NEVER cleared); Denied / TimedOut drop only that job
  and say so.
- A watchdog frees the window if Revit never picks a request up (a dialog or
  an edit mode open in Revit).
- Results come back on the window's dispatcher; the window never waits.
"""
import frm_clr  # noqa: F401 - assemblies first, always

from System import Action, TimeSpan
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import frm_core as core

WATCHDOG_SECONDS = 20


class _Handler(IExternalEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        self.runner._execute(uiapp)

    def GetName(self):
        return u"RevoBIM Find Room"


class Runner(object):
    def __init__(self, dispatcher, log=None, on_busy=None):
        self.dispatcher = dispatcher
        self.log = log or (lambda m: None)
        self.on_busy = on_busy or (lambda busy: None)
        self.queue = []
        self.busy = False
        self.handler = _Handler(self)
        self.event = ExternalEvent.Create(self.handler)
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(WATCHDOG_SECONDS)
        self.timer.Tick += self._watchdog

    def submit(self, name, work, done=None):
        """work(uiapp) runs in Revit's API context; done(result, error) runs
        back on the window's thread."""
        job = (name, work, done)
        self.queue.append(job)
        try:
            answer = core.to_text(self.event.Raise())
        except Exception as exc:
            answer = u"Error {0}".format(exc)
        if answer in (u"Accepted", u"Pending"):
            self._set_busy(True)
            self.timer.Stop()
            self.timer.Start()
            if answer == u"Pending":
                self.log(u"job {0} queued behind a pending request".format(name))
            return True
        try:
            self.queue.remove(job)
        except ValueError:
            pass
        self.log(u"job {0} refused by Revit: {1}".format(name, answer))
        self._post(done, None, u"Revit refused the request ({0}) - finish what "
                               u"is open in Revit and try again.".format(answer))
        return False

    def _execute(self, uiapp):
        jobs, self.queue = self.queue, []
        for name, work, done in jobs:
            result, error = None, None
            try:
                result = work(uiapp)
            except Exception as exc:
                error = u"{0}: {1}".format(name, exc)
                self.log(u"job failed - {0}".format(error))
            self._post(done, result, error)
        if not self.queue:
            self.timer.Stop()
            self._post_busy(False)

    def _post(self, done, result, error):
        if done is None:
            return

        def call():
            try:
                done(result, error)
            except Exception as exc:
                self.log(u"callback failed: {0}".format(exc))
        try:
            self.dispatcher.BeginInvoke(Action(call))
        except Exception:
            call()

    def _post_busy(self, busy):
        def call():
            self._set_busy(busy)
        try:
            self.dispatcher.BeginInvoke(Action(call))
        except Exception:
            call()

    def _set_busy(self, busy):
        self.busy = busy
        try:
            self.on_busy(busy)
        except Exception:
            pass

    def _watchdog(self, sender, args):
        self.timer.Stop()
        if self.busy:
            self.log(u"watchdog: Revit did not pick up {0} job(s) in {1}s".format(
                len(self.queue), WATCHDOG_SECONDS))
            self._set_busy(False)

    def dispose(self):
        try:
            self.timer.Stop()
        except Exception:
            pass
        try:
            self.event.Dispose()
        except Exception:
            pass
