# -*- coding: utf-8 -*-
u"""Hanger Automation - Family Hangers tab: everything that touches Revit.

Works on Revit ducts and fabrication ducts alike.  Jobs (run from the window
through the shared ExternalEvent):
  job_place    pick ducts one after another and place the chosen hanger family
  job_realign  pick a duct, then hangers, and re-align them to it
  job_auto     select a duct run and place hangers along it by the placement rules
Quiet jobs (no results box): list_job, preview_job, params_job.

The hanger is placed on the duct's level, centred on the duct, its reference
level at the duct invert, its two stretch parameters set to half the duct
width (plus clearance), turned square to the duct, and optionally its drop rod
run up to the soffit.
"""
import fha_clr  # noqa: F401  (must be first)
import fha_core as core
import hfam_core as fc
import fha_revit as frv
from Autodesk.Revit import DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilySymbol, FamilyInstance, Level, XYZ, Line,
    ElementTransformUtils, TransactionGroup, ReferenceArray, FabricationPart,
    RevitLinkInstance, ReferenceIntersector, FindReferenceTarget, ElementCategoryFilter,
)
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Electrical import CableTray
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from System.IO import MemoryStream
from System.Drawing import Size
from System.Drawing.Imaging import ImageFormat

MM = core.MM
eid_value = frv.eid_value
el_name = frv.el_name
pt = frv.pt
to_xyz = frv.to_xyz
END_MARGIN = 50.0 / MM
TOL = 1.0 / MM


# ================================================================ basics
def bic_or_none(name):
    return getattr(DB.BuiltInCategory, name, None)


def cat_is(el, name):
    b = bic_or_none(name)
    try:
        return b is not None and el.Category is not None and eid_value(el.Category.Id) == int(b)
    except Exception:
        return False


def hanger_cat_key(el):
    for key, _label in fc.CATEGORIES[1:]:
        if cat_is(el, key):
            return key
    return None


def bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def param_double(el, bip_name):
    try:
        b = bip(bip_name)
        p = el.get_Parameter(b) if b is not None else None
        if p is not None and p.HasValue:
            return p.AsDouble()
    except Exception:
        pass
    return None


def is_rvt_duct(el):
    u"""A Revit MEP curve a hanger can carry: duct, pipe or cable tray."""
    return isinstance(el, (Duct, Pipe, CableTray))


def is_fab_service(el):
    u"""A fabrication duct or pipe part (not a hanger)."""
    if not isinstance(el, FabricationPart) or frv.is_hanger(el):
        return False
    return frv.is_duct(el) or cat_is(el, 'OST_FabricationPipework')


def is_host_duct(el):
    u"""A straight a hanger can go on: a Revit duct, pipe or cable tray, or a
    fabrication duct / pipe straight."""
    if is_rvt_duct(el):
        return True
    return is_fab_service(el) and frv.is_straight(el)


def service_kind(el):
    if isinstance(el, Pipe):
        return u'pipe'
    if isinstance(el, CableTray):
        return u'cable tray'
    if isinstance(el, Duct):
        return u'duct'
    if isinstance(el, FabricationPart):
        return u'FAB pipe' if cat_is(el, 'OST_FabricationPipework') else u'FAB duct'
    return u'service'


def is_ductwork(el):
    u"""DW/144 applies to ductwork only."""
    return isinstance(el, Duct) or (isinstance(el, FabricationPart) and frv.is_duct(el))


RUN_CATEGORIES = ('OST_DuctFitting', 'OST_DuctAccessory', 'OST_PipeFitting', 'OST_PipeAccessory',
                  'OST_CableTrayFitting')


def is_run_member(el):
    if is_rvt_duct(el):
        return True
    if isinstance(el, FabricationPart):
        return is_fab_service(el)
    if isinstance(el, FamilyInstance):
        return any(cat_is(el, c) for c in RUN_CATEGORIES)
    return False


UNIT_CATEGORIES = ('OST_MechanicalEquipment', 'OST_DuctAccessory')


def is_unit(el):
    u"""Mechanical equipment or a duct accessory a hanger can go under."""
    return isinstance(el, FamilyInstance) and any(cat_is(el, c) for c in UNIT_CATEGORIES)


def is_hanger_family(el):
    return isinstance(el, FamilyInstance) and hanger_cat_key(el) is not None


class _Filter(ISelectionFilter):
    def __init__(self, test, points=False):
        self.test = test
        self.points = points

    def AllowElement(self, e):
        try:
            return bool(self.test(e))
        except Exception:
            return False

    def AllowReference(self, r, p):
        return self.points


def pick_duct_point(uidoc, prompt, test=None):
    u"""(duct, picked point or None).  A point on the duct's face, so the hanger
    lands where the user clicked; falls back to an element pick."""
    doc = uidoc.Document
    test = test or is_host_duct
    try:
        ref = uidoc.Selection.PickObject(ObjectType.PointOnElement, _Filter(test, True), prompt)
    except Exception as ex:
        if 'Cancel' in type(ex).__name__ or 'cancel' in u'{0}'.format(ex).lower():
            raise
        ref = uidoc.Selection.PickObject(ObjectType.Element, _Filter(test), prompt)
    p = None
    try:
        if ref.GlobalPoint is not None:
            p = pt(ref.GlobalPoint)
    except Exception:
        p = None
    return doc.GetElement(ref.ElementId), p


# ================================================================= debug
def fmm(v):
    try:
        return u'{0:.0f}'.format(v * MM)
    except Exception:
        return u'-'


def fpt(p):
    try:
        return u'({0:.0f}, {1:.0f}, {2:.0f})'.format(p[0] * MM, p[1] * MM, p[2] * MM)
    except Exception:
        return u'-'


def describe(el):
    u"""'Duct 123456 (Rectangular Duct : Default)' style label for the log."""
    try:
        kind = service_kind(el) if (is_rvt_duct(el) or isinstance(el, FabricationPart)) else el.Category.Name
    except Exception:
        kind = u'element'
    name = el_name(el)
    return u'{0} {1}{2}'.format(kind, eid_value(el.Id), u' ({0})'.format(name) if name else u'')


def log_context(uidoc, settings, log, title, symbol=None, cfg=None):
    u"""Everything worth knowing before a family job starts."""
    doc = uidoc.Document
    log.add(u'== {0}{1}'.format(title, u' (Family Floor Support tab)' if is_floor(settings) else u''))
    try:
        log.add(u'model: {0} | workshared: {1}'.format(doc.Title, doc.IsWorkshared))
    except Exception:
        pass
    try:
        v = uidoc.ActiveView
        log.add(u'view: {0} | type {1} | scale 1:{2}'.format(el_name(v), v.ViewType, v.Scale))
    except Exception:
        pass
    try:
        log.add(u'levels: {0}'.format(u', '.join(u'{0} @ {1}'.format(el_name(lv), fmm(e)) for lv, e in levels(doc))))
    except Exception:
        pass
    if symbol is not None:
        try:
            log.add(u'hanger: {0} : {1} | category {2} | placement {3} | active {4}'.format(
                el_name(symbol.Family), el_name(symbol), symbol.Category.Name,
                symbol.Family.FamilyPlacementType, symbol.IsActive))
        except Exception as ex:
            log.add(u'hanger: ? ({0})'.format(ex))
    if cfg is not None:
        log.add(u'family settings: ' + u' | '.join(u'{0}={1}'.format(k, cfg.get(k)) for k in sorted(cfg)))
    keys = sorted(k for k in settings if k.startswith(u'fam_'))
    log.add(u'tab settings: ' + u' | '.join(u'{0}={1}'.format(k, settings.get(k)) for k in keys))


def log_section(log, sec):
    if sec.get('unit'):
        log.add(u'   unit {0} wide x {1} long x {2} high | bottom face at {3} | hanger runs across it, '
                u'the unit runs along {4} | centre line {5} -> {6}'.format(
                    fmm(sec['width']), fmm(sec.get('length', 0.0)), fmm(sec['depth']), fmm(sec.get('bottom')),
                    sec.get('run_from', u'?'), fpt(sec['a']), fpt(sec['b'])))
        return
    ins = sec.get('ins', 0.0) or 0.0
    log.add(u'   duct {0} x {1} mm{2} | insulation {3} mm{4} | hanger fits {5} x {6} | centreline {7} -> {8}'.format(
        fmm(sec.get('bare_width', sec['width'])), fmm(sec.get('bare_depth', sec['depth'])),
        u' round' if sec['round'] else u'', fmm(ins),
        (u' (outside it)' if sec.get('ins_used') else u' (inside it)') if ins > 0 else u'',
        fmm(sec['width']), fmm(sec['depth']), fpt(sec['a']), fpt(sec['b'])))


# ============================================================ family list
def list_family_types(doc):
    u"""Every type of every family in the three hanger categories."""
    out = []
    for key, label in fc.CATEGORIES[1:]:
        b = bic_or_none(key)
        if b is None:
            continue  # MEP Ancillary Framing is not in every release
        try:
            col = FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(b)
        except Exception:
            continue
        for s in col:
            try:
                fam = el_name(s.Family)
                typ = el_name(s)
                out.append({'key': fc.item_key(fam, typ), 'family': fam, 'type': typ,
                            'cat': key, 'cat_label': label, 'id': s.Id})
            except Exception:
                continue
    out.sort(key=lambda d: (d['family'].lower(), d['type'].lower()))
    return out


def preview_bytes(doc, symbol_id, px=112):
    u"""PNG bytes of a type's preview image, or None."""
    try:
        s = doc.GetElement(symbol_id)
        bmp = s.GetPreviewImage(Size(px, px))
        if bmp is None:
            return None
        ms = MemoryStream()
        bmp.Save(ms, ImageFormat.Png)
        return ms.ToArray()
    except Exception:
        return None


def family_param_names(doc, symbol_id, log):
    u"""Names of the writable numeric instance parameters of the family.

    From an instance already in the model when there is one, otherwise by
    opening the family (read only, closed without saving)."""
    names = set()
    source = u''
    try:
        s = doc.GetElement(symbol_id)
        fam = s.Family
    except Exception:
        return [], u'type not found'
    try:
        for inst in FilteredElementCollector(doc).OfClass(FamilyInstance):
            try:
                if eid_value(inst.Symbol.Family.Id) != eid_value(fam.Id):
                    continue
            except Exception:
                continue
            for p in inst.Parameters:
                try:
                    if not p.IsReadOnly and str(p.StorageType) == 'Double':
                        names.add(p.Definition.Name)
                except Exception:
                    pass
            source = u'an instance in the model'
            break
    except Exception as ex:
        log.add(u'instance params: {0}'.format(ex))
    if not names:
        fdoc = None
        try:
            fdoc = doc.EditFamily(fam)
            for fp in fdoc.FamilyManager.Parameters:
                try:
                    if fp.IsInstance and str(fp.StorageType) == 'Double':
                        names.add(fp.Definition.Name)
                except Exception:
                    pass
            source = u'the family'
        except Exception as ex:
            log.add(u'family params: {0}'.format(ex))
            source = u'nothing (place one instance, then try again)'
        finally:
            try:
                if fdoc is not None:
                    fdoc.Close(False)
            except Exception:
                pass
    return sorted(names, key=lambda n: n.lower()), source


# ============================================================ duct geometry
def insulation_thickness(el):
    u"""Insulation thickness on a duct (0 when none).  Revit ducts: the
    DuctInsulation elements hosted on it; FAB parts: their own
    InsulationThickness."""
    if isinstance(el, CableTray):
        return 0.0
    if isinstance(el, FabricationPart):
        try:
            if el.HasInsulation:
                return float(el.InsulationThickness or 0.0)
        except Exception:
            pass
        try:
            return float(el.InsulationThickness or 0.0)
        except Exception:
            return 0.0
    t = 0.0
    try:
        doc = el.Document
        for iid in DB.InsulationLiningBase.GetInsulationIds(doc, el.Id):
            ins = doc.GetElement(iid)
            try:
                v = float(ins.Thickness)
            except Exception:
                v = (param_double(ins, 'RBS_INSULATION_THICKNESS_FOR_DUCT')
                     or param_double(ins, 'RBS_INSULATION_THICKNESS_FOR_PIPE') or 0.0)
            t = max(t, v)
    except Exception:
        pass
    return t


