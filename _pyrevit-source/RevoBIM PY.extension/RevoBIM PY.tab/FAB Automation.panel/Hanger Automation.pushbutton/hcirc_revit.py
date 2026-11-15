# -*- coding: utf-8 -*-
u"""Hanger Automation - Circular System Based floor supports and (1.14.0)
hangers: everything that touches Revit.

A path of its own.  The Family Floor Support and Family Hangers tabs only come
here when the chosen family is saved as Circular System Based in Family
settings; the rectangular supports and the Rectangular Hanger System families
stay entirely in hfam_revit, which this
module reads from (sections, levels, picking, the run graph, locks, the base
pick, worksets) but never changes.

Jobs (run from the window through the shared ExternalEvent):
  job_place    click pipes / round ducts one after another: a ring at each click
  job_realign  pick the service, then the supports: each slides sideways onto
               the centreline and is refitted
  job_auto     select a run: rings along it by the Auto placement rules
  job_dims     the dimension placer, reading a ring by the way its service runs

Each support:
  - stands on the service's level (or the floor / roof / equipment picked),
    at the service centreline, turned so the service runs along the family's
    X or Y (Family settings);
  - diameter parameter = the service's outside diameter (+ insulation, ticked);
  - support height parameter = base up to the service centre AT THAT SUPPORT
    (the intersecting midpoint: a sloping pipe gets a different height at
    every support) - the family is placed at its reference level and its
    height parameter runs up to the ring centre (1.13.0);
  - then the ring is measured in the placed support (its round faces and
    arcs) as a check: if it is not on the service centre the results say so.
    The height is never changed by the check.  Every step is in the debug log.

Each circular hanger (Family Hangers tab) goes on the service's level with its
reference on the service CENTRELINE (1.14.1: the pipe / round duct / round FAB
duct centre where it hangs), turned to the X / Y set, its diameter parameter
set to the service's diameter, its drop rod run from there up to the level or
structure above (ticked).  The same ring check follows.
"""
import fha_clr  # noqa: F401  (must be first)
import math
import fha_core as core
import hfam_core as fc
import hcirc_core as cc
import fha_revit as frv
import hfam_revit as hr
from Autodesk.Revit import DB
from Autodesk.Revit.DB import XYZ, TransactionGroup, ElementTransformUtils
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ObjectType

MM = core.MM
TOL = hr.TOL
eid_value = frv.eid_value
el_name = frv.el_name
pt = frv.pt
to_xyz = frv.to_xyz
fmm = hr.fmm
fpt = hr.fpt
describe = hr.describe
NOT_ROUND = u'A Circular System Based {1} goes on a pipe or round duct - {0} was skipped.'


def noun(cfg):
    u"""'support' on the Family Floor Support tab, 'hanger' on Family Hangers."""
    return u'support' if hr.is_floor(cfg) else u'hanger'


def title(cfg):
    return u'circular floor support' if hr.is_floor(cfg) else u'circular hanger'


# ============================================================ the ring
def _radius(face):
    try:
        return face.get_Radius(0).GetLength()
    except Exception:
        pass
    try:
        return face.Radius[0].GetLength()
    except Exception:
        return None


def _walk_rings(geo, out):
    for g in geo:
        if isinstance(g, DB.GeometryInstance):
            try:
                _walk_rings(g.GetInstanceGeometry(), out)
            except Exception:
                pass
        elif isinstance(g, DB.Solid):
            try:
                for f in g.Faces:
                    if isinstance(f, DB.CylindricalFace):
                        r = _radius(f)
                        if r:
                            a = f.Axis
                            out.append((r, pt(f.Origin), (a.X, a.Y, a.Z), u'round face'))
            except Exception:
                pass
            try:
                for ed in g.Edges:
                    c = ed.AsCurve()
                    if isinstance(c, DB.Arc):
                        n = c.Normal
                        out.append((c.Radius, pt(c.Center), (n.X, n.Y, n.Z), u'arc'))
            except Exception:
                pass
        elif isinstance(g, DB.Arc):
            try:
                n = g.Normal
                out.append((g.Radius, pt(g.Center), (n.X, n.Y, n.Z), u'arc line'))
            except Exception:
                pass


def ring_candidates(inst):
    u"""(radius, centre, axis, kind) for every round face and arc of the placed support."""
    opt = DB.Options()
    opt.ComputeReferences = False
    try:
        opt.DetailLevel = getattr(DB.ViewDetailLevel, 'Fine')
    except Exception:
        pass
    out = []
    try:
        geo = inst.get_Geometry(opt)
        if geo is not None:
            _walk_rings(geo, out)
    except Exception:
        pass
    return out


