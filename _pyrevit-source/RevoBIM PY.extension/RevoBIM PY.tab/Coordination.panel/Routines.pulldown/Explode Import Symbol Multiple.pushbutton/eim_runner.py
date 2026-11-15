# -*- coding: utf-8 -*-
"""Drives the explode, one import at a time, from Revit's Idling event.

Why Idling: the ribbon only offers Explode once Revit has redrawn it for a
single selected import, and a ribbon command only runs after API code has
returned. Each idle tick does one small step (select, press, check) and
hands control back. The engine is persistent (script.py) so the handlers
outlive the command.

Every handler is held as one delegate object so exactly that delegate comes
off again - an IronPython bound method makes a fresh delegate each time.
"""
import time

import eim_clr  # noqa: F401  (assembly references first)
from System import EventHandler, AppDomain
from System.Collections.Generic import List
from Autodesk.Revit.DB import ElementId, Transaction, ImportInstance, ElementType
from Autodesk.Revit.UI.Events import IdlingEventArgs, DialogBoxShowingEventArgs
from Autodesk.Revit.DB.Events import DocumentChangedEventArgs

import eim_core
import eim_ribbon
from eim_version import __version__

BUSY_KEY = u'RevoBIM.ExplodeImportMultiple.busy'
BUSY_STALE = 600.0
TICK_SECONDS = 0.12


def busy_since():
    try:
        value = AppDomain.CurrentDomain.GetData(BUSY_KEY)
        if value is None:
            return None
        started = float(str(value))
        if time.time() - started > BUSY_STALE:
            return None
        return started
    except Exception:
        return None


def _set_busy(on):
    try:
        AppDomain.CurrentDomain.SetData(BUSY_KEY, str(time.time()) if on else None)
    except Exception:
        pass