def section(el):
    sec = _section(el)
    sec['ins'] = insulation_thickness(el)
    return sec


def _section(el):
    u"""{'a','b','width','depth','round'} for a Revit duct or fabrication straight."""
    if isinstance(el, Pipe):
        c = el.Location.Curve
        a, b = pt(c.GetEndPoint(0)), pt(c.GetEndPoint(1))
        d = param_double(el, 'RBS_PIPE_OUTER_DIAMETER') or param_double(el, 'RBS_PIPE_DIAMETER_PARAM') or 0.0
        return {'a': a, 'b': b, 'width': d, 'depth': d, 'round': True}
    if isinstance(el, CableTray):
        c = el.Location.Curve
        a, b = pt(c.GetEndPoint(0)), pt(c.GetEndPoint(1))
        w = param_double(el, 'RBS_CABLETRAY_WIDTH_PARAM') or 0.0
        h = param_double(el, 'RBS_CABLETRAY_HEIGHT_PARAM') or 0.0
        return {'a': a, 'b': b, 'width': w, 'depth': h, 'round': False}
    if is_rvt_duct(el):
        c = el.Location.Curve
        a, b = pt(c.GetEndPoint(0)), pt(c.GetEndPoint(1))
        d = param_double(el, 'RBS_CURVE_DIAMETER_PARAM')
        if d:
            return {'a': a, 'b': b, 'width': d, 'depth': d, 'round': True}
        w = param_double(el, 'RBS_CURVE_WIDTH_PARAM') or 0.0
        h = param_double(el, 'RBS_CURVE_HEIGHT_PARAM') or 0.0
        return {'a': a, 'b': b, 'width': w, 'depth': h, 'round': False}
    ends, _sides = frv.end_pair(el, frv.all_conns(el))
    a, b = pt(ends[0].Origin), pt(ends[1].Origin)
    vals = {}
    try:
        for dd in el.GetDimensions():
            try:
                vals[(dd.Name or u'').strip().lower()] = float(el.GetDimensionValue(dd))
            except Exception:
                pass
    except Exception:
        pass
    w = vals.get(u'width') or vals.get(u'main width')
    dia = (vals.get(u'outside diameter') or vals.get(u'diameter') or vals.get(u'main diameter')
           or vals.get(u'nominal diameter'))
    if not w and dia:
        return {'a': a, 'b': b, 'width': dia, 'depth': dia, 'round': True}
    h = vals.get(u'depth') or vals.get(u'height') or vals.get(u'main depth') or 0.0
    return {'a': a, 'b': b, 'width': w or 0.0, 'depth': h, 'round': False}


def levels(doc):
    out = []
    for lv in FilteredElementCollector(doc).OfClass(Level):
        try:
            out.append((lv, lv.ProjectElevation))
        except Exception:
            pass
    out.sort(key=lambda x: x[1])
    return out


def _level_from_id(doc, lid):
    try:
        if lid is not None and eid_value(lid) > 0:
            lv = doc.GetElement(lid)
            if isinstance(lv, Level):
                return lv
    except Exception:
        pass
    return None


