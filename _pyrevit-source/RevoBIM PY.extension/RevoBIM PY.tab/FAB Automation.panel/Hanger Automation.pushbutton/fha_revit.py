# -*- coding: utf-8 -*-
u"""Hanger Automation - everything that touches the Revit API.

Three jobs, each run from the window through one ExternalEvent:
  job_rehost  re-host selected fabrication hangers on their nearest duct
  job_extend  run selected hangers' rods up to the soffit above
  job_place   place, host, size, extend and dimension hangers on a duct run

API used (checked against the 2024-2027 docs):
  FabricationPart.CreateHanger(doc, button, [condition,] hostId, Connector, distance, attach)
  FabricationHostedInfo.PlaceOnHost(hostId, Connector, distance)
  FabricationRodInfo  RodCount, GetRodEndPosition, GetRodLength (incl. structure
                      extension), SetRodLength (excl. it; returns bool; hanger must
                      not be auto-hosted), GetRodStructureExtension, AttachToStructure
  FabricationService  PaletteCount, GetButtonCount(p), GetButton(p, b)
  FabricationServiceButton  IsAHanger, ConditionCount, GetConditionLower/UpperValue,
                            IsUnrestrictedCondition
Hosting is always measured from a Connector object, never an index.
"""
import fha_clr  # noqa: F401  (must be first)
import fha_core as core
from Autodesk.Revit import DB
from Autodesk.Revit.DB import (
    Transaction, TransactionGroup, SubTransaction, FilteredElementCollector, FabricationPart,
    FabricationConfiguration, XYZ, Line, ReferenceArray, Options, PlanarFace,
    GeometryInstance, Solid, ElementId, IFailuresPreprocessor,
    FailureProcessingResult, FailureSeverity, ReferenceIntersector,
    FindReferenceTarget, ElementMulticategoryFilter, View3D, DimensionType,
    ViewFamilyType, WorksharingUtils, Element,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from System import Int64

MM = core.MM
ROD_TOL = 0.02          # ft, how close a rod top must be to the soffit
END_MARGIN = 0.1        # ft, never host a hanger closer than this to a joint
TAP_REACH = 2.5         # ft, plan offset within which a tap counts as on the run


# ================================================================ basics
def eid_value(eid):
    u"""ElementId -> int on every Revit version (.Value from 2024, gone .IntegerValue in 2026)."""
    if eid is None:
        return 0
    try:
        return int(eid.Value)
    except Exception:
        pass
    try:
        return int(eid.IntegerValue)
    except Exception:
        return 0


def ws_int(wsid):
    u"""WorksetId -> int (WorksetId keeps IntegerValue on every release)."""
    try:
        return int(wsid.IntegerValue)
    except Exception:
        return 0


def el_name(el):
    u"""Element.Name raises AttributeError on some IronPython builds."""
    try:
        return Element.Name.GetValue(el)
    except Exception:
        pass
    try:
        return el.Name
    except Exception:
        return u''


def bic(name):
    return getattr(DB.BuiltInCategory, name)


def _cat_is(el, name):
    try:
        return el.Category is not None and eid_value(el.Category.Id) == int(bic(name))
    except Exception:
        return False


def is_fab(el):
    return isinstance(el, FabricationPart)


def is_hanger(el):
    if not is_fab(el):
        return False
    try:
        if el.IsAHanger():
            return True
    except Exception:
        pass
    return _cat_is(el, 'OST_FabricationHangers')


def is_duct(el):
    return is_fab(el) and not is_hanger(el) and _cat_is(el, 'OST_FabricationDuctwork')


def is_tap(el):
    try:
        return bool(el.IsATap())
    except Exception:
        return False


def is_straight(el):
    try:
        return bool(el.IsAStraight())
    except Exception:
        return False


def pt(v):
    return (v.X, v.Y, v.Z)


def to_xyz(v):
    return XYZ(v[0], v[1], v[2])


# the running job's debug log (set by the window around each job), so a
# transaction Revit throws away says why in the log
CURRENT_LOG = [None]
_ERRORS = []


def _say(text):
    try:
        if CURRENT_LOG[0] is not None:
            CURRENT_LOG[0].add(text)
    except Exception:
        pass


class WarningSwallower(IFailuresPreprocessor):
    u"""Delete warnings so Revit does not stop the run with a dialog.  Errors
    are left to Revit (they undo the transaction) but noted for the log."""
    def PreprocessFailures(self, accessor):
        try:
            for f in list(accessor.GetFailureMessages()):
                if f.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(f)
                else:
                    try:
                        _ERRORS.append(u'{0}'.format(f.GetDescriptionText()))
                    except Exception:
                        _ERRORS.append(u'(an error Revit gave no text for)')
        except Exception:
            pass
        return FailureProcessingResult.Continue


def start_txn(doc, name):
    del _ERRORS[:]
    t = Transaction(doc, name)
    t.Start()
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return t


def committed(t):
    try:
        status = str(t.Commit())
    except Exception as ex:
        _say(u'   Revit refused to commit: {0}'.format(ex))
        try:
            t.RollBack()
        except Exception:
            pass
        return False
    if status != 'Committed':
        _say(u'   Revit undid "{0}" ({1}){2}'.format(_txn_name(t), status, u': ' + u' | '.join(_ERRORS) if _ERRORS
                                                     else u''))
    del _ERRORS[:]
    return status == 'Committed'


def _txn_name(t):
    try:
        return t.GetName()
    except Exception:
        return u'?'


def rollback(t):
    try:
        t.RollBack()
    except Exception:
        pass


class _FabFilter(ISelectionFilter):
    def __init__(self, want):
        self.want = want

    def AllowElement(self, e):
        return is_duct(e) if self.want == 'duct' else is_hanger(e)

    def AllowReference(self, r, p):
        return False


def get_selection(uidoc, want, prompt):
    u"""The current selection filtered to ducts / hangers, else ask for a pick."""
    doc = uidoc.Document
    keep = is_duct if want == 'duct' else is_hanger
    els = []
    for i in uidoc.Selection.GetElementIds():
        e = doc.GetElement(i)
        if e is not None and keep(e):
            els.append(e)
    if els:
        return els
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, _FabFilter(want), prompt)
        return [doc.GetElement(r.ElementId) for r in refs]
    except Exception:
        return []  # Esc


def checkout(doc, elements, log):
    try:
        if doc.IsWorkshared and elements:
            ids = List[ElementId]()
            for e in elements:
                ids.Add(e.Id)
            WorksharingUtils.CheckoutElements(doc, ids)
    except Exception as ex:
        log.add(u'checkout: {0}'.format(ex))


def user_worksets(doc):
    u"""[(name, id int)] of the model's user worksets, by name; [] if not workshared."""
    out = []
    try:
        if not doc.IsWorkshared:
            return out
        kind = getattr(DB.WorksetKind, 'UserWorkset')
        for ws in DB.FilteredWorksetCollector(doc).OfKind(kind):
            try:
                out.append((u'{0}'.format(ws.Name), ws_int(ws.Id)))
            except Exception:
                pass
    except Exception:
        pass
    out.sort(key=lambda x: x[0].lower())
    return out


def hanger_host(doc, h):
    u"""The service a fabrication hanger hangs from, if Revit knows it."""
    try:
        hid = h.GetHostedInfo().HostId
        return doc.GetElement(hid)
    except Exception:
        return None