def measure_ring(doc, inst, dia, q, along):
    try:
        doc.Regenerate()
    except Exception:
        pass
    return cc.pick_ring(ring_candidates(inst), dia / 2.0, q, along)


def base_point(inst):
    try:
        return pt(inst.Location.Point)
    except Exception:
        return None


# ============================================================ fitting
def circ_stand(base_el, q, z_bot, level, problems, log):
    u"""Where a ring support's base stands on the picked element: straight
    below the service centre (its single post), else its level."""
    z, how, _under = base_el.stand(q, z_bot, [(q[0], q[1])])
    if z is None:
        problems.append(u'the picked base is not under every support - those stand on the level')
        log.add(u'   base: {0} is not under it - standing on the level'.format(base_el.label()))
        return level.ProjectElevation
    log.add(u'   base: stands at {0} on {1} ({2})'.format(fmm(z), base_el.label(), how))
    if z > z_bot + TOL:
        problems.append(u'the picked base is above the service there - that support stands on the level')
        return level.ProjectElevation
    return z


def fit_circ(doc, inst, sec, q, level, cfg, log, base_el=None):
    u"""Turn, lift and size one ring support, the ring centre at the service
    centre, then check where the ring went.  Caller holds the
    transaction.  Returns a list of problems."""
    problems = []
    along, across = fc.plan_dirs(sec['a'], sec['b'])
    run_axis = cfg.get(u'circ_axis', u'X')
    ang = hr.align_rotation(doc, inst, cc.circ_x_dir(run_axis, along, across))
    z_bot = q[2] - sec['depth'] / 2.0
    log.add(u'   level {0} @ {1} | service centre here {2}, underside {3} | runs along the family {4} | turned {5} deg'.format(
        el_name(level), fmm(level.ProjectElevation), fmm(q[2]), fmm(z_bot), run_axis,
        u'{0:.1f}'.format(ang * 57.29577951) if ang is not None else u'? (rotation failed)'))
    stand = level.ProjectElevation
    p = hr.offset_param(inst)
    if base_el is not None and p is not None:
        stand = circ_stand(base_el, q, z_bot, level, problems, log)
    elif base_el is not None:
        problems.append(u'no writable offset parameter - the support could not be lifted onto the picked element')
    base = stand - level.ProjectElevation
    if p is None:
        log.add(u'   offset: no writable Elevation from Level / Offset from Host')
    else:
        p.Set(base)
        log.add(u'   offset: {0} = {1}{2}'.format(p.Definition.Name, fmm(base), u' (stands on the level)' if abs(base) < TOL
                                                 else u' (stands on the picked element, hosted on the level)'))
    dia = sec['width']
    if q[2] < stand - TOL:
        problems.append(u'the service is below what the support stands on')
    height = cc.support_height(q[2], stand)
    sec['set_dia'] = dia
    ok_dia = hr.set_length(inst, cfg.get(u'dia'), dia)
    log.add(u'   diameter: {0} = {1}{2}'.format(cfg.get(u'dia') or u'(not set)', fmm(dia), u'' if ok_dia else u'  <- NOT SET'))
    if not ok_dia:
        problems.append(u'diameter parameter "{0}" not found or read only - set it in Family settings'.format(
            cfg.get(u'dia') or u'(not set)'))
    hname = cfg.get(u'circ_height')
    ok_h = hr.set_length(inst, hname, height)
    log.add(u'   support height: {0} = {1} (base {2} up to the service centre here {3}){4}'.format(
        hname or u'(not set)', fmm(height), fmm(stand), fmm(q[2]), u'' if ok_h else u'  <- NOT SET'))
    sec['set_height'] = height
    if not ok_h:
        problems.append(u'support height parameter "{0}" not found or read only - set it in Family settings'.format(
            hname or u'(not set)'))
        return problems
    bp = base_point(inst)
    if bp is not None:
        log.add(u'   placed: base point {0} (wanted {1} on {2})'.format(fpt(bp), fmm(stand), el_name(level)))
    # ---- check: where did the ring end up? (reported, never corrected)
    m = measure_ring(doc, inst, dia, q, along)
    if m is None:
        log.add(u'   ring check: no round face or arc of about {0} radius found in the family - not checked'.format(
            fmm(dia / 2.0)))
        return problems
    off = cc.ring_off(m['z'], q[2])
    log.add(u'   ring check: {0}, radius {1}, centre at {2} ({3} mm off the service centre) | {4} mm off the '
            u'centreline in plan | the service runs {5} through it'.format(
                m['kind'], fmm(m['r']), fmm(m['z']), u'{0:+.1f}'.format(off * MM), u'{0:.1f}'.format(m['off'] * MM),
                u'straight' if m['along'] > 0.9 else u'at {0:.0f} deg'.format(57.29577951 * _acos(m['along']))))
    if abs(off) > cc.CENTRE_OK_MM / MM:
        problems.append(u'the ring came out {0:.0f} mm {1} the service centre - check that "{2}" runs from the family\'s '
                        u'reference level to the ring centre'.format(abs(off) * MM, u'above' if off > 0 else u'below', hname))
    if m['along'] < 0.7:
        problems.append(u'the ring faces across the service - switch "The service runs along" (X / Y) in Family settings')
    return problems