def element_level(doc, el, z=None):
    u"""The level an element is assigned to (reference / start / schedule level),
    else the level at or below z."""
    try:
        lv = el.ReferenceLevel
        if isinstance(lv, Level):
            return lv
    except Exception:
        pass
    try:
        lv = _level_from_id(doc, el.LevelId)
        if lv is not None:
            return lv
    except Exception:
        pass
    for name in ('RBS_START_LEVEL_PARAM', 'FABRICATION_LEVEL_PARAM', 'FAMILY_LEVEL_PARAM',
                 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM', 'SCHEDULE_LEVEL_PARAM'):
        try:
            b = bip(name)
            p = el.get_Parameter(b) if b is not None else None
            lv = _level_from_id(doc, p.AsElementId()) if p is not None else None
            if lv is not None:
                return lv
        except Exception:
            pass
    for nm in (u'Reference Level', u'Level', u'Schedule Level'):
        try:
            p = el.LookupParameter(nm)
            lv = _level_from_id(doc, p.AsElementId()) if p is not None else None
            if lv is not None:
                return lv
        except Exception:
            pass
    try:
        host = el.Host
        if isinstance(host, Level):
            return host
    except Exception:
        pass
    if z is not None:
        lvls = levels(doc)
        below = [lv for lv, e in lvls if e <= z + TOL]
        if below:
            return below[-1]
        if lvls:
            return lvls[0][0]
    return None


# ============================================================ parameters
OFFSET_BIPS = ('INSTANCE_ELEVATION_PARAM', 'INSTANCE_FREE_HOST_OFFSET_PARAM')
OFFSET_NAMES = (u'Elevation from Level', u'Offset from Host', u'Offset')


def offset_param(inst):
    for name in OFFSET_BIPS:
        try:
            b = bip(name)
            p = inst.get_Parameter(b) if b is not None else None
            if p is not None and not p.IsReadOnly:
                return p
        except Exception:
            pass
    for nm in OFFSET_NAMES:
        try:
            p = inst.LookupParameter(nm)
            if p is not None and not p.IsReadOnly:
                return p
        except Exception:
            pass
    return None


def set_length(inst, name, value):
    u"""True if the instance has a writable numeric parameter `name` and took value."""
    if not name:
        return False
    try:
        p = inst.LookupParameter(name)
        if p is None or p.IsReadOnly or str(p.StorageType) != 'Double':
            return False
        p.Set(float(value))
        return True
    except Exception:
        return False


def get_length(inst, name):
    try:
        p = inst.LookupParameter(name)
        return p.AsDouble() if p is not None else None
    except Exception:
        return None


def set_level(inst, level):
    for name in ('FAMILY_LEVEL_PARAM', 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM', 'SCHEDULE_LEVEL_PARAM'):
        try:
            b = bip(name)
            p = inst.get_Parameter(b) if b is not None else None
            if p is not None and not p.IsReadOnly:
                p.Set(level.Id)
                return True
        except Exception:
            pass
    return False


def is_floor(cfg_or_settings):
    u"""True for the Family Floor Support tab (cfg['mode'] or settings['_mode'])."""
    try:
        return (cfg_or_settings.get(u'mode') or cfg_or_settings.get(u'_mode')) == u'floor'
    except Exception:
        return False


def noun_of(settings):
    return u'floor support' if is_floor(settings) else u'hanger'


def floor_level(doc, service, z_invert, log=None):
    u"""The level a floor support stands on: the service's own level, unless
    that is above the service's invert - then the highest level below it."""
    level = element_level(doc, service, z_invert)
    if level is not None and level.ProjectElevation <= z_invert + TOL:
        return level
    below = [lv for lv, e in levels(doc) if e <= z_invert + TOL]
    if below:
        if log is not None:
            log.add(u'   the service\'s level {0} is above its invert - standing on {1}'.format(
                el_name(level) if level is not None else u'?', el_name(below[-1])))
        return below[-1]
    return level


# ============================================================ soffit
class SoffitFinder(object):
    u"""Where a drop rod should stop: the base of the level above (default) or
    the underside of structure above (ray, through fha_revit.Soffit)."""
    def __init__(self, doc, settings, log, want_structure):
        self.doc = doc
        self.lvls = [e for _lv, e in levels(doc)]
        self.ray = frv.Soffit(doc, settings, log) if want_structure else None

    def above(self, mode, x, y, z):
        if mode == u'structure' and self.ray is not None and self.ray.ok():
            hit = self.ray.above(x, y, z + 0.01)
            if hit is not None:
                return hit
        return fc.level_above(self.lvls, z)

    def close(self):
        if self.ray is not None:
            self.ray.close()


# ============================================================ placing
def align_rotation(doc, inst, want_x):
    u"""Turn the instance about its own vertical axis so its X axis lies along want_x."""
    try:
        cur = inst.HandOrientation
        ang = fc.rotation_to((cur.X, cur.Y), (want_x[0], want_x[1]))
        if abs(ang) > 1e-6:
            o = inst.Location.Point
            axis = Line.CreateBound(o, XYZ(o.X, o.Y, o.Z + 1.0))
            ElementTransformUtils.RotateElement(doc, inst.Id, axis, ang)
        return ang
    except Exception:
        return None


def fit_to_duct(doc, inst, sec, q, level, cfg, rod, finder, log, base_el=None):
    u"""Offset to the invert, square to the duct, width to the duct, rod to the
    soffit.  Caller holds the transaction.  Returns a list of problems."""
    problems = []
    z_bot = q[2] - sec['depth'] / 2.0
    along, across = fc.plan_dirs(sec['a'], sec['b'])
    ang = align_rotation(doc, inst, fc.family_x_dir(cfg[u'axis'], along, across))
    log.add(u'   level {0} @ {1} | invert {2} | turned {3} deg'.format(
        el_name(level), fmm(level.ProjectElevation), fmm(z_bot),
        u'{0:.1f}'.format(ang * 57.29577951) if ang is not None else u'? (rotation failed)'))
    floor = is_floor(cfg)
    stand = level.ProjectElevation   # where a floor support's base sits: its level ...
    p = offset_param(inst)
    if floor and base_el is not None and p is not None:   # ... or the top of the floor / roof / equipment picked
        stand = floor_stand(base_el, sec, q, z_bot, cfg, level, problems, log)
    elif floor and base_el is not None:
        problems.append(u'no writable offset parameter - the support could not be lifted onto the picked element')
    base = stand - level.ProjectElevation if floor else z_bot - level.ProjectElevation
    if p is None:
        if not floor:
            problems.append(u'no writable offset / elevation parameter')
        log.add(u'   offset: no writable Elevation from Level / Offset from Host')
    else:
        p.Set(base)
        log.add(u'   offset: {0} = {1}{2}'.format(p.Definition.Name, fmm(base), (
            u' (stands on the level)' if abs(base) < TOL else u' (stands on the picked element, hosted on the level)')
            if floor else u''))
    if floor:
        first, height = fc.floor_values(z_bot, stand, sec,
                                        core.parse_mm(cfg.get(u'height_clear', u'0'), 0.0) / MM)
        if first < -TOL:
            problems.append(u'the service is below what the support stands on')
        for key, label, val in ((u'first_bar', u'first bar', first), (u'height', u'support height', height)):
            ok = set_length(inst, cfg.get(key), val)
            log.add(u'   {0}: {1} = {2}{3}'.format(label, cfg.get(key) or u'(not set)', fmm(val), u'' if ok else u'  <- NOT SET'))
            if not ok:
                problems.append(u'{0} parameter "{1}" not found or read only - set it in Family settings'.format(
                    label, cfg.get(key) or u'(not set)'))
    clear = core.parse_mm(cfg.get(u'clearance', u'0'), 0.0) / MM
    axis_vec = (1.0, 0.0)
    try:
        doc.Regenerate()
        v = inst.HandOrientation if cfg.get(u'axis', u'X') == u'X' else inst.FacingOrientation
        axis_vec = (v.X, v.Y)
    except Exception:
        pass
    vals = dict(zip((u'left', u'right'), fc.side_values(sec, axis_vec, clear, cfg.get(u'swap') == u'1')))
    sec['set_left'], sec['set_right'] = vals[u'left'], vals[u'right']
    for key in (u'left', u'right'):
        ok = set_length(inst, cfg.get(key), vals[key])
        log.add(u'   width {0}: {1} = {2}{3}'.format(key, cfg.get(key) or u'(not set)', fmm(vals[key]),
                                                   u'' if ok else u'  <- NOT SET'))
        if not ok:
            problems.append(u'width parameter "{0}" not found or read only - set it in Family settings'.format(cfg.get(key) or u'(not set)'))
    if sec.get('ext_neg') is not None and abs(sec['ext_neg'] - sec['ext_pos']) > 1.0 / MM:
        check_sides(doc, inst, sec, q, cfg, vals, clear, log)
    if rod:
        top = finder.above(cfg.get(u'soffit', u'level'), q[0], q[1], z_bot)
        L = fc.rod_length(z_bot, top)
        if L is None:
            problems.append(u'no level / soffit above the hanger for the drop rod')
            log.add(u'   rod: nothing above {0} ({1})'.format(fmm(z_bot), cfg.get(u'soffit')))
        else:
            ok = set_length(inst, cfg.get(u'rod'), L)
            log.add(u'   rod: {0} = {1} (soffit {2} by {3}){4}'.format(
                cfg.get(u'rod'), fmm(L), fmm(top), cfg.get(u'soffit'), u'' if ok else u'  <- NOT SET'))
            if not ok:
                problems.append(u'drop rod parameter "{0}" not found'.format(cfg.get(u'rod')))
    return problems


def check_sides(doc, inst, sec, q, cfg, vals, clear, log):
    u"""A shared hanger reaches further one way than the other.  Measure where
    it actually went (its bounding box across the run) and, if the long side
    came out on the short side, swap the two width values."""
    try:
        doc.Regenerate()
        bb = inst.get_BoundingBox(None)
        corners = [(x, y) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        ac = sec['across']
        rp, rn = fc.reaches(corners, q, ac)
        wp, wn = sec['ext_pos'] + clear, sec['ext_neg'] + clear
        log.add(u'   reaches {0} / {1} mm either side (wanted {2} / {3})'.format(fmm(rp), fmm(rn), fmm(wp), fmm(wn)))
        if fc.sides_mirrored(rp, rn, wp, wn):
            vals[u'left'], vals[u'right'] = vals[u'right'], vals[u'left']
            for key in (u'left', u'right'):
                set_length(inst, cfg.get(key), vals[key])
            sec['set_left'], sec['set_right'] = vals[u'left'], vals[u'right']
            doc.Regenerate()
            bb = inst.get_BoundingBox(None)
            corners = [(x, y) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
            rp, rn = fc.reaches(corners, q, ac)
            log.add(u'   came out mirrored - swapped the widths: now {0} / {1} mm'.format(fmm(rp), fmm(rn)))
    except Exception as ex:
        log.add(u'   could not measure the hanger to check its sides: {0}'.format(ex))


def place_one(doc, symbol, duct, sec, q, cfg, rod, finder, log, ws=None, base_el=None):
    u"""Create one hanger at centreline point q.  Caller holds the transaction.
    Returns (instance, problems)."""
    if is_floor(cfg):
        level = floor_level(doc, duct, q[2] - sec['depth'] / 2.0, log)
    else:
        level = element_level(doc, duct, q[2])
    if level is None:
        return None, [u'the duct has no level']
    try:
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
    except Exception:
        pass
    along, across = fc.plan_dirs(sec['a'], sec['b'])
    want_x = fc.family_x_dir(cfg[u'axis'], along, across)
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
        ws.apply(inst, duct, True)
    else:
        frv.match_workset(inst, duct)
    log.add(u'+ hanger {0} on {1} at {2} ({3})'.format(eid_value(inst.Id), describe(duct), fpt(q), placement or u'?'))
    log_section(log, sec)
    problems = fit_to_duct(doc, inst, sec, q, level, cfg, rod, finder, log, base_el)
    frv.write_service_comment(inst, frv.services_of(doc, sec, duct), log)
    return inst, problems


def instance_point(inst):
    try:
        return pt(inst.Location.Point)
    except Exception:
        return None


def run_straights(doc, duct, limit=600):
    u"""(element, section) for every straight on the picked duct's run, walking
    through fittings and accessories, so each hanger can be fitted to the
    segment it actually hangs from (sizes change along a run)."""
    out = []
    seen = set([eid_value(duct.Id)])
    todo = [duct]
    while todo and len(seen) < limit:
        el = todo.pop()
        if is_host_duct(el):
            try:
                out.append((el, section(el)))
            except Exception:
                pass
        for c in g_conns(el):
            nb = g_neighbour(c)
            if nb is None:
                continue
            o = nb.Owner
            oid = eid_value(o.Id)
            if oid not in seen:
                seen.add(oid)
                todo.append(o)
    return out


def realign_one(doc, inst, duct, sec, cfg, rod, finder, log, ws=None, base_el=None):
    u"""Square a hanger up to its duct WITHOUT moving it along the run: it only
    slides sideways onto the centreline (the line is not clipped to the
    segment), then its level, invert, rotation, width and rod are refitted.
    Caller holds the transaction."""
    p = instance_point(inst)
    if p is None:
        return [u'the hanger has no location point']
    q = fc.on_line(sec['a'], sec['b'], p)
    log.add(u'~ hanger {0} at {1} -> {2} | sideways {3} mm | on {4}'.format(
        eid_value(inst.Id), fpt(p), fpt(q), fmm(fc.plan_offset(sec['a'], sec['b'], p)), describe(duct)))
    log_section(log, sec)
    try:
        ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(q[0] - p[0], q[1] - p[1], 0.0))
    except Exception as ex:
        return [u'could not move it: {0}'.format(ex)]
    if is_floor(cfg):
        duct_level = floor_level(doc, duct, q[2] - sec['depth'] / 2.0, log)
    else:
        duct_level = element_level(doc, duct, q[2])
    level = element_level(doc, inst, p[2])
    problems = []
    if duct_level is not None and (level is None or eid_value(level.Id) != eid_value(duct_level.Id)):
        if set_level(inst, duct_level):
            log.add(u'   level {0} -> {1}'.format(el_name(level) if level else u'?', el_name(duct_level)))
            level = duct_level
        else:
            problems.append(u'kept its own level (level is not editable on this family)')
    if ws is not None:
        ws.apply(inst, duct, False)
    doc.Regenerate()
    if level is None:
        return problems + [u'no level']
    return problems + fit_to_duct(doc, inst, sec, q, level, cfg, rod, finder, log, base_el)


# ================================================================ graph
def g_conns(el):
    if isinstance(el, FabricationPart):
        return frv.all_conns(el)
    cm = None
    try:
        cm = el.ConnectorManager
    except Exception:
        pass
    if cm is None:
        try:
            cm = el.MEPModel.ConnectorManager
        except Exception:
            cm = None
    out = []
    try:
        for c in cm.Connectors:
            try:
                if str(c.ConnectorType) == 'Logical':
                    continue
            except Exception:
                pass
            out.append(c)
    except Exception:
        pass
    out.sort(key=lambda c: c.Id)
    return out


PART_KIND = {
    'Elbow': 'bend', 'Offset': 'bend', 'Tee': 'tee', 'Cross': 'tee', 'Wye': 'tee',
    'LateralTee': 'tee', 'LateralCross': 'tee', 'Pants': 'tee', 'Transition': 'inline',
    'Union': 'inline', 'Cap': 'other', 'TapPerpendicular': 'tap', 'TapAdjustable': 'tap',
    'SpudPerpendicular': 'tap', 'SpudAdjustable': 'tap',
}


def g_kind(el, cons, accessories):
    if isinstance(el, FabricationPart):
        return frv.classify(el, cons)
    if is_rvt_duct(el):
        return 'straight'
    n = len(cons)
    if isinstance(el, FamilyInstance) and (cat_is(el, 'OST_DuctAccessory') or cat_is(el, 'OST_PipeAccessory')):
        if n >= 2:
            return 'accessory' if accessories else 'inline'
        return 'other'
    try:
        k = PART_KIND.get(str(el.MEPModel.PartType))
        if k:
            return k
    except Exception:
        pass
    if n == 1:
        return 'tap'
    if n == 2:
        return 'inline' if core.vdot(frv.axis(cons[0]), frv.axis(cons[1])) < -0.98 else 'bend'
    return 'tee' if n >= 3 else 'other'


def g_neighbour(c):
    try:
        own = eid_value(c.Owner.Id)
        for r in c.AllRefs:
            try:
                if str(r.ConnectorType) == 'Logical':
                    continue
            except Exception:
                pass
            o = r.Owner
            if o is not None and eid_value(o.Id) != own and is_run_member(o):
                return r
    except Exception:
        pass
    return None


def g_record(el, accessories):
    cons = g_conns(el)
    kind = g_kind(el, cons, accessories)
    sides = []
    side_ids = set()
    if kind == 'straight':
        ends, side = frv.end_pair(el, cons)
        sides = [pt(c.Origin) for c in side]
        side_ids = set(c.Id for c in side)
        cons = ends
    rec = {'kind': kind, 'len': 0.0, 'horizontal': True, 'conns': [], 'cobj': cons,
           'pts': [pt(c.Origin) for c in cons], 'cid': dict((c.Id, k) for k, c in enumerate(cons)),
           'sides': sides, 'side_ids': side_ids}
    if len(cons) >= 2:
        a, b = rec['pts'][0], rec['pts'][1]
        rec['len'] = core.vlen(core.vsub(b, a))
        if kind == 'straight':
            rec['horizontal'] = abs(b[2] - a[2]) < 0.1 * max(rec['len'], 1e-6)
    for c in cons:
        role = None
        if kind == 'tee':
            role = 'branch'
            for o in cons:
                if o is not c and abs(core.vdot(frv.axis(c), frv.axis(o))) > 0.98:
                    role = 'main'
        rec['conns'].append({'to': None, 'to_conn': None, 'role': role, '_nb': g_neighbour(c)})
    return rec


def build_graph(seeds, accessories, log):
    u"""The selected run plus one ring of neighbours that only type the span ends."""
    elems, parts = {}, {}
    selected = set(eid_value(e.Id) for e in seeds)
    for e in seeds:
        elems[eid_value(e.Id)] = e
        parts[eid_value(e.Id)] = g_record(e, accessories)
    for pid in list(selected):
        for c in parts[pid]['conns']:
            nb = c['_nb']
            if nb is None:
                continue
            nid = eid_value(nb.Owner.Id)
            if nid in parts:
                continue
            elems[nid] = nb.Owner
            rec = g_record(nb.Owner, accessories)
            if rec['kind'] == 'straight':
                rec['kind'] = 'other'   # a neighbouring straight is a boundary, not hung
            parts[nid] = rec
    taps = {}
    for pid, rec in parts.items():
        for c in rec['conns']:
            nb = c.pop('_nb', None)
            if nb is None or pid not in selected:
                continue
            nid = eid_value(nb.Owner.Id)
            other = parts.get(nid)
            if other is None:
                continue
            if nb.Id in other['cid']:
                c['to'], c['to_conn'] = nid, other['cid'][nb.Id]
            elif nb.Id in other.get('side_ids', ()):
                taps[-nid] = {'kind': 'tap', 'len': 0.0, 'horizontal': True, 'conns': []}
                c['to'], c['to_conn'] = -nid, None
    parts.update(taps)
    log.add(u'run: {0} parts, {1} selected'.format(len(parts), len(selected)))
    return parts, elems, selected


# ============================================================= dimension
def dim_ref_across(inst, along):
    u"""(reference, which) - the family's centre reference square to the run,
    chosen from the instance's own axes (so a hanger turned either way works),
    falling back to the other centre, then to a face square to the run."""
    try:
        h, f = inst.HandOrientation, inst.FacingOrientation
        first = fc.reference_type_across((h.X, h.Y), (f.X, f.Y), along)
    except Exception:
        first = 'CenterFrontBack'
    other = 'CenterLeftRight' if first == 'CenterFrontBack' else 'CenterFrontBack'
    for n in (first, other):
        try:
            refs = inst.GetReferences(getattr(DB.FamilyInstanceReferenceType, n))
            if refs is not None and refs.Count > 0:
                return refs[0], n
        except Exception:
            pass
    try:
        fs = frv.faces_across(inst, along, None)
        if fs:
            p = instance_point(inst)
            best = min(fs, key=lambda fa: abs(frv._t(fa, p, along)))
            return best.Reference, u'face'
    except Exception:
        pass
    return None, None


def dim_refs_for(inst, axis, along=None):
    if along is None:
        along = (0.0, 1.0, 0.0) if axis == u'X' else (1.0, 0.0, 0.0)
    return dim_ref_across(inst, along)[0]


def chain_dimension(doc, view, p_start, p_end, insts, first_el, last_el, axis, settings, log, dim_type=None):
    u"""One chained dimension along a run in `view`: the run's ends and every
    hanger's centre plane square to the run.  Revit refuses a dimension whose
    references it cannot see in that view (a duct end outside the crop, say),
    so if the full chain is refused it is tried again on the hangers alone.
    Every reason it gives up is logged.  Returns hangers dimensioned."""
    try:
        doc.Regenerate()   # hangers placed this run need geometry before another view can reference them
    except Exception:
        pass
    d = core.vnorm(core.vsub(p_end, p_start))
    hang = []
    for inst in insts:
        r, which = dim_ref_across(inst, d)
        p = instance_point(inst)
        if r is not None and p is not None:
            hang.append((core.vdot(core.vsub(p, p_start), d), r))
        else:
            log.add(u'   dimension: {0} {1} has no reference square to the run'.format(
                u'hanger', eid_value(inst.Id)))
    ends = []
    for el, at_end in ((first_el, False), (last_el, True)):
        fs = frv.faces_across(el, d, view)
        if fs:
            key = lambda f: frv._t(f, p_start, d)
            f = max(fs, key=key) if at_end else min(fs, key=key)
            ends.append((frv._t(f, p_start, d), f.Reference))
    p0, p1 = frv.view_dim_line(view, p_start, p_end, core.as_float(settings, u'fam_dim_offset', 800.0))
    line = Line.CreateBound(to_xyz(p0), to_xyz(p1))
    tries = [(u'run ends and hangers', hang + ends), (u'hangers only', hang)]
    last = None
    for label, items in tries:
        items = core.collapse_refs(items, 0.01)
        if not hang or len(items) < 2:
            last = u'{0} usable references ({1} hangers)'.format(len(items), len(hang))
            continue
        refs = ReferenceArray()
        for _t, r in items:
            refs.Append(r)
        try:
            if dim_type is not None:
                doc.Create.NewDimension(view, line, refs, dim_type)
            else:
                doc.Create.NewDimension(view, line, refs)
            log.add(u'   dimension in {0}: {1}, {2} references{3}'.format(
                el_name(view), label, len(items), u'' if label == tries[0][0] else u' (the full chain was refused)'))
            return len(hang)
        except Exception as ex:
            last = u'{0}: {1}'.format(label, ex)
            log.add(u'   dimension in {0} refused ({1})'.format(el_name(view), last))
    log.add(u'   no dimension in {0} - {1}'.format(el_name(view), last))
    return 0


# ============================================================= locks
PLAN_TYPES = ('FloorPlan', 'CeilingPlan', 'EngineeringPlan')


def geo_items(el, view):
    u"""(lines, planar faces) of an element with references (centreline included)."""
    lines, faces = [], []
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    if view is not None:
        opt.View = view

    def walk(geo):
        for g in geo:
            if isinstance(g, DB.GeometryInstance):
                walk(g.GetInstanceGeometry())
            elif isinstance(g, DB.Solid):
                for f in g.Faces:
                    if isinstance(f, DB.PlanarFace) and f.Reference is not None:
                        faces.append(f)
            elif isinstance(g, Line):
                try:
                    if g.Reference is not None:
                        lines.append(g)
                except Exception:
                    pass
    try:
        geo = el.get_Geometry(opt)
        if geo is not None:
            walk(geo)
    except Exception:
        pass
    return lines, faces


def host_kind(el):
    u"""'duct', 'pipe', ... for services; the category name for anything else."""
    if is_rvt_duct(el) or isinstance(el, FabricationPart):
        return service_kind(el)
    try:
        return el.Category.Name.lower()
    except Exception:
        return u'element'


def lock_section_name(host):
    return u'Hanger Automation - bottom locks {0} {1}'.format(host_kind(host), eid_value(host.Id))


def find_lock_section(doc, name):
    u"""A bottom-lock section made on an earlier run (exact name, else its
    first '(n)' copy), so each service keeps one."""
    best = None
    try:
        for v in FilteredElementCollector(doc).OfClass(DB.ViewSection):
            try:
                if v.IsTemplate:
                    continue
            except Exception:
                pass
            nm = el_name(v)
            if nm == name:
                return v
            if best is None and nm.startswith(name + u' ('):
                best = v
    except Exception:
        pass
    return best


def make_lock_section(doc, service, sec, log):
    u"""A section along the service that holds its hangers' bottom locks
    (a lock on a horizontal face lives in a section / elevation view and is
    deleted with it).  Reuses the one made on an earlier run."""
    base = lock_section_name(service)
    old = find_lock_section(doc, base)
    if old is not None:
        log.add(u'   lock section: reusing {0}'.format(el_name(old)))
        return old
    vft = None
    for v in FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if str(v.ViewFamily) == 'Section':
            vft = v
            break
    if vft is None:
        return None
    along, _across = fc.plan_dirs(sec['a'], sec['b'])
    L = core.vlen(core.vsub(sec['b'], sec['a']))
    mid = core.vscale(core.vadd(sec['a'], sec['b']), 0.5)
    tf = DB.Transform.Identity
    tf.Origin = to_xyz(mid)
    tf.BasisX = XYZ(along[0], along[1], 0.0)
    tf.BasisY = XYZ.BasisZ
    tf.BasisZ = XYZ(along[1], -along[0], 0.0)
    box = DB.BoundingBoxXYZ()
    box.Transform = tf
    half = L / 2.0 + 1.0
    box.Min = XYZ(-half, -(sec['depth'] / 2.0 + 3.0), -(sec['width'] / 2.0 + 2.0))
    box.Max = XYZ(half, sec['depth'] / 2.0 + 8.0, sec['width'] / 2.0 + 2.0)
    view = DB.ViewSection.CreateSection(doc, vft.Id, box)
    for n in range(20):
        try:
            view.Name = base if n == 0 else u'{0} ({1})'.format(base, n)
            break
        except Exception:
            continue
    try:
        doc.Regenerate()   # so the new view has geometry to take references from
    except Exception:
        pass
    log.add(u'   lock section: {0}'.format(el_name(view)))
    return view


REF_TYPES = ('CenterLeftRight', 'CenterFrontBack', 'CenterElevation', 'Left', 'Right', 'Front', 'Back',
             'Top', 'Bottom', 'StrongReference', 'WeakReference')
REF_LABELS = {'CenterLeftRight': u'Center (Left/Right)', 'CenterFrontBack': u'Center (Front/Back)',
              'CenterElevation': u'Center (Elevation)', 'StrongReference': u'Strong Reference',
              'WeakReference': u'Weak Reference'}


def instance_refs(inst, kinds):
    u"""[(reference, label)] of a family instance's reference planes of these
    FamilyInstanceReferenceTypes, in that order."""
    out = []
    for k in kinds:
        e = getattr(DB.FamilyInstanceReferenceType, k, None)
        if e is None:
            continue
        try:
            refs = inst.GetReferences(e)
        except Exception:
            refs = None
        if refs is None:
            continue
        for r in refs:
            nm = u''
            try:
                nm = inst.GetReferenceName(r) or u''
            except Exception:
                pass
            out.append((r, u'{0}{1}'.format(REF_LABELS.get(k, k), u' "{0}"'.format(nm) if nm else u'')))
    return out


def family_reference_summary(inst):
    u"""'Center (Left/Right) "CL", Strong Reference x2 ...' - what the family offers."""
    parts = []
    for k in REF_TYPES:
        got = instance_refs(inst, (k,))
        if got:
            parts.append(u', '.join(lbl for _r, lbl in got))
    return u'; '.join(parts) or u'none (every reference plane is Not a Reference)'


def walk_faces(geo, faces, pts, tf=None):
    u"""Planar faces with references and edge points of a geometry tree, in
    model coordinates: (face, origin z, normal z)."""
    for g in geo:
        if isinstance(g, DB.GeometryInstance):
            try:
                walk_faces(g.GetInstanceGeometry(), faces, pts, tf)
            except Exception:
                pass
        elif isinstance(g, DB.Solid):
            try:
                for f in g.Faces:
                    if isinstance(f, DB.PlanarFace) and f.Reference is not None:
                        faces.append((f, f.Origin.Z, f.FaceNormal.Z))
            except Exception:
                pass
            if pts is not None:
                try:
                    for ed in g.Edges:
                        for p in ed.Tessellate():
                            pts.append((p.X, p.Y, p.Z))
                except Exception:
                    pass


def element_faces(el, view=None, pts=None):
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = False
    if view is not None:
        opt.View = view
    else:
        try:
            opt.DetailLevel = getattr(DB.ViewDetailLevel, 'Fine')
        except Exception:
            pass
    faces = []
    try:
        geo = el.get_Geometry(opt)
        if geo is not None:
            walk_faces(geo, faces, pts)
    except Exception:
        pass
    return faces


def try_align(doc, view, targets, candidates, log, max_tries=80):
    u"""NewAlignment for the first (target, candidate) pair Revit accepts.
    Revit only aligns references that already coincide, so a wrong pair is
    simply refused.  Returns (target label, candidate label) or None."""
    n = 0
    last = None
    for rt, lt in targets:
        for rc, lc in candidates:
            n += 1
            if n > max_tries:
                return None, last
            try:
                doc.Create.NewAlignment(view, rt, rc)
                return (lt, lc), None
            except Exception as ex:
                last = u'{0}'.format(ex)
    return None, last


class Locker(object):
    u"""Align-locks a hanger to what it carries.

    Services: the hanger's centre plane along the run to the service centreline
    (plan view), and its face / plane at the invert to the service's bottom
    face - or its insulation's, when the hanger sits outside it (in a section
    kept per service).  Units (equipment, duct accessories): to the unit's
    centre planes and bottom face.  Single services only; shared hangers are
    never locked.  Every reference the family offers is tried, so a family
    whose centre plane is a Strong / Weak reference still locks."""
    def __init__(self, doc, view, log):
        self.doc, self.log = doc, log
        self.plan = view if (view is not None and str(view.ViewType) in PLAN_TYPES) else None
        self.sections = {}
        self.told = set()

    def _section(self, service, sec):
        key = eid_value(service.Id)
        if key in self.sections and not _alive(self.sections[key]):
            del self.sections[key]   # made in a placement Revit then undid: make it again
        if key not in self.sections:
            try:
                self.sections[key] = make_lock_section(self.doc, service, sec, self.log)
            except Exception as ex:
                self.log.add(u'   lock section: {0}'.format(ex))
                self.sections[key] = None
        return self.sections[key]

    def _tell_family(self, inst):
        try:
            key = eid_value(inst.Symbol.Family.Id)
        except Exception:
            key = None
        if key in self.told:
            return
        self.told.add(key)
        self.log.add(u'   family reference planes: {0}'.format(family_reference_summary(inst)))

    def lock(self, inst, host, sec, q):
        notes = []
        self._tell_family(inst)
        along, _across = fc.plan_dirs(sec['a'], sec['b'])
        unit = sec.get('unit', False)
        what = host_kind(host)
        # ---- centre: hanger plane along the run <-> service centreline / unit centre plane
        h, f = inst.HandOrientation, inst.FacingOrientation
        square = fc.reference_type_across((h.X, h.Y), (f.X, f.Y), along)
        along_type = 'CenterFrontBack' if square == 'CenterLeftRight' else 'CenterLeftRight'
        if self.plan is None:
            notes.append(u'centre lock needs a plan view open')
        else:
            cands = instance_refs(inst, (along_type, square, 'StrongReference', 'WeakReference',
                                         'Left', 'Right', 'Front', 'Back'))
            if unit:
                targets = instance_refs(host, ('CenterLeftRight', 'CenterFrontBack', 'StrongReference',
                                               'WeakReference'))
            else:
                lines, _f = geo_items(host, self.plan)
                targets = []
                for ln in lines:
                    try:
                        d = ln.Direction
                        if abs(d.X * along[0] + d.Y * along[1]) > 0.999:
                            targets.append((ln.Reference, u'centreline'))
                    except Exception:
                        pass
            if not targets:
                notes.append(u'no centreline reference on the {0}'.format(what) if not unit else
                             u'the {0} family has no centre reference planes'.format(what))
            elif not cands:
                notes.append(u'the hanger family has no reference planes to lock with - in the family editor set '
                             u'the centre plane that runs along the {0} to Is Reference: {1}'.format(
                                 what, REF_LABELS[along_type]))
            else:
                hit, err = try_align(self.doc, self.plan, targets, cands, self.log)
                if hit:
                    self.log.add(u'   locked to the {0}: hanger {1} <-> {2}'.format(
                        u'unit centre' if unit else u'centreline', hit[1], hit[0]))
                elif unit:
                    notes.append(u'the hanger is centred on the {0}\'s geometry, which is off its centre reference '
                                 u'planes - no centre lock'.format(what))
                else:
                    notes.append(u'no reference plane of the hanger lies on the {0} centreline ({1} tried) - in the '
                                 u'family editor set the centre plane that runs along the {0} to Is Reference: '
                                 u'{2}{3}'.format(what, len(cands), REF_LABELS[along_type],
                                                  u' (last refusal: {0})'.format(err) if err else u''))
        # ---- bottom: hanger at the invert <-> service / insulation / unit bottom face
        if sec.get('round'):
            self.log.add(u'   round {0}: centre lock only (no flat bottom face)'.format(what))
            return notes
        z_inv = q[2] - sec['depth'] / 2.0
        owners = [host]
        if sec.get('ins_used'):
            try:
                owners = [self.doc.GetElement(i) for i in
                          DB.InsulationLiningBase.GetInsulationIds(self.doc, host.Id)] or owners
            except Exception:
                pass
        downs = []
        for el in owners:
            downs.extend((fa, z) for fa, z, nz in element_faces(el) if nz < -0.99)
        if not downs:
            notes.append(u'no flat bottom face found on the {0}'.format(what))
            return notes
        z_low = min(z for _fa, z in downs)
        bottoms = [(fa.Reference, u'bottom face at {0}'.format(fmm(z))) for fa, z in downs if abs(z - z_low) < 2.0 / MM]
        if unit:
            bottoms += instance_refs(host, ('Bottom',))
        view = self._section(host, sec)
        if view is None:
            notes.append(u'no section view type for the bottom lock')
            return notes
        hfaces = element_faces(inst, view) or element_faces(inst)
        flats = [(fa, z, nz) for fa, z, nz in hfaces if abs(nz) > 0.99 and abs(z - z_inv) < 2.0 / MM]
        flats.sort(key=lambda x: -x[2])   # the upward face (bearer top) first
        cands = [(fa.Reference, u'face at {0}'.format(fmm(z))) for fa, z, _nz in flats]
        cands += instance_refs(inst, ('Bottom', 'Top', 'CenterElevation', 'StrongReference', 'WeakReference'))
        if not cands:
            heights = sorted(set(fmm(z) for _fa, z, nz in hfaces if abs(nz) > 0.99))
            notes.append(u'no face or reference plane of the hanger at the invert {0} (its flat faces are at {1})'.format(
                fmm(z_inv), u', '.join(heights) or u'-'))
            return notes
        hit, err = try_align(self.doc, view, bottoms, cands, self.log)
        if hit:
            self.log.add(u'   locked to the bottom: hanger {0} <-> {1} {2}'.format(hit[1], what, hit[0]))
        else:
            heights = sorted(set(fmm(z) for _fa, z, nz in hfaces if abs(nz) > 0.99))
            notes.append(u'bottom lock refused - the hanger has nothing exactly at the invert {0} '
                         u'(its flat faces are at {1}){2}'.format(
                             fmm(z_inv), u', '.join(heights) or u'-', u'; Revit: {0}'.format(err) if err else u''))
        return notes


def _alive(el):
    try:
        return el is None or bool(el.IsValidObject)
    except Exception:
        return True


def lock_if(locker, inst, service, sec, q, problems, log):
    u"""Lock a single-service hanger; shared hangers are never locked."""
    if locker is None or inst is None:
        return
    if len(sec.get('keys', [0])) > 1:
        log.add(u'   not locked: shared hanger')
        return
    for n in locker.lock(inst, service, sec, q):
        log.add(u'   lock: {0}'.format(n))
        problems.append(u'Lock: ' + n)


# ============================================================= bundles
def fitted(el, outside):
    return fc.apply_insulation(section(el), outside)


def bundle_for(lead, lead_sec, point, others, outside, log, rules=None):
    u"""(section, bundle) for one hanger round the lead service and any of the
    `others` that sit with it, by the Hanger rules (parallel, bottoms within
    the height limit, clear gaps under the gap limit).  `others`:
    [(element, fitted section)].  Every decision is logged."""
    z_tol, gap_tol, ang, centre = rules or (fc.BUNDLE_Z_MM / MM, fc.BUNDLE_GAP_MM / MM, fc.BUNDLE_ANGLE_DEG, u'mean')
    members = [(eid_value(lead.Id), lead_sec['a'], lead_sec['b'], lead_sec['width'], lead_sec['depth'])]
    for el, sc in others:
        if eid_value(el.Id) != eid_value(lead.Id):
            members.append((eid_value(el.Id), sc['a'], sc['b'], sc['width'], sc['depth']))
    b = fc.bundle(point, members, z_tol, gap_tol, ang, centre)
    if len(members) > 1:
        if len(b['keys']) > 1:
            log.add(u'   shared hanger: {0} | {1} centre | reaches {2} / {3} mm either side | {4} mm wide at the lowest invert {5}'.format(
                b['keys'], centre, fmm(b['ext_neg']), fmm(b['ext_pos']), fmm(b['width']), fmm(b['bottom'])))
        else:
            log.add(u'   no shared hanger here (rules: height {0} mm, gap {1} mm, {2} deg)'.format(
                fmm(z_tol), fmm(gap_tol), ang))
        for n in b['notes']:
            log.add(u'      {0}'.format(n))
    return fc.bundle_section(b, lead_sec), fc.bundle_point(b, lead_sec, point)


def selected_services(uidoc, outside):
    out = []
    for i in uidoc.Selection.GetElementIds():
        e = uidoc.Document.GetElement(i)
        if e is not None and is_host_duct(e):
            out.append((e, fitted(e, outside)))
    return out


def unit_section_of(el, log):
    u"""Section of a unit (equipment / duct accessory) for a hanger under it:
    its bottom face, its width across, the way it runs (in-line connectors,
    else its longer side)."""
    pts = []
    faces = element_faces(el, None, pts)
    downs = [z for _fa, z, nz in faces if nz < -0.99]
    bottom = min(downs) if downs else None
    if not pts:
        try:
            bb = el.get_BoundingBox(None)
            pts = [(x, y, z) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y) for z in (bb.Min.Z, bb.Max.Z)]
            log.add(u'   no solid geometry read - sized from its bounding box')
        except Exception:
            return None
    conns = []
    for c in g_conns(el):
        try:
            bz = c.CoordinateSystem.BasisZ
            conns.append((pt(c.Origin), (bz.X, bz.Y, bz.Z)))
        except Exception:
            pass
    hint = fc.inline_direction(conns)
    try:
        h, f = el.HandOrientation, el.FacingOrientation
        hand, facing = (h.X, h.Y), (f.X, f.Y)
    except Exception:
        hand, facing = (1.0, 0.0), (0.0, 1.0)
    sec = fc.unit_section(hand, facing, pts, bottom, hint)
    if bottom is None:
        log.add(u'   no flat bottom face - using the lowest point of the unit')
    return sec


# ================================================================== jobs
def _chosen(uidoc, settings, res):
    fam = settings.get(u'_fam') or {}
    sid = fam.get('id')
    symbol = uidoc.Document.GetElement(sid) if sid is not None else None
    if symbol is None:
        res['lines'].append(u'Choose a hanger family and type first.')
        return None, None
    cfg = dict(fam.get('cfg') or fc.FAM_DEFAULTS)
    cfg[u'mode'] = settings.get(u'_mode', u'hang')
    return symbol, cfg


def _verify(inst, cfg, sec, res, problems, log):
    u"""Read back after commit: the width parameters must hold half the duct."""
    try:
        if not inst.IsValidObject:
            return False
    except Exception:
        return False
    half = fc.half_width(sec['width'], core.parse_mm(cfg.get(u'clearance', u'0'), 0.0))
    for key in (u'left', u'right'):
        want = sec.get('set_' + key, half)
        v = get_length(inst, cfg.get(key))
        if v is not None and abs(v - want) > TOL:
            problems.append(u'{0} reads {1:.0f} mm, not {2:.0f} mm'.format(cfg.get(key), v * MM, want * MM))
    return True


def job_place(uidoc, settings, log):
    doc = uidoc.Document
    res = frv.new_result(u'Place {0} on service'.format(noun_of(settings)))
    symbol, cfg = _chosen(uidoc, settings, res)
    if symbol is None:
        return res
    rod = core.as_bool(settings, u'fam_rod_place') and not is_floor(settings)
    outside = core.as_bool(settings, u'fam_ins_place')
    log_context(uidoc, settings, log, u'Place {0} on service'.format(noun_of(settings)), symbol, cfg)
    # Services selected before pressing the button are hung TOGETHER: one hanger
    # round every one of them that runs parallel alongside the click, however far
    # apart or uneven in height (you chose them) - at the lowest invert.
    rules = fc.wrap_rules(fc.group_rules(settings))
    locker = Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_place') else None
    group = selected_services(uidoc, outside)
    if group:
        log.add(u'pre-selected services - one {0} goes round all of them at each click: '.format(noun_of(settings)) +
                u', '.join(describe(e) for e, _s in group))
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    picked_base = floor_base_pick(uidoc, settings, res, log)
    base_el = BaseSurface(doc, picked_base[0], picked_base[1], log) if picked_base else None
    if base_el is not None:
        log.add(u'supports stand on {0}'.format(base_el.label()))
    finder = SoffitFinder(doc, settings, log, rod and cfg.get(u'soffit') == u'structure')
    issues = []
    fam_id = eid_value(symbol.Family.Id)

    def pick_test(e):
        if is_host_duct(e):
            return True
        if not is_unit(e):
            return False
        try:
            return eid_value(e.Symbol.Family.Id) != fam_id   # not a hanger of the chosen family
        except Exception:
            return True
    try:
        while True:
            try:
                prompt = (u'Click on one of the selected services where the {0} goes - it goes round all of them '
                          u'(Esc to finish)' if group else
                          u'Click on a duct, pipe, cable tray, mechanical equipment or duct accessory where the {0} '
                          u'goes (Esc to finish)').format(noun_of(settings))
                duct, p = pick_duct_point(uidoc, prompt, pick_test)
            except Exception:
                break   # Esc
            log.add(u'click on {0} at {1}'.format(describe(duct), fpt(p) if p else u'(no point - using the middle)'))
            unit = not is_host_duct(duct)
            if unit:
                sec = unit_section_of(duct, log)
                if sec is None:
                    issues.append(u'Could not read the size of {0}.'.format(describe(duct)))
                    continue
            else:
                sec = fc.apply_insulation(section(duct), outside)
            if p is None:
                p = core.vscale(core.vadd(sec['a'], sec['b']), 0.5)
            q = fc.on_centreline(sec['a'], sec['b'], p, END_MARGIN)
            sec['keys'] = [eid_value(duct.Id)]
            if group and not unit:
                sec, q = bundle_for(duct, sec, q, group, outside, log, rules)
                left = [e for e, _s in group if eid_value(e.Id) not in sec['keys']]
                if left:
                    issues.append(u'Left out of the combined {0}: {1} - not parallel to the clicked service, or not '
                                  u'running alongside it where you clicked.'.format(
                                      noun_of(settings), u', '.join(describe(e) for e in left)))
            t = frv.start_txn(doc, u'Place hanger on duct')
            try:
                inst, problems = place_one(doc, symbol, duct, sec, q, cfg, rod, finder, log, ws, base_el)
                lock_if(locker, inst, duct, sec, q, problems, log)
                if inst is None or not frv.committed(t):
                    frv.rollback(t)
                    res['failed'] += 1
                    issues.extend(problems)
                    continue
                if _verify(inst, cfg, sec, res, problems, log):
                    res['done'] += 1
                issues.extend(problems)
            except Exception as ex:
                log.add(u'place: {0}'.format(ex))
                frv.rollback(t)
                res['failed'] += 1
    finally:
        finder.close()
        if base_el is not None:
            base_el.close()
    res['lines'].extend(sorted(set(issues)))
    res['lines'].extend(ws.problems)
    return res


def job_realign(uidoc, settings, log):
    doc = uidoc.Document
    res = frv.new_result(u'Re-align {0}s to service'.format(noun_of(settings)))
    symbol, chosen_cfg = _chosen(uidoc, settings, res)
    fams = settings.get(u'_fams') or {}
    picked = [e for e, _s in selected_services(uidoc, True)]
    if not picked:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, _Filter(is_host_duct),
                                               u'Pick the duct, pipe or cable tray (several to hang together), then Finish')
            picked = [doc.GetElement(r.ElementId) for r in refs]
        except Exception:
            picked = []
    if not picked:
        res['lines'].append(u'No service picked.')
        return res
    duct = picked[0]
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, _Filter(is_hanger_family),
                                           u'Pick the hangers to re-align, then Finish')
        hangers = [doc.GetElement(r.ElementId) for r in refs]
    except Exception:
        hangers = []
    if not hangers:
        res['lines'].append(u'No hangers picked.')
        return res
    log_context(uidoc, settings, log, u'Re-align {0}s to service'.format(noun_of(settings)), symbol, chosen_cfg)
    log.add(u'picked {0}; {1} hangers'.format(u', '.join(describe(e) for e in picked), len(hangers)))
    straights = []
    seen = set()
    for svc in picked:
        for e, sc in run_straights(doc, svc):
            if eid_value(e.Id) not in seen:
                seen.add(eid_value(e.Id))
                straights.append((e, sc))
    log.add(u'run: {0} straights - {1}'.format(len(straights), u', '.join(
        u'{0} {1}x{2}'.format(eid_value(e.Id), fmm(sc['width']), fmm(sc['depth'])) for e, sc in straights)))
    by_id = dict((eid_value(e.Id), (e, sc)) for e, sc in straights)
    segs = [(eid_value(e.Id), sc['a'], sc['b']) for e, sc in straights]
    rod = core.as_bool(settings, u'fam_rod_realign') and not is_floor(settings)
    outside = core.as_bool(settings, u'fam_ins_realign')
    rules = fc.group_rules(settings)
    locker = Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_realign') else None
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    frv.checkout(doc, hangers, log)
    picked_base = floor_base_pick(uidoc, settings, res, log)
    tg = TransactionGroup(doc, u'Hanger Automation - re-align hangers')
    tg.Start()
    base_el = BaseSurface(doc, picked_base[0], picked_base[1], log) if picked_base else None
    finder = None
    issues = []
    done = []
    try:
        cfgs = []
        for h in hangers:
            fam = el_name(h.Symbol.Family)
            cfg = dict(fc.fam_config(fams, fam) if fam in fams else (chosen_cfg or fc.fam_config(fams, fam)))
            cfg[u'mode'] = settings.get(u'_mode', u'hang')
            cfgs.append(cfg)
        finder = SoffitFinder(doc, settings, log, rod and any(c.get(u'soffit') == u'structure' for c in cfgs))
        for h, cfg in zip(hangers, cfgs):
            p = instance_point(h)
            key = fc.pick_segment(p, segs, 300.0 / MM) if p is not None else None
            seg_el, sec = by_id.get(key, (duct, section(duct)))
            sec = fc.apply_insulation(sec, outside)
            if p is not None and len(picked) > 1:
                q0 = fc.on_line(sec['a'], sec['b'], p)
                others = [(e, fc.apply_insulation(sc, outside)) for e, sc in straights]
                sec, _q = bundle_for(seg_el, sec, q0, others, outside, log, rules)
            if key is None:
                log.add(u'hanger {0}: not over any straight of the run - using the picked duct'.format(eid_value(h.Id)))
            t = frv.start_txn(doc, u'Re-align hanger')
            try:
                problems = realign_one(doc, h, seg_el, sec, cfg, rod, finder, log, ws, base_el)
                if p is not None:
                    lock_if(locker, h, seg_el, sec, fc.on_line(sec['a'], sec['b'], p), problems, log)
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
        if finder is not None:
            finder.close()
        if base_el is not None:
            base_el.close()
        tg.Assimilate()
    for h, cfg, sec in done:
        if _verify(h, cfg, sec, res, issues, log):
            res['done'] += 1
    res['lines'].extend(sorted(set(issues)))
    res['lines'].extend(ws.problems)
    return res


