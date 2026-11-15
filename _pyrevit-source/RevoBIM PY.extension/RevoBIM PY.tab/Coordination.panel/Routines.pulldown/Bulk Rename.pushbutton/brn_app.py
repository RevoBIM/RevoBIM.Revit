# -*- coding: utf-8 -*-
"""Reads what is selected and opens the window, or asks for a selection."""
import brn_clr  # noqa: F401  must stay first
import brn_core as core
import brn_dialogs
import brn_main
import brn_revit

from System import AppDomain
from Autodesk.Revit.UI import ExternalEvent

NOTHING = (u'Select the views, sheets, schedules or families you want to rename '
           u'in the Project Browser first, then run Bulk Rename.')


def launch(uiapp):
    settings = core.load_settings()
    log = core.Log(settings.get('debug', '1') == '1')
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        brn_dialogs.tell(uiapp, settings, log, u'Open a model first.')
        return
    doc = uidoc.Document
    rows, left_out = brn_revit.read_selection(doc, uidoc.Selection.GetElementIds())
    log(u'selected {0}, left out {1}'.format(len(rows), left_out))
    if not rows:
        brn_dialogs.tell(uiapp, settings, log, NOTHING,
                         title=u'Nothing selected')
        return
    old = AppDomain.CurrentDomain.GetData(brn_main.APP_KEY)
    if old is not None:
        try:
            old.force_close()
        except Exception:
            pass
    runner = brn_revit.Runner(log)
    runner.attach(ExternalEvent.Create(runner))
    taken = brn_revit.read_taken(doc, rows)
    parameters = brn_revit.text_parameters(doc, rows)
    window = brn_main.BulkRenameWindow(uiapp, settings, log, doc, rows, taken,
                                       left_out, runner, parameters)
    AppDomain.CurrentDomain.SetData(brn_main.APP_KEY, window)
    window.window.Show()
