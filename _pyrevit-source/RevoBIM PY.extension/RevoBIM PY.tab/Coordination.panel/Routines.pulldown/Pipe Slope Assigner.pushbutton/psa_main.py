# -*- coding: utf-8 -*-
"""RevoBIM Pipe Slope Assigner - the run, start to finish.

    selection -> prompt -> (clicks) -> walk -> outlet -> plan -> borrow
    -> write -> read back -> parameters put back -> report

The window is modeless by default: Revit stays fully usable while it is open,
and Apply queues the work through an ExternalEvent (picks included - they run
in the handler, in API context). That needs __persistentengine__ in script.py
and the window, event and handler parked where nothing collects them. Setting
window=modal brings back the fixed window with the picks run in the command.
"""

import psa_clr  # noqa: F401  (assemblies before any System.* name)

import time
import traceback

from Autodesk.Revit.DB import TransactionGroup
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

import psa_core as core
import psa_revit as rv
import psa_ui as ui


# ====================== picking ======================

class HorizontalPipeFilter(ISelectionFilter):
    """Only pipes at 46 degrees or flatter light up under the cursor."""

    def AllowElement(self, element):
        try:
            if not isinstance(element, Pipe):
                return False
            curve = element.Location.Curve
            a, b = rv.to_t(curve.GetEndPoint(0)), rv.to_t(curve.GetEndPoint(1))
            return not core.is_steep(a, b)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


def is_cancel(ex):
    return 'OperationCanceled' in type(ex).__name__


def pick_pipe(uidoc, prompt):
    """(element, point) or None on Escape."""
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, HorizontalPipeFilter(), prompt)
    except Exception as ex:
        if is_cancel(ex):
            return None
        raise
    el = uidoc.Document.GetElement(ref)
    pt = None
    try:
        if ref.GlobalPoint is not None:
            pt = rv.to_t(ref.GlobalPoint)
    except Exception:
        pt = None
    if pt is None:
        curve = el.Location.Curve
        pt = rv.to_t(curve.Evaluate(0.5, True))
    return el, pt


def pick_direction(uidoc, lead=u''):
    head = u'RevoBIM Pipe Slope Assigner - ' + lead
    first = pick_pipe(uidoc, head + u'click where the fall STARTS (fall from, the high end)')
    if first is None:
        return None
    second = pick_pipe(uidoc, head + u'now click where it falls TO (the low end)')
    if second is None:
        return None
    return {'from': first, 'to': second}


def read_selection(doc, adapter, element_ids):
    """(pipes, how many other elements, every selected id as a number)."""
    pipes, others, ids = [], 0, set()
    for eid in element_ids:
        el = doc.GetElement(eid)
        if el is None:
            continue
        ids.add(adapter.eid(el))
        if adapter.kind(el) == 'pipe':
            pipes.append(el)
        else:
            others += 1
    return pipes, others, ids


def selected_pipes(uidoc, adapter):
    return read_selection(uidoc.Document, adapter, uidoc.Selection.GetElementIds())


class SystemFilter(ISelectionFilter):
    """Pipes, pipe fittings and pipe accessories - what a system is made of."""

    def __init__(self, adapter):
        self.adapter = adapter

    def AllowElement(self, element):
        try:
            return self.adapter.kind(element) in ('pipe', 'fitting')
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


def pick_system(uidoc, adapter):
    """Several pipes and fittings; Finish (or Enter) when done. None on Escape."""
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, SystemFilter(adapter),
            u'RevoBIM Pipe Slope Assigner - select the pipes and fittings of the system, '
            u'then Finish')
    except Exception as ex:
        if is_cancel(ex):
            return None
        raise
    doc = uidoc.Document
    return [doc.GetElement(r) for r in refs]


# ====================== one run ======================