def _acos(c):
    return math.acos(max(-1.0, min(1.0, c)))


def fit_circ_hanger(doc, inst, sec, q, level, cfg, rod, finder, log):
    u"""A circular hanger: its reference on the service centreline (the
    centre where it hangs) on the service's level, turned to the X / Y set, the
    diameter parameter set, the drop rod from the centre up to the soffit.
    Then the ring check.  Caller holds the transaction."""
    problems = []
    along, across = fc.plan_dirs(sec['a'], sec['b'])
    run_axis = cfg.get(u'circ_axis', u'X')
    ang = hr.align_rotation(doc, inst, cc.circ_x_dir(run_axis, along, across))
    z_bot = q[2] - sec['depth'] / 2.0
    log.add(u'   level {0} @ {1} | service centre here {2}, invert {3} | runs along the family {4} | turned {5} deg'.format(
        el_name(level), fmm(level.ProjectElevation), fmm(q[2]), fmm(z_bot), run_axis,
        u'{0:.1f}'.format(ang * 57.29577951) if ang is not None else u'? (rotation failed)'))
    p = hr.offset_param(inst)
    base = cc.hanger_offset(q[2], level.ProjectElevation)
    if p is None:
        problems.append(u'no writable offset / elevation parameter')
        log.add(u'   offset: no writable Elevation from Level / Offset from Host')
    else:
        p.Set(base)
        log.add(u'   offset: {0} = {1} (the service centreline)'.format(p.Definition.Name, fmm(base)))
    dia = sec['width']
    sec['set_dia'] = dia
    ok_dia = hr.set_length(inst, cfg.get(u'dia'), dia)
    log.add(u'   diameter: {0} = {1}{2}'.format(cfg.get(u'dia') or u'(not set)', fmm(dia), u'' if ok_dia else u'  <- NOT SET'))
    if not ok_dia:
        problems.append(u'diameter parameter "{0}" not found or read only - set it in Family settings'.format(
            cfg.get(u'dia') or u'(not set)'))
    if rod:   # from the hanger's reference (the centreline) up
        top = finder.above(cfg.get(u'soffit', u'level'), q[0], q[1], q[2])
        L = fc.rod_length(q[2], top)
        if L is None:
            problems.append(u'no level / soffit above the hanger for the drop rod')
            log.add(u'   rod: nothing above {0} ({1})'.format(fmm(q[2]), cfg.get(u'soffit')))
        else:
            ok = hr.set_length(inst, cfg.get(u'rod'), L)
            log.add(u'   rod: {0} = {1} (soffit {2} by {3}){4}'.format(
                cfg.get(u'rod'), fmm(L), fmm(top), cfg.get(u'soffit'), u'' if ok else u'  <- NOT SET'))
            if not ok:
                problems.append(u'drop rod parameter "{0}" not found'.format(cfg.get(u'rod')))
    # ---- check: where did the ring end up? (reported, never corrected)
    m = measure_ring(doc, inst, dia, q, along)
    if m is None:
        log.add(u'   ring check: no round face or arc of about {0} radius found in the family - not checked'.format(
            fmm(dia / 2.0)))
        return problems
    off = cc.ring_off(m['z'], q[2])
    log.add(u'   ring check: {0}, radius {1}, centre at {2} ({3} mm off the service centre) | {4} mm off the '
            u'centreline in plan'.format(m['kind'], fmm(m['r']), fmm(m['z']), u'{0:+.1f}'.format(off * MM),
                                         u'{0:.1f}'.format(m['off'] * MM)))
    if abs(off) > cc.CENTRE_OK_MM / MM:
        problems.append(u'the ring came out {0:.0f} mm {1} the service centre - the hanger is placed with its '
                        u'reference on the service centreline, so check that the family\'s reference level runs '
                        u'through the ring centre'.format(abs(off) * MM, u'above' if off > 0 else u'below'))
    if m['along'] < 0.7:
        problems.append(u'the ring faces across the service - switch "The service runs along" (X / Y) in Family settings')
    return problems