class Worksets(object):
    u"""Puts placed and edited hangers on the workset chosen on the tab
    (see fha_core.WS_OPTIONS / workset_target).  One per job."""
    def __init__(self, doc, choice, log):
        self.doc, self.log = doc, log
        self.choice = choice or core.WS_LEAVE
        self.on = False
        self.active = self.named = None
        self.problems = []
        self.moved = 0
        self.last_moved = False
        try:
            self.on = bool(doc.IsWorkshared)
        except Exception:
            self.on = False
        if not self.on:
            if self.choice != core.WS_LEAVE:
                log.add(u'workset: the model is not workshared - nothing to set')
            return
        try:
            self.active = ws_int(doc.GetWorksetTable().GetActiveWorksetId())
        except Exception:
            self.active = None
        names = user_worksets(doc)
        if self.choice not in (core.WS_LEAVE, core.WS_SERVICE, core.WS_ACTIVE):
            for name, wid in names:
                if name == self.choice:
                    self.named = wid
            if self.named is None:
                self.problems.append(u'Workset "{0}" is not in this model - new hangers went on their '
                                     u'service\'s workset, edited ones were left where they were.'.format(self.choice))
        label = dict(core.WS_OPTIONS).get(self.choice, u'"{0}"'.format(self.choice))
        log.add(u'workset: {0}{1}'.format(label, u' (id {0})'.format(self.named) if self.named is not None else u''))

    def apply(self, el, service=None, new=True, like=None):
        u"""Move el to its workset.  service: what it serves (for 'same as the
        service'); like: the hanger it replaced (kept its workset under
        'leave as is').  Caller holds the transaction.  False if Revit refused."""
        if not self.on or el is None:
            return True
        svc = None
        if like is not None and self.choice == core.WS_LEAVE:
            svc = ws_int(like.WorksetId)
        elif service is not None:
            svc = ws_int(service.WorksetId)
        target = core.workset_target(self.choice, svc, self.active, self.named, new)
        self.last_moved = False
        if target is None:
            return True
        try:
            if ws_int(el.WorksetId) == target:
                return True
            p = el.get_Parameter(getattr(DB.BuiltInParameter, 'ELEM_PARTITION_PARAM'))
            if p is None or p.IsReadOnly:
                raise Exception(u'workset is read only')
            p.Set(target)
            self.last_moved = True
            self.moved += 1
            return True
        except Exception as ex:
            msg = u'Could not move a hanger to its workset (is it owned by someone else?)'
            if msg not in self.problems:
                self.problems.append(msg)
            self.log.add(u'   workset: element {0} not moved: {1}'.format(eid_value(el.Id), ex))
            return False


def match_workset(new_el, like_el):
    u"""Newly created elements go on the workset of the element they serve."""
    try:
        p = new_el.get_Parameter(getattr(DB.BuiltInParameter, 'ELEM_PARTITION_PARAM'))
        if p is not None and not p.IsReadOnly:
            p.Set(ws_int(like_el.WorksetId))
    except Exception:
        pass


# ============================================================ connectors
def all_conns(part):
    out = []
    try:
        for c in part.ConnectorManager.Connectors:
            out.append(c)
    except Exception:
        pass
    out.sort(key=lambda c: c.Id)
    return out


def axis(c):
    try:
        return pt(c.CoordinateSystem.BasisZ)
    except Exception:
        return (0.0, 0.0, 0.0)


def end_pair(part, cons):
    u"""(ends, sides): the two end connectors of a straight, and any side
    (tap) connectors cut into it.  Ends are the anti-parallel pair furthest apart."""
    if len(cons) <= 2:
        return cons, []
    best = None
    for i in range(len(cons)):
        for j in range(i + 1, len(cons)):
            if core.vdot(axis(cons[i]), axis(cons[j])) < -0.98:
                d = cons[i].Origin.DistanceTo(cons[j].Origin)
                if best is None or d > best[0]:
                    best = (d, i, j)
    if best is None:
        return cons[:2], cons[2:]
    ends = [cons[best[1]], cons[best[2]]]
    sides = [c for k, c in enumerate(cons) if k not in (best[1], best[2])]
    return ends, sides


def neighbour(c):
    u"""The connector joined to c on another fabrication part, or None."""
    try:
        own = eid_value(c.Owner.Id)
        for r in c.AllRefs:
            o = r.Owner
            if o is not None and eid_value(o.Id) != own and is_fab(o) and not is_hanger(o):
                return r
    except Exception:
        pass
    return None


def classify(part, cons):
    if is_tap(part):
        return 'tap'
    n = len(cons)
    if is_straight(part):
        return 'straight'
    if n == 1:
        return 'tap'
    if n == 2:
        return 'inline' if core.vdot(axis(cons[0]), axis(cons[1])) < -0.98 else 'bend'
    if n >= 3:
        return 'tee'
    return 'other'


def part_record(part):
    u"""fha_core part record, plus the Revit bits the jobs need:
    cobj (connector objects in conns order), pts (their origins), cid (Id -> index),
    sides (origins of tap connectors cut into a straight)."""
    cons = all_conns(part)
    kind = classify(part, cons)
    sides = []
    if kind == 'straight':
        cons, side = end_pair(part, cons)
        sides = [pt(c.Origin) for c in side]
    rec = {'kind': kind, 'len': 0.0, 'horizontal': True, 'conns': [],
           'cobj': cons, 'pts': [pt(c.Origin) for c in cons],
           'cid': dict((c.Id, k) for k, c in enumerate(cons)), 'sides': sides,
           'side_ids': set()}
    if kind == 'straight' and len(cons) == 2:
        a, b = rec['pts'][0], rec['pts'][1]
        rec['len'] = core.vlen(core.vsub(b, a))
        rec['horizontal'] = abs(b[2] - a[2]) < 0.1 * max(rec['len'], 1e-6)
        rec['side_ids'] = set(c.Id for c in all_conns(part)) - set(c.Id for c in cons)
    elif len(cons) >= 2:
        rec['len'] = core.vlen(core.vsub(rec['pts'][1], rec['pts'][0]))
    for c in cons:
        role = None
        if kind == 'tee':
            role = 'branch'
            for o in cons:
                if o is not c and abs(core.vdot(axis(c), axis(o))) > 0.98:
                    role = 'main'
        rec['conns'].append({'to': None, 'to_conn': None, 'role': role, '_nb': neighbour(c)})
    return rec


def build_graph(seeds, whole_system, log):
    u"""parts (fha_core shape) and elems, for the selected ducts.

    'Selected run only' keeps the selection plus one ring of neighbours, which
    only type the ends of the spans (a neighbouring straight becomes a plain
    boundary so it never gets hangers of its own).  'Whole connected system'
    walks everything connected.
    """
    elems, parts = {}, {}
    todo = list(seeds)
    seen = set(eid_value(e.Id) for e in seeds)
    selected = set(seen)
    while todo:
        e = todo.pop()
        pid = eid_value(e.Id)
        elems[pid] = e
        parts[pid] = part_record(e)
        for c in parts[pid]['conns']:
            nb = c['_nb']
            if nb is None:
                continue
            o = nb.Owner
            nid = eid_value(o.Id)
            if nid in seen:
                continue
            seen.add(nid)
            if whole_system and is_duct(o):
                selected.add(nid)
                todo.append(o)
            else:
                elems[nid] = o
                rec = part_record(o)
                if rec['kind'] == 'straight' or not is_duct(o):
                    rec['kind'] = 'other'
                parts[nid] = rec
    # resolve links now every record exists
    taps = {}
    for pid, rec in parts.items():
        for c in rec['conns']:
            nb = c.pop('_nb', None)
            if nb is None:
                continue
            nid = eid_value(nb.Owner.Id)
            if nid not in parts or pid not in selected:
                continue
            other = parts[nid]
            if nb.Id in other['cid']:
                c['to'], c['to_conn'] = nid, other['cid'][nb.Id]
            elif nb.Id in other.get('side_ids', ()):
                # this run starts at a tap cut into another straight: a takeoff
                key = -nid
                taps[key] = {'kind': 'tap', 'len': 0.0, 'horizontal': True, 'conns': []}
                c['to'], c['to_conn'] = key, None
    parts.update(taps)
    log.add(u'graph: {0} parts, {1} selected, {2} takeoff ends'.format(len(parts), len(selected), len(taps)))
    return parts, elems, selected