def existing_points(doc, symbol):
    u"""Locations of hangers already in the model: the chosen family and fab hangers."""
    out = []
    fid = eid_value(symbol.Family.Id)
    col = FilteredElementCollector(doc).OfClass(FamilyInstance)
    try:
        col = col.OfCategoryId(symbol.Category.Id)
    except Exception:
        pass
    for inst in col:
        try:
            if eid_value(inst.Symbol.Family.Id) == fid:
                p = instance_point(inst)
                if p is not None:
                    out.append(p)
        except Exception:
            pass
    try:
        for h in FilteredElementCollector(doc).OfCategory(frv.bic('OST_FabricationHangers')).WhereElementIsNotElementType():
            p = frv.hanger_point(h)
            if p is not None:
                out.append(p)
    except Exception:
        pass
    return out


def job_auto(uidoc, settings, log):
    u"""Hangers along a selected duct run.

    Spans of horizontal straights run between bends, tees, takeoffs, set downs
    and (ticked) in-line accessories.  Per span: the first hanger at the start
    offset, then at most the span's spacing apart (your maximum, capped by
    DW/144 for the duct size), a hanger at the end offset before a bend, set
    down or accessory with the spacing shrunk to fit, nothing on takeoff stubs,
    hangers moved clear of taps, kept off joints and flanges by the flange
    clearance, and skipped where a hanger already is.
    """
    doc = uidoc.Document
    res = frv.new_result(u'Auto place {0}s along run'.format(noun_of(settings)))
    symbol, cfg = _chosen(uidoc, settings, res)
    if symbol is None:
        return res
    seeds = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    seeds = [e for e in seeds if e is not None and is_run_member(e)]
    if not seeds:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, _Filter(is_run_member),
                                               u'Select the run(s) - ducts, pipes or cable trays and their fittings - then Finish')
            seeds = [doc.GetElement(r.ElementId) for r in refs]
        except Exception:
            seeds = []
    if not seeds:
        res['lines'].append(u'No ducts selected.')
        return res
    accessories = core.as_bool(settings, u'fam_accessory')
    log_context(uidoc, settings, log, u'Auto place {0}s along run'.format(noun_of(settings)), symbol, cfg)
    log.add(u'selected: ' + u', '.join(describe(e) for e in seeds[:60]) + (u' ...' if len(seeds) > 60 else u''))
    parts, elems, selected = build_graph(seeds, accessories, log)
    for pid in sorted(parts):
        rec = parts[pid]
        log.add(u'   part {0}: {1} len {2} {3}| links {4}'.format(
            pid, rec['kind'], fmm(rec['len']), u'' if rec.get('horizontal', True) else u'(not flat) ',
            [c['to'] for c in rec['conns']]))
    spans = [s for s in core.build_spans(parts)
             if any(it['id'] in selected for it in s['chain'] if it['kind'] == 'straight')]
    if not spans:
        res['lines'].append(u'No horizontal straight runs in the selection.')
        return res
    flange = core.as_float(settings, u'fam_flange_clear', 150.0) / MM
    user_max = core.as_float(settings, u'fam_spacing', 3000.0)
    use_dw = core.as_bool(settings, u'fam_dw144')
    takeoff_clear = core.as_float(settings, u'fam_takeoff_clear', 400.0) / MM
    existing = existing_points(doc, symbol) if core.as_bool(settings, u'fam_skip_existing') else []
    exist_clear = core.as_float(settings, u'existing_clear', 300.0) / MM
    tap_pts = frv.all_tap_points(doc)
    rod = core.as_bool(settings, u'fam_rod_auto') and not is_floor(settings)
    outside = core.as_bool(settings, u'fam_ins_auto')
    rules = fc.group_rules(settings)
    locker = Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_auto') else None
    targets = frv.dim_targets(uidoc, settings, u'fam_dims', res, log)   # asks in a 3D view
    want_dims = targets is not None
    dim_type = frv.find_dim_type(doc, settings.get(u'fam_dim_type', u''))

    # services that can share a hanger: every selected straight
    pool = [(elems[pid], fitted(elems[pid], outside)) for pid in sorted(selected)
            if pid in elems and is_host_duct(elems[pid])]
    sized = []
    for span in spans:
        ws = [section(elems[it['id']])['width'] for it in span['chain'] if it['kind'] == 'straight']
        sized.append((-max(ws), span))
    spans = [sp for _w, sp in sorted(sized, key=lambda x: x[0])]   # widest first leads a group
    covered = []   # (centre, service ids) of shared hangers placed this run

    picked_base = floor_base_pick(uidoc, settings, res, log)
    tg = TransactionGroup(doc, u'Hanger Automation - hangers along run')
    tg.Start()
    base_el = BaseSurface(doc, picked_base[0], picked_base[1], log) if picked_base else None
    if base_el is not None:
        log.add(u'supports stand on {0}'.format(base_el.label()))
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    finder = SoffitFinder(doc, settings, log, rod and cfg.get(u'soffit') == u'structure')
    issues, made_all = [], []
    dimmed = 0
    n_jobs = 0
    try:
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
            straight_els = [elems[it['id']] for it in chain if it['kind'] == 'straight']
            secs = [section(e) for e in straight_els]
            width = max(sc['width'] for sc in secs)
            depth = max(sc['depth'] for sc in secs)
            is_round = all(sc['round'] for sc in secs)
            duct_run = all(is_ductwork(e) for e in straight_els)
            spacing = fc.span_spacing_mm(user_max, use_dw and duct_run, width * MM, depth * MM, is_round)
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
            # only hangers that really sit on THIS span count: on it (not round a
            # bend on the next duct), within reach of its centreline; shared
            # hangers placed this run only where this span is one of their services
            span_keys = set(it['id'] for it in chain if it['kind'] == 'straight')
            reach = width / 2.0 + rules[1] / 2.0
            dz_reach = 1000.0 if is_floor(cfg) else 5.0   # floor supports stand far below their service
            mine = [cq for cq, keys in covered if span_keys & set(keys)]
            for pts_list, counted, what, off in ((existing, True, u'hangers already in the model', reach),
                                                 (mine, False, u'shared hangers placed this run', 10.0)):
                if pts_list:
                    ex_st = [x for x in (core.station_on_run(segs, e, off, max_dz_ft=dz_reach) for e in pts_list)
                             if x is not None]
                    before = list(st)
                    st = core.drop_near(st, ex_st, exist_clear)
                    if len(st) < len(before):
                        log.add(u'   dropped {0} -> {1} (within {2} mm of {3} at {4})'.format(
                            [fmm(x) for x in before], [fmm(x) for x in st], fmm(exist_clear), what,
                            [fmm(x) for x in ex_st]))
                    if counted:
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
            log.add(u'span {0} mm [{1}] {2} {3}->{4} | {5}x{6}{7} | spacing {8:.0f}{9} | planned {10} | takeoffs at {11} | placing at {12}'.format(
                fmm(length), u','.join(str(it['id']) for it in chain), service_kind(straight_els[0]),
                span['start_end']['type'], span['end_end']['type'], fmm(width), fmm(depth),
                u' round' if is_round else u'', spacing, u'' if duct_run else u' (not ductwork: no DW/144 cap)',
                [fmm(x) for x in planned], [fmm(x) for x in block_st], [fpt(q) for _d, q in places]))
            if not places:
                continue
            n_jobs += 1
            made = []
            for host, q in places:
                sec = fitted(host, outside)
                if len(pool) > 1:
                    sec, q = bundle_for(host, sec, q, pool, outside, log, rules)
                t = frv.start_txn(doc, u'Place hanger')
                try:
                    inst, problems = place_one(doc, symbol, host, sec, q, cfg, rod, finder, log, ws, base_el)
                    lock_if(locker, inst, host, sec, q, problems, log)
                    issues.extend(problems)
                    if inst is not None and frv.committed(t):
                        made.append((inst, sec))
                        if len(sec.get('keys', [])) > 1:
                            covered.append((q, sec['keys']))
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
                if frv.dimension_in_targets(
                        doc, targets, p_start, p_end,
                        lambda v, a=p_start, b=p_end, hs=hs, f=first_el, l=last_el: chain_dimension(
                            doc, v, a, b, hs, f, l, cfg[u'axis'], settings, log, dim_type), log):
                    dimmed += 1
            made_all.extend(made)
    finally:
        finder.close()
        if base_el is not None:
            base_el.close()
        tg.Assimilate()
    if not made_all and not res['failed']:
        res['lines'].append(u'Nothing to place - every span already has its hangers or is too short.')
    for inst, sec in made_all:
        if _verify(inst, cfg, sec, res, issues, log):
            res['done'] += 1
        else:
            res['failed'] += 1
    if res['skipped']:
        res['lines'].append(u'{0} skipped where a hanger already was (untick "Skip existing hangers" to place anyway).'.format(res['skipped']))
    if want_dims:
        res['lines'].append(targets.summary(dimmed, n_jobs))
        frv.offer_open(uidoc, settings, targets, dimmed, log)
    res['lines'].extend(sorted(set(issues)))
    res['lines'].extend(ws.problems)
    return res