def outlet_for(uidoc, adapter, m, g, settings, picks, log, asked=False):
    """(root, reason, anchor) or raises Refusal. May ask for two clicks."""
    anchor_mode = settings.get('anchor', 'low')
    if picks is not None:
        f_el, f_pt = picks['from']
        t_el, t_pt = picks['to']
        fid, tid = adapter.eid(f_el), adapter.eid(t_el)
        in_f, in_t = fid in m.pipes, tid in m.pipes
        if in_f or in_t:
            if not (in_f and in_t):
                raise core.Refusal(u'The fall-from and fall-to clicks are on '
                                   u'different runs.')
            src_f, _ = core.click_sources(m, fid, f_pt)
            src_t, _ = core.click_sources(m, tid, t_pt)
            root, reason = core.choose_outlet_picked(g, src_f, src_t)
            if root is None:
                raise core.Refusal(reason)
            anchor = ('point', tid, t_pt) if anchor_mode == 'low' else ('point', fid, f_pt)
            log.add(u'  outlet from clicks: {0} ({1})', core.node_text(root), reason)
            return root, reason, anchor
        if asked:
            raise core.Refusal(u'Left as it was - the two direction clicks were not on '
                               u'this run.')

    root, reason = core.choose_outlet_auto(g)
    if root is None:
        log.add(u'  auto direction: {0} - asking for two clicks', reason)
        clicks = pick_direction(uidoc, u'level run: ')
        if clicks is None:
            raise core.Refusal(u'Left as it was - the run is level and the two '
                               u'direction clicks were cancelled.')
        return outlet_for(uidoc, adapter, m, g, dict(settings), clicks, log, True)
    if anchor_mode == 'low':
        anchor = ('node', root)
    else:
        dist = g.dijkstra({root: 0.0})
        head = max(core.terminals(g), key=lambda k: (dist.get(k, -1), repr(k)))
        anchor = ('node', head)
    log.add(u'  outlet auto: {0} ({1})', core.node_text(root), reason)
    return root, reason, anchor


def log_model(m, g, log):
    log.add(u'  scope {0}: {1} pipes, {2} fittings, {3} stretched, {4} fixed',
            m.scope, len(m.pipes), len(m.fittings), len(m.stretch), len(m.fixed))
    for pid, p in sorted(m.pipes.items()):
        log.add(u'    pipe {0}: {1} -> {2}  now {3}', pid, core.fmt_pt(p['ends'][0]),
                core.fmt_pt(p['ends'][1]), core.ratio_text(core.gradient(*p['ends'])))
    for fid, f in sorted(m.fittings.items()):
        log.add(u'    fitting {0}: {1} connectors, axes meet at {2} (placed at {3})', fid,
                len(f['conns']), core.fmt_pt(f['centre']),
                core.fmt_pt(f['located']) if f.get('located') else u'-')
    for sid, s in sorted(m.stretch.items()):
        log.add(u'    stretch {0}: {1}, {2}', sid, s['kind'], u'down' if s['down'] else u'up')
    for xid, x in sorted(m.fixed.items()):
        log.add(u'    fixed {0}: {1} ({2})', xid, x['kind'], x['desc'])
    for note in m.notes:
        log.add(u'    note: {0}', note)
    terms = core.terminals(g)
    log.add(u'  graph: {0} nodes, ends: {1}', len(g.pos), u', '.join(
        u'{0} [{1}, z {2:.1f}]'.format(core.node_text(t), core.node_class(g, t),
                                       core.ft_to_mm(g.pos[t][2])) for t in terms))


def biggest_move(m, plan):
    moved = 0.0
    for pid, (a, b) in plan.pipes.items():
        old = m.pipes[pid]['ends']
        moved = max(moved, core.v_len(core.v_sub(a, old[0])), core.v_len(core.v_sub(b, old[1])))
    return core.ft_to_mm(moved)