def all_tap_points(doc):
    u"""Origins of every fabrication tap in the model (taps hosted on a straight
    are not always joined to it through a connector)."""
    out = []
    try:
        col = FilteredElementCollector(doc).OfCategory(bic('OST_FabricationDuctwork')).WhereElementIsNotElementType()
        for e in col:
            if is_fab(e) and is_tap(e):
                try:
                    out.append(pt(e.Origin))
                except Exception:
                    pass
    except Exception:
        pass
    return out


# ======================================================== hanger buttons
def hanger_buttons(doc):
    u"""[(label, service_id, button)] for every hanger button in the loaded services."""
    out = []
    try:
        cfg = FabricationConfiguration.GetFabricationConfiguration(doc)
        if cfg is None:
            return out
        for svc in cfg.GetAllLoadedServices():
            try:
                for p in range(svc.PaletteCount):
                    for b in range(svc.GetButtonCount(p)):
                        btn = svc.GetButton(p, b)
                        if btn is not None and btn.IsAHanger:
                            out.append((u'{0} : {1}'.format(svc.Name, btn.Name), svc.ServiceId, btn))
            except Exception:
                continue
    except Exception:
        pass
    return out


def duct_size_ft(el):
    u"""The size hanger conditions are keyed on: width, else diameter, else largest."""
    vals = {}
    try:
        for d in el.GetDimensions():
            try:
                vals[(d.Name or u'').strip().lower()] = float(el.GetDimensionValue(d))
            except Exception:
                pass
    except Exception:
        pass
    for k in (u'width', u'diameter', u'main width', u'main diameter'):
        if vals.get(k, 0) > 0:
            return vals[k]
    return max([0.0] + list(vals.values()))


def button_conditions(btn):
    u"""[(index, lower, upper, unrestricted)] for a hanger button."""
    conds = []
    try:
        for i in range(btn.ConditionCount):
            try:
                unr = bool(btn.IsUnrestrictedCondition(i))
            except Exception:
                unr = False
            conds.append((i, btn.GetConditionLowerValue(i), btn.GetConditionUpperValue(i), unr))
    except Exception:
        pass
    return conds


def condition_for(btn, size_ft):
    u"""(fits, condition index) - a button with no conditions fits anything."""
    conds = button_conditions(btn)
    if not conds:
        return True, None
    idx = core.pick_condition(conds, size_ft)
    return idx is not None, idx


class ButtonPicker(object):
    u"""Chooses the hanger button and condition for a duct, cached per size."""
    def __init__(self, doc, wanted, log):
        self.all = hanger_buttons(doc)
        self.wanted = (wanted or u'').strip()
        self.log = log
        self.cache = {}

    def _candidates(self, service_id):
        if self.wanted:
            exact = [b for b in self.all if b[0] == self.wanted]
            if exact:
                return exact
            low = self.wanted.lower()
            part = [b for b in self.all if low in b[0].lower()]
            if part:
                return part
            self.log.add(u'button "{0}" not found, choosing automatically'.format(self.wanted))
        same = [b for b in self.all if b[1] == service_id]
        return same or self.all

    def pick(self, host):
        try:
            sid = host.ServiceId
        except Exception:
            sid = None
        size = duct_size_ft(host)
        key = (sid, round(size, 4))
        if key in self.cache:
            return self.cache[key]
        choice = (None, None, None)
        for label, _sid, btn in self._candidates(sid):
            fits, idx = condition_for(btn, size)
            if fits:
                choice = (label, btn, idx)
                break
            if choice[1] is None:
                choice = (label, btn, None)  # keep looking for a better fit
        self.log.add(u'button for {0:.0f} mm: {1} condition {2}'.format(size * MM, choice[0], choice[2]))
        self.cache[key] = choice
        return choice


# ================================================================ comments
def family_type_label(el):
    u"""'Family : Type' of a service - a FAB part by its service and part name."""
    try:
        if isinstance(el, FabricationPart):
            svc = u'{0}'.format(el.ServiceName or u'').strip()
            name = u'{0}'.format(el.Name or u'').strip()
            if svc or name:
                return u' : '.join(x for x in (svc, name) if x)
    except Exception:
        pass
    try:
        t = el.Document.GetElement(el.GetTypeId())
        fam = u'{0}'.format(t.FamilyName or u'').strip()
        typ = u'{0}'.format(el_name(t)).strip()
        if fam or typ:
            return u' : '.join(x for x in (fam, typ) if x)
    except Exception:
        pass
    try:
        p = el.get_Parameter(getattr(DB.BuiltInParameter, 'ELEM_FAMILY_AND_TYPE_PARAM'))
        v = p.AsValueString() if p is not None else None
        if v:
            return u'{0}'.format(v).replace(u': ', u' : ')
    except Exception:
        pass
    return u''


def write_service_comment(hanger, services, log):
    u"""Write the family and type of the service(s) a hanger carries into its
    Comments ('2xCable Tray : Ladder, Pipe Types : Copper').  Caller holds the
    transaction.  Returns the text written, or None."""
    if hanger is None:
        return None
    text = core.service_comment([family_type_label(s) for s in services if s is not None])
    if not text:
        return None
    try:
        p = hanger.get_Parameter(getattr(DB.BuiltInParameter, 'ALL_MODEL_INSTANCE_COMMENTS'))
        if p is None or p.IsReadOnly:
            log.add(u'   comments: no writable Comments parameter')
            return None
        p.Set(text)
        log.add(u'   comments: {0}'.format(text))
        return text
    except Exception as ex:
        log.add(u'   comments: {0}'.format(ex))
        return None


def services_of(doc, sec, fallback):
    u"""The service elements a hanger goes round: every service in a shared
    hanger (sec['keys']), else the one it hangs from."""
    out = []
    for k in sec.get('keys') or []:
        e = None
        for make in (lambda: ElementId(Int64(k)), lambda: ElementId(int(k))):   # Int64 from 2024, int before
            try:
                e = doc.GetElement(make())
                break
            except Exception:
                pass
        if e is not None:
            out.append(e)
    return out or [fallback]


# ================================================================ hangers
def create_hanger(doc, btn, cond, host, conn, dist_ft, log):
    u"""CreateHanger with the condition overload first, then without."""
    tries = []
    if cond is not None:
        tries.append((btn, int(cond), host.Id, conn, float(dist_ft), False))
    tries.append((btn, host.Id, conn, float(dist_ft), False))
    last = None
    for args in tries:
        try:
            h = FabricationPart.CreateHanger(doc, *args)
            if h is not None:
                write_service_comment(h, [host], log)
                return h
        except Exception as ex:
            last = ex
    log.add(u'CreateHanger refused on {0}: {1}'.format(eid_value(host.Id), last))
    return None


def place_on_host(hanger, host, conn, dist_ft, log):
    info = hanger.GetHostedInfo()
    last = None
    for disconnect_first in (False, True):
        try:
            if disconnect_first:
                info.DisconnectFromHost()
            info.PlaceOnHost(host.Id, conn, float(dist_ft))
            write_service_comment(hanger, [host], log)
            return True
        except Exception as ex:
            last = ex
    log.add(u'PlaceOnHost refused for hanger {0}: {1}'.format(eid_value(hanger.Id), last))
    return False


def host_of(hanger):
    try:
        return eid_value(hanger.GetHostedInfo().HostId)
    except Exception:
        return 0