# ===================================================== drop rod extender
def make_temp_3d(doc, log):
    u"""A clean isometric view (no template, no section box) for ray casting.
    Returns (view, made_here)."""
    t = frv.start_txn(doc, u'Temporary 3D view')
    try:
        vft = None
        for v in FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
            if str(v.ViewFamily) == 'ThreeDimensional':
                vft = v
                break
        view = DB.View3D.CreateIsometric(doc, vft.Id)
        try:
            view.ViewTemplateId = DB.ElementId.InvalidElementId
        except Exception:
            pass
        if frv.committed(t):
            return view, True
    except Exception as ex:
        frv.rollback(t)
        log.add(u'temporary 3D view: {0}'.format(ex))
    for v in FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate:
            return v, False
    return None, False


def drop_temp_view(doc, view, made, log):
    if view is None or not made:
        return
    t = frv.start_txn(doc, u'Remove temporary 3D view')
    try:
        doc.Delete(view.Id)
        frv.committed(t)
    except Exception as ex:
        frv.rollback(t)
        log.add(u'remove temporary view: {0}'.format(ex))


class Target(object):
    u"""The element the drop rods go up to, in this model or a linked one.

    underside(x, y, z): the first face of that element straight above the
    point (a ray through a clean temporary 3D view, links included); when the
    element is not directly above, its lowest point (its invert) instead."""
    def __init__(self, doc, el, link, log):
        self.doc, self.el, self.link, self.log = doc, el, link, log
        self.view, self.made = make_temp_3d(doc, log)
        self.ri = None
        try:
            if self.view is not None:
                if link is None:
                    self.ri = ReferenceIntersector(el.Id, FindReferenceTarget.Face, self.view)
                else:
                    self.ri = ReferenceIntersector(ElementCategoryFilter(el.Category.Id), FindReferenceTarget.Face, self.view)
                    self.ri.FindReferencesInRevitLinks = True
        except Exception as ex:
            log.add(u'target ray: {0}'.format(ex))

    def label(self):
        where = u'link {0}'.format(el_name(self.link)) if self.link is not None else u'this model'
        try:
            cat = self.el.Category.Name
        except Exception:
            cat = u'element'
        return u'{0} {1} ({2}) in {3}'.format(cat, eid_value(self.el.Id), el_name(self.el), where)

    def lowest(self):
        try:
            bb = self.el.get_BoundingBox(None)
            if self.link is None:
                return bb.Min.Z
            tf = self.link.GetTotalTransform()
            return min(tf.OfPoint(bb.Min).Z, tf.OfPoint(bb.Max).Z)
        except Exception:
            return None

    def underside(self, x, y, z):
        origin = XYZ(x, y, z + 0.01)
        if self.ri is not None:
            try:
                if self.link is None:
                    hit = self.ri.FindNearest(origin, XYZ.BasisZ)
                    if hit is not None:
                        return hit.GetReference().GlobalPoint.Z, u'ray'
                else:
                    hits = sorted(list(self.ri.Find(origin, XYZ.BasisZ)), key=lambda h: h.Proximity)
                    for h in hits:
                        r = h.GetReference()
                        if eid_value(r.ElementId) == eid_value(self.link.Id) and \
                                eid_value(r.LinkedElementId) == eid_value(self.el.Id):
                            return r.GlobalPoint.Z, u'ray'
            except Exception as ex:
                self.log.add(u'target ray: {0}'.format(ex))
        low = self.lowest()
        return (low, u'lowest point') if low is not None and low > z else (None, u'not above')

    def close(self):
        drop_temp_view(self.doc, self.view, self.made, self.log)