def prepare_one(uidoc, adapter, m, settings, picks, log, rows):
    """Outlet, plan and checks - and any clicks - before anything is opened.

    Returns the plan, or None when there is nothing to change. Picking is kept
    out of the TransactionGroup the write runs in.
    """
    n = int(settings.get('slope', '100'))
    start = m.start_ids[0] if m.start_ids else u'?'
    log.section(u'run from pipe {0}'.format(start))
    g = core.build_graph(m)
    log_model(m, g, log)

    root, reason, anchor = outlet_for(uidoc, adapter, m, g, settings, picks, log)
    plan = core.make_plan(m, g, n, root, anchor)
    plan.reason = reason
    log.add(u'  held elevation: {0} ({1})', anchor[0], core.node_text(anchor[1])
            if anchor[0] == 'node' else u'pipe {0} at the click'.format(anchor[1]))
    log.add(u'  outlet centreline height {0:.1f} mm', core.ft_to_mm(plan.z_root))
    for pid, (a, b) in sorted(plan.pipes.items()):
        log.add(u'    plan pipe {0}: {1} -> {2}', pid, core.fmt_pt(a), core.fmt_pt(b))
    for w in plan.warnings:
        log.add(u'  warning: {0}', w)
        rows.append(('warn', w))
    problems = core.check_plan(m, plan)
    if problems:
        for p in problems:
            log.add(u'  plan problem: {0}', p)
        for p in problems[:12]:
            rows.append(('bad', p))
        if len(problems) > 12:
            rows.append(('bad', u'... and {0} more in the report.'.format(len(problems) - 12)))
        raise core.Refusal(u'{0} from pipe {1} left alone - nothing was changed, because '
                           u'{2} did not check out (listed above).'.format(
                               u'System' if m.scope == 'selection' else u'Run', start,
                               core.plural(len(problems), u'thing')))
    if biggest_move(m, plan) < 0.05:
        rows.append(('ok', u'Run from pipe {0}: already at {1}, falling the right '
                           u'way - nothing to change.'.format(start, core.slope_label(n))))
        return None
    return plan


def write_one(doc, m, plan, log, rows):
    """Borrow, write, read back, put parameters back. True when written."""
    n = plan.n
    start = m.start_ids[0] if m.start_ids else u'?'
    reason = plan.reason
    log.section(u'writing run from pipe {0}'.format(start))
    touched = [rec['el'] for store in (m.pipes, m.fittings, m.stretch) for rec in store.values()]
    joined_fixed = set(b for (a, ca, b, cb) in plan.joins if b in m.fixed)
    touched += [m.fixed[x]['el'] for x in joined_fixed]
    refused = rv.borrow(doc, touched, log)
    if refused:
        for eid, why in refused:
            rows.append(('bad', u'Element {0}: {1}.'.format(eid, why)))
        raise core.Refusal(u'Run from pipe {0} left alone - {1} element(s) are held '
                           u'by somebody else.'.format(start, len(refused)))

    snap = rv.snapshot_params([rec['el'] for store in (m.pipes, m.fittings, m.stretch)
                               for rec in store.values()])
    log.add(u'  parameter values held: {0}', sum(len(v[1]) for v in snap.values()))

    status, errors, join_fail = rv.apply_plan(doc, m, plan, log)
    if not rv.committed(status):
        raise core.Refusal(u'Run from pipe {0}: Revit rolled the change back ({1}). {2}'.format(
            start, status, u' '.join(errors[:3])))

    pipe_rows, bad, broken = rv.verify(m, plan, log)
    changes = rv.changed_params(snap)
    if changes:
        log.add(u'  {0} parameter value(s) changed by the reconnect - restoring', len(changes))
        t, swallow = rv.start_transaction(doc, u'RevoBIM Pipe Slope Assigner - keep parameters', log)
        restored, failed = rv.restore_params(changes, log)
        status2 = t.Commit()
        if not rv.committed(status2):
            rows.append(('bad', u'Parameter values could not be put back ({0}).'.format(status2)))
        for eid, name, why in failed:
            rows.append(('warn', u'Element {0}: "{1}" could not be put back - {2}.'.format(
                eid, name, why)))
        still = rv.changed_params(snap)
        if still:
            for (el, pid, name, kind, before, now) in still[:20]:
                rows.append(('bad', u'Element {0}: "{1}" is {2}, was {3}.'.format(
                    rv.eid_value(el.Id), name, now, before)))
        log.add(u'  parameters restored: {0}, still different: {1}', restored, len(still))

    pipes, fits, ups, brs = core.fall_summary(m, plan)
    head = u'Run from pipe {0}: {1} pipe{2} at {3}, {4}.'.format(
        start, pipes, u'' if pipes == 1 else u's', core.slope_label(int(n)), reason)
    extra = []
    if ups:
        extra.append(u'{0} upright{1} stretched'.format(ups, u'' if ups == 1 else u's'))
    if brs:
        extra.append(u'{0} branch pipe{1} stretched'.format(brs, u'' if brs == 1 else u's'))
    if extra:
        head += u' ' + u', '.join(extra).capitalize() + u'.'
    rows.append(('ok' if not bad and not broken else 'warn', head))
    rows.extend(pipe_rows)
    for (a, b, why) in join_fail:
        rows.append(('bad', u'Could not rejoin {0} to {1}: {2}.'.format(a, b, why)))
    for (a, b) in broken:
        if not any(x[0] == a and x[1] == b for x in join_fail):
            rows.append(('bad', u'{0} and {1} are not joined after the change.'.format(a, b)))
    for (inside, icid, other, moved) in plan.loose:
        rows.append(('warn', u'{0} is left loose from {1} ({2}) - the joint had to move '
                             u'{3:.0f} mm and {1} is not part of the run.'.format(
                                 inside, other, m.fixed.get(other, {}).get('desc', u''), moved)))
    for note in m.notes + plan.notes:
        rows.append(('info', note))
    return True