def size_to_host(hanger, host, log):
    u"""Copy width / diameter / depth onto same-named hanger dimensions where they differ."""
    changed = 0
    try:
        hd = dict(((d.Name or u'').strip().lower(), d) for d in hanger.GetDimensions())
        for d in host.GetDimensions():
            k = (d.Name or u'').strip().lower()
            if k in hd and k in (u'width', u'diameter', u'depth', u'height'):
                v = host.GetDimensionValue(d)
                try:
                    if abs(hanger.GetDimensionValue(hd[k]) - v) > 1e-6:
                        hanger.SetDimensionValue(hd[k], v)
                        changed += 1
                except Exception:
                    pass
    except Exception as ex:
        log.add(u'size_to_host: {0}'.format(ex))
    return changed


def hanger_point(h):
    try:
        return pt(h.Origin)
    except Exception:
        pass
    try:
        bb = h.get_BoundingBox(None)
        return ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)
    except Exception:
        return None


def hanger_bottom_z(h):
    try:
        return h.get_BoundingBox(None).Min.Z
    except Exception:
        p = hanger_point(h)
        return p[2] if p else None


def straight_hosts(doc):
    u"""Horizontal fabrication duct straights as fha_core hosts, plus id -> (element, ends)."""
    hosts, info = [], {}
    col = FilteredElementCollector(doc).OfCategory(bic('OST_FabricationDuctwork')).WhereElementIsNotElementType()
    for e in col:
        if not is_duct(e) or not is_straight(e):
            continue
        ends, _s = end_pair(e, all_conns(e))
        if len(ends) != 2:
            continue
        a, b = pt(ends[0].Origin), pt(ends[1].Origin)
        L = core.vlen(core.vsub(b, a))
        hid = eid_value(e.Id)
        hosts.append({'id': hid, 'a': a, 'b': b, 'horizontal': abs(a[2] - b[2]) < 0.1 * max(L, 1e-6)})
        info[hid] = (e, ends)
    return hosts, info


# ===================================================== replacing a hanger
def hanger_signature(h):
    u"""What identifies the kind of hanger, size aside."""
    def get(name):
        try:
            return getattr(h, name)
        except Exception:
            return None
    return {'name': el_name(h), 'product': get('ProductName'), 'alias': get('Alias'),
            'item_id': get('ItemCustomId'), 'code': get('ProductCode'),
            'service': get('ServiceId')}


class HangerMatcher(object):
    u"""Finds the hanger button that makes the same kind of hanger as an existing one.

    Revit does not say which button a hanger came from, so each candidate button
    in the hanger's own service is tried for real inside a SubTransaction that is
    rolled back, and the result compared with the old hanger (item id, product,
    size-free name words).  The answer is cached per kind of hanger.
    """
    MAX_PROBES = 16

    def __init__(self, doc, wanted, log):
        self.doc = doc
        self.log = log
        self.picker = ButtonPicker(doc, wanted, log)
        self.cache = {}

    def _probe(self, btn, host, conn, dist):
        size = duct_size_ft(host)
        fits, cond = condition_for(btn, size)
        if not fits:
            return None
        st = SubTransaction(self.doc)
        st.Start()
        try:
            h = create_hanger(self.doc, btn, cond, host, conn, dist, self.log)
            return hanger_signature(h) if h is not None else None
        except Exception:
            return None
        finally:
            try:
                st.RollBack()
            except Exception:
                pass

    def button_for(self, old, host, conn, dist):
        u"""(label, button, how) for re-creating `old` on `host`."""
        sig = hanger_signature(old)
        key = (sig['service'], sig['item_id'], sig['product'], tuple(sorted(core.name_tokens(sig['name']))))
        if key in self.cache:
            return self.cache[key]
        same = [b for b in self.picker.all if b[1] == sig['service']]
        choice = None
        if len(same) == 1:
            choice = (same[0][0], same[0][2], u'only hanger button in its service')
        elif same:
            best = None
            for label, _sid, btn in same[:self.MAX_PROBES]:
                got = self._probe(btn, host, conn, dist)
                if got is None:
                    continue
                score = core.signature_score(sig, got)
                self.log.add(u'  probe {0}: score {1:.2f}'.format(label, score))
                if best is None or score > best[0]:
                    best = (score, label, btn)
            if best is not None and best[0] > 0:
                choice = (best[1], best[2], u'matched to the existing hanger ({0:.1f})'.format(best[0]))
        if choice is None:
            label, btn, _c = self.picker.pick(host)
            if btn is not None:
                choice = (label, btn, u'no match - automatic choice for the duct')
        if choice is None:
            choice = (None, None, u'no hanger buttons loaded')
        self.log.add(u'hanger {0} ({1}) -> {2}: {3}'.format(
            eid_value(old.Id), sig['name'], choice[0], choice[2]))
        self.cache[key] = choice
        return choice


USER_PARAMS = (u'Comments', u'Mark')


def copy_user_params(old, new, log):
    u"""Comments, Mark and every writable shared parameter, old -> new."""
    copied = 0
    try:
        params = list(old.Parameters)
    except Exception:
        params = []
    for p in params:
        try:
            if p.IsReadOnly or not p.HasValue:
                continue
            name = p.Definition.Name
            shared = False
            try:
                shared = bool(p.IsShared)
            except Exception:
                pass
            if not shared and name not in USER_PARAMS:
                continue
            q = new.get_Parameter(p.GUID) if shared else new.LookupParameter(name)
            if q is None or q.IsReadOnly:
                continue
            kind = str(p.StorageType)
            if kind == 'String':
                q.Set(p.AsString() or u'')
            elif kind == 'Integer':
                q.Set(p.AsInteger())
            elif kind == 'Double':
                q.Set(p.AsDouble())
            else:
                continue
            copied += 1
        except Exception as ex:
            log.add(u'copy parameter: {0}'.format(ex))
    return copied


def copy_workset(old, new):
    try:
        bip = getattr(DB.BuiltInParameter, 'ELEM_PARTITION_PARAM')
        p = new.get_Parameter(bip)
        if p is not None and not p.IsReadOnly:
            p.Set(ws_int(old.WorksetId))
    except Exception:
        pass


def rod_tops(h):
    try:
        info = h.GetRodInfo()
        return [info.GetRodEndPosition(i).Z for i in range(info.RodCount)]
    except Exception:
        return []


def set_rod_tops(doc, h, tops, log):
    u"""Give a new hanger's rods the old hanger's top levels (before any extend)."""
    if not tops:
        return
    try:
        info = h.GetRodInfo()
        try:
            info.CanRodsBeHosted = False
        except Exception:
            pass
        for i in range(min(info.RodCount, len(tops))):
            end = info.GetRodEndPosition(i)
            target = core.rod_target_length(info.GetRodLength(i), end.Z, tops[i], 0.0)
            if target > 0:
                info.SetRodLength(i, target)
        doc.Regenerate()
    except Exception as ex:
        log.add(u'rod tops: {0}'.format(ex))


def replace_hanger(doc, old, host, conn, dist, matcher, log, ws=None):
    u"""Delete `old` and place a new hanger on `host`, exactly as a fresh
    placement would - same kind of hanger, condition and size from the duct -
    keeping its workset, Comments, Mark, shared parameters and rod tops.
    Caller holds the transaction.  Returns (new hanger or None, note)."""
    label, btn, how = matcher.button_for(old, host, conn, dist)
    if btn is None:
        return None, how
    fits, cond = condition_for(btn, duct_size_ft(host))
    tops = rod_tops(old)
    new = create_hanger(doc, btn, cond, host, conn, dist, log)
    if new is None:
        return None, u'Revit refused to create {0} here'.format(label)
    if ws is not None:
        ws.apply(new, host, True, like=old)
    else:
        copy_workset(old, new)
    copy_user_params(old, new, log)
    doc.Delete(old.Id)
    set_rod_tops(doc, new, tops, log)
    return new, u'{0} ({1})'.format(label, how)


