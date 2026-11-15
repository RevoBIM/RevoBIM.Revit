# -*- coding: utf-8 -*-
"""Level Manager - the ExternalEvent runner every Revit read and write from
the modeless window goes through.

Never wait for the event from the window that raised it: Revit raises it on
the window's own thread. Jobs are queued, Raise() is called, and the result
comes back through a callback marshalled onto the window's dispatcher.
"""
import lvm_clr  # noqa: F401
import traceback

from System import Action, DateTime
from System.Windows.Threading import DispatcherTimer
from System import TimeSpan
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEventRequest

import lvm_core as core

to_text = core.to_text

WATCHDOG_SECONDS = 20


class JobFailed(object):
    def __init__(self, text):
        self.text = text


class Runner(IExternalEventHandler):
    """Queue of (name, job, callback). job(uiapp) runs in Revit's API context;
    callback(result) runs on the window's dispatcher afterwards."""

    def __init__(self):
        self.event = None
        self.jobs = []
        self.dispatcher = None
        self.direct = False          # modal fallback: run jobs straight away
        self.uiapp = None
        self.busy = False
        self.busy_since = None
        self.on_busy = None          # callback(bool) for the window
        self.log = lambda msg: None
        self._timer = None
        self.running = False         # True while Execute is inside a job

    # ---- IExternalEventHandler ---------------------------------------------
    def GetName(self):
        return "RevoBIM Level Manager"

    def Execute(self, uiapp):
        self.running = True
        try:
            while self.jobs:
                name, job, callback = self.jobs.pop(0)
                self._run(uiapp, name, job, callback)
        finally:
            self.running = False
            self._set_busy(False)

    # ---- queueing ----------------------------------------------------------
    def _run(self, uiapp, name, job, callback):
        try:
            result = job(uiapp)
        except Exception:
            result = JobFailed(traceback.format_exc())
            self.log(u"job '{0}' failed:\n{1}".format(name, result.text))
        self._post(callback, result)

    def _post(self, callback, result):
        if callback is None:
            return
        def deliver():
            try:
                callback(result)
            except Exception:
                self.log(u"callback failed:\n" + traceback.format_exc())
        if self.dispatcher is not None and not self.direct:
            try:
                self.dispatcher.BeginInvoke(Action(deliver))
                return
            except Exception:
                pass
        deliver()

    def submit(self, name, job, callback=None):
        """True when the job will run. A Pending answer means an earlier
        request is still waiting - queue behind it, never clear the queue."""
        if self.direct:
            self._set_busy(True)
            try:
                self._run(self.uiapp, name, job, callback)
            finally:
                self._set_busy(False)
            return True
        entry = (name, job, callback)
        self.jobs.append(entry)
        status = u""
        try:
            status = to_text(self.event.Raise())
        except Exception as ex:
            status = u"error: " + to_text(ex)
        accepted = to_text(getattr(ExternalEventRequest, "Accepted", "Accepted"))
        pending = to_text(getattr(ExternalEventRequest, "Pending", "Pending"))
        if status in (accepted, pending, u"Accepted", u"Pending"):
            self._set_busy(True)
            return True
        try:
            self.jobs.remove(entry)
        except ValueError:
            pass
        self.log(u"Raise() refused '{0}': {1}".format(name, status))
        return False

    # ---- busy flag and watchdog --------------------------------------------
    def _set_busy(self, value):
        self.busy = value
        self.busy_since = DateTime.Now if value else None
        if self.on_busy is not None:
            try:
                self.on_busy(value)
            except Exception:
                pass
        if value and not self.direct:
            self._arm_watchdog()

    def _arm_watchdog(self):
        if self._timer is None:
            self._timer = DispatcherTimer()
            self._timer.Interval = TimeSpan.FromSeconds(2)
            self._timer.Tick += self._tick
        self._timer.Start()

    def _tick(self, sender, args):
        if not self.busy:
            self._timer.Stop()
            return
        if self.busy_since is None or self.running:
            return
        waited = (DateTime.Now - self.busy_since).TotalSeconds
        if waited > WATCHDOG_SECONDS:
            # free the window; the queue is kept - a Pending request may still run
            self.log(u"watchdog freed the window after {0:.0f}s ({1} queued)".format(waited, len(self.jobs)))
            self._set_busy(False)
            self._timer.Stop()