# ====================== a whole job ======================

def new_log(uiapp):
    log = core.Log()
    log.add(u'RevoBIM Pipe Slope Assigner v{0}', core.__version__)
    try:
        app = uiapp.Application
        log.add(u'Revit {0} ({1})', app.VersionNumber, app.VersionBuild)
    except Exception:
        pass
    return log


def run_job(uiapp, settings, log):
    """Selection -> clicks -> walk -> plan -> write. Returns (rows, wrote).

    Runs inside the command (modal window) or inside the ExternalEvent handler
    (modeless window) - both are API context, and both can ask for picks.
    """
    uidoc = uiapp.ActiveUIDocument
    rows = []
    if uidoc is None:
        rows.append(('bad', u'No model is open.'))
        return rows, False
    doc = uidoc.Document
    log.add(u'Document: {0} | workshared: {1}', doc.Title, doc.IsWorkshared)
    log.add(u'Settings: ' + u', '.join(u'{0}={1}'.format(k, settings.get(k))
                                       for k, _ in core.DEFAULTS))
    core.set_upright(settings)
    log.add(u'Set up / set down line: steeper than {0:.0f} degrees', core.STEEP_DEG)
    adapter = rv.RevitAdapter(doc)
    scope = settings.get('scope', 'run')
    starts, others, allowed = selected_pipes(uidoc, adapter)
    log.add(u'Selected pipes: {0} | other elements: {1}', len(starts), others)
    if scope == 'selection' and not starts:
        picked = pick_system(uidoc, adapter)
        if picked is None:
            log.add(u'System selection cancelled.')
            return rows, False
        starts = [el for el in picked if adapter.kind(el) == 'pipe']
        allowed = set(adapter.eid(el) for el in picked)
        log.add(u'Picked: {0} pipes, {1} elements', len(starts), len(allowed))
    if scope != 'selection':
        allowed = None

    picks = None
    if settings.get('direction') == 'pick':
        picks = pick_direction(uidoc)
        if picks is None:
            log.add(u'Direction clicks cancelled.')
            return rows, False
        log.add(u'Fall from: pipe {0} at {1}', adapter.eid(picks['from'][0]),
                core.fmt_pt(picks['from'][1]))
        log.add(u'Fall to:   pipe {0} at {1}', adapter.eid(picks['to'][0]),
                core.fmt_pt(picks['to'][1]))
        if not any(adapter.eid(s) == adapter.eid(picks['from'][0]) for s in starts):
            if allowed is None or adapter.eid(picks['from'][0]) in allowed:
                starts = [picks['from'][0]] + list(starts)
    if not starts:
        picked = pick_pipe(uidoc, u'RevoBIM Pipe Slope Assigner - click a horizontal '
                                  u'pipe in the run')
        if picked is None:
            log.add(u'Pipe click cancelled.')
            return rows, False
        starts = [picked[0]]

    if scope == 'selection':
        starts, steep = core.horizontal_starts(adapter, starts)
        if steep:
            rows.append(('info', u'{0} steeper than {1:.0f} degrees left as they are - set '
                                  u'ups, set downs and uprights stretch to stay joined.'.format(
                                      core.plural(steep, u'selected pipe'), core.STEEP_DEG)))
        if not starts:
            rows.append(('bad', u'Nothing horizontal in the selection to fall.'))
            return rows, False

    models = []
    covered = set()
    for s in starts:
        if adapter.eid(s) in covered:
            continue
        try:
            m = core.walk(adapter, s, scope, allowed)
        except core.Refusal as r:
            rows.append(('bad', core.text_type(r)))
            continue
        covered.update(m.pipes.keys())
        models.append(m)

    prepared = []
    for m in models:
        try:
            plan = prepare_one(uidoc, adapter, m, settings, picks, log, rows)
            if plan is not None:
                prepared.append((m, plan))
        except core.Refusal as r:
            rows.append(('bad', core.text_type(r)))
            log.add(u'  refused: {0}', r)
        except Exception:
            log.add(traceback.format_exc())
            rows.append(('bad', u'Run from pipe {0} could not be worked out - see the '
                                u'report.'.format(m.start_ids[0] if m.start_ids else u'?')))

    wrote = False
    if prepared:
        group = TransactionGroup(doc, u'RevoBIM Pipe Slope Assigner')
        group.Start()
        rv.suppress_dialogs(uiapp, True)
        try:
            for m, plan in prepared:
                try:
                    if write_one(doc, m, plan, log, rows):
                        wrote = True
                except core.Refusal as r:
                    rows.append(('bad', core.text_type(r)))
                    log.add(u'  refused: {0}', r)
                except Exception:
                    log.add(traceback.format_exc())
                    rows.append(('bad', u'Run from pipe {0} failed - see the report.'.format(
                        m.start_ids[0] if m.start_ids else u'?')))
        finally:
            seen = rv.suppress_dialogs(uiapp, False)
            if seen:
                log.add(u'Revit dialogs answered during the run: {0}', seen)
            try:
                if wrote:
                    group.Assimilate()
                else:
                    group.RollBack()
            except Exception:
                log.add(traceback.format_exc())
    return rows, wrote