def place_circ(doc, symbol, service, sec, q, cfg, log, ws=None, base_el=None, rod=False, finder=None):
    u"""Create one ring support / hanger at centreline point q.  Caller holds
    the transaction.  Returns (instance, problems)."""
    floor = hr.is_floor(cfg)
    if floor:
        level = hr.floor_level(doc, service, q[2] - sec['depth'] / 2.0, log)
    else:
        level = hr.element_level(doc, service, q[2])
    if level is None:
        return None, [u'the service has no level']
    try:
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
    except Exception:
        pass
    along, across = fc.plan_dirs(sec['a'], sec['b'])
    want_x = cc.circ_x_dir(cfg.get(u'circ_axis', u'X'), along, across)
    loc = XYZ(q[0], q[1], level.ProjectElevation)
    placement = u''
    try:
        placement = str(symbol.Family.FamilyPlacementType)
    except Exception:
        pass
    inst = None
    if placement == 'WorkPlaneBased':
        try:
            inst = doc.Create.NewFamilyInstance(level.GetPlaneReference(), loc, to_xyz(want_x), symbol)
        except Exception as ex:
            log.add(u'work plane placement: {0}'.format(ex))
    if inst is None:
        try:
            st = getattr(StructuralType, 'NonStructural')
            inst = doc.Create.NewFamilyInstance(loc, symbol, level, st)
        except Exception as ex:
            return None, [u'Revit refused to place {0}: {1}'.format(el_name(symbol), ex)]
    doc.Regenerate()
    if ws is not None:
        ws.apply(inst, service, True)
    else:
        frv.match_workset(inst, service)
    log.add(u'+ {0} {1} on {2} at {3} ({4})'.format(title(cfg), eid_value(inst.Id), describe(service), fpt(q),
                                                   placement or u'?'))
    hr.log_section(log, sec)
    frv.write_service_comment(inst, [service], log)
    if not floor:
        return inst, fit_circ_hanger(doc, inst, sec, q, level, cfg, rod, finder, log)
    return inst, fit_circ(doc, inst, sec, q, level, cfg, log, base_el)


def realign_circ(doc, inst, service, sec, cfg, log, ws=None, base_el=None, rod=False, finder=None):
    u"""Slide a ring support sideways onto the service centreline (never along
    the run), then refit it.  Caller holds the transaction."""
    p = hr.instance_point(inst)
    if p is None:
        return [u'the support has no location point']
    q = fc.on_line(sec['a'], sec['b'], p)
    log.add(u'~ {0} {1} at {2} -> {3} | sideways {4} mm | on {5}'.format(
        title(cfg), eid_value(inst.Id), fpt(p), fpt(q), fmm(fc.plan_offset(sec['a'], sec['b'], p)), describe(service)))
    hr.log_section(log, sec)
    try:
        ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(q[0] - p[0], q[1] - p[1], 0.0))
    except Exception as ex:
        return [u'could not move it: {0}'.format(ex)]
    if hr.is_floor(cfg):
        want = hr.floor_level(doc, service, q[2] - sec['depth'] / 2.0, log)
    else:
        want = hr.element_level(doc, service, q[2])
    level = hr.element_level(doc, inst, p[2])
    problems = []
    if want is not None and (level is None or eid_value(level.Id) != eid_value(want.Id)):
        if hr.set_level(inst, want):
            log.add(u'   level {0} -> {1}'.format(el_name(level) if level else u'?', el_name(want)))
            level = want
        else:
            problems.append(u'kept its own level (level is not editable on this family)')
    if ws is not None:
        ws.apply(inst, service, False)
    doc.Regenerate()
    if level is None:
        return problems + [u'no level']
    if not hr.is_floor(cfg):
        return problems + fit_circ_hanger(doc, inst, sec, q, level, cfg, rod, finder, log)
    return problems + fit_circ(doc, inst, sec, q, level, cfg, log, base_el)