# ================================================================== rods
STRUCTURE_KEYS = (('ext_floors', 'OST_Floors'), ('ext_framing', 'OST_StructuralFraming'),
                  ('ext_roofs', 'OST_Roofs'))


class Soffit(object):
    u"""Ray casts up to structure through a temporary, clean 3D view.

    A view the user owns may hide floors or have a section box, and a
    ReferenceIntersector only sees what its view shows, so a fresh isometric
    view is made inside the run's transaction group and deleted at the end.
    """
    def __init__(self, doc, settings, log):
        self.doc = doc
        self.log = log
        self.view = None
        self.ri = None
        self.temp = False
        self.reason = u''
        cats = List[DB.BuiltInCategory]()
        for key, name in STRUCTURE_KEYS:
            if core.as_bool(settings, key):
                cats.Add(bic(name))
        if cats.Count == 0:
            self.reason = u'no structure category ticked'
            return
        t = start_txn(doc, u'Temporary 3D view')
        try:
            vft = None
            for v in FilteredElementCollector(doc).OfClass(ViewFamilyType):
                if str(v.ViewFamily) == 'ThreeDimensional':
                    vft = v
                    break
            self.view = View3D.CreateIsometric(doc, vft.Id)
            try:
                self.view.ViewTemplateId = ElementId.InvalidElementId
            except Exception:
                pass
            try:
                self.view.IsSectionBoxActive = False
            except Exception:
                pass
            if committed(t):
                self.temp = True
            else:
                self.view = None
        except Exception as ex:
            rollback(t)
            self.view = None
            log.add(u'temporary 3D view: {0}'.format(ex))
        if self.view is None:
            for v in FilteredElementCollector(doc).OfClass(View3D):
                if not v.IsTemplate:
                    self.view = v
                    log.add(u'using existing 3D view {0}'.format(el_name(v)))
                    break
        if self.view is None:
            self.reason = u'no 3D view to cast from'
            return
        self.ri = ReferenceIntersector(ElementMulticategoryFilter(cats), FindReferenceTarget.Face, self.view)
        try:
            self.ri.FindReferencesInRevitLinks = True
        except Exception:
            pass

    def ok(self):
        return self.ri is not None

    def above(self, x, y, z):
        u"""Z of the first structure face above (x, y, z), or None."""
        try:
            hit = self.ri.FindNearest(XYZ(x, y, z), XYZ.BasisZ)
            if hit is not None:
                return hit.GetReference().GlobalPoint.Z
        except Exception as ex:
            self.log.add(u'ray: {0}'.format(ex))
        return None

    def close(self):
        if self.view is None or not self.temp:
            return  # never delete a view this run did not make
        t = start_txn(self.doc, u'Remove temporary 3D view')
        try:
            self.doc.Delete(self.view.Id)
            committed(t)
        except Exception:
            rollback(t)


def extend_rods(doc, hanger, soffit, log, allow_attach=True):
    u"""Run every rod of one hanger up to the soffit above it.

    Returns 'extended', 'already', 'attached' or 'failed'.  Caller holds a
    transaction.  Each rod is read back after a regenerate.
    """
    try:
        info = hanger.GetRodInfo()
        n = info.RodCount
    except Exception as ex:
        log.add(u'hanger {0}: no rod info ({1})'.format(eid_value(hanger.Id), ex))
        return 'failed'
    if n == 0:
        return 'failed'
    base_z = hanger_bottom_z(hanger)
    try:
        if info.CanRodsBeHosted:
            info.CanRodsBeHosted = False  # SetRodLength refuses an auto-hosted hanger
    except Exception:
        pass
    targets = {}
    already = 0
    for i in range(n):
        try:
            end = info.GetRodEndPosition(i)
            # cast from under the hanger: a rod already pushed into the slab
            # would otherwise see the slab's top face as the next soffit
            start_z = min(end.Z, base_z) - 0.05 if base_z is not None else end.Z - 1.0
            hit = soffit.above(end.X, end.Y, start_z) if soffit.ok() else None
            if hit is None:
                continue
            ext = 0.0
            try:
                ext = info.GetRodStructureExtension(i)
            except Exception:
                pass
            if core.rod_ok(end.Z, hit, ext, ROD_TOL):
                already += 1
                continue
            target = core.rod_target_length(info.GetRodLength(i), end.Z, hit, ext)
            if target <= 0:
                log.add(u'hanger {0} rod {1}: soffit below rod start'.format(eid_value(hanger.Id), i))
                continue
            if info.SetRodLength(i, target) is False:
                log.add(u'hanger {0} rod {1}: SetRodLength refused {2:.0f} mm'.format(eid_value(hanger.Id), i, target * MM))
                continue
            targets[i] = (hit, ext)
        except Exception as ex:
            log.add(u'hanger {0} rod {1}: {2}'.format(eid_value(hanger.Id), i, ex))
    if targets:
        try:
            doc.Regenerate()
        except Exception:
            pass
        good = 0
        for i, (hit, ext) in targets.items():
            try:
                if core.rod_ok(info.GetRodEndPosition(i).Z, hit, ext, ROD_TOL * 5):
                    good += 1
            except Exception:
                pass
        if good:
            return 'extended'
    if already == n:
        return 'already'
    if allow_attach:
        try:
            info.AttachToStructure()
            doc.Regenerate()
            if info.IsAttachedToStructure:
                return 'attached'
        except Exception as ex:
            log.add(u'hanger {0}: AttachToStructure {1}'.format(eid_value(hanger.Id), ex))
    return 'failed'


# ============================================================ dimensions
DIM_VIEW_TYPES = ('FloorPlan', 'CeilingPlan', 'EngineeringPlan', 'AreaPlan',
                  'Section', 'Elevation', 'Detail')


def can_dimension_in(view):
    try:
        return (not isinstance(view, View3D)) and str(view.ViewType) in DIM_VIEW_TYPES
    except Exception:
        return False


def faces_across(el, direction, view):
    u"""Planar faces of el whose normal runs along `direction`, with references."""
    out = []
    for use_view in (True, False):
        opt = Options()
        opt.ComputeReferences = True
        if use_view and view is not None:
            opt.View = view
        else:
            opt.DetailLevel = getattr(DB.ViewDetailLevel, 'Fine')

        def walk(geo):
            for g in geo:
                if isinstance(g, GeometryInstance):
                    walk(g.GetInstanceGeometry())
                elif isinstance(g, Solid):
                    for f in g.Faces:
                        if isinstance(f, PlanarFace) and f.Reference is not None:
                            if abs(core.vdot(pt(f.FaceNormal), direction)) > 0.99:
                                out.append(f)
        try:
            geo = el.get_Geometry(opt)
            if geo is not None:
                walk(geo)
        except Exception:
            pass
        if out:
            break
    return out


def _t(face, origin, direction):
    return core.vdot(core.vsub(pt(face.Origin), origin), direction)


# ---- views to dimension in (the active one, or chosen in the Dimension views picker)
def view_dim_line(view, p_start, p_end, offset_mm):
    u"""(p0, p1) of a run's dimension line in this view: offset to the side in a
    plan, below the run and in the view plane in a section / elevation."""
    try:
        if str(view.ViewType) not in core.PLAN_VIEW_TYPES:
            return core.dim_line_in_view(p_start, p_end, offset_mm, pt(view.UpDirection), pt(view.ViewDirection),
                                         pt(view.Origin))
    except Exception:
        pass
    p0, p1, _n = core.dim_line(p_start, p_end, offset_mm)
    try:   # in a plan the line sits on the view's own level
        z = view.GenLevel.ProjectElevation
        p0, p1 = (p0[0], p0[1], z), (p1[0], p1[1], z)
    except Exception:
        pass
    return p0, p1


