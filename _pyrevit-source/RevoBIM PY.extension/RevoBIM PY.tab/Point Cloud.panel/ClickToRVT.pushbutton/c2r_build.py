# -*- coding: utf-8 -*-
"""Click to RVT Element - what the project offers and how to place it.

`read_catalogue` lists every type the recogniser can choose between, with
the sizes each one allows. The creators place one recognised shape as one
element and return its ids. They run inside a transaction opened by
c2r_jobs; none opens one of its own.
"""
import c2r_clr  # noqa: F401

import math

from System.Collections.Generic import List
from Autodesk.Revit.DB import (FilteredElementCollector, Level, XYZ, Line, CurveLoop, Curve,
                               BuiltInParameter, BuiltInCategory, FamilySymbol, WallType, WallKind,
                               FloorType, CeilingType, Wall, Floor, Ceiling, ElementTransformUtils,
                               RoutingPreferenceRuleGroupType, Element)
from Autodesk.Revit.DB.Plumbing import Pipe, PipeType, PipingSystemType, PipeSegment
from Autodesk.Revit.DB.Mechanical import Duct, DuctType, MechanicalSystemType, DuctSizeSettings
from Autodesk.Revit.DB.Electrical import (CableTray, CableTrayType, Conduit, ConduitType,
                                          CableTraySizes, ConduitSizeSettings)
from Autodesk.Revit.DB.Structure import StructuralType

import c2r_core as core

MM = core.MM_PER_FT

FALLBACK_ROUND = [63, 80, 100, 125, 150, 160, 200, 250, 315, 355, 400, 450, 500, 560, 630, 710, 800, 900, 1000]
FALLBACK_RECT = [100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 700, 800, 900, 1000, 1200, 1400, 1600, 1800, 2000]
FALLBACK_TRAY = [50, 75, 100, 150, 225, 300, 450, 600, 750, 900]


# =====================================================================
# helpers
# =====================================================================

def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def ename(e):
    """Name of an element or type without tripping IronPython's Name quirk."""
    for getter in (lambda x: x.Name, lambda x: Element.Name.__get__(x), lambda x: Element.Name.GetValue(x)):
        try:
            n = getter(e)
            if n:
                return n
        except Exception:
            pass
    for bip in (u'SYMBOL_NAME_PARAM', u'ALL_MODEL_TYPE_NAME'):
        try:
            p = e.get_Parameter(getattr(BuiltInParameter, bip))
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    return u'?'


def bip(name):
    return getattr(BuiltInParameter, name)


def set_param(e, name, value):
    """Set a built-in parameter; True only if it reads back."""
    try:
        p = e.get_Parameter(bip(name))
        if p is None or p.IsReadOnly:
            return False
        p.Set(value)
        return True
    except Exception:
        return False


def xyz(p):
    return XYZ(p[0] / MM, p[1] / MM, p[2] / MM)


def _sym_dim(sym, names):
    for n in names:
        try:
            p = sym.LookupParameter(n)
            if p is not None and p.HasValue:
                v = p.AsDouble() * MM
                if v > 1.0:
                    return v
        except Exception:
            pass
    return None


# =====================================================================
# catalogue
# =====================================================================

def _pipe_sizes(doc, ptype):
    sizes = {}
    try:
        rpm = ptype.RoutingPreferenceManager
        grp = RoutingPreferenceRuleGroupType.Segments
        for i in range(rpm.GetNumberOfRules(grp)):
            seg = doc.GetElement(rpm.GetRule(grp, i).MEPPartId)
            if not isinstance(seg, PipeSegment):
                continue
            for s in seg.GetSizes():
                nom = round(s.NominalDiameter * MM, 2)
                if nom not in sizes:
                    sizes[nom] = s.OuterDiameter * MM
    except Exception:
        pass
    return sorted(sizes.items())


def _duct_sizes(doc):
    rnd = []
    rect = []
    try:
        dss = DuctSizeSettings.GetDuctSizeSettings(doc)
        for kv in dss:
            shape = u'{0}'.format(kv.Key)
            for s in kv.Value:
                try:
                    if not s.UsedInSizeLists:
                        continue
                except Exception:
                    pass
                v = round(s.NominalDiameter * MM, 1)
                if u'Round' in shape:
                    rnd.append(v)
                elif u'Rect' in shape:
                    rect.append(v)
    except Exception:
        pass
    return (sorted(set(rnd)) or FALLBACK_ROUND), (sorted(set(rect)) or FALLBACK_RECT)


def _tray_widths(doc):
    out = []
    try:
        for s in CableTraySizes.GetCableTraySizes(doc):
            out.append(round(s.NominalDiameter * MM, 1))
    except Exception:
        pass
    return sorted(set(out)) or FALLBACK_TRAY