def pick_target(uidoc, linked_first, log):
    u"""(element, link instance or None).  Clicking a linked model goes on to
    a second click on the element inside it."""
    doc = uidoc.Document
    prompt = u'Click the element to extend the drop rods to (floor, beam, steel, service...)'
    if not linked_first:
        ref = uidoc.Selection.PickObject(ObjectType.Element, prompt)
        el = doc.GetElement(ref.ElementId)
        if not isinstance(el, RevitLinkInstance):
            return el, None
        log.add(u'clicked link {0} - now picking inside it'.format(el_name(el)))
    ref = uidoc.Selection.PickObject(ObjectType.LinkedElement, u'Click the element in the linked model')
    link = doc.GetElement(ref.ElementId)
    ldoc = link.GetLinkDocument()
    return ldoc.GetElement(ref.LinkedElementId), link


# ============================================================ floor base
BASE_CATS = ('OST_Floors', 'OST_Roofs', 'OST_MechanicalEquipment', 'OST_StructuralFoundation')


def base_ok(e):
    return isinstance(e, RevitLinkInstance) or any(cat_is(e, c) for c in BASE_CATS)


class BaseSurface(Target):
    u"""The floor, roof or mechanical equipment floor supports stand on, in this
    model or a linked one.  stand(): the top surface straight below a support's
    centre (a ray down through a clean temporary 3D view, links included) - on
    a slope that is the height where the centre meets it.  If the centre is off
    the surface, the highest hit under either post (its edge); then the top of
    its bounding box when the support is over it."""
    def top_at(self, x, y, z_from):
        if self.ri is None:
            return None
        origin = XYZ(x, y, z_from - 0.003)
        down = XYZ(0.0, 0.0, -1.0)
        try:
            if self.link is None:
                hit = self.ri.FindNearest(origin, down)
                return hit.GetReference().GlobalPoint.Z if hit is not None else None
            hits = sorted(list(self.ri.Find(origin, down)), key=lambda h: h.Proximity)
            for h in hits:
                r = h.GetReference()
                if eid_value(r.ElementId) == eid_value(self.link.Id) and \
                        eid_value(r.LinkedElementId) == eid_value(self.el.Id):
                    return r.GlobalPoint.Z
        except Exception as ex:
            self.log.add(u'   base ray: {0}'.format(ex))
        return None

    def box_top(self, x, y):
        try:
            bb = self.el.get_BoundingBox(None)
            pts = [XYZ(px, py, pz) for px in (bb.Min.X, bb.Max.X) for py in (bb.Min.Y, bb.Max.Y)
                   for pz in (bb.Min.Z, bb.Max.Z)]
            if self.link is not None:
                tf = self.link.GetTotalTransform()
                pts = [tf.OfPoint(p) for p in pts]
            xs, ys, zs = [p.X for p in pts], [p.Y for p in pts], [p.Z for p in pts]
            if min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys):
                return max(zs)
        except Exception:
            pass
        return None

    def stand(self, q, z_from, posts):
        u"""(z or None, how, [z under each post])"""
        zc = self.top_at(q[0], q[1], z_from)
        under = [self.top_at(px, py, z_from) for px, py in posts]
        if zc is not None:
            return zc, u'its top surface under the centre', under
        hits = [z for z in under if z is not None]
        if hits:
            return max(hits), u'its edge (the centre is off the surface)', under
        zb = self.box_top(q[0], q[1])
        if zb is not None and zb <= z_from:
            return zb, u'the top of its box (no face hit)', under
        return None, u'not under this support', under