def run_fits_view(view, p_start, p_end):
    u"""A plan takes any horizontal run; a section only a run along it."""
    try:
        if str(view.ViewType) in core.PLAN_VIEW_TYPES:
            return True
        r = pt(view.RightDirection)
        return abs(core.vdot(core.vnorm(core.vsub(p_end, p_start)), core.vnorm(r))) > 0.999
    except Exception:
        return True


def dim_view_rows(doc):
    u"""[{'key', 'id', 'name', 'type', 'scale'}] - every plan / section view a run can be dimensioned in."""
    rows = []
    for v in FilteredElementCollector(doc).OfClass(DB.View):
        try:
            if v.IsTemplate or not can_dimension_in(v):
                continue
            rows.append({'key': eid_value(v.Id), 'id': v.Id, 'name': el_name(v), 'type': str(v.ViewType),
                         'scale': v.Scale})
        except Exception:
            pass
    return rows


def dim_sheet_rows(doc, ok_keys):
    u"""[{'key', 'id', 'number', 'name', 'views': [view keys]}] - sheets carrying such a view."""
    out = []
    for sh in FilteredElementCollector(doc).OfClass(DB.ViewSheet):
        try:
            if sh.IsPlaceholder:
                continue
        except Exception:
            pass
        try:
            placed = [eid_value(i) for i in sh.GetAllPlacedViews()]
        except Exception:
            placed = []
        views = [k for k in placed if k in ok_keys]
        if views:
            out.append({'key': eid_value(sh.Id), 'id': sh.Id, 'number': u'{0}'.format(sh.SheetNumber),
                        'name': el_name(sh), 'views': views})
    return out


class DimTargets(object):
    u"""The views a run's dimensions go in, and how many runs each got."""
    def __init__(self, views, active=False, sheets=None):
        self.views = views
        self.active = active
        self.sheets = sheets or []    # [(sheet element, [view keys])] ticked in the picker
        self.count = {}

    def add(self, view):
        k = eid_value(view.Id)
        self.count[k] = self.count.get(k, 0) + 1

    def summary(self, dimmed, runs):
        if self.active:
            return u'{0} of {1} runs dimensioned in {2}.'.format(dimmed, runs, el_name(self.views[0]))
        got = len([v for v in self.views if self.count.get(eid_value(v.Id))])
        return u'{0} of {1} runs dimensioned, in {2} of the {3} views chosen.'.format(dimmed, runs, got, len(self.views))


def dim_targets(uidoc, settings, key, res, log):
    u"""Where this run's dimensions go, or None for none.  The active view if
    it can take dimensions; otherwise (a 3D view) the user is asked - skip, or
    tick sheets and views in the picker (settings['_ui']).  Call before any
    transaction group."""
    if not core.as_bool(settings, key):
        return None
    view = uidoc.ActiveView
    if can_dimension_in(view):
        return DimTargets([view], True)
    ui = settings.get(u'_ui')
    if ui is None:
        res['lines'].append(u'Dimensions skipped: open a plan or section view to get them.')
        return None
    doc = uidoc.Document
    rows = dim_view_rows(doc)
    sheets = dim_sheet_rows(doc, set(r['key'] for r in rows))
    try:
        choice = ui.choose_dim_views(el_name(view), rows, sheets)
    except Exception as ex:
        log.add(u'dimension views: {0}'.format(ex))
        choice = None
    if not choice:
        res['lines'].append(u'Dimension placement skipped.')
        log.add(u'dimensions: skipped from {0}'.format(el_name(view)))
        return None
    by_key = dict((r['key'], r) for r in rows)
    keys = core.chosen_views(choice.get('views', []), choice.get('sheets', []), sheets)
    views = [v for v in (doc.GetElement(by_key[k]['id']) for k in keys if k in by_key) if v is not None]
    chosen = [(doc.GetElement(r['id']), r['views']) for r in sheets if r['key'] in choice.get('sheets', [])]
    log.add(u'dimensions: in {0} views - {1}'.format(len(views), u', '.join(el_name(v) for v in views[:20])))
    return DimTargets(views, False, [(sh, ks) for sh, ks in chosen if sh is not None])


def dimension_in_targets(doc, targets, p_start, p_end, place, log):
    u"""Dimension one run in every target view (each its own transaction).
    place(view) -> hangers dimensioned.  True if any view took it."""
    got = False
    for v in targets.views:
        if not run_fits_view(v, p_start, p_end):
            log.add(u'dimension: the run does not lie along {0} - not dimensioned there'.format(el_name(v)))
            continue
        t = start_txn(doc, u'Hanger dimension')
        try:
            n = place(v)
            if n and committed(t):
                targets.add(v)
                got = True
            elif not n:
                rollback(t)
        except Exception as ex:
            log.add(u'dimension in {0}: {1}'.format(el_name(v), ex))
            rollback(t)
    return got


def open_views(uidoc, views, log):
    for v in views:
        try:
            uidoc.ActiveView = v
        except Exception as ex:
            try:
                uidoc.RequestViewChange(v)
            except Exception:
                log.add(u'open {0}: {1}'.format(el_name(v), ex))


def offer_open(uidoc, settings, targets, runs, log):
    u"""After a run dimensioned in chosen views: ask whether to open them (or
    the ticked sheets they are on).  Call with no transaction open."""
    if targets is None or targets.active or not runs:
        return
    ui = settings.get(u'_ui')
    done = [v for v in targets.views if targets.count.get(eid_value(v.Id))]
    if ui is None or not done:
        return
    sheets = [sh for sh, keys in targets.sheets if any(targets.count.get(k) for k in keys)]
    try:
        ans = ui.ask_open(runs, [el_name(v) for v in done],
                          [u'{0} - {1}'.format(sh.SheetNumber, el_name(sh)) for sh in sheets])
    except Exception as ex:
        log.add(u'open views: {0}'.format(ex))
        return
    pick = sheets if ans == u'sheets' else (done if ans == u'views' else [])
    log.add(u'opening {0} {1}'.format(len(pick), ans or u'nothing'))
    open_views(uidoc, pick, log)


def chain_dimension(doc, view, p_start, p_end, hangers, first_el, last_el, settings, dim_type, log):
    u"""One chained dimension along a span: run start, every hanger, run end.

    Hangers use the face pointing back toward the run start, so the spacing
    between hangers reads true.  Returns the number of hangers dimensioned.
    """
    try:
        doc.Regenerate()   # hangers placed this run need geometry before another view can reference them
    except Exception:
        pass
    d = core.vnorm(core.vsub(p_end, p_start))
    items = []
    for h in hangers:
        fs = faces_across(h, d, view)
        hp = hanger_point(h)
        if not fs or hp is None:
            continue
        th = core.vdot(core.vsub(hp, p_start), d)
        back = [f for f in fs if core.vdot(pt(f.FaceNormal), d) < 0] or fs
        best = min(back, key=lambda f: abs(_t(f, p_start, d) - th))
        items.append((_t(best, p_start, d), best.Reference))
    n_h = len(items)
    items_h = list(items)
    for el, at_end in ((first_el, False), (last_el, True)):
        fs = faces_across(el, d, view)
        if fs:
            f = max(fs, key=lambda f: _t(f, p_start, d)) if at_end else min(fs, key=lambda f: _t(f, p_start, d))
            items.append((_t(f, p_start, d), f.Reference))
    items = core.collapse_refs(items, 0.01)
    if len(items) < 2 or n_h == 0:
        log.add(u'dimension skipped: {0} references ({1} hangers)'.format(len(items), n_h))
        return 0
    refs = ReferenceArray()
    for _t0, r in items:
        refs.Append(r)
    p0, p1 = view_dim_line(view, p_start, p_end, core.as_float(settings, u'dim_offset', 800.0))
    line = Line.CreateBound(to_xyz(p0), to_xyz(p1))
    for label, chosen in ((u'run ends and hangers', items), (u'hangers only', None)):
        if chosen is None:   # the full chain was refused: the hangers alone
            if n_h < 2:
                break
            chosen = core.collapse_refs(items_h, 0.01)
            refs = ReferenceArray()
            for _t0, r in chosen:
                refs.Append(r)
        try:
            if dim_type is not None:
                doc.Create.NewDimension(view, line, refs, dim_type)
            else:
                doc.Create.NewDimension(view, line, refs)
            log.add(u'dimension in {0}: {1}, {2} references'.format(el_name(view), label, len(chosen)))
            return n_h
        except Exception as ex:
            log.add(u'NewDimension refused in {0} ({1}): {2}'.format(el_name(view), label, ex))
    return 0


