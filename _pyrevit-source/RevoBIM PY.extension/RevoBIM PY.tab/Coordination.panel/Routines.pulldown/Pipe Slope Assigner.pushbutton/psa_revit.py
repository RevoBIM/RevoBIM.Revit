# -*- coding: utf-8 -*-
"""RevoBIM Pipe Slope Assigner - everything that talks to Revit.

The adapter answers psa_core's questions about elements. apply_plan() does the
write, in this order inside one transaction:

    unpin -> disconnect every joint the run touches -> turn and move fittings
    -> recut pipes (same XY, new heights) -> stretch uprights and branch pipes
    -> regenerate -> reconnect -> regenerate -> repin

Rewriting a pipe's LocationCurve while it is still joined does not keep the
joint (that is what left the rest of the run behind in Drainage Elevation
Match 1.1), so every joint is freed first and put back by position after.

Then, after commit: every pipe's fall and every joint is read back, and any
parameter value the reconnect disturbed is put back in a second transaction.
Both sit in one TransactionGroup, so Revit's undo sees one step.
"""

import psa_clr  # noqa: F401  (assemblies before any System.* name)

from System import AppDomain
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, ConnectorType, ElementId,
    ElementTransformUtils, FailureProcessingResult, FailureSeverity,
    FamilyInstance, IFailuresPreprocessor, Line, LocationPoint, StorageType,
    Transaction, TransactionStatus, WorksharingUtils, XYZ)
from Autodesk.Revit.DB.Plumbing import Pipe

import psa_core as core


# ====================== helpers ======================