def verify_circ(inst, cfg, sec, problems):
    u"""Read back after commit: the diameter must hold the service's."""
    try:
        if not inst.IsValidObject:
            return False
    except Exception:
        return False
    v = hr.get_length(inst, cfg.get(u'dia'))
    if v is not None and sec.get('set_dia') is not None and abs(v - sec['set_dia']) > TOL:
        problems.append(u'{0} reads {1:.0f} mm, not {2:.0f} mm'.format(cfg.get(u'dia'), v * MM, sec['set_dia'] * MM))
    return True


def _chosen(uidoc, settings, res):
    u"""(symbol, cfg) - cfg['mode'] says which tab: 'floor' or 'hang'."""
    return hr._chosen(uidoc, settings, res)


def _rod(settings, key, cfg, log, doc):
    u"""(rod ticked, SoffitFinder) for a hanger job; (False, None) for supports."""
    rod = core.as_bool(settings, key) and not hr.is_floor(cfg)
    finder = hr.SoffitFinder(doc, settings, log, rod and cfg.get(u'soffit') == u'structure') if rod else None
    return rod, finder


def _close(finder):
    if finder is not None:
        finder.close()


def _round_section(el, outside):
    u"""The fitted section of a pipe / round duct, or None for anything else."""
    if not hr.is_host_duct(el):
        return None
    sec = hr.fitted(el, outside)
    return sec if sec.get('round') else None


# ================================================================== jobs
def job_place(uidoc, settings, log):
    doc = uidoc.Document
    res = frv.new_result(u'Place circular {0} on service'.format(hr.noun_of(settings)))
    symbol, cfg = _chosen(uidoc, settings, res)
    if symbol is None:
        return res
    outside = core.as_bool(settings, u'fam_ins_place')
    hr.log_context(uidoc, settings, log, u'Place {0} on service'.format(title(cfg)), symbol, cfg)
    rod, finder = _rod(settings, u'fam_rod_place', cfg, log, doc)
    locker = hr.Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_place') else None
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    picked_base = hr.floor_base_pick(uidoc, settings, res, log)
    base_el = hr.BaseSurface(doc, picked_base[0], picked_base[1], log) if picked_base else None
    if base_el is not None:
        log.add(u'supports stand on {0}'.format(base_el.label()))
    issues = []
    try:
        while True:
            try:
                svc, p = hr.pick_duct_point(uidoc, u'Click on a pipe or round duct where the {0} goes '
                                                   u'(Esc to finish)'.format(title(cfg)), hr.is_host_duct)
            except Exception:
                break   # Esc
            log.add(u'click on {0} at {1}'.format(describe(svc), fpt(p) if p else u'(no point - using the middle)'))
            sec = _round_section(svc, outside)
            if sec is None:
                issues.append(NOT_ROUND.format(describe(svc), noun(cfg)))
                res['skipped'] += 1
                continue
            if p is None:
                p = core.vscale(core.vadd(sec['a'], sec['b']), 0.5)
            q = fc.on_centreline(sec['a'], sec['b'], p, hr.END_MARGIN)
            sec['keys'] = [eid_value(svc.Id)]
            t = frv.start_txn(doc, u'Place circular support')
            try:
                inst, problems = place_circ(doc, symbol, svc, sec, q, cfg, log, ws, base_el, rod, finder)
                hr.lock_if(locker, inst, svc, sec, q, problems, log)
                if inst is None or not frv.committed(t):
                    frv.rollback(t)
                    res['failed'] += 1
                    issues.extend(problems)
                    continue
                if verify_circ(inst, cfg, sec, problems):
                    res['done'] += 1
                issues.extend(problems)
            except Exception as ex:
                log.add(u'place: {0}'.format(ex))
                frv.rollback(t)
                res['failed'] += 1
    finally:
        _close(finder)
        if base_el is not None:
            base_el.close()
    res['lines'].extend(sorted(set(issues)))
    res['lines'].extend(ws.problems)
    return res