def linear_dimension_types(doc):
    u"""[(name, DimensionType)] for linear dimension styles."""
    out = []
    linear = getattr(DB.DimensionStyleType, 'Linear', None)
    try:
        for t in FilteredElementCollector(doc).OfClass(DimensionType):
            try:
                if linear is not None and t.StyleType != linear:
                    continue
            except Exception:
                pass
            nm = el_name(t)
            if nm:
                out.append((nm, t))
    except Exception:
        pass
    out.sort(key=lambda x: x[0].lower())
    return out


def find_dim_type(doc, name):
    if not name:
        return None
    for nm, t in linear_dimension_types(doc):
        if nm == name:
            return t
    return None


# ================================================================== jobs
def new_result(title):
    return {'title': title, 'done': 0, 'skipped': 0, 'failed': 0, 'lines': []}


def job_extend(uidoc, settings, log, hangers=None):
    doc = uidoc.Document
    res = new_result(u'Extend hangers to structure')
    if hangers is None:
        hangers = get_selection(uidoc, 'hanger', u'Select fabrication hangers to extend to structure')
    if not hangers:
        res['lines'].append(u'No fabrication hangers selected.')
        return res
    checkout(doc, hangers, log)
    ws = Worksets(doc, settings.get(u'workset', u''), log)
    tally = {'extended': 0, 'already': 0, 'attached': 0, 'failed': 0}
    tg = TransactionGroup(doc, u'Hanger Automation - extend rods')
    tg.Start()
    soffit = Soffit(doc, settings, log)
    try:
        if not soffit.ok():
            res['lines'].append(u'Using Revit attach to structure only: {0}.'.format(soffit.reason))
        for h in hangers:
            t = start_txn(doc, u'Extend rods')
            moved = False
            try:
                ws.apply(h, hanger_host(doc, h), False)
                moved = ws.last_moved
                outcome = extend_rods(doc, h, soffit, log)
            except Exception as ex:
                log.add(u'extend {0}: {1}'.format(eid_value(h.Id), ex))
                outcome = 'failed'
            if outcome == 'already' and moved:
                committed(t)   # rods fine, but it changed workset
            elif outcome == 'failed' or outcome == 'already':
                rollback(t)
            elif not committed(t):
                outcome = 'failed'
            tally[outcome] = tally.get(outcome, 0) + 1
    finally:
        soffit.close()
        tg.Assimilate()
    res['done'] = tally['extended'] + tally['attached']
    res['skipped'] = tally['already']
    res['failed'] = tally['failed']
    if tally['attached']:
        res['lines'].append(u'{0} attached with Revit attach to structure (no soffit found by ray).'.format(tally['attached']))
    if tally['already']:
        res['lines'].append(u'{0} already at structure.'.format(tally['already']))
    if tally['failed']:
        res['lines'].append(u'{0} found no structure above - check the ticked categories and that the slab is loaded.'.format(tally['failed']))
    res['lines'].extend(ws.problems)
    return res


def job_rehost(uidoc, settings, log):
    u"""Re-host each selected hanger on its nearest duct.

    Replace mode (default): the hanger is replaced by a new one placed on the
    duct exactly as if it had just been placed - so it takes the duct's width,
    depth and condition - keeping workset, Comments, Mark, shared parameters
    and rod tops.  Move mode: PlaceOnHost only (Revit keeps the old size).
    """
    doc = uidoc.Document
    res = new_result(u'Auto rehost and size')
    hangers = get_selection(uidoc, 'hanger', u'Select fabrication hangers to rehost')
    if not hangers:
        res['lines'].append(u'No fabrication hangers selected.')
        return res
    replace = core.as_bool(settings, u'rehost_replace')
    radius = core.as_float(settings, u'search_radius', 1500.0) / MM
    hosts, info = straight_hosts(doc)
    log.add(u'{0} horizontal straights; mode {1}'.format(len(hosts), u'replace' if replace else u'move'))
    plan = []
    for h in hangers:
        p = hanger_point(h)
        near = core.nearest_host(p, hosts, radius, END_MARGIN) if p else None
        if near is None:
            res['skipped'] += 1
            log.add(u'hanger {0}: no duct within {1:.0f} mm'.format(eid_value(h.Id), radius * MM))
            continue
        host, ends = info[near['host']['id']]
        plan.append((h, host, ends[0], near['dist']))
    if not plan:
        res['lines'].append(u'No duct straight within {0:.0f} mm of the selected hangers.'.format(radius * MM))
        return res
    matcher = HangerMatcher(doc, settings.get(u'button', u''), log) if replace else None
    if replace and not matcher.picker.all:
        res['lines'].append(u'No hanger buttons in the loaded fabrication services - moving the hangers instead.')
        replace = False
    checkout(doc, [x[0] for x in plan] + [x[1] for x in plan], log)
    ws = Worksets(doc, settings.get(u'workset', u''), log)
    tg = TransactionGroup(doc, u'Hanger Automation - rehost')
    tg.Start()
    outcome = []   # (hanger to read back, host, how)
    for old, host, conn, dist in plan:
        t = start_txn(doc, u'Rehost hanger')
        try:
            new, note = (None, u'')
            if replace:
                new, note = replace_hanger(doc, old, host, conn, dist, matcher, log, ws)
            if new is not None:
                if committed(t):
                    outcome.append((new, host, u'replaced'))
                else:
                    res['failed'] += 1
                continue
            if replace:
                log.add(u'hanger {0}: {1}; moving it instead'.format(eid_value(old.Id), note))
                rollback(t)
                t = start_txn(doc, u'Rehost hanger')
            placed = place_on_host(old, host, conn, dist, log)
            if placed:
                ws.apply(old, host, False)
            if placed and committed(t):
                outcome.append((old, host, u'moved'))
            else:
                rollback(t)
                res['failed'] += 1
        except Exception as ex:
            log.add(u'rehost {0}: {1}'.format(eid_value(old.Id), ex))
            rollback(t)
            res['failed'] += 1
    tg.Assimilate()
    good, replaced, moved = [], 0, 0
    for h, host, how in outcome:  # read back after the group has closed
        try:
            ok = h.IsValidObject and host_of(h) == eid_value(host.Id)
        except Exception:
            ok = False
        if ok:
            good.append(h)
            res['done'] += 1
            replaced += 1 if how == u'replaced' else 0
            moved += 1 if how == u'moved' else 0
        else:
            res['failed'] += 1
    if replaced:
        res['lines'].append(u'{0} replaced with a new hanger sized to its duct.'.format(replaced))
    if moved:
        res['lines'].append(u'{0} moved only (kept their old size){1}.'.format(
            moved, u' - see Copy debug for why' if replace else u''))
    if good:
        try:
            ids = List[ElementId]()
            for h in good:
                ids.Add(h.Id)
            uidoc.Selection.SetElementIds(ids)
        except Exception:
            pass
    if good and core.as_bool(settings, u'extend_after'):
        r2 = job_extend(uidoc, settings, log, good)
        res['lines'].append(u'Rods: {0} to structure, {1} already there, {2} not found.'.format(
            r2['done'], r2['skipped'], r2['failed']))
    res['lines'].extend(p for p in ws.problems if p not in res['lines'])
    return res