def _conduit_sizes(doc):
    out = {}
    try:
        for kv in ConduitSizeSettings.GetConduitSizeSettings(doc):
            for s in kv.Value:
                nom = round(s.NominalDiameter * MM, 2)
                out.setdefault(nom, s.OuterDiameter * MM)
    except Exception:
        pass
    return sorted(out.items())


def _shape_of(dtype):
    try:
        s = u'{0}'.format(dtype.Shape)
    except Exception:
        s = u''
    if u'Round' in s:
        return u'round'
    if u'Rect' in s:
        return u'rect'
    if u'Oval' in s:
        return u'oval'
    n = ename(dtype).lower()
    if u'round' in n or u'circ' in n:
        return u'round'
    return u'rect'


def read_catalogue(doc, st):
    cat = {}
    col = lambda cls: list(FilteredElementCollector(doc).OfClass(cls).ToElements())
    cat[u'pipe'] = [{u'name': ename(t), u'id': t.Id, u'sizes': _pipe_sizes(doc, t)} for t in col(PipeType)]
    cat[u'pipe'] = [t for t in cat[u'pipe'] if t[u'sizes']]
    rnd, rect = _duct_sizes(doc)
    cat[u'duct'] = [{u'name': ename(t), u'id': t.Id, u'shape': _shape_of(t)} for t in col(DuctType)]
    cat[u'duct_round_sizes'] = rnd
    cat[u'duct_rect_sizes'] = rect
    cat[u'tray'] = [{u'name': ename(t), u'id': t.Id} for t in col(CableTrayType)]
    cat[u'tray_widths'] = _tray_widths(doc)
    csz = _conduit_sizes(doc)
    cat[u'conduit'] = [{u'name': ename(t), u'id': t.Id, u'sizes': csz} for t in col(ConduitType)] if csz else []
    walls = []
    for t in col(WallType):
        try:
            if t.Kind != WallKind.Basic:
                continue
            walls.append({u'name': ename(t), u'id': t.Id, u'width': round(t.Width * MM, 1)})
        except Exception:
            pass
    cat[u'wall'] = walls
    floors = []
    for t in col(FloorType):
        try:
            if t.IsFoundationSlab:
                continue
        except Exception:
            pass
        floors.append({u'name': ename(t), u'id': t.Id})
    cat[u'floor'] = floors
    cat[u'ceiling'] = [{u'name': ename(t), u'id': t.Id} for t in col(CeilingType)]
    for kind, bic, wkey, dkey in ((u'column', u'OST_StructuralColumns', u'column_w_params', u'column_d_params'),
                                  (u'beam', u'OST_StructuralFraming', u'beam_w_params', u'beam_d_params')):
        lst = []
        try:
            syms = FilteredElementCollector(doc).OfCategory(getattr(BuiltInCategory, bic)).OfClass(FamilySymbol).ToElements()
        except Exception:
            syms = []
        for s in syms:
            w = _sym_dim(s, core.param_names(st[wkey]))
            d = _sym_dim(s, core.param_names(st[dkey]))
            try:
                fam = s.FamilyName
            except Exception:
                fam = u''
            lst.append({u'name': (fam + u': ' if fam else u'') + ename(s), u'id': s.Id, u'w': w, u'd': d})
        cat[kind] = lst
    cat[u'pipe_systems'] = [(ename(t), t.Id) for t in col(PipingSystemType)]
    cat[u'duct_systems'] = [(ename(t), t.Id) for t in col(MechanicalSystemType)]
    levels = []
    for l in col(Level):
        levels.append((ename(l), l.ProjectElevation * MM, l.Id))
    cat[u'levels'] = sorted(levels, key=lambda x: x[1])
    for k in core.KIND_KEYS:
        if k in cat:
            cat[k].sort(key=lambda t: t[u'name'])
    return cat


# =====================================================================
# creators - each returns the ids it created
# =====================================================================

class Placement(object):
    """What a creator needs beyond the shape and the type."""

    def __init__(self, doc, cat, opts, st, log):
        self.doc = doc
        self.cat = cat
        self.opts = opts
        self.st = st
        self.log = log

    def level(self, z):
        levels = self.cat[u'levels']
        want = self.opts.get(u'level') or u''
        if want:
            for l in levels:
                if l[0] == want:
                    return l
        return core.level_below(levels, z) or (levels[0] if levels else None)

    def level_el(self, lvl):
        return self.doc.GetElement(lvl[2])

    def system(self, key):
        lst = self.cat.get(key) or []
        want = self.opts.get(u'pipe_system' if key == u'pipe_systems' else u'duct_system') or u''
        for n, i in lst:
            if n == want:
                return i
        if lst:
            return lst[0][1]
        raise ValueError(u'The model has no {0} system types'.format(u'piping' if key == u'pipe_systems' else u'duct'))


