# -*- coding: utf-8 -*-
u"""Project Browser Pro - the ExternalEvent every Revit call goes through.

A dockable pane or a modeless window cannot touch the document directly, so
each Revit call is queued here as a job and run in Revit's API context.

Rules learned the hard way on other tools, all kept here:
  * never wait for the event from the thread that raised it - Revit runs it
    on that same thread, so waiting is a deadlock; the result comes back
    through a callback on the dispatcher instead
  * check what Raise() answers. Pending means an earlier request is still
    waiting: queue behind it. Never clear the whole queue on a refusal -
    that lost a callback once and left a window busy for ever; remove only
    the refused job
  * a watchdog: if nothing has run 20 s after a raise, raise again and log it
  * ExternalEvent.Create only works in API context, so ensure_event() is
    called from the command, or from the Idling event for the panes
"""
import time

import pbp_clr  # noqa: F401
from System import Action
from System.Windows.Threading import Dispatcher
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import pbp_log
from pbp_compat import to_text, on_path

WATCHDOG_SECONDS = 20.0
ACCEPTED = (u'Accepted', u'Pending')


class Runner(IExternalEventHandler):

    def __init__(self):
        self.jobs = []
        self.event = None
        self.dispatcher = None
        self.raised_at = 0.0
        self.done_count = 0
        self.refused = 0

    # ---- IExternalEventHandler ----
    def GetName(self):
        return u'RevoBIM Project Browser Pro'

    def Execute(self, uiapp):
        self.raised_at = 0.0
        jobs = list(self.jobs)
        del self.jobs[:]
        on_path()
        for name, work, done in jobs:
            result = None
            error = None
            try:
                result = work(uiapp)
            except Exception:
                error = pbp_log.exc(u'job ' + to_text(name))
            self.done_count += 1
            if done is not None:
                self._deliver(name, done, result, error)

    # ---- plumbing ----
    def _deliver(self, name, done, result, error):
        def call():
            try:
                on_path()
                done(result, error)
            except Exception:
                pbp_log.exc(u'callback ' + to_text(name))
        try:
            if self.dispatcher is not None:
                self.dispatcher.BeginInvoke(Action(call))
                return
        except Exception:
            pbp_log.exc(u'deliver ' + to_text(name))
        call()

    def ensure_event(self):
        u"""Create the event. Only works in API context - see the module doc."""
        if self.event is None:
            try:
                self.event = ExternalEvent.Create(self)
                self.dispatcher = Dispatcher.CurrentDispatcher
                pbp_log.log(u'runner: external event created')
            except Exception:
                pbp_log.exc(u'runner: ExternalEvent.Create')
        return self.event is not None

    def ready(self):
        return self.event is not None

    def _raise(self):
        try:
            return to_text(self.event.Raise())
        except Exception:
            pbp_log.exc(u'runner: Raise')
            return u'error'

    def queue(self, name, work, done=None):
        u"""Queue a job; True when Revit has it (now or behind another)."""
        if self.event is None:
            pbp_log.log(u'runner: no event yet, dropped ' + to_text(name))
            return False
        job = (name, work, done)
        self.jobs.append(job)
        answer = self._raise()
        if answer in ACCEPTED:
            if not self.raised_at:
                self.raised_at = time.time()
            return True
        if job in self.jobs:
            self.jobs.remove(job)
        self.refused += 1
        pbp_log.log(u'runner: Revit answered {0} for {1}'.format(answer, to_text(name)))
        return False

    def stalled(self, now=None):
        now = time.time() if now is None else now
        return bool(self.raised_at) and (now - self.raised_at) > WATCHDOG_SECONDS

    def kick(self):
        pbp_log.log(u'runner: watchdog - nothing ran for {0:.0f}s, raising again ({1} queued)'.format(
            float(WATCHDOG_SECONDS), len(self.jobs)))
        self.raised_at = 0.0
        if self.jobs and self.event is not None:
            if self._raise() in ACCEPTED:
                self.raised_at = time.time()

    def busy(self):
        return bool(self.jobs)

    def describe(self):
        return u'event={0} queued={1} done={2} refused={3} raised_at={4:.0f}'.format(
            self.event is not None, len(self.jobs), self.done_count, self.refused,
            float(self.raised_at))


_RUNNER = [None]


def get():
    u"""This engine's runner. Each pyRevit engine has its own copy of this
    module, so the panes (startup engine) and the floating window (command
    engine) each have one."""
    if _RUNNER[0] is None:
        _RUNNER[0] = Runner()
    return _RUNNER[0]
