# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : the ExternalEvent queue.

The window is modeless so Revit stays usable, which means nothing in it may
touch the model directly: every read and write is a job handed to Revit
through one ExternalEvent and run when Revit is ready.

Rules this follows, each learnt the hard way in another tool:
- never wait for the event from the window that raised it - Revit runs it on
  the same thread, so waiting is a deadlock.  Queue, return, and hand the
  result back on the window's dispatcher;
- read Raise()'s answer.  Accepted: Revit will call us.  Pending: an earlier
  request is still waiting, and this job is simply queued behind it - the
  queue must NOT be cleared, or the earlier job's callback is lost and the
  window stays busy for ever.  Denied or TimedOut: drop this job only, and
  say so;
- a watchdog frees a window whose request Revit never picked up (Revit in a
  modal dialog or edit mode), so it can never be left unclickable;
- direct mode runs jobs at once, for the dialog fallback, where the command
  is still running and the API is available.
"""

import time
import traceback

import wsm_clr  # noqa: F401  (assemblies first)

from System import Action                                     # noqa: E402
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler  # noqa: E402

import wsm_core as core                                       # noqa: E402

WATCHDOG_SECONDS = 30.0


class Job(object):
    def __init__(self, label, work, done):
        self.label = label
        self.work = work        # work(uiapp) -> result, in API context
        self.done = done        # done(result, error), on the window's thread
        self.raised_at = time.time()


class Runner(IExternalEventHandler):

    def __init__(self):
        self.jobs = []
        self.event = None
        self.direct = False
        self.uiapp = None
        self.dispatcher = None
        self.running = False
        self.log = []

    # ---------------------------------------------------------- set up

    def setup(self, uiapp, dispatcher, direct=False):
        """Call from the command, in API context: ExternalEvent.Create must
        run there."""
        self.uiapp = uiapp
        self.dispatcher = dispatcher
        self.direct = bool(direct)
        if not self.direct:
            self.event = ExternalEvent.Create(self)

    def GetName(self):
        return u"RevoBIM PY - Workset Management"

    # ---------------------------------------------------------- queueing

    def busy(self):
        return bool(self.jobs) or self.running

    def queued(self, label):
        return any(job.label == label for job in self.jobs)

    def submit(self, label, work, done):
        """-> (True, '') when the job will run, (False, why) when it will not."""
        job = Job(label, work, done)
        if self.direct:
            self.run_job(job, self.uiapp)
            return True, u""
        self.jobs.append(job)
        try:
            status = core.to_text(self.event.Raise().ToString())
        except Exception as err:
            status = u"failed: {0}".format(err)
        self.log.append(u"{0}: Raise -> {1} ({2} queued)".format(label, status, len(self.jobs)))
        if status in ("Accepted", "Pending"):
            return True, u""
        if job in self.jobs:
            self.jobs.remove(job)
        return False, (u"Revit would not take the request ({0}) - finish what you are "
                       u"doing in Revit, then try again.".format(status))

    def watchdog(self):
        """-> labels of jobs dropped because Revit never picked them up."""
        if self.running or not self.jobs:
            return []
        oldest = min(job.raised_at for job in self.jobs)
        if time.time() - oldest < WATCHDOG_SECONDS:
            return []
        dropped = [job.label for job in self.jobs]
        self.jobs = []
        self.log.append(u"watchdog dropped: {0}".format(u", ".join(dropped)))
        return dropped

    # ---------------------------------------------------------- running

    def Execute(self, uiapp):
        """Revit calls this when it is ready.  Every queued job runs, in order;
        nothing may escape, or Revit puts up an error of its own."""
        self.running = True
        try:
            while self.jobs:
                self.run_job(self.jobs.pop(0), uiapp)
        finally:
            self.running = False

    def run_job(self, job, uiapp):
        result, error = None, None
        try:
            result = job.work(uiapp)
        except Exception as err:
            error = err
            self.log.append(u"{0} failed:\n{1}".format(job.label, traceback.format_exc()))
        self.hand_back(job, result, error)

    def hand_back(self, job, result, error):
        def callback():
            try:
                job.done(result, error)
            except Exception:
                self.log.append(u"{0} callback failed:\n{1}".format(
                    job.label, traceback.format_exc()))
        if self.dispatcher is None:
            callback()
            return
        try:
            self.dispatcher.BeginInvoke(Action(callback))
        except Exception:
            callback()