def floor_stand(base_el, sec, q, z_bot, cfg, level, problems, log):
    u"""Height a floor support's base stands at on the picked element, or its
    level (with a problem) when the element is not under it."""
    along, across = fc.plan_dirs(sec['a'], sec['b'])
    clear = core.parse_mm(cfg.get(u'clearance', u'0'), 0.0) / MM
    hn = sec.get('ext_neg', sec['width'] / 2.0) + clear
    hp = sec.get('ext_pos', sec['width'] / 2.0) + clear
    posts = [(q[0] - across[0] * hn, q[1] - across[1] * hn), (q[0] + across[0] * hp, q[1] + across[1] * hp)]
    z, how, under = base_el.stand(q, z_bot, posts)
    shown = [fmm(u) if u is not None else u'-' for u in under]
    if z is None:
        problems.append(u'the picked base is not under every support - those stand on the level')
        log.add(u'   base: {0} is not under it - standing on the level'.format(base_el.label()))
        return level.ProjectElevation
    fall = [u for u in under if u is not None]
    slope = u' | falls {0} mm across the frame'.format(fmm(max(fall) - min(fall))) if len(fall) == 2 and \
        abs(fall[0] - fall[1]) > 1.0 / MM else u''
    log.add(u'   base: stands at {0} on {1} ({2}) | under the posts {3}{4}'.format(
        fmm(z), base_el.label(), how, u' / '.join(shown), slope))
    if z > z_bot + TOL:
        problems.append(u'the picked base is above the service there - that support stands on the level')
        return level.ProjectElevation
    return z


def pick_base(uidoc, linked_first, log):
    u"""(element, link instance or None) the floor supports stand on."""
    doc = uidoc.Document
    if not linked_first:
        ref = uidoc.Selection.PickObject(ObjectType.Element, _Filter(base_ok),
                                         u'Click the floor, roof or mechanical equipment the supports stand on '
                                         u'(or a linked model) - Esc stands them on the level')
        el = doc.GetElement(ref.ElementId)
        if not isinstance(el, RevitLinkInstance):
            return el, None
        log.add(u'clicked link {0} - now picking inside it'.format(el_name(el)))
    ref = uidoc.Selection.PickObject(ObjectType.LinkedElement, u'Click the floor, roof or equipment in the linked model')
    link = doc.GetElement(ref.ElementId)
    return link.GetLinkDocument().GetElement(ref.LinkedElementId), link