def job_place(uidoc, settings, log):
    doc = uidoc.Document
    res = new_result(u'Auto place hangers')
    seeds = get_selection(uidoc, 'duct', u'Select the fabrication duct run to hang')
    if not seeds:
        res['lines'].append(u'No fabrication duct selected.')
        return res
    whole = settings.get(u'scope', u'run') == u'system'
    parts, elems, selected = build_graph(seeds, whole, log)
    spans = [s for s in core.build_spans(parts)
             if any(it['id'] in selected for it in s['chain'] if it['kind'] == 'straight')]
    if not spans:
        res['lines'].append(u'No horizontal straight runs in the selection.')
        return res
    cfg = core.plan_config(settings)
    clear_tk = cfg['takeoff_clear'] / MM
    edge = cfg['edge'] / MM
    picker = ButtonPicker(doc, settings.get(u'button', u''), log)
    if not picker.all:
        res['lines'].append(u'No hanger buttons in the loaded fabrication services - load a hanger service first.')
        return res
    tap_pts = all_tap_points(doc)
    existing = []
    if core.as_bool(settings, u'skip_existing'):
        for h in FilteredElementCollector(doc).OfCategory(bic('OST_FabricationHangers')).WhereElementIsNotElementType():
            p = hanger_point(h)
            if p is not None:
                existing.append(p)
    exist_clear = core.as_float(settings, u'existing_clear', 300.0) / MM
    targets = dim_targets(uidoc, settings, u'dims', res, log)
    want_dims = targets is not None
    dim_type = find_dim_type(doc, settings.get(u'dim_type', u''))
    want_rods = core.as_bool(settings, u'extend_place')

    # ---- plan everything before writing anything
    jobs = []
    for span in spans:
        chain = span['chain']
        points = {}
        for it in chain:
            rec = parts[it['id']]
            if len(rec['pts']) >= 2:
                points[it['id']] = (rec['pts'][it['entry']], rec['pts'][it['exit']])
        segs = core.span_segments(chain, points)
        if not segs:
            continue
        length = core.span_length(span)
        st = core.plan_stations(length, span['start_end']['type'], span['end_end']['type'], cfg)
        blocks = []
        for it in chain:
            for sp in parts[it['id']].get('sides', []):
                blocks.append(sp)
        blocks += tap_pts
        block_st = [s for s in (core.station_of_point(segs, b, TAP_REACH) for b in blocks) if s is not None]
        st = core.avoid_blocks(st, block_st, clear_tk, length, edge)
        st = core.dedupe(st, cfg['min_gap'] / MM / 2.0)
        if existing:
            ex_st = [s for s in (core.station_of_point(segs, e, TAP_REACH) for e in existing) if s is not None]
            before = len(st)
            st = core.drop_near(st, ex_st, exist_clear)
            res['skipped'] += before - len(st)
        first_id = chain[0]['id']
        last_id = chain[-1]['id']
        p_start = points[first_id][0] if first_id in points else segs[0][1]
        p_end = points[last_id][1] if last_id in points else segs[-1][2]
        first_st = [it for it in chain if it['kind'] == 'straight'][0]['id']
        last_st = [it for it in chain if it['kind'] == 'straight'][-1]['id']
        places = []
        for s in st:
            loc = core.locate(chain, s, END_MARGIN)
            if loc is None:
                continue
            rec = parts[loc['id']]
            places.append((elems[loc['id']], rec['cobj'][loc['entry']], loc['dist']))
        if places:
            jobs.append({'places': places, 'p_start': p_start, 'p_end': p_end,
                         'first': elems[first_st], 'last': elems[last_st], 'length': length})
        log.add(u'span {0:.0f} mm ({1} -> {2}): {3} hangers, {4} takeoffs on it'.format(
            length * MM, span['start_end']['type'], span['end_end']['type'], len(places), len(block_st)))
    if not jobs:
        res['lines'].append(u'Nothing to place - every span already has its hangers or is a takeoff stub.')
        return res

    # ---- write
    hosts = []
    for j in jobs:
        hosts.extend(p[0] for p in j['places'])
    checkout(doc, hosts, log)
    ws = Worksets(doc, settings.get(u'workset', u''), log)
    tg = TransactionGroup(doc, u'Hanger Automation - place hangers')
    tg.Start()
    soffit = Soffit(doc, settings, log) if want_rods else None
    created = []
    rods = {'extended': 0, 'already': 0, 'attached': 0, 'failed': 0}
    dimmed = 0
    try:
        for j in jobs:
            made = []
            for host, conn, dist in j['places']:
                label, btn, cond = picker.pick(host)
                if btn is None:
                    res['failed'] += 1
                    continue
                t = start_txn(doc, u'Place hanger')
                try:
                    h = create_hanger(doc, btn, cond, host, conn, dist, log)
                    if h is None:
                        rollback(t)
                        res['failed'] += 1
                        continue
                    ws.apply(h, host, True)
                    if committed(t):
                        made.append((h, host))
                    else:
                        res['failed'] += 1
                except Exception as ex:
                    log.add(u'place on {0}: {1}'.format(eid_value(host.Id), ex))
                    rollback(t)
                    res['failed'] += 1
            if soffit is not None:
                for h, _host in made:
                    t = start_txn(doc, u'Extend rods')
                    try:
                        outcome = extend_rods(doc, h, soffit, log)
                    except Exception as ex:
                        log.add(u'rods {0}: {1}'.format(eid_value(h.Id), ex))
                        outcome = 'failed'
                    if outcome in ('failed', 'already'):
                        rollback(t)
                    elif not committed(t):
                        outcome = 'failed'
                    rods[outcome] += 1
            if made and want_dims:
                hs = [m[0] for m in made]
                if dimension_in_targets(doc, targets, j['p_start'], j['p_end'],
                                        lambda v, j=j, hs=hs: chain_dimension(doc, v, j['p_start'], j['p_end'], hs,
                                                                              j['first'], j['last'], settings,
                                                                              dim_type, log), log):
                    dimmed += 1
            created.extend(made)
    finally:
        if soffit is not None:
            soffit.close()
        tg.Assimilate()
    for h, host in created:  # read back after the group has closed
        try:
            if h.IsValidObject and host_of(h) == eid_value(host.Id):
                res['done'] += 1
            else:
                res['failed'] += 1
        except Exception:
            res['failed'] += 1
    if res['skipped']:
        res['lines'].append(u'{0} skipped where a hanger already was.'.format(res['skipped']))
    if soffit is not None:
        if not soffit.ok():
            res['lines'].append(u'Rods: ray cast unavailable ({0}); used Revit attach to structure.'.format(soffit.reason))
        res['lines'].append(u'Rods: {0} to structure, {1} attached by Revit, {2} found no structure.'.format(
            rods['extended'], rods['attached'], rods['failed']))
    if want_dims:
        res['lines'].append(targets.summary(dimmed, len(jobs)))
        offer_open(uidoc, settings, targets, dimmed, log)
    res['lines'].extend(ws.problems)
    return res