def summarise(settings, rows, wrote, log, started):
    """Writes the log. Returns (summary, issues, path)."""
    log.section(u'result')
    for state, text in rows:
        log.add(u'[{0}] {1}', state, text)
    log.add(u'Took {0:.1f}s', time.time() - started)
    path = log.write()
    issues = any(state in ('bad', 'warn') for state, _ in rows)
    label = core.slope_label(int(settings.get('slope', '100')))
    if issues:
        summary = u'Finished, but some of it needs a look - the red and orange lines below.'
    elif wrote:
        summary = u'Fall set to {0}.'.format(label)
    else:
        summary = u'Nothing changed.'
    return summary, issues, path


def wants_results(settings, issues):
    show = settings.get('show_results', 'issues')
    return (settings.get('debug') == '1' or show == 'always'
            or (show == 'issues' and issues))


# ====================== the modeless window ======================

# The window, its ExternalEvent and the handler are parked here as well as in
# the AppDomain: pyRevit's persistent engine keeps this module alive, and
# anything not held somewhere is collected out from under the user.
PARKED = {}


class JobHandler(IExternalEventHandler):
    """Revit calls Execute when it is idle, in API context, on its own UI
    thread - the same thread the window lives on, so the window can be updated
    straight from here. The window never waits for it: it queues, returns,
    and hears back through done()."""

    def __init__(self):
        self.job = None

    def Execute(self, uiapp):
        job, self.job = self.job, None
        if job is None:
            return
        core.run_safely(lambda: job['work'](uiapp), job['done'], ui.write_error)

    def GetName(self):
        return u'RevoBIM Pipe Slope Assigner'


def selection_update(dialog):
    """The SelectionChanged callback for this window."""
    def on_selection(args):
        if dialog.busy:
            return
        doc = args.GetDocument()
        adapter = rv.RevitAdapter(doc)
        starts, others, ids = read_selection(doc, adapter, args.GetSelectedElements())
        dialog.set_selection(core.selection_text(adapter, starts, others),
                             core.make_preview(adapter, starts, allowed=ids))
    return on_selection