def floor_base_pick(uidoc, settings, res, log):
    u"""Floor Support tab with 'Supports stand on: a picked element': ask for it.
    (element, link) or None (the level).  Call before any transaction group."""
    if not is_floor(settings) or settings.get(u'flr_base', u'level') != u'element':
        return None
    linked = core.as_bool(settings, u'flr_base_linked')
    ui = settings.get(u'_ui')
    if ui is not None:   # say so first: a pick with only Revit's status bar to tell you looks like a hang
        try:
            ans = ui.ask_base_pick(linked)
        except Exception as ex:
            log.add(u'base prompt: {0}'.format(ex))
            ans = u'pick'
        log.add(u'base: asked to pick - {0}'.format(ans or u'closed'))
        if ans != u'pick':
            res['lines'].append(u'No base picked - the supports stand on the level.')
            return None
    try:
        el, link = pick_base(uidoc, linked, log)
    except Exception:
        res['lines'].append(u'No base picked - the supports stand on the level.')
        return None
    if el is None:
        return None
    if not any(cat_is(el, c) for c in BASE_CATS):
        log.add(u'base: {0} is not a floor, roof or equipment - using it anyway'.format(describe(el)))
    return el, link


def job_rods(uidoc, settings, log):
    u"""Drop rod extender: pick hangers, then any element above them (this
    model or a link); each hanger's drop rod runs from its reference level up
    to that element's underside above it, or its lowest point."""
    doc = uidoc.Document
    res = frv.new_result(u'Drop rod extender')
    log_context(uidoc, settings, log, u'Drop rod extender')
    fams = settings.get(u'_fams') or {}
    chosen = settings.get(u'_fam') or {}
    hangers = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    hangers = [h for h in hangers if h is not None and is_hanger_family(h)]
    if not hangers:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, _Filter(is_hanger_family),
                                               u'Pick the hangers (box or click), then Finish')
            hangers = [doc.GetElement(r.ElementId) for r in refs]
        except Exception:
            hangers = []
    if not hangers:
        res['lines'].append(u'No hangers picked.')
        return res
    try:
        el, link = pick_target(uidoc, core.as_bool(settings, u'fam_rod_linked'), log)
    except Exception:
        res['lines'].append(u'No target picked.')
        return res
    frv.checkout(doc, hangers, log)
    ws = frv.Worksets(doc, settings.get(u'fam_workset', u''), log)
    tg = TransactionGroup(doc, u'Hanger Automation - extend drop rods')
    tg.Start()
    target = Target(doc, el, link, log)
    log.add(u'target: {0} | lowest point {1}'.format(target.label(), fmm(target.lowest())))
    try:
        for h in hangers:
            fam = el_name(h.Symbol.Family)
            cfg = fams.get(fam) or (chosen.get('cfg') if chosen.get('family') == fam else None) or fc.fam_config(fams, fam)
            p = instance_point(h)
            if p is None:
                res['failed'] += 1
                continue
            top, how = target.underside(p[0], p[1], p[2])
            L = fc.rod_to_target(p[2], top)
            log.add(u'hanger {0} ({1}) ref {2} -> target {3} by {4}: rod {5} = {6}'.format(
                eid_value(h.Id), fam, fmm(p[2]), fmm(top), how, cfg.get(u'rod'), fmm(L)))
            if L is None:
                res['skipped'] += 1
                res['lines'].append(u'Hanger {0}: the target is not above it.'.format(eid_value(h.Id)))
                continue
            t = frv.start_txn(doc, u'Extend drop rod')
            ok_rod = set_length(h, cfg.get(u'rod'), L)
            if ok_rod:
                ws.apply(h, None, False)
            if ok_rod and frv.committed(t):
                if abs((get_length(h, cfg.get(u'rod')) or 0.0) - L) < TOL:
                    res['done'] += 1
                else:
                    res['failed'] += 1
            else:
                frv.rollback(t)
                res['failed'] += 1
                res['lines'].append(u'Hanger {0}: no writable "{1}" parameter - check Family settings.'.format(
                    eid_value(h.Id), cfg.get(u'rod')))
    finally:
        target.close()
        tg.Assimilate()
    res['lines'].insert(0, u'Target: {0}'.format(target.label()))
    res['lines'].extend(ws.problems)
    return res


# ======================================================= dimension placer
def is_floor_plan(view):
    try:
        return (not view.IsTemplate) and str(view.ViewType) == 'FloorPlan'
    except Exception:
        return False


def view_hangers(doc, view, family_names):
    u"""Hanger family instances visible in the view: the configured / chosen
    families, plus anything in MEP Ancillary Framing."""
    out = []
    try:
        col = FilteredElementCollector(doc, view.Id).OfClass(FamilyInstance)
    except Exception:
        return out
    for e in col:
        try:
            if hanger_cat_key(e) is None:
                continue
            if el_name(e.Symbol.Family) in family_names or cat_is(e, 'OST_MEPAncillaryFraming'):
                out.append(e)
        except Exception:
            pass
    return out


def view_dimension_ids(doc, view):
    ids = []
    try:
        for d in FilteredElementCollector(doc, view.Id).OfCategory(frv.bic('OST_Dimensions')).WhereElementIsNotElementType():
            ids.append(d.Id)
    except Exception:
        pass
    return ids


def reset_isolate(doc, view, log):
    t = frv.start_txn(doc, u'Hanger dimensions - show all')
    try:
        view.DisableTemporaryViewMode(getattr(DB.TemporaryViewMode, 'TemporaryHideIsolate'))
        frv.committed(t)
    except Exception as ex:
        frv.rollback(t)
        log.add(u'reset isolate: {0}'.format(ex))


def isolate(doc, view, ids, log):
    t = frv.start_txn(doc, u'Hanger dimensions - isolate hangers')
    try:
        lst = List[DB.ElementId]()
        for i in ids:
            lst.Add(i)
        view.IsolateElementsTemporary(lst)
        return frv.committed(t)
    except Exception as ex:
        frv.rollback(t)
        log.add(u'isolate: {0}'.format(ex))
        return False


def run_direction(inst, cfg):
    u"""The direction of the duct run at a hanger: square to its width axis."""
    try:
        if cfg.get(u'axis', u'X') == u'X':
            v = inst.FacingOrientation
        else:
            v = inst.HandOrientation
        return (v.X, v.Y, 0.0)
    except Exception:
        return None


def job_dims(uidoc, settings, log):
    u"""Dimension placer: floor plans only.  Isolates the hangers (keeping
    dimensions visible), lets the user box-select or click hangers, then puts a
    centre-to-centre chained dimension along each straight line of hangers,
    offset by the chosen distance, and restores the view."""
    doc = uidoc.Document
    view = uidoc.ActiveView
    res = frv.new_result(u'Dimension placer')
    log_context(uidoc, settings, log, u'Dimension placer')
    if not is_floor_plan(view):
        res['lines'].append(u'Open a floor plan first - the dimension placer only works in floor plans.')
        return res
    fams = settings.get(u'_fams') or {}
    chosen = settings.get(u'_fam') or {}
    names = set(fams)
    if chosen.get('family'):
        names.add(chosen['family'])
    hangers = view_hangers(doc, view, names)
    log.add(u'hangers in view: {0} (families {1})'.format(len(hangers), sorted(names)))
    if not hangers:
        res['lines'].append(u'No hanger families are visible in this view.')
        return res
    allowed = set(eid_value(h.Id) for h in hangers)
    reset_isolate(doc, view, log)
    isolated = isolate(doc, view, [h.Id for h in hangers] + view_dimension_ids(doc, view), log)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    picked = []
    try:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element,
                                               _Filter(lambda e: eid_value(e.Id) in allowed),
                                               u'Select hangers to dimension (box or click), then Finish')
            picked = [doc.GetElement(r.ElementId) for r in refs]
        except Exception:
            picked = []
        log.add(u'picked {0} hangers{1}'.format(len(picked), u'' if isolated else u' (view could not be isolated)'))
        if len(picked) < 2:
            res['lines'].append(u'Pick at least two hangers.')
            return res
        items = []
        cfg_default = chosen.get('cfg') or dict(fc.FAM_DEFAULTS)
        by_key = {}
        for i, h in enumerate(picked):
            cfg = fams.get(el_name(h.Symbol.Family), cfg_default)
            p = instance_point(h)
            d = run_direction(h, cfg)
            if p is None or d is None:
                log.add(u'hanger {0}: no location / orientation'.format(eid_value(h.Id)))
                continue
            items.append((i, p, d))
            by_key[i] = h
        groups = fc.group_runs(items, 300.0 / MM)
        grouped = set(k for _d, ks in groups for k in ks)
        lonely = [eid_value(by_key[k].Id) for k in by_key if k not in grouped]
        offset = core.as_float(settings, u'fam_dim_offset', 800.0)
        dim_type = frv.find_dim_type(doc, settings.get(u'fam_dim_type', u''))
        t = frv.start_txn(doc, u'Hanger dimensions')
        made = 0
        try:
            for d, keys in groups:
                insts = [by_key[k] for k in keys]
                pts = [instance_point(h) for h in insts]
                refs = []
                kinds = []
                for h, p in zip(insts, pts):
                    r, which = dim_ref_across(h, d)
                    kinds.append(which)
                    if r is not None:
                        refs.append((core.vdot(p, d), r))
                refs = core.collapse_refs(refs, 0.01)
                log.add(u'run along ({0:.3f}, {1:.3f}): hangers {2} | references {3}'.format(
                    d[0], d[1], [eid_value(h.Id) for h in insts], kinds))
                if len(refs) < 2:
                    log.add(u'   skipped - fewer than two usable references')
                    continue
                arr = ReferenceArray()
                for _s, r in refs:
                    arr.Append(r)
                z = pts[0][2]
                p0, p1, _n = core.dim_line((pts[0][0], pts[0][1], z), (pts[-1][0], pts[-1][1], z), offset, 0.0)
                line = Line.CreateBound(to_xyz(p0), to_xyz(p1))
                try:
                    if dim_type is not None:
                        doc.Create.NewDimension(view, line, arr, dim_type)
                    else:
                        doc.Create.NewDimension(view, line, arr)
                    made += 1
                    res['done'] += len(refs)
                    log.add(u'   dimension {0} -> {1}, {2} references'.format(fpt(p0), fpt(p1), len(refs)))
                except Exception as ex:
                    res['failed'] += 1
                    log.add(u'   NewDimension refused: {0}'.format(ex))
            if made:
                frv.committed(t)
            else:
                frv.rollback(t)
        except Exception as ex:
            log.add(u'dimensions: {0}'.format(ex))
            frv.rollback(t)
        res['title'] = u'Dimension placer'
        res['lines'].append(u'{0} chained dimension{1} on {2} run{3}.'.format(
            made, u'' if made == 1 else u's', len(groups), u'' if len(groups) == 1 else u's'))
        if lonely:
            res['skipped'] += len(lonely)
            res['lines'].append(u'{0} hanger(s) not in line with another picked hanger: {1}'.format(len(lonely), lonely))
        return res
    finally:
        reset_isolate(doc, view, log)
        try:
            uidoc.RefreshActiveView()
        except Exception:
            pass


# ============================================================ quiet jobs
def list_job(uidoc, settings, log):
    return list_family_types(uidoc.Document)


def preview_job_for(symbol_id):
    def job(uidoc, settings, log):
        return preview_bytes(uidoc.Document, symbol_id)
    return job


def params_job_for(symbol_id):
    def job(uidoc, settings, log):
        return family_param_names(uidoc.Document, symbol_id, log)
    return job
