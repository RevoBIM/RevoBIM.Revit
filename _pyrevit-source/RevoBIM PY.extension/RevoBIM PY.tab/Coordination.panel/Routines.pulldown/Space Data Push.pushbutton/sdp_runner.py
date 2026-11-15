# -*- coding: utf-8 -*-
"""The ExternalEvent runner. A modeless window cannot touch the model directly,
so every read and write goes out as a job through this."""
import sdp_clr

import time

import sdp_logic as L

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler


class Runner(IExternalEventHandler):
    __namespace__ = u'RevoBIM.SpaceDataPush'

    def __init__(self):
        self.queue = L.JobQueue()
        self.job_started = None
        self.queued_at = None
        self.suppress = False
        self.dialogs = []
        self._hooked = False
        self.event = ExternalEvent.Create(self)

    def submit(self, job):
        """Queue a job and raise the event. Returns False only if Revit refused,
        and then removes just this job. 'Pending' means an earlier request is still
        waiting: the job stays queued behind it and the handler drains everything."""
        self.queue.push(job)
        try:
            answer = '%s' % (self.event.Raise(),)
        except Exception as ex:
            L.log_debug(u'ExternalEvent.Raise raised: %s' % ex)
            self.queue.discard(job)
            return False
        if answer in ('Accepted', 'Pending'):
            if self.queued_at is None:
                self.queued_at = time.time()
            return True
        L.log_debug(u'ExternalEvent.Raise answered %s' % answer)
        self.queue.discard(job)
        return False

    def Execute(self, uiapp):
        self._hook_dialogs(uiapp)
        self.queued_at = None
        for job in self.queue.drain():
            self.job_started = time.time()
            try:
                job(uiapp)
            except Exception as ex:
                L.log_debug(u'job raised: %s' % ex)
            self.job_started = None

    def GetName(self):
        return u'RevoBIM Space Data Push'

    # Revit's own dialogs are answered for the duration of a write only. The
    # handler is hooked ONCE and switched with a flag: unsubscribing an
    # IronPython bound method from a .NET event is not reliable.
    def _hook_dialogs(self, uiapp):
        if self._hooked:
            return
        try:
            uiapp.DialogBoxShowing += self._on_dialog
            self._hooked = True
        except Exception as ex:
            L.log_debug(u'could not hook DialogBoxShowing: %s' % ex)

    def _on_dialog(self, sender, args):
        if not self.suppress:
            return
        try:
            try:
                self.dialogs.append(L.to_text(args.DialogId))
            except Exception:
                pass
            args.OverrideResult(1)
        except Exception:
            pass