def open_modeless(uiapp, settings, text, preview):
    handler = JobHandler()
    event = ExternalEvent.Create(handler)
    state = {'results': None}

    def on_closed():
        rv.watch_selection(uiapp, None)
        handler.job = None
        rv.park_window(None)
        PARKED.clear()
        ui.clear_alive_check()
        try:
            event.Dispose()
        except Exception:
            pass

    dialog = ui.SlopeDialog(uiapp, settings, text, preview, modeless=True,
                            on_closed=on_closed)

    def apply(chosen):
        core.save_settings(chosen)

        def work(app):
            started = time.time()
            log = new_log(app)
            dialog.set_busy(True, u'Working - click in the model if asked (Esc cancels).')
            rows, wrote = run_job(app, chosen, log)
            summary, issues, path = summarise(chosen, rows, wrote, log, started)
            return {'rows': rows, 'wrote': wrote, 'summary': summary, 'issues': issues,
                    'path': path, 'report': log.text()}

        def done(result, error):
            dialog.set_busy(False)
            if error is not None:
                dialog.chrome.status(u'Something went wrong - details in {0}'.format(
                    core.ERROR_FILE), 'Red')
                return
            dialog.chrome.status(result['summary'] + u'  Select another run and Apply again.',
                                 'Orange' if result['issues'] else 'Green')
            if wants_results(chosen, result['issues']):
                old = state['results']
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
                results = ui.ResultsWindow(uiapp, dialog.settings, result['summary'],
                                           result['rows'], result['report'], result['path'],
                                           chosen.get('debug') == '1')
                state['results'] = results
                results.show(modal=False)

        handler.job = {'work': work, 'done': done}
        answer = event.Raise()
        if 'Accepted' in str(answer):
            dialog.set_busy(True, u'Waiting for Revit - finish or Esc out of any command '
                                  u'you are in.')
        else:
            handler.job = None
            dialog.chrome.status(u'Revit would not take the request ({0}). Try again.'.format(
                answer), 'Red')

    dialog.on_apply_cb = apply
    PARKED.update({'dialog': dialog, 'event': event, 'handler': handler, 'state': state})
    rv.park_window(dialog.window)
    if rv.watch_selection(uiapp, selection_update(dialog)):
        dialog.chrome.status(u'Revit stays usable - change the selection and the preview follows.')
    else:
        dialog.chrome.status(u'Revit stays usable. The preview updates on Apply.')
    ui.arm_alive_check()
    dialog.show()


def ask_modal_instead():
    """The last modeless window never ran a handler - pyRevit did not keep the
    engine alive. Offer the fixed window before building another dead one."""
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons
        answer = TaskDialog.Show(
            u'RevoBIM Pipe Slope Assigner',
            u'Last time the Pipe Slope Assigner window stopped responding - pyRevit '
            u'closed the engine behind it.\n\nOpen it as a fixed window this time? Revit '
            u'is locked while a fixed window is open, but it always works.\n\n'
            u'(Change back any time: window=modeless in '
            u'%APPDATA%\\RevoBIM\\pipe_slope_assigner.txt)',
            TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        return 'Yes' in str(answer)
    except Exception:
        return False


# ====================== the command ======================

def main(uiapp):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return
    existing = rv.open_window()
    if existing is not None:
        try:
            existing.Activate()
            return
        except Exception:
            pass

    settings = core.load_settings()
    if settings.get('window') == 'modeless' and ui.alive_check_failed():
        ui.clear_alive_check()
        if ask_modal_instead():
            settings['window'] = 'modal'
            core.save_settings(settings)

    doc = uidoc.Document
    adapter = rv.RevitAdapter(doc)
    core.set_upright(settings)
    starts, others, ids = selected_pipes(uidoc, adapter)
    text = core.selection_text(adapter, starts, others)
    preview = core.make_preview(adapter, starts, allowed=ids)

    if settings.get('window') == 'modeless':
        open_modeless(uiapp, settings, text, preview)
        return

    dialog = ui.SlopeDialog(uiapp, settings, text, preview)
    chosen = dialog.show()
    if chosen is None:
        return
    core.save_settings(chosen)
    started = time.time()
    log = new_log(uiapp)
    rows, wrote = run_job(uiapp, chosen, log)
    summary, issues, path = summarise(chosen, rows, wrote, log, started)
    if wants_results(chosen, issues):
        ui.ResultsWindow(uiapp, chosen, summary, rows, log.text(), path,
                         chosen.get('debug') == '1').show(modal=True)