class ExplodeRun(object):

    def __init__(self, uiapp, doc, id_by_key, cls, mode, settings, log, on_report):
        self.uiapp = uiapp
        self.doc = doc
        self.id_by_key = id_by_key          # int key -> ElementId, held as-is
        self.cls = cls
        self.mode = mode
        self.settings = settings
        self.log = log
        self.on_report = on_report          # callable(title, lines) for a themed report
        self.plan = eim_core.ExplodePlan(cls['explode'])
        self.unpinned = []
        self.added = []
        self.added_by_key = {}
        self.dialogs = []
        self.started = None
        self.last_tick = 0.0
        self.finished = False
        self._found = (u'missing', None, None)
        self._idling = None
        self._changed = None
        self._dialog = None

    # ======================================================================
    # Start / finish
    # ======================================================================

    def start(self):
        self.started = time.time()
        _set_busy(True)
        self.log(u'run: {0} explode of {1} import(s), Revit {2}'.format(
            self.mode, len(self.plan.keys), self._revit_version()))
        self._unpin()
        try:
            self._idling = EventHandler[IdlingEventArgs](self._on_idling)
            self.uiapp.Idling += self._idling
            self._changed = EventHandler[DocumentChangedEventArgs](self._on_changed)
            self.uiapp.Application.DocumentChanged += self._changed
            if self.settings.get(u'suppress_dialogs') == u'1':
                self._dialog = EventHandler[DialogBoxShowingEventArgs](self._on_dialog)
                self.uiapp.DialogBoxShowing += self._dialog
        except Exception as ex:
            self.log(u'run: could not hook events {0}'.format(ex))
            self._finish(u'Could not start: {0}'.format(ex))

    def _revit_version(self):
        try:
            return self.uiapp.Application.VersionNumber
        except Exception:
            return u'?'

    def _unhook(self):
        for event_owner, attr, handler in (
                (self.uiapp, 'Idling', self._idling),
                (self._application(), 'DocumentChanged', self._changed),
                (self.uiapp, 'DialogBoxShowing', self._dialog)):
            if handler is None or event_owner is None:
                continue
            try:
                if attr == 'Idling':
                    event_owner.Idling -= handler
                elif attr == 'DocumentChanged':
                    event_owner.DocumentChanged -= handler
                else:
                    event_owner.DialogBoxShowing -= handler
            except Exception as ex:
                self.log(u'run: unhook {0} failed {1}'.format(attr, ex))
        self._idling = self._changed = self._dialog = None

    def _application(self):
        try:
            return self.uiapp.Application
        except Exception:
            return None

    def _finish(self, abort_reason=None):
        if self.finished:
            return
        self.finished = True
        self._unhook()
        _set_busy(False)
        extra = []
        if abort_reason:
            extra.append(u'Stopped early: {0}'.format(abort_reason))
            done = set([r[0] for r in self.plan.results])
            for key in self.plan.keys:
                if key not in done:
                    self.plan.results.append((key, u'failed', u'not reached - ' + abort_reason))
        self._repin_failures()
        self._select_results()
        ok, failed, gone = self.plan.counts()
        self.log(u'run: finished ok={0} failed={1} gone={2} in {3:.1f}s, {4} new elements'.format(
            ok, failed, gone, time.time() - (self.started or time.time()), len(self.added)))
        if self.dialogs:
            extra.append(u'Revit dialogs answered automatically: {0}'.format(u', '.join(self.dialogs)))
        if failed:
            lines = eim_core.report_lines(self.plan.results, self.cls['names'], self.mode, extra)
            if self.settings.get(u'debug') == u'1':
                lines.append(u'')
                lines.append(u'Debug log: %APPDATA%\\RevoBIM\\explode_import_multiple_debug.txt')
            try:
                self.on_report(u'{0} could not be exploded'.format(
                    eim_core.plural(failed, u'import symbol')), lines)
            except Exception as ex:
                self.log(u'run: report window failed {0}'.format(ex))

    # ======================================================================
    # Model writes (Idling and the command are both valid API contexts)
    # ======================================================================

    def _unpin(self):
        keys = self.cls.get('pinned') or []
        if not keys:
            return
        t = Transaction(self.doc, u'RevoBIM - Unpin imports to explode')
        try:
            t.Start()
            for key in keys:
                el = self.doc.GetElement(self.id_by_key[key])
                if el is not None and el.Pinned:
                    el.Pinned = False
                    self.unpinned.append(key)
            t.Commit()
            self.log(u'run: unpinned {0}'.format(len(self.unpinned)))
        except Exception as ex:
            self.unpinned = []
            self.log(u'run: unpin failed {0}'.format(ex))
            try:
                t.RollBack()
            except Exception:
                pass

    def _repin_failures(self):
        failed = set([r[0] for r in self.plan.results if r[1] == u'failed'])
        keys = [k for k in self.unpinned if k in failed]
        if not keys:
            return
        t = Transaction(self.doc, u'RevoBIM - Re-pin imports not exploded')
        try:
            t.Start()
            for key in keys:
                el = self.doc.GetElement(self.id_by_key[key])
                if el is not None:
                    el.Pinned = True
            t.Commit()
            self.log(u'run: re-pinned {0} not exploded'.format(len(keys)))
        except Exception as ex:
            self.log(u'run: re-pin failed {0}'.format(ex))
            try:
                t.RollBack()
            except Exception:
                pass

    def _select_results(self):
        uidoc = self.uiapp.ActiveUIDocument
        if uidoc is None:
            return
        failed_ids = [self.id_by_key[r[0]] for r in self.plan.results
                      if r[1] == u'failed' and self._exists(r[0])]
        keep = []
        if self.settings.get(u'select_results') == u'1':
            for eid in self.added:
                el = self.doc.GetElement(eid)
                if el is None or isinstance(el, ElementType):
                    continue
                try:
                    if el.Category is None:
                        continue
                    if el.ViewSpecific or isinstance(el, ImportInstance) or el.Location is not None:
                        keep.append(eid)
                except Exception:
                    continue
        chosen = keep + failed_ids
        try:
            uidoc.Selection.SetElementIds(List[ElementId](chosen))
            self.log(u'run: selected {0} result(s) and {1} not exploded'.format(len(keep), len(failed_ids)))
        except Exception as ex:
            self.log(u'run: could not select results {0}'.format(ex))
            try:
                uidoc.Selection.SetElementIds(List[ElementId](failed_ids))
            except Exception:
                pass

    # ======================================================================
    # Events
    # ======================================================================

    def _exists(self, key):
        try:
            el = self.doc.GetElement(self.id_by_key[key])
            return el is not None and el.IsValidObject
        except Exception:
            return False

    def _on_changed(self, sender, args):
        try:
            if args.GetDocument().Equals(self.doc):
                added = list(args.GetAddedElementIds())
                self.added.extend(added)
                key = self.plan.current()
                if key is not None:
                    self.added_by_key[key] = self.added_by_key.get(key, 0) + len(added)
        except Exception as ex:
            self.log(u'changed: {0}'.format(ex))

    def _on_dialog(self, sender, args):
        try:
            if self.finished:
                return
            dialog_id = u'{0}'.format(getattr(args, 'DialogId', u'') or u'(no id)')
            self.dialogs.append(dialog_id)
            self.log(u'dialog: answered OK to {0}'.format(dialog_id))
            args.OverrideResult(1)
        except Exception as ex:
            self.log(u'dialog: {0}'.format(ex))

    def _on_idling(self, sender, args):
        try:
            args.SetRaiseWithoutDelay()
        except Exception:
            pass
        if self.finished:
            return
        try:
            self._tick()
        except Exception as ex:
            self.log(u'idling: {0}'.format(ex))
            self._finish(u'an error in the run ({0})'.format(ex))

    def _tick(self):
        now = time.time()
        if now - self.last_tick < TICK_SECONDS:
            return
        self.last_tick = now

        uidoc = self.uiapp.ActiveUIDocument
        if uidoc is None or not uidoc.Document.Equals(self.doc):
            self._finish(u'the active model changed')
            return
        if now - self.started > eim_core.run_timeout(len(self.plan.keys)):
            self._finish(u'it ran out of time')
            return

        key = self.plan.current()
        exists = self._exists(key) if key is not None else False
        button = u'missing'
        if key is not None and self.plan.state == u'find':
            self._found = eim_ribbon.find(self.mode)
            button = self._found[0]

        before = len(self.plan.results)
        action, act_key = self.plan.tick(now, exists, button)
        if len(self.plan.results) > before:
            r = self.plan.results[-1]
            self.log(u'item {0}: {1} - {2} ({3} new elements)'.format(
                r[0], r[1], r[2], self.added_by_key.get(r[0], 0)))

        if action == u'finished':
            self._finish()
        elif action == u'select':
            uidoc.Selection.SetElementIds(List[ElementId]([self.id_by_key[act_key]]))
            self.log(u'item {0}: selected alone (attempt {1})'.format(act_key, self.plan.attempts + 1))
        elif action == u'invoke':
            route = eim_ribbon.invoke(self._found[1], self._found[2], self.log)
            if route is None:
                self.log(u'item {0}: no ribbon handler, trying UI Automation'.format(act_key))
                self.plan.route = u'uia'
                eim_ribbon.invoke_uia_async(self.mode, self.uiapp.MainWindowHandle, self.log)
            else:
                self.plan.route = route
        elif action == u'invoke_uia':
            self.log(u'item {0}: ribbon item not found, trying UI Automation'.format(act_key))
            eim_ribbon.invoke_uia_async(self.mode, self.uiapp.MainWindowHandle, self.log)
