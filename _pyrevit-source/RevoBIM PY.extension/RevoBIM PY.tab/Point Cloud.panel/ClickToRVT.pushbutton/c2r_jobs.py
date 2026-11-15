# -*- coding: utf-8 -*-
"""Click to RVT Element - the jobs the window sends out through its
ExternalEvent. Every Revit write in the tool is in this module, one
transaction per placement, warnings swallowed, errors rolled back and
reported in Revit's own words.
"""
import c2r_clr  # noqa: F401

import time

from System.Collections.Generic import List
from Autodesk.Revit.DB import (Transaction, TransactionStatus, IFailuresPreprocessor, FailureSeverity,
                               FailureProcessingResult, ElementId)

import c2r_core as core
import c2r_cloud as cloud
import c2r_build as build


class Swallow(IFailuresPreprocessor):
    """Warnings deleted; errors recorded so the status line can name them."""

    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, fa):
        try:
            for f in fa.GetFailureMessages():
                if f.GetSeverity() == FailureSeverity.Warning:
                    fa.DeleteWarning(f)
                else:
                    try:
                        self.errors.append(f.GetDescriptionText())
                    except Exception:
                        self.errors.append(u'Revit error')
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _alive(doc, ids):
    out = []
    for i in ids or []:
        try:
            if doc.GetElement(i) is not None:
                out.append(i)
        except Exception:
            pass
    return out


def place(doc, cand, rec, cat, opts, st, log, replace=None):
    """One undoable transaction: remove `replace` (a swap), create the
    candidate. Returns the ids that exist afterwards."""
    sw = Swallow()
    t = Transaction(doc, u'RevoBIM Click to RVT Element')
    opt = t.GetFailureHandlingOptions()
    opt.SetFailuresPreprocessor(sw)
    t.SetFailureHandlingOptions(opt)
    t.Start()
    try:
        old = _alive(doc, replace)
        if old:
            lst = List[ElementId]()
            for i in old:
                lst.Add(i)
            doc.Delete(lst)
        pl = build.Placement(doc, cat, opts, st, log)
        ids = build.create(pl, cand, rec)
        status = t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        raise
    if status != TransactionStatus.Committed:
        raise ValueError(u'Revit refused it: {0}'.format(u'; '.join(sw.errors) or u'{0}'.format(status)))
    ids = _alive(doc, ids)
    if not ids:
        raise ValueError(u'Revit accepted the transaction but the element is not there')
    return ids


def click_job(uiapp, opts, st, log):
    """Pick on the cloud, recognise, (place). Returns a result dict for the
    window; `cancelled` when Escape was pressed at the first click."""
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return {u'error': u'No model is open'}
    doc = uidoc.Document
    if not cloud.clouds_in(doc):
        return {u'error': u'There is no point cloud in this model'}
    try:
        inst, click = cloud.pick_point(uidoc, u'Click to RVT Element: click the scanned object (Esc to stop)')
    except Exception as ex:
        if cloud.is_cancel(ex):
            return {u'cancelled': True}
        raise
    t0 = time.time()
    log(u'click at ({0:.0f}, {1:.0f}, {2:.0f}) mm on {3}'.format(click[0], click[1], click[2], build.ename(inst)))
    cat = build.read_catalogue(doc, st)
    harv = cloud.Harvester(inst, int(float(st[u'max_points'])), log)
    widths = [t[u'width'] for t in cat.get(u'wall') or []]
    click_end = opts.get(u'run_mode') == u'click'
    try:
        rec = core.recognise(click, harv, cat[u'levels'], st, widths=widths, trace=not click_end, log=log)
    except core.RecogniseError as ex:
        return {u'error': u'{0}'.format(ex), u'click': click}
    if click_end and rec[u'shape'] in (u'round', u'rect'):
        try:
            _i2, click2 = cloud.pick_point(uidoc, u'Click to RVT Element: click the far end of the run')
            core.end_from_click(rec, click2)
        except core.RecogniseError as ex:
            return {u'error': u'{0}'.format(ex), u'click': click}
        except Exception as ex:
            if cloud.is_cancel(ex):
                return {u'cancelled': True}
            raise
    log(u'recognised: {0} in {1:.1f} s, {2} harvests, {3} pts'.format(
        core.describe(rec), time.time() - t0, harv.calls, harv.total))
    cands = core.candidates(rec, cat, opts, st)
    for c in cands:
        log(u'  candidate {0}: {1} [{2}] err {3:.1f} score {4:.1f}'.format(
            c[u'kind'], c[u'text'], c[u'type'][u'name'], c[u'err'], c[u'score']))
    res = {u'rec': rec, u'cands': cands, u'cat': cat, u'placed': None, u'ids': [], u'click': click}
    if not cands:
        res[u'error'] = u'{0} - but no ticked kind with a type in this model fits it'.format(core.describe(rec))
        return res
    if opts.get(u'auto_place'):
        try:
            res[u'ids'] = place(doc, cands[0], rec, cat, opts, st, log)
            res[u'placed'] = 0
        except Exception as ex:
            res[u'error'] = u'{0} not placed: {1}'.format(cands[0][u'text'], ex)
            log(u'place failed: {0}'.format(ex))
    return res


def place_job(uiapp, last, index, opts, st, log):
    """Place (or swap to) candidate `index` of the last recognition."""
    doc = uiapp.ActiveUIDocument.Document
    cand = last[u'cands'][index]
    ids = place(doc, cand, last[u'rec'], last[u'cat'], opts, st, log, replace=last.get(u'ids'))
    return {u'ids': ids, u'placed': index}


def select_job(uiapp, ids):
    uidoc = uiapp.ActiveUIDocument
    alive = _alive(uidoc.Document, ids)
    lst = List[ElementId]()
    for i in alive:
        lst.Add(i)
    uidoc.Selection.SetElementIds(lst)
    if alive:
        try:
            uidoc.ShowElements(lst)
        except Exception:
            pass
    return len(alive)


def delete_job(uiapp, ids):
    doc = uiapp.ActiveUIDocument.Document
    alive = _alive(doc, ids)
    if not alive:
        return 0
    t = Transaction(doc, u'RevoBIM Click to RVT Element - delete')
    t.Start()
    try:
        lst = List[ElementId]()
        for i in alive:
            lst.Add(i)
        doc.Delete(lst)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return len(alive)


def catalogue_job(uiapp, st):
    return build.read_catalogue(uiapp.ActiveUIDocument.Document, st)