def job_realign(uidoc, settings, log):
    doc = uidoc.Document
    res = frv.new_result(u'Re-align circular {0}s to service'.format(hr.noun_of(settings)))
    symbol, chosen_cfg = _chosen(uidoc, settings, res)
    if symbol is None:
        return res
    fams = settings.get(u'_fams') or {}
    chosen_family = el_name(symbol.Family)
    picked = [e for e, _s in hr.selected_services(uidoc, True)]
    if not picked:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, hr._Filter(hr.is_host_duct),
                                               u'Pick the pipe or round duct, then Finish')
            picked = [doc.GetElement(r.ElementId) for r in refs]
        except Exception:
            picked = []
    if not picked:
        res['lines'].append(u'No service picked.')
        return res
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, hr._Filter(hr.is_hanger_family),
                                           u'Pick the circular {0}s to re-align, then Finish'.format(noun(chosen_cfg)))
        supports = [doc.GetElement(r.ElementId) for r in refs]
    except Exception:
        supports = []
    if not supports:
        res['lines'].append(u'No supports picked.')
        return res
    hr.log_context(uidoc, settings, log, u'Re-align {0}s to service'.format(title(chosen_cfg)), symbol, chosen_cfg)
    rod, finder = _rod(settings, u'fam_rod_realign', chosen_cfg, log, doc)
    log.add(u'picked {0}; {1} supports'.format(u', '.join(describe(e) for e in picked), len(supports)))
    straights, seen = [], set()
    for svc in picked:
        for e, sc in hr.run_straights(doc, svc):
            if eid_value(e.Id) not in seen:
                seen.add(eid_value(e.Id))
                straights.append((e, sc))
    by_id = dict((eid_value(e.Id), (e, sc)) for e, sc in straights)
    segs = [(eid_value(e.Id), sc['a'], sc['b']) for e, sc in straights]
    outside = core.as_bool(settings, u'fam_ins_realign')
    locker = hr.Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_realign') else None
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    frv.checkout(doc, supports, log)
    picked_base = hr.floor_base_pick(uidoc, settings, res, log)
    tg = TransactionGroup(doc, u'Hanger Automation - re-align circular supports')
    tg.Start()
    base_el = hr.BaseSurface(doc, picked_base[0], picked_base[1], log) if picked_base else None
    issues, done = [], []
    try:
        for h in supports:
            fam = el_name(h.Symbol.Family)
            if fam == chosen_family:
                cfg = dict(chosen_cfg)
            elif cc.is_circ(fams.get(fam, {})):
                cfg = dict(fc.fam_config(fams, fam), mode=chosen_cfg.get(u'mode', u'hang'))
            else:
                issues.append(u'{0} {1} ({2}) is not a Circular System Based family - left alone.'.format(
                    noun(chosen_cfg).capitalize(), eid_value(h.Id), fam))
                res['skipped'] += 1
                continue
            p = hr.instance_point(h)
            key = fc.pick_segment(p, segs, 300.0 / MM) if p is not None else None
            seg_el, sec = by_id.get(key, (picked[0], hr.section(picked[0])))
            sec = fc.apply_insulation(sec, outside)
            if not sec.get('round'):
                issues.append(NOT_ROUND.format(describe(seg_el), noun(cfg)))
                res['skipped'] += 1
                continue
            if key is None:
                log.add(u'support {0}: not over any straight of the run - using the picked service'.format(eid_value(h.Id)))
            sec['keys'] = [eid_value(seg_el.Id)]
            t = frv.start_txn(doc, u'Re-align circular support')
            try:
                problems = realign_circ(doc, h, seg_el, sec, cfg, log, ws, base_el, rod, finder)
                if p is not None:
                    hr.lock_if(locker, h, seg_el, sec, fc.on_line(sec['a'], sec['b'], p), problems, log)
                if frv.committed(t):
                    done.append((h, cfg, sec))
                else:
                    res['failed'] += 1
                issues.extend(problems)
            except Exception as ex:
                log.add(u'realign {0}: {1}'.format(eid_value(h.Id), ex))
                frv.rollback(t)
                res['failed'] += 1
    finally:
        _close(finder)
        if base_el is not None:
            base_el.close()
        tg.Assimilate()
    for h, cfg, sec in done:
        if verify_circ(h, cfg, sec, issues):
            res['done'] += 1
    res['lines'].extend(sorted(set(issues)))
    res['lines'].extend(ws.problems)
    return res