def eid_value(element_id):
    """ElementId as a number on every release: .Value from 2024, the old
    integer property only as a guarded fallback (removed in 2026)."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def to_t(xyz):
    return (float(xyz.X), float(xyz.Y), float(xyz.Z))


def to_xyz(t):
    return XYZ(t[0], t[1], t[2])


def bic_value(name):
    """A BuiltInCategory as a number, looked up at call time."""
    try:
        return eid_value(ElementId(getattr(BuiltInCategory, name)))
    except Exception:
        try:
            return int(getattr(BuiltInCategory, name))
        except Exception:
            return None


def connector_manager(el):
    if isinstance(el, Pipe):
        return el.ConnectorManager
    mep = getattr(el, 'MEPModel', None)          # FamilyInstance: via MEPModel
    if mep is None:
        return None
    try:
        return mep.ConnectorManager
    except Exception:
        return None


def iter_connectors(el):
    cm = connector_manager(el)
    if cm is None:
        return []
    out = []
    try:
        for c in cm.Connectors:
            out.append(c)
    except Exception:
        pass
    return out


def find_connector(el, cid, near=None):
    """A connector by its id, else the one nearest a point."""
    conns = iter_connectors(el)
    for c in conns:
        try:
            if c.Id == cid and c.ConnectorType != ConnectorType.Logical:
                return c
        except Exception:
            continue
    if near is None:
        return None
    best, best_d = None, None
    for c in conns:
        try:
            if c.ConnectorType == ConnectorType.Logical:
                continue
            d = core.v_len(core.v_sub(to_t(c.Origin), near))
        except Exception:
            continue
        if best_d is None or d < best_d:
            best, best_d = c, d
    return best


def element_name(el):
    parts = []
    try:
        if el.Category is not None:
            parts.append(el.Category.Name)
    except Exception:
        pass
    try:
        sym = getattr(el, 'Symbol', None)
        if sym is not None:
            parts.append(u'{0} : {1}'.format(sym.FamilyName, sym.Name))
    except Exception:
        pass
    if not parts:
        try:
            parts.append(el.Name)
        except Exception:
            parts.append(u'element')
    return u' - '.join(parts)


# ====================== the adapter ======================

class RevitAdapter(object):
    """What psa_core.walk needs to know about an element, read from Revit."""

    def __init__(self, doc):
        self.doc = doc
        self._fitting_cats = None

    def fitting_cats(self):
        if self._fitting_cats is None:
            self._fitting_cats = set(v for v in (bic_value('OST_PipeFitting'),
                                                 bic_value('OST_PipeAccessory'))
                                     if v is not None)
        return self._fitting_cats

    def eid(self, el):
        return eid_value(el.Id)

    def kind(self, el):
        if isinstance(el, Pipe):
            return 'pipe'
        if isinstance(el, FamilyInstance):
            try:
                cat = el.Category
                if cat is not None and eid_value(cat.Id) in self.fitting_cats():
                    return 'fitting'
            except Exception:
                pass
        return 'fixed'

    def ends(self, el):
        curve = el.Location.Curve
        return [to_t(curve.GetEndPoint(0)), to_t(curve.GetEndPoint(1))]

    def centre(self, el):
        loc = el.Location
        if isinstance(loc, LocationPoint):
            return to_t(loc.Point)
        pts = [to_t(c.Origin) for c in iter_connectors(el)]
        if pts:
            k = 1.0 / len(pts)
            return (sum(p[0] for p in pts) * k, sum(p[1] for p in pts) * k,
                    sum(p[2] for p in pts) * k)
        box = el.get_BoundingBox(None)
        return to_t((box.Min + box.Max) * 0.5)

    def in_group(self, el):
        try:
            return eid_value(el.GroupId) > 0
        except Exception:
            return False

    def describe(self, el):
        return u'{0} {1}'.format(element_name(el), eid_value(el.Id))

    def connectors(self, el):
        out = []
        is_pipe = isinstance(el, Pipe)
        ends = self.ends(el) if is_pipe else None
        me = eid_value(el.Id)
        for c in iter_connectors(el):
            try:
                ct = c.ConnectorType
                if ct == ConnectorType.Logical:
                    continue
                origin = to_t(c.Origin)
                try:
                    direction = to_t(c.CoordinateSystem.BasisZ)
                except Exception:
                    direction = (0.0, 0.0, 0.0)
                rec = {'id': c.Id, 'origin': origin, 'dir': direction,
                       'end': None, 'curve': ct == ConnectorType.Curve,
                       'partners': []}
                if is_pipe and ct == ConnectorType.End:
                    d0 = core.v_len(core.v_sub(origin, ends[0]))
                    d1 = core.v_len(core.v_sub(origin, ends[1]))
                    rec['end'] = 0 if d0 <= d1 else 1
                if c.IsConnected:
                    for ref in c.AllRefs:
                        try:
                            if ref.ConnectorType == ConnectorType.Logical:
                                continue
                            owner = ref.Owner
                            if owner is None or eid_value(owner.Id) == me:
                                continue
                            rec['partners'].append((owner, ref.Id))
                        except Exception:
                            continue
                out.append(rec)
            except Exception:
                continue
        return out


# ====================== dialogs ======================

HOOK_KEY = 'RevoBIM.PipeSlopeAssigner.dialog_hook'
FLAG_KEY = 'RevoBIM.PipeSlopeAssigner.suppress'
SEEN_KEY = 'RevoBIM.PipeSlopeAssigner.dialogs_seen'


def _on_dialog(sender, args):
    try:
        domain = AppDomain.CurrentDomain
        if domain.GetData(FLAG_KEY):
            seen = domain.GetData(SEEN_KEY) or u''
            try:
                seen = seen + u'{0}; '.format(args.DialogId)
            except Exception:
                pass
            domain.SetData(SEEN_KEY, seen)
            args.OverrideResult(1)
    except Exception:
        pass


def suppress_dialogs(uiapp, on):
    """Revit's own dialogs are answered for the duration of a run.

    Hooked once per Revit session and switched with a flag: unsubscribing an
    IronPython bound method from a .NET event is not reliable.
    """
    try:
        domain = AppDomain.CurrentDomain
        domain.SetData(FLAG_KEY, bool(on))
        if on:
            domain.SetData(SEEN_KEY, u'')
        if on and domain.GetData(HOOK_KEY) is None:
            uiapp.DialogBoxShowing += _on_dialog
            domain.SetData(HOOK_KEY, u'hooked')
        if not on:
            return domain.GetData(SEEN_KEY) or u''
    except Exception:
        pass
    return u''


# ====================== the open window and the selection ======================

WINDOW_KEY = 'RevoBIM.PipeSlopeAssigner.window'
SEL_HOOK_KEY = 'RevoBIM.PipeSlopeAssigner.selection_hook'
SEL_TARGET_KEY = 'RevoBIM.PipeSlopeAssigner.selection_target'


def open_window():
    """The Pipe Slope Assigner window already on screen, or None."""
    try:
        window = AppDomain.CurrentDomain.GetData(WINDOW_KEY)
        if window is not None and window.IsVisible:
            return window
    except Exception:
        pass
    return None


def park_window(window):
    """Held by the AppDomain as well as by the module, so a second press of
    the button brings the open window forward instead of opening another."""
    try:
        AppDomain.CurrentDomain.SetData(WINDOW_KEY, window)
    except Exception:
        pass


def _on_selection(sender, args):
    try:
        target = AppDomain.CurrentDomain.GetData(SEL_TARGET_KEY)
        if target is not None:
            target(args)
    except Exception:
        pass


def watch_selection(uiapp, callback):
    """Call callback(args) whenever Revit's selection changes; None stops it.

    UIApplication.SelectionChanged runs in API context, so the callback may
    read the model. Hooked once per Revit session and pointed at the current
    window through the AppDomain - unsubscribing an IronPython bound method
    from a .NET event is not reliable. Returns False where the event does not
    exist, so the window can say its preview only updates on Apply.
    """
    try:
        domain = AppDomain.CurrentDomain
        domain.SetData(SEL_TARGET_KEY, callback)
        if callback is None:
            return True
        if domain.GetData(SEL_HOOK_KEY) is None:
            uiapp.SelectionChanged += _on_selection
            domain.SetData(SEL_HOOK_KEY, u'hooked')
        return True
    except Exception:
        return False


class Swallow(IFailuresPreprocessor):
    """Warnings are deleted and logged. An error rolls the transaction back,
    and its text is kept for the report."""

    def __init__(self, log):
        self.log = log
        self.errors = []

    def PreprocessFailures(self, accessor):
        try:
            failed = False
            for failure in accessor.GetFailureMessages():
                try:
                    text = failure.GetDescriptionText()
                except Exception:
                    text = u'(no description)'
                if failure.GetSeverity() == FailureSeverity.Warning:
                    self.log.add(u'  Revit warning deleted: {0}', text)
                    accessor.DeleteWarning(failure)
                else:
                    self.errors.append(text)
                    self.log.add(u'  Revit error: {0}', text)
                    failed = True
            if failed:
                return FailureProcessingResult.ProceedWithRollBack
        except Exception:
            pass
        return FailureProcessingResult.Continue


def start_transaction(doc, name, log):
    t = Transaction(doc, name)
    swallow = Swallow(log)
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(swallow)
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    return t, swallow


# ====================== worksharing ======================

def borrow(doc, elements, log):
    """Borrow before writing: an unborrowed element on a workshared model
    writes nothing and says nothing. Returns [(eid, reason)] for anything
    somebody else holds."""
    if not doc.IsWorkshared or not elements:
        return []
    ids = List[ElementId]()
    for el in elements:
        ids.Add(el.Id)
    got = set()
    try:
        for i in WorksharingUtils.CheckoutElements(doc, ids):
            got.add(eid_value(i))
    except Exception as ex:
        log.add(u'  CheckoutElements raised: {0}', ex)
    me = u''
    try:
        me = doc.Application.Username
    except Exception:
        pass
    refused = []
    for el in elements:
        eid = eid_value(el.Id)
        owner = None
        try:
            ws = doc.GetWorksetTable().GetWorkset(el.WorksetId)
            if ws is not None and ws.Owner and ws.Owner != me:
                owner = u'workset "{0}" is owned by {1}'.format(ws.Name, ws.Owner)
        except Exception:
            pass
        if owner is None and eid not in got:
            try:
                status = WorksharingUtils.GetCheckoutStatus(doc, el.Id)
                if str(status) == 'OwnedByOtherUser':
                    info = WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id)
                    owner = u'borrowed by {0}'.format(info.Owner or u'another user')
            except Exception:
                pass
        if owner:
            refused.append((eid, owner))
    return refused


# ====================== parameter retention ======================

GEOMETRY_BIPS = (
    'RBS_OFFSET_PARAM', 'RBS_START_OFFSET_PARAM', 'RBS_END_OFFSET_PARAM',
    'RBS_PIPE_SLOPE', 'CURVE_ELEM_LENGTH', 'RBS_PIPE_INVERT_ELEVATION',
    'RBS_START_LEVEL_PARAM', 'INSTANCE_ELEVATION_PARAM',
    'INSTANCE_FREE_HOST_OFFSET_PARAM', 'FAMILY_LEVEL_PARAM',
    'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM', 'RBS_PIPE_DIAMETER_PARAM',
    'RBS_CURVE_DIAMETER_PARAM', 'INSTANCE_REFERENCE_LEVEL_PARAM',
)

# Values these words name are moved by re-sloping on purpose; everything else
# the run carried before is carried after.
GEOMETRY_WORDS = (u'offset', u'elevation', u'slope', u'length', u'angle',
                  u'invert', u'level', u'height', u'diameter', u'radius',
                  u'size', u'top of', u'bottom of')


def geometry_param_ids():
    out = set()
    for name in GEOMETRY_BIPS:
        member = getattr(BuiltInParameter, name, None)
        if member is None:
            continue
        try:
            out.add(int(member))
        except Exception:
            pass
    return out


def read_param(p):
    st = p.StorageType
    if st == StorageType.String:
        return u'string', p.AsString() or u''
    if st == StorageType.Integer:
        return u'integer', p.AsInteger()
    if st == StorageType.Double:
        return u'double', p.AsDouble()
    if st == StorageType.ElementId:
        return u'id', p.AsElementId()
    return None, None


def same_value(kind, a, b):
    if kind == u'double':
        return abs(float(a) - float(b)) < 1e-9
    if kind == u'id':
        return eid_value(a) == eid_value(b)
    return a == b


def snapshot_params(elements):
    skip = geometry_param_ids()
    snap = {}
    for el in elements:
        values = {}
        try:
            params = list(el.Parameters)
        except Exception:
            params = []
        for p in params:
            try:
                if p.IsReadOnly or not p.HasValue:
                    continue
                pid = eid_value(p.Id)
                if pid in skip:
                    continue
                name = p.Definition.Name
                lowered = name.lower()
                if any(word in lowered for word in GEOMETRY_WORDS):
                    continue
                kind, value = read_param(p)
                if kind is None:
                    continue
                values[pid] = (name, kind, value)
            except Exception:
                continue
        snap[eid_value(el.Id)] = (el, values)
    return snap


def param_by_id(el, pid, name):
    try:
        for p in el.Parameters:
            if eid_value(p.Id) == pid:
                return p
    except Exception:
        pass
    try:
        return el.LookupParameter(name)
    except Exception:
        return None


def changed_params(snap):
    out = []
    for eid, (el, values) in snap.items():
        for pid, (name, kind, before) in values.items():
            p = param_by_id(el, pid, name)
            if p is None:
                out.append((el, pid, name, kind, before, u'(gone)'))
                continue
            try:
                k2, now = read_param(p)
            except Exception:
                continue
            if k2 != kind or not same_value(kind, before, now):
                out.append((el, pid, name, kind, before, now))
    return out


def restore_params(changes, log):
    restored, failed = 0, []
    for (el, pid, name, kind, before, now) in changes:
        p = param_by_id(el, pid, name)
        if p is None or p.IsReadOnly:
            failed.append((eid_value(el.Id), name, u'no longer writable'))
            continue
        try:
            p.Set(before)
            k2, after = read_param(p)
            if same_value(kind, before, after):
                restored += 1
                log.add(u'  restored {0} "{1}"', eid_value(el.Id), name)
            else:
                failed.append((eid_value(el.Id), name, u'did not stick'))
        except Exception as ex:
            failed.append((eid_value(el.Id), name, core.text_type(ex)))
    return restored, failed


# ====================== the write ======================

def element_of(m, eid):
    for store in (m.pipes, m.fittings, m.stretch, m.fixed):
        rec = store.get(eid)
        if rec is not None:
            return rec['el']
    return None


def set_curve(el, a, b):
    if core.v_len(core.v_sub(a, b)) < core.mm_to_ft(1.0):
        raise core.Refusal(u'Pipe {0} would be shorter than 1mm.'.format(
            eid_value(el.Id)))
    el.Location.Curve = Line.CreateBound(to_xyz(a), to_xyz(b))


def apply_plan(doc, m, plan, log):
    """One transaction. Returns (status, errors, join failures)."""
    moving = ([p['el'] for p in m.pipes.values()]
              + [f['el'] for f in m.fittings.values()]
              + [s['el'] for s in m.stretch.values()])
    join_fail = []
    t, swallow = start_transaction(doc, u'RevoBIM Pipe Slope Assigner', log)
    try:
        pinned = []
        for el in moving:
            try:
                if el.Pinned:
                    el.Pinned = False
                    pinned.append(el)
            except Exception:
                pass

        freed = 0
        for (a, ca, b, cb) in m.links:
            ea, eb = element_of(m, a), element_of(m, b)
            if ea is None or eb is None:
                continue
            c1, c2 = find_connector(ea, ca), find_connector(eb, cb)
            if c1 is None or c2 is None:
                continue
            try:
                if c1.IsConnectedTo(c2):
                    c1.DisconnectFrom(c2)
                    freed += 1
            except Exception as ex:
                log.add(u'  could not free {0}/{1} from {2}/{3}: {4}', a, ca, b, cb, ex)
        log.add(u'  joints freed: {0}', freed)

        for fid, fp in plan.fittings.items():
            el = m.fittings[fid]['el']
            if fp['angle'] > 1e-9:
                try:
                    axis = Line.CreateUnbound(to_xyz(fp['centre']), to_xyz(fp['axis']))
                    ElementTransformUtils.RotateElement(doc, el.Id, axis, fp['angle'])
                except Exception as ex:
                    log.add(u'  fitting {0} would not turn ({1}) - moved only', fid, ex)
            if core.v_len(fp['move']) > 1e-9:
                ElementTransformUtils.MoveElement(doc, el.Id, to_xyz(fp['move']))
            log.add(u'  fitting {0}: turned {1:.3f} deg, moved {2:.1f} mm', fid,
                    fp['angle'] * 57.29577951308232, core.ft_to_mm(fp['move'][2]))

        for pid, (a, b) in plan.pipes.items():
            set_curve(m.pipes[pid]['el'], a, b)
        for sid, (a, b) in plan.stretch.items():
            set_curve(m.stretch[sid]['el'], a, b)
            log.add(u'  stretched {0} {1}: {2} -> {3}', m.stretch[sid]['kind'], sid,
                    core.fmt_pt(m.stretch[sid]['ends'][0]), core.fmt_pt(a))

        doc.Regenerate()

        joined = 0
        for (a, ca, b, cb) in plan.joins:
            ea, eb = element_of(m, a), element_of(m, b)
            where_a = core.new_point_of(m, plan, a, ca) if m.in_scope(a) else None
            where_b = core.new_point_of(m, plan, b, cb) if m.in_scope(b) else None
            c1 = find_connector(ea, ca, where_a) if ea is not None else None
            c2 = find_connector(eb, cb, where_b) if eb is not None else None
            if c1 is None or c2 is None:
                join_fail.append((a, b, u'connector not found'))
                continue
            try:
                if c1.IsConnectedTo(c2):
                    joined += 1
                    continue
            except Exception:
                pass
            gap = core.ft_to_mm(core.v_len(core.v_sub(to_t(c1.Origin), to_t(c2.Origin))))
            if gap > core.JOIN_GIVE_UP_MM:
                join_fail.append((a, b, u'{0:.1f} mm apart'.format(gap)))
                continue
            try:
                c1.ConnectTo(c2)
                joined += 1
                if gap > core.JOIN_TOL_MM:
                    log.add(u'  joined {0} to {1} across {2:.1f} mm', a, b, gap)
            except Exception as ex:
                join_fail.append((a, b, core.text_type(ex)))
        log.add(u'  joints made: {0} of {1}', joined, len(plan.joins))

        doc.Regenerate()

        for el in pinned:
            try:
                el.Pinned = True
            except Exception:
                pass

        status = t.Commit()
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    return status, swallow.errors, join_fail


def committed(status):
    return status == TransactionStatus.Committed


def verify(m, plan, log):
    """Read everything back after commit - a commit regenerates, and a void
    API call is not evidence."""
    rows = []
    bad = 0
    for pid, p in sorted(m.pipes.items()):
        el = p['el']
        try:
            curve = el.Location.Curve
            a, b = to_t(curve.GetEndPoint(0)), to_t(curve.GetEndPoint(1))
        except Exception:
            rows.append(('bad', u'Pipe {0}: could not be read back.'.format(pid)))
            bad += 1
            continue
        before = core.ratio_text(core.gradient(p['ends'][0], p['ends'][1]))
        now = core.gradient(a, b)
        d0, d1 = plan.dist[('p', pid, 0)], plan.dist[('p', pid, 1)]
        right_way = (abs(d0 - d1) < 1e-6 or not core.fall_matters(a, b, plan.n)
                     or ((a[2] < b[2]) == (d0 < d1)))
        ok = core.fall_ok(a, b, plan.n) and right_way
        size = u''
        try:
            size = u' \u00d8{0:.0f}'.format(core.ft_to_mm(el.Diameter))
        except Exception:
            pass
        text = u'Pipe {0}{1}: {2} -> {3}{4}'.format(
            pid, size, before, core.ratio_text(now),
            u'' if right_way else u' - falls the wrong way')
        rows.append(('ok' if ok else 'bad', text))
        if not ok:
            bad += 1
        log.add(u'  {0}  ends {1} {2}', text, core.fmt_pt(a), core.fmt_pt(b))
    broken = []
    for (a, ca, b, cb) in plan.joins:
        ea, eb = element_of(m, a), element_of(m, b)
        c1 = find_connector(ea, ca, core.new_point_of(m, plan, a, ca) if m.in_scope(a) else None)
        c2 = find_connector(eb, cb, core.new_point_of(m, plan, b, cb) if m.in_scope(b) else None)
        ok = False
        try:
            ok = c1 is not None and c2 is not None and c1.IsConnectedTo(c2)
        except Exception:
            ok = False
        if not ok:
            broken.append((a, b))
    return rows, bad, broken
