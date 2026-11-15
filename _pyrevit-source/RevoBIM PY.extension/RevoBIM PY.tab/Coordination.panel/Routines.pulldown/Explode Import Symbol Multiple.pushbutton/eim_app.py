# -*- coding: utf-8 -*-
"""Reads the selection, asks Partial or Full, and starts the run."""
import eim_clr  # noqa: F401  (assembly references first)
from Autodesk.Revit.DB import ImportInstance

import eim_core
import eim_settings
import eim_runner
from eim_window import ExplodeWindow
import eim_theme
from eim_version import __version__


def _name(el):
    """Import symbols show their file name as their category name."""
    for getter in (lambda e: e.Category.Name, lambda e: e.Name):
        try:
            value = getter(el)
            if value:
                return u'{0}'.format(value)
        except Exception:
            pass
    return u'Import symbol'


def read_selection(uidoc):
    doc = uidoc.Document
    items, id_by_key = [], {}
    for eid in list(uidoc.Selection.GetElementIds()):
        el = doc.GetElement(eid)
        if el is None:
            continue
        key = eim_core.eid_value(eid)
        id_by_key[key] = eid
        is_import = isinstance(el, ImportInstance)
        linked = False
        if is_import:
            try:
                linked = bool(el.IsLinked)
            except Exception:
                linked = False
        try:
            pinned = bool(el.Pinned)
        except Exception:
            pinned = False
        items.append({'key': key, 'is_import': is_import, 'is_linked': linked,
                      'pinned': pinned, 'name': _name(el) if is_import else u''})
    return items, id_by_key


def main(uiapp):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return
    doc = uidoc.Document
    settings = eim_settings.load()
    canvas_dark = eim_theme.canvas_is_dark()
    owner = None
    try:
        owner = uiapp.MainWindowHandle
    except Exception:
        owner = None

    def report(title, lines):
        w = ExplodeWindow(settings, owner, canvas_dark)
        w.result(title, lines)
        eim_settings.save(settings)

    if eim_runner.busy_since() is not None:
        report(u'Still exploding the last selection',
               [u'A run is already going. Give it a moment to finish, then try again.'])
        return

    items, id_by_key = read_selection(uidoc)
    cls = eim_core.classify(items)
    headline, detail = eim_core.summary_lines(cls)

    window = ExplodeWindow(settings, owner, canvas_dark)
    choice = window.prompt(headline, detail, bool(cls['explode']))
    eim_settings.save(settings)
    if not choice or not cls['explode']:
        return

    log = eim_settings.Log(settings.get(u'debug') == u'1')
    log(u'selection: {0} item(s), explode {1}, linked {2}, other {3}, pinned {4}, canvas dark {5}'.format(
        len(items), len(cls['explode']), len(cls['linked']), cls['other'],
        len(cls['pinned']), canvas_dark))
    run = eim_runner.ExplodeRun(uiapp, doc, id_by_key, cls, choice, settings, log, report)
    _RUNS.append(run)       # keep it alive while Idling drives it
    del _RUNS[:-3]
    run.start()


_RUNS = []