def job_auto(uidoc, settings, log):
    u"""Ring supports along a selected pipe / round duct run, by the same
    placement rules as the other supports (spans between bends, tees and set
    downs, start / end offsets, maximum spacing, clear of takeoffs, joints and
    existing supports).  One ring per service - never shared."""
    doc = uidoc.Document
    res = frv.new_result(u'Auto place circular {0}s along run'.format(hr.noun_of(settings)))
    symbol, cfg = _chosen(uidoc, settings, res)
    if symbol is None:
        return res
    seeds = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    seeds = [e for e in seeds if e is not None and hr.is_run_member(e)]
    if not seeds:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, hr._Filter(hr.is_run_member),
                                               u'Select the run(s) - pipes or round ducts and their fittings - then Finish')
            seeds = [doc.GetElement(r.ElementId) for r in refs]
        except Exception:
            seeds = []
    if not seeds:
        res['lines'].append(u'No pipes selected.')
        return res
    accessories = core.as_bool(settings, u'fam_accessory')
    hr.log_context(uidoc, settings, log, u'Auto place {0}s along run'.format(title(cfg)), symbol, cfg)
    log.add(u'selected: ' + u', '.join(describe(e) for e in seeds[:60]) + (u' ...' if len(seeds) > 60 else u''))
    parts, elems, selected = hr.build_graph(seeds, accessories, log)
    spans = [s for s in core.build_spans(parts)
             if any(it['id'] in selected for it in s['chain'] if it['kind'] == 'straight')]
    if not spans:
        res['lines'].append(u'No level straight runs in the selection.')
        return res
    flange = core.as_float(settings, u'fam_flange_clear', 150.0) / MM
    user_max = core.as_float(settings, u'fam_spacing', 3000.0)
    use_dw = core.as_bool(settings, u'fam_dw144')
    takeoff_clear = core.as_float(settings, u'fam_takeoff_clear', 400.0) / MM
    existing = hr.existing_points(doc, symbol) if core.as_bool(settings, u'fam_skip_existing') else []
    exist_clear = core.as_float(settings, u'existing_clear', 300.0) / MM
    tap_pts = frv.all_tap_points(doc)
    outside = core.as_bool(settings, u'fam_ins_auto')
    locker = hr.Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_auto') else None
    targets = frv.dim_targets(uidoc, settings, u'fam_dims', res, log)   # asks in a 3D view
    want_dims = targets is not None
    dim_type = frv.find_dim_type(doc, settings.get(u'fam_dim_type', u''))
    picked_base = hr.floor_base_pick(uidoc, settings, res, log)
    tg = TransactionGroup(doc, u'Hanger Automation - circular supports along run')
    tg.Start()
    base_el = hr.BaseSurface(doc, picked_base[0], picked_base[1], log) if picked_base else None
    if base_el is not None:
        log.add(u'supports stand on {0}'.format(base_el.label()))
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    rod, finder = _rod(settings, u'fam_rod_auto', cfg, log, doc)
    issues, made_all = [], []
    dimmed = n_jobs = 0
    not_round = set()
    try:
        for span in spans:
            chain = span['chain']
            straight_els = [elems[it['id']] for it in chain if it['kind'] == 'straight']
            secs = [hr.section(e) for e in straight_els]
            if not all(sc['round'] for sc in secs):
                for e, sc in zip(straight_els, secs):
                    if not sc['round']:
                        not_round.add(describe(e))
                log.add(u'span [{0}] skipped - not all pipe / round duct'.format(u','.join(str(it['id']) for it in chain)))
                continue
            points = {}
            for it in chain:
                rec = parts[it['id']]
                if len(rec['pts']) >= 2:
                    points[it['id']] = (rec['pts'][it['entry']], rec['pts'][it['exit']])
            segs = core.span_segments(chain, points)
            if not segs:
                continue
            width = max(sc['width'] for sc in secs)
            duct_run = all(hr.is_ductwork(e) for e in straight_els)
            spacing = fc.span_spacing_mm(user_max, use_dw and duct_run, width * MM, width * MM, True)
            pcfg = fc.auto_config(settings, spacing)
            length = core.span_length(span)
            planned = core.plan_stations(length, span['start_end']['type'], span['end_end']['type'], pcfg)
            blocks = []
            for it in chain:
                blocks.extend(parts[it['id']].get('sides', []))
            blocks += tap_pts
            block_st = [x for x in (core.station_of_point(segs, b, frv.TAP_REACH) for b in blocks) if x is not None]
            st = core.avoid_blocks(planned, block_st, takeoff_clear, length, pcfg['edge'] / MM)
            st = core.dedupe(st, pcfg['min_gap'] / MM / 2.0)
            if existing:
                reach = width / 2.0 + 150.0 / MM
                ex_st = [x for x in (core.station_on_run(segs, e, reach, max_dz_ft=1000.0) for e in existing)
                         if x is not None]
                before = list(st)
                st = core.drop_near(st, ex_st, exist_clear)
                if len(st) < len(before):
                    log.add(u'   dropped {0} -> {1} (within {2} mm of supports already in the model at {3})'.format(
                        [fmm(x) for x in before], [fmm(x) for x in st], fmm(exist_clear), [fmm(x) for x in ex_st]))
                res['skipped'] += len(before) - len(st)
            places = []
            for x in st:
                loc = core.locate(chain, x, flange)
                if loc is None:
                    continue
                rec = parts[loc['id']]
                a, b = rec['pts'][loc['entry']], rec['pts'][1 - loc['entry']]
                d = core.vnorm(core.vsub(b, a))
                places.append((elems[loc['id']], core.vadd(a, core.vscale(d, loc['dist']))))
            log.add(u'span {0} mm [{1}] {2} {3}->{4} | dia {5} | spacing {6:.0f} | planned {7} | placing at {8}'.format(
                fmm(length), u','.join(str(it['id']) for it in chain), hr.service_kind(straight_els[0]),
                span['start_end']['type'], span['end_end']['type'], fmm(width), spacing,
                [fmm(x) for x in planned], [fpt(q) for _d, q in places]))
            if not places:
                continue
            n_jobs += 1
            made = []
            for host, q in places:
                sec = hr.fitted(host, outside)
                sec['keys'] = [eid_value(host.Id)]
                t = frv.start_txn(doc, u'Place circular support')
                try:
                    inst, problems = place_circ(doc, symbol, host, sec, q, cfg, log, ws, base_el, rod, finder)
                    hr.lock_if(locker, inst, host, sec, q, problems, log)
                    issues.extend(problems)
                    if inst is not None and frv.committed(t):
                        made.append((inst, sec))
                    else:
                        frv.rollback(t)
                        res['failed'] += 1
                except Exception as ex:
                    log.add(u'auto place: {0}'.format(ex))
                    frv.rollback(t)
                    res['failed'] += 1
            if made and want_dims:
                p_start = points[chain[0]['id']][0] if chain[0]['id'] in points else segs[0][1]
                p_end = points[chain[-1]['id']][1] if chain[-1]['id'] in points else segs[-1][2]
                hs = [m[0] for m in made]
                first_el, last_el = straight_els[0], straight_els[-1]
                axis = cc.width_axis(cfg.get(u'circ_axis', u'X'))
                if frv.dimension_in_targets(
                        doc, targets, p_start, p_end,
                        lambda v, a=p_start, b=p_end, hs=hs, f=first_el, l=last_el: hr.chain_dimension(
                            doc, v, a, b, hs, f, l, axis, settings, log, dim_type), log):
                    dimmed += 1
            made_all.extend(made)
    finally:
        _close(finder)
        if base_el is not None:
            base_el.close()
        tg.Assimilate()
    if not made_all and not res['failed'] and not not_round:
        res['lines'].append(u'Nothing to place - every span already has its {0}s or is too short.'.format(noun(cfg)))
    for inst, sec in made_all:
        if verify_circ(inst, cfg, sec, issues):
            res['done'] += 1
        else:
            res['failed'] += 1
    for name in sorted(not_round):
        issues.append(NOT_ROUND.format(name, noun(cfg)))
    if res['skipped']:
        res['lines'].append(u'{0} skipped where a {1} already was (untick "Skip existing {1}s" to place anyway).'.format(
            res['skipped'], noun(cfg)))
    if want_dims:
        res['lines'].append(targets.summary(dimmed, n_jobs))
        frv.offer_open(uidoc, settings, targets, dimmed, log)
    res['lines'].extend(sorted(set(issues)))
    res['lines'].extend(ws.problems)
    return res


def job_dims(uidoc, settings, log):
    u"""The dimension placer, with every circular family read by the way its
    service runs (the placer reads hangers by their width axis)."""
    st = dict(settings)
    fams = {}
    for name, cfg in (settings.get(u'_fams') or {}).items():
        if cc.is_circ(cfg):
            cfg = dict(cfg, axis=cc.width_axis(cfg.get(u'circ_axis', u'X')))
        fams[name] = cfg
    st[u'_fams'] = fams
    chosen = dict(settings.get(u'_fam') or {})
    ccfg = chosen.get('cfg')
    if ccfg and cc.is_circ(ccfg):
        chosen['cfg'] = dict(ccfg, axis=cc.width_axis(ccfg.get(u'circ_axis', u'X')))
    st[u'_fam'] = chosen
    return hr.job_dims(uidoc, st, log)