def _need_level(lvl):
    if lvl is None:
        raise ValueError(u'The model has no levels')
    return lvl


def make_pipe(pl, cand, rec):
    lvl = _need_level(pl.level(min(rec[u'p0'][2], rec[u'p1'][2])))
    e = Pipe.Create(pl.doc, pl.system(u'pipe_systems'), cand[u'type'][u'id'], lvl[2], xyz(rec[u'p0']), xyz(rec[u'p1']))
    set_param(e, u'RBS_PIPE_DIAMETER_PARAM', cand[u'size'][u'diameter'] / MM)
    return [e.Id]


def make_conduit(pl, cand, rec):
    lvl = _need_level(pl.level(min(rec[u'p0'][2], rec[u'p1'][2])))
    e = Conduit.Create(pl.doc, cand[u'type'][u'id'], xyz(rec[u'p0']), xyz(rec[u'p1']), lvl[2])
    set_param(e, u'RBS_CONDUIT_DIAMETER_PARAM', cand[u'size'][u'diameter'] / MM)
    return [e.Id]


def _width_direction(rec, swap=False):
    a, s, t = rec[u'frame']
    ang = rec.get(u'angle', 0.0) + (math.pi / 2 if swap else 0.0)
    return core.v_add(core.v_mul(s, math.cos(ang)), core.v_mul(t, math.sin(ang)))


def _turn_upright(pl, e, rec, swap=False):
    """A vertical rectangular run is turned about its axis to sit square to
    the cloud's outline."""
    if not rec.get(u'vertical'):
        return
    try:
        pl.doc.Regenerate()
        want = _width_direction(rec, swap)
        cur = None
        for c in e.ConnectorManager.Connectors:
            bx = c.CoordinateSystem.BasisX
            cur = (bx.X, bx.Y, 0.0)
            break
        if cur is None:
            return
        ang = math.atan2(want[1], want[0]) - math.atan2(cur[1], cur[0])
        while ang > math.pi / 2:
            ang -= math.pi
        while ang < -math.pi / 2:
            ang += math.pi
        if abs(ang) > math.radians(0.5):
            p = xyz(rec[u'p0'])
            ElementTransformUtils.RotateElement(pl.doc, e.Id, Line.CreateBound(p, p + XYZ.BasisZ), ang)
    except Exception as ex:
        pl.log(u'rotate: {0}'.format(ex))


def make_duct(pl, cand, rec):
    lvl = _need_level(pl.level(min(rec[u'p0'][2], rec[u'p1'][2])))
    e = Duct.Create(pl.doc, pl.system(u'duct_systems'), cand[u'type'][u'id'], lvl[2], xyz(rec[u'p0']), xyz(rec[u'p1']))
    sz = cand[u'size']
    if sz.get(u'shape') == u'round':
        set_param(e, u'RBS_CURVE_DIAMETER_PARAM', sz[u'diameter'] / MM)
    else:
        set_param(e, u'RBS_CURVE_WIDTH_PARAM', sz[u'width'] / MM)
        set_param(e, u'RBS_CURVE_HEIGHT_PARAM', sz[u'height'] / MM)
        _turn_upright(pl, e, rec)
    return [e.Id]


def make_tray(pl, cand, rec):
    lvl = _need_level(pl.level(min(rec[u'p0'][2], rec[u'p1'][2])))
    e = CableTray.Create(pl.doc, cand[u'type'][u'id'], xyz(rec[u'p0']), xyz(rec[u'p1']), lvl[2])
    set_param(e, u'RBS_CABLETRAY_WIDTH_PARAM', cand[u'size'][u'width'] / MM)
    set_param(e, u'RBS_CABLETRAY_HEIGHT_PARAM', cand[u'size'][u'height'] / MM)
    return [e.Id]


def make_wall(pl, cand, rec):
    width = cand[u'size'][u'width']
    off = core.v_mul(rec[u'body'], width / 2.0)
    a = core.v_add(rec[u'face_a'], off)
    b = core.v_add(rec[u'face_b'], off)
    base = rec[u'base_z']
    lvl = _need_level(pl.level(base + 300.0))
    offset = base - lvl[1]
    if abs(offset) < 150.0:
        offset = 0.0
    z = lvl[1] + offset
    height = max(300.0, rec[u'top_z'] - z)
    line = Line.CreateBound(xyz((a[0], a[1], lvl[1])), xyz((b[0], b[1], lvl[1])))
    e = Wall.Create(pl.doc, line, cand[u'type'][u'id'], lvl[2], height / MM, offset / MM, False, False)
    if pl.st[u'wall_height'] == u'levels':
        above = core.level_above(pl.cat[u'levels'], lvl[1])
        if above is not None:
            set_param(e, u'WALL_HEIGHT_TYPE', above[2])
            set_param(e, u'WALL_TOP_OFFSET', 0.0)
    return [e.Id]


