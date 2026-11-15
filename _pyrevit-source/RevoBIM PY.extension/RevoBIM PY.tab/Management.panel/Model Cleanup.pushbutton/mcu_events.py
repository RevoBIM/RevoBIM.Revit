# -*- coding: utf-8 -*-
"""Revit work from a modeless window, through one ExternalEvent.

A modeless window lives on Revit's thread but outside Revit's API context,
so nothing it does can touch the model directly. Every job goes into a queue
here; Revit calls Execute when it is free, in API context, and the queue is
drained there. The window never waits for that - it queues, returns, and the
job carries on the work when it runs.

The ExternalEvent has to be created while a command is running, so the
window makes its runner in its constructor.
"""
import traceback

import mcu_clr  # noqa: F401 - must come before any System.* / Autodesk.* import
import mcu_core as core

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent


class ApiRunner(IExternalEventHandler):
    """job(uiapp) callables run one after another in Revit's API context."""

    def __init__(self, on_error=None, name=u"Model Cleanup"):
        self.queue = []
        self.running = None
        self.on_error = on_error
        self.name = name
        self.event = ExternalEvent.Create(self)

    def GetName(self):
        return self.name

    def request(self, label, job):
        """(kept, status). kept is False only when Revit refused - then this
        job, and only this one, is taken back off the queue."""
        entry = (label, job)
        self.queue.append(entry)
        try:
            status = core.to_text(self.event.Raise())
        except Exception as error:
            status = u"Raise failed: " + core.to_text(error)
        if core.raise_kept(status):
            core.log(u"queued {0} ({1})".format(label, status))
            return True, status
        self._drop(entry)
        core.log(u"Revit refused {0} ({1})".format(label, status))
        return False, status

    def cancel(self, label=None):
        """Take waiting jobs back off the queue (all, or those with this
        label). A job already running cannot be cancelled here."""
        before = len(self.queue)
        self.queue = [e for e in self.queue if label is not None and e[0] != label]
        return before - len(self.queue)

    def waiting(self):
        return [label for label, _ in self.queue]

    def _drop(self, entry):
        for index in range(len(self.queue) - 1, -1, -1):
            if self.queue[index] is entry:
                del self.queue[index]
                return

    def Execute(self, uiapp):
        # A job may queue another (closing the window queues the clean-up of
        # the background copy); it runs in this same pass.
        while self.queue:
            label, job = self.queue.pop(0)
            self.running = label
            try:
                job(uiapp)
            except Exception:
                text = traceback.format_exc()
                core.write_error(label, text)
                if self.on_error is not None:
                    try:
                        self.on_error(label, text)
                    except Exception:
                        core.log(u"error handler failed for " + core.to_text(label))
            finally:
                self.running = None