def _loop(points, z):
    cl = CurveLoop()
    n = len(points)
    for k in range(n):
        p = points[k]
        q = points[(k + 1) % n]
        cl.Append(Line.CreateBound(xyz((p[0], p[1], z)), xyz((q[0], q[1], z))))
    return cl


def _ccw(points):
    return points if core.polygon_area(points) >= 0 else list(reversed(points))


def make_slab(pl, cand, rec):
    kind = cand[u'kind']
    z = rec[u'z']
    lvl = _need_level(pl.level(z + 50.0))
    loops = []
    if pl.st[u'floor_outline'] == u'traced' and len(rec[u'loop']) >= 4:
        loops.append(_ccw(rec[u'loop']))
    loops.append(_ccw(rec[u'rect_loop']))
    last = None
    for k in range(len(loops)):
        pts = loops[k]
        try:
            lst = List[CurveLoop]()
            lst.Add(_loop(pts, lvl[1]))
            if kind == u'floor':
                e = Floor.Create(pl.doc, lst, cand[u'type'][u'id'], lvl[2])
                set_param(e, u'FLOOR_HEIGHTABOVELEVEL_PARAM', (z - lvl[1]) / MM)
            else:
                e = Ceiling.Create(pl.doc, lst, cand[u'type'][u'id'], lvl[2])
                set_param(e, u'CEILING_HEIGHTABOVELEVEL_PARAM', (z - lvl[1]) / MM)
            if k == len(loops) - 1:
                pl.log(u'slab: placed with the rectangle outline')
            return [e.Id]
        except Exception as ex:
            last = ex
            pl.log(u'slab: outline refused ({0}), trying the rectangle'.format(ex))
    raise last


def make_column(pl, cand, rec):
    sym = pl.doc.GetElement(cand[u'type'][u'id'])
    if not sym.IsActive:
        sym.Activate()
        pl.doc.Regenerate()
    zlo = min(rec[u'p0'][2], rec[u'p1'][2])
    lvl = _need_level(pl.level(zlo + 300.0))
    centre = rec[u'C']
    p = xyz((centre[0], centre[1], lvl[1]))
    e = pl.doc.Create.NewFamilyInstance(p, sym, pl.level_el(lvl), StructuralType.Column)
    above = core.level_above(pl.cat[u'levels'], lvl[1])
    if above is not None:
        set_param(e, u'FAMILY_TOP_LEVEL_PARAM', above[2])
        set_param(e, u'FAMILY_TOP_LEVEL_OFFSET_PARAM', 0.0)
    set_param(e, u'FAMILY_BASE_LEVEL_OFFSET_PARAM', 0.0)
    want = _width_direction(rec, cand[u'size'].get(u'swap'))
    ang = math.atan2(want[1], want[0])
    if abs(ang) > math.radians(0.5):
        ElementTransformUtils.RotateElement(pl.doc, e.Id, Line.CreateBound(p, p + XYZ.BasisZ), ang)
    return [e.Id]


def make_beam(pl, cand, rec):
    sym = pl.doc.GetElement(cand[u'type'][u'id'])
    if not sym.IsActive:
        sym.Activate()
        pl.doc.Regenerate()
    a, s, t = rec[u'frame']
    up = core.v_mul(t, rec[u'H'] / 2.0)
    p0 = core.v_add(rec[u'p0'], up)
    p1 = core.v_add(rec[u'p1'], up)
    lvl = _need_level(pl.level(p0[2]))
    e = pl.doc.Create.NewFamilyInstance(Line.CreateBound(xyz(p0), xyz(p1)), sym, pl.level_el(lvl), StructuralType.Beam)
    return [e.Id]


CREATORS = {
    u'pipe': make_pipe, u'conduit': make_conduit, u'duct': make_duct, u'tray': make_tray,
    u'wall': make_wall, u'floor': make_slab, u'ceiling': make_slab,
    u'column': make_column, u'beam': make_beam,
}


def create(pl, cand, rec):
    fn = CREATORS.get(cand[u'kind'])
    if fn is None:
        raise ValueError(u'No creator for {0}'.format(cand[u'kind']))
    return fn(pl, cand, rec)
